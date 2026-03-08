from __future__ import annotations

import unittest

from autodrc.casegen import (
    PatternCase,
    generate_forbidden_angle_cases,
    generate_min_width_cases,
)
from autodrc.llm_policy import adjust_llm_cases, select_best_llm_case
from autodrc.lpl import rectangle
from autodrc.rules import ParsedRule


class LLMPolicyTests(unittest.TestCase):
    def test_adjust_min_width_cases(self) -> None:
        bad_good = PatternCase(
            case_id="x_good",
            intent="GOOD",
            description="bad good",
            polygons=(rectangle("met1", 0, 0, 400, 100),),
        )
        bad_bad = PatternCase(
            case_id="x_bad",
            intent="BAD",
            description="bad bad",
            polygons=(rectangle("met1", 0, 0, 400, 200),),
        )
        illegal = PatternCase(
            case_id="x_illegal",
            intent="ILLEGAL",
            description="illegal",
            polygons=generate_min_width_cases(layer="met1", min_width_nm=140)[2].polygons,
        )
        rule = ParsedRule(
            rule_type="min_width",
            layer="met1",
            threshold_nm=140,
            source_text="Minimum width 0.14um on met1",
        )
        adjusted = adjust_llm_cases(base_cases=[bad_good, bad_bad, illegal], rule=rule)
        self.assertEqual(len(adjusted), 3)
        self.assertEqual(adjusted[0].intent, "GOOD")
        self.assertEqual(adjusted[1].intent, "BAD")
        self.assertIn("repaired", adjusted[0].description)

    def test_adjust_forbidden_use_cases(self) -> None:
        bad_good = PatternCase(
            case_id="u_good",
            intent="GOOD",
            description="should be empty but uses modulecut",
            polygons=(rectangle("modulecut", 0, 0, 100, 100),),
        )
        bad_bad = PatternCase(
            case_id="u_bad",
            intent="BAD",
            description="should use modulecut but empty",
            polygons=(),
        )
        illegal_wrong = PatternCase(
            case_id="u_illegal",
            intent="ILLEGAL",
            description="illegal but actually legal",
            polygons=(rectangle("modulecut", 0, 0, 100, 100),),
        )
        rule = ParsedRule(
            rule_type="forbidden_use",
            layer="modulecut",
            threshold_nm=1,
            source_text="moduleCut layer is for SkyWater use only",
        )
        adjusted = adjust_llm_cases(
            base_cases=[bad_good, bad_bad, illegal_wrong],
            rule=rule,
        )
        self.assertEqual(len(adjusted[0].polygons), 0)  # GOOD fallback: no use
        self.assertGreater(len(adjusted[1].polygons), 0)  # BAD fallback: must use
        self.assertIn("repaired", adjusted[2].description)  # ILLEGAL fallback

    def test_select_best_llm_case_prefers_intent_match(self) -> None:
        rule = ParsedRule(
            rule_type="min_width",
            layer="met1",
            threshold_nm=140,
            source_text="Minimum width 0.14um on met1",
        )
        bad_good = PatternCase(
            case_id="cand0",
            intent="GOOD",
            description="too narrow",
            polygons=(rectangle("met1", 0, 0, 400, 100),),
        )
        good_good = PatternCase(
            case_id="cand1",
            intent="GOOD",
            description="wide enough",
            polygons=(rectangle("met1", 0, 0, 400, 180),),
        )
        picked = select_best_llm_case(candidates=[bad_good, good_good], rule=rule)
        self.assertEqual(picked.case_id, "cand1")

    def test_adjust_preserves_allow_non_manhattan_after_repair(self) -> None:
        wrong_good = PatternCase(
            case_id="a_good",
            intent="GOOD",
            description="wrong good",
            polygons=generate_forbidden_angle_cases(layer="licon", allowed_angle_deg=90)[1].polygons,
        )
        wrong_bad = PatternCase(
            case_id="a_bad",
            intent="BAD",
            description="wrong bad",
            polygons=generate_forbidden_angle_cases(layer="licon", allowed_angle_deg=90)[0].polygons,
        )
        wrong_illegal = PatternCase(
            case_id="a_illegal",
            intent="ILLEGAL",
            description="wrong illegal",
            polygons=(rectangle("licon", 0, 0, 100, 100),),
        )
        rule = ParsedRule(
            rule_type="forbidden_angle",
            layer="licon",
            threshold_nm=90,
            source_text="licon should be rectangle",
        )
        adjusted = adjust_llm_cases(
            base_cases=[wrong_good, wrong_bad, wrong_illegal],
            rule=rule,
        )
        bad_case = next(case for case in adjusted if case.intent == "BAD")
        self.assertTrue(bad_case.allow_non_manhattan)
        self.assertTrue(bad_case.to_dict()["geometry_valid"])

    def test_adjust_must_interact_forces_good_template(self) -> None:
        llm_good = PatternCase(
            case_id="mi_good",
            intent="GOOD",
            description="llm good",
            polygons=(rectangle("met1", 0, 0, 200, 200),),
        )
        llm_bad = PatternCase(
            case_id="mi_bad",
            intent="BAD",
            description="llm bad",
            polygons=(rectangle("met1", 0, 0, 200, 200),),
        )
        llm_illegal = PatternCase(
            case_id="mi_illegal",
            intent="ILLEGAL",
            description="llm illegal",
            polygons=(rectangle("met1", 0, 0, 200, 200),),
        )
        rule = ParsedRule(
            rule_type="must_interact",
            layer="met1",
            threshold_nm=40,
            source_text="floating met1, must interact with via1",
        )
        adjusted = adjust_llm_cases(
            base_cases=[llm_good, llm_bad, llm_illegal],
            rule=rule,
            secondary_layer="mcon",
            rule_text="floating met1, must interact with via1",
        )
        good_case = next(case for case in adjusted if case.intent == "GOOD")
        self.assertIn("repaired", good_case.description)
        used_layers = {poly.layer for poly in good_case.polygons}
        self.assertIn("met1", used_layers)
        self.assertIn("mcon", used_layers)

    def test_adjust_min_width_forces_template_bad_even_when_geometry_matches(self) -> None:
        llm_good = PatternCase(
            case_id="mw_good",
            intent="GOOD",
            description="llm good",
            polygons=(rectangle("met1", 0, 0, 400, 180),),
        )
        llm_bad = PatternCase(
            case_id="mw_bad",
            intent="BAD",
            description="llm bad already narrow",
            polygons=(rectangle("met1", 0, 0, 400, 100),),
        )
        llm_illegal = PatternCase(
            case_id="mw_illegal",
            intent="ILLEGAL",
            description="llm illegal",
            polygons=generate_min_width_cases(layer="met1", min_width_nm=140)[2].polygons,
        )
        rule = ParsedRule(
            rule_type="min_width",
            layer="met1",
            threshold_nm=140,
            source_text="Minimum width 0.14um on met1",
        )
        adjusted = adjust_llm_cases(
            base_cases=[llm_good, llm_bad, llm_illegal],
            rule=rule,
        )
        bad_case = next(case for case in adjusted if case.intent == "BAD")
        self.assertIn("repaired", bad_case.description)

    def test_context_markers_skip_layer_alias_of_primary_layer(self) -> None:
        llm_good = PatternCase(
            case_id="alias_good",
            intent="GOOD",
            description="good",
            polygons=(rectangle("met1", 0, 0, 400, 180),),
        )
        llm_bad = PatternCase(
            case_id="alias_bad",
            intent="BAD",
            description="bad",
            polygons=(rectangle("met1", 0, 0, 400, 100),),
        )
        llm_illegal = PatternCase(
            case_id="alias_illegal",
            intent="ILLEGAL",
            description="illegal",
            polygons=generate_min_width_cases(layer="met1", min_width_nm=140)[2].polygons,
        )
        rule_text = (
            "Rule ID: m1.1\n"
            "Description: m1.1 : min. m1 width : 0.14um\n"
            "Runset expression: m1.width(0.14, euclidian)"
        )
        rule = ParsedRule(
            rule_type="min_width",
            layer="met1",
            threshold_nm=140,
            source_text=rule_text,
        )
        adjusted = adjust_llm_cases(
            base_cases=[llm_good, llm_bad, llm_illegal],
            rule=rule,
            rule_text=rule_text,
        )
        bad_case = next(case for case in adjusted if case.intent == "BAD")
        bad_layers = {poly.layer for poly in bad_case.polygons}
        self.assertIn("met1", bad_layers)
        self.assertNotIn("m1", bad_layers)

    def test_adjust_max_length_min_max_prefers_exact_threshold(self) -> None:
        llm_good = PatternCase(
            case_id="ml_good",
            intent="GOOD",
            description="llm good but shorter",
            polygons=(rectangle("licon", 0, 0, 150, 60),),
        )
        llm_bad = PatternCase(
            case_id="ml_bad",
            intent="BAD",
            description="llm bad longer",
            polygons=(rectangle("licon", 0, 0, 220, 60),),
        )
        llm_illegal = PatternCase(
            case_id="ml_illegal",
            intent="ILLEGAL",
            description="llm illegal",
            polygons=(rectangle("licon", 0, 0, 200, 200),),
        )
        rule = ParsedRule(
            rule_type="max_length",
            layer="licon",
            threshold_nm=170,
            source_text="licon.1: min/max. licon length : 0.17um",
        )
        adjusted = adjust_llm_cases(
            base_cases=[llm_good, llm_bad, llm_illegal],
            rule=rule,
            rule_text=rule.source_text,
        )
        good_case = next(case for case in adjusted if case.intent == "GOOD")
        good_points = good_case.to_dict()["lpl"][0]["points"]
        good_len = max(
            abs(good_points[1][0] - good_points[0][0]),
            abs(good_points[2][1] - good_points[1][1]),
        )
        self.assertEqual(good_len, 170)

    def test_context_markers_keep_negated_layers_separate(self) -> None:
        llm_good = PatternCase(
            case_id="neg_good",
            intent="GOOD",
            description="good",
            polygons=(rectangle("dnwell", 0, 0, 4000, 4000),),
        )
        llm_bad = PatternCase(
            case_id="neg_bad",
            intent="BAD",
            description="bad",
            polygons=(rectangle("dnwell", 0, 0, 4000, 4000),),
        )
        llm_illegal = PatternCase(
            case_id="neg_illegal",
            intent="ILLEGAL",
            description="illegal",
            polygons=generate_min_width_cases(layer="dnwell", min_width_nm=3000)[2].polygons,
        )
        rule_text = (
            "Rule ID: dnwell.2\n"
            "Description: dnwell.2 : min. dnwell spacing : 6.3um\n"
            "Runset expression: dnwell.not(uhvi.or(vhvi)).space(6.3, euclidian)"
        )
        rule = ParsedRule(
            rule_type="min_spacing",
            layer="dnwell",
            threshold_nm=6300,
            source_text=rule_text,
        )
        adjusted = adjust_llm_cases(
            base_cases=[llm_good, llm_bad, llm_illegal],
            rule=rule,
            rule_text=rule_text,
        )
        bad_case = next(case for case in adjusted if case.intent == "BAD").to_dict()["lpl"]
        dnwell_max_x = max(point[0] for poly in bad_case if poly["layer"] == "dnwell" for point in poly["points"])
        marker_min_x = min(point[0] for poly in bad_case if poly["layer"] in {"uhvi", "vhvi"} for point in poly["points"])
        self.assertGreater(marker_min_x, dnwell_max_x)

    def test_context_markers_skip_alias_of_existing_case_layer(self) -> None:
        llm_good = PatternCase(
            case_id="alias2_good",
            intent="GOOD",
            description="good",
            polygons=(rectangle("capm", 0, 0, 1000, 1000), rectangle("met3", 1400, 0, 300, 600)),
        )
        llm_bad = PatternCase(
            case_id="alias2_bad",
            intent="BAD",
            description="bad",
            polygons=(rectangle("capm", 0, 0, 1000, 1000), rectangle("met3", 1400, 0, 300, 600)),
        )
        llm_illegal = PatternCase(
            case_id="alias2_illegal",
            intent="ILLEGAL",
            description="illegal",
            polygons=generate_min_width_cases(layer="met1", min_width_nm=140)[2].polygons,
        )
        rule_text = (
            "Rule ID: capm.11\n"
            "Description: capm.11 : Min spacing of capm and met3 not overlapping capm : 0.5um\n"
            "Runset expression: (m3.not_interacting(capm)).separation(capm, 0.5, euclidian)"
        )
        rule = ParsedRule(
            rule_type="min_spacing",
            layer="capm",
            threshold_nm=500,
            source_text=rule_text,
        )
        adjusted = adjust_llm_cases(
            base_cases=[llm_good, llm_bad, llm_illegal],
            rule=rule,
            rule_text=rule_text,
        )
        bad_layers = {poly.layer for poly in next(case for case in adjusted if case.intent == "BAD").polygons}
        self.assertIn("met3", bad_layers)
        self.assertNotIn("m3", bad_layers)

    def test_adjust_cover_only_rule_disables_context_markers(self) -> None:
        llm_good = PatternCase(
            case_id="ce_good",
            intent="GOOD",
            description="llm good",
            polygons=(rectangle("nwell", 0, 0, 400, 400), rectangle("hvi", 0, 0, 400, 400)),
        )
        llm_bad = PatternCase(
            case_id="ce_bad",
            intent="BAD",
            description="llm bad",
            polygons=(rectangle("nwell", 0, 0, 400, 400), rectangle("hvi", 200, 0, 200, 400)),
        )
        llm_illegal = PatternCase(
            case_id="ce_illegal",
            intent="ILLEGAL",
            description="llm illegal",
            polygons=(rectangle("nwell", 0, 0, 100, 100),),
        )
        rule_text = (
            "Rule ID: nwell.9\n"
            "Description: nwell.9 : HVnwell must be enclosed by hv marker\n"
            "Runset expression: nwell.interacting(nwell.and(hvmarker)).not(hvmarker)\n"
            "Upstream chain: hvi = polygons(75, 20) | rdl = polygons(74, 20) | vhvi = polygons(74, 21) | uhvi = polygons(74, 22)"
        )
        rule = ParsedRule(
            rule_type="min_enclosure",
            layer="hvi",
            threshold_nm=60,
            source_text=rule_text,
        )
        adjusted = adjust_llm_cases(
            base_cases=[llm_good, llm_bad, llm_illegal],
            rule=rule,
            secondary_layer="nwell",
            rule_text=rule_text,
        )
        bad_case = next(case for case in adjusted if case.intent == "BAD")
        bad_layers = {poly.layer for poly in bad_case.polygons}
        self.assertEqual(bad_layers, {"nwell", "hvi"})

    def test_adjust_prec_resistor_spacing_skips_context_markers(self) -> None:
        llm_good = PatternCase(
            case_id="mr_good",
            intent="GOOD",
            description="llm good",
            polygons=(rectangle("licon", 0, 0, 170, 170), rectangle("licon", 220, 0, 170, 170)),
        )
        llm_bad = PatternCase(
            case_id="mr_bad",
            intent="BAD",
            description="llm bad",
            polygons=(rectangle("licon", 0, 0, 170, 170), rectangle("licon", 150, 0, 170, 170)),
        )
        llm_illegal = PatternCase(
            case_id="mr_illegal",
            intent="ILLEGAL",
            description="llm illegal",
            polygons=(rectangle("licon", 0, 0, 100, 100),),
        )
        rule_text = (
            "Rule ID: MR_licon.SP.1\n"
            "Description: MR_licon.SP.1: min. licon spacing in periphery : 0.17um\n"
            "Runset expression: licon_peri.not(prec_resistor).space(0.17, euclidian)"
        )
        rule = ParsedRule(
            rule_type="min_spacing",
            layer="licon",
            threshold_nm=170,
            source_text=rule_text,
        )
        adjusted = adjust_llm_cases(
            base_cases=[llm_good, llm_bad, llm_illegal],
            rule=rule,
            rule_text=rule_text,
        )
        bad_case = next(case for case in adjusted if case.intent == "BAD")
        bad_layers = {poly.layer for poly in bad_case.polygons}
        self.assertEqual(bad_layers, {"licon"})


if __name__ == "__main__":
    unittest.main()
