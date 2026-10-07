from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autodrc.closed_loop import run_closed_loop
from autodrc.corner_mining import mine_corner_cases
from autodrc.discriminator import DiscriminatorWeights
from autodrc.generalization import evaluate_generalization
from autodrc.instruction_dataset import (
    build_feedback_rows,
    build_instruction_rows,
    write_jsonl,
)
from autodrc.runset_corpus import parse_runset_outputs, to_pretrain_examples
from autodrc.specs import KNOWN_TASKS, UNKNOWN_TASKS
from autodrc.training_recipes import export_recipes
from autodrc.validation import build_validation_report
from autodrc.tech import detect_tech_name, require_sky_research


def default_runset_path() -> Path:
    return (
        Path.home()
        / ".klayout"
        / "salt"
        / "Efabless_sky130"
        / "tech"
        / "sky130"
        / "drc"
        / "sky130A_mr.drc"
    )


def run_full_pipeline(
    *,
    out_root: Path,
    runset_path: Path | None = None,
    run_corner_mining: bool = True,
    run_known_drc_batch: bool = True,
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
) -> dict[str, Any]:
    runset = runset_path or default_runset_path()
    if not runset.exists():
        raise FileNotFoundError(f"runset not found: {runset}")
    if detect_tech_name(runset) == 'ihp_sg13g2':
        from autodrc.ihp_workflow import run_ihp_workflow
        result = run_ihp_workflow(runset_path=runset,out_root=out_root,generator=generator,
            corner_deltas_nm=(10,20,30) if run_corner_mining else (),run_selected_drc=run_known_drc_batch,
            llm_model=llm_model,llm_max_new_tokens=llm_max_new_tokens,llm_temperature=llm_temperature,
            llm_top_p=llm_top_p,llm_trust_remote_code=llm_trust_remote_code,
            llm_load_in_4bit=llm_load_in_4bit,llm_repair=llm_repair,
            llm_fallback=llm_fallback,llm_prompt_profile=llm_prompt_profile,llm_strict_response=llm_strict_response)
        (out_root/'pipeline_summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        return result
    require_sky_research(detect_tech_name(runset))
    out_root.mkdir(parents=True, exist_ok=True)

    # 1) Rule-to-Runset corpus
    rules = parse_runset_outputs(runset)
    corpus_dir = out_root / "data" / "rule_to_runset"
    write_jsonl(corpus_dir / "catalog.jsonl", (r.__dict__ for r in rules))
    write_jsonl(corpus_dir / "pretrain.jsonl", to_pretrain_examples(rules))

    # 2) Closed-loop baseline batch for known rules
    known_runs: list[dict[str, Any]] = []
    if run_known_drc_batch:
        for task in KNOWN_TASKS:
            summary = run_closed_loop(
                rule_type=task.rule_type,
                layer=task.layer,
                threshold_nm=task.threshold_nm,
                out_dir=out_root / "runs" / "known_rules" / task.name,
                max_iters=3,
                runset_path=runset,
                target_categories=list(task.target_categories),
                generator=generator,
                rule_text=task.description,
                llm_model=llm_model,
                llm_max_new_tokens=llm_max_new_tokens,
                llm_temperature=llm_temperature,
                llm_top_p=llm_top_p,
                llm_trust_remote_code=llm_trust_remote_code,
                llm_load_in_4bit=llm_load_in_4bit,
                llm_repair=llm_repair,
                llm_fallback=llm_fallback,llm_prompt_profile=llm_prompt_profile,
                llm_strict_response=llm_strict_response,
            )
            known_runs.append(
                {
                    "task": task.name,
                    "converged": summary["converged"],
                    "iterations_run": summary["iterations_run"],
                    "target_categories": summary["target_categories"],
                }
            )

    # 3) Instruction + feedback datasets
    data_dir = out_root / "data" / "instruction_tuning"
    instruction_rows = build_instruction_rows(
        [*KNOWN_TASKS, *UNKNOWN_TASKS], delta_nm=20
    )
    feedback_rows = build_feedback_rows(out_root / "runs")
    write_jsonl(data_dir / "instruction.jsonl", instruction_rows)
    write_jsonl(data_dir / "feedback.jsonl", feedback_rows)

    # 4) Validation report for closed-loop quality metrics
    validation_summary = build_validation_report(
        out_root / "runs",
        out_path=out_root / "runs" / "validation" / "validation_summary.json",
    )

    # 5) Generalization evaluation
    gen_summary = evaluate_generalization(
        out_dir=out_root / "runs" / "generalization",
        include_known=True,
        include_unknown=True,
        delta_nm=20,
        with_drc_for_known=False,
    )

    # 6) Guided decoding / corner mining
    if run_corner_mining:
        corner_summary = mine_corner_cases(
            rule_type="min_width",
            layer="met1",
            threshold_nm=140,
            deltas_nm=[10, 20, 30, 40],
            weights_grid=[
                DiscriminatorWeights(target_hit=1.5, non_target_penalty=0.2),
                DiscriminatorWeights(target_hit=2.0, non_target_penalty=0.3),
                DiscriminatorWeights(target_hit=3.0, non_target_penalty=0.4),
            ],
            out_dir=out_root / "runs" / "corner_mining",
            runset_path=runset,
        )
        best_corner = corner_summary.get("best")
    else:
        best_corner = None

    # 7) Training recipes for LoRA/Q-LoRA
    recipes_stats = export_recipes(
        out_path=out_root / "config" / "training_recipes.json",
        train_jsonl=str(data_dir / "instruction.jsonl"),
        out_dir=str(out_root / "runs" / "training"),
    )

    summary = {
        "runset_path": str(runset),
        "generator": generator,
        "llm_model": llm_model,
        "llm_repair": llm_repair,
        "llm_fallback": llm_repair if llm_fallback is None else llm_fallback,
        "llm_prompt_profile": llm_prompt_profile,"llm_strict_response": llm_strict_response,
        "rules_extracted": len(rules),
        "known_runs": known_runs,
        "instruction_rows": len(instruction_rows),
        "feedback_rows": len(feedback_rows),
        "validation_overall": validation_summary.get("overall", {}),
        "generalization_semantic_avg": gen_summary["semantic_avg_pass_rate"],
        "corner_best": best_corner,
        "recipes": recipes_stats,
    }
    (out_root / "pipeline_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="Run full Auto DRC research pipeline.")
    p.add_argument("--out-root", default="artifacts/full_pipeline")
    p.add_argument("--runset", help="Path to a DRC runset")
    p.add_argument("--skip-corner-mining", action="store_true")
    p.add_argument("--skip-known-drc-batch", action="store_true")
    p.add_argument("--generator", choices=["template", "llm"], default="template")
    p.add_argument("--llm-model", help="HF model name/path used when --generator llm")
    p.add_argument("--llm-max-new-tokens", type=int, default=256)
    p.add_argument("--llm-temperature", type=float, default=0.2)
    p.add_argument("--llm-top-p", type=float, default=0.9)
    p.add_argument("--llm-trust-remote-code", action="store_true")
    p.add_argument("--llm-load-in-4bit", action="store_true")
    p.add_argument("--llm-disable-repair", action="store_true")
    p.add_argument("--llm-fallback",choices=["auto","enabled","disabled"],default="auto")
    p.add_argument("--llm-prompt-profile",choices=["legacy","compact","chat"],default="legacy")
    p.add_argument("--llm-strict-response",action="store_true")
    args = p.parse_args()

    if args.generator == "llm" and not args.llm_model:
        raise SystemExit("--llm-model is required when --generator llm")

    summary = run_full_pipeline(
        out_root=Path(args.out_root),
        runset_path=Path(args.runset) if args.runset else None,
        run_corner_mining=not args.skip_corner_mining,
        run_known_drc_batch=not args.skip_known_drc_batch,
        generator=args.generator,
        llm_model=args.llm_model,
        llm_max_new_tokens=args.llm_max_new_tokens,
        llm_temperature=args.llm_temperature,
        llm_top_p=args.llm_top_p,
        llm_trust_remote_code=args.llm_trust_remote_code,
        llm_load_in_4bit=args.llm_load_in_4bit,
        llm_repair=not args.llm_disable_repair,
        llm_fallback={'auto':None,'enabled':True,'disabled':False}[args.llm_fallback],
        llm_prompt_profile=args.llm_prompt_profile,llm_strict_response=args.llm_strict_response,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
