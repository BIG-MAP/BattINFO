# Cell-Type Library

## Purpose

BattINFO should support a reusable library of commercial cell types curated once
from datasheets and then referenced by physical cell instances, tests, and
datasets.

The integration model is:

```text
datasheet PDF -> curated battery descriptor JSON -> generated RDF/JSON-LD
```

The descriptor JSON is the canonical authoring and review format. The RDF
publication artifact is generated from that canonical JSON and is not maintained
separately.

## Source Of Truth

Use this order:

1. `domain-battery` and `battinfo.ttl` define semantics and profile policy.
2. `assets/library/cell-types/*.json` stores the canonical reusable type
   records as BattINFO battery descriptors.
3. `assets/library-rdf/cell-types/*.jsonld` and
   `ontology/library/cell-types.jsonld` are generated publication artifacts.

`ontology/battinfo.ttl` should stay focused on ontology/profile terms. It
should not become a hand-maintained dump of every commercial cell type.

## Repository Layout

- `assets/library/cell-types/`
  - canonical reusable type descriptors
- `src/battinfo/data/library/cell-types/`
  - packaged copies when the library is shipped with the Python package
- `assets/library-rdf/cell-types/`
  - per-record generated RDF/JSON-LD artifacts
- `assets/library-rdf/cell-types.index.json`
  - generated manifest over the library
- `ontology/library/cell-types.jsonld`
  - aggregated generated RDF publication artifact

## Reuse Model

The reusable type IRI is the descriptor `specification.id`.

Downstream linkage then works as:

```text
descriptor specification.id -> cell-instance.type_id
cell-instance.id -> test.cell_id
test.id / cell-instance.id -> dataset.about[]
```

That means a commercial type is curated once, and every concrete physical cell
instance reuses that same type IRI.

## Why JSON First

Keep the reusable type library as BattINFO battery descriptors because that is:

- easier to curate and diff than raw RDF
- compatible with JSON Schema validation
- aligned with the current BattINFO/BDF contract direction
- deterministic to project into JSON-LD

Generated RDF is still first-class, but it is derived.

## Build Workflow

Use:

```powershell
python .tools/build/build_cell_type_library_rdf.py --clean-output
```

This does three things:

1. validates every descriptor in `assets/library/cell-types/`
2. generates per-record domain-battery JSON-LD into
   `assets/library-rdf/cell-types/`
3. generates:
   - `assets/library-rdf/cell-types.index.json`
   - `ontology/library/cell-types.jsonld`

## Curation Workflow

Recommended workflow for a new commercial cell type:

1. identify the datasheet PDF
2. create a BattINFO battery descriptor draft
3. review and enrich the specification
4. place the curated descriptor in `assets/library/cell-types/`
5. rebuild the RDF library artifacts
6. reference the type IRI from cell-instance records

## Current Boundary

Today, the reusable type library is integrated as descriptor JSON plus
generated JSON-LD. That is enough to treat the type catalog as RDF-backed data
without turning `battinfo.ttl` into a data dump.

If a Turtle export becomes necessary later, it should be added as another
generated artifact from the same canonical descriptor library rather than as a
hand-maintained ontology file.

