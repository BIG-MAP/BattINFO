from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.validate import ValidationPolicy, validate_semantic_report

STRICT_SEMANTIC = ValidationPolicy(name="strict-semantic", semantic="error")


def _load_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_semantic_validation_accepts_canonical_cell_type_example() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-types/A123__ANR26650M1-B.json")
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert report.ok
    assert not report.errors


def test_semantic_validation_rejects_short_id_mismatch() -> None:
    doc = _load_json("src/battinfo/data/examples/tests/test-5p7v-2n8k-4m3t-6q9r.json")
    doc["test"]["short_id"] = "xxxxxx"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert report.errors[0].code == "semantic.short_id_mismatch"


def test_semantic_validation_rejects_unit_mismatch_for_specs() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-types/A123__ANR26650M1-B.json")
    doc["specs"]["nominal_capacity"]["unit"] = "V"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.unit_mismatch" for issue in report.errors)


def test_semantic_validation_rejects_invalid_spec_range_ordering() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-types/A123__ANR26650M1-B.json")
    doc["specs"]["storage_temperature_min"]["value"] = 70
    doc["specs"]["storage_temperature_max"]["value"] = 60
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.range_invalid" for issue in report.errors)


def test_semantic_validation_rejects_invalid_dataset_temporal_order_and_checksum() -> None:
    doc = _load_json("src/battinfo/data/examples/datasets/dataset-1f8r-6v2k-9p4m-3t7x.json")
    doc["dataset"]["dateModified"] = doc["dataset"]["dateCreated"] - 1
    doc["dataset"]["distribution"][0]["checksum"]["value"] = "xyz"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    codes = {issue.code for issue in report.errors}
    assert "semantic.temporal_order_invalid" in codes
    assert "semantic.checksum_invalid" in codes


def test_semantic_validation_warns_for_unmapped_controlled_value() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-types/A123__ANR26650M1-B.json")
    doc["product"]["chemistry"] = "VeryNewChem"
    report = validate_semantic_report(doc)
    assert report.ok
    assert report.warnings
    assert report.warnings[0].code == "semantic.controlled_value_unmapped"


def test_semantic_validation_defaults_to_warning_mode_for_hard_rules() -> None:
    doc = _load_json("src/battinfo/data/examples/tests/test-5p7v-2n8k-4m3t-6q9r.json")
    doc["test"]["short_id"] = "xxxxxx"
    report = validate_semantic_report(doc)
    assert report.ok
    assert report.warnings
    assert report.warnings[0].code == "semantic.short_id_mismatch"
