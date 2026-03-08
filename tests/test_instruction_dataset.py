from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from autodrc.instruction_dataset import build_feedback_rows, build_instruction_rows
from autodrc.specs import KNOWN_TASKS


class InstructionDatasetTests(unittest.TestCase):
    def test_build_instruction_rows(self) -> None:
        rows = build_instruction_rows(KNOWN_TASKS[:1], delta_nm=20)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["task"], "instruction_tuning")

    def test_build_feedback_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x" / "iteration_summary.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                json.dumps(
                    {
                        "rule_type": "min_width",
                        "layer": "met1",
                        "threshold_nm": 140,
                        "iteration": 2,
                        "delta_nm": 30,
                        "good_ok": False,
                        "bad_ok": True,
                        "converged_this_iter": False,
                        "target_categories": ["m1.1"],
                        "cases": [
                            {
                                "case_id": "a",
                                "intent": "GOOD",
                                "geometry_valid": True,
                                "drc_items_target": 0,
                                "category_hits": {},
                                "intent_match": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            rows = build_feedback_rows(Path(tmp))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["output"]["label"], "accept")
        self.assertEqual(rows[0]["input"]["iteration"], 2)
        self.assertEqual(rows[0]["input"]["delta_nm"], 30)
        self.assertFalse(rows[0]["input"]["good_ok"])
        self.assertTrue(rows[0]["input"]["bad_ok"])


if __name__ == "__main__":
    unittest.main()
