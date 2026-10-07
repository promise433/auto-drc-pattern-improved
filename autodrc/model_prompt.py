"""可选的简洁提示；不提供模板坐标，也不代替模型生成。"""
from __future__ import annotations
import json
import re

SYSTEM_INSTRUCTION = (
    'You generate layout polygon lists. Return one JSON object only. '
    'Use exactly the requested intent and physical layer names. '
    'Do not echo the task, schema or instructions. Coordinates are integer nanometres. '
    'A polygon has layer and points; points are pairs [x,y], at least four vertices '
    'including the repeated first vertex. GOOD and BAD polygons must be closed, '
    'nonzero-area and Manhattan. GOOD obeys the target; BAD violates it with '
    'all required input layers present. ILLEGAL must contain an invalid polygon. '
    'Output keys: intent, lpl, optionally labels. Each label uses '
    'layer="text_0", text, position=[x,y]. Never output a schema or code.'
)


def compact_task(rule_text: str, intent: str, expected_layer: str | None,
                 tech_name: str, allowed_layers: set[str]) -> str:
    contract = None
    for line in rule_text.splitlines():
        if line.startswith('IHP contract: '):
            contract = json.loads(line.split(': ', 1)[1])
    fields = {}
    for name in ('Rule ID', 'Description', 'Runset expression'):
        match = re.search(r'^' + re.escape(name) + r':\s*(.+)$', rule_text, re.M)
        if match:
            fields[name] = match[1]
    task = dict(technology=tech_name, intent=intent, main_layer=expected_layer,
                rule=fields or rule_text, allowed_layers=sorted(allowed_layers))
    if contract:
        task['executed_requirements'] = {k: contract[k] for k in (
            'expression', 'operation', 'operands', 'operand_layers', 'input_clauses',
            'threshold_nm', 'array_count', 'seed_nm', 'device_text',
            'executed_lower_nm', 'executed_upper_nm', 'selected_branch') if k in contract}
    return SYSTEM_INSTRUCTION + '\nTask: ' + json.dumps(task, ensure_ascii=False, separators=(',', ':'))
