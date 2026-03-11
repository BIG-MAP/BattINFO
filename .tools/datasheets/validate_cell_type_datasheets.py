from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.validate.pydantic import validate_json


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate BattINFO cell-type datasheet JSON files.")
    parser.add_argument(
        "--dir",
        type=Path,
        default=ROOT / "assets" / "datasheets" / "cell-types",
        help="Directory containing *.datasheet.json files.",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default="cell-type-datasheet",
        help="Validation profile (default: cell-type-datasheet).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    datasheet_dir = args.dir
    profile = args.profile

    files = sorted(datasheet_dir.glob("*.datasheet.json"))
    if not files:
        print(f"[WARN] No datasheet files found in: {datasheet_dir}")
        return 0

    failures = 0
    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        result = validate_json(doc, profile=profile)
        if result.ok:
            print(f"[OK] {_display_path(path)}")
            continue
        failures += 1
        print(f"[FAIL] {_display_path(path)}")
        for err in result.errors:
            print(f"  - {err}")

    print(f"\nValidated {len(files)} datasheet file(s) with profile={profile}. Failures: {failures}.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

