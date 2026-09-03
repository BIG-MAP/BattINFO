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

A deeper treatment of authoring many cells against one spec lives beside
this page: [cell fleets](../cell-fleet.md) (reference-based authoring
patterns for a fleet).

```{toctree}
:hidden:

../cell-fleet
```
