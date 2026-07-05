"""PR B (step A), remaining entities: each *Input save builder builds its canonical record THROUGH
its model's to_record(), not a parallel hand-assembled dict. Pins that routing preserves the fields
and (where the model does more) aligns the DTO save path with what the object-first path already
produces."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import validate_record
from battinfo.api import (
    _record_from_cell_instance,
    _record_from_dataset,
    _record_from_test,
    _record_from_test_protocol,
    _to_unix_time,
)
from battinfo.bundle import CellInstance, Dataset, Test, TestSpec

_SPEC = "https://w3id.org/battinfo/spec/1c4m-7p9q-2k6t-8v3r"
_DS = "https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x"


def test_cell_instance_routes_through_model_and_validates() -> None:
    rec = _record_from_cell_instance(CellInstance(
        id="https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8", cell_spec_id=_SPEC,
        serial_number="FAC-002", batch_id="B1", manufactured_at="2022-01-15",
        measured={"mass": {"value": 45, "unit": "g"}}, dataset_ids=[_DS], notes=["n"],
    ))
    assert validate_record(rec).ok, [str(e) for e in validate_record(rec).errors][:3]
    ci = rec["cell_instance"]
    assert ci["cell_spec_id"] == _SPEC and ci["serial_number"] == "FAC-002" and ci["batch_id"] == "B1"
    assert ci["manufactured_at"] == _to_unix_time("2022-01-15")  # ISO string converted to unix
    assert rec["datasets"] == [{"id": _DS, "role": "raw"}]
    assert rec["measured"] == {"mass": {"value": 45, "unit": "g"}}


def test_cell_instance_save_path_now_matches_the_object_first_path() -> None:
    # Routing aligns the two save paths: the DTO builder now emits the derived name the model already
    # produces via Workspace.cell(), instead of silently omitting it.
    rec = _record_from_cell_instance(CellInstance(
        uid="3m6k-9t2p-7x4h-9nq8", cell_spec_id=_SPEC, serial_number="FAC-001",
    ))
    model_direct = CellInstance(
        id="https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8", cell_spec_id=_SPEC,
        serial_number="FAC-001",
    ).to_record()
    assert rec["cell_instance"]["name"] == model_direct["cell_instance"]["name"] == "FAC-001"


def test_cell_instance_mints_id_from_uid() -> None:
    rec = _record_from_cell_instance(CellInstance(uid="3m6k-9t2p-7x4h-9nq8", cell_spec_id=_SPEC))
    assert rec["cell_instance"]["id"] == "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8"
    assert rec["cell_instance"]["short_id"] == "3m6k9t"


def test_test_routes_through_model_mapping_fields_and_validates() -> None:
    # The Test model names fields differently from the record (test_type/cell_instance_id/instrument/
    # protocol); routing must map them back to kind/cell_id/instrument_name/protocol_* — byte-identically.
    rec = _record_from_test(Test(
        uid="5p7v-2n8k-4m3t-6q9r", cell_id="https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8",
        name="Capacity check", kind="capacity_check",
        protocol_id="https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
        protocol_name="CC discharge C/5", protocol_url="https://x/proto", status="completed",
        instrument_name="Maccor", started_at="2022-02-01", ended_at="2022-02-02", dataset_ids=[_DS],
    ))
    assert validate_record(rec).ok, [str(e) for e in validate_record(rec).errors][:3]
    t = rec["test"]
    assert t["cell_id"] == "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8"
    assert t["kind"] == "capacity_check" and t["instrument_name"] == "Maccor"
    assert t["protocol_name"] == "CC discharge C/5" and t["protocol_url"] == "https://x/proto"
    assert t["started_at"] == _to_unix_time("2022-02-01")  # ISO -> unix
    assert t["ended_at"] == _to_unix_time("2022-02-02")
    assert t["dataset_ids"] == [_DS]


_CELL = "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8"
_TEST = "https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r"
_TEST2 = "https://w3id.org/battinfo/test/7d9k-2m4p-8t3x-6nq5"
_DS_IRI = "https://w3id.org/battinfo/dataset/8c1h-8pk6-8034-vav6"


def test_dataset_routes_through_model_and_validates() -> None:
    # The flat authoring shape (title/format/checksum_*/source_*) is absorbed by the model
    # and serialized via to_record(); the record must be schema-valid and carry the fields.
    rec = _record_from_dataset(Dataset(
        id=_DS_IRI, title="MN1500 dataset", format="application/x-hdf5",
        download_url="https://x/d.h5", checksum_algorithm="sha256", checksum_value="abc",
        related_cell_ids=[_CELL], related_test_ids=[_TEST], created_at="2022-03-01",
        source_type="measurement", source_url="https://x/src",
    ))
    assert validate_record(rec).ok, [str(e) for e in validate_record(rec).errors][:3]
    ds = rec["dataset"]
    assert ds["name"] == "MN1500 dataset"
    assert ds["about"] == [_CELL, _TEST]
    assert ds["created_at"] == _to_unix_time("2022-03-01")  # ISO -> unix
    assert ds["distributions"][0]["encoding_format"] == "application/x-hdf5"
    assert ds["distributions"][0]["checksum"] == {"algorithm": "sha256", "value": "abc"}
    assert rec["provenance"]["source_type"] == "measurement"


def test_dataset_relates_to_multiple_tests_losslessly() -> None:
    # One dataset can relate to several tests; the model must carry all of them in `about`
    # (the single cell_instance_id/test_id shape would have dropped the extras).
    rec = _record_from_dataset(Dataset(
        id=_DS_IRI, title="Multi", related_cell_ids=[_CELL], related_test_ids=[_TEST, _TEST2],
        source_type="lab",
    ))
    assert validate_record(rec).ok, [str(e) for e in validate_record(rec).errors][:3]
    assert rec["dataset"]["about"] == [_CELL, _TEST, _TEST2]


def test_dataset_always_emits_required_access_url() -> None:
    # access_url is schema-required; the model fills it even when unset so an object-first
    # dataset is valid on its own (previously only the DTO save path guaranteed this).
    rec = _record_from_dataset(Dataset(id=_DS_IRI, title="Bare", source_type="other"))
    assert validate_record(rec).ok, [str(e) for e in validate_record(rec).errors][:3]
    assert rec["dataset"]["access_url"]  # present and non-empty


def test_dataset_mints_id_from_uid() -> None:
    rec = _record_from_dataset(Dataset(uid="8c1h-8pk6-8034-vav6", title="X", source_type="other"))
    assert rec["dataset"]["id"] == _DS_IRI
    assert rec["dataset"]["short_id"] == "8c1h8p"


_SPEC_IRI = "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5"


def test_test_spec_parses_experiment_into_method_and_facets() -> None:
    # The PyBaMM-style experiment[] authoring input is parsed by the model into the canonical
    # method[] and rolled up into facets — via the model, not a parallel hand-builder.
    rec = _record_from_test_protocol(TestSpec(
        id=_SPEC_IRI, name="CC cycling", kind="cycling",
        experiment=["Discharge at C/10 until 2.5 V", "Charge at C/10 until 4.2 V"], cycles=3,
        conditions={"temperature": {"value": 25, "unit": "degC"}},
        source_type="manual",
    ))
    assert validate_record(rec).ok, [str(e) for e in validate_record(rec).errors][:3]
    assert rec["test_spec"]["kind"] == "cycling"
    assert rec["method"], "experiment[] should parse into a non-empty method[]"
    assert 0.1 in rec["facets"]["c_rates"]
    assert rec["facets"]["voltage_window_V"] == [2.5, 4.2]
    assert rec["provenance"]["source_type"] == "manual"


def test_test_spec_defaults_provenance_and_mints_id() -> None:
    rec = _record_from_test_protocol(TestSpec(uid="7d9k-2m4p-8t3x-6nq5", name="X", kind="other"))
    assert rec["test_spec"]["id"] == _SPEC_IRI
    assert rec["test_spec"]["short_id"] == "7d9k2m"
    assert rec["provenance"]["source_type"] == "manual"  # dataset/test-spec default
    assert isinstance(rec["provenance"]["retrieved_at"], int)  # defaulted to now
