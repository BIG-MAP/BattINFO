from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str]


PROFILE_TO_SCHEMA = {
    "base": "battinfo.base.schema.json",
    "batterypass": "profiles/batterypass.schema.json",
}


@lru_cache(maxsize=1)
def _schema_registry() -> Registry:
    schema_root = resources.files("battinfo").joinpath("data", "schemas")
    resources_by_id: list[tuple[str, Resource]] = []
    for schema_path in schema_root.rglob("*.json"):
        with schema_path.open("r", encoding="utf-8") as handle:
            schema = json.load(handle)
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            resources_by_id.append((schema_id, Resource.from_contents(schema)))
    return Registry().with_resources(resources_by_id)


@lru_cache(maxsize=8)
def _schema_for_profile(profile: str) -> dict[str, Any]:
    rel_path = PROFILE_TO_SCHEMA[profile]
    schema_file = resources.files("battinfo").joinpath("data", "schemas", *rel_path.split("/"))
    with schema_file.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_json(data: dict[str, Any], profile: str = "base") -> ValidationResult:
    """Validate JSON input using profile-aware JSON Schema validation."""
    if profile not in PROFILE_TO_SCHEMA:
        return ValidationResult(
            ok=False,
            errors=[f"Unknown profile '{profile}'. Expected one of: {', '.join(PROFILE_TO_SCHEMA)}."],
        )

    schema = _schema_for_profile(profile)
    validator = Draft202012Validator(schema, registry=_schema_registry())
    errors = sorted(validator.iter_errors(data), key=lambda err: list(err.path))
    if not errors:
        return ValidationResult(ok=True, errors=[])

    rendered: list[str] = []
    for err in errors:
        loc = ".".join(str(part) for part in err.path)
        if loc:
            rendered.append(f"{loc}: {err.message}")
        else:
            rendered.append(err.message)
    return ValidationResult(ok=False, errors=rendered)
