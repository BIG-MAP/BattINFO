from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

import battinfo as bi
import battinfo.api as api
from battinfo.transform.json_to_jsonld import to_jsonld
from battinfo.validate.record import validate_record

ROOT = Path(__file__).resolve().parents[1]

# (base, record_key, family-arg, instance-create-wrapper, expected JSON-LD @type token)
FAMILIES = [
    ("electrode", "electrode", "electrode", "Electrode"),
    ("separator", "separator", "separator", "Separator"),
    ("current-collector", "current_collector", "current_collector", "CurrentCollector"),
    ("electrolyte", "electrolyte", "electrolyte", "Electrolyte"),
    ("housing", "housing", "housing", "Case"),
]


def _schema_registry(schema_root: Path) -> Registry:
    registry = Registry()
    for path in sorted(schema_root.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        schema_id = doc.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, Resource.from_contents(doc))
    return registry


def _validator(schema_file: str) -> Draft202012Validator:
    schema_root = ROOT / "src" / "battinfo" / "data" / "schemas"
    schema = json.loads((schema_root / schema_file).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=_schema_registry(schema_root))


@pytest.mark.parametrize("base,record_key,family,_type", FAMILIES)
@pytest.mark.parametrize("role", ["spec", "instance"])
def test_component_examples_validate(base, record_key, family, _type, role):
    schema_file = f"{base}-spec.schema.json" if role == "spec" else f"{base}.schema.json"
    examples_dir = ROOT / "examples" / (f"{base}-spec" if role == "spec" else base)
    if not examples_dir.exists():
        pytest.skip(f"no {role} examples for {base}")
    validator = _validator(schema_file)
    paths = sorted(examples_dir.glob("*.json"))
    assert paths, f"no examples in {examples_dir}"
    for path in paths:
        doc = json.loads(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
        assert not errors, f"{path} failed: {errors[0].message}"


@pytest.mark.parametrize("base,record_key,family,_type", FAMILIES)
@pytest.mark.parametrize("role", ["spec", "instance"])
def test_component_schemas_and_examples_synced(base, record_key, family, _type, role):
    schema_file = f"{base}-spec.schema.json" if role == "spec" else f"{base}.schema.json"
    assets = ROOT / "assets" / "schemas" / schema_file
    package = ROOT / "src" / "battinfo" / "data" / "schemas" / schema_file
    assert json.loads(assets.read_text(encoding="utf-8")) == json.loads(package.read_text(encoding="utf-8"))

    subdir = f"{base}-spec" if role == "spec" else base
    repo = ROOT / "examples" / subdir
    pkg = ROOT / "src" / "battinfo" / "data" / "examples" / subdir
    if not repo.exists():
        return
    repo_files = sorted(p.name for p in repo.glob("*.json"))
    assert repo_files == sorted(p.name for p in pkg.glob("*.json"))
    for fn in repo_files:
        assert json.loads((repo / fn).read_text(encoding="utf-8")) == json.loads((pkg / fn).read_text(encoding="utf-8"))


@pytest.mark.parametrize("base,record_key,family,type_token", FAMILIES)
def test_component_examples_reference_resolution(base, record_key, family, type_token):
    examples_dir = ROOT / "examples" / f"{base}-spec"
    for path in sorted(examples_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        result = validate_record(doc, source_root=ROOT / "examples")
        assert result.ok, f"{path}: {result.errors[:1]}"


@pytest.mark.parametrize("base,record_key,family,type_token", FAMILIES)
def test_component_jsonld_emits_expected_type(base, record_key, family, type_token):
    examples_dir = ROOT / "examples" / f"{base}-spec"
    path = sorted(examples_dir.glob("*.json"))[0]
    doc = json.loads(path.read_text(encoding="utf-8"))
    node = to_jsonld(doc, target="domain-battery")["@graph"][0]
    flat = json.dumps(node)
    assert type_token in flat, f"{base}: expected {type_token} in JSON-LD"


def test_component_spec_instance_roundtrip(tmp_path):
    # separator spec + instance through the generic API
    spec = bi.create_separator_spec(uid="sepa23456789abcd", name="Celgard 2400",
                                    body={"material": "polypropylene", "structure": "monolayer"})
    api.save_component_spec("separator", spec, source_root=tmp_path)
    inst = bi.create_separator(uid="seps23456789abcd", spec_id=spec["separator_spec"]["id"], lot_id="L1")
    api.save_component_instance("separator", inst, source_root=tmp_path)
    assert validate_record(inst, source_root=tmp_path).ok
    assert [s["name"] for s in bi.query_separator_specs(directory=tmp_path / "separator-spec")] == ["Celgard 2400"]
    assert [i["id"] for i in bi.query_separators(directory=tmp_path / "separator")]


def test_electrolyte_assembles_material_specs(tmp_path):
    # electrolyte-spec salt + solvents reference material-specs; missing ones are flagged
    spec = bi.create_electrolyte_spec(
        uid="elye23456789abcd", name="1M LiPF6 EC:EMC",
        body={"family": "organic",
              "salt": {"name": "LiPF6", "material_spec_id": "https://w3id.org/battinfo/material-spec/0000-0000-0000-0000"}},
        validate=False)
    result = validate_record(spec, source_root=tmp_path)
    assert any(i.code == "reference.missing" for i in result.issues)
