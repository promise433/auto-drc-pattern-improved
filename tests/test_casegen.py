from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autodrc.casegen import (
    _TECH_CONTEXT_MARKER_SKIP_POLICY,
    _add_sky130_licon_npc_good_carrier,
    _extract_context_layers,
    _extract_ihp_spacing_partner_layer,
    _extract_sky130_spacing_partner_layer,
    _extract_spacing_partner_layer,
    _widen_sky130_licon_npc_spacing_partner,
    _square_sky130_licon_npc_spacing_carrier,
    generate_cases_for_rule,
    generate_forbidden_angle_cases,
    generate_min_spacing_cases,
    generate_min_width_cases,
    write_cases,
)

IHP_TECH = "ihp_sg13g2"


class CasegenTests(unittest.TestCase):
    def test_cap2m_intersection_enclosure_bad_exercises_own_expression(self) -> None:
        text="Runset expression: cap2m.and(m4).enclosing(m4,0.14,euclidian)"
        cases=generate_cases_for_rule(rule_type="min_enclosure",layer="m4",layer_b="cap2m",threshold_nm=140,rule_text=text)
        bad=cases[1]
        self.assertEqual(next(p.points for p in bad.polygons if p.layer=="m4"),next(p.points for p in bad.polygons if p.layer=="cap2m"))
        old=generate_cases_for_rule(rule_type="min_enclosure",layer="m4",layer_b="cap2m",threshold_nm=140,
            rule_text="Runset expression: m4.enclosing(cap2m,0.14,euclidian)")
        self.assertEqual(cases[0].polygons,old[0].polygons)
        self.assertEqual(cases[2],old[2])

    def test_sky_angle_subbranches_have_active_good_and_bad_operands(self) -> None:
        for layer in ("diff", "tap"):
            for operator, angle in (("and",45),("not",90)):
                text = f"Runset expression: {layer}.{operator}(areaid_en.and(uhvi)).with_angle(0..{angle})"
                cases = generate_cases_for_rule(rule_type="forbidden_angle",layer=layer,threshold_nm=angle,rule_text=text)
                for case in cases[:2]:
                    names = {p.layer for p in case.polygons}
                    self.assertEqual(names, {layer,"uhvi","areaid_en"} if operator=="and" else {layer})
                    if operator=="and":
                        for marker in case.polygons[1:]:
                            x0,y0=min(x for x,y in marker.points),min(y for x,y in marker.points)
                            x1,y1=max(x for x,y in marker.points),max(y for x,y in marker.points)
                            self.assertGreaterEqual(min(x1-x0,y1-y0),840)
                            self.assertTrue(all(x0<x<x1 and y0<y<y1 for x,y in case.polygons[0].points))
                legacy = generate_forbidden_angle_cases(layer=layer,allowed_angle_deg=angle,context_layers=("uhvi",))
                self.assertEqual(cases[2],legacy[2])

    def test_pwde_hv_spacing_good_and_bad_have_active_context_without_width_errors(self) -> None:
        text = "Runset expression: pwde.and(uhvi.or(vhvi)).space(1.27, euclidian)"
        for delta in (20,60,100):
            cases = generate_cases_for_rule(rule_type="min_spacing",layer="pwde",threshold_nm=1270,
                                            delta_nm=delta,rule_text=text)
            for case in cases[:2]:
                self.assertEqual([p.layer for p in case.polygons],["pwde","pwde","uhvi"])
                a,b,context = case.polygons
                self.assertGreaterEqual(min(max(x for x,y in a.points)-min(x for x,y in a.points),
                    max(y for x,y in a.points)-min(y for x,y in a.points)),840)
                gap = min(x for x,y in b.points)-max(x for x,y in a.points)
                self.assertEqual(gap,1270+(delta if case.intent=="GOOD" else -delta))
                self.assertTrue(all(min(x for x,y in context.points)<x<max(x for x,y in context.points)
                    and min(y for x,y in context.points)<y<max(y for x,y in context.points)
                    for polygon in (a,b) for x,y in polygon.points))
            plain = generate_min_spacing_cases(layer="pwde",min_spacing_nm=1270,delta_nm=delta)
            self.assertEqual(cases[2],plain[2])
        plain = generate_cases_for_rule(rule_type="min_spacing",layer="pwde",threshold_nm=1270,
            rule_text="Description: inside v20\nRunset expression: pwde.space(1.27, euclidian)")
        self.assertTrue(all(p.layer!="uhvi" for c in plain for p in c.polygons))

    def test_derived_core_operands_have_effective_context_and_legal_carriers(self) -> None:
        for layer in ("diff","tap"):
            text = f"Runset expression: {layer}_cross_areaid_ce\nUpstream chain: {layer}_width = {layer}.rectangles.width(0.15, euclidian).polygons | {layer}_cross_areaid_ce = {layer}_width.edges.outside_part(areaid_ce).not({layer}_width.outside(areaid_ce).edges)"
            cases = generate_cases_for_rule(rule_type="min_width",layer=layer,threshold_nm=150,rule_text=text)
            for case in cases[:2]:
                shape,core=case.polygons
                self.assertLess(min(y for x,y in shape.points),min(y for x,y in core.points))
                self.assertGreater(max(y for x,y in shape.points),max(y for x,y in core.points))
            self.assertEqual(max(x for x,y in cases[1].polygons[0].points),145)
        cases = generate_cases_for_rule(rule_type="via_enclosure",layer="m2",layer_b="via",threshold_nm=45,
            rule_text="Runset expression: m2.enclosing(via_inside_periphery, 0.045, euclidian)\nUpstream chain: via_inside_periphery = via.and(areaid_ce)")
        for case in cases[:2]:
            self.assertEqual({p.layer for p in case.polygons},{"via","m2","met1","areaid_ce"})
            self.assertTrue(case.to_dict()["geometry_valid"])
            self.assertTrue(all(v%5==0 for p in case.polygons for point in p.points for v in point))
        poly = generate_cases_for_rule(rule_type="min_spacing",layer="poly",threshold_nm=160,
            rule_text="Runset expression: poly.interacting(core_poly_gap).isolated(0.16, projection)\nUpstream chain: core_poly_gap = poly.inside(areaid_ce).drc(width(projection) <= 0.15).polygons")
        self.assertTrue(all(any(p.layer=="areaid_ce" for p in c.polygons) for c in poly[:2]))
        self.assertTrue(all(max(x for x,y in p.points)-min(x for x,y in p.points)==150
                            for c in poly[:2] for p in c.polygons if p.layer=="poly"))
    def test_core_region_context_requires_actual_inside_expression_or_definition(self) -> None:
        for layer, expression, upstream in (
            ("diff", "diff.inside(areaid_ce).width(0.14, euclidian)", ""),
            ("nsdm", "not_sram_nsdm.inside(areaid_ce).space(0.29, euclidian)", ""),
            ("li1", "li_core.width(0.14, euclidian)", "li_core = li.and(areaid_ce)"),
        ):
            with self.subTest(layer=layer):
                rule_type = "min_spacing" if ".space(" in expression else "min_width"
                cases = generate_cases_for_rule(rule_type=rule_type, layer=layer, threshold_nm=140,
                    rule_text=f"Runset expression: {expression}\nUpstream chain: {upstream}")
                for case in cases[:2]:
                    core = next(p for p in case.polygons if p.layer == "areaid_ce")
                    for p in case.polygons[:-1]:
                        self.assertTrue(all(min(x for x,y in core.points) < x < max(x for x,y in core.points)
                            and min(y for x,y in core.points) < y < max(y for x,y in core.points) for x,y in p.points))
                self.assertNotIn("areaid_ce", [p.layer for p in cases[2].polygons])
        for text in ("Description: width inside areaid:core\nRunset expression: li.width(0.14, euclidian)",
                     "Runset expression: li_core.width(0.14, euclidian)\nUpstream chain: li_core = li.not(areaid_ce)"):
            cases = generate_cases_for_rule(rule_type="min_width", layer="li1", threshold_nm=140, rule_text=text)
            self.assertTrue(all(p.layer != "areaid_ce" for c in cases for p in c.polygons))

    def test_core_spacing_preserves_gap_with_legal_width_and_good_parallel_spacing(self) -> None:
        for layer, expression, definition, threshold, minimum_width, minimum_gap in (
            ("ldntm", "ldntm_core.space(0.7, euclidian)", "ldntm_core = ldntm.and(areaid_ce)", 700, 700, 720),
            ("nsdm", "nsdm.inside(areaid_ce).space(0.29, euclidian)", "", 290, 290, 380),
        ):
            cases = generate_cases_for_rule(rule_type="min_spacing",layer=layer,threshold_nm=threshold,
                rule_text=f"Runset expression: {expression}\nUpstream chain: {definition}")
            for case in cases[:2]:
                left,right = case.polygons[:2]
                for poly in (left,right):
                    self.assertGreaterEqual(max(x for x,y in poly.points)-min(x for x,y in poly.points),minimum_width)
                    self.assertGreaterEqual(max(y for x,y in poly.points)-min(y for x,y in poly.points),minimum_width)
                gap = min(x for x,y in right.points)-max(x for x,y in left.points)
                self.assertEqual(gap,minimum_gap if case.intent=="GOOD" else threshold-20)

    def test_via2_adjacent_enclosure_has_upper_metal_context_in_good_and_bad(self) -> None:
        text = ("Description: via2.5 : min. m3 enclosure of via2 of 2 adjacent edges : 0.085um\n"
                "Runset expression: via2_interact\nUpstream chain: m2.enclosing(via2, 0.085, projection).second_edges")
        cases = generate_cases_for_rule(rule_type="via_enclosure", layer="m2", layer_b="via2",
            threshold_nm=85, rule_text=text)
        for case in cases[:2]:
            self.assertEqual(sum(p.layer in {"m3", "met3"} for p in case.polygons), 1)
            self.assertTrue(case.to_dict()["geometry_valid"])
            carrier = next(p for p in case.polygons if p.layer in {"m3", "met3"})
            width = max(x for x, y in carrier.points) - min(x for x, y in carrier.points)
            height = max(y for x, y in carrier.points) - min(y for x, y in carrier.points)
            self.assertGreater(width * height, 240000)
        self.assertFalse(cases[2].to_dict()["geometry_valid"])

    def test_sky_context_identifiers_are_not_layers_but_body_mentions_survive(self) -> None:
        from autodrc.llm_policy import _context_layers_from_text
        for body, expected in (("npc enclosure of poly_licon", ()), ("npc enclosure of licon", ("licon",))):
            text = f"Rule ID: licon.6\nDescription: licon.6 : {body}\nRunset expression: npc.enclosing(polyLicon1_CORE, 0.045, euclidian)"
            self.assertEqual(_extract_context_layers(rule_text=text, excluded_layers=("npc", "poly")), expected)
            self.assertEqual(tuple(_context_layers_from_text(rule_text=text, primary_layer="npc", secondary_layer="poly")), expected)

    def test_sky_poly_licon_core_cases_have_legal_contact_and_distinct_bad_conditions(self) -> None:
        for expression, covered_bad in (("npc.enclosing(polyLicon1_CORE, 0.045, euclidian)", True),
                                        ("polyLicon1_CORE.not(npc)", False)):
            for delta in (20, 60, 100):
                cases = generate_cases_for_rule(rule_type="min_enclosure", layer="npc", layer_b="poly",
                    threshold_nm=45, delta_nm=delta, rule_text="Runset expression: " + expression)
                for case in cases[:2]:
                    self.assertTrue(case.to_dict()["geometry_valid"])
                    shapes = {p.layer: p for p in case.polygons}
                    self.assertEqual(set(shapes), {"licon", "poly", "areaid_ce", "npc"})
                    self.assertEqual(shapes["licon"].points, shapes["poly"].points)
                    self.assertEqual({x for x, y in shapes["licon"].points}, {0, 170})
                    self.assertEqual({y for x, y in shapes["licon"].points}, {0, 170})
                    self.assertTrue(all(v % 5 == 0 for p in case.polygons for point in p.points for v in point))
                    self.assertGreaterEqual(max(x for x, y in shapes["npc"].points) - min(x for x, y in shapes["npc"].points), 270)
                self.assertLess(min(x for x, y in cases[0].polygons[-1].points), -45)
                bad_x = min(x for x, y in cases[1].polygons[-1].points)
                self.assertEqual(bad_x < 0, covered_bad)
                if covered_bad:
                    self.assertLess(-bad_x, 45)
                self.assertFalse(cases[2].to_dict()["geometry_valid"])

    def test_context_extraction_preserves_field_order_and_filters(self) -> None:
        for tech, primary, first, last in (
            ("sky130", "met1", "npc", "poly"),
            (IHP_TECH, "activ", "psd", "salblock"),
        ):
            with self.subTest(tech=tech):
                text = (
                    f"Description: {first} {first}\nRunset expression: nwell\n"
                    f"Context: {last} areaid_ce prec_resistor"
                )
                self.assertEqual(
                    _extract_context_layers(rule_text=text, excluded_layers=(primary,), tech_name=tech),
                    (first, "nwell", last),
                )
                self.assertEqual(
                    _extract_context_layers(rule_text=text, excluded_layers=(primary, first), tech_name=tech),
                    ("nwell", last),
                )

    def test_context_extraction_accepts_one_pass_physical_alias_exclusions(self) -> None:
        for tech, alias, excluded, context in (
            ("sky130", "m1", "met1", "npc"),
            (IHP_TECH, "contbar", "cont", "psd"),
        ):
            with self.subTest(tech=tech):
                self.assertEqual(
                    _extract_context_layers(
                        rule_text=f"Description: {alias}\nRunset expression: {context}",
                        excluded_layers=iter(("", excluded)), tech_name=tech,
                    ),
                    (context,),
                )

    def test_ihp_extractor_changes_leave_all_sky_context_callers_unchanged(self) -> None:
        for rule_type in ("min_width", "forbidden_overlap", "forbidden_angle"):
            with self.subTest(rule_type=rule_type):
                ihp_args = dict(
                    rule_type=rule_type, layer="activ", threshold_nm=90, tech_name=IHP_TECH,
                    layer_b="met1" if rule_type == "forbidden_overlap" else None,
                    rule_text="Description: context psd",
                )
                sky_args = dict(
                    rule_type=rule_type, layer="met1", threshold_nm=90, tech_name="sky130",
                    layer_b="met2" if rule_type == "forbidden_overlap" else None,
                    rule_text="Description: context npc",
                )
                ihp_before = [c.to_dict() for c in generate_cases_for_rule(**ihp_args)]
                sky_before = [c.to_dict() for c in generate_cases_for_rule(**sky_args)]
                with patch("autodrc.casegen._extract_ihp_context_layers", return_value=("nwell",)) as extract:
                    ihp_after = [c.to_dict() for c in generate_cases_for_rule(**ihp_args)]
                    sky_after = [c.to_dict() for c in generate_cases_for_rule(**sky_args)]
                    extract.assert_called_once()
                self.assertNotEqual(ihp_before, ihp_after)
                self.assertEqual(sky_before, sky_after)
                self.assertEqual(ihp_before, [c.to_dict() for c in generate_cases_for_rule(**ihp_args)])

    def test_spacing_partner_dispatches_to_the_matching_technology(self) -> None:
        sky_text = "Description: met1 space to met2 = 0.14"
        ihp_text = "Description: activ space to topmetal1 = 0.14"
        with (
            patch(
                "autodrc.casegen._extract_sky130_spacing_partner_layer",
                wraps=_extract_sky130_spacing_partner_layer,
            ) as sky_extract,
            patch(
                "autodrc.casegen._extract_ihp_spacing_partner_layer",
                wraps=_extract_ihp_spacing_partner_layer,
            ) as ihp_extract,
        ):
            self.assertEqual(
                _extract_spacing_partner_layer(
                    rule_text=sky_text, primary_layer="met1", tech_name="sky130"
                ),
                "met2",
            )
            self.assertEqual(
                _extract_spacing_partner_layer(
                    rule_text=ihp_text, primary_layer="activ", tech_name=IHP_TECH
                ),
                "topmetal1",
            )
        sky_extract.assert_called_once_with(rule_text=sky_text, primary_layer="met1")
        ihp_extract.assert_called_once_with(rule_text=ihp_text, primary_layer="activ")

    def test_ihp_spacing_partner_changes_leave_sky_generation_unchanged(self) -> None:
        ihp_args = dict(
            rule_type="min_spacing",
            layer="activ",
            threshold_nm=90,
            delta_nm=20,
            tech_name=IHP_TECH,
            rule_text=(
                "Description: activ space to cont = 0.09\n"
                "Runset expression: activ.separation(cont, 0.09, euclidian)"
            ),
        )
        sky_args = dict(
            rule_type="min_spacing",
            layer="met1",
            threshold_nm=140,
            delta_nm=20,
            tech_name="sky130",
            rule_text=(
                "Description: met1 space to met2 = 0.14\n"
                "Runset expression: met1.separation(met2, 0.14, euclidian)"
            ),
        )
        ihp_before = [case.to_dict() for case in generate_cases_for_rule(**ihp_args)]
        sky_before = [case.to_dict() for case in generate_cases_for_rule(**sky_args)]
        with patch("autodrc.casegen._extract_ihp_spacing_partner_layer", return_value="nwell") as ihp_extract:
            ihp_after = [case.to_dict() for case in generate_cases_for_rule(**ihp_args)]
            sky_after = [case.to_dict() for case in generate_cases_for_rule(**sky_args)]
        ihp_extract.assert_called_once_with(rule_text=ihp_args["rule_text"], primary_layer="activ")
        self.assertNotEqual(ihp_before, ihp_after)
        self.assertEqual(sky_before, sky_after)

    def test_context_marker_skip_policy_preserves_tech_behavior(self) -> None:
        for tech, layer, context in (("sky130", "met1", "nwell"), (IHP_TECH, "activ", "psd")):
            for rule_type, expression, expected_marker in (
                ("max_length", f"{layer}.drc(length > 0.5)", tech == IHP_TECH),
                ("min_spacing", f"{layer}.space(0.5, euclidian)", False),
                ("min_spacing", f"{layer}.space(0.5, euclidian).interacting({context})", True),
            ):
                with self.subTest(tech=tech, expression=expression):
                    cases = generate_cases_for_rule(
                        rule_type=rule_type, layer=layer, threshold_nm=500,
                        rule_text=f"Description: context {context}\nRunset expression: {expression}",
                        tech_name=tech,
                    )
                    self.assertEqual("[ctx-markers]" in cases[1].description, expected_marker)
                    self.assertEqual(context in {p.layer for p in cases[1].polygons}, expected_marker)
                    self.assertNotIn(context, {p.layer for p in cases[0].polygons})
                    self.assertNotIn(context, {p.layer for p in cases[2].polygons})

    def test_ihp_context_skip_policy_changes_leave_sky_outputs_unchanged(self) -> None:
        for rule_type, flag, value in (
            ("max_length", "skip_max_length", True),
            ("min_spacing", "skip_simple_same_layer_spacing", False),
        ):
            with self.subTest(rule_type=rule_type):
                ihp_expression = "activ.drc(length > 0.5)" if rule_type == "max_length" else "activ.space(0.5, euclidian)"
                sky_expression = "met1.drc(length > 0.5)" if rule_type == "max_length" else "met1.space(0.5, euclidian)"
                ihp_args = dict(
                    rule_type=rule_type, layer="activ", threshold_nm=500, tech_name=IHP_TECH,
                    rule_text=f"Description: context psd\nRunset expression: {ihp_expression}",
                )
                sky_args = dict(
                    rule_type=rule_type, layer="met1", threshold_nm=500, tech_name="sky130",
                    rule_text=f"Description: context nwell\nRunset expression: {sky_expression}",
                )
                ihp_before = [c.to_dict() for c in generate_cases_for_rule(**ihp_args)]
                sky_before = [c.to_dict() for c in generate_cases_for_rule(**sky_args)]
                with patch.dict(_TECH_CONTEXT_MARKER_SKIP_POLICY[IHP_TECH], {flag: value}):
                    ihp_after = [c.to_dict() for c in generate_cases_for_rule(**ihp_args)]
                    sky_after = [c.to_dict() for c in generate_cases_for_rule(**sky_args)]
                self.assertNotEqual(ihp_before, ihp_after)
                self.assertEqual(sky_before, sky_after)
                self.assertEqual(ihp_before, [c.to_dict() for c in generate_cases_for_rule(**ihp_args)])

    def test_generate_width_cases(self) -> None:
        cases = generate_min_width_cases(layer="met1", min_width_nm=140, delta_nm=20)
        self.assertEqual([c.intent for c in cases], ["GOOD", "BAD", "ILLEGAL"])
        self.assertTrue(cases[0].to_dict()["geometry_valid"])
        self.assertFalse(cases[2].to_dict()["geometry_valid"])

    def test_generate_width_cases_large_threshold_scales_length(self) -> None:
        cases = generate_min_width_cases(layer="rdl", min_width_nm=10000, delta_nm=20)
        good = cases[0].to_dict()["lpl"][0]["points"]
        width = good[2][1] - good[1][1]
        length = good[1][0] - good[0][0]
        self.assertGreaterEqual(width, 10020)
        self.assertGreaterEqual(length, 10040)

    def test_generate_spacing_cases(self) -> None:
        cases = generate_min_spacing_cases(layer="met1", min_spacing_nm=140, delta_nm=20)
        self.assertEqual([c.intent for c in cases], ["GOOD", "BAD", "ILLEGAL"])
        self.assertFalse(cases[2].to_dict()["geometry_valid"])

    def test_generate_spacing_cases_scale_bar_width_for_wide_layers(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing",
            layer="dnwell",
            threshold_nm=6300,
            delta_nm=100,
        )
        bad_lpl = cases[1].to_dict()["lpl"]
        width = bad_lpl[0]["points"][1][0] - bad_lpl[0]["points"][0][0]
        self.assertGreaterEqual(width, 3000)

    def test_sky_high_voltage_spacing_preserves_minimum_body_width(self) -> None:
        for layer in ("hvtp", "hvtr"):
            with self.subTest(layer=layer):
                cases = generate_min_spacing_cases(layer=layer, min_spacing_nm=380)
                for case in cases[:2]:
                    for polygon in case.polygons:
                        width = max(x for x, _ in polygon.points) - min(x for x, _ in polygon.points)
                        self.assertEqual(width, 380)

    def test_generate_cross_layer_spacing_cases_from_rule_text(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing",
            layer="hvtr",
            threshold_nm=380,
            delta_nm=20,
            rule_text="Runset expression: hvtr.separation(hvtp, 0.38, euclidian)",
            tech_name=IHP_TECH,
        )
        layers = {poly["layer"] for poly in cases[1].to_dict()["lpl"]}
        self.assertIn("hvtr", layers)
        self.assertIn("hvtp", layers)

    def test_simple_spacing_description_does_not_infer_partner_layer(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing", layer="urpm", threshold_nm=840,
            rule_text="Rule ID: urpm.2\nDescription: urpm.2 : min. rpm spacing : 0.84um\n"
                       "Runset expression: urpm.space(0.84, euclidian)",
        )
        self.assertEqual({poly.layer for poly in cases[0].polygons}, {"urpm"})
        self.assertEqual({poly.layer for poly in cases[1].polygons}, {"urpm"})

    def test_sky_spacing_to_phrase_selects_partner_over_carrier_layer(self) -> None:
        for phrase in ("space to", "spacing to", "space to edges of", "spacing to edges of"):
            with self.subTest(phrase=phrase):
                self.assertEqual(
                    _extract_spacing_partner_layer(
                        rule_text=f"Description: licon.13: min. licon on diff {phrase} npc in periphery : 0.09um",
                        primary_layer="licon", tech_name="sky130",
                    ),
                    "npc",
                )

    def test_sky_licon13_spacing_uses_npc_gap_and_keeps_carrier_context(self) -> None:
        rule_text = (
            "Rule ID: licon.13\n"
            "Description: licon.13: min. licon on diff spacing to npc in periphery : 0.09um\n"
            "Runset expression: licon_peri.and(difftap).separation(npc, 0.09, euclidian)\n"
            "Upstream chain: difftap = diff.or(tap) | licon_peri = licon.outside(areaid_ce)"
        )
        for delta, good_gap, bad_gap in ((20, 110, 70), (60, 150, 30), (100, 190, 1)):
            with self.subTest(delta=delta):
                good, bad, illegal = generate_cases_for_rule(
                    rule_type="min_spacing", layer="licon", threshold_nm=90,
                    delta_nm=delta, rule_text=rule_text, tech_name="sky130",
                )
                for case, expected_gap in ((good, good_gap), (bad, bad_gap)):
                    self.assertTrue(case.to_dict()["geometry_valid"])
                    licon, npc = case.polygons[:2]
                    self.assertEqual((licon.layer, npc.layer), ("licon", "npc"))
                    self.assertEqual(
                        min(x for x, _ in npc.points) - max(x for x, _ in licon.points),
                        expected_gap,
                    )
                    self.assertEqual(sum(poly.layer == "npc" for poly in case.polygons), 1)
                self.assertEqual({poly.layer for poly in good.polygons}, {"licon", "npc", "diff"})
                self.assertEqual({poly.layer for poly in bad.polygons}, {"licon", "npc", "diff", "tap"})
                self.assertFalse(illegal.to_dict()["geometry_valid"])

    def test_sky_licon13_good_carrier_preserves_existing_geometry_and_other_intents(self) -> None:
        for expression in (
            "licon_peri.and(difftap).separation(npc, 0.09, euclidian)",
            " LICON_PERI . AND ( DIFFTAP ) . SEPARATION ( NPC , 0.09 , EUCLIDIAN ) ",
        ):
            with self.subTest(expression=expression):
                args = dict(
                    rule_type="min_spacing", layer="licon", threshold_nm=90, delta_nm=20,
                    rule_text=(
                        "Description: min. licon on diff spacing to npc in periphery : 0.09um\n"
                        f"Runset expression: {expression}"
                    ),
                    tech_name="sky130",
                )
                with patch("autodrc.casegen._add_sky130_licon_npc_good_carrier", side_effect=lambda **kw: kw["cases"]):
                    original = generate_cases_for_rule(**args)
                current = generate_cases_for_rule(**args)
                self.assertEqual(current[1:], original[1:])
                self.assertEqual(current[0].polygons[:-1], original[0].polygons)
                licon, npc, diff = current[0].polygons
                self.assertEqual(diff.layer, "diff")
                self.assertEqual(diff.points, licon.points)
                self.assertEqual(current[0].case_id, original[0].case_id)
                self.assertEqual(current[0].intent, "GOOD")
                self.assertTrue(current[0].to_dict()["geometry_valid"])
                self.assertEqual(min(x for x, _ in npc.points) - max(x for x, _ in diff.points), 110)

    def test_sky_licon13_good_carrier_is_limited_to_verified_expression_and_layers(self) -> None:
        supported = "licon_peri.and(difftap).separation(npc, 0.09, euclidian)"
        cases = generate_cases_for_rule(
            rule_type="min_spacing", layer="licon", threshold_nm=90,
            rule_text="Runset expression: licon.separation(npc, 0.09, euclidian)",
        )
        variants = (
            ("sky130", "licon", "npc", "Description: " + supported),
            ("sky130", "licon", "npc", "Runset expression: " + supported.replace("and(difftap)", "and(poly)")),
            ("sky130", "licon", "npc", "Runset expression: " + supported.replace("0.09", "0.10")),
            ("sky130", "licon", "npc", "Runset expression: " + supported + ".interacting(poly)"),
            ("sky130", "licon", "npc", "Runset expression: licon.space(0.09)\nUpstream chain: " + supported),
            ("sky130", "tap", "npc", "Runset expression: " + supported),
            ("sky130", "licon", "poly", "Runset expression: " + supported),
            (IHP_TECH, "licon", "npc", "Runset expression: " + supported),
        )
        for tech, layer, partner, text in variants:
            with self.subTest(tech=tech, layer=layer, partner=partner, text=text):
                self.assertIs(
                    _add_sky130_licon_npc_good_carrier(
                        cases=cases, layer=layer, other_layer=partner, rule_text=text, tech_name=tech,
                    ),
                    cases,
                )

    def test_sky_licon13_npc_width_changes_only_partner_right_edge(self) -> None:
        for expression in (
            "licon_peri.and(difftap).separation(npc, 0.09, euclidian)",
            " LICON_PERI . AND ( DIFFTAP ) . SEPARATION ( NPC , 0.09 , EUCLIDIAN ) ",
        ):
            for delta in (20, 60, 100):
                with self.subTest(expression=expression, delta=delta):
                    args = dict(
                        rule_type="min_spacing", layer="licon", threshold_nm=90,
                        delta_nm=delta, tech_name="sky130",
                        rule_text="Description: min. licon on diff spacing to npc\n"
                                  f"Runset expression: {expression}",
                    )
                    with patch("autodrc.casegen._square_sky130_licon_npc_spacing_carrier", side_effect=lambda **kw: kw["cases"]):
                        with patch("autodrc.casegen._widen_sky130_licon_npc_spacing_partner", side_effect=lambda **kw: kw["cases"]):
                            original = generate_cases_for_rule(**args)
                        current = generate_cases_for_rule(**args)
                    self.assertEqual(current[2], original[2])
                    for before, after in zip(original[:2], current[:2]):
                        npc_before, npc_after = before.polygons[1], after.polygons[1]
                        x0 = min(x for x, _ in npc_before.points)
                        x1 = max(x for x, _ in npc_before.points)
                        self.assertEqual(x1 - x0, 120)
                        self.assertEqual(npc_after.layer, "npc")
                        self.assertEqual(npc_after.points, tuple(
                            (x0 + 270 if x == x1 else x, y) for x, y in npc_before.points
                        ))
                        self.assertEqual(after.polygons[:1] + after.polygons[2:],
                                         before.polygons[:1] + before.polygons[2:])
                        a, b = before.to_dict(), after.to_dict()
                        a.pop("lpl")
                        b.pop("lpl")
                        self.assertEqual(a, b)

    def test_sky_licon13_carriers_are_legal_170nm_squares(self) -> None:
        text = "Runset expression: licon_peri.and(difftap).separation(npc, 0.09, euclidian)"
        cases = generate_cases_for_rule(rule_type="min_spacing", layer="licon", threshold_nm=90,
                                        delta_nm=20, rule_text=text, tech_name="sky130")
        for case in cases[:2]:
            for poly in case.polygons:
                if poly.layer in {"licon", "diff"}:
                    dims = (max(x for x, _ in poly.points) - min(x for x, _ in poly.points),
                            max(y for _, y in poly.points) - min(y for _, y in poly.points))
                    self.assertEqual(dims, (170, 170))
        self.assertFalse(cases[2].to_dict()["geometry_valid"])

    def test_sky_licon13_npc_width_is_limited_to_verified_expression_and_layers(self) -> None:
        supported = "licon_peri.and(difftap).separation(npc, 0.09, euclidian)"
        cases = generate_cases_for_rule(
            rule_type="min_spacing", layer="licon", threshold_nm=90,
            rule_text="Runset expression: licon.separation(npc, 0.09, euclidian)",
        )
        for tech, layer, partner, text in (
            ("sky130", "licon", "npc", "Description: " + supported),
            ("sky130", "licon", "npc", "Runset expression: " + supported.replace("0.09", "0.10")),
            ("sky130", "licon", "npc", "Runset expression: " + supported + ".interacting(poly)"),
            ("sky130", "licon", "npc", "Runset expression: licon.space(0.09)\nUpstream chain: " + supported),
            ("sky130", "licon", "poly", "Runset expression: " + supported),
            ("sky130", "tap", "npc", "Runset expression: " + supported),
            (IHP_TECH, "licon", "npc", "Runset expression: " + supported),
        ):
            with self.subTest(tech=tech, layer=layer, partner=partner, text=text):
                self.assertIs(_widen_sky130_licon_npc_spacing_partner(
                    cases=cases, layer=layer, other_layer=partner,
                    rule_text=text, tech_name=tech,
                ), cases)

    def test_sky_licon13_npc_width_keeps_defaults_and_original_bad_markers(self) -> None:
        from autodrc.casegen import _default_box_dims, generate_cross_layer_spacing_cases

        self.assertEqual(_default_box_dims("npc", tech_name="sky130"), (120, 400))
        generic = generate_cross_layer_spacing_cases(
            layer="licon", other_layer="npc", min_spacing_nm=90,
        )
        self.assertEqual(max(x for x, _ in generic[0].polygons[1].points), 400)
        good, bad, _ = generate_cases_for_rule(
            rule_type="min_spacing", layer="licon", threshold_nm=90,
            rule_text="Description: min. licon on diff spacing to npc\n"
                      "Runset expression: licon_peri.and(difftap).separation(npc, 0.09, euclidian)\n"
                      "Upstream chain: difftap = diff.or(tap)",
        )
        self.assertEqual(good.polygons[0].points, good.polygons[2].points)
        for marker in bad.polygons[2:]:
            self.assertIn(marker.layer, ("diff", "tap"))
            self.assertEqual(marker.points, ((-80, -80), (440, -80), (440, 480), (-80, 480), (-80, -80)))
        self.assertEqual(max(x for x, _ in bad.polygons[1].points), 510)

    def test_context_markers_skip_derived_nonphysical_layers(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="max_length", layer="licon", threshold_nm=170,
            rule_text="Rule ID: licon.1\nDescription: licon.1: min/max. licon length : 0.17um\n"
                       "Runset expression: licon_not_prec_resistor.drc(length != 0.17)\n"
                       "Upstream chain: prec_resistor = (rpm | urpm) & psdm",
        )
        self.assertTrue(all(poly.layer != "prec_resistor" for poly in cases[1].polygons))
        self.assertEqual({poly.layer for poly in cases[1].polygons}, {"licon"})

    def test_generate_spacing_cases_extract_partner_from_description_and_add_context(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing",
            layer="psd",
            threshold_nm=180,
            delta_nm=20,
            rule_text=(
                "Rule ID: pSD.d\n"
                "Description: Min. pSD space to unrelated N+Activ in PWell = 0.18\n"
                "Runset expression: pSD.ext_separation(NAct_PWell, 0.18.um)\n"
                "Upstream chain: L1:activ = source.polygons(\"1/0\") | "
                "L2:pwell_block = source.polygons(\"46/21\")"
            ),
            tech_name=IHP_TECH,
        )
        bad_layers = {poly["layer"] for poly in cases[1].to_dict()["lpl"]}
        self.assertIn("psd", bad_layers)
        self.assertIn("activ", bad_layers)
        self.assertIn("pwellblock", bad_layers)

    def test_generate_spacing_cases_ignores_inside_context_for_partner_extraction(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing",
            layer="nwell",
            threshold_nm=620,
            delta_nm=20,
            rule_text=(
                "Rule ID: NW.d1\n"
                "Description: Min. NWell space to external N+Activ inside ThickGateOx = 0.62\n"
                "Runset expression: NWell.ext_separation(NActHV_ana, 0.62.um)\n"
                "Upstream chain: L1:activ = source.polygons(\"1/0\") | "
                "L2:thickgateox = source.polygons(\"44/0\")"
            ),
            tech_name=IHP_TECH,
        )
        bad_layers = {poly["layer"] for poly in cases[1].to_dict()["lpl"]}
        self.assertIn("nwell", bad_layers)
        self.assertIn("activ", bad_layers)

    def test_generate_spacing_cases_maps_gate_phrase_to_gatpoly(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing",
            layer="psd",
            threshold_nm=400,
            delta_nm=20,
            rule_text=(
                "Rule ID: pSD.j1\n"
                "Description: Min. pSD space to NFET gate inside ThickGateOx = 0.40\n"
                "Runset expression: pSD_Nsram.ext_separation(NGate_outside_SVaricap.inside(ThickGateOx), 0.4.um)\n"
                "Upstream chain: L1:gatpoly = source.polygons(\"5/0\") | "
                "L2:thickgateox = source.polygons(\"44/0\")"
            ),
            tech_name=IHP_TECH,
        )
        bad_layers = {poly["layer"] for poly in cases[1].to_dict()["lpl"]}
        self.assertIn("psd", bad_layers)
        self.assertIn("gatpoly", bad_layers)

    def test_generic_min_width_bad_case_gets_context_markers(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_width",
            layer="metal1",
            threshold_nm=3500,
            delta_nm=20,
            rule_text=(
                "Rule ID: Seal.a_Metal1\n"
                "Description: Min. EdgeSeal-Metal1 width = 3.50\n"
                "Runset expression: Metal1.ext_and(EdgeSeal).ext_width(3.5.um)"
            ),
            tech_name=IHP_TECH,
        )
        bad_layers = {poly["layer"] for poly in cases[1].to_dict()["lpl"]}
        self.assertIn("metal1", bad_layers)
        self.assertIn("edgeseal", bad_layers)

    def test_sky130_ignores_ihp_only_context_tokens(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing",
            layer="met1",
            threshold_nm=4900,
            delta_nm=20,
            rule_text="Description: Min. TopMetal1:filler space to TRANS = 4.90",
            tech_name="sky130",
        )
        bad_layers = {poly["layer"] for poly in cases[1].to_dict()["lpl"]}
        self.assertEqual(bad_layers, {"met1"})

    def test_ihp_recognizes_ihp_only_context_tokens(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing",
            layer="topmetal1_filler",
            threshold_nm=4900,
            delta_nm=20,
            rule_text="Description: Min. TopMetal1:filler space to TRANS = 4.90",
            tech_name=IHP_TECH,
        )
        bad_layers = {poly["layer"] for poly in cases[1].to_dict()["lpl"]}
        self.assertIn("topmetal1_filler", bad_layers)
        self.assertIn("trans", bad_layers)

    def test_generate_difftap_spacing_uses_tap_partner(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing",
            layer="diff",
            threshold_nm=270,
            delta_nm=20,
            rule_text="Runset expression: difftap.space(0.27, euclidian)",
        )
        layers = {poly["layer"] for poly in cases[1].to_dict()["lpl"]}
        self.assertIn("diff", layers)
        self.assertIn("tap", layers)

    def test_write_cases(self) -> None:
        cases = generate_min_width_cases(layer="met1", min_width_nm=140, delta_nm=20)
        with tempfile.TemporaryDirectory() as tmp:
            out = write_cases(cases, Path(tmp), prefix="t")
            self.assertEqual(len(out), 3)
            self.assertTrue(all(path.exists() for path in out))

    def test_unknown_rule_casegen(self) -> None:
        density_cases = generate_cases_for_rule(
            rule_type="min_density", layer="met1", threshold_nm=3000, delta_nm=20
        )
        min_length_cases = generate_cases_for_rule(
            rule_type="min_length",
            layer="contbar",
            threshold_nm=340,
            delta_nm=20,
            tech_name=IHP_TECH,
        )
        endcap_cases = generate_cases_for_rule(
            rule_type="poly_endcap", layer="poly", threshold_nm=150, delta_nm=20
        )
        window_cases = generate_cases_for_rule(
            rule_type="density_window", layer="met1", threshold_nm=4000, delta_nm=20
        )
        enclosure_cases = generate_cases_for_rule(
            rule_type="via_enclosure", layer="met1", threshold_nm=60, delta_nm=20
        )
        area_cases = generate_cases_for_rule(
            rule_type="min_area", layer="met1", threshold_nm=140000, delta_nm=20
        )
        interact_cases = generate_cases_for_rule(
            rule_type="must_interact",
            layer="met1",
            layer_b="via",
            threshold_nm=40,
            delta_nm=20,
        )
        forbidden_use_cases = generate_cases_for_rule(
            rule_type="forbidden_use", layer="modulecut", threshold_nm=1, delta_nm=20
        )
        max_width_cases = generate_cases_for_rule(
            rule_type="max_width",
            layer="mcon",
            threshold_nm=175,
            delta_nm=20,
            rule_text="ct.3_a : max. width of ring-shaped mcon : 0.175um",
        )
        max_area_cases = generate_cases_for_rule(
            rule_type="max_area", layer="mim", threshold_nm=1300000, delta_nm=20
        )
        self.assertEqual(len(density_cases), 3)
        self.assertEqual(len(min_length_cases), 3)
        self.assertEqual(len(endcap_cases), 3)
        self.assertEqual(len(window_cases), 3)
        self.assertEqual(len(enclosure_cases), 3)
        self.assertEqual(len(area_cases), 3)
        self.assertEqual(len(interact_cases), 3)
        self.assertEqual(len(forbidden_use_cases), 3)
        self.assertEqual(len(max_width_cases), 3)
        self.assertEqual(len(max_area_cases), 3)
        self.assertEqual(forbidden_use_cases[0].to_dict()["lpl"], [])

    def test_generate_hole_area_cases_from_rule_text(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_area",
            layer="met2",
            threshold_nm=140000,
            delta_nm=20,
            rule_text="Runset expression: m2.holes.with_area(0..0.14)",
        )
        self.assertGreater(len(cases[0].to_dict()["lpl"]), 1)
        self.assertGreater(len(cases[1].to_dict()["lpl"]), 1)

    def test_via_enclosure_rule_text_uses_real_via_size_and_cover_only(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="via_enclosure",
            layer="met1",
            layer_b="via",
            threshold_nm=55,
            delta_nm=20,
            rule_text=(
                "Description: via.4a_a : 0.15um via must be enclosed by met1\n"
                "Runset expression: rectVIA.squares.drc(width == 0.15).not(m1)"
            ),
        )
        bad_case = cases[1].to_dict()["lpl"]
        via_poly = next(poly for poly in bad_case if poly["layer"] == "via")
        via_width = via_poly["points"][1][0] - via_poly["points"][0][0]
        self.assertEqual(via_width, 150)
        self.assertIn("does not fully cover", cases[1].description)

    def test_via_enclosure_must_be_over_uses_cover_only_template(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="via_enclosure",
            layer="mim",
            layer_b="topvia1",
            threshold_nm=60,
            delta_nm=20,
            rule_text="TopVia1 must be over MIM",
            tech_name=IHP_TECH,
        )
        self.assertIn("fully covers", cases[0].description)
        self.assertIn("does not fully cover", cases[1].description)

    def test_must_interact_good_case_uses_full_overlap(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="must_interact",
            layer="met1",
            layer_b="via",
            threshold_nm=40,
            delta_nm=20,
        )
        good_lpl = cases[0].to_dict()["lpl"]
        self.assertEqual(good_lpl[0]["points"], good_lpl[1]["points"])

    def test_ring_rule_casegen_dispatch(self) -> None:
        width_cases = generate_cases_for_rule(
            rule_type="min_width",
            layer="mcon",
            threshold_nm=170,
            delta_nm=20,
            rule_text="ct.3 : min. width of ring-shaped mcon : 0.17um",
        )
        enclosure_cases = generate_cases_for_rule(
            rule_type="min_enclosure",
            layer="areaid_sl",
            layer_b="mcon",
            threshold_nm=60,
            delta_nm=20,
            rule_text="ct.3_b: ring-shaped mcon must be enclosed by areaid_sl",
        )
        self.assertGreater(len(width_cases[0].to_dict()["lpl"]), 1)
        self.assertGreater(len(enclosure_cases[0].to_dict()["lpl"]), 2)
        self.assertTrue(width_cases[0].to_dict()["geometry_valid"])
        self.assertTrue(enclosure_cases[0].to_dict()["geometry_valid"])

    def test_enclosure_inner_dimensions_preserve_sky_and_ihp_geometry(self) -> None:
        for tech, inner, outer, expected in (
            ("sky130", "nwell", "hvi", (840, 840)),
            (IHP_TECH, "contbar", "metal1", (340, 160)),
        ):
            with self.subTest(tech=tech):
                cases = generate_cases_for_rule(
                    rule_type="min_enclosure", layer=outer, layer_b=inner,
                    threshold_nm=60, delta_nm=20, tech_name=tech,
                )
                for case in cases:
                    points = next(poly.points for poly in case.polygons if poly.layer == inner)
                    width = max(x for x, _ in points) - min(x for x, _ in points)
                    height = max(y for _, y in points) - min(y for _, y in points)
                    self.assertEqual((width, height), expected)

    def test_cover_only_enclosure_rule_casegen_dispatch(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_enclosure",
            layer="areaid_sl",
            layer_b="mcon",
            threshold_nm=60,
            delta_nm=20,
            rule_text="ct.3_b: ring-shaped mcon must be enclosed by areaid_sl",
        )
        self.assertIn("fully covers", cases[0].description)
        self.assertIn("does not fully cover", cases[1].description)

    def test_min_max_length_rule_uses_exact_good_length(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="max_length",
            layer="licon",
            threshold_nm=170,
            delta_nm=20,
            rule_text="licon.1: min/max. licon length : 0.17um",
        )
        good_points = cases[0].to_dict()["lpl"][0]["points"]
        bad_points = cases[1].to_dict()["lpl"][0]["points"]
        good_len = max(abs(good_points[1][0] - good_points[0][0]), abs(good_points[2][1] - good_points[1][1]))
        bad_len = max(abs(bad_points[1][0] - bad_points[0][0]), abs(bad_points[2][1] - bad_points[1][1]))
        self.assertEqual(good_len, 170)
        self.assertGreater(bad_len, 170)

    def test_min_length_rule_uses_longer_good_and_shorter_bad(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_length",
            layer="contbar",
            threshold_nm=340,
            delta_nm=20,
            tech_name=IHP_TECH,
        )
        good_points = cases[0].to_dict()["lpl"][0]["points"]
        bad_points = cases[1].to_dict()["lpl"][0]["points"]
        good_len = max(abs(good_points[1][0] - good_points[0][0]), abs(good_points[2][1] - good_points[1][1]))
        bad_len = max(abs(bad_points[1][0] - bad_points[0][0]), abs(bad_points[2][1] - bad_points[1][1]))
        self.assertGreaterEqual(good_len, 360)
        self.assertLess(bad_len, 340)

    def test_min_length_contbar_uses_full_contbar_width(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_length",
            layer="contbar",
            threshold_nm=340,
            delta_nm=20,
            tech_name=IHP_TECH,
        )
        good_points = cases[0].to_dict()["lpl"][0]["points"]
        good_w = good_points[1][0] - good_points[0][0]
        good_h = good_points[2][1] - good_points[1][1]
        self.assertEqual(min(good_w, good_h), 160)

    def test_exact_width_rule_uses_exact_good_width(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="max_width",
            layer="contbar",
            threshold_nm=160,
            delta_nm=20,
            rule_text="CntB.a: Min. and max. ContBar width = 0.16",
            tech_name=IHP_TECH,
        )
        good_points = cases[0].to_dict()["lpl"][0]["points"]
        bad_points = cases[1].to_dict()["lpl"][0]["points"]
        good_w = min(
            good_points[1][0] - good_points[0][0],
            good_points[2][1] - good_points[1][1],
        )
        bad_w = min(
            bad_points[1][0] - bad_points[0][0],
            bad_points[2][1] - bad_points[1][1],
        )
        self.assertEqual(good_w, 160)
        self.assertGreater(bad_w, 160)

    def test_max_area_rule_uses_smaller_good_and_larger_bad(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="max_area",
            layer="mim",
            threshold_nm=1300000,
            delta_nm=20,
        )
        good_points = cases[0].to_dict()["lpl"][0]["points"]
        bad_points = cases[1].to_dict()["lpl"][0]["points"]
        good_area = (good_points[1][0] - good_points[0][0]) * (good_points[2][1] - good_points[1][1])
        bad_area = (bad_points[1][0] - bad_points[0][0]) * (bad_points[2][1] - bad_points[1][1])
        self.assertLessEqual(good_area, 1300000)
        self.assertGreater(bad_area, 1300000)

    def test_forbidden_angle_45_bad_case_contains_non_45_multiples(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="forbidden_angle",
            layer="met1",
            threshold_nm=45,
            delta_nm=20,
        )
        bad_points = cases[1].to_dict()["lpl"][0]["points"]
        pts = bad_points[:-1]

        has_acute_non_45_corner = False
        for i in range(len(pts)):
            p_prev = pts[i - 1]
            p = pts[i]
            p_next = pts[(i + 1) % len(pts)]
            v1 = (p_prev[0] - p[0], p_prev[1] - p[1])
            v2 = (p_next[0] - p[0], p_next[1] - p[1])
            n1 = math.hypot(v1[0], v1[1])
            n2 = math.hypot(v2[0], v2[1])
            if n1 == 0 or n2 == 0:
                continue
            c = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
            ang = math.degrees(math.acos(c))
            if 0 < ang < 45:
                has_acute_non_45_corner = True
                break
        self.assertTrue(has_acute_non_45_corner)

    def test_forbidden_angle_90_bad_case_contains_non_90_corner(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="forbidden_angle",
            layer="met1",
            threshold_nm=90,
            delta_nm=20,
        )
        bad_points = cases[1].to_dict()["lpl"][0]["points"]
        pts = bad_points[:-1]

        has_non_90_corner = False
        for i in range(len(pts)):
            p_prev = pts[i - 1]
            p = pts[i]
            p_next = pts[(i + 1) % len(pts)]
            v1 = (p_prev[0] - p[0], p_prev[1] - p[1])
            v2 = (p_next[0] - p[0], p_next[1] - p[1])
            n1 = math.hypot(v1[0], v1[1])
            n2 = math.hypot(v2[0], v2[1])
            if n1 == 0 or n2 == 0:
                continue
            c = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
            ang = math.degrees(math.acos(c))
            if abs(ang - 90.0) > 1e-3:
                has_non_90_corner = True
                break
        self.assertTrue(has_non_90_corner)

    def test_forbidden_angle_context_layers_are_added_from_rule_text(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="forbidden_angle",
            layer="gatpoly",
            threshold_nm=90,
            delta_nm=20,
            rule_text="45-degree and 90-degree angles for GatPoly on Activ area are not allowed",
            tech_name=IHP_TECH,
        )
        bad_layers = {poly["layer"] for poly in cases[1].to_dict()["lpl"]}
        self.assertIn("gatpoly", bad_layers)
        self.assertIn("activ", bad_layers)

    def test_sky_straddle_bad_crosses_nwell_boundary(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="forbidden_overlap", layer="nwell", layer_b="lvtn",
            threshold_nm=40, delta_nm=20,
            rule_text="MR_lvtn.OVL.2 : lvtn must not straddle nwell",
            tech_name="sky130",
        )
        good, bad, illegal = (case.to_dict() for case in cases)
        self.assertTrue(good["geometry_valid"])
        self.assertTrue(bad["geometry_valid"])
        self.assertFalse(illegal["geometry_valid"])
        nwell, lvtn = bad["lpl"]
        well_x = [point[0] for point in nwell["points"]]
        implant_x = [point[0] for point in lvtn["points"]]
        self.assertLess(min(well_x), min(implant_x))
        self.assertLess(min(implant_x), max(well_x))
        self.assertLess(max(well_x), max(implant_x))
        good_well_x = [point[0] for point in good["lpl"][0]["points"]]
        good_implant_x = [point[0] for point in good["lpl"][1]["points"]]
        self.assertLess(max(good_well_x), min(good_implant_x))

    def test_forbidden_overlap_context_layers_are_added_from_rule_text(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="forbidden_overlap",
            layer="cont",
            layer_b="gatpoly",
            threshold_nm=40,
            delta_nm=20,
            rule_text="Cont on GatPoly over Activ is not allowed",
            tech_name=IHP_TECH,
        )
        bad_layers = {poly["layer"] for poly in cases[1].to_dict()["lpl"]}
        self.assertIn("cont", bad_layers)
        self.assertIn("gatpoly", bad_layers)
        self.assertIn("activ", bad_layers)

    def test_forbidden_overlap_specializes_cont_and_contbar_geometry(self) -> None:
        cont_cases = generate_cases_for_rule(
            rule_type="forbidden_overlap",
            layer="cont",
            layer_b="gatpoly",
            threshold_nm=40,
            delta_nm=20,
            rule_text="Cont on GatPoly over Activ is not allowed",
            tech_name=IHP_TECH,
        )
        cont_poly = next(poly for poly in cont_cases[1].to_dict()["lpl"] if poly["layer"] == "cont")
        cont_w = cont_poly["points"][1][0] - cont_poly["points"][0][0]
        cont_h = cont_poly["points"][2][1] - cont_poly["points"][1][1]
        self.assertEqual((cont_w, cont_h), (160, 160))

        contbar_cases = generate_cases_for_rule(
            rule_type="forbidden_overlap",
            layer="contbar",
            layer_b="gatpoly",
            threshold_nm=40,
            delta_nm=20,
            rule_text="ContBar on GatPoly over Activ is not allowed",
            tech_name=IHP_TECH,
        )
        contbar_poly = next(
            poly for poly in contbar_cases[1].to_dict()["lpl"] if poly["layer"] == "contbar"
        )
        contbar_w = contbar_poly["points"][1][0] - contbar_poly["points"][0][0]
        contbar_h = contbar_poly["points"][2][1] - contbar_poly["points"][1][1]
        self.assertEqual(min(contbar_w, contbar_h), 160)
        self.assertGreaterEqual(max(contbar_w, contbar_h), 340)

    def test_generate_across_boundary_spacing_cases_from_rule_text(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing",
            layer="nsdm",
            threshold_nm=380,
            delta_nm=20,
            rule_text=(
                "Runset expression: nsdm.space(0.38, euclidian).polygons.interacting(areaid_ce_merged) "
                "nsdm_space.interacting(nsdm_space.edges.outside_part(areaid_ce_merged))"
            ),
        )
        bad_layers = [poly["layer"] for poly in cases[1].to_dict()["lpl"]]
        self.assertEqual(bad_layers.count("nsdm"), 2)
        self.assertIn("areaid_ce", bad_layers)

    def test_generate_across_boundary_width_cases_from_rule_text(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_width",
            layer="nsdm",
            threshold_nm=380,
            delta_nm=20,
            rule_text=(
                "Runset expression: nsdm.width(0.38, euclidian).polygons.interacting(areaid_ce_merged) "
                "nsdm_width.interacting(nsdm_width.edges.outside_part(areaid_ce_merged))"
            ),
        )
        bad_layers = [poly["layer"] for poly in cases[1].to_dict()["lpl"]]
        self.assertEqual(bad_layers.count("nsdm"), 1)
        self.assertIn("areaid_ce", bad_layers)

    def test_non_huge_spacing_rule_does_not_use_huge_spacing_template(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing",
            layer="met1",
            threshold_nm=140,
            delta_nm=20,
            rule_text=(
                "Rule ID: m1.2\n"
                "Runset expression: non_huge_m1.space(0.14, euclidian)\n"
                "Upstream chain: L1:huge_m1 = m1.with_area(0.144..) | L2:non_huge_m1 = m1.not(huge_m1)"
            ),
        )
        widths = []
        for poly in cases[1].to_dict()["lpl"]:
            if poly["layer"] != "met1":
                continue
            points = poly["points"]
            widths.append(points[1][0] - points[0][0])
        self.assertTrue(widths)
        self.assertLess(max(widths), 1000)

    def test_huge_spacing_rule_still_uses_huge_spacing_template(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing",
            layer="met1",
            threshold_nm=280,
            delta_nm=20,
            rule_text="Runset expression: huge_m1.separation(non_huge_m1, 0.28, euclidian) + huge_m1.space(0.28, euclidian)",
        )
        widths = []
        for poly in cases[1].to_dict()["lpl"]:
            if poly["layer"] != "met1":
                continue
            points = poly["points"]
            widths.append(points[1][0] - points[0][0])
        self.assertGreaterEqual(max(widths), 3200)

    def test_generate_bot_plate_spacing_cases_from_rule_text(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing",
            layer="capm",
            threshold_nm=1200,
            delta_nm=20,
            rule_text="Runset expression: m3_bot_plate .isolated(1.2, euclidian) .polygons .not(m3)",
        )
        bad_layers = [poly["layer"] for poly in cases[1].to_dict()["lpl"]]
        self.assertEqual(bad_layers.count("capm"), 2)
        self.assertEqual(bad_layers.count("m3"), 2)

    def test_generate_interacting_isolated_spacing_cases_from_rule_text(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing",
            layer="cap2m",
            threshold_nm=1200,
            delta_nm=20,
            rule_text="Runset expression: (m4.interacting(cap2m)).isolated(1.2, euclidian)",
        )
        bad_layers = [poly["layer"] for poly in cases[1].to_dict()["lpl"]]
        self.assertEqual(bad_layers.count("cap2m"), 2)
        self.assertEqual(bad_layers.count("m4"), 2)

    def test_generate_hole_enclosure_uses_hole_bbox(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_enclosure",
            layer="dnwell",
            layer_b="nwell",
            threshold_nm=1030,
            delta_nm=100,
            rule_text="Runset expression: dnwell.enclosing(nwell_interact.holes, 1.03, euclidian)",
        )
        bad_dnwell = next(
            poly for poly in cases[1].to_dict()["lpl"] if poly["layer"] == "dnwell"
        )
        bad_width = bad_dnwell["points"][1][0] - bad_dnwell["points"][0][0]
        self.assertLess(bad_width, 5000)


if __name__ == "__main__":
    unittest.main()
