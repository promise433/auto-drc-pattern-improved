#!/usr/bin/env python3
"""Offline fixed-candidate IHP ablation; never loads or invokes a model.

Repair includes the conservative IHP verified-construction replacement.
Fallback applies only to an intent with no successfully parsed response.
Missing intents remain explicit records rather than aborting another intent.
Production closed_loop and its defaults are deliberately not changed.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

from autodrc.casegen import PatternCase, generate_cases_for_rule
from autodrc.llm_policy import adjust_llm_cases, select_best_llm_case
from autodrc.rules import ParsedRule

INTENTS = ('GOOD', 'BAD', 'ILLEGAL')
GROUPS = {'template': None, 'raw_model': (False, False),
          'hybrid': (True, True), 'no_repair': (False, True),
          'no_fallback': (True, False)}


def replay_intents(*, candidates, rule, secondary_layer=None,
                   repair_enabled=True, fallback_enabled=True):
    """Select identical candidates, then independently gate fallback/repair.

    This deliberately evaluates available intents even when another is missing;
    production aborts in that situation with repair disabled. It is a fixed
    candidate experiment, not a replay of the entire adaptive closed loop.
    """
    result = []
    for intent in INTENTS:
        pool = candidates[intent]
        selected = None
        source = 'missing'
        if pool:
            selected = select_best_llm_case(candidates=pool, rule=rule)
            source = 'model'
        elif fallback_enabled:
            selected = next(c for c in generate_cases_for_rule(
                rule_type=rule.rule_type, layer=rule.layer,
                layer_b=secondary_layer, threshold_nm=rule.threshold_nm,
                delta_nm=20, rule_text=rule.source_text,
                tech_name='ihp_sg13g2') if c.intent == intent)
            selected = replace(selected,
                               case_id=f'{rule.layer}_{rule.rule_type}_{intent.lower()}_llm',
                               description=
                               '[model-fallback:no-usable-response] ' + selected.description)
            source = 'template_fallback'
        before = selected
        if selected is not None and repair_enabled:
            selected = adjust_llm_cases(base_cases=[selected], rule=rule,
                secondary_layer=secondary_layer, rule_text=rule.source_text,
                tech_name='ihp_sg13g2')[0]
            if '[repaired]' in selected.description:
                source = 'template_repair'
        result.append(dict(intent=intent, source=source, case=selected,
                           before_repair=before, candidate_count=len(pool)))
    return result


_evidence = None


def evidence_bytes(path):
    global _evidence
    if Path(path).is_file():
        return Path(path).read_bytes()
    if _evidence is None:
        from scripts.project_quality import Evidence
        _evidence = Evidence()
    return _evidence.read_bytes(str(path))


def read(path):
    return json.loads(evidence_bytes(path))


def saved_case(directory, case_id):
    matches = list((directory / 'cases').glob('*_' + case_id + '.json'))
    if not matches:
        global _evidence
        if _evidence is None:
            from scripts.project_quality import Evidence
            _evidence = Evidence()
        prefix = str(directory / 'cases') + '/'
        matches = [Path(p) for p in _evidence.entries if p.startswith(prefix) and p.endswith('_' + case_id + '.json')]
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one recorded case: ' + case_id)
    return read(matches[0])


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def geometry(case):
    return {k: case.get(k, [] if k in {'lpl', 'labels'} else False)
            for k in ('lpl', 'labels', 'allow_non_manhattan')}


def evaluate(out, evidence):
    from autodrc.llm_generator import (_extract_json, _polygons_from_payload,
        _labels_from_payload, LLMCase)
    import autodrc.llm_generator as generator
    from autodrc.tech import load_known_layers_for_tech
    # Fail fast if any accidental inference path is reached.
    def forbidden(*a, **kw):
        raise AssertionError('New model calls are forbidden')
    generator._load_model_and_tokenizer = forbidden
    generator.generate_case_with_llm = forbidden
    started = time.monotonic()
    trace = read(evidence / 'model_trace.json')
    rows = [json.loads(x) for x in evidence_bytes(evidence / 'coverage/coverage_rows.jsonl').decode().splitlines()]
    assert len(rows) == 7 and len(trace) == 49
    parsed = []
    known = set(load_known_layers_for_tech('ihp_sg13g2'))
    for record in trace:
        raw_path = Path(record['call_dir']) / ('llm_raw_' + record['intent'].lower() + '.txt')
        raw_bytes = evidence_bytes(raw_path)
        raw = raw_bytes.decode()
        item = dict(index=record['index'], intent=record['intent'],
            original_status=record['status'], raw_path=str(raw_path),
            raw_sha256=hashlib.sha256(raw_bytes).hexdigest(),
            prompt_path=str(Path(record['call_dir']) / 'prompt.txt'),
            prompt_sha256=record['prompt_sha256'], parameters=record['parameters'],
            original_error=record.get('error'), original_seconds=record['elapsed_seconds'])
        try:
            payload = _extract_json(raw)
            polys = _polygons_from_payload(payload,
                expected_layer=record['parameters']['expected_layer'], tech_name='ihp_sg13g2')
            labels = _labels_from_payload(payload, tech_name='ihp_sg13g2')
            if payload.get('intent', record['intent']) != record['intent']:
                raise ValueError('Response intent does not match requested intent')
            case = LLMCase(record['intent'], polys, raw, labels)
            item.update(status='returned', payload=case.to_case_dict())
        except (ValueError, TypeError, OverflowError) as exc:
            item.update(status='error', error=str(exc))
        assert item['status'] == record['status']
        assert set(load_known_layers_for_tech('ihp_sg13g2')) == known
        parsed.append(item)
    save(out / 'responses.json', parsed)
    all_results = []
    unique = {}
    for row in rows:
        directory = Path(row['run_dir']) / 'iter_01'
        summary = read(Path(row['run_dir']) / 'summary.json')
        assert len(summary['iterations']) == 1
        text = summary['iterations'][0]['rule_text']
        rule = ParsedRule(row['rule_type_engine'], row['layer'], row['threshold_engine_nm'], text)
        pools = {intent: [] for intent in INTENTS}
        indices = []
        for item in parsed:
            if Path(item['parameters']['debug_dir']).parent.parent != directory:
                continue
            indices.append(item['index'])
            if item['status'] != 'returned':
                continue
            payload = item['payload']
            from autodrc.llm_generator import _polygons_from_payload, _labels_from_payload
            attempt = int(Path(item['parameters']['debug_dir']).name.rsplit('_', 1)[1])
            pools[item['intent']].append(PatternCase(
                f"{row['layer']}_{row['rule_type_engine']}_{item['intent'].lower()}_llm",
                item['intent'], f'llm-generated for: {text} [cand={attempt}]',
                _polygons_from_payload(payload, expected_layer=row['layer'], tech_name='ihp_sg13g2'),
                labels=_labels_from_payload(payload, tech_name='ihp_sg13g2')))
        assert len(indices) == 7
        for group, switches in GROUPS.items():
            tick = time.monotonic()
            if switches is None:
                cases = generate_cases_for_rule(rule_type=rule.rule_type, layer=rule.layer,
                    layer_b=row.get('layer_b'), threshold_nm=rule.threshold_nm,
                    delta_nm=20, rule_text=text, tech_name='ihp_sg13g2')
                results = [dict(intent=c.intent, case=c, before_repair=None,
                                source='template', candidate_count=None) for c in cases]
            else:
                results = replay_intents(candidates=pools, rule=rule,
                    secondary_layer=row.get('layer_b'), repair_enabled=switches[0],
                    fallback_enabled=switches[1])
            elapsed = time.monotonic() - tick
            for value in results:
                case = value.pop('case')
                before = value.pop('before_repair')
                data = case.to_dict() if case else None
                key = None
                if data:
                    key = row['rule_id'] + ':' + hashlib.sha256(
                        json.dumps(geometry(data), sort_keys=True).encode()).hexdigest()[:16]
                    unique.setdefault(key, dict(key=key, row=row, pattern=data))
                record = dict(group=group, rule_id=row['rule_id'], line_no=row['line_no'],
                    case=data, before_repair=before.to_dict() if before else None,
                    artifact_key=key, response_indices=indices,
                    evaluation_seconds_per_task=elapsed, **value)
                all_results.append(record)
                if group == 'hybrid':
                    old = saved_case(directory, case.case_id)
                    assert geometry(data) == geometry(old), row['rule_id']
    assert len(all_results) == 105
    save(out / 'cases.json', all_results)
    save(out / 'unique_patterns.json', list(unique.values()))
    save(out / 'EVALUATION.json', dict(passed=True, tasks=7, slots_per_group=21,
        actual_recorded_calls=49, response_returns=sum(x['status']=='returned' for x in parsed),
        errors=sum(x['status']=='error' for x in parsed), new_model_calls=0,
        elapsed_seconds=time.monotonic()-started, selection='production select_best_llm_case',
        templates_delta_nm=20, candidate_pool_frozen=True, hybrid_equals_old_smoke=True,
        scope='available intents evaluated independently; no adaptive feedback/extra iterations'))
    print('fixed candidate evaluation passed; unique patterns:', len(unique))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--evidence', type=Path, required=True)
    p.add_argument('--out-dir', type=Path, required=True)
    args = p.parse_args()
    args.out_dir.mkdir(exist_ok=False)
    evaluate(args.out_dir, args.evidence)


if __name__ == '__main__':
    main()
