from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autodrc.tech import detect_tech_name, normalize_tech_name
from autodrc.pipeline import run_full_pipeline
from autodrc.generalization import evaluate_generalization
from autodrc.closed_loop import run_closed_loop
from autodrc.runset_coverage import _augment_layer_map_with_aliases


class TechnologyBoundaryTests(unittest.TestCase):
    def test_unknown_technology_does_not_select_sky(self):
        self.assertEqual(normalize_tech_name(None), 'sky130')
        self.assertEqual(normalize_tech_name('ihp'), 'ihp_sg13g2')
        with self.assertRaises(ValueError):
            normalize_tech_name('ihp_typo')

    def test_renamed_ihp_deck_and_conflicting_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'renamed.drc'
            path.write_text('TopMetal1 = source.polygons("126/0")')
            self.assertEqual(detect_tech_name(path), 'ihp_sg13g2')
            conflict = Path(tmp)/'sky130.drc'
            conflict.write_text(path.read_text())
            with self.assertRaises(ValueError):
                detect_tech_name(conflict)

    def test_ihp_pipeline_rejects_incomplete_deck_before_sky_drc(self):
        with tempfile.TemporaryDirectory() as tmp, patch('autodrc.pipeline.run_closed_loop') as loop:
            path = Path(tmp)/'sg13g2.drc'
            path.write_text('# IHP-SG13G2')
            out = Path(tmp)/'output'
            with self.assertRaisesRegex(ValueError, "Unknown IHP output"):
                run_full_pipeline(out_root=out, runset_path=path)
            with self.assertRaises(NotImplementedError):
                evaluate_generalization(out_dir=out, tech_name='ihp')
            self.assertFalse(out.exists())
            loop.assert_not_called()

    def test_ihp_requires_target_and_nanometre_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'sg13g2.drc'
            path.write_text('# IHP-SG13G2')
            options = dict(rule_type='min_width', layer='activ', threshold_nm=150,
                           runset_path=path, out_dir=Path(tmp)/'output')
            with self.assertRaisesRegex(ValueError, 'explicit target'):
                run_closed_loop(**options)
            with self.assertRaisesRegex(ValueError, 'nanometres'):
                run_closed_loop(**options, dbu=0.005, target_categories=['Act.a'])

    def test_conflicting_layer_alias_is_not_silently_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'layers.json'
            path.write_text('{"topmetal1": [20, 0]}')
            with self.assertRaises(ValueError):
                _augment_layer_map_with_aliases(path, {'topmetal1': (126, 0)})
            self.assertEqual(path.read_text(), '{"topmetal1": [20, 0]}')

    def test_ihp_functional_workflow_rejects_sky_before_outputs(self):
        from autodrc.ihp_workflow import run_ihp_workflow
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sky130.drc';path.write_text('# sky130')
            out=Path(tmp)/'output'
            with self.assertRaises(ValueError):
                run_ihp_workflow(runset_path=path,out_root=out)
            self.assertFalse(out.exists())

    def test_ihp_functional_workflow_rejects_unknown_task_before_outputs(self):
        from autodrc.ihp_workflow import run_ihp_workflow
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sg13g2.drc';path.write_text('# IHP-SG13G2')
            out=Path(tmp)/'output'
            with self.assertRaisesRegex(ValueError,'Unknown IHP output'):
                run_ihp_workflow(runset_path=path,out_root=out,rule_ids=('m1.1',))
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
