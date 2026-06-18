from __future__ import annotations

from pathlib import Path
from typing import Any

from battinfo.canonical_aliases import record_to_snake_aliases
from battinfo.entities import kind_for_doc
from battinfo.validate.core import (
    DEFAULT_POLICY,
    ValidationPolicy,
    ValidationReport,
    ValidationResult,
    combine_reports,
    get_validation_policy,
)
from battinfo.validate.references import validate_references_report
from battinfo.validate.schema import schema_for_rel_path, validate_schema_data
from battinfo.validate.semantic import validate_semantic_report
from battinfo.validate.shacl import validate_shacl_report


def _entity_schema_rel_path(doc: dict[str, Any]) -> str:
    kind = kind_for_doc(doc)
    if kind is None:
        raise ValueError(
            "Unsupported record type: expected cell_spec, cell_instance, test_spec, "
            "test, dataset, material_spec, or material."
        )
    return kind.schema_file


def _resource_type(doc: dict[str, Any]) -> str | None:
    kind = kind_for_doc(doc)
    return kind.entity_type if kind is not None else None


def validate_record_report(
    doc: dict[str, Any],
    *,
    source_root: str | Path | None = None,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationReport:
    normalized_doc = record_to_snake_aliases(doc)
    resolved_policy = get_validation_policy(policy) if isinstance(policy, str) else policy
    reports: list[ValidationReport] = []
    resource_type = _resource_type(normalized_doc)

    if resolved_policy.schema != "off":
        schema_rel_path = _entity_schema_rel_path(normalized_doc)
        reports.append(
            validate_schema_data(
                normalized_doc,
                schema_for_rel_path(schema_rel_path),
                resource_type=resource_type,
                policy=resolved_policy,
            )
        )

    if source_root is not None and resolved_policy.references != "off":
        reports.append(validate_references_report(normalized_doc, source_root, policy=resolved_policy))

    if resolved_policy.semantic != "off":
        reports.append(validate_semantic_report(normalized_doc, policy=resolved_policy))
        reports.append(validate_shacl_report(normalized_doc, policy=resolved_policy))

    return combine_reports(*reports, policy=resolved_policy)


def validate_record(
    doc: dict[str, Any],
    *,
    source_root: str | Path | None = None,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationResult:
    return validate_record_report(doc, source_root=source_root, policy=policy).to_result()
