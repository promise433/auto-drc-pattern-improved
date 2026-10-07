"""真实在线研究循环：失败反馈、候选增长和显式预算，不做模型训练。"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import json
from typing import Callable
from autodrc.research_design import CandidateSchedule


def run_adaptive_research(*,generate: Callable,evaluate: Callable,select: Callable,
        schedule: CandidateSchedule,max_rounds: int,call_limit: int,out_path: Path,
        include_feedback: bool=False) -> dict:
    if max_rounds<1 or call_limit<1:raise ValueError('Positive explicit budgets required')
    if out_path.exists():raise FileExistsError('Use a new explicit output path')
    count=schedule.initial;calls=0;rounds=[];feedback=None;finished=False
    def save():
        result=dict(passed=finished,actual_calls=calls,rounds=rounds,schedule=asdict(schedule),
            max_rounds=max_rounds,call_limit=call_limit,include_feedback=include_feedback,
            scope='actual adaptive calls; evaluator evidence separate; no forced template repair')
        out_path.parent.mkdir(parents=True,exist_ok=True);out_path.write_text(json.dumps(result,indent=2)+'\n')
        return result
    for number in range(1,max_rounds+1):
        row=dict(round=number,requested=count,candidates=[],feedback_used=feedback if include_feedback else None)
        rounds.append(row);save()
        for index in range(count):
            if calls>=call_limit:
                row['stop_reason']='call_budget_exhausted';return save()
            calls+=1
            candidate=generate(round=number,candidate=index+1,feedback=feedback if include_feedback else None)
            observation=evaluate(candidate)
            row['candidates'].append(dict(candidate=candidate,observation=observation));save()
        selected=select(row['candidates'])
        row['selected']=selected
        finished=bool(selected and selected['observation'].get('passed',False))
        row['passed']=finished
        if finished:return save()
        feedback=(dict(previous_round=number,observations=[x['observation'] for x in row['candidates']])
                  if include_feedback else None)
        count=schedule.next_count(count,passed=False);row['next_requested']=count;save()
    return save()
