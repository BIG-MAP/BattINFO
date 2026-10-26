"""The base new records mint under (IRI ruling of 22 October 2026, decision 5; BIG-MAP/BattINFO#482).

A uid never depends on the base. A workspace or batch folder records its
base when it is created, and new ones record ``https://w3id.org/battinfo/id/1001/``;
one that records none was created before the switch and keeps the old form,
``https://w3id.org/battinfo/{segment}/{uid}``, for good. The paths without a
container take ``base=``, by default ``/id/1001/``, and a folder that already
holds a record keeps that record's IRI. Seeds take a parent's IRI in the old
form, so adopting either form of a parent never moves a child.

``tests/test_golden_iris.py`` checks every minting path in both forms; this
module checks the containers and the rules around them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402
from battinfo import api  # noqa: E402
from battinfo.bundle import CellSpec  # noqa: E402
from battinfo.entities import seed_iri  # noqa: E402
from battinfo.namespace import (  # noqa: E402
    DEFAULT_RECORD_BASE,
    OLD_FORM_BASE,
    base_prefix,
    parse_record_iri,
    record_iri,
)

UID = "b6yn-0sxe-t2qk-9mjv"
SPEC_FIELDS = {"manufacturer": "Example Lab", "model": "R2032", "format": "coin", "chemistry": "li-ion"}


def _prefix(iri: str) -> str | None:
    parsed = parse_record_iri(iri)
    assert parsed is not None, iri
    return parsed.prefix


def _uid(iri: str) -> str:
    parsed = parse_record_iri(iri)
    assert parsed is not None, iri
    return parsed.uid


def _state(root: Path) -> dict[str, Any] | None:
    path = root / ".battinfo" / "workspace.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ── The helpers ─────────────────────────────────────────────────────────────


def test_base_prefix_reads_both_bases_and_refuses_anything_else() -> None:
    assert base_prefix(OLD_FORM_BASE) is None
    assert base_prefix(DEFAULT_RECORD_BASE) == "1001"
    assert DEFAULT_RECORD_BASE == "https://w3id.org/battinfo/id/1001/"
    for wrong in (
        "https://w3id.org/battinfo/id/1000/",  # definitions only
        "https://w3id.org/battinfo/id/1001",  # no trailing slash
        "https://w3id.org/battinfo/id/abc/",
        "https://example.org/",
        "",
    ):
        with pytest.raises(ValueError):
            base_prefix(wrong)


def test_a_seed_takes_a_record_iri_in_the_old_form() -> None:
    old = record_iri("spec", UID)
    assert seed_iri(record_iri("spec", UID, "1001")) == old
    assert seed_iri(record_iri("spec", UID, "1002")) == old
    assert seed_iri(old) == old
    for unchanged in (
        "https://w3id.org/battinfo/id/" + UID,  # a shared thing is not a record
        "https://example.org/id/1001/spec/" + UID,
        "C01",
        "",
    ):
        assert seed_iri(unchanged) == unchanged


# ── A workspace records its base when it is created ─────────────────────────


def test_a_new_workspace_records_1001_and_mints_under_it(tmp_path: Path) -> None:
    root = tmp_path / "lab"
    ws = battinfo.workspace(root, registry_url=None)
    assert ws.record_base == DEFAULT_RECORD_BASE
    assert _state(root) == {"schema_version": "0.1.0", "record_base": DEFAULT_RECORD_BASE}

    ws.add("cell", spec=CellSpec(**SPEC_FIELDS), serial_numbers=["C01"])
    ws.save()
    assert [_prefix(item.id) for item in [*ws._ws.cell_specs, *ws._ws.cells]] == ["1001", "1001"]

    again = battinfo.workspace(root, registry_url=None)
    assert again.record_base == DEFAULT_RECORD_BASE


def test_a_workspace_created_before_the_switch_keeps_the_old_form(tmp_path: Path) -> None:
    """A ``.battinfo/`` folder that records no base: opening it never writes one, and it mints the old form."""
    root = tmp_path / "lab"
    (root / ".battinfo").mkdir(parents=True)

    ws = battinfo.workspace(root, registry_url=None)
    assert ws.record_base == OLD_FORM_BASE
    assert _state(root) is None
    ws.add("cell", spec=CellSpec(**SPEC_FIELDS), serial_numbers=["C01"])
    ws.license("cc-by-4.0")
    ws.save()
    assert [_prefix(item.id) for item in [*ws._ws.cell_specs, *ws._ws.cells]] == [None, None]

    reopened = battinfo.workspace(root, registry_url=None)
    assert reopened.record_base == OLD_FORM_BASE
    assert "record_base" not in (_state(root) or {})


def test_a_new_workspace_can_keep_the_old_form(tmp_path: Path) -> None:
    root = tmp_path / "lab"
    ws = battinfo.workspace(root, registry_url=None, base=OLD_FORM_BASE)
    assert ws.record_base == OLD_FORM_BASE
    assert "record_base" not in (_state(root) or {})
    assert battinfo.workspace(root, registry_url=None).record_base == OLD_FORM_BASE


def test_a_workspace_keeps_its_base(tmp_path: Path) -> None:
    old = tmp_path / "old"
    (old / ".battinfo").mkdir(parents=True)
    with pytest.raises(ValueError, match="keeps its base"):
        battinfo.workspace(old, registry_url=None, base=DEFAULT_RECORD_BASE)
    assert battinfo.workspace(old, registry_url=None, base=OLD_FORM_BASE).record_base == OLD_FORM_BASE

    new = tmp_path / "new"
    battinfo.workspace(new, registry_url=None)
    with pytest.raises(ValueError, match="keeps its base"):
        battinfo.workspace(new, registry_url=None, base=OLD_FORM_BASE)
    with pytest.raises(ValueError, match="definitions only"):
        battinfo.workspace(tmp_path / "other", registry_url=None, base="https://w3id.org/battinfo/id/1000/")
    assert not (tmp_path / "other").exists()


def test_a_new_workspace_gives_a_cell_of_an_old_form_spec_the_uid_an_old_workspace_gives(tmp_path: Path) -> None:
    """The worked case of the ruling: a new workspace references a published spec and adds a cell."""
    old = battinfo.workspace(tmp_path / "old", registry_url=None, base=OLD_FORM_BASE)
    old.add("cell", spec=CellSpec(**SPEC_FIELDS), serial_numbers=["C01"])
    old.save()
    spec_iri, old_cell = old._ws.cell_specs[0].id, old._ws.cells[0].id
    assert _prefix(spec_iri) is None

    new = battinfo.workspace(tmp_path / "new", registry_url=None)
    new.add("cell", spec=CellSpec(id=spec_iri, **SPEC_FIELDS), serial_numbers=["C01"])
    (cell,) = new._ws._finalized_records()["cells"]

    assert cell.cell_spec_id == spec_iri  # referenced by the IRI it has
    assert cell.id == record_iri("cell", _uid(old_cell), "1001")


def test_a_record_minted_beside_the_other_form_of_its_iri_is_minted_again(tmp_path: Path) -> None:
    """Two forms of one uid are one record and one file, so a sibling minted onto the other form moves off it."""
    from battinfo._workspace import Workspace
    from battinfo.entities import cell_spec_uid

    uid = cell_spec_uid({**SPEC_FIELDS, "size_code": None})
    engine = Workspace(tmp_path / "engine")  # mints under /id/1001/
    pinned = CellSpec(
        id=record_iri("spec", uid), properties={"rated_capacity": {"value": 2.0, "unit": "Ah"}}, **SPEC_FIELDS
    )
    sibling = CellSpec(properties={"rated_capacity": {"value": 3.0, "unit": "Ah"}}, **SPEC_FIELDS)
    engine.add(pinned, sibling)

    first, second = engine._finalized_records()["cell_specs"]
    assert first.id == record_iri("spec", uid)
    assert _prefix(second.id) == "1001" and _uid(second.id) != uid


def test_a_cell_gets_one_uid_under_either_form_of_its_spec(tmp_path: Path) -> None:
    spec_old = record_iri("spec", UID)
    cells = [
        api.create_cell_instance(cell_spec_id=spec, serial_number="C01", validate=False, base=base)["cell_instance"][
            "id"
        ]
        for spec, base in (
            (spec_old, OLD_FORM_BASE),
            (record_iri("spec", UID, "1001"), OLD_FORM_BASE),
            (spec_old, DEFAULT_RECORD_BASE),
        )
    ]
    assert len({_uid(iri) for iri in cells}) == 1
    assert [_prefix(iri) for iri in cells] == [None, None, "1001"]


# ── Paths without a container ───────────────────────────────────────────────


def test_a_save_keeps_the_iri_a_folder_already_holds(tmp_path: Path) -> None:
    records = tmp_path / "records"
    first = api.save_cell_spec(dict(SPEC_FIELDS), source_root=records, base=OLD_FORM_BASE)
    assert _prefix(first["id"]) is None
    (path,) = (records / "cell-spec").glob("*.json")
    before = path.read_bytes()

    again = api.save_cell_spec(dict(SPEC_FIELDS), source_root=records, mode="upsert")
    assert again["id"] == first["id"]
    assert again["content_changed"] is False
    assert path.read_bytes() == before

    elsewhere = api.save_cell_spec(dict(SPEC_FIELDS), source_root=tmp_path / "fresh")
    assert elsewhere["id"] == record_iri("spec", _uid(first["id"]), "1001")


def test_a_save_of_the_1001_form_of_a_saved_record_keeps_the_old_form(tmp_path: Path) -> None:
    """An explicit /id/1001/ id beside a file of the old form adopts the saved IRI (#483)."""
    records = tmp_path / "records"
    saved = api.save_cell_spec(dict(SPEC_FIELDS), source_root=records, base=OLD_FORM_BASE)
    other_form = record_iri("spec", _uid(saved["id"]), "1001")
    (path,) = (records / "cell-spec").glob("*.json")
    before = path.read_bytes()

    again = api.save_cell_spec({"id": other_form, **SPEC_FIELDS}, source_root=records, mode="upsert")
    assert again["id"] == saved["id"]
    assert again["content_changed"] is False
    assert path.read_bytes() == before


def test_a_save_of_the_old_form_of_a_saved_record_names_the_iri_it_keeps(tmp_path: Path) -> None:
    """An explicit old-form id beside a file of the /id/1001/ form is refused, naming the saved IRI to use."""
    records = tmp_path / "records"
    saved = api.save_cell_spec(dict(SPEC_FIELDS), source_root=records)
    old_form = record_iri("spec", _uid(saved["id"]))
    (path,) = (records / "cell-spec").glob("*.json")
    before = path.read_bytes()

    with pytest.raises(ValueError) as refused:
        api.save_cell_spec({"id": old_form, **SPEC_FIELDS}, source_root=records, mode="upsert")
    message = str(refused.value)
    assert f"already holds this record as {saved['id']}" in message
    assert f"base={DEFAULT_RECORD_BASE!r}" in message
    assert "never reused across namespaces" not in message
    assert path.read_bytes() == before


def test_publish_with_force_keeps_the_iri_its_folder_held(tmp_path: Path) -> None:
    """force=True deletes the folder before the save, and the spec still keeps the IRI it was saved under."""
    root = tmp_path / "publish"
    first = battinfo.publish(CellSpec(**SPEC_FIELDS), destination="local", root=root, base=OLD_FORM_BASE)
    assert _prefix(first.canonical_iri) is None

    again = battinfo.publish(CellSpec(**SPEC_FIELDS), destination="local", root=root, force=True)
    assert again.canonical_iri == first.canonical_iri

    fresh = battinfo.publish(CellSpec(**SPEC_FIELDS), destination="local", root=tmp_path / "fresh")
    assert fresh.canonical_iri == record_iri("spec", _uid(first.canonical_iri), "1001")


def test_a_publication_keeps_the_iris_its_folder_already_holds(tmp_path: Path) -> None:
    from battinfo.bundle import Cell, Dataset, Test
    from battinfo.publication import publish

    run = tmp_path / "run1"
    run.mkdir()
    (run / "data.csv").write_text("time_s,voltage_V\n0,3.0\n", encoding="utf-8")

    def build(**base: str) -> dict[str, Any]:
        return publish(
            cell_spec=CellSpec(**SPEC_FIELDS),
            cell_instance=Cell(serial_number="P01"),
            test=Test(test_kind="cycling"),
            dataset=Dataset(dataset_path=str(run), name="P01 cycling", license="CC-BY-4.0"),
            validation_policy="default",
            **base,
        )

    first = build(base=OLD_FORM_BASE)
    keys = ("cell_spec_id", "cell_instance_id", "test_id", "dataset_id")
    assert {_prefix(first[key]) for key in keys} == {None}

    again = build()
    assert [again[key] for key in keys] == [first[key] for key in keys]

    (run / "battinfo.publish.jsonld").unlink()
    fresh = build()
    assert [fresh[key] for key in keys] == [record_iri(*_segment_uid(first[key]), "1001") for key in keys]


def _segment_uid(iri: str) -> tuple[str, str]:
    parsed = parse_record_iri(iri)
    assert parsed is not None
    return parsed.segment, parsed.uid


def test_a_parameter_file_takes_its_iri_in_either_form() -> None:
    from battinfo.api._parameters import parameter_file_issues, parameter_file_uid

    digest = "ab" * 32
    uid = parameter_file_uid(digest)
    for iri in (record_iri("dataset", uid), record_iri("dataset", uid, "1001")):
        body = {"id": iri, "parameters_sha256": digest, "parts": []}
        assert [issue for issue in parameter_file_issues(body) if issue[0] == "id_mismatch"] == []
    wrong = {"id": record_iri("dataset", UID, "1001"), "parameters_sha256": digest, "parts": []}
    assert [issue[0] for issue in parameter_file_issues(wrong)].count("id_mismatch") == 1


# ── Batch folders ───────────────────────────────────────────────────────────


def _batch_manifest(folder: Path) -> dict[str, Any]:
    return yaml.safe_load((folder / "batch.yaml").read_text(encoding="utf-8"))


def test_a_new_batch_records_1001(tmp_path: Path) -> None:
    from battinfo.contribution import init_batch

    made = init_batch(tmp_path / "batch", "Energizer CR2032", 1, serial_numbers=["C01"])
    assert _batch_manifest(tmp_path / "batch")["record_base"] == DEFAULT_RECORD_BASE
    (cell,) = made["cells"]
    assert _prefix(cell["cell_iri"]) == "1001"
    cell_manifest = yaml.safe_load((tmp_path / "batch" / cell["folder"] / "battinfo.yaml").read_text(encoding="utf-8"))
    assert cell_manifest["record_base"] == DEFAULT_RECORD_BASE


def test_a_batch_created_before_the_switch_keeps_the_old_form(tmp_path: Path) -> None:
    from battinfo.contribution import add_to_batch, init_batch

    folder = tmp_path / "batch"
    made = init_batch(folder, "Energizer CR2032", 1, serial_numbers=["C01"])
    manifest = _batch_manifest(folder)
    del manifest["record_base"]  # as a batch.yaml written before the switch
    (folder / "batch.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")

    added = add_to_batch(folder, 1, serial_numbers=["C02"])
    (new_cell,) = added["new_cells"]
    assert _prefix(new_cell["cell_iri"]) is None
    assert "record_base" not in _batch_manifest(folder)
    assert _prefix(made["cells"][0]["cell_iri"]) == "1001"  # the cell already made keeps its IRI

    with pytest.raises(ValueError, match="cannot change it"):
        init_batch(folder, "Energizer CR2032", 1, serial_numbers=["C03"], overwrite=True, base=DEFAULT_RECORD_BASE)


# ── Other containers ────────────────────────────────────────────────────────


def test_a_contribution_records_its_base(tmp_path: Path) -> None:
    from battinfo.contribution import init_contribution, load_contribution_manifest, recorded_record_base

    new = init_contribution(tmp_path / "new", cell_name="C01")
    manifest = load_contribution_manifest(new)
    assert recorded_record_base(manifest, where="battinfo.yaml") == DEFAULT_RECORD_BASE

    old = init_contribution(tmp_path / "old", cell_name="C01", base=OLD_FORM_BASE)
    assert "record_base" not in load_contribution_manifest(old)
    assert recorded_record_base(load_contribution_manifest(old), where="battinfo.yaml") == OLD_FORM_BASE


def test_a_local_workspace_records_its_base(tmp_path: Path) -> None:
    from battinfo.local_workspace import WORKSPACE_FILENAME, LocalWorkspace

    workspace = LocalWorkspace.init(tmp_path / "local")
    manifest_path = tmp_path / "local" / WORKSPACE_FILENAME
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["record_base"] == DEFAULT_RECORD_BASE
    records = workspace._normalize()["records"]
    assert _prefix(records["cell"]["cell_instance"]["id"]) == "1001"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["record_base"]  # a workspace created before the switch
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    old_records = workspace._normalize()["records"]
    assert _prefix(old_records["cell"]["cell_instance"]["id"]) is None
    assert _uid(old_records["cell"]["cell_instance"]["id"]) == _uid(records["cell"]["cell_instance"]["id"])
