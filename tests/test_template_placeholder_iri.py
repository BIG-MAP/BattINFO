"""Templates carry no placeholder IRI (evaluation finding C-01).

`battinfo template cell-instance` wrote `https://w3id.org/battinfo/cell/0000-0000-0000-0000`
as the record id; `battinfo save cell-instance` saved it as a real record and
strict and publisher validation passed it, so everyone following the
getting-started steps claimed the same IRI. The other templates did the same
for their kinds. No template now writes an all-zero IRI: the id is left out
unless a uid is given, and saving the filled-in record mints it. Validation
still rejects a record whose own IRI has the all-zero uid, under every policy,
as the backstop for drafts made from older templates.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from battinfo import CellSpec, TestSpec, api
from battinfo.api import save_cell_spec, save_record, template_cell_instance
from battinfo.cli import app
from battinfo.entities import kind_for_doc
from battinfo.validate import NAMED_POLICIES, validate_record_report

PLACEHOLDER_CELL = "https://w3id.org/battinfo/cell/0000-0000-0000-0000"
# What a save mints for a cell: its IRI under /id/1001/ (IRI ruling, decision 5).
CELL_IRI = re.compile(r"^https://w3id\.org/battinfo/id/1001/cell/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$")


def _cli(*args: str) -> dict:
    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def test_template_save_validate_mints_a_real_iri(tmp_path: Path) -> None:
    """The reproduction from the evaluation: template, save, validate."""
    root = tmp_path / "examples"
    spec = save_cell_spec(
        CellSpec(
            manufacturer="Energizer",
            model="CR2032",
            format="coin",
            chemistry="li-metal",
            properties={"nominal_capacity": {"value": 0.235, "unit": "Ah"}},
        ),
        source_root=root,
        build_jsonld=False,
        build_html=False,
    )
    draft = tmp_path / "draft.json"
    _cli("template", "cell-instance", "--cell-spec-id", spec["id"], "--out", str(draft))
    record = json.loads(draft.read_text(encoding="utf-8"))
    body = record["cell_instance"]
    assert "id" not in body and "short_id" not in body
    assert body["cell_spec_id"] == spec["id"]
    # Filled in as the template's note asks: the serial number is what the IRI is minted from.
    body["serial_number"] = "CR2032-001"
    draft.write_text(json.dumps(record), encoding="utf-8")

    saved = _cli("save", "cell-instance", "--input", str(draft), "--source-root", str(root))
    assert saved["status"] == "created"
    assert CELL_IRI.fullmatch(saved["id"]) and saved["id"] != PLACEHOLDER_CELL

    for policy in ("strict", "publisher"):
        report = _cli("validate", saved["path"], "--source-root", str(root), "--policy", policy, "--format", "json")
        assert report["ok"] is True, report


def test_template_still_pins_an_explicit_uid() -> None:
    record = template_cell_instance(
        cell_spec_id="https://w3id.org/battinfo/spec/pge5-wer6-2q82-v9k0", uid="1f8r6v2k9p4m3t7x"
    )
    assert record["cell_instance"]["id"] == "https://w3id.org/battinfo/id/1001/cell/1f8r-6v2k-9p4m-3t7x"
    assert "id" not in template_cell_instance()["cell_instance"]


def _placeholder_cell_record() -> dict:
    return {
        "schema_version": "0.2.0",
        "cell_instance": {
            "id": PLACEHOLDER_CELL,
            "short_id": "000000",
            "cell_spec_id": "https://w3id.org/battinfo/spec/8dzc-d9jz-12m6-cg03",
        },
        "provenance": {"source_type": "measurement", "retrieved_at": 1791730794},
    }


@pytest.mark.parametrize("policy", sorted(NAMED_POLICIES))
def test_validation_rejects_the_placeholder_uid_under_every_policy(policy: str) -> None:
    report = validate_record_report(_placeholder_cell_record(), policy=policy)
    assert not report.ok
    errors = [issue for issue in report.errors if issue.code == "identity.placeholder_iri"]
    assert len(errors) == 1
    assert errors[0].path == "cell_instance.id"
    assert "template placeholder" in errors[0].message


def test_placeholder_spec_iri_is_rejected_too() -> None:
    record = {
        "schema_version": "0.2.0",
        "cell_spec": {
            "id": "https://w3id.org/battinfo/spec/0000-0000-0000-0000",
            "name": "X Y",
            "manufacturer": {"type": "Organization", "name": "X"},
            "model": "Y",
            "cell_format": "coin",
            "chemistry": "li-ion",
        },
        "provenance": {"source_type": "manual", "retrieved_at": 1791730794},
    }
    report = validate_record_report(record, policy="ingest")
    assert any(issue.code == "identity.placeholder_iri" for issue in report.errors)


def test_save_and_cli_validate_refuse_the_placeholder(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="template placeholder"):
        save_record(
            _placeholder_cell_record(),
            source_root=tmp_path,
            resolve_references=False,
            build_jsonld=False,
            build_html=False,
        )
    path = tmp_path / "cell-0000-0000-0000-0000.json"
    path.write_text(json.dumps(_placeholder_cell_record()), encoding="utf-8")
    result = CliRunner().invoke(app, ["validate", str(path), "--policy", "ingest", "--format", "json"])
    assert result.exit_code != 0
    assert "template placeholder" in result.stdout


# ── Every template, Python and CLI ────────────────────────────────────────────

TEMPLATES = {
    "cell-spec": api.template_cell_spec,
    "cell-instance": api.template_cell_instance,
    "dataset": api.template_dataset,
    "test": api.template_test,
    "test-spec": api.template_test_spec,
    "library-cell-spec": api.template_library_cell_spec,
    "material-spec": api.template_material_spec,
    "material": api.template_material,
    "electrode-spec": api.template_electrode_spec,
    "electrode": api.template_electrode,
    "separator-spec": lambda **kw: api.template_component_spec("separator", **kw),
    "separator": lambda **kw: api.template_component_instance("separator", **kw),
    "parameter-set": api.template_parameter_set,
}


def _body(record: dict) -> dict:
    kind = kind_for_doc(record)
    return record[kind.record_key] if kind is not None else record["specification"]


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_no_template_writes_a_placeholder_iri(name: str) -> None:
    record = TEMPLATES[name]()
    assert "0000-0000-0000-0000" not in json.dumps(record)
    body = _body(record)
    assert not {"id", "short_id"} & set(body)
    assert "identifier" not in body


@pytest.mark.parametrize("name", sorted(TEMPLATES))
def test_a_uid_still_pins_the_template_iri(name: str) -> None:
    body = _body(TEMPLATES[name](uid="1f8r6v2k9p4m3t7x"))
    assert body["id"].endswith("/1f8r-6v2k-9p4m-3t7x")


def test_filled_templates_save_with_the_iri_their_fields_mint(tmp_path: Path) -> None:
    """Saving a filled-in template mints the IRI the same record gets from its builder."""
    root = tmp_path / "records"
    built_root = tmp_path / "built"
    spec_template = api.template_cell_spec(
        manufacturer="Energizer", model_name="CR2032", chemistry="li-metal", format="coin"
    )
    spec_saved = api.save_cell_spec(spec_template, source_root=root, build_jsonld=False, build_html=False)
    spec_built = api.save_cell_spec(
        CellSpec(manufacturer="Energizer", model="CR2032", format="coin", chemistry="li-metal"),
        source_root=built_root,
        build_jsonld=False,
        build_html=False,
    )
    assert spec_saved["id"] == spec_built["id"]

    protocol_saved = api.save_test_spec(
        api.template_test_spec(name="CC discharge", kind="capacity_check"),
        source_root=root,
        build_jsonld=False,
        build_html=False,
    )
    protocol_built = api.save_test_spec(
        TestSpec(name="CC discharge", kind="capacity_check", experiment=["Discharge at C/10 until 2.5 V"]),
        source_root=built_root,
        build_jsonld=False,
        build_html=False,
    )
    assert protocol_saved["id"] == protocol_built["id"]

    cell_template = api.template_cell_instance(cell_spec_id=spec_saved["id"])
    cell_template["cell_instance"]["serial_number"] = "S1"
    cell_saved = api.save_cell_instance(cell_template, source_root=root, build_jsonld=False, build_html=False)
    test_saved = api.save_test(
        api.template_test(cell_id=cell_saved["id"], name="S1 discharge"),
        source_root=root,
        build_jsonld=False,
        build_html=False,
    )
    dataset_saved = api.save_dataset(
        api.template_dataset(
            title="S1 data",
            related_cell_ids=[cell_saved["id"]],
            related_test_ids=[test_saved["id"]],
            access_url="https://zenodo.org/records/1/files/S1.csv",
        ),
        source_root=root,
        build_jsonld=False,
        build_html=False,
    )
    for saved in (cell_saved, test_saved, dataset_saved):
        assert saved["status"] == "created" and "0000-0000" not in saved["id"]
        record = json.loads(Path(saved["path"]).read_text(encoding="utf-8"))
        assert validate_record_report(record, source_root=root, policy="strict").ok
    dataset = json.loads(Path(dataset_saved["path"]).read_text(encoding="utf-8"))["dataset"]
    assert dataset["identifier"] == "dataset:" + dataset["id"].rsplit("/", 1)[1]


def test_filled_component_and_parameter_templates_mint_on_save(tmp_path: Path) -> None:
    root = tmp_path / "records"
    material_spec = api.save_material_spec(api.template_material_spec(name="Graphite SLP30"), source_root=root)
    material_template = api.template_material(material_spec_id=material_spec["id"])
    material_template["material"]["lot_id"] = "LOT-1"
    material = api.save_material(material_template, source_root=root)
    electrode_spec = api.save_electrode_spec(api.template_electrode_spec(name="Graphite anode sheet"), source_root=root)
    electrode_template = api.template_electrode(electrode_spec_id=electrode_spec["id"])
    electrode_template["electrode"]["batch_id"] = "B-1"
    electrode = api.save_electrode(electrode_template, source_root=root)
    parameter_set = api.save_parameter_set(api.template_parameter_set(), source_root=root)
    for saved in (material_spec, material, electrode_spec, electrode, parameter_set):
        assert saved["status"] == "created" and "0000-0000" not in saved["id"]
    # Deterministic kinds land on the IRI their builders mint for the same fields.
    assert material_spec["id"] == api.create_material_spec(name="Graphite SLP30")["material_spec"]["id"]
    assert material["id"] == api.create_material(material_spec_id=material_spec["id"], lot_id="LOT-1")["material"]["id"]
    # Saving the same filled-in template again hits the same record, not a second one.
    with pytest.raises(ValueError, match="already exists"):
        api.save_material(material_template, source_root=root)


def test_component_templates_need_a_uid(tmp_path: Path) -> None:
    """A component family has no natural key; a random IRI would duplicate on every re-run."""
    root = tmp_path / "records"
    with pytest.raises(ValueError, match=r"separator-spec records have no natural key.*give it a uid"):
        api.save_component_spec("separator", api.template_component_spec("separator"), source_root=root)
    spec = api.save_component_spec(
        "separator", api.template_component_spec("separator", uid="1f8r6v2k9p4m3t7x"), source_root=root
    )
    assert spec["status"] == "created" and spec["id"].endswith("/1f8r-6v2k-9p4m-3t7x")
    with pytest.raises(ValueError, match="give it a uid"):
        api.save_component_instance(
            "separator",
            api.template_component_instance("separator", spec_id=spec["id"]),
            source_root=root,
        )


def test_library_template_mints_on_save(tmp_path: Path) -> None:
    record = api.template_library_cell_spec(
        manufacturer="Energizer", model="CR2032", chemistry="li-metal", format="coin"
    )
    assert "id" not in record["specification"]
    saved = api.save_library_cell_spec(record, library_root=tmp_path / "library", package_root=tmp_path / "package")
    assert saved["status"] == "created" and "0000-0000" not in saved["id"]


def test_library_save_refuses_an_old_placeholder_id(tmp_path: Path) -> None:
    record = api.template_library_cell_spec(
        manufacturer="Energizer", model="CR2032", chemistry="li-metal", format="coin", uid="0000000000000000"
    )
    with pytest.raises(ValueError, match="template placeholder"):
        api.save_library_cell_spec(record, library_root=tmp_path / "library", package_root=tmp_path / "package")


@pytest.mark.parametrize(
    ("command", "key"),
    [
        (["template", "cell-spec"], "cell_spec"),
        (["template", "cell-instance"], "cell_instance"),
        (["template", "dataset"], "dataset"),
        (["template", "test-spec"], "test_spec"),
        (["template", "test"], "test"),
        (["library", "template", "cell-spec"], "specification"),
    ],
)
def test_cli_templates_write_no_placeholder_iri(command: list[str], key: str) -> None:
    record = _cli(*command, "--format", "json")
    assert "0000-0000-0000-0000" not in json.dumps(record)
    assert "id" not in record[key]
    pinned = _cli(*command, "--uid", "1f8r6v2k9p4m3t7x", "--format", "json")
    assert pinned[key]["id"].endswith("/1f8r-6v2k-9p4m-3t7x")


def test_cli_cell_spec_template_saves_with_a_minted_iri(tmp_path: Path) -> None:
    draft = tmp_path / "spec.json"
    _cli(
        "template",
        "cell-spec",
        "--manufacturer",
        "Energizer",
        "--model-name",
        "CR2032",
        "--chemistry",
        "li-metal",
        "--cell-format",
        "coin",
        "--out",
        str(draft),
    )
    saved = _cli("save", "cell-spec", "--input", str(draft), "--source-root", str(tmp_path / "examples"))
    assert saved["status"] == "created" and "0000-0000" not in saved["id"]


# ── Save-time minting: deterministic or refused ──────────────────────────────


def test_a_saved_template_dataset_gets_the_builder_iri(tmp_path: Path) -> None:
    """template_dataset() lists its cells and tests as related ones, which the builder
    leaves out of the identity seed; saving the template mints the builder's IRI."""
    from battinfo import Dataset

    cell = "https://w3id.org/battinfo/cell/2435-kc9w-g9q0-1xsm"
    test = "https://w3id.org/battinfo/test/y4gj-dvk5-e8x4-3y3t"
    url = "https://zenodo.org/records/1/files/S1.csv"
    saved = api.save_dataset(
        api.template_dataset(title="S1 data", related_cell_ids=[cell], related_test_ids=[test], access_url=url),
        source_root=tmp_path / "template",
        resolve_references=False,
        build_jsonld=False,
        build_html=False,
    )
    built = api.save_dataset(
        Dataset(name="S1 data", related_cell_ids=[cell], related_test_ids=[test], access_url=url, source_type="other"),
        source_root=tmp_path / "builder",
        resolve_references=False,
        build_jsonld=False,
        build_html=False,
    )
    assert saved["id"] == built["id"]


def test_an_organization_without_an_id_gets_its_name_derived_iri(tmp_path: Path) -> None:
    from battinfo.api import create_organization

    record = create_organization(name="Example Lab", type="ResearchOrganization")
    expected = record["organization"].pop("id")
    record["organization"].pop("short_id")
    saved = save_record(record, source_root=tmp_path, build_jsonld=False, build_html=False)
    assert saved["id"] == expected


def test_a_channel_without_an_id_gets_its_equipment_and_index_iri(tmp_path: Path) -> None:
    from battinfo.api import create_channel

    record = create_channel(equipment_id="https://w3id.org/battinfo/equipment/1f8r-6v2k-9p4m-3t7x", index=3)
    expected = record["channel"].pop("id")
    record["channel"].pop("short_id")
    saved = save_record(record, source_root=tmp_path, resolve_references=False, build_jsonld=False, build_html=False)
    assert saved["id"] == expected


@pytest.mark.parametrize("kind", ["equipment-spec", "equipment"])
def test_equipment_without_an_id_is_refused(tmp_path: Path, kind: str) -> None:
    from battinfo.api import create_equipment, create_equipment_spec

    record = (
        create_equipment_spec(name="SkyRC MC3000", model="MC3000")
        if kind == "equipment-spec"
        else create_equipment(spec_id="https://w3id.org/battinfo/spec/1f8r-6v2k-9p4m-3t7x", serial_number="E1")
    )
    body = record[kind.replace("-", "_")]
    body.pop("id")
    body.pop("short_id")
    with pytest.raises(ValueError, match="give it a uid"):
        save_record(record, source_root=tmp_path, resolve_references=False, build_jsonld=False, build_html=False)


def test_a_cell_template_without_a_serial_is_refused(tmp_path: Path) -> None:
    template = template_cell_instance(cell_spec_id="https://w3id.org/battinfo/spec/pge5-wer6-2q82-v9k0")
    with pytest.raises(ValueError, match="fill in its serial_number, batch_id or name"):
        save_record(template, source_root=tmp_path, resolve_references=False, build_jsonld=False, build_html=False)
