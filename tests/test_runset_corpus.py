from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autodrc.runset_corpus import parse_runset_outputs, to_pretrain_examples


class RunsetCorpusTests(unittest.TestCase):
    def test_parse_runset_outputs(self) -> None:
        text = """
m1.width(0.14).output("m1.1", "m1.1 : min. m1 width : 0.14um")
li.width(0.14).output("li.8", "li.8 : min. li core width : 0.14um")
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.drc"
            p.write_text(text, encoding="utf-8")
            rows = parse_runset_outputs(p)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].rule_id, "m1.1")
        self.assertEqual(rows[0].threshold_nm, 140)
        self.assertEqual(rows[0].layer_hint, "met1")

    def test_parse_runset_outputs_multiline_and_skip_comments(self) -> None:
        text = """
# m1.width(0.14).output("m1.1", "m1.1 : min. m1 width : 0.14um")
m1
  .space(0.14, euclidian)
  .output(
    "m1.2",
    "m1.2 : min. m1 spacing : 0.14um"
  )
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.drc"
            p.write_text(text, encoding="utf-8")
            rows = parse_runset_outputs(p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].rule_id, "m1.2")
        self.assertEqual(rows[0].threshold_nm, 140)

    def test_pretrain_examples(self) -> None:
        text = 'm1.width(0.14).output("m1.1", "m1.1 : min. m1 width : 0.14um")\n'
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.drc"
            p.write_text(text, encoding="utf-8")
            rows = parse_runset_outputs(p)
        examples = to_pretrain_examples(rows)
        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0]["task"], "rule_to_runset")

    def test_parse_runset_outputs_supports_ihp_single_quotes_and_unitless_threshold(self) -> None:
        text = """
acta_l1.output('Act.a', "5.5. Act.a : Min. Activ width : #{act_a_value} µm")
end.().output("NW.a", "Min. NWell width = 0.62")
"""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sg13g2_maximal.drc"
            p.write_text(text, encoding="utf-8")
            rows = parse_runset_outputs(p)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].rule_id, "Act.a")
        self.assertEqual(rows[0].layer_hint, "activ")
        self.assertIsNone(rows[0].threshold_nm)
        self.assertEqual(rows[1].rule_id, "NW.a")
        self.assertEqual(rows[1].layer_hint, "nwell")
        self.assertEqual(rows[1].threshold_nm, 620)

    def test_parse_runset_outputs_sky130_does_not_adopt_ihp_prefixes(self) -> None:
        text = 'acta_l1.output("Act.a", "Min. Activ width = 0.62")\n'
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.drc"
            p.write_text(text, encoding="utf-8")
            rows = parse_runset_outputs(p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].layer_hint, "unknown")

    def test_parse_runset_outputs_ihp_contbar_stays_contbar(self) -> None:
        text = 'cntb_a1.output("CntB.a1", "Min. ContBar length = 0.34")\n'
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "sg13g2_maximal.drc"
            p.write_text(text, encoding="utf-8")
            rows = parse_runset_outputs(p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].layer_hint, "contbar")


if __name__ == "__main__":
    unittest.main()
