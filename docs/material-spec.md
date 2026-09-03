# Material fields

BattINFO models every entity as a **spec + instance** pair: a *spec* is the reusable,
datasheet-like type description; an *instance* is a physical realization of that spec.
This page is the field reference for the material family — `material-spec` (the grade)
and `material` (a physical lot/batch).

> **Just want to register your materials?** The recipe is
> [How-to: register materials](howto/register-materials.md). (How new
> spec/instance families are added uniformly — the entity registry in
> [`src/battinfo/entities.py`](../src/battinfo/entities.py) — is an
> implementation topic; see [How BattINFO is built](how-battinfo-is-built.md).)

## Records

### `material-spec`

A reusable material specification. Top-level key `material_spec`.

| Field | Required | Notes |
| --- | --- | --- |
| `id` | ✓ | `https://w3id.org/battinfo/spec/{uid}` — content-derived from (manufacturer, product, grade); re-authoring the same product is a no-op |
| `name` | ✓ | Material grade, e.g. `"LFP"`, `"Graphite"`, `"NMC811"` |
| `kind` | ✓ (at save) | Level-1 [MaterialKind](materials-model.md) key from the curated vocabulary (`graphite`, `lfp`, `nmc811`, …). The genome's aggregation axis; resolves to the kind's chemical-substance class IRI. Aliases resolve on input; an unknown kind is rejected at save. See `battinfo.materials.material_kind_keys()` |
| `grade` | | Manufacturer grade / product version; part of spec identity |
| `material_class` | | `active_material`, `binder`, `conductive_additive`, `current_collector`, `separator_material`, `electrolyte_salt`, `electrolyte_solvent`, `electrolyte_additive`, `metal_electrode`, `coating`, `other` |
| `electrode_polarity` | | `positive` / `negative` / `none` (for active materials) |
| `formula` | | Idealized composition, e.g. `LiFePO4`, `C`, `Zn`, `(C2H2F2)n` |
| `chemistry_family` | | Coarse family label, e.g. `olivine`, `layered-oxide`, `spinel` |
| `manufacturer` / `supplier` | | Organization reference — a plain name string **or** an `{type: Organization, name, id}` object whose `id` links to an `organization` record |
| `product_id` | | Manufacturer / supplier grade identifier |
| `composition` | | Structured derivation: `base_material_id`, `coatings[]`, `dopants[]`, `constituents[]` (see below) |
| `property` | | Curated quantity map (snake_case keys → `{value, unit}`), e.g. `specific_capacity`, `true_density`, `particle_size_d50`. Each quantity may carry `co_type` + `conditions` (see below) |

### Properties with conditions

A quantity is rarely meaningful without the conditions it was measured under. Any
quantity (here and in cell/test records) may carry an optional `co_type`
(`Measured` / `Conventional` / `Rated` / `Nominal`) and a `conditions` map — each
condition is itself a quantity (`discharge_c_rate`, `lower_voltage_limit`,
`upper_voltage_limit`, `temperature`, `counter_electrode`, …):

```json
"specific_capacity": {
  "value": 160, "unit": "mAh/g", "co_type": "Measured",
  "conditions": {
    "discharge_c_rate":   {"value": 0.1, "unit": "C"},
    "lower_voltage_limit":{"value": 2.5, "unit": "V"},
    "upper_voltage_limit":{"value": 3.65,"unit": "V"},
    "temperature":        {"value": 25,  "unit": "degC"},
    "counter_electrode":  {"value_text": "Li metal", "unit_text": "n/a"}
  }
}
```

In JSON-LD this emits a typed EMMO property (`[SpecificCapacity, MeasuredProperty]`)
with each condition as a `hasMeasurementParameter`. Plausibility bounds and unit
compatibility are checked for known material keys during semantic validation.

### Properties that summarise a sample

A lab number is often a batch average. When it is, say so: `standard_deviation` (in the same unit as `value`) and `sample_count` sit alongside `value` and `unit` on the same quantity, so the mean and its spread stay one property instead of competing for the same EMMO class.

```json
"loading": {
  "value": 3.6472, "unit": "mg/cm2",
  "standard_deviation": 0.3017, "sample_count": 8,
  "min_value": 3.2844, "max_value": 4.0667
}
```

A zero standard deviation is published, not suppressed: it says every member of the sample carried the same number, which is a finding about how the value was obtained rather than a missing value.

In JSON-LD both ride `schema:valueReference` as named `schema:PropertyValue` qualifiers on the property node — the standard deviation carrying the quantity's unit, the count carrying none:

```json
"schema:valueReference": [
  {"@type": "schema:PropertyValue", "schema:propertyID": "standard_deviation",
   "schema:value": 0.3017, "schema:unitText": "mg/cm2"},
  {"@type": "schema:PropertyValue", "schema:propertyID": "sample_count", "schema:value": 8}
]
```

Not an EMMO class, because there is not one: the pinned closure publishes no `StandardDeviation`, `Variance` or `SampleCount`, and the additions are queued upstream. It does publish `MetrologicalUncertainty`, which is deliberately not used here — the spread of a batch of eight discs is a property of a population of distinct objects, not the uncertainty attributed to a single measurand, and typing it as uncertainty would claim something the number does not support.

### Structured composition

For derived/blended grades, `composition` references other material-specs by IRI:

```json
"composition": {
  "base_material_id": "https://w3id.org/battinfo/spec/<NMC811>",
  "coatings": [{"material_spec_id": "https://w3id.org/battinfo/spec/<Al2O3>",
                "name": "Al2O3", "property": {"thickness": {"value": 5, "unit": "nm"}}}],
  "dopants": [{"element": "Al", "fraction": {"value": 0.01, "unit": "1"}}],
  "constituents": []
}
```

All `*_material_id` references are existence-checked against material-spec records.

### `material`

A physical lot/batch realizing a spec. Top-level key `material`. Its `id`
(`https://w3id.org/battinfo/material/{uid}`) is content-derived from (spec_id, lot).
Links to its spec via `material_spec_id` (required); carries lot facts (`lot_id`,
`supplier`, `received_date`, `opened_date`, `expires_at`, `amount`, `storage`), a
`processing` block, an OPEN measured `property` block for as-received
characterisation (unmapped keys get the standard labeled-fallback + warning, not a
closed vocabulary), and a `datasets[]` array linking the lot to its characterization
data (XRD/SEM/ICP/PSD), each `{id, role}` existence-checked against `dataset` records.

Processing lives HERE, never on the spec: aqueous vs NMP is not a distinct product.

| Field | Required | Notes |
| --- | --- | --- |
| `material_spec_id` | ✓ | Level-2 spec IRI |
| `lot_id` | | Lot / batch number (accepts `lot=` in `ws.add`); part of instance identity |
| `processing` | | `{route: aqueous\|nmp\|dry\|other, solvent, detail}` |
| `amount` | | Quantity on hand/consumed, `{value, unit}` |
| `storage` | | Storage conditions, free text |
| `property` | | OPEN as-received measurement map |

Both `material-spec` and `material` carry record-level `contributor` / `license` /
`funding`, stamped by `ws.save` exactly like every other record type.

## Bridge: embedded ↔ standalone

Cell-specs still embed materials inline (`positive_electrode.coating.component`,
`electrolyte.salt`, …). To dedup a material across many cells, lift the embedded holder
to a standalone spec and reference it by IRI:

```python
from battinfo.materials import (
    extract_material_specs, link_component_to_spec, material_spec_from_component)

specs = extract_material_specs(cell_spec_record)   # one material-spec per unique material
spec  = material_spec_from_component(holder, material_class="active_material")
holder = link_component_to_spec(holder, spec["material_spec"]["id"])  # holder now carries material_spec_id
```

The embedded `material-component` holder gained an optional `material_spec_id` field for
this reference. Rewiring the full cell-spec fleet onto references is Phase 3.

## Worked example (Python API)

```python
from battinfo.api import (
    create_material, create_material_spec, query_material_specs,
    save_material, save_material_spec)

spec = create_material_spec(
    name="LFP",
    material_class="active_material",
    electrode_polarity="positive",
    formula="LiFePO4",
    chemistry_family="olivine",
    manufacturer="Canrud",
    property={"specific_capacity": {"value": 160, "unit": "mAh/g"}},
)
save_material_spec(spec, source_root="examples", mode="upsert")

lot = create_material(
    material_spec_id=spec["material_spec"]["id"],
    lot_id="CANRUD-LFP-2026-03",
    supplier="Canrud",
    property={"mass": {"value": 19.5, "unit": "mg"}},
)
save_material(lot, source_root="examples", mode="upsert")  # resolves the material_spec_id reference

# pass directory= explicitly — the default reads the packaged examples
query_material_specs(material_class="active_material", directory="examples/material-spec")
```

## Examples

Canonical examples live in [`examples/material-spec/`](https://github.com/BIG-MAP/BattINFO/tree/main/examples/material-spec) and
[`examples/material/`](https://github.com/BIG-MAP/BattINFO/tree/main/examples/material) (the single source of truth, mirrored into
the wheel by `scripts/sync_examples.py`). Coverage spans graphite, LFP, NMC811, NMC622,
LCO, LMFP, LNMO, zinc, carbon black, PVDF, and the KOH / LiPF6 / EC / EMC electrolyte
constituents. The Li-ion cathode/anode actives and electrolyte salts/solvents are
grounded in the DIGIBAT Discovery-Benchmark coin-cell corpus; LNMO, zinc, and KOH are
synthetic reference examples.

> Electrolyte *formulations* (e.g. "7M KOH in H₂O", "1M LiPF₆ EC:EMC 3:7") are modelled
> by the [`electrolyte-spec`](component-specs.md) family, which assembles these
> material-spec constituents; coated electrodes are modelled by
> [`electrode-spec`](electrodes-model.md), which names its active material's kind and may
> reference the powder's material-spec.
