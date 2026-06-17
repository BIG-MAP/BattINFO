# BattINFO Documentation

BattINFO is the implementation layer for the EMMO domain-battery ontology — providing JSON schemas, a Python library, a CLI, and canonical mapping tables for authoring, validating, and publishing battery metadata as Linked Data.

---

## Getting started

| | |
|---|---|
| **[Quickstart](../QUICKSTART.md)** | Create and publish your first cell-spec record in 5 minutes |
| **[01 — Concepts](guides/01-concepts.ipynb)** | Data model, record types, IRIs, and the semantic layer |
| **[02 — First cell spec](guides/02-first-cell-type.ipynb)** | Materials → components → cell spec → publish |
| **[03 — Linked records](guides/03-linked-records.ipynb)** | Cell instance → test → dataset → registry submission |
| **[04 — Semantic layer](guides/04-semantic-layer.ipynb)** | JSON-LD anatomy, EMMO type stacking, RDF validation, SPARQL |
| **[05 — Descriptors](guides/05-descriptors.ipynb)** | Research-grade descriptors: electrode composition, electrolyte, separator |

Open notebooks from the repo root with the `.venv` kernel selected.

---

## Reference

| | |
|---|---|
| **[Python API](python-api.md)** | Full Python surface: Workspace, authoring helpers, query/save/publish functions |
| **[CLI spec](cli-spec.md)** | All CLI commands, options, and output formats |
| **[Validation contract](validation-contract.md)** | Validation policies, machine-readable issue output |
| **[Identifier policy](../IDENTIFIER_POLICY.md)** | IRI minting, governance, and stability guarantees |

---

## Domain and schemas

| | |
|---|---|
| **[Cell descriptor standard](cell-descriptor-standard.md)** | Normative cell descriptor specification |
| **[Ontology / profile architecture](ontology-profile-architecture.md)** | How BattINFO, EMMO, and schema.org compose |
| **[Schemas](../assets/schemas/)** | JSON Schema (draft 2020-12) files for all record types |
| **[Property mappings](../assets/mappings/domain-battery/)** | Curated property → EMMO IRI and unit → EMMO/QUDT IRI tables |

---

## Workflows

| | |
|---|---|
| **[Instance / test / dataset workflow](instance-test-dataset-workflow.md)** | Detailed workflow reference for linked records |
| **[Editorial cell-spec workflow](editorial-cell-type-workflow.md)** | Submission and curation workflow for the cell-spec library |
| **[Ingest manifest contract](ingest-manifest-contract.md)** | Batch intake from a folder of raw data files |
| **[Dataset registry intake spec](dataset-registry-intake-spec.md)** | Submission package format for registry intake |
| **[Resolver deployment](resolver.md)** | Building and deploying static resolver artifacts |

---

## Scope and status

| | |
|---|---|
| **[Alpha scope](alpha-scope.md)** | What is in scope for alpha testing, what is in development |
| **[CHANGELOG](../CHANGELOG.md)** | Release history and notable changes |

---

## Internal / maintainer

| | |
|---|---|
| **[Agent guide](../AGENTS.md)** | Machine-readable manifest for AI agents working on this repo |
| **[Validation roadmap](validation-roadmap.md)** | Planned validation enhancements |
| **[Converter compatibility](converter-compatibility.md)** | Compatibility notes for external format converters |
