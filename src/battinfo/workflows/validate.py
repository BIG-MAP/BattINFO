from __future__ import annotations

from typing import Any

from battinfo.validate.pydantic import ValidationResult, validate_json
from battinfo.validate.record import validate_record


def run_validation(data: dict[str, Any], profile: str = "cell-type") -> ValidationResult:
    return validate_json(data, profile=profile)


def run_record_validation(data: dict[str, Any], source_root: str | None = None) -> ValidationResult:
    return validate_record(data, source_root=source_root)

