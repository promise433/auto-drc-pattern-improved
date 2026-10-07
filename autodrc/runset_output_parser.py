from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunsetOutputCall:
    rule_id: str
    description: str
    start: int


def _skip_ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _parse_quoted_string(text: str, pos: int) -> tuple[str, int] | None:
    if pos >= len(text) or text[pos] not in {'"', "'"}:
        return None

    quote = text[pos]
    pos += 1
    out: list[str] = []
    escaped = False

    while pos < len(text):
        ch = text[pos]
        if escaped:
            out.append(ch)
            escaped = False
            pos += 1
            continue
        if ch == "\\":
            out.append(ch)
            escaped = True
            pos += 1
            continue
        if ch == quote:
            return ("".join(out), pos + 1)
        out.append(ch)
        pos += 1
    return None


def find_output_calls(cleaned_text: str) -> list[RunsetOutputCall]:
    rows: list[RunsetOutputCall] = []
    needle = ".output("
    pos = 0

    while True:
        start = cleaned_text.find(needle, pos)
        if start < 0:
            break

        cursor = _skip_ws(cleaned_text, start + len(needle))
        rule_parsed = _parse_quoted_string(cleaned_text, cursor)
        if rule_parsed is None:
            pos = start + 1
            continue
        rule_id, cursor = rule_parsed

        cursor = _skip_ws(cleaned_text, cursor)
        if cursor >= len(cleaned_text) or cleaned_text[cursor] != ",":
            pos = start + 1
            continue

        cursor = _skip_ws(cleaned_text, cursor + 1)
        desc_parsed = _parse_quoted_string(cleaned_text, cursor)
        if desc_parsed is None:
            pos = start + 1
            continue
        description, _ = desc_parsed

        rows.append(
            RunsetOutputCall(
                rule_id=rule_id,
                description=description,
                start=start,
            )
        )
        pos = start + 1

    return rows
