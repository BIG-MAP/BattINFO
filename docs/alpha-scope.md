# BattINFO Alpha Scope

This document defines the BattINFO feature boundary for alpha testing.

Status:
- pre-release
- alpha-ready scope defined
- release tagging and external tester rollout happen separately

Tested runtime support:
- Python 3.10
- Python 3.11

## Core Scope

The following features are in scope for alpha testing now:

- battery-descriptor validation for the stable integration subset
- battery-descriptor to JSON-LD mapping
- canonical record workflows for `cell-type`, `cell-instance`, `test`, and `dataset`
- CLI/API query, register, publish, and index flows for canonical records
- JSON-LD-first publication with `publish(...)` and `load_publication(...)`
- validation policies `default`, `strict`, `publisher`, and `ingest`
- resolver artifact generation for canonical records

Core scope expectations:
- tested in CI
- documented as supported
- treated as the primary feedback target for alpha testers

## Preview Scope

The following features are available but not part of the core alpha contract:

- reusable cell-type library registration/query/build-RDF flows
- repository notebooks used for onboarding and workflow examples
- curated datasheet validation examples already included in the repository

Preview scope expectations:
- expected to work
- still subject to interface refinement during alpha
- feedback is welcome, but regressions here do not block the alpha gate unless they break core scope

## In-Development Scope

The following features are explicitly out of alpha scope:

- datasheet authoring as a public, frozen contract
- ingestion pipelines for CellInfo/PDF or other external source normalization
- semantic mapping candidate generation and review workflows
- reference validation strategies intended for larger external corpora beyond repository-scale source trees

In-development expectations:
- no stability promise
- documentation should label them clearly as draft, experimental, or internal
- issues here should not be framed as alpha blockers unless they impact core scope

## Alpha Gate

BattINFO is considered alpha-test ready when:

- all core-scope workflows install and run from a clean environment
- core-scope validation behavior is documented and machine-readable
- CI proves the supported Python versions for the core surface
- top-level docs do not over-promise preview or in-development features
