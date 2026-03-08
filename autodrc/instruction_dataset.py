from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Iterable

from autodrc.casegen import PatternCase, generate_cases_for_rule
from autodrc.specs import KNOWN_TASKS, UNKNOWN_TASKS, RuleTask


def _case_to_row(task: RuleTask, case: PatternCase) -> dict[str, object]:
    return {
        "task": "instruction_tuning",
        "instruction": (
            "Generate a layout polygon list (LPL) that matches the requested DRC intent."
        ),
        "input": {
            "rule_name": task.name,
            "rule_type": task.rule_type,
            "layer": task.layer,
            "threshold_nm": task.threshold_nm,
            "description": task.description,
            "intent": case.intent,
        },
        "output": {
            "intent": case.intent,
            "lpl": [p.to_dict() for p in case.polygons],
            "description": case.description,
        },
        "metadata": {"known_rule": task.known_rule, "target_categories": list(task.target_categories)},
    }


def build_instruction_rows(tasks: Iterable[RuleTask], delta_nm: int = 20) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for task in tasks:
        cases = generate_cases_for_rule(
            rule_type=task.rule_type,
            layer=task.layer,
            threshold_nm=task.threshold_nm,
            delta_nm=delta_nm,
        )
        rows.extend(_case_to_row(task, case) for case in cases)
    return rows


def _iter_summary_files(root: Path) -> list[Path]:
    return sorted(root.glob("**/iteration_summary.json"))


def build_feedback_rows(runs_root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for summary_file in _iter_summary_files(runs_root):
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        for case in summary.get("cases", []):
            rows.append(
                {
                    "task": "feedback_augmentation",
                    "instruction": (
                        "Classify whether this generated layout satisfies the requested intent "
                        "under target-rule DRC feedback."
                    ),
                    "input": {
                        "rule_type": summary.get("rule_type"),
                        "layer": summary.get("layer"),
                        "threshold_nm": summary.get("threshold_nm"),
                        "iteration": summary.get("iteration"),
                        "delta_nm": summary.get("delta_nm"),
                        "good_ok": summary.get("good_ok"),
                        "bad_ok": summary.get("bad_ok"),
                        "converged_this_iter": summary.get("converged_this_iter"),
                        "target_categories": summary.get("target_categories", []),
                        "intent": case.get("intent"),
                        "geometry_valid": case.get("geometry_valid"),
                        "drc_items_target": case.get("drc_items_target"),
                        "category_hits": case.get("category_hits", {}),
                        "case_id": case.get("case_id"),
                    },
                    "output": {
                        "label": "accept" if case.get("intent_match") else "reject",
                        "intent_match": bool(case.get("intent_match")),
                    },
                    "metadata": {"source_summary": str(summary_file)},
                }
            )
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Build instruction-tuning and feedback-augmentation datasets."
    )
    p.add_argument(
        "--out-instruction",
        default="data/instruction_tuning/instruction.jsonl",
        help="Output JSONL for instruction tuning data",
    )
    p.add_argument(
        "--out-feedback",
        default="data/instruction_tuning/feedback.jsonl",
        help="Output JSONL for DRC feedback augmentation data",
    )
    p.add_argument("--runs-root", default="runs", help="Closed-loop run directory root")
    p.add_argument("--delta-nm", type=int, default=20)
    p.add_argument(
        "--include-unknown",
        action="store_true",
        help="Include unknown/generalization rules in instruction data",
    )
    args = p.parse_args()

    tasks: list[RuleTask] = list(KNOWN_TASKS)
    if args.include_unknown:
        tasks.extend(list(UNKNOWN_TASKS))

    instruction_rows = build_instruction_rows(tasks, delta_nm=args.delta_nm)
    feedback_rows = build_feedback_rows(Path(args.runs_root))

    write_jsonl(Path(args.out_instruction), instruction_rows)
    write_jsonl(Path(args.out_feedback), feedback_rows)

    stats = {
        "instruction_rows": len(instruction_rows),
        "feedback_rows": len(feedback_rows),
        "out_instruction": args.out_instruction,
        "out_feedback": args.out_feedback,
        "included_unknown": args.include_unknown,
    }
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
