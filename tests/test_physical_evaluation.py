import unittest
from autodrc.physical_evaluation import evaluate_observation


class PhysicalEvaluationTests(unittest.TestCase):
    def check(self,**kw):
        args=dict(intent='GOOD',geometry_valid=True,category_hits={},target_category='x',input_counts={'derived':1},minimums={'derived':1})
        args.update(kw);return evaluate_observation(**args)

    def test_empty_input_is_not_a_good_success(self):
        self.assertFalse(self.check(input_counts={'derived':0}).passed)
        self.assertFalse(self.check(input_counts={}).passed)

    def test_shared_category_wrong_branch_cannot_pass_bad(self):
        self.assertFalse(self.check(intent='BAD',category_hits={'x':1},selected_predicate_count=0).passed)
        self.assertTrue(self.check(intent='BAD',category_hits={'x':1},selected_predicate_count=1).passed)

    def test_other_hits_remain_visible_and_are_not_global_clean(self):
        value=self.check(category_hits={'other':2})
        self.assertTrue(value.passed);self.assertFalse(value.globally_clean);self.assertEqual(value.other_hits,{'other':2})
