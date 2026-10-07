"""固定候选对照：保留缺失和失败，不启动模型或物理引擎。"""
from __future__ import annotations
from dataclasses import replace
import json
from pathlib import Path
from autodrc.casegen import PatternCase, generate_cases_for_rule
from autodrc.llm_policy import adjust_llm_cases, select_best_llm_case
from autodrc.rules import ParsedRule
from autodrc.tech import normalize_tech_name

ARMS = {'template': None, 'raw_model': (False, False), 'hybrid': (True, True),
        'no_repair': (False, True), 'no_fallback': (True, False)}
INTENTS = ('GOOD', 'BAD', 'ILLEGAL')


def compare_fixed_candidates(*, candidates: dict[str, list[PatternCase]],
        rule: ParsedRule, tech_name: str, secondary_layer: str | None = None,
        delta_nm: int = 20, rigorous_geometry: bool = False) -> list[dict]:
    tech = normalize_tech_name(tech_name)
    if set(candidates) != set(INTENTS):
        raise ValueError('必须保留GOOD/BAD/ILLEGAL三个意图的固定候选槽')
    if any(case.intent != intent for intent,pool in candidates.items() for case in pool):
        raise ValueError('候选意图与固定槽不一致')
    if rigorous_geometry:
        candidates={intent:[replace(case,rigorous_geometry=True) for case in pool]
                    for intent,pool in candidates.items()}
    # Selection is computed once and shared by all four model arms.
    selected = {intent:select_best_llm_case(candidates=pool,rule=rule) if pool else None
                for intent,pool in candidates.items()}
    result=[]
    for arm,switches in ARMS.items():
        if switches is None:
            cases=generate_cases_for_rule(rule_type=rule.rule_type,layer=rule.layer,
                layer_b=secondary_layer,threshold_nm=rule.threshold_nm,delta_nm=delta_nm,
                rule_text=rule.source_text,tech_name=tech)
            cases=[replace(c,rigorous_geometry=True) for c in cases] if rigorous_geometry else cases
            result.extend(dict(arm=arm,intent=c.intent,source='template',case=c.to_dict(),
                before_repair=None,candidate_count=None) for c in cases)
            continue
        repair,fallback=switches
        for intent in INTENTS:
            case=selected[intent];source='model' if case else 'missing'
            if case is None and fallback:
                case=next(c for c in generate_cases_for_rule(rule_type=rule.rule_type,
                    layer=rule.layer,layer_b=secondary_layer,threshold_nm=rule.threshold_nm,
                    delta_nm=20 if tech=='ihp_sg13g2' else delta_nm,
                    rule_text=rule.source_text,tech_name=tech) if c.intent==intent)
                case=replace(case,description='[model-fallback:no-usable-response] '+case.description)
                source='template_fallback'
            if case is not None and rigorous_geometry:
                case=replace(case,rigorous_geometry=True)
            before=case
            if case is not None and repair:
                case=adjust_llm_cases(base_cases=[case],rule=rule,
                    secondary_layer=secondary_layer,rule_text=rule.source_text,tech_name=tech)[0]
                if '[repaired]' in case.description:source='template_repair'
            result.append(dict(arm=arm,intent=intent,source=source,
                case=case.to_dict() if case else None,
                before_repair=before.to_dict() if before else None,
                candidate_count=len(candidates[intent])))
    return result


def run_fixed_comparison(*, task_manifest: Path, model_trace: Path, out_dir: Path,
                         strict_response: bool = True) -> dict:
    """复用用户指定的真实响应，输出五组固定分母；不执行物理DRC。"""
    from autodrc.llm_generator import parse_model_response, LLMResponseError
    from autodrc.runset_coverage import (parse_runset_outputs, parse_runset_output_semantics,
        classify_rule, _compose_runset_rule_text, _load_layer_map, _parse_layer_aliases, _parse_wildcards)
    from autodrc.tech import detect_tech_name, layer_map_path_for_runset
    tasks=json.loads(task_manifest.read_text());trace=json.loads(model_trace.read_text())
    if not isinstance(tasks,list) or not tasks or not isinstance(trace,list):
        raise ValueError('需要非空任务清单和真实调用列表')
    if len({t['key'] for t in tasks})!=len(tasks):
        raise ValueError('重复任务身份')
    # Before creating output, tie each task back to the actual official output.
    official={}
    for task in tasks:
        runset=Path(task['runset_path'])
        if str(runset) not in official:
            rules=parse_runset_outputs(runset);semantics=parse_runset_output_semantics(runset)
            layers=_load_layer_map(layer_map_path_for_runset(runset)) | set(_parse_layer_aliases(runset,_parse_wildcards(runset)))
            official[str(runset)]=(rules,semantics,layers)
        rules,semantics,layers=official[str(runset)]
        index=task['global_index']-1
        if not 0<=index<len(rules):raise ValueError('任务索引越界')
        rule,semantic=rules[index],semantics[index]
        if (rule.rule_id,rule.line_no,detect_tech_name(runset))!=(task['rule_id'],task['line_no'],task['tech_name']):
            raise ValueError('任务与官方身份/工艺不一致')
        if task['rule_text']!=_compose_runset_rule_text(rule,semantic) or task['classification']!=classify_rule(rule,layers,semantic):
            raise ValueError('任务文本或分类与当前官方脚本不一致')
    task_by_key={t['key']:t for t in tasks}
    if any(record.get('task_key') not in task_by_key for record in trace):
        raise ValueError('调用指向未登记任务')
    if not trace or len({r['index'] for r in trace})!=len(trace):
        raise ValueError('调用列表为空或有重复身份')
    import hashlib
    profiles=list(dict.fromkeys(record['profile'] for record in trace))
    rows=[];responses=[]
    for profile in profiles:
        for task in tasks:
            pools={intent:[] for intent in INTENTS}
            calls=[r for r in trace if r['profile']==profile and r['task_key']==task['key']]
            # A missing response file is an evidence-integrity error. A recorded
            # failed completion is retained in the fixed denominator instead.
            for record in calls:
                raw_path=Path(record['call_dir'])/('llm_raw_'+record['intent'].lower()+'.txt')
                raw=raw_path.read_text();info=task['classification']
                if record.get('raw_sha256') and hashlib.sha256(raw_path.read_bytes()).hexdigest()!=record['raw_sha256']:
                    raise ValueError('原始响应哈希不一致')
                if record['intent'] not in INTENTS or record.get('tech_name',task['tech_name'])!=task['tech_name']:
                    raise ValueError('调用意图或工艺身份不一致')
                status=dict(profile=profile,task_key=task['key'],call_index=record['index'],
                            intent=record['intent'],raw_path=str(raw_path))
                try:
                    parsed=parse_model_response(raw,intent=record['intent'],expected_layer=info['layer'],
                        tech_name=task['tech_name'],strict=strict_response)
                    pools[record['intent']].append(PatternCase(task['key']+'_'+record['intent'].lower(),
                        record['intent'],'actual-model-call='+str(record['index']),parsed.polygons,
                        labels=parsed.labels,rigorous_geometry=strict_response))
                    status['status']='returned'
                except LLMResponseError as exc:
                    status.update(status='response_error',error=str(exc))
                responses.append(status)
            info=task['classification']
            rule=ParsedRule(info['rule_type'],info['layer'],info['threshold_nm'],task['rule_text'])
            rows.extend(dict(profile=profile,task_key=task['key'],**row) for row in
                compare_fixed_candidates(candidates=pools,rule=rule,tech_name=task['tech_name'],secondary_layer=info.get('layer_b'),rigorous_geometry=strict_response))
    if out_dir.exists():raise FileExistsError('请使用新的独立输出目录')
    out_dir.mkdir(parents=True)
    import hashlib
    identity=dict(task_manifest=str(task_manifest),task_sha256=hashlib.sha256(task_manifest.read_bytes()).hexdigest(),
        model_trace=str(model_trace),trace_sha256=hashlib.sha256(model_trace.read_bytes()).hexdigest(),
        strict_response=strict_response,new_model_calls=0,new_drc_calls=0,
        tasks=len(tasks),profiles=profiles,slots_per_arm=len(tasks)*3,
        physical_verified=False,scope='固定候选构造对照；物理正确性须由独立DRC和输入/分支审查证明')
    for name,data in [('cases.json',rows),('responses.json',responses),('identity.json',identity)]:
        (out_dir/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    return identity


def main():
    import argparse
    p=argparse.ArgumentParser(description='零新模型调用的双工艺固定候选五组对照')
    p.add_argument('--task-manifest',type=Path,required=True)
    p.add_argument('--model-trace',type=Path,required=True)
    p.add_argument('--out-dir',type=Path,required=True)
    p.add_argument('--legacy-parser',action='store_true',help='复核历史宽松解析，保留转换来源边界')
    args=p.parse_args()
    print(json.dumps(run_fixed_comparison(task_manifest=args.task_manifest,model_trace=args.model_trace,
        out_dir=args.out_dir,strict_response=not args.legacy_parser),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
