from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

import battinfo.api as api

ROOT = Path(__file__).resolve().parents[1]


def _schema_registry(schema_root: Path) -> Registry:
    registry = Registry()
    for path in sorted(schema_root.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        schema_id = doc.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, Resource.from_contents(doc))
    return registry


def _validate_examples(schema_file: str, examples_subdir: str) -> None:
    schema_root = ROOT / "src" / "battinfo" / "data" / "schemas"
    schema_doc = json.loads((schema_root / schema_file).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema_doc, registry=_schema_registry(schema_root))

    examples_dir = ROOT / "examples" / examples_subdir
    example_paths = sorted(examples_dir.glob("*.json"))
    assert example_paths, f"No examples found in {examples_dir}"
    for example_path in example_paths:
        doc = json.loads(example_path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
        assert not errors, f"{example_path} failed validation: {errors[0].message}"


def test_material_spec_examples_validate_against_normative_schema() -> None:
    _validate_examples("material-spec.schema.json", "material-spec")


def test_material_examples_validate_against_normative_schema() -> None:
    _validate_examples("material.schema.json", "material")


def _assert_synced(schema_file: str, examples_subdir: str) -> None:
    assets_schema = ROOT / "assets" / "schemas" / schema_file
    package_schema = ROOT / "src" / "battinfo" / "data" / "schemas" / schema_file
    assert json.loads(assets_schema.read_text(encoding="utf-8")) == json.loads(
        package_schema.read_text(encoding="utf-8")
    )

    repo_examples = ROOT / "examples" / examples_subdir
    package_examples = ROOT / "src" / "battinfo" / "data" / "examples" / examples_subdir
    repo_files = sorted(path.name for path in repo_examples.glob("*.json"))
    package_files = sorted(path.name for path in package_examples.glob("*.json"))
    assert repo_files == package_files
    for filename in repo_files:
        assert json.loads((repo_examples / filename).read_text(encoding="utf-8")) == json.loads(
            (package_examples / filename).read_text(encoding="utf-8")
        )


def test_material_schemas_and_examples_synced_between_assets_and_package() -> None:
    _assert_synced("material-spec.schema.json", "material-spec")
    _assert_synced("material.schema.json", "material")


def test_material_specs_cover_key_chemistries() -> None:
    examples_dir = ROOT / "examples" / "material-spec"
    observed = {
        json.loads(path.read_text(encoding="utf-8"))["material_spec"]["name"]
        for path in sorted(examples_dir.glob("*.json"))
    }
    expected = {"Graphite", "LFP", "NMC811", "LCO", "LMFP", "LNMO", "Zinc", "Carbon black", "PVDF", "KOH"}
    assert expected.issubset(observed), f"missing: {expected - observed}"


def test_material_spec_and_instance_roundtrip(tmp_path: Path) -> None:
    spec = api.create_material_spec(
        uid="abcd23456789abcd",
        name="LFP",
        material_class="active_material",
        electrode_polarity="positive",
        formula="LiFePO4",
        property={"specific_capacity": {"value": 160, "unit": "mAh/g"}},
    )
    spec_id = spec["material_spec"]["id"]
    assert spec_id.startswith("https://w3id.org/battinfo/material-spec/")

    saved_spec = api.save_material_spec(spec, source_root=tmp_path)
    assert saved_spec["status"] == "created"
    assert saved_spec["entity_type"] == "material-spec"

    material = api.create_material(uid="1234abcd5678ef90", material_spec_id=spec_id, lot_id="LOT-1")
    saved_material = api.save_material(material, source_root=tmp_path)  # resolves spec reference
    assert saved_material["entity_type"] == "material"

    assert [s["name"] for s in api.query_material_specs(directory=tmp_path / "material-spec")] == ["LFP"]
    assert [m["lot_id"] for m in api.query_materials(directory=tmp_path / "material")] == ["LOT-1"]

    index = api.build_index(source_root=tmp_path)
    assert index["material_spec_count"] == 1
    assert index["material_count"] == 1


def test_material_instance_missing_spec_reference_is_flagged(tmp_path: Path) -> None:
    from battinfo.validate.record import validate_record

    material = api.create_material(
        material_spec_id="https://w3id.org/battinfo/material-spec/0000-0000-0000-0000",
        lot_id="ORPHAN",
        validate=False,
    )
    # Reference existence is checked when a source_root is supplied.
    result = validate_record(material, source_root=tmp_path)
    assert not result.ok
    assert any(issue.code == "reference.missing" for issue in result.issues)


def test_material_instance_resolves_existing_spec_reference(tmp_path: Path) -> None:
    from battinfo.validate.record import validate_record

    spec = api.create_material_spec(uid="abcd23456789abcd", name="LFP", material_class="active_material")
    api.save_material_spec(spec, source_root=tmp_path)
    material = api.create_material(uid="1234abcd5678ef90", material_spec_id=spec["material_spec"]["id"], lot_id="LOT-1")
    api.save_material(material, source_root=tmp_path)

    result = validate_record(material, source_root=tmp_path)
    assert result.ok, result.errors


def test_material_property_conditions_emit_measurement_parameters() -> None:
    from battinfo.transform.json_to_jsonld import to_jsonld

    rec = api.create_material_spec(
        uid="abcd23456789abcd", name="LFP", material_class="active_material", formula="LiFePO4",
        property={"specific_capacity": {"value": 160, "unit": "mAh/g", "co_type": "Measured",
                                        "conditions": {"discharge_c_rate": {"value": 0.1, "unit": "C"},
                                                       "lower_voltage_limit": {"value": 2.5, "unit": "V"},
                                                       "temperature": {"value": 25, "unit": "degC"}}}},
    )
    node = to_jsonld(rec, target="domain-battery")["@graph"][0]
    assert node["@type"] == "LithiumIronPhosphate"
    props = node["hasProperty"]
    cap = props if isinstance(props, dict) else props[0]
    assert "SpecificCapacity" in cap["@type"] and "MeasuredProperty" in cap["@type"]
    params = cap["hasMeasurementParameter"]
    labels = {p.get("rdfs:label") for p in params}
    assert {"discharge_c_rate", "lower_voltage_limit", "temperature"}.issubset(labels)


def test_material_property_out_of_range_warns() -> None:
    from battinfo.validate.semantic import validate_semantic_report

    rec = api.create_material_spec(uid="abcd23456789abcd", name="LFP",
                                   property={"specific_capacity": {"value": 16000, "unit": "mAh/g"}}, validate=False)
    report = validate_semantic_report(rec, policy="default")
    assert any(i.code == "semantic.value_out_of_plausible_range" for i in report.issues)


def test_material_spec_composition_reference_resolves(tmp_path: Path) -> None:
    from battinfo.validate.record import validate_record

    base = api.create_material_spec(uid="base23456789abcd", name="NMC811", material_class="active_material")
    api.save_material_spec(base, source_root=tmp_path)
    coated = api.create_material_spec(
        uid="coat23456789abcd", name="Al2O3-coated NMC811", material_class="active_material",
        composition={"base_material_id": base["material_spec"]["id"]},
    )
    api.save_material_spec(coated, source_root=tmp_path)
    assert validate_record(coated, source_root=tmp_path).ok


def test_material_instance_dataset_link_reference_checked(tmp_path: Path) -> None:
    from battinfo.validate.record import validate_record

    spec = api.create_material_spec(uid="abcd23456789abcd", name="LFP")
    api.save_material_spec(spec, source_root=tmp_path)
    material = api.create_material(
        uid="1234abcd5678ef90", material_spec_id=spec["material_spec"]["id"], lot_id="LOT-1",
        dataset_ids=["https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x"], validate=False,
    )
    # The dataset is not registered, so the link is flagged.
    result = validate_record(material, source_root=tmp_path)
    assert any(i.code == "reference.missing" and "datasets" in i.path for i in result.issues)


def test_material_manufacturer_coerced_to_organization() -> None:
    rec = api.create_material_spec(uid="abcd23456789abcd", name="LFP", manufacturer="Canrud")
    mfr = rec["material_spec"]["manufacturer"]
    assert mfr == {"type": "Organization", "name": "Canrud"}
