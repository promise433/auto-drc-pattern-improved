from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any

from autodrc.runset_output_parser import find_output_calls
_OPEN_BLOCK_RE = re.compile(
    r"^\s*(if|unless|while|until|case|for|begin)\b.*$|^\s*.*\bdo\b\s*(?:\|[^|]*\|)?\s*$",
    re.IGNORECASE,
)
_CLOSE_BLOCK_RE = re.compile(r"^\s*end\b", re.IGNORECASE)
_BRANCH_RE = re.compile(r"^\s*(elsif|else|when)\b.*$", re.IGNORECASE)
_ASSIGN_RE = re.compile(
    r"^\s*(?P<lhs>[$]?[A-Za-z_][A-Za-z0-9_]*)\s*(?P<op>\|\|=|\+=|-=|\*=|/=|%=|=(?!=))\s*(?P<rhs>.*?)\s*$"
)
_TOKEN_RE = re.compile(r"[$]?[A-Za-z_][A-Za-z0-9_]*")
_RUBY_KEYWORDS = {
    "if",
    "unless",
    "while",
    "until",
    "case",
    "for",
    "begin",
    "do",
    "elsif",
    "else",
    "when",
    "true",
    "false",
    "and",
    "or",
    "not",
    "end",
    "nil",
    "then",
    "in",
}


@dataclass(frozen=True)
class RunsetBlock:
    block_id: str
    parent_block_id: str | None
    header: str
    start_line: int
    end_line: int
    depth: int
    condition_vars: tuple[str, ...]
    body_excerpt: str


@dataclass(frozen=True)
class RunsetAssignment:
    lhs: str
    op: str
    rhs: str
    line_no: int


@dataclass(frozen=True)
class RunsetOutputSemantic:
    rule_id: str
    description: str
    line_no: int
    source_file: str
    expression: str
    context_stack: tuple[str, ...]
    block_path: tuple[str, ...]
    required_defines: tuple[str, ...]
    expression_refs: tuple[str, ...]
    upstream_vars: tuple[str, ...]
    upstream_assignments: tuple[str, ...]
    unresolved_refs: tuple[str, ...]
    anonymous_body: str = ""


def _strip_full_line_comments(text: str) -> str:
    lines = text.splitlines()
    cleaned = [("" if line.lstrip().startswith("#") else line) for line in lines]
    return "\n".join(cleaned)


def _strip_inline_comment(line: str) -> str:
    quote: str | None = None
    escaped = False
    for idx, ch in enumerate(line):
        if quote is not None:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == quote:
                quote = None
            continue
        if ch in {"'", '"'}:
            quote = ch
            continue
        if ch == "#":
            return line[:idx]
    return line


def _extract_condition_vars(header: str) -> tuple[str, ...]:
    tokens = re.findall(r"[$]?[A-Za-z_][A-Za-z0-9_]*", header)
    out: list[str] = []
    for token in tokens:
        low = token.lower().lstrip("$")
        if low in {"if", "unless", "while", "until", "case", "for", "begin", "do", "elsif", "else", "when", "true", "false", "and", "or", "not", "end"}:
            continue
        if low not in out:
            out.append(low)
    return tuple(out)


def _extract_assignments(cleaned_text: str) -> tuple[list[RunsetAssignment], dict[str, list[RunsetAssignment]], set[str]]:
    assignments: list[RunsetAssignment] = []
    lines = [_strip_inline_comment(line).strip() for line in cleaned_text.splitlines()]
    index = 0
    while index < len(lines):
        lineno = index + 1
        line = lines[index]
        index += 1
        if not line:
            continue
        m = _ASSIGN_RE.match(line)
        if not m:
            continue
        lhs = m.group("lhs").lstrip("$").lower()
        parts = [m.group("rhs").strip()]
        while index < len(lines):
            rhs_so_far = " ".join(parts)
            unquoted = re.sub(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*' ''', "", rhs_so_far, flags=re.VERBOSE)
            balance = sum(unquoted.count(x) - unquoted.count(y) for x, y in (("(", ")"), ("[", "]"), ("{", "}")))
            pending = not rhs_so_far.strip() or balance > 0 or bool(re.search(r"(?:[|&+*/,-]|\\)\s*$", unquoted))
            next_line = lines[index]
            if not pending and not next_line.startswith("."):
                break
            if not next_line:
                index += 1
                continue
            if _ASSIGN_RE.match(next_line) or _CLOSE_BLOCK_RE.match(next_line):
                break
            parts.append(next_line)
            index += 1
        rhs = re.sub(r"\s+", " ", " ".join(parts)).strip()
        if not rhs:
            continue
        assignments.append(
            RunsetAssignment(
                lhs=lhs,
                op=m.group("op"),
                rhs=rhs,
                line_no=lineno,
            )
        )

    by_var: dict[str, list[RunsetAssignment]] = {}
    for row in assignments:
        by_var.setdefault(row.lhs, []).append(row)
    for rows in by_var.values():
        rows.sort(key=lambda item: item.line_no)
    candidate_vars = set(by_var.keys())
    return assignments, by_var, candidate_vars


def _extract_refs(text: str, candidate_vars: set[str]) -> tuple[str, ...]:
    refs: list[str] = []
    for token in _TOKEN_RE.findall(text):
        low = token.lower().lstrip("$")
        if low in _RUBY_KEYWORDS:
            continue
        if low not in candidate_vars:
            continue
        if low not in refs:
            refs.append(low)
    return tuple(refs)


def _latest_assignment_before(
    assignments_by_var: dict[str, list[RunsetAssignment]],
    var: str,
    before_line: int,
) -> RunsetAssignment | None:
    rows = assignments_by_var.get(var)
    if not rows:
        return None
    for row in reversed(rows):
        if row.line_no < before_line:
            return row
    return None


def _resolve_upstream_dependencies(
    *,
    expression: str,
    output_line: int,
    assignments_by_var: dict[str, list[RunsetAssignment]],
    candidate_vars: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    expression_refs = _extract_refs(expression, candidate_vars)
    unresolved: list[str] = []
    seen_queries: set[tuple[str, int]] = set()
    seen_assignments: set[tuple[str, int]] = set()
    ordered_assignments: list[RunsetAssignment] = []
    stack: list[tuple[str, int]] = [(ref, output_line) for ref in reversed(expression_refs)]

    while stack:
        var, before_line = stack.pop()
        query = (var, before_line)
        if query in seen_queries:
            continue
        seen_queries.add(query)

        row = _latest_assignment_before(assignments_by_var, var, before_line)
        if row is None:
            if var not in unresolved:
                unresolved.append(var)
            continue

        key = (row.lhs, row.line_no)
        if key not in seen_assignments:
            seen_assignments.add(key)
            ordered_assignments.append(row)

        rhs_refs = _extract_refs(row.rhs, candidate_vars)
        if row.op != "=" and row.lhs not in rhs_refs:
            rhs_refs += (row.lhs,)
        for ref in reversed(rhs_refs):
            stack.append((ref, row.line_no))

    ordered_assignments.sort(key=lambda item: item.line_no)
    upstream_vars: list[str] = []
    upstream_assignment_rows: list[str] = []
    for row in ordered_assignments:
        if row.lhs not in upstream_vars:
            upstream_vars.append(row.lhs)
        upstream_assignment_rows.append(f"L{row.line_no}:{row.lhs} {row.op} {row.rhs}")

    return (
        expression_refs,
        tuple(upstream_vars),
        tuple(upstream_assignment_rows),
        tuple(unresolved),
    )


def _infer_required_defines(context_stack: tuple[str, ...]) -> tuple[str, ...]:
    context = " | ".join(context_stack).lower()
    out: list[str] = []
    if "if floating_met" in context:
        out.append("floating_met=true")
    if "if seal" in context:
        out.append("seal=true")
    if "if sram_exclude" in context:
        out.append("sram_exclude=true")
    if "if offgrid" in context:
        out.append("offgrid=true")
    if "if feol" in context:
        out.append("feol=true")
    if "if beol" in context:
        out.append("beol=true")
    return tuple(out)


def _scan_structure(
    cleaned_text: str,
) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]], list[RunsetBlock]]:
    lines = cleaned_text.splitlines()
    # 1-based indexing: index 0 is unused sentinel.
    contexts: list[tuple[str, ...]] = [tuple()]
    block_paths: list[tuple[str, ...]] = [tuple()]
    context_stack: list[str] = []
    block_id_stack: list[str] = []
    open_blocks: dict[str, dict[str, Any]] = {}
    block_order: list[str] = []
    next_id = 1

    for lineno, line in enumerate(lines, start=1):
        contexts.append(tuple(context_stack))
        block_paths.append(tuple(block_id_stack))
        stripped = line.strip()
        if block_id_stack:
            bid = block_id_stack[-1]
            body = open_blocks[bid]["body_lines"]
            if stripped:
                body.append(stripped)
        if not stripped:
            continue
        if _CLOSE_BLOCK_RE.match(stripped):
            if block_id_stack:
                bid = block_id_stack.pop()
                context_stack.pop()
                open_blocks[bid]["end_line"] = lineno
            continue
        if _BRANCH_RE.match(stripped):
            if context_stack:
                context_stack[-1] = stripped
            continue
        if _OPEN_BLOCK_RE.match(stripped):
            block_id = f"b{next_id:04d}"
            next_id += 1
            parent_block_id = block_id_stack[-1] if block_id_stack else None
            block_id_stack.append(block_id)
            context_stack.append(stripped)
            open_blocks[block_id] = {
                "block_id": block_id,
                "parent_block_id": parent_block_id,
                "header": stripped,
                "start_line": lineno,
                "end_line": len(lines),
                "depth": len(block_id_stack) - 1,
                "condition_vars": _extract_condition_vars(stripped),
                "body_lines": [],
            }
            block_order.append(block_id)

    blocks: list[RunsetBlock] = []
    for block_id in block_order:
        row = open_blocks[block_id]
        body_lines = row["body_lines"]
        excerpt = " ".join(body_lines[:16])
        excerpt = re.sub(r"\s+", " ", excerpt).strip()
        blocks.append(
            RunsetBlock(
                block_id=row["block_id"],
                parent_block_id=row["parent_block_id"],
                header=row["header"],
                start_line=int(row["start_line"]),
                end_line=int(row["end_line"]),
                depth=int(row["depth"]),
                condition_vars=tuple(row["condition_vars"]),
                body_excerpt=excerpt,
            )
        )
    return contexts, block_paths, blocks


def _extract_expression(cleaned_text: str, output_start: int) -> str:
    prefix = cleaned_text[:output_start]
    masked = re.sub(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*' ''',
                    lambda m: " " * len(m.group()), prefix, flags=re.VERBOSE)
    i = output_start - 1
    depth = 0
    start = 0

    while i >= 0:
        ch = masked[i]
        if ch in ")]}":
            depth += 1
        elif ch in "([{":
            depth = max(0, depth - 1)
        elif ch == "\n" and depth == 0:
            line_start = masked.rfind("\n", 0, i) + 1
            prev_line = masked[line_start:i].strip()
            following = masked[i + 1:].lstrip() or ".output"
            continues = following.startswith(".") or bool(re.search(r"[|&+*/,-]$", prev_line))
            if not continues or _ASSIGN_RE.match(prev_line) or re.match(
                r"^(if|unless|elsif|else|when|end)\b", prev_line, re.IGNORECASE,
            ):
                start = i + 1
                break
        elif ch == ";" and depth == 0:
            start = i+1
            break
        i -= 1

    expr = prefix[start:].strip()
    expr = re.sub(
        r"""(?s)^.*\.output\(\s*(?:"[^"]*"|'[^']*')\s*,\s*(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')\s*\)\s*""",
        "",
        expr,
    )
    return re.sub(r"\s+", " ", expr)


def parse_runset_output_semantics(runset_path: Path) -> list[RunsetOutputSemantic]:
    raw = runset_path.read_text(encoding="utf-8", errors="replace")
    cleaned = _strip_full_line_comments(raw)
    contexts, block_paths, blocks = _scan_structure(cleaned)
    assignments, assignments_by_var, candidate_vars = _extract_assignments(cleaned)
    anonymous_blocks = [block for block in blocks if block.header.lstrip().startswith("->")]
    lines = cleaned.splitlines()

    rows: list[RunsetOutputSemantic] = []
    for item in find_output_calls(cleaned):
        line_no = cleaned.count("\n", 0, item.start) + 1
        context_stack = contexts[line_no] if line_no < len(contexts) else tuple()
        block_path = block_paths[line_no] if line_no < len(block_paths) else tuple()
        expression = _extract_expression(cleaned, item.start)
        anonymous_body = ""
        scoped_assignments = assignments_by_var
        scoped_candidates = candidate_vars
        owner = next((block for block in reversed(anonymous_blocks)
                      if block.start_line < line_no <= block.end_line), None)
        if owner is not None:
            anonymous_body = "\n".join(lines[owner.start_line:owner.end_line - 1])
            # The complete body remains available even when the last expression
            # is a branch/loop rather than a single directly provable predicate.
            if owner.end_line == line_no:
                expression = _extract_expression(anonymous_body, len(anonymous_body))
            else:
                # IHP also outputs each element of an array from inside the
                # anonymous body. Retain the array, rather than a dangling
                # `each { |result| result` receiver.
                expression = re.sub(r"\.each\s*\{\s*\|\s*(\w+)\s*\|\s*\1\s*$", "", expression).strip()
            if expression == "end":
                expression = "-> do " + re.sub(r"\s+", " ", anonymous_body).strip() + " end.()"
            scoped_assignments = {}
            for assignment in assignments:
                scope = next((block for block in anonymous_blocks
                              if block.start_line < assignment.line_no < block.end_line), None)
                if scope is None or scope.block_id == owner.block_id:
                    scoped_assignments.setdefault(assignment.lhs, []).append(assignment)
            scoped_candidates = set(scoped_assignments)
        expression_refs, upstream_vars, upstream_assignments, unresolved_refs = (
            _resolve_upstream_dependencies(
                expression=expression,
                output_line=line_no,
                assignments_by_var=scoped_assignments,
                candidate_vars=scoped_candidates,
            )
        )
        rows.append(
            RunsetOutputSemantic(
                rule_id=item.rule_id,
                description=item.description,
                line_no=line_no,
                source_file=str(runset_path),
                expression=expression,
                context_stack=context_stack,
                block_path=block_path,
                required_defines=_infer_required_defines(context_stack),
                expression_refs=expression_refs,
                upstream_vars=upstream_vars,
                upstream_assignments=upstream_assignments,
                unresolved_refs=unresolved_refs,
                anonymous_body=anonymous_body,
            )
        )
    return rows


def parse_runset_blocks(runset_path: Path) -> list[RunsetBlock]:
    raw = runset_path.read_text(encoding="utf-8", errors="replace")
    cleaned = _strip_full_line_comments(raw)
    _, _, blocks = _scan_structure(cleaned)
    return blocks


def write_semantics_jsonl(path: Path, rows: list[RunsetOutputSemantic]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            payload = asdict(row)
            payload["context_stack"] = list(row.context_stack)
            payload["block_path"] = list(row.block_path)
            payload["required_defines"] = list(row.required_defines)
            payload["expression_refs"] = list(row.expression_refs)
            payload["upstream_vars"] = list(row.upstream_vars)
            payload["upstream_assignments"] = list(row.upstream_assignments)
            payload["unresolved_refs"] = list(row.unresolved_refs)
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_blocks_jsonl(path: Path, rows: list[RunsetBlock]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            payload = asdict(row)
            payload["condition_vars"] = list(row.condition_vars)
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Extract runset output items with expression and block-context semantics."
    )
    p.add_argument("--runset", required=True, help="Path to a DRC runset")
    p.add_argument(
        "--out-jsonl",
        default="artifacts/runset_blocks/outputs_with_context.jsonl",
        help="Output JSONL path",
    )
    p.add_argument(
        "--out-blocks-jsonl",
        default="artifacts/runset_blocks/block_graph.jsonl",
        help="Output block graph JSONL path",
    )
    args = p.parse_args()

    rows = parse_runset_output_semantics(Path(args.runset))
    blocks = parse_runset_blocks(Path(args.runset))
    write_semantics_jsonl(Path(args.out_jsonl), rows)
    write_blocks_jsonl(Path(args.out_blocks_jsonl), blocks)
    print(
        json.dumps(
            {
                "rules_extracted": len(rows),
                "blocks_extracted": len(blocks),
                "out_jsonl": args.out_jsonl,
                "out_blocks_jsonl": args.out_blocks_jsonl,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
