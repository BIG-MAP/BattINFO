# Engineering cell description

A cell-spec carries two layers of information. Its **composition and nominal
performance** — chemistry, electrode bases, capacity, voltage — describe what
the cell *is*. Its **as-designed engineering** description records how the cell
is physically built: the housing and can, the terminals and current-collector
tabs, the wound or stacked electrode assembly, seals, and secondary coatings.

This page is the reference for that engineering layer. Every field below is part
of the shipped record model and validates today; the worked examples at the end
are authored through the package and pass `battinfo validate`.

The engineering layer deliberately excludes two things: design-tool scratch
math (intermediate volumes, slurry masses — recomputed, not stored) and
state-dependent behaviour (swelling versus cycle, impedance decomposition —
these belong to measurement series on a `test`/`dataset`, not to a spec).

## Design principle: holder + property

Every engineering part is a **holder**: identity fields
(`material` / `manufacturer` / `supplier` / `product_id`) plus a `property`
dict of `{value, unit}` quantities. The quantities ride the same generic
descriptor emitter every other holder uses, so a part gains no bespoke transform
logic — it names its material and lists its measured quantities, and the JSON-LD
export types and emits them. Unknown property keys are preserved in the record
and flagged with a `semantic.property_unmapped` warning rather than dropped.

## Housing

`CellSpec.housing` is the format-neutral mechanical enclosure. It replaces the
retired coin-specific `coin_hardware` dict (which still loads, migrating into
`housing` automatically). A housing can be authored inline on a cell-spec or
lifted into a standalone `housing-spec` record referenced by
`housing_spec_id` — see [Components](component-specs.md).

| Field | Model | Holds |
| --- | --- | --- |
| `case` | `Case` | the case/can: `size_code`, `material`, `coating`, `property` (wall thickness, weight, available volume, filling ratio, outer dimensions) |
| `cap` | `HardwarePart` | the cap/lid |
| `terminals` | `list[Terminal]` | external terminals, each with `polarity` and `property` (width, thickness, weld width) |
| `seals` | `list[Seal]` | pouch/prismatic seals |
| `parts` | `list[HardwarePart]` | discrete parts (spring, spacer, can, vent, ...) each carrying a free-text `type` |

The case JSON-LD `@type` is chosen from the cell format: a `prismatic` cell
emits `PrismaticCase`, `cylindrical` emits a cylindrical can, `coin` emits a
coin case, and so on.

## Current-collector tabs

Tabs belong to an electrode's current collector, so each electrode carries an
optional `tab` (`Electrode.tab`, a `CurrentCollectorTab`): `material`,
`manufacturer` / `supplier` / `product_id`, and a `property` dict (width,
thickness, length, weld width, tape width). It emits under
`hasCurrentCollectorTab` on the electrode node.

## Electrode-assembly geometry (stack / jelly-roll)

`CellSpec.construction` (`CellConstruction`) records the durable geometry of the
wound or stacked electrode assembly:

| Field | Meaning |
| --- | --- |
| `assembly_type` | e.g. `wound`, `stacked` |
| `layering` | `single_layer`, `multilayer`, `not_applicable`, `unknown` (wound cells use `not_applicable`; the winding is described by the fields below) |
| `layer_count` | stacked-cell layer count |
| `cathode_sheet_count` / `anode_sheet_count` / `separator_sheet_count` | sheet counts of the assembly |
| `winding_turns` | number of turns for a jelly-roll |
| `electrode_length` | quantity: length of the wound electrode strip |
| `jellyroll_volume` | quantity: volume of the wound assembly |

## Coatings

An electrode's `coating` (`Coating`) carries the active/binder/additive
composition and its own `property` dict. Secondary layers — for example a
ceramic coating on the separator or electrode — are modelled as an additional
coating holder, so no new field type is needed to express them.

## EMMO term status

Most engineering quantities and part types resolve to existing EMMO classes:
`PrismaticCase`, `CylindricalCase`, `CoinCase`, `CellCan`, `CellLid`,
`Terminal`, `CurrentCollectorTab`, `ElectrodeStack`, `CalenderedDensity`,
`MassLoading`, `Thickness`, `Volume`, and `Length`.

A few terms are not yet in the ontology: `Seal`, `JellyRoll`, `CeramicCoating`,
and cylindrical safety hardware such as a safety vent or current-interrupt
device. Until they are added upstream (tracked in the ontology-additions queue),
a part of one of these kinds is emitted carrying its authored label
(`skos:prefLabel` / `schema:additionalType`) and fires a
`semantic.hardware_part_unmapped` or `semantic.property_unmapped` warning — the
value is preserved, never silently dropped, but it is not yet a typed EMMO node
and will not survive a round-trip as a typed part. This is the expected state
for those parts today, and it is why the cylindrical example below emits one
warning for its vent.

## Worked examples

Three housing examples ship under `examples/housing-spec/`, one per format,
grounded in the DIGIBAT Discovery-Benchmark and the Cell Design Tool:

| Format | Example | Engineering content |
| --- | --- | --- |
| coin | `housing-spec-38af-bpnv-1zmm-32hs.json` | CR2032 case + spring + spacer |
| prismatic | `housing-spec-ypyh-v38v-r276-snmk.json` | LFP 100 Ah aluminium case + Al/Cu terminals + PP seals |
| cylindrical | `housing-spec-k2q4-dk79-g890-7veq.json` | 21700 nickel-plated steel can + Al/Ni current-collector tabs + top-cap safety vent |

The cylindrical example is authored through `create_component_spec("housing", …)`,
passes `battinfo validate`, emits a `CylindricalCase` node, and is stamped at the
current `schema_version`. Its case `@type` is derived from `cell_format`
(`cylindrical` → `CylindricalCase`). The safety vent is carried as a `vent`
part — a dedicated `parts[].type` value. It has no EMMO class yet, so it is
emitted with its authored label and a `semantic.hardware_part_unmapped` warning,
pending an upstream `SafetyVent` term.

The **jelly-roll** geometry of a wound cell is authored on the cell-spec's
`construction` block (the `CellConstruction` fields above: `winding_turns`,
`cathode_sheet_count` / `anode_sheet_count` / `separator_sheet_count`,
`electrode_length`, `jellyroll_volume`), and current-collector `tab`s attach to
each electrode holder. Author them by constructing a `CellSpec` with these blocks
and calling `to_record()`.
