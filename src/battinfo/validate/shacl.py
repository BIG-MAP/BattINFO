"""SHACL validation layer for BattINFO records.

Applies the SHACL shapes in ``assets/shapes/`` to the JSON-LD representation
of a record (as produced by :mod:`battinfo.jsonld`).  Requires ``pyshacl``.

The shapes target *quantity nodes* — the blank nodes that are values of each
spec property IRI.  All violations are emitted as ``sh:Warning`` (never errors)
since the Python semantic layer already blocks hard errors before this runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from battinfo.validate.core import (
    DEFAULT_POLICY,
    ValidationIssue,
    ValidationPolicy,
    ValidationReport,
    ValidationResult,
    get_validation_policy,
)

_SHAPES_DIR = Path(__file__).parent.parent.parent.parent / "assets" / "shapes"
# shacl.py lives at src/battinfo/validate/shacl.py → 4 levels up = repo root
# Fall back to the packaged copy when installed as a wheel.

_PACKAGED_SHAPES_DIR = Path(__file__).parent.parent / "data" / "shapes"


def _shapes_path(filename: str) -> Path | None:
    """Return the path to a shapes .ttl file, checking repo then packaged copy."""
    candidate = _SHAPES_DIR / filename
    if candidate.exists():
        return candidate
    packaged = _PACKAGED_SHAPES_DIR / filename
    if packaged.exists():
        return packaged
    return None


def _record_to_jsonld(record: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw BattINFO record dict to its JSON-LD representation."""
    product = record.get("cell_spec") or record.get("specification") or {}
    specs = record.get("properties") or {}

    if not product and not specs:
        # Non-cell-spec record: test, dataset, etc. — return minimal JSON-LD
        return record

    # Lazy import to avoid circular dependency
    from battinfo.jsonld import cell_spec_to_jsonld  # noqa: PLC0415

    return cell_spec_to_jsonld(record)


def _parse_shacl_report(report_graph: Any, _data_graph: Any) -> list[ValidationIssue]:
    """Walk an rdflib SHACL report graph and extract ValidationIssue objects."""
    try:
        from rdflib.namespace import SH  # noqa: PLC0415
        from rdflib import URIRef, Literal  # noqa: PLC0415
    except ImportError:
        return []

    issues: list[ValidationIssue] = []
    SH_result = SH.result
    SH_message = SH.resultMessage
    SH_path = SH.resultPath
    SH_severity = SH.resultSeverity
    SH_Violation = SH.Violation
    SH_Warning = SH.Warning

    for result in report_graph.objects(None, SH_result):
        messages = list(report_graph.objects(result, SH_message))
        msg_text = str(messages[0]) if messages else "SHACL constraint violation"

        paths = list(report_graph.objects(result, SH_path))
        path_text = str(paths[0]).split("#")[-1].split("/")[-1] if paths else ""

        severities = list(report_graph.objects(result, SH_severity))
        sev = "warning"
        if severities:
            sev = "error" if severities[0] == SH_Violation else "warning"

        issues.append(
            ValidationIssue(
                code="shacl.constraint_violation",
                severity=sev,  # type: ignore[arg-type]
                path=path_text,
                message=msg_text,
                validator="shacl",
                resource_type="cell-spec",
            )
        )
    return issues


def validate_shacl_report(
    doc: dict[str, Any],
    *,
    shapes_filename: str = "cell-spec.shapes.ttl",
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationReport:
    """Validate *doc* against the SHACL shapes and return a ValidationReport.

    Only cell-spec records are validated; other record types return an empty
    report.  ``pyshacl`` must be installed (it is a dev dependency).
    """
    resolved_policy = get_validation_policy(policy) if isinstance(policy, str) else policy

    # Only run on cell-spec records
    product = doc.get("cell_spec") or doc.get("specification")
    if not product:
        return ValidationReport(policy=resolved_policy)

    try:
        import pyshacl  # noqa: PLC0415
    except ImportError:
        return ValidationReport(
            issues=(
                ValidationIssue(
                    code="shacl.unavailable",
                    severity="warning",
                    path="",
                    message="pyshacl is not installed; SHACL validation skipped. Install with: pip install pyshacl",
                    validator="shacl",
                ),
            ),
            policy=resolved_policy,
        )

    shapes_path = _shapes_path(shapes_filename)
    if shapes_path is None:
        return ValidationReport(
            issues=(
                ValidationIssue(
                    code="shacl.shapes_not_found",
                    severity="warning",
                    path="",
                    message=f"SHACL shapes file '{shapes_filename}' not found; SHACL validation skipped.",
                    validator="shacl",
                ),
            ),
            policy=resolved_policy,
        )

    jsonld_doc = _record_to_jsonld(doc)

    import warnings as _warnings  # noqa: PLC0415

    try:
        with _warnings.catch_warnings():
            _warnings.filterwarnings("ignore", category=DeprecationWarning)
            conforms, report_graph, _report_text = pyshacl.validate(
                json.dumps(jsonld_doc),
                shacl_graph=str(shapes_path),
                data_graph_format="json-ld",
                shacl_graph_format="turtle",
                inference="none",
                abort_on_first=False,
            )
    except Exception as exc:  # noqa: BLE001
        return ValidationReport(
            issues=(
                ValidationIssue(
                    code="shacl.runtime_error",
                    severity="warning",
                    path="",
                    message=f"SHACL validation failed: {exc}",
                    validator="shacl",
                ),
            ),
            policy=resolved_policy,
        )

    if conforms:
        return ValidationReport(policy=resolved_policy)

    issues = _parse_shacl_report(report_graph, None)
    return ValidationReport(issues=tuple(issues), policy=resolved_policy)


def validate_shacl(
    doc: dict[str, Any],
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationResult:
    return validate_shacl_report(doc, policy=policy).to_result()
