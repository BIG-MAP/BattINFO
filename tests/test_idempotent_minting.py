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

import pytest

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
    created = api.create_cell_instance(cell_spec_id=spec["id"], serial_number="LAB-0002", source_root=root)
    assert created["cell_instance"]["id"] == saved["id"]


def test_workspace_rename_with_a_serial_keeps_the_iri(tmp_path: Path) -> None:
    import json

    import battinfo

    def minted(folder: str, name: str) -> str:
        ws = battinfo.workspace(tmp_path / folder, registry_url=None)
        spec = battinfo.CellSpec(
            manufacturer="Example Lab",
            model="R2032 graphite half cell",
            format="coin",
            chemistry="li-ion",
        )
        ws.add("cell", spec=spec, names=[name], serial_numbers=["C01"])
        ws.save()
        (path,) = (tmp_path / folder / ".battinfo" / "records" / "cell-instance").glob("*.json")
        return json.loads(path.read_text(encoding="utf-8"))["cell_instance"]["id"]

    assert minted("first", "Cell one") == minted("second", "Graphite AQ-1 cell C01")


# ── Parity: one identity, one IRI, on every minting path ──────────────────────
#
# The workspace (ws.add and the engine behind it), the create_* builders, the
# save_* functions, a save of a record without an id (save_record), the
# publication package and the embedded-to-standalone bridges mint the same cell,
# material-spec and electrode-spec IRI for the same identity.


def _without_id_save(body_key: str, body: dict, root: Path) -> str:
    from battinfo.bundle import SCHEMA_VERSION

    doc = {"schema_version": SCHEMA_VERSION, body_key: body}
    return api.save_record(doc, source_root=root, validate=False, dry_run=True, resolve_references=False)["id"]


MATERIAL_SPEC_IDENTITIES = {
    "kind key": {"name": "Graphite SLP30", "kind": "graphite", "manufacturer": "Imerys", "product_id": "SLP30"},
    "kind alias": {"name": "Graphite SLP30", "kind": "Graphite", "manufacturer": "Imerys", "product_id": "SLP30"},
    "kind from the name": {"name": "Graphite"},
    "grade": {"name": "NMC811", "kind": "NMC 811", "manufacturer": "Targray", "grade": "SNMC03008"},
}


@pytest.mark.parametrize("case", sorted(MATERIAL_SPEC_IDENTITIES))
def test_every_path_mints_one_material_spec_iri(case: str, tmp_path: Path) -> None:
    import battinfo

    fields = MATERIAL_SPEC_IDENTITIES[case]
    ws = battinfo.workspace(tmp_path / "ws", registry_url=None)
    iris = {
        "ws": ws.add("material_spec", **fields)[0]["material_spec"]["id"],
        "create": api.create_material_spec(validate=False, **fields)["material_spec"]["id"],
        "save": api.save_material_spec(dict(fields), source_root=tmp_path / "save", validate=False)["id"],
        "save_record": _without_id_save(
            "material_spec",
            {**fields, "manufacturer": {"type": "Organization", "name": fields["manufacturer"]}}
            if "manufacturer" in fields
            else dict(fields),
            tmp_path / "save-record",
        ),
    }
    assert len(set(iris.values())) == 1, iris


def test_the_material_bridge_mints_the_material_spec_iri(tmp_path: Path) -> None:
    import battinfo
    from battinfo.materials import material_spec_from_component

    ws = battinfo.workspace(tmp_path, registry_url=None)
    holder = {"name": "Graphite", "manufacturer": "Imerys", "product_id": "SLP30"}
    lifted = material_spec_from_component(holder)["material_spec"]["id"]
    assert lifted == ws.add("material_spec", **holder)[0]["material_spec"]["id"]
    assert lifted == api.create_material_spec(validate=False, **holder)["material_spec"]["id"]


ELECTRODE_SPEC_IDENTITIES = {
    "kind key": {"name": "Graphite anode", "active_material_kind": "graphite"},
    "kind alias": {"name": "Graphite anode", "active_material_kind": "Graphite"},
    "kind from the name": {"name": "LFP"},
    "producer and route": {
        "name": "Si-Gr anode",
        "active_material_kind": "Si-Gr",
        "manufacturer": "SINTEF",
        "product_id": "SG-1",
        "processing": {"route": "aqueous"},
    },
}


@pytest.mark.parametrize("case", sorted(ELECTRODE_SPEC_IDENTITIES))
def test_every_path_mints_one_electrode_spec_iri(case: str, tmp_path: Path) -> None:
    import battinfo

    fields = ELECTRODE_SPEC_IDENTITIES[case]
    ws = battinfo.workspace(tmp_path / "ws", registry_url=None)
    body = dict(fields)
    if "manufacturer" in body:
        body["manufacturer"] = {"type": "Organization", "name": body["manufacturer"]}
    iris = {
        "ws": ws.add("electrode_spec", **fields)[0]["electrode_spec"]["id"],
        "create": api.create_electrode_spec(validate=False, **fields)["electrode_spec"]["id"],
        "save": api.save_electrode_spec(dict(fields), source_root=tmp_path / "save", validate=False)["id"],
        "save_record": _without_id_save("electrode_spec", body, tmp_path / "save-record"),
    }
    assert len(set(iris.values())) == 1, iris


def test_the_component_bridge_lifts_electrodes_through_the_electrode_spec_builder() -> None:
    from battinfo.components import extract_component_specs

    record = {
        "cell_spec": {"name": "Example cell"},
        "positive_electrode": {
            "manufacturer": "SINTEF",
            "product_id": "LFP-1",
            "coating": {"component": {"active_material": [{"name": "LFP"}], "binder": [{"name": "PVDF"}]}},
        },
        "negative_electrode": {"coating": {"component": {"active_material": [{"name": "Graphite"}]}}},
    }
    lifted = {spec["electrode_spec"]["name"]: spec["electrode_spec"] for spec in extract_component_specs(record)}
    positive = lifted["Example cell positive electrode"]
    negative = lifted["Example cell negative electrode"]
    # The active material's kind is read from the coating, and the IRI is the
    # one the electrode-spec builder gives the same identity.
    assert positive["active_material_kind"] == "lfp"
    assert negative["active_material_kind"] == "graphite"
    expected = api.create_electrode_spec(
        validate=False,
        name="Example cell positive electrode",
        active_material_kind="lfp",
        manufacturer="SINTEF",
        product_id="LFP-1",
    )["electrode_spec"]["id"]
    assert positive["id"] == expected
    assert (
        negative["id"]
        == (
            api.create_electrode_spec(
                validate=False, name="Example cell negative electrode", active_material_kind="graphite"
            )["electrode_spec"]["id"]
        )
    )


def test_a_save_without_an_id_refuses_an_unknown_kind_as_the_builders_do(tmp_path: Path) -> None:
    body = {"name": "Mystery powder", "kind": "unobtainium"}
    with pytest.raises(ValueError, match="Unknown material kind 'unobtainium'"):
        api.create_material_spec(validate=False, **body)
    with pytest.raises(ValueError, match="Unknown material kind 'unobtainium'"):
        _without_id_save("material_spec", body, tmp_path)
    electrode = {"name": "Mystery electrode", "active_material_kind": "unobtainium"}
    with pytest.raises(ValueError, match="Unknown electrode kind 'unobtainium'"):
        api.create_electrode_spec(validate=False, **electrode)
    with pytest.raises(ValueError, match="Unknown electrode kind 'unobtainium'"):
        _without_id_save("electrode_spec", electrode, tmp_path)


CELL_IDENTITIES = {
    "serial and name": {"serial_number": "S1", "name": "Cell A"},
    "serial, batch and name": {"serial_number": "S2", "batch_id": "B7", "name": "Cell B"},
    "serial": {"serial_number": "S3"},
    "name": {"name": "Cell C"},
    "batch": {"batch_id": "B8"},
    "batch and name": {"batch_id": "B9", "name": "Cell D"},
}


def _publication_cell_iri(root: Path, **fields: str) -> str:
    """The IRI the publication package (build_publication_package, publish) mints for a cell."""
    from battinfo.bundle import Cell, CellSpec, Dataset, Test
    from battinfo.publication import _finalize_publication_bundle

    run = root / "run1"
    run.mkdir(parents=True, exist_ok=True)
    bundle, _ = _finalize_publication_bundle(
        cell_spec=CellSpec(id=CELL_SPEC_IRI, **SPEC_FIELDS),
        cell_instance=Cell(cell_spec_id=CELL_SPEC_IRI, **fields),
        test=Test(test_kind="cycling"),
        dataset=Dataset(dataset_path=str(run)),
    )
    return str(bundle.cell_instance.id)


@pytest.mark.parametrize("case", sorted(CELL_IDENTITIES))
def test_every_path_mints_one_cell_iri(case: str, tmp_path: Path) -> None:
    import battinfo
    from battinfo.bundle import CellSpec

    fields = CELL_IDENTITIES[case]
    engine = Workspace(tmp_path / "engine")
    cell = engine.cell(CellSpec(id=CELL_SPEC_IRI, **SPEC_FIELDS), **fields)
    engine.render()
    iris = {
        "engine": str(cell.id),
        "save": api.save_cell_instance(
            {"cell_spec_id": CELL_SPEC_IRI, **fields}, source_root=tmp_path / "save", resolve_references=False
        )["id"],
        "save_record": _without_id_save("cell_instance", {"cell_spec_id": CELL_SPEC_IRI, **fields}, tmp_path / "rec"),
        "publication": _publication_cell_iri(tmp_path / "publication", **fields),
    }
    if "batch_id" not in fields:  # ws.add("cell") takes names and serial numbers
        ws = battinfo.workspace(tmp_path / "ws", registry_url=None)
        names = [fields["name"]] if "name" in fields else None
        serials = [fields["serial_number"]] if "serial_number" in fields else None
        (added,) = ws.add("cell", spec=CellSpec(id=CELL_SPEC_IRI, **SPEC_FIELDS), names=names, serial_numbers=serials)
        ws._ws.render()  # mints the IRIs a ws.save() writes
        iris["ws"] = str(added.id)
    if set(fields) == {"serial_number"}:  # create_cell_instance takes a serial number only
        iris["create"] = api.create_cell_instance(
            cell_spec_id=CELL_SPEC_IRI, serial_number=fields["serial_number"], validate=False
        )["cell_instance"]["id"]
    assert len(set(iris.values())) == 1, iris


def test_renaming_a_cell_with_a_serial_keeps_its_iri_in_the_publication_package(tmp_path: Path) -> None:
    first = _publication_cell_iri(tmp_path / "a", serial_number="FAC-001", name="Cell A")
    renamed = _publication_cell_iri(tmp_path / "b", serial_number="FAC-001", name="Graphite AQ-1 cell FAC-001")
    assert first == renamed
