"""Nothing accepted by the authoring models is silently dropped (beta-hardening plan 2.1).

- ``specs=`` must be a mapping: a list/scalar used to be popped and discarded without a word.
- Provenance kwargs (``source_name=``, ``file_hash=``, ``curated_by=``, ...) used to be
  absorbed into ``source`` and then omitted from the emitted record by four of the five
  serializers. All records now emit the full provenance block via one shared serializer,
  the schemas accept it, and from_record reads it back losslessly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import validate_record
from battinfo.api import (
    _record_from_cell_instance,
    _record_from_cell_spec,
    _record_from_dataset,
    _record_from_test,
    _record_from_test_protocol,
)
from battinfo.bundle import CellInstance, CellSpecification, Dataset, Test, TestSpec

UID = "ffffffffffffffff"
SPEC_IRI = "https://w3id.org/battinfo/spec/aaaa-aaaa-aaaa-aaaa"
CELL_IRI = "https://w3id.org/battinfo/cell/bbbb-bbbb-bbbb-bbbb"
SHA256 = "a" * 64

PROVENANCE_KWARGS = dict(
    source_name="Acme datasheet portal",
    file_hash=SHA256,
    curated_by="https://orcid.org/0000-0002-1825-0097",
    workflow_version="ingest-1.2",
)


def test_specs_non_mapping_raises_with_the_fix() -> None:
    with pytest.raises(TypeError, match="specs= must be a mapping"):
        CellSpecification(
            manufacturer="Acme", model_name="X", chemistry="LFP", format="cylindrical",
            specs=[("nominal_capacity", 2.5)],
        )


def test_specs_mapping_still_accepted() -> None:
    spec = CellSpecification(
        manufacturer="Acme", model_name="X", chemistry="LFP", format="cylindrical",
        specs={"nominal_capacity": {"value": 2.5, "unit": "Ah"}},
    )
    assert spec.properties["nominal_capacity"] == {"value": 2.5, "unit": "Ah"}


def _assert_provenance_survives(record: dict, model_cls, prov_key: str = "provenance") -> None:
    prov = record[prov_key]
    assert prov["source_name"] == PROVENANCE_KWARGS["source_name"]
    assert prov["file_hash"] == SHA256
    assert prov["curated_by"] == PROVENANCE_KWARGS["curated_by"]
    assert prov["workflow_version"] == PROVENANCE_KWARGS["workflow_version"]
    result = validate_record(record)
    assert result.ok, [str(e) for e in result.errors][:3]
    loaded = model_cls.from_record(record)
    assert loaded.source.name == PROVENANCE_KWARGS["source_name"]
    assert loaded.source.file_hash == SHA256
    assert loaded.source.curated_by == PROVENANCE_KWARGS["curated_by"]


def test_cell_spec_provenance_round_trip() -> None:
    record = _record_from_cell_spec(CellSpecification(
        manufacturer="Acme", model_name="X", chemistry="LFP", format="cylindrical",
        uid=UID, **PROVENANCE_KWARGS,
    ))
    _assert_provenance_survives(record, CellSpecification)


def test_cell_instance_provenance_round_trip() -> None:
    record = _record_from_cell_instance(CellInstance(
        uid=UID, cell_spec_id=SPEC_IRI, **PROVENANCE_KWARGS,
    ))
    _assert_provenance_survives(record, CellInstance)


def test_test_provenance_round_trip() -> None:
    record = _record_from_test(Test(
        uid=UID, cell_id=CELL_IRI, name="T", kind="cycling", **PROVENANCE_KWARGS,
    ))
    _assert_provenance_survives(record, Test)


def test_test_spec_provenance_round_trip() -> None:
    record = _record_from_test_protocol(TestSpec(
        name="P", uid=UID, **PROVENANCE_KWARGS,
    ))
    _assert_provenance_survives(record, TestSpec)


def test_cell_instance_conflicting_spec_references_raise() -> None:
    spec = CellSpecification(
        id=SPEC_IRI, manufacturer="Acme", model_name="X", chemistry="LFP", format="cylindrical",
    )
    other = "https://w3id.org/battinfo/spec/cccc-cccc-cccc-cccc"
    with pytest.raises(ValueError, match="Conflicting cell spec references"):
        CellInstance(spec, cell_spec_id=other)


def test_cell_instance_positional_spec_with_matching_id_is_kept() -> None:
    spec = CellSpecification(
        id=SPEC_IRI, manufacturer="Acme", model_name="X", chemistry="LFP", format="cylindrical",
    )
    # Previously the positional object was silently discarded whenever cell_spec_id= was given.
    instance = CellInstance(spec, cell_spec_id=SPEC_IRI)
    assert instance.cell_spec is spec
    assert instance.cell_spec_id == SPEC_IRI


def test_test_conflicting_cell_references_raise() -> None:
    cell = CellInstance(id=CELL_IRI, cell_spec_id=SPEC_IRI)
    other = "https://w3id.org/battinfo/cell/dddd-dddd-dddd-dddd"
    with pytest.raises(ValueError, match="Conflicting cell references"):
        Test(cell, cell_id=other, name="T", kind="cycling")


def test_test_positional_cell_with_matching_id_is_kept() -> None:
    cell = CellInstance(id=CELL_IRI, cell_spec_id=SPEC_IRI)
    test = Test(cell, cell_id=CELL_IRI, name="T", kind="cycling")
    assert test.cell is cell
    assert test.cell_instance_id == CELL_IRI


def test_dataset_provenance_round_trip() -> None:
    record = _record_from_dataset(Dataset(
        uid=UID, title="D", access_url="https://data.example.com/d", **PROVENANCE_KWARGS,
    ))
    _assert_provenance_survives(record, Dataset)
