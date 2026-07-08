"""Workspace-level equipment/channel UX (Phase A) + the SkyRC MC3000 canonical example.

Covers:
- ws.add("equipment", ...) creates the unit + N channels and is idempotent;
- channel resolution by label, by "unit/CHn", by IRI, and from disk;
- ws.add("test", ..., channel=...) stamps equipment_id + channel_id into the
  saved test record;
- ws.template("equipment-spec", ...) writes a draft that ws.load lifts to a
  strict-valid canonical record with a deterministic IRI;
- the committed MC3000 examples pass strict validation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import battinfo
from battinfo.entities import stable_uid
from battinfo.validate.record import validate_record_report

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

SERIAL = "MC3K-2026-0001"


def _spec_record() -> dict:
    paths = sorted((EXAMPLES / "equipment-spec").glob("*.json"))
    assert paths, "no equipment-spec example"
    return json.loads(paths[0].read_text(encoding="utf-8"))


def _ws(tmp_path: Path):
    return battinfo.workspace(tmp_path, registry_url=None)


def _record_counts(ws) -> tuple[int, int, int]:
    root = ws._ws.source_root
    return (
        len(list((root / "equipment-spec").glob("*.json"))),
        len(list((root / "equipment").glob("*.json"))),
        len(list((root / "channel").glob("*.json"))),
    )


def test_add_equipment_creates_unit_and_channels_and_is_idempotent(tmp_path: Path, capsys) -> None:
    ws = _ws(tmp_path)
    records = ws.add(
        "equipment", spec=_spec_record(), serial_number=SERIAL, name="Cycler 1", location="Lab B"
    )
    # Unit + 4 channels returned (channel count from the spec's channel_count).
    assert len(records) == 5
    assert "equipment" in records[0]
    assert all("channel" in r for r in records[1:])
    assert _record_counts(ws) == (1, 1, 4)
    first_ids = [r.get("equipment", r.get("channel"))["id"] for r in records]
    out = capsys.readouterr().out
    assert "Cycler 1" in out and "4 registered" in out

    # Re-running with the same inputs converges: same IRIs, no new files.
    again = ws.add(
        "equipment", spec=_spec_record(), serial_number=SERIAL, name="Cycler 1", location="Lab B"
    )
    assert [r.get("equipment", r.get("channel"))["id"] for r in again] == first_ids
    assert _record_counts(ws) == (1, 1, 4)

    # ...including from a fresh session over the same workspace directory.
    ws2 = _ws(tmp_path)
    ws2.add("equipment", spec=_spec_record(), serial_number=SERIAL, name="Cycler 1", location="Lab B")
    assert _record_counts(ws2) == (1, 1, 4)


def test_add_equipment_accepts_path_and_iri_and_channels_override(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    spec_path = sorted((EXAMPLES / "equipment-spec").glob("*.json"))[0]
    records = ws.add("equipment", spec=spec_path, serial_number=SERIAL, name="Cycler 1")
    assert _record_counts(ws) == (1, 1, 4)

    # The saved spec can now be referenced by IRI for a second physical unit.
    spec_id = _spec_record()["equipment_spec"]["id"]
    more = ws.add("equipment", spec=spec_id, serial_number="MC3K-2026-0002", name="Cycler 2", channels=2)
    assert len(more) == 3  # unit + 2 channels (channels= overrides channel_count)
    assert _record_counts(ws) == (1, 2, 6)
    assert more[0]["equipment"]["id"] != records[0]["equipment"]["id"]


def test_add_equipment_error_paths(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    with pytest.raises(ValueError, match="spec="):
        ws.add("equipment", serial_number=SERIAL)
    with pytest.raises(ValueError, match="serial_number"):
        ws.add("equipment", spec=_spec_record())
    # A spec without channel_count needs channels=N.
    bare = _spec_record()
    bare["equipment_spec"].pop("channel_count")
    with pytest.raises(ValueError, match="channels="):
        ws.add("equipment", spec=bare, serial_number=SERIAL)
    # The unsupported-type teaching error mentions equipment now.
    with pytest.raises(ValueError, match="equipment"):
        ws.add("dataset")


def test_channel_resolution_by_label_unit_form_and_iri(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    records = ws.add("equipment", spec=_spec_record(), serial_number=SERIAL, name="Cycler 1")
    equipment_id = records[0]["equipment"]["id"]
    ch2 = records[2]["channel"]

    # Default channel labels are "<unit>/CHn"; the serial form and the raw IRI
    # resolve to the same channel.
    assert ws._resolve_channel("Cycler 1/CH2") == (equipment_id, ch2["id"])
    assert ws._resolve_channel(f"{SERIAL}/CH2") == (equipment_id, ch2["id"])
    assert ws._resolve_channel(ch2["id"]) == (equipment_id, ch2["id"])

    with pytest.raises(ValueError, match="Unknown channel") as exc:
        ws._resolve_channel("Cycler 9/CH1")
    assert "Cycler 1/CH1" in str(exc.value)  # the teaching error lists known channels


def test_channel_resolution_reads_records_saved_by_a_previous_session(tmp_path: Path) -> None:
    ws1 = _ws(tmp_path)
    records = ws1.add("equipment", spec=_spec_record(), serial_number=SERIAL, name="Cycler 1")
    ws2 = _ws(tmp_path)  # fresh session, empty in-memory index
    assert ws2._resolve_channel("Cycler 1/CH3") == (
        records[0]["equipment"]["id"],
        records[3]["channel"]["id"],
    )


def test_test_record_carries_equipment_and_channel_ids(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    records = ws.add("equipment", spec=_spec_record(), serial_number=SERIAL, name="Cycler 1")
    equipment_id = records[0]["equipment"]["id"]
    channel_id = records[2]["channel"]["id"]

    from battinfo import CellSpec

    spec = CellSpec(manufacturer="Acme", model="X-1", format="cylindrical", chemistry="Li-ion")
    ws.add("cell", spec=spec, serial_numbers=["CELL-001"])
    tests = ws.add("test", type="cycling", cell="CELL-001", channel="Cycler 1/CH2")
    assert tests[0].equipment_id == equipment_id
    assert tests[0].channel_id == channel_id

    # The unknown-channel teaching error fires before any test is created.
    with pytest.raises(ValueError, match="Unknown channel"):
        ws.add("test", type="cycling", cell="CELL-001", channel="nope/CH9")

    # The stamped fields survive into the saved canonical test record.
    ws.save()
    test_files = sorted((ws._ws.source_root / "test").glob("*.json"))
    assert len(test_files) == 1
    saved = json.loads(test_files[0].read_text(encoding="utf-8"))
    assert saved["test"]["equipment_id"] == equipment_id
    assert saved["test"]["channel_id"] == channel_id


def test_template_writes_a_loadable_draft_with_deterministic_iri(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    path = ws.template(
        "equipment-spec",
        name="SkyRC MC3000",
        manufacturer="SkyRC",
        model="MC3000",
        equipment_class="cycler",
        channel_count=4,
        supported_chemistries=["NiMH", "Li-ion"],
    )
    assert path.exists() and path.name.endswith(".equipment-spec.json")

    record = ws.load(path)
    body = record["equipment_spec"]
    assert body["name"] == "SkyRC MC3000"
    assert body["channel_count"] == 4
    assert body["supported_chemistries"] == ["NiMH", "Li-ion"]
    report = validate_record_report(record, policy="strict")
    assert report.ok, [issue.message for issue in report.errors]

    # Re-loading the same draft mints the same IRI (natural-key minting).
    assert ws.load(path)["equipment_spec"]["id"] == body["id"]

    # The lifted record feeds straight into ws.add("equipment", ...).
    ws.add("equipment", spec=record, serial_number=SERIAL, name="Cycler 1")
    assert _record_counts(ws) == (1, 1, 4)


def test_mc3000_examples_are_the_canonical_equipment_examples() -> None:
    spec = _spec_record()
    body = spec["equipment_spec"]
    assert body["name"] == "SkyRC MC3000"
    assert body["channel_count"] == 4
    assert "Li-ion" in body["supported_chemistries"]
    assert body["property"]["charge_current"] == {"min_value": 0.05, "max_value": 3.0, "unit": "A"}

    equipment = json.loads(sorted((EXAMPLES / "equipment").glob("*.json"))[0].read_text(encoding="utf-8"))
    eq_body = equipment["equipment"]
    assert eq_body["serial_number"] == SERIAL
    assert eq_body["equipment_spec_id"] == body["id"]
    # Equipment uid is minted deterministically from (spec uid, serial number).
    spec_uid = body["id"].rsplit("/", 1)[-1]
    assert eq_body["id"].rsplit("/", 1)[-1] == stable_uid(f"equipment:{spec_uid}:{SERIAL}")

    channels = [
        json.loads(p.read_text(encoding="utf-8"))["channel"]
        for p in sorted((EXAMPLES / "channel").glob("*.json"))
    ]
    assert sorted(c["index"] for c in channels) == [1, 2, 3, 4]
    assert {c["label"] for c in channels} == {f"MC3000-A/CH{i}" for i in range(1, 5)}

    # All six records pass strict validation (references resolve inside examples/).
    docs = [spec, equipment] + [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted((EXAMPLES / "channel").glob("*.json"))
    ]
    assert len(docs) == 6
    for doc in docs:
        report = validate_record_report(doc, source_root=EXAMPLES, policy="strict")
        assert report.ok, [issue.message for issue in report.errors]
