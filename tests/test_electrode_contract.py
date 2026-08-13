"""Electrode record contract: examples validate, copies stay in sync, records round-trip.

The electrode counterpart of ``test_material_contract.py``. Electrode used to be
covered by ``test_component_contract.py``'s generic family sweep; it left that
sweep when it became first-class, so its contract is pinned here.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

import battinfo.api as api

ROOT = Path(__file__).resolve().parents[1]


def _load_script(script: str):
    spec = importlib.util.spec_from_file_location(script, ROOT / "scripts" / f"{script}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    example_paths = sorted((ROOT / "examples" / examples_subdir).glob("*.json"))
    assert example_paths, f"No examples found in examples/{examples_subdir}"
    for example_path in example_paths:
        doc = json.loads(example_path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
        assert not errors, f"{example_path} failed validation: {errors[0].message}"


def test_electrode_spec_examples_validate_against_normative_schema() -> None:
    _validate_examples("electrode-spec.schema.json", "electrode-spec")


def test_electrode_examples_validate_against_normative_schema() -> None:
    _validate_examples("electrode.schema.json", "electrode")


def _assert_synced(schema_file: str, examples_subdir: str) -> None:
    assets_schema = ROOT / "assets" / "schemas" / schema_file
    package_schema = ROOT / "src" / "battinfo" / "data" / "schemas" / schema_file
    assert json.loads(assets_schema.read_text(encoding="utf-8")) == json.loads(
        package_schema.read_text(encoding="utf-8")
    )

    repo_examples = ROOT / "examples" / examples_subdir
    package_examples = ROOT / "src" / "battinfo" / "data" / "examples" / examples_subdir
    repo_files = sorted(path.name for path in repo_examples.glob("*.json"))
    assert repo_files == sorted(path.name for path in package_examples.glob("*.json"))
    for filename in repo_files:
        assert json.loads((repo_examples / filename).read_text(encoding="utf-8")) == json.loads(
            (package_examples / filename).read_text(encoding="utf-8")
        )


def test_electrode_schemas_and_examples_synced_between_assets_and_package() -> None:
    _assert_synced("electrode-spec.schema.json", "electrode-spec")
    _assert_synced("electrode.schema.json", "electrode")


def test_every_example_carries_a_kind() -> None:
    """Kind is the aggregation axis; an example without one teaches the wrong thing."""
    from battinfo.electrodes import resolve_electrode_kind

    for path in sorted((ROOT / "examples" / "electrode-spec").glob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))["electrode_spec"]
        kind = body.get("kind")
        assert kind, f"{path.name} has no kind"
        assert resolve_electrode_kind(kind) == kind, f"{path.name} kind {kind!r} is not canonical"


def test_example_ids_are_content_derived() -> None:
    """Re-minting the corpus must be a no-op — the id says what the record is."""
    assert _load_script("migrate_electrode_ids").migrate(ROOT / "examples", write=False) == {}


def test_electrode_spec_and_batch_roundtrip(tmp_path: Path) -> None:
    spec = api.create_electrode_spec(
        name="NMC811 cathode", kind="nmc811", manufacturer="Canrud",
        composition={"active": 0.96,
                     "binder": {"name": "PVDF", "fraction": 0.02},
                     "additive": {"name": "Carbon black", "fraction": 0.02}},
        processing={"route": "nmp", "solvent": "NMP"},
        current_collector={"name": "Aluminium foil", "thickness": {"value": 15, "unit": "um"}},
        property={"loading": {"value": 21, "unit": "mg/cm2"}},
    )
    spec_id = spec["electrode_spec"]["id"]
    assert spec_id.startswith("https://w3id.org/battinfo/spec/")

    saved_spec = api.save_electrode_spec(spec, source_root=tmp_path)
    assert saved_spec["status"] == "created"
    assert saved_spec["entity_type"] == "electrode-spec"

    batch = api.create_electrode(electrode_spec_id=spec_id, batch="CATH-1", count=24)
    saved_batch = api.save_electrode(batch, source_root=tmp_path)  # resolves the spec reference
    assert saved_batch["entity_type"] == "electrode"

    assert [s["name"] for s in api.query_electrode_specs(source_root=tmp_path)] == ["NMC811 cathode"]
    assert [b["batch_id"] for b in api.query_electrodes(source_root=tmp_path)] == ["CATH-1"]
    assert api.query_electrode_specs(source_root=tmp_path, kind="nmc811")
    assert api.query_electrodes(source_root=tmp_path, electrode_spec_id=spec_id)

    index = api.build_index(source_root=tmp_path)
    assert index["electrode_spec_count"] == 1
    assert index["electrode_count"] == 1


def test_electrode_missing_spec_reference_is_flagged(tmp_path: Path) -> None:
    from battinfo.validate.record import validate_record

    batch = api.create_electrode(
        electrode_spec_id="https://w3id.org/battinfo/spec/0000-0000-0000-0000",
        batch="ORPHAN", validate=False,
    )
    result = validate_record(batch, source_root=tmp_path)
    assert not result.ok
    assert any(issue.code == "reference.missing" for issue in result.issues)


def test_electrode_spec_material_references_are_checked(tmp_path: Path) -> None:
    """A coating that names an unregistered material-spec is flagged, at any depth."""
    from battinfo.validate.record import validate_record

    spec = api.create_electrode_spec(
        name="Graphite anode", kind="graphite",
        active_material_spec_id="https://w3id.org/battinfo/spec/0000-0000-0000-0000",
        composition={"active": 0.95}, validate=False,
    )
    result = validate_record(spec, source_root=tmp_path)
    assert any(i.code == "reference.missing" for i in result.issues)


def test_electrode_manufacturer_coerced_to_organization() -> None:
    spec = api.create_electrode_spec(uid="abcd23456789abcd", name="LFP cathode", kind="lfp",
                                     manufacturer="Canrud")
    assert spec["electrode_spec"]["manufacturer"] == {"type": "Organization", "name": "Canrud"}
