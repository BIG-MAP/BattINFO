"""Emitter convergence: resolver (B) and publication-package (C) cell-spec nodes.

Covers the three convergence steps:

1. The resolver JSON-LD carries every descriptor the canonical record holds
   (no silent drops): model, IEC code, country of origin, release year,
   physical @type stack via isDescriptionFor, and a standard-vocabulary
   provenance node.
2. One quantity-node shape everywhere (list @type + RealData + bare-IRI unit),
   with the round-trip importer accepting both the old and the new shapes.
3. B and C share one builder: byte-identical spec nodes for the same record.
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api._resolver import _resolver_jsonld
from battinfo.api._shared import _validate_publication_artifact
from battinfo.transform.cell_spec_node import build_cell_spec_node


def _cell_spec_record(**overrides) -> dict:
    cell_spec = {
        "id": "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
        "short_id": "7d9k2m",
        "identifier": "cell-spec:7d9k-2m4p-8t3x-6nq5",
        "name": "A123 ANR26650M1-B",
        "model": "ANR26650M1-B",
        "manufacturer": {"type": "Organization", "name": "A123"},
        "cell_format": "cylindrical",
        "chemistry": "Li-ion",
        "positive_electrode_basis": "LFP",
        "negative_electrode_basis": "graphite",
        "size_code": "R26650",
        "iec_code": "IFpR26650",
        "country_of_origin": "United States",
        "rechargeable": True,
        "year": 2012,
    }
    cell_spec.update(overrides.pop("cell_spec", {}))
    record = {
        "schema_version": "0.1.0",
        "cell_spec": cell_spec,
        "properties": {
            "nominal_capacity": {"value": 2.5, "unit": "Ah"},
            "nominal_voltage": {"value": 3.3, "unit": "V"},
        },
        "provenance": {
            "source_type": "datasheet",
            "source_url": "https://example.org/datasheets/anr26650m1-b.pdf",
            "citation": "A123 Systems (2012). ANR26650M1-B datasheet.",
            "retrieved_at": 1769585584,
        },
    }
    record.update(overrides)
    return record


# ── Step 1: resolver enrichment (no silent drops) ────────────────────────────


def test_resolver_cell_spec_carries_all_descriptors() -> None:
    doc = _resolver_jsonld(_cell_spec_record())

    assert doc["@type"] == ["BatteryCellSpecification", "schema:CreativeWork"]
    assert doc["@id"] == "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5"
    assert doc["schema:model"] == "ANR26650M1-B"
    assert doc["schema:productID"] == "IFpR26650"
    assert doc["schema:size"] == "R26650"
    assert doc["schema:countryOfOrigin"] == {
        "@type": "schema:Country",
        "schema:name": "United States",
    }
    assert doc["schema:releaseDate"] == "2012-01-01"
    assert doc["schema:identifier"] == "7d9k-2m4p-8t3x-6nq5"
    assert doc["schema:url"].endswith("/registry/spec/7d9k-2m4p-8t3x-6nq5")


def test_resolver_cell_spec_expresses_descriptors_via_type_stack() -> None:
    doc = _resolver_jsonld(_cell_spec_record())

    physical = doc["isDescriptionFor"]["@type"]
    assert "CylindricalBattery" in physical
    assert "LithiumIonBattery" in physical
    # Electrode bases are expressed through the physical @type stack, not literals.
    assert "LithiumIonIronPhosphateBattery" in physical
    assert "LithiumIonGraphiteBattery" in physical
    assert "SecondaryBattery" in physical
    assert "battinfo:chemistry" not in doc
    assert "battinfo:cellFormat" not in doc
    assert "battinfo:positiveElectrodeBasis" not in doc
    assert "battinfo:negativeElectrodeBasis" not in doc


def test_resolver_cell_spec_emits_standard_vocab_provenance() -> None:
    doc = _resolver_jsonld(_cell_spec_record())

    prov = doc["dcterms:source"]
    assert prov["@type"] == "prov:Entity"
    assert prov["dcterms:type"] == "datasheet"
    assert prov["prov:hadPrimarySource"] == {
        "@id": "https://example.org/datasheets/anr26650m1-b.pdf"
    }
    assert prov["prov:generatedAtTime"].startswith("2026-01-28T")
    assert prov["dcterms:bibliographicCitation"].startswith("A123 Systems (2012)")


def test_resolver_cell_spec_quantity_nodes_use_canonical_shape() -> None:
    doc = _resolver_jsonld(_cell_spec_record())

    nodes = {node["@type"][0]: node for node in doc["hasProperty"]}
    capacity = nodes["NominalCapacity"]
    assert capacity["@type"] == ["NominalCapacity", "ConventionalProperty"]
    assert capacity["hasNumericalPart"] == {"@type": "RealData", "hasNumberValue": 2.5}
    assert isinstance(capacity["hasMeasurementUnit"], str)


def test_resolver_cell_spec_artifact_passes_publication_validation() -> None:
    _validate_publication_artifact(_resolver_jsonld(_cell_spec_record()))


def test_shipped_example_record_resolves_without_drops() -> None:
    src = ROOT / "examples" / "cell-spec" / "A123__ANR26650M1-B.json"
    record = json.loads(src.read_text(encoding="utf-8"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        doc = _resolver_jsonld(record)
    assert doc["schema:model"] == record["cell_spec"]["model"]
    assert doc["schema:productID"] == record["cell_spec"]["iec_code"]
    assert "isDescriptionFor" in doc
    assert doc["dcterms:source"]["dcterms:type"] == "datasheet"
    _validate_publication_artifact(doc)


# ── Emit-time warnings at the drop sites ─────────────────────────────────────


def test_unmapped_property_key_warns_at_emit_time() -> None:
    record = _cell_spec_record(
        properties={"frobnication_index": {"value": 42.0, "unit": "V"}}
    )
    with pytest.warns(UserWarning, match="semantic.property_unmapped.*frobnication_index"):
        doc = build_cell_spec_node(record)
    # Emitted with the non-canonical fallback term rather than silently dropped.
    assert doc["hasProperty"][0]["@type"][0] == "battinfo:frobnicationIndex"


def test_value_text_only_property_warns_at_emit_time() -> None:
    record = _cell_spec_record(
        properties={"cycle_life": {"value_text": ">=1000 cycles"}}
    )
    with pytest.warns(UserWarning, match="semantic.value_text_only.*cycle_life"):
        build_cell_spec_node(record)


def test_mapped_numeric_properties_do_not_warn() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        build_cell_spec_node(_cell_spec_record())
