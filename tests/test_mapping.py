from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.transform.json_to_jsonld import to_jsonld


def _load_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _load_golden(path: str) -> dict:
    return json.loads((ROOT / "tests" / "golden" / path).read_text(encoding="utf-8"))


def test_domain_battery_mapping_contains_expected_keys() -> None:
    doc = _load_json("src/battinfo/data/examples/cells/A123_20AH.curated.json")
    mapped = to_jsonld(doc, target="domain-battery")
    golden = _load_golden("domain_battery_a123_20ah.jsonld")
    assert mapped == golden


def test_batterypass_mapping_contains_profile_markers() -> None:
    doc = _load_json("src/battinfo/data/examples/cells/A123_20AH.curated.json")
    mapped = to_jsonld(doc, target="batterypass")
    golden = _load_golden("batterypass_a123_20ah.jsonld")
    assert mapped == golden
