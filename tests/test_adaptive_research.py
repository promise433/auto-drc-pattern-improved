import tempfile
from pathlib import Path
import unittest
from autodrc.adaptive_research import run_adaptive_research
from autodrc.research_design import CandidateSchedule


class AdaptiveResearchTests(unittest.TestCase):
    def run_case(self,schedule,feedback):
        calls=[]
        def generate(**kwargs):calls.append(kwargs);return kwargs
        evaluate=lambda c:dict(passed=c['round']==2 and c['candidate']==2)
        select=lambda rows:next((r for r in rows if r['observation']['passed']),rows[0])
        with tempfile.TemporaryDirectory() as tmp:
            result=run_adaptive_research(generate=generate,evaluate=evaluate,select=select,schedule=schedule,
                max_rounds=2,call_limit=4,out_path=Path(tmp)/'out.json',include_feedback=feedback)
        return result,calls

    def test_actual_failed_round_changes_next_requests_and_supplies_observations(self):
        result,calls=self.run_case(CandidateSchedule(),True)
        self.assertTrue(result['passed']);self.assertEqual(result['actual_calls'],3)
        self.assertIsNone(calls[0]['feedback']);self.assertFalse(calls[1]['feedback']['observations'][0]['passed'])

    def test_disabled_boost_and_feedback_remain_independent(self):
        result,calls=self.run_case(CandidateSchedule(feedback_boost=False),False)
        self.assertFalse(result['passed']);self.assertEqual(len(calls),2)
        self.assertTrue(all(c['feedback'] is None for c in calls))
