from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

from battinfo.validate.core import DEFAULT_POLICY, ValidationIssue, ValidationPolicy, ValidationReport, ValidationResult, get_validation_policy

_EXPLICIT_ALLOWED_TYPE_TERMS = {
    "BatteryCell",
    "BatteryModule",
    "BatteryPack",
    "BatterySystem",
    "CoinCell",
    "ConventionalProperty",
    "CylindricalBattery",
    "GraphiteElectrode",
    "LithiumIonBattery",
    "LithiumIonGraphiteBattery",
    "LithiumIonIronPhosphateBattery",
    "LithiumIronPhosphateElectrode",
    "PouchCell",
    "PrismaticBattery",
    "RealData",
    "MaximumChargingTemperature",
    "MinimumChargingTemperature",
    "MaximumDischargingTemperature",
    "MinimumDischargingTemperature",
    "MaximumStorageTemperature",
    "MinimumStorageTemperature",
}


def _load_mapping_json(*parts: str) -> dict[str, Any]:
    path = resources.files("battinfo").joinpath("data", "mappings", "domain-battery", *parts)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _is_absolute_or_compact_iri(value: str) -> bool:
    return "://" in value or ":" in value


def _collect_bare_terms(value: Any, out: set[str]) -> None:
    if isinstance(value, str):
        if value and not _is_absolute_or_compact_iri(value):
            out.add(value)
        return
    if isinstance(value, list):
        for item in value:
            _collect_bare_terms(item, out)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_bare_terms(item, out)


@lru_cache(maxsize=1)
def _allowed_type_terms() -> set[str]:
    allowed = set(_EXPLICIT_ALLOWED_TYPE_TERMS)

    entity_map = _load_mapping_json("entity_type_map.json")
    _collect_bare_terms(entity_map.get("mappings", {}), allowed)

    for filename in ("property_map.candidates.json", "property_map.curated.json"):
        property_map = _load_mapping_json(filename)
        for item in property_map.get("mappings", []):
            for key in ("class_pref_label", "class_label"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    allowed.add(value)
    return allowed


def _walk_relative_type_errors(node: Any, path: str, errors: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            next_path = f"{path}.{key}" if path else key
            if key == "@context":
                continue
            if key == "@type":
                values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
                for idx, item in enumerate(values):
                    if not isinstance(item, str):
                        continue
                    if item.startswith("@"):
                        continue
                    if _is_absolute_or_compact_iri(item):
                        continue
                    if item not in _allowed_type_terms():
                        item_path = next_path if isinstance(value, str) else f"{next_path}[{idx}]"
                        errors.append(f"{item_path}: relative @type reference '{item}' is not in the allowed term set")
            else:
                _walk_relative_type_errors(value, next_path, errors)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            next_path = f"{path}[{idx}]" if path else f"[{idx}]"
            _walk_relative_type_errors(item, next_path, errors)


def validate_jsonld_report(
    data: dict[str, Any],
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationReport:
    resolved_policy = get_validation_policy(policy) if isinstance(policy, str) else policy
    errors: list[str] = []
    _walk_relative_type_errors(data, "", errors)
    issues = []
    for rendered in errors:
        path, _, message = rendered.partition(": ")
        issues.append(
            ValidationIssue(
                code="jsonld.type_term_unknown",
                severity="error",
                path=path if _ else "",
                message=message if _ else rendered,
                validator="@type",
                resource_type="jsonld",
            )
        )
    return ValidationReport(issues=tuple(issues), policy=resolved_policy)


def validate_jsonld(
    data: dict[str, Any],
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationResult:
    return validate_jsonld_report(data, policy=policy).to_result()
