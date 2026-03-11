from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ValidationMode = Literal["error", "warn", "off"]
ValidationSeverity = Literal["error", "warning"]
ValidationPolicyName = Literal["default", "strict", "publisher", "ingest"]


@dataclass(frozen=True)
class ValidationPolicy:
    name: str = "default"
    schema: ValidationMode = "error"
    references: ValidationMode = "error"
    semantic: ValidationMode = "warn"
    publication: ValidationMode = "error"


DEFAULT_POLICY = ValidationPolicy()
STRICT_POLICY = ValidationPolicy(name="strict", semantic="error")
PUBLISHER_POLICY = ValidationPolicy(name="publisher", semantic="error", publication="error")
INGEST_POLICY = ValidationPolicy(name="ingest", semantic="warn", references="warn")
NAMED_POLICIES: dict[str, ValidationPolicy] = {
    DEFAULT_POLICY.name: DEFAULT_POLICY,
    STRICT_POLICY.name: STRICT_POLICY,
    PUBLISHER_POLICY.name: PUBLISHER_POLICY,
    INGEST_POLICY.name: INGEST_POLICY,
}


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: ValidationSeverity
    path: str
    message: str
    hint: str | None = None
    validator: str | None = None
    resource_type: str | None = None
    profile: str | None = None

    def render(self) -> str:
        if self.path:
            return f"{self.path}: {self.message}"
        return self.message


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str]
    issues: tuple[ValidationIssue, ...] = ()
    policy: str = "default"


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...] = ()
    policy: ValidationPolicy = field(default_factory=lambda: DEFAULT_POLICY)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    def render_errors(self) -> list[str]:
        return [issue.render() for issue in self.errors]

    def to_result(self) -> ValidationResult:
        return ValidationResult(
            ok=self.ok,
            errors=self.render_errors(),
            issues=self.issues,
            policy=self.policy.name,
        )


def combine_reports(*reports: ValidationReport, policy: ValidationPolicy | None = None) -> ValidationReport:
    resolved_policy = policy or (reports[0].policy if reports else DEFAULT_POLICY)
    issues: list[ValidationIssue] = []
    for report in reports:
        issues.extend(report.issues)
    return ValidationReport(issues=tuple(issues), policy=resolved_policy)


def get_validation_policy(name: str) -> ValidationPolicy:
    key = name.strip().lower()
    if key not in NAMED_POLICIES:
        raise ValueError(f"Unknown validation policy '{name}'. Expected one of: {', '.join(sorted(NAMED_POLICIES))}.")
    return NAMED_POLICIES[key]
