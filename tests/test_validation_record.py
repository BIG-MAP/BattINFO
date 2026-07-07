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


def test_validate_record_report_accepts_canonical_cell_spec_example() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["properties"]["specific_energy"] = {"value": 130.0, "unit": "Wh/kg"}
    doc["properties"]["energy_density"] = {"value": 250.0, "unit": "Wh/L"}
    doc["properties"]["specific_power"] = {"value": 900.0, "unit": "W/kg"}
    doc["properties"]["power_density"] = {"value": 1700.0, "unit": "W/L"}
    doc["properties"]["typical_energy"] = {"value": 8.25, "unit": "Wh"}
    doc["properties"]["rated_energy"] = {"value": 8.0, "unit": "Wh"}
    report = validate_record_report(doc, policy=STRICT)
    assert report.ok
    # The record is valid but NOT fully exportable - the mappability warnings
    # (red-team W3.3) truthfully flag what the JSON-LD path would drop:
    # unmapped keys, text-only values, and alias pairs collapsing to one node.
    expected_warnings = {
        "semantic.property_unmapped",       # specific_power, power_density, nominal_continuous_*
        "semantic.value_text_only",         # cycle_life ">1000"
        "semantic.property_alias_collision",  # typical_energy + rated_energy
    }
    assert {i.code for i in report.issues} <= expected_warnings
    assert all(i.severity == "warning" for i in report.issues)
    assert doc["cell_spec"]["iec_code"] == "IFpR26650"
    assert doc["cell_spec"]["country_of_origin"] == "United States"
    assert doc["cell_spec"]["year"] == 2012


def test_validate_record_report_accepts_cell_spec_with_bibliography() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
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
    # Only the truthful mappability warnings the base example carries.
    assert {i.code for i in report.issues} <= {
        "semantic.property_unmapped", "semantic.value_text_only",
    }


def test_validate_record_report_accepts_linked_dataset_example_with_source_root() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    report = validate_record_report(doc, source_root=ROOT / "src" / "battinfo" / "data" / "examples", policy=STRICT)
    assert report.ok
    assert not report.issues


def test_validate_record_report_accepts_test_protocol_example() -> None:
    doc = _load_json("src/battinfo/data/examples/test-protocol/test-protocol-8r2m-4v6k-9p3t-7n5x.json")
    report = validate_record_report(doc, policy=STRICT)
    assert report.ok
    assert not report.issues


def test_validate_record_report_includes_test_protocol_reference_issues() -> None:
    doc = _load_json("src/battinfo/data/examples/test/test-5p7v-2n8k-4m3t-6q9r.json")
    doc["test"]["protocol_id"] = "https://w3id.org/battinfo/spec/eysh-4h5s-k4bx-zkgg"
    report = validate_record_report(doc, source_root=ROOT / "src" / "battinfo" / "data" / "examples", policy=STRICT)
    assert not report.ok
    assert any(issue.code == "reference.missing" and issue.path == "test.protocol_id" for issue in report.errors)


def test_validate_record_report_combines_schema_and_semantic_issues() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    doc["dataset"]["access_url"] = "not-a-uri"
    doc["dataset"]["modified_at"] = doc["dataset"]["created_at"] - 1
    report = validate_record_report(doc, policy=STRICT)
    assert not report.ok
    codes = {issue.code for issue in report.errors}
    assert "schema.format.uri" in codes
    assert "semantic.temporal_order_invalid" in codes


def test_validate_record_report_includes_reference_issues_when_source_root_provided() -> None:
    doc = _load_json("src/battinfo/data/examples/test/test-5p7v-2n8k-4m3t-6q9r.json")
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


def test_validate_record_report_accepts_dataset_with_cell_spec_link_only() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    doc["dataset"]["about"] = ["https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5"]
    report = validate_record_report(doc, policy=STRICT)
    assert report.ok


def test_validate_record_result_preserves_issue_metadata() -> None:
    doc = _load_json("src/battinfo/data/examples/test/test-5p7v-2n8k-4m3t-6q9r.json")
    doc["test"]["short_id"] = "xxxxxx"
    result = validate_record(doc, policy=STRICT)
    assert not result.ok
    assert result.issues
    assert result.issues[0].code == "semantic.short_id_mismatch"


def test_validate_record_accepts_named_policy_string() -> None:
    doc = _load_json("src/battinfo/data/examples/test/test-5p7v-2n8k-4m3t-6q9r.json")
    doc["test"]["short_id"] = "xxxxxx"
    result = validate_record(doc, policy="strict")
    assert not result.ok
    assert result.policy == "strict"


def test_validate_record_report_rejects_invalid_size_code_shape() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["cell_spec"]["size_code"] = "26650"
    report = validate_record_report(doc, policy=STRICT)
    assert not report.ok
    codes = {issue.code for issue in report.errors}
    assert "semantic.size_code_invalid" in codes



def test_string_number_value_fails_loud() -> None:
    """'2.5' (string) used to pass strict validation and emit an untyped
    string literal into RDF (red-team W3.4). The schema now requires number;
    value_text exists for genuinely textual values."""
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["properties"]["nominal_capacity"]["value"] = "2.5"
    report = validate_record_report(doc, policy=STRICT)
    assert not report.ok
    assert any("nominal_capacity" in i.path and i.severity == "error" for i in report.issues)
