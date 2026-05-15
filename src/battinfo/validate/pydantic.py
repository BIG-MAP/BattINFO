from __future__ import annotations

from battinfo.validate.core import (
    DEFAULT_POLICY,
    ValidationPolicy,
    ValidationReport,
    ValidationResult,
    get_validation_policy,
)
from battinfo.validate.schema import validate_profile


def validate_json_report(
    data: dict[str, object],
    profile: str = "base",
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationReport:
    """Validate JSON input and return a structured validation report."""
    resolved_policy = get_validation_policy(policy) if isinstance(policy, str) else policy
    return validate_profile(data, profile=profile, policy=resolved_policy)


def validate_json(
    data: dict[str, object],
    profile: str = "base",
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationResult:
    """Validate JSON input using profile-aware JSON Schema validation."""
    return validate_json_report(data, profile=profile, policy=policy).to_result()
