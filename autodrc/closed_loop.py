from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any
import xml.etree.ElementTree as ET

from autodrc.casegen import (
    PatternCase,
    generate_cases_for_rule,
    write_cases,
)
from autodrc.llm_generator import LLMResponseError, generate_case_with_llm
from autodrc.llm_policy import adjust_llm_cases, select_best_llm_case
from autodrc.rules import ParsedRule, parse_rule_text
from autodrc.tech import detect_tech_name, layer_map_path_for_runset, normalize_tech_name


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_lyrdb_items(report_path: Path) -> tuple[int, dict[str, int]]:
    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_path}")

    raw = report_path.read_text(encoding="utf-8", errors="replace")
    root = ET.fromstring(raw)

    item_count = 0
    category_hits: dict[str, int] = {}
    for node in root.iter():
        name = _local_name(node.tag)
        if name == "item":
            item_count += 1
            for child in node:
                if _local_name(child.tag) == "category":
                    cat = (child.text or "").strip().strip("'")
                    if cat:
                        category_hits[cat] = category_hits.get(cat, 0) + 1
    return item_count, dict(sorted(category_hits.items()))


@dataclass(frozen=True)
class CmdResult:
    returncode: int
    stdout: str
    stderr: str


def run_cmd(cmd: list[str]) -> CmdResult:
    extra_env: dict[str, str] = {}
    extra_ld_library_path = os.environ.get("AUTO_DRC_KLAYOUT_LD_LIBRARY_PATH", "").strip()
    if extra_ld_library_path:
        current_ld_library_path = os.environ.get("LD_LIBRARY_PATH", "").strip()
        if current_ld_library_path:
            extra_env["LD_LIBRARY_PATH"] = (
                f"{extra_ld_library_path}:{current_ld_library_path}"
            )
        else:
            extra_env["LD_LIBRARY_PATH"] = extra_ld_library_path
    env = None
    if extra_env:
        env = os.environ.copy()
        env.update(extra_env)
    p = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)
    return CmdResult(returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)


def _klayout_bin() -> str:
    return os.environ.get("AUTO_DRC_KLAYOUT_BIN", "klayout").strip() or "klayout"


@dataclass(frozen=True)
class CaseRunResult:
    case_id: str
    intent: str
    geometry_valid: bool
    gds_path: str
    report_path: str
    drc_returncode: int
    drc_items_total: int | None
    drc_items_target: int | None
    intent_match: bool
    category_hits: dict[str, int]
    drc_stdout_tail: str
    drc_stderr_tail: str


def evaluate_intent(intent: str, geometry_valid: bool, drc_items: int | None) -> bool:
    if intent == "GOOD":
        return geometry_valid and (drc_items == 0)
    if intent == "BAD":
        return geometry_valid and (drc_items is not None and drc_items > 0)
    if intent == "ILLEGAL":
        return not geometry_valid
    raise ValueError(f"Unknown intent: {intent}")


def _case_by_intent(
    case_results: list[CaseRunResult], intent: str
) -> CaseRunResult | None:
    for case in case_results:
        if case.intent == intent:
            return case
    return None


def _next_delta_nm(
    *,
    current_delta_nm: int,
    delta_step_nm: int,
    good_ok: bool,
    bad_ok: bool,
    good_target_hits: int | None,
    bad_target_hits: int | None,
) -> tuple[int, str]:
    step_factor = 1
    reason = "steady_step"
    if (not good_ok) and (not bad_ok):
        step_factor = 2
        reason = "dual_miss_accelerate"
    elif (not good_ok) and (good_target_hits is None or good_target_hits > 0):
        step_factor = 2
        reason = "good_still_violates_target_accelerate"
    elif (not bad_ok) and (bad_target_hits is None or bad_target_hits <= 0):
        step_factor = 2
        reason = "bad_not_hitting_target_accelerate"
    return current_delta_nm + step_factor * delta_step_nm, reason


def _next_llm_candidate_counts(
    *,
    feedback_boost: bool,
    candidate_growth: int,
    max_candidates_per_intent: int,
    current_good: int,
    current_bad: int,
    current_illegal: int,
    good_ok: bool,
    bad_ok: bool,
) -> tuple[int, int, int, list[str]]:
    next_good = current_good
    next_bad = current_bad
    next_illegal = current_illegal
    actions: list[str] = []
    if not feedback_boost:
        return next_good, next_bad, next_illegal, actions

    if not good_ok and next_good < max_candidates_per_intent:
        next_good = min(max_candidates_per_intent, next_good + candidate_growth)
        actions.append("boost_good_candidates")
    if not bad_ok and next_bad < max_candidates_per_intent:
        next_bad = min(max_candidates_per_intent, next_bad + candidate_growth)
        actions.append("boost_bad_candidates")
    return next_good, next_bad, next_illegal, actions


def _default_target_categories(rule_type: str, layer: str) -> list[str]:
    lyr = layer.lower()
    table: dict[tuple[str, str], list[str]] = {
        ("min_width", "met1"): ["m1.1"],
        ("min_spacing", "met1"): ["m1.2"],
        ("min_width", "met2"): ["m2.1"],
        ("min_spacing", "met2"): ["m2.2"],
        ("min_width", "met3"): ["m3.1"],
        ("min_spacing", "met3"): ["m3.2"],
        ("min_width", "met4"): ["m4.1"],
        ("min_spacing", "met4"): ["m4.2"],
        ("min_width", "met5"): ["m5.1"],
        ("min_spacing", "met5"): ["m5.2"],
        ("min_width", "li1"): ["li.1"],
        ("min_spacing", "li1"): ["li.3"],
        ("min_width", "poly"): ["poly.1a"],
        ("min_spacing", "poly"): ["poly.2"],
    }
    return table.get((rule_type, lyr), [])


def _default_rule_text(rule_type: str, layer: str, threshold_nm: int) -> str:
    if rule_type == "min_width":
        return f"Minimum width {threshold_nm}nm on {layer}"
    if rule_type == "min_spacing":
        return f"Minimum spacing {threshold_nm}nm on {layer}"
    return f"Rule {rule_type} threshold {threshold_nm}nm on {layer}"


def _generate_cases(
    *,
    generator: str,
    rule_type: str,
    layer: str,
    secondary_layer: str | None = None,
    threshold_nm: int,
    delta_nm: int,
    rule_text: str | None,
    llm_model: str | None,
    llm_max_new_tokens: int,
    llm_temperature: float,
    llm_top_p: float,
    llm_trust_remote_code: bool,
    llm_load_in_4bit: bool,
    llm_debug_dir: Path | None,
    llm_repair: bool,
    llm_fallback: bool | None = None,
    llm_prompt_profile: str = 'legacy',
    llm_strict_response: bool = False,
    tech_name: str = "sky130",
    llm_good_candidates: int = 1,
    llm_bad_candidates: int = 3,
    llm_illegal_candidates: int = 1,
) -> list[PatternCase]:
    if generator == "template":
        return generate_cases_for_rule(
            rule_type=rule_type,
            layer=layer,
            threshold_nm=threshold_nm,
            delta_nm=delta_nm,
            layer_b=secondary_layer,
            rule_text=rule_text,
            tech_name=tech_name,
        )

    if generator != "llm":
        raise ValueError(f"Unsupported generator: {generator}")
    if not llm_model:
        raise ValueError("llm_model must be provided when generator='llm'")
    fallback_enabled = llm_repair if llm_fallback is None else llm_fallback

    text = rule_text or _default_rule_text(rule_type, layer, threshold_nm)
    cases: list[PatternCase] = []
    parsed_rule = ParsedRule(
        rule_type=rule_type,
        layer=layer,
        threshold_nm=threshold_nm,
        source_text=text,
    )
    candidates_by_intent = {
        "GOOD": max(1, llm_good_candidates),
        "BAD": max(1, llm_bad_candidates),
        "ILLEGAL": max(1, llm_illegal_candidates),
    }
    attempts: list[dict[str, Any]] = []
    if llm_debug_dir is not None:
        llm_debug_dir.mkdir(parents=True, exist_ok=True)
    for intent in ("GOOD", "BAD", "ILLEGAL"):
        intent_candidates: list[PatternCase] = []
        errors: list[str] = []
        response_errors_only = True
        for attempt in range(candidates_by_intent[intent]):
            if attempt == 0:
                temp = llm_temperature
            else:
                temp = min(0.95, llm_temperature + 0.12 * attempt)
            try:
                attempt_record = dict(intent=intent, candidate=attempt + 1, temperature=temp)
                attempts.append(attempt_record)
                llm_case = generate_case_with_llm(
                    model_name=llm_model,
                    rule_text=text,
                    intent=intent,
                    max_new_tokens=llm_max_new_tokens,
                    temperature=temp,
                    top_p=llm_top_p,
                    trust_remote_code=llm_trust_remote_code,
                    load_in_4bit=llm_load_in_4bit,
                    debug_dir=(llm_debug_dir / f"candidate_{intent.lower()}_{attempt + 1:02d}"
                               if llm_debug_dir is not None else None),
                    expected_layer=layer,
                    tech_name=tech_name,
                    prompt_profile=llm_prompt_profile,
                    strict_response=llm_strict_response,
                )
                intent_candidates.append(
                    PatternCase(
                        case_id=f"{layer}_{rule_type}_{intent.lower()}_llm",
                        intent=intent,
                        description=f"llm-generated for: {text} [cand={attempt + 1}]",
                        polygons=llm_case.polygons,
                        labels=llm_case.labels,
                        rigorous_geometry=llm_case.rigorous_geometry,
                        allow_non_manhattan=llm_case.allow_non_manhattan,
                    )
                )
                attempt_record.update(status="returned", case_before_selection=llm_case.to_case_dict())
            except Exception as exc:
                attempt_record.update(status="error", error_type=type(exc).__name__, error=str(exc))
                errors.append(str(exc))
                response_errors_only = response_errors_only and isinstance(exc, LLMResponseError)
                continue
            finally:
                if llm_debug_dir is not None:
                    (llm_debug_dir / "generation_attempts.json").write_text(
                        json.dumps(attempts, indent=2), encoding="utf-8")
        if not intent_candidates:
            if fallback_enabled and response_errors_only:
                fallback = next(case for case in generate_cases_for_rule(
                    rule_type=rule_type, layer=layer, layer_b=secondary_layer,
                    threshold_nm=threshold_nm,
                    delta_nm=20 if normalize_tech_name(tech_name) == "ihp_sg13g2" else delta_nm,
                    rule_text=text, tech_name=tech_name,
                ) if case.intent == intent)
                cases.append(PatternCase(case_id=f"{layer}_{rule_type}_{intent.lower()}_llm",
                    intent=intent, description=f"[model-fallback:no-usable-response] {fallback.description}",
                    polygons=fallback.polygons, allow_non_manhattan=fallback.allow_non_manhattan,
                    labels=fallback.labels))
                if llm_debug_dir is not None:
                    (llm_debug_dir / f"fallback_{intent.lower()}.json").write_text(json.dumps(dict(
                        intent=intent, source="template", reason="no_usable_model_response",
                        candidate_errors=errors, case=cases[-1].to_dict()), indent=2), encoding="utf-8")
                continue
            raise RuntimeError(
                f"LLM produced no usable candidate for intent={intent}; errors={errors[:3]}"
            )
        selected = select_best_llm_case(candidates=intent_candidates, rule=parsed_rule)
        cases.append(selected)
    if llm_repair:
        return adjust_llm_cases(
            base_cases=cases,
            rule=parsed_rule,
            secondary_layer=secondary_layer,
            rule_text=text,
            tech_name=tech_name,
        )
    return cases


def _default_sky130_runset() -> Path:
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


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def run_closed_loop(
    *,
    rule_type: str,
    layer: str,
    secondary_layer: str | None = None,
    threshold_nm: int,
    out_dir: Path,
    initial_delta_nm: int = 20,
    delta_step_nm: int = 20,
    max_iters: int = 3,
    runset_path: Path | None = None,
    top_cell: str = "TOP",
    feol: bool = True,
    beol: bool = True,
    offgrid: bool = True,
    dbu: float = 0.001,
    target_categories: list[str] | None = None,
    generator: str = "template",
    rule_text: str | None = None,
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
    runset_defines: dict[str, str] | None = None,
) -> dict[str, Any]:
    if threshold_nm <= 0:
        raise ValueError("threshold_nm must be > 0")
    if initial_delta_nm <= 0 or delta_step_nm <= 0:
        raise ValueError("delta values must be > 0")
    if max_iters <= 0:
        raise ValueError("max_iters must be > 0")
    if generator not in {"template", "llm"}:
        raise ValueError("generator must be 'template' or 'llm'")
    if generator == "llm" and not llm_model:
        raise ValueError("llm_model must be provided when generator='llm'")
    if llm_good_candidates <= 0 or llm_bad_candidates <= 0 or llm_illegal_candidates <= 0:
        raise ValueError("llm candidate counts must be > 0")
    if llm_candidate_growth <= 0:
        raise ValueError("llm_candidate_growth must be > 0")
    if llm_max_candidates_per_intent <= 0:
        raise ValueError("llm_max_candidates_per_intent must be > 0")

    runset = runset_path or _default_sky130_runset()
    if not runset.exists():
        raise FileNotFoundError(f"runset not found: {runset}")

    tech_name = detect_tech_name(runset)
    if dbu != 0.001:
        raise ValueError("LPL coordinates are nanometres; closed_loop requires dbu=0.001 um")
    if tech_name == "ihp_sg13g2" and not target_categories:
        raise ValueError("IHP requires explicit target_categories from the selected runset")

    root = out_dir
    root.mkdir(parents=True, exist_ok=True)

    lpl_to_gds_script = _repo_root() / "scripts" / "lpl_to_gds.rb"
    layer_map_json = layer_map_path_for_runset(runset)
    target_cats = target_categories if target_categories is not None else _default_target_categories(rule_type, layer)

    delta_nm = initial_delta_nm
    iterations: list[dict[str, Any]] = []
    converged = False
    iter_good_candidates = llm_good_candidates
    iter_bad_candidates = llm_bad_candidates
    iter_illegal_candidates = llm_illegal_candidates

    for idx in range(1, max_iters + 1):
        iter_dir = root / f"iter_{idx:02d}"
        case_dir = iter_dir / "cases"
        gds_dir = iter_dir / "gds"
        report_dir = iter_dir / "reports"
        log_dir = iter_dir / "logs"
        for d in (case_dir, gds_dir, report_dir, log_dir):
            d.mkdir(parents=True, exist_ok=True)

        cases = _generate_cases(
            generator=generator,
            rule_type=rule_type,
            layer=layer,
            secondary_layer=secondary_layer,
            threshold_nm=threshold_nm,
            delta_nm=delta_nm,
            rule_text=rule_text,
            llm_model=llm_model,
            llm_max_new_tokens=llm_max_new_tokens,
            llm_temperature=llm_temperature,
            llm_top_p=llm_top_p,
            llm_trust_remote_code=llm_trust_remote_code,
            llm_load_in_4bit=llm_load_in_4bit,
            llm_debug_dir=log_dir if generator == "llm" else None,
            llm_repair=llm_repair,
            llm_fallback=llm_fallback,
            llm_prompt_profile=llm_prompt_profile,
            llm_strict_response=llm_strict_response,
            tech_name=tech_name,
            llm_good_candidates=iter_good_candidates,
            llm_bad_candidates=iter_bad_candidates,
            llm_illegal_candidates=iter_illegal_candidates,
        )

        case_json_paths = write_cases(cases, case_dir, prefix=f"iter{idx:02d}")

        case_results: list[CaseRunResult] = []
        for case, case_json in zip(cases, case_json_paths):
            gds_path = gds_dir / f"{case.case_id}.gds"
            report_path = report_dir / f"{case.case_id}.lyrdb"

            gds_path_abs = gds_path.resolve()
            report_path_abs = report_path.resolve()

            case_dict = case.to_dict()
            geometry_valid = bool(case_dict["geometry_valid"])
            if not geometry_valid:
                match = evaluate_intent(
                    intent=case.intent,
                    geometry_valid=geometry_valid,
                    drc_items=None,
                )
                case_results.append(
                    CaseRunResult(
                        case_id=case.case_id,
                        intent=case.intent,
                        geometry_valid=geometry_valid,
                        gds_path=str(gds_path_abs),
                        report_path=str(report_path_abs),
                        drc_returncode=-1,
                        drc_items_total=None,
                        drc_items_target=None,
                        intent_match=match,
                        category_hits={},
                        drc_stdout_tail="skipped DRC: invalid geometry",
                        drc_stderr_tail="",
                    )
                )
                continue

            lpl_cmd = [
                _klayout_bin(),
                "-b",
                "-r",
                str(lpl_to_gds_script),
                "-rd",
                f"input_json={case_json}",
                "-rd",
                f"output_gds={gds_path_abs}",
                "-rd",
                f"top_cell={top_cell}",
                "-rd",
                f"layer_map_json={layer_map_json}",
                "-rd",
                f"dbu={dbu}",
            ]
            gds_res = run_cmd(lpl_cmd)
            (log_dir / f"{case.case_id}_lpl_to_gds.stdout.log").write_text(
                gds_res.stdout, encoding="utf-8"
            )
            (log_dir / f"{case.case_id}_lpl_to_gds.stderr.log").write_text(
                gds_res.stderr, encoding="utf-8"
            )
            if gds_res.returncode != 0:
                raise RuntimeError(
                    f"Failed to convert LPL->GDS for {case.case_id} (rc={gds_res.returncode})"
                )

            drc_cmd = [
                _klayout_bin(),
                "-b",
                "-r",
                str(runset),
                "-rd",
                f"input={gds_path_abs}",
                "-rd",
                f"report={report_path_abs}",
                "-rd",
                f"top_cell={top_cell}",
                "-rd",
                f"feol={str(feol).lower()}",
                "-rd",
                f"beol={str(beol).lower()}",
                "-rd",
                f"offgrid={str(offgrid).lower()}",
            ]
            if tech_name == "ihp_sg13g2":
                drc_cmd.extend(["-rd", f"topcell={top_cell}", "-rd", f"log={log_dir.resolve() / (case.case_id + '_runset.log')}",
                                "-rd", "threads=1", "-rd", "run_mode=flat",
                                "-rd", "fillerRules=true", "-rd", "latchUpRules=true", "-rd", "no_recommended=false"])
            if runset_defines:
                for key, value in sorted(runset_defines.items()):
                    drc_cmd.extend(["-rd", f"{key}={value}"])
            drc_res = run_cmd(drc_cmd)
            (log_dir / f"{case.case_id}_drc.stdout.log").write_text(
                drc_res.stdout, encoding="utf-8"
            )
            (log_dir / f"{case.case_id}_drc.stderr.log").write_text(
                drc_res.stderr, encoding="utf-8"
            )

            drc_items: int | None = None
            category_hits: dict[str, int] = {}
            has_engine_error = "ERROR:" in drc_res.stderr
            if drc_res.returncode == 0 and (not has_engine_error) and report_path_abs.exists():
                try:
                    drc_items, category_hits = parse_lyrdb_items(report_path_abs)
                except Exception:
                    drc_items = None
                    category_hits = {}

            if drc_items is None:
                drc_items_target: int | None = None
            elif target_cats:
                drc_items_target = sum(category_hits.get(cat, 0) for cat in target_cats)
            else:
                drc_items_target = drc_items

            match = evaluate_intent(
                intent=case.intent,
                geometry_valid=geometry_valid,
                drc_items=drc_items_target,
            )
            case_results.append(
                CaseRunResult(
                    case_id=case.case_id,
                    intent=case.intent,
                    geometry_valid=geometry_valid,
                    gds_path=str(gds_path_abs),
                    report_path=str(report_path_abs),
                    drc_returncode=(1 if has_engine_error else drc_res.returncode),
                    drc_items_total=drc_items,
                    drc_items_target=drc_items_target,
                    intent_match=match,
                    category_hits=category_hits,
                    drc_stdout_tail=drc_res.stdout[-1000:],
                    drc_stderr_tail=drc_res.stderr[-1000:],
                )
            )

        good_case = _case_by_intent(case_results, "GOOD")
        bad_case = _case_by_intent(case_results, "BAD")
        if good_case is None or bad_case is None:
            raise RuntimeError("Generated case set must include both GOOD and BAD intents.")

        good_ok = good_case.intent_match
        bad_ok = bad_case.intent_match
        iter_ok = good_ok and bad_ok
        good_target_hits = good_case.drc_items_target
        bad_target_hits = bad_case.drc_items_target

        next_delta, delta_action = _next_delta_nm(
            current_delta_nm=delta_nm,
            delta_step_nm=delta_step_nm,
            good_ok=good_ok,
            bad_ok=bad_ok,
            good_target_hits=good_target_hits,
            bad_target_hits=bad_target_hits,
        )
        next_good_candidates, next_bad_candidates, next_illegal_candidates, llm_actions = (
            _next_llm_candidate_counts(
                feedback_boost=(generator == "llm" and llm_feedback_boost),
                candidate_growth=llm_candidate_growth,
                max_candidates_per_intent=llm_max_candidates_per_intent,
                current_good=iter_good_candidates,
                current_bad=iter_bad_candidates,
                current_illegal=iter_illegal_candidates,
                good_ok=good_ok,
                bad_ok=bad_ok,
            )
        )

        iter_summary = {
            "iteration": idx,
            "delta_nm": delta_nm,
            "rule_type": rule_type,
            "layer": layer,
            "threshold_nm": threshold_nm,
            "generator": generator,
            "rule_text": rule_text,
            "llm_model": llm_model,
            "llm_repair": llm_repair,
            "llm_fallback": llm_repair if llm_fallback is None else llm_fallback,
            "llm_prompt_profile": llm_prompt_profile,
            "llm_strict_response": llm_strict_response,
            "llm_good_candidates": iter_good_candidates,
            "llm_bad_candidates": iter_bad_candidates,
            "llm_illegal_candidates": iter_illegal_candidates,
            "llm_feedback_boost": llm_feedback_boost,
            "target_categories": target_cats,
            "good_ok": good_ok,
            "bad_ok": bad_ok,
            "good_target_hits": good_target_hits,
            "bad_target_hits": bad_target_hits,
            "converged_this_iter": iter_ok,
            "next_delta_nm": next_delta,
            "delta_action": delta_action,
            "next_llm_good_candidates": next_good_candidates,
            "next_llm_bad_candidates": next_bad_candidates,
            "next_llm_illegal_candidates": next_illegal_candidates,
            "llm_feedback_actions": llm_actions,
            "cases": [asdict(r) for r in case_results],
        }
        if generator == "llm":
            iter_summary["model_calls"] = len(json.loads((log_dir / "generation_attempts.json").read_text()))
            iter_summary["generation_sources"] = [dict(case_id=case.case_id, intent=case.intent,
                source=("template_fallback" if "[model-fallback:" in case.description else
                        "template_repair" if "[repaired]" in case.description else "model"),
                description=case.description) for case in cases]
        iterations.append(iter_summary)
        (iter_dir / "iteration_summary.json").write_text(
            json.dumps(iter_summary, indent=2), encoding="utf-8"
        )

        if iter_ok:
            converged = True
            break
        delta_nm = next_delta
        iter_good_candidates = next_good_candidates
        iter_bad_candidates = next_bad_candidates
        iter_illegal_candidates = next_illegal_candidates

    final_summary = {
        "converged": converged,
        "iterations_run": len(iterations),
        "rule_type": rule_type,
        "layer": layer,
        "threshold_nm": threshold_nm,
        "generator": generator,
        "rule_text": rule_text,
        "llm_model": llm_model,
        "llm_repair": llm_repair,
        "llm_fallback": llm_repair if llm_fallback is None else llm_fallback,
        "llm_prompt_profile": llm_prompt_profile,
        "llm_strict_response": llm_strict_response,
        "llm_good_candidates": llm_good_candidates,
        "llm_bad_candidates": llm_bad_candidates,
        "llm_illegal_candidates": llm_illegal_candidates,
        "llm_feedback_boost": llm_feedback_boost,
        "llm_candidate_growth": llm_candidate_growth,
        "llm_max_candidates_per_intent": llm_max_candidates_per_intent,
        "target_categories": target_cats,
        "initial_delta_nm": initial_delta_nm,
        "delta_step_nm": delta_step_nm,
        "max_iters": max_iters,
        "runset_path": str(runset),
        "tech_name": tech_name,
        "layer_map_path": str(layer_map_json),
        "dbu_um": dbu,
        "iterations": iterations,
    }
    if generator == "llm":
        final_summary["model_calls"] = sum(it["model_calls"] for it in iterations)
    (root / "summary.json").write_text(json.dumps(final_summary, indent=2), encoding="utf-8")
    return final_summary


def _arg_parser() -> Any:
    import argparse

    p = argparse.ArgumentParser(
        description="Closed-loop Auto DRC runner: generate -> GDS -> DRC -> evaluate."
    )
    p.add_argument("--rule-text", help="Natural language rule text")
    p.add_argument("--rule-type", choices=["min_width", "min_spacing"])
    p.add_argument("--layer", default="met1")
    p.add_argument("--secondary-layer", help="Secondary layer for two-layer rules")
    p.add_argument("--threshold-nm", type=int, help="Threshold in nm")
    p.add_argument(
        "--generator",
        choices=["template", "llm"],
        default="template",
        help="Case generator backend: template or llm",
    )
    p.add_argument("--llm-model", help="HF model name/path used when --generator llm")
    p.add_argument("--llm-max-new-tokens", type=int, default=256)
    p.add_argument("--llm-temperature", type=float, default=0.2)
    p.add_argument("--llm-top-p", type=float, default=0.9)
    p.add_argument("--llm-good-candidates", type=int, default=1)
    p.add_argument("--llm-bad-candidates", type=int, default=3)
    p.add_argument("--llm-illegal-candidates", type=int, default=1)
    p.add_argument("--llm-trust-remote-code", action="store_true")
    p.add_argument("--llm-load-in-4bit", action="store_true")
    p.add_argument(
        "--llm-disable-repair",
        action="store_true",
        help="Disable rule-aware post-repair for LLM outputs.",
    )
    p.add_argument(
        "--llm-disable-feedback-boost",
        action="store_true",
        help="Disable DRC-feedback-driven candidate boosting between iterations.",
    )
    p.add_argument('--llm-fallback', choices=['auto','enabled','disabled'], default='auto',
        help='auto兼容旧行为；enabled/disabled独立控制无响应模板回退')
    p.add_argument('--llm-prompt-profile', choices=['legacy','compact','chat'], default='legacy')
    p.add_argument('--llm-strict-response', action='store_true')
    p.add_argument(
        "--llm-candidate-growth",
        type=int,
        default=1,
        help="Candidate increment per failed intent at each iteration.",
    )
    p.add_argument(
        "--llm-max-candidates-per-intent",
        type=int,
        default=6,
        help="Upper bound for GOOD/BAD/ILLEGAL candidate counts per iteration.",
    )
    p.add_argument("--initial-delta-nm", type=int, default=20)
    p.add_argument("--delta-step-nm", type=int, default=20)
    p.add_argument("--max-iters", type=int, default=3)
    p.add_argument("--out-dir", default="runs/closed_loop")
    p.add_argument("--runset", help="Path to a DRC runset")
    p.add_argument("--top-cell", default="TOP")
    p.add_argument("--feol", default="true", choices=["true", "false"])
    p.add_argument("--beol", default="true", choices=["true", "false"])
    p.add_argument("--offgrid", default="true", choices=["true", "false"])
    p.add_argument(
        "--target-category",
        action="append",
        default=None,
        help="Target DRC category ID to evaluate (repeatable).",
    )
    return p


def main() -> int:
    args = _arg_parser().parse_args()

    if args.generator == "llm" and not args.llm_model:
        raise SystemExit("--llm-model is required when --generator llm")

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

    summary = run_closed_loop(
        rule_type=rule_type,
        layer=layer,
        secondary_layer=args.secondary_layer,
        threshold_nm=threshold_nm,
        out_dir=Path(args.out_dir),
        initial_delta_nm=args.initial_delta_nm,
        delta_step_nm=args.delta_step_nm,
        max_iters=args.max_iters,
        runset_path=Path(args.runset) if args.runset else None,
        top_cell=args.top_cell,
        feol=(args.feol == "true"),
        beol=(args.beol == "true"),
        offgrid=(args.offgrid == "true"),
        target_categories=args.target_category,
        generator=args.generator,
        rule_text=args.rule_text,
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
        llm_prompt_profile=args.llm_prompt_profile,
        llm_strict_response=args.llm_strict_response,
        llm_feedback_boost=not args.llm_disable_feedback_boost,
        llm_candidate_growth=args.llm_candidate_growth,
        llm_max_candidates_per_intent=args.llm_max_candidates_per_intent,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
