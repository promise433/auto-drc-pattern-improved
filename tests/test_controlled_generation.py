import unittest
from autodrc.controlled_generation import PrefixDiscriminator, structured_prompt, strict_final_payload
from autodrc.llm_generator import parse_model_response
from dataclasses import replace


class ControlledGenerationTests(unittest.TestCase):
    def test_outside_pool_is_blocked_and_discriminator_changes_branch(self):
        import torch
        processor=PrefixDiscriminator([[3,4],[3,5]],[0,4],prompt_length=1,eos_token_id=9,strength=2)
        # Token 6 is overwhelmingly preferred by the unmodified model but it
        # cannot complete a registered layout. Physical score selects token 5.
        logits=torch.zeros((1,10));logits[0,6]=100;logits[0,4]=3
        result=processor(torch.tensor([[1,3]]),logits)
        self.assertEqual(int(result.argmax()),5)
        self.assertTrue(torch.isneginf(result[0,6]))
        self.assertTrue(processor.events[0]['original_top_blocked'])
        end=processor(torch.tensor([[1,3,5]]),logits)
        self.assertEqual(int(end.argmax()),9)
        with self.assertRaises(ValueError):processor.allowed([3,8])

    def test_schema_constraints_and_rule_text_are_explicit(self):
        prompt=structured_prompt('Minimum NWell width 0.62um','BAD','nwell','ihp')
        self.assertIn('1000 nanometres',prompt)
        self.assertIn('Minimum NWell width 0.62um',prompt)
        self.assertIn('not text labels',prompt)
        self.assertIn('"primary_layer": "nwell"',prompt)
        self.assertNotIn('400',prompt)
        self.assertNotIn('REQUESTED_INTENT',prompt)
        self.assertIn('"intent":"BAD"',prompt)

    def test_nonmanhattan_is_explicit_and_legacy_serialization_preserved(self):
        raw='{"intent":"BAD","lpl":[{"layer":"met1","points":[[0,0],[100,0],[50,100],[0,0]]}]}'
        case=parse_model_response(raw,intent='BAD',expected_layer='met1',tech_name='sky130',strict=True)
        self.assertFalse(case.to_case_dict()['geometry_valid'])
        self.assertTrue(replace(case,allow_non_manhattan=True).to_case_dict()['geometry_valid'])

    def test_reasoning_cannot_use_an_intermediate_example_as_final_payload(self):
        raw='<think>{"intent":"GOOD","lpl":[]} example only</think>\n{"intent":"BAD","lpl":[]}'
        final=strict_final_payload(raw,reasoning=True)
        self.assertEqual(parse_model_response(final,intent='BAD',expected_layer='met1',tech_name='sky130',strict=True).intent,'BAD')
        self.assertEqual(strict_final_payload(raw),raw)

    def test_truncated_or_ambiguous_reasoning_is_rejected(self):
        from autodrc.llm_generator import LLMResponseError
        for raw in ('<think>{"intent":"GOOD","lpl":[]}', '<think>reason</think></think>{"intent":"GOOD","lpl":[]}'):
            with self.assertRaises(LLMResponseError):strict_final_payload(raw,reasoning=True)
