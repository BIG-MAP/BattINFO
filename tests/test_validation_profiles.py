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


def test_battery_descriptor_profile_example_is_valid() -> None:
    doc = _load_json("assets/examples/battery-descriptors/minimal.example.json")
    result = validate_json(doc, profile="battery-descriptor")
    assert result.ok, result.errors


def test_test_profile_example_is_valid() -> None:
    doc = _load_json("assets/examples/tests/test-5p7v-2n8k-4m3t-6q9r.json")
    result = validate_json(doc, profile="test")
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


def test_cell_type_datasheet_profile_example_is_valid() -> None:
    doc = _load_json("assets/datasheets/cell-types/pvn1-43h7-rm3e-mjqq.datasheet.json")
    result = validate_json(doc, profile="cell-type-datasheet")
    assert result.ok, result.errors


def test_cell_type_datasheet_rejects_non_prefixed_extensions() -> None:
    doc = _load_json("assets/datasheets/cell-types/pvn1-43h7-rm3e-mjqq.datasheet.json")
    doc["extensions"] = {"vendor_tag": "not-allowed"}
    result = validate_json(doc, profile="cell-type-datasheet")
    assert not result.ok
    assert any("extensions" in err for err in result.errors)


def test_datasheet_source_manifest_profile_example_is_valid() -> None:
    doc = {
        "version": "1.0.0",
        "generated_at": "2026-02-23T00:00:00Z",
        "sources": [
            {
                "source_id": "src:cellinfo-0123456789abcdef",
                "source_type": "cellinfo-json",
                "path": "C:/data/cells-clean/A123_20AH.json",
                "file_name": "A123_20AH.json",
                "checksum_sha256": "a" * 64,
                "size_bytes": 1234,
                "discovered_at": "2026-02-23T00:00:00Z",
                "hints": {
                    "manufacturer": "A123",
                    "models": ["A123_20AH"],
                    "contains_multiple_cells": False,
                },
            }
        ],
    }
    result = validate_json(doc, profile="datasheet-source-manifest")
    assert result.ok, result.errors


def test_datasheet_source_manifest_rejects_invalid_generated_at_format() -> None:
    doc = {
        "version": "1.0.0",
        "generated_at": "not-a-datetime",
        "sources": [],
    }
    result = validate_json(doc, profile="datasheet-source-manifest")
    assert not result.ok
    assert any("generated_at" in err for err in result.errors)


def test_cell_type_candidate_profile_example_is_valid() -> None:
    doc = {
        "version": "1.0.0",
        "candidate": {
            "candidate_id": "candidate:cellinfo:a123-20ah",
            "source_document_id": "src:cellinfo-0123456789abcdef",
            "source_type": "cellinfo-json",
            "product": {
                "name": "A123_20AH",
                "manufacturer": "A123",
                "model": "A123_20AH",
                "chemistry": "Li-ion",
                "positive_electrode_basis": "LFP",
                "negative_electrode_basis": "unknown",
                "format": "prismatic",
            },
            "specs": {
                "nominal_capacity": {"value": 20.0, "unit": "Ah"},
                "nominal_voltage": {"value": 3.3, "unit": "V"},
            },
            "split": {
                "is_multi_cell_source": False,
                "variant_index": 0,
                "variant_total": 1,
            },
        },
        "provenance": {
            "extracted_at": "2026-02-23T00:00:00Z",
            "extractor": "tests",
            "extractor_version": "1.0.0",
            "source_record": "C:/data/cells-clean/A123_20AH.json",
            "source_checksum": "b" * 64,
        },
    }
    result = validate_json(doc, profile="cell-type-candidate")
    assert result.ok, result.errors
