"""Committed guide notebooks must not leak the executing machine's paths."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Windows user-profile paths and unix home dirs — none belong in committed output.
_LOCAL_PATH = re.compile(r"[A-Za-z]:[\/]Users[\/]|/home/|/Users/")


def test_no_machine_local_paths_in_committed_outputs() -> None:
    offenders: list[str] = []
    for notebook in sorted((ROOT / "docs" / "guides").glob("*.ipynb")):
        nb = json.loads(notebook.read_text(encoding="utf-8"))
        for index, cell in enumerate(nb.get("cells", [])):
            blob = json.dumps(cell.get("outputs", []))
            if _LOCAL_PATH.search(blob):
                offenders.append(f"{notebook.name} cell {index}")
    assert not offenders, (
        "machine-local paths leaked into committed notebook outputs — re-run "
        "`uv run python scripts/execute_guides.py`:\n" + "\n".join(offenders)
    )
