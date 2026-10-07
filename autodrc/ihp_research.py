"""IHP research helpers with explicit limits; these do not train or run DRC."""
from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path

from autodrc.casegen import generate_min_density_cases, generate_density_window_cases, generate_poly_endcap_cases, generate_via_enclosure_cases
from autodrc.discriminator import DiscriminatorWeights, score_case
from autodrc.generalization import check_case_semantics
from autodrc.specs import RuleTask
from autodrc.training_recipes import default_recipes, to_command


def evaluate_ihp_synthetic_tasks(out_path: Path, delta_nm: int = 20) -> dict:
    # Same four families as the legacy SKY geometry benchmark. Pin/layer
    # remapping is only for the analytic checker; exported geometry stays IHP.
    definitions = [
        ('metal1_min_density','min_density',3000,generate_min_density_cases(layer='metal1',min_density_bps=3000,delta_bps=delta_nm*10),{}),
        ('metal1_density_window','density_window',4000,generate_density_window_cases(layer='metal1',min_density_bps=4000,delta_bps=delta_nm*10),{}),
        ('gatpoly_endcap','poly_endcap',150,
         [replace(c,polygons=tuple(replace(p,layer={'diff':'activ','poly':'gatpoly'}[p.layer]) for p in c.polygons))
          for c in generate_poly_endcap_cases(endcap_nm=150,delta_nm=delta_nm)],{'activ':'diff','gatpoly':'poly'}),
        ('metal1_via1_enclosure','via_enclosure',60,
         generate_via_enclosure_cases(metal_layer='metal1',via_layer='via1',enclosure_nm=60,delta_nm=delta_nm,tech_name='ihp'),{'via1':'via'}),
    ]
    rows=[]
    for name,kind,threshold,cases,aliases in definitions:
        task=RuleTask(name,kind,'metal1',threshold,'Synthetic geometry task; not an official IHP output',False)
        checks=[]
        for case in cases:
            analytic_case=replace(case,polygons=tuple(replace(p,layer=aliases.get(p.layer,p.layer)) for p in case.polygons))
            checks.append(dict(intent=case.intent,semantic_match=check_case_semantics(analytic_case,task),case=case.to_dict()))
        rows.append(dict(task=name,rule_type=kind,threshold=threshold,
            threshold_unit='basis_points' if 'density' in kind else 'nm',checks=checks,
            semantic_pass_rate=sum(x['semantic_match'] for x in checks)/len(checks)))
    result=dict(tech_name='ihp_sg13g2',scope='synthetic geometry only; no official unknown-task DRC claim',
        unknown_task_drc_verified=False,semantic_results=rows,
        semantic_avg_pass_rate=sum(r['semantic_pass_rate'] for r in rows)/len(rows))
    out_path.parent.mkdir(parents=True,exist_ok=True)
    out_path.write_text(json.dumps(result,indent=2))
    return result


def rank_ihp_corners(corners: list[dict], out_path: Path) -> dict:
    profiles=[DiscriminatorWeights(target_hit=1.5,non_target_penalty=.2),
              DiscriminatorWeights(target_hit=2.,non_target_penalty=.3),
              DiscriminatorWeights(target_hit=3.,non_target_penalty=.4)]
    scans=[]
    for corner in corners:
        row=corner['result']['rows'][0]
        summary=json.loads((Path(row['run_dir'])/'summary.json').read_text())
        case=next(c for c in summary['iterations'][-1]['cases'] if c['intent']=='BAD')
        for index,weights in enumerate(profiles,1):
            scored=score_case(target_hits=case['category_hits'].get('NW.a',0),total_hits=case['drc_items_total'],
                geometry_valid=case['geometry_valid'],delta_nm=corner['delta_nm'],weights=weights)
            scans.append(dict(rule_id='NW.a',delta_nm=corner['delta_nm'],profile=f'w{index:02d}',
                weights=asdict(weights),score=scored.score,score_detail=asdict(scored),source_summary=str(Path(row['run_dir'])/'summary.json')))
    result=dict(tech_name='ihp_sg13g2',scans=scans,best=max(scans,key=lambda r:r['score']) if scans else None,
        scope='weights rescore the same real IHP DRC inputs without redundant engine calls')
    out_path.parent.mkdir(parents=True,exist_ok=True);out_path.write_text(json.dumps(result,indent=2))
    return result


def export_ihp_recipe(out_path: Path, instruction_path: Path, model: str) -> dict:
    recipe=replace(default_recipes()[0],name='lora_ihp_instruction',base_model=model,
        notes='IHP corpus with explicit output identities; recipe export only, training not executed.')
    payload=[dict(tech_name='ihp_sg13g2',recipe=asdict(recipe),
        command=to_command(recipe,str(instruction_path),str(out_path.parent/'training')),training_started=False)]
    out_path.parent.mkdir(parents=True,exist_ok=True);out_path.write_text(json.dumps(payload,indent=2))
    return dict(recipes=1,out_path=str(out_path),training_started=False)
