# BattINFO Documentation

BattINFO is the implementation layer for the EMMO domain-battery ontology — providing JSON schemas, a Python library, a CLI, and canonical mapping tables for authoring, validating, and publishing battery metadata as Linked Data.

---

## Getting started

| | |
|---|---|
| **[Quickstart](../QUICKSTART.md)** | Create and publish your first cell-spec record in 5 minutes |
| **[1 — Concepts](guides/01-concepts.ipynb)** | The record model, IRIs, and the semantic layer |
| **[2 — Describing a cell](guides/02-first-cell-type.ipynb)** | Author and publish a cell spec, with a taste of material-level depth |
| **[3 — Linked records](guides/03-linked-records.ipynb)** | Cells, test specs, tests, and datasets with the workspace |
| **[4 — Semantic layer](guides/04-semantic-layer.ipynb)** | JSON-LD anatomy, EMMO type stacking, RDF and SPARQL |
| **[5 — Cell descriptors](guides/05-descriptors.ipynb)** | Research-grade composition: materials, BOMs, electrodes, electrolyte |
| **[6 — Publish your first dataset](guides/06-publish-your-data.ipynb)** | End to end: raw cycler CSV → validated records → DOI + registry |

Each notebook runs from its own folder and writes only to a throwaway `_scratch/` directory next to it.

---

## Reference

| | |
|---|---|
| **[Workspace authoring](workspace-authoring.md)** | The blessed authoring surface: `battinfo.workspace(".")` end-to-end, and which surface to use when |
| **[Python API](python-api.md)** | Full Python surface: Workspace, authoring helpers, query/save/publish functions |
| **[CLI spec](cli-spec.md)** | All CLI commands, options, and output formats |
| **[Validation contract](validation-contract.md)** | Validation policies, machine-readable issue output |
| **[Identifier policy](../IDENTIFIER_POLICY.md)** | IRI minting, governance, and stability guarantees |

---

## Domain and schemas

| | |
|---|---|
| **[How BattINFO is built](how-battinfo-is-built.md)** | The orientation roadmap: layers, modules, and the two ideas everything follows |
| **[Data federation](data-federation.md)** | Why battery data needs federation, how BattINFO is the backbone, and Battery Genome in practice |
| **[Cell descriptor standard](internal/cell-descriptor-standard.md)** | Normative cell descriptor specification |
| **[Ontology / profile architecture](ontology-profile-architecture.md)** | How BattINFO, EMMO, and schema.org compose |
| **[Schemas](../assets/schemas/)** | JSON Schema (draft 2020-12) files for all record types |
| **[Property mappings](../assets/mappings/domain-battery/)** | Curated property → EMMO IRI and unit → EMMO/QUDT IRI tables |

---

## Workflows

| | |
|---|---|
| **[How-to guides](howto/bulk-ingest.md)** | Task recipes: bulk ingest, fixing validation errors, resuming submissions, funding/ORCID |
| **[Instance / test / dataset workflow](instance-test-dataset-workflow.md)** | Detailed workflow reference for linked records |
| **[Editorial cell-spec workflow](internal/editorial-cell-type-workflow.md)** | Submission and curation workflow for the cell-spec library |
| **[Ingest manifest contract](ingest-manifest-contract.md)** | Batch intake from a folder of raw data files |
| **[Dataset registry intake spec](internal/dataset-registry-intake-spec.md)** | Submission package format for registry intake |
| **[Resolver deployment](internal/resolver.md)** | Building and deploying static resolver artifacts |

---

## Scope and status

| | |
|---|---|
| **[Scope](scope.md)** | What is supported, what is in development |
| **[CHANGELOG](../CHANGELOG.md)** | Release history and notable changes |

---

## Internal / maintainer

| | |
|---|---|
| **[Agent guide](../AGENTS.md)** | Machine-readable manifest for AI agents working on this repo |
| **[Validation roadmap](internal/validation-roadmap.md)** | Planned validation enhancements |
| **[Converter compatibility](internal/converter-compatibility.md)** | Compatibility notes for external format converters |
