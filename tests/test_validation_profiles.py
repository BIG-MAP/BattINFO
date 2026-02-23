from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.validate.pydantic import validate_json


def _load_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_base_profile_example_is_valid() -> None:
    doc = _load_json("src/battinfo/data/examples/cells/A123_20AH.curated.json")
    result = validate_json(doc, profile="base")
    assert result.ok, result.errors


def test_batterypass_profile_example_is_valid() -> None:
    doc = _load_json("assets/examples/profiles/batterypass-minimal.json")
    result = validate_json(doc, profile="batterypass")
    assert result.ok, result.errors


def test_batterypass_requires_measurements() -> None:
    doc = _load_json("assets/examples/profiles/batterypass-minimal.json")
    doc.pop("measurements", None)
    result = validate_json(doc, profile="batterypass")
    assert not result.ok
    assert any("measurements" in err for err in result.errors)
