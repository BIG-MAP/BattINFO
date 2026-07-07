# Test specs

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
mode/direction/setpoints/termination); `facets` are derived automatically for filtering.
The model is two-layer by design: a descriptive `method[]` (what the procedure is) plus
actionable `artifacts[]` (runnable protocol files carried as linked distributions).

> The `kind` enum in `test-protocol.schema.json` is kept in sync with the `BatteryTestType`
> Python enum (`bundle.py`); the coverage test guards against drift.

## Semantic depth of a test protocol

The current representation types the protocol at the class level and carries a free-text
`description`. EMMO domain-electrochemistry has richer terms that allow a more explicit,
machine-replicable representation — here is what is available and when to use it.

### What the ontology provides

| EMMO term | Meaning |
|---|---|
| `ConstantCurrentConstantVoltageCycling` | The complete CC-CV cycle-life protocol |
| `ConstantCurrentConstantVoltageCharging` | A single CC-CV charge step |
| `ConstantCurrentDischarging` | A single CC discharge step |
| `Resting` | A rest / OCV hold step |
| `ElectrochemicalTestingProcedure` | General electrochemical test container |
| `SerialWorkflow` / `IterativeWorkflow` | Structural containers for step sequences |
| `hasNext` / `precedes` / `follows` | Step-to-step sequencing predicates |
| `StepDuration`, `StepSignalCurrent`, `StepSignalVoltage` | Per-step parameters |

A 1C CC-CV cycle-life protocol could therefore be expressed as an `IterativeWorkflow`
containing a `SerialWorkflow` whose steps are:
`ConstantCurrentConstantVoltageCharging` → `Resting` → `ConstantCurrentDischarging` →
`Resting`, each step carrying typed parameters for C-rate, voltage limit, cut-off
current, rest duration, and temperature.

### Pros of explicit step decomposition

- **Machine-replicable**: the test can be reproduced from the JSON-LD alone without
  parsing free text.
- **SPARQL-queryable at step level**: structured queries like *"find all datasets charged
  to 4.2 V at 1C CC-CV"* become precise rather than text-search-based.
- **Parameter validation**: step parameters (C-rate, voltage limits, temperatures) can
  be range-checked against cell specs and standards (IEC 62660, EUCAR) automatically.
- **Stable protocol identity**: the semantic structure survives even if the free-text
  description is incomplete or updated.

### Cons and practical limits

- **Authoring burden**: a four-step cycle becomes a graph of ~10 typed nodes. No
  researcher will author this by hand, so tooling is a prerequisite.
- **EMMO coverage gaps**: GITT, interspersed EIS, multi-rate formation sequences, and
  temperature ramps do not yet have first-class EMMO step types. Mixed typed/free-text
  nodes undermine the value of the graph.
- **Cycler-file redundancy and false precision**: the ground-truth protocol is usually
  the binary file in Biologic BT-Lab, Maccor, or Arbin format. A parallel step graph
  that was hand-authored can silently diverge from what was actually run — which is
  worse than no graph at all.
- **Version fragility**: step-graph records couple tightly to specific EMMO term IRIs.
  An upstream rename invalidates stored records in a way that a text description does
  not.

### Current recommendation

Type the protocol at the class level (e.g. `ConstantCurrentConstantVoltageCycling`) and
record protocol-level parameters (C-rate, voltage window, temperature, cut-off
condition) as typed properties. Keep the free-text `description` as the human-readable
ground truth. Reserve step-level decomposition for cases where:

1. The protocol is simple enough to express without gaps (standard CC, CC-CV, or rest
   steps only), **and**
2. The step graph is generated programmatically from a machine-readable protocol
   definition (e.g. a cycler script), not authored by hand.

When the cycler file is included as a dataset distribution, it already carries the
authoritative step definition — the EMMO class typing on the protocol record is
then sufficient for discovery and filtering.
