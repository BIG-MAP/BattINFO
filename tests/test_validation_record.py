from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.validate import ValidationPolicy, validate_record, validate_record_report

STRICT = ValidationPolicy(name="strict", semantic="error")


def _load_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_validate_record_report_accepts_canonical_cell_type_example() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-type/A123__ANR26650M1-B.json")
    doc["specs"]["specific_energy"] = {"value": 130.0, "unit": "Wh/kg"}
    doc["specs"]["energy_density"] = {"value": 250.0, "unit": "Wh/L"}
    doc["specs"]["specific_power"] = {"value": 900.0, "unit": "W/kg"}
    doc["specs"]["power_density"] = {"value": 1700.0, "unit": "W/L"}
    doc["specs"]["typical_energy"] = {"value": 8.25, "unit": "Wh"}
    doc["specs"]["rated_energy"] = {"value": 8.0, "unit": "Wh"}
    report = validate_record_report(doc, policy=STRICT)
    assert report.ok
    assert not report.issues
    assert doc["product"]["iecCode"] == "IFpR26650"
    assert doc["product"]["countryOfOrigin"] == "United States"
    assert doc["product"]["year"] == 2012


def test_validate_record_report_accepts_cell_type_with_bibliography() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-type/A123__ANR26650M1-B.json")
    doc["bibliography"] = {
        "subject_of": [
            {
                "id": "https://doi.org/10.1000/example-publication",
                "doi": "10.1000/example-publication",
                "type": "Article",
                "headline": "Example publication",
                "author": "Example Author",
                "date_published": 2026,
            }
        ]
    }
    report = validate_record_report(doc, policy=STRICT)
    assert report.ok
    assert not report.issues


def test_validate_record_report_accepts_linked_dataset_example_with_source_root() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    report = validate_record_report(doc, source_root=ROOT / "src" / "battinfo" / "data" / "examples", policy=STRICT)
    assert report.ok
    assert not report.issues


def test_validate_record_report_accepts_test_protocol_example() -> None:
    doc = _load_json("src/battinfo/data/examples/test-protocols/test-protocol-8r2m-4v6k-9p3t-7n5x.json")
    report = validate_record_report(doc, policy=STRICT)
    assert report.ok
    assert not report.issues


def test_validate_record_report_includes_test_protocol_reference_issues() -> None:
    doc = _load_json("src/battinfo/data/examples/tests/test-5p7v-2n8k-4m3t-6q9r.json")
    doc["test"]["protocol_id"] = "https://w3id.org/battinfo/test-protocol/eysh-4h5s-k4bx-zkgg"
    report = validate_record_report(doc, source_root=ROOT / "src" / "battinfo" / "data" / "examples", policy=STRICT)
    assert not report.ok
    assert any(issue.code == "reference.missing" and issue.path == "test.protocol_id" for issue in report.errors)


def test_validate_record_report_combines_schema_and_semantic_issues() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    doc["dataset"]["access_url"] = "not-a-uri"
    doc["dataset"]["dateModified"] = doc["dataset"]["dateCreated"] - 1
    report = validate_record_report(doc, policy=STRICT)
    assert not report.ok
    codes = {issue.code for issue in report.errors}
    assert "schema.format.uri" in codes
    assert "semantic.temporal_order_invalid" in codes


def test_validate_record_report_includes_reference_issues_when_source_root_provided() -> None:
    doc = _load_json("src/battinfo/data/examples/tests/test-5p7v-2n8k-4m3t-6q9r.json")
    doc["test"]["dataset_ids"] = ["https://w3id.org/battinfo/dataset/eysh-4h5s-k4bx-zkgg"]
    report = validate_record_report(doc, source_root=ROOT / "src" / "battinfo" / "data" / "examples", policy=STRICT)
    assert not report.ok
    assert any(issue.code == "reference.missing" for issue in report.errors)


def test_validate_record_report_rejects_dataset_without_cell_link() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    doc["dataset"]["about"] = ["https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r"]
    report = validate_record_report(doc, policy=STRICT)
    assert not report.ok
    assert any(issue.code == "semantic.dataset_missing_cell_link" for issue in report.errors)


def test_validate_record_report_accepts_dataset_with_cell_type_link_only() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    doc["dataset"]["about"] = ["https://w3id.org/battinfo/cell-type/7d9k-2m4p-8t3x-6nq5"]
    report = validate_record_report(doc, policy=STRICT)
    assert report.ok


def test_validate_record_result_preserves_issue_metadata() -> None:
    doc = _load_json("src/battinfo/data/examples/tests/test-5p7v-2n8k-4m3t-6q9r.json")
    doc["test"]["short_id"] = "xxxxxx"
    result = validate_record(doc, policy=STRICT)
    assert not result.ok
    assert result.issues
    assert result.issues[0].code == "semantic.short_id_mismatch"


def test_validate_record_accepts_named_policy_string() -> None:
    doc = _load_json("src/battinfo/data/examples/tests/test-5p7v-2n8k-4m3t-6q9r.json")
    doc["test"]["short_id"] = "xxxxxx"
    result = validate_record(doc, policy="strict")
    assert not result.ok
    assert result.policy == "strict"


def test_validate_record_report_rejects_invalid_size_code_shape() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-type/A123__ANR26650M1-B.json")
    doc["product"]["size_code"] = "26650"
    report = validate_record_report(doc, policy=STRICT)
    assert not report.ok
    codes = {issue.code for issue in report.errors}
    assert "semantic.size_code_invalid" in codes

