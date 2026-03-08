from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
from typing import Any

from autodrc.closed_loop import run_closed_loop
from autodrc.runset_corpus import RunsetRule, parse_runset_outputs
from autodrc.runset_semantics import RunsetOutputSemantic, parse_runset_output_semantics


_LAYER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("met1", re.compile(r"\b(?:met1|m1)\b", re.IGNORECASE)),
    ("met2", re.compile(r"\b(?:met2|m2)\b", re.IGNORECASE)),
    ("met3", re.compile(r"\b(?:met3|m3)\b", re.IGNORECASE)),
    ("met4", re.compile(r"\b(?:met4|m4)\b", re.IGNORECASE)),
    ("met5", re.compile(r"\b(?:met5|m5)\b", re.IGNORECASE)),
    ("li1", re.compile(r"\b(?:li1|li)\b", re.IGNORECASE)),
    ("poly", re.compile(r"\bpoly\b", re.IGNORECASE)),
    ("diff", re.compile(r"\bdiff\b", re.IGNORECASE)),
    ("tap", re.compile(r"\btap\b", re.IGNORECASE)),
    ("via", re.compile(r"\bvia\b", re.IGNORECASE)),
    ("via2", re.compile(r"\bvia2\b", re.IGNORECASE)),
    ("via3", re.compile(r"\bvia3\b", re.IGNORECASE)),
    ("via4", re.compile(r"\bvia4\b", re.IGNORECASE)),
    ("mcon", re.compile(r"\bmcon\b", re.IGNORECASE)),
    ("nwell", re.compile(r"\bnwell\b", re.IGNORECASE)),
    ("dnwell", re.compile(r"\bdnwell\b", re.IGNORECASE)),
    ("pwde", re.compile(r"\bpwde\b", re.IGNORECASE)),
    ("nsdm", re.compile(r"\bnsdm\b", re.IGNORECASE)),
    ("psdm", re.compile(r"\bpsdm\b", re.IGNORECASE)),
    ("nsm", re.compile(r"\bnsm\b", re.IGNORECASE)),
    ("npc", re.compile(r"\bnpc\b", re.IGNORECASE)),
    ("capm", re.compile(r"\bcapm\b", re.IGNORECASE)),
    ("cap2m", re.compile(r"\bcap2m\b", re.IGNORECASE)),
    ("rdl", re.compile(r"\brdl\b", re.IGNORECASE)),
    ("ncm", re.compile(r"\bncm\b", re.IGNORECASE)),
    ("pwell", re.compile(r"\bpwell\b", re.IGNORECASE)),
    ("licon", re.compile(r"\blicon\b", re.IGNORECASE)),
    ("modulecut", re.compile(r"\bmodulecut\b", re.IGNORECASE)),
    ("areaid_re", re.compile(r"\bareaid(?:[._]re)\b", re.IGNORECASE)),
    ("difftap", re.compile(r"\bdifftap\b", re.IGNORECASE)),
]

_THRESH_UM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(um|µm)", re.IGNORECASE)
_THRESH_NM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*nm", re.IGNORECASE)
_THRESH_AREA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:um\^?2|µm\^?2|um2|µm2|um²|µm²)", re.IGNORECASE)

_SUPPORTED_RULE_TYPES = {
    "min_width",
    "max_width",
    "min_spacing",
    "min_area",
    "via_enclosure",
    "min_enclosure",
    "forbidden_overlap",
    "forbidden_angle",
    "offgrid_vertex",
    "max_length",
    "must_interact",
    "forbidden_use",
}

_RELAXED_RULE_TYPES = {
    "forbidden_angle",
    "forbidden_overlap",
    "max_length",
    "max_width",
    "min_enclosure",
    "via_enclosure",
    "must_interact",
    "forbidden_use",
}

_CONTEXT_LIMITED_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ("inside", re.compile(r"\binside\b", re.IGNORECASE)),
    ("across", re.compile(r"\bacross\b", re.IGNORECASE)),
    ("holes", re.compile(r"\bholes?\b", re.IGNORECASE)),
    ("huge", re.compile(r"\b3um\.[a-z0-9_]+\b", re.IGNORECASE)),
    ("minmax", re.compile(r"\bminimum/maximum\b|\bmin/max\b", re.IGNORECASE)),
    ("bot_plate", re.compile(r"\bbot_plate\b", re.IGNORECASE)),
    ("areaid", re.compile(r"\bareaid[:._][a-z0-9_]+\b", re.IGNORECASE)),
]

_INTERACT_CONTACT_PRIORITY = ("mcon", "licon", "via4", "via3", "via2", "via")
_LAYER_TOKEN_ALIASES: dict[str, str] = {
    "via1": "via",
    "met1": "met1",
    "met2": "met2",
    "met3": "met3",
    "met4": "met4",
    "met5": "met5",
    "nwellhole": "nwell",
    "hvnwell": "nwell",
    "poly_licon": "poly",
    "polylicon": "poly",
}


def _extract_layer_mentions(text: str, layer_map: set[str]) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for layer in sorted(layer_map, key=len, reverse=True):
        layer_pat = re.escape(layer).replace(r"\_", r"(?:[_\.\s:]+)")
        if re.search(rf"\b{layer_pat}\b", lowered):
            found.append(layer)
    return found


def _parse_wildcards(runset_path: Path) -> dict[str, tuple[int, int]]:
    text = runset_path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, tuple[int, int]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        m = re.search(r'^(\w+)\s*=\s*"(\d+)\/(\d+)"', stripped)
        if m:
            out[m.group(1).lower()] = (int(m.group(2)), int(m.group(3)))
    return out


def _parse_layer_aliases(runset_path: Path, wildcards: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int]]:
    text = runset_path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, tuple[int, int]] = {}
    for line in text.splitlines():
        stripped = line.strip()
        m1 = re.search(r"^(\w+)\s*=\s*polygons\((\d+)\s*,\s*(\d+)\)", stripped)
        if m1:
            out[m1.group(1).lower()] = (int(m1.group(2)), int(m1.group(3)))
            continue
        m2 = re.search(r"^(\w+)\s*=\s*input\((\d+)\s*,\s*(\d+)\)", stripped)
        if m2:
            out[m2.group(1).lower()] = (int(m2.group(2)), int(m2.group(3)))
            continue
        m3 = re.search(r"^(\w+)\s*=\s*polygons\((\w+)\)", stripped)
        if m3:
            key = m3.group(2).lower()
            if key in wildcards:
                out[m3.group(1).lower()] = wildcards[key]
            continue
        m4 = re.search(r"^(\w+)\s*=\s*input\((\w+)\)", stripped)
        if m4:
            key = m4.group(2).lower()
            if key in wildcards:
                out[m4.group(1).lower()] = wildcards[key]
            continue
    return out


def _augment_layer_map_with_aliases(layer_map_path: Path, aliases: dict[str, tuple[int, int]]) -> None:
    rows = json.loads(layer_map_path.read_text(encoding="utf-8"))
    changed = False
    for alias, pair in aliases.items():
        if alias in rows:
            continue
        rows[alias] = [pair[0], pair[1]]
        changed = True
    if changed:
        layer_map_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


def _load_layer_map(path: Path) -> set[str]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {str(key).lower() for key in rows.keys()}


def infer_rule_type(description: str) -> str | None:
    text = description.lower()
    if "for skywater use only" in text or "use of" in text and "prohibited" in text:
        return "forbidden_use"
    if "offgrid" in text or "off-grid" in text:
        return "offgrid_vertex"
    if "should be rectangle" in text or "should be rectangular" in text:
        return "forbidden_angle"
    if "must interact with" in text:
        return "must_interact"
    if "angle" in text and ("non" in text or "acute" in text):
        return "forbidden_angle"
    if (
        "must not overlap" in text
        or "must not straddle" in text
        or "can't overlap" in text
        or "may not overlap" in text
        or " overlaps " in text
        or "prohibited" in text
    ):
        return "forbidden_overlap"
    if "maximum length" in text or ("min/max" in text and "length" in text):
        return "max_length"
    if "maximum width" in text or "max. width" in text or "max width" in text:
        return "max_width"
    if (
        "must be enclosed by" in text
        or "enclosure of" in text
        or "covered by" in text
        or "enclose all" in text
    ):
        if "via" in text:
            return "via_enclosure"
        return "min_enclosure"
    if "enclosure" in text and "via" in text:
        return "via_enclosure"
    if "spacing" in text:
        return "min_spacing"
    if "width" in text:
        return "min_width"
    if "area" in text:
        return "min_area"
    return None


def _canonical_layer_name(layer: str) -> str:
    low = layer.lower()
    alias_map = {
        "m1": "m1",
        "met1": "m1",
        "m2": "m2",
        "met2": "m2",
        "m3": "m3",
        "met3": "m3",
        "m4": "m4",
        "met4": "m4",
        "m5": "m5",
        "met5": "m5",
        "li": "li1",
        "li1": "li1",
        "via1": "via",
        "via": "via",
    }
    return alias_map.get(low, low)


def _resolve_semantic_layer_token(token: str, layer_map: set[str]) -> str | None:
    low = token.lower().strip()
    if not low:
        return None

    candidates: list[str] = [low]
    if low.endswith("_merged"):
        candidates.append(low[: -len("_merged")])

    parts = low.split("_")
    for end in range(1, len(parts)):
        head = "_".join(parts[:end])
        if head:
            candidates.append(head)
    for start in range(len(parts)):
        tail = "_".join(parts[start:])
        if tail:
            candidates.append(tail)
        if tail.endswith("_merged"):
            candidates.append(tail[: -len("_merged")])

    for candidate in candidates:
        resolved = _resolve_layer_token(candidate, layer_map)
        if resolved:
            return resolved
    return None


def _semantic_primary_layer(
    rule: RunsetRule,
    semantic: RunsetOutputSemantic | None,
    layer_map: set[str],
) -> str | None:
    if semantic is None:
        return None

    candidates: list[str] = []
    for token in semantic.expression_refs + semantic.upstream_vars:
        resolved = _resolve_semantic_layer_token(token, layer_map)
        if resolved is None or resolved.startswith("areaid"):
            continue
        if resolved not in candidates:
            candidates.append(resolved)

    if not candidates:
        return None

    prefix = rule.rule_id.split(".")[0].lower()
    for candidate in candidates:
        cand_low = candidate.lower()
        if cand_low == prefix or cand_low.endswith(f"_{prefix}"):
            return candidate
    return candidates[0]


def infer_layer(
    rule: RunsetRule,
    layer_map: set[str],
    semantic: RunsetOutputSemantic | None = None,
    rule_type: str | None = None,
) -> str | None:
    if rule.rule_id == "via2.5":
        for candidate in ("m2", "met2"):
            if candidate in layer_map:
                return candidate

    semantic_layer = None
    if rule_type not in {"via_enclosure", "min_enclosure"}:
        semantic_layer = _semantic_primary_layer(rule, semantic, layer_map)

    hint = (rule.layer_hint or "").lower()
    hint_layer = hint if hint and hint != "unknown" and hint in layer_map else None
    if semantic_layer is not None:
        if hint_layer is None:
            return semantic_layer
        if _canonical_layer_name(semantic_layer) == _canonical_layer_name(hint_layer):
            return hint_layer
        return semantic_layer

    if hint and hint != "unknown" and hint in layer_map:
        return hint

    prefix = rule.rule_id.split(".")[0].lower()
    if prefix in {"capm", "cap2m"} and prefix in layer_map:
        return prefix

    text = f"{rule.rule_id} {rule.description}".lower()
    for layer, pattern in _LAYER_PATTERNS:
        if layer in layer_map and pattern.search(text):
            return layer

    mentions = _extract_layer_mentions(text, layer_map)
    if mentions:
        return mentions[0]

    if prefix == "difftap":
        if "difftap" in layer_map:
            return "difftap"
        if "diff" in layer_map:
            return "diff"
    if prefix == "modulecut":
        if "areaid_mt" in layer_map:
            return "areaid_mt"
        if "modulecut" in layer_map:
            return "modulecut"
    if prefix.startswith("areaid_re") and "areaid_re" in layer_map:
        return "areaid_re"
    prefix_map = {
        "m1": "met1",
        "m2": "met2",
        "m3": "met3",
        "m4": "met4",
        "m5": "met5",
        "li": "li1",
        "poly": "poly",
        "ct": "mcon",
        "via": "via",
        "via2": "via2",
        "via3": "via3",
        "via4": "via4",
        "licon": "licon",
    }
    mapped = prefix_map.get(prefix)
    if mapped in layer_map:
        return mapped
    return None


def infer_threshold(rule_type: str, description: str) -> int | None:
    text = description.lower()
    if rule_type == "min_area":
        matches = _THRESH_AREA_RE.findall(text)
        if not matches:
            return None
        value = float(matches[-1])
        return int(round(value * 1_000_000))

    nm_matches = _THRESH_NM_RE.findall(text)
    if nm_matches:
        value = float(nm_matches[-1])
        return int(round(value))

    um_matches = _THRESH_UM_RE.findall(text)
    if not um_matches:
        return None

    value = float(um_matches[-1][0])
    return int(round(value * 1000))


def _overlap_pair_from_text(text: str, layer_map: set[str]) -> tuple[str, str]:
    tokens = _extract_layer_mentions(text, layer_map)
    unique_tokens: list[str] = []
    for token in tokens:
        if token not in unique_tokens:
            unique_tokens.append(token)
    if len(unique_tokens) >= 2:
        return unique_tokens[0], unique_tokens[1]

    found: list[str] = []
    for layer, pattern in _LAYER_PATTERNS:
        if layer in layer_map and pattern.search(text):
            found.append(layer)
    unique = []
    for layer in found:
        if layer not in unique:
            unique.append(layer)
    if len(unique) >= 2:
        return unique[0], unique[1]
    if len(unique) == 1:
        if unique[0] != "nwell" and "nwell" in layer_map:
            return unique[0], "nwell"
        if unique[0] != "diff" and "diff" in layer_map:
            return unique[0], "diff"
        return unique[0], unique[0]
    return "met1", "nwell" if "nwell" in layer_map else "diff"


def _interact_pair_from_text(rule: RunsetRule, layer_map: set[str]) -> tuple[str, str] | None:
    text = f"{rule.rule_id} {rule.description}".lower()
    normalized = re.sub(r"[^a-z0-9_]+", "_", text)
    primary = infer_layer(rule, layer_map)
    toks = _extract_layer_mentions(text, layer_map)
    uniq: list[str] = []
    for token in toks:
        if token not in uniq:
            uniq.append(token)
    if (
        primary == "met1"
        and "mcon" in layer_map
        and ("via1" in normalized or "via" in normalized)
    ):
        # m1 floating checks accept via1/mcon interaction; mcon is more stable
        # for template GOOD cases and avoids false floating hits on met1.
        return primary, "mcon"
    if primary is not None:
        for layer in _INTERACT_CONTACT_PRIORITY:
            if layer == primary or layer not in layer_map:
                continue
            if layer in uniq:
                return primary, layer
            if layer == "via" and ("via1" in normalized or re.search(r"\bvia\b", normalized)):
                return primary, "via"
            if layer != "via" and layer in normalized:
                return primary, layer
    if primary is not None:
        for token in uniq:
            if token != primary:
                return primary, token
    if len(uniq) >= 2:
        return uniq[0], uniq[1]
    if primary is None:
        return None
    if "via4" in normalized and "via4" in layer_map:
        return primary, "via4"
    if "via3" in normalized and "via3" in layer_map:
        return primary, "via3"
    if "via2" in normalized and "via2" in layer_map:
        return primary, "via2"
    if "via1" in normalized and "via" in layer_map:
        return primary, "via"
    if "via" in layer_map:
        return primary, "via"
    return None


def _context_markers(description: str) -> list[str]:
    markers: list[str] = []
    for name, pattern in _CONTEXT_LIMITED_HINTS:
        if pattern.search(description):
            markers.append(name)
    return markers


def _resolve_layer_token(token: str, layer_map: set[str]) -> str | None:
    low = token.lower().strip()
    if not low:
        return None
    if low in layer_map:
        return low
    compact = re.sub(r"[^a-z0-9_]+", "", low)
    if compact in layer_map:
        return compact
    mapped = _LAYER_TOKEN_ALIASES.get(compact)
    if mapped and mapped in layer_map:
        return mapped
    return None


def _resolve_layer_phrase(phrase: str, layer_map: set[str]) -> str | None:
    low = phrase.lower().strip()
    if not low:
        return None
    direct = _resolve_layer_token(low, layer_map)
    if direct:
        return direct

    underscored = re.sub(r"[^a-z0-9]+", "_", low).strip("_")
    if underscored in layer_map:
        return underscored
    compact = re.sub(r"[^a-z0-9]+", "", low)
    if compact in layer_map:
        return compact

    for tok in re.findall(r"[a-z0-9_]+", low):
        resolved = _resolve_layer_token(tok, layer_map)
        if resolved:
            return resolved

    if "hv" in low and "marker" in low:
        for candidate in ("hvi", "vhvi", "uhvi", "hvntm"):
            if candidate in layer_map:
                return candidate
    return None


def _enclosure_pair_from_text(text: str, layer_map: set[str]) -> tuple[str, str] | None:
    t = text.lower()
    t = re.sub(r"^\s*[a-z0-9_.-]+\s*:\s*", "", t)

    patterns: list[tuple[re.Pattern[str], str, str]] = [
        (
            re.compile(
                r"\b(?P<inner>[a-z0-9_]+)\b.*\b(?:must be enclosed by|enclosed by|covered by)\b\s*(?P<outer>[a-z0-9_ ]+)",
                re.IGNORECASE,
            ),
            "inner",
            "outer",
        ),
        (
            re.compile(
                r"\benclosure of\s+(?P<inner>[a-z0-9_]+)\s+by\s+(?P<outer>[a-z0-9_ ]+)",
                re.IGNORECASE,
            ),
            "inner",
            "outer",
        ),
        (
            re.compile(
                r"\b(?P<outer>[a-z0-9_]+)\s+enclosure of\s+(?P<inner>[a-z0-9_]+)",
                re.IGNORECASE,
            ),
            "inner",
            "outer",
        ),
        (
            re.compile(
                r"\b(?P<outer>[a-z0-9_]+)\b.*\benclose all\b.*\b(?P<inner>[a-z0-9_]+)\b",
                re.IGNORECASE,
            ),
            "inner",
            "outer",
        ),
    ]
    for pattern, inner_name, outer_name in patterns:
        m = pattern.search(t)
        if not m:
            continue
        inner = _resolve_layer_phrase(m.group(inner_name), layer_map)
        outer = _resolve_layer_phrase(m.group(outer_name), layer_map)
        if inner and outer:
            return (inner, outer)

    layers = []
    for tok in re.findall(r"[a-z0-9_]+", t):
        resolved = _resolve_layer_token(tok, layer_map)
        if resolved:
            layers.append(resolved)
    uniq: list[str] = []
    for layer in layers:
        if layer not in uniq:
            uniq.append(layer)
    if len(uniq) >= 2:
        if "enclosure of" in t or "enclose all" in t:
            return (uniq[1], uniq[0])
        if "enclosed by" in t or "covered by" in t:
            return (uniq[0], uniq[1])
        return (uniq[0], uniq[1])
    return None


def _enclosure_pair_from_semantic(
    semantic: RunsetOutputSemantic | None,
    layer_map: set[str],
    *,
    rule_type: str,
) -> tuple[str, str] | None:
    if semantic is None or not semantic.expression:
        return None

    expr = semantic.expression.lower()
    patterns: list[tuple[re.Pattern[str], str, str]] = []
    if rule_type == "via_enclosure":
        patterns.append(
            (
                re.compile(r"\b(?P<inner>[a-z0-9_]+)\s*\.not\(\s*(?P<outer>[a-z0-9_]+)\s*\)"),
                "inner",
                "outer",
            )
        )
    patterns.append(
        (
            re.compile(r"\b(?P<outer>[a-z0-9_]+)\s*\.enclosing\(\s*(?P<inner>[a-z0-9_]+)\b"),
            "inner",
            "outer",
        )
    )
    for pattern, inner_name, outer_name in patterns:
        match = pattern.search(expr)
        if not match:
            continue
        inner = _resolve_semantic_layer_token(match.group(inner_name), layer_map)
        outer = _resolve_semantic_layer_token(match.group(outer_name), layer_map)
        if inner and outer:
            return (inner, outer)
    return None


def _angle_target_from_text(text: str) -> int:
    low = text.lower()
    if "non 45 degree angle" in low:
        return 45
    if "non 90 degree angle" in low:
        return 90
    return 90


def classify_rule(
    rule: RunsetRule,
    layer_map: set[str],
    semantic: RunsetOutputSemantic | None = None,
) -> dict[str, Any]:
    rule_type = infer_rule_type(rule.description)
    if rule_type is None:
        return {"supported": False, "reason": "unsupported_rule_type", "rule_type": None}

    if rule_type not in _SUPPORTED_RULE_TYPES:
        return {"supported": False, "reason": "unsupported_rule_type", "rule_type": rule_type}

    if rule_type == "forbidden_use":
        layer = infer_layer(rule, layer_map, semantic=semantic, rule_type=rule_type)
        if layer is None:
            return {
                "supported": False,
                "reason": "unknown_layer",
                "rule_type": rule_type,
                "layer": None,
            }
        return {
            "supported": True,
            "rule_type": rule_type,
            "layer": layer,
            "threshold_nm": 1,
        }

    if rule_type == "must_interact":
        pair = _interact_pair_from_text(rule, layer_map)
        if pair is None:
            return {
                "supported": False,
                "reason": "unknown_layer",
                "rule_type": rule_type,
                "layer": None,
            }
        return {
            "supported": True,
            "rule_type": rule_type,
            "layer": pair[0],
            "layer_b": pair[1],
            "threshold_nm": 40,
        }

    if rule_type == "forbidden_overlap":
        la, lb = _overlap_pair_from_text(f"{rule.rule_id} {rule.description}".lower(), layer_map)
        return {
            "supported": True,
            "rule_type": rule_type,
            "layer": la,
            "layer_b": lb,
            "threshold_nm": 40,
        }

    if rule_type in {"via_enclosure", "min_enclosure"}:
        pair = _enclosure_pair_from_semantic(
            semantic,
            layer_map,
            rule_type=rule_type,
        ) or _enclosure_pair_from_text(rule.description, layer_map)
        inner_layer = pair[0] if pair else None
        outer_layer = pair[1] if pair else None
        if rule.rule_id == "via2.5":
            outer_layer = infer_layer(rule, layer_map, semantic=semantic, rule_type=rule_type) or outer_layer
            inner_layer = "via2" if "via2" in layer_map else inner_layer
        if inner_layer is None or outer_layer is None:
            layer = infer_layer(rule, layer_map, semantic=semantic, rule_type=rule_type)
            if layer is None:
                return {
                    "supported": False,
                    "reason": "unknown_layer",
                    "rule_type": rule_type,
                    "layer": None,
                }
            outer_layer = layer
            inner_layer = "via" if rule_type == "via_enclosure" else "nwell"

        threshold = infer_threshold(rule_type, rule.description)
        if threshold is None:
            threshold = 60

        return {
            "supported": True,
            "rule_type": rule_type,
            "layer": outer_layer,
            "layer_b": inner_layer,
            "threshold_nm": threshold,
        }

    layer = infer_layer(rule, layer_map, semantic=semantic, rule_type=rule_type)
    if layer is None:
        return {
            "supported": False,
            "reason": "unknown_layer",
            "rule_type": rule_type,
            "layer": None,
        }

    if rule_type in {"offgrid_vertex", "forbidden_angle"}:
        threshold = 5 if rule_type == "offgrid_vertex" else _angle_target_from_text(rule.description)
    else:
        threshold = infer_threshold(rule_type, rule.description)
        if threshold is None:
            if rule_type in {"min_enclosure", "via_enclosure"}:
                # Some enclosure rules in the runset omit explicit numbers in output text.
                # Use a conservative default so they can still enter coverage attempts.
                threshold = 60
            else:
                return {
                    "supported": False,
                    "reason": "missing_threshold",
                    "rule_type": rule_type,
                    "layer": layer,
                }

    if threshold <= 0:
        return {
            "supported": False,
            "reason": "invalid_threshold",
            "rule_type": rule_type,
            "layer": layer,
            "threshold_nm": threshold,
        }

    return {
        "supported": True,
        "rule_type": rule_type,
        "layer": layer,
        "threshold_nm": threshold,
    }


def _align_semantics(
    rules: list[RunsetRule], semantics: list[RunsetOutputSemantic]
) -> tuple[list[RunsetOutputSemantic | None], bool]:
    if len(rules) == len(semantics):
        return list(semantics), True

    keyed: dict[tuple[str, int, str], list[RunsetOutputSemantic]] = {}
    for row in semantics:
        key = (row.rule_id, row.line_no, row.description)
        keyed.setdefault(key, []).append(row)

    aligned: list[RunsetOutputSemantic | None] = []
    for rule in rules:
        key = (rule.rule_id, rule.line_no, rule.description)
        bucket = keyed.get(key, [])
        if bucket:
            aligned.append(bucket.pop(0))
        else:
            aligned.append(None)
    ok = all(row is not None for row in aligned)
    return aligned, ok


def _compose_runset_rule_text(rule: RunsetRule, semantic: RunsetOutputSemantic | None) -> str:
    parts = [
        f"Rule ID: {rule.rule_id}",
        f"Description: {rule.description}",
    ]
    if semantic is not None and semantic.expression:
        parts.append(f"Runset expression: {semantic.expression}")
    if semantic is not None and semantic.expression_refs:
        parts.append(f"Expression refs: {', '.join(semantic.expression_refs)}")
    if semantic is not None and semantic.upstream_assignments:
        chain = " | ".join(semantic.upstream_assignments[:12])
        parts.append(f"Upstream chain: {chain}")
    if semantic is not None and semantic.unresolved_refs:
        parts.append(f"Unresolved refs: {', '.join(semantic.unresolved_refs)}")
    if semantic is not None and semantic.context_stack:
        parts.append(f"Runset context: {' | '.join(semantic.context_stack)}")
    return "\n".join(parts)


def _runset_defines_from_context(semantic: RunsetOutputSemantic | None) -> dict[str, str]:
    if semantic is None:
        return {}

    context = " | ".join(semantic.context_stack).lower()
    defines: dict[str, str] = {}
    if "if floating_met" in context:
        defines["floating_met"] = "true"
    if "if seal" in context:
        defines["seal"] = "true"
    if "if sram_exclude" in context:
        defines["sram_exclude"] = "true"
    return defines


def _top_cell_for_rule(rule: RunsetRule) -> str:
    if rule.rule_id in {"m1.4a", "m1.4a_a"}:
        return "s8cell_ee_plus_sseln_a"
    return "TOP"


def _rule_identity(rule: RunsetRule) -> tuple[str, int, str]:
    return (rule.rule_id, rule.line_no, rule.description)


def _row_identity(row: dict[str, Any]) -> tuple[str, int, str] | None:
    rule_id = row.get("rule_id")
    line_no = row.get("line_no")
    description = row.get("description")
    if not isinstance(rule_id, str) or not isinstance(line_no, int) or not isinstance(description, str):
        return None
    return (rule_id, line_no, description)


def _load_existing_rows(path: Path) -> dict[tuple[str, int, str], dict[str, Any]]:
    if not path.exists():
        return {}
    out: dict[tuple[str, int, str], dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        key = _row_identity(row)
        if key is None:
            continue
        out[key] = row
    return out


def _load_existing_rule_summary(
    *,
    run_dir: Path,
    generator: str,
    llm_model: str | None,
) -> dict[str, Any] | None:
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        return None

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(summary, dict):
        return None
    if summary.get("generator") != generator:
        return None
    if generator == "llm" and llm_model is not None and summary.get("llm_model") != llm_model:
        return None
    if not isinstance(summary.get("iterations"), list):
        return None
    return summary


def _target_categories_for_rule(rule: RunsetRule) -> list[str]:
    targets = [rule.rule_id]
    if rule.rule_id == "cap2m.3":
        targets.append("cap2m.3_a")
    if rule.rule_id == "m1.4a_a":
        targets.append("m1.4a")
    return targets


def _write_rows_jsonl(out_path: Path, rows: list[dict[str, Any]]) -> None:
    out_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _status_from_closed_loop_summary(
    *,
    summary: dict[str, Any],
    rule_type: str,
    description: str,
) -> dict[str, Any]:
    iterations = summary.get("iterations")
    if not isinstance(iterations, list):
        iterations = []
    last_iter = iterations[-1] if iterations else {}
    if not isinstance(last_iter, dict):
        last_iter = {}

    good_ok = bool(last_iter.get("good_ok"))
    bad_ok = bool(last_iter.get("bad_ok"))
    strict_converged = bool(summary.get("converged")) or (good_ok and bad_ok)

    relaxed_converged = False
    relaxed_reason: str | None = None
    markers = _context_markers(description)
    if (not strict_converged) and (good_ok or bad_ok):
        # Some runset families are hard to satisfy with a strict GOOD+BAD pair
        # using template approximations. Keep a relaxed signal for progress tracking.
        if markers:
            relaxed_converged = True
            relaxed_reason = "context_limited_single_sided_hit"
        elif rule_type in _RELAXED_RULE_TYPES:
            relaxed_converged = True
            relaxed_reason = "relaxed_criterion"
        else:
            relaxed_converged = True
            relaxed_reason = "single_sided_hit"

    if strict_converged:
        status = "covered"
        reason = None
    elif relaxed_converged:
        status = "covered_relaxed"
        reason = relaxed_reason
    else:
        status = "attempted"
        reason = "not_converged"

    iterations_run_raw = summary.get("iterations_run", len(iterations))
    try:
        iterations_run = int(iterations_run_raw)
    except (TypeError, ValueError):
        iterations_run = len(iterations)

    return {
        "status": status,
        "reason": reason,
        "iterations_run": iterations_run,
        "good_ok": good_ok,
        "bad_ok": bad_ok,
        "converged": strict_converged,
        "converged_relaxed": relaxed_converged,
        "context_markers": markers,
    }


def run_runset_coverage(
    *,
    runset_path: Path,
    out_dir: Path,
    generator: str = "template",
    llm_model: str | None = None,
    llm_max_new_tokens: int = 256,
    llm_temperature: float = 0.2,
    llm_top_p: float = 0.9,
    llm_trust_remote_code: bool = False,
    llm_load_in_4bit: bool = False,
    llm_repair: bool = True,
    llm_good_candidates: int = 1,
    llm_bad_candidates: int = 3,
    llm_illegal_candidates: int = 1,
    llm_feedback_boost: bool = True,
    llm_candidate_growth: int = 1,
    llm_max_candidates_per_intent: int = 6,
    rule_ids: list[str] | None = None,
    rule_id_regex: str | None = None,
    max_rules: int = 0,
    max_iters: int = 1,
    initial_delta_nm: int = 20,
    resume: bool = False,
    resume_rerun_not_covered: bool = False,
) -> dict[str, Any]:
    layer_map_path = Path(__file__).resolve().parent.parent / "config" / "layers_sky130.json"
    wildcards = _parse_wildcards(runset_path)
    aliases = _parse_layer_aliases(runset_path, wildcards)
    _augment_layer_map_with_aliases(layer_map_path, aliases)
    layer_map = _load_layer_map(layer_map_path)
    rules = parse_runset_outputs(runset_path)
    semantics = parse_runset_output_semantics(runset_path)

    pairs = list(zip(rules, semantics))
    if rule_ids:
        rule_id_set = {rid.strip() for rid in rule_ids if rid.strip()}
        pairs = [pair for pair in pairs if pair[0].rule_id in rule_id_set]
    if rule_id_regex:
        rule_pat = re.compile(rule_id_regex)
        pairs = [pair for pair in pairs if rule_pat.search(pair[0].rule_id)]

    if max_rules > 0:
        pairs = pairs[:max_rules]

    rules = [pair[0] for pair in pairs]
    semantics = [pair[1] for pair in pairs]

    aligned_semantics, semantic_alignment_ok = _align_semantics(rules, semantics)

    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / "coverage_rows.jsonl"
    existing_rows = _load_existing_rows(rows_path) if resume else {}
    resumed_rows_from_cache = 0
    resumed_rules_from_summary = 0
    rows: list[dict[str, Any]] = []

    for idx, rule in enumerate(rules, start=1):
        semantic = aligned_semantics[idx - 1] if idx - 1 < len(aligned_semantics) else None
        runset_defines = _runset_defines_from_context(semantic)
        cached_row: dict[str, Any] | None = None
        rerun_cached_row = False
        base = {
            "index": idx,
            "rule_id": rule.rule_id,
            "description": rule.description,
            "line_no": rule.line_no,
            "source_file": rule.source_file,
            "runset_expression": semantic.expression if semantic else "",
            "runset_context_stack": list(semantic.context_stack) if semantic else [],
            "runset_defines": dict(runset_defines),
            "runset_expression_refs": list(semantic.expression_refs) if semantic else [],
            "runset_upstream_vars": list(semantic.upstream_vars) if semantic else [],
            "runset_upstream_assignments": (
                list(semantic.upstream_assignments) if semantic else []
            ),
            "runset_unresolved_refs": list(semantic.unresolved_refs) if semantic else [],
        }
        if resume:
            cached_row = existing_rows.get(_rule_identity(rule))
            if cached_row is not None:
                cached_status = str(cached_row.get("status") or "")
                rerun_cached_row = resume_rerun_not_covered and cached_status != "covered"
            if cached_row is not None and not rerun_cached_row:
                reused = dict(cached_row)
                reused["index"] = idx
                reused.setdefault("runset_expression", base["runset_expression"])
                reused.setdefault("runset_context_stack", base["runset_context_stack"])
                reused.setdefault("runset_defines", base["runset_defines"])
                reused.setdefault("runset_expression_refs", base["runset_expression_refs"])
                reused.setdefault("runset_upstream_vars", base["runset_upstream_vars"])
                reused.setdefault(
                    "runset_upstream_assignments", base["runset_upstream_assignments"]
                )
                reused.setdefault("runset_unresolved_refs", base["runset_unresolved_refs"])
                reused["resumed_from_cache"] = True
                rows.append(reused)
                resumed_rows_from_cache += 1
                _write_rows_jsonl(rows_path, rows)
                continue

        info = classify_rule(rule, layer_map, semantic=semantic)
        if not info.get("supported"):
            base.update(
                {
                    "status": "unsupported",
                    "reason": info.get("reason"),
                    "rule_type": info.get("rule_type"),
                    "layer": info.get("layer"),
                    "threshold_nm": info.get("threshold_nm"),
                }
            )
            rows.append(base)
            _write_rows_jsonl(rows_path, rows)
            continue

        rule_type = str(info["rule_type"])
        layer = str(info["layer"])
        layer_b = str(info["layer_b"]) if info.get("layer_b") else None
        threshold_nm = int(info.get("threshold_nm", 0))

        if rule_type == "forbidden_overlap":
            rule_type_engine = "forbidden_overlap"
            threshold_engine = max(20, threshold_nm)
        elif rule_type == "must_interact":
            rule_type_engine = "must_interact"
            threshold_engine = max(20, threshold_nm)
        elif rule_type == "forbidden_use":
            rule_type_engine = "forbidden_use"
            threshold_engine = max(1, threshold_nm)
        elif rule_type == "max_length":
            rule_type_engine = "max_length"
            threshold_engine = max(50, threshold_nm)
        elif rule_type == "max_width":
            rule_type_engine = "max_width"
            threshold_engine = max(50, threshold_nm)
        elif rule_type == "min_enclosure":
            rule_type_engine = "min_enclosure"
            threshold_engine = max(20, threshold_nm)
        elif rule_type == "via_enclosure":
            rule_type_engine = "via_enclosure"
            threshold_engine = max(20, threshold_nm)
        elif rule_type == "offgrid_vertex":
            rule_type_engine = "offgrid_vertex"
            threshold_engine = max(1, threshold_nm)
        elif rule_type == "forbidden_angle":
            rule_type_engine = "forbidden_angle"
            threshold_engine = threshold_nm if threshold_nm in {45, 90} else 90
        else:
            rule_type_engine = rule_type
            threshold_engine = threshold_nm

        run_dir = out_dir / "rules" / rule.rule_id.replace("/", "_").replace(":", "_")
        try:
            summary = None
            reused_existing_summary = False
            if resume and not rerun_cached_row:
                summary = _load_existing_rule_summary(
                    run_dir=run_dir,
                    generator=generator,
                    llm_model=llm_model,
                )
                reused_existing_summary = summary is not None
            if summary is None:
                summary = run_closed_loop(
                    rule_type=rule_type_engine,
                    layer=layer,
                    secondary_layer=layer_b,
                    threshold_nm=threshold_engine,
                    out_dir=run_dir,
                    initial_delta_nm=initial_delta_nm,
                    delta_step_nm=initial_delta_nm,
                    max_iters=max_iters,
                    runset_path=runset_path,
                    top_cell=_top_cell_for_rule(rule),
                    target_categories=_target_categories_for_rule(rule),
                    generator=generator,
                    rule_text=_compose_runset_rule_text(rule, semantic),
                    llm_model=llm_model,
                    llm_max_new_tokens=llm_max_new_tokens,
                    llm_temperature=llm_temperature,
                    llm_top_p=llm_top_p,
                    llm_trust_remote_code=llm_trust_remote_code,
                    llm_load_in_4bit=llm_load_in_4bit,
                    llm_repair=llm_repair,
                    llm_good_candidates=llm_good_candidates,
                    llm_bad_candidates=llm_bad_candidates,
                    llm_illegal_candidates=llm_illegal_candidates,
                    llm_feedback_boost=llm_feedback_boost,
                    llm_candidate_growth=llm_candidate_growth,
                    llm_max_candidates_per_intent=llm_max_candidates_per_intent,
                    runset_defines=runset_defines,
                )
            if reused_existing_summary:
                resumed_rules_from_summary += 1

            status_info = _status_from_closed_loop_summary(
                summary=summary,
                rule_type=rule_type,
                description=rule.description,
            )
            base.update(
                {
                    "status": status_info["status"],
                    "reason": status_info["reason"],
                    "rule_type": rule_type,
                    "rule_type_engine": rule_type_engine,
                    "layer": layer,
                    "layer_b": layer_b,
                    "threshold_nm": threshold_nm,
                    "threshold_engine_nm": threshold_engine,
                    "iterations_run": status_info["iterations_run"],
                    "good_ok": status_info["good_ok"],
                    "bad_ok": status_info["bad_ok"],
                    "converged": status_info["converged"],
                    "converged_relaxed": status_info["converged_relaxed"],
                    "context_markers": status_info["context_markers"],
                    "resumed_from_summary": reused_existing_summary,
                    "run_dir": str(run_dir),
                }
            )
        except Exception as exc:
            base.update(
                {
                    "status": "error",
                    "reason": "runtime_error",
                    "error": str(exc),
                    "rule_type": rule_type,
                    "layer": layer,
                    "threshold_nm": threshold_nm,
                    "run_dir": str(run_dir),
                }
            )
        rows.append(base)
        _write_rows_jsonl(rows_path, rows)

    status_counter = Counter(row["status"] for row in rows)
    reason_counter = Counter(row.get("reason") for row in rows if row.get("reason"))
    total = len(rows)
    covered = status_counter.get("covered", 0)
    covered_relaxed = covered + status_counter.get("covered_relaxed", 0)
    supported = (
        covered
        + status_counter.get("covered_relaxed", 0)
        + status_counter.get("attempted", 0)
        + status_counter.get("error", 0)
    )

    unique_rule_ids = {str(row["rule_id"]) for row in rows}
    unique_total = len(unique_rule_ids)
    unique_supported_ids = {
        str(row["rule_id"])
        for row in rows
        if row.get("status") in {"covered", "covered_relaxed", "attempted", "error"}
    }
    unique_covered_ids = {
        str(row["rule_id"]) for row in rows if row.get("status") == "covered"
    }
    unique_covered_relaxed_ids = {
        str(row["rule_id"])
        for row in rows
        if row.get("status") in {"covered", "covered_relaxed"}
    }
    rules_with_semantic_expression = sum(1 for row in rows if row.get("runset_expression"))
    rules_with_semantic_context = sum(1 for row in rows if row.get("runset_context_stack"))
    rules_with_upstream_assignments = sum(
        1 for row in rows if row.get("runset_upstream_assignments")
    )
    rules_with_unresolved_refs = sum(1 for row in rows if row.get("runset_unresolved_refs"))

    summary = {
        "runset_path": str(runset_path),
        "generator": generator,
        "llm_model": llm_model,
        "llm_max_new_tokens": llm_max_new_tokens,
        "llm_temperature": llm_temperature,
        "llm_top_p": llm_top_p,
        "llm_load_in_4bit": llm_load_in_4bit,
        "llm_repair": llm_repair,
        "llm_good_candidates": llm_good_candidates,
        "llm_bad_candidates": llm_bad_candidates,
        "llm_illegal_candidates": llm_illegal_candidates,
        "llm_feedback_boost": llm_feedback_boost,
        "llm_candidate_growth": llm_candidate_growth,
        "llm_max_candidates_per_intent": llm_max_candidates_per_intent,
        "resume": resume,
        "resume_rerun_not_covered": resume_rerun_not_covered,
        "resumed_rows_from_cache": resumed_rows_from_cache,
        "resumed_rules_from_summary": resumed_rules_from_summary,
        "rule_ids": rule_ids or [],
        "rule_id_regex": rule_id_regex,
        "total_rules": total,
        "supported_rules": supported,
        "covered_rules": covered,
        "covered_rules_relaxed": covered_relaxed,
        "support_rate": (supported / total) if total else 0.0,
        "coverage_rate": (covered / total) if total else 0.0,
        "coverage_rate_relaxed": (covered_relaxed / total) if total else 0.0,
        "unique_rule_ids_total": unique_total,
        "unique_rule_ids_supported": len(unique_supported_ids),
        "unique_rule_ids_covered": len(unique_covered_ids),
        "unique_rule_ids_covered_relaxed": len(unique_covered_relaxed_ids),
        "unique_support_rate": (len(unique_supported_ids) / unique_total) if unique_total else 0.0,
        "unique_coverage_rate": (len(unique_covered_ids) / unique_total) if unique_total else 0.0,
        "unique_coverage_rate_relaxed": (
            len(unique_covered_relaxed_ids) / unique_total
        )
        if unique_total
        else 0.0,
        "semantic_alignment_ok": semantic_alignment_ok,
        "rules_with_semantic_expression": rules_with_semantic_expression,
        "rules_with_semantic_context": rules_with_semantic_context,
        "rules_with_upstream_assignments": rules_with_upstream_assignments,
        "rules_with_unresolved_refs": rules_with_unresolved_refs,
        "status_counts": dict(status_counter),
        "reason_counts": dict(reason_counter),
    }

    (out_dir / "coverage_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    _write_rows_jsonl(rows_path, rows)
    return {"summary": summary, "rows": rows}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run full runset-rule coverage benchmark.")
    parser.add_argument(
        "--runset",
        default=str(
            Path.home()
            / ".klayout"
            / "salt"
            / "Efabless_sky130"
            / "tech"
            / "sky130"
            / "drc"
            / "sky130A_mr.drc"
        ),
    )
    parser.add_argument("--out-dir", default="artifacts/runset_coverage")
    parser.add_argument("--generator", choices=["template", "llm"], default="template")
    parser.add_argument("--llm-model")
    parser.add_argument("--llm-max-new-tokens", type=int, default=256)
    parser.add_argument("--llm-temperature", type=float, default=0.2)
    parser.add_argument("--llm-top-p", type=float, default=0.9)
    parser.add_argument("--llm-good-candidates", type=int, default=1)
    parser.add_argument("--llm-bad-candidates", type=int, default=3)
    parser.add_argument("--llm-illegal-candidates", type=int, default=1)
    parser.add_argument("--llm-trust-remote-code", action="store_true")
    parser.add_argument("--llm-load-in-4bit", action="store_true")
    parser.add_argument("--llm-disable-repair", action="store_true")
    parser.add_argument(
        "--llm-disable-feedback-boost",
        action="store_true",
        help="Disable per-iteration candidate growth driven by DRC feedback.",
    )
    parser.add_argument(
        "--llm-candidate-growth",
        type=int,
        default=1,
        help="Candidate increment per failed intent at each closed-loop iteration.",
    )
    parser.add_argument(
        "--llm-max-candidates-per-intent",
        type=int,
        default=6,
        help="Upper bound for GOOD/BAD/ILLEGAL candidate counts per iteration.",
    )
    parser.add_argument(
        "--rule-id",
        action="append",
        default=[],
        help="Only run selected rule ID(s); repeat flag for multiple IDs.",
    )
    parser.add_argument(
        "--rule-id-regex",
        default=None,
        help="Only run rules whose rule_id matches this regex.",
    )
    parser.add_argument("--max-rules", type=int, default=0)
    parser.add_argument("--max-iters", type=int, default=1)
    parser.add_argument("--initial-delta-nm", type=int, default=20)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse cached coverage rows/rule summaries in out-dir and only run missing rules.",
    )
    parser.add_argument(
        "--resume-rerun-not-covered",
        action="store_true",
        help=(
            "When used with --resume, rerun cached rows whose status is not 'covered' "
            "(covered_relaxed/attempted/error)."
        ),
    )
    args = parser.parse_args()

    if args.generator == "llm" and not args.llm_model:
        raise SystemExit("--llm-model is required for --generator llm")

    result = run_runset_coverage(
        runset_path=Path(args.runset),
        out_dir=Path(args.out_dir),
        generator=args.generator,
        llm_model=args.llm_model,
        llm_max_new_tokens=args.llm_max_new_tokens,
        llm_temperature=args.llm_temperature,
        llm_top_p=args.llm_top_p,
        llm_good_candidates=args.llm_good_candidates,
        llm_bad_candidates=args.llm_bad_candidates,
        llm_illegal_candidates=args.llm_illegal_candidates,
        llm_trust_remote_code=args.llm_trust_remote_code,
        llm_load_in_4bit=args.llm_load_in_4bit,
        llm_repair=not args.llm_disable_repair,
        llm_feedback_boost=not args.llm_disable_feedback_boost,
        llm_candidate_growth=args.llm_candidate_growth,
        llm_max_candidates_per_intent=args.llm_max_candidates_per_intent,
        rule_ids=args.rule_id,
        rule_id_regex=args.rule_id_regex,
        max_rules=args.max_rules,
        max_iters=args.max_iters,
        initial_delta_nm=args.initial_delta_nm,
        resume=args.resume,
        resume_rerun_not_covered=args.resume_rerun_not_covered,
    )
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
