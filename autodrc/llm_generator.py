from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autodrc.lpl import Polygon, TextLabel, validate_all
from autodrc.tech import load_known_layers_for_tech, normalize_tech_name


_TECH_DEFAULT_LAYER = {
    "sky130": "met1",
    "ihp_sg13g2": "activ",
}


def _default_layer_for_tech(tech_name: str) -> str:
    tech = normalize_tech_name(tech_name)
    return _TECH_DEFAULT_LAYER.get(tech, "met1")


def _allowed_layers_for_tech(tech_name: str) -> set[str]:
    tech = normalize_tech_name(tech_name)
    try:
        return load_known_layers_for_tech(tech)
    except Exception:
        return set()

_MODEL_CACHE: dict[tuple[str, bool, bool], tuple[Any, Any]] = {}
_DEFAULT_TEMPERATURE = 0.2
_DEFAULT_TOP_P = 0.9
_QWEN3_NON_THINKING_TEMPERATURE = 0.7
_QWEN3_NON_THINKING_TOP_P = 0.8


@dataclass(frozen=True)
class LLMCase:
    intent: str
    polygons: tuple[Polygon, ...]
    raw_response: str
    labels: tuple[TextLabel, ...] = ()
    rigorous_geometry: bool = False
    allow_non_manhattan: bool = False

    def to_case_dict(self) -> dict[str, Any]:
        errors = validate_all(self.polygons, rigorous=self.rigorous_geometry,
                              allow_non_manhattan=self.allow_non_manhattan)
        for index, label in enumerate(self.labels):
            errors.extend(f"label[{index}]: {error}" for error in label.validate())
        result = {
            "intent": self.intent,
            "lpl": [poly.to_dict() for poly in self.polygons],
            "geometry_valid": len(errors) == 0,
            "validation_errors": errors,
        }
        if self.labels:
            result["labels"] = [label.to_dict() for label in self.labels]
        return result


class LLMResponseError(ValueError):
    """The model completed inference but returned no usable layout payload."""


def build_prompt(
    rule_text: str,
    intent: str,
    expected_layer: str | None = None,
    *,
    tech_name: str = "sky130",
    prompt_profile: str = "legacy",
) -> str:
    default_layer = (expected_layer or _default_layer_for_tech(tech_name)).lower()
    allowed_layers = sorted(_allowed_layers_for_tech(tech_name) | {default_layer})
    if prompt_profile not in {'legacy', 'compact', 'chat'}:
        raise ValueError('Unknown prompt profile: ' + prompt_profile)
    if prompt_profile != 'legacy':
        from autodrc.model_prompt import compact_task
        return compact_task(rule_text, intent, default_layer,
                            normalize_tech_name(tech_name), set(allowed_layers))
    instruction = "Generate a layout polygon list (LPL) that matches the requested DRC intent."
    payload = {
        "rule_text": rule_text,
        "intent": intent,
        "output_schema": {
            "intent": intent,
            "lpl": [
                {
                    "layer": default_layer,
                    "points": [[0, 0], [400, 0], [400, 160], [0, 160], [0, 0]],
                }
            ],
        },
        "constraints": {
            "layers_allowed": allowed_layers,
            "manhattan_only": True,
            "closed_polygons": True,
            "return_json_only": True,
        },
    }
    if normalize_tech_name(tech_name) == "ihp_sg13g2":
        payload["constraints"]["coordinate_unit"] = "integer nanometres"
        payload["constraints"]["label_coordinate_unit"] = "integer nanometres"
        payload["constraints"]["labels_optional"] = True
        payload["output_schema"]["labels"] = []
        payload["constraints"]["label_schema"] = {
            "layer": "text_0", "text": "device name or pin", "position": [0, 0]
        }
    return (
        f"### Instruction:\n{instruction}\n\n"
        f"### Input:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        "### Response:\n"
    )


def _is_qwen3_model(model: Any) -> bool:
    return getattr(getattr(model, "config", None), "model_type", None) == "qwen3"


def _effective_sampling_params(
    *, is_qwen3: bool, temperature: float, top_p: float
) -> tuple[float, float]:
    if not is_qwen3:
        return (temperature, top_p)

    effective_temperature = temperature
    effective_top_p = top_p

    if temperature == _DEFAULT_TEMPERATURE:
        effective_temperature = _QWEN3_NON_THINKING_TEMPERATURE
    if top_p == _DEFAULT_TOP_P:
        effective_top_p = _QWEN3_NON_THINKING_TOP_P
    return (effective_temperature, effective_top_p)


def _tokenize_prompt(
    tokenizer: Any, prompt: str, *, is_qwen3: bool
) -> dict[str, Any]:
    if is_qwen3 and hasattr(tokenizer, "apply_chat_template"):
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    return tokenizer(prompt, return_tensors="pt")


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 2:
            return parts[1].strip()
    return text


def _extract_json(text: str) -> dict[str, Any]:
    text = _strip_code_fence(text.strip())
    decoder = json.JSONDecoder()

    candidates: list[dict[str, Any]] = []
    for match in re.finditer(r"\{", text):
        start = match.start()
        try:
            obj, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            candidates.append(obj)

    if not candidates:
        match = _JSON_BLOCK_RE.search(text)
        if match:
            return json.loads(match.group(0))
        raise ValueError("No JSON object found in model response")

    for candidate in reversed(candidates):
        if "lpl" in candidate:
            return candidate
    return candidates[-1]


def _sanitize_layer(layer: str, expected_layer: str | None, *, tech_name: str) -> str:
    allowed_layers = _allowed_layers_for_tech(tech_name)
    low = layer.strip().lower()
    if low in allowed_layers and low != "string":
        return low
    return (expected_layer or _default_layer_for_tech(tech_name)).lower()


def _to_point(raw: Any) -> tuple[int, int]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ValueError("Invalid point format")
    x = int(round(float(raw[0])))
    y = int(round(float(raw[1])))
    return (x, y)


def _polygons_from_payload(
    payload: dict[str, Any], expected_layer: str | None = None, *, tech_name: str = "sky130"
) -> tuple[Polygon, ...]:
    lpl = payload.get("lpl")
    if not isinstance(lpl, list):
        raise ValueError("Response JSON missing 'lpl' list")
    polygons: list[Polygon] = []
    for item in lpl:
        if not isinstance(item, dict):
            raise ValueError("LPL entry must be an object")
        layer = item.get("layer")
        points = item.get("points")
        if not isinstance(layer, str) or not isinstance(points, list):
            raise ValueError("Invalid LPL entry (layer/points)")
        point_tuples = tuple(_to_point(p) for p in points)
        polygons.append(
            Polygon(
                layer=_sanitize_layer(layer, expected_layer, tech_name=tech_name),
                points=point_tuples,
            )
        )
    return tuple(polygons)


def _labels_from_payload(payload: dict[str, Any], *, tech_name: str) -> tuple[TextLabel, ...]:
    entries = payload.get("labels", [])
    if not isinstance(entries, list):
        raise ValueError("Response labels must be a list")
    labels = []
    allowed = _allowed_layers_for_tech(tech_name)
    if normalize_tech_name(tech_name) == "ihp_sg13g2":
        allowed = allowed & {"text_0"}
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("layer") not in allowed:
            raise ValueError("Invalid label layer")
        position = entry.get("position")
        if not isinstance(position, list) or len(position) != 2 or any(type(v) is not int for v in position):
            raise ValueError("Label position must contain two integer nanometre coordinates")
        label = TextLabel(entry["layer"], entry.get("text"), tuple(position))
        if label.validate():
            raise ValueError("Invalid label text or position")
        labels.append(label)
    return tuple(labels)


def parse_model_response(raw: str, *, intent: str, expected_layer: str | None,
                         tech_name: str, strict: bool = False) -> LLMCase:
    """解析真实续写；严格模式拒绝嵌套示例、错误层和坐标隐式转换。"""
    try:
        if strict:
            def unique_keys(pairs):
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise ValueError('Duplicate JSON key: ' + key)
                    value[key] = item
                return value
            payload = json.loads(raw.strip(), object_pairs_hook=unique_keys)
            if not isinstance(payload, dict) or set(payload) - {'intent', 'lpl', 'labels'}:
                raise ValueError('Expected one layout object, not a nested schema or task echo')
            if payload.get('intent') != intent or not isinstance(payload.get('lpl'), list):
                raise ValueError('Explicit matching intent and lpl are required')
            allowed = _allowed_layers_for_tech(tech_name)
            for entry in payload['lpl']:
                if not isinstance(entry, dict) or set(entry) != {'layer', 'points'}:
                    raise ValueError('Polygon must contain only layer and points')
                if entry['layer'] not in allowed:
                    raise ValueError('Unknown physical layer; no implicit layer substitution')
                if not isinstance(entry['points'], list) or any(
                    not isinstance(point, list) or len(point) != 2 or
                    any(type(v) is not int for v in point) for point in entry['points']):
                    raise ValueError('Coordinates must be integer nanometres; no rounding')
        else:
            payload = _extract_json(raw)
        polygons = (tuple(Polygon(entry['layer'],tuple(tuple(point) for point in entry['points']))
                          for entry in payload['lpl']) if strict else
                    _polygons_from_payload(payload, expected_layer=expected_layer, tech_name=tech_name))
        if payload.get('intent', intent) != intent:
            raise ValueError('Response intent does not match requested intent')
        labels = _labels_from_payload(payload, tech_name=tech_name)
    except (ValueError, TypeError, OverflowError) as exc:
        raise LLMResponseError(str(exc)) from exc
    return LLMCase(intent, polygons, raw, labels, rigorous_geometry=strict)


def _load_model_and_tokenizer(
    model_name: str,
    trust_remote_code: bool,
    load_in_4bit: bool,
) -> tuple[Any, Any]:
    cache_key = (model_name, trust_remote_code, load_in_4bit)
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    quantization_config = None
    if load_in_4bit:
        try:
            from transformers import BitsAndBytesConfig
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("bitsandbytes is required for --load-in-4bit.") from exc
        compute_dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=compute_dtype,
        )

    device_map = "auto" if torch.cuda.is_available() else None
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32

    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        use_fast=True,
        trust_remote_code=trust_remote_code,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=dtype,
        device_map=device_map,
        trust_remote_code=trust_remote_code,
        quantization_config=quantization_config,
    )
    _MODEL_CACHE[cache_key] = (tokenizer, model)
    return tokenizer, model


def generate_case_with_llm(
    *,
    model_name: str,
    rule_text: str,
    intent: str,
    max_new_tokens: int = 256,
    temperature: float = 0.2,
    top_p: float = 0.9,
    trust_remote_code: bool = False,
    load_in_4bit: bool = False,
    debug_dir: Path | None = None,
    expected_layer: str | None = None,
    tech_name: str = "sky130",
    prompt_profile: str = "legacy",
    strict_response: bool = False,
) -> LLMCase:
    import torch

    tokenizer, model = _load_model_and_tokenizer(
        model_name=model_name,
        trust_remote_code=trust_remote_code,
        load_in_4bit=load_in_4bit,
    )

    prompt = build_prompt(
        rule_text,
        intent,
        expected_layer=expected_layer,
        tech_name=tech_name,
        prompt_profile=prompt_profile,
    )
    is_qwen3 = _is_qwen3_model(model)
    temperature, top_p = _effective_sampling_params(
        is_qwen3=is_qwen3,
        temperature=temperature,
        top_p=top_p,
    )
    if prompt_profile == 'chat':
        if not getattr(tokenizer, 'chat_template', None):
            raise ValueError('chat profile requires an existing tokenizer chat_template')
        prompt = tokenizer.apply_chat_template([{'role': 'user', 'content': prompt}],
            tokenize=False, add_generation_prompt=True,
            **({'enable_thinking': False} if is_qwen3 else {}))
        inputs = tokenizer(prompt, return_tensors='pt', add_special_tokens=False)
    else:
        inputs = _tokenize_prompt(tokenizer, prompt, is_qwen3=is_qwen3)
    if torch.cuda.is_available():
        inputs = {k: v.to(model.device) for k, v in inputs.items()}

    output = model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        top_p=top_p,
        do_sample=temperature > 0,
    )
    prompt_length = inputs["input_ids"].shape[-1]
    decoded = tokenizer.decode(output[0][prompt_length:], skip_special_tokens=True)
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"llm_prompt_{intent.lower()}.txt").write_text(prompt, encoding="utf-8")
        (debug_dir / f"llm_raw_{intent.lower()}.txt").write_text(decoded, encoding="utf-8")
        (debug_dir / 'generation_metadata.json').write_text(json.dumps(dict(
            prompt_profile=prompt_profile, strict_response=strict_response,
            input_tokens=prompt_length, new_tokens=len(output[0])-prompt_length,
            max_new_tokens=max_new_tokens, temperature=temperature, top_p=top_p)), encoding='utf-8')
    return parse_model_response(decoded, intent=intent, expected_layer=expected_layer,
                                tech_name=tech_name, strict=strict_response)


def write_case_json(case: LLMCase, out_path: Path) -> None:
    payload = case.to_case_dict()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Generate LPL via HF model and save as JSON.")
    p.add_argument("--model", required=True)
    p.add_argument("--rule-text", required=True)
    p.add_argument("--intent", choices=["GOOD", "BAD", "ILLEGAL"], required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--max-new-tokens", type=int, default=256)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--top-p", type=float, default=0.9)
    p.add_argument("--trust-remote-code", action="store_true")
    p.add_argument("--load-in-4bit", action="store_true")
    p.add_argument("--expected-layer")
    p.add_argument("--tech-name", default="sky130")
    p.add_argument('--prompt-profile', choices=['legacy', 'compact', 'chat'], default='legacy')
    p.add_argument('--strict-response', action='store_true')
    args = p.parse_args()

    case = generate_case_with_llm(
        model_name=args.model,
        rule_text=args.rule_text,
        intent=args.intent,
        max_new_tokens=args.max_new_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        trust_remote_code=args.trust_remote_code,
        load_in_4bit=args.load_in_4bit,
        expected_layer=args.expected_layer,
        tech_name=args.tech_name,
        prompt_profile=args.prompt_profile,
        strict_response=args.strict_response,
    )
    write_case_json(case, Path(args.out))
    print(json.dumps(case.to_case_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
