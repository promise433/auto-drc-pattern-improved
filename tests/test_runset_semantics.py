from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from autodrc.runset_semantics import parse_runset_blocks, parse_runset_output_semantics


class RunsetSemanticsTests(unittest.TestCase):
    def test_anonymous_array_output_retains_all_branches_and_local_scope(self) -> None:
        text = '''a = input(1, 0)
b = input(2, 0)
-> (;x) do
  x = a.ext_width(0.1.um)
  [x, b.ext_space(0.2.um)
  ].each { |result| result.output("a.x", "combined") }
end.()
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.drc"
            path.write_text(text)
            row = parse_runset_output_semantics(path)[0]
        self.assertEqual(row.expression, "[x, b.ext_space(0.2.um) ]")
        self.assertEqual(row.expression_refs, ("x", "b"))
        self.assertTrue(any("x = a.ext_width" in value for value in row.upstream_assignments))
        self.assertIn('result.output("a.x"', row.anonymous_body)

    def test_anonymous_output_keeps_predicate_and_cached_upstream(self) -> None:
        text = '''NWell = input(31, 0)
cached = NWell.ext_width(0.62.um)
-> do
  cached.dup
end.().output("NW.a", "width")
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.drc"
            path.write_text(text)
            row = parse_runset_output_semantics(path)[0]
        self.assertEqual(row.expression, "cached.dup")
        self.assertEqual(row.expression_refs, ("cached",))
        self.assertIn("nwell", row.upstream_vars)
        self.assertIn("NWell.ext_width(0.62.um)", row.upstream_assignments[-1])
        self.assertEqual(row.anonymous_body.strip(), "cached.dup")

    def test_anonymous_locals_do_not_leak_between_rules(self) -> None:
        text = '''a = input(1, 0)
b = input(2, 0)
-> (;x) do
  x = a.ext_width(0.1.um)
  x.dup
end.().output("a.x", "width")
-> (;x) do
  b.ext_enclosed(a, 0.2.um)
end.().output("b.x", "enclosure")
-> (;x) do
  x = b.ext_space(0.3.um)
  x.dup
end.().output("b.y", "spacing")
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.drc"
            path.write_text(text)
            rows = parse_runset_output_semantics(path)
        self.assertEqual(rows[1].expression, "b.ext_enclosed(a, 0.2.um)")
        self.assertEqual(rows[2].expression, "x.dup")
        self.assertTrue(any("x = b.ext_space" in value for value in rows[2].upstream_assignments))
        self.assertFalse(any("x = a.ext_width" in value for value in rows[2].upstream_assignments))

    def test_anonymous_nested_branch_preserves_full_body(self) -> None:
        text = '''a = input(1, 0)
-> (;x) do
  x = a.ext_width(0.1.um)
  if $recommended
    x
  else
    a.ext_space(0.2.um)
  end
end.().output("a.x", "conditional")
a.output("a.use", "use")
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.drc"
            path.write_text(text)
            rows = parse_runset_output_semantics(path)
        self.assertIn("if $recommended", rows[0].anonymous_body)
        self.assertIn("a.ext_space(0.2.um)", rows[0].expression)
        self.assertEqual(rows[1].expression, "a")

    def test_output_receiver_excludes_logs_and_previous_multiline_assignment(self) -> None:
        text = '''diff = polygons(65, 20)
areaid_ce = polygons(81, 2)
filtered =
  diff.width(0.15).polygons
    .edges
    .outside_part(areaid_ce)
filtered.output("diff.1", "diff width")
log("END: 65/20 (diff) )")
log("START: 81/10 (moduleCut)")
areaid_mt = polygons(81, 10)
areaid_mt.output("moduleCut.1", "reserved")
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"x.drc"
            path.write_text(text)
            rows = parse_runset_output_semantics(path)
        self.assertEqual(rows[0].expression,"filtered")
        self.assertEqual(rows[1].expression,"areaid_mt")
        self.assertEqual(rows[0].expression_refs,("filtered",))

    def test_output_receiver_keeps_long_parenthesized_and_chained_expression(self) -> None:
        text = 'log("old")\n(\n  m1.space(0.14) +\n  m2.space(0.14)\n)\n' + '\n'.join(
            ' .sized(0)' for _ in range(10)) + '\n .output("m1.x", "demo")\n'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"x.drc"
            path.write_text(text)
            row=parse_runset_output_semantics(path)[0]
        self.assertNotIn("log",row.expression)
        self.assertIn("m1.space(0.14)",row.expression)
        self.assertIn("m2.space(0.14)",row.expression)
        self.assertEqual(row.expression.count(".sized(0)"),10)
    def test_multiline_assignment_resolves_latest_redefinition(self) -> None:
        text = '''seed = poly
error_corners = seed.width(0.1)
via2_edges =
  m2.enclosing(via2, 0.085, projection).second_edges
error_corners =
  via2_edges.width(angle_limit(100.0), 1.dbu)
via2_interact = via2.interacting(error_corners.polygons(1.dbu))
via2_interact.output("via2.5", "via2.5 : adjacent edge enclosure")
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.drc"
            path.write_text(text)
            row = parse_runset_output_semantics(path)[0]
        self.assertTrue(any("L3:via2_edges = m2.enclosing" in x for x in row.upstream_assignments))
        self.assertTrue(any("L5:error_corners = via2_edges.width" in x for x in row.upstream_assignments))
        self.assertFalse(any("L2:error_corners" in x for x in row.upstream_assignments))
        self.assertFalse(any("seed" in x for x in row.upstream_assignments))

    def test_multiline_nested_rhs_and_self_redefinition_keep_previous_value(self) -> None:
        text = '''a = polygons(66, 44)
a = (a.not(
  excluded
)).interacting(poly)
a += tap
a.output("licon.x", "licon.x : test")
'''
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.drc"
            path.write_text(text)
            row = parse_runset_output_semantics(path)[0]
        self.assertEqual(len(row.upstream_assignments), 3)
        self.assertTrue(row.upstream_assignments[0].startswith("L1:a = polygons"))
        self.assertIn("a.not( excluded )", row.upstream_assignments[1])
        self.assertEqual(row.upstream_assignments[2], "L5:a += tap")

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

    def test_parse_semantics_supports_single_quote_output(self) -> None:
        text = """
if FEOL
  acta_l1 = activ_drw.width(act_a_value.um, euclidian)
  acta_l1.output('Act.a', "5.5. Act.a : Min. Activ width : #{act_a_value} µm")
end
"""
        with tempfile.TemporaryDirectory() as tmp:
            runset = Path(tmp) / "x.drc"
            runset.write_text(text, encoding="utf-8")
            rows = parse_runset_output_semantics(runset)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].rule_id, "Act.a")
        self.assertEqual(rows[0].expression, "acta_l1")
        self.assertTrue(
            any("activ_drw.width" in item for item in rows[0].upstream_assignments)
        )
        self.assertIn("if FEOL", rows[0].context_stack)


if __name__ == "__main__":
    unittest.main()
