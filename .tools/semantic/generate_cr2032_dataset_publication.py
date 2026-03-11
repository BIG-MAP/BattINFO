from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.publication import (  # noqa: E402
    DEFAULT_CR2032_LIBRARY_SPEC,
    DEFAULT_CR2032_REPORT_FILENAME,
    DEFAULT_PUBLISH_FILENAME,
    publish_dataset_metadata,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a BattINFO publication JSON-LD file for the Energizer CR2032 example. "
            "Optional bundle JSON files can also be emitted for local inspection."
        )
    )
    parser.add_argument("--datasheet", type=Path, required=True)
    parser.add_argument("--library-spec", type=Path, default=DEFAULT_CR2032_LIBRARY_SPEC)
    parser.add_argument("--dataset-dir", type=Path, action="append", dest="dataset_dirs", required=True)
    parser.add_argument("--staging-root", type=Path, required=True)
    parser.add_argument("--publish-filename", default=DEFAULT_PUBLISH_FILENAME)
    parser.add_argument("--report-filename", default=DEFAULT_CR2032_REPORT_FILENAME)
    parser.add_argument("--dataset-glob", default="**/*")
    parser.add_argument("--emit-bundle-dir", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = publish_dataset_metadata(
        cell_specification=args.library_spec,
        datasheet_path=args.datasheet,
        dataset_dirs=args.dataset_dirs,
        staging_root=args.staging_root,
        test_kind="capacity_check",
        protocol_name="constant current discharging",
        instrument_name="short Landt cycler",
        test_status="completed",
        test_name_template="{dataset_key} constant current discharging",
        dataset_name_template="{cell_type_name} dataset {dataset_key}",
        dataset_description_template=(
            "Dataset directory packaged with self-contained BattINFO publication metadata for one "
            "{cell_type_name} constant-current discharge run."
        ),
        publish_filename=args.publish_filename,
        report_filename=args.report_filename,
        dataset_glob=args.dataset_glob,
        emit_bundle_dir=args.emit_bundle_dir,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

