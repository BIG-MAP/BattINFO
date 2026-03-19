# BattINFO

BattINFO is the implementation and interoperability layer for the
domain-battery ontology. It provides canonical JSON schemas, mappings,
examples, and tooling so data engineers and lab scientists can create,
validate, and transform battery metadata without touching RDF directly.

Status: Pre-release with alpha-ready scope defined.
- Core query/create/publish/index workflows are implemented and tested.
- Core, preview, and in-development boundaries are now documented for alpha testing.

Alpha scope
- Core: stable battery-descriptor validation/mapping, canonical record query/save/publish/index flows, JSON-LD-first publication, and validation policies.
- Preview: reusable cell-type library flows beyond the alpha walkthrough fixtures and curated datasheet validation examples.
- In development: datasheet authoring as a public contract, semantic mapping workflows, and large-scale reference validation.
- Implementation plan for closing alpha blockers: `docs/alpha-implementation-plan.md`

Alpha hardening targets
- simple commercial cell records with specification-sheet-level metadata
- detailed cell descriptors covering coin, cylindrical, pouch, and prismatic formats
- explicit canonical test records and linked dataset records
- clean-environment install, validate, publish, index, and query workflows for the supported alpha cases

Alpha bootstrap
```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python -m pip install -e .[dev]
```

Alpha verification
```powershell
.\.venv\Scripts\python .tools/quality/run_alpha_verification.py
```

Agent bootstrap
- Repo-local agent guide: `AGENTS.md`
- Machine-readable agent manifest: `.tools/agent/manifest.json`
- Contract check: `python .tools/quality/check_agent_readiness.py`
- Machine-readable alpha report: `.\.venv\Scripts\python .tools/quality/run_alpha_verification.py --report-json .battinfo/reports/alpha-verification.json`

Equivalent explicit commands:
```powershell
.\.venv\Scripts\python -m pytest -q tests/test_alpha_workflow.py tests/test_alpha_descriptor_matrix.py tests/test_alpha_scope_acceptance.py
.\.venv\Scripts\python tests/installed_smoke.py
.\.venv\Scripts\python -m build --no-isolation
```

The alpha verification set covers:
- simple commercial cell save/query
- detailed cell descriptors for coin, cylindrical, single-layer pouch, multilayer pouch, and prismatic
- canonical battery-test records for cycling, rate capability, formation, HPPC, ICI, GITT, DCIR, and EIS
- linked dataset records that must reference a tested cell and may also reference a test
- packaging smoke via `python -m build --no-isolation`

Reference policy for alpha:
- `save record --resolve-references` is best-effort and does not require every linked target to already exist
- full referential integrity is enforced on the finished source tree by `save batch --resolve-references` and `build_index(..., validate=True)`

Migration note:
- Local canonical record writes now use `save*` names.
- The older local `register*` names were removed.
- `register*` is reserved for future remote registry communication.

Tested Python support for alpha preparation
- Python 3.10 and 3.11 are the tested targets in CI.
- See `docs/alpha-scope.md` for scope boundaries and support expectations.

Core principles
- Domain-battery remains the normative ontology (semantics and terms).
- BattINFO is non-normative and operational (schemas, mappings, tooling).
- Canonical contract is JSON Schema; Pydantic models are generated for the CLI.
- Battery Pass JSON-LD outputs are supported and pinned per release.

What BattINFO does
- Validate battery metadata as plain JSON (JSON Schema / Pydantic).
- Map JSON inputs into domain-battery aligned JSON-LD.
- Produce Battery Pass JSON-LD (pinned to v1.2.0).
- Provide profiles, examples, and mapping rules for common workflows.
- Support a reusable cell-type library curated once as BattINFO descriptors and published as generated RDF/JSON-LD.
- Enforce persistent, opaque BattINFO identifiers under `https://w3id.org/battinfo/`.
- Publish dataset metadata as JSON-LD with a core `CellType -> CellInstance -> Test -> Dataset` chain.

Quick start
```
battinfo validate input.json --profile battery-descriptor --format json
battinfo validate input.json --profile batterypass --format json
battinfo validate input.datasheet.json --profile cell-type-datasheet
battinfo template cell-type --manufacturer Duracell --model-name MN1500 --chemistry Zn-air --cell-format cylindrical --out mn1500.cell-type.json --format json
battinfo save record --input mn1500.cell-type.json --source-root assets/examples --no-resolve-references --format json
battinfo map input.json --target domain-battery --out output.domain.jsonld
battinfo map input.json --target batterypass --out output.jsonld
battinfo query cell-types --manufacturer A123 --chemistry LFP --format json
battinfo create cell-instance --model-name ANR26650M1-B --manufacturer A123 --format json
battinfo save cell-type --manufacturer Duracell --model-name MN1500 --chemistry Zn-air --cell-format cylindrical --source-file manual-mn1500.json --format json
battinfo save cell-instance --type-id https://w3id.org/battinfo/cell-type/3m6k-9t2p-7x4h-9nq8 --source-type lab --format json
battinfo save dataset --title "MN1500 cycling" --source-type measurement --format json
battinfo save batch --source-dir batch/cell-types --source-dir batch/cell-instances --source-dir batch/datasets --source-root assets/examples --format json
battinfo publish batch --source-dir assets/examples/cell-instances --format json
battinfo index build --source-root assets/examples --out .battinfo/index.json --format json
battinfo index stats --index .battinfo/index.json --format json
```

Python API quick start
```python
from battinfo import CellInstance, CellType, Dataset, Test, load_publication, publish

cell_type = CellType(
    manufacturer="Energizer",
    model="CR2032",
    format="coin",
    chemistry="Li-primary",
    size_code="CR2032",
)

cell = CellInstance(cell_type=cell_type, serial_number="energizer-cr2032-202602-dtjrga")
test = Test(cell=cell, kind="capacity_check", protocol="constant current discharging", instrument="short Landt cycler")
dataset = Dataset(path="path/to/dataset-dir", cell=cell, test=test, name="Energizer CR2032 dataset")

publish(cell_type=cell_type, cell_instance=cell, test=test, dataset=dataset)
bundle = load_publication("path/to/dataset-dir/battinfo.publish.jsonld")
```
- Full API guide: `docs/python-api.md`
- Validation contract: `docs/validation-contract.md`

Identifier policy
- See `IDENTIFIER_POLICY.md` for canonical identifier and minting governance.

Notebooks
- See `notebooks/README.md` for the current executable workflow examples:
  the minimal end-to-end BattINFO authoring and publication flow.
- If VS Code gets stuck on notebook kernel restart for the repo `.venv`, run:
  `battinfo notebook recover --project-root . --format text`

Cell-type datasheets and registry intake
- Dataset registry intake spec (v1 draft): `docs/dataset-registry-intake-spec.md`
- Validate a directory of BattINFO cell-type datasheets:
  `python .tools/datasheets/validate_cell_type_datasheets.py --dir <path-to-datasheets> --profile cell-type-datasheet`
- Run datasheet quality checks:
  `python .tools/datasheets/check_datasheet_quality.py --dir <path-to-datasheets> --report .battinfo/reports/datasheet-quality.md`
- Build datasheet curation backlog report:
  `python .tools/datasheets/report_datasheet_curation_backlog.py --dir <path-to-datasheets> --out .battinfo/reports/datasheet-curation-backlog.md --max-list 30`
- Build datasheet delta report:
  `python .tools/datasheets/report_datasheet_delta.py --baseline-dir <baseline-dir> --enriched-dir <updated-dir> --out .battinfo/reports/datasheet-delta.md`
- Generate first-pass semantic mapping candidates for quantitative properties:
  `python .tools/semantic/generate_semantic_mapping_candidates.py --ontology https://w3id.org/emmo/domain/battery/inferred --sample-json assets/examples/cell-types/A123__ANR26650M1-B.json --out-dir assets/mappings/domain-battery --overwrite`
- Run semantic mapping quality gates and emit review report:
  `python .tools/semantic/check_semantic_mapping_candidates.py --property-map assets/mappings/domain-battery/property_map.candidates.json --unit-map assets/mappings/domain-battery/unit_map.candidates.json --report assets/mappings/domain-battery/quantitative_mapping_gate.md`

Template-first save workflow
- Generate starter records:
  `battinfo template cell-type --out cell-type.template.json`
  `battinfo template cell-instance --out cell-instance.template.json`
  `battinfo template dataset --out dataset.template.json`
- Register canonical records:
  `battinfo save record --input cell-type.template.json --source-root assets/examples --no-resolve-references --format json`
  `battinfo save record --input cell-instance.template.json --source-root assets/examples --resolve-references --format json`
  `battinfo save record --input dataset.template.json --source-root assets/examples --resolve-references --format json`
- Register in one pass from staging directories:
  `battinfo save batch --source-dir batch/cell-types --source-dir batch/cell-instances --source-dir batch/datasets --source-root assets/examples --resolve-references --format json`

CLI roadmap
- See `docs/cli-spec.md` for the concrete `query` / `create` / `publish` / `index` command specification.

Resolver artifact build (first draft)
```
python .tools/build/build_resolver_artifacts.py
python .tools/quality/lint_identifier_policy.py
python .tools/library/validate_cells_clean.py
python .tools/datasheets/validate_cell_type_datasheets.py
```
This generates static resolution artifacts under `.battinfo/resolver-site/` for:
- `cell`
- `cell-type`
- `dataset`

Repository layout
- `assets/` Canonical schemas, mappings, and examples (source of truth)
- `src/battinfo/` Python package + CLI
- `assets/compat.yaml` Compatibility metadata for domain-battery and Battery Pass
- `docs/` Adoption and usage docs
- `.tools/` Maintainer-only tooling grouped into `build/`, `datasheets/`, `library/`, `quality/`, and `semantic/`
- `tests/` Regression and contract tests
- `legacy/` Prior ontology artifacts and docs (archived)

Repository hygiene
- Keep canonical and packaged source-of-truth content under `assets/` and `src/battinfo/data/`.
- Keep experimental outputs, review artifacts, and scratch runs under ignored local paths such as `.battinfo/`, not at repository root.
- Treat hidden directories such as `.venv/`, `.pytest_cache/`, `.battinfo/`, and `.jupyter-runtime-test/` as local runtime state.

Compatibility
See `assets/compat.yaml`.

Notes
- BattINFO does not host or modify the domain-battery ontology.
- BattINFO does not publish authoritative Battery Pass artifacts.



