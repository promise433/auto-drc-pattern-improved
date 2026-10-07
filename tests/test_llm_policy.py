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
    def _verified_bad_inputs(self):
        from autodrc.casegen import generate_cases_for_rule
        for layer, partner, threshold, text in (
            ("m1", "via", 55, "Runset expression: m1 .edges .enclosing(rectVIA.drc(width == 0.15), 0.055, euclidian)"),
            ("m2", "via2", 85, "Runset expression: via2_interact\nUpstream chain: via2_edges_with_less_enclosure = m2.enclosing(via2, 0.085, projection).second_edges"),
        ):
            rule = ParsedRule("via_enclosure", layer, threshold, text)
            cases = generate_cases_for_rule(rule_type=rule.rule_type, layer=layer,
                layer_b=partner, threshold_nm=threshold, delta_nm=20, rule_text=text)
            yield rule, partner, cases

    def test_verified_sky_bad_preserves_complete_correct_candidate(self):
        for rule, partner, cases in self._verified_bad_inputs():
            candidate = cases[1]
            fixed = adjust_llm_cases(base_cases=[candidate], rule=rule, secondary_layer=partner)[0]
            self.assertIs(fixed, candidate)

    def test_verified_sky_bad_replaces_missing_operands_and_wrong_shape(self):
        from dataclasses import replace
        for rule, partner, cases in self._verified_bad_inputs():
            expected = cases[1]
            for candidate in (replace(expected, polygons=expected.polygons[:1]),
                    replace(expected, polygons=(rectangle(rule.layer, 0, 0, 400, 160),)),
                    replace(expected, allow_non_manhattan=True)):
                fixed = adjust_llm_cases(base_cases=[candidate], rule=rule, secondary_layer=partner)[0]
                self.assertEqual(fixed.polygons, expected.polygons)
                self.assertEqual(fixed.labels, expected.labels)
                self.assertEqual(fixed.allow_non_manhattan, expected.allow_non_manhattan)
                self.assertIn("[sky-verified-bad;delta=20]", fixed.description)

    def test_explicit_sky_policy_preserves_requested_delta(self):
        from autodrc.casegen import generate_cases_for_rule
        from autodrc.llm_policy import LLMPolicy
        for rule, partner, cases in self._verified_bad_inputs():
            for delta in (40, 60):
                fixed = adjust_llm_cases(base_cases=[cases[1]], rule=rule,
                    secondary_layer=partner, policy=LLMPolicy(repair_delta_nm=delta))[0]
                expected = generate_cases_for_rule(rule_type=rule.rule_type, layer=rule.layer,
                    layer_b=partner, threshold_nm=rule.threshold_nm, delta_nm=delta, rule_text=rule.source_text)[1]
                self.assertEqual(fixed.polygons, expected.polygons)

    def test_verified_bad_does_not_change_good_or_illegal(self):
        from autodrc.llm_policy import LLMPolicy
        for rule, partner, cases in self._verified_bad_inputs():
            for candidate in (cases[0], cases[2]):
                self.assertEqual(adjust_llm_cases(base_cases=[candidate], rule=rule, secondary_layer=partner),
                    adjust_llm_cases(base_cases=[candidate], rule=rule, secondary_layer=partner, policy=LLMPolicy()))

    def test_same_named_expression_requires_verified_upstream_branch(self):
        from autodrc.llm_policy import LLMPolicy
        for text in ("Runset expression: via2_interact",
                "Runset expression: via2_interact\nUpstream chain: m1.enclosing(via,0.085,projection).second_edges"):
            rule = ParsedRule("via_enclosure", "m2", 85, text)
            candidate = PatternCase("model", "BAD", "model", (rectangle("m2", 0, 0, 400, 160),))
            self.assertEqual(adjust_llm_cases(base_cases=[candidate], rule=rule, secondary_layer="via2"),
                adjust_llm_cases(base_cases=[candidate], rule=rule, secondary_layer="via2", policy=LLMPolicy()))

    def test_sky_licon_core_bad_keeps_complete_template_without_diff_tap_markers(self) -> None:
        from autodrc.casegen import generate_cases_for_rule
        for expression in ("npc.enclosing(polyLicon1_CORE,0.045,euclidian)", "polyLicon1_CORE.not(npc)"):
            text = "Runset expression: " + expression + "\nUpstream chain: difftap=diff.or(tap); polylicon1_core=licon.and(poly).and(areaid_ce)"
            rule = ParsedRule(rule_type="min_enclosure",layer="npc",threshold_nm=45,source_text=text)
            candidate = PatternCase(case_id="model_bad",intent="BAD",description="model",polygons=(rectangle("npc",0,0,400,160),))
            fixed = adjust_llm_cases(base_cases=[candidate],rule=rule,secondary_layer="poly")[0]
            expected = generate_cases_for_rule(rule_type=rule.rule_type,layer="npc",layer_b="poly",threshold_nm=45,delta_nm=60,rule_text=text)[1]
            self.assertEqual(fixed.polygons,expected.polygons)
            self.assertEqual({p.layer for p in fixed.polygons},{"licon","poly","areaid_ce","npc"})

    def test_sky_unscored_good_uses_full_template_operands(self) -> None:
        from autodrc.casegen import generate_cases_for_rule
        for kind,layer,partner,threshold,text in (
            ("via_enclosure","m2","via2",40,"Runset expression: m2.enclosing(via2,0.04,euclidian)"),
            ("min_enclosure","m1","mcon",30,"Runset expression: m1.enclosing(mcon,0.03,euclidian)"),
            ("forbidden_overlap","thkox","diff",20,"Runset expression: thkox.interacting(diff).not_inside(diff).edges.and(diff)"),
            ("max_width","via",None,205,"Description: max width of ring-shaped via\nRunset expression: ringVIA.drc(width >= 0.205)"),
        ):
            rule=ParsedRule(rule_type=kind,layer=layer,threshold_nm=threshold,source_text=text)
            candidate=PatternCase(case_id="model",intent="GOOD",description="model",polygons=(rectangle(layer,0,0,400,160),))
            fixed=adjust_llm_cases(base_cases=[candidate],rule=rule,secondary_layer=partner)[0]
            expected=generate_cases_for_rule(rule_type=kind,layer=layer,layer_b=partner,threshold_nm=threshold,delta_nm=20,rule_text=text)[0]
            self.assertIn("[repaired]",fixed.description)
            self.assertEqual(fixed.polygons,expected.polygons)

    def test_sky_offgrid_good_requires_active_on_grid_vertices(self) -> None:
        rule=ParsedRule(rule_type="offgrid_vertex",layer="met1",threshold_nm=5,source_text="Runset expression: m1.ongrid(0.005)")
        for x in (0,1):
            candidate=PatternCase(case_id="model",intent="GOOD",description="model",polygons=(rectangle("met1",x,0,400,160),))
            fixed=adjust_llm_cases(base_cases=[candidate],rule=rule)[0]
            if x==0:
                self.assertEqual(fixed,candidate)
            else:
                self.assertIn("[repaired]",fixed.description)
                self.assertTrue(all(px%5==0 and py%5==0 for p in fixed.polygons for px,py in p.points))

    def test_cap2m_good_cannot_bypass_intersection_context(self) -> None:
        text="Runset expression: cap2m.and(m4).enclosing(m4,0.14,euclidian)"
        rule=ParsedRule(rule_type="min_enclosure",layer="m4",threshold_nm=140,source_text=text)
        candidate=PatternCase(case_id="model",intent="GOOD",description="model",
            polygons=(rectangle("m4",0,0,2000,2000),))
        fixed=adjust_llm_cases(base_cases=[candidate],rule=rule,secondary_layer="cap2m")[0]
        self.assertIn("[repaired]",fixed.description)
        self.assertEqual({p.layer for p in fixed.polygons},{"cap2m","m4"})

    def test_sky_angle_good_cannot_bypass_actual_region_branch(self) -> None:
        for layer in ("diff", "tap"):
            for operator, angle in (("and",45),("not",90)):
                text=f"Runset expression: {layer}.{operator}(areaid_en.and(uhvi)).with_angle(0..{angle})"
                rule=ParsedRule(rule_type="forbidden_angle",layer=layer,threshold_nm=angle,source_text=text)
                candidate=PatternCase(case_id="model",intent="GOOD",description="model",
                    polygons=(rectangle(layer,0,0,400,400),rectangle("uhvi",0,0,1000,1000),rectangle("areaid_en",0,0,1000,1000)))
                fixed=adjust_llm_cases(base_cases=[candidate],rule=rule)[0]
                self.assertIn("[repaired]",fixed.description)
                self.assertEqual({p.layer for p in fixed.polygons},{layer,"uhvi","areaid_en"} if operator=="and" else {layer})

    def test_pwde_good_without_hv_context_is_repaired(self) -> None:
        text = "Runset expression: pwde.and(uhvi.or(vhvi)).space(1.27, euclidian)"
        rule = ParsedRule(rule_type="min_spacing",layer="pwde",threshold_nm=1270,source_text=text)
        candidate = PatternCase(case_id="model",intent="GOOD",description="model",
            polygons=(rectangle("pwde",0,0,1000,1000),rectangle("pwde",2400,0,1000,1000)))
        fixed = adjust_llm_cases(base_cases=[candidate],rule=rule)[0]
        self.assertIn("[repaired]",fixed.description)
        self.assertEqual([p.layer for p in fixed.polygons],["pwde","pwde","uhvi"])

    def test_geometric_good_does_not_bypass_verified_core_context(self) -> None:
        text = "Runset expression: diff.inside(areaid_ce).width(0.14, euclidian)"
        rule = ParsedRule(rule_type="min_width",layer="diff",threshold_nm=140,source_text=text)
        for context in ((),(rectangle("areaid_ce",10000,10000,500,500),)):
            candidate = PatternCase(case_id="model_good",intent="GOOD",description="model",
                polygons=(rectangle("diff",0,0,400,180),)+context)
            fixed = adjust_llm_cases(base_cases=[candidate],rule=rule)[0]
            self.assertIn("[repaired]",fixed.description)
            core=next(p for p in fixed.polygons if p.layer=="areaid_ce")
            shape=next(p for p in fixed.polygons if p.layer=="diff")
            self.assertTrue(all(min(x for x,y in core.points)<x<max(x for x,y in core.points)
                and min(y for x,y in core.points)<y<max(y for x,y in core.points) for x,y in shape.points))
        simple_rule = ParsedRule(rule_type="min_width",layer="met1",threshold_nm=140,source_text="met1 minimum width 0.14um")
        simple = PatternCase(case_id="simple",intent="GOOD",description="model",polygons=(rectangle("met1",0,0,600,180),))
        self.assertEqual(adjust_llm_cases(base_cases=[simple],rule=simple_rule)[0],simple)

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
            tech_name="ihp_sg13g2",
        )
        good_case = next(case for case in adjusted if case.intent == "GOOD")
        good_points = good_case.to_dict()["lpl"][0]["points"]
        good_len = max(
            abs(good_points[1][0] - good_points[0][0]),
            abs(good_points[2][1] - good_points[1][1]),
        )
        self.assertEqual(good_len, 170)

    def test_adjust_max_width_min_max_prefers_exact_threshold(self) -> None:
        llm_good = PatternCase(
            case_id="mwx_good",
            intent="GOOD",
            description="llm good but too narrow",
            polygons=(rectangle("contbar", 0, 0, 340, 140),),
        )
        llm_bad = PatternCase(
            case_id="mwx_bad",
            intent="BAD",
            description="llm bad and too wide",
            polygons=(rectangle("contbar", 0, 0, 340, 220),),
        )
        llm_illegal = PatternCase(
            case_id="mwx_illegal",
            intent="ILLEGAL",
            description="llm illegal",
            polygons=(rectangle("contbar", 0, 0, 200, 200),),
        )
        rule = ParsedRule(
            rule_type="max_width",
            layer="contbar",
            threshold_nm=160,
            source_text="CntB.a: Min. and max. ContBar width = 0.16",
        )
        adjusted = adjust_llm_cases(
            base_cases=[llm_good, llm_bad, llm_illegal],
            rule=rule,
            rule_text=rule.source_text,
        )
        good_case = next(case for case in adjusted if case.intent == "GOOD")
        good_points = good_case.to_dict()["lpl"][0]["points"]
        good_w = min(
            abs(good_points[1][0] - good_points[0][0]),
            abs(good_points[2][1] - good_points[1][1]),
        )
        self.assertEqual(good_w, 160)

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

    def test_adjust_sky130_ignores_ihp_only_context_layers(self) -> None:
        llm_good = PatternCase(
            case_id="ihpctx_good",
            intent="GOOD",
            description="good",
            polygons=(rectangle("met1", 0, 0, 400, 180),),
        )
        llm_bad = PatternCase(
            case_id="ihpctx_bad",
            intent="BAD",
            description="bad",
            polygons=(rectangle("met1", 0, 0, 400, 100),),
        )
        llm_illegal = PatternCase(
            case_id="ihpctx_illegal",
            intent="ILLEGAL",
            description="illegal",
            polygons=generate_min_width_cases(layer="met1", min_width_nm=140)[2].polygons,
        )
        rule_text = "Description: Min. TopMetal1:filler space to TRANS = 4.90"
        rule = ParsedRule(
            rule_type="min_spacing",
            layer="met1",
            threshold_nm=4900,
            source_text=rule_text,
        )
        adjusted = adjust_llm_cases(
            base_cases=[llm_good, llm_bad, llm_illegal],
            rule=rule,
            rule_text=rule_text,
            tech_name="sky130",
        )
        bad_layers = {poly.layer for poly in next(case for case in adjusted if case.intent == "BAD").polygons}
        self.assertEqual(bad_layers, {"met1"})

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
