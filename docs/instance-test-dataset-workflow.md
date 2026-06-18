# Instance, Test, Dataset Workflow

## Purpose

This document describes the current BattINFO workflow for going from a cell descriptor to explicit physical instances, tests, and linked datasets.

## Recommended Flow

1. Create one cell descriptor for the commercial cell type.
2. Add lightweight `instances` in the descriptor if you want the instance names recorded near the specification.
3. Register canonical `cell-instance` records for the physical cells you actually procure and test.
4. Register canonical `test` records for concrete test activities performed on those physical cells.
5. Register canonical `dataset` records for the generated data products, and link them to the cell instance and test.

Reference handling:
- single-record save is best-effort and allows unresolved linked records to be written
- full cross-record integrity is enforced when validating the finished set, for example with `save batch --resolve-references` or `build_index(..., validate=True)`

## Current Canonical Contracts

- cell descriptor:
  - `assets/schemas/cell-descriptor.schema.json`
- cell instance:
  - `assets/schemas/cell-instance.schema.json`
- test:
  - `assets/schemas/test.schema.json`
- dataset:
  - `assets/schemas/dataset.schema.json`

## Linkage Model

The intended linkage chain is:

```text
descriptor specification.id -> cell-instance.type_id
cell-instance.id -> test.cell_id
test.id -> dataset.about[]
cell-instance.id -> dataset.about[]
test.dataset_ids[] -> dataset.id
```

This means:
- the descriptor defines the cell type
- the cell-instance identifies the actual physical item under test
- the test identifies the concrete activity or campaign performed on that item
- the dataset identifies the produced data asset

Dataset linkage policy for alpha:
- a dataset must reference at least one BattINFO cell
- a dataset may reference a BattINFO test when a concrete test record exists

## Project Provenance (Funding)

Beyond the per-record linkage chain, a whole authoring workspace can be tagged
with the **funding project (grant)** that produced the work, so every record —
cell spec, cell instance, test, test protocol, and dataset — can be traced back
to its project (for example, everything done under EU grant 101103997 /
*DigiBatt*).

Set it once per workspace:

```python
import battinfo
ws = battinfo.workspace(".")

ws.project("101103997")          # just the grant identifier (the common case)
# Title, funder, and programme are resolved from OpenAIRE and cached in
# .battinfo/workspace.json; for EU grants a resolvable CORDIS IRI is derived.
# Pass name=/funder=/... to fill them in by hand when you are offline or the
# grant is not in OpenAIRE; manual values win and survive ws.project(refresh=True).

ws.project()                     # show the current project
ws.project(clear=True)           # remove the tag
```

How it propagates:

- **On `ws.save()`** every record gets a top-level `funding` block (schema
  `Funding` → schema.org `Grant`); re-saving back-fills records authored before
  the project was set. The block is workspace-managed — when no project is set,
  records are left untouched.
- **In JSON-LD** (`ws.export("json-ld")`, RO-Crate, the Zenodo graph) it renders
  as `schema:funding` → a `schema:Grant` node with `schema:funder`. The funding
  *programme* is kept only in the native record (schema.org has no standard term
  for it).
- **On `ws.submit()`** the grant is surfaced at the submission `provenance.project`
  so the registry can filter by project.
- **On `ws.zenodo()`** the project's CORDIS page is added to the deposit's
  related identifiers (`relation: isPartOf`).

The `funding` block is an optional top-level property of every record envelope
schema (`assets/schemas/{cell-spec,cell-instance,test,test-protocol,dataset}.schema.json`).

## Current Example Chain

- descriptor:
  - `examples/cell-descriptors/a123-anr26650m1-b.example.json`
- cell instance:
  - `examples/cell-instance/cell-3m6k-9t2p-7x4h-9nq8.json`
- test:
  - `examples/test/test-5p7v-2n8k-4m3t-6q9r.json`
- dataset:
  - `examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json`

## CLI Workflow

Example commands:

```powershell
battinfo validate examples/cell-descriptors/a123-anr26650m1-b.example.json

battinfo save cell-instance --type-id https://w3id.org/battinfo/cell/7d9k-2m4p-8t3x-6nq5 --uid 3m6k9t2p7x4h9nq8 --source-type lab

battinfo save test --cell-id https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8 --name "Baseline cycling" --kind cycle_life --uid 5p7v2n8k4m3t6q9r

battinfo save dataset --title "Baseline cycling dataset" --related-cell-id https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8 --related-test-id https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r --uid 8c1h8pk68034vav6
```

Query commands over the linked chain:

```powershell
battinfo query cell-instances --type-id https://w3id.org/battinfo/cell/7d9k-2m4p-8t3x-6nq5 --has-dataset --format json

battinfo query tests --cell-id https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8 --format json

battinfo query tests --dataset-id https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x --format json

battinfo query dataset --related-cell-id https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8 --format json

battinfo query dataset --related-test-id https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r --format json
```

## Current Boundaries

What is now first-class:
- specification contract
- instance contract
- test contract
- dataset contract
- explicit links between instance, test, and dataset

What is still intentionally light:
- the descriptor `instances` block remains a lightweight reference layer, not the full canonical `cell-instance` contract
- test result content is still represented at the dataset layer rather than as a deeply modeled measurement/event ontology







