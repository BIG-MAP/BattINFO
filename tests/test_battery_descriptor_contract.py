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


def test_battery_descriptor_examples_validate_against_normative_schema() -> None:
    schema_root = ROOT / "src" / "battinfo" / "data" / "schemas"
    schema_path = schema_root / "battery-descriptor.schema.json"
    schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))

    registry = _schema_registry(schema_root)
    validator = Draft202012Validator(schema_doc, registry=registry)

    examples_dir = ROOT / "assets" / "examples" / "battery-descriptors"
    example_paths = sorted(examples_dir.glob("*.json"))
    assert example_paths, f"No battery-descriptor examples found in {examples_dir}"

    for example_path in example_paths:
        doc = json.loads(example_path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
        assert not errors, f"{example_path} failed validation: {errors[0].message}"


def test_battery_descriptor_schema_files_are_synced_between_assets_and_package() -> None:
    assets_root = ROOT / "assets" / "schemas"
    package_root = ROOT / "src" / "battinfo" / "data" / "schemas"

    tracked = [assets_root / "battery-descriptor.schema.json"]
    tracked.extend(sorted((assets_root / "modules" / "common").glob("*.json")))
    tracked.extend(sorted((assets_root / "modules" / "components").glob("*.json")))

    for src_path in tracked:
        rel = src_path.relative_to(assets_root)
        pkg_path = package_root / rel
        assert pkg_path.exists(), f"Missing packaged schema copy: {pkg_path}"

        src_doc = json.loads(src_path.read_text(encoding="utf-8"))
        pkg_doc = json.loads(pkg_path.read_text(encoding="utf-8"))
        assert src_doc == pkg_doc, f"Schema drift detected for {rel}"

