"""Guard that the packaged example copy stays in sync with the source.

`examples/` (repo root) is the single source of truth. `src/battinfo/data/examples/`
is an auto-generated, committed copy so the records ship in the wheel. This test
runs `scripts/sync_examples.py --check` and fails if the two have drifted —
i.e. someone edited the source without regenerating, or edited the copy directly.

Fix: `python scripts/sync_examples.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync_examples.py"


def test_packaged_examples_in_sync() -> None:
    result = subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "Packaged examples are out of sync with examples/.\n"
        "Run: python scripts/sync_examples.py\n\n"
        f"{result.stdout}{result.stderr}"
    )
