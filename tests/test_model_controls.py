import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autodrc.closed_loop import _generate_cases
from autodrc.llm_generator import build_prompt, generate_case_with_llm, parse_model_response, LLMResponseError


class ModelControlTests(unittest.TestCase):
    def test_default_prompt_is_preserved_and_compact_has_no_example_coordinates(self):
        default=build_prompt('Minimum width 0.14um on met1','GOOD')
        self.assertEqual(default,build_prompt('Minimum width 0.14um on met1','GOOD',prompt_profile='legacy'))
        compact=build_prompt('Minimum width 0.14um on met1','GOOD',prompt_profile='compact')
        self.assertNotIn('400',compact)
        self.assertNotIn('output_schema',compact)
        self.assertIn('integer nanometres',compact)
        with self.assertRaises(ValueError):build_prompt('width','GOOD',prompt_profile='invalid')

    def test_strict_parser_refuses_nested_example_rounding_and_unknown_layers(self):
        polygon=dict(layer='nwell',points=[[0,0],[400,0],[400,160],[0,160],[0,0]])
        value=dict(intent='BAD',lpl=[polygon])
        case=parse_model_response(json.dumps(value),intent='BAD',expected_layer='nwell',tech_name='ihp',strict=True)
        self.assertTrue(case.to_case_dict()['geometry_valid'])
        bad_values=[dict(output_schema=value),dict(intent='GOOD',lpl=[polygon]),
                    dict(intent='BAD',lpl=[dict(polygon,layer='not_a_physical_layer')]),
                    dict(intent='BAD',lpl=[dict(polygon,points=[[.5,0],[400,0],[400,160],[0,160],[.5,0]])])]
        for bad in bad_values:
            with self.subTest(bad=bad),self.assertRaises(LLMResponseError):
                parse_model_response(json.dumps(bad),intent='BAD',expected_layer='nwell',tech_name='ihp',strict=True)
        with self.assertRaises(LLMResponseError):
            parse_model_response('{"intent":"BAD","intent":"BAD","lpl":[]}',intent='BAD',expected_layer='nwell',tech_name='ihp',strict=True)

    def test_chat_uses_existing_template_and_decodes_only_new_tokens(self):
        raw='{"intent":"GOOD","lpl":[]}'
        tokenizer=Mock(return_value={'input_ids':SimpleNamespace(shape=(1,1))})
        tokenizer.chat_template='existing';tokenizer.apply_chat_template.return_value='NATIVE_PROMPT'
        tokenizer.decode.side_effect=lambda tokens,**kw:''.join(tokens)
        model=SimpleNamespace(config=SimpleNamespace(model_type='llama'),generate=Mock(return_value=[['PROMPT',raw]]))
        with tempfile.TemporaryDirectory() as tmp,patch('autodrc.llm_generator._load_model_and_tokenizer',return_value=(tokenizer,model)),patch.dict(
            'sys.modules',{'torch':SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:False))}):
            case=generate_case_with_llm(model_name='existing',rule_text='Use of met1 prohibited',intent='GOOD',prompt_profile='chat',debug_dir=Path(tmp))
            self.assertEqual(case.raw_response,raw)
            self.assertEqual((Path(tmp)/'llm_prompt_good.txt').read_text(),'NATIVE_PROMPT')
        self.assertFalse(tokenizer.call_args.kwargs['add_special_tokens'])

    def options(self):
        return dict(generator='llm',rule_type='min_width',layer='met1',threshold_nm=140,
            delta_nm=20,rule_text='Minimum width 0.14um on met1',llm_model='fixture',
            llm_max_new_tokens=128,llm_temperature=.2,llm_top_p=.9,
            llm_trust_remote_code=False,llm_load_in_4bit=False,llm_debug_dir=None)

    def test_fallback_can_run_without_repair(self):
        with patch('autodrc.closed_loop.generate_case_with_llm',side_effect=LLMResponseError('empty')),patch(
            'autodrc.closed_loop.adjust_llm_cases',side_effect=AssertionError('repair disabled')):
            cases=_generate_cases(**self.options(),llm_repair=False,llm_fallback=True)
        self.assertEqual(len(cases),3)
        self.assertTrue(all('[model-fallback:' in c.description for c in cases))

    def test_disabled_fallback_does_not_hide_response_failure(self):
        with patch('autodrc.closed_loop.generate_case_with_llm',side_effect=LLMResponseError('empty')):
            with self.assertRaises(RuntimeError):_generate_cases(**self.options(),llm_repair=True,llm_fallback=False)

    def test_fallback_never_hides_model_loading_failure(self):
        with patch('autodrc.closed_loop.generate_case_with_llm',side_effect=OSError('missing weights')):
            with self.assertRaises(RuntimeError):_generate_cases(**self.options(),llm_repair=False,llm_fallback=True)

    def test_pipeline_forwards_controls_to_selected_technology(self):
        from autodrc.pipeline import run_full_pipeline
        with tempfile.TemporaryDirectory() as tmp:
            runset=Path(tmp)/'sg13g2.drc';runset.write_text('# IHP-SG13G2')
            def workflow(**kw):
                kw['out_root'].mkdir();return dict(tech_name='ihp_sg13g2')
            with patch('autodrc.ihp_workflow.run_ihp_workflow',side_effect=workflow) as call:
                run_full_pipeline(out_root=Path(tmp)/'out',runset_path=runset,generator='llm',llm_model='existing',
                    llm_repair=False,llm_fallback=True,llm_prompt_profile='chat',llm_strict_response=True)
            self.assertFalse(call.call_args.kwargs['llm_repair'])
            self.assertTrue(call.call_args.kwargs['llm_fallback'])
            self.assertEqual(call.call_args.kwargs['llm_prompt_profile'],'chat')
            self.assertTrue(call.call_args.kwargs['llm_strict_response'])

    def test_coverage_cache_identity_includes_effective_controls(self):
        from autodrc.runset_coverage import run_runset_coverage
        with tempfile.TemporaryDirectory() as tmp:
            runset=Path(tmp)/'x.drc';runset.write_text('m1.width(0.14).output("m1.1","min m1 width 0.14um")')
            result=dict(iterations=[dict(good_ok=True,bad_ok=True)],iterations_run=1,converged=True)
            identities=[]
            with patch('autodrc.runset_coverage.run_closed_loop',return_value=result) as loop:
                for index,kwargs in enumerate([dict(llm_repair=False,llm_fallback=False),
                    dict(llm_repair=False,llm_fallback=True),dict(llm_repair=False,llm_fallback=True,llm_prompt_profile='chat',llm_strict_response=True)]):
                    out=Path(tmp)/str(index)
                    run_runset_coverage(runset_path=runset,out_dir=out,generator='llm',llm_model='fixture',**kwargs)
                    identity=json.loads(next((out/'cache_inputs').glob('*.json')).read_text())
                    identities.append(identity['parameters'])
                    for key,value in kwargs.items():self.assertEqual(loop.call_args.kwargs[key],value)
            self.assertNotEqual(identities[0],identities[1]);self.assertNotEqual(identities[1],identities[2])
