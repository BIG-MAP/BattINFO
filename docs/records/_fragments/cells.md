A cell is described at two levels, the spec + instance pattern every family
uses. The **cell spec** is the design — the datasheet: manufacturer, model,
format, chemistry, and rated properties as `{value, unit}` quantities. The
**cell instance** is one physical unit built to that design: a serial number
and batch under `cell_spec_id`, plus what was measured on that unit. The
(spec, serial) pair seeds the instance IRI, so re-registering the same cell
is a no-op instead of a duplicate.

A cell instance can also state which physical components went into it —
`working_electrode_id` points at the electrode disc inside this cell (see
[electrodes](electrodes.md)).

## The engineering layer

Beyond composition and nominal performance, a cell spec can carry the
**as-designed engineering** description: how the cell is physically built.
Two things are deliberately excluded: design-tool scratch math (intermediate
volumes, slurry masses — recomputed, not stored) and state-dependent
behaviour (swelling versus cycle, impedance decomposition — those belong to
measurement series on a test or dataset, not to a spec).

Every engineering part follows one **holder + property** principle: identity
fields (`material` / `manufacturer` / `supplier` / `product_id`) plus a
`property` dict of `{value, unit}` quantities. Unknown property keys are
preserved in the record and flagged with a `semantic.property_unmapped`
warning rather than dropped.

Where each part lives:

- The **housing** (case, cap, terminals, seals, discrete parts) is authored
  inline on the cell spec or lifted into a standalone housing spec referenced
  by `housing_spec_id` — its field tables are on the
  [components page](components.md#housing-spec-fields).
- **Current-collector tabs** and **coatings** belong to the electrode — see
  [electrodes](electrodes.md).
- The **electrode-assembly geometry** (wound or stacked: `assembly_type`,
  layer and sheet counts, `winding_turns`, `electrode_length`,
  `jellyroll_volume`) is the cell spec's own `construction` block — see the
  cell-spec field table below.

## Composing a cell from parts

A cell-spec can be described from reusable, IRI-addressable parts: seven
optional top-level reference fields sit beside the inline holders —

| Field | Resolves to |
| --- | --- |
| `positive_electrode_spec_id` / `negative_electrode_spec_id` | `electrode-spec` |
| `working_electrode_spec_id` / `counter_electrode_spec_id` | `electrode-spec` |
| `electrolyte_spec_id` | `electrolyte-spec` |
| `separator_spec_id` | `separator-spec` |
| `housing_spec_id` | `housing-spec` |

Which electrode pair a cell uses follows from its `cell_configuration` —
polarity for a full cell, role for a half or three-electrode cell (see
[electrodes](electrodes.md#cells-reference-electrodes)). A cell may
**reference**, **inline**, or both — inline holders stay optional, so
existing records are unaffected. The JSON-LD emits reference nodes
(`hasPositiveElectrode: {"@id": <electrode-spec IRI>}`, etc.); when an
inline node is also present, the `@id` merges onto it.

References are **checked at save**: a `*_spec_id` that points at nothing
fails the save with the missing IRI named (opt out with
`resolve_references=False` for staged workflows; `save_batch` allows
references within the batch and validates the completed set). The bench
recipe is [How-to: build a cell from components](../howto/build-a-cell-from-components.md),
and `extract_component_specs(cell_spec_record)` goes the other way, lifting
a cell's inline holders into standalone component-specs so any inline cell
can be decomposed and de-duplicated.

The example cells on the shelf below use exactly this pattern — shared
component-specs referenced by IRI across the fleet. The NMC811 coin shows
the complete graph end-to-end:

```text
cell-spec COIN-NMC811-D  →  cell-instance (P025-CEL-001)  →  test (cycling)  →  dataset
        ↓ references
   electrode-spec / electrolyte-spec / separator-spec / housing-spec  →  material-specs
```

