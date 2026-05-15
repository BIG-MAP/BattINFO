# BattINFO

BattINFO is the **semantic data layer for battery science**. It provides a
Python library, CLI, and canonical asset suite — JSON schemas, ontology
mappings, and examples — that make it straightforward to create, validate,
and publish battery metadata as machine-readable Linked Data.

Every record published through BattINFO is a valid RDF document, typed against
[EMMO domain-battery](https://github.com/emmo-repo/domain-battery) and
resolvable through persistent `https://w3id.org/battinfo/` IRIs.

## Get started

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
```

```python
from battinfo import CellType, publish

result = publish(
    CellType(manufacturer="Panasonic", model="NCR18650B",
             format="cylindrical", chemistry="Li-ion",
             nominal_properties={"nominal_capacity": {"value": 3.4, "unit": "Ah"}}),
    destination="local",
    root=".battinfo/my-library",
)
print(result.canonical_iri)
# https://w3id.org/battinfo/cell-type/xxxx-xxxx-xxxx-xxxx
```

**→ [Full quickstart](QUICKSTART.md)** · **[Documentation index](docs/index.md)**

---

## Guide notebooks

Interactive Jupyter notebooks in `docs/guides/` — open from the repo root with the `.venv` kernel.

| Notebook | What you'll learn |
|---|---|
| [01 — Concepts](docs/guides/01-concepts.ipynb) | Data model, record types, IRIs, and the semantic layer |
| [02 — First cell type](docs/guides/02-first-cell-type.ipynb) | Materials → components → cell type → publish |
| [03 — Linked records](docs/guides/03-linked-records.ipynb) | Cell instance → test → dataset → registry submission |
| [04 — Semantic layer](docs/guides/04-semantic-layer.ipynb) | JSON-LD anatomy, EMMO type stacking, RDF and SPARQL |
| [05 — Descriptors](docs/guides/05-descriptors.ipynb) | Research-grade descriptors: electrodes, electrolyte, separator |

---

## Semantic foundation

| Layer | What it provides |
|-------|-----------------|
| `ontology/battinfo.ttl` | OWL application ontology; imports EMMO domain-battery 0.18.8 and domain-electrochemistry 0.34.0 with pinned versioned IRIs |
| `assets/mappings/domain-battery/` | 47 curated property→EMMO-IRI mappings and 27 unit→EMMO-IRI mappings; drives JSON→JSON-LD transformation |
| `assets/schemas/` | 23 JSON Schema (draft 2020-12) files covering cell types, cell instances, electrodes, electrolytes, separators, tests, datasets, and organisations |
| `src/battinfo/transform/json_to_jsonld.py` | Deterministic, mapping-table-driven transformation to EMMO-aligned JSON-LD using the canonical domain-battery context |
| `src/battinfo/validate/` | Multi-layer validation: JSON Schema, Pydantic, JSON-LD (URDNA2015), semantic rules, referential integrity, publication |

Published records use:
- `hasProperty` → `[ClassName, ConventionalProperty]` → `hasNumericalPart` → `hasNumericalValue` (canonical EMMO quantity pattern)
- `hasMeasurementUnit` → full EMMO or QUDT IRI (never a bare string)
- `@type` stacking: a cylindrical LFP cell is simultaneously `BatteryCell`, `CylindricalBattery`, `LithiumIonBattery`, `LithiumIonIronPhosphateBattery`, and `LithiumIonGraphiteBattery`

## Status

Pre-release (alpha). Core query/create/publish/index workflows are implemented and tested against 296 tests.
Ontology dependency versions are pinned and verified. See [`docs/alpha-scope.md`](docs/alpha-scope.md).

Alpha scope
- Core: stable cell-descriptor validation/mapping, canonical record query/save/publish/index flows, JSON-LD-first publication, and validation policies.
- Preview: reusable cell-type library flows beyond the alpha walkthrough fixtures.
- In development: registry sync/query flows and large-scale reference validation.
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
- **Domain-battery is the normative ontology** (semantics and terms). BattINFO is non-normative and operational (schemas, mappings, tooling).
- **Canonical contract is JSON Schema**; Pydantic models are generated for the CLI and Python API.
- **JSON-LD-first publication**: every record rendered for the resolver or registry is valid RDF aligned to domain-battery.
- **Stable, opaque identifiers**: all published entities carry a `https://w3id.org/battinfo/{type}/{uid}` IRI, governed by the identifier policy in `IDENTIFIER_POLICY.md`.
- Battery Pass JSON-LD outputs are supported and pinned per release.

What BattINFO does
- Validate battery metadata as plain JSON (JSON Schema / Pydantic) and as semantic RDF (JSON-LD + URDNA2015 normalisation).
- Map JSON inputs into domain-battery-aligned JSON-LD using authoritative curated property and unit mappings.
- Produce Battery Pass-compatible JSON-LD (pinned to v1.2.0).
- Provide profiles, examples, and mapping rules for all common battery record types.
- Support a reusable cell-type library curated once as BattINFO descriptors and published as generated RDF/JSON-LD.
- Publish dataset metadata as JSON-LD with a core `CellType → CellInstance → Test → Dataset` provenance chain.

Checking EMMO dependency versions
```powershell
.\.venv\Scripts\python .tools/quality/check_emmo_versions.py
```
The bundled EMMO domain-battery context (`src/battinfo/data/context/domain-battery.context.json`)
enables offline JSON-LD processing. Refresh it when upgrading EMMO versions:
```powershell
.\.venv\Scripts\python .tools/quality/refresh_emmo_context.py
```

Python authoring terminology
- `Workspace` is the primary Python authoring surface for linked BattINFO records.
- `LocalWorkspace` is the separate disk-first scaffold behind `battinfo workspace ...`.
- `battinfo ingest ...` is the fastest user-facing intake flow for one typed resource instance plus its attached files.
- The formal `battinfo.ingest.json` contract is documented in `docs/ingest-manifest-contract.md`.

Quick start
```
battinfo validate input.json --profile cell-descriptor --format json
battinfo validate input.json --profile batterypass --format json
battinfo template cell-type-draft --out a123-anr26650m1-b.draft.json --format json
battinfo template cell-type --manufacturer Duracell --model-name MN1500 --chemistry Zn-air --cell-format cylindrical --out mn1500.cell-type.json --format json
battinfo save record --input mn1500.cell-type.json --source-root examples --no-resolve-references --format json
battinfo map input.json --target domain-battery --out output.domain.jsonld
battinfo map input.json --target batterypass --out output.jsonld
battinfo query cell-type --manufacturer A123 --chemistry LFP --format json
battinfo create cell-instance --model-name ANR26650M1-B --manufacturer A123 --format json
battinfo save cell-type --manufacturer Duracell --model-name MN1500 --chemistry Zn-air --cell-format cylindrical --source-file manual-mn1500.json --format json
battinfo save cell-instance --type-id https://w3id.org/battinfo/cell-type/3m6k-9t2p-7x4h-9nq8 --source-type lab --format json
battinfo save dataset --title "MN1500 cycling" --source-type measurement --format json
battinfo save batch --source-dir batch/cell-type --source-dir batch/cell-instances --source-dir batch/dataset --source-root examples --format json
battinfo publish batch --source-dir examples/cell-instances --format json
battinfo index build --source-root examples --out .battinfo/index.json --format json
battinfo index stats --index .battinfo/index.json --format json
```

Fast ingest flow
- Use this path when you already have one instance folder containing photos and raw CSV datasets.
- Recommended folder shape:
  - `image/photo/*`
  - `timeseries/raw/*.csv`
- First-time setup for a cell instance:
  `battinfo ingest init D:\cell_phone\novonix\google--g20m7--2025--15qnrp --resource-type cell-instance --type-record battinfo-records/records/cell-type/google--g20m7--2025/record.json --resource-iri https://w3id.org/battinfo/cell/15qn-rpd4-xhy7-kx2q --publisher-id demo-lab --license CC-BY-4.0 --format json`
- Review what BattINFO will infer:
  `battinfo ingest inspect D:\cell_phone\novonix\google--g20m7--2025--15qnrp --format json`
- Build the linked `Workspace` and submission package:
  `battinfo ingest build D:\cell_phone\novonix\google--g20m7--2025--15qnrp --resource-type cell-instance --workspace-id google-g20m7-instance-demo --source-version demo-2026-04-09 --artifact-base-url http://127.0.0.1:8040 --format json`
- Publish the same folder in one command:
  `battinfo ingest publish D:\cell_phone\novonix\google--g20m7--2025--15qnrp --resource-type cell-instance --registry-url https://registry.example.org --api-key <submission-key> --workspace-id google-g20m7-instance-demo --source-version demo-2026-04-09 --artifact-base-url https://artifacts.example.org --platform-url https://www.battery-genome.org --format json`
- After `battinfo.ingest.json` exists inside the folder, the follow-up commands only need the folder path plus publication-specific options.
- The ingest flow currently supports `--resource-type cell-instance` and is designed to expand to other instance/resource types later.
- The ingest flow automatically:
  - preserves an existing `resource_iri` when supplied
  - creates one standalone photo dataset per image
  - creates one test plus one dataset per CSV
  - wires the first photo dataset as the Battery Genome cell hero image

Python API quick start
```python
from pathlib import Path

from battinfo import Workspace, load_publication

workspace = Workspace(root=Path(".battinfo/demo"))

cell_type = workspace.cell_type(
    manufacturer="Energizer",
    model="CR2032",
    format="coin",
    chemistry="Li-primary",
    size_code="CR2032",
)

cell = workspace.cell(cell_type, serial_number="energizer-cr2032-202602-dtjrga")
test = workspace.test(
    cell,
    kind="capacity_check",
    protocol="constant current discharging",
    instrument="short Landt cycler",
)
dataset = workspace.dataset(
    cell,
    test=test,
    path="path/to/dataset-dir",
    title="Energizer CR2032 dataset",
)

workspace.save()
workspace.build_publication_package(dataset)
bundle = load_publication("path/to/dataset-dir/battinfo.publish.jsonld")
```
- Full API guide: `docs/python-api.md`
- Validation contract: `docs/validation-contract.md`
- Editorial cell-type workflow contract: `docs/editorial-cell-type-workflow.md`

Identifier policy
- See `IDENTIFIER_POLICY.md` for canonical identifier and minting governance.

Notebooks
- See `examples/notebooks/README.md` for the current executable workflow examples:
  the minimal end-to-end BattINFO authoring and publication flow.
- If VS Code gets stuck on notebook kernel restart for the repo `.venv`, run:
  `battinfo notebook recover --workspace-root . --format text`

Source documents and submission packages
- Dataset registry intake / submission package spec (v1 draft): `docs/dataset-registry-intake-spec.md`
- `battinfo` now treats the submission package as a thin transport envelope. BattINFO-generated packages carry canonical BattINFO records in `battinfo_records`; registry display metadata is derived downstream instead of duplicated in the submission payload.
- New human-facing publish path for cell types:
  `result = publish(cell_type, destination="local")`
  `result = publish(cell_type, destination="registry", registry_base_url="...", api_key="...", workspace_id="...", publisher_id="...")`
  `result = publish(cell_type, destination="battery-genome", registry_base_url="...", api_key="...", platform_base_url="...", workspace_id="...", publisher_id="...")`
- Matching CLI path:
  `battinfo publish cell-type --manufacturer Google --model G20M7 --cell-format prismatic --chemistry Li-ion --destination local --format json`
- `publish(...)` writes the canonical BattINFO record first, then optionally generates and submits the registry submission package behind the scenes. For the legacy dataset publication-package flow, the existing keyword form `publish(cell_type=..., cell_instance=..., test=..., dataset=...)` still works.
- Run datasheet quality checks:
  `python .tools/datasheets/check_datasheet_quality.py --dir <path-to-datasheets> --report .battinfo/reports/datasheet-quality.md`
- Build datasheet curation backlog report:
  `python .tools/datasheets/report_datasheet_curation_backlog.py --dir <path-to-datasheets> --out .battinfo/reports/datasheet-curation-backlog.md --max-list 30`
- Build datasheet delta report:
  `python .tools/datasheets/report_datasheet_delta.py --baseline-dir <baseline-dir> --enriched-dir <updated-dir> --out .battinfo/reports/datasheet-delta.md`
- Generate first-pass semantic mapping candidates for quantitative properties:
  `python .tools/semantic/generate_semantic_mapping_candidates.py --ontology https://w3id.org/emmo/domain/battery/inferred --sample-json examples/cell-type/A123__ANR26650M1-B.json --out-dir assets/mappings/domain-battery --overwrite`
- Run semantic mapping quality gates and emit review report:
  `python .tools/semantic/check_semantic_mapping_candidates.py --property-map assets/mappings/domain-battery/property_map.candidates.json --unit-map assets/mappings/domain-battery/unit_map.candidates.json --report assets/mappings/domain-battery/quantitative_mapping_gate.md`

Template-first save workflow
- Generate a hand-edited authoring draft:
  `battinfo template cell-type-draft --out cell-type.draft.json`
- Generate starter records:
  `battinfo template cell-type --out cell-type.template.json`
  `battinfo template cell-instance --out cell-instance.template.json`
  `battinfo template dataset --out dataset.template.json`
- Register canonical records:
  `battinfo save record --input cell-type.template.json --source-root examples --no-resolve-references --format json`
  `battinfo save record --input cell-instance.template.json --source-root examples --resolve-references --format json`
  `battinfo save record --input dataset.template.json --source-root examples --resolve-references --format json`
- Register in one pass from staging directories:
  `battinfo save batch --source-dir batch/cell-type --source-dir batch/cell-instances --source-dir batch/dataset --source-root examples --resolve-references --format json`

CLI roadmap
- See `docs/cli-spec.md` for the concrete `query` / `create` / `publish` / `index` command specification.

Registry and platform demo
- Scaffold a Python-authored demo environment with canonical records plus a generated submission package:
  `battinfo demo setup .battinfo/demo-e2e --format json`
- Publish the same demo through a registry and optionally verify the Battery Genome page:
  `battinfo demo verify .battinfo/demo-e2e --registry-url http://127.0.0.1:8000 --api-key <submission-key> --platform-url http://127.0.0.1:3001 --format json`
- The same flow is available from Python with `setup_demo_environment(...)` and `run_demo_pipeline(...)`.

Resolver artifact build (first draft)
```
python .tools/build/build_resolver_artifacts.py
python .tools/quality/lint_identifier_policy.py
python .tools/library/validate_cells_clean.py
```
This generates static resolution artifacts under `.battinfo/resolver-site/` for:
- `cell`
- `cell-type`
- `dataset`

Repository layout
- `assets/` Canonical schemas and mapping assets
- `examples/` Canonical example records, walkthrough notebooks, and small demo workflows
- `src/battinfo/` Python package + CLI
- `docs/` Adoption and usage docs
- `.tools/` Maintainer-only tooling grouped into `build/`, `datasheets/`, `library/`, `quality/`, and `semantic/`
- `tests/` Regression and contract tests
- `legacy/` Prior ontology artifacts and docs (archived)

Repository hygiene
- Keep schemas and mapping tables under `assets/`.
- Keep canonical example records and notebooks under `examples/`.
- Treat generated-output paths such as `.battinfo/library-rdf/` as rebuildable outputs, not hand-edited source.
- Keep the packaged runtime subset under `src/battinfo/data/`.
- Keep experimental outputs, review artifacts, and scratch runs under ignored local paths such as `.battinfo/`, not at repository root.
- Treat hidden directories such as `.venv/`, `.pytest_cache/`, `.battinfo/`, and `.jupyter-runtime-test/` as local runtime state.

Notes
- BattINFO does not host or modify the domain-battery ontology.
- BattINFO does not publish authoritative Battery Pass artifacts.










