"""Idempotent minting: save_* without a uid mints from the natural key (3.3).

Re-running an identical ingest must land on the existing records (a no-op),
not mint a fresh random corpus. Seeds mirror the Workspace finalizers exactly,
so both authoring paths mint the same IRI for the same identity. Records with
no distinguishing identity fall back to random minting — two anonymous but
physically distinct records must never silently dedup.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import Workspace, api  # noqa: E402

SPEC_FIELDS = {
    "manufacturer": "Energizer",
    "model": "CR2032",
    "format": "coin",
    "chemistry": "Li-primary",
}


def test_rerun_of_identical_spec_ingest_is_a_noop(tmp_path: Path) -> None:
    root = tmp_path / "examples"
    first = api.save_cell_spec(dict(SPEC_FIELDS), source_root=root)
    again = api.save_cell_spec(dict(SPEC_FIELDS), source_root=root, mode="upsert")
    assert again["id"] == first["id"], "same natural key must mint the same IRI"
    assert again["status"] == "updated"
    assert again["content_changed"] is False, "identical re-save must be a no-op"

    existing = api.save_cell_spec(dict(SPEC_FIELDS), source_root=root, duplicate_policy="return_existing")
    assert existing["status"] == "exists"
    assert existing["id"] == first["id"]


def test_changed_content_updates_in_place_under_the_same_natural_key(tmp_path: Path) -> None:
    root = tmp_path / "examples"
    first = api.save_cell_spec(dict(SPEC_FIELDS), source_root=root)
    revised = api.save_cell_spec(
        {**SPEC_FIELDS, "nominal_capacity": {"value": 0.235, "unit": "Ah"}},
        source_root=root,
        mode="upsert",
    )
    assert revised["id"] == first["id"], "a corrected datasheet updates the record, not a sibling"
    assert revised["status"] == "updated"
    assert revised["content_changed"] is True


def test_api_and_workspace_mint_the_same_iri_for_the_same_identity(tmp_path: Path) -> None:
    api_record = api.save_cell_spec(dict(SPEC_FIELDS), source_root=tmp_path / "api" / "examples")

    workspace = Workspace(root=tmp_path / "ws")
    workspace.cell_spec(**SPEC_FIELDS)
    ws_results = workspace.save(source_root=tmp_path / "ws" / "examples", build_index=False)
    ws_id = ws_results["cell_specs"][0]["id"]

    assert api_record["id"] == ws_id


def test_serialised_instance_rerun_lands_on_the_same_record(tmp_path: Path) -> None:
    root = tmp_path / "examples"
    spec = api.save_cell_spec(dict(SPEC_FIELDS), source_root=root)
    draft = {"cell_spec_id": spec["id"], "serial_number": "LAB-0001"}
    first = api.save_cell_instance(dict(draft), source_root=root)
    again = api.save_cell_instance(dict(draft), source_root=root, mode="upsert")
    assert again["id"] == first["id"]
    assert again["content_changed"] is False


def test_anonymous_instances_still_mint_distinct_ids(tmp_path: Path) -> None:
    root = tmp_path / "examples"
    spec = api.save_cell_spec(dict(SPEC_FIELDS), source_root=root)
    draft = {"cell_spec_id": spec["id"]}  # no serial, batch, or name
    first = api.save_cell_instance(dict(draft), source_root=root)
    second = api.save_cell_instance(dict(draft), source_root=root)
    assert first["id"] != second["id"], "anonymous records must never silently dedup"
    assert first["status"] == second["status"] == "created"


def test_named_test_spec_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "examples"
    draft = {"name": "1C cycling at 25C", "kind": "cycling", "version": "1.0"}
    first = api.save_test_spec(dict(draft), source_root=root)
    again = api.save_test_spec(dict(draft), source_root=root, duplicate_policy="return_existing")
    assert again["id"] == first["id"]
    assert again["status"] == "exists"


def test_explicit_uid_still_wins(tmp_path: Path) -> None:
    root = tmp_path / "examples"
    record = api.save_cell_spec({**SPEC_FIELDS, "uid": "7d9k2m4p8t3x6nq5"}, source_root=root)
    assert record["id"].endswith("7d9k-2m4p-8t3x-6nq5")


CELL_SPEC_IRI = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"


def test_cell_seed_takes_the_serial_before_the_name() -> None:
    from battinfo.entities import cell_instance_identity_seed as seed

    # A cell with a serial is seeded from the serial, whatever its name.
    assert seed(cell_spec_id=CELL_SPEC_IRI, serial_number="S1", name="Cell A") == f"{CELL_SPEC_IRI}::S1::::S1"
    assert seed(cell_spec_id=CELL_SPEC_IRI, serial_number="S1", name="Renamed") == f"{CELL_SPEC_IRI}::S1::::S1"
    # Cells without a serial keep the seeds they had before the change.
    assert seed(cell_spec_id=CELL_SPEC_IRI, serial_number="S1") == f"{CELL_SPEC_IRI}::S1::::S1"
    assert seed(cell_spec_id=CELL_SPEC_IRI, name="Cell A") == f"{CELL_SPEC_IRI}::::::Cell A"
    assert seed(cell_spec_id=CELL_SPEC_IRI, batch_id="B7", name="Cell A") == f"{CELL_SPEC_IRI}::::B7::Cell A"
    assert seed(cell_spec_id=CELL_SPEC_IRI, batch_id="B7") == f"{CELL_SPEC_IRI}::::B7::B7"
    assert seed(cell_spec_id=CELL_SPEC_IRI) is None


def test_renaming_a_saved_cell_with_a_serial_keeps_its_iri(tmp_path: Path) -> None:
    root = tmp_path / "examples"
    spec = api.save_cell_spec(dict(SPEC_FIELDS), source_root=root)
    first = api.save_cell_instance(
        {"cell_spec_id": spec["id"], "serial_number": "LAB-0001", "name": "Cell A"},
        source_root=root,
    )
    renamed = api.save_cell_instance(
        {"cell_spec_id": spec["id"], "serial_number": "LAB-0001", "name": "Graphite AQ-1 cell A"},
        source_root=root,
        mode="upsert",
    )
    assert renamed["id"] == first["id"], "a new display name must not mint a new cell"


def test_every_cell_surface_mints_one_iri_for_one_serial(tmp_path: Path) -> None:
    root = tmp_path / "examples"
    spec = api.save_cell_spec(dict(SPEC_FIELDS), source_root=root)
    saved = api.save_cell_instance(
        {"cell_spec_id": spec["id"], "serial_number": "LAB-0002", "name": "Cell B"},
        source_root=root,
    )
    created = api.create_cell_instance(
        cell_spec_id=spec["id"], serial_number="LAB-0002", source_root=root
    )
    assert created["cell_instance"]["id"] == saved["id"]


def test_workspace_rename_with_a_serial_keeps_the_iri(tmp_path: Path) -> None:
    import json

    import battinfo

    def minted(folder: str, name: str) -> str:
        ws = battinfo.workspace(tmp_path / folder, registry_url=None)
        spec = battinfo.CellSpec(
            manufacturer="Example Lab", model="R2032 graphite half cell",
            format="coin", chemistry="li-ion",
        )
        ws.add("cell", spec=spec, names=[name], serial_numbers=["C01"])
        ws.save()
        (path,) = (tmp_path / folder / ".battinfo" / "records" / "cell-instance").glob("*.json")
        return json.loads(path.read_text(encoding="utf-8"))["cell_instance"]["id"]

    assert minted("first", "Cell one") == minted("second", "Graphite AQ-1 cell C01")
