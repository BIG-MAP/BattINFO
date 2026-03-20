# BattINFO Agent Guide

This repository is ready for coding agents, but the fastest path is to use the
human-first API and the alpha verification gate rather than inferring workflows
 from low-level schemas.

## Purpose

BattINFO is the implementation and interoperability layer for the
domain-battery ontology. The supported alpha surface is:

- simple commercial cell records
- detailed cell descriptions for coin, cylindrical, pouch, and prismatic cells
- canonical battery test records
- linked dataset records

## Fast Start

Use these commands first:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python -m pip install -e .[dev]
.\.venv\Scripts\python .tools/quality/run_alpha_verification.py
```

For machine-readable alpha verification output:

```powershell
.\.venv\Scripts\python .tools/quality/run_alpha_verification.py --report-json .battinfo/reports/alpha-verification.json
```

## Preferred Surfaces

For humans and agents writing new workflows:

- use `battinfo.Workspace` for linked canonical records
- use `battinfo.quantity(...)` and `battinfo.properties(...)` for quantities and property bags
- use `battinfo.bom(...)`, `battinfo.electrode(...)`, `battinfo.electrolyte_recipe(...)`, `battinfo.separator_spec(...)`, and `Workspace.describe_cell(...)` for detailed cell descriptions

Avoid starting from:

- raw nested dict payloads
- direct edits under `examples/` unless the task is fixture maintenance
- generated/package copies under `src/battinfo/data/` unless you are intentionally syncing source-of-truth assets

## Source Of Truth

- canonical schemas and mappings: `assets/`
- canonical examples and notebooks: `examples/`
- packaged copies used by the installed library: `src/battinfo/data/`
- public Python API: `src/battinfo/__init__.py`
- human-first workflow API: `src/battinfo/workspace.py`
- authoring helpers for detailed cell descriptions: `src/battinfo/authoring.py`
- typed bundle models: `src/battinfo/bundle.py`
- CLI and low-level registration/query API: `src/battinfo/cli.py`, `src/battinfo/api.py`
- acceptance tests: `tests/test_alpha_workflow.py`, `tests/test_alpha_descriptor_matrix.py`, `tests/test_alpha_scope_acceptance.py`

## Safe Write Locations

Write transient outputs under:

- `.battinfo/`
- temporary directories created by tests

Do not treat these as source of truth:

- `.venv/`
- `.pytest_cache/`
- `.jupyter-runtime-test/`
- `.battinfo/`

## Verification

Primary gate:

- `python .tools/quality/run_alpha_verification.py`

Useful focused checks:

- `python -m pytest -q tests/test_workspace.py`
- `python -m pytest -q tests/test_bundle.py`
- `python -m pytest -q tests/test_api.py tests/test_cli_query_create_publish.py`
- `python tests/installed_smoke.py`

## Notebook Intent

The notebooks under `examples/notebooks/` are executable onboarding workflows, not
scratchpads. They should stay:

- public-API-first
- human-first in narrative and code style
- free of repo-local `sys.path` manipulation and ad hoc helper scaffolding

## Agent Contract

Machine-readable agent metadata lives at:

- `.tools/agent/manifest.json`

The contract check is:

- `python .tools/quality/check_agent_readiness.py`
