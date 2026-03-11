from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CELLS_CLEAN_DIR = ROOT / "src" / "battinfo" / "data" / "examples" / "cells-clean"
NUMERIC_KEYS = ("value", "value_min", "value_max", "value_typical")


def is_nan_like(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() == "nan"
    if isinstance(value, float):
        return math.isnan(value)
    return False


def main() -> None:
    files = sorted(CELLS_CLEAN_DIR.glob("*.json"))
    removed_specs_total = 0
    changed_files = 0

    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        specs = doc.get("specs")
        if not isinstance(specs, dict):
            continue

        removed = []
        for key in list(specs.keys()):
            spec_item = specs.get(key)
            if not isinstance(spec_item, dict):
                continue
            if any(is_nan_like(spec_item.get(numeric_key)) for numeric_key in NUMERIC_KEYS):
                removed.append(key)
                specs.pop(key, None)

        if not removed:
            continue

        removed_specs_total += len(removed)
        changed_files += 1

        quality = doc.get("quality")
        if isinstance(quality, dict):
            warnings = quality.get("warnings")
            if not isinstance(warnings, list):
                warnings = []
            warnings.append(
                "Removed NaN-valued specs during cleanup: " + ", ".join(sorted(removed))
            )
            quality["warnings"] = warnings

        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(
        f"cleaned_files={changed_files} removed_specs={removed_specs_total} total_files={len(files)}"
    )


if __name__ == "__main__":
    main()

