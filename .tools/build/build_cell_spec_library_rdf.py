from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import build_cell_spec_library_rdf


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build per-record and aggregate JSON-LD artifacts for the cell-spec library."
    )
    parser.add_argument("--input-dir", type=Path, default=ROOT / "assets" / "library" / "cell-specs")
    parser.add_argument("--output-jsonld-dir", type=Path, default=ROOT / "assets" / "library-rdf" / "cell-specs")
    parser.add_argument("--aggregate-jsonld", type=Path, default=ROOT / "ontology" / "library" / "cell-specs.jsonld")
    parser.add_argument("--manifest-json", type=Path, default=ROOT / "assets" / "library-rdf" / "cell-specs.index.json")
    parser.add_argument("--glob", default="*.json", help="File glob used to select library cell specifications.")
    parser.add_argument(
        "--clean-output",
        action="store_true",
        help="Remove existing JSON-LD outputs before writing rebuilt artifacts.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    payload = build_cell_spec_library_rdf(
        input_dir=args.input_dir,
        output_jsonld_dir=args.output_jsonld_dir,
        aggregate_jsonld=args.aggregate_jsonld,
        manifest_json=args.manifest_json,
        glob=args.glob,
        clean_output=args.clean_output,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
