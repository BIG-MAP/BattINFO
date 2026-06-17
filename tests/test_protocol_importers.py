"""Tests for the executable-protocol importers (Phase 3): aurora-unicycler,
PyBaMM experiments, and bmgen EMMO JSON-LD -> structured TestSpec.method."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.interop.protocols import (  # noqa: E402
    import_aurora_unicycler,
    import_bmgen_jsonld,
    import_pybamm_experiment,
)
from battinfo.validate import validate_json  # noqa: E402

SPEC_ID = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"

AURORA = {
    "unicycler": {"version": "0.3.2"},
    "sample": {"name": "cell-1", "capacity_mAh": "123"},
    "record": {"current_mA": "0.1", "voltage_V": "0.1", "time_s": "10"},
    "safety": {"max_voltage_V": "5", "min_voltage_V": "-0.1", "max_current_mA": "10",
               "min_current_mA": "-10", "max_capacity_mAh": None, "delay_s": "10"},
    "method": [
        {"step": "open_circuit_voltage", "until_time_s": "3600"},
        {"step": "constant_current", "rate_C": "0.1", "until_voltage_V": "4.2"},
        {"step": "constant_voltage", "voltage_V": "4.2", "until_rate_C": "0.05"},
        {"step": "constant_current", "rate_C": "-0.1", "until_voltage_V": "2.5"},
        {"step": "loop", "loop_to": 2, "cycle_count": 3},
    ],
}


def test_import_aurora_unicycler_method_safety_record_loop() -> None:
    spec = import_aurora_unicycler(AURORA, source_locator="files/cc.unicycler.json",
                                   source_sha256="a" * 64)
    # OCV rest, then a 3× group of [CC charge, CV hold, CC discharge].
    assert [s.mode for s in spec.method] == ["rest", "group"]
    group = spec.method[1]
    assert group.count == 3
    assert [s.mode for s in group.steps] == ["cc", "cv", "cc"]

    charge = group.steps[0]
    assert charge.direction == "charge"
    assert charge.setpoints["c_rate"].value == 0.1
    assert charge.termination[0].direction == "above" and charge.termination[0].value == 4.2

    hold = group.steps[1]
    assert hold.mode == "cv" and hold.setpoints["voltage"].value == 4.2
    assert hold.termination[0].quantity == "c_rate" and hold.termination[0].value == 0.05

    discharge = group.steps[2]
    assert discharge.direction == "discharge"      # negative rate_C
    assert discharge.termination[0].direction == "below" and discharge.termination[0].value == 2.5

    assert spec.record == {"current_mA": 0.1, "voltage_V": 0.1, "time_s": 10}
    assert spec.safety["max_voltage_V"] == 5
    assert spec.test_type.value == "cycling"       # inferred from the loop
    assert spec.artifacts[0].format == "aurora-unicycler-json"

    spec.id = SPEC_ID
    assert validate_json(spec.to_record(), profile="test-protocol").ok


def test_import_pybamm_experiment_folds_repeated_cycles() -> None:
    spec = import_pybamm_experiment(
        [("Charge at 1 C until 4.2 V", "Discharge at 1 C until 2.5 V")] * 3
        + ["Rest for 1 hour"],
        source_locator="files/exp.py",
    )
    assert [s.mode for s in spec.method] == ["group", "rest"]
    assert spec.method[0].count == 3
    assert [s.direction for s in spec.method[0].steps] == ["charge", "discharge"]
    assert spec.test_type.value == "cycling"
    assert spec.artifacts[0].format == "pybamm-experiment"
    spec.id = SPEC_ID
    assert validate_json(spec.to_record(), profile="test-protocol").ok


def test_import_pybamm_to_config_via_description() -> None:
    # to_config() form: a single cycle with steps carrying their PyBaMM string.
    config = {"cycles": [[
        {"type": "CurrentStep", "value": "1C", "termination": ["4.2 V"],
         "description": "Charge at 1 C until 4.2 V"},
        {"type": "CurrentStep", "value": "-1C", "termination": ["2.5 V"],
         "description": "Discharge at 1 C until 2.5 V"},
    ]]}
    spec = import_pybamm_experiment(config, source_locator="files/exp.json")
    # Single cycle flattens (no group).
    assert [s.mode for s in spec.method] == ["cc", "cc"]
    assert [s.direction for s in spec.method] == ["charge", "discharge"]
    assert spec.method[0].termination[0].direction == "above"
    assert spec.artifacts[0].format == "pybamm-experiment"
    spec.id = SPEC_ID
    assert validate_json(spec.to_record(), profile="test-protocol").ok


def test_import_pybamm_to_config_structural_fallback_and_cycles() -> None:
    # No description → interpret type/value/direction/termination; 3 identical cycles fold.
    cycle = [
        {"type": "CurrentStep", "direction": "Charge", "value": "1C", "termination": ["4.2 V"]},
        {"type": "VoltageStep", "direction": "Charge", "value": 4.2, "termination": ["C/50"]},
        {"type": "CurrentStep", "direction": "Discharge", "value": "1C", "termination": ["2.5 V"]},
    ]
    config = {"cycles": [cycle, cycle, cycle]}
    spec = import_pybamm_experiment(config)
    assert [s.mode for s in spec.method] == ["group"]
    grp = spec.method[0]
    assert grp.count == 3
    assert [s.mode for s in grp.steps] == ["cc", "cv", "cc"]
    assert grp.steps[1].setpoints["voltage"].value == 4.2
    assert grp.steps[1].termination[0].quantity == "c_rate"
    assert spec.test_type.value == "cycling"


BMGEN = {
    "@context": {"@context": "https://w3id.org/emmo/domain/battery/context"},
    "@graph": [
        {"@type": "ConstantCurrentConstantVoltageCharging", "hasProcessParameter": [
            {"@type": "ChargingCurrent", "hasNumericalPart": {"hasNumberValue": 2.0}},
            {"@type": "ChargingVoltage", "hasNumericalPart": {"hasNumberValue": 4.2}},
            {"@type": "TerminationQuantity", "hasNumericalPart": {"hasNumberValue": 0.1}},
        ]},
        {"@type": "ConstantCurrentDischarging", "hasProcessParameter": [
            {"@type": "DischargingCurrent", "hasNumericalPart": {"hasNumberValue": 1.0}},
            {"@type": "LowerVoltageLimit", "hasNumericalPart": {"hasNumberValue": 3.0}},
        ]},
    ],
}


def test_import_bmgen_jsonld_reshapes_process_graph() -> None:
    spec = import_bmgen_jsonld(BMGEN, source_locator="files/program.jsonld")
    assert [s.mode for s in spec.method] == ["cccv", "cc"]
    charge = spec.method[0]
    assert charge.direction == "charge"
    assert charge.setpoints["current"].value == 2.0
    assert charge.setpoints["voltage"].value == 4.2
    assert charge.termination[0].quantity == "current" and charge.termination[0].direction == "below"

    discharge = spec.method[1]
    assert discharge.direction == "discharge"
    assert discharge.termination[0].quantity == "voltage" and discharge.termination[0].value == 3.0
    assert spec.artifacts[0].format == "bmgen-jsonld"
    spec.id = SPEC_ID
    assert validate_json(spec.to_record(), profile="test-protocol").ok
