from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources
from typing import Any, Mapping

from battinfo.canonical_aliases import record_to_legacy_aliases
from battinfo.validate.core import (
    DEFAULT_POLICY,
    ValidationIssue,
    ValidationPolicy,
    ValidationReport,
    ValidationResult,
    get_validation_policy,
)

SPEC_UNIT_COMPATIBILITY: dict[str, set[str]] = {
    "nominal_capacity": {"ah", "mah"},
    "minimum_capacity": {"ah", "mah"},
    "min_capacity": {"ah", "mah"},
    "rated_capacity": {"ah", "mah"},
    "typical_energy": {"wh", "kwh", "mwh"},
    "rated_energy": {"wh", "kwh", "mwh"},
    "nominal_voltage": {"v", "mv"},
    "charging_voltage": {"v", "mv"},
    "discharging_cutoff_voltage": {"v", "mv"},
    "specific_energy": {"wh/kg", "mah/g"},
    "energy_density": {"wh/l", "wh/lt", "wh/liter"},
    "specific_power": {"w/kg", "mw/g"},
    "power_density": {"w/l", "w/lt", "w/liter"},
    "internal_resistance": {"ω", "ohm", "mω", "mohm", "milliohm"},
    "impedance": {"ω", "ohm", "mω", "mohm", "milliohm"},
    "mass": {"g", "kg", "mg"},
    "volume": {"l", "ml", "cm3", "cc", "mm3"},
    "pulse_charging_current": {"a", "ma", "c"},
    "continuous_charging_current": {"a", "ma", "c"},
    "nominal_continuous_charging_current": {"a", "ma", "c"},
    "maximum_continuous_charging_current": {"a", "ma", "c"},
    "pulse_discharging_current": {"a", "ma", "c"},
    "continuous_discharging_current": {"a", "ma", "c"},
    "nominal_continuous_discharging_current": {"a", "ma", "c"},
    "maximum_continuous_discharging_current": {"a", "ma", "c"},
    "charging_time": {"s", "sec", "second", "seconds", "min", "minute", "minutes", "h", "hr", "hour", "hours"},
    "cycle_life": {"count", "cycle", "cycles"},
    "diameter": {"mm", "cm", "m", "um", "μm"},
    "height": {"mm", "cm", "m", "um", "μm"},
    "width": {"mm", "cm", "m", "um", "μm"},
    "length": {"mm", "cm", "m", "um", "μm"},
    "thickness": {"mm", "cm", "m", "um", "μm"},
    "minimum_charging_temperature": {"°c", "c", "degc", "k"},
    "maximum_charging_temperature": {"°c", "c", "degc", "k"},
    "charging_temperature_min": {"°c", "c", "degc", "k"},
    "charging_temperature_max": {"°c", "c", "degc", "k"},
    "minimum_discharging_temperature": {"°c", "c", "degc", "k"},
    "maximum_discharging_temperature": {"°c", "c", "degc", "k"},
    "discharging_temperature_min": {"°c", "c", "degc", "k"},
    "discharging_temperature_max": {"°c", "c", "degc", "k"},
    "minimum_storage_temperature": {"°c", "c", "degc", "k"},
    "maximum_storage_temperature": {"°c", "c", "degc", "k"},
    "storage_temperature_min": {"°c", "c", "degc", "k"},
    "storage_temperature_max": {"°c", "c", "degc", "k"},
}

PAIRED_SPEC_RANGES: tuple[tuple[str, str], ...] = (
    ("minimum_charging_temperature", "maximum_charging_temperature"),
    ("charging_temperature_min", "charging_temperature_max"),
    ("minimum_discharging_temperature", "maximum_discharging_temperature"),
    ("discharging_temperature_min", "discharging_temperature_max"),
    ("minimum_storage_temperature", "maximum_storage_temperature"),
    ("storage_temperature_min", "storage_temperature_max"),
    ("minimum_capacity", "nominal_capacity"),
    ("min_capacity", "nominal_capacity"),
)

CELL_IRI_PREFIX = "https://w3id.org/battinfo/cell/"
CELL_TYPE_IRI_PREFIX = "https://w3id.org/battinfo/cell-type/"

INTERNAL_IDENTIFIER_PREFIX: dict[str, tuple[str, ...]] = {
    "cell-type": ("product", "cell_type"),
    "cell": ("cell_instance",),
    "test": ("test",),
    "dataset": ("dataset",),
}

SIZE_CODE_PATTERN = re.compile(r"^[RP][A-Za-z0-9]+(?:[/-][A-Za-z0-9]+)*$")


def _load_mapping_json(*parts: str) -> dict[str, Any]:
    path = resources.files("battinfo").joinpath("data", "mappings", "domain-battery", *parts)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _controlled_value_map() -> dict[str, set[str]]:
    raw = _load_mapping_json("entity_type_map.json")
    mappings = raw.get("mappings", {})
    out: dict[str, set[str]] = {}
    for key in ("format", "chemistry", "positive_electrode_basis", "negative_electrode_basis"):
        values = mappings.get(key, {})
        if isinstance(values, Mapping):
            out[key] = {str(name).strip().lower() for name in values.keys()}
        else:
            out[key] = set()
    return out


def _entity_from_doc(doc: dict[str, Any]) -> tuple[str, Mapping[str, Any]] | None:
    for resource_type, keys in INTERNAL_IDENTIFIER_PREFIX.items():
        for key in keys:
            value = doc.get(key)
            if isinstance(value, Mapping):
                return resource_type, value
    return None


def _iri_uid(entity_id: str) -> str | None:
    parts = entity_id.rstrip("/").split("/")
    if len(parts) < 2:
        return None
    return parts[-1]


def _short_uid(entity_id: str) -> str | None:
    uid = _iri_uid(entity_id)
    if uid is None:
        return None
    return uid.replace("-", "")[:6]


def _numeric_spec_value(item: Mapping[str, Any]) -> float | None:
    value = item.get("value")
    if isinstance(value, (int, float)):
        return float(value)
    for key in ("typical_value", "max_value", "min_value"):
        candidate = item.get(key)
        if isinstance(candidate, (int, float)):
            return float(candidate)
    return None


def _unit_token(item: Mapping[str, Any]) -> str | None:
    for key in ("unit", "unit_text", "unit_code"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def _normalized_unit(unit: str) -> str:
    return unit.replace(" ", "").replace("ohms", "ohm")


def _append_issue(
    issues: list[ValidationIssue],
    *,
    code: str,
    severity: str,
    path: str,
    message: str,
    resource_type: str | None,
) -> None:
    issues.append(
        ValidationIssue(
            code=code,
            severity=severity,  # type: ignore[arg-type]
            path=path,
            message=message,
            validator="semantic",
            resource_type=resource_type,
        )
    )


def _validate_identifier_consistency(
    doc: dict[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    issue_severity: str,
) -> None:
    entity = _entity_from_doc(doc)
    if entity is None:
        return
    entity_type, record = entity
    entity_id = record.get("id")
    if not isinstance(entity_id, str):
        return
    expected_short = _short_uid(entity_id)
    short_id = record.get("short_id")
    if expected_short and isinstance(short_id, str) and short_id != expected_short:
        _append_issue(
            issues,
            code="semantic.short_id_mismatch",
            severity=issue_severity,
            path=f"{entity_type}.short_id",
            message=f"short_id '{short_id}' must match the first 6 undashed UID characters '{expected_short}'.",
            resource_type=resource_type,
        )
    identifier = record.get("identifier")
    expected_uid = _iri_uid(entity_id)
    expected_prefix = f"{entity_type}:"
    if isinstance(identifier, str) and identifier.startswith(expected_prefix) and expected_uid is not None:
        actual_uid = identifier.split(":", 1)[1]
        if actual_uid != expected_uid:
            _append_issue(
                issues,
                code="semantic.identifier_uid_mismatch",
                severity=issue_severity,
                path=f"{entity_type}.identifier",
                message=f"identifier '{identifier}' must use UID '{expected_uid}' to match id '{entity_id}'.",
                resource_type=resource_type,
            )


def _validate_controlled_values(
    doc: dict[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
) -> None:
    product = doc.get("product")
    if not isinstance(product, Mapping):
        return
    value_map = _controlled_value_map()
    field_map = {
        "cellFormat": "format",
        "chemistry": "chemistry",
        "positiveElectrodeBasis": "positive_electrode_basis",
        "negativeElectrodeBasis": "negative_electrode_basis",
    }
    for field, mapping_key in field_map.items():
        value = product.get(field)
        if not isinstance(value, str):
            continue
        normalized = value.strip().lower()
        if not normalized or normalized == "unknown":
            continue
        if normalized not in value_map.get(mapping_key, set()):
            _append_issue(
                issues,
                code="semantic.controlled_value_unmapped",
                severity="warning",
                path=f"product.{field}",
                message=f"value '{value}' is not present in the controlled mapping for '{mapping_key}'.",
                resource_type=resource_type,
            )


def _validate_size_code(
    doc: dict[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    issue_severity: str,
) -> None:
    product = doc.get("product")
    if not isinstance(product, Mapping):
        return
    size_code = product.get("sizeCode")
    if not isinstance(size_code, str) or not size_code.strip():
        return
    normalized = size_code.strip()
    if not SIZE_CODE_PATTERN.fullmatch(normalized):
        _append_issue(
            issues,
            code="semantic.size_code_invalid",
            severity=issue_severity,
            path="product.sizeCode",
            message="sizeCode must start with 'R' or 'P', for example 'R26650', 'P20/50/50', or 'P20-50-50'.",
            resource_type=resource_type,
        )
        return

    format_value = product.get("cellFormat")
    if not isinstance(format_value, str):
        return
    format_key = format_value.strip().lower()
    prefix = normalized[0]
    expected_prefix = None
    if format_key in {"coin", "cylindrical"}:
        expected_prefix = "R"
    elif format_key in {"pouch", "prismatic"}:
        expected_prefix = "P"
    if expected_prefix is not None and prefix != expected_prefix:
        _append_issue(
            issues,
            code="semantic.size_code_prefix_mismatch",
            severity=issue_severity,
            path="product.sizeCode",
            message=f"sizeCode '{size_code}' must start with '{expected_prefix}' for cellFormat '{format_value}'.",
            resource_type=resource_type,
        )


def _validate_specs(
    specs: Mapping[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    issue_severity: str,
) -> None:
    for spec_name, spec_value in specs.items():
        if not isinstance(spec_value, Mapping):
            continue
        unit = _unit_token(spec_value)
        if unit is not None and spec_name in SPEC_UNIT_COMPATIBILITY:
            normalized = _normalized_unit(unit)
            if normalized not in SPEC_UNIT_COMPATIBILITY[spec_name]:
                _append_issue(
                    issues,
                    code="semantic.unit_mismatch",
                    severity=issue_severity,
                    path=f"specs.{spec_name}",
                    message=f"unit '{unit}' is not compatible with spec '{spec_name}'.",
                    resource_type=resource_type,
                )

        min_value = spec_value.get("min_value")
        max_value = spec_value.get("max_value")
        typical_value = spec_value.get("typical_value")
        if isinstance(min_value, (int, float)) and isinstance(max_value, (int, float)) and float(min_value) > float(max_value):
            _append_issue(
                issues,
                code="semantic.range_invalid",
                severity=issue_severity,
                path=f"specs.{spec_name}",
                message=f"min_value {min_value} must be <= max_value {max_value}.",
                resource_type=resource_type,
            )
        if (
            isinstance(typical_value, (int, float))
            and isinstance(min_value, (int, float))
            and isinstance(max_value, (int, float))
            and not (float(min_value) <= float(typical_value) <= float(max_value))
        ):
            _append_issue(
                issues,
                code="semantic.range_invalid",
                severity=issue_severity,
                path=f"specs.{spec_name}.typical_value",
                message=f"typical_value {typical_value} must fall between min_value {min_value} and max_value {max_value}.",
                resource_type=resource_type,
            )

    for lower_key, upper_key in PAIRED_SPEC_RANGES:
        lower = specs.get(lower_key)
        upper = specs.get(upper_key)
        if not isinstance(lower, Mapping) or not isinstance(upper, Mapping):
            continue
        lower_num = _numeric_spec_value(lower)
        upper_num = _numeric_spec_value(upper)
        if lower_num is None or upper_num is None:
            continue
        lower_unit = _unit_token(lower)
        upper_unit = _unit_token(upper)
        if lower_unit and upper_unit and _normalized_unit(lower_unit) != _normalized_unit(upper_unit):
            _append_issue(
                issues,
                code="semantic.unit_mismatch",
                severity=issue_severity,
                path=f"specs.{lower_key}",
                message=f"paired specs '{lower_key}' and '{upper_key}' must use the same unit.",
                resource_type=resource_type,
            )
            continue
        if lower_num > upper_num:
            _append_issue(
                issues,
                code="semantic.range_invalid",
                severity=issue_severity,
                path=f"specs.{lower_key}",
                message=f"spec '{lower_key}' value {lower_num} must be <= '{upper_key}' value {upper_num}.",
                resource_type=resource_type,
            )


def _validate_dataset_semantics(
    dataset: Mapping[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    issue_severity: str,
) -> None:
    about = dataset.get("about")
    related_entities = dataset.get("related_entities")
    has_battery_link = False
    if isinstance(about, list):
        has_battery_link = any(
            isinstance(item, str)
            and (item.startswith(CELL_IRI_PREFIX) or item.startswith(CELL_TYPE_IRI_PREFIX))
            for item in about
        )
    elif isinstance(related_entities, Mapping):
        cell_ids = related_entities.get("cell_ids")
        if isinstance(cell_ids, list):
            has_battery_link = any(isinstance(item, str) and item.startswith(CELL_IRI_PREFIX) for item in cell_ids)
    if not has_battery_link:
        _append_issue(
            issues,
            code="semantic.dataset_missing_cell_link",
            severity=issue_severity,
            path="dataset.about",
            message="dataset must reference at least one BattINFO cell or cell_type IRI.",
            resource_type=resource_type,
        )

    created = dataset.get("dateCreated")
    modified = dataset.get("dateModified")
    published = dataset.get("datePublished")
    if isinstance(created, int) and isinstance(modified, int) and modified < created:
        _append_issue(
            issues,
            code="semantic.temporal_order_invalid",
            severity=issue_severity,
            path="dataset.dateModified",
            message=f"dateModified {modified} must be >= dateCreated {created}.",
            resource_type=resource_type,
        )
    if isinstance(created, int) and isinstance(published, int) and published < created:
        _append_issue(
            issues,
            code="semantic.temporal_order_invalid",
            severity=issue_severity,
            path="dataset.datePublished",
            message=f"datePublished {published} must be >= dateCreated {created}.",
            resource_type=resource_type,
        )

    distributions = dataset.get("distribution")
    if isinstance(distributions, list):
        for idx, distribution in enumerate(distributions):
            if not isinstance(distribution, Mapping):
                continue
            checksum = distribution.get("checksum")
            if not isinstance(checksum, Mapping):
                continue
            algorithm = checksum.get("algorithm")
            value = checksum.get("value")
            if not isinstance(algorithm, str) or not isinstance(value, str):
                continue
            expected_length = {"sha256": 64, "sha512": 128, "md5": 32}.get(algorithm)
            if expected_length is None:
                continue
            is_hex = all(ch in "0123456789abcdefABCDEF" for ch in value)
            if len(value) != expected_length or not is_hex:
                _append_issue(
                    issues,
                    code="semantic.checksum_invalid",
                    severity=issue_severity,
                    path=f"dataset.distribution[{idx}].checksum.value",
                    message=f"checksum for algorithm '{algorithm}' must be {expected_length} hex characters.",
                    resource_type=resource_type,
                )


def _validate_test_semantics(
    test: Mapping[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    issue_severity: str,
) -> None:
    started = test.get("started_at")
    ended = test.get("ended_at")
    if isinstance(started, int) and isinstance(ended, int) and ended < started:
        _append_issue(
            issues,
            code="semantic.temporal_order_invalid",
            severity=issue_severity,
            path="test.ended_at",
            message=f"ended_at {ended} must be >= started_at {started}.",
            resource_type=resource_type,
        )


def validate_semantic_report(
    doc: dict[str, Any],
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationReport:
    doc = record_to_legacy_aliases(doc)
    resolved_policy = get_validation_policy(policy) if isinstance(policy, str) else policy
    if resolved_policy.semantic == "off":
        return ValidationReport(policy=resolved_policy)

    issues: list[ValidationIssue] = []
    entity = _entity_from_doc(doc)
    resource_type = entity[0] if entity is not None else None
    hard_issue_severity = "error" if resolved_policy.semantic == "error" else "warning"

    _validate_identifier_consistency(doc, issues, resource_type, hard_issue_severity)
    _validate_controlled_values(doc, issues, resource_type)
    _validate_size_code(doc, issues, resource_type, hard_issue_severity)

    specs = doc.get("specs")
    if isinstance(specs, Mapping):
        _validate_specs(specs, issues, resource_type, hard_issue_severity)

    dataset = doc.get("dataset")
    if isinstance(dataset, Mapping):
        _validate_dataset_semantics(dataset, issues, resource_type, hard_issue_severity)

    test = doc.get("test")
    if isinstance(test, Mapping):
        _validate_test_semantics(test, issues, resource_type, hard_issue_severity)

    return ValidationReport(issues=tuple(issues), policy=resolved_policy)


def validate_semantic(
    doc: dict[str, Any],
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationResult:
    return validate_semantic_report(doc, policy=policy).to_result()
