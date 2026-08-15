# Electrodes: kind, powder spec, electrode spec, batch

The material spec describes the **powder**; the electrode spec describes the
**electrode**. They are different things that people routinely conflate, and
keeping them apart is what lets you say "every Si/Gr anode in the corpus,
regardless of whose silicon it used".

Electrodes extend the materials model by one level rather than repeating it, so
the chain from generic chemistry to the thing you actually put in a cell is four
steps:

| Level | What it is | Form | Example |
| --- | --- | --- | --- |
| 1. **kind** | the *generic* active material | curated vocabulary (not a record) | `silicon_graphite` |
| 2. **material-spec** | a *powder product* | `material-spec` record | Targray NMC811, grade X |
| 3. **electrode-spec** | a *designed electrode* | `electrode-spec` record | Si-Gr anode, aqueous, 90/5/5 |
| 4. **electrode** | an *actual coated batch* | `electrode` record | batch `Si-AQ-1` |

Who references whom: an `electrode-spec` names a level-1 `kind` and *may* point at
a level-2 `material-spec`; an `electrode` points at its `electrode-spec`; a
`cell-spec` may point at an `electrode-spec` for either side. Every arrow points
up the table, and every one except the batch → spec link is optional.

## Level 3 — electrode-spec (the designed electrode)

### Kind is required, the powder reference is not

`kind` names the electrode's **active material**, drawn from the same curated
vocabulary the powders use (`battinfo.electrodes.electrode_kind_keys()` lists the
active-material subset; aliases like `Si/Gr` and `NMC 811` resolve on input).

`active_material_spec_id` — the link to the powder record — is **optional**. That
asymmetry is the design, not an oversight: labs buy electrodes. A purchased
NMC811 cathode sheet whose powder provenance nobody knows is still a first-class,
queryable record that aggregates with every other NMC811 cathode. Author the
powder reference when you have it, and the electrode joins the material corpus
too; leave it out and you lose the powder link, not the record.

A `kind` that resolves but is not an active material (a binder, a salt) is a
**warning**, not an error — the record is still usable, and the author is better
placed than the validator to fix the mix-up. `polarity` is **derived** from the
kind's family, so a record never states the same fact twice; stating a polarity
that contradicts the kind ("LFP anode") warns.

### Composition is the cell-spec coating shape

`coating.component` carries `active_material` / `binder` / `additive`, each a
material holder with a weight fraction under `property.mass_fraction` and an
optional `material_spec_id`. This is *the same shape* a cell-spec's inline
electrode coating already uses — a composition authored on an electrode-spec is a
composition a cell reads, with no translation.

`composition=` is authoring shorthand for that shape, never a second stored form:

```python
composition={"active": 0.90,                                  # name derived from kind
             "binder": {"name": "CMC", "fraction": 0.05},
             "additive": {"name": "Carbon black", "fraction": 0.05}}
```

### Design values

The open `property` map carries what the design specifies: `loading` (areal
loading), `dry_thickness` and `calendered_thickness`, `areal_capacity`,
`porosity`, `diameter` / `width` / `length`. `current_collector` carries the foil
(material name and/or `material_spec_id`) with its `thickness`. Because the map is
open, a design value nobody anticipated needs no schema change — the mapped keys
emit curated EMMO classes (`ActiveMassLoading`, `DryCoatingThickness`,
`CalenderedCoatingThickness`, `AreicCapacity`, `Thickness`), unmapped ones get the
standard labeled fallback plus a warning.

### Processing is spec-level here — and this one matters

An electrode's `processing` block (`route` = `aqueous` | `nmp` | `dry` | `other`,
plus `solvent` and free-text `detail`) is part of the **design**. An
aqueous-processed electrode is a different electrode from an NMP-processed one:
different binder, different drying, different porosity, different performance. So
the route is part of the spec identity, and the same recipe processed two ways
mints two IRIs.

Contrast the material model, where `processing` lives on the **instance**: a
powder lot can legitimately be carbon-coated or not without becoming a different
product. Same field name, deliberately opposite placement, because the two levels
mean different things. Both emit the same way — a `prov:wasGeneratedBy`
Manufacturing process carrying the route as a `schema:DefinedTerm` and the solvent
as a typed substance.

### Identity

A deterministic, content-derived IRI minted from normalized **(producer, product,
grade, kind, processing route)**. Re-authoring the same design is a no-op, never a
duplicate; there is no random-id path. Electrode specs mint under the shared
`spec/` segment, like every other spec (IDENTIFIER_POLICY §6.1).

## Level 4 — electrode (the coated batch)

The physical thing on the bench: a coated web, a sheet, a stack of punched discs.

- **`spec` link** (required) — a built electrode without a design is not
  describable.
- **`batch_id`** (e.g. `Si-AQ-1`), `lot_id` for purchased material, `supplier`,
  `manufactured_at` / `received_date` / `expires_at`, `amount` (coated area, web
  length, mass), `count` (discs), `storage`.
- **An OPEN `property` block** for as-built actuals — measured loading, measured
  calendered thickness, measured porosity, disc diameter and mass. Whatever this
  batch was actually measured for is recordable without a schema change. The
  design values live on the spec; these are what the coater got.
- **Identity** — deterministic from **(spec_id, batch)**. Electrode batches mint
  under the `electrode/` segment.

## Blessed API

```python
ws = battinfo.workspace(".")
ws.license("cc-by-4.0"); ws.contributor(orcid="0000-...")

gr = ws.add("material_spec", name="Targray Si/Gr", kind="silicon_graphite",
            manufacturer="Targray")[0]

anode = ws.add("electrode_spec", name="Si-Gr anode", kind="silicon_graphite",
               manufacturer="SINTEF", grade="AQ",
               active_material_spec_id=gr["material_spec"]["id"],
               composition={"active": 0.90,
                            "binder": {"name": "CMC", "fraction": 0.05},
                            "additive": {"name": "Carbon black", "fraction": 0.05}},
               processing={"route": "aqueous", "solvent": "water"},
               current_collector={"name": "Copper foil",
                                  "thickness": {"value": 10, "unit": "um"}},
               property={"loading": {"value": 6.2, "unit": "mg/cm2"},
                         "areal_capacity": {"value": 2.8, "unit": "mAh/cm2"}})[0]

ws.add("electrode", spec=anode, batch="Si-AQ-1", count=48,
       manufactured_at="2026-03-04", storage="dry room",
       property={"loading": {"value": 6.35, "unit": "mg/cm2"}})

ws.save()   # writes + stamps contributor/license/funding onto both records
```

`spec=` accepts the record returned by `ws.add`, an IRI, or a name added in this
session. Attribution is stamped exactly as on every other record type, and
`ws.submit()` sends electrodes along with everything else.

## Linked data

An electrode-spec node is typed from its kind and its polarity — the chemistry
defined-classes say what it is made of, the polarity class says which side it is
on:

```json
"@type": ["SiliconGraphiteElectrode", "NegativeElectrode"]
```

with the coating as an `ElectrodeCoating` (`hasActiveMaterial` / `hasBinder` /
`hasConductiveAdditive`), the foil as `hasCurrentCollector`, the design values as
`hasProperty`, the powder reference as `hasActiveMaterial` on the electrode
itself, and the processing route as `prov:wasGeneratedBy`. A batch emits
`schema:isVariantOf` → its spec, plus its batch label as a
`schema:PropertyValue`.

## Cells reference electrodes

A cell-spec can cite a designed electrode two ways, both optional and both additive — existing embedded electrode fields stay valid. They say different things, so pick on meaning rather than taste:

- **Prefer** the top-level `positive_electrode_spec_id` / `negative_electrode_spec_id` when the cell spec's electrode simply *is* the published design. The spec's `@id` merges onto the emitted electrode node, so the cell spec and the design are one node in the graph.
- Use `electrode_spec_id` **inside** the `positive_electrode` / `negative_electrode` holder when the inline description is a *variant* of the design, or when both electrodes need independent inline detail. It emits `schema:isVariantOf` — the same seam `material_spec_id` gives an inline material — which states that the holder realizes the design without claiming to be it.

Both are authorable from the model:

```python
cs.positive_electrode_spec_id = "https://w3id.org/battinfo/spec/rkf4-xz0y-h8kz-rmxz"   # preferred
cs.negative_electrode = electrode(bom=bom(active_material=material("Graphite")))
cs.negative_electrode.electrode_spec_id = "https://w3id.org/battinfo/spec/d7qr-n581-74c3-7g7r"
```

An inline current collector cites the foil material the same way, through `current_collector.material_spec_id`.

Cell instances do not yet reference electrode batches; there is no natural slot on
`cell_instance` today, and inventing one was out of scope for the promotion.

## Examples

`examples/electrode-spec/*` and `examples/electrode/*`. The Si-Gr pair
(`grade: AQ` and `grade: NMP`) exists specifically to show the identity rule: same
recipe, same loading, two routes, two IRIs. The batch example shows measured
actuals differing from the design values, which is exactly why the batch is its
own record.

See [materials](materials-model.md) for levels 1-2, and
[components](component-specs.md) for the remaining component families.
