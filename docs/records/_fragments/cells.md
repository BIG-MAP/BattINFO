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

Two deeper treatments live beside this page: [cell fleets](../cell-fleet.md)
(reference-based authoring patterns for many cells against one spec) and the
[engineering cell description](../engineering-cell-description.md) (housing,
tabs, electrode-assembly geometry for prismatic/cylindrical/pouch designs).

```{toctree}
:hidden:

../cell-fleet
../engineering-cell-description
```
