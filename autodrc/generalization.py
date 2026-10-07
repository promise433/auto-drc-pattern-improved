from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autodrc.casegen import PatternCase, generate_cases_for_rule
from autodrc.closed_loop import run_closed_loop
from autodrc.lpl import Polygon
from autodrc.specs import KNOWN_TASKS, UNKNOWN_TASKS, RuleTask
from autodrc.tech import require_sky_research


DENSITY_WINDOW_AREA_NM2 = 2000 * 2000


def _bbox(poly: Polygon) -> tuple[int, int, int, int]:
    xs = [p[0] for p in poly.points]
    ys = [p[1] for p in poly.points]
    return min(xs), min(ys), max(xs), max(ys)


def _rect_wh(poly: Polygon) -> tuple[int, int]:
    x0, y0, x1, y1 = _bbox(poly)
    return x1 - x0, y1 - y0


def _rect_area(poly: Polygon) -> int:
    w, h = _rect_wh(poly)
    return max(0, w) * max(0, h)


def _poly_by_layer(case: PatternCase, layer: str) -> list[Polygon]:
    return [p for p in case.polygons if p.layer.lower() == layer.lower()]


def _spacing_nm(a: Polygon, b: Polygon) -> int:
    ax0, ay0, ax1, ay1 = _bbox(a)
    bx0, by0, bx1, by1 = _bbox(b)

    x_gap = max(0, max(ax0, bx0) - min(ax1, bx1))
    y_gap = max(0, max(ay0, by0) - min(ay1, by1))
    return max(x_gap, y_gap)


def _enclosure_nm(outer: Polygon, inner: Polygon) -> int:
    ox0, oy0, ox1, oy1 = _bbox(outer)
    ix0, iy0, ix1, iy1 = _bbox(inner)
    if ix0 < ox0 or iy0 < oy0 or ix1 > ox1 or iy1 > oy1:
        return -1
    return min(ix0 - ox0, iy0 - oy0, ox1 - ix1, oy1 - iy1)


def check_case_semantics(case: PatternCase, task: RuleTask) -> bool:
    case_dict = case.to_dict()
    if case.intent == "ILLEGAL":
        return not bool(case_dict["geometry_valid"])
    if not case_dict["geometry_valid"]:
        return False

    t = task.rule_type
    thr = task.threshold_nm
    layer = task.layer

    if t == "min_width":
        polys = _poly_by_layer(case, layer)
        if not polys:
            return False
        pass_rule = all(min(_rect_wh(p)) >= thr for p in polys)
    elif t == "min_spacing":
        polys = _poly_by_layer(case, layer)
        if len(polys) < 2:
            return False
        pass_rule = _spacing_nm(polys[0], polys[1]) >= thr
    elif t == "min_density":
        polys = _poly_by_layer(case, layer)
        if not polys:
            return False
        fill = sum(_rect_area(p) for p in polys)
        window_area = 1000 * 1000
        density_bps = int(round(fill * 10000 / window_area))
        pass_rule = density_bps >= thr
    elif t == "density_window":
        polys = _poly_by_layer(case, layer)
        if not polys:
            return False
        fill = sum(_rect_area(p) for p in polys)
        density_bps = int(round(fill * 10000 / DENSITY_WINDOW_AREA_NM2))
        pass_rule = density_bps >= thr
    elif t == "poly_endcap":
        diff = _poly_by_layer(case, "diff")
        poly = _poly_by_layer(case, "poly")
        if not diff or not poly:
            return False
        _, dy0, _, dy1 = _bbox(diff[0])
        _, py0, _, py1 = _bbox(poly[0])
        ext = min(dy0 - py0, py1 - dy1)
        pass_rule = ext >= thr
    elif t == "via_enclosure":
        vias = _poly_by_layer(case, "via")
        metals = _poly_by_layer(case, layer)
        if not vias or not metals:
            return False
        pass_rule = _enclosure_nm(metals[0], vias[0]) >= thr
    else:
        return False

    if case.intent == "GOOD":
        return pass_rule
    if case.intent == "BAD":
        return not pass_rule
    return False


def evaluate_task_semantics(
    task: RuleTask,
    delta_nm: int = 20,
    tech_name: str = "sky130",
) -> dict[str, Any]:
    cases = generate_cases_for_rule(
        rule_type=task.rule_type,
        layer=task.layer,
        threshold_nm=task.threshold_nm,
        delta_nm=delta_nm,
        tech_name=tech_name,
    )
    checks = []
    for case in cases:
        ok = check_case_semantics(case, task)
        checks.append({"case_id": case.case_id, "intent": case.intent, "semantic_match": ok})
    pass_rate = sum(1 for c in checks if c["semantic_match"]) / len(checks)
    return {
        "task": task.name,
        "known_rule": task.known_rule,
        "rule_type": task.rule_type,
        "layer": task.layer,
        "threshold_nm": task.threshold_nm,
        "semantic_pass_rate": pass_rate,
        "checks": checks,
    }


def evaluate_generalization(
    *,
    out_dir: Path,
    include_known: bool = True,
    include_unknown: bool = True,
    delta_nm: int = 20,
    with_drc_for_known: bool = False,
    tech_name: str = "sky130",
) -> dict[str, Any]:
    require_sky_research(tech_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks: list[RuleTask] = []
    if include_known:
        tasks.extend(KNOWN_TASKS)
    if include_unknown:
        tasks.extend(UNKNOWN_TASKS)

    rows = [evaluate_task_semantics(task, delta_nm=delta_nm, tech_name=tech_name) for task in tasks]

    if with_drc_for_known:
        drc_rows: list[dict[str, Any]] = []
        for task in KNOWN_TASKS:
            summary = run_closed_loop(
                rule_type=task.rule_type,
                layer=task.layer,
                threshold_nm=task.threshold_nm,
                out_dir=out_dir / "known_rule_drc" / task.name,
                max_iters=1,
                initial_delta_nm=delta_nm,
                target_categories=list(task.target_categories),
            )
            iter0 = summary["iterations"][0]
            drc_rows.append(
                {
                    "task": task.name,
                    "good_ok": iter0["good_ok"],
                    "bad_ok": iter0["bad_ok"],
                    "converged": iter0["converged_this_iter"],
                }
            )
    else:
        drc_rows = []

    summary = {
        "semantic_results": rows,
        "drc_results": drc_rows,
        "semantic_avg_pass_rate": (
            sum(r["semantic_pass_rate"] for r in rows) / len(rows) if rows else 0.0
        ),
    }
    (out_dir / "generalization_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Generalization and robustness evaluation for known/unknown rules."
    )
    p.add_argument("--tech-name", default="sky130")
    p.add_argument("--out-dir", default="runs/generalization")
    p.add_argument("--delta-nm", type=int, default=20)
    p.add_argument("--include-known", action="store_true")
    p.add_argument("--include-unknown", action="store_true")
    p.add_argument("--with-drc-for-known", action="store_true")
    args = p.parse_args()

    include_known = args.include_known or (not args.include_unknown)
    include_unknown = args.include_unknown or (not args.include_known)

    summary = evaluate_generalization(
        tech_name=args.tech_name,
        out_dir=Path(args.out_dir),
        include_known=include_known,
        include_unknown=include_unknown,
        delta_nm=args.delta_nm,
        with_drc_for_known=args.with_drc_for_known,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
