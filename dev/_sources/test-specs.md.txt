# Test Specs (test-protocol) & full enum coverage

A **test-spec** (`test-protocol` record) is the reusable, IRI-addressable description of a test
procedure — the *spec* half of `test-spec` + `test`. A `test` (instance) links a cell-instance to
a test-spec via `protocol_id` and to its `dataset`s.

`examples/test-protocol/` now carries **one example for every `BatteryTestType`** value (20
kinds), enforced by `tests/test_test_contract.py::test_test_protocol_examples_cover_full_battery_test_type_enum`.

| Kind | Modelled with |
| --- | --- |
| cycling, capacity_check, formation, rate_capability, hppc, ici, gitt, dcir, rpt, quasi_ocv, duty_cycle | structured `method[]` (CC/CV/rest/pulse steps) + `conditions` |
| eis, impedance | an `eis` method step (frequency window + AC amplitude) + `conditions` |
| calendar_ageing | storage `conditions` + check-up cadence |
| wltp, nedc | drive-cycle power profile — `description` + `protocol_url`; the full time-resolved trace is carried as a linked actionable artifact |
| sem, characterization, field, other | minimal `name` + `kind` + `description` (no electrochemical method) |

## Authoring

```python
import battinfo as bi

bi.save_test_spec(bi.TestSpec(
    name="Capacity Check — C/10 at 25 C",
    kind=bi.BatteryTestType.CAPACITY_CHECK,
    description="CC-CV charge then slow C/10 discharge.",
    experiment=["Charge at C/3 until 4.2 V", "Hold at 4.2 V until C/20", "Discharge at C/10 until 2.5 V"],
    conditions={"ambient_temperature": {"value": 25.0, "unit": "degC"}},
), source_root="examples")
```

`experiment` PyBaMM-style strings parse into the structured `method[]` (steps with
mode/direction/setpoints/termination); `facets` are derived automatically for filtering. See
[project_test_spec_model] in the design notes for the two-layer method/artifact model.

> The `kind` enum in `test-protocol.schema.json` is kept in sync with the `BatteryTestType`
> Python enum (`bundle.py`); the coverage test guards against drift.
