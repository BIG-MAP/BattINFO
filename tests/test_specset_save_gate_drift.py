"""One property vocabulary: a key the model advertises is never rejected at save.

``battinfo.SpecSet`` (LinkML-generated from schema/cell-spec.yaml), the records
@context, and the shipped save-gate schema
(src/battinfo/data/schemas/cell-canonical.schema.json ``$defs.SpecSet``, which
cell-spec.schema.json references) must agree on the property key set. Before this
gate, five SpecSet keys (charging_cutoff_voltage, upper_voltage_limit,
maximum_pulse_charging_current, operating_temperature_min/max, and the two the
audit missed) were advertised by the model yet rejected by
``additionalProperties: false`` at ws.save. This test fails the moment a SpecSet
slot is added without also extending the save gate and the context.
"""

from __future__ import annotations

import json
from pathlib import Path

from battinfo.bundle_generated import SpecSet

ROOT = Path(__file__).resolve().parents[1]
SAVE_GATE = ROOT / "src" / "battinfo" / "data" / "schemas" / "cell-canonical.schema.json"
CONTEXT = ROOT / "src" / "battinfo" / "data" / "context" / "records.context.json"


def _specset_keys() -> set[str]:
    return set(SpecSet.model_fields)


def _save_gate_keys() -> set[str]:
    schema = json.loads(SAVE_GATE.read_text(encoding="utf-8"))
    return set(schema["$defs"]["SpecSet"]["properties"])


def _context_keys() -> set[str]:
    return set(json.loads(CONTEXT.read_text(encoding="utf-8"))["@context"])


def test_every_specset_key_is_accepted_by_the_save_gate() -> None:
    missing = sorted(_specset_keys() - _save_gate_keys())
    assert not missing, (
        "SpecSet advertises keys the save gate rejects at ws.save: "
        f"{missing}. Add them to $defs/SpecSet/properties in "
        "assets/schemas/cell-canonical.schema.json and re-sync the package copy."
    )


def test_every_specset_key_is_mapped_in_the_records_context() -> None:
    missing = sorted(_specset_keys() - _context_keys())
    assert not missing, (
        f"SpecSet keys absent from the records @context: {missing}. "
        "Add their EMMO mapping in schema/*.yaml and regenerate the context."
    )


def test_save_gate_specset_is_closed() -> None:
    # The gate must stay strict; the fix is to widen the key set, not to open it.
    schema = json.loads(SAVE_GATE.read_text(encoding="utf-8"))
    assert schema["$defs"]["SpecSet"]["additionalProperties"] is False


# ── Measured-instance keys ────────────────────────────────────────────────────
# A cell instance's `measured` block records what an individual cell actually
# did; IEC nominal/rated capacity are manufacturer declarations about the
# product type. The direction-qualified keys (discharging_/charging_ capacity
# and energy, matching the BDF column vocabulary and the EMMO
# DischargingCapacity/ChargingCapacity/DischargingEnergy/ChargingEnergy
# classes) exist so a measured value never has to masquerade as a declaration.

_MEASURED = {
    "discharging_capacity": {"value": 4.85, "unit": "Ah"},
    "charging_capacity": {"value": 4.87, "unit": "Ah"},
    "discharging_energy": {"value": 17.6, "unit": "Wh"},
    "charging_energy": {"value": 18.1, "unit": "Wh"},
    "specific_energy": {"value": 252.0, "unit": "Wh/kg"},
    "energy_density": {"value": 720.0, "unit": "Wh/L"},
}


def _example_cell_instance_record() -> dict:
    path = (
        ROOT / "src" / "battinfo" / "data" / "examples" / "cell-instance"
        / "cell-3m6k-9t2p-7x4h-9nq8.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_measured_capacity_and_energy_pass_the_strict_save_gate() -> None:
    from battinfo.validate import ValidationPolicy, validate_record_report

    record = _example_cell_instance_record()
    record["measured"] = dict(_MEASURED)
    report = validate_record_report(
        record, policy=ValidationPolicy(name="strict", semantic="error")
    )
    assert report.ok, [f"{i.code}: {i.message}" for i in report.issues]


def test_measured_capacity_and_energy_round_trip_through_cell() -> None:
    from battinfo.bundle import Cell

    record = _example_cell_instance_record()
    record["measured"] = dict(_MEASURED)
    cell = Cell.from_record(record)
    assert cell.measured == _MEASURED
    assert cell.to_record()["measured"] == _MEASURED


def test_measured_capacity_and_energy_are_typed_specset_fields() -> None:
    from battinfo.bundle_adapter import specs_to_specset, specset_to_specs

    for key in (
        "discharging_capacity",
        "charging_capacity",
        "discharging_energy",
        "charging_energy",
    ):
        assert key in SpecSet.model_fields

    specset = specs_to_specset(dict(_MEASURED))
    assert specset is not None
    # Typed fields, not extras: attribute access works and carries the values.
    assert specset.discharging_capacity.sv_value == 4.85
    assert specset.discharging_capacity.sv_unit == "Ah"
    assert specset.charging_capacity.sv_value == 4.87
    assert specset.discharging_energy.sv_value == 17.6
    assert specset.discharging_energy.sv_unit == "Wh"
    assert specset.charging_energy.sv_value == 18.1
    assert specset_to_specs(specset) == _MEASURED
