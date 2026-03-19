from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / ".tools" / "agent" / "manifest.json"
AGENTS_PATH = ROOT / "AGENTS.md"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def main() -> None:
    _require(AGENTS_PATH.exists(), f"missing agent guide: {AGENTS_PATH}")
    _require(MANIFEST_PATH.exists(), f"missing agent manifest: {MANIFEST_PATH}")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    for key in ("repo", "install", "verification", "preferred_surfaces", "source_of_truth", "docs"):
        _require(key in manifest, f"manifest missing key: {key}")

    path_values = [
        manifest["preferred_surfaces"]["workflow_api"],
        manifest["preferred_surfaces"]["authoring_api"],
        manifest["preferred_surfaces"]["public_exports"],
        manifest["preferred_surfaces"]["low_level_api"],
        manifest["source_of_truth"]["canonical_assets"],
        manifest["source_of_truth"]["packaged_assets"],
        manifest["source_of_truth"]["tests"],
        manifest["source_of_truth"]["notebooks"],
        manifest["docs"]["agent_guide"],
        manifest["docs"]["readme"],
        manifest["docs"]["alpha_scope"],
        manifest["docs"]["python_api"],
        manifest["docs"]["notebooks"],
    ]

    for value in path_values:
        path = ROOT / value
        _require(path.exists(), f"manifest path does not exist: {value}")

    for value in manifest.get("safe_write_roots", []):
        candidate = Path(value)
        _require(not candidate.is_absolute(), f"safe write root must be repo-relative: {value}")

    print("agent-readiness: ok")


if __name__ == "__main__":
    main()
