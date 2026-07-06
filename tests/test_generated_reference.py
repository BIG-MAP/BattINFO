"""Committed generated reference pages must match what the code produces today."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load(script: str):
    spec = importlib.util.spec_from_file_location(script, ROOT / "scripts" / f"{script}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schema_reference_matches_the_schemas() -> None:
    gen = _load("gen_schema_reference")
    expected = gen.build()
    actual = gen.OUT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert actual == expected.replace("\r\n", "\n"), (
        "docs/pages/schema-reference.md drifts — run `uv run python scripts/gen_schema_reference.py`"
    )


def test_cli_reference_matches_the_typer_app(tmp_path: Path) -> None:
    out = tmp_path / "cli.md"
    subprocess.run(
        [sys.executable, "-m", "typer", "battinfo.cli", "utils", "docs", "--name", "battinfo",
         "--output", str(out)],
        check=True,
        cwd=ROOT,
        capture_output=True,
        env={**os.environ, "PYTHONUTF8": "1"},  # typer writes with the locale encoding otherwise
    )
    expected = out.read_text(encoding="utf-8").replace("\r\n", "\n")
    actual = (ROOT / "docs" / "pages" / "cli-reference.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert actual == expected, (
        "docs/pages/cli-reference.md drifts from the CLI — regenerate with "
        "`python -m typer battinfo.cli utils docs --name battinfo --output docs/pages/cli-reference.md`"
    )
