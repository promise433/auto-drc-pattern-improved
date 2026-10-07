"""Bounded IHP workflow using explicit official output identities."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path

from autodrc.instruction_dataset import build_feedback_rows, write_jsonl
from autodrc.runset_corpus import parse_runset_outputs
from autodrc.runset_coverage import run_runset_coverage, classify_rule
from autodrc.runset_semantics import parse_runset_output_semantics
from autodrc.tech import detect_tech_name, load_known_layers_for_tech
from autodrc.validation import build_validation_report
from autodrc.ihp_research import evaluate_ihp_synthetic_tasks, rank_ihp_corners, export_ihp_recipe


DEFAULT_RULE_IDS=('NW.a','NW.c','M1.c','Rsil.f','Cnt.b1','npn13G2L.b')


def ihp_pretrain_example(rule, semantic, classification):
    contract=classification.get('ihp_contract') or {}
    area=contract.get('rule_type') in {'min_area','max_area'}
    return dict(task='rule_to_runset',
        instruction='Map the official description and expression to executed IHP rule metadata.',
        input=dict(description=rule.description,expression=semantic.expression,anonymous_body=semantic.anonymous_body),
        output=dict(tech_name='ihp_sg13g2',rule_id=rule.rule_id,source_file=rule.source_file,line_no=rule.line_no,
            rule_type=contract.get('rule_type'),operand_layers=contract.get('operand_layers',[]),
            threshold_value=contract.get('threshold_nm'),threshold_unit=('nm2' if area else 'nm') if contract else None,
            supported=bool(contract) and classification['supported'],official_limitation=contract.get('official_limitation'),
            host_limitation=contract.get('host_limitation'),selected_branch=contract.get('selected_branch'),
            compound_expression=contract.get('compound_expression')),
        metadata=dict(tech_name='ihp_sg13g2',description_layer_hint=rule.layer_hint,
            description_threshold_hint_nm=rule.threshold_nm,hints_are_not_executed_values=True))


def run_ihp_workflow(*,runset_path: Path,out_root: Path,
                     rule_ids: tuple[str,...]=DEFAULT_RULE_IDS,
                     corner_deltas_nm: tuple[int,...]=(10,20,30),
                     generator: str='template', llm_model: str | None=None,
                     llm_max_new_tokens: int=128, llm_temperature: float=.2, llm_top_p: float=.9,
                     llm_trust_remote_code: bool=False,llm_load_in_4bit: bool=False,llm_repair: bool=True,
                     llm_fallback: bool | None=None,llm_prompt_profile: str='legacy',
                     llm_strict_response: bool=False,
                     run_selected_drc: bool=True) -> dict:
    if detect_tech_name(runset_path)!='ihp_sg13g2':
        raise ValueError('IHP workflow requires an IHP runset')
    if not rule_ids or len(rule_ids)>12 or len(set(rule_ids))!=len(rule_ids):
        raise ValueError('Select 1..12 distinct IHP output IDs')
    if len(corner_deltas_nm)>3 or any(type(x) is not int or x<=0 for x in corner_deltas_nm):
        raise ValueError('Select at most three positive corner offsets')
    if generator not in {'template','llm'} or (generator=='llm' and not llm_model):
        raise ValueError('Select template or llm with an explicit model')
    rules=parse_runset_outputs(runset_path)
    by_id={rule.rule_id:rule for rule in rules}
    missing=set(rule_ids)-by_id.keys()
    if missing:
        raise ValueError('Unknown IHP output IDs: '+', '.join(sorted(missing)))
    semantics={r.rule_id:s for r,s in zip(rules,parse_runset_output_semantics(runset_path))}
    classifications={r.rule_id:classify_rule(r,load_known_layers_for_tech('ihp'),semantics[r.rule_id]) for r in rules}
    for rule_id in rule_ids:
        classification=classifications[rule_id]
        if not classification['supported'] or not classification.get('ihp_contract'):
            raise ValueError('Unsupported IHP task '+rule_id+': '+classification['reason'])
    if out_root.exists():
        raise FileExistsError('Use a new isolated workflow output directory')
    # Preflight precedes output. IHP uses its own output identities and tasks.
    out_root.mkdir(parents=True)
    write_jsonl(out_root/'data/catalog.jsonl',(dict(tech_name='ihp_sg13g2',description_hints_only=True,
        executed_contract=classifications[r.rule_id].get('ihp_contract'),**asdict(r)) for r in rules))
    write_jsonl(out_root/'data/pretrain.jsonl',
        (ihp_pretrain_example(r,semantics[r.rule_id],classifications[r.rule_id]) for r in rules))
    coverage_dir=out_root/'runs/selected'
    coverage=run_runset_coverage(runset_path=runset_path,out_dir=coverage_dir,rule_ids=list(rule_ids),
        generator=generator,max_iters=3 if generator=='llm' else 1,initial_delta_nm=20,resume=False,
        llm_model=llm_model,llm_max_new_tokens=llm_max_new_tokens,llm_temperature=llm_temperature,llm_top_p=llm_top_p,
        llm_trust_remote_code=llm_trust_remote_code,llm_load_in_4bit=llm_load_in_4bit,llm_repair=llm_repair,
        llm_fallback=llm_fallback,llm_prompt_profile=llm_prompt_profile,llm_strict_response=llm_strict_response,
        llm_good_candidates=2,llm_bad_candidates=4,llm_illegal_candidates=1,
        llm_candidate_growth=2,llm_max_candidates_per_intent=8) if run_selected_drc else dict(summary={},rows=[])
    rows=coverage['rows']
    model_calls=0
    instructions=[]
    for row in rows:
        if not row.get('run_dir') or not (Path(row['run_dir'])/'summary.json').exists():
            continue
        summary=json.loads((Path(row['run_dir'])/'summary.json').read_text())
        model_calls+=summary.get('model_calls',0)
        iteration=summary['iterations'][-1]
        cases_dir=Path(row['run_dir'])/('iter_%02d'%iteration['iteration'])/'cases'
        for case in iteration['cases']:
            pattern=json.loads(next(cases_dir.glob('*_'+case['case_id']+'.json')).read_text())
            output=dict(intent=case['intent'],lpl=pattern['lpl'],description=pattern['description'])
            if pattern.get('labels'):output['labels']=pattern['labels']
            instructions.append(dict(task='instruction_tuning',
                instruction='Generate an IHP layout for the explicit official output and intent.',
                input=dict(tech_name='ihp_sg13g2',rule_id=row['rule_id'],source_file=row['source_file'],
                    line_no=row['line_no'],expression=row['runset_expression'],rule_text=iteration['rule_text'],intent=case['intent']),
                output=output,metadata=dict(tech_name='ihp_sg13g2',target_categories=[row['rule_id']],
                    source_summary=str(Path(row['run_dir'])/'summary.json'),geometry_valid=case['geometry_valid'],
                    intent_match=case['intent_match'],category_hits=case['category_hits'],generator=generator,
                    generation_source=next((x['source'] for x in iteration.get('generation_sources',[]) if x['case_id']==case['case_id']),'template'))))
    write_jsonl(out_root/'data/instruction.jsonl',instructions)
    feedback=build_feedback_rows(coverage_dir)
    for row in feedback:row['metadata']['tech_name']='ihp_sg13g2'
    write_jsonl(out_root/'data/feedback.jsonl',feedback)
    validation=build_validation_report(coverage_dir,out_path=out_root/'validation.json')
    corners=[]
    for delta in corner_deltas_nm:
        result=run_runset_coverage(runset_path=runset_path,out_dir=out_root/'runs'/('corner_'+str(delta)),
            rule_ids=['NW.a'],generator='template',max_iters=1,initial_delta_nm=delta,resume=False)
        corners.append(dict(rule_id='NW.a',delta_nm=delta,result=result))
    generalization=evaluate_ihp_synthetic_tasks(out_root/'research/generalization.json')
    corner_mining=rank_ihp_corners(corners,out_root/'research/corner_mining.json')
    recipes=export_ihp_recipe(out_root/'research/training_recipes.json',out_root/'data/instruction.jsonl',
        llm_model or os.environ.get('AUTO_DRC_LLM_MODEL','TinyLlama/TinyLlama-1.1B-Chat-v1.0'))
    summary=dict(tech_name='ihp_sg13g2',runset_path=str(runset_path),generator=generator,
        model_calls=model_calls,llm_model=llm_model,llm_repair=llm_repair,
        llm_fallback=llm_repair if llm_fallback is None else llm_fallback,
        llm_prompt_profile=llm_prompt_profile,llm_strict_response=llm_strict_response,training_started=False,
        rules=len(rules),selected_rule_ids=list(rule_ids) if run_selected_drc else [],
        coverage=coverage,instruction_rows=len(instructions),feedback_rows=len(feedback),
        validation=validation,corners=corners,generalization=generalization,corner_mining=corner_mining,
        recipes=recipes,unknown_task_drc_verified=False)
    (out_root/'summary.json').write_text(json.dumps(summary,indent=2))
    return summary


def main() -> int:
    import argparse
    parser=argparse.ArgumentParser(description='运行有限IHP模板/模型、数据和反馈流程；不训练')
    parser.add_argument('--runset',type=Path,required=True)
    parser.add_argument('--out-root',type=Path,required=True)
    parser.add_argument('--rule-id',action='append')
    parser.add_argument('--skip-corners',action='store_true')
    parser.add_argument('--generator',choices=['template','llm'],default='template')
    parser.add_argument('--llm-model')
    parser.add_argument('--llm-max-new-tokens',type=int,default=128)
    parser.add_argument('--llm-disable-repair',action='store_true')
    parser.add_argument('--llm-fallback',choices=['auto','enabled','disabled'],default='auto')
    parser.add_argument('--llm-prompt-profile',choices=['legacy','compact','chat'],default='legacy')
    parser.add_argument('--llm-strict-response',action='store_true')
    args=parser.parse_args()
    result=run_ihp_workflow(runset_path=args.runset,out_root=args.out_root,
        rule_ids=tuple(args.rule_id or DEFAULT_RULE_IDS),corner_deltas_nm=() if args.skip_corners else (10,20,30),
        generator=args.generator,llm_model=args.llm_model,llm_max_new_tokens=args.llm_max_new_tokens,
        llm_repair=not args.llm_disable_repair,
        llm_fallback={'auto':None,'enabled':True,'disabled':False}[args.llm_fallback],
        llm_prompt_profile=args.llm_prompt_profile,llm_strict_response=args.llm_strict_response)
    print(json.dumps(result,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
