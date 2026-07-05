"""Render validation reports in the authoring vocabulary, aggregated.

Validation collects every issue, but the save/publish raise sites used to surface only
the FIRST error, phrased in canonical record paths (``cell_spec.cell_format``) that don't
match what the author actually typed (``format=``). This module turns a report into one
actionable message: all errors at once, canonical paths translated back to authoring
kwargs, and quantity-shape errors carrying a copy-pasteable example.
"""
from __future__ import annotations

import json
import re

from battinfo.validate.core import ValidationIssue, ValidationReport

# Canonical record path → the authoring kwarg the user actually typed. Longest-prefix
# match, so "cell_spec.manufacturer.name" wins over "cell_spec.manufacturer".
_AUTHORING_KWARGS: dict[str, str] = {
    "cell_spec.cell_format": "format=",
    "cell_spec.manufacturer.name": "manufacturer=",
    "cell_spec.manufacturer": "manufacturer=",
    "cell_spec.model": "model_name=",
    "cell_spec.positive_electrode_basis": "positive_electrode_basis=",
    "cell_spec.negative_electrode_basis": "negative_electrode_basis=",
    "cell_instance.cell_spec_id": "cell_spec_id=",
    "cell_instance.serial_number": "serial_number=",
    "test.cell_id": "cell_id=",
    "test.kind": "kind=",
    "test_spec.kind": "kind=",
    "dataset.name": "title=",
    "dataset.access_url": "access_url=",
    "provenance.source_type": "source_type=",
    "provenance.source_url": "source_url=",
    "provenance.source_file": "source_file=",
    "provenance.source_name": "source_name=",
    "provenance.retrieved_at": "retrieved_at=",
    "provenance.citation": "citation=",
    "provenance.file_hash": "file_hash=",
    "provenance.curated_by": "curated_by=",
}

_REQUIRED_KEY_RE = re.compile(r"'([^']+)' is a required property")


def _full_path(issue: ValidationIssue) -> str:
    """Required-property errors anchor at the PARENT object; extend the path with the
    missing key from the message so translation and reading both point at the field."""
    path = issue.path or ""
    match = _REQUIRED_KEY_RE.match(issue.message)
    if match:
        key = match.group(1)
        return f"{path}.{key}" if path else key
    return path


def _authoring_kwarg(path: str) -> str | None:
    while path:
        if path in _AUTHORING_KWARGS:
            return _AUTHORING_KWARGS[path]
        if "." not in path:
            return None
        path = path.rsplit(".", 1)[0]
    return None


def _quantity_hint(path: str) -> str | None:
    """For errors under properties.<name>, show the accepted quantity shape."""
    parts = path.split(".")
    if len(parts) < 2 or parts[0] != "properties":
        return None
    prop = parts[1]
    from battinfo.validate.semantic import SPEC_UNIT_COMPATIBILITY  # noqa: PLC0415

    units = SPEC_UNIT_COMPATIBILITY.get(prop)
    unit = sorted(units)[0] if units else "<unit>"
    example = json.dumps({prop: {"value": 0.0, "unit": unit}})
    hint = f"pass a quantity object, e.g. {example}"
    if units:
        hint += f"; run `battinfo properties show {prop}` for accepted units"
    return hint


def render_issue(issue: ValidationIssue) -> str:
    """One line for one issue: path (translated where possible), message, actionable hint."""
    path = _full_path(issue)
    line = f"{path}: {issue.message}" if path else issue.message
    extras: list[str] = []
    kwarg = _authoring_kwarg(path)
    if kwarg:
        extras.append(f"authoring field: {kwarg}")
    quantity = _quantity_hint(path)
    if quantity:
        extras.append(quantity)
    if issue.hint:
        extras.append(issue.hint)
    if extras:
        line += " (" + "; ".join(extras) + ")"
    return line


def format_report_errors(report: ValidationReport, *, prefix: str = "Validation failed") -> str:
    """Aggregate EVERY error in the report into one message (never just the first)."""
    errors = report.errors
    if not errors:
        return prefix
    if len(errors) == 1:
        return f"{prefix}: {render_issue(errors[0])}"
    lines = "\n".join(f"  - {render_issue(issue)}" for issue in errors)
    return f"{prefix} with {len(errors)} errors:\n{lines}"
