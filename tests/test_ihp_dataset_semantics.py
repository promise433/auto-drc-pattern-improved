from types import SimpleNamespace
import unittest

from autodrc.ihp_contracts import compile_contract
from autodrc.ihp_workflow import ihp_pretrain_example


class IHPDatasetSemanticsTests(unittest.TestCase):
    def example(self, expression, description, hint, layer):
        rule=SimpleNamespace(rule_id='fixture',description=description,threshold_nm=hint,
            layer_hint=layer,source_file='sg13g2_maximal.drc',line_no=1)
        semantic=SimpleNamespace(expression=expression,anonymous_body=expression)
        upstream=(f'L1:{layer} = source.polygons("24/0")',)
        contract=compile_contract(expression,upstream,{layer},None)
        return ihp_pretrain_example(rule,semantic,dict(ihp_contract=contract,supported=True))

    def test_description_length_is_not_exported_as_executed_res_length(self):
        row=self.example('RES.ext_width(0.5.um)','Min. RES length = 0.50',500,'res')
        self.assertEqual(row['output']['rule_type'],'min_width')
        self.assertEqual((row['output']['threshold_value'],row['output']['threshold_unit']),(500,'nm'))

    def test_actual_area_and_unit_override_description_hint(self):
        row=self.example('LBE.ext_with_area([["<", 250000.0.um2]])','Min. LBE area = 30000.00',30000000,'lbe')
        self.assertEqual((row['output']['threshold_value'],row['output']['threshold_unit']),(250000000000,'nm2'))
        self.assertEqual(row['metadata']['description_threshold_hint_nm'],30000000)


if __name__=='__main__':
    unittest.main()
