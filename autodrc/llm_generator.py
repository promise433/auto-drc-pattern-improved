from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autodrc.lpl import Polygon, validate_all


_BASE_ALLOWED_LAYERS = {
    "li1",
    "met1",
    "met2",
    "met3",
    "met4",
    "met5",
    "poly",
    "diff",
    "via",
    "mcon",
    "via2",
    "via3",
    "via4",
    "nwell",
    "pwell",
}


def _load_allowed_layers() -> set[str]:
    layers = set(_BASE_ALLOWED_LAYERS)
    cfg = Path(__file__).resolve().parent.parent / "config" / "layers_sky130.json"
    try:
        rows = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:
        return layers
    if isinstance(rows, dict):
        for key in rows.keys():
            token = str(key).strip().lower()
            if token:
                layers.add(token)
    return layers


_ALLOWED_LAYERS = _load_allowed_layers()

_MODEL_CACHE: dict[tuple[str, bool, bool], tuple[Any, Any]] = {}


@dataclass(frozen=True)
class LLMCase:
    intent: str
    polygons: tuple[Polygon, ...]
    raw_response: str

    def to_case_dict(self) -> dict[str, Any]:
        errors = validate_all(self.polygons)
        return {
            "intent": self.intent,
            "lpl": [poly.to_dict() for poly in self.polygons],
            "geometry_valid": len(errors) == 0,
            "validation_errors": errors,
        }


def build_prompt(rule_text: str, intent: str, expected_layer: str | None = None) -> str:
    instruction = "Generate a layout polygon list (LPL) that matches the requested DRC intent."
    payload = {
        "rule_text": rule_text,
        "intent": intent,
        "output_schema": {
            "intent": "GOOD|BAD|ILLEGAL",
            "lpl": [
                {
                    "layer": expected_layer or "met1",
                    "points": [[0, 0], [400, 0], [400, 160], [0, 160], [0, 0]],
                }
            ],
        },
        "constraints": {
            "layers_allowed": sorted(_ALLOWED_LAYERS),
            "manhattan_only": True,
            "closed_polygons": True,
            "return_json_only": True,
        },
    }
    return (
        f"### Instruction:\n{instruction}\n\n"
        f"### Input:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
        "### Response:\n"
    )


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


def _sanitize_layer(layer: str, expected_layer: str | None) -> str:
    low = layer.strip().lower()
    if low in _ALLOWED_LAYERS and low != "string":
        return low
    return (expected_layer or "met1").lower()


def _to_point(raw: Any) -> tuple[int, int]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ValueError("Invalid point format")
    x = int(round(float(raw[0])))
    y = int(round(float(raw[1])))
    return (x, y)


def _polygons_from_payload(
    payload: dict[str, Any], expected_layer: str | None = None
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
            Polygon(layer=_sanitize_layer(layer, expected_layer), points=point_tuples)
        )
    return tuple(polygons)


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
) -> LLMCase:
    import torch

    tokenizer, model = _load_model_and_tokenizer(
        model_name=model_name,
        trust_remote_code=trust_remote_code,
        load_in_4bit=load_in_4bit,
    )

    prompt = build_prompt(rule_text, intent, expected_layer=expected_layer)
    inputs = tokenizer(prompt, return_tensors="pt")
    if torch.cuda.is_available():
        inputs = {k: v.to(model.device) for k, v in inputs.items()}

    output = model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        top_p=top_p,
        do_sample=temperature > 0,
    )
    decoded = tokenizer.decode(output[0], skip_special_tokens=True)
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / f"llm_raw_{intent.lower()}.txt").write_text(decoded, encoding="utf-8")

    payload = _extract_json(decoded)
    polygons = _polygons_from_payload(payload, expected_layer=expected_layer)
    response_intent = payload.get("intent", intent)
    return LLMCase(intent=response_intent, polygons=polygons, raw_response=decoded)


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
    )
    write_case_json(case, Path(args.out))
    print(json.dumps(case.to_case_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
