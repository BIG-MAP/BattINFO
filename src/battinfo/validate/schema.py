from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from battinfo.validate.core import DEFAULT_POLICY, ValidationIssue, ValidationPolicy, ValidationReport

if TYPE_CHECKING:  # jsonschema/referencing are imported lazily so `import battinfo` stays fast
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import ValidationError
    from referencing import Registry

PROFILE_TO_SCHEMA = {
    "base": "battinfo.base.schema.json",
    "cell-spec": "cell-spec.schema.json",
    "cell-instance": "cell-instance.schema.json",
    "dataset": "dataset.schema.json",
    "batterypass": "profiles/batterypass.schema.json",
    "test-protocol": "test-protocol.schema.json",
    "test": "test.schema.json",
    "material-spec": "material-spec.schema.json",
    "material": "material.schema.json",
    "electrode-spec": "electrode-spec.schema.json",
    "electrode": "electrode.schema.json",
    "separator-spec": "separator-spec.schema.json",
    "separator": "separator.schema.json",
    "current-collector-spec": "current-collector-spec.schema.json",
    "current-collector": "current-collector.schema.json",
    "electrolyte-spec": "electrolyte-spec.schema.json",
    "electrolyte": "electrolyte.schema.json",
    "housing-spec": "housing-spec.schema.json",
    "housing": "housing.schema.json",
}


@lru_cache(maxsize=1)
def _format_checker() -> Any:
    """Build the shared FormatChecker on first use (jsonschema imported lazily)."""
    from jsonschema import FormatChecker  # noqa: PLC0415

    checker = FormatChecker()
    checker.checks("date-time")(_check_date_time_format)
    checker.checks("uri")(_check_uri_format)
    return checker


def _check_date_time_format(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return True
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _check_uri_format(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return True
    parsed = urlparse(value)
    if not parsed.scheme:
        return False
    return bool(parsed.netloc or parsed.path)


@lru_cache(maxsize=1)
def schema_registry() -> "Registry":
    from referencing import Registry, Resource  # noqa: PLC0415

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
def schema_for_profile(profile: str) -> dict[str, Any]:
    rel_path = PROFILE_TO_SCHEMA[profile]
    schema_file = resources.files("battinfo").joinpath("data", "schemas", *rel_path.split("/"))
    with schema_file.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=16)
def schema_for_rel_path(rel_path: str) -> dict[str, Any]:
    schema_file = resources.files("battinfo").joinpath("data", "schemas", *rel_path.split("/"))
    with schema_file.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_validator(schema: dict[str, Any]) -> "Draft202012Validator":
    from jsonschema import Draft202012Validator  # noqa: PLC0415

    return Draft202012Validator(schema, registry=schema_registry(), format_checker=_format_checker())


def _render_path(error: ValidationError) -> str:
    return ".".join(str(part) for part in error.path)


def _validator_code(error: ValidationError) -> str:
    validator = error.validator or "unknown"
    if validator == "format":
        fmt = str(error.validator_value).replace("-", "_")
        return f"schema.format.{fmt}"
    return f"schema.{validator}"


def _enhance_message(error: ValidationError) -> str:
    msg = error.message
    if error.validator == "additionalProperties" and list(error.path) == ["properties"]:
        msg += " Run 'battinfo specs list' to see all valid property names."
    return msg


def _resource_type_from_profile(profile: str | None) -> str | None:
    if profile == "cell-spec":
        return "cell-spec"
    return None


def validate_schema_data(
    data: dict[str, Any],
    schema: dict[str, Any],
    *,
    profile: str | None = None,
    resource_type: str | None = None,
    policy: ValidationPolicy = DEFAULT_POLICY,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    validator = build_validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda err: list(err.path))
    resolved_resource_type = resource_type or _resource_type_from_profile(profile)
    for err in errors:
        issues.append(
            ValidationIssue(
                code=_validator_code(err),
                severity="error",
                path=_render_path(err),
                message=_enhance_message(err),
                validator=str(err.validator) if err.validator is not None else None,
                resource_type=resolved_resource_type,
                profile=profile,
            )
        )
    return ValidationReport(issues=tuple(issues), policy=policy)


def validate_profile(
    data: dict[str, Any],
    profile: str = "base",
    *,
    policy: ValidationPolicy = DEFAULT_POLICY,
) -> ValidationReport:
    if profile not in PROFILE_TO_SCHEMA:
        issue = ValidationIssue(
            code="schema.profile_unknown",
            severity="error",
            path="",
            message=f"Unknown profile '{profile}'. Expected one of: {', '.join(PROFILE_TO_SCHEMA)}.",
            validator="profile",
            profile=profile,
        )
        return ValidationReport(issues=(issue,), policy=policy)
    return validate_schema_data(data, schema_for_profile(profile), profile=profile, policy=policy)

