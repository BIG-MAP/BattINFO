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
    CellInstanceInput,
    TestInput,
    _record_from_cell_instance,
    _record_from_test,
)

_SPEC = "https://w3id.org/battinfo/spec/1c4m-7p9q-2k6t-8v3r"
_DS = "https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x"


def test_cell_instance_routes_through_model_and_validates() -> None:
    rec = _record_from_cell_instance(CellInstanceInput(
        id="https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8", cell_spec_id=_SPEC,
        serial_number="FAC-002", batch_id="B1", manufactured_at="2022-01-15",
        measured={"mass": {"value": 45, "unit": "g"}}, dataset_ids=[_DS], notes=["n"],
    ))
    assert validate_record(rec).ok, [str(e) for e in validate_record(rec).errors][:3]
    ci = rec["cell_instance"]
    assert ci["cell_spec_id"] == _SPEC and ci["serial_number"] == "FAC-002" and ci["batch_id"] == "B1"
    assert ci["manufactured_at"] == 1642201200  # ISO string converted to unix, as before
    assert rec["datasets"] == [{"id": _DS, "role": "raw"}]
    assert rec["measured"] == {"mass": {"value": 45, "unit": "g"}}


def test_cell_instance_save_path_now_matches_the_object_first_path() -> None:
    # Routing aligns the two save paths: the DTO builder now emits the derived name the model already
    # produces via Workspace.cell(), instead of silently omitting it.
    from battinfo.bundle import CellInstance

    rec = _record_from_cell_instance(CellInstanceInput(
        uid="3m6k-9t2p-7x4h-9nq8", cell_spec_id=_SPEC, serial_number="FAC-001",
    ))
    model_direct = CellInstance(
        id="https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8", cell_spec_id=_SPEC,
        serial_number="FAC-001",
    ).to_record()
    assert rec["cell_instance"]["name"] == model_direct["cell_instance"]["name"] == "FAC-001"


def test_cell_instance_mints_id_from_uid() -> None:
    rec = _record_from_cell_instance(CellInstanceInput(uid="3m6k-9t2p-7x4h-9nq8", cell_spec_id=_SPEC))
    assert rec["cell_instance"]["id"] == "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8"
    assert rec["cell_instance"]["short_id"] == "3m6k9t"


def test_test_routes_through_model_mapping_fields_and_validates() -> None:
    # The Test model names fields differently from the record (test_type/cell_instance_id/instrument/
    # protocol); routing must map them back to kind/cell_id/instrument_name/protocol_* — byte-identically.
    rec = _record_from_test(TestInput(
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
    assert t["started_at"] == 1643670000 and t["ended_at"] == 1643756400  # ISO -> unix
    assert t["dataset_ids"] == [_DS]
