from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]


def _schema_registry(schema_root: Path) -> Registry:
    registry = Registry()
    for path in sorted(schema_root.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        schema_id = doc.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, Resource.from_contents(doc))
    return registry


def test_test_examples_validate_against_normative_schema() -> None:
    schema_root = ROOT / "src" / "battinfo" / "data" / "schemas"
    schema_path = schema_root / "test.schema.json"
    schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))

    registry = _schema_registry(schema_root)
    validator = Draft202012Validator(schema_doc, registry=registry)

    examples_dir = ROOT / "examples" / "tests"
    example_paths = sorted(examples_dir.glob("*.json"))
    assert example_paths, f"No test examples found in {examples_dir}"

    for example_path in example_paths:
        doc = json.loads(example_path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
        assert not errors, f"{example_path} failed validation: {errors[0].message}"


def test_test_schema_and_examples_are_synced_between_assets_and_package() -> None:
    assets_schema = ROOT / "assets" / "schemas" / "test.schema.json"
    package_schema = ROOT / "src" / "battinfo" / "data" / "schemas" / "test.schema.json"
    assert json.loads(assets_schema.read_text(encoding="utf-8")) == json.loads(package_schema.read_text(encoding="utf-8"))

    assets_examples = ROOT / "examples" / "tests"
    package_examples = ROOT / "src" / "battinfo" / "data" / "examples" / "tests"
    asset_files = sorted(path.name for path in assets_examples.glob("*.json"))
    package_files = sorted(path.name for path in package_examples.glob("*.json"))
    assert asset_files == package_files

    for filename in asset_files:
        assets_example = assets_examples / filename
        package_example = package_examples / filename
        assert json.loads(assets_example.read_text(encoding="utf-8")) == json.loads(
            package_example.read_text(encoding="utf-8")
        )


def test_test_examples_cover_alpha_hardening_kinds() -> None:
    examples_dir = ROOT / "examples" / "tests"
    observed = {
        json.loads(path.read_text(encoding="utf-8"))["test"]["kind"]
        for path in sorted(examples_dir.glob("*.json"))
    }
    expected = {"cycle_life", "rate_capability", "formation", "hppc", "ici", "gitt", "dcir", "eis"}
    assert expected.issubset(observed)

