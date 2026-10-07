import unittest
from autodrc.casegen import PatternCase
from autodrc.lpl import Polygon,TextLabel,rectangle
from autodrc.shape_space import transform_case,diversity,payload,case_from_payload


class ShapeSpaceTests(unittest.TestCase):
    def test_complete_geometry_and_labels_rotate_together_and_invert(self):
        case=PatternCase('x','GOOD','device',(rectangle('nwell',10,20,100,300),),labels=(TextLabel('text_0','E',(50,100)),))
        rotated=transform_case(case,quarter_turns=1)
        restored=transform_case(rotated,quarter_turns=3)
        self.assertEqual(restored.polygons,case.polygons);self.assertEqual(restored.labels,case.labels)
        self.assertEqual(rotated.labels[0].position,(-100,50))

    def test_translation_is_not_counted_as_intrinsic_diversity(self):
        a=PatternCase('a','GOOD','x',(rectangle('met1',0,0,200,500),))
        b=transform_case(a,translate_nm=(1000,2000))
        c=PatternCase('c','GOOD','x',(rectangle('met1',0,0,300,500),))
        value=diversity([a,b,c]);self.assertEqual(value['exact_unique'],3);self.assertEqual(value['translation_normalized_unique'],2)

    def test_reloaded_payload_is_revalidated_instead_of_trusting_flag(self):
        value=dict(intent='GOOD',lpl=[dict(layer='met1',points=[[0,0],[10,0],[20,0],[0,0]])],geometry_valid=True)
        self.assertFalse(case_from_payload(value).to_dict()['geometry_valid'])

    def test_intent_and_polygon_traversal_do_not_inflate_geometric_diversity(self):
        a=PatternCase('a','GOOD','x',(rectangle('met1',0,0,200,200),))
        b=PatternCase('b','BAD','x',(Polygon('met1',((200,200),(200,0),(0,0),(0,200),(200,200))),))
        c=transform_case(a,quarter_turns=1,translate_nm=(200,0))
        value=diversity([a,b,c]);self.assertEqual(value['exact_unique'],1);self.assertEqual(value['translation_normalized_unique'],1)
