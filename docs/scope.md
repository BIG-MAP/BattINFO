# BattINFO Scope & Capabilities

This document maps the BattINFO surface by maturity, so you know what you can
rely on today, what is available but still evolving, and what is in development.

Tested runtime support:

- Python 3.11
- Python 3.12

## Supported

These capabilities are covered by tests in CI, documented as supported, and are
the primary target for feedback:

- cell-descriptor validation for the stable integration subset
- cell-descriptor to JSON-LD mapping
- canonical record workflows for `cell-spec`, `cell-instance`, `test`, and `dataset`
- CLI/API query, save, publish, and index flows for canonical records
- JSON-LD-first publication with `publish(...)` and `load_publication(...)`
- validation policies `default`, `strict`, `publisher`, and `ingest`
- resolver artifact generation for canonical records

Representative cases exercised end-to-end:

- commercial battery cell records with simple specification-sheet metadata
- detailed battery cell descriptors for coin, cylindrical, single-layer pouch, multilayer pouch, and prismatic formats
- explicit canonical `test` records for common battery test workflows
- explicit canonical `dataset` records linked to a tested cell and optionally to a test
- repository notebooks that walk through the supported cases

## Preview

Available and expected to work, but interfaces may still be refined:

- reusable cell-spec library workflows beyond the descriptor fixtures
- curated datasheet validation examples included in the repository

Feedback is welcome; regressions here do not block a release unless they break a
supported capability.

## In development

Present but with no stability promise — documented as draft, experimental, or
internal:

- datasheet authoring as a public, frozen contract
- ingestion pipelines and other external-source normalization workflows
- semantic mapping candidate generation and review workflows
- reference validation strategies for larger external corpora beyond repository-scale source trees

## Verification

A release is considered ready when:

- all supported workflows install and run from a clean environment
- supported validation behavior is documented and machine-readable
- CI proves the supported Python versions for the supported surface
- top-level docs do not over-promise preview or in-development features

Bootstrap and run the verification gate:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python -m pip install -e .[dev]
.\.venv\Scripts\python .tools/quality/run_verification.py
```
