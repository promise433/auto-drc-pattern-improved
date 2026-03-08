from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autodrc.closed_loop import (
    _generate_cases,
    _next_delta_nm,
    _next_llm_candidate_counts,
    evaluate_intent,
    parse_lyrdb_items,
)


class ClosedLoopHelpersTests(unittest.TestCase):
    def test_evaluate_intent(self) -> None:
        self.assertTrue(evaluate_intent("GOOD", geometry_valid=True, drc_items=0))
        self.assertFalse(evaluate_intent("GOOD", geometry_valid=True, drc_items=2))
        self.assertTrue(evaluate_intent("BAD", geometry_valid=True, drc_items=1))
        self.assertFalse(evaluate_intent("BAD", geometry_valid=True, drc_items=0))
        self.assertTrue(evaluate_intent("ILLEGAL", geometry_valid=False, drc_items=0))

    def test_parse_lyrdb_items(self) -> None:
        content = """<?xml version="1.0" encoding="utf-8"?>
<report-database>
  <items>
    <item><category>'m1.1'</category></item>
    <item><category>'m1.1'</category></item>
    <item><category>'m1.6'</category></item>
  </items>
</report-database>
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "r.lyrdb"
            p.write_text(content, encoding="utf-8")
            count, hits = parse_lyrdb_items(p)
        self.assertEqual(count, 3)
        self.assertEqual(hits, {"m1.1": 2, "m1.6": 1})

    def test_generate_cases_template_backend(self) -> None:
        cases = _generate_cases(
            generator="template",
            rule_type="min_width",
            layer="met1",
            threshold_nm=140,
            delta_nm=20,
            rule_text="Minimum width 0.14um on met1",
            llm_model=None,
            llm_max_new_tokens=64,
            llm_temperature=0.2,
            llm_top_p=0.9,
            llm_trust_remote_code=False,
            llm_load_in_4bit=False,
            llm_debug_dir=None,
            llm_repair=True,
        )
        self.assertEqual(len(cases), 3)
        self.assertEqual([c.intent for c in cases], ["GOOD", "BAD", "ILLEGAL"])

    def test_next_delta_nm_accelerates_on_dual_miss(self) -> None:
        nxt, reason = _next_delta_nm(
            current_delta_nm=20,
            delta_step_nm=10,
            good_ok=False,
            bad_ok=False,
            good_target_hits=1,
            bad_target_hits=0,
        )
        self.assertEqual(nxt, 40)
        self.assertEqual(reason, "dual_miss_accelerate")

    def test_next_delta_nm_steady_when_single_side_miss(self) -> None:
        nxt, reason = _next_delta_nm(
            current_delta_nm=20,
            delta_step_nm=10,
            good_ok=True,
            bad_ok=False,
            good_target_hits=0,
            bad_target_hits=2,
        )
        self.assertEqual(nxt, 30)
        self.assertEqual(reason, "steady_step")

    def test_next_llm_candidate_counts_boosts_only_failed_intent(self) -> None:
        good, bad, illegal, actions = _next_llm_candidate_counts(
            feedback_boost=True,
            candidate_growth=2,
            max_candidates_per_intent=6,
            current_good=2,
            current_bad=3,
            current_illegal=1,
            good_ok=False,
            bad_ok=True,
        )
        self.assertEqual(good, 4)
        self.assertEqual(bad, 3)
        self.assertEqual(illegal, 1)
        self.assertEqual(actions, ["boost_good_candidates"])


if __name__ == "__main__":
    unittest.main()
