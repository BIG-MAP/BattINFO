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
