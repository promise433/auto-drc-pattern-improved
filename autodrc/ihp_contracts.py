"""IHP predicate inputs and sufficient masks, derived from the actual runset.

Certificates describe a region wholly present/absent under boolean layer
operations. Unknown geometric filters never become a positive certificate.
They can still be empty when their incoming region is provably empty.
"""
from __future__ import annotations

import json
import re
from typing import Any

# A clause is a tuple of required present and required absent physical layers.
Clause = tuple[frozenset[str], frozenset[str]]
Certificates = tuple[list[Clause], list[Clause]]


def split_arguments(text: str) -> list[str]:
    result: list[str] = []
    start = depth = 0
    quote = None
    escaped = False
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            result.append(text[start:index].strip())
            start = index + 1
    result.append(text[start:].strip())
    return result


def last_call(text: str) -> tuple[str, str, str] | None:
    text = text.strip()
    if not text.endswith(")"):
        match = re.fullmatch(r"(.*)\.([A-Za-z_]\w*)", text, re.S)
        return (match[1], match[2], "") if match else None
    masked = re.sub(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*' ''',
                    lambda m: " " * len(m[0]), text, flags=re.X)
    depth = 0
    for index in range(len(text) - 1, -1, -1):
        char = masked[index]
        if char == ")":
            depth += 1
        elif char == "(":
            depth -= 1
            if depth == 0:
                match = re.fullmatch(r"(.*)\.([A-Za-z_]\w*)", text[:index], re.S)
                return (match[1], match[2], text[index + 1:-1]) if match else None
    return None


def _simplify(clauses: list[Clause]) -> list[Clause]:
    result = []
    for positive, negative in sorted(set(clauses), key=lambda x: (len(x[0])+len(x[1]), sorted(x[0]),sorted(x[1]))):
        if not any(p <= positive and n <= negative for p,n in result):
            result.append((positive, negative))
    return result[:128]


def _merge(left: list[Clause], right: list[Clause]) -> list[Clause]:
    result = []
    for ap, an in left:
        for bp, bn in right:
            positive, negative = ap | bp, an | bn
            if not positive & negative:
                item = (positive, negative)
                if item not in result:
                    result.append(item)
    # Dropping sufficient alternatives is conservative; never invent a clause.
    return _simplify(result)


def _and(a: Certificates, b: Certificates) -> Certificates:
    return _merge(a[0], b[0]), _simplify(a[1] + b[1])


def _or(a: Certificates, b: Certificates) -> Certificates:
    return _simplify(a[0] + b[0]), _merge(a[1], b[1])


def input_certificates(expression: str, assignments: dict[str, str],
                       layers: dict[str, str], active: frozenset[str] = frozenset()) -> Certificates:
    expression = expression.strip()
    low = expression.lower()
    if re.fullmatch(r'source\.labels\("\d+/\d+"\)', expression):
        # LPL templates carry polygons only, never text labels.
        return [], [(frozenset(), frozenset())]
    if re.fullmatch(r"[A-Za-z_]\w*", expression):
        if low in layers:
            layer = layers[low]
            return [(frozenset([layer]), frozenset())], [(frozenset(), frozenset([layer]))]
        if low in assignments and low not in active:
            return input_certificates(assignments[low], assignments, layers, active | {low})
        return [], []
    call = last_call(expression)
    if not call:
        return [], []
    primary, method, arguments = call
    a = input_certificates(primary, assignments, layers, active)
    if method in {"holes", "with_holes"} and primary.strip().lower() in layers:
        # This constructor uses at most two disjoint/nested axis-aligned seeds
        # on a physical input. Their union has no enclosed hole.
        return [], [(frozenset(), frozenset())]
    if method in {"dup", "merge", "merged", "ext_merged"}:
        return a
    values = split_arguments(arguments)
    if method=='ext_rectangles' and not re.search(r'inverted:\s*true',arguments):
        if not arguments or (len(values)>=4 and all(re.fullmatch(r'\[\[\s*["\']==["\']\s*,\s*[\d.]+\.um\s*\]\]',value) for value in values[2:4])):
            # These positive filters are backed by required rectangle sizes in
            # the construction contract below, not a guess at the layer name.
            return a
    if method=='ext_with_area' and re.fullmatch(r'\[\["\>",\s*\(0\.16\*0\.16\)\.um2\]\]',arguments):
        # Official ContBar: the fixed 340x160nm rectangle has area >160².
        return a
    if method == "ext_interacting_with_text" and values:
        labels = input_certificates(values[0], assignments, layers, active)
        return [], a[1] + labels[1]
    if method in {"ext_coincident_edges", "ext_coincident_part", "ext_with_coincident_edges",
                  "ext_touching", "ext_overlapping", "ext_covering"} and values:
        b = input_certificates(values[0], assignments, layers, active)
        if method=='ext_covering' and _primary_layer(primary,assignments,layers)==_primary_layer(values[0],assignments,layers) is not None:
            # The rectangular construction supplies both expressions on the
            # same physical seed; the derived subset is covered by its carrier.
            return _and(a,b)
        # A matching-result layer needs both operands; with no partner there is
        # no match. This proves emptiness only, never successful geometry.
        return [], a[1] + b[1]
    if method in {"ext_and", "and", "ext_or", "or", "ext_not", "not", "ext_outside",
                  "outside", "inside", "not_outside", "ext_interacting", "interacting"}:
        operands = [input_certificates(value, assignments, layers, active)
                    for value in values if value and not re.match(r"\w+:", value)]
        if not operands:
            return [], a[1]
        b = operands[0]
        for operand in operands[1:]:
            b = _or(b, operand)
        if method in {"ext_or", "or"}:
            return _or(a, b)
        if method in {"ext_not", "not", "ext_outside", "outside"} or re.search(r"inverted:\s*true", arguments):
            return _and(a, (b[1], b[0]))
        return _and(a, b)
    # Width/area/device filters and holes need their own geometric construction.
    # A known-empty receiver is sufficient to prove their result empty.
    return [], a[1]


def _primary_layer(expression: str, assignments: dict[str, str],
                   layers: dict[str, str], active: frozenset[str] = frozenset()) -> str | None:
    key = expression.strip().lower()
    if key in layers:
        return layers[key]
    if key in assignments and key not in active:
        return _primary_layer(assignments[key], assignments, layers, active | {key})
    call = last_call(expression)
    if call:
        return _primary_layer(call[0], assignments, layers, active)
    return None


def _rectangle_size(expression: str, assignments: dict[str,str], active: frozenset[str]=frozenset()) -> tuple[int,int] | None:
    key=expression.strip().lower()
    if key in assignments and key not in active:
        return _rectangle_size(assignments[key],assignments,active | {key})
    call=last_call(expression)
    if not call:
        return None
    if call[1]=='ext_rectangles':
        values=split_arguments(call[2])
        if len(values)>=4:
            sizes=[re.fullmatch(r'\[\[\s*["\']==["\']\s*,\s*([\d.]+)\.um\s*\]\]',value) for value in values[2:4]]
            if all(sizes):
                return tuple(round(float(match[1])*1000) for match in sizes)
    if call[1]=='ext_with_area' and re.fullmatch(r'\[\["\>",\s*\(0\.16\*0\.16\)\.um2\]\]',call[2]):
        return 340,160
    return _rectangle_size(call[0],assignments,active)


def _expand_receiver(expression: str, assignments: dict[str,str], active=frozenset()) -> str:
    key=expression.strip().lower()
    if key in assignments and key not in active:
        if re.fullmatch(r'source\.polygons\("\d+/\d+"\)',assignments[key].strip()):
            return expression
        return _expand_receiver(assignments[key],assignments,active | {key})
    call=last_call(expression)
    if call:
        if call[1]=='dup':
            return _expand_receiver(call[0],assignments,active)
        return _expand_receiver(call[0],assignments,active)+'.'+call[1]+'('+call[2]+')'
    return expression


def compile_contract(expression: str, upstream: tuple[str, ...],
                     layer_map: set[str], rule_type: str | None,
                     _visited: frozenset[str] = frozenset()) -> dict[str, Any] | None:
    original = expression
    if expression in _visited:
        return None
    _visited = _visited | {expression}
    assignments = {}
    for value in upstream:
        match = re.match(r"L\d+:([A-Za-z_]\w*) = (.*)", value, re.S)
        if match:
            assignments[match[1].lower()] = match[2]
    channel = next((re.fullmatch(r'Activ\.ext_not\((nmosHV|pmosHV)\)\.ext_interacting\(\1\)\.ext_space\(([\d.]+)\.um, metric: projection, consider_touch_points: false, polygon_output: true\)', rhs)
                    for rhs in assignments.values() if 'ext_not(nmosHV)' in rhs or 'ext_not(pmosHV)' in rhs), None)
    if channel is not None and rule_type == 'min_length':
        device=channel[1]
        return dict(expression=original,operation='channel_length',rule_type='min_length',
                    threshold_nm=round(float(channel[2])*1000),device=device,
                    operands=[f'Activ.ext_not({device}).ext_interacting({device})',device],
                    operand_layers=['activ','gatpoly'],input_clauses=[],options=[])
    # Only official direct input declarations are physical leaves. Derived
    # names such as NAct must never be resolved by their spelling alone.
    layers = {}
    for name, rhs in assignments.items():
        if re.fullmatch(r'source\.polygons\("\d+/\d+"\)', rhs.strip()) and name in layer_map:
            layers[name] = name
    seen = set()
    while True:
        call = last_call(expression)
        if call and call[1] == "dup":
            expression = call[0]
        key = expression.strip().lower()
        if re.fullmatch(r"\w+", key) and key in assignments and key not in seen:
            seen.add(key)
            expression = assignments[key]
            continue
        if call and call[1] == "dup":
            continue
        break
    call = last_call(expression)
    if 'subst_tie_hole_w_npn' in assignments and 'ext_interacting_with_text(TEXT_0, "npn*")' in assignments['subst_tie_hole_w_npn']:
        mode=None
        primary=None
        threshold=0
        if expression=='subst_tie_hole_w_npn.ext_interacting(TRANS, inverted: true)':
            mode='recognition'
            operands=['subst_tie_hole_w_npn','TRANS']
        elif call and call[1]=='ext_separation' and split_arguments(call[2])[0]=='subst_tie_trans':
            mode='separation'
            primary=call[0]
            value=re.fullmatch(r'([\d.]+)\.um',split_arguments(call[2])[1])
            if value:
                threshold=round(float(value[1])*1000)
            else:
                mode=None
            operands=[primary,'subst_tie_trans']
        elif expression.startswith('npnPActRing.ext_enclosed(subst_tie_npn,'):
            mode='enclosure'
            threshold=200
            operands=['npnPActRing','subst_tie_npn']
        if mode:
            physical=_primary_layer(primary,assignments,layers) if primary else 'psd'
            if physical:
                return dict(expression=original,operation='npn_ring',rule_type='min_spacing' if mode=='separation' else 'min_enclosure',
                    threshold_nm=threshold,operand_layers=[physical],operands=operands,input_clauses=[],options=[],mode=mode)
    seal_layer=re.fullmatch(r'ring_passiv_(\w+)_edgA1_in_Seal_f_\w+_sep(?:\.dup)?',original)
    if 'ring_passiv' in assignments and assignments['ring_passiv']=='selring_pass.ext_outside(sealring)':
        seal_width=original=='ring_passiv.ext_not(ring_passiv.sized(-4.2.um/2.0+1.dbu, acute_limit).sized(4.2.um/2.0-1.dbu, acute_limit))'
        if seal_width or seal_layer:
            partner=seal_layer[1].lower() if seal_layer else None
            if partner is None or partner in layers:
                return dict(expression=original,operation='seal_ring',rule_type='min_width' if seal_width else 'min_spacing',
                    threshold_nm=4198 if seal_width else 1000,operand_layers=['passiv']+([partner] if partner else []),
                    operands=['ring_passiv']+([seal_layer[1]+'_edgA1_in'] if partner else []),input_clauses=[],options=[])
    resistor=re.search(r'(Rppd|Rhigh)_Cont\.ext_separation\(SalBlock_\1, 0\.2\.um\)',original)
    if resistor:
        family=resistor[1]
        return dict(expression=original,operation='resistor_contact',rule_type='min_spacing',threshold_nm=200,
            operand_layers=['cont','salblock'],operands=[family+'_Cont','SalBlock_'+family],input_clauses=[],options=[],family=family)
    if original=='Rhigh_identical_nsd_psd.dup' and assignments.get('psd_not_nsd')=='nSD.ext_not(pSD)' and assignments.get('nsd_not_psd')=='pSD_not_nSD.dup':
        return dict(expression=original,operation='resistor_masks',rule_type='forbidden_overlap',threshold_nm=0,
            operand_layers=['nsd','psd'],operands=['nSD','pSD','Rhigh_recognition'],input_clauses=[],options=[],
            official_difference='Both nominal difference branches use nSD minus pSD')
    latch=None
    if original=='PAct_NWell.ext_not(x).ext_outside(devExclud)' and assignments.get('x')=='all_ntie.ext_enlarge_inside(NWell, 20.0.um, 0.1.um)':
        latch='well_distance'
        latch_operands=['PAct_NWell','all_ntie','NWell']
    elif original=='drcErrA.ext_with_coincident_edges(drcErrA_Edge)' and assignments.get('sizeda')=='size_Cont.dup':
        latch='n_contact_distance'
        latch_operands=['NAct_NWell','Cont','size_Cont']
    elif original=='drcErrA.ext_with_coincident_edges(drcErrA_Edge)' and assignments.get('sizeda')=='Cont.ext_enlarge_inside(Act_connect, 6.um, 0.21.um)':
        latch='p_contact_distance'
        latch_operands=['PWell_Tie_wo_varicap_abut','Cont','sizedA']
    elif original=='drcErrA_Poly.ext_interacting(Cont_not_outside_NAct, inverted: true)' and 'Abut_NWell_Tie_Cont.ext_enlarge_inside' in assignments.get('sizeda',''):
        latch='n_abutted_tie'
        latch_operands=['Abut_NWell_Tie','Abut_NWell_Tie_Cont','Gate']
    elif original=='drcErrA_Poly.ext_interacting(Cont_not_outside_PAct, inverted: true)' and 'Abut_PWell_Tie_Cont.ext_enlarge_inside' in assignments.get('sizeda',''):
        latch='p_abutted_tie'
        latch_operands=['Abut_PWell_Tie','Abut_PWell_Tie_Cont','Act_connect']
    if latch:
        return dict(expression=original,operation='latchup_distance',rule_type='max_length',threshold_nm=20000 if latch=='well_distance' else 6000,
            operand_layers=['activ'],operands=latch_operands,input_clauses=[],options=[],mode=latch)
    implant_mode=None
    if original=='layD.dup' and assignments.get('layc','').startswith('layB.ext_width(0.3.um,') and assignments.get('layd')=='layC.ext_covering(layB)':
        implant_mode='partial_width';implant_operands=['layA','layB']
    elif original=='abuttedNTAP.ext_outside(good_region)' and assignments.get('abuttedntap')=='NAct_NWell.ext_interacting(PAct_NWell)':
        implant_mode='tie_overlap';implant_operands=['NAct_NWell','PAct_NWell','abuttedNTAP']
    if implant_mode:
        return dict(expression=original,operation='abutted_implant',rule_type='min_width',threshold_nm=300,
            operand_layers=['activ','psd'],operands=implant_operands,input_clauses=[],options=[],mode=implant_mode)
    isolated_mode=None
    if original=='Iso_PWell_Act.ext_not(scr1_or_schottky_nbl1).ext_separation(NWell.with_holes, 0.39.um, max_angle: 180)':
        isolated_mode='well_ring';isolated_operands=['Iso_PWell_Act.ext_not(scr1_or_schottky_nbl1)','NWell.with_holes']
    elif original=='x1.ext_and(Activ)' and assignments.get('x1','').startswith('nSDBlock_Iso_PWell_Act.ext_enclosed(tmp.ext_not(tmp.ext_covering(npnMPA)), 0.15.um,'):
        isolated_mode='salblock';isolated_operands=['nSDBlock_Iso_PWell_Act','tmp.ext_not(tmp.ext_covering(npnMPA))','Activ']
    elif original=='schottky_contbar.ext_enclosed(schottky_pwb, 0.25.um)':
        isolated_mode='schottky';isolated_operands=['schottky_contbar','schottky_pwb']
    if isolated_mode:
        return dict(expression=original,operation='isolated_device',rule_type='min_spacing' if isolated_mode=='well_ring' else 'min_enclosure',
            threshold_nm=390 if isolated_mode=='well_ring' else 150 if isolated_mode=='salblock' else 250,
            operand_layers=['activ'],operands=isolated_operands,input_clauses=[],options=[],mode=isolated_mode)
    emitter=re.fullmatch(r'(emit_npn13G2(?:L|V)?)\.ext_with_length\((.*)\)',expression)
    if emitter:
        terms=re.findall(r'\["([<>])",\s*([\d.]+)\.um\]',emitter[2])
        recognition=assignments.get(emitter[1].lower(),'')
        inside=last_call(recognition)
        device=inside[2] if inside and inside[1]=='inside' else ''
        text_match=re.search(r'ext_interacting_with_text\(TEXT_0, "([^"]+)"\)',assignments.get(device.lower(),''))
        if terms and text_match:
            lower=next((round(float(v)*1000)+1000 for op,v in terms if op=='>'),0)
            upper=next((round(float(v)*1000) for op,v in terms if op=='<'),None)
            return dict(expression=original,operation='emitter_length',rule_type='max_length',
                threshold_nm=lower,operand_layers=['emwind'],operands=[emitter[1]],input_clauses=[],options=[],
                device_text=text_match[1],executed_lower_nm=lower,executed_upper_nm=upper,
                official_limitation='empty executed edge-length interval' if upper is not None and lower>=upper else None)
    if call and call[1]=='ext_not':
        partner=_expand_receiver(call[2],assignments)
        matching=last_call(partner)
        if matching and matching[1]=='ext_covering' and matching[0].strip()==call[0].strip():
            candidate_clauses=input_certificates(matching[2],assignments,layers)[0]
            if call[0].lower()=='mim' and any(p==frozenset({'vmim'}) for p,n in candidate_clauses):
                return dict(expression=original,operation='matching_coverage',rule_type='min_enclosure',
                    threshold_nm=0,operand_layers=['mim','vmim'],operands=[call[0],matching[2]],
                    matching_result=call[2],input_clauses=[],options=[])
    if call and call[1]=='ext_and' and call[0].strip().lower() in assignments:
        candidate=last_call(assignments[call[0].strip().lower()])
        if candidate and candidate[1]=='ext_enclosed' and call[2].strip().lower() in layers:
            contract=compile_contract(assignments[call[0].strip().lower()],upstream,layer_map,'min_enclosure',_visited)
            if contract:
                contract['postfilter_expression']=original
                return contract
    if call and call[1]=='ext_rectangles' and re.search(r'inverted:\s*true',call[2]):
        clauses=input_certificates(call[0],assignments,layers)[0]
        if clauses and all({'activ','gatpoly'} <= set(p) for p,n in clauses):
            return dict(expression=original,operation='gate_rectangle',rule_type='angle',threshold_nm=90,
                        operand_layers=['activ','gatpoly'],operands=[call[0]],input_clauses=[],options=[])
    if call and (call[1]=='ext_outside' or (call[1]=='ext_not' and rule_type=='forbidden_overlap')):
        contract=compile_contract(call[0],upstream,layer_map,rule_type,_visited)
        excluded=input_certificates(call[2],assignments,layers)[1]
        if contract and excluded and contract.get('input_clauses'):
            clauses=[(frozenset(x['present']),frozenset(x['absent'])) for x in contract['input_clauses'][0]]
            guarded=_merge(clauses,excluded)
            if guarded:
                contract['input_clauses'][0]=[dict(present=sorted(p),absent=sorted(n)) for p,n in guarded]
                contract['guarded_expression']=original
                return contract
    expanded=_expand_receiver(expression,assignments)
    hole=re.fullmatch(r'\((\w+)\.holes - \1\.with_holes\)\.without_holes\(\)\.ext_not\(\1\)\.ext_with_area\(\[\["<", ([\d.]+)\.um2\]\]\)',expanded)
    if hole and hole[1].lower() in layers:
        return dict(expression=original,operation='hole_area',rule_type='min_area',
                    threshold_nm=round(float(hole[2])*1_000_000),
                    operand_layers=[layers[hole[1].lower()]],operands=[hole[1],hole[1]+'.holes'],
                    input_clauses=[],options=[])
    # A closing followed by an opening identifies the real large-array domain.
    # Keep the officially selected contacts as measured operands, not x1 alone.
    array_next=next((rhs for rhs in assignments.values() if '.sized(-(((5*0.16)+(3*0.18))/2-0.005).um' in rhs),None)
    via_array=next((rhs for rhs in assignments.values() if '.sized(-(((4*0.19+3*0.22)-0.05)*0.5).um' in rhs),None)
    if array_next or via_array:
        selected_name=next((name for name,rhs in assignments.items() if '.inside(' in rhs and
                           ('vialargearray' in rhs.lower() or re.search(r'via[1-4]array',rhs.lower()))),None)
        if selected_name:
            physical=_primary_layer(assignments[selected_name],assignments,layers)
            if physical:
                return dict(expression=original,operation='large_array',rule_type='min_spacing',
                    threshold_nm=200 if array_next else 290,operand_layers=[physical],
                    operands=[assignments[selected_name]],input_clauses=[],options=[],array_count=5 if array_next else 4,
                    seed_nm=160 if array_next else 190,
                    bridge_gap_nm=190 if array_next else 286,bridge_bad_comparison='<=',
                    nominal_threshold_nm=200 if array_next else 290)
    # These official maximum-width checks return the surviving core after
    # erosion. Expanding receiver aliases preserves the actual three-step slit
    # expression and its exclusions, rather than reading the description.
    current=expanded
    sized=[]
    while (sized_call:=last_call(current)) and sized_call[1]=='sized':
        value=split_arguments(sized_call[2])[0]
        m=re.fullmatch(r'(-?[\d.]+)\.um(?:/([\d.]+))?',value)
        if not m:
            break
        sized.append(float(m[1])*1000/(float(m[2]) if m[2] else 1))
        current=sized_call[0]
    if sized and sized[0]>0 and all(value<0 for value in sized[1:]) and abs(sum(sized))<0.001:
        clauses=input_certificates(current,assignments,layers)[0]
        physical=_primary_layer(current,assignments,layers)
        if clauses and physical:
            return dict(expression=original,operation='morphological_width',rule_type='max_width',
                threshold_nm=round(2*sized[0]),operands=[current],operand_layers=[physical],
                input_clauses=[[dict(present=sorted(p),absent=sorted(n)) for p,n in clauses]],options=[])
    if call and call[1]=='drc' and rule_type in {'min_enclosure','via_enclosure'}:
        outer=re.search(r'secondary\(([A-Za-z_]\w*)\)',call[2])
        endcap=re.search(r'enclosed\([A-Za-z_]\w*, projection, whole_edges, one_side_allowed, two_opposite_sides_allowed\) < ([\d.]+)\.um',call[2])
        if outer and endcap:
            operands=[call[0],outer[1]]
            clauses=[input_certificates(value,assignments,layers)[0] for value in operands]
            primary_layers=[_primary_layer(value,assignments,layers) for value in operands]
            if all(clauses) and all(primary_layers):
                return dict(expression=original,operation='endcap',rule_type='min_enclosure',
                    threshold_nm=round(float(endcap[1])*1000),operands=operands,operand_layers=primary_layers,
                    operand_sizes=[_rectangle_size(value,assignments) for value in operands],
                    input_clauses=[[dict(present=sorted(p),absent=sorted(n)) for p,n in alternatives] for alternatives in clauses],options=[])
    branches = []
    if expression.strip().startswith('[') and expression.strip().endswith(']'):
        branches = split_arguments(expression.strip()[1:-1])
    elif call and call[1] in {'ext_or', 'or'}:
        branches = [call[0]] + split_arguments(call[2])
    elif call and call[1]=='ext_with_coincident_edges':
        values=split_arguments(call[2])
        if values and _primary_layer(call[0],assignments,layers)==_primary_layer(values[0],assignments,layers) is not None:
            branches=values[:1]
    else:
        # Ruby's union operator on DRC layers. Do not split operators inside
        # arguments or strings, and never treat subtraction as a union.
        parts = split_arguments(expression.replace(' + ', ', '))
        if len(parts) > 1:
            branches = parts
    for branch in branches:
        contract = compile_contract(branch, upstream, layer_map, rule_type, _visited)
        if contract is not None:
            contract['compound_expression'] = original
            contract['selected_branch'] = branch
            return contract
    if not call:
        return None
    primary, operation, arguments = call
    operations = {"ext_width": "min_width", "ext_space": "min_spacing",
                  "ext_enclosed": "min_enclosure", "ext_separation": "min_spacing",
                  "ext_with_area": "area", "ext_with_length": "length", "ext_not": "coverage",
                  "ext_and":"forbidden_overlap", "inside":"forbidden_overlap"}
    if operation not in operations:
        return None
    if operation == "ext_not" and rule_type not in {"min_enclosure", "via_enclosure"}:
        return None
    values = split_arguments(arguments)
    operands = [primary]
    if operation in {"ext_enclosed", "ext_separation", "ext_not","ext_and","inside"}:
        operands.append(values.pop(0))
    clauses = [input_certificates(value, assignments, layers)[0] for value in operands]
    if not all(clauses):
        return None
    threshold = 0
    nominal_threshold = None
    kind = operations[operation]
    if operation in {"ext_with_area","ext_with_length"}:
        unit='um2' if operation=='ext_with_area' else 'um'
        area_product=re.fullmatch(r'\[\["([<>])",\s*\(([\d.]+)\*([\d.]+)\)\.um2\]\]',values[0]) if unit=='um2' else None
        if area_product:
            values[0]='[["'+area_product[1]+'", '+str(float(area_product[2])*float(area_product[3]))+'.um2]]'
        match = re.fullmatch(r'\[\[\s*["\']([<>])["\']\s*,\s*([\d.]+)\.'+unit+r'\s*\]\]', values[0])
        if not match:
            return None
        threshold = round(float(match[2]) * (1_000_000 if unit=='um2' else 1000))
        kind = ('min_' if match[1]=='<' else 'max_')+('area' if unit=='um2' else 'length')
        if unit=='um' and match[1]=='>':
            # Official ext_with_length adds the Ruby number 1 to a floating
            # micrometre value before calling with_length: this is +1um,
            # not +1 database unit. Keep the nominal and executed boundaries.
            nominal_threshold=threshold
            threshold += 1000
    elif kind not in {"coverage","forbidden_overlap"}:
        match = re.fullmatch(r"([\d.]+)\.um", values[0])
        if not match:
            return None
        threshold = round(float(match[1]) * 1000)
    serial = [[dict(present=sorted(p), absent=sorted(n)) for p, n in alternatives] for alternatives in clauses]
    primary_layers = [_primary_layer(value, assignments, layers) for value in operands]
    if not all(primary_layers):
        return None
    contract=dict(expression=expression, operation=operation, rule_type=kind,
                threshold_nm=threshold, operands=operands, input_clauses=serial,
                operand_layers=primary_layers,
                operand_sizes=[_rectangle_size(value,assignments) for value in operands],
                nominal_threshold_nm=nominal_threshold,
                options=values[1:] if kind not in {"coverage","forbidden_overlap"} else [])
    if operation=='ext_separation' and 'max_angle: 0' in contract['options'] and 'include_max_angle: true' in contract['options']:
        # Keep the actual cases and score. This is evidence about the fixed
        # host, not a blanket unsupported classification for other engines.
        contract['host_limitation']=dict(engine='KLayout 0.30.7',scope='nondegenerate polygon edge pairs',
            executed_angle_degrees=0.000001,
            explanation='cos(angle)+1e-10 exceeds 1 in EdgeRelationFilter::check; all such edge pairs rejected')
    return contract


def contract_from_text(rule_text: str | None) -> dict[str, Any] | None:
    for line in (rule_text or "").splitlines():
        if line.startswith("IHP contract: "):
            return json.loads(line.split(": ", 1)[1])
    return None


def generate_contract_cases(contract: dict[str, Any], delta_nm: int):
    from dataclasses import replace
    from autodrc import casegen as cg
    layers = contract['operand_layers']
    if contract['operation']=='isolated_device':
        result=[]
        for intent in ['GOOD','BAD']:
            mode=contract['mode']
            if mode in {'well_ring','schottky'}:
                shapes=[cg.rectangle('nwell',-1000,-1000,6000,1000),cg.rectangle('nwell',-1000,4000,6000,1000),
                        cg.rectangle('nwell',-1000,0,1000,4000),cg.rectangle('nwell',4000,0,1000,4000)]
                if mode=='well_ring':
                    gap=410 if intent=='GOOD' else 370
                    shapes += [cg.rectangle('activ',gap,1000,500,500),cg.rectangle('nbulay',-3000,-3000,10000,10000)]
                else:
                    margin=270 if intent=='GOOD' else 230
                    shapes += [cg.rectangle(layer,0,0,4000,4000) for layer in ['nbulay','nsd_block','salblock','recog_diode','thickgateox']]
                    # The vertical 160x340nm bar fits the recognised strip
                    # while keeping PWell:block at least 620nm from NWell.
                    shapes += [cg.rectangle('cont',900,1000,160,340),
                               cg.rectangle('pwell_block',900-margin,1000-margin,160+2*margin,340+2*margin),
                               cg.rectangle('activ',780,880,400,580),cg.rectangle('metal1',840,940,320,460)]
            else:
                margin=170 if intent=='GOOD' else 130
                shapes=[cg.rectangle('activ',0,0,3000,3000),cg.rectangle('nbulay',-2000,-2000,7000,7000),
                        cg.rectangle('nsd_block',1000,1000,1000,1000),
                        cg.rectangle('salblock',1000-margin,1000-margin,1000+2*margin,1000+2*margin)]
            result.append(cg.PatternCase(case_id='isolated_device_'+intent.lower(),intent=intent,
                description='Actual isolated device recognition: '+mode,polygons=tuple(shapes)))
        result.append(cg.generate_min_width_cases(layer='activ',min_width_nm=150,delta_nm=delta_nm)[2])
        return result
    if contract['operation']=='abutted_implant':
        result=[]
        for intent in ['GOOD','BAD']:
            mode=contract['mode']
            if mode=='partial_width':
                left=500 if intent=='GOOD' else 800
                shapes=[cg.rectangle('activ',0,0,1000,1000),cg.rectangle('psd',left,-180,1000,1360)]
            else:
                left=600 if intent=='GOOD' else 200
                shapes=[cg.rectangle('activ',0,0,1000,1000),cg.rectangle('psd',left,-180,1180-left,1360),
                        cg.rectangle('activ',2500,0,400,400),cg.rectangle('nwell',-620,-620,4140,2240),
                        cg.rectangle('cont',2620,120,160,160),cg.rectangle('metal1',2540,40,320,320)]
            result.append(cg.PatternCase(case_id='abutted_implant_'+intent.lower(),intent=intent,
                description='Actual partial implant / abutted well tie: '+mode,polygons=tuple(shapes)))
        result.append(cg.generate_min_width_cases(layer='activ',min_width_nm=300,delta_nm=delta_nm)[2])
        return result
    if contract['operation']=='latchup_distance':
        result=[]
        for intent in ['GOOD','BAD']:
            mode=contract['mode']
            if mode=='well_distance':
                x=10000 if intent=='GOOD' else 22000
                shapes=[cg.rectangle('activ',0,0,400,400),cg.rectangle('psd',-180,-180,760,760),
                        cg.rectangle('nwell',-620,-620,25000,1640),cg.rectangle('activ',x,0,400,400),
                        cg.rectangle('cont',x+120,120,160,160),cg.rectangle('metal1',x+40,40,320,320)]
            elif mode in {'n_abutted_tie','p_abutted_tie'}:
                shapes=[cg.rectangle('activ',0,0,10000,600),cg.rectangle('cont',500,220,160,160),
                        cg.rectangle('metal1',440,160,320,320)]
                if mode=='n_abutted_tie':
                    shapes += [cg.rectangle('psd',-180,-180,2180,960),
                               cg.rectangle('nwell',-620,-620,11240,1840),
                               cg.rectangle('gatpoly',8500,-180,500,960)]
                else:
                    shapes.append(cg.rectangle('psd',2000,-180,8180,960))
                if intent=='GOOD':
                    shapes.extend([cg.rectangle('cont',9500,220,160,160),cg.rectangle('metal1',9440,160,320,320)])
            else:
                length=4000 if intent=='GOOD' else 8000
                shapes=[cg.rectangle('activ',0,0,length,500),cg.rectangle('cont',120,170,160,160),
                        cg.rectangle('metal1',60,110,320,320)]
                if mode=='n_contact_distance':
                    shapes.append(cg.rectangle('nwell',-310,-310,length+620,1120))
                else:
                    shapes.append(cg.rectangle('psd',-180,-180,length+360,860))
            result.append(cg.PatternCase(case_id='latchup_distance_'+intent.lower(),intent=intent,
                description='Actual latch-up connected-contact propagation: '+mode,polygons=tuple(shapes)))
        result.append(cg.generate_min_width_cases(layer='activ',min_width_nm=150,delta_nm=delta_nm)[2])
        return result
    if contract['operation']=='resistor_contact':
        result=[]
        for intent,gap in [('GOOD',200),('BAD',180)]:
            end=160+gap+1000
            shapes=[cg.rectangle('cont',0,100,160,160),cg.rectangle('gatpoly',-90,-200,end+270,900),
                    cg.rectangle('salblock',160+gap,0,1000,500),
                    cg.rectangle('psd',-270,-380,end+630,1260),cg.rectangle('extblock',-270,-380,end+630,1260),
                    cg.rectangle('metal1',-60,40,320,320)]
            if contract['family']=='Rhigh':
                shapes.append(cg.rectangle('nsd',-270,-380,end+630,1260))
            result.append(cg.PatternCase(case_id='resistor_contact_'+intent.lower(),intent=intent,
                description=f'Actual resistor contact to SalBlock gap {gap}nm',polygons=tuple(shapes)))
        result.append(cg.generate_min_spacing_cases(layer='cont',min_spacing_nm=200,delta_nm=delta_nm,tech_name='ihp_sg13g2')[2])
        return result
    if contract['operation']=='resistor_masks':
        result=[]
        for intent,left in [('GOOD',0),('BAD',200)]:
            shapes=(cg.rectangle('nsd',0,0,4000,4000),cg.rectangle('psd',left,0,4000-left,4000),
                    cg.rectangle('extblock',0,0,4000,4000),cg.rectangle('gatpoly',1000,1000,600,2000))
            result.append(cg.PatternCase(case_id='resistor_masks_'+intent.lower(),intent=intent,
                description='Actual nSD-minus-pSD coincidence at resistor recognition boundary',polygons=shapes))
        result.append(cg.generate_min_width_cases(layer='nsd',min_width_nm=310,delta_nm=delta_nm)[2])
        return result
    if contract['operation']=='seal_ring':
        result=[]
        for intent in ['GOOD','BAD']:
            width=4200 if len(layers)==2 or intent=='GOOD' else 4180
            side=100000
            shapes=[cg.rectangle('passiv',0,0,side,width),cg.rectangle('passiv',0,side-width,side,width),
                    cg.rectangle('passiv',0,width,width,side-2*width),cg.rectangle('passiv',side-width,width,width,side-2*width)]
            if len(layers)==2:
                gap=1020 if intent=='GOOD' else 980
                shapes += [cg.rectangle(layers[1],-gap-4000,20000,4000,4000),
                           cg.rectangle('edgeseal',-gap-4000,20000,4000,4000)]
            result.append(cg.PatternCase(case_id='seal_ring_'+intent.lower(),intent=intent,
                description='Actual passivation ring outside sealring',polygons=tuple(shapes)))
        result.append(cg.generate_min_width_cases(layer='passiv',min_width_nm=4200,delta_nm=delta_nm)[2])
        return result
    if contract['operation']=='npn_ring':
        result=[]
        for intent in ['GOOD','BAD']:
            shapes=[cg.rectangle('psd',-1000,-1000,6000,1000),cg.rectangle('psd',-1000,4000,6000,1000),
                    cg.rectangle('psd',-1000,0,1000,4000),cg.rectangle('psd',4000,0,1000,4000)]
            mode=contract['mode']
            if mode=='separation' and layers[0]=='nsd_block':
                shapes=[cg.rectangle('psd',-800,-800,5600,800),cg.rectangle('psd',-800,4000,5600,800),
                        cg.rectangle('psd',-800,0,800,4000),cg.rectangle('psd',4000,0,800,4000)]
            if mode=='recognition':
                shapes.append(cg.rectangle('trans',0 if intent=='GOOD' else 10000,0,4000,4000))
            elif mode=='enclosure':
                shapes.append(cg.rectangle('trans',0,0,4000,4000))
                x,width=(-800,600) if intent=='GOOD' else (-900,800)
                shapes.append(cg.rectangle('activ',x,1000,width,1000))
            else:
                physical=layers[0]
                gap=contract['threshold_nm']+delta_nm if intent=='GOOD' else contract['threshold_nm']-delta_nm
                shapes.append(cg.rectangle('trans',0,0,4000,4000))
                width=400 if physical=='activ' else 1000 if physical in {'salblock','nsd_block','nbulay'} else 620 if physical in {'nwell','pwell_block'} else 500
                height=1000
                if physical=='cont':
                    width=height=160
                shapes.append(cg.rectangle(physical,-gap-width,1000,width,height))
                if physical=='cont':
                    shapes.extend([cg.rectangle('activ',-gap-width-120,880,width+190,400),
                                   cg.rectangle('metal1',-gap-width-60,940,320,320)])
            result.append(cg.PatternCase(case_id='npn_ring_'+intent.lower(),intent=intent,
                description='Actual labelled substrate-tie ring: '+mode,polygons=tuple(shapes),
                labels=(cg.TextLabel('text_0','npn13G2',(2000,2000)),)))
        result.append(cg.generate_min_width_cases(layer='psd',min_width_nm=310,delta_nm=delta_nm)[2])
        return result
    if contract['operation']=='emitter_length':
        result=[]
        for intent,length in [('GOOD',contract['threshold_nm']-delta_nm),('BAD',contract['threshold_nm']+delta_nm)]:
            shapes=(cg.rectangle('trans',0,0,10000,10000),cg.rectangle('emwind',1000,1000,70,length),
                    cg.rectangle('metal2_pin',5000,5000,400,400))
            result.append(cg.PatternCase(case_id='emitter_length_'+intent.lower(),intent=intent,
                description=f'Actually labelled emitter edge {length}nm',polygons=shapes,
                labels=(cg.TextLabel('text_0',contract['device_text'],(3000,3000)),cg.TextLabel('text_0','E',(5200,5200)))))
        result.append(cg.generate_min_width_cases(layer='emwind',min_width_nm=70,delta_nm=delta_nm)[2])
        return result
    if contract['operation']=='matching_coverage':
        result=[]
        for intent,x in [('GOOD',600),('BAD',4000)]:
            result.append(cg.PatternCase(case_id='matching_coverage_'+intent.lower(),intent=intent,
                description='Actual MIM covering / not covering a nonempty Vmim candidate',
                polygons=(cg.rectangle('mim',0,0,2000,2000),cg.rectangle('vmim',x,600,420,420))))
        result.append(cg.generate_min_width_cases(layer='mim',min_width_nm=1140,delta_nm=delta_nm)[2])
        return result
    if contract['operation']=='gate_rectangle':
        result=[]
        for intent in ['GOOD','BAD']:
            active=cg.rectangle('activ',0,0,1000,1000)
            points=((300,-180),(600,-180),(600,1180),(300,1180)) if intent=='GOOD' else (
                (300,-180),(600,-180),(600,400),(1180,400),(1180,700),(300,700))
            result.append(cg.PatternCase(case_id='gate_rectangle_'+intent.lower(),intent=intent,
                description='Actual rectangular / L-shaped gate intersection',
                polygons=(active,cg.Polygon('gatpoly',points+(points[0],)))))
        result.append(cg.generate_min_width_cases(layer='gatpoly',min_width_nm=300,delta_nm=delta_nm)[2])
        return result
    if contract['operation']=='hole_area':
        import math
        side=math.ceil(math.sqrt(contract['threshold_nm']))
        result=[]
        for intent,hole_side in [('GOOD',side+delta_nm),('BAD',max(10,side-delta_nm))]:
            wall=1000
            shapes=[cg.rectangle(layers[0],-wall,-wall,hole_side+2*wall,wall),
                    cg.rectangle(layers[0],-wall,hole_side,hole_side+2*wall,wall),
                    cg.rectangle(layers[0],-wall,0,wall,hole_side),
                    cg.rectangle(layers[0],hole_side,0,wall,hole_side)]
            result.append(cg.PatternCase(case_id='hole_area_'+intent.lower(),intent=intent,
                description=f'Actual enclosed hole {hole_side}nm square',polygons=tuple(shapes)))
        result.append(cg.generate_min_width_cases(layer=layers[0],min_width_nm=wall,delta_nm=delta_nm)[2])
        return result
    if contract['operation']=='large_array':
        result=[]
        count,seed=contract['array_count'],contract['seed_nm']
        for intent,gap in [('GOOD',contract['threshold_nm']),('BAD',contract['threshold_nm']-10)]:
            shapes=[cg.rectangle(layers[0],x*(seed+gap),y*(seed+gap),seed,seed)
                    for x in range(count) for y in range(count)]
            extent=count*seed+(count-1)*gap
            if layers[0]=='cont':
                shapes += [cg.rectangle('activ',-120,-120,extent+240,extent+240),
                           cg.rectangle('metal1',-60,-60,extent+120,extent+120)]
            else:
                for metal in [int(layers[0][-1]),int(layers[0][-1])+1]:
                    shapes.append(cg.rectangle('metal'+str(metal),-60,-60,extent+120,extent+120))
            result.append(cg.PatternCase(case_id='large_array_'+intent.lower(),intent=intent,
                description=f'{count}x{count} actual array with {gap}nm gaps',polygons=tuple(shapes)))
        result.append(cg.generate_min_spacing_cases(layer=layers[0],min_spacing_nm=contract['threshold_nm'],
            delta_nm=delta_nm,tech_name='ihp_sg13g2')[2])
        return result
    if contract['operation']=='channel_length':
        result=[]
        threshold=contract['threshold_nm']
        for intent,length in [('GOOD',threshold+delta_nm),('BAD',max(1,threshold-delta_nm))]:
            active_width=length+460
            shapes=[cg.rectangle('activ',-230,0,active_width,500),
                    cg.rectangle('gatpoly',0,-180,length,860),
                    cg.rectangle('thickgateox',-570,-520,active_width+680,1540)]
            if contract['device']=='pmosHV':
                shapes += [cg.rectangle('psd',-630,-400,active_width+800,1300),
                           cg.rectangle('nwell',-850,-620,active_width+1240,1740)]
                tx=length+1230
                shapes[-1]=cg.rectangle('nwell',-850,-620,tx+710+850,1740)
                shapes += [cg.rectangle('activ',tx,0,400,400),cg.rectangle('cont',tx+120,120,160,160),
                           cg.rectangle('metal1',tx+40,40,320,320)]
            result.append(cg.PatternCase(case_id=f"{contract['device']}_channel_{intent.lower()}",intent=intent,
                description=f'Actual HV channel length {length}nm versus {threshold}nm',polygons=tuple(shapes)))
        result.append(cg.generate_min_length_cases(layer='gatpoly',min_length_nm=threshold,delta_nm=delta_nm,tech_name='ihp_sg13g2')[2])
        return result
    choices = contract['input_clauses']
    fixed_sizes=contract.get('operand_sizes',[None for _ in layers])
    selected = None
    paired_enclosure = contract['operation'] in {'ext_enclosed', 'ext_not', 'endcap'}
    def cost(clause):
        return (len(clause['present']) + 10*('nsd_block' in clause['present']) +
                5*('nsd' in clause['present'])+10*('activ' in clause['absent']), len(clause['absent']), clause['present'])
    for left in sorted(choices[0], key=cost):
        if layers[0] not in left['present']:
            continue
        for right in sorted(choices[1], key=cost) if len(choices) == 2 else [None]:
            if right is not None and layers[1] not in right['present']:
                continue
            if paired_enclosure and (set(left['present']) & set(right['absent']) or
                                     set(right['present']) & set(left['absent'])):
                continue
            selected = [left] + ([right] if right is not None else [])
            break
        if selected is not None:
            break
    if selected is None:
        return None
    kind, threshold = contract['rule_type'], contract['threshold_nm']
    def size(layer):
        if layer.endswith('_filler') and layer.startswith(('topmetal1','topmetal2')):
            return 5000
        if layer.endswith('_filler') and layer.startswith('metal'):
            return 1000
        if layer.endswith('_slit'):
            return 2800
        if layer=='psd':
            return 500
        if layer=='res':
            return 500
        if layer=='lbe':
            return 500000
        if layer=='nsd_block':
            return 1000
        if layer=='mim':
            return 2000
        if layer in {'passiv','dfpad'}:
            return 50000
        if layer in {'via1','via2','via3','via4'}:
            return 190
        return max(cg._layer_size_hint(layer, tech_name='ihp_sg13g2'),
                   500 if layer=='gatpoly' else
                   420 if layer=='salblock' else
                   400 if layer in {'activ','metal1','metal2','metal3','metal4','metal5'} else 0)
    if paired_enclosure:
        seed_size=max(600,size(layers[0])) if layers[0]=='activ' and layers[1]=='thickgateox' else size(layers[0])
        cases = cg.generate_min_enclosure_cases(inner_layer=layers[0], outer_layer=layers[1],
            enclosure_nm=max(1, threshold), delta_nm=delta_nm, inner_size_nm=seed_size,
            cover_only=kind == 'coverage', tech_name='ihp_sg13g2')
        if layers[0]=='cont' or layers[0] in {'via1','via2','via3','via4'} or fixed_sizes[0]:
            updated=[]
            for case in cases:
                if case.intent=='ILLEGAL':
                    updated.append(case)
                    continue
                original_inner=case.polygons[0]
                x0,y0,x1,y1=cg._bbox(original_inner)
                width,height=fixed_sizes[0] or ((160,160) if layers[0]=='cont' else (190,190))
                outer=case.polygons[1]
                ox0,oy0,ox1,oy1=cg._bbox(outer)
                # Keep every original enclosure margin when resizing a square
                # seed into a filtered bar. Leaving the old outer box clips it.
                outer=cg.rectangle(layers[1],ox0,oy0,
                    width+(x0-ox0)+(ox1-x1),height+(y0-oy0)+(oy1-y1))
                updated.append(replace(case,polygons=(cg.rectangle(layers[0],x0,y0,width,height),outer)+case.polygons[2:]))
            cases=updated
        if contract['operation']=='endcap':
            updated=[]
            for case in cases:
                if case.intent=='ILLEGAL':
                    updated.append(case)
                    continue
                inner=case.polygons[0]
                x0,y0,x1,y1=cg._bbox(inner)
                margin=threshold+delta_nm if case.intent=='GOOD' else max(1,threshold-delta_nm)
                width=x1-x0+2*margin
                height=y1-y0+2*margin
                if layers[0].startswith('via'):
                    # Three insufficient sides violate the endcap predicate;
                    # extending the fourth side supplies valid metal area.
                    width=max(width,700 if case.intent=='BAD' else 400)
                    if case.intent=='GOOD':
                        height=max(height,400)
                elif layers[0]=='cont' and case.intent=='BAD':
                    width=max(width,700)
                outer=cg.rectangle(layers[1],x0-margin,y0-margin,width,height)
                updated.append(replace(case,polygons=(inner,outer)))
            cases=updated
        if kind == 'coverage':
            # Keep a valid outer metal body in BAD; expose a small slice of the
            # inner contact instead of narrowing the outer carrier to half size.
            updated = []
            for case in cases:
                if case.intent == 'ILLEGAL':
                    updated.append(case)
                    continue
                inner = case.polygons[0]
                x0, y0, x1, y1 = cg._bbox(inner)
                width, height = max(400, x1-x0+80), max(400, y1-y0+80)
                margin=120 if layers[1]=='activ' else 60
                if layers[1]=='activ':
                    width,height=max(400,x1-x0+240),max(400,y1-y0+240)
                outer = cg.rectangle(layers[1], x0-margin if case.intent == 'GOOD' else x0+min(5,delta_nm),
                                     y0-margin, width, height)
                updated.append(replace(case, polygons=(inner, outer)))
            cases = updated
    elif kind == 'max_width':
        cases=cg.generate_max_width_cases(layer=layers[0],max_width_nm=threshold,delta_nm=delta_nm)
    elif kind == 'min_width':
        cases = cg.generate_min_width_cases(layer=layers[0], min_width_nm=threshold, delta_nm=delta_nm)
        if layers[0]=='psd':
            updated=[]
            for case in cases:
                if case.intent=='ILLEGAL':
                    updated.append(case);continue
                x0,y0,x1,y1=cg._bbox(case.polygons[0]);width=min(x1-x0,y1-y0)
                updated.append(replace(case,polygons=(cg.rectangle('psd',x0,y0,width,max(width,1000,250000//width+1)),)))
            cases=updated
        if contract.get('compound_expression','').strip().startswith('[') and '.sized(-' in contract['compound_expression']:
            cases[0]=replace(cases[0],polygons=(cg.rectangle(layers[0],0,0,threshold,max(400,threshold)),),
                             description=f'Exact size {threshold}nm; combined minimum/maximum predicate')
    elif kind in {'min_spacing','forbidden_overlap'}:
        if len(layers) == 2:
            cases = []
            widths = [size(layer) for layer in layers]
            heights = [max(width, 1000 if layer == 'activ' else 400) for layer,width in zip(layers,widths)]
            for role,layer in enumerate(layers):
                if layer=='cont':
                    widths[role]=heights[role]=160
            for role,fixed in enumerate(fixed_sizes):
                if fixed:
                    widths[role],heights[role]=fixed
            for intent,gap in [('GOOD',50000 if kind=='forbidden_overlap' else threshold+delta_nm),
                               ('BAD',-widths[0] if kind=='forbidden_overlap' else max(1,threshold-delta_nm))]:
                if intent=='GOOD' and layers==['passiv','activ'] and 'edgeseal' in selected[1]['present']:
                    gap=max(gap,25000+delta_nm)
                if intent=='GOOD' and 'extblock' in selected[0]['present'] and layers[1]=='psd':
                    gap=max(gap,490+delta_nm)
                shapes = (cg.rectangle(layers[0],0,0,widths[0],heights[0]),
                          cg.rectangle(layers[1],widths[0]+gap,0,widths[1],heights[1]))
                cases.append(cg.PatternCase(case_id=f'{layers[0]}_{layers[1]}_spacing_{intent.lower()}',
                    intent=intent,description=f'Actual predicate spacing {gap}nm versus {threshold}nm',polygons=shapes))
            cases.append(cg.generate_cross_layer_spacing_cases(layer=layers[0],other_layer=layers[1],
                         min_spacing_nm=max(1,threshold),delta_nm=delta_nm,tech_name='ihp_sg13g2')[2])
        else:
            cases = cg.generate_min_spacing_cases(layer=layers[0], min_spacing_nm=threshold,
                        delta_nm=delta_nm, tech_name='ihp_sg13g2')
            spacing_size=fixed_sizes[0] or ((500,500) if
                layers[0]=='activ' and {'gatpoly','thickgateox'}<=set(selected[0]['present']) else
                (size(layers[0]),size(layers[0])))
            if spacing_size:
                width,height=spacing_size
                updated=[]
                for case in cases:
                    if case.intent=='ILLEGAL':
                        updated.append(case)
                        continue
                    gap=threshold+delta_nm if case.intent=='GOOD' else max(1,threshold-delta_nm)
                    updated.append(replace(case,polygons=(cg.rectangle(layers[0],0,0,width,height),
                        cg.rectangle(layers[0],width+gap,0,width,height))))
                cases=updated
    elif kind in {'min_area', 'max_area'}:
        fn = cg.generate_min_area_cases if kind == 'min_area' else cg.generate_max_area_cases
        cases = fn(layer=layers[0], **{kind+'_nm2': threshold}, delta_percent=max(10,min(50,delta_nm)), tech_name='ihp_sg13g2')
        if layers[0]=='mim' and kind=='min_area' and threshold==1300000:
            cases[1]=replace(cases[1],polygons=(cg.rectangle('mim',0,0,1140,1140),),
                description='1140nm square: valid width and 1299600nm² below 1300000nm²')
        if layers[0]=='cont' and fixed_sizes[0] and kind=='min_area':
            length=(threshold+159)//160
            cases[:2]=[replace(cases[i],polygons=(cg.rectangle('cont',0,0,
                length+delta_nm if i==0 else max(170,length-delta_nm),160),)) for i in range(2)]
        if kind=='min_area' and layers[0]=='activ' and threshold<122000:
            cases[0]=cg.generate_min_area_cases(layer='activ',min_area_nm2=122000,
                            delta_percent=max(10,min(50,delta_nm)),tech_name='ihp_sg13g2')[0]
    elif kind in {'min_length','max_length'}:
        fn=cg.generate_min_length_cases if kind=='min_length' else cg.generate_max_length_cases
        options=dict(layer=layers[0],delta_nm=delta_nm,**{kind+'_nm':threshold})
        if kind=='min_length':
            options['tech_name']='ihp_sg13g2'
        cases=fn(**options)
    else:
        return None
    result = []
    for case in cases:
        if case.intent == 'ILLEGAL':
            result.append(case)
            continue
        polygons = list(case.polygons)
        if kind=='min_spacing' and layers==['salblock','cont']:
            # This contact is on a poly carrier related to SalBlock, which
            # avoids introducing an unrelated active/poly spacing violation.
            bounds=[cg._bbox(p) for p in polygons]
            x0=min(b[0] for b in bounds);y0=min(b[1] for b in bounds)
            x1=max(b[2] for b in bounds);y1=max(b[3] for b in bounds)
            polygons.append(cg.rectangle('gatpoly',x0-200,y0-200,x1-x0+400,y1-y0+400))
        if paired_enclosure and layers[0]=='cont' and layers[1]=='psd':
            x0,y0,x1,y1=cg._bbox(case.polygons[0])
            margin=max(180,threshold+delta_nm) if case.intent=='GOOD' else max(1,threshold-delta_nm)
            polygons[1]=cg.rectangle('psd',x0-margin,y0-margin,max(600,x1-x0+2*margin),max(500,y1-y0+2*margin))
        if paired_enclosure and layers[0]=='gatpoly' and layers[1]=='activ':
            x0,y0,x1,y1=cg._bbox(case.polygons[0])
            margin=threshold+delta_nm if case.intent=='GOOD' else max(1,threshold-delta_nm)
            polygons=[cg.rectangle('gatpoly',x0,y0-180,x1-x0,y1-y0+360),
                      cg.rectangle('activ',x0-margin,y0,x1-x0+2*margin,y1-y0)]
        if paired_enclosure and layers[0]=='activ' and layers[1]=='thickgateox':
            x0,y0,x1,y1=cg._bbox(case.polygons[0])
            mx=max(threshold+delta_nm,500) if case.intent=='GOOD' else max(1,threshold-delta_nm)
            my=max(threshold+delta_nm,500)
            polygons[1]=cg.rectangle('thickgateox',x0-mx,y0-my,x1-x0+2*mx,y1-y0+2*my)
        # Increase only the GOOD enclosure for stricter companion endcap rules;
        # BAD retains the small margin that violates the requested predicate.
        if paired_enclosure and case.intent == 'GOOD' and contract['operation'] == 'ext_enclosed' and threshold < 50:
            inner=case.polygons[0]
            x0,y0,x1,y1=cg._bbox(inner)
            polygons[1]=cg.rectangle(layers[1],x0-60,y0-60,max(400,x1-x0+120),max(400,y1-y0+120))
        if paired_enclosure and layers[1]=='activ' and any('edgeseal' in clause['present'] for clause in selected):
            # Keep the measured small enclosure on the left/bottom, and extend
            # the opposite sides to satisfy the 3.5um seal active width.
            x0,y0,x1,y1=cg._bbox(polygons[1])
            polygons[1]=cg.rectangle('activ',x0,y0,max(3500,x1-x0),max(3500,y1-y0))
        for role, clause in enumerate(selected):
            originals = ([case.polygons[role]] if len(layers)==2 else
                         [p for p in polygons if p.layer == layers[role]])
            for marker in clause['present']:
                if marker == layers[role] or (paired_enclosure and marker in layers):
                    continue
                for primary in originals:
                    x0,y0,x1,y1=cg._bbox(primary)
                    margin = {'activ':120,'gatpoly':90,'psd':180,'nwell':310,'thickgateox':340,'salblock':200,'extblock':180,'res':1000}.get(marker,0)
                    if marker in {'activ','gatpoly'} and layers[role]!='cont':
                        margin=0
                    if marker=='thickgateox' and layers[role]=='activ' and 'gatpoly' in clause['present'] and not paired_enclosure:
                        margin=500
                    if marker=='nsd' and 'psd' in clause['present']:
                        margin=180
                    if marker=='nbulay':
                        margin=1240
                    mx0,my0=x0-margin,y0-margin
                    mw,mh=x1-x0+2*margin,y1-y0+2*margin
                    if marker=='activ' and layers[role]=='cont':
                        mw,mh=max(400,mw),max(400,mh)
                        if kind=='min_spacing' and len(layers)==2:
                            mx0=x0-170 if role==0 else x0-70
                            mw=max(400,x1-x0+240)
                    polygons.append(cg.rectangle(marker,mx0,my0,mw,mh))
            if layers[role]=='activ' and 'gatpoly' in clause['present'] and paired_enclosure:
                # A crossed gate: active supplies source/drain extension in X,
                # and poly supplies endcaps in Y. The intersection is the seed.
                for primary in originals:
                    x0,y0,x1,y1=cg._bbox(primary)
                    polygons.remove(primary)
                    polygons.append(cg.rectangle('activ',x0-230,y0,x1-x0+460,y1-y0))
                    polygons=[p for p in polygons if not (p.layer=='gatpoly' and cg._bbox(p)==(x0,y0,x1,y1))]
                    polygons.append(cg.rectangle('gatpoly',x0,y0-180,x1-x0,y1-y0+360))
            if layers[role]=='activ' and 'gatpoly' in clause['present'] and not paired_enclosure:
                polygons=[p for p in polygons if p.layer!='gatpoly']
                for primary in originals:
                    x0,y0,x1,y1=cg._bbox(primary)
                    polygons.remove(primary)
                    polygons.append(cg.rectangle('activ',x0,y0-230,x1-x0,y1-y0+460))
                    polygons.append(cg.rectangle('gatpoly',x0-180,y0,x1-x0+360,y1-y0))
        if kind=='forbidden_overlap' and layers[0]=='cont' and layers[1]=='activ':
            cont=case.polygons[0]
            x0,y0,x1,y1=cg._bbox(cont)
            if case.intent=='BAD':
                # A contacted gate overlap is the intended error; both masks
                # can otherwise enclose the complete contact legally.
                polygons=[p for p in polygons if p.layer not in {'activ','gatpoly'}]
                active_height=max(400,y1-y0+240)
                polygons.extend([cg.rectangle('activ',x0-320,y0-120,x1-x0+640,active_height),
                                 cg.rectangle('gatpoly',x0-90,y0-300,x1-x0+180,active_height+360)])
        if paired_enclosure and layers[0]=='cont' and layers[1]=='metal1' and contract['operation']=='ext_not':
            x0,y0,x1,y1=cg._bbox(case.polygons[0])
            polygons.append(cg.rectangle('activ',x0-120,y0-120,max(400,x1-x0+240),max(400,y1-y0+240)))
        if paired_enclosure and layers[0]=='cont' and layers[1]=='metal1' and contract['operation']=='endcap':
            x0,y0,x1,y1=cg._bbox(case.polygons[0])
            polygons.append(cg.rectangle('activ',x0-120,y0-120,x1-x0+240,y1-y0+240))
        if paired_enclosure and layers[0] in {'via1','via2','via3','via4'} and case.intent=='BAD':
            outer=polygons[1]
            x0,y0,x1,y1=cg._bbox(outer)
            polygons[1]=cg.rectangle(outer.layer,x0,y0,max(700,x1-x0),y1-y0)
        for primary in list(polygons):
            if primary.layer=='cont' and not (paired_enclosure and layers[1]=='metal1'):
                x0,y0,x1,y1=cg._bbox(primary)
                if paired_enclosure and layers[1]=='activ' and any('edgeseal' in clause['present'] for clause in selected):
                    polygons.append(cg.Polygon('metal1',polygons[1].points))
                else:
                    polygons.append(cg.rectangle('metal1',x0-60,y0-60,max(320,x1-x0+120),max(320,y1-y0+120)))
                def covers_contact(p):
                    px0,py0,px1,py1=cg._bbox(p)
                    return p.layer in {'activ','gatpoly'} and px0<=x0 and py0<=y0 and px1>=x1 and py1>=y1
                if not any(covers_contact(p) for p in polygons) and not (paired_enclosure and layers[1]=='activ') and not any('activ' in c['absent'] for c in selected):
                    body=500 if 'nsd_block' in layers else 400
                    polygons.append(cg.rectangle('activ',x0-120,y0-120,max(body,x1-x0+240),max(body,y1-y0+240)))
            if primary.layer in {'via1','via2','via3','via4'}:
                for metal in [int(primary.layer[-1]),int(primary.layer[-1])+1]:
                    carrier='metal'+str(metal)
                    if not any(p.layer==carrier for p in polygons):
                        x0,y0,x1,y1=cg._bbox(primary)
                        polygons.append(cg.rectangle(carrier,x0-60,y0-60,max(400,x1-x0+120),max(400,y1-y0+120)))
            if primary.layer=='mim':
                x0,y0,x1,y1=cg._bbox(primary)
                polygons.append(cg.rectangle('vmim',x0+100,y0+100,min(420,x1-x0-200),min(420,y1-y0-200)))
        # A P+ diffusion inside NWell needs an actual contacted NWell tie. Add an
        # isolated tie to the right and extend the same well without moving the
        # target's left/bottom enclosure boundary.
        if paired_enclosure and 'activ' in layers and any('psd' in p['present'] for p in selected):
            well=next((p for p in polygons if p.layer=='nwell'),None)
            if well is not None:
                active=next(p for p in case.polygons if p.layer=='activ')
                ax0,ay0,ax1,ay1=cg._bbox(active)
                tx=ax1+1000
                x0,y0,x1,y1=cg._bbox(well)
                polygons.remove(well)
                polygons.append(cg.rectangle('nwell',x0,min(y0,ay0-310),max(x1,tx+710)-x0,max(y1,ay0+710)-min(y0,ay0-310)))
                polygons.extend([cg.rectangle('activ',tx,ay0,400,400),
                                 cg.rectangle('cont',tx+120,ay0+120,160,160),
                                 cg.rectangle('metal1',tx+40,ay0+40,320,320)])
        if layers[0]=='salblock' and 'gatpoly' in selected[0]['present'] and not paired_enclosure:
            # The width target is the poly/SalBlock intersection. Enlarging the
            # physical SalBlock around the unchanged poly keeps that target and
            # satisfies its independent 200nm extension predicate.
            polygons=[p if p.layer!='salblock' else cg.rectangle('salblock',cg._bbox(p)[0]-200,cg._bbox(p)[1]-200,
                          cg._bbox(p)[2]-cg._bbox(p)[0]+400,cg._bbox(p)[3]-cg._bbox(p)[1]+400) for p in polygons]
        if any('edgeseal' in clause['present'] for clause in selected):
            # Size companion carriers independently, then cover their actual
            # final extents with EdgeSeal. The target cut or width stays fixed.
            updated=[]
            for p in polygons:
                x0,y0,x1,y1=cg._bbox(p)
                carrier=p.layer=='activ' or p.layer in {'metal1','metal2','metal3','metal4','metal5','topmetal1','topmetal2'}
                primary_width=kind in {'min_width','max_width'} and p.layer==layers[0]
                if carrier and not primary_width:
                    if layers[0]=='cont' and kind=='min_width' and p.layer in {'activ','metal1'}:
                        cx0,cy0,cx1,cy1=cg._bbox(case.polygons[0])
                        p=cg.rectangle(p.layer,cx0-1300,cy0-1300,max(3500,cx1-cx0+2600),max(3500,cy1-cy0+2600))
                    else:
                        p=cg.rectangle(p.layer,x0,y0,max(3500,x1-x0),max(3500,y1-y0))
                updated.append(p)
            polygons=updated
            relevant=[cg._bbox(p) for p in polygons if p.layer not in {'edgeseal','passiv','dfpad','dfpad_pillar'}]
            if relevant:
                x0=min(b[0] for b in relevant);y0=min(b[1] for b in relevant)
                x1=max(b[2] for b in relevant);y1=max(b[3] for b in relevant)
                polygons=[p for p in polygons if p.layer!='edgeseal']+[cg.rectangle('edgeseal',x0-200,y0-200,x1-x0+400,y1-y0+400)]
        # Preserve separate shapes; deduplicate identical masks only.
        polygons = list(dict.fromkeys(polygons))
        result.append(replace(case, polygons=tuple(polygons),
                              description=case.description+' [IHP actual-predicate inputs]'))
    return result
