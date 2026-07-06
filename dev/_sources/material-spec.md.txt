# Material Spec & Material Instance

BattINFO models every entity as a **spec + instance** pair: a *spec* is the reusable,
datasheet-like type description; an *instance* is a physical realization of that spec.
This page documents the first standalone material family — `material-spec` (the type)
and `material` (a physical lot/batch) — and the entity registry that makes adding such
families uniform.

## The entity registry

All record types are declared once in [`src/battinfo/entities.py`](../src/battinfo/entities.py)
as `EntityKind` entries (top-level JSON key, schema file, on-disk subdirectory, IRI
namespace, and the instance→spec link field). Dispatch, validation, IRI minting, the
record-set directory list, and `build_index` all derive from this registry, so a new
spec/instance family is a single registry entry plus its schema and examples — not a
copy-paste across `api.py`, `ws.py`, and the validators.

## Records

### `material-spec`

A reusable material specification. Top-level key `material_spec`.

| Field | Required | Notes |
| --- | --- | --- |
| `id` | ✓ | `https://w3id.org/battinfo/material-spec/{uid}` |
| `name` | ✓ | Material grade, e.g. `"LFP"`, `"Graphite"`, `"NMC811"` |
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

### Structured composition

For derived/blended grades, `composition` references other material-specs by IRI:

```json
"composition": {
  "base_material_id": "https://w3id.org/battinfo/material-spec/<NMC811>",
  "coatings": [{"material_spec_id": "https://w3id.org/battinfo/material-spec/<Al2O3>",
                "name": "Al2O3", "property": {"thickness": {"value": 5, "unit": "nm"}}}],
  "dopants": [{"element": "Al", "fraction": {"value": 0.01, "unit": "1"}}],
  "constituents": []
}
```

All `*_material_id` references are existence-checked against material-spec records.

### `material`

A physical lot/batch realizing a spec. Top-level key `material`. Links to its spec via
`material_spec_id`; carries lot facts (`lot_id`, `supplier`, `received_date`, measured
`property`) and a `datasets[]` array linking the lot to its characterization data
(XRD/SEM/ICP/PSD), each `{id, role}` existence-checked against `dataset` records.

## Bridge: embedded ↔ standalone

Cell-specs still embed materials inline (`positive_electrode.coating.component`,
`electrolyte.salt`, …). To dedup a material across many cells, lift the embedded holder
to a standalone spec and reference it by IRI:

```python
specs = bi.extract_material_specs(cell_spec_record)   # one material-spec per unique material
spec  = bi.material_spec_from_component(holder, material_class="active_material")
holder = bi.link_component_to_spec(holder, spec["material_spec"]["id"])  # holder now carries material_spec_id
```

The embedded `material-component` holder gained an optional `material_spec_id` field for
this reference. Rewiring the full cell-spec fleet onto references is Phase 3.

## Worked example (Python API)

```python
import battinfo as bi

spec = bi.create_material_spec(
    name="LFP",
    material_class="active_material",
    electrode_polarity="positive",
    formula="LiFePO4",
    chemistry_family="olivine",
    manufacturer="Canrud",
    property={"specific_capacity": {"value": 160, "unit": "mAh/g"}},
)
bi.save_material_spec(spec, source_root="examples")

lot = bi.create_material(
    material_spec_id=spec["material_spec"]["id"],
    lot_id="CANRUD-LFP-2026-03",
    supplier="Canrud",
    property={"mass": {"value": 19.5, "unit": "mg"}},
)
bi.save_material(lot, source_root="examples")  # resolves the material_spec_id reference

bi.query_material_specs(material_class="active_material")
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
> by the forthcoming `electrolyte-spec` family, which assembles these material-spec
> constituents. See the spec/instance roadmap for the remaining component families
> (electrode, electrolyte, separator, current-collector, housing).
