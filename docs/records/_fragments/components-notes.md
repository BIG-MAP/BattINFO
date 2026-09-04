**The family table.** Each family is a thin registry entry reusing an existing embedded holder shape; specs reference `material-spec` records by IRI.

| Family | Spec record | Instance record | References materials via |
| --- | --- | --- | --- |
| separator | `separator-spec` | `separator` | `material_spec_id` |
| current-collector | `current-collector-spec` | `current-collector` | `material_spec_id` |
| housing | `housing-spec` | `housing` | (materials as strings) |

**The generated surface.** Per family you get `create_<family>_spec`, `save_<family>_spec`, `query_<family>_specs`, `template_<family>_spec` and the bare-name instance equivalents; generic `create/save/query/template_component_spec(family, …)` functions underlie them. Electrodes expose the same names but as hand-written first-class builders; electrolytes share the machinery with [their own page](electrolytes.md).

**History, in one line:** electrodes used to be a generic family here and are now first-class (curated kind, route in the identity, their own emitter) — see [electrodes](electrodes.md).

**Naming convention.** Family identifiers use underscores (`current_collector`); the IRI namespace uses hyphens; the generic API derives one from the other.
