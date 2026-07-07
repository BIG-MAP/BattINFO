# Cell specs

## Purpose

BattINFO should support a reusable library of commercial cell specs curated once
from datasheets and then referenced by physical cell instances, tests, and
datasets.

The integration model is:

```text
datasheet PDF -> curated cell record JSON -> generated RDF/JSON-LD
```

The descriptor JSON is the canonical authoring and review format. The RDF
publication artifact is generated from that canonical JSON and is not maintained
separately.

## Source Of Truth

Use this order:

1. `domain-battery` and `battinfo.ttl` define semantics and profile policy.
2. The curated shared corpus should live outside this repo, for example in a
   dedicated `battinfo-records` repository.
3. Local working copies and rebuildable artifacts can live under `.battinfo/`
   when you want to validate or regenerate the library locally.

`battinfo.ttl` should stay focused on ontology/profile terms. It
should not become a hand-maintained dump of every commercial cell spec.

## Repository Layout

- external curated records repo, for example `battinfo-records/`
  - maintained shared cell-spec corpus
- `.battinfo/library/cell-spec/`
  - local working copy or sync target used during rebuilds
- `src/battinfo/data/library/cell-spec/`
  - packaged copies when the library is shipped with the Python package
- `.battinfo/library-rdf/cell-spec/`
  - output location for per-record generated RDF/JSON-LD artifacts
- `.battinfo/library-rdf/cell-spec.index.json`
  - generated manifest over the library
- `.battinfo/library/cell-spec.jsonld`
  - aggregated generated RDF publication artifact

## Reuse Model

The reusable spec IRI is the descriptor `specification.id`.

Downstream linkage then works as:

```text
descriptor specification.id -> cell-instance.cell_spec_id
cell-instance.id -> test.cell_id
test.id / cell-instance.id -> dataset.about[]
```

That means a commercial spec is curated once, and every concrete physical cell
instance reuses that same spec IRI.

## Why JSON First

Keep the reusable spec library as BattINFO battery descriptors because that is:

- easier to curate and diff than raw RDF
- compatible with JSON Schema validation
- aligned with the current BattINFO/BDF contract direction
- deterministic to project into JSON-LD

Generated RDF is still first-class, but it is derived.

## Build Workflow

Use:

```powershell
python .tools/build/build_cell_spec_library_rdf.py --clean-output
```

This does three things:

1. validates every descriptor in `.battinfo/library/cell-spec/`
2. generates per-record domain-battery JSON-LD into
   `.battinfo/library-rdf/cell-spec/`
3. generates:
   - `.battinfo/library-rdf/cell-spec.index.json`
   - `.battinfo/library/cell-spec.jsonld`

## Curation Workflow

Recommended workflow for a new commercial cell spec:

1. identify the datasheet PDF
2. create a BattINFO battery descriptor draft
3. review and enrich the specification
4. place the curated descriptor in the external curated records repo, or sync it
   into `.battinfo/library/cell-spec/` for local rebuilds
5. rebuild the RDF library artifacts
6. reference the spec IRI from cell-instance records

## Current Boundary

Today, the reusable spec library is integrated as descriptor JSON plus
generated JSON-LD. That is enough to treat the spec catalog as RDF-backed data
without turning `battinfo.ttl` into a data dump.

If a Turtle export becomes necessary later, it should be added as another
generated artifact from the same canonical descriptor library rather than as a
hand-maintained ontology file.



