from __future__ import annotations

from typing import Any

from battinfo.validate.pydantic import ValidationResult, validate_json


def run_validation(data: dict[str, Any], profile: str = "base") -> ValidationResult:
    return validate_json(data, profile=profile)
