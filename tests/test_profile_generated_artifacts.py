from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


GENERATED_DIR = ROOT / "src" / "battinfo" / "data" / "profiles" / "cell-spec" / "generated"


def test_generated_profile_fragments_exist() -> None:
    filenames = [
        "top-level.schema.fragment.json",
        "specification-core.schema.fragment.json",
        "instance-reference.schema.fragment.json",
        "provenance.schema.fragment.json",
        "quantity.schema.fragment.json",
        "quantitative-properties.schema.fragment.json",
    ]
    for filename in filenames:
        path = GENERATED_DIR / filename
        assert path.exists(), f"Missing generated profile artifact {path}"


def test_generated_top_level_fragment_is_a_valid_schema_fragment() -> None:
    fragment = _load_json(GENERATED_DIR / "top-level.schema.fragment.json")
    assert "required" in fragment
    assert "properties" in fragment
    assert fragment.get("type") == "object"


def test_generated_specification_core_fragment_matches_schema_subset() -> None:
    fragment = _load_json(GENERATED_DIR / "specification-core.schema.fragment.json")
    schema = _load_json(ROOT / "assets" / "schemas" / "modules" / "components" / "specification.schema.json")

    assert fragment["required"] == schema["required"]
    assert fragment["properties"] == schema["properties"]
    assert fragment["additionalProperties"] == schema["additionalProperties"]
    assert fragment["type"] == schema["type"]


def test_generated_instance_reference_fragment_matches_schema() -> None:
    fragment = _load_json(GENERATED_DIR / "instance-reference.schema.fragment.json")
    schema = _load_json(ROOT / "assets" / "schemas" / "modules" / "components" / "cell-instance-reference.schema.json")

    comparable = {key: fragment[key] for key in ("type", "additionalProperties", "required", "properties")}
    expected = {key: schema[key] for key in ("type", "additionalProperties", "required", "properties")}
    assert comparable == expected


def test_generated_provenance_fragment_matches_schema() -> None:
    fragment = _load_json(GENERATED_DIR / "provenance.schema.fragment.json")
    schema = _load_json(ROOT / "assets" / "schemas" / "modules" / "common" / "provenance.schema.json")

    comparable = {key: fragment[key] for key in ("type", "additionalProperties", "required", "properties")}
    expected = {key: schema[key] for key in ("type", "additionalProperties", "required", "properties")}
    assert comparable == expected


def test_generated_quantity_fragment_matches_schema() -> None:
    fragment = _load_json(GENERATED_DIR / "quantity.schema.fragment.json")
    schema = _load_json(ROOT / "assets" / "schemas" / "modules" / "common" / "quantity.schema.json")

    comparable = {key: fragment[key] for key in ("type", "additionalProperties", "properties", "allOf")}
    expected = {key: schema[key] for key in ("type", "additionalProperties", "properties", "allOf")}
    assert comparable == expected


def test_generated_quantitative_properties_fragment_matches_schema() -> None:
    fragment = _load_json(GENERATED_DIR / "quantitative-properties.schema.fragment.json")
    schema = _load_json(ROOT / "assets" / "schemas" / "modules" / "common" / "quantitative-properties.schema.json")

    comparable = {key: fragment[key] for key in ("type", "patternProperties", "additionalProperties")}
    expected = {key: schema[key] for key in ("type", "patternProperties", "additionalProperties")}
    assert comparable == expected

