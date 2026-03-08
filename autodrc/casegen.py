from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Iterable

from autodrc.lpl import Polygon, rectangle, validate_all


@dataclass(frozen=True)
class PatternCase:
    case_id: str
    intent: str
    description: str
    polygons: tuple[Polygon, ...]
    allow_non_manhattan: bool = False

    def to_dict(self) -> dict[str, object]:
        errors = validate_all(
            self.polygons, allow_non_manhattan=self.allow_non_manhattan
        )
        return {
            "case_id": self.case_id,
            "intent": self.intent,
            "description": self.description,
            "lpl": [poly.to_dict() for poly in self.polygons],
            "geometry_valid": len(errors) == 0,
            "validation_errors": errors,
        }


def _load_known_layers() -> set[str]:
    cfg = Path(__file__).resolve().parent.parent / "config" / "layers_sky130.json"
    try:
        rows = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(rows, dict):
        return set()
    return {str(key).strip().lower() for key in rows.keys() if str(key).strip()}


_RULE_TEXT_EXTRA_LAYERS = {
    "areaid_ce",
    "areaid_ce_merged",
    "hvtp",
    "hvtr",
    "prec_resistor",
    "uhvi",
    "vhvi",
}
_KNOWN_LAYERS = _load_known_layers() | _RULE_TEXT_EXTRA_LAYERS
_LAYER_ALIASES = {
    "m1": "met1",
    "m2": "met2",
    "m3": "met3",
    "m4": "met4",
    "m5": "met5",
    "li": "li1",
    "via1": "via",
    "met1": "met1",
    "met2": "met2",
    "met3": "met3",
    "met4": "met4",
    "met5": "met5",
}
_LAYER_SIZE_HINT_NM = {
    "dnwell": 3000,
    "nwell": 840,
    "hvi": 600,
    "hvtr": 380,
    "hvtp": 380,
    "rdl": 10000,
    "rpm": 1270,
    "urpm": 1270,
    "nsdm": 380,
    "psdm": 380,
    "capm": 1000,
    "cap2m": 1000,
    "met1": 140,
    "met2": 140,
    "met3": 300,
    "met4": 300,
    "met5": 1600,
    "li1": 170,
    "licon": 170,
    "mcon": 170,
    "via": 150,
    "via2": 200,
    "via3": 200,
    "via4": 800,
}


def _normalize_layer_name(token: str) -> str | None:
    low = token.strip().lower()
    if not low:
        return None
    low = re.sub(r"[^a-z0-9_]+", "", low)
    if not low:
        return None
    mapped = _LAYER_ALIASES.get(low, low)
    if mapped in _KNOWN_LAYERS:
        return mapped
    return None


def _extract_layers_from_text(text: str | None) -> list[str]:
    if not text:
        return []
    low = text.lower()
    found: list[str] = []
    for layer in sorted(_KNOWN_LAYERS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(layer)}\b", low):
            normalized = _normalize_layer_name(layer)
            if normalized and normalized not in found:
                found.append(normalized)
    return found


def _layer_size_hint(layer: str) -> int:
    normalized = _normalize_layer_name(layer) or layer.lower()
    return _LAYER_SIZE_HINT_NM.get(normalized, 80)


def _bbox(poly: Polygon) -> tuple[int, int, int, int]:
    xs = [point[0] for point in poly.points]
    ys = [point[1] for point in poly.points]
    return min(xs), min(ys), max(xs), max(ys)


def _extract_spacing_partner_layer(*, rule_text: str | None, primary_layer: str) -> str | None:
    if not rule_text:
        return None
    low = rule_text.lower()
    primary = _normalize_layer_name(primary_layer) or primary_layer.lower()
    if "difftap.space(" in low:
        return "tap" if primary != "tap" else "diff"
    match = re.search(r"\.separation\(([^,]+),", low)
    candidates: list[str] = []
    if match is not None:
        candidates.extend(_extract_layers_from_text(match.group(1)))
        candidates.extend(_extract_layers_from_text(low[: match.start()]))
    for layer in candidates:
        if layer == primary or layer.startswith("areaid"):
            continue
        return layer
    return None


def _is_huge_spacing_rule(rule_text: str | None) -> bool:
    if not rule_text:
        return False
    low = rule_text.lower()
    expr = low
    for line in rule_text.splitlines():
        line_low = line.strip().lower()
        if line_low.startswith("runset expression:"):
            expr = line_low.split(":", 1)[1].strip()
            break
    return bool(re.search(r"\bhuge_[a-z0-9_]+\s*\.(?:space|separation)\(", expr))


def _is_hole_area_rule(rule_text: str | None) -> bool:
    if not rule_text:
        return False
    low = rule_text.lower()
    return ".holes" in low and "with_area" in low


def _is_across_boundary_spacing_rule(rule_text: str | None) -> bool:
    if not rule_text:
        return False
    low = rule_text.lower()
    return "outside_part(areaid" in low and "interacting(areaid" in low and ".space(" in low


def _is_across_boundary_width_rule(rule_text: str | None) -> bool:
    if not rule_text:
        return False
    low = rule_text.lower()
    return "outside_part(areaid" in low and "interacting(areaid" in low and ".width(" in low


def _is_hole_enclosure_rule(rule_text: str | None) -> bool:
    if not rule_text:
        return False
    low = rule_text.lower()
    return ".holes" in low or "nwellhole" in low


def _extract_via_size_nm(*, rule_text: str | None, via_layer: str) -> int:
    default = _layer_size_hint(via_layer)
    if not rule_text:
        return default
    low = rule_text.lower()
    match = re.search(r"width\s*==\s*(\d+(?:\.\d+)?)", low)
    if match is not None:
        return max(1, int(round(float(match.group(1)) * 1000)))
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:um|µm)\s+via\d*", low)
    if match is not None:
        return max(1, int(round(float(match.group(1)) * 1000)))
    return default


def _has_adjacent_edge_enclosure(rule_text: str | None) -> bool:
    if not rule_text:
        return False
    low = rule_text.lower()
    return "2 adjacent edges" in low or ("projection" in low and "second_edges" in low)


def _ring_polygons(
    layer: str, x: int, y: int, outer_w: int, outer_h: int, ring_w: int
) -> tuple[Polygon, ...]:
    if ring_w <= 0:
        raise ValueError("ring_w must be > 0")
    if outer_w <= 2 * ring_w or outer_h <= 2 * ring_w:
        raise ValueError("outer size must be > 2 * ring_w")
    top = rectangle(layer, x, y + outer_h - ring_w, outer_w, ring_w)
    bottom = rectangle(layer, x, y, outer_w, ring_w)
    left = rectangle(layer, x, y + ring_w, ring_w, outer_h - 2 * ring_w)
    right = rectangle(
        layer, x + outer_w - ring_w, y + ring_w, ring_w, outer_h - 2 * ring_w
    )
    return (top, bottom, left, right)


def _is_ring_rule(rule_text: str | None) -> bool:
    if not rule_text:
        return False
    low = rule_text.lower()
    return "ring-shaped" in low or ".holes" in low or "nwellhole" in low


def _is_cover_only_rule(rule_text: str | None) -> bool:
    if not rule_text:
        return False
    low = rule_text.lower()
    if "must be enclosed by" in low and ".not(" in low:
        return True
    has_cover_phrase = (
        "must be enclosed by" in low
        or "must enclose all" in low
        or "should covered by" in low
        or "must be enclosed in" in low
    )
    has_numeric = bool(re.search(r"\d+(?:\.\d+)?\s*(?:nm|um|µm)", low))
    return has_cover_phrase and (not has_numeric)


def _is_min_max_length_rule(rule_text: str | None) -> bool:
    if not rule_text:
        return False
    low = rule_text.lower()
    return ("min/max" in low and "length" in low) or ("length !=" in low)


def generate_min_width_cases(
    *,
    layer: str,
    min_width_nm: int,
    delta_nm: int = 20,
    run_length_nm: int = 400,
    ring_mode: bool = False,
) -> list[PatternCase]:
    if min_width_nm <= 0:
        raise ValueError("min_width_nm must be > 0")
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")
    if run_length_nm <= 0:
        raise ValueError("run_length_nm must be > 0")

    good_width = min_width_nm + delta_nm
    bad_width = max(1, min_width_nm - delta_nm)

    run_length_nm = max(run_length_nm, good_width + delta_nm)

    if ring_mode:
        ring_span = max(run_length_nm, good_width * 8)
        ring_span = max(ring_span, 2 * good_width + 40)
        bad_ring_width = min(max(1, bad_width), max(1, ring_span // 2 - 1))
        good_polys = _ring_polygons(layer, 0, 0, ring_span, ring_span, good_width)
        bad_polys = _ring_polygons(layer, 0, 0, ring_span, ring_span, bad_ring_width)
        illegal_poly = Polygon(
            layer=layer,
            points=((0, 0), (ring_span, 20), (ring_span, 80), (0, 80), (0, 0)),
        )
        good = PatternCase(
            case_id=f"{layer}_ring_width_good",
            intent="GOOD",
            description=f"ring width {good_width}nm >= min_width {min_width_nm}nm",
            polygons=good_polys,
        )
        bad = PatternCase(
            case_id=f"{layer}_ring_width_bad",
            intent="BAD",
            description=f"ring width {bad_ring_width}nm < min_width {min_width_nm}nm",
            polygons=bad_polys,
        )
        illegal = PatternCase(
            case_id=f"{layer}_ring_width_illegal",
            intent="ILLEGAL",
            description="contains non-manhattan edge to simulate syntax/geometry illegal case",
            polygons=(illegal_poly,),
        )
        return [good, bad, illegal]

    good = PatternCase(
        case_id=f"{layer}_width_good",
        intent="GOOD",
        description=f"width {good_width}nm >= min_width {min_width_nm}nm",
        polygons=(rectangle(layer, 0, 0, run_length_nm, good_width),),
    )
    bad = PatternCase(
        case_id=f"{layer}_width_bad",
        intent="BAD",
        description=f"width {bad_width}nm < min_width {min_width_nm}nm",
        polygons=(rectangle(layer, 0, 0, run_length_nm, bad_width),),
    )

    illegal_poly = Polygon(
        layer=layer,
        points=((0, 0), (run_length_nm, 20), (run_length_nm, 80), (0, 80), (0, 0)),
    )
    illegal = PatternCase(
        case_id=f"{layer}_width_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge to simulate syntax/geometry illegal case",
        polygons=(illegal_poly,),
    )
    return [good, bad, illegal]


def generate_across_boundary_min_width_cases(
    *,
    layer: str,
    min_width_nm: int,
    delta_nm: int = 20,
    areaid_layer: str = "areaid_ce",
) -> list[PatternCase]:
    if min_width_nm <= 0:
        raise ValueError("min_width_nm must be > 0")
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")

    body_h = max(1200, min_width_nm * 4)
    good_width = min_width_nm + delta_nm
    bad_width = max(1, min_width_nm - delta_nm)
    overlap_y = ((max(240, min(body_h // 2, 600)) + 4) // 5) * 5
    areaid_y = ((max(80, (body_h - overlap_y) // 2) + 4) // 5) * 5
    pad_x = max(40, min(120, min_width_nm // 2))

    good_poly = rectangle(layer, 0, 0, good_width, body_h)
    bad_poly = rectangle(layer, 0, 0, bad_width, body_h)
    good_areaid = rectangle(
        areaid_layer,
        -pad_x,
        areaid_y,
        good_width + 2 * pad_x,
        overlap_y,
    )
    bad_areaid = rectangle(
        areaid_layer,
        -pad_x,
        areaid_y,
        bad_width + 2 * pad_x,
        overlap_y,
    )
    illegal_poly = Polygon(
        layer=layer,
        points=((0, 0), (bad_width + 40, 20), (bad_width, body_h), (0, body_h), (0, 0)),
    )

    good = PatternCase(
        case_id=f"{layer}_across_areaid_width_good",
        intent="GOOD",
        description=f"across-boundary width {good_width}nm >= {min_width_nm}nm",
        polygons=(good_poly, good_areaid),
    )
    bad = PatternCase(
        case_id=f"{layer}_across_areaid_width_bad",
        intent="BAD",
        description=f"across-boundary width {bad_width}nm < {min_width_nm}nm",
        polygons=(bad_poly, bad_areaid),
    )
    illegal = PatternCase(
        case_id=f"{layer}_across_areaid_width_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge to simulate syntax/geometry illegal case",
        polygons=(bad_areaid, illegal_poly),
    )
    return [good, bad, illegal]


def generate_min_spacing_cases(
    *,
    layer: str,
    min_spacing_nm: int,
    delta_nm: int = 20,
    bar_width_nm: int = 80,
    bar_height_nm: int = 400,
) -> list[PatternCase]:
    if min_spacing_nm <= 0:
        raise ValueError("min_spacing_nm must be > 0")
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")
    if bar_width_nm <= 0 or bar_height_nm <= 0:
        raise ValueError("bar_width_nm and bar_height_nm must be > 0")

    bar_width_nm = max(bar_width_nm, _layer_size_hint(layer))
    bar_height_nm = max(bar_height_nm, bar_width_nm * 2)

    good_spacing = min_spacing_nm + delta_nm
    bad_spacing = max(0, min_spacing_nm - delta_nm)

    left = rectangle(layer, 0, 0, bar_width_nm, bar_height_nm)
    right_good = rectangle(
        layer, bar_width_nm + good_spacing, 0, bar_width_nm, bar_height_nm
    )
    right_bad = rectangle(
        layer, bar_width_nm + bad_spacing, 0, bar_width_nm, bar_height_nm
    )
    illegal_poly = Polygon(
        layer=layer,
        points=((0, 0), (100, 50), (180, 50), (180, 120), (0, 120), (0, 0)),
    )

    good = PatternCase(
        case_id=f"{layer}_spacing_good",
        intent="GOOD",
        description=f"spacing {good_spacing}nm >= min_spacing {min_spacing_nm}nm",
        polygons=(left, right_good),
    )
    bad = PatternCase(
        case_id=f"{layer}_spacing_bad",
        intent="BAD",
        description=f"spacing {bad_spacing}nm < min_spacing {min_spacing_nm}nm",
        polygons=(left, right_bad),
    )
    illegal = PatternCase(
        case_id=f"{layer}_spacing_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge to simulate syntax/geometry illegal case",
        polygons=(left, illegal_poly),
    )
    return [good, bad, illegal]


def generate_cross_layer_spacing_cases(
    *,
    layer: str,
    other_layer: str,
    min_spacing_nm: int,
    delta_nm: int = 20,
) -> list[PatternCase]:
    if min_spacing_nm <= 0:
        raise ValueError("min_spacing_nm must be > 0")
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")

    primary_w = max(120, _layer_size_hint(layer))
    secondary_w = max(120, _layer_size_hint(other_layer))
    primary_h = max(400, primary_w * 2)
    secondary_h = max(400, secondary_w * 2)
    good_spacing = min_spacing_nm + delta_nm
    bad_spacing = max(1, min_spacing_nm - delta_nm)

    left = rectangle(layer, 0, 0, primary_w, primary_h)
    right_good = rectangle(other_layer, primary_w + good_spacing, 0, secondary_w, secondary_h)
    right_bad = rectangle(other_layer, primary_w + bad_spacing, 0, secondary_w, secondary_h)
    illegal_poly = Polygon(
        layer=other_layer,
        points=((primary_w + bad_spacing, 0), (primary_w + bad_spacing + 40, 30), (primary_w + bad_spacing + secondary_w, 30), (primary_w + bad_spacing + secondary_w, secondary_h), (primary_w + bad_spacing, secondary_h), (primary_w + bad_spacing, 0)),
    )

    good = PatternCase(
        case_id=f"{layer}_{other_layer}_spacing_good",
        intent="GOOD",
        description=f"{layer}/{other_layer} spacing {good_spacing}nm >= {min_spacing_nm}nm",
        polygons=(left, right_good),
    )
    bad = PatternCase(
        case_id=f"{layer}_{other_layer}_spacing_bad",
        intent="BAD",
        description=f"{layer}/{other_layer} spacing {bad_spacing}nm < {min_spacing_nm}nm",
        polygons=(left, right_bad),
    )
    illegal = PatternCase(
        case_id=f"{layer}_{other_layer}_spacing_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge to simulate syntax/geometry illegal case",
        polygons=(left, illegal_poly),
    )
    return [good, bad, illegal]


def generate_across_boundary_spacing_cases(
    *,
    layer: str,
    min_spacing_nm: int,
    delta_nm: int = 20,
    areaid_layer: str = "areaid_ce",
) -> list[PatternCase]:
    if min_spacing_nm <= 0:
        raise ValueError("min_spacing_nm must be > 0")
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")

    body_w = max(_layer_size_hint(layer), min_spacing_nm)
    body_h = max(body_w * 2, 760)
    y_shift = ((max(80, body_h // 3) + 4) // 5) * 5
    overlap = ((max(40, min(120, body_w // 4)) + 4) // 5) * 5
    good_spacing = min_spacing_nm + delta_nm
    bad_spacing = max(1, min_spacing_nm - delta_nm)
    areaid_y = ((max(40, min(body_h // 3, 200)) + 4) // 5) * 5
    areaid_h = ((max(260, min(body_h // 2, body_h - areaid_y + y_shift // 2)) + 4) // 5) * 5

    left = rectangle(layer, 0, 0, body_w, body_h)
    right_good = rectangle(layer, body_w + good_spacing, y_shift, body_w, body_h)
    right_bad = rectangle(layer, body_w + bad_spacing, y_shift, body_w, body_h)
    good_areaid = rectangle(
        areaid_layer,
        body_w - overlap,
        areaid_y,
        good_spacing + 2 * overlap,
        areaid_h,
    )
    bad_areaid = rectangle(
        areaid_layer,
        body_w - overlap,
        areaid_y,
        bad_spacing + 2 * overlap,
        areaid_h,
    )
    illegal_poly = Polygon(
        layer=layer,
        points=((body_w + bad_spacing, y_shift), (body_w + bad_spacing + 40, y_shift + 30), (body_w + bad_spacing + body_w, y_shift + 30), (body_w + bad_spacing + body_w, y_shift + body_h), (body_w + bad_spacing, y_shift + body_h), (body_w + bad_spacing, y_shift)),
    )

    good = PatternCase(
        case_id=f"{layer}_across_areaid_spacing_good",
        intent="GOOD",
        description=f"across-boundary spacing {good_spacing}nm >= {min_spacing_nm}nm",
        polygons=(left, right_good, good_areaid),
    )
    bad = PatternCase(
        case_id=f"{layer}_across_areaid_spacing_bad",
        intent="BAD",
        description=f"across-boundary spacing {bad_spacing}nm < {min_spacing_nm}nm",
        polygons=(left, right_bad, bad_areaid),
    )
    illegal = PatternCase(
        case_id=f"{layer}_across_areaid_spacing_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge to simulate syntax/geometry illegal case",
        polygons=(left, bad_areaid, illegal_poly),
    )
    return [good, bad, illegal]


def generate_interacting_isolated_spacing_cases(
    *,
    inner_layer: str,
    carrier_layer: str,
    min_spacing_nm: int,
    delta_nm: int = 20,
) -> list[PatternCase]:
    if min_spacing_nm <= 0:
        raise ValueError("min_spacing_nm must be > 0")
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")

    inner_w = max(_layer_size_hint(inner_layer), 1000)
    inner_h = max(inner_w * 2, 2000)
    carrier_margin = max(180, _layer_size_hint(carrier_layer))
    carrier_w = inner_w + 2 * carrier_margin
    carrier_h = inner_h + 2 * carrier_margin
    good_spacing = min_spacing_nm + delta_nm
    bad_spacing = max(1, min_spacing_nm - delta_nm)

    left_carrier = rectangle(carrier_layer, 0, 0, carrier_w, carrier_h)
    left_inner = rectangle(
        inner_layer,
        carrier_margin,
        carrier_margin,
        inner_w,
        inner_h,
    )
    right_carrier_good = rectangle(
        carrier_layer,
        carrier_w + good_spacing,
        0,
        carrier_w,
        carrier_h,
    )
    right_inner_good = rectangle(
        inner_layer,
        carrier_w + good_spacing + carrier_margin,
        carrier_margin,
        inner_w,
        inner_h,
    )
    right_carrier_bad = rectangle(
        carrier_layer,
        carrier_w + bad_spacing,
        0,
        carrier_w,
        carrier_h,
    )
    right_inner_bad = rectangle(
        inner_layer,
        carrier_w + bad_spacing + carrier_margin,
        carrier_margin,
        inner_w,
        inner_h,
    )
    illegal_poly = Polygon(
        layer=carrier_layer,
        points=((carrier_w + bad_spacing, 0), (carrier_w + bad_spacing + 40, 30), (carrier_w + bad_spacing + carrier_w, 30), (carrier_w + bad_spacing + carrier_w, carrier_h), (carrier_w + bad_spacing, carrier_h), (carrier_w + bad_spacing, 0)),
    )

    good = PatternCase(
        case_id=f"{inner_layer}_{carrier_layer}_isolated_good",
        intent="GOOD",
        description=f"interacting {carrier_layer} spacing {good_spacing}nm >= {min_spacing_nm}nm",
        polygons=(left_carrier, left_inner, right_carrier_good, right_inner_good),
    )
    bad = PatternCase(
        case_id=f"{inner_layer}_{carrier_layer}_isolated_bad",
        intent="BAD",
        description=f"interacting {carrier_layer} spacing {bad_spacing}nm < {min_spacing_nm}nm",
        polygons=(left_carrier, left_inner, right_carrier_bad, right_inner_bad),
    )
    illegal = PatternCase(
        case_id=f"{inner_layer}_{carrier_layer}_isolated_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge to simulate syntax/geometry illegal case",
        polygons=(left_carrier, left_inner, illegal_poly),
    )
    return [good, bad, illegal]


def generate_sized_overlap_spacing_cases(
    *,
    outer_layer: str,
    overlap_layer: str,
    min_spacing_nm: int,
    delta_nm: int = 20,
    expand_nm: int = 140,
    separate_overlap: bool = False,
) -> list[PatternCase]:
    if min_spacing_nm <= 0:
        raise ValueError("min_spacing_nm must be > 0")
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")

    overlap_w = max(_layer_size_hint(overlap_layer) * 2, 600)
    overlap_h = max(overlap_w * 2, 1600)
    outer_margin = max(expand_nm + 80, 220)
    outer_w = overlap_w + 2 * outer_margin
    outer_h = overlap_h + 2 * outer_margin
    left_outer = rectangle(outer_layer, 0, 0, outer_w, outer_h)
    left_overlap_x = outer_margin
    left_overlap_y = outer_margin
    left_overlap = rectangle(overlap_layer, left_overlap_x, left_overlap_y, overlap_w, overlap_h)

    if separate_overlap:
        good_spacing = min_spacing_nm + delta_nm
        bad_spacing = max(1, min_spacing_nm - delta_nm)
        right_overlap_good = rectangle(
            overlap_layer,
            left_overlap_x + overlap_w + expand_nm + good_spacing,
            left_overlap_y,
            overlap_w,
            overlap_h,
        )
        right_overlap_bad = rectangle(
            overlap_layer,
            left_overlap_x + overlap_w + expand_nm + bad_spacing,
            left_overlap_y,
            overlap_w,
            overlap_h,
        )
        good_polys = (left_outer, left_overlap, right_overlap_good)
        bad_polys = (left_outer, left_overlap, right_overlap_bad)
    else:
        good_overlap_gap = min_spacing_nm + 2 * expand_nm + delta_nm
        bad_overlap_gap = max(1, min_spacing_nm + 2 * expand_nm - delta_nm)
        right_overlap_good_x = left_overlap_x + overlap_w + good_overlap_gap
        right_overlap_bad_x = left_overlap_x + overlap_w + bad_overlap_gap
        right_overlap_good = rectangle(
            overlap_layer,
            right_overlap_good_x,
            left_overlap_y,
            overlap_w,
            overlap_h,
        )
        right_overlap_bad = rectangle(
            overlap_layer,
            right_overlap_bad_x,
            left_overlap_y,
            overlap_w,
            overlap_h,
        )
        right_outer_good = rectangle(
            outer_layer,
            right_overlap_good_x - outer_margin,
            0,
            outer_w,
            outer_h,
        )
        right_outer_bad = rectangle(
            outer_layer,
            right_overlap_bad_x - outer_margin,
            0,
            outer_w,
            outer_h,
        )
        good_polys = (left_outer, left_overlap, right_outer_good, right_overlap_good)
        bad_polys = (left_outer, left_overlap, right_outer_bad, right_overlap_bad)

    illegal_poly = Polygon(
        layer=overlap_layer,
        points=((left_overlap_x + overlap_w + expand_nm, 0), (left_overlap_x + overlap_w + expand_nm + 40, 30), (left_overlap_x + overlap_w + expand_nm + overlap_w, 30), (left_overlap_x + overlap_w + expand_nm + overlap_w, overlap_h), (left_overlap_x + overlap_w + expand_nm, overlap_h), (left_overlap_x + overlap_w + expand_nm, 0)),
    )

    good = PatternCase(
        case_id=f"{outer_layer}_{overlap_layer}_plate_spacing_good",
        intent="GOOD",
        description=f"bot-plate spacing >= {min_spacing_nm}nm",
        polygons=good_polys,
    )
    bad = PatternCase(
        case_id=f"{outer_layer}_{overlap_layer}_plate_spacing_bad",
        intent="BAD",
        description=f"bot-plate spacing < {min_spacing_nm}nm",
        polygons=bad_polys,
    )
    illegal = PatternCase(
        case_id=f"{outer_layer}_{overlap_layer}_plate_spacing_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge to simulate syntax/geometry illegal case",
        polygons=(left_outer, left_overlap, illegal_poly),
    )
    return [good, bad, illegal]


def generate_huge_spacing_cases(
    *,
    layer: str,
    min_spacing_nm: int,
    delta_nm: int = 20,
) -> list[PatternCase]:
    if min_spacing_nm <= 0:
        raise ValueError("min_spacing_nm must be > 0")
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")

    huge_w = max(3200, _layer_size_hint(layer) * 8)
    huge_h = max(4000, huge_w)
    small_w = max(_layer_size_hint(layer), 240)
    small_h = huge_h
    good_spacing = min_spacing_nm + delta_nm
    bad_spacing = max(1, min_spacing_nm - delta_nm)

    huge = rectangle(layer, 0, 0, huge_w, huge_h)
    small_good = rectangle(layer, huge_w + good_spacing, 0, small_w, small_h)
    small_bad = rectangle(layer, huge_w + bad_spacing, 0, small_w, small_h)
    illegal_poly = Polygon(
        layer=layer,
        points=((huge_w + bad_spacing, 0), (huge_w + bad_spacing + 80, 40), (huge_w + bad_spacing + small_w, 40), (huge_w + bad_spacing + small_w, small_h), (huge_w + bad_spacing, small_h), (huge_w + bad_spacing, 0)),
    )

    good = PatternCase(
        case_id=f"{layer}_huge_spacing_good",
        intent="GOOD",
        description=f"huge/non-huge spacing {good_spacing}nm >= {min_spacing_nm}nm",
        polygons=(huge, small_good),
    )
    bad = PatternCase(
        case_id=f"{layer}_huge_spacing_bad",
        intent="BAD",
        description=f"huge/non-huge spacing {bad_spacing}nm < {min_spacing_nm}nm",
        polygons=(huge, small_bad),
    )
    illegal = PatternCase(
        case_id=f"{layer}_huge_spacing_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge to simulate syntax/geometry illegal case",
        polygons=(huge, illegal_poly),
    )
    return [good, bad, illegal]


def generate_min_density_cases(
    *,
    layer: str,
    min_density_bps: int,
    delta_bps: int = 500,
    window_w_nm: int = 1000,
    window_h_nm: int = 1000,
) -> list[PatternCase]:
    """
    min_density_bps: threshold in basis points (10000 = 100%)
    """
    if not (0 < min_density_bps < 10000):
        raise ValueError("min_density_bps must be in (0, 10000)")
    if delta_bps <= 0:
        raise ValueError("delta_bps must be > 0")

    area = window_w_nm * window_h_nm
    good_bps = min(9900, min_density_bps + delta_bps)
    bad_bps = max(100, min_density_bps - delta_bps)

    good_fill_area = int(round(area * good_bps / 10000))
    bad_fill_area = int(round(area * bad_bps / 10000))

    good_fill = rectangle(layer, 0, 0, window_w_nm, max(1, good_fill_area // window_w_nm))
    bad_fill = rectangle(layer, 0, 0, window_w_nm, max(1, bad_fill_area // window_w_nm))
    illegal_fill = Polygon(
        layer=layer,
        points=((0, 0), (window_w_nm, 120), (window_w_nm, 300), (0, 300), (0, 0)),
    )

    good = PatternCase(
        case_id=f"{layer}_density_good",
        intent="GOOD",
        description=f"density {good_bps/100:.2f}% >= min_density {min_density_bps/100:.2f}%",
        polygons=(good_fill,),
    )
    bad = PatternCase(
        case_id=f"{layer}_density_bad",
        intent="BAD",
        description=f"density {bad_bps/100:.2f}% < min_density {min_density_bps/100:.2f}%",
        polygons=(bad_fill,),
    )
    illegal = PatternCase(
        case_id=f"{layer}_density_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge to simulate illegal geometry",
        polygons=(illegal_fill,),
    )
    return [good, bad, illegal]


def generate_min_area_cases(
    *,
    layer: str,
    min_area_nm2: int,
    delta_percent: int = 20,
) -> list[PatternCase]:
    if min_area_nm2 <= 0:
        raise ValueError("min_area_nm2 must be > 0")
    if delta_percent <= 0:
        raise ValueError("delta_percent must be > 0")

    good_area = int(round(min_area_nm2 * (100 + delta_percent) / 100))
    bad_area = max(1, int(round(min_area_nm2 * (100 - delta_percent) / 100)))

    min_side = _layer_size_hint(layer)

    def dims_for_area(area_nm2: int) -> tuple[int, int]:
        width = max(1, min_side, int(round(area_nm2 ** 0.5)))
        height = max(1, (area_nm2 + width - 1) // width)
        return width, height

    good_w, good_h = dims_for_area(good_area)
    bad_w, bad_h = dims_for_area(bad_area)

    good = PatternCase(
        case_id=f"{layer}_area_good",
        intent="GOOD",
        description=f"area {good_w * good_h}nm^2 >= min_area {min_area_nm2}nm^2",
        polygons=(rectangle(layer, 0, 0, good_w, good_h),),
    )
    bad = PatternCase(
        case_id=f"{layer}_area_bad",
        intent="BAD",
        description=f"area {bad_w * bad_h}nm^2 < min_area {min_area_nm2}nm^2",
        polygons=(rectangle(layer, 0, 0, bad_w, bad_h),),
    )
    illegal_poly = Polygon(
        layer=layer,
        points=((0, 0), (good_w, 20), (good_w, good_h), (0, good_h), (0, 0)),
    )
    illegal = PatternCase(
        case_id=f"{layer}_area_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge to simulate illegal geometry",
        polygons=(illegal_poly,),
    )
    return [good, bad, illegal]


def generate_hole_area_cases(
    *,
    layer: str,
    min_area_nm2: int,
    delta_percent: int = 20,
) -> list[PatternCase]:
    if min_area_nm2 <= 0:
        raise ValueError("min_area_nm2 must be > 0")
    if delta_percent <= 0:
        raise ValueError("delta_percent must be > 0")

    good_area = int(round(min_area_nm2 * (100 + delta_percent) / 100))
    bad_area = max(1, int(round(min_area_nm2 * (100 - delta_percent) / 100)))
    ring_w = max(80, _layer_size_hint(layer))

    def ring_for_area(area_nm2: int) -> tuple[Polygon, ...]:
        hole_side = max(1, int(round(area_nm2 ** 0.5)))
        outer = hole_side + 2 * ring_w
        return _ring_polygons(layer, 0, 0, outer, outer, ring_w)

    good_polys = ring_for_area(good_area)
    bad_polys = ring_for_area(bad_area)
    outer = max(_bbox(poly)[2] for poly in good_polys)
    illegal_poly = Polygon(
        layer=layer,
        points=((0, 0), (outer, 20), (outer, ring_w), (0, ring_w), (0, 0)),
    )

    good = PatternCase(
        case_id=f"{layer}_hole_area_good",
        intent="GOOD",
        description=f"hole area > min_area {min_area_nm2}nm^2",
        polygons=good_polys,
    )
    bad = PatternCase(
        case_id=f"{layer}_hole_area_bad",
        intent="BAD",
        description=f"hole area < min_area {min_area_nm2}nm^2",
        polygons=bad_polys,
    )
    illegal = PatternCase(
        case_id=f"{layer}_hole_area_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge to simulate illegal geometry",
        polygons=(illegal_poly,),
    )
    return [good, bad, illegal]


def _outer_rect_with_side_margins(
    *,
    layer: str,
    inner_x: int,
    inner_y: int,
    inner_w: int,
    inner_h: int,
    left_nm: int,
    right_nm: int,
    bottom_nm: int,
    top_nm: int,
) -> Polygon:
    return rectangle(
        layer,
        inner_x - left_nm,
        inner_y - bottom_nm,
        inner_w + left_nm + right_nm,
        inner_h + bottom_nm + top_nm,
    )


def generate_density_window_cases(
    *,
    layer: str,
    min_density_bps: int,
    delta_bps: int = 500,
    window_w_nm: int = 2000,
    window_h_nm: int = 2000,
) -> list[PatternCase]:
    """
    More realistic density style: fixed analysis window (implicit).
    """
    if not (0 < min_density_bps < 10000):
        raise ValueError("min_density_bps must be in (0, 10000)")
    if delta_bps <= 0:
        raise ValueError("delta_bps must be > 0")

    area = window_w_nm * window_h_nm
    good_bps = min(9900, min_density_bps + delta_bps)
    bad_bps = max(100, min_density_bps - delta_bps)

    good_fill_area = int(round(area * good_bps / 10000))
    bad_fill_area = int(round(area * bad_bps / 10000))

    good_fill = rectangle(layer, 0, 0, window_w_nm, max(1, good_fill_area // window_w_nm))
    bad_fill = rectangle(layer, 0, 0, window_w_nm, max(1, bad_fill_area // window_w_nm))
    illegal_fill = Polygon(
        layer=layer,
        points=((0, 0), (window_w_nm, 120), (window_w_nm, 700), (0, 700), (0, 0)),
    )

    good = PatternCase(
        case_id=f"{layer}_density_window_good",
        intent="GOOD",
        description=(
            f"window density {good_bps/100:.2f}% >= min_density {min_density_bps/100:.2f}%"
        ),
        polygons=(good_fill,),
    )
    bad = PatternCase(
        case_id=f"{layer}_density_window_bad",
        intent="BAD",
        description=(
            f"window density {bad_bps/100:.2f}% < min_density {min_density_bps/100:.2f}%"
        ),
        polygons=(bad_fill,),
    )
    illegal = PatternCase(
        case_id=f"{layer}_density_window_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge to simulate illegal geometry",
        polygons=(illegal_fill,),
    )
    return [good, bad, illegal]


def generate_poly_endcap_cases(
    *,
    endcap_nm: int,
    delta_nm: int = 20,
) -> list[PatternCase]:
    if endcap_nm <= 0:
        raise ValueError("endcap_nm must be > 0")
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")

    diff = rectangle("diff", 120, 200, 560, 200)
    gate_w = 40
    good_ext = endcap_nm + delta_nm
    bad_ext = max(1, endcap_nm - delta_nm)

    good_poly = rectangle("poly", 380, 200 - good_ext, gate_w, 200 + 2 * good_ext)
    bad_poly = rectangle("poly", 380, 200 - bad_ext, gate_w, 200 + 2 * bad_ext)
    illegal_poly = Polygon(
        layer="poly",
        points=((380, 120), (420, 140), (420, 480), (380, 480), (380, 120)),
    )

    good = PatternCase(
        case_id="poly_endcap_good",
        intent="GOOD",
        description=f"poly extension {good_ext}nm >= endcap {endcap_nm}nm",
        polygons=(diff, good_poly),
    )
    bad = PatternCase(
        case_id="poly_endcap_bad",
        intent="BAD",
        description=f"poly extension {bad_ext}nm < endcap {endcap_nm}nm",
        polygons=(diff, bad_poly),
    )
    illegal = PatternCase(
        case_id="poly_endcap_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan poly edge",
        polygons=(diff, illegal_poly),
    )
    return [good, bad, illegal]


def generate_via_enclosure_cases(
    *,
    metal_layer: str,
    via_layer: str = "via",
    enclosure_nm: int,
    delta_nm: int = 20,
    via_size_nm: int | None = None,
    ring_inner: bool = False,
    cover_only: bool = False,
    adjacent_edge_mode: bool = False,
) -> list[PatternCase]:
    """
    Two-layer coupling example: via square must be enclosed by metal.
    """
    if enclosure_nm <= 0:
        raise ValueError("enclosure_nm must be > 0")
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")

    if via_size_nm is None:
        via_size_nm = _layer_size_hint(via_layer)

    if ring_inner:
        ring_outer = max(via_size_nm * 5, 600)
        ring_width = max(40, min(via_size_nm, ring_outer // 4))
        via_polys = _ring_polygons(via_layer, 300, 300, ring_outer, ring_outer, ring_width)
        inner_x = 300
        inner_y = 300
        inner_w = ring_outer
        inner_h = ring_outer
    else:
        via_polys = (rectangle(via_layer, 300, 300, via_size_nm, via_size_nm),)
        inner_x = 300
        inner_y = 300
        inner_w = via_size_nm
        inner_h = via_size_nm

    if cover_only:
        good_met = rectangle(
            metal_layer,
            inner_x - 40,
            inner_y - 40,
            inner_w + 80,
            inner_h + 80,
        )
        bad_met = rectangle(
            metal_layer,
            inner_x + inner_w // 2,
            inner_y,
            max(10, inner_w // 2),
            inner_h,
        )
        good_desc = f"{metal_layer} fully covers {via_layer}"
        bad_desc = f"{metal_layer} does not fully cover {via_layer}"
    else:
        good_enc = enclosure_nm + delta_nm
        bad_enc = max(1, enclosure_nm - delta_nm)
        min_metal = _layer_size_hint(metal_layer)
        good_right = good_enc + max(0, min_metal - (inner_w + 2 * good_enc))
        good_top = good_enc + max(0, min_metal - (inner_h + 2 * good_enc))
        good_met = _outer_rect_with_side_margins(
            layer=metal_layer,
            inner_x=inner_x,
            inner_y=inner_y,
            inner_w=inner_w,
            inner_h=inner_h,
            left_nm=good_enc,
            right_nm=good_right,
            bottom_nm=good_enc,
            top_nm=good_top,
        )
        bad_right = good_enc
        bad_top = good_enc
        if adjacent_edge_mode:
            bad_right += max(0, min_metal - (inner_w + bad_enc + bad_right))
            bad_top += max(0, min_metal - (inner_h + bad_enc + bad_top))
        bad_met = _outer_rect_with_side_margins(
            layer=metal_layer,
            inner_x=inner_x,
            inner_y=inner_y,
            inner_w=inner_w,
            inner_h=inner_h,
            left_nm=bad_enc,
            right_nm=bad_right,
            bottom_nm=bad_enc,
            top_nm=bad_top,
        )
        good_desc = f"{metal_layer} enclosure {good_enc}nm >= {enclosure_nm}nm"
        if adjacent_edge_mode:
            bad_desc = f"{metal_layer} enclosure on 2 adjacent edges {bad_enc}nm < {enclosure_nm}nm"
        else:
            bad_desc = f"{metal_layer} enclosure {bad_enc}nm < {enclosure_nm}nm"
    illegal_met = Polygon(
        layer=metal_layer,
        points=((260, 260), (480, 290), (480, 480), (260, 480), (260, 260)),
    )

    good = PatternCase(
        case_id=f"{metal_layer}_via_enclosure_good",
        intent="GOOD",
        description=good_desc,
        polygons=via_polys + (good_met,),
    )
    bad = PatternCase(
        case_id=f"{metal_layer}_via_enclosure_bad",
        intent="BAD",
        description=bad_desc,
        polygons=via_polys + (bad_met,),
    )
    illegal = PatternCase(
        case_id=f"{metal_layer}_via_enclosure_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan metal edge",
        polygons=via_polys + (illegal_met,),
    )
    return [good, bad, illegal]


def generate_min_enclosure_cases(
    *,
    inner_layer: str,
    outer_layer: str,
    enclosure_nm: int,
    delta_nm: int = 20,
    inner_size_nm: int = 120,
    ring_inner: bool = False,
    cover_only: bool = False,
    hole_inner: bool = False,
) -> list[PatternCase]:
    if enclosure_nm <= 0:
        raise ValueError("enclosure_nm must be > 0")
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")

    inner_size_nm = max(inner_size_nm, _layer_size_hint(inner_layer))

    if ring_inner:
        ring_outer = max(inner_size_nm * 5, 600)
        ring_width = max(40, min(inner_size_nm, ring_outer // 4))
        inner_polys = _ring_polygons(
            inner_layer, 300, 300, ring_outer, ring_outer, ring_width
        )
        if hole_inner:
            inner_x = 300 + ring_width
            inner_y = 300 + ring_width
            inner_w = ring_outer - 2 * ring_width
            inner_h = ring_outer - 2 * ring_width
        else:
            inner_x = 300
            inner_y = 300
            inner_w = ring_outer
            inner_h = ring_outer
    else:
        inner_polys = (rectangle(inner_layer, 300, 300, inner_size_nm, inner_size_nm),)
        inner_x = 300
        inner_y = 300
        inner_w = inner_size_nm
        inner_h = inner_size_nm

    if cover_only:
        good_outer = rectangle(
            outer_layer,
            inner_x - 40,
            inner_y - 40,
            inner_w + 80,
            inner_h + 80,
        )
        bad_outer = rectangle(
            outer_layer,
            inner_x + inner_w // 2,
            inner_y,
            max(10, inner_w // 2),
            inner_h,
        )
        good_desc = f"{outer_layer} fully covers {inner_layer}"
        bad_desc = f"{outer_layer} does not fully cover {inner_layer}"
    else:
        good_enc = enclosure_nm + delta_nm
        bad_enc = max(1, enclosure_nm - delta_nm)
        min_outer = _layer_size_hint(outer_layer)
        good_right = good_enc + max(0, min_outer - (inner_w + 2 * good_enc))
        good_top = good_enc + max(0, min_outer - (inner_h + 2 * good_enc))
        good_outer = _outer_rect_with_side_margins(
            layer=outer_layer,
            inner_x=inner_x,
            inner_y=inner_y,
            inner_w=inner_w,
            inner_h=inner_h,
            left_nm=good_enc,
            right_nm=good_right,
            bottom_nm=good_enc,
            top_nm=good_top,
        )
        bad_outer = _outer_rect_with_side_margins(
            layer=outer_layer,
            inner_x=inner_x,
            inner_y=inner_y,
            inner_w=inner_w,
            inner_h=inner_h,
            left_nm=bad_enc,
            right_nm=good_enc + max(0, min_outer - (inner_w + bad_enc + good_enc)),
            bottom_nm=bad_enc,
            top_nm=good_enc + max(0, min_outer - (inner_h + bad_enc + good_enc)),
        )
        good_desc = (
            f"{outer_layer} enclosure of {inner_layer} {good_enc}nm >= {enclosure_nm}nm"
        )
        bad_desc = (
            f"{outer_layer} enclosure of {inner_layer} {bad_enc}nm < {enclosure_nm}nm"
        )
    illegal_outer = Polygon(
        layer=outer_layer,
        points=((260, 260), (480, 290), (480, 480), (260, 480), (260, 260)),
    )

    good = PatternCase(
        case_id=f"{outer_layer}_{inner_layer}_enclosure_good",
        intent="GOOD",
        description=good_desc,
        polygons=inner_polys + (good_outer,),
    )
    bad = PatternCase(
        case_id=f"{outer_layer}_{inner_layer}_enclosure_bad",
        intent="BAD",
        description=bad_desc,
        polygons=inner_polys + (bad_outer,),
    )
    illegal = PatternCase(
        case_id=f"{outer_layer}_{inner_layer}_enclosure_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan enclosing edge",
        polygons=inner_polys + (illegal_outer,),
    )
    return [good, bad, illegal]


def generate_offgrid_vertex_cases(
    *,
    layer: str,
    grid_nm: int = 5,
) -> list[PatternCase]:
    if grid_nm <= 0:
        raise ValueError("grid_nm must be > 0")

    size = 200
    good = PatternCase(
        case_id=f"{layer}_offgrid_good",
        intent="GOOD",
        description=f"all vertices aligned to {grid_nm}nm grid",
        polygons=(rectangle(layer, 0, 0, size, size),),
    )
    bad = PatternCase(
        case_id=f"{layer}_offgrid_bad",
        intent="BAD",
        description=f"contains vertices off {grid_nm}nm grid",
        polygons=(rectangle(layer, 1, 1, size, size),),
    )
    illegal = PatternCase(
        case_id=f"{layer}_offgrid_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge",
        polygons=(
            Polygon(
                layer=layer,
                points=((1, 1), (size + 1, 21), (size + 1, size + 1), (1, size + 1), (1, 1)),
            ),
        ),
    )
    return [good, bad, illegal]


def _diamond(layer: str, cx: int = 200, cy: int = 200, r: int = 100) -> Polygon:
    return Polygon(
        layer=layer,
        points=((cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy), (cx, cy - r)),
    )


def _non_45_polygon(layer: str) -> Polygon:
    # Includes an acute corner (~34 deg), so it violates both 90-only
    # and 45-multiple angle constraints.
    return Polygon(
        layer=layer,
        points=((100, 100), (300, 100), (600, 110), (300, 300), (100, 300), (100, 100)),
    )


def generate_forbidden_angle_cases(
    *,
    layer: str,
    allowed_angle_deg: int = 90,
) -> list[PatternCase]:
    if allowed_angle_deg not in {45, 90}:
        raise ValueError("allowed_angle_deg must be 45 or 90")

    rect = rectangle(layer, 100, 100, 200, 200)
    diamond = _diamond(layer)
    non_45 = _non_45_polygon(layer)

    if allowed_angle_deg == 90:
        good_poly = rect
        bad_poly = non_45
        good_desc = "only 90-degree angles"
        bad_desc = "contains non-90-degree angles"
    else:
        good_poly = diamond
        bad_poly = non_45
        good_desc = "only 45-degree angles"
        bad_desc = "contains non-45-multiple angles"

    illegal_poly = Polygon(
        layer=layer,
        points=((100, 100), (220, 160), (300, 300), (100, 300)),
    )

    good = PatternCase(
        case_id=f"{layer}_angle_good",
        intent="GOOD",
        description=good_desc,
        polygons=(good_poly,),
        allow_non_manhattan=True,
    )
    bad = PatternCase(
        case_id=f"{layer}_angle_bad",
        intent="BAD",
        description=bad_desc,
        polygons=(bad_poly,),
        allow_non_manhattan=True,
    )
    illegal = PatternCase(
        case_id=f"{layer}_angle_illegal",
        intent="ILLEGAL",
        description="open polygon (illegal syntax)",
        polygons=(illegal_poly,),
        allow_non_manhattan=True,
    )
    return [good, bad, illegal]


def generate_forbidden_overlap_cases(
    *,
    layer_a: str,
    layer_b: str,
    delta_nm: int = 40,
) -> list[PatternCase]:
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")

    base = 200
    good_a = rectangle(layer_a, 0, 0, base, base)
    good_b = rectangle(layer_b, base + delta_nm, 0, base, base)

    bad_a = rectangle(layer_a, 0, 0, base, base)
    bad_b = rectangle(layer_b, base // 2, 0, base, base)

    illegal_b = Polygon(
        layer=layer_b,
        points=((base // 2, 0), (base + 30, 20), (base + 30, base), (base // 2, base), (base // 2, 0)),
    )

    good = PatternCase(
        case_id=f"{layer_a}_{layer_b}_overlap_good",
        intent="GOOD",
        description=f"{layer_a} and {layer_b} do not overlap",
        polygons=(good_a, good_b),
    )
    bad = PatternCase(
        case_id=f"{layer_a}_{layer_b}_overlap_bad",
        intent="BAD",
        description=f"{layer_a} overlaps {layer_b}",
        polygons=(bad_a, bad_b),
    )
    illegal = PatternCase(
        case_id=f"{layer_a}_{layer_b}_overlap_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge",
        polygons=(bad_a, illegal_b),
    )
    return [good, bad, illegal]


def _interact_layers_from_rule_text(*, rule_text: str | None, fallback_layer: str) -> list[str]:
    layers: list[str] = []

    def _push(layer: str) -> None:
        low = layer.lower()
        if low not in layers:
            layers.append(low)

    if rule_text:
        low = rule_text.lower()
        for key in ("mcon", "licon", "via4", "via3", "via2"):
            if key in low:
                _push(key)
        if "via1" in low or re.search(r"\bvia\b", low):
            _push("via")

    fallback = fallback_layer.lower()
    if not layers:
        _push(fallback)
    elif fallback in {"mcon", "licon", "via", "via2", "via3", "via4"}:
        _push(fallback)
    return layers


def generate_must_interact_cases(
    *,
    layer_a: str,
    layer_b: str,
    delta_nm: int = 40,
    rule_text: str | None = None,
) -> list[PatternCase]:
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")

    base = 200
    interact_layers = _interact_layers_from_rule_text(
        rule_text=rule_text,
        fallback_layer=layer_b,
    )
    interact_layers = [layer for layer in interact_layers if layer != layer_a.lower()]
    if not interact_layers:
        interact_layers = [layer_b.lower()]

    # GOOD: interacting geometry on one or more contact layers.
    good_a = rectangle(layer_a, 0, 0, base, base)
    good_contacts = tuple(rectangle(layer, 0, 0, base, base) for layer in interact_layers)

    # BAD: all contact layers are intentionally separated.
    bad_a = rectangle(layer_a, 0, 0, base, base)
    bad_contacts = tuple(
        rectangle(layer, (idx + 1) * (base + delta_nm), 0, base, base)
        for idx, layer in enumerate(interact_layers)
    )
    contact_desc = " or ".join(interact_layers)

    illegal_b = Polygon(
        layer=interact_layers[0],
        points=(
            (base + delta_nm, 0),
            (base + delta_nm + 30, 20),
            (base + delta_nm + 30, base),
            (base + delta_nm, base),
            (base + delta_nm, 0),
        ),
    )

    good = PatternCase(
        case_id=f"{layer_a}_{layer_b}_interact_good",
        intent="GOOD",
        description=f"{layer_a} interacts with {contact_desc}",
        polygons=(good_a,) + good_contacts,
    )
    bad = PatternCase(
        case_id=f"{layer_a}_{layer_b}_interact_bad",
        intent="BAD",
        description=f"{layer_a} does not interact with {contact_desc}",
        polygons=(bad_a,) + bad_contacts,
    )
    illegal = PatternCase(
        case_id=f"{layer_a}_{layer_b}_interact_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge",
        polygons=(bad_a, illegal_b) + bad_contacts[1:],
    )
    return [good, bad, illegal]


def generate_forbidden_use_cases(*, layer: str) -> list[PatternCase]:
    good = PatternCase(
        case_id=f"{layer}_forbidden_use_good",
        intent="GOOD",
        description=f"{layer} not used",
        polygons=(),
    )
    bad = PatternCase(
        case_id=f"{layer}_forbidden_use_bad",
        intent="BAD",
        description=f"{layer} used",
        polygons=(rectangle(layer, 0, 0, 200, 200),),
    )
    illegal = PatternCase(
        case_id=f"{layer}_forbidden_use_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge",
        polygons=(
            Polygon(
                layer=layer,
                points=((0, 0), (200, 20), (200, 200), (0, 200), (0, 0)),
            ),
        ),
    )
    return [good, bad, illegal]


def generate_max_length_cases(
    *,
    layer: str,
    max_length_nm: int,
    delta_nm: int = 40,
    rule_text: str | None = None,
) -> list[PatternCase]:
    if max_length_nm <= 0:
        raise ValueError("max_length_nm must be > 0")
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")

    exact_mode = _is_min_max_length_rule(rule_text)
    if exact_mode:
        # For runset checks like `length != 0.17`, both rectangle dimensions
        # are constrained by the nominal value.
        width = max_length_nm
        good_len = max_length_nm
    else:
        width = max(60, max_length_nm // 3)
        good_len = max(1, max_length_nm - delta_nm)
    bad_len = max_length_nm + delta_nm

    good = PatternCase(
        case_id=f"{layer}_maxlen_good",
        intent="GOOD",
        description=(
            f"length {good_len}nm == target_length {max_length_nm}nm"
            if exact_mode
            else f"length {good_len}nm <= max_length {max_length_nm}nm"
        ),
        polygons=(rectangle(layer, 0, 0, good_len, width),),
    )
    bad = PatternCase(
        case_id=f"{layer}_maxlen_bad",
        intent="BAD",
        description=f"length {bad_len}nm > max_length {max_length_nm}nm",
        polygons=(rectangle(layer, 0, 0, bad_len, width),),
    )
    illegal = PatternCase(
        case_id=f"{layer}_maxlen_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge",
        polygons=(
            Polygon(
                layer=layer,
                points=((0, 0), (bad_len, 20), (bad_len, width), (0, width), (0, 0)),
            ),
        ),
    )
    return [good, bad, illegal]


def generate_max_width_cases(
    *,
    layer: str,
    max_width_nm: int,
    delta_nm: int = 20,
    ring_mode: bool = False,
) -> list[PatternCase]:
    if max_width_nm <= 0:
        raise ValueError("max_width_nm must be > 0")
    if delta_nm <= 0:
        raise ValueError("delta_nm must be > 0")

    good_w = max(1, max_width_nm - delta_nm)
    bad_w = max_width_nm + delta_nm

    if ring_mode:
        ring_span = max(8 * bad_w, 2 * bad_w + 40)
        good_polys = _ring_polygons(layer, 0, 0, ring_span, ring_span, good_w)
        bad_polys = _ring_polygons(layer, 0, 0, ring_span, ring_span, bad_w)
        illegal_poly = Polygon(
            layer=layer,
            points=((0, 0), (ring_span, 20), (ring_span, 80), (0, 80), (0, 0)),
        )
        good = PatternCase(
            case_id=f"{layer}_ring_maxwidth_good",
            intent="GOOD",
            description=f"ring width {good_w}nm <= max_width {max_width_nm}nm",
            polygons=good_polys,
        )
        bad = PatternCase(
            case_id=f"{layer}_ring_maxwidth_bad",
            intent="BAD",
            description=f"ring width {bad_w}nm > max_width {max_width_nm}nm",
            polygons=bad_polys,
        )
        illegal = PatternCase(
            case_id=f"{layer}_ring_maxwidth_illegal",
            intent="ILLEGAL",
            description="contains non-manhattan edge",
            polygons=(illegal_poly,),
        )
        return [good, bad, illegal]

    run_len = max(400, bad_w + 40)
    good = PatternCase(
        case_id=f"{layer}_maxwidth_good",
        intent="GOOD",
        description=f"width {good_w}nm <= max_width {max_width_nm}nm",
        polygons=(rectangle(layer, 0, 0, run_len, good_w),),
    )
    bad = PatternCase(
        case_id=f"{layer}_maxwidth_bad",
        intent="BAD",
        description=f"width {bad_w}nm > max_width {max_width_nm}nm",
        polygons=(rectangle(layer, 0, 0, run_len, bad_w),),
    )
    illegal = PatternCase(
        case_id=f"{layer}_maxwidth_illegal",
        intent="ILLEGAL",
        description="contains non-manhattan edge",
        polygons=(
            Polygon(
                layer=layer,
                points=((0, 0), (run_len, 20), (run_len, bad_w), (0, bad_w), (0, 0)),
            ),
        ),
    )
    return [good, bad, illegal]


def generate_cases_for_rule(
    *,
    rule_type: str,
    layer: str,
    threshold_nm: int,
    delta_nm: int = 20,
    layer_b: str | None = None,
    rule_text: str | None = None,
) -> list[PatternCase]:
    ring_mode = _is_ring_rule(rule_text)
    cover_only_mode = _is_cover_only_rule(rule_text)
    if rule_type == "min_width":
        if _is_across_boundary_width_rule(rule_text):
            return generate_across_boundary_min_width_cases(
                layer=layer,
                min_width_nm=threshold_nm,
                delta_nm=delta_nm,
            )
        return generate_min_width_cases(
            layer=layer, min_width_nm=threshold_nm, delta_nm=delta_nm, ring_mode=ring_mode
        )
    if rule_type == "min_spacing":
        low = (rule_text or "").lower()
        if _is_huge_spacing_rule(rule_text):
            return generate_huge_spacing_cases(
                layer=layer,
                min_spacing_nm=threshold_nm,
                delta_nm=delta_nm,
            )
        if _is_across_boundary_spacing_rule(rule_text):
            return generate_across_boundary_spacing_cases(
                layer=layer,
                min_spacing_nm=threshold_nm,
                delta_nm=delta_nm,
            )
        if "m3_bot_plate" in low:
            return generate_sized_overlap_spacing_cases(
                outer_layer=layer,
                overlap_layer="m3",
                min_spacing_nm=threshold_nm,
                delta_nm=delta_nm,
                separate_overlap=(".separation(" in low or "not_interacting(m3_bot_plate)" in low),
            )
        if ".isolated(" in low and "interacting(cap2m)" in low:
            return generate_interacting_isolated_spacing_cases(
                inner_layer="cap2m",
                carrier_layer="m4",
                min_spacing_nm=threshold_nm,
                delta_nm=delta_nm,
            )
        spacing_partner = _extract_spacing_partner_layer(
            rule_text=rule_text,
            primary_layer=layer,
        )
        if spacing_partner is not None:
            return generate_cross_layer_spacing_cases(
                layer=layer,
                other_layer=spacing_partner,
                min_spacing_nm=threshold_nm,
                delta_nm=delta_nm,
            )
        return generate_min_spacing_cases(
            layer=layer, min_spacing_nm=threshold_nm, delta_nm=delta_nm
        )
    if rule_type == "min_density":
        return generate_min_density_cases(
            layer=layer, min_density_bps=threshold_nm, delta_bps=delta_nm * 10
        )
    if rule_type == "min_area":
        if _is_hole_area_rule(rule_text):
            return generate_hole_area_cases(
                layer=layer,
                min_area_nm2=threshold_nm,
                delta_percent=max(10, min(50, delta_nm)),
            )
        return generate_min_area_cases(
            layer=layer,
            min_area_nm2=threshold_nm,
            delta_percent=max(10, min(50, delta_nm)),
        )
    if rule_type == "density_window":
        return generate_density_window_cases(
            layer=layer, min_density_bps=threshold_nm, delta_bps=delta_nm * 10
        )
    if rule_type == "poly_endcap":
        return generate_poly_endcap_cases(endcap_nm=threshold_nm, delta_nm=delta_nm)
    if rule_type == "via_enclosure":
        return generate_via_enclosure_cases(
            metal_layer=layer,
            via_layer=layer_b or "via",
            enclosure_nm=threshold_nm,
            delta_nm=delta_nm,
            via_size_nm=_extract_via_size_nm(rule_text=rule_text, via_layer=layer_b or "via"),
            ring_inner=ring_mode,
            cover_only=cover_only_mode,
            adjacent_edge_mode=_has_adjacent_edge_enclosure(rule_text),
        )
    if rule_type == "min_enclosure":
        return generate_min_enclosure_cases(
            inner_layer=layer_b or "nwell",
            outer_layer=layer,
            enclosure_nm=threshold_nm,
            delta_nm=delta_nm,
            ring_inner=ring_mode,
            cover_only=cover_only_mode,
            hole_inner=_is_hole_enclosure_rule(rule_text),
        )
    if rule_type == "forbidden_overlap":
        return generate_forbidden_overlap_cases(
            layer_a=layer,
            layer_b=layer_b or ("nwell" if layer != "nwell" else "diff"),
            delta_nm=delta_nm,
        )
    if rule_type == "must_interact":
        return generate_must_interact_cases(
            layer_a=layer,
            layer_b=layer_b or "via",
            delta_nm=delta_nm,
            rule_text=rule_text,
        )
    if rule_type == "forbidden_use":
        return generate_forbidden_use_cases(layer=layer)
    if rule_type == "max_length":
        return generate_max_length_cases(
            layer=layer,
            max_length_nm=threshold_nm,
            delta_nm=delta_nm,
            rule_text=rule_text,
        )
    if rule_type == "max_width":
        return generate_max_width_cases(
            layer=layer,
            max_width_nm=threshold_nm,
            delta_nm=delta_nm,
            ring_mode=ring_mode,
        )
    if rule_type == "offgrid_vertex":
        return generate_offgrid_vertex_cases(layer=layer)
    if rule_type == "forbidden_angle":
        return generate_forbidden_angle_cases(
            layer=layer,
            allowed_angle_deg=threshold_nm if threshold_nm in {45, 90} else 90,
        )
    raise ValueError(f"Unsupported rule_type: {rule_type}")


def write_cases(cases: Iterable[PatternCase], out_dir: Path, prefix: str = "seed") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for idx, case in enumerate(cases):
        path = out_dir / f"{prefix}_{idx:02d}_{case.case_id}.json"
        path.write_text(json.dumps(case.to_dict(), indent=2), encoding="utf-8")
        paths.append(path)
    return paths
