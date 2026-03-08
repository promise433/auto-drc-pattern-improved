from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Iterable


OUTPUT_RE = re.compile(
    r"""\.output\(\s*"(?P<rule_id>[^"]+)"\s*,\s*"(?P<desc>[^"]+)"\s*\)""",
    re.DOTALL,
)
THRESHOLD_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*um")


@dataclass(frozen=True)
class RunsetRule:
    rule_id: str
    description: str
    line_no: int
    threshold_nm: int | None
    layer_hint: str
    source_file: str


def _layer_from_rule_id(rule_id: str, description: str) -> str:
    rid = rule_id.lower()
    desc = description.lower()
    if rid.startswith("modulecut.") or "modulecut" in desc:
        return "modulecut"
    if rid.startswith("difftap.") or " difftap " in desc:
        return "difftap"
    if rid.startswith("licon.") or " licon " in desc:
        return "licon"
    if rid.startswith("ct.") or " mcon " in desc:
        return "mcon"
    if rid.startswith("areaid_re") or "areaid.re" in desc or "areaid_re" in desc:
        return "areaid_re"
    if rid.startswith("m1.") or " m1 " in desc:
        return "met1"
    if rid.startswith("m2.") or " m2 " in desc:
        return "met2"
    if rid.startswith("m3.") or " m3 " in desc:
        return "met3"
    if rid.startswith("m4.") or " m4 " in desc:
        return "met4"
    if rid.startswith("m5.") or " m5 " in desc:
        return "met5"
    if rid.startswith("li.") or " li " in desc:
        return "li1"
    if rid.startswith("poly.") or " poly " in desc:
        return "poly"
    return "unknown"


def _threshold_from_description(description: str) -> int | None:
    m = THRESHOLD_RE.search(description)
    if not m:
        return None
    return int(round(float(m.group("value")) * 1000))


def parse_runset_outputs(runset_path: Path) -> list[RunsetRule]:
    text = runset_path.read_text(encoding="utf-8", errors="replace")
    # Keep line numbers stable by replacing full-line comments with blank lines.
    lines = text.splitlines()
    cleaned_lines = [("" if line.lstrip().startswith("#") else line) for line in lines]
    cleaned = "\n".join(cleaned_lines)
    rows: list[RunsetRule] = []
    for m in OUTPUT_RE.finditer(cleaned):
        rule_id = m.group("rule_id")
        desc = m.group("desc")
        line_no = cleaned.count("\n", 0, m.start()) + 1
        rows.append(
            RunsetRule(
                rule_id=rule_id,
                description=desc,
                line_no=line_no,
                threshold_nm=_threshold_from_description(desc),
                layer_hint=_layer_from_rule_id(rule_id, desc),
                source_file=str(runset_path),
            )
        )
    return rows


def to_pretrain_examples(rows: Iterable[RunsetRule]) -> list[dict[str, object]]:
    examples: list[dict[str, object]] = []
    for row in rows:
        examples.append(
            {
                "task": "rule_to_runset",
                "instruction": "Map natural-language DRC rule to runset target metadata.",
                "input": row.description,
                "output": {
                    "rule_id": row.rule_id,
                    "layer": row.layer_hint,
                    "threshold_nm": row.threshold_nm,
                },
            }
        )
    return examples


def write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Extract SKY130 runset output rules and build Rule-to-Runset corpus."
    )
    p.add_argument("--runset", required=True, help="Path to sky130A_mr.drc")
    p.add_argument(
        "--out-catalog",
        default="data/rule_to_runset/catalog.jsonl",
        help="Output rule catalog JSONL",
    )
    p.add_argument(
        "--out-pretrain",
        default="data/rule_to_runset/pretrain.jsonl",
        help="Output pretrain examples JSONL",
    )
    args = p.parse_args()

    rows = parse_runset_outputs(Path(args.runset))
    write_jsonl(Path(args.out_catalog), (asdict(r) for r in rows))
    write_jsonl(Path(args.out_pretrain), to_pretrain_examples(rows))
    print(
        json.dumps(
            {
                "rules_extracted": len(rows),
                "catalog": args.out_catalog,
                "pretrain": args.out_pretrain,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
