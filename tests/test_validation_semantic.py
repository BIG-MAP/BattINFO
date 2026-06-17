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


def test_semantic_validation_accepts_canonical_cell_spec_example() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert report.ok
    assert not report.errors


def test_semantic_validation_rejects_short_id_mismatch() -> None:
    doc = _load_json("src/battinfo/data/examples/test/test-5p7v-2n8k-4m3t-6q9r.json")
    doc["test"]["short_id"] = "xxxxxx"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert report.errors[0].code == "semantic.short_id_mismatch"


def test_semantic_validation_rejects_unit_mismatch_for_specs() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["properties"]["nominal_capacity"]["unit"] = "V"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.unit_mismatch" for issue in report.errors)


def test_semantic_validation_rejects_unit_mismatch_for_nominal_continuous_current_specs() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["properties"]["nominal_continuous_charging_current"]["unit"] = "V"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.unit_mismatch" for issue in report.errors)


def test_semantic_validation_rejects_invalid_spec_range_ordering() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["properties"]["minimum_storage_temperature"]["value"] = 70
    doc["properties"]["maximum_storage_temperature"]["value"] = 60
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.range_invalid" for issue in report.errors)


def test_semantic_validation_rejects_invalid_dataset_temporal_order_and_checksum() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    doc["dataset"]["modified_at"] = doc["dataset"]["created_at"] - 1
    doc["dataset"]["distributions"][0]["checksum"]["value"] = "xyz"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    codes = {issue.code for issue in report.errors}
    assert "semantic.temporal_order_invalid" in codes
    assert "semantic.checksum_invalid" in codes


def test_semantic_validation_rejects_dataset_without_cell_link() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    doc["dataset"]["about"] = ["https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r"]
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.dataset_missing_cell_link" for issue in report.errors)


def test_semantic_validation_allows_dataset_with_cell_spec_link_only() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    doc["dataset"]["about"] = ["https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5"]
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert report.ok


def test_semantic_validation_allows_dataset_without_test_link_when_cell_is_present() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    doc["dataset"]["about"] = ["https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8"]
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert report.ok


def test_semantic_validation_warns_for_unmapped_controlled_value() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["cell_spec"]["chemistry"] = "VeryNewChem"
    report = validate_semantic_report(doc)
    assert report.ok
    assert report.warnings
    assert report.warnings[0].code == "semantic.controlled_value_unmapped"


def test_semantic_validation_defaults_to_warning_mode_for_hard_rules() -> None:
    doc = _load_json("src/battinfo/data/examples/test/test-5p7v-2n8k-4m3t-6q9r.json")
    doc["test"]["short_id"] = "xxxxxx"
    report = validate_semantic_report(doc)
    assert report.ok
    assert report.warnings
    assert report.warnings[0].code == "semantic.short_id_mismatch"


def test_semantic_validation_rejects_size_code_without_round_or_pouch_prefix() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["cell_spec"]["size_code"] = "26650"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.size_code_invalid" for issue in report.errors)


def test_semantic_validation_rejects_size_code_prefix_mismatch_for_format() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["cell_spec"]["size_code"] = "P20/50/50"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.size_code_prefix_mismatch" for issue in report.errors)

