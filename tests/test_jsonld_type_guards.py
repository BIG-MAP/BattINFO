"""Regression tests: record_to_jsonld must tolerate wrong-but-close input types.

These guard against silent JSON-LD corruption / crashes from hand-built or
externally-imported records whose fields drift from the canonical list[str] /
Mapping shapes (audit theme C).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.jsonld import record_to_jsonld  # noqa: E402


def test_dataset_about_as_string_is_not_shredded_into_per_character_nodes() -> None:
    iri = "https://w3id.org/emmo#LithiumIonBattery"
    out = record_to_jsonld({"dataset": {"id": "d1", "name": "DS", "about": iri}}, "dataset")
    assert out["dcterms:subject"] == [{"@id": iri}]


def test_dataset_about_as_list_still_works_and_drops_non_strings() -> None:
    out = record_to_jsonld(
        {"dataset": {"id": "d1", "name": "DS", "about": ["https://x/a", None, "", "https://x/b"]}},
        "dataset",
    )
    assert out["dcterms:subject"] == [{"@id": "https://x/a"}, {"@id": "https://x/b"}]


def test_dataset_checksum_as_string_does_not_crash() -> None:
    out = record_to_jsonld(
        {"dataset": {"id": "d1", "name": "DS", "distributions": [{"content_url": "http://x", "checksum": "deadbeef"}]}},
        "dataset",
    )
    # A bare-string checksum is tolerated (skipped), not an AttributeError.
    dist = out["dcat:distribution"][0]
    assert "spdx:checksum" not in dist


def test_dataset_checksum_as_mapping_is_emitted() -> None:
    out = record_to_jsonld(
        {"dataset": {"id": "d1", "name": "DS", "distributions": [
            {"content_url": "http://x", "checksum": {"algorithm": "sha256", "value": "ab"}}]}},
        "dataset",
    )
    assert out["dcat:distribution"][0]["spdx:checksum"]["spdx:checksumValue"] == "ab"


def test_test_dataset_ids_with_none_does_not_emit_null_id() -> None:
    out = record_to_jsonld({"test": {"id": "t1", "dataset_ids": ["ds-a", None, ""]}}, "test")
    assert out["battinfo:hasDataset"] == [{"@id": "ds-a"}]
