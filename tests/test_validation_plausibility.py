"""Tests for the Phase 2 plausibility validation layer.

Covers:
- SPEC_PLAUSIBILITY_BOUNDS checks in validate/semantic.py
- SHACL shapes in assets/shapes/cell-spec.shapes.ttl via validate/shacl.py
- Integration: validate_record_report includes SHACL for cell-spec records
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.validate.core import ValidationPolicy
from battinfo.validate.record import validate_record_report
from battinfo.validate.semantic import validate_semantic_report
from battinfo.validate.shacl import validate_shacl_report

WARN_POLICY = ValidationPolicy(name="warn", semantic="warning")
STRICT_POLICY = ValidationPolicy(name="strict", semantic="error")

_A123 = ROOT / "src" / "battinfo" / "data" / "examples" / "cell-spec" / "A123__ANR26650M1-B.json"


def _load() -> dict:
    return json.loads(_A123.read_text(encoding="utf-8"))


# ── Semantic plausibility (Python layer) ──────────────────────────────────────


def test_plausibility_accepts_valid_record() -> None:
    doc = _load()
    report = validate_semantic_report(doc, policy=WARN_POLICY)
    plausibility_issues = [i for i in report.issues if i.code == "semantic.value_out_of_plausible_range"]
    assert not plausibility_issues, f"Expected no plausibility issues, got: {plausibility_issues}"


@pytest.mark.parametrize(
    "spec_key, bad_value, unit",
    [
        # Voltage decimal-shift errors
        ("nominal_voltage",             33.0,   "V"),    # 33V instead of 3.3V
        ("nominal_voltage",             0.01,   "V"),    # impossibly low
        ("charging_voltage",            55.0,   "V"),    # way too high
        ("discharging_cutoff_voltage",  -2.0,   "V"),    # negative cutoff
        ("charging_cutoff_voltage",     7.0,    "V"),    # above 6V limit
        # Capacity magnitude errors
        ("nominal_capacity",            5000.0, "Ah"),   # 5000 Ah for a single cell
        ("nominal_capacity",            0.0,    "Ah"),   # zero is not positive
        ("rated_capacity",             -1.0,   "Ah"),    # negative
        # Energy
        ("nominal_energy",             -0.5,   "Wh"),    # negative
        # Specific energy out of physical range
        ("specific_energy",             1500.0, "Wh/kg"),# > theoretical Li-metal limit
        ("specific_energy",             0.5,    "Wh/kg"),# < 1 Wh/kg impossibly low
        # Energy density out of range
        ("energy_density",              3000.0, "Wh/L"), # > physical limit
        # Mass magnitude errors
        ("mass",                        0.01,   "g"),    # <0.05 g (below coin cell)
        ("mass",                        100000.0,"g"),   # 100 kg single cell (above large-industrial-cell ceiling)
        # Dimension errors
        ("diameter",                    600.0,  "mm"),   # 60 cm diameter
        ("height",                      2500.0, "mm"),   # 2.5 m height
        ("thickness",                   250.0,  "mm"),   # 25 cm thick
        # Efficiency out of 0-100%
        ("round_trip_energy_efficiency", 105.0, "%"),    # > 100%
        ("capacity_fade",               -5.0,   "%"),    # negative fade
        # Cycle life typo
        ("cycle_life",                  200000,"cycles"),# 200k cycles
    ],
)
def test_plausibility_rejects_bad_spec_value(spec_key: str, bad_value: float, unit: str) -> None:
    doc = _load()
    if spec_key not in doc.get("properties", {}):
        doc.setdefault("properties", {})[spec_key] = {"value": bad_value, "unit": unit}
    else:
        doc["properties"][spec_key] = {"value": bad_value, "unit": unit}

    report = validate_semantic_report(doc, policy=WARN_POLICY)
    plausibility_issues = [i for i in report.issues if i.code == "semantic.value_out_of_plausible_range"]
    assert plausibility_issues, (
        f"Expected plausibility warning for {spec_key}={bad_value} {unit}, "
        f"but got none. All issues: {[i.code for i in report.issues]}"
    )
    assert any(spec_key in i.path for i in plausibility_issues), (
        f"Expected issue path to contain '{spec_key}', got paths: {[i.path for i in plausibility_issues]}"
    )


# ── SHACL layer ───────────────────────────────────────────────────────────────


def test_shacl_accepts_valid_record() -> None:
    doc = _load()
    report = validate_shacl_report(doc, policy=WARN_POLICY)
    assert not report.errors, f"SHACL should produce no errors for valid record, got: {report.errors}"


@pytest.mark.parametrize(
    "spec_key, bad_value, unit, expected_shacl_msg_fragment",
    [
        ("nominal_voltage", 33.0, "V", "0.3, 5.5"),
        ("nominal_capacity", -0.5, "Ah", "positive"),
        ("energy_density", 3500.0, "Wh/L", "2500"),
    ],
)
def test_shacl_warns_on_bad_spec_value(
    spec_key: str, bad_value: float, unit: str, expected_shacl_msg_fragment: str
) -> None:
    doc = _load()
    doc.setdefault("properties", {})[spec_key] = {"value": bad_value, "unit": unit}

    report = validate_shacl_report(doc, policy=WARN_POLICY)
    shacl_issues = [i for i in report.issues if i.code == "shacl.constraint_violation"]
    assert shacl_issues, (
        f"Expected SHACL warning for {spec_key}={bad_value} {unit}, got none. "
        f"All issues: {[i.code for i in report.issues]}"
    )
    assert any(expected_shacl_msg_fragment in i.message for i in shacl_issues), (
        f"Expected SHACL message to contain '{expected_shacl_msg_fragment}'. "
        f"Got messages: {[i.message for i in shacl_issues]}"
    )


def test_shacl_ignores_non_cell_spec_records() -> None:
    """SHACL validation should silently skip dataset/test records."""
    doc = {
        "dataset": {
            "id": "https://w3id.org/battinfo/dataset/test",
            "about": ["https://w3id.org/battinfo/spec/test"],
        }
    }
    report = validate_shacl_report(doc, policy=WARN_POLICY)
    # No SHACL issues — just returns empty report for non-cell-spec records
    shacl_errors = [i for i in report.issues if i.code == "shacl.constraint_violation"]
    assert not shacl_errors


# ── Integration: validate_record_report includes SHACL ────────────────────────


def test_validate_record_includes_shacl_for_valid_record() -> None:
    doc = _load()
    report = validate_record_report(doc, policy=WARN_POLICY)
    shacl_errors = [i for i in report.issues if i.code == "shacl.constraint_violation"]
    assert not shacl_errors, f"Valid A123 record should have no SHACL violations, got: {shacl_errors}"


def test_validate_record_includes_shacl_for_bad_voltage() -> None:
    doc = _load()
    doc["properties"]["nominal_voltage"] = {"value": 33.0, "unit": "V"}
    report = validate_record_report(doc, policy=WARN_POLICY)
    # Should have both semantic plausibility AND SHACL warnings for 33V
    sem_issues = [i for i in report.issues if i.code == "semantic.value_out_of_plausible_range"]
    shacl_issues = [i for i in report.issues if i.code == "shacl.constraint_violation"]
    assert sem_issues, "Expected semantic plausibility warning for 33V"
    assert shacl_issues, "Expected SHACL warning for 33V"
