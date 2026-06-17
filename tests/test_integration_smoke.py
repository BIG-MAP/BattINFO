"""Integration smoke test: all validation layers run end-to-end on a real record.

Verifies that the four-layer pipeline (JSON Schema → semantic → SHACL → references)
runs without crashing and produces a clean report for the A123 example record.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo
from battinfo import validate_record, validate_record_report, ValidationPolicy

_A123 = ROOT / "src" / "battinfo" / "data" / "examples" / "cell-spec" / "A123__ANR26650M1-B.json"

WARN_POLICY = ValidationPolicy(name="warn", semantic="warning")


def _load() -> dict:
    return json.loads(_A123.read_text(encoding="utf-8"))


# ── Top-level __init__ exports ────────────────────────────────────────────────


def test_validate_record_accessible_from_top_level() -> None:
    """validate_record and validate_record_report are importable from battinfo.*"""
    assert callable(battinfo.validate_record)
    assert callable(battinfo.validate_record_report)
    assert callable(battinfo.validate_shacl)
    assert callable(battinfo.validate_shacl_report)


# ── Full four-layer pipeline on A123 ─────────────────────────────────────────


def test_validate_record_report_clean_on_a123() -> None:
    """Full pipeline returns no errors for the canonical A123 example record."""
    doc = _load()
    report = validate_record_report(doc, policy=WARN_POLICY)
    errors = [i for i in report.issues if i.severity == "error"]
    assert not errors, f"Expected no errors for valid A123, got: {errors}"


def test_validate_record_report_runs_shacl_layer() -> None:
    """Pipeline includes SHACL layer: injecting 33V produces both semantic AND SHACL warnings."""
    doc = _load()
    doc["properties"]["nominal_voltage"] = {"value": 33.0, "unit": "V"}
    report = validate_record_report(doc, policy=WARN_POLICY)

    sem_codes = {i.code for i in report.issues}
    assert "semantic.value_out_of_plausible_range" in sem_codes, (
        "Expected semantic plausibility warning for 33V nominal_voltage"
    )
    assert "shacl.constraint_violation" in sem_codes, (
        "Expected SHACL warning for 33V nominal_voltage — SHACL layer not running?"
    )


def test_validate_record_strict_policy_clean_on_a123() -> None:
    """Strict policy: A123 example still has zero errors."""
    doc = _load()
    result = validate_record(doc, policy="strict")
    assert result.ok, f"Expected valid A123 to pass strict policy, got issues: {result.issues}"


def test_validate_record_report_structure() -> None:
    """ValidationReport has expected structure after full pipeline run."""
    doc = _load()
    report = validate_record_report(doc, policy=WARN_POLICY)
    # Report is a ValidationReport with expected attributes
    assert hasattr(report, "issues")
    assert hasattr(report, "errors")
    assert hasattr(report, "warnings")
    assert hasattr(report, "ok")
    assert report.ok, f"Expected ok=True for valid A123, issues: {report.issues}"
