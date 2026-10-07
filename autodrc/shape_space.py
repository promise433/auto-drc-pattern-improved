"""几何候选多样性与受控变换；是否保留目标由独立物理核对决定。"""
from __future__ import annotations
from dataclasses import replace
import hashlib
import json
from autodrc.casegen import PatternCase
from autodrc.lpl import Polygon, TextLabel


def transform_case(case: PatternCase, *,quarter_turns: int=0,reflect: bool=False,
                   translate_nm: tuple[int,int]=(0,0),suffix: str='variant') -> PatternCase:
    if type(quarter_turns) is not int or not 0<=quarter_turns<4:raise ValueError('quarter_turns must be 0..3')
    if len(translate_nm)!=2 or any(type(v) is not int for v in translate_nm):raise ValueError('translation must be integer nanometres')
    def point(p):
        x,y=p
        if reflect:x=-x
        for _ in range(quarter_turns):x,y=-y,x
        return x+translate_nm[0],y+translate_nm[1]
    return replace(case,case_id=case.case_id+'_'+suffix,description=case.description+' [transform:'+suffix+']',
        polygons=tuple(Polygon(p.layer,tuple(point(x) for x in p.points)) for p in case.polygons),
        labels=tuple(TextLabel(t.layer,t.text,point(t.position)) for t in case.labels),rigorous_geometry=True)


def case_from_payload(value: dict, *,rigorous: bool=True,allow_non_manhattan: bool=False) -> PatternCase:
    return PatternCase(value.get('case_id','research'),value['intent'],value.get('description','external research candidate'),
        tuple(Polygon(p['layer'],tuple(tuple(x) for x in p['points'])) for p in value['lpl']),
        allow_non_manhattan=allow_non_manhattan,
        labels=tuple(TextLabel(t['layer'],t['text'],tuple(t['position'])) for t in value.get('labels',[])),rigorous_geometry=rigorous)


def payload(case: PatternCase) -> dict:
    value=case.to_dict();result=dict(intent=case.intent,lpl=value['lpl'])
    if case.labels:result['labels']=value['labels']
    return result


def diversity(cases: list[PatternCase]) -> dict:
    def digest(value):
        polygons=[]
        for poly in value['lpl']:
            points=tuple(tuple(p) for p in poly['points'])
            closed=len(points)>3 and points[0]==points[-1]
            if closed:
                # 闭合环起点及遍历方向不构成新的几何。
                ring=points[:-1];reverse=tuple(reversed(ring))
                points=min(sequence[i:]+sequence[:i] for sequence in (ring,reverse) for i in range(len(ring)))
            polygons.append((poly['layer'],closed,points))
        labels=sorted((t['layer'],t['text'],tuple(t['position'])) for t in value.get('labels',[]))
        return hashlib.sha256(json.dumps([sorted(polygons),labels],sort_keys=True).encode()).hexdigest()
    exact=set();translated=set();features=[]
    for case in cases:
        value=payload(case);exact.add(digest(value))
        if case.polygons:
            points=[p for poly in case.polygons for p in poly.points];x0=min(p[0] for p in points);y0=min(p[1] for p in points)
            normalized=payload(transform_case(case,translate_nm=(-x0,-y0)))
            translated.add(digest(normalized))
            features.append(dict(polygons=len(case.polygons),layers=len({p.layer for p in case.polygons}),
                vertices=sum(len(p.points)-1 for p in case.polygons),labels=len(case.labels),
                non_manhattan=any(a[0]!=b[0] and a[1]!=b[1] for p in case.polygons for a,b in zip(p.points,p.points[1:]))))
        else:translated.add(digest(value))
    return dict(cases=len(cases),exact_unique=len(exact),translation_normalized_unique=len(translated),features=features,
                scope='geometric diversity only; target/branch preservation requires physical evidence')
