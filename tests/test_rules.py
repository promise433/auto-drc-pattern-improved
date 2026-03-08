from __future__ import annotations

import unittest

from autodrc.rules import parse_rule_text


class ParseRuleTests(unittest.TestCase):
    def test_parse_width_um(self) -> None:
        parsed = parse_rule_text("Minimum width 0.14um on met1")
        self.assertEqual(parsed.rule_type, "min_width")
        self.assertEqual(parsed.layer, "met1")
        self.assertEqual(parsed.threshold_nm, 140)

    def test_parse_spacing_nm(self) -> None:
        parsed = parse_rule_text("min spacing 220nm for li1")
        self.assertEqual(parsed.rule_type, "min_spacing")
        self.assertEqual(parsed.layer, "li1")
        self.assertEqual(parsed.threshold_nm, 220)

    def test_parse_density_percent(self) -> None:
        parsed = parse_rule_text("Minimum density 30% on met1")
        self.assertEqual(parsed.rule_type, "min_density")
        self.assertEqual(parsed.layer, "met1")
        self.assertEqual(parsed.threshold_nm, 3000)

    def test_parse_endcap(self) -> None:
        parsed = parse_rule_text("Poly endcap 0.15um")
        self.assertEqual(parsed.rule_type, "poly_endcap")
        self.assertEqual(parsed.layer, "poly")
        self.assertEqual(parsed.threshold_nm, 150)

    def test_parse_density_window(self) -> None:
        parsed = parse_rule_text("Minimum density 40% in window on met1")
        self.assertEqual(parsed.rule_type, "density_window")
        self.assertEqual(parsed.layer, "met1")
        self.assertEqual(parsed.threshold_nm, 4000)

    def test_parse_area_um2(self) -> None:
        parsed = parse_rule_text("Minimum area 0.14um2 on met1")
        self.assertEqual(parsed.rule_type, "min_area")
        self.assertEqual(parsed.layer, "met1")
        self.assertEqual(parsed.threshold_nm, 140000)

    def test_parse_via_enclosure(self) -> None:
        parsed = parse_rule_text("Minimum via enclosure 0.06um by met1")
        self.assertEqual(parsed.rule_type, "via_enclosure")
        self.assertEqual(parsed.layer, "met1")
        self.assertEqual(parsed.threshold_nm, 60)


if __name__ == "__main__":
    unittest.main()
