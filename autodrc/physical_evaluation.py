"""独立物理评测契约：自身目标、必要输入、正确分支与其他命中分开。"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class PhysicalVerdict:
    passed: bool
    geometry_valid: bool
    inputs_ok: bool
    target_ok: bool
    branch_ok: bool
    illegal_rejected: bool
    other_hits: dict[str,int]
    globally_clean: bool


def evaluate_observation(*,intent: str,geometry_valid: bool,category_hits: dict[str,int],
        target_category: str,input_counts: dict[str,int]|None,minimums: dict[str,int]|None,
        selected_predicate_count: int|None=None) -> PhysicalVerdict:
    if intent not in {'GOOD','BAD','ILLEGAL'}:raise ValueError('Unknown intent')
    other={k:v for k,v in category_hits.items() if k!=target_category and v}
    if intent=='ILLEGAL':
        return PhysicalVerdict(not geometry_valid,geometry_valid,False,False,False,not geometry_valid,other,False)
    inputs=bool(input_counts) and minimums is not None and all(
        type(v) is int and v>=minimums[k] for k,v in input_counts.items()) and set(input_counts)==set(minimums)
    hit=category_hits.get(target_category,0)
    target=(hit==0 if intent=='GOOD' else hit>0)
    branch=selected_predicate_count==0 if intent=='GOOD' and selected_predicate_count is not None else (
        selected_predicate_count>0 if selected_predicate_count is not None else True)
    return PhysicalVerdict(bool(geometry_valid and inputs and target and branch),geometry_valid,inputs,target,
                           branch,False,other,geometry_valid and not any(category_hits.values()))
