from __future__ import annotations

import argparse
from pathlib import Path

from autodrc.casegen import (
    generate_cases_for_rule,
    write_cases,
)
from autodrc.rules import parse_rule_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate baseline GOOD/BAD/ILLEGAL LPL cases for DRC rules."
    )
    parser.add_argument("--rule-text", help="Natural language rule text")
    parser.add_argument(
        "--rule-type",
        choices=["min_width", "min_spacing", "min_density", "poly_endcap"],
        help="Rule type when --rule-text is not provided",
    )
    parser.add_argument("--layer", default="met1", help="Layer name")
    parser.add_argument("--min-width-nm", type=int, help="Minimum width threshold (nm)")
    parser.add_argument("--min-spacing-nm", type=int, help="Minimum spacing threshold (nm)")
    parser.add_argument(
        "--min-density-bps",
        type=int,
        help="Minimum density threshold (basis points, 3000=30%%)",
    )
    parser.add_argument("--endcap-nm", type=int, help="Minimum poly endcap threshold (nm)")
    parser.add_argument("--delta-nm", type=int, default=20, help="Margin from threshold")
    parser.add_argument(
        "--tech-name",
        default="sky130",
        choices=["sky130", "ihp_sg13g2"],
        help="Technology-specific layer/context rules to use",
    )
    parser.add_argument("--out-dir", default="data/seed_cases", help="Output directory")
    parser.add_argument("--prefix", default="seed", help="Output file prefix")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.rule_text:
        parsed = parse_rule_text(args.rule_text, default_layer=args.layer)
        rule_type = parsed.rule_type
        layer = parsed.layer
        threshold = parsed.threshold_nm
    else:
        if not args.rule_type:
            raise SystemExit("Either --rule-text or --rule-type is required")
        rule_type = args.rule_type
        layer = args.layer
        if rule_type == "min_width":
            if args.min_width_nm is None:
                raise SystemExit("--min-width-nm is required for rule-type=min_width")
            threshold = args.min_width_nm
        elif rule_type == "min_spacing":
            if args.min_spacing_nm is None:
                raise SystemExit("--min-spacing-nm is required for rule-type=min_spacing")
            threshold = args.min_spacing_nm
        elif rule_type == "min_density":
            if args.min_density_bps is None:
                raise SystemExit("--min-density-bps is required for rule-type=min_density")
            threshold = args.min_density_bps
        else:
            if args.endcap_nm is None:
                raise SystemExit("--endcap-nm is required for rule-type=poly_endcap")
            threshold = args.endcap_nm

    cases = generate_cases_for_rule(
        rule_type=rule_type,
        layer=layer,
        threshold_nm=threshold,
        delta_nm=args.delta_nm,
        tech_name=args.tech_name,
    )

    out_paths = write_cases(cases, Path(args.out_dir), prefix=args.prefix)
    print(f"Generated {len(out_paths)} case files:")
    for path in out_paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
