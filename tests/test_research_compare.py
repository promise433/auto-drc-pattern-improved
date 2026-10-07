import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autodrc.casegen import PatternCase
from autodrc.lpl import rectangle
from autodrc.research_compare import compare_fixed_candidates
from autodrc.rules import ParsedRule


class ResearchCompareTests(unittest.TestCase):
    def test_fixed_denominators_and_independent_gates(self):
        rule=ParsedRule('min_width','met1',140,'Minimum width 0.14um on met1')
        candidate=PatternCase('raw','BAD','actual',(rectangle('met1',0,0,100,400),))
        rows=compare_fixed_candidates(candidates={'GOOD':[],'BAD':[candidate],'ILLEGAL':[]},rule=rule,tech_name='sky130')
        self.assertEqual(len(rows),15)
        raw=[r for r in rows if r['arm']=='raw_model']
        self.assertIsNone(raw[0]['case']);self.assertIsNone(raw[2]['case'])
        self.assertEqual(raw[1]['case']['lpl'],candidate.to_dict()['lpl'])
        no_repair=next(r for r in rows if r['arm']=='no_repair' and r['intent']=='BAD')
        self.assertEqual(no_repair['case']['lpl'],candidate.to_dict()['lpl'])
        no_fallback=[r for r in rows if r['arm']=='no_fallback']
        self.assertIsNone(no_fallback[0]['case']);self.assertIsNone(no_fallback[2]['case'])

    def test_missing_or_mismatched_intent_slots_are_rejected(self):
        rule=ParsedRule('min_width','met1',140,'width')
        with self.assertRaises(ValueError):compare_fixed_candidates(candidates={'BAD':[]},rule=rule,tech_name='sky130')
        with self.assertRaises(ValueError):compare_fixed_candidates(candidates={'GOOD':[],
            'BAD':[PatternCase('x','GOOD','x',(rectangle('met1',0,0,100,400),))],'ILLEGAL':[]},rule=rule,tech_name='sky130')

    def test_unknown_technology_is_never_silently_sky(self):
        with self.assertRaises(ValueError):compare_fixed_candidates(candidates={'GOOD':[],'BAD':[],'ILLEGAL':[]},
            rule=ParsedRule('min_width','met1',140,'width'),tech_name='unknown')

    def test_selection_is_computed_once_for_all_model_arms(self):
        candidate=PatternCase('x','BAD','actual',(rectangle('met1',0,0,100,400),))
        with patch('autodrc.research_compare.select_best_llm_case',return_value=candidate) as choose:
            compare_fixed_candidates(candidates={'GOOD':[],'BAD':[candidate],'ILLEGAL':[]},
                rule=ParsedRule('min_width','met1',140,'width'),tech_name='sky130')
        self.assertEqual(choose.call_count,1)
