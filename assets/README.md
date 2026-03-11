# Assets

Canonical schemas, mappings, and examples live here. These are the tracked source-of-truth assets.

Generated review batches, ingest bridge outputs, and scratch reports should go under
ignored local paths such as `.battinfo/`, not back into `assets/`.

Subdirectories:
- `compat.yaml` Compatibility metadata for domain-battery and Battery Pass
- `examples/` Human-readable canonical examples and profile fixtures
- `schemas/` Normative JSON Schemas used by CLI/API validation
- `library/` Canonical reusable source records
- `library-rdf/` Generated RDF/JSON-LD library artifacts
- `datasheets/` Curated datasheet JSON examples
- `mappings/` Mapping rules and candidate mapping artifacts

Identifier-constrained resource schemas include:
- `schemas/cell-type.schema.json`
- `schemas/cell-instance.schema.json`
- `schemas/dataset.schema.json`
- `schemas/test.schema.json`
