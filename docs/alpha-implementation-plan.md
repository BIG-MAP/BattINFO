# Alpha Implementation Plan

This document converts the current alpha review findings into an implementation sequence that is small enough to execute in reviewable chunks while still converging on the stated alpha scope.

The target alpha scope for this plan is:

- easy clean-environment install and build
- validated and queryable commercial battery cell records with simple specification-sheet data
- validated and queryable detailed battery cell records for:
  - coin
  - cylindrical
  - single-layer pouch
  - multilayer pouch
  - prismatic
- validated and queryable test records for:
  - cycling
  - rate capability
  - formation
  - HPPC
  - ICI
  - GITT
  - DCIR
  - EIS
- validated and queryable dataset records linked to both a cell and a test

## Design Constraints

- Keep the current alpha scope narrow and explicit.
- Prefer additive schema/API changes over disruptive redesign.
- Ensure every supported alpha case has:
  - at least one canonical example
  - validation coverage
  - linkage coverage
  - query coverage
- Treat preview and in-development surfaces as out of scope unless they block the alpha path above.

## Current Blocking Gaps

- The shipped descriptor -> cell-instance example chain is inconsistent.
- The canonical test taxonomy does not cover all required test kinds.
- The detailed cell descriptor contract cannot distinguish the required pouch subtypes and does not yet prove the required format cases with canonical examples.
- Top-level docs do not yet provide a clean bootstrap and alpha verification path.
- The documented CLI contract lags the shipped CLI surface in some areas, including test querying.

## Chunk 0: Lock the Alpha Contract

Purpose:
- Freeze what alpha promises and what it does not.

Deliverables:
- align `README.md`, `docs/alpha-scope.md`, and `docs/cli-spec.md`
- define one acceptance matrix for the supported alpha cases
- declare the canonical alpha verification command set

Planned changes:
- update the core-scope wording in `docs/alpha-scope.md`
- add the supported alpha cases to `README.md`
- document `query tests` in `docs/cli-spec.md`
- add the acceptance matrix to this plan or a dedicated alpha acceptance doc

Acceptance criteria:
- top-level docs describe the same supported alpha surface
- no top-level doc implies broader support than the actual tested surface
- the alpha verification path is documented in one place

Primary files:
- `README.md`
- `docs/alpha-scope.md`
- `docs/cli-spec.md`
- `docs/index.md`

## Chunk 1: Repair the Canonical Example Chain

Purpose:
- make the shipped `CellType -> CellInstance -> Test -> Dataset` path internally consistent

Deliverables:
- one canonical linked example chain with matching IDs
- regression tests for all required links

Planned changes:
- fix the `specification.id` / `cell_instance.type_id` mismatch in the A123 example chain
- assert these links in tests:
  - descriptor `specification.id` -> cell-instance `type_id`
  - cell-instance `id` -> test `cell_id`
  - test `id` -> dataset `about[]`
  - test `dataset_ids[]` -> dataset `id`

Acceptance criteria:
- the bundled example chain validates end to end
- tests fail on any future ID drift in the example chain

Primary files:
- `examples/cell-descriptors/a123-anr26650m1-b.example.json`
- `examples/cell-instances/cell-3m6k-9t2p-7x4h-9nq8.json`
- `examples/tests/test-5p7v-2n8k-4m3t-6q9r.json`
- `examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json`
- `tests/test_alpha_workflow.py`
- `tests/test_api.py`

## Chunk 2: Expand the Canonical Test Taxonomy

Purpose:
- make all required alpha test kinds first-class, validated, and queryable

Recommended approach:
- use explicit `test.kind` enum values for alpha:
  - `cycle_life`
  - `rate_capability`
  - `formation`
  - `hppc`
  - `ici`
  - `gitt`
  - `dcir`
  - `eis`
- retain existing values that are already in use:
  - `capacity_check`
  - `calendar_ageing`
  - `impedance`
  - `other`

Notes:
- `impedance` should remain valid for backward compatibility during alpha.
- `eis` should be preferred for the explicit electrochemical impedance workflow.

Deliverables:
- schema enum update
- typed API update
- CLI help and validation update
- one canonical example per required test kind
- query tests by `kind`

Acceptance criteria:
- each required test kind validates without falling back to `other`
- each required test kind can be queried through API and CLI

Primary files:
- `assets/schemas/test.schema.json`
- `src/battinfo/data/schemas/test.schema.json`
- `src/battinfo/api.py`
- `src/battinfo/cli.py`
- `examples/tests/`
- `tests/test_test_contract.py`
- `tests/test_cli_query_create_publish.py`
- `tests/test_api.py`

## Chunk 3: Add Minimal Structural Fields for Required Cell Formats

Purpose:
- represent the required detailed cell cases without over-designing the ontology contract

Recommended approach:
- keep `specification.format` unchanged
- add a minimal construction block under `specification`, for example:
  - `construction.assembly_type`: `wound|stacked|other|unknown`
  - `construction.layer_count`: integer or null
  - `construction.layer_count_basis`: `single_layer|multilayer|unknown`

The exact field names can be refined during implementation, but alpha needs enough structure to distinguish:
- coin
- cylindrical
- prismatic
- pouch, single-layer
- pouch, multilayer

Deliverables:
- schema extension for format-specific construction metadata
- validation tests for the new fields
- mapping updates only where needed for stable JSON-LD output

Acceptance criteria:
- a pouch descriptor can encode and validate single-layer vs multilayer explicitly
- the additional fields do not break existing cylindrical, coin, or prismatic examples

Primary files:
- `assets/schemas/modules/components/specification.schema.json`
- `src/battinfo/data/schemas/modules/components/specification.schema.json`
- `assets/schemas/cell-descriptor.schema.json`
- `src/battinfo/workflows/map.py`
- `src/battinfo/transform/json_to_jsonld.py`
- `tests/test_battery_descriptor_schema.py`
- `tests/test_mapping.py`

## Chunk 4: Add the Required Canonical Cell Examples

Purpose:
- prove the supported detailed cell cases with validated examples rather than inferred support

Deliverables:
- one simple commercial cell example with specification-sheet-level data
- one detailed descriptor example each for:
  - coin
  - cylindrical
  - single-layer pouch
  - multilayer pouch
  - prismatic

Required content for each detailed example:
- `specification`
- positive electrode
- negative electrode
- electrolyte
- separator
- construction metadata when needed for the format distinction

Acceptance criteria:
- every required format example validates
- every required format example maps to JSON-LD successfully
- every required format example is covered by at least one positive test

Primary files:
- `examples/cell-descriptors/`
- `src/battinfo/data/examples/cell-descriptors/`
- `.battinfo/library/cell-type/`
- `tests/test_battery_descriptor_contract.py`
- `tests/test_mapping.py`

## Chunk 5: Strengthen Dataset and Query Coverage

Purpose:
- make the alpha dataset story explicit: a dataset must describe a cell and result from a test

Deliverables:
- richer linked dataset examples
- query coverage for cell, test, and dataset relations
- docs that show the full workflow including `query tests`

Planned changes:
- ensure canonical dataset examples link both the cell and the test
- add query tests for:
  - datasets by related cell
  - datasets by related test
  - tests by cell
  - tests by dataset
- ensure index outputs continue to include tests as first-class records

Acceptance criteria:
- the linked dataset story is proven by examples and tests
- users can query from either side of the cell/test/dataset chain

Primary files:
- `examples/dataset/`
- `src/battinfo/api.py`
- `src/battinfo/cli.py`
- `docs/instance-test-dataset-workflow.md`
- `tests/test_cli_query_create_publish.py`
- `tests/test_api.py`
- `tests/test_alpha_workflow.py`

## Chunk 6: Clean Bootstrap and Packaging

Purpose:
- satisfy the alpha requirement that core workflows install and run from a clean environment

Deliverables:
- clean install instructions
- one documented alpha verification command set
- optional packaging smoke check

Recommended bootstrap path:
1. `python -m venv .venv`
2. `.\\.venv\\Scripts\\python -m pip install -U pip setuptools wheel`
3. `.\\.venv\\Scripts\\python -m pip install -e .[dev]`
4. `.\\.venv\\Scripts\\python .tools\\quality\\run_alpha_verification.py`

Recommended packaging check:
- `.\\.venv\\Scripts\\python -m build --no-isolation`

Acceptance criteria:
- README bootstrap instructions work from a clean virtual environment
- alpha verification does not depend on undocumented local state
- packaging smoke check is documented if it is part of the alpha gate

Primary files:
- `README.md`
- `pyproject.toml`
- `tests/installed_smoke.py`
- optional helper script under `.tools/` if needed

## Chunk 7: Add a Dedicated Alpha Acceptance Suite

Purpose:
- provide a single go/no-go test surface for the supported alpha scope

Deliverables:
- one canonical alpha verification entry point
- acceptance fixtures if needed

Required coverage:
- simple commercial cell
- detailed cell descriptors for the supported formats
- each required test kind
- linked dataset case
- query, validate, publish, and index flows over that fixture set

Acceptance criteria:
- one small test group proves the entire stated alpha scope
- the alpha verification entry point is the default release gate for alpha readiness

Primary files:
- `tests/test_alpha_workflow.py`
- `tests/test_alpha_descriptor_matrix.py`
- `tests/test_alpha_scope_acceptance.py`
- `.tools/quality/run_alpha_verification.py`
- `tests/fixtures/` if introduced

## Suggested Implementation Order

1. Chunk 0: lock docs and acceptance matrix
2. Chunk 1: repair the canonical example chain
3. Chunk 2: expand the test taxonomy
4. Chunk 3: add minimal structural fields for required cell formats
5. Chunk 4: add the required canonical cell examples
6. Chunk 5: strengthen dataset and query coverage
7. Chunk 6: clean bootstrap and packaging
8. Chunk 7: add the dedicated alpha acceptance suite

## Suggested PR Breakdown

PR 1:
- Chunk 0
- Chunk 1

PR 2:
- Chunk 2

PR 3:
- Chunk 3
- first format-specific descriptor examples

PR 4:
- remaining required cell examples
- dataset/query coverage

PR 5:
- bootstrap/packaging cleanup
- alpha acceptance suite

## Definition of Done

BattINFO is ready for the stated alpha scope when:

- the supported alpha cases are documented consistently
- the canonical example chain is internally consistent
- every required test kind is first-class and queryable
- every required cell format has a validated canonical example
- linked datasets are validated and queryable through the cell/test chain
- a clean environment can install, validate, publish, index, and query the supported cases
- the dedicated alpha acceptance suite passes




