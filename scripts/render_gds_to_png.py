#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-render GDS files to PNG images through KLayout."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        help="GDS files or directories containing GDS files.",
    )
    parser.add_argument(
        "--out-dir",
        default="artifacts/rendered_pngs",
        help="Output root for rendered PNGs.",
    )
    parser.add_argument(
        "--root",
        help="Optional base directory for preserving relative paths under --out-dir.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1600,
        help="PNG width in pixels.",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=1600,
        help="PNG height in pixels.",
    )
    parser.add_argument(
        "--klayout-bin",
        default="klayout",
        help="KLayout executable.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Render at most this many files after discovery. 0 means no limit.",
    )
    parser.add_argument(
        "--flat",
        action="store_true",
        help="Do not preserve source directory structure under --out-dir.",
    )
    parser.add_argument(
        "--flat-name-mode",
        choices=["stem", "relative", "rulecase"],
        default="stem",
        help="Naming strategy when --flat is used.",
    )
    parser.add_argument(
        "--selection",
        choices=["all", "one-per-rule"],
        default="all",
        help="Render every discovered GDS or choose one representative GDS per rule.",
    )
    parser.add_argument(
        "--manifest",
        help="Optional CSV manifest path recording source-to-image mapping.",
    )
    parser.add_argument(
        "--editable",
        action="store_true",
        help="Create editable standalone views in KLayout.",
    )
    return parser.parse_args()


def discover_gds(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found.extend(sorted(p for p in path.rglob("*.gds") if p.is_file()))
            continue
        if path.is_file() and path.suffix.lower() == ".gds":
            found.append(path)
            continue
        raise FileNotFoundError(f"Input path not found or not a GDS file: {path}")
    return found


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        ordered.append(resolved)
    return ordered


def sanitize_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._") or "render"


def rule_info_for(source: Path) -> tuple[str | None, str]:
    parts = source.parts
    if "rules" in parts:
        idx = parts.index("rules")
        if idx + 1 < len(parts):
            return parts[idx + 1], source.stem
    return None, source.stem


def select_sources(sources: list[Path], mode: str) -> list[Path]:
    if mode == "all":
        return sources

    grouped: dict[str, list[Path]] = {}
    for source in sources:
        rule_id, _case_id = rule_info_for(source)
        key = rule_id or str(source)
        grouped.setdefault(key, []).append(source)

    selected: list[Path] = []
    for _key, group in sorted(grouped.items()):
        ordered = sorted(group)
        preferred = next((p for p in ordered if "bad" in p.stem.lower()), None)
        if preferred is None:
            preferred = next((p for p in ordered if "good" in p.stem.lower()), None)
        selected.append(preferred or ordered[0])
    return selected


def output_path_for(
    source: Path,
    out_dir: Path,
    root: Path | None,
    flat: bool,
    flat_name_mode: str,
) -> Path:
    if flat:
        if flat_name_mode == "rulecase":
            rule_id, case_id = rule_info_for(source)
            if rule_id:
                return out_dir / f"{sanitize_filename(rule_id)}__{sanitize_filename(case_id)}.png"
        if flat_name_mode == "relative" and root is not None:
            try:
                rel = source.relative_to(root).with_suffix("")
            except ValueError:
                pass
            else:
                flat_name = "__".join(rel.parts)
                return out_dir / f"{sanitize_filename(flat_name)}.png"
        return out_dir / f"{sanitize_filename(source.stem)}.png"
    if root is not None:
        try:
            rel = source.relative_to(root)
        except ValueError:
            rel = source.name
        else:
            rel = rel.with_suffix(".png")
        return out_dir / rel
    return out_dir / f"{source.stem}.png"


def render_one(
    source: Path,
    target: Path,
    klayout_bin: str,
    ruby_script: Path,
    width: int,
    height: int,
    editable: bool,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    cmd = [
        klayout_bin,
        "-z",
        "-nc",
        "-rx",
        "-r",
        str(ruby_script),
        "-rd",
        f"input_gds={source}",
        "-rd",
        f"output_png={target}",
        "-rd",
        f"width={width}",
        "-rd",
        f"height={height}",
        "-rd",
        f"editable={'true' if editable else 'false'}",
    ]
    res = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if res.returncode != 0:
        raise RuntimeError(
            f"Failed to render {source} -> {target}\n"
            f"stdout:\n{res.stdout}\n"
            f"stderr:\n{res.stderr}"
        )


def write_manifest(manifest_path: Path, rows: list[dict[str, str]]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["rule_id", "case_id", "source_gds", "output_png"],
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    if not args.inputs:
        print("No GDS inputs provided.", file=sys.stderr)
        return 2

    script_path = Path(__file__).resolve().with_name("klayout_render_gds.rb")
    out_dir = Path(args.out_dir).resolve()
    root = Path(args.root).resolve() if args.root else None

    sources = unique_paths(discover_gds(args.inputs))
    sources = select_sources(sources, args.selection)
    if args.limit > 0:
        sources = sources[: args.limit]
    if not sources:
        print("No GDS files found.", file=sys.stderr)
        return 1

    rendered = 0
    manifest_rows: list[dict[str, str]] = []
    for source in sources:
        target = output_path_for(source, out_dir, root, args.flat, args.flat_name_mode)
        render_one(
            source=source,
            target=target,
            klayout_bin=args.klayout_bin,
            ruby_script=script_path,
            width=args.width,
            height=args.height,
            editable=args.editable,
        )
        rule_id, case_id = rule_info_for(source)
        manifest_rows.append(
            {
                "rule_id": rule_id or "",
                "case_id": case_id,
                "source_gds": str(source),
                "output_png": str(target),
            }
        )
        rendered += 1
        print(f"rendered {source} -> {target}")

    if args.manifest:
        write_manifest(Path(args.manifest).resolve(), manifest_rows)
    print(f"Rendered {rendered} file(s) into {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
