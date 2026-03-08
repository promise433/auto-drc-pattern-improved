from __future__ import annotations

import json
from pathlib import Path

from autodrc.closed_loop import run_closed_loop
from autodrc.generalization import evaluate_task_semantics
from autodrc.specs import KNOWN_TASKS, UNKNOWN_TASKS
from autodrc.validation import build_validation_report


def run_benchmark(out_dir: Path, delta_nm: int = 20) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)

    known_results = []
    for task in KNOWN_TASKS:
        summary = run_closed_loop(
            rule_type=task.rule_type,
            layer=task.layer,
            threshold_nm=task.threshold_nm,
            out_dir=out_dir / "known_drc" / task.name,
            max_iters=2,
            initial_delta_nm=delta_nm,
            target_categories=list(task.target_categories),
        )
        known_results.append(
            {
                "task": task.name,
                "converged": summary["converged"],
                "iterations_run": summary["iterations_run"],
            }
        )

    unknown_results = [evaluate_task_semantics(task, delta_nm=delta_nm) for task in UNKNOWN_TASKS]
    validation = build_validation_report(
        out_dir / "known_drc",
        out_path=out_dir / "known_drc" / "validation_summary.json",
    )

    report = {
        "known_rule_benchmark": known_results,
        "unknown_rule_semantic_benchmark": unknown_results,
        "known_rule_validation": validation,
    }
    (out_dir / "benchmark_summary.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Run known/unknown rule benchmark suite.")
    p.add_argument("--out-dir", default="runs/benchmark")
    p.add_argument("--delta-nm", type=int, default=20)
    args = p.parse_args()

    report = run_benchmark(Path(args.out_dir), delta_nm=args.delta_nm)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
