from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from autodrc.casegen import (
    generate_cases_for_rule,
    generate_min_spacing_cases,
    generate_min_width_cases,
    write_cases,
)


class CasegenTests(unittest.TestCase):
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

    def test_generate_cross_layer_spacing_cases_from_rule_text(self) -> None:
        cases = generate_cases_for_rule(
            rule_type="min_spacing",
            layer="hvtr",
            threshold_nm=380,
            delta_nm=20,
            rule_text="Runset expression: hvtr.separation(hvtp, 0.38, euclidian)",
        )
        layers = {poly["layer"] for poly in cases[1].to_dict()["lpl"]}
        self.assertIn("hvtr", layers)
        self.assertIn("hvtp", layers)

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
        self.assertEqual(len(density_cases), 3)
        self.assertEqual(len(endcap_cases), 3)
        self.assertEqual(len(window_cases), 3)
        self.assertEqual(len(enclosure_cases), 3)
        self.assertEqual(len(area_cases), 3)
        self.assertEqual(len(interact_cases), 3)
        self.assertEqual(len(forbidden_use_cases), 3)
        self.assertEqual(len(max_width_cases), 3)
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
