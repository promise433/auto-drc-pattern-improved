import unittest
from autodrc.research_design import semantic_text,CandidateSchedule,replay_candidate_policy


class ResearchDesignTests(unittest.TestCase):
    def test_semantic_profiles_remove_upstream_without_substituting_template_coordinates(self):
        text='Rule ID: x\nDescription: width\nRunset expression: m.width(0.14)\nRunset context: if BEOL\nUpstream chain: a=b'
        self.assertNotIn('expression',semantic_text(text,'description'))
        self.assertNotIn('Upstream',semantic_text(text,'context'))
        self.assertEqual(semantic_text(text,'full'),text)
        with self.assertRaises(ValueError):semantic_text(text,'unknown')

    def test_feedback_changes_only_requested_pool_size_and_cost(self):
        pools=[[dict(id='fail',passed=False),dict(id='second',passed=True)] for _ in range(2)]
        select=lambda rows:next((r for r in rows if r['passed']),rows[0])
        fixed=replay_candidate_policy(rounds=pools,schedule=CandidateSchedule(feedback_boost=False),select=select)
        boost=replay_candidate_policy(rounds=pools,schedule=CandidateSchedule(),select=select)
        self.assertFalse(fixed['passed']);self.assertEqual(fixed['candidate_calls_charged'],2)
        self.assertTrue(boost['passed']);self.assertEqual(boost['candidate_calls_charged'],3)

    def test_missing_candidate_is_integrity_error_not_an_easier_denominator(self):
        with self.assertRaises(ValueError):replay_candidate_policy(rounds=[[]],schedule=CandidateSchedule(),select=lambda x:None)
