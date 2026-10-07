from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autodrc.runset_corpus import RunsetRule
from autodrc.runset_coverage import (
    _exact_target_status,
    _parse_layer_aliases,
    _resolve_layer_token,
    classify_rule,
    infer_rule_type,
    infer_threshold,
    run_runset_coverage,
)
from autodrc.runset_semantics import RunsetOutputSemantic


class RunsetCoverageTests(unittest.TestCase):
    def test_exact_target_does_not_accept_legacy_alias_or_invalid_layout(self) -> None:
        for target,alias in (("cap2m.3","cap2m.3_a"),("m1.4a_a","m1.4a")):
            good=dict(intent="GOOD",geometry_valid=True,drc_returncode=0,category_hits={})
            bad=dict(intent="BAD",geometry_valid=True,drc_returncode=0,category_hits={alias:1})
            summary=dict(converged=True,iterations=[dict(good_ok=True,bad_ok=True,cases=[good,bad])])
            self.assertFalse(_exact_target_status(summary,target)["exact_target_strict"])
            bad["category_hits"]={target:1}
            self.assertTrue(_exact_target_status(summary,target)["exact_target_strict"])
            bad["geometry_valid"]=False
            self.assertFalse(_exact_target_status(summary,target)["exact_target_strict"])
            bad["geometry_valid"]=True
            bad["drc_returncode"]=1
            self.assertFalse(_exact_target_status(summary,target)["exact_target_strict"])

    def test_legacy_success_without_cases_has_no_exact_target_evidence(self) -> None:
        summary=dict(converged=True,iterations=[dict(good_ok=True,bad_ok=True)])
        status=_exact_target_status(summary,"m1.1")
        self.assertFalse(status["exact_target_evidence"])
        self.assertFalse(status["exact_target_strict"])

    def test_resume_detects_ld_library_path_engine_library_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runset = root / "x.drc"
            runset.write_text('m1.width(0.14).output("m1.1", "min. m1 width : 0.14um")')
            library = root / "libklayout_test.so"
            library.write_bytes(b"first")
            summary = dict(generator="template",converged=True,iterations_run=1,
                           iterations=[dict(good_ok=True,bad_ok=True)])
            options = dict(runset_path=runset,out_dir=root/"output")
            with patch.dict("os.environ", {"LD_LIBRARY_PATH":str(root),"AUTO_DRC_KLAYOUT_LD_LIBRARY_PATH":""}), patch(
                "autodrc.runset_coverage.run_closed_loop",return_value=summary
            ) as loop:
                run_runset_coverage(**options)
                run_runset_coverage(**options,resume=True)
                self.assertEqual(loop.call_count,1)
                library.write_bytes(b"other")
                run_runset_coverage(**options,resume=True)
                self.assertEqual(loop.call_count,2)

    def test_resume_detects_same_path_model_and_engine_content_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            runset=root/"x.drc"
            runset.write_text('m1.width(0.14).output("m1.1", "min. m1 width : 0.14um")')
            model=root/"model"
            model.mkdir()
            weights=model/"weights.safetensors"
            weights.write_bytes(b"first")
            engine=root/"klayout"
            engine.write_bytes(b"first")
            summary=dict(generator="llm",llm_model=str(model),converged=True,iterations_run=1,
                         iterations=[dict(good_ok=True,bad_ok=True)])
            options=dict(runset_path=runset,out_dir=root/"output",generator="llm",llm_model=str(model))
            with patch("autodrc.runset_coverage._klayout_bin",return_value=str(engine)), patch(
                "autodrc.runset_coverage.run_closed_loop",return_value=summary
            ) as loop:
                run_runset_coverage(**options)
                run_runset_coverage(**options,resume=True)
                self.assertEqual(loop.call_count,1)
                weights.write_bytes(b"other")
                run_runset_coverage(**options,resume=True)
                self.assertEqual(loop.call_count,2)
                engine.write_bytes(b"other")
                run_runset_coverage(**options,resume=True)
                self.assertEqual(loop.call_count,3)

    def test_duplicate_ids_keep_separate_artifacts_and_summary_resume(self) -> None:
        text = ('m1.width(0.14).output("dup.1", "min. m1 width : 0.14um")\n'
                'm1.width(0.20).output("dup.1", "min. m1 width : 0.20um")\n')
        def loop(**kwargs):
            directory = kwargs["out_dir"]
            directory.mkdir(parents=True, exist_ok=True)
            result = dict(generator="template", iterations_run=1, converged=True,
                          rule_text=kwargs["rule_text"], iterations=[dict(good_ok=True, bad_ok=True)])
            (directory / "summary.json").write_text(json.dumps(result))
            return result
        with tempfile.TemporaryDirectory() as tmp:
            runset = Path(tmp) / "x.drc"
            output = Path(tmp) / "out"
            runset.write_text(text)
            with patch("autodrc.runset_coverage.run_closed_loop", side_effect=loop) as mocked:
                first = run_runset_coverage(runset_path=runset, out_dir=output)
                self.assertEqual(mocked.call_count, 2)
            directories = [Path(row["run_dir"]) for row in first["rows"]]
            self.assertNotEqual(*directories)
            self.assertNotEqual((directories[0]/"summary.json").read_text(), (directories[1]/"summary.json").read_text())
            with patch("autodrc.runset_coverage.run_closed_loop", side_effect=loop) as mocked:
                resumed = run_runset_coverage(runset_path=runset, out_dir=output, resume=True)
                mocked.assert_not_called()
                self.assertEqual(resumed["summary"]["resumed_rows_from_cache"], 2)
            (output/"coverage_rows.jsonl").unlink()
            with patch("autodrc.runset_coverage.run_closed_loop", side_effect=loop) as mocked:
                resumed = run_runset_coverage(runset_path=runset, out_dir=output, resume=True)
                mocked.assert_not_called()
                self.assertEqual(resumed["summary"]["resumed_rules_from_summary"], 2)
            self.assertEqual([row["run_dir"] for row in resumed["rows"]], [str(p) for p in directories])

    def test_resume_recomputes_when_generation_parameters_or_runset_change(self) -> None:
        text = 'm1.width(0.14).output("m1.1", "min. m1 width : 0.14um")\n'
        summary = dict(generator="template", iterations_run=1, converged=True,
                       iterations=[dict(good_ok=True, bad_ok=True)])
        with tempfile.TemporaryDirectory() as tmp:
            runset = Path(tmp) / "x.drc"
            output = Path(tmp) / "out"
            runset.write_text(text)
            with patch("autodrc.runset_coverage.run_closed_loop", return_value=summary):
                run_runset_coverage(runset_path=runset, out_dir=output)
            with patch("autodrc.runset_coverage.run_closed_loop", return_value=summary) as mocked:
                changed = run_runset_coverage(runset_path=runset, out_dir=output, resume=True, initial_delta_nm=60)
                self.assertEqual(mocked.call_count, 1)
                self.assertFalse(changed["rows"][0].get("resumed_from_cache", False))
            runset.write_text(text.replace("width(0.14)", "width(0.15)"))
            with patch("autodrc.runset_coverage.run_closed_loop", return_value=summary) as mocked:
                run_runset_coverage(runset_path=runset, out_dir=output, resume=True, initial_delta_nm=60)
                self.assertEqual(mocked.call_count, 1)

    def test_sky_hv_marker_enclosure_keeps_distinct_layers(self) -> None:
        description = "nwell.9 : HVnwell must be enclosed by hv marker"
        rule = RunsetRule("nwell.9", description, 332, None, "unknown", "sky130A_mr.drc")
        semantic = self._semantic(
            rule_id=rule.rule_id, description=description,
            expression="nwell .interacting(nwell.and(hvmarker)) .not(hvmarker)",
            expression_refs=("nwell", "hvmarker"),
            upstream_vars=("nwell", "hvi", "rdl", "vhvi", "uhvi", "hvmarker"),
        )
        info = classify_rule(rule, {"nwell", "hvi", "rdl", "vhvi", "uhvi"}, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual((info["layer"], info["layer_b"]), ("hvi", "nwell"))

    def test_sky_straddle_retains_template_layer_orientation(self) -> None:
        rule = RunsetRule("MR_lvtn.OVL.2", "MR_lvtn.OVL.2 : lvtn must not straddle nwell",
                          387, None, "unknown", "sky130A_mr.drc")
        info = classify_rule(rule, {"lvtn", "nwell"})
        self.assertTrue(info["supported"])
        self.assertEqual((info["layer"], info["layer_b"]), ("nwell", "lvtn"))

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
        self.assertEqual(
            infer_rule_type("5.5. Act.b : Min. Activ space or notch: 0.21 µm."),
            "min_spacing",
        )
        self.assertEqual(
            infer_rule_type("Min. ThickGateOx extension over Activ = 0.27"),
            "min_enclosure",
        )
        self.assertEqual(
            infer_rule_type("Min. Activ drain/source extension = 0.23"),
            "min_enclosure",
        )
        self.assertEqual(
            infer_rule_type("Cont must be within Activ or GatPoly"),
            "min_enclosure",
        )
        self.assertEqual(
            infer_rule_type("Cont must be covered with Metal1"),
            "min_enclosure",
        )
        self.assertEqual(
            infer_rule_type("45-degree and 90-degree angles for GatPoly on Activ area are not allowed"),
            "forbidden_angle",
        )
        self.assertEqual(
            infer_rule_type("Max. Activ:filler width = 5.00"),
            "max_width",
        )
        self.assertEqual(
            infer_rule_type("Min. ContBar length = 0.34"),
            "min_length",
        )
        self.assertEqual(
            infer_rule_type("Max. MIM area per MIM device (µm²) = 5625.00"),
            "max_area",
        )
        self.assertEqual(
            infer_rule_type("TopVia1 must be over MIM"),
            "via_enclosure",
        )

    def test_infer_threshold_supports_area_unit_before_value(self) -> None:
        self.assertEqual(infer_threshold("min_area", "Min. Activ area (µm²) = 0.122"), 122000)
        self.assertEqual(infer_threshold("max_area", "Max. MIM area per MIM device (µm²) = 5625.00"), 5625000000)

    def test_parse_layer_aliases_reads_ihp_source_polygons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runset_path = Path(tmp) / "sg13g2_maximal.drc"
            runset_path.write_text(
                'metal5 = source.polygons("67/0")\n'
                'topvia2 = source.polygons("133/0")\n',
                encoding="utf-8",
            )
            aliases = _parse_layer_aliases(runset_path, {})
        self.assertEqual(aliases["metal5"], (67, 0))
        self.assertEqual(aliases["topvia2"], (133, 0))

    def test_resolve_layer_token_uses_ihp_alias_only_in_ihp_context(self) -> None:
        self.assertEqual(_resolve_layer_token("cntb", {"contbar", "cont"}), "contbar")
        self.assertIsNone(_resolve_layer_token("cntb", {"met1", "mcon", "diff"}))

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

    def test_classify_extension_over_prefers_semantic_enclosure_pair(self) -> None:
        rule = RunsetRule(
            rule_id="TGO.a",
            description="Min. ThickGateOx extension over Activ = 0.27",
            line_no=1,
            threshold_nm=None,
            layer_hint="thickgateox",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="Activ.ext_enclosed(ThickGateOx, 0.27.um)",
            expression_refs=("activ", "thickgateox"),
            upstream_vars=("activ", "thickgateox"),
        )
        layer_map = {"activ", "thickgateox"}
        info = classify_rule(rule, layer_map, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_enclosure")
        self.assertEqual(info["layer"], "thickgateox")
        self.assertEqual(info["layer_b"], "activ")

    def test_classify_cover_only_within_rule(self) -> None:
        rule = RunsetRule(
            rule_id="Cnt.g",
            description="Cont must be within Activ or GatPoly",
            line_no=1,
            threshold_nm=None,
            layer_hint="cont",
            source_file="x.drc",
        )
        layer_map = {"cont", "activ", "gatpoly"}
        info = classify_rule(rule, layer_map)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_enclosure")
        self.assertEqual(info["layer_b"], "cont")
        self.assertEqual(info["layer"], "activ")

    def test_classify_sky130_does_not_adopt_ihp_text_layers(self) -> None:
        rule = RunsetRule(
            rule_id="Act.a",
            description="Min. Activ width = 0.62",
            line_no=1,
            threshold_nm=None,
            layer_hint="unknown",
            source_file="x.drc",
        )
        info = classify_rule(rule, {"met1", "diff", "poly"})
        self.assertFalse(info["supported"])
        self.assertEqual(info["reason"], "unknown_layer")

    def test_classify_min_length_uses_contbar_layer(self) -> None:
        rule = RunsetRule(
            rule_id="CntB.a1",
            description="Min. ContBar length = 0.34",
            line_no=1,
            threshold_nm=None,
            layer_hint="unknown",
            source_file="x.drc",
        )
        layer_map = {"cont", "contbar"}
        info = classify_rule(rule, layer_map)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_length")
        self.assertEqual(info["layer"], "contbar")
        self.assertEqual(info["threshold_nm"], 340)

    def test_classify_pwell_block_width_prefers_specific_text_layer(self) -> None:
        rule = RunsetRule(
            rule_id="PWB.a",
            description="Min. PWell:block width = 0.62",
            line_no=1,
            threshold_nm=None,
            layer_hint="unknown",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="PWell_block_PWB_a.dup",
            expression_refs=("pwell_block_pwb_a",),
            upstream_vars=("pwell", "pwellblock"),
        )
        info = classify_rule(rule, {"pwell", "pwellblock"}, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_width")
        self.assertEqual(info["layer"], "pwellblock")
        self.assertEqual(info["threshold_nm"], 620)

    def test_classify_nbulay_width_prefers_prefix_aligned_semantic_layer(self) -> None:
        rule = RunsetRule(
            rule_id="NBL.a",
            description="Min. nBuLay width = 1.00",
            line_no=1,
            threshold_nm=None,
            layer_hint="unknown",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="nBuLayGen_nBuLay_NBL_a.dup",
            expression_refs=("nbulaygen_nbulay_nbl_a",),
            upstream_vars=("nwell", "nbulay", "nbulay_block"),
        )
        info = classify_rule(rule, {"nwell", "nbulay", "nbulay_block"}, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_width")
        self.assertEqual(info["layer"], "nbulay")
        self.assertEqual(info["threshold_nm"], 1000)

    def test_classify_spacing_prefers_subject_layer_over_inside_context(self) -> None:
        rule = RunsetRule(
            rule_id="NW.d1",
            description="Min. NWell space to external N+Activ inside ThickGateOx = 0.62",
            line_no=1,
            threshold_nm=None,
            layer_hint="unknown",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="NWell.ext_separation(NActHV_ana, 0.62.um)",
            expression_refs=("nwell", "nacthv_ana"),
            upstream_vars=("activ", "nwell", "thickgateox"),
        )
        info = classify_rule(rule, {"activ", "nwell", "thickgateox"}, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_spacing")
        self.assertEqual(info["layer"], "nwell")

    def test_classify_psd_spacing_prefers_subject_layer_over_inside_context(self) -> None:
        rule = RunsetRule(
            rule_id="pSD.j1",
            description="Min. pSD space to NFET gate inside ThickGateOx = 0.40",
            line_no=1,
            threshold_nm=None,
            layer_hint="unknown",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="pSD_Nsram.ext_separation(NGate_outside_SVaricap.inside(ThickGateOx), 0.4.um)",
            expression_refs=("psd_nsram", "ngate_outside_svaricap", "thickgateox"),
            upstream_vars=("psd", "gatpoly", "thickgateox"),
        )
        info = classify_rule(rule, {"psd", "gatpoly", "thickgateox"}, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_spacing")
        self.assertEqual(info["layer"], "psd")

    def test_classify_width_prefers_subject_layer_over_semantic_context(self) -> None:
        rule = RunsetRule(
            rule_id="Rppd.a",
            description="Min. GatPoly width = 0.50",
            line_no=1,
            threshold_nm=None,
            layer_hint="unknown",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="Rppd_all.ext_width(0.5.um)",
            expression_refs=("rppd_all",),
            upstream_vars=("activ", "gatpoly", "psd", "salblock"),
        )
        info = classify_rule(rule, {"activ", "gatpoly", "psd", "salblock"}, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_width")
        self.assertEqual(info["layer"], "gatpoly")

    def test_classify_nsd_block_width_prefers_subject_layer(self) -> None:
        rule = RunsetRule(
            rule_id="nmosi.f",
            description="Min. nSD:block width to separate ptap in nmosi = 0.62",
            line_no=1,
            threshold_nm=None,
            layer_hint="unknown",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="nSDBlock_Iso_PWell_Act.ext_width(0.62.um)",
            expression_refs=("nsdblock_iso_pwell_act",),
            upstream_vars=("activ", "nsd_block", "nbulay", "pwell_block"),
        )
        info = classify_rule(rule, {"activ", "nsd_block", "nbulay", "pwell_block"}, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_width")
        self.assertEqual(info["layer"], "nsd_block")

    def test_classify_via3_array_spacing_prefers_subject_layer(self) -> None:
        rule = RunsetRule(
            rule_id="V3.b1",
            description=(
                "Min. Via3 space in an array of more than 3 rows and more then 3 columns "
                "(V3.b1 is only required in one direction. The distance of the other "
                "direction must be at least V3.b.) = 0.29"
            ),
            line_no=1,
            threshold_nm=None,
            layer_hint="unknown",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="via3SepErr_2.ext_or(via3In.ext_touching(via3SepErr_2))",
            expression_refs=("via3seperr_2", "via3in"),
            upstream_vars=("edgeseal", "via3", "via3array"),
        )
        info = classify_rule(rule, {"edgeseal", "via3"}, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_spacing")
        self.assertEqual(info["layer"], "via3")

    def test_classify_via4_array_spacing_prefers_subject_layer(self) -> None:
        rule = RunsetRule(
            rule_id="V4.b1",
            description=(
                "Min. Via4 space in an array of more than 3 rows and more then 3 columns "
                "(V4.b1 is only required in one direction. The distance of the other "
                "direction must be at least V4.b.) = 0.29"
            ),
            line_no=1,
            threshold_nm=None,
            layer_hint="unknown",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="via4SepErr_2.ext_or(via4In.ext_touching(via4SepErr_2))",
            expression_refs=("via4seperr_2", "via4in"),
            upstream_vars=("edgeseal", "via4", "via4array"),
        )
        info = classify_rule(rule, {"edgeseal", "via4"}, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_spacing")
        self.assertEqual(info["layer"], "via4")

    def test_classify_topmetal1_max_width_prefers_text_specific_layer(self) -> None:
        rule = RunsetRule(
            rule_id="Slt.c.TM1",
            description="Max. TopMetal1 width without requiring a slit = 30.00",
            line_no=1,
            threshold_nm=None,
            layer_hint="unknown",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="tM1_L2.sized(15.um, acute_limit)",
            expression_refs=("tm1_l2",),
            upstream_vars=("mim", "topmetal1", "topmetal1_slit"),
        )
        info = classify_rule(
            rule,
            {"mim", "topmetal1", "topmetal1_slit"},
            semantic=semantic,
        )
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "max_width")
        self.assertEqual(info["layer"], "topmetal1")
        self.assertEqual(info["threshold_nm"], 30000)

    def test_classify_seal_width_keeps_semantic_primary_layer(self) -> None:
        rule = RunsetRule(
            rule_id="Seal.a_Metal1",
            description="Min. EdgeSeal-Metal1 width = 3.50",
            line_no=1,
            threshold_nm=None,
            layer_hint="unknown",
            source_file="x.drc",
        )
        semantic = self._semantic(
            rule_id=rule.rule_id,
            description=rule.description,
            expression="Metal1_edgA1_in.ext_width(3.5.um, metric: projection)",
            expression_refs=("metal1_edga1_in", "metric"),
            upstream_vars=("metal1", "edgeseal"),
        )
        info = classify_rule(rule, {"metal1", "edgeseal"}, semantic=semantic)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_width")
        self.assertEqual(info["layer"], "metal1")
        self.assertEqual(info["threshold_nm"], 3500)

    def test_classify_max_area_rule(self) -> None:
        rule = RunsetRule(
            rule_id="MIM.g",
            description="Max. MIM area per MIM device (µm²) = 5625.00",
            line_no=1,
            threshold_nm=None,
            layer_hint="mim",
            source_file="x.drc",
        )
        layer_map = {"mim"}
        info = classify_rule(rule, layer_map)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "max_area")
        self.assertEqual(info["layer"], "mim")
        self.assertEqual(info["threshold_nm"], 5625000000)

    def test_classify_cover_only_via_over_rule(self) -> None:
        rule = RunsetRule(
            rule_id="MIM.h",
            description="TopVia1 must be over MIM",
            line_no=1,
            threshold_nm=None,
            layer_hint="mim",
            source_file="x.drc",
        )
        layer_map = {"mim", "topvia1"}
        info = classify_rule(rule, layer_map)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "via_enclosure")
        self.assertEqual(info["layer"], "mim")
        self.assertEqual(info["layer_b"], "topvia1")

    def test_classify_zero_threshold_uses_small_epsilon(self) -> None:
        rule = RunsetRule(
            rule_id="nSDB.e",
            description="Min. nSD:block space to Cont = 0.00",
            line_no=1,
            threshold_nm=None,
            layer_hint="cont",
            source_file="x.drc",
        )
        layer_map = {"cont"}
        info = classify_rule(rule, layer_map)
        self.assertTrue(info["supported"])
        self.assertEqual(info["rule_type"], "min_spacing")
        self.assertEqual(info["threshold_nm"], 1)

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
            # Create the identity evidence required by reliable summary resume.
            with patch("autodrc.runset_coverage.run_closed_loop", return_value=cached_summary):
                run_runset_coverage(runset_path=runset_path, out_dir=out_dir, max_iters=1, rule_ids=["m1.1"])
            (out_dir / "coverage_rows.jsonl").unlink()
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
