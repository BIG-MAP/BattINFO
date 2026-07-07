"""Generate the CLI reference page from the typer app, platform-independently.

typer renders Path option defaults with the OS separator, so raw output
differs between Windows and Linux. This wrapper normalises backslashes to
forward slashes (the only backslashes in the help corpus are path separators),
making the committed page byte-identical on every platform.

Usage:
    uv run python scripts/gen_cli_reference.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "pages" / "cli-reference.md"


def build() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "cli.md"
        subprocess.run(
            [sys.executable, "-m", "typer", "battinfo.cli", "utils", "docs",
             "--name", "battinfo", "--output", str(raw)],
            check=True,
            cwd=ROOT,
            capture_output=True,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        text = raw.read_text(encoding="utf-8").replace("\r\n", "\n")
    text = text.replace("\\", "/")
    # typer titles the page with the bare program name; give readers a real
    # title and say what the page is.
    header = (
        "# CLI reference\n\n"
        "Every `battinfo` command, generated from the CLI itself "
        "(so it cannot drift). All commands and options:\n"
    )
    assert text.startswith("# `battinfo`\n"), "unexpected typer docs header"
    return header + text[len("# `battinfo`\n"):]


def main() -> int:
    OUT.write_text(build(), encoding="utf-8", newline="\n")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
