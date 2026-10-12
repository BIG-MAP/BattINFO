from __future__ import annotations

from pathlib import Path
from typing import Any

from battinfo.canonical_aliases import record_to_snake_aliases
from battinfo.entities import is_placeholder_iri, kind_for_doc
from battinfo.validate.core import (
    DEFAULT_POLICY,
    ValidationIssue,
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
        from battinfo.entities import ENTITY_KINDS  # noqa: PLC0415

        expected = ", ".join(k.record_key for k in ENTITY_KINDS)
        raise ValueError(f"Unsupported record type: expected one of {expected}.")
    return kind.schema_file


def _resource_type(doc: dict[str, Any]) -> str | None:
    kind = kind_for_doc(doc)
    return kind.entity_type if kind is not None else None


def _placeholder_iri_report(doc: dict[str, Any], policy: ValidationPolicy) -> ValidationReport:
    """Reject a record whose own IRI is the all-zero template placeholder.

    Templates no longer write it, but a draft made from an older template still
    carries it, and every such record would claim the same IRI. So this is an
    error under every policy, whatever its schema/semantic settings.
    """
    kind = kind_for_doc(doc)
    body = doc.get(kind.record_key) if kind is not None else None
    entity_id = body.get("id") if isinstance(body, dict) else None
    if kind is None or not is_placeholder_iri(entity_id):
        return ValidationReport(policy=policy)
    fix = ("Remove id, short_id and identifier so the save mints the IRI, or set the IRI "
           "this record was published under.")
    issue = ValidationIssue(
        code="identity.placeholder_iri",
        severity="error",
        path=f"{kind.record_key}.id",
        message=(f"{entity_id} is a template placeholder, not a real IRI: every record made "
                 f"from an unedited template would claim it. {fix}"),
        validator="identity",
        resource_type=kind.entity_type,
    )
    return ValidationReport(issues=(issue,), policy=policy)


def validate_record_report(
    doc: dict[str, Any],
    *,
    source_root: str | Path | None = None,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationReport:
    """Validate one canonical record and return every issue found.

    *doc* is a canonical record as saved on disk (``{"schema_version": ...,
    "cell_spec": {...}}`` and so on, for any record type). The checks are the
    record's JSON Schema, a refusal of the all-zero template IRI, the semantic
    rules (controlled values, units, plausible ranges) and, for cell specs,
    the SHACL shapes. With *source_root* (a records folder) every IRI the
    record points at must also resolve to a saved record of the right type.

    *policy* is a :class:`ValidationPolicy` or one of the names
    ``"default"``, ``"strict"``, ``"publisher"`` and ``"ingest"``; it decides
    which checks run and whether their findings are errors or warnings. The
    function never raises over a finding: read ``report.ok``,
    ``report.errors`` and ``report.warnings``, or ``report.to_dict()``. It
    raises ``ValueError`` for an unknown policy name or a document that is
    not a record of any known type.
    """
    normalized_doc = record_to_snake_aliases(doc)
    resolved_policy = get_validation_policy(policy) if isinstance(policy, str) else policy
    reports: list[ValidationReport] = [_placeholder_iri_report(normalized_doc, resolved_policy)]
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
