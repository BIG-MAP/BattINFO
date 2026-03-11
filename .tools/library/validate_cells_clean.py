from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "src" / "battinfo" / "data" / "schemas" / "cell-canonical.schema.json"
CELLS_CLEAN_DIR = ROOT / "src" / "battinfo" / "data" / "examples" / "cells-clean"


def main() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    registry = Registry().with_resources([(schema["$id"], Resource.from_contents(schema))])
    validator = Draft202012Validator(schema, registry=registry)

    files = sorted(CELLS_CLEAN_DIR.glob("*.json"))
    failures: list[tuple[str, str, str]] = []
    for path in files:
        doc = json.loads(path.read_text(encoding="utf-8"))
        for err in validator.iter_errors(doc):
            location = ".".join(str(p) for p in err.path)
            failures.append((path.name, location, err.message))
            break

    if failures:
        print(f"validation-errors={len(failures)} of {len(files)}")
        for name, location, message in failures[:20]:
            print(f"{name} :: {location} :: {message}")
        raise SystemExit(1)

    print(f"validation-ok={len(files)}")


if __name__ == "__main__":
    main()

