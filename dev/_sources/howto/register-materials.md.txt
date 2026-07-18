# Register the materials in your lab

Five lines per material — create it, save it into your library, keep the IRI:

```python
from battinfo.api import create_material_spec, save_material_spec

nmc = create_material_spec(name="NMC811", material_class="active_material",
                           electrode_polarity="positive", formula="LiNi0.8Mn0.1Co0.1O2")
saved = save_material_spec(nmc, source_root="my-library", mode="upsert")
NMC811_IRI = saved["id"]   # e.g. https://w3id.org/battinfo/spec/3ypr-gngx-x28c-rarf
```

`source_root` is the folder that holds your record library (records land in
`my-library/material-spec/`). `mode="upsert"` makes the call safe to re-run:
the same material converges on the same record instead of erroring as a
duplicate.

## Variants

A binder, a conductive additive, a salt, a solvent — same five lines, different
`material_class`:

```python
pvdf = save_material_spec(create_material_spec(
    name="PVDF", material_class="binder", formula="(C2H2F2)n"),
    source_root="my-library", mode="upsert")

salt = save_material_spec(create_material_spec(
    name="LiPF6", material_class="electrolyte_salt", formula="LiPF6"),
    source_root="my-library", mode="upsert")
```

Valid `material_class` values: `active_material`, `binder`,
`conductive_additive`, `current_collector`, `separator_material`,
`electrolyte_salt`, `electrolyte_solvent`, `electrolyte_additive`,
`metal_electrode`, `coating`, `other`.

With a manufacturer and a datasheet number:

```python
graphite = save_material_spec(create_material_spec(
    name="Graphite", material_class="active_material", electrode_polarity="negative",
    formula="C", manufacturer="Targray",
    property={"specific_capacity": {"value": 355, "unit": "mAh/g"}}),
    source_root="my-library", mode="upsert")
```

Quantities are always `{"value": ..., "unit": ...}` maps; a measured value can
also carry the conditions it was measured under — see
[Materials](../material-spec.md) for the property and composition reference.

## Find them again

Query your own library by passing its directory explicitly — with no argument,
`query_material_specs()` reads the example records packaged with BattINFO, not
yours:

```python
from battinfo.api import query_material_specs

mine = query_material_specs(material_class="active_material",
                            directory="my-library/material-spec")
print(sorted(m["name"] for m in mine))   # ['Graphite', 'NMC811']
```

## Log a physical lot

The spec is the datasheet; a `material` record is the jar on the shelf:

```python
from battinfo.api import create_material, save_material

lot = create_material(material_spec_id=NMC811_IRI, lot_id="CANRUD-NMC-2026-07")
save_material(lot, source_root="my-library", mode="upsert")
```

## What just happened

Each save wrote one plain-JSON record into your library and minted it a
permanent `https://w3id.org/battinfo/spec/` IRI. That IRI is how everything
else refers to the material: electrode recipes reference it
(see [Build a cell from components](build-a-cell-from-components.md)), and the
saved record validates against the material-spec schema before it lands.
Re-saving with `mode="upsert"` updates in place — same IRI, never a duplicate.
