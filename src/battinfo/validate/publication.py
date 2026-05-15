from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from battinfo.validate.core import (
    DEFAULT_POLICY,
    ValidationIssue,
    ValidationPolicy,
    ValidationReport,
    ValidationResult,
    combine_reports,
    get_validation_policy,
)
from battinfo.validate.jsonld import validate_jsonld_report

SHA256_RE = re.compile(r"^[A-Fa-f0-9]{64}$")


def _issue_severity(policy: ValidationPolicy) -> str:
    return "error" if policy.publication == "error" else "warning"


def _append_issue(
    issues: list[ValidationIssue],
    *,
    code: str,
    severity: str,
    path: str,
    message: str,
) -> None:
    issues.append(
        ValidationIssue(
            code=code,
            severity=severity,  # type: ignore[arg-type]
            path=path,
            message=message,
            validator="publication",
            resource_type="jsonld-publication",
        )
    )


def _is_absolute_uri(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parsed = urlparse(value)
    return bool(parsed.scheme and (parsed.netloc or parsed.path))


def _type_values(node: dict[str, Any]) -> list[str]:
    value = node.get("@type")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _graph_nodes(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    graph = data.get("@graph")
    if isinstance(graph, list):
        return [(f"@graph[{idx}]", item) for idx, item in enumerate(graph) if isinstance(item, dict)]
    return [("", data)] if isinstance(data, dict) else []


def _shape_issues(data: dict[str, Any], policy: ValidationPolicy) -> ValidationReport:
    severity = _issue_severity(policy)
    issues: list[ValidationIssue] = []
    nodes = _graph_nodes(data)
    has_graph = isinstance(data.get("@graph"), list)
    seen_ids: dict[str, str] = {}

    if not nodes:
        _append_issue(
            issues,
            code="publication.node_missing",
            severity=severity,
            path="",
            message="Publication payload must contain a JSON-LD node or @graph.",
        )
        return ValidationReport(issues=tuple(issues), policy=policy)

    for path, node in nodes:
        node_id = node.get("@id")
        if not isinstance(node_id, str) or not node_id:
            _append_issue(
                issues,
                code="publication.node_missing_id",
                severity=severity,
                path=f"{path}.@id" if path else "@id",
                message="Publication nodes must define a non-empty @id.",
            )
            continue
        if node_id in seen_ids:
            _append_issue(
                issues,
                code="publication.duplicate_node_id",
                severity=severity,
                path=f"{path}.@id" if path else "@id",
                message=f"Duplicate publication node id '{node_id}' also appears at {seen_ids[node_id]}.",
            )
        else:
            seen_ids[node_id] = path or "@root"

    node_ids = set(seen_ids)
    for path, node in nodes:
        if "schema:Dataset" not in _type_values(node):
            continue

        node_id = node.get("@id")
        is_battinfo_dataset = isinstance(node_id, str) and node_id.startswith("https://w3id.org/battinfo/dataset/")

        about = node.get("schema:about")
        if about is not None and not isinstance(about, list):
            _append_issue(
                issues,
                code="publication.reference_invalid",
                severity=severity,
                path=f"{path}.schema:about" if path else "schema:about",
                message="Publication schema:about must be a list of @id references.",
            )
        elif is_battinfo_dataset and has_graph and (not isinstance(about, list) or not about):
            _append_issue(
                issues,
                code="publication.dataset_about_missing",
                severity=severity,
                path=f"{path}.schema:about" if path else "schema:about",
                message="Published dataset nodes must define non-empty schema:about references.",
            )
        elif isinstance(about, list):
            for idx, ref in enumerate(about):
                ref_path = f"{path}.schema:about[{idx}]" if path else f"schema:about[{idx}]"
                if not isinstance(ref, dict) or not isinstance(ref.get("@id"), str):
                    _append_issue(
                        issues,
                        code="publication.reference_invalid",
                        severity=severity,
                        path=ref_path,
                        message="Publication references must be objects with an @id string.",
                    )
                    continue
                ref_id = ref["@id"]
                # Only enforce intra-graph referential integrity inside a @graph publication
                # package.  Resolver documents are single-node and carry cross-document
                # references to external BattINFO records — those are expected to be absent.
                if has_graph and ref_id.startswith("https://w3id.org/battinfo/") and ref_id not in node_ids:
                    _append_issue(
                        issues,
                        code="publication.reference_missing_node",
                        severity=severity,
                        path=f"{ref_path}.@id",
                        message=f"Publication graph is missing a node for referenced BattINFO id '{ref_id}'.",
                    )

        distributions = node.get("schema:distribution")
        if distributions is not None and not isinstance(distributions, list):
            _append_issue(
                issues,
                code="publication.distribution_invalid",
                severity=severity,
                path=f"{path}.schema:distribution" if path else "schema:distribution",
                message="Publication schema:distribution must be a list of distribution objects.",
            )
            continue
        if is_battinfo_dataset and has_graph and (not isinstance(distributions, list) or not distributions):
            _append_issue(
                issues,
                code="publication.dataset_distribution_missing",
                severity=severity,
                path=f"{path}.schema:distribution" if path else "schema:distribution",
                message="Published dataset nodes must define at least one schema:distribution entry.",
            )
            continue
        if not isinstance(distributions, list):
            continue

        for idx, entry in enumerate(distributions):
            entry_path = f"{path}.schema:distribution[{idx}]" if path else f"schema:distribution[{idx}]"
            if not isinstance(entry, dict):
                _append_issue(
                    issues,
                    code="publication.distribution_invalid",
                    severity=severity,
                    path=entry_path,
                    message="Distribution entries must be JSON objects.",
                )
                continue
            for key in ("schema:contentUrl", "schema:encodingFormat", "schema:sha256", "schema:isPartOf"):
                if key not in entry:
                    _append_issue(
                        issues,
                        code="publication.distribution_missing_field",
                        severity=severity,
                        path=entry_path,
                        message=f"Distribution entry is missing required field '{key}'.",
                    )
            content_url = entry.get("schema:contentUrl")
            if content_url is not None and not _is_absolute_uri(content_url):
                _append_issue(
                    issues,
                    code="publication.distribution_url_invalid",
                    severity=severity,
                    path=f"{entry_path}.schema:contentUrl",
                    message="Distribution contentUrl must be an absolute URI.",
                )
            checksum = entry.get("schema:sha256")
            if checksum is not None and (not isinstance(checksum, str) or not SHA256_RE.fullmatch(checksum)):
                _append_issue(
                    issues,
                    code="publication.distribution_checksum_invalid",
                    severity=severity,
                    path=f"{entry_path}.schema:sha256",
                    message="Distribution sha256 must be a 64-character hexadecimal digest.",
                )
            is_part_of = entry.get("schema:isPartOf")
            if is_part_of is not None:
                ref_id = is_part_of.get("@id") if isinstance(is_part_of, dict) else None
                if not isinstance(ref_id, str) or not _is_absolute_uri(ref_id):
                    _append_issue(
                        issues,
                        code="publication.distribution_parent_invalid",
                        severity=severity,
                        path=f"{entry_path}.schema:isPartOf",
                        message="Distribution schema:isPartOf must be an object containing an absolute @id URI.",
                    )

    return ValidationReport(issues=tuple(issues), policy=policy)

def validate_publication_report(
    data: dict[str, Any],
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationReport:
    resolved_policy = get_validation_policy(policy) if isinstance(policy, str) else policy
    if resolved_policy.publication == "off":
        return ValidationReport(policy=resolved_policy)
    jsonld_report = validate_jsonld_report(data, policy=resolved_policy)
    return combine_reports(
        jsonld_report,
        _shape_issues(data, resolved_policy),
        policy=resolved_policy,
    )


def validate_publication(
    data: dict[str, Any],
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationResult:
    return validate_publication_report(data, policy=policy).to_result()
