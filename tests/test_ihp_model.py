import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autodrc.casegen import PatternCase
from autodrc.closed_loop import _generate_cases
from autodrc.ihp_contracts import compile_contract, generate_contract_cases
from autodrc.llm_generator import LLMCase, LLMResponseError, _labels_from_payload, build_prompt
from autodrc.llm_policy import adjust_llm_cases
from autodrc.lpl import TextLabel, rectangle
from autodrc.rules import ParsedRule


class IHPModelTests(unittest.TestCase):
    def test_label_parsing_preserves_layer_cache_and_next_prompt(self):
        from autodrc.tech import load_known_layers_for_tech
        from autodrc.llm_generator import _polygons_from_payload
        known=load_known_layers_for_tech('ihp_sg13g2')
        before=set(known)
        prompt=build_prompt('M1.d','BAD','metal1',tech_name='ihp')
        _labels_from_payload({'labels':[dict(layer='text_0',text='E',position=[0,0])]},tech_name='ihp')
        self.assertEqual(known,before)
        self.assertEqual(build_prompt('M1.d','BAD','metal1',tech_name='ihp'),prompt)
        polygons=_polygons_from_payload({'lpl':[dict(layer='metal1',points=[[0,0],[100,0],[100,100],[0,100],[0,0]])]},
            expected_layer='activ',tech_name='ihp')
        self.assertEqual(polygons[0].layer,'metal1')

    def contract(self):
        return compile_contract('Cont.ext_not(Metal1)',
            ('L1:cont = source.polygons("6/0")','L2:metal1 = source.polygons("8/0")'),
            {'cont','metal1'}, 'min_enclosure')

    def test_good_bbox_cannot_accept_absent_derived_input(self):
        contract=self.contract();text='IHP contract: '+json.dumps(contract)
        rule=ParsedRule('min_enclosure','metal1',20,text)
        candidate=PatternCase('candidate','GOOD','model',(rectangle('metal1',0,0,1000,1000),))
        result=adjust_llm_cases(base_cases=[candidate],rule=rule,rule_text=text,tech_name='ihp')[0]
        self.assertIn('[repaired]',result.description)
        self.assertEqual(result.polygons,generate_contract_cases(contract,20)[0].polygons)
        self.assertIn('cont',{p.layer for p in result.polygons})

    def test_exact_construction_and_invalid_candidate_are_preserved(self):
        contract=self.contract();text='IHP contract: '+json.dumps(contract)
        cases=generate_contract_cases(contract,20)
        result=adjust_llm_cases(base_cases=cases,rule=ParsedRule('min_enclosure','metal1',20,text),
            rule_text=text,tech_name='ihp')
        self.assertEqual(result,cases)

    def test_device_labels_survive_repair_and_response_fallback(self):
        # Use the real template contract from the accepted local inventory.
        from autodrc.runset_coverage import classify_rule,_compose_runset_rule_text
        from autodrc.runset_corpus import parse_runset_outputs
        from autodrc.runset_semantics import parse_runset_output_semantics
        from autodrc.tech import load_known_layers_for_tech
        deck_setting=os.environ.get('AUTO_DRC_IHP_RUNSET')
        if not deck_setting: self.skipTest('AUTO_DRC_IHP_RUNSET is not configured')
        deck=Path(deck_setting)
        if not deck.exists(): self.skipTest('local official PDK absent')
        rule,semantic=next((r,s) for r,s in zip(parse_runset_outputs(deck),parse_runset_output_semantics(deck)) if r.rule_id=='npn13G2L.b')
        info=classify_rule(rule,load_known_layers_for_tech('ihp'),semantic)
        text=_compose_runset_rule_text(rule,semantic)
        options=dict(generator='llm',rule_type=info['rule_type'],layer=info['layer'],secondary_layer=info.get('layer_b'),
            threshold_nm=info['threshold_nm'],delta_nm=100,rule_text=text,llm_model='fixture',llm_max_new_tokens=128,
            llm_temperature=.2,llm_top_p=.9,llm_trust_remote_code=False,llm_load_in_4bit=False,tech_name='ihp')
        for response in (LLMResponseError('truncated JSON'),LLMCase('GOOD',(rectangle('trans',0,0,100,100),),'raw')):
            with tempfile.TemporaryDirectory() as tmp, patch('autodrc.closed_loop.generate_case_with_llm',side_effect=response if isinstance(response,Exception) else None,return_value=response):
                cases=_generate_cases(**options,llm_debug_dir=Path(tmp),llm_repair=True)
                self.assertTrue(all(c.labels for c in cases[:2]))
                self.assertTrue(all(c.to_dict()['geometry_valid'] for c in cases[:2]))
                self.assertEqual(len(json.loads((Path(tmp)/'generation_attempts.json').read_text())),5)

    def test_labels_are_validated_without_sanitizing_wrong_layers(self):
        payload={'labels':[dict(layer='text_0',text='E',position=[2,3])]}
        labels=_labels_from_payload(payload,tech_name='ihp')
        self.assertEqual(labels,(TextLabel('text_0','E',(2,3)),))
        case=LLMCase('GOOD',(rectangle('trans',0,0,100,100),),'raw',labels)
        self.assertTrue(case.to_case_dict()['geometry_valid'])
        for entry in (dict(layer='met1',text='E',position=[2,3]),dict(layer='text_0',text='',position=[2,3]),
                      dict(layer='text_0',text='E',position=[2.5,3])):
            with self.assertRaises(ValueError): _labels_from_payload({'labels':[entry]},tech_name='ihp')
        self.assertNotIn('labels',LLMCase('GOOD',case.polygons,'raw').to_case_dict())
        self.assertNotIn('coordinate_unit',build_prompt('test','GOOD',tech_name='sky130'))
        self.assertIn('integer nanometres',build_prompt('test','GOOD',tech_name='ihp'))

    def test_synthetic_research_is_ihp_geometry_without_drc_claim(self):
        from autodrc.ihp_research import evaluate_ihp_synthetic_tasks
        from autodrc.tech import load_known_layers_for_tech
        with tempfile.TemporaryDirectory() as tmp:
            result=evaluate_ihp_synthetic_tasks(Path(tmp)/'synthetic.json')
        self.assertEqual(len(result['semantic_results']),4)
        self.assertEqual(result['semantic_avg_pass_rate'],1.)
        self.assertFalse(result['unknown_task_drc_verified'])
        known=load_known_layers_for_tech('ihp')
        for row in result['semantic_results']:
            for check in row['checks']:
                self.assertTrue(all(p['layer'] in known for p in check['case']['lpl']))


if __name__=='__main__': unittest.main()
