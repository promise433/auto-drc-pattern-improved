from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autodrc.runset_corpus import RunsetRule
from autodrc.runset_coverage import classify_rule, infer_rule_type, run_runset_coverage
from autodrc.runset_semantics import RunsetOutputSemantic


class RunsetCoverageTests(unittest.TestCase):
    def _semantic(
        self,
        *,
        rule_id: str,
        description: str,
        expression: str,
        expression_refs: tuple[str, ...],
        upstream_vars: tuple[str, ...] = (),
    ) -> RunsetOutputSemantic:
        return RunsetOutputSemantic(
            rule_id=rule_id,
            description=description,
            line_no=1,
            source_file="x.drc",
            expression=expression,
            context_stack=(),
            block_path=(),
            required_defines=(),
            expression_refs=expression_refs,
            upstream_vars=upstream_vars,
            upstream_assignments=(),
            unresolved_refs=(),
        )

    def test_infer_rule_type_extensions(self) -> None:
        self.assertEqual(
            infer_rule_type("m1.x : floating met1, must interact with via1"),
            "must_interact",
        )
        self.assertEqual(
            infer_rule_type("moduleCut.1 : moduleCut layer is for SkyWater use only"),
            "forbidden_use",
        )
        self.assertEqual(
            infer_rule_type("licon.1_c : licon should be rectangle"),
            "forbidden_angle",
        )
        self.assertEqual(
            infer_rule_type("licon.13_a : licon on diff in periphery can't overlap npc"),
            "forbidden_overlap",
        )
        self.assertEqual(
            infer_rule_type("ct.3_a : max. width of ring-shaped mcon : 0.175um"),
            "max_width",
        )

    def test_classify_must_interact(self) -> None:
        rule = RunsetRule(
            rule_id="m2.x",
            description="floating met2, must interact with via1 or via2",
            line_no=1,
            threshold_nm=None,
            layer_hint="met2",
            source_file="x.drc",
        )
        layer_map = {"met2", "via", "via2"}
        info = classify_rule(rule, layer_map)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "must_interact")
        self.assertEqual(info["layer"], "met2")
        self.assertIn(info["layer_b"], {"via", "via2"})

    def test_classify_m1_must_interact_prefers_mcon(self) -> None:
        rule = RunsetRule(
            rule_id="m1.x",
            description="floating met1, must interact with via1",
            line_no=1,
            threshold_nm=None,
            layer_hint="met1",
            source_file="x.drc",
        )
        layer_map = {"met1", "via", "mcon"}
        info = classify_rule(rule, layer_map)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "must_interact")
        self.assertEqual(info["layer"], "met1")
        self.assertEqual(info["layer_b"], "mcon")

    def test_classify_capm_spacing_prefers_capm_over_via_token(self) -> None:
        rule = RunsetRule(
            rule_id="capm.5",
            description="capm.5 : min. capm spacing to via3 : 0.14um",
            line_no=1,
            threshold_nm=None,
            layer_hint="unknown",
            source_file="x.drc",
        )
        layer_map = {"capm", "via3"}
        info = classify_rule(rule, layer_map)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_spacing")
        self.assertEqual(info["layer"], "capm")

    def test_classify_m4_must_interact_prefers_via_over_metal(self) -> None:
        rule = RunsetRule(
            rule_id="m4.x",
            description="floating met3, must interact with via3 or via4",
            line_no=1,
            threshold_nm=None,
            layer_hint="met4",
            source_file="x.drc",
        )
        layer_map = {"met4", "met3", "via3", "via4"}
        info = classify_rule(rule, layer_map)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "must_interact")
        self.assertEqual(info["layer"], "met4")
        self.assertIn(info["layer_b"], {"via3", "via4"})

    def test_classify_forbidden_use(self) -> None:
        rule = RunsetRule(
            rule_id="moduleCut.1",
            description="moduleCut.1 : moduleCut layer is for SkyWater use only",
            line_no=1,
            threshold_nm=None,
            layer_hint="modulecut",
            source_file="x.drc",
        )
        layer_map = {"modulecut"}
        info = classify_rule(rule, layer_map)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "forbidden_use")
        self.assertEqual(info["layer"], "modulecut")

    def test_classify_via4_enclose_all_pair_order(self) -> None:
        rule = RunsetRule(
            rule_id="via4.4_a",
            description="via4.4_a : m4 must enclose all via4",
            line_no=1,
            threshold_nm=None,
            layer_hint="met4",
            source_file="x.drc",
        )
        layer_map = {"m4", "met4", "via4"}
        info = classify_rule(rule, layer_map)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "via_enclosure")
        self.assertEqual(info["layer_b"], "via4")
        self.assertIn(info["layer"], {"m4", "met4"})
        self.assertNotEqual(info["layer"], info["layer_b"])

    def test_classify_min_enclosure_enclosure_of_order(self) -> None:
        rule = RunsetRule(
            rule_id="m1.4",
            description="m1.4 : min. m1 enclosure of mcon : 0.03um",
            line_no=1,
            threshold_nm=None,
            layer_hint="met1",
            source_file="x.drc",
        )
        layer_map = {"m1", "met1", "mcon"}
        info = classify_rule(rule, layer_map)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_enclosure")
        self.assertEqual(info["layer_b"], "mcon")
        self.assertIn(info["layer"], {"m1", "met1"})

    def test_classify_min_enclosure_of_by_maps_nwellhole(self) -> None:
        rule = RunsetRule(
            rule_id="nwell.6",
            description="nwell.6 : min enclosure of nwellHole by dnwell : 1.03um",
            line_no=1,
            threshold_nm=None,
            layer_hint="nwell",
            source_file="x.drc",
        )
        layer_map = {"nwell", "dnwell"}
        info = classify_rule(rule, layer_map)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_enclosure")
        self.assertEqual(info["layer"], "dnwell")
        self.assertEqual(info["layer_b"], "nwell")

    def test_classify_via_enclosure_prefers_semantic_specific_via_layer(self) -> None:
        rule = RunsetRule(
            rule_id="via2.4_a",
            description="via2.4_a : via must be enclosed by met2",
            line_no=1,
            threshold_nm=None,
            layer_hint="met2",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="via2.not(m2)",
            expression_refs=("via2", "m2"),
            upstream_vars=("via2", "m2"),
        )
        layer_map = {"m2", "met2", "via", "via2"}
        info = classify_rule(rule, layer_map, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "via_enclosure")
        self.assertEqual(info["layer_b"], "via2")
        self.assertIn(info["layer"], {"m2", "met2"})

    def test_classify_min_width_prefers_semantic_specific_layer(self) -> None:
        rule = RunsetRule(
            rule_id="MR_li.WID.4",
            description="MR_li.WID.4 : li:res minimum width : 0.29um",
            line_no=1,
            threshold_nm=None,
            layer_hint="li1",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression='log("START") li_res.width(0.29, euclidian)',
            expression_refs=("li_res",),
            upstream_vars=("li_res",),
        )
        layer_map = {"li1", "li_res"}
        info = classify_rule(rule, layer_map, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_width")
        self.assertEqual(info["layer"], "li_res")

    def test_classify_across_areaid_width_prefers_semantic_diff_implant_layer(self) -> None:
        rule = RunsetRule(
            rule_id="nsdm.3",
            description="nsdm.3 : min. diff width across areaid:ce : 0.38um",
            line_no=1,
            threshold_nm=None,
            layer_hint="diff",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="nsdm.width(0.38, euclidian).polygons.interacting(areaid_ce_merged)",
            expression_refs=("nsdm", "areaid_ce_merged"),
            upstream_vars=("nsdm", "areaid_ce", "areaid_ce_merged"),
        )
        layer_map = {"diff", "nsdm", "areaid_ce"}
        info = classify_rule(rule, layer_map, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_width")
        self.assertEqual(info["layer"], "nsdm")

    def test_classify_prec_resistor_spacing_prefers_licon_from_semantic_prefix(self) -> None:
        rule = RunsetRule(
            rule_id="MR_licon.SP.1",
            description="MR_licon.SP.1: min. licon spacing in periphery : 0.17um",
            line_no=1,
            threshold_nm=None,
            layer_hint="poly",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="licon_peri.not(prec_resistor).space(0.17, euclidian)",
            expression_refs=("licon_peri", "prec_resistor"),
            upstream_vars=("licon", "prec_resistor"),
        )
        layer_map = {"poly", "licon", "prec_resistor"}
        info = classify_rule(rule, layer_map, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_spacing")
        self.assertEqual(info["layer"], "licon")

    def test_classify_m1_4a_a_ignores_semantic_not_pair_for_enclosure(self) -> None:
        rule = RunsetRule(
            rule_id="m1.4a_a",
            description="m1.4a_a : mcon periph must be enclosed by met1 for specific cells",
            line_no=1,
            threshold_nm=None,
            layer_hint="met1",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="in_cell6_m1.not(m1)",
            expression_refs=("in_cell6_m1", "m1"),
            upstream_vars=("in_cell6_m1", "m1", "mcon"),
        )
        layer_map = {"m1", "met1", "mcon"}
        info = classify_rule(rule, layer_map, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_enclosure")
        self.assertEqual(info["layer_b"], "mcon")
        self.assertIn(info["layer"], {"m1", "met1"})

    def test_runset_coverage_summary_includes_unique_rule_id_metrics(self) -> None:
        runset_text = """
m1.width(0.14).output("dup.1", "dup.1 : min. m1 width : 0.14um")
m1.width(0.14).output("dup.1", "dup.1 : min. m1 width : 0.14um")
m1.width(0.14).output("relax.1", "relax.1 : min. m1 width : 0.14um")
m1.width(0.14).output("solo.1", "solo.1 : min. m1 width : 0.14um")
m1.width(0.14).output("unsup.1", "unsup.1 : custom check without known keyword")
"""

        def _summary(*, converged: bool, good_ok: bool, bad_ok: bool) -> dict[str, object]:
            return {
                "iterations": [{"good_ok": good_ok, "bad_ok": bad_ok}],
                "iterations_run": 1,
                "converged": converged,
            }

        side_effect = [
            _summary(converged=True, good_ok=True, bad_ok=True),
            _summary(converged=False, good_ok=False, bad_ok=False),
            _summary(converged=False, good_ok=True, bad_ok=False),
            _summary(converged=False, good_ok=False, bad_ok=False),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            runset_path = Path(tmp) / "x.drc"
            out_dir = Path(tmp) / "out"
            runset_path.write_text(runset_text, encoding="utf-8")
            with patch("autodrc.runset_coverage.run_closed_loop", side_effect=side_effect):
                result = run_runset_coverage(
                    runset_path=runset_path,
                    out_dir=out_dir,
                    max_iters=1,
                )

        summary = result["summary"]
        self.assertEqual(summary["total_rules"], 5)
        self.assertEqual(summary["supported_rules"], 4)
        self.assertEqual(summary["covered_rules"], 1)
        self.assertEqual(summary["covered_rules_relaxed"], 2)

        self.assertEqual(summary["unique_rule_ids_total"], 4)
        self.assertEqual(summary["unique_rule_ids_supported"], 3)
        self.assertEqual(summary["unique_rule_ids_covered"], 1)
        self.assertEqual(summary["unique_rule_ids_covered_relaxed"], 2)
        self.assertAlmostEqual(summary["unique_support_rate"], 0.75)
        self.assertAlmostEqual(summary["unique_coverage_rate"], 0.25)
        self.assertAlmostEqual(summary["unique_coverage_rate_relaxed"], 0.5)
        self.assertTrue(summary["semantic_alignment_ok"])
        self.assertEqual(summary["rules_with_semantic_expression"], 5)
        self.assertEqual(summary["rules_with_semantic_context"], 0)

        first_row = result["rows"][0]
        self.assertIn("runset_expression", first_row)
        self.assertIn("runset_context_stack", first_row)
        self.assertIn("runset_expression_refs", first_row)
        self.assertIn("runset_upstream_assignments", first_row)
        self.assertIn("runset_unresolved_refs", first_row)

    def test_runset_coverage_infers_defines_from_context(self) -> None:
        runset_text = """
if FLOATING_MET
  m1.not_interacting(via).output("m1.x", "floating met1, must interact with via1")
end
"""

        summary = {
            "iterations": [{"good_ok": True, "bad_ok": True}],
            "iterations_run": 1,
            "converged": True,
        }

        with tempfile.TemporaryDirectory() as tmp:
            runset_path = Path(tmp) / "x.drc"
            out_dir = Path(tmp) / "out"
            runset_path.write_text(runset_text, encoding="utf-8")
            with patch("autodrc.runset_coverage.run_closed_loop", return_value=summary) as mocked:
                result = run_runset_coverage(
                    runset_path=runset_path,
                    out_dir=out_dir,
                    max_iters=1,
                )

        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs.get("runset_defines"), {"floating_met": "true"})
        self.assertEqual(result["rows"][0]["runset_defines"], {"floating_met": "true"})

    def test_runset_coverage_passes_llm_options(self) -> None:
        runset_text = """
m1.width(0.14).output("m1.1", "m1.1 : min. m1 width : 0.14um")
"""
        summary = {
            "iterations": [{"good_ok": True, "bad_ok": True}],
            "iterations_run": 1,
            "converged": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            runset_path = Path(tmp) / "x.drc"
            out_dir = Path(tmp) / "out"
            runset_path.write_text(runset_text, encoding="utf-8")
            with patch("autodrc.runset_coverage.run_closed_loop", return_value=summary) as mocked:
                result = run_runset_coverage(
                    runset_path=runset_path,
                    out_dir=out_dir,
                    generator="llm",
                    llm_model="models/TinyLlama-1.1B-Chat-v1.0",
                    llm_max_new_tokens=64,
                    llm_temperature=0.4,
                    llm_top_p=0.8,
                    llm_trust_remote_code=True,
                    llm_load_in_4bit=False,
                    llm_repair=False,
                    llm_feedback_boost=False,
                    llm_candidate_growth=2,
                    llm_max_candidates_per_intent=7,
                    max_iters=1,
                )
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["generator"], "llm")
        self.assertEqual(kwargs["llm_model"], "models/TinyLlama-1.1B-Chat-v1.0")
        self.assertEqual(kwargs["llm_max_new_tokens"], 64)
        self.assertEqual(kwargs["llm_temperature"], 0.4)
        self.assertEqual(kwargs["llm_top_p"], 0.8)
        self.assertTrue(kwargs["llm_trust_remote_code"])
        self.assertFalse(kwargs["llm_load_in_4bit"])
        self.assertFalse(kwargs["llm_repair"])
        self.assertFalse(kwargs["llm_feedback_boost"])
        self.assertEqual(kwargs["llm_candidate_growth"], 2)
        self.assertEqual(kwargs["llm_max_candidates_per_intent"], 7)
        self.assertEqual(result["summary"]["llm_max_new_tokens"], 64)

    def test_runset_coverage_adds_cap2m_enclosure_alias_target(self) -> None:
        runset_text = '''
m4.enclosing(cap2m, 0.14, euclidian).output("cap2m.3", "cap2m.3 : min. m4 enclosure of cap2m : 0.14um")
'''
        summary = {
            "iterations": [{"good_ok": True, "bad_ok": True}],
            "iterations_run": 1,
            "converged": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            runset_path = Path(tmp) / "x.drc"
            out_dir = Path(tmp) / "out"
            runset_path.write_text(runset_text, encoding="utf-8")
            with patch("autodrc.runset_coverage.run_closed_loop", return_value=summary) as mocked:
                run_runset_coverage(
                    runset_path=runset_path,
                    out_dir=out_dir,
                    max_iters=1,
                )

        self.assertEqual(mocked.call_args.kwargs["target_categories"], ["cap2m.3", "cap2m.3_a"])

    def test_runset_coverage_filters_by_rule_ids(self) -> None:
        runset_text = """
m1.width(0.14).output("m1.1", "m1.1 : min. m1 width : 0.14um")
m2.width(0.14).output("m2.1", "m2.1 : min. m2 width : 0.14um")
m3.width(0.14).output("m3.1", "m3.1 : min. m3 width : 0.14um")
"""
        summary = {
            "iterations": [{"good_ok": True, "bad_ok": True}],
            "iterations_run": 1,
            "converged": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            runset_path = Path(tmp) / "x.drc"
            out_dir = Path(tmp) / "out"
            runset_path.write_text(runset_text, encoding="utf-8")
            with patch("autodrc.runset_coverage.run_closed_loop", return_value=summary) as mocked:
                result = run_runset_coverage(
                    runset_path=runset_path,
                    out_dir=out_dir,
                    rule_ids=["m1.1", "m3.1"],
                    max_iters=1,
                )

        self.assertEqual(result["summary"]["total_rules"], 2)
        self.assertEqual(result["summary"]["rule_ids"], ["m1.1", "m3.1"])
        self.assertEqual([row["rule_id"] for row in result["rows"]], ["m1.1", "m3.1"])
        self.assertEqual(mocked.call_count, 2)

    def test_runset_coverage_filters_by_rule_id_regex(self) -> None:
        runset_text = """
m1.width(0.14).output("m1.1", "m1.1 : min. m1 width : 0.14um")
m2.width(0.14).output("m2.1", "m2.1 : min. m2 width : 0.14um")
m3.width(0.14).output("m3.1", "m3.1 : min. m3 width : 0.14um")
"""
        summary = {
            "iterations": [{"good_ok": True, "bad_ok": True}],
            "iterations_run": 1,
            "converged": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            runset_path = Path(tmp) / "x.drc"
            out_dir = Path(tmp) / "out"
            runset_path.write_text(runset_text, encoding="utf-8")
            with patch("autodrc.runset_coverage.run_closed_loop", return_value=summary) as mocked:
                result = run_runset_coverage(
                    runset_path=runset_path,
                    out_dir=out_dir,
                    rule_id_regex=r"^m[12]\.",
                    max_iters=1,
                )

        self.assertEqual(result["summary"]["total_rules"], 2)
        self.assertEqual(result["summary"]["rule_id_regex"], r"^m[12]\.")
        self.assertEqual([row["rule_id"] for row in result["rows"]], ["m1.1", "m2.1"])
        self.assertEqual(mocked.call_count, 2)

    def test_runset_coverage_resume_reuses_existing_rule_summary(self) -> None:
        runset_text = """
m1.width(0.14).output("m1.1", "m1.1 : min. m1 width : 0.14um")
m2.width(0.14).output("m2.1", "m2.1 : min. m2 width : 0.14um")
"""
        cached_summary = {
            "iterations": [{"good_ok": True, "bad_ok": True}],
            "iterations_run": 1,
            "converged": True,
            "generator": "template",
        }
        fresh_summary = {
            "iterations": [{"good_ok": True, "bad_ok": True}],
            "iterations_run": 1,
            "converged": True,
            "generator": "template",
        }
        with tempfile.TemporaryDirectory() as tmp:
            runset_path = Path(tmp) / "x.drc"
            out_dir = Path(tmp) / "out"
            runset_path.write_text(runset_text, encoding="utf-8")
            cached_path = out_dir / "rules" / "m1.1"
            cached_path.mkdir(parents=True, exist_ok=True)
            (cached_path / "summary.json").write_text(
                json.dumps(cached_summary), encoding="utf-8"
            )
            with patch("autodrc.runset_coverage.run_closed_loop", return_value=fresh_summary) as mocked:
                result = run_runset_coverage(
                    runset_path=runset_path,
                    out_dir=out_dir,
                    max_iters=1,
                    resume=True,
                )

        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(mocked.call_args.kwargs["target_categories"], ["m2.1"])
        rows_by_id = {row["rule_id"]: row for row in result["rows"]}
        self.assertTrue(rows_by_id["m1.1"]["resumed_from_summary"])
        self.assertFalse(rows_by_id["m2.1"]["resumed_from_summary"])
        self.assertEqual(result["summary"]["resumed_rules_from_summary"], 1)

    def test_runset_coverage_resume_reuses_cached_rows_file(self) -> None:
        runset_text = """
m1.width(0.14).output("m1.1", "m1.1 : min. m1 width : 0.14um")
"""
        summary = {
            "iterations": [{"good_ok": True, "bad_ok": True}],
            "iterations_run": 1,
            "converged": True,
            "generator": "template",
        }
        with tempfile.TemporaryDirectory() as tmp:
            runset_path = Path(tmp) / "x.drc"
            out_dir = Path(tmp) / "out"
            runset_path.write_text(runset_text, encoding="utf-8")

            with patch("autodrc.runset_coverage.run_closed_loop", return_value=summary):
                run_runset_coverage(
                    runset_path=runset_path,
                    out_dir=out_dir,
                    max_iters=1,
                )

            with patch("autodrc.runset_coverage.run_closed_loop", return_value=summary) as mocked:
                result = run_runset_coverage(
                    runset_path=runset_path,
                    out_dir=out_dir,
                    max_iters=1,
                    resume=True,
                )

        self.assertEqual(mocked.call_count, 0)
        self.assertEqual(result["summary"]["resumed_rows_from_cache"], 1)
        self.assertTrue(result["rows"][0]["resumed_from_cache"])

    def test_resume_rerun_not_covered_recomputes_cached_relaxed_rows(self) -> None:
        runset_text = """
m1.width(0.14).output("m1.1", "m1.1 : min. m1 width : 0.14um")
"""
        relaxed_summary = {
            "iterations": [{"good_ok": True, "bad_ok": False}],
            "iterations_run": 1,
            "converged": False,
            "generator": "template",
        }
        strict_summary = {
            "iterations": [{"good_ok": True, "bad_ok": True}],
            "iterations_run": 1,
            "converged": True,
            "generator": "template",
        }
        with tempfile.TemporaryDirectory() as tmp:
            runset_path = Path(tmp) / "x.drc"
            out_dir = Path(tmp) / "out"
            runset_path.write_text(runset_text, encoding="utf-8")

            with patch("autodrc.runset_coverage.run_closed_loop", return_value=relaxed_summary):
                first = run_runset_coverage(
                    runset_path=runset_path,
                    out_dir=out_dir,
                    max_iters=1,
                )
            self.assertEqual(first["rows"][0]["status"], "covered_relaxed")

            with patch("autodrc.runset_coverage.run_closed_loop", return_value=strict_summary) as mocked:
                second = run_runset_coverage(
                    runset_path=runset_path,
                    out_dir=out_dir,
                    max_iters=1,
                    resume=True,
                    resume_rerun_not_covered=True,
                )

        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(second["rows"][0]["status"], "covered")
        self.assertFalse(second["rows"][0].get("resumed_from_cache", False))
        self.assertEqual(second["summary"]["resumed_rows_from_cache"], 0)
        self.assertTrue(second["summary"]["resume_rerun_not_covered"])

    def test_classify_via2_5_prefers_m2_override(self) -> None:
        rule = RunsetRule(
            rule_id="via2.5",
            description="via2.5 : min. m3 enclosure of via2 of 2 adjacent edges : 0.085um",
            line_no=1,
            threshold_nm=None,
            layer_hint="unknown",
            source_file="x.drc",
        )
        layer_map = {"m2", "met3", "via2"}
        info = classify_rule(rule, layer_map)
        self.assertTrue(info["supported"])
        self.assertEqual(info["layer"], "m2")
        self.assertEqual(info["layer_b"], "via2")

    def test_runset_coverage_uses_special_top_cell_for_m1_4a(self) -> None:
        runset_text = """
 in_cell6_m1.enclosing(mcon, 0.005, euclidian).output(
     "m1.4a",
     "m1.4a : min. m1 enclosure of mcon for specific cells : 0.005um"
 )
 """
        summary = {
            "iterations": [{"good_ok": True, "bad_ok": True}],
            "iterations_run": 1,
            "converged": True,
        }
        with tempfile.TemporaryDirectory() as tmp:
            runset_path = Path(tmp) / "x.drc"
            out_dir = Path(tmp) / "out"
            runset_path.write_text(runset_text, encoding="utf-8")
            with patch("autodrc.runset_coverage.run_closed_loop", return_value=summary) as mocked:
                run_runset_coverage(
                    runset_path=runset_path,
                    out_dir=out_dir,
                    max_iters=1,
                )

        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(mocked.call_args.kwargs["top_cell"], "s8cell_ee_plus_sseln_a")


if __name__ == "__main__":
    unittest.main()
