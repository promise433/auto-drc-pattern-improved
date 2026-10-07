from __future__ import annotations

from collections import Counter
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any

from autodrc.closed_loop import _klayout_bin, run_closed_loop
from autodrc.runset_corpus import RunsetRule, parse_runset_outputs
from autodrc.runset_semantics import RunsetOutputSemantic, parse_runset_output_semantics
from autodrc.tech import detect_tech_name, layer_map_path_for_runset, normalize_tech_name


_COMMON_LAYER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("met1", re.compile(r"\b(?:met1|m1)\b", re.IGNORECASE)),
    ("metal1", re.compile(r"\bmetal1\b", re.IGNORECASE)),
    ("met2", re.compile(r"\b(?:met2|m2)\b", re.IGNORECASE)),
    ("metal2", re.compile(r"\bmetal2\b", re.IGNORECASE)),
    ("met3", re.compile(r"\b(?:met3|m3)\b", re.IGNORECASE)),
    ("metal3", re.compile(r"\bmetal3\b", re.IGNORECASE)),
    ("met4", re.compile(r"\b(?:met4|m4)\b", re.IGNORECASE)),
    ("metal4", re.compile(r"\bmetal4\b", re.IGNORECASE)),
    ("metal5_filler", re.compile(r"\bmetal5[:._ ]*filler\b|\bm5fil\b", re.IGNORECASE)),
    ("metal5_slit", re.compile(r"\bmetal5[:._ ]*slit\b", re.IGNORECASE)),
    ("met5", re.compile(r"\b(?:met5|m5)\b", re.IGNORECASE)),
    ("metal5", re.compile(r"\bmetal5\b", re.IGNORECASE)),
    ("li1", re.compile(r"\b(?:li1|li)\b", re.IGNORECASE)),
    ("poly", re.compile(r"\bpoly\b", re.IGNORECASE)),
    ("diff", re.compile(r"\bdiff\b", re.IGNORECASE)),
    ("tap", re.compile(r"\btap\b", re.IGNORECASE)),
    ("via", re.compile(r"\bvia\b", re.IGNORECASE)),
    ("via2", re.compile(r"\bvia2\b", re.IGNORECASE)),
    ("via3", re.compile(r"\bvia3\b", re.IGNORECASE)),
    ("via4", re.compile(r"\bvia4\b", re.IGNORECASE)),
    ("topvia1", re.compile(r"\btopvia1\b", re.IGNORECASE)),
    ("topvia2", re.compile(r"\btopvia2\b", re.IGNORECASE)),
    ("mcon", re.compile(r"\bmcon\b", re.IGNORECASE)),
    ("nwell", re.compile(r"\bnwell\b", re.IGNORECASE)),
    ("pwell", re.compile(r"\bpwell\b", re.IGNORECASE)),
    ("modulecut", re.compile(r"\bmodulecut\b", re.IGNORECASE)),
    ("areaid_re", re.compile(r"\bareaid(?:[._]re)\b", re.IGNORECASE)),
    ("difftap", re.compile(r"\bdifftap\b", re.IGNORECASE)),
]
_TECH_LAYER_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    "sky130": [
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
        ("licon", re.compile(r"\blicon\b", re.IGNORECASE)),
    ],
    "ihp_sg13g2": [
        ("activ_filler", re.compile(r"\bactiv[:._ ]*filler\b|\bafil\b", re.IGNORECASE)),
        ("activ", re.compile(r"\bactiv\b|\bact\b", re.IGNORECASE)),
        ("gatpoly_filler", re.compile(r"\bgatpoly[:._ ]*filler\b|\bgfil\b", re.IGNORECASE)),
        ("gatpoly", re.compile(r"\bgatpoly\b|\bgat\b", re.IGNORECASE)),
        ("contbar", re.compile(r"\bcontbar\b|\bcntb\b", re.IGNORECASE)),
        ("cont", re.compile(r"\bcont\b|\bcnt\b|\bcontact\b", re.IGNORECASE)),
        ("psd", re.compile(r"\bpsd\b", re.IGNORECASE)),
        ("nsd", re.compile(r"\bnsd\b", re.IGNORECASE)),
        ("pwellblock", re.compile(r"\bpwell[:._ ]*block\b|\bpwb\b", re.IGNORECASE)),
        ("nbulay", re.compile(r"\bnbulay\b|\bnbl\b", re.IGNORECASE)),
        ("nbulay_block", re.compile(r"\bnbulay[:._ ]*block\b|\bnblb\b", re.IGNORECASE)),
        ("thickgateox", re.compile(r"\bthickgateox\b|\btgo\b", re.IGNORECASE)),
        ("salblock", re.compile(r"\bsalblock\b", re.IGNORECASE)),
        ("digibnd", re.compile(r"\bdigibnd\b", re.IGNORECASE)),
        ("extblock", re.compile(r"\bextblock\b|\bextb\b", re.IGNORECASE)),
        ("mim", re.compile(r"\bmim\b", re.IGNORECASE)),
        ("topmetal1_filler", re.compile(r"\btopmetal1[:._ ]*filler\b|\btm1fil\b", re.IGNORECASE)),
        ("topmetal1_slit", re.compile(r"\btopmetal1[:._ ]*slit\b|\btm1slt\b", re.IGNORECASE)),
        ("topmetal1", re.compile(r"\btopmetal1\b|\btm1\b", re.IGNORECASE)),
        ("topmetal2", re.compile(r"\btopmetal2\b|\btm2\b", re.IGNORECASE)),
        ("topmetal2_filler", re.compile(r"\btopmetal2[:._ ]*filler\b|\btm2fil\b", re.IGNORECASE)),
        ("topmetal2_slit", re.compile(r"\btopmetal2[:._ ]*slit\b", re.IGNORECASE)),
        ("edgeseal", re.compile(r"\bedgeseal\b", re.IGNORECASE)),
        ("lbe", re.compile(r"\blbe\b", re.IGNORECASE)),
    ],
}

_THRESH_UM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(um|µm)", re.IGNORECASE)
_THRESH_NM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*nm", re.IGNORECASE)
_THRESH_AREA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:um\^?2|µm\^?2|um2|µm2|um²|µm²)", re.IGNORECASE)
_THRESH_AREA_CONTEXT_RE = re.compile(
    r"(?:um\^?2|µm\^?2|um2|µm2|um²|µm²)\)?\s*=\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_MAX_PREFIX_RE = re.compile(r"\bmax(?:imum)?\.?\b", re.IGNORECASE)
_MIN_PREFIX_RE = re.compile(r"\bmin(?:imum)?\.?\b", re.IGNORECASE)
_MINMAX_PREFIX_RE = re.compile(
    r"\bmin(?:imum)?\.?\s*(?:/|and)\s*max(?:imum)?\.?\b|\bmin/max\b",
    re.IGNORECASE,
)

_SUPPORTED_RULE_TYPES = {
    "min_width",
    "min_length",
    "max_width",
    "max_area",
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
    "max_area",
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
_COMMON_LAYER_TOKEN_ALIASES: dict[str, str] = {
    "via1": "via",
    "met1": "met1",
    "metal1": "metal1",
    "met2": "met2",
    "metal2": "metal2",
    "met3": "met3",
    "metal3": "metal3",
    "met4": "met4",
    "metal4": "metal4",
    "met5": "met5",
    "metal5": "metal5",
    "nwellhole": "nwell",
    "hvnwell": "nwell",
    "poly_licon": "poly",
    "polylicon": "poly",
}
_TECH_LAYER_TOKEN_ALIASES: dict[str, dict[str, str]] = {
    "sky130": {},
    "ihp_sg13g2": {
        "act": "activ",
        "cnt": "cont",
        "cntb": "contbar",
        "gat": "gatpoly",
        "nw": "nwell",
        "pwb": "pwellblock",
        "nbl": "nbulay",
        "nblb": "nbulay_block",
        "tgo": "thickgateox",
        "afil": "activ_filler",
        "gfil": "gatpoly_filler",
        "tm1": "topmetal1",
        "tm1fil": "topmetal1_filler",
        "tm1slt": "topmetal1_slit",
        "topmetal1": "topmetal1",
        "topmetal1_filler": "topmetal1_filler",
        "topmetal1_slit": "topmetal1_slit",
        "tm2": "topmetal2",
        "topmetal2": "topmetal2",
        "topvia1": "topvia1",
        "topvia2": "topvia2",
        "extb": "extblock",
        "extblock": "extblock",
        "mim": "mim",
        "lbe": "lbe",
    },
}
_COMMON_PREFIX_MAP: dict[str, str] = {
    "m1": "met1",
    "m2": "met2",
    "m3": "met3",
    "m4": "met4",
    "m5": "met5",
    "nw": "nwell",
    "poly": "poly",
    "via": "via",
    "via2": "via2",
    "via3": "via3",
    "via4": "via4",
}
_TECH_PREFIX_MAP: dict[str, dict[str, str]] = {
    "sky130": {
        "li": "li1",
        "ct": "mcon",
        "licon": "licon",
    },
    "ihp_sg13g2": {
        "act": "activ",
        "cnt": "cont",
        "cntb": "contbar",
        "gat": "gatpoly",
        "pwb": "pwellblock",
        "nbl": "nbulay",
        "nblb": "nbulay_block",
        "tgo": "thickgateox",
        "afil": "activ_filler",
        "gfil": "gatpoly_filler",
        "psd": "psd",
        "nsd": "nsd",
        "extb": "extblock",
        "mim": "mim",
        "tm1": "topmetal1",
        "tm1fil": "topmetal1_filler",
        "tm1slt": "topmetal1_slit",
        "tm2": "topmetal2",
        "lbe": "lbe",
    },
}
_IHP_ONLY_LAYERS = {
    "activ",
    "activ_filler",
    "cont",
    "contbar",
    "gatpoly",
    "gatpoly_filler",
    "psd",
    "nsd",
    "nbulay",
    "nbulay_block",
    "pwellblock",
    "thickgateox",
    "salblock",
    "digibnd",
    "extblock",
    "mim",
    "topmetal1",
    "topmetal1_filler",
    "topmetal1_slit",
    "topmetal2",
    "topmetal2_filler",
    "topmetal2_slit",
    "topvia1",
    "topvia2",
    "edgeseal",
    "lbe",
    "trans",
}
_SKY130_ONLY_LAYERS = {
    "diff",
    "tap",
    "licon",
    "mcon",
    "dnwell",
    "pwde",
    "nsdm",
    "psdm",
    "nsm",
    "npc",
    "capm",
    "cap2m",
    "rdl",
    "ncm",
    "difftap",
    "modulecut",
}


def _coverage_tech_name(layer_map: set[str], tech_name: str | None = None) -> str:
    if tech_name is not None:
        return normalize_tech_name(tech_name)
    ihp_score = len(layer_map & _IHP_ONLY_LAYERS)
    sky_score = len(layer_map & _SKY130_ONLY_LAYERS)
    return "ihp_sg13g2" if ihp_score > sky_score else "sky130"


def _layer_patterns_for_tech(layer_map: set[str], tech_name: str | None = None) -> list[tuple[str, re.Pattern[str]]]:
    tech = _coverage_tech_name(layer_map, tech_name)
    return _COMMON_LAYER_PATTERNS + _TECH_LAYER_PATTERNS.get(tech, [])


def _layer_token_aliases_for_tech(
    layer_map: set[str],
    tech_name: str | None = None,
) -> dict[str, str]:
    tech = _coverage_tech_name(layer_map, tech_name)
    out = dict(_COMMON_LAYER_TOKEN_ALIASES)
    out.update(_TECH_LAYER_TOKEN_ALIASES.get(tech, {}))
    return out


def _prefix_map_for_tech(layer_map: set[str], tech_name: str | None = None) -> dict[str, str]:
    tech = _coverage_tech_name(layer_map, tech_name)
    out = dict(_COMMON_PREFIX_MAP)
    out.update(_TECH_PREFIX_MAP.get(tech, {}))
    return out


def _default_overlap_pair(layer_map: set[str], tech_name: str | None = None) -> tuple[str, str]:
    tech = _coverage_tech_name(layer_map, tech_name)
    if tech == "ihp_sg13g2":
        primary_candidates = ("activ", "cont", "gatpoly", "met1", "metal1", "mim")
        secondary_candidates = ("nwell", "pwell", "met1", "metal1", "activ", "cont")
    else:
        primary_candidates = ("met1", "diff", "poly", "li1", "mcon")
        secondary_candidates = ("nwell", "diff", "tap", "poly", "met1")

    primary = next((layer for layer in primary_candidates if layer in layer_map), None)
    if primary is None:
        primary = next(iter(sorted(layer_map)), "met1")
    secondary = next(
        (layer for layer in secondary_candidates if layer in layer_map and layer != primary),
        primary,
    )
    return (primary, secondary)


def _extract_layer_mentions(text: str, layer_map: set[str]) -> list[str]:
    lowered = text.lower()
    hits: list[tuple[int, int, str]] = []
    for layer in sorted(layer_map, key=len, reverse=True):
        layer_pat = re.escape(layer).replace(r"\_", r"(?:[_\.\s:]+)")
        match = re.search(rf"\b{layer_pat}\b", lowered)
        if match:
            hits.append((match.start(), -len(layer), layer))
    if _coverage_tech_name(layer_map) != "sky130":
        hits.sort()
    return [layer for _, _, layer in hits]


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
        m5 = re.search(r'^(\w+)\s*=\s*source\.polygons\("(\d+)\/(\d+)"\)', stripped)
        if m5:
            out[m5.group(1).lower()] = (int(m5.group(2)), int(m5.group(3)))
            continue
        m6 = re.search(r"^(\w+)\s*=\s*source\.polygons\((\w+)\)", stripped)
        if m6:
            key = m6.group(2).lower()
            if key in wildcards:
                out[m6.group(1).lower()] = wildcards[key]
            continue
    return out


def _augment_layer_map_with_aliases(layer_map_path: Path, aliases: dict[str, tuple[int, int]]) -> None:
    rows = json.loads(layer_map_path.read_text(encoding="utf-8"))
    changed = False
    for alias, pair in aliases.items():
        if alias in rows:
            if tuple(rows[alias]) != pair:
                raise ValueError(f"Layer mapping conflicts with runset: {alias} {rows[alias]} != {pair}")
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
    has_max = bool(_MAX_PREFIX_RE.search(text))
    has_min = bool(_MIN_PREFIX_RE.search(text))
    has_minmax = bool(_MINMAX_PREFIX_RE.search(text))
    if "for skywater use only" in text or "use of" in text and "prohibited" in text:
        return "forbidden_use"
    if "offgrid" in text or "off-grid" in text:
        return "offgrid_vertex"
    if ("angle" in text or "angles" in text) and ("not allowed" in text or "not permitted" in text):
        return "forbidden_angle"
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
        or " overlaps " in f" {text} "
        or "prohibited" in text
        or ("not allowed" in text and (" on " in f" {text} " or " over " in f" {text} "))
    ):
        return "forbidden_overlap"
    if "length" in text and (has_minmax or "length !=" in text):
        return "max_length"
    if "length" in text and has_max:
        return "max_length"
    if "length" in text and has_min:
        return "min_length"
    if "width" in text and has_max:
        return "max_width"
    if "area" in text and has_max:
        return "max_area"
    if (
        "must be enclosed by" in text
        or "enclosure of" in text
        or "covered by" in text
        or "must be covered with" in text
        or "must be within" in text
        or "must be over" in text
        or "must enclose" in text
        or "enclose all" in text
        or "extension over" in text
        or "overlap of" in text
        or ("extension" in text and has_min)
    ):
        if "via" in text:
            return "via_enclosure"
        return "min_enclosure"
    if "enclosure" in text and "via" in text:
        return "via_enclosure"
    if "spacing" in text or " space " in f" {text} " or "space:" in text or "space or notch" in text:
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
        "metal1": "m1",
        "m2": "m2",
        "met2": "m2",
        "metal2": "m2",
        "m3": "m3",
        "met3": "m3",
        "metal3": "m3",
        "m4": "m4",
        "met4": "m4",
        "metal4": "m4",
        "m5": "m5",
        "met5": "m5",
        "metal5": "m5",
        "li": "li1",
        "li1": "li1",
        "activ": "activ",
        "cont": "cont",
        "contbar": "contbar",
        "gatpoly": "gatpoly",
        "via1": "via",
        "via": "via",
        "topmetal1": "topmetal1",
        "topmetal2": "topmetal2",
        "topvia1": "topvia1",
        "topvia2": "topvia2",
    }
    return alias_map.get(low, low)


def _layer_specificity(layer: str) -> int:
    low = layer.lower()
    score = len(low)
    if low.endswith("_block"):
        score += 40
    if low.endswith("_filler") or low.endswith("_slit"):
        score += 35
    if low.endswith("_pin"):
        score += 15
    if low.startswith("topmetal") or low.startswith("topvia"):
        score += 25
    if low in {
        "contbar",
        "nbulay",
        "nbulay_block",
        "pwellblock",
        "thickgateox",
        "salblock",
        "extblock",
        "topmetal1",
        "topmetal1_filler",
        "topmetal1_slit",
        "topmetal2",
        "topmetal2_filler",
        "topmetal2_slit",
        "topvia1",
        "topvia2",
        "trans",
    }:
        score += 50
    if low in {
        "activ",
        "cont",
        "gatpoly",
        "mim",
        "nwell",
        "pwell",
        "metal1",
        "metal2",
        "metal3",
        "metal4",
        "metal5",
        "met1",
        "met2",
        "met3",
        "met4",
        "met5",
    }:
        score -= 10
    return score


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
    resolved_prefix = _resolve_layer_token(prefix, layer_map)
    for candidate in candidates:
        cand_low = candidate.lower()
        if cand_low == prefix or cand_low.endswith(f"_{prefix}"):
            return candidate
        if (
            resolved_prefix is not None
            and _canonical_layer_name(candidate) == _canonical_layer_name(resolved_prefix)
        ):
            return candidate
    return candidates[0]


def _infer_text_layer(rule: RunsetRule, layer_map: set[str]) -> str | None:
    prefix = rule.rule_id.split(".")[0].lower()
    text = f"{rule.rule_id} {rule.description}".lower()

    pattern_hits: list[tuple[int, int, str]] = []
    for layer, pattern in _layer_patterns_for_tech(layer_map):
        if layer not in layer_map:
            continue
        match = pattern.search(text)
        if match is None:
            continue
        pattern_hits.append((_layer_specificity(layer), -match.start(), layer))
    if pattern_hits:
        return max(pattern_hits)[2]

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

    prefix_map = _prefix_map_for_tech(layer_map)
    if prefix == "cntb" and "contbar" not in layer_map:
        prefix_map = dict(prefix_map)
        prefix_map.pop("cntb", None)
    mapped = prefix_map.get(prefix)
    if mapped in layer_map:
        return mapped
    return None


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
    prefix_layer = _resolve_layer_token(rule.rule_id.split(".")[0].lower(), layer_map)
    focused_text_layer = _focused_text_layer(rule, layer_map, rule_type)
    text_layer = _infer_text_layer(rule, layer_map)

    if focused_text_layer is not None:
        if semantic_layer is not None and prefix_layer is not None and (
            _canonical_layer_name(prefix_layer) == _canonical_layer_name(semantic_layer)
        ):
            if hint_layer is not None and (
                _canonical_layer_name(semantic_layer) == _canonical_layer_name(hint_layer)
            ):
                return hint_layer
            return semantic_layer
        if hint_layer is not None and (
            _canonical_layer_name(focused_text_layer) == _canonical_layer_name(hint_layer)
        ):
            return hint_layer
        return focused_text_layer

    if semantic_layer is not None:
        if (
            text_layer is not None
            and _layer_specificity(text_layer) >= _layer_specificity(semantic_layer) + 30
        ):
            return text_layer
        if hint_layer is None:
            return semantic_layer
        if _canonical_layer_name(semantic_layer) == _canonical_layer_name(hint_layer):
            return hint_layer
        return semantic_layer

    if hint and hint != "unknown" and hint in layer_map:
        return hint
    return text_layer


def infer_threshold(rule_type: str, description: str) -> int | None:
    text = description.lower()
    if rule_type in {"min_area", "max_area"}:
        matches = _THRESH_AREA_RE.findall(text)
        if matches:
            value = float(matches[-1])
            return int(round(value * 1_000_000))
        match = _THRESH_AREA_CONTEXT_RE.search(text)
        if match is not None:
            value = float(match.group(1))
            return int(round(value * 1_000_000))
        inline = re.findall(r"=\s*(\d+(?:\.\d+)?)\b", text)
        if not inline:
            return None
        value = float(inline[-1])
        return int(round(value * 1_000_000))

    nm_matches = _THRESH_NM_RE.findall(text)
    if nm_matches:
        value = float(nm_matches[-1])
        return int(round(value))

    um_matches = _THRESH_UM_RE.findall(text)
    if not um_matches:
        inline = re.search(r"=\s*(\d+(?:\.\d+)?)\b", text)
        if not inline or _THRESH_AREA_RE.search(text):
            return None
        value = float(inline.group(1))
    else:
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
    for layer, pattern in _layer_patterns_for_tech(layer_map):
        if layer in layer_map and pattern.search(text):
            found.append(layer)
    unique = []
    for layer in found:
        if layer not in unique:
            unique.append(layer)
    if len(unique) >= 2:
        return unique[0], unique[1]
    if len(unique) == 1:
        primary, secondary = _default_overlap_pair(layer_map)
        if unique[0] != primary and primary in layer_map:
            return unique[0], primary
        if unique[0] != secondary and secondary in layer_map:
            return unique[0], secondary
        return unique[0], unique[0]
    return _default_overlap_pair(layer_map)


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
    mapped = _layer_token_aliases_for_tech(layer_map).get(compact)
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


def _resolve_primary_layer_phrase(phrase: str, layer_map: set[str]) -> str | None:
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

    mentions = _extract_layer_mentions(low, layer_map)
    unique_mentions: list[str] = []
    for mention in mentions:
        if mention not in unique_mentions:
            unique_mentions.append(mention)
    if len(unique_mentions) == 1:
        return unique_mentions[0]
    if len(unique_mentions) > 1:
        return None

    pattern_hits: list[str] = []
    for layer, pattern in _layer_patterns_for_tech(layer_map):
        if layer not in layer_map:
            continue
        if pattern.search(low):
            pattern_hits.append(layer)
    unique_hits: list[str] = []
    for hit in pattern_hits:
        if hit not in unique_hits:
            unique_hits.append(hit)
    if len(unique_hits) == 1:
        return unique_hits[0]
    return None


def _focused_text_layer(
    rule: RunsetRule,
    layer_map: set[str],
    rule_type: str | None,
) -> str | None:
    if rule_type not in {
        "min_width",
        "max_width",
        "min_length",
        "max_length",
        "min_area",
        "max_area",
        "min_spacing",
    }:
        return None

    description = re.sub(r"^\s*[a-z0-9_.-]+\s*:\s*", "", rule.description.lower()).strip()
    keyword_map = {
        "min_width": "width",
        "max_width": "width",
        "min_length": "length",
        "max_length": "length",
        "min_area": "area",
        "max_area": "area",
        "min_spacing": "space",
    }
    keyword = keyword_map.get(rule_type)
    if not keyword:
        return None

    match = re.search(rf"\b{keyword}\b", description)
    if match is None:
        return None

    prefix = description[: match.start()]
    prefix = re.sub(r"^\s*(?:min(?:imum)?|max(?:imum)?)(?:\.)?\s*", "", prefix).strip(" :-")
    prefix = re.sub(r"\b(?:minimum|maximum|min|max)\b.*$", "", prefix).strip(" :-")
    if not prefix:
        return None
    return _resolve_primary_layer_phrase(prefix, layer_map)


def _enclosure_pair_from_text(text: str, layer_map: set[str]) -> tuple[str, str] | None:
    t = text.lower()
    t = re.sub(r"^\s*[a-z0-9_.-]+\s*:\s*", "", t)
    phrase = r"[a-z0-9_:+\- ]+?"
    final_phrase = r"[a-z0-9_:+\- ]+"

    patterns: list[tuple[re.Pattern[str], str, str]] = [
        (
            re.compile(
                rf"\b(?P<inner>{phrase})\b.*\b(?:must be enclosed by|enclosed by|covered by|must be covered with|must be within|must be over)\b\s*(?P<outer>{final_phrase})",
                re.IGNORECASE,
            ),
            "inner",
            "outer",
        ),
        (
            re.compile(
                rf"\benclosure of\s+(?P<inner>{phrase})\s+by\s+(?P<outer>{final_phrase})",
                re.IGNORECASE,
            ),
            "inner",
            "outer",
        ),
        (
            re.compile(
                rf"\b(?P<outer>{phrase})\s+enclosure of\s+(?P<inner>{final_phrase})",
                re.IGNORECASE,
            ),
            "inner",
            "outer",
        ),
        (
            re.compile(
                rf"\b(?P<outer>{phrase})\b.*\b(?:must enclose(?: all)?|enclose all)\b.*\b(?P<inner>{final_phrase})\b",
                re.IGNORECASE,
            ),
            "inner",
            "outer",
        ),
        (
            re.compile(
                rf"\b(?P<outer>{phrase})\s+extension over\s+(?P<inner>{final_phrase})",
                re.IGNORECASE,
            ),
            "inner",
            "outer",
        ),
        (
            re.compile(
                rf"\b(?P<outer>{phrase})\s+overlap of\s+(?P<inner>{final_phrase})",
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
        if "enclosure of" in t:
            if " by " in f" {t} ":
                return (uniq[0], uniq[1])
            return (uniq[1], uniq[0])
        if "enclose all" in t or "must enclose" in t:
            return (uniq[1], uniq[0])
        if "enclosed by" in t or "covered by" in t or "must be covered with" in t or "must be within" in t:
            return (uniq[0], uniq[1])
        if "extension over" in t or "overlap of" in t:
            return (uniq[1], uniq[0])
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
    patterns.append(
        (
            re.compile(r"\b(?P<inner>[a-z0-9_]+)\s*\.ext_enclosed\(\s*(?P<outer>[a-z0-9_]+)\b"),
            "inner",
            "outer",
        )
    )
    semantic_texts = [semantic.expression, *reversed(semantic.upstream_assignments)]
    for raw_text in semantic_texts:
        expr = raw_text.lower()
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
    if semantic is not None and _coverage_tech_name(layer_map) == "ihp_sg13g2":
        from autodrc.ihp_contracts import compile_contract
        contract = compile_contract(semantic.expression, semantic.upstream_assignments, layer_map, rule_type)
        if contract is not None:
            if contract.get('official_limitation'):
                return dict(supported=False,reason='official_empty_executed_interval',
                            rule_type=contract['rule_type'],ihp_contract=contract,
                            official_limitation=contract['official_limitation'])
            layers = contract['operand_layers']
            kind = contract['rule_type']
            paired = contract['operation'] in {'ext_enclosed', 'ext_not', 'endcap'}
            return dict(supported=True, rule_type='min_enclosure' if kind == 'coverage' else kind,
                        layer=layers[1] if paired else layers[0],
                        **({'layer_b': layers[0] if paired else layers[1]} if len(layers) == 2 else {}),
                        threshold_nm=max(1, contract['threshold_nm']), ihp_contract=contract)
    if rule_type is None:
        return {"supported": False, "reason": "unsupported_rule_type", "rule_type": None}

    if rule_type not in _SUPPORTED_RULE_TYPES:
        return {"supported": False, "reason": "unsupported_rule_type", "rule_type": rule_type}

    if rule_type == "forbidden_use":
        receiver = semantic.expression.strip() if semantic else ""
        layer = (_resolve_semantic_layer_token(receiver, layer_map)
                 if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", receiver) else None)
        layer = layer or infer_layer(rule, layer_map, semantic=semantic, rule_type=rule_type)
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
        elif threshold == 0:
            threshold = 1
        elif threshold < 0:
            return {
                "supported": False,
                "reason": "invalid_threshold",
                "rule_type": rule_type,
                "layer": outer_layer,
                "threshold_nm": threshold,
            }

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

    if threshold == 0:
        threshold = 1

    if threshold < 0:
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
    if semantic is not None and semantic.anonymous_body:
        parts.append("Anonymous body: " + re.sub(r"\s+", " ", semantic.anonymous_body).strip())
    if semantic is not None and semantic.anonymous_body:
        from autodrc.ihp_contracts import compile_contract
        # The runtime config is the IHP layer namespace; no SKY fallback aliases.
        contract = compile_contract(semantic.expression, semantic.upstream_assignments,
                                    set(_load_layer_map(Path(__file__).parent.parent / 'config/layers_ihp_sg13g2.json')),
                                    infer_rule_type(rule.description))
        if contract is not None:
            parts.append('IHP contract: ' + json.dumps(contract, sort_keys=True))
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
    cache_identity: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if cache_identity is not None:
        identity_path = run_dir / "cache_identity.json"
        if not identity_path.exists():
            return None
        try:
            if json.loads(identity_path.read_text(encoding="utf-8")) != cache_identity:
                return None
        except (ValueError, OSError):
            return None
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


def _exact_target_status(summary: dict[str, Any], rule_id: str) -> dict[str, Any]:
    iterations = summary.get("iterations") or []
    cases = iterations[-1].get("cases", []) if iterations else []
    good = [case for case in cases if case.get("intent") == "GOOD"]
    bad = [case for case in cases if case.get("intent") == "BAD"]
    evidence = bool(good and bad) and all(isinstance(case.get("category_hits"), dict) for case in good + bad)
    def valid(case: dict[str, Any]) -> bool:
        return bool(case.get("geometry_valid")) and case.get("drc_returncode") == 0
    good_ok = evidence and all(valid(case) and case["category_hits"].get(rule_id, 0) == 0 for case in good)
    bad_ok = evidence and all(valid(case) and case["category_hits"].get(rule_id, 0) > 0 for case in bad)
    return {"exact_target_evidence": evidence, "exact_target_good_ok": bool(good_ok),
            "exact_target_bad_ok": bool(bad_ok), "exact_target_strict": bool(good_ok and bad_ok)}


def _cache_asset_identity(reference: str) -> dict[str, Any]:
    path = Path(reference)
    if not path.exists():
        return {"reference": reference, "content_known": False}
    files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
    hashes = {}
    for file in files:
        digest = hashlib.sha256()
        with file.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
        hashes[file.name if path.is_file() else str(file.relative_to(path))] = digest.hexdigest()
    return {"path": str(path.resolve()), "content_known": True, "files": hashes}


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
    llm_fallback: bool | None = None,
    llm_prompt_profile: str = 'legacy',
    llm_strict_response: bool = False,
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
    tech_name = detect_tech_name(runset_path)
    layer_map_path = layer_map_path_for_runset(runset_path)
    wildcards = _parse_wildcards(runset_path)
    aliases = _parse_layer_aliases(runset_path, wildcards)
    _augment_layer_map_with_aliases(layer_map_path, aliases)
    layer_map = _load_layer_map(layer_map_path)
    rules = parse_runset_outputs(runset_path)
    semantics = parse_runset_output_semantics(runset_path)
    directory_counts = Counter(rule.rule_id.replace("/", "_").replace(":", "_") for rule in rules)
    generation_parameters = {
        "tech_name": tech_name,
        "generator": generator, "llm_model": llm_model, "llm_max_new_tokens": llm_max_new_tokens,
        "llm_temperature": llm_temperature, "llm_top_p": llm_top_p,
        "llm_trust_remote_code": llm_trust_remote_code, "llm_load_in_4bit": llm_load_in_4bit,
        "llm_repair": llm_repair,
        "llm_fallback": llm_repair if llm_fallback is None else llm_fallback,
        "llm_prompt_profile": llm_prompt_profile,"llm_strict_response": llm_strict_response, "llm_good_candidates": llm_good_candidates,
        "llm_bad_candidates": llm_bad_candidates, "llm_illegal_candidates": llm_illegal_candidates,
        "llm_feedback_boost": llm_feedback_boost, "llm_candidate_growth": llm_candidate_growth,
        "llm_max_candidates_per_intent": llm_max_candidates_per_intent,
        "max_iters": max_iters, "initial_delta_nm": initial_delta_nm,
    }
    source_root = Path(__file__).parent
    signature_inputs = {
        "version": 3,
        "runset_sha256": hashlib.sha256(runset_path.read_bytes()).hexdigest(),
        "layer_map_sha256": hashlib.sha256(layer_map_path.read_bytes()).hexdigest(),
        "parameters": generation_parameters,
        "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted(source_root.glob("*.py"))},
        "converter": _cache_asset_identity(str(source_root.parent / "scripts/lpl_to_gds.rb")),
        "python": {"executable": sys.executable, "version": sys.version},
        "engine": _cache_asset_identity(shutil.which(_klayout_bin()) or _klayout_bin()),
        "engine_environment": {name: os.environ.get(name, "") for name in
                               ("AUTO_DRC_KLAYOUT_LD_LIBRARY_PATH", "LD_LIBRARY_PATH", "KLAYOUT_PATH")},
    }
    library_files = {}
    library_directories = (os.environ.get("AUTO_DRC_KLAYOUT_LD_LIBRARY_PATH", "") + os.pathsep +
                           os.environ.get("LD_LIBRARY_PATH", "")).split(os.pathsep)
    for directory in dict.fromkeys(library_directories):
        if directory:
            for path in sorted(Path(directory).glob("libklayout*.so*")):
                if path.is_file():
                    resolved = str(path.resolve())
                    if resolved not in library_files:
                        library_files[resolved] = _cache_asset_identity(resolved)
    signature_inputs["engine_libraries"] = library_files
    if generator == "llm" and llm_model:
        signature_inputs["model"] = _cache_asset_identity(llm_model)
        versions = {}
        for name in ("torch", "transformers", "tokenizers", "numpy", "accelerate", "bitsandbytes"):
            try:
                versions[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                versions[name] = None
        signature_inputs["model_packages"] = versions
    cache_signature = hashlib.sha256(json.dumps(signature_inputs, sort_keys=True).encode()).hexdigest()

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
    cache_inputs_dir = out_dir / "cache_inputs"
    cache_inputs_dir.mkdir(exist_ok=True)
    cache_inputs_file = cache_inputs_dir / (cache_signature + ".json")
    if not cache_inputs_file.exists():
        cache_inputs_file.write_text(json.dumps(signature_inputs, indent=2, sort_keys=True), encoding="utf-8")
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
            "tech_name": tech_name,
            "index": idx,
            "rule_id": rule.rule_id,
            "description": rule.description,
            "line_no": rule.line_no,
            "source_file": rule.source_file,
            "cache_signature": cache_signature,
            "runset_expression": semantic.expression if semantic else "",
            "runset_anonymous_body": semantic.anonymous_body if semantic else "",
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
            if cached_row is not None and cached_row.get("cache_signature") != cache_signature:
                cached_row = None
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

        directory_name = rule.rule_id.replace("/", "_").replace(":", "_")
        if directory_counts[directory_name] > 1:
            description_hash = hashlib.sha256(rule.description.encode()).hexdigest()[:12]
            directory_name += f"_L{rule.line_no}_{description_hash}"
        run_dir = out_dir / "rules" / directory_name
        cache_identity = {"signature": cache_signature, "rule_id": rule.rule_id,
                          "line_no": rule.line_no, "description": rule.description,
                          "rule_text": _compose_runset_rule_text(rule, semantic), "defines": runset_defines}
        try:
            summary = None
            reused_existing_summary = False
            if resume and not rerun_cached_row:
                summary = _load_existing_rule_summary(
                    run_dir=run_dir,
                    generator=generator,
                    llm_model=llm_model,
                    cache_identity=cache_identity,
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
                    llm_fallback=llm_fallback,llm_prompt_profile=llm_prompt_profile,
                    llm_strict_response=llm_strict_response,
                    llm_good_candidates=llm_good_candidates,
                    llm_bad_candidates=llm_bad_candidates,
                    llm_illegal_candidates=llm_illegal_candidates,
                    llm_feedback_boost=llm_feedback_boost,
                    llm_candidate_growth=llm_candidate_growth,
                    llm_max_candidates_per_intent=llm_max_candidates_per_intent,
                    runset_defines=runset_defines,
                )
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "cache_identity.json").write_text(json.dumps(cache_identity, indent=2), encoding="utf-8")
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
            base.update(_exact_target_status(summary, rule.rule_id))
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
        "coverage_criterion": "legacy_target_set; exact_target_strict separately requires the output ID itself",
        "exact_target_covered_rules": sum(bool(row.get("exact_target_strict")) for row in rows),
        "exact_target_unique_rule_ids_covered": len({row["rule_id"] for row in rows if row.get("exact_target_strict")}),
        "exact_target_unverified_rules": sum(not row.get("exact_target_evidence", False) for row in rows),
        "runset_path": str(runset_path),
        "generator": generator,
        "llm_model": llm_model,
        "llm_max_new_tokens": llm_max_new_tokens,
        "llm_temperature": llm_temperature,
        "llm_top_p": llm_top_p,
        "llm_load_in_4bit": llm_load_in_4bit,
        "llm_repair": llm_repair,
        "llm_fallback": llm_repair if llm_fallback is None else llm_fallback,
        "llm_prompt_profile": llm_prompt_profile,"llm_strict_response": llm_strict_response,
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
        help="Path to a DRC runset",
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
    parser.add_argument("--llm-fallback",choices=["auto","enabled","disabled"],default="auto")
    parser.add_argument("--llm-prompt-profile",choices=["legacy","compact","chat"],default="legacy")
    parser.add_argument("--llm-strict-response",action="store_true")
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
        llm_fallback={'auto':None,'enabled':True,'disabled':False}[args.llm_fallback],
        llm_prompt_profile=args.llm_prompt_profile,llm_strict_response=args.llm_strict_response,
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
