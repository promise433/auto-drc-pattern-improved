from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _safe_div(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def compute_case_metrics(cases: list[dict[str, Any]]) -> dict[str, float | int]:
    total_cases = len(cases)
    intent_matches = sum(1 for case in cases if bool(case.get("intent_match")))

    good_cases = [case for case in cases if case.get("intent") == "GOOD"]
    bad_cases = [case for case in cases if case.get("intent") == "BAD"]
    illegal_cases = [case for case in cases if case.get("intent") == "ILLEGAL"]

    good_legal = [case for case in good_cases if bool(case.get("geometry_valid"))]
    bad_legal = [case for case in bad_cases if bool(case.get("geometry_valid"))]

    good_false_hits = sum(
        1
        for case in good_legal
        if case.get("drc_items_target") is not None and int(case.get("drc_items_target", 0)) > 0
    )
    bad_target_hits = sum(
        1
        for case in bad_legal
        if case.get("drc_items_target") is not None and int(case.get("drc_items_target", 0)) > 0
    )
    illegal_caught = sum(1 for case in illegal_cases if not bool(case.get("geometry_valid")))

    return {
        "total_cases": total_cases,
        "intent_accuracy": _safe_div(intent_matches, total_cases),
        "target_rule_hit_rate": _safe_div(bad_target_hits, len(bad_legal)),
        "false_positive_rate": _safe_div(good_false_hits, len(good_legal)),
        "illegal_detection_rate": _safe_div(illegal_caught, len(illegal_cases)),
        "good_cases": len(good_cases),
        "bad_cases": len(bad_cases),
        "illegal_cases": len(illegal_cases),
    }


def summarize_iteration_summary(iteration_summary: dict[str, Any]) -> dict[str, Any]:
    cases = list(iteration_summary.get("cases", []))
    metrics = compute_case_metrics(cases)
    return {
        "iteration": iteration_summary.get("iteration"),
        "rule_type": iteration_summary.get("rule_type"),
        "layer": iteration_summary.get("layer"),
        "threshold_nm": iteration_summary.get("threshold_nm"),
        "target_categories": iteration_summary.get("target_categories", []),
        "metrics": metrics,
    }


def _iter_iteration_summary_files(root: Path) -> list[Path]:
    return sorted(root.glob("**/iteration_summary.json"))


def build_validation_report(runs_root: Path, out_path: Path | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for summary_path in _iter_iteration_summary_files(runs_root):
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        row = summarize_iteration_summary(payload)
        row["source"] = str(summary_path)
        rows.append(row)

    aggregated_cases = 0
    aggregated_matches = 0
    weighted_target_hits_num = 0.0
    weighted_target_hits_den = 0
    weighted_false_pos_num = 0.0
    weighted_false_pos_den = 0

    for row in rows:
        metrics = row["metrics"]
        total = int(metrics["total_cases"])
        aggregated_cases += total
        aggregated_matches += int(round(float(metrics["intent_accuracy"]) * total))

        bad_count = int(metrics["bad_cases"])
        good_count = int(metrics["good_cases"])
        weighted_target_hits_num += float(metrics["target_rule_hit_rate"]) * bad_count
        weighted_target_hits_den += bad_count
        weighted_false_pos_num += float(metrics["false_positive_rate"]) * good_count
        weighted_false_pos_den += good_count

    report = {
        "runs_root": str(runs_root),
        "entries": len(rows),
        "overall": {
            "intent_accuracy": _safe_div(aggregated_matches, aggregated_cases),
            "target_rule_hit_rate": _safe_div(
                int(round(weighted_target_hits_num * 1000000)), weighted_target_hits_den * 1000000
            ),
            "false_positive_rate": _safe_div(
                int(round(weighted_false_pos_num * 1000000)), weighted_false_pos_den * 1000000
            ),
        },
        "details": rows,
    }

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build validation metrics report from closed-loop iteration summaries."
    )
    parser.add_argument("--runs-root", default="runs")
    parser.add_argument("--out", default="runs/validation/validation_summary.json")
    args = parser.parse_args()

    report = build_validation_report(Path(args.runs_root), out_path=Path(args.out))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
