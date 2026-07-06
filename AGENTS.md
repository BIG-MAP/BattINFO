# BattINFO Agent Guide

This repository is ready for coding agents, but the fastest path is to use the
human-first API and the verification gate rather than inferring workflows
 from low-level schemas.

## Purpose

BattINFO is the implementation and interoperability layer for the
domain-battery ontology. The supported surface is:

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
.\.venv\Scripts\python .tools/quality/run_verification.py
```

For machine-readable verification output:

```powershell
.\.venv\Scripts\python .tools/quality/run_verification.py --report-json .battinfo/reports/verification.json
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
- CLI and low-level registration/query API: `src/battinfo/cli.py`, `src/battinfo/api/` (facade in `__init__.py`)
- acceptance tests: `tests/test_core_workflow.py`, `tests/test_descriptor_matrix.py`, `tests/test_scope_acceptance.py`

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

- `python .tools/quality/run_verification.py`

Useful focused checks:

- `python -m pytest -q tests/test_workspace.py`
- `python -m pytest -q tests/test_bundle.py`
- `python -m pytest -q tests/test_api.py tests/test_cli_query_create_publish.py`
- `python tests/installed_smoke.py`

## Agent Contract

Machine-readable agent metadata lives at:

- `.tools/agent/manifest.json`

The contract check is:

- `python .tools/quality/check_agent_readiness.py`

---

## Data Publication Workflow (battinfo push)

This section covers the researcher-facing data publication pipeline for
uploading battery measurement data to Zenodo and the battery-genome registry.

### One-time setup

```powershell
battinfo config set creator "Family, Given; Institution"
battinfo config set zenodo_token <token>       # from zenodo.org/account/settings/applications
battinfo config set community battinfo-reference
```

Verify:
```powershell
battinfo config show
```

### Publish a folder of data (single command)

```powershell
battinfo push ./my_data/ --cell-spec "Energizer CR2032" --sandbox
```

`push` auto-detects the folder layout:
- **Flat files** (`run1.nda`, `run2.nda` …) — groups by filename pattern, creates cell folders, moves files
- **Sub-folder layout** (one subdir per cell, each containing raw files) — treats each subdir as a cell
- **Existing batch** (folder already contains `batch.yaml`) — skips init, processes all cell sub-folders

Flags:
- `--cell-spec` — required for flat/subdir layouts; omit for existing batches
- `--cells N` — override detected cell count
- `--sandbox` — upload to sandbox.zenodo.org (safe for testing)
- `--yes` / `-y` — skip confirmation prompt (use in automation)
- `--dry-run` — package only, no upload
- `--json` — machine-readable JSON output (Sprint 2, pending)

### Step-by-step (if push is not appropriate)

```powershell
battinfo batch init   ./cr2032/ --cell-spec "Energizer CR2032" --count 6 --batch-id LOT-2025
# Drop raw files into each cell folder (e.g. cr2032/energizer-CR2032-abc123/)
battinfo dataset process ./cr2032/          # validates, converts to BDF, writes annotations
# Edit battinfo-annotations.yaml in any cell with '?' entries, then re-run process
battinfo batch package  ./cr2032/           # builds staging/ with Zenodo metadata
battinfo batch upload   ./cr2032/staging/   # uploads as draft, prints URL
```

### Folder structure after init

```
cr2032/
  batch.yaml                          <- batch manifest (cell spec, lab, operator)
  energizer-CR2032-abc123/
    battinfo.yaml                     <- cell manifest (edit: batch_id, lab, operator)
    2025-06-01__capacity_check__25degC.nda    <- raw data (drop here)
    2025-06-01__capacity_check__25degC.bdf.parquet  <- auto-generated by dataset process
    battinfo-annotations.yaml         <- auto-generated; fill in any '?' entries
    photos/
  energizer-CR2032-def456/
    ...
  staging/                            <- created by batch package / push
    battinfo.bundle.json
    battinfo.publish.jsonld
    ro-crate-metadata.json
    dataset-001.nda
    dataset-001.bdf.parquet
    ...
```

### Data model key concepts

| Concept | Description |
|---------|-------------|
| `cell_spec_iri` | Stable IRI for a reusable cell specification (e.g. Energizer CR2032) |
| `cell_iri` | Stable IRI for one physical cell instance; minted at `batch init` time |
| `batch.yaml` | Batch-level manifest: cell spec, count, lab, operator |
| `battinfo.yaml` | Per-cell manifest: cell IRI, batch ID, provenance fields |
| `battinfo-annotations.yaml` | Per-cell file metadata: test type, date, temperature for each raw file |
| `battinfo.bundle.json` | Multi-dataset Zenodo record (harvest target for battery-genome registry) |
| `ZENODO_RECORD_ID` | Placeholder replaced by the real Zenodo record ID after deposit creation |

### Automation / AI agent pattern

```python
from battinfo.contribution import push_batch
from battinfo.config import resolve_creators, resolve_zenodo_token

result = push_batch(
    "./my_data/",
    cell_spec="Energizer CR2032",
    creators=resolve_creators(None),       # reads from ~/.battinfo/config.yaml
    zenodo_token=resolve_zenodo_token(),   # reads from config / env
    sandbox=True,
    confirm=False,                         # no interactive prompt
)
print(result["zenodo_url"])  # Zenodo draft URL
```

### Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `cell_spec is required` | Flat folder with no `--cell-spec` | Pass `--cell-spec "Manufacturer Model"` |
| `No raw data files found` | Files not in expected extensions or wrong folder | Check `_RAW_EXTENSIONS` in `contribution.py` |
| `No creator specified` | Config not set, no `--creator` flag | `battinfo config set creator "..."` |
| `Zenodo token required` | Token not in config or env | `battinfo config set zenodo_token <token>` |
| `invalid ingest manifest … type_record` | Cell spec IRI not found in library | Check IRI is correct; run `battinfo library query cell-spec --id <iri>` |
| `? entries in battinfo-annotations.yaml` | Filename not recognised, BDF inference inconclusive | Edit the YAML: fill in `test_type`, `date`, `temperature_degC` |

### Key source files

| File | Purpose |
|------|---------|
| `src/battinfo/contribution.py` | `init_batch`, `process_contribution`, `package_batch`, `push_batch`, `_group_files_by_cell` |
| `src/battinfo/cli.py` | `battinfo push`, `battinfo batch *`, `battinfo dataset *`, `battinfo config *` |
| `src/battinfo/config.py` | User config: `load_user_config`, `resolve_creators`, `resolve_zenodo_token` |
| `src/battinfo/processing.py` | BDF conversion: `convert_raw_to_bdf`, `_infer_test_type_from_df` |
| `src/battinfo/zenodo.py` | `upload_zenodo_package`, `ZenodoClient` |
| `src/battinfo/bundle.py` | `ZenodoCellRecord`, `ZenodoDatasetEntry` |
| `src/battinfo/publication.py` | `build_zenodo_package` |
