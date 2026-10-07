from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Iterable

from autodrc.runset_output_parser import find_output_calls
from autodrc.tech import detect_tech_name, normalize_tech_name

THRESHOLD_UM_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?:um|µm)", re.IGNORECASE)
THRESHOLD_INLINE_RE = re.compile(r"=\s*(?P<value>\d+(?:\.\d+)?)\b")
_AREA_HINT_RE = re.compile(r"(?:um\^?2|µm\^?2|um2|µm2|um²|µm²)", re.IGNORECASE)


@dataclass(frozen=True)
class RunsetRule:
    rule_id: str
    description: str
    line_no: int
    threshold_nm: int | None
    layer_hint: str
    source_file: str


def _layer_from_rule_id(rule_id: str, description: str, *, tech_name: str = "sky130") -> str:
    tech = normalize_tech_name(tech_name)
    rid = rule_id.lower()
    desc = description.lower()
    if tech == "ihp_sg13g2":
        ihp_prefix_map = {
            "nw": "nwell",
            "pwb": "pwellblock",
            "nbl": "nbulay",
            "nblb": "nbulay_block",
            "act": "activ",
            "afil": "activ_filler",
            "tgo": "thickgateox",
            "gat": "gatpoly",
            "gfil": "gatpoly_filler",
            "cnt": "cont",
            "cntb": "contbar",
            "psd": "psd",
            "nsd": "nsd",
            "sdiod": "salblock",
        }
        rid_prefix = rid.split(".", 1)[0]
        if rid_prefix in ihp_prefix_map:
            return ihp_prefix_map[rid_prefix]
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
    phrase_map: dict[str, str] = {}
    if tech == "ihp_sg13g2":
        phrase_map.update(
            {
                "nwell": "nwell",
                "pwell:block": "pwellblock",
                "pwell block": "pwellblock",
                "nbulay:block": "nbulay_block",
                "nbulay block": "nbulay_block",
                "nbulay": "nbulay",
                "activ:filler": "activ_filler",
                "activ filler": "activ_filler",
                "activ": "activ",
                "gatpoly:filler": "gatpoly_filler",
                "gatpoly filler": "gatpoly_filler",
                "gatpoly": "gatpoly",
                "contbar": "contbar",
                "cont": "cont",
                "thickgateox": "thickgateox",
                "psd": "psd",
                "nsd": "nsd",
                "salblock": "salblock",
            }
        )
    for token, layer in phrase_map.items():
        if token in desc:
            return layer
    return "unknown"


def _threshold_from_description(description: str) -> int | None:
    m = THRESHOLD_UM_RE.search(description)
    if m:
        return int(round(float(m.group("value")) * 1000))

    if _AREA_HINT_RE.search(description):
        return None

    low = description.lower()
    if not any(
        token in low
        for token in (
            "width",
            "space",
            "spacing",
            "enclosure",
            "extension",
            "overlap",
            "notch",
            "length",
        )
    ):
        return None

    m = THRESHOLD_INLINE_RE.search(description)
    if not m:
        return None
    return int(round(float(m.group("value")) * 1000))


def parse_runset_outputs(runset_path: Path) -> list[RunsetRule]:
    tech_name = detect_tech_name(runset_path)
    text = runset_path.read_text(encoding="utf-8", errors="replace")
    # Keep line numbers stable by replacing full-line comments with blank lines.
    lines = text.splitlines()
    cleaned_lines = [("" if line.lstrip().startswith("#") else line) for line in lines]
    cleaned = "\n".join(cleaned_lines)
    rows: list[RunsetRule] = []
    for item in find_output_calls(cleaned):
        line_no = cleaned.count("\n", 0, item.start) + 1
        rows.append(
            RunsetRule(
                rule_id=item.rule_id,
                description=item.description,
                line_no=line_no,
                threshold_nm=_threshold_from_description(item.description),
                layer_hint=_layer_from_rule_id(
                    item.rule_id,
                    item.description,
                    tech_name=tech_name,
                ),
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
        description="Extract runset output rules and build Rule-to-Runset corpus."
    )
    p.add_argument("--runset", required=True, help="Path to a DRC runset")
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
