"""Independent gates must control execution, not just source labels."""
import json
import unittest
from unittest.mock import patch

from autodrc.casegen import PatternCase, generate_cases_for_rule
from autodrc.rules import ParsedRule
from scripts.ihp_fixed_ablation import replay_intents, geometry


class FixedAblationTest(unittest.TestCase):
    def setUp(self):
        contract = dict(expression='NWell.ext_width(0.62.um)', operation='ext_width',
            rule_type='min_width', threshold_nm=620, operands=['NWell'],
            operand_layers=['nwell'], operand_sizes=[None],
            input_clauses=[[dict(present=['nwell'], absent=[])]], options=[])
        self.rule = ParsedRule('min_width', 'nwell', 620,
            'Rule ID: NW.a\nRunset expression: NWell.ext_width(0.62.um)\nIHP contract: ' + json.dumps(contract))
        from autodrc.lpl import Polygon
        self.bad = PatternCase('raw', 'BAD', 'actual candidate',
            (Polygon('nwell', ((0,0),(400,0),(400,160),(0,160),(0,0))),))
        self.pools = {'GOOD': [], 'BAD': [self.bad], 'ILLEGAL': []}

    def test_raw_never_generates_or_repairs(self):
        with patch('scripts.ihp_fixed_ablation.generate_cases_for_rule', side_effect=AssertionError), \
             patch('scripts.ihp_fixed_ablation.adjust_llm_cases', side_effect=AssertionError):
            rows = replay_intents(candidates=self.pools, rule=self.rule,
                                  repair_enabled=False, fallback_enabled=False)
        self.assertIsNone(rows[0]['case'])
        self.assertIs(rows[1]['case'], self.bad)
        self.assertIsNone(rows[2]['case'])

    def test_no_repair_retains_raw_and_fills_only_missing(self):
        with patch('scripts.ihp_fixed_ablation.adjust_llm_cases', side_effect=AssertionError):
            rows = replay_intents(candidates=self.pools, rule=self.rule,
                                  repair_enabled=False, fallback_enabled=True)
        self.assertIs(rows[1]['case'], self.bad)
        self.assertEqual([r['source'] for r in rows],
                         ['template_fallback', 'model', 'template_fallback'])

    def test_no_fallback_repairs_available_without_filling_missing(self):
        rows = replay_intents(candidates=self.pools, rule=self.rule,
                              repair_enabled=True, fallback_enabled=False)
        self.assertIsNone(rows[0]['case'])
        self.assertIsNone(rows[2]['case'])
        self.assertEqual(rows[1]['source'], 'template_repair')
        self.assertNotEqual(geometry(self.bad.to_dict()), geometry(rows[1]['case'].to_dict()))

    def test_hybrid_geometry_matches_template(self):
        rows = replay_intents(candidates=self.pools, rule=self.rule)
        templates = generate_cases_for_rule(rule_type='min_width', layer='nwell',
            threshold_nm=620, delta_nm=20, rule_text=self.rule.source_text,
            tech_name='ihp_sg13g2')
        for row, template in zip(rows, templates):
            self.assertEqual(geometry(row['case'].to_dict()), geometry(template.to_dict()))

    def test_fallback_does_not_replace_available_invalid_geometry(self):
        invalid = generate_cases_for_rule(rule_type='min_width', layer='nwell',
            threshold_nm=620, delta_nm=20, rule_text=self.rule.source_text,
            tech_name='ihp_sg13g2')[2]
        self.pools['ILLEGAL'] = [invalid]
        rows = replay_intents(candidates=self.pools, rule=self.rule,
                              repair_enabled=False, fallback_enabled=True)
        self.assertIs(rows[2]['case'], invalid)
        self.assertEqual(rows[2]['source'], 'model')
