from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re

from autodrc.casegen import PatternCase, _extract_rule_expression, _is_ring_rule, _layer_size_hint, _sky_rule_text_without_identifiers, generate_cases_for_rule
from autodrc.lpl import Polygon, rectangle
from autodrc.rules import ParsedRule
from autodrc.tech import (
    load_known_layers_for_tech,
    load_layer_pairs_for_tech,
    normalize_tech_name,
)


@dataclass(frozen=True)
class LLMPolicy:
    repair_delta_nm: int = 60
    force_template_bad: bool = True


_SKY_SCORED_GOOD_TYPES = {
    "min_width", "min_length", "min_spacing", "max_width", "max_length",
    "min_area", "max_area", "forbidden_use", "offgrid_vertex",
}


_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


@lru_cache(maxsize=None)
def _known_layers_for_tech(tech_name: str) -> set[str]:
    tech = normalize_tech_name(tech_name)
    try:
        return load_known_layers_for_tech(tech)
    except Exception:
        return set()


@lru_cache(maxsize=None)
def _layer_pairs_for_tech(tech_name: str) -> dict[str, tuple[int, int]]:
    tech = normalize_tech_name(tech_name)
    try:
        return load_layer_pairs_for_tech(tech)
    except Exception:
        return {}


def _bbox(poly: Polygon) -> tuple[int, int, int, int]:
    xs = [p[0] for p in poly.points]
    ys = [p[1] for p in poly.points]
    return min(xs), min(ys), max(xs), max(ys)


def _rect_wh(poly: Polygon) -> tuple[int, int]:
    x0, y0, x1, y1 = _bbox(poly)
    return x1 - x0, y1 - y0


def _spacing_nm(a: Polygon, b: Polygon) -> int:
    ax0, ay0, ax1, ay1 = _bbox(a)
    bx0, by0, bx1, by1 = _bbox(b)
    x_gap = max(0, max(ax0, bx0) - min(ax1, bx1))
    y_gap = max(0, max(ay0, by0) - min(ay1, by1))
    return max(x_gap, y_gap)


def _poly_area_nm2(poly: Polygon) -> int:
    area2 = 0
    pts = list(poly.points)
    if len(pts) < 3:
        return 0
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        area2 += x1 * y2 - x2 * y1
    return abs(area2) // 2


def _max_dim(poly: Polygon) -> int:
    w, h = _rect_wh(poly)
    return max(w, h)


def _context_layers_from_text(
    *,
    rule_text: str | None,
    primary_layer: str,
    secondary_layer: str | None,
    tech_name: str = "sky130",
) -> list[str]:
    if not rule_text:
        return []
    tech = normalize_tech_name(tech_name)
    if tech == "sky130":
        rule_text = _sky_rule_text_without_identifiers(rule_text)
    low = rule_text.lower()
    if "licon_peri.not(prec_resistor).space" in low:
        return []

    primary = primary_layer.lower()
    secondary = secondary_layer.lower() if secondary_layer else None
    layer_pairs = _layer_pairs_for_tech(tech)
    known_layers = _known_layers_for_tech(tech)
    primary_pair = layer_pairs.get(primary)
    secondary_pair = layer_pairs.get(secondary) if secondary else None
    layers: list[str] = []
    for token in _TOKEN_RE.findall(low):
        if token == primary:
            continue
        if secondary and token == secondary:
            continue
        if token not in known_layers:
            continue
        token_pair = layer_pairs.get(token)
        if primary_pair is not None and token_pair == primary_pair:
            continue
        if secondary_pair is not None and token_pair == secondary_pair:
            continue
        if token not in layers:
            layers.append(token)
    return layers


def _layer_mode_from_rule_text(rule_text: str, layer: str) -> str:
    low = rule_text.lower()
    key = layer.lower()
    if key.startswith("areaid"):
        token_pat = rf"{re.escape(key)}(?:_[a-z0-9]+)*"
    else:
        token_pat = re.escape(key)
    if re.search(rf"outside_part\([^)]*\b{token_pat}\b", low):
        return "cross"
    if re.search(rf"outside\([^)]*\b{token_pat}\b", low):
        return "separate"
    if re.search(rf"(?:^|\W)not\([^\n]{{0,120}}\b{token_pat}\b", low):
        return "separate"
    if re.search(rf"not_interacting\([^)]*\b{token_pat}\b", low):
        return "separate"
    if re.search(rf"inside\([^)]*\b{token_pat}\b", low):
        return "inside"
    if re.search(rf"interacting\([^)]*\b{token_pat}\b", low):
        return "interact"
    if re.search(rf"and\([^)]*\b{token_pat}\b", low):
        return "interact"
    return "interact"


def _is_exact_length_rule(source_text: str) -> bool:
    low = source_text.lower()
    return (
        ("min/max" in low and "length" in low)
        or ("min. and max." in low and "length" in low)
        or ("min and max" in low and "length" in low)
        or ("length !=" in low)
    )


def _is_exact_width_rule(source_text: str) -> bool:
    low = source_text.lower()
    return (
        ("min/max" in low and "width" in low)
        or ("min. and max." in low and "width" in low)
        or ("min and max" in low and "width" in low)
        or ("width !=" in low)
    )


def _is_cover_only_rule(rule_text: str | None) -> bool:
    if not rule_text:
        return False
    low = rule_text.lower()
    if "must be enclosed by" in low and ".not(" in low:
        return True
    has_cover_phrase = (
        "must be enclosed by" in low
        or "must enclose all" in low
        or "covered by" in low
        or "must be enclosed in" in low
        or "must be covered with" in low
        or "must be within" in low
        or "must be over" in low
    )
    has_numeric = bool(re.search(r"\d+(?:\.\d+)?\s*(?:nm|um|µm)", low))
    return has_cover_phrase and (not has_numeric)


def _with_context_markers(
    case: PatternCase,
    context_layers: list[str],
    rule_text: str | None,
    *,
    tech_name: str = "sky130",
) -> PatternCase:
    if case.intent != "BAD" or not context_layers:
        return case
    if not case.polygons:
        return case
    tech = normalize_tech_name(tech_name)

    x0 = min(_bbox(poly)[0] for poly in case.polygons)
    y0 = min(_bbox(poly)[1] for poly in case.polygons)
    x1 = max(_bbox(poly)[2] for poly in case.polygons)
    y1 = max(_bbox(poly)[3] for poly in case.polygons)
    pad = 80
    marker_w = max(20, (x1 - x0) + 2 * pad)
    marker_h = max(20, (y1 - y0) + 2 * pad)
    marker_x = x0 - pad
    marker_y = y0 - pad
    base_w = max(20, x1 - x0)
    base_h = max(20, y1 - y0)

    existing_layers = {poly.layer.lower() for poly in case.polygons}
    layer_pairs = _layer_pairs_for_tech(tech)
    existing_pairs = {
        pair for poly_layer in existing_layers if (pair := layer_pairs.get(poly_layer)) is not None
    }
    markers: list[Polygon] = []
    for idx, layer in enumerate(context_layers[:6]):
        layer_pair = layer_pairs.get(layer)
        if layer in existing_layers:
            continue
        if layer_pair is not None and layer_pair in existing_pairs:
            continue
        mode = _layer_mode_from_rule_text(rule_text or "", layer)
        size_hint = _layer_size_hint(layer, tech_name=tech)
        if mode == "inside":
            mx = marker_x - 20 * idx
            my = marker_y - 20 * idx
            mw = max(size_hint, marker_w + 40 * idx)
            mh = max(size_hint, marker_h + 40 * idx)
        elif mode == "cross":
            if layer.startswith("areaid") and len(case.polygons) >= 2:
                first_bbox, second_bbox = sorted(
                    (_bbox(poly) for poly in case.polygons[:2]), key=lambda box: (box[0], box[1])
                )
                overlap = max(20, min(80, (first_bbox[2] - first_bbox[0]) // 4))
                mx = first_bbox[2] - overlap
                my = min(first_bbox[1], second_bbox[1]) - pad
                mw = max(
                    size_hint,
                    (second_bbox[0] - first_bbox[2]) + 2 * overlap,
                )
                mh = max(size_hint, max(first_bbox[3], second_bbox[3]) - my + pad)
            else:
                mx = x0 + (base_w // 2)
                my = y0 - pad
                mw = max(size_hint, (base_w // 2) + pad)
                mh = max(size_hint, base_h + 2 * pad)
        elif mode == "separate":
            # Keep marker near but disjoint for `.outside/.not` style filters.
            mx = x1 + pad + idx * 40
            my = y0
            mw = max(size_hint, base_w // 2)
            mh = max(size_hint, base_h)
        else:
            mx = marker_x
            my = marker_y
            mw = max(size_hint, marker_w)
            mh = max(size_hint, marker_h)
        markers.append(rectangle(layer, mx, my, mw, mh))

    if not markers:
        return case
    return PatternCase(
        case_id=case.case_id,
        intent=case.intent,
        description=case.description + " [ctx-markers]",
        polygons=case.polygons + tuple(markers),
        labels=case.labels,
        allow_non_manhattan=case.allow_non_manhattan,
        rigorous_geometry=case.rigorous_geometry,
    )


def _intent_match(rule: ParsedRule, case: PatternCase) -> bool:
    case_dict = case.to_dict()
    geometry_valid = bool(case_dict["geometry_valid"])
    if case.intent == "ILLEGAL":
        return not geometry_valid
    if not geometry_valid:
        return False

    if rule.rule_type == "min_width":
        if not case.polygons:
            return False
        widths = [min(_rect_wh(poly)) for poly in case.polygons if poly.layer == rule.layer]
        if not widths:
            return False
        pass_rule = all(width >= rule.threshold_nm for width in widths)
    elif rule.rule_type == "min_length":
        lengths = [_max_dim(poly) for poly in case.polygons if poly.layer == rule.layer]
        if not lengths:
            return False
        pass_rule = all(length >= rule.threshold_nm for length in lengths)
    elif rule.rule_type == "min_spacing":
        polys = [poly for poly in case.polygons if poly.layer == rule.layer]
        if len(polys) < 2:
            return False
        pass_rule = _spacing_nm(polys[0], polys[1]) >= rule.threshold_nm
    elif rule.rule_type == "max_width":
        widths = [min(_rect_wh(poly)) for poly in case.polygons if poly.layer == rule.layer]
        if not widths:
            return False
        if _is_exact_width_rule(rule.source_text):
            pass_rule = all(width == rule.threshold_nm for width in widths)
        else:
            pass_rule = all(width <= rule.threshold_nm for width in widths)
    elif rule.rule_type == "max_length":
        lengths = [_max_dim(poly) for poly in case.polygons if poly.layer == rule.layer]
        if not lengths:
            return False
        if _is_exact_length_rule(rule.source_text):
            pass_rule = all(length == rule.threshold_nm for length in lengths)
        else:
            pass_rule = all(length <= rule.threshold_nm for length in lengths)
    elif rule.rule_type == "min_area":
        areas = [_poly_area_nm2(poly) for poly in case.polygons if poly.layer == rule.layer]
        if not areas:
            return False
        pass_rule = all(area >= rule.threshold_nm for area in areas)
    elif rule.rule_type == "max_area":
        areas = [_poly_area_nm2(poly) for poly in case.polygons if poly.layer == rule.layer]
        if not areas:
            return False
        pass_rule = all(area <= rule.threshold_nm for area in areas)
    elif rule.rule_type == "forbidden_use":
        used = any(poly.layer == rule.layer for poly in case.polygons)
        pass_rule = not used
    else:
        return True

    if case.intent == "GOOD":
        return pass_rule
    if case.intent == "BAD":
        return not pass_rule
    return False


def score_case_for_intent(*, rule: ParsedRule, case: PatternCase) -> int:
    case_dict = case.to_dict()
    geometry_valid = bool(case_dict["geometry_valid"])
    validation_errors = case_dict.get("validation_errors", [])
    err_count = len(validation_errors) if isinstance(validation_errors, list) else 0

    score = 0
    if case.intent == "ILLEGAL":
        if not geometry_valid:
            return 300 - err_count
        return -50

    if not geometry_valid:
        return -100 - err_count

    score += 100
    if _intent_match(rule, case):
        score += 200
    if case.intent == "GOOD":
        score -= len(case.polygons)
    elif case.intent == "BAD":
        score += min(20, len(case.polygons))
    return score


def select_best_llm_case(*, candidates: list[PatternCase], rule: ParsedRule) -> PatternCase:
    if not candidates:
        raise ValueError("candidates is empty")

    best = candidates[0]
    best_score = score_case_for_intent(rule=rule, case=best)
    for case in candidates[1:]:
        score = score_case_for_intent(rule=rule, case=case)
        if score > best_score:
            best = case
            best_score = score
    return best


def adjust_llm_cases(
    *,
    base_cases: list[PatternCase],
    rule: ParsedRule,
    secondary_layer: str | None = None,
    rule_text: str | None = None,
    policy: LLMPolicy | None = None,
    tech_name: str = "sky130",
) -> list[PatternCase]:
    use_default_policy = policy is None
    if policy is None:
        policy = LLMPolicy()
    tech = normalize_tech_name(tech_name)

    if tech == "ihp_sg13g2":
        from autodrc.ihp_contracts import contract_from_text
        if contract_from_text(rule_text or rule.source_text) is not None:
            # Bounding boxes cannot certify derived inputs, array counts,
            # device labels or a compound output's branch. Only exact geometry
            # equivalence to the independently verified construction is accepted.
            templates = {c.intent: c for c in generate_cases_for_rule(
                rule_type=rule.rule_type, layer=rule.layer, layer_b=secondary_layer,
                threshold_nm=rule.threshold_nm, delta_nm=20,
                rule_text=rule_text or rule.source_text, tech_name=tech,
            )}
            adjusted = []
            for case in base_cases:
                replacement = templates.get(case.intent)
                valid = bool(case.to_dict()["geometry_valid"])
                keep = (case.intent == "ILLEGAL" and not valid) or (
                    replacement is not None and valid and
                    case.polygons == replacement.polygons and case.labels == replacement.labels and
                    case.allow_non_manhattan == replacement.allow_non_manhattan)
                if keep or replacement is None:
                    adjusted.append(case)
                else:
                    adjusted.append(PatternCase(
                        case_id=case.case_id, intent=case.intent,
                        description=case.description + " [repaired] [ihp-verified-construction;delta=20]",
                        polygons=replacement.polygons, labels=replacement.labels,
                        allow_non_manhattan=replacement.allow_non_manhattan,
                        rigorous_geometry=case.rigorous_geometry,
                    ))
            return adjusted

    try:
        fallback = generate_cases_for_rule(
            rule_type=rule.rule_type,
            layer=rule.layer,
            layer_b=secondary_layer,
            threshold_nm=rule.threshold_nm,
            delta_nm=policy.repair_delta_nm,
            rule_text=rule_text or rule.source_text,
            tech_name=tech,
        )
    except ValueError:
        return base_cases

    fallback_by_intent = {case.intent: case for case in fallback}
    semantic_good = None
    needs_semantic_good = tech == "sky130" and (
        rule.rule_type not in _SKY_SCORED_GOOD_TYPES
        or _is_ring_rule(rule_text or rule.source_text)
    )
    if needs_semantic_good:
        # Bounding boxes cannot establish enclosure, holes, or conditional
        # operands. Reuse the GOOD geometry validated by the full template run.
        semantic_good = next(case for case in generate_cases_for_rule(
            rule_type=rule.rule_type, layer=rule.layer, layer_b=secondary_layer,
            threshold_nm=rule.threshold_nm, delta_nm=20,
            rule_text=rule_text or rule.source_text, tech_name=tech,
        ) if case.intent == "GOOD")
    good_template = fallback_by_intent.get("GOOD")
    needs_verified_good_context = tech == "sky130" and good_template is not None and (
        any(poly.layer == "areaid_ce" for poly in good_template.polygons)
        or "[diff-carrier]" in good_template.description
        or "[upper-metal-carrier]" in good_template.description
        or "[hv-context;" in good_template.description
        or "[angle-branch-context]" in good_template.description
        or "[cap-intersection-target]" in good_template.description
    )
    context_layers = _context_layers_from_text(
        rule_text=rule_text or rule.source_text,
        primary_layer=rule.layer,
        secondary_layer=secondary_layer,
        tech_name=tech,
    )
    apply_context_markers = rule.rule_type not in {
        "must_interact",
        "max_length",
        "max_width",
        "forbidden_angle",
    }
    if apply_context_markers and _is_cover_only_rule(rule_text or rule.source_text):
        apply_context_markers = False
    if apply_context_markers and "licon_peri.not(prec_resistor).space" in (rule_text or rule.source_text).lower():
        apply_context_markers = False
    if tech == "sky130" and good_template is not None and "[hv-context;" in good_template.description:
        apply_context_markers = False
    expression = re.sub(r"\s+", "", _extract_rule_expression(rule_text or rule.source_text) or "").lower()
    if tech == "sky130" and rule.layer == "npc" and rule.threshold_nm == 45 and expression in {
        "npc.enclosing(polylicon1_core,0.045,euclidian)", "polylicon1_core.not(npc)",
    }:
        apply_context_markers = False

    def _maybe_with_context(case: PatternCase) -> PatternCase:
        if not apply_context_markers:
            return case
        return _with_context_markers(
            case,
            context_layers,
            rule_text or rule.source_text,
            tech_name=tech,
        )

    verified_bad = None
    normalized_text = re.sub(r"\s+", "", rule_text or rule.source_text).lower()
    # These two official branches have independently checked 20nm BAD
    # constructions; the generic 60nm repair introduces unrelated violations.
    if use_default_policy and tech == "sky130" and rule.rule_type == "via_enclosure" and (
        (rule.layer == "m1" and secondary_layer == "via" and rule.threshold_nm == 55
         and expression == "m1.edges.enclosing(rectvia.drc(width==0.15),0.055,euclidian)")
        or (rule.layer == "m2" and secondary_layer == "via2" and rule.threshold_nm == 85
            and expression == "via2_interact"
            and "m2.enclosing(via2,0.085,projection).second_edges" in normalized_text)
    ):
        verified_bad = _maybe_with_context(next(c for c in generate_cases_for_rule(
            rule_type=rule.rule_type, layer=rule.layer, layer_b=secondary_layer,
            threshold_nm=rule.threshold_nm, delta_nm=20,
            rule_text=rule_text or rule.source_text, tech_name=tech,
        ) if c.intent == "BAD"))

    adjusted: list[PatternCase] = []
    for case in base_cases:
        is_illegal_geometry = not bool(case.to_dict()["geometry_valid"])
        if case.intent == "BAD" and verified_bad is not None:
            if (not is_illegal_geometry and case.polygons == verified_bad.polygons
                    and case.labels == verified_bad.labels
                    and case.allow_non_manhattan == verified_bad.allow_non_manhattan):
                adjusted.append(case)
            else:
                adjusted.append(PatternCase(
                    case_id=case.case_id, intent=case.intent,
                    description=case.description + " [repaired] [sky-verified-bad;delta=20]",
                    polygons=verified_bad.polygons, labels=verified_bad.labels,
                    allow_non_manhattan=verified_bad.allow_non_manhattan,
                    rigorous_geometry=case.rigorous_geometry,
                ))
            continue
        if case.intent == "ILLEGAL":
            is_match = is_illegal_geometry
        else:
            is_match = (not is_illegal_geometry) and _intent_match(rule, case)

        if case.intent == "BAD" and policy.force_template_bad:
            is_match = False
        if case.intent == "GOOD" and rule.rule_type == "must_interact":
            # LLM GOOD samples for floating-metal interaction are unstable;
            # force deterministic template geometry for strict convergence.
            is_match = False
        if case.intent == "GOOD" and needs_verified_good_context:
            is_match = False
        if case.intent == "GOOD" and needs_semantic_good:
            is_match = False
        if case.intent == "GOOD" and tech == "sky130" and rule.rule_type == "offgrid_vertex":
            primary = [p for p in case.polygons if p.layer == rule.layer]
            grid = max(1, rule.threshold_nm)
            is_match = not is_illegal_geometry and bool(primary) and all(
                x % grid == 0 and y % grid == 0 for p in primary for x,y in p.points
            )

        if is_match:
            adjusted.append(_maybe_with_context(case))
            continue
        replacement = semantic_good if case.intent == "GOOD" and needs_semantic_good else fallback_by_intent.get(case.intent)
        if replacement is None:
            adjusted.append(_maybe_with_context(case))
            continue
        fixed = PatternCase(
            case_id=case.case_id,
            intent=case.intent,
            description=case.description + " [repaired]",
            polygons=replacement.polygons,
            allow_non_manhattan=replacement.allow_non_manhattan,
            labels=replacement.labels,
            rigorous_geometry=case.rigorous_geometry,
        )
        adjusted.append(_maybe_with_context(fixed))
    return adjusted
