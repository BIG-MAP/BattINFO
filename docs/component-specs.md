# Components

BattINFO models every entity as a **spec + instance** pair. After materials
([material-spec.md](material-spec.md)), the five **component** families let a cell be
described from reusable, IRI-addressable parts. Each family is a thin registry entry that
reuses an existing embedded holder shape; component-specs reference `material-spec` records
by IRI.

| Family | Spec record | Instance record | References materials via |
| --- | --- | --- | --- |
| electrode | `electrode-spec` | `electrode` | coating active/binder/additive `material_spec_id` |
| electrolyte | `electrolyte-spec` | `electrolyte` | salt + solvent + additive `material_spec_id` |
| separator | `separator-spec` | `separator` | `material_spec_id` |
| current-collector | `current-collector-spec` | `current-collector` | `material_spec_id` |
| housing | `housing-spec` | `housing` | (materials as strings) |

## Generic API + per-family wrappers

A generic factory in `api.py` is parameterized by family; thin per-family wrappers are
generated from the entity registry, so the surface matches the cell/material API:

```python
import battinfo as bi

# electrode-spec whose coating references standalone material-specs by IRI
electrode = bi.create_electrode_spec(
    name="NMC811 cathode", polarity="positive", manufacturer="Canrud",
    body={
        "coating": {"component": {
            "active_material": [{"name": "NMC811", "material_spec_id": NMC811_IRI,
                                 "property": {"mass_fraction": {"value": 0.96, "unit": "1"}}}],
            "binder": [{"name": "PVDF", "material_spec_id": PVDF_IRI}],
            "additive": [{"name": "Carbon black", "material_spec_id": CB_IRI}]},
            "property": {"loading": {"value": 21, "unit": "mg/cm2"}}},
        "current_collector": {"name": "Aluminium foil", "property": {"thickness": {"value": 15, "unit": "um"}}},
    })
bi.save_electrode_spec(electrode, source_root="examples")

# generic form is also available
bi.create_component_spec("electrolyte", name="…", body={...})
```

Per family you get `create_<family>_spec`, `save_<family>_spec`, `query_<family>_specs`,
`template_<family>_spec` and the bare-name instance equivalents (`create_<family>`,
`query_<family>s`). Generic functions `create/save/query/template_component_spec(family, …)`
(and `_instance`) underlie them.

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
wheel). Coverage: NMC811 cathode + graphite anode electrodes; Celgard PP + ceramic-coated PE
separators; Al/Cu current collectors; organic + aqueous electrolytes; CR2032 coin + LFP 100 Ah
prismatic housings — grounded in the DIGIBAT Discovery-Benchmark and the Cell_Design_Tool.
Cell-specs will reference these component-specs by IRI in Phase 3.
