from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / ".tools" / "agent" / "manifest.json"


def test_agent_manifest_and_guide_exist() -> None:
    assert (ROOT / "AGENTS.md").exists()
    assert MANIFEST_PATH.exists()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["repo"]["name"] == "BattINFO"
    assert "workflow_api" in manifest["preferred_surfaces"]
    assert "primary" in manifest["verification"]


def test_agent_readiness_check_script_passes() -> None:
    subprocess.run(
        [sys.executable, ".tools/quality/check_agent_readiness.py"],
        cwd=ROOT,
        check=True,
    )
