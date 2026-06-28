"""Regression tests: non-finite numerics (NaN / +-Infinity) must never silently
flow through import, export, or validation (audit theme A).

NaN/Inf are not valid measurements and are not JSON-serialisable per RFC 8259, so
they must be skipped on the interop boundaries and rejected by validation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.interop import bpx  # noqa: E402
from battinfo.interop.solid_state_db import _number, from_solid_state_db_row  # noqa: E402
from battinfo.validate import validate_record  # noqa: E402


def test_to_bpx_drops_non_finite_and_emits_valid_json() -> None:
    result = bpx.to_bpx({
        "cell_spec": {"name": "X", "cell_format": "cylindrical"},
        "properties": {"nominal_capacity": {"value": float("nan"), "unit": "Ah"},
                       "mass": {"value": 48.0, "unit": "g"}},
    })
    text = result.to_json()
    assert "NaN" not in text and "Infinity" not in text
    json.loads(text)  # must be valid JSON (no parse error)


def test_from_bpx_skips_non_finite_with_warning() -> None:
    result = bpx.from_bpx({"Parameterisation": {"Cell": {"Nominal cell capacity [A.h]": float("nan")}}})
    assert "nominal_capacity" not in result.specs
    assert any("non-finite" in w for w in result.warnings)


def test_solid_state_number_rejects_non_finite() -> None:
    assert _number("nan") is None
    assert _number("inf") is None
    assert _number("-inf") is None
    assert _number("3.5") == 3.5


def test_solid_state_row_with_nan_cycle_life_does_not_crash() -> None:
    res = from_solid_state_db_row({"ID": "42", "CAM_Material": "LiCoO2", "AAM_Material": "Li",
                                   "CLC_CycleLife": "nan"})
    assert res.row_id == "42"


def test_validation_rejects_non_finite_spec_value() -> None:
    doc = json.loads((ROOT / "src/battinfo/data/examples/cell-spec/cell-spec-0hpw-gkhk-gcg8-23x1.json")
                     .read_text(encoding="utf-8"))
    doc["properties"]["nominal_capacity"] = {"value": float("nan"), "unit": "Ah"}
    result = validate_record(doc, policy="strict")
    assert result.ok is False
    assert any(i.code == "semantic.value_not_finite" for i in result.issues)


def test_num_rejects_non_finite() -> None:
    # The shared protocol/discovery/converter numeric coercion must reject non-finite
    # rather than coercing NaN/Inf into a quantity that later fails json.dumps.
    from battinfo.interop.protocols import _num

    assert _num("NaN") is None
    assert _num("Infinity") is None
    assert _num("-inf") is None
    assert _num(float("nan")) is None
    assert _num("3.5") == 3.5


def test_validation_rejects_nested_non_finite_quantity() -> None:
    # The flat specs check missed deeply-nested quantities (e.g. an electrode
    # coating's property.loading.value); the recursive walk catches them.
    from battinfo.validate.semantic import validate_semantic_report

    doc = {"electrode_spec": {"coating": {"property": {"loading": {"value": float("nan"), "unit": "mg/cm2"}}}}}
    result = validate_semantic_report(doc, policy="strict")
    assert any(i.code == "semantic.value_not_finite" for i in result.issues)


def test_walk_non_finite_no_false_positive_on_clean_record() -> None:
    # The whole-record non-finite walk must not flag any value in a clean shipped record.
    from battinfo.validate.semantic import validate_semantic_report

    doc = json.loads((ROOT / "src/battinfo/data/examples/cell-spec/cell-spec-0hpw-gkhk-gcg8-23x1.json")
                     .read_text(encoding="utf-8"))
    result = validate_semantic_report(doc, policy="strict")
    assert not any(i.code == "semantic.value_not_finite" for i in result.issues)
