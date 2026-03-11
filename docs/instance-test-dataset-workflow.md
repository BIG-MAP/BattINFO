# Instance, Test, Dataset Workflow

## Purpose

This document describes the current BattINFO workflow for going from a battery descriptor to explicit physical instances, tests, and linked datasets.

## Recommended Flow

1. Create one battery descriptor for the commercial cell type.
2. Add lightweight `instances` in the descriptor if you want the instance names recorded near the specification.
3. Register canonical `cell-instance` records for the physical cells you actually procure and test.
4. Register canonical `test` records for concrete test activities performed on those physical cells.
5. Register canonical `dataset` records for the generated data products, and link them to the cell instance and test.

## Current Canonical Contracts

- battery descriptor:
  - `assets/schemas/battery-descriptor.schema.json`
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

## Current Example Chain

- descriptor:
  - `assets/examples/battery-descriptors/a123-anr26650m1-b.example.json`
- cell instance:
  - `assets/examples/cell-instances/cell-3m6k-9t2p-7x4h-9nq8.json`
- test:
  - `assets/examples/tests/test-5p7v-2n8k-4m3t-6q9r.json`
- dataset:
  - `assets/examples/datasets/dataset-1f8r-6v2k-9p4m-3t7x.json`

## CLI Workflow

Example commands:

```powershell
battinfo validate assets/examples/battery-descriptors/a123-anr26650m1-b.example.json

battinfo register cell-instance --type-id https://w3id.org/battinfo/cell-type/7d9k-2m4p-8t3x-6nq5 --uid 3m6k9t2p7x4h9nq8 --source-type lab

battinfo register test --cell-id https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8 --name "Baseline cycling" --kind cycle_life --uid 5p7v2n8k4m3t6q9r

battinfo register dataset --title "Baseline cycling dataset" --related-cell-id https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8 --related-test-id https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r --uid 8c1h8pk68034vav6
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
