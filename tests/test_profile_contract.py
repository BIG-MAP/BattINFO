from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


PROFILE_PATH = ROOT / "src" / "battinfo" / "data" / "profiles" / "battery-descriptor" / "profile.json"


def test_profile_asset_exists() -> None:
    assert PROFILE_PATH.exists(), "Missing packaged battery-descriptor profile asset"


def test_profile_top_level_contract_matches_descriptor_schema() -> None:
    profile = _load_json(PROFILE_PATH)
    schema = _load_json(ROOT / "assets" / "schemas" / "battery-descriptor.schema.json")

    assert profile["contract"]["top_level"]["required"] == schema["required"]
    assert sorted(profile["contract"]["top_level"]["optional"]) == sorted(
        set(schema["properties"]).difference(schema["required"])
    )


def test_profile_required_core_matches_specification_schema() -> None:
    profile = _load_json(PROFILE_PATH)
    specification_schema = _load_json(
        ROOT / "assets" / "schemas" / "modules" / "components" / "specification.schema.json"
    )

    assert profile["contract"]["specification"]["required_core"] == specification_schema["required"]


def test_profile_required_core_fields_have_field_bindings() -> None:
    profile = _load_json(PROFILE_PATH)
    bindings = profile["field_bindings"]

    for field in profile["contract"]["specification"]["required_core"]:
        key = f"specification.{field}"
        assert key in bindings, f"Missing field binding for {key}"

    for field in profile["contract"]["top_level"]["required"]:
        assert field in bindings or field == "specification", f"Missing top-level binding for {field}"


def test_profile_controlled_values_match_schema_and_entity_map() -> None:
    profile = _load_json(PROFILE_PATH)
    specification_schema = _load_json(
        ROOT / "assets" / "schemas" / "modules" / "components" / "specification.schema.json"
    )
    entity_type_map = _load_json(ROOT / "assets" / "mappings" / "domain-battery" / "entity_type_map.json")

    profile_values = profile["controlled_values"]["specification.format"]["values"]
    schema_values = specification_schema["properties"]["format"]["enum"]
    mapping_values = list(entity_type_map["mappings"]["format"].keys())

    assert profile_values == schema_values
    assert sorted(profile_values) == sorted(mapping_values)


def test_profile_references_current_mapping_assets() -> None:
    profile = _load_json(PROFILE_PATH)
    bindings = profile["field_bindings"]

    expected_paths = {
        "specification.format": "assets/mappings/domain-battery/entity_type_map.json#/mappings/format",
        "specification.chemistry": "assets/mappings/domain-battery/entity_type_map.json#/mappings/chemistry",
        "specification.positive_electrode_basis": (
            "assets/mappings/domain-battery/entity_type_map.json#/mappings/positive_electrode_basis"
        ),
        "specification.negative_electrode_basis": (
            "assets/mappings/domain-battery/entity_type_map.json#/mappings/negative_electrode_basis"
        ),
    }

    for field, expected in expected_paths.items():
        assert bindings[field]["binding_source"] == expected
