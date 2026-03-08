from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from autodrc.closed_loop import run_closed_loop
from autodrc.discriminator import DiscriminatorWeights, score_case
from autodrc.rules import parse_rule_text


def _parse_float_list(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def _parse_int_list(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def mine_corner_cases(
    *,
    rule_type: str,
    layer: str,
    threshold_nm: int,
    deltas_nm: list[int],
    weights_grid: list[DiscriminatorWeights],
    out_dir: Path,
    runset_path: Path | None = None,
    top_cell: str = "TOP",
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    scans: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None

    for w_idx, weights in enumerate(weights_grid, start=1):
        profile_name = f"w{w_idx:02d}"
        for delta in deltas_nm:
            run_dir = out_dir / profile_name / f"delta_{delta:03d}"
            summary = run_closed_loop(
                rule_type=rule_type,
                layer=layer,
                threshold_nm=threshold_nm,
                out_dir=run_dir,
                initial_delta_nm=delta,
                delta_step_nm=1,
                max_iters=1,
                runset_path=runset_path,
                top_cell=top_cell,
            )
            iter0 = summary["iterations"][0]
            bad_case = next(c for c in iter0["cases"] if c["intent"] == "BAD")
            total = bad_case.get("drc_items_total")
            target = bad_case.get("drc_items_target")
            if total is None or target is None:
                score = None
                row = {
                    "profile": profile_name,
                    "delta_nm": delta,
                    "weights": asdict(weights),
                    "error": "missing DRC counts",
                    "run_dir": str(run_dir),
                }
            else:
                scored = score_case(
                    target_hits=int(target),
                    total_hits=int(total),
                    geometry_valid=bool(bad_case.get("geometry_valid", False)),
                    delta_nm=delta,
                    weights=weights,
                )
                score = scored.score
                row = {
                    "profile": profile_name,
                    "delta_nm": delta,
                    "weights": asdict(weights),
                    "score": score,
                    "score_detail": asdict(scored),
                    "bad_case": bad_case,
                    "run_dir": str(run_dir),
                }
            scans.append(row)
            if score is not None and (best is None or score > best["score"]):
                best = row

    result = {
        "rule_type": rule_type,
        "layer": layer,
        "threshold_nm": threshold_nm,
        "deltas_nm": deltas_nm,
        "profiles": [asdict(w) for w in weights_grid],
        "best": best,
        "scans": scans,
    }
    (out_dir / "corner_mining_summary.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Guided decoding / corner-case mining with discriminator weight sweep."
    )
    p.add_argument("--rule-text", help="Natural language rule text")
    p.add_argument("--rule-type", choices=["min_width", "min_spacing"])
    p.add_argument("--layer", default="met1")
    p.add_argument("--threshold-nm", type=int)
    p.add_argument("--deltas-nm", default="10,20,30,40")
    p.add_argument("--target-hit-weights", default="1.5,2.0,3.0")
    p.add_argument("--non-target-penalties", default="0.2,0.4")
    p.add_argument("--delta-penalty", type=float, default=0.02)
    p.add_argument("--invalid-penalty", type=float, default=3.0)
    p.add_argument("--out-dir", default="runs/corner_mining")
    p.add_argument("--runset", help="Path to runset")
    p.add_argument("--top-cell", default="TOP")
    args = p.parse_args()

    if args.rule_text:
        parsed = parse_rule_text(args.rule_text, default_layer=args.layer)
        rule_type = parsed.rule_type
        layer = parsed.layer
        threshold_nm = parsed.threshold_nm
    else:
        if not args.rule_type or args.threshold_nm is None:
            raise SystemExit(
                "Either --rule-text OR (--rule-type and --threshold-nm) must be provided."
            )
        rule_type = args.rule_type
        layer = args.layer
        threshold_nm = args.threshold_nm

    deltas = _parse_int_list(args.deltas_nm)
    target_hit_weights = _parse_float_list(args.target_hit_weights)
    non_target_penalties = _parse_float_list(args.non_target_penalties)
    weights_grid: list[DiscriminatorWeights] = []
    for th in target_hit_weights:
        for nt in non_target_penalties:
            weights_grid.append(
                DiscriminatorWeights(
                    target_hit=th,
                    non_target_penalty=nt,
                    invalid_penalty=args.invalid_penalty,
                    delta_penalty=args.delta_penalty,
                )
            )

    summary = mine_corner_cases(
        rule_type=rule_type,
        layer=layer,
        threshold_nm=threshold_nm,
        deltas_nm=deltas,
        weights_grid=weights_grid,
        out_dir=Path(args.out_dir),
        runset_path=Path(args.runset) if args.runset else None,
        top_cell=args.top_cell,
    )
    print(json.dumps(summary.get("best"), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
