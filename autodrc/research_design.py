"""非训练研究设计：语义深度、固定候选数与反馈策略显式分开。"""
from __future__ import annotations
from dataclasses import asdict,dataclass
import json
from autodrc.physical_evaluation import evaluate_observation


SEMANTIC_PROFILES=('description','expression','context','full')


def semantic_text(text: str,profile: str) -> str:
    if profile not in SEMANTIC_PROFILES:raise ValueError('Unknown semantic profile')
    if profile=='full':return text
    allowed={'Rule ID','Description'}
    if profile in {'expression','context'}:allowed.add('Runset expression')
    if profile=='context':allowed.add('Runset context')
    return '\n'.join(line for line in text.splitlines() if line.split(':',1)[0] in allowed)


@dataclass(frozen=True)
class CandidateSchedule:
    initial: int=1
    growth: int=1
    maximum: int=4
    feedback_boost: bool=True

    def next_count(self,current: int,*,passed: bool) -> int:
        if self.initial<1 or self.growth<1 or self.maximum<self.initial:raise ValueError('Invalid candidate schedule')
        if not self.feedback_boost or passed:return current
        return min(self.maximum,current+self.growth)


def replay_candidate_policy(*,rounds: list[list[dict]],schedule: CandidateSchedule,
                            select: callable) -> dict:
    """重放预登记真实候选；不声称这是实时模型再采样的因果实验。"""
    current=schedule.initial;used=0;history=[];success=False
    for number,pool in enumerate(rounds,1):
        if len(pool)<current:raise ValueError('Missing registered candidates; keep failure rather than reduce denominator')
        selected=select(pool[:current]);used+=current
        success=bool(selected and selected.get('passed',False))
        next_count=schedule.next_count(current,passed=success)
        history.append(dict(round=number,requested=current,selected=selected,next_count=next_count,passed=success))
        if success:break
        current=next_count
    return dict(passed=success,candidate_calls_charged=used,rounds_run=len(history),history=history,
                schedule=asdict(schedule),scope='paired fixed-pool feedback replay; not independent adaptive inference')
