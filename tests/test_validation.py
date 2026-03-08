from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from autodrc.validation import build_validation_report, compute_case_metrics


class ValidationTests(unittest.TestCase):
    def test_compute_case_metrics(self) -> None:
        cases = [
            {
                "intent": "GOOD",
                "geometry_valid": True,
                "drc_items_target": 0,
                "intent_match": True,
            },
            {
                "intent": "BAD",
                "geometry_valid": True,
                "drc_items_target": 2,
                "intent_match": True,
            },
            {
                "intent": "ILLEGAL",
                "geometry_valid": False,
                "drc_items_target": None,
                "intent_match": True,
            },
        ]
        metrics = compute_case_metrics(cases)
        self.assertEqual(metrics["total_cases"], 3)
        self.assertAlmostEqual(metrics["intent_accuracy"], 1.0)
        self.assertAlmostEqual(metrics["target_rule_hit_rate"], 1.0)
        self.assertAlmostEqual(metrics["false_positive_rate"], 0.0)
        self.assertAlmostEqual(metrics["illegal_detection_rate"], 1.0)

    def test_build_validation_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary = root / "run_a" / "iteration_summary.json"
            summary.parent.mkdir(parents=True, exist_ok=True)
            summary.write_text(
                json.dumps(
                    {
                        "iteration": 1,
                        "rule_type": "min_width",
                        "layer": "met1",
                        "threshold_nm": 140,
                        "target_categories": ["m1.1"],
                        "cases": [
                            {
                                "intent": "GOOD",
                                "geometry_valid": True,
                                "drc_items_target": 0,
                                "intent_match": True,
                            },
                            {
                                "intent": "BAD",
                                "geometry_valid": True,
                                "drc_items_target": 1,
                                "intent_match": True,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out_path = root / "validation.json"
            report = build_validation_report(root, out_path=out_path)
            self.assertTrue(out_path.exists())

        self.assertEqual(report["entries"], 1)
        self.assertAlmostEqual(report["overall"]["intent_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
