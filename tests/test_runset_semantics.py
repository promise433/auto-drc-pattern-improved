from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autodrc.runset_semantics import parse_runset_blocks, parse_runset_output_semantics


class RunsetSemanticsTests(unittest.TestCase):
    def test_parse_semantics_extracts_expression_and_context(self) -> None:
        text = """
if feol
  base = poly.interacting(diff)
  base.width(0.14).output("poly.1", "poly.1 : min. poly width : 0.14um")
end
met1.space(0.14).output("m1.2", "m1.2 : min. m1 spacing : 0.14um")
"""
        with tempfile.TemporaryDirectory() as tmp:
            runset = Path(tmp) / "x.drc"
            runset.write_text(text, encoding="utf-8")
            rows = parse_runset_output_semantics(runset)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].rule_id, "poly.1")
        self.assertIn("base.width(0.14)", rows[0].expression)
        self.assertIn("if feol", rows[0].context_stack)
        self.assertEqual(rows[0].required_defines, ("feol=true",))
        self.assertTrue(rows[0].block_path)

        self.assertEqual(rows[1].rule_id, "m1.2")
        self.assertIn("met1.space(0.14)", rows[1].expression)
        self.assertEqual(rows[1].context_stack, tuple())

    def test_parse_semantics_extracts_upstream_dependency_chain(self) -> None:
        text = """
seed = met1
derived = seed.sized(10.nm)
guarded = derived.not_interacting(via)
guarded.output("m1.x", "m1.x : floating met1, must interact with via1")
"""
        with tempfile.TemporaryDirectory() as tmp:
            runset = Path(tmp) / "x.drc"
            runset.write_text(text, encoding="utf-8")
            rows = parse_runset_output_semantics(runset)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.rule_id, "m1.x")
        self.assertEqual(row.expression_refs, ("guarded",))
        self.assertEqual(row.upstream_vars, ("seed", "derived", "guarded"))
        self.assertTrue(any("L2:seed = met1" in item for item in row.upstream_assignments))
        self.assertTrue(any("L3:derived = seed.sized(10.nm)" in item for item in row.upstream_assignments))
        self.assertTrue(any("L4:guarded = derived.not_interacting(via)" in item for item in row.upstream_assignments))
        self.assertEqual(row.unresolved_refs, tuple())

    def test_parse_semantics_reports_unresolved_upstream_refs(self) -> None:
        text = """
x = y.sized(10.nm)
y = met1
x.output("m1.y", "m1.y : demo rule")
"""
        with tempfile.TemporaryDirectory() as tmp:
            runset = Path(tmp) / "x.drc"
            runset.write_text(text, encoding="utf-8")
            rows = parse_runset_output_semantics(runset)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.expression_refs, ("x",))
        self.assertEqual(row.unresolved_refs, ("y",))

    def test_parse_semantics_multiline_output(self) -> None:
        text = """
if beol
  m2
    .space(0.28)
    .output(
      "m2.2",
      "m2.2 : min. m2 spacing : 0.28um"
    )
end
"""
        with tempfile.TemporaryDirectory() as tmp:
            runset = Path(tmp) / "x.drc"
            runset.write_text(text, encoding="utf-8")
            rows = parse_runset_output_semantics(runset)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].rule_id, "m2.2")
        self.assertIn(".space(0.28)", rows[0].expression)
        self.assertIn("if beol", rows[0].context_stack)
        self.assertEqual(rows[0].required_defines, ("beol=true",))

    def test_parse_blocks_builds_parent_child_graph(self) -> None:
        text = """
if FEOL
  if SRAM_EXCLUDE
    m1.width(0.14).output("m1.1", "m1.1 : min. m1 width : 0.14um")
  else
    m1.space(0.14).output("m1.2", "m1.2 : min. m1 spacing : 0.14um")
  end
end
"""
        with tempfile.TemporaryDirectory() as tmp:
            runset = Path(tmp) / "x.drc"
            runset.write_text(text, encoding="utf-8")
            blocks = parse_runset_blocks(runset)

        self.assertGreaterEqual(len(blocks), 2)
        top = blocks[0]
        child = blocks[1]
        self.assertEqual(top.parent_block_id, None)
        self.assertEqual(child.parent_block_id, top.block_id)
        self.assertIn("if FEOL", top.header)
        self.assertIn("if SRAM_EXCLUDE", child.header)
        self.assertGreaterEqual(child.end_line, child.start_line)


if __name__ == "__main__":
    unittest.main()
