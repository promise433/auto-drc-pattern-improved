import json
import unittest
from autodrc.lpl import Polygon
from autodrc.llm_generator import parse_model_response
from autodrc.casegen import PatternCase
from autodrc.llm_policy import adjust_llm_cases
from autodrc.rules import ParsedRule


class RigorousGeometryTests(unittest.TestCase):
    def test_degenerate_closed_manhattan_geometry_is_rejected_only_when_requested(self):
        for points in [((0,0),(10,0),(20,0),(0,0)),
                       ((0,0),(10,0),(10,0),(10,10),(0,10),(0,0)),
                       ((0,0),(10,0),(5,0),(5,10),(0,10),(0,0))]:
            polygon=Polygon('met1',points)
            self.assertEqual(polygon.validate(),[])
            self.assertTrue(polygon.validate(rigorous=True))

    def test_crossing_and_nonadjacent_touch_are_rejected(self):
        crossing=Polygon('met1',((0,0),(20,20),(0,20),(20,0),(0,0)))
        self.assertTrue(any('self-intersection' in e for e in crossing.validate(True,rigorous=True)))
        touching=Polygon('met1',((0,0),(20,0),(20,20),(10,20),(10,0),(0,0)))
        self.assertTrue(any('self-intersection' in e for e in touching.validate(rigorous=True)))

    def test_valid_collinear_vertices_and_allowed_triangle(self):
        rectangle=Polygon('met1',((0,0),(10,0),(20,0),(20,10),(0,10),(0,0)))
        self.assertEqual(rectangle.validate(rigorous=True),[])
        triangle=Polygon('met1',((0,0),(20,0),(10,20),(0,0)))
        self.assertEqual(triangle.validate(True,rigorous=True),[])
        self.assertTrue(triangle.validate(rigorous=True))

    def test_strict_parser_flags_geometry_without_removing_response(self):
        raw=json.dumps(dict(intent='GOOD',lpl=[dict(layer='met1',points=[[0,0],[10,0],[20,0],[0,0]])]))
        legacy=parse_model_response(raw,intent='GOOD',expected_layer='met1',tech_name='sky130')
        strict=parse_model_response(raw,intent='GOOD',expected_layer='met1',tech_name='sky130',strict=True)
        self.assertTrue(legacy.to_case_dict()['geometry_valid'])
        self.assertFalse(strict.to_case_dict()['geometry_valid'])
        # An invalid raw GOOD is repaired to a genuinely valid construction.
        case=PatternCase('raw','GOOD','actual raw',strict.polygons,rigorous_geometry=True)
        fixed=adjust_llm_cases(base_cases=[case],rule=ParsedRule('min_width','met1',140,'met1 width'),tech_name='sky130')[0]
        self.assertTrue(fixed.rigorous_geometry)
        self.assertTrue(fixed.to_dict()['geometry_valid'])

    def test_strict_integer_coordinates_are_never_converted_through_float(self):
        x=2**53+1
        points=[[x,0],[x+20,0],[x+20,20],[x,20],[x,0]]
        raw=json.dumps(dict(intent='BAD',lpl=[dict(layer='met1',points=points)]))
        case=parse_model_response(raw,intent='BAD',expected_layer='met1',tech_name='sky130',strict=True)
        self.assertEqual(case.to_case_dict()['lpl'][0]['points'],points)
