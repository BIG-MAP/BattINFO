**Composing a cell from parts.** The seven reference fields resolve as: `positive_electrode_spec_id` / `negative_electrode_spec_id` and `working_electrode_spec_id` / `counter_electrode_spec_id` → `electrode-spec` (which pair applies follows from `cell_configuration`); `electrolyte_spec_id` → `electrolyte-spec`; `separator_spec_id` → `separator-spec`; `housing_spec_id` → `housing-spec`. A cell may reference, inline, or both — inline holders stay optional, so existing records are unaffected. The JSON-LD emits reference nodes (`hasPositiveElectrode: {"@id": …}`), merging the `@id` onto an inline node when both are present.

**References are checked at save.** A `*_spec_id` that points at nothing fails the save with the missing IRI named; `resolve_references=False` opts out for staged workflows, and `save_batch` allows references within the batch and validates the completed set. `extract_component_specs(cell_spec_record)` goes the other way, lifting inline holders into standalone specs so any inline cell can be decomposed and de-duplicated.

**The engineering layer.** Beyond composition and rated performance, a spec can carry the as-designed build. Deliberately excluded: design-tool scratch math (recomputed, not stored) and state-dependent behaviour (belongs to tests and datasets). Every part follows holder + property: identity fields plus `{value, unit}` quantities, unknown keys preserved and warned rather than dropped. The housing (case, cap, terminals, seals, parts) is authored inline or as a standalone [housing spec](components.md); tabs and coatings belong to [the electrode](electrodes.md); the wound/stacked geometry is the spec's own `construction` block.

**The full graph, end to end:**

```text
cell-spec  →  cell-instance  →  test  →  dataset
     ↓ references
electrode-spec / electrolyte-spec / separator-spec / housing-spec  →  material-specs
```
