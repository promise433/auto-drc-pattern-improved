from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autodrc.pipeline import run_full_pipeline
from autodrc.specs import KNOWN_TASKS


class PipelineTests(unittest.TestCase):
    def test_selected_runset_is_forwarded_to_all_known_rule_loops(self):
        with tempfile.TemporaryDirectory() as tmp:
            runset = Path(tmp) / 'selected.drc'
            runset.write_text('m1.width(0.14).output("m1.1", "min. m1 width : 0.14um")')
            with patch('autodrc.pipeline.run_closed_loop', return_value=dict(
                converged=True, iterations_run=1, target_categories=['m1.1'])) as loop:
                result = run_full_pipeline(out_root=Path(tmp)/'output', runset_path=runset,
                                           run_corner_mining=False)
            self.assertEqual(loop.call_count, len(KNOWN_TASKS))
            self.assertTrue(all(c.kwargs['runset_path'] == runset for c in loop.call_args_list))
            self.assertEqual(result['runset_path'], str(runset))

    def test_ihp_pipeline_dispatches_only_to_ihp_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            runset=Path(tmp)/'sg13g2.drc';runset.write_text('# IHP-SG13G2')
            out=Path(tmp)/'output'
            def workflow(**kwargs):
                kwargs['out_root'].mkdir()
                return dict(tech_name='ihp_sg13g2',generator=kwargs['generator'])
            with patch('autodrc.ihp_workflow.run_ihp_workflow',side_effect=workflow) as ihp, patch('autodrc.pipeline.run_closed_loop') as sky:
                result=run_full_pipeline(out_root=out,runset_path=runset,generator='llm',llm_model='local',
                    run_corner_mining=False,run_known_drc_batch=False)
            sky.assert_not_called()
            self.assertEqual(result['tech_name'],'ihp_sg13g2')
            self.assertEqual(ihp.call_args.kwargs['corner_deltas_nm'],())
            self.assertFalse(ihp.call_args.kwargs['run_selected_drc'])
            self.assertEqual(ihp.call_args.kwargs['llm_model'],'local')


if __name__ == '__main__':
    unittest.main()
