"""Every emitted record's provenance is stamped with the writing battinfo version (3.2).

Malformed records must be forensically attributable to the library build that
wrote them. The stamp is applied at emission (``_provenance_record`` for the
model path, ``stamp_provenance`` for the direct api.py builders); an existing
value is never overwritten, so re-serialising another build's record does not
falsify its origin.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402
from battinfo.bundle import CellSpec, stamp_provenance  # noqa: E402


def _spec() -> CellSpec:
    return CellSpec(
        id="https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
        manufacturer="Energizer",
        model="CR2032",
        format="coin",
        chemistry="Li-primary",
        source={"type": "datasheet", "retrieved_at": 1781589239},
    )


def test_to_record_stamps_current_version() -> None:
    record = _spec().to_record()
    assert record["provenance"]["battinfo_version"] == battinfo.__version__


def test_explicit_version_is_preserved_through_round_trip() -> None:
    record = _spec().to_record()
    record["provenance"]["battinfo_version"] = "0.0.1"
    reread = CellSpec.from_record(record)
    assert reread.to_record()["provenance"]["battinfo_version"] == "0.0.1"


def test_round_trip_is_a_fixed_point() -> None:
    first = _spec().to_record()
    second = CellSpec.from_record(first).to_record()
    assert first["provenance"] == second["provenance"]


def test_stamp_provenance_preserves_existing_value() -> None:
    prov = {"source_type": "datasheet", "battinfo_version": "9.9.9"}
    assert stamp_provenance(prov)["battinfo_version"] == "9.9.9"


def test_stamp_provenance_fills_missing_value() -> None:
    prov: dict = {"source_type": "datasheet"}
    assert stamp_provenance(prov)["battinfo_version"] == battinfo.__version__


def test_stamped_record_is_schema_valid() -> None:
    from battinfo.validate import validate_record_report

    record = _spec().to_record()
    report = validate_record_report(record)
    assert not [i for i in report.issues if i.severity == "error"], [
        f"{i.path}: {i.message}" for i in report.issues
    ]


def test_component_builder_records_are_stamped_and_valid() -> None:
    from battinfo.api import create_component_spec

    record = create_component_spec(
        "separator",
        uid="7d9k2m4p8t3x6nq5",
        name="Celgard 2325",
        validate=True,
    )
    assert record["provenance"]["battinfo_version"] == battinfo.__version__
