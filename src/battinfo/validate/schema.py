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

# profiles/batterypass.schema.json still ships, marked withdrawn, so that its
# published URL keeps resolving; it is not a validation profile since 0.8.0.
PROFILE_TO_SCHEMA = {
    "base": "battinfo.base.schema.json",
    "cell-spec": "cell-spec.schema.json",
    "cell-instance": "cell-instance.schema.json",
    "dataset": "dataset.schema.json",
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


# Parameter-set fields that belong to one flavour only (supersedes belongs to both).
_PARAMETER_FILE_ONLY = (
    "parts",
    "parameters_sha256",
    "virtual_cell",
    "cell_instance_id",
    "distributions",
    "not_imported",
)
_CLAIM_BATCH_ONLY = ("material_kind", "material_spec_id", "scope", "electrode_polarity")
_CELL_LINKS = ("cell_spec_id", "cell_instance_id", "virtual_cell")
_CLAIM_BATCH_TARGETS = ("material_kind", "material_spec_id", "cell_spec_id")


def _parameter_set_flavour_message(body: Any) -> str | None:
    """What makes a parameter-set body neither a claim batch nor a parameter file, in words.

    The schema states the two flavours as a ``oneOf``, whose own message is
    a dump of the whole record. The flavour is read off the body first
    (``parts`` or ``claims``), and the message says what that flavour lacks
    or must not carry.
    """
    if not isinstance(body, dict):
        return None
    if "parts" in body and "claims" in body:
        return (
            "a parameter set is either a claim batch (claims about one target) or a parameter "
            "file (parts), never both: this one carries claims and parts."
        )
    problems: list[str] = []
    if "parts" in body or ("claims" not in body and any(f in body for f in _PARAMETER_FILE_ONLY)):
        for needed in ("parts", "parameters_sha256"):
            if needed not in body:
                problems.append(f"it has no {needed}")
        links = [f for f in _CELL_LINKS if f in body]
        if not links:
            problems.append(
                "it names no cell: give exactly one of cell_spec_id (a cell spec), cell_instance_id "
                "(one physical cell) or virtual_cell: true (no real cell)"
            )
        elif len(links) > 1:
            problems.append(f"it links more than one cell ({', '.join(links)}): keep exactly one")
        stray = [f for f in _CLAIM_BATCH_ONLY if f in body]
        if stray:
            problems.append(
                f"{', '.join(stray)} {'belongs' if len(stray) == 1 else 'belong'} to a claim batch: "
                "a parameter file has no scope or "
                "target, and names each material on its material part"
            )
        what = "parameter file"
    elif "claims" in body:
        targets = [f for f in _CLAIM_BATCH_TARGETS if f in body]
        if not targets:
            problems.append("it names no target: give exactly one of material_kind, material_spec_id, cell_spec_id")
        elif len(targets) > 1:
            problems.append(f"it names more than one target ({', '.join(targets)}): keep exactly one")
        stray = [f for f in _PARAMETER_FILE_ONLY if f in body]
        if stray:
            problems.append(
                f"{', '.join(stray)} {'belongs' if len(stray) == 1 else 'belong'} to a parameter file "
                "(one BPX file, with parts), not to a "
                "claim batch"
            )
        what = "claim batch"
    else:
        return (
            "a parameter set carries claims (a claim batch about one target) or parts (a parameter "
            "file); this one carries neither."
        )
    if not problems:
        return f"this {what} matches neither parameter-set flavour."
    return f"this {what} is not valid: " + "; ".join(problems) + "."


def _contains_message(error: ValidationError) -> str | None:
    """A ``contains`` count error on a role-tagged array, naming the role and the count found."""
    schema = error.schema if isinstance(error.schema, dict) else {}
    contains = schema.get("contains")
    role = contains.get("properties", {}).get("role", {}).get("const") if isinstance(contains, dict) else None
    if not isinstance(role, str) or not isinstance(error.instance, list):
        return None
    found = sum(1 for item in error.instance if isinstance(item, dict) and item.get("role") == role)
    low, high = schema.get("minContains", 1), schema.get("maxContains")
    if low == high:
        return f"needs exactly {low} '{role}' entr{'y' if low == 1 else 'ies'}; found {found}."
    if high is not None and found > high:
        return f"holds at most {high} '{role}' entr{'y' if high == 1 else 'ies'}; found {found}."
    return f"needs at least {low} '{role}' entr{'y' if low == 1 else 'ies'}; found {found}."


def _enhance_message(error: ValidationError) -> str:
    msg = error.message
    if error.validator in ("contains", "minContains", "maxContains"):
        msg = _contains_message(error) or msg
    if error.validator == "oneOf" and isinstance(error.schema, dict):
        titles = {branch.get("title") for branch in error.schema.get("oneOf") or [] if isinstance(branch, dict)}
        if titles == {"Claim batch", "Parameter file"}:
            msg = _parameter_set_flavour_message(error.instance) or msg
    if error.validator == "anyOf" and list(error.path) == ["parameter_set", "id"]:
        msg = (
            f"{error.instance!r} is not a parameter-set IRI: parameter sets mint under "
            "https://w3id.org/battinfo/dataset/{uid} (IDENTIFIER_POLICY 6.3), and a "
            "https://w3id.org/battinfo/spec/{uid} IRI is accepted only for a record minted "
            "before 2026-10-11."
        )
    if error.validator == "additionalProperties" and list(error.path) == ["properties"]:
        msg += " Run 'battinfo properties list' to see all valid property names."
    if error.validator == "type" and error.validator_value == "number" and isinstance(error.instance, str):
        # A quantity's value took text before 0.8.0; say where the text goes now.
        description = error.schema.get("description", "") if isinstance(error.schema, dict) else ""
        msg = msg.rstrip(".") + ". Write the number without quotes"
        msg += "; text that is not a number belongs in value_text." if "value_text" in description else "."
    if error.validator in ("pattern", "maxLength") and list(error.path)[-1:] == ["handle"]:
        msg += (
            " A handle is lowercase ASCII segments joined by '/', each made of letters and"
            " digits separated by single hyphens, at most 120 characters"
            " (e.g. 'flores-ocv/graphite-aq-1-063b77-cell'); battinfo.naming.handle_for()"
            " builds one from structured parts."
        )
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
