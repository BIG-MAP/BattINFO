from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

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


def _entity_schema_rel_path(doc: dict[str, Any]) -> str:
    if isinstance(doc.get("product"), Mapping):
        return "cell-type.schema.json"
    if isinstance(doc.get("cell_type"), Mapping):
        return "cell-type.schema.json"
    if isinstance(doc.get("cell_instance"), Mapping):
        return "cell-instance.schema.json"
    if isinstance(doc.get("test_protocol"), Mapping):
        return "test-protocol.schema.json"
    if isinstance(doc.get("test"), Mapping):
        return "test.schema.json"
    if isinstance(doc.get("dataset"), Mapping):
        return "dataset.schema.json"
    raise ValueError("Unsupported record type: expected product/cell_type, cell_instance, test_protocol, test, or dataset.")


def _resource_type(doc: dict[str, Any]) -> str | None:
    if isinstance(doc.get("product"), Mapping) or isinstance(doc.get("cell_type"), Mapping):
        return "cell-type"
    if isinstance(doc.get("cell_instance"), Mapping):
        return "cell"
    if isinstance(doc.get("test_protocol"), Mapping):
        return "test-protocol"
    if isinstance(doc.get("test"), Mapping):
        return "test"
    if isinstance(doc.get("dataset"), Mapping):
        return "dataset"
    return None


def validate_record_report(
    doc: dict[str, Any],
    *,
    source_root: str | Path | None = None,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationReport:
    resolved_policy = get_validation_policy(policy) if isinstance(policy, str) else policy
    reports: list[ValidationReport] = []
    resource_type = _resource_type(doc)

    if resolved_policy.schema != "off":
        schema_rel_path = _entity_schema_rel_path(doc)
        reports.append(
            validate_schema_data(
                doc,
                schema_for_rel_path(schema_rel_path),
                resource_type=resource_type,
                policy=resolved_policy,
            )
        )

    if source_root is not None and resolved_policy.references != "off":
        reports.append(validate_references_report(doc, source_root, policy=resolved_policy))

    if resolved_policy.semantic != "off":
        reports.append(validate_semantic_report(doc, policy=resolved_policy))

    return combine_reports(*reports, policy=resolved_policy)


def validate_record(
    doc: dict[str, Any],
    *,
    source_root: str | Path | None = None,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationResult:
    return validate_record_report(doc, source_root=source_root, policy=policy).to_result()
