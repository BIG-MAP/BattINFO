# Cell Fleet & the cell→component reference seam

With materials and the five component families in place, a **cell-spec** can now be
described from reusable parts: it references standalone component-specs by IRI, which in
turn reference material-specs — completing the three-level graph
**cell → component → material**.

## Reference seam

A cell-spec gains five optional top-level reference fields (siblings of the inline
`positive_electrode`/`electrolyte`/… holders):

| Field | Resolves to |
| --- | --- |
| `positive_electrode_spec_id` / `negative_electrode_spec_id` | `electrode-spec` |
| `electrolyte_spec_id` | `electrolyte-spec` |
| `separator_spec_id` | `separator-spec` |
| `housing_spec_id` | `housing-spec` |

A cell may **reference**, **inline**, or both — inline holders stay optional, so existing
records are unaffected. References are existence-checked against the source root, and the
JSON-LD emits reference nodes (`hasPositiveElectrode: {"@id": <electrode-spec IRI>}`, etc.);
when a basis/inline node is also present, the `@id` is merged onto it.

```python
import battinfo as bi

rec = bi.save_cell_spec(bi.CellSpec(
    model_name="COIN-NMC811-D", manufacturer="EMPA", format="coin", chemistry="Li-ion",
    positive_electrode_spec_id=NMC811_CATHODE_IRI,
    negative_electrode_spec_id=GRAPHITE_ANODE_IRI,
    electrolyte_spec_id=ORGANIC_ELECTROLYTE_IRI,
    separator_spec_id=CELGARD_IRI,
    housing_spec_id=COIN_HOUSING_IRI,
    properties={"nominal_capacity": {"value": 0.0038, "unit": "Ah"}, "nominal_voltage": {"value": 3.8, "unit": "V"}},
), source_root="examples")
```

### Bridge (inline → standalone)

`extract_component_specs(cell_spec_record)` lifts a cell's inline holders into standalone
component-specs (the counterpart of `extract_material_specs`), so any inline cell can be
decomposed and de-duplicated.

## The fleet (reference-based)

`examples/cell-spec/` adds 8 cells that reference shared component-specs by IRI:

| Cell | format | chemistry | grounding |
| --- | --- | --- | --- |
| COIN-NMC811-D | coin | Li-ion (NMC811) | Discovery |
| COIN-LFP-D | coin | Li-ion (LFP) | Discovery |
| COIN-LCO-D | coin | Li-ion (LCO) | Discovery |
| COIN-LMFP-D | coin | Li-ion (LMFP) | Discovery |
| COIN-NMC622-D | coin | Li-ion (NMC622) | Discovery |
| PRISM-LFP-100AH | prismatic | Li-ion (LFP) | Cell_Design (engineering) |
| COIN-ZNMNO2-ALK | coin | Zn-MnO2 alkaline | synthetic (7M KOH, non-Li-ion) |
| COIN-LNMO-D | coin | Li-ion (LNMO) | synthetic (high-voltage) |

The component fleet was extended with one cathode electrode-spec per chemistry
(LFP/LCO/LMFP/NMC622/LNMO/MnO2 cathodes, Zn anode) and an MnO2 material-spec; the graphite
anode, organic + aqueous electrolytes, Celgard separator, and coin/prismatic housings are
shared across cells.

## Full-graph showcase

The NMC811 coin demonstrates the complete graph end-to-end:

```text
cell-spec COIN-NMC811-D  →  cell-instance (P025-CEL-001)  →  test (cycling)  →  dataset
        ↓ references
   electrode-spec / electrolyte-spec / separator-spec / housing-spec  →  material-specs
```

`examples/cell-instance/`, `examples/test/`, and `examples/dataset/` carry the linked
instance/test/dataset for it; the broader instance/test/dataset fleet is Phase 4.
