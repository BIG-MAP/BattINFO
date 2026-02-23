from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    schema_path = repo_root / "assets" / "schemas" / "battinfo.base.schema.json"
    output_path = repo_root / "src" / "battinfo" / "models" / "generated.py"

    cmd = [
        sys.executable,
        "-m",
        "datamodel_code_generator",
        "--input",
        str(schema_path),
        "--input-file-type",
        "jsonschema",
        "--output",
        str(output_path),
        "--output-model-type",
        "pydantic_v2.BaseModel",
        "--target-python-version",
        "3.10",
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
