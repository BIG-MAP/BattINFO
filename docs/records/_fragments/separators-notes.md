**Generated surface.** `create_separator_spec`, `save_separator_spec`, `query_separator_specs`, `template_separator_spec` and the bare-name instance equivalents are thin wrappers over the shared component machinery (`create_component_spec("separator", ...)` underneath) — one registry entry per family, no divergent code paths.

**Coatings are a holder.** A ceramic-coated separator states its coating under `coating` (the same holder shape an electrode coating uses); `CeramicCoating` is a published class and types the node.
