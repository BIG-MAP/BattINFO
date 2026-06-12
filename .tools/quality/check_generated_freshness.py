"""
CI check: verify that records.context.json matches what the schema would generate.

Exits 0 if up-to-date, 1 if stale.

Usage:
  python .tools/quality/check_generated_freshness.py
  # or via Makefile:
  make check-freshness
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
ASSEMBLE = REPO_ROOT / "scripts" / "assemble_context.py"
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python"


def main() -> int:
    if not ASSEMBLE.exists():
        print(f"ERROR: {ASSEMBLE} not found", file=sys.stderr)
        return 1

    python_exe = str(PYTHON) if PYTHON.exists() else sys.executable
    result = subprocess.run(
        [python_exe, str(ASSEMBLE), "--check"],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
