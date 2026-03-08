from __future__ import annotations

import unittest

from autodrc.casegen import generate_cases_for_rule
from autodrc.generalization import check_case_semantics
from autodrc.specs import RuleTask


class GeneralizationTests(unittest.TestCase):
    def test_min_density_semantics(self) -> None:
        task = RuleTask(
            name="x",
            rule_type="min_density",
            layer="met1",
            threshold_nm=3000,
            description="",
            known_rule=False,
        )
        cases = generate_cases_for_rule(
            rule_type=task.rule_type,
            layer=task.layer,
            threshold_nm=task.threshold_nm,
            delta_nm=20,
        )
        checks = [check_case_semantics(c, task) for c in cases]
        self.assertEqual(checks, [True, True, True])

    def test_poly_endcap_semantics(self) -> None:
        task = RuleTask(
            name="x",
            rule_type="poly_endcap",
            layer="poly",
            threshold_nm=150,
            description="",
            known_rule=False,
        )
        cases = generate_cases_for_rule(
            rule_type=task.rule_type,
            layer=task.layer,
            threshold_nm=task.threshold_nm,
            delta_nm=20,
        )
        checks = [check_case_semantics(c, task) for c in cases]
        self.assertEqual(checks, [True, True, True])

    def test_density_window_semantics(self) -> None:
        task = RuleTask(
            name="x",
            rule_type="density_window",
            layer="met1",
            threshold_nm=4000,
            description="",
            known_rule=False,
        )
        cases = generate_cases_for_rule(
            rule_type=task.rule_type,
            layer=task.layer,
            threshold_nm=task.threshold_nm,
            delta_nm=20,
        )
        checks = [check_case_semantics(c, task) for c in cases]
        self.assertEqual(checks, [True, True, True])

    def test_via_enclosure_semantics(self) -> None:
        task = RuleTask(
            name="x",
            rule_type="via_enclosure",
            layer="met1",
            threshold_nm=60,
            description="",
            known_rule=False,
        )
        cases = generate_cases_for_rule(
            rule_type=task.rule_type,
            layer=task.layer,
            threshold_nm=task.threshold_nm,
            delta_nm=20,
        )
        checks = [check_case_semantics(c, task) for c in cases]
        self.assertEqual(checks, [True, True, True])


if __name__ == "__main__":
    unittest.main()
