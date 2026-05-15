# Assets

Canonical schema and mapping assets live here.

Generated review batches, ingest bridge outputs, and scratch reports should go under
ignored local paths such as `.battinfo/`, not back into `assets/`.

Subdirectories:
- `schemas/` Normative JSON Schemas used by CLI/API validation
- `mappings/` Canonical mapping tables plus review artifacts used by maintainer tooling

Author by hand:
- `schemas/`
- the canonical mapping tables under `mappings/domain-battery/`

Do not treat as hand-authored source of truth:
- generated review JSON-LD examples such as `*.domain-battery.review.jsonld`
- generated review reports under `mappings/domain-battery/`

Examples and notebooks now live under the top-level `examples/` tree. Reusable
shared record corpora should live outside this repo, for example in a dedicated
`battinfo-records` repository, not under `assets/`.

Identifier-constrained resource schemas include:
- `schemas/cell-type.schema.json`
- `schemas/cell-instance.schema.json`
- `schemas/dataset.schema.json`
- `schemas/test.schema.json`

Workflow/support schemas also include:
- `schemas/ingest-manifest.schema.json`
