from pathlib import Path
import json
import unittest

from autodrc.ihp_contracts import compile_contract, input_certificates, generate_contract_cases
from autodrc.runset_coverage import classify_rule, parse_runset_outputs
from autodrc.runset_semantics import parse_runset_output_semantics


class IHPContractTests(unittest.TestCase):
    def test_polarity_comes_from_derived_boolean_input(self):
        layers = {'activ': 'activ', 'psd': 'psd', 'nsd': 'nsd', 'block': 'nsd_block'}
        assignments = {'ndrv': 'nSD.ext_or(Activ.ext_not(block.ext_or(pSD)))',
                       'nact': 'Activ.ext_and(ndrv)', 'pact': 'Activ.ext_not(nact)'}
        clauses, _ = input_certificates('pact', assignments, layers)
        self.assertTrue(clauses)
        self.assertTrue(all('activ' in positive and 'nsd' in negative and
                            bool(positive & {'psd', 'nsd_block'}) for positive, negative in clauses))

    def test_unknown_filter_cannot_certify_positive_input(self):
        layers = {'a': 'activ', 'b': 'nwell'}
        clauses, empty = input_certificates('a.ext_rectangles(inverted: true)', {}, layers)
        self.assertEqual(clauses, [])
        self.assertEqual(empty, [(frozenset(), frozenset({'activ'}))])
        # A filter with an absent base cannot manufacture new geometry.
        clauses, _ = input_certificates('b.ext_not(a.ext_rectangles(inverted: true))', {}, layers)
        self.assertEqual(clauses, [(frozenset({'nwell'}), frozenset({'activ'}))])

    def test_actual_width_and_area_override_description(self):
        upstream = ('L1:res = source.polygons("24/0")', 'L2:lbe = source.polygons("157/0")')
        width = compile_contract('RES.ext_width(0.5.um)', upstream, {'res','lbe'}, 'min_length')
        area = compile_contract('LBE.ext_with_area([["<", 250000.0.um2]])', upstream, {'res','lbe'}, 'min_area')
        self.assertEqual(width['rule_type'], 'min_width')
        self.assertEqual(area['threshold_nm'], 250000000000)

    def test_full_coverage_bad_exposes_contact_without_narrowing_metal(self):
        upstream = ('L1:cont = source.polygons("6/0")', 'L2:metal1 = source.polygons("8/0")')
        contract = compile_contract('Cont.ext_not(Metal1)', upstream, {'cont','metal1'}, 'min_enclosure')
        cases = generate_contract_cases(contract, 20)
        good, bad = cases[:2]
        for case in (good, bad):
            contact = next(p for p in case.polygons if p.layer == 'cont')
            metal = next(p for p in case.polygons if p.layer == 'metal1')
            self.assertGreaterEqual(max(x for x,y in metal.points)-min(x for x,y in metal.points), 400)
        self.assertLess(min(x for x,y in good.polygons[1].points), min(x for x,y in good.polygons[0].points))
        self.assertGreater(min(x for x,y in bad.polygons[1].points), min(x for x,y in bad.polygons[0].points))

    def test_derived_name_is_not_a_physical_layer_guess(self):
        self.assertIsNone(compile_contract('NAct.ext_width(0.5.um)', (), {'activ','nact'}, 'min_width'))

    def test_union_keeps_compound_expression_and_one_explicit_branch(self):
        upstream=('L1:a = source.polygons("1/0")', 'L2:b = source.polygons("2/0")',
                  'L3:err = a.ext_space(0.2.um)', 'L4:combined = err + b.ext_space(0.2.um)')
        contract=compile_contract('combined.dup',upstream,{'a','b'},'min_spacing')
        self.assertEqual(contract['compound_expression'],'combined.dup')
        self.assertEqual(contract['operands'],['a'])
        self.assertEqual(contract['threshold_nm'],200)

    def test_exact_size_array_good_uses_equal_boundary(self):
        upstream=('L1:cont = source.polygons("6/0")',)
        expression='[Cont.ext_width(0.16.um), Cont.sized(-0.16.um/2.0, acute_limit).sized(0.16.um/2.0, acute_limit)]'
        contract=compile_contract(expression,upstream,{'cont'},'min_width')
        cases=generate_contract_cases(contract,20)
        self.assertEqual(max(x for x,y in cases[0].polygons[0].points),160)
        points=cases[1].polygons[0].points
        self.assertEqual(min(max(x for x,y in points)-min(x for x,y in points),
                             max(y for x,y in points)-min(y for x,y in points)),140)

    def test_official_length_helper_float_offset_is_one_micrometre(self):
        upstream=('L1:slit = source.polygons("8/24")',)
        contract=compile_contract('slit.ext_with_length([[">", 20.0.um]])',upstream,{'slit'},'max_width')
        self.assertEqual(contract['nominal_threshold_nm'],20000)
        self.assertEqual(contract['threshold_nm'],21000)

    def test_filtered_bar_resize_preserves_enclosure_on_all_sides(self):
        upstream=('L1:cont = source.polygons("6/0")','L2:activ = source.polygons("1/0")',
                  'L3:bar = Cont.ext_with_area([[">", (0.16*0.16).um2]])')
        contract=compile_contract('bar.ext_enclosed(Activ,0.07.um)',upstream,{'cont','activ'},'min_enclosure')
        case=generate_contract_cases(contract,20)[0]
        cont=case.polygons[0];active=case.polygons[1]
        self.assertEqual(max(x for x,y in cont.points)-min(x for x,y in cont.points),340)
        self.assertGreaterEqual(max(x for x,y in active.points)-max(x for x,y in cont.points),90)

    def test_actual_hole_and_array_inputs_are_explicit(self):
        upstream=('L1:activ = source.polygons("1/0")',)
        c=compile_contract('(Activ.holes - Activ.with_holes).without_holes.ext_not(Activ).ext_with_area([["<", 0.15.um2]])',
                           upstream,{'activ'},'min_area')
        self.assertEqual(c['operands'],['Activ','Activ.holes'])
        self.assertEqual(len(generate_contract_cases(c,20)[0].polygons),4)

    def test_morphological_threshold_comes_from_expression(self):
        upstream=('L1:metal1 = source.polygons("8/0")','L2:a = Metal1.sized(-3.um, acute_limit)',
                  'L3:b = a.sized(-12.um, acute_limit)')
        c=compile_contract('b.sized(15.um, acute_limit)',upstream,{'metal1'},'max_width')
        self.assertEqual(c['threshold_nm'],30000)
        self.assertEqual(c['operands'],['Metal1'])

    def test_forbidden_gate_contact_retains_both_real_inputs(self):
        upstream=('L1:cont = source.polygons("6/0")','L2:activ = source.polygons("1/0")',
                  'L3:gatpoly = source.polygons("5/0")','L4:gate = Activ.ext_and(GatPoly)')
        c=compile_contract('Cont.ext_and(Gate)',upstream,{'cont','activ','gatpoly'},'forbidden_overlap')
        self.assertEqual(c['rule_type'],'forbidden_overlap')
        self.assertEqual(c['operands'],['Cont','Gate'])

    def test_gate_rectangle_good_and_bad_are_legal_closed_shapes(self):
        cases=generate_contract_cases(dict(operation='gate_rectangle',operand_layers=['activ','gatpoly']),20)
        self.assertTrue(all(c.to_dict()['geometry_valid'] for c in cases[:2]))
        self.assertFalse(cases[2].to_dict()['geometry_valid'])

    def test_emitter_official_empty_interval_and_text_are_retained(self):
        upstream=('L1:emwind = source.polygons("33/0")','L2:trans = source.polygons("26/0")',
            'L3:transG2 = TRANS.ext_interacting_with_text(TEXT_0, "npn13G2").ext_covering(emi2Pin)',
            'L4:emit_npn13G2 = EmWind.inside(transG2)')
        c=compile_contract('emit_npn13G2.ext_with_length([[">", 0.07.um], ["<", 0.9.um]])',upstream,{'emwind','trans'},'min_length')
        self.assertEqual((c['executed_lower_nm'],c['executed_upper_nm']),(1070,900))
        self.assertIsNotNone(c['official_limitation'])
        self.assertEqual(generate_contract_cases(c,20)[0].to_dict()['labels'][0]['text'],'npn13G2')

    def test_labels_do_not_change_unlabelled_serialization(self):
        from autodrc.casegen import PatternCase, rectangle, TextLabel
        case=PatternCase('test','GOOD','test',(rectangle('trans',0,0,100,100),))
        self.assertNotIn('labels',case.to_dict())
        from dataclasses import replace
        bad=replace(case,labels=(TextLabel('text_0','E',(1.5,0)),))
        self.assertFalse(bad.to_dict()['geometry_valid'])

    def test_zero_angle_host_limit_does_not_change_actual_threshold(self):
        import math
        upstream=('L1:a = source.polygons("14/0")','L2:b = source.polygons("6/0")')
        c=compile_contract('a.ext_separation(b,0.09.um,max_angle: 0,include_max_angle: true)',upstream,{'a','b'},'min_spacing')
        self.assertEqual(c['threshold_nm'],90)
        self.assertEqual(c['host_limitation']['engine'],'KLayout 0.30.7')
        self.assertGreater(math.cos(math.radians(0.000001))+1e-10,1)


if __name__ == '__main__':
    unittest.main()
