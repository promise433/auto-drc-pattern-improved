"""显式受控推理：结构提示、可选前缀，以及有限候选空间的在线解码。

候选空间由调用者提供；它不是自由模型成功率，也不声称穷尽任意规则。
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable
from autodrc.llm_generator import LLMResponseError, _load_model_and_tokenizer, parse_model_response
from autodrc.tech import load_known_layers_for_tech, normalize_tech_name


def structured_prompt(rule_text: str, intent: str, expected_layer: str, tech_name: str) -> str:
    if intent not in {'GOOD','BAD','ILLEGAL'}:raise ValueError('Unknown intent')
    tech=normalize_tech_name(tech_name)
    import re
    from autodrc.casegen import _normalize_layer_name
    layers={expected_layer}
    for token in re.findall(r'[A-Za-z_][A-Za-z_0-9]*',rule_text):
        layer=_normalize_layer_name(token,tech_name=tech)
        if layer and layer!='text_0':layers.add(layer)
    layers=sorted(layers)
    return ('Generate one layout as JSON. Output no prose and no Markdown. '
        'LPL is an ARRAY of POLYGONS, not text labels. Each polygon has exactly two fields: '
        '"layer" (one of the physical layers below) and "points" (an array of [x,y] integer pairs). '
        'Coordinates are integer NANOMETRES: 1 micrometre = 1000 nanometres. '
        'GOOD and BAD polygons must be closed and have nonzero area: repeat the first point as the last point. '
        'GOOD must satisfy the target and BAD must violate it, with all required input layers present. '
        'ILLEGAL must have invalid geometry, such as an unclosed polygon. '
        'The top-level object has only "intent" and "lpl", optionally "labels". Do NOT output "technology", "rule_text" or "physical_layers". '
        'Output structure: {"intent":"'+intent+'","lpl":[{"layer":"PHYSICAL_LAYER","points":[[X0,Y0],[X1,Y0],[X1,Y1],[X0,Y1],[X0,Y0]]}]}. '
        'Replace X0, X1, Y0, Y1 with integer coordinates, and replace PHYSICAL_LAYER with a physical layer. '
        'For device pin labels only, add a separate top-level "labels" array; '
        'never put "text" or "position" inside "lpl". '
        'Use "labels" only when the rule explicitly requires device labels.\n'+
        json.dumps(dict(technology=tech,intent=intent,primary_layer=expected_layer,
                        physical_layers=layers,rule_text=rule_text),ensure_ascii=False))


@dataclass(frozen=True)
class GuidedCandidate:
    candidate_id: str
    payload: dict
    score: float = 0.0
    provenance: str = 'caller_provided'


class PrefixDiscriminator:
    """逐token屏蔽池外路径，并在分叉时叠加候选判别分数。"""
    def __init__(self, token_sequences: list[list[int]], scores: list[float], *,
                 prompt_length: int, eos_token_id: int, strength: float = 0.0):
        if not token_sequences or len(token_sequences)!=len(scores):raise ValueError('Empty or mismatched candidate pool')
        if strength<0:raise ValueError('strength must be nonnegative')
        self.prompt_length=prompt_length;self.eos_token_id=eos_token_id;self.strength=strength
        self.transitions={};self.events=[]
        for sequence,score in zip(token_sequences,scores):
            if not sequence:raise ValueError('Empty candidate token sequence')
            for i,token in enumerate(sequence+[eos_token_id]):
                prefix=tuple(sequence[:i]);branches=self.transitions.setdefault(prefix,{})
                branches[token]=max(branches.get(token,float('-inf')),float(score))

    def allowed(self,prefix):
        if tuple(prefix) not in self.transitions:raise ValueError('Generated prefix left the registered pool')
        return self.transitions[tuple(prefix)]

    def __call__(self,input_ids,scores):
        import torch
        result=torch.full_like(scores,float('-inf'))
        for batch,row in enumerate(input_ids):
            prefix=row[self.prompt_length:].tolist();allowed=self.allowed(prefix)
            original_top=int(scores[batch].argmax().item())
            for token,score in allowed.items():result[batch,token]=scores[batch,token]+self.strength*score
            if len(allowed)>1 or original_top not in allowed:
                self.events.append(dict(step=len(prefix),branches=len(allowed),
                    original_top_token=original_top,original_top_blocked=original_top not in allowed,
                    allowed_tokens=list(allowed),guidance_scores=list(allowed.values())))
        return result


def strict_final_payload(raw: str, *, reasoning: bool = False) -> str:
    if not reasoning or not raw.lstrip().startswith('<think>'):
        return raw
    if raw.count('</think>') != 1:
        raise LLMResponseError('Incomplete or ambiguous reasoning delimiter')
    return raw.split('</think>', 1)[1].strip()


def generate_controlled_case(*,model_name: str,rule_text: str,intent: str,expected_layer: str,
        tech_name: str,debug_dir: Path,max_new_tokens: int=768,temperature: float=.3,top_p: float=.85,
        prefill: bool=False,candidates: list[GuidedCandidate]|None=None,guidance_strength: float=0.0,
        allow_non_manhattan: bool=False, reasoning: bool=False):
    import torch
    from transformers import LogitsProcessorList
    tokenizer,model=_load_model_and_tokenizer(model_name,False,False)
    if reasoning and (prefill or candidates):raise ValueError('Reasoning must use free generation without a prefilled layout or candidate pool')
    prompt=structured_prompt(rule_text,intent,expected_layer,tech_name)
    if getattr(tokenizer,'chat_template',None):
        prompt=tokenizer.apply_chat_template([dict(role='user',content=prompt)],tokenize=False,add_generation_prompt=True,
            **({'enable_thinking':reasoning} if getattr(model.config,'model_type',None)=='qwen3' else {}))
    prefix=json.dumps(dict(intent=intent),separators=(',',':'))[:-1]+',"lpl":[' if prefill else ''
    if candidates and prefill:raise ValueError('Pool guidance and free prefill must be evaluated separately')
    actual_prompt=prompt+prefix
    inputs=tokenizer(actual_prompt,return_tensors='pt',add_special_tokens=False)
    if torch.cuda.is_available():inputs={k:v.to(model.device) for k,v in inputs.items()}
    prompt_length=inputs['input_ids'].shape[-1];processor=None;kwargs={}
    if candidates:
        for candidate in candidates:
            if candidate.payload.get('intent')!=intent:raise ValueError('Pool intent mismatch')
        sequences=[tokenizer.encode(json.dumps(c.payload,separators=(',',':')),add_special_tokens=False) for c in candidates]
        if max(map(len,sequences))+1>max_new_tokens:raise ValueError('Registered pool exceeds generation token budget')
        processor=PrefixDiscriminator(sequences,[c.score for c in candidates],prompt_length=prompt_length,
            eos_token_id=tokenizer.eos_token_id,strength=guidance_strength)
        kwargs['logits_processor']=LogitsProcessorList([processor])
    debug_dir.mkdir(parents=True,exist_ok=True)
    (debug_dir/('llm_prompt_'+intent.lower()+'.txt')).write_text(actual_prompt)
    output=model.generate(**inputs,max_new_tokens=max_new_tokens,temperature=temperature,top_p=top_p,
                          do_sample=temperature>0,**kwargs)
    suffix=tokenizer.decode(output[0][prompt_length:],skip_special_tokens=True)
    raw=prefix+suffix
    (debug_dir/('llm_raw_'+intent.lower()+'.txt')).write_text(raw)
    (debug_dir/'actual_generation_suffix.txt').write_text(suffix)
    metadata=dict(prompt_profile='controlled',prefill=prefill,scaffold_prefix=prefix,
        input_tokens=prompt_length,new_tokens=len(output[0])-prompt_length,max_new_tokens=max_new_tokens,
        temperature=temperature,top_p=top_p,online_pool_guidance=bool(candidates),guidance_strength=guidance_strength,
        model_selected_from_caller_pool=bool(candidates),raw_coordinates_are_free_model_outputs=not bool(candidates),
        reasoning=reasoning,strict_parse_scope='final payload after a complete think delimiter' if reasoning else 'complete raw response')
    if processor:
        metadata['guidance_events']=processor.events
        metadata['candidate_pool']=[dict(candidate_id=c.candidate_id,score=c.score,provenance=c.provenance,
            payload_sha256=hashlib.sha256(json.dumps(c.payload,sort_keys=True).encode()).hexdigest()) for c in candidates]
    (debug_dir/'generation_metadata.json').write_text(json.dumps(metadata,indent=2))
    if candidates:
        payload=json.loads(raw)
        if not any(payload==c.payload for c in candidates):raise LLMResponseError('Decoded result differs from registered candidate pool')
    final=strict_final_payload(raw,reasoning=reasoning)
    if reasoning:(debug_dir/'strict_final_payload.txt').write_text(final)
    case=parse_model_response(final,intent=intent,expected_layer=expected_layer,tech_name=tech_name,strict=True)
    if allow_non_manhattan:
        from dataclasses import replace
        case=replace(case,allow_non_manhattan=True)
    return case


def main():
    import argparse
    parser=argparse.ArgumentParser(description='显式结构提示和在线候选路径引导；无模型训练')
    parser.add_argument('--model',required=True)
    parser.add_argument('--rule-text-file',type=Path,required=True)
    parser.add_argument('--intent',choices=['GOOD','BAD','ILLEGAL'],required=True)
    parser.add_argument('--expected-layer',required=True)
    parser.add_argument('--tech-name',required=True)
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--candidate-pool',type=Path)
    parser.add_argument('--guidance-strength',type=float,default=0.)
    parser.add_argument('--prefill',action='store_true')
    parser.add_argument('--allow-non-manhattan',action='store_true')
    parser.add_argument('--max-new-tokens',type=int,default=768)
    parser.add_argument('--reasoning',action='store_true')
    args=parser.parse_args()
    if args.out_dir.exists():raise FileExistsError('Use a new explicit output directory')
    candidates=[GuidedCandidate(**row) for row in json.loads(args.candidate_pool.read_text())] if args.candidate_pool else None
    case=generate_controlled_case(model_name=args.model,rule_text=args.rule_text_file.read_text(),intent=args.intent,
        expected_layer=args.expected_layer,tech_name=args.tech_name,debug_dir=args.out_dir,
        max_new_tokens=args.max_new_tokens,prefill=args.prefill,candidates=candidates,
        guidance_strength=args.guidance_strength,allow_non_manhattan=args.allow_non_manhattan,reasoning=args.reasoning)
    (args.out_dir/'case.json').write_text(json.dumps(case.to_case_dict(),indent=2))
    print(json.dumps(case.to_case_dict(),indent=2))


if __name__=='__main__':main()
