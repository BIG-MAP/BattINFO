"""Regenerate the BattINFO Converter version-matrix fixtures.

Converts a representative spread of the BattInfoConverter tool's *filled* Excel
templates into JSON-LD and writes them under
``tests/fixtures/interop/converter-versions/``. Those committed fixtures are what
``tests/test_converter_version_matrix.py`` imports — so this script is only
needed when refreshing them (e.g. a new converter release).

It depends on the BattInfoConverter source tree, which is NOT a BattINFO
dependency. Point ``--converter-root`` at a checkout and run::

    uv run --with simplejson python scripts/generate_converter_version_fixtures.py \
        --converter-root "C:/.../battery-genome/BattInfoConverter"

The chosen templates span the tool's history and, critically, both component
holders: ``hasConstituent`` (<= v1.1.11) and ``hasComponent`` (>= v1.1.15).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# (version, filled-template filename under "Excel for reference/")
TEMPLATES = [
    ("1.0.0", "241125_Battery2030+_CoinCellBattery_Schema_Ontologized_1.0.0_filled.xlsx"),
    ("1.1.2", "250515_241125_Battery2030+_CoinCellBattery_Schema_Ontologized_1.1.2_filled.xlsx"),
    ("1.1.8", "250515_241125_Battery2030+_CoinCellBattery_Schema_Ontologized_1.1.8_filled.xlsx"),
    ("1.1.11", "BattINFO_converter_standard_Excel_version_1.1.11_filled.xlsx"),
    ("1.1.15", "BattINFO_converter_standard_Excel_version_1.1.15_filled.xlsx"),
    ("1.1.17", "BattINFO_converter_standard_Excel_version_1.1.17_filled.xlsx"),
]

OUT_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "interop" / "converter-versions"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--converter-root", required=True, type=Path,
                        help="Path to a BattInfoConverter checkout.")
    args = parser.parse_args()

    src = args.converter_root / "src"
    excel_dir = args.converter_root / "Excel for reference"
    if not src.is_dir() or not excel_dir.is_dir():
        parser.error(f"not a BattInfoConverter checkout: {args.converter_root}")
    sys.path.insert(0, str(src))
    from battinfoconverter_backend import convert_excel_to_jsonld  # noqa: PLC0415

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for version, filename in TEMPLATES:
        template = excel_dir / filename
        if not template.exists():
            print(f"!! v{version}: missing {filename}", file=sys.stderr)
            continue
        jsonld = convert_excel_to_jsonld(template, validate=False)
        dst = OUT_DIR / f"converter-v{version}.coincell.jsonld"
        dst.write_text(json.dumps(jsonld, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        holder = "hasComponent" if "hasComponent" in jsonld else "hasConstituent"
        print(f"v{version:7s} {holder:14s} -> {dst.relative_to(OUT_DIR.parents[3])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
