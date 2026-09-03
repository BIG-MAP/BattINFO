BattINFO models every entity as a **spec + instance** pair. After materials
([materials](materials.md#records)) and electrodes
([electrodes-model.md](electrodes.md)), four **component** families let the rest of a
cell be described from reusable, IRI-addressable parts. Each family is a thin registry entry
that reuses an existing embedded holder shape; component-specs reference `material-spec`
records by IRI.

| Family | Spec record | Instance record | References materials via |
| --- | --- | --- | --- |
| electrolyte | `electrolyte-spec` | `electrolyte` | salt + solvent + additive `material_spec_id` |
| separator | `separator-spec` | `separator` | `material_spec_id` |
| current-collector | `current-collector-spec` | `current-collector` | `material_spec_id` |
| housing | `housing-spec` | `housing` | (materials as strings) |

Electrodes used to be a fifth generic family. They are now first-class — a curated `kind`,
deterministic identity that includes the processing route, design values, and their own
emitter — so they have their own page: [Electrodes](electrodes.md).

## Generic API + per-family wrappers

A generic factory in `api.py` is parameterized by family; thin per-family wrappers are
generated from the entity registry, so the surface matches the cell/material API:

```python
from battinfo.api import create_separator_spec, create_component_spec

separator = create_separator_spec(
    name="Celgard 2400", manufacturer="Celgard",
    body={"material": "polypropylene", "structure": "monolayer",
          "property": {"thickness": {"value": 25, "unit": "um"}}})

# generic form is also available
create_component_spec("electrolyte", name="…", body={...})
```

The step-by-step bench version of this — materials first, IRIs harvested from
each save — is [How-to: build a cell from components](../howto/build-a-cell-from-components.md).

Per family you get `create_<family>_spec`, `save_<family>_spec`, `query_<family>_specs`,
`template_<family>_spec` and the bare-name instance equivalents (`create_<family>`,
`query_<family>s`). Generic functions `create/save/query/template_component_spec(family, …)`
(and `_instance`) underlie them. Electrodes expose the same function names, but as
hand-written first-class builders rather than generated wrappers.

### Naming convention

Family identifiers use **underscores** (`current_collector`); the IRI namespace uses
**hyphens** (`https://w3id.org/battinfo/spec/…`). The generic API derives
the namespace via `family.replace("_", "-")`.

## Electrolyte assembles material constituents

`electrolyte-spec` carries `salt` + `solvent_mixture.component[]` + `additive[]`, each able
to reference a `material-spec` by IRI — so the **organic 1M LiPF₆ EC:EMC 3:7** and
**aqueous 7M KOH** example formulations are assembled from the LiPF6/EC/EMC/KOH material-specs
and emit `OrganicElectrolyte` / `AqueousElectrolyte` JSON-LD with `hasSolute`/`hasSolvent`.

## Examples

`examples/<family>-spec/*` + `examples/<family>/*` (single source of truth, mirrored into the
wheel). Coverage: Celgard PP + ceramic-coated PE separators; Al/Cu current collectors;
organic + aqueous electrolytes; CR2032 coin + LFP 100 Ah prismatic housings — grounded in the DIGIBAT Discovery-Benchmark and the Cell_Design_Tool.
Cell-specs reference these component-specs by IRI today via the five `*_spec_id`
fields — see [Cells](../cell-fleet.md) for the reference seam and the example fleet
that uses it.
