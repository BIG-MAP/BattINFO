# BattINFO

BattINFO is the implementation and interoperability layer for the
domain-battery ontology. It provides canonical JSON schemas, mappings,
examples, and tooling so data engineers and lab scientists can create,
validate, and transform battery metadata without touching RDF directly.

Status: Pre-release with alpha-ready scope defined.
- Core query/create/publish/index workflows are implemented and tested.
- Core, preview, and in-development boundaries are now documented for alpha testing.

Alpha scope
- Core: stable battery-descriptor validation/mapping, canonical record query/register/publish/index flows, JSON-LD-first publication, and validation policies.
- Preview: reusable cell-type library flows, notebooks, and curated datasheet validation examples.
- In development: datasheet authoring as a public contract, ingestion pipelines, semantic mapping candidate workflows, and large-scale reference validation.

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
battinfo validate assets/datasheets/cell-types/pvn1-43h7-rm3e-mjqq.datasheet.json --profile cell-type-datasheet
battinfo template cell-type --manufacturer Duracell --model-name MN1500 --chemistry Zn-air --cell-format cylindrical --out mn1500.cell-type.json --format json
battinfo register record --input mn1500.cell-type.json --source-root assets/examples --no-resolve-references --format json
battinfo map input.json --target domain-battery --out output.domain.jsonld
battinfo map input.json --target batterypass --out output.jsonld
battinfo query cell-types --manufacturer A123 --chemistry LFP --format json
battinfo create cell-instance --model-name ANR26650M1-B --manufacturer A123 --format json
battinfo register cell-type --manufacturer Duracell --model-name MN1500 --chemistry Zn-air --cell-format cylindrical --source-file manual-mn1500.json --format json
battinfo register cell-instance --type-id https://w3id.org/battinfo/cell-type/3m6k-9t2p-7x4h-9nq8 --source-type lab --format json
battinfo register dataset --title "MN1500 cycling" --source-type measurement --format json
battinfo register batch --source-dir .battinfo/candidates/cell-types --source-dir .battinfo/candidates/cell-instances --source-dir .battinfo/candidates/datasets --source-root assets/examples --format json
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
  descriptor examples, registration flows, and JSON-LD-first dataset publication review.
  These notebooks are currently part of the preview scope, not the core alpha contract.

Cell-type datasheet standard
- Draft v1 reference: `docs/datasheet-standard.md`
- v1.0 release-candidate checklist: `docs/datasheet-v1-rc-checklist.md`
- Dataset registry intake spec (v1 draft): `docs/dataset-registry-intake-spec.md`
- Ingestion pipeline guide (CellInfo + local PDFs): `docs/ingestion-pipeline.md`
- Example batch generation:
  `python .tools/datasheets/generate_cell_type_datasheet_examples.py --count 10 --target-dir .battinfo/datasheets/top10 --strategy diverse --clean-target --batch-tag cellinfo-top10-diverse-v1`
- Example batch generation with conservative negative-electrode inference:
  `python .tools/datasheets/generate_cell_type_datasheet_examples.py --count 100 --strategy diverse --target-dir .battinfo/datasheets/pilot100-enriched --clean-target --batch-tag cellinfo-pilot100-diverse-v1-enriched --infer-negative-electrode-basis`
- Validate generated datasheets:
  `python .tools/datasheets/validate_cell_type_datasheets.py --dir .battinfo/datasheets/top10 --profile cell-type-datasheet`
- Run quality gates on generated batch:
  `python .tools/datasheets/check_datasheet_quality.py --dir .battinfo/datasheets/top10 --report .battinfo/reports/cellinfo-top10-gate.md --max-empty-specs 0 --max-unknown-manufacturer 0 --max-unknown-chemistry 0 --max-unknown-positive-electrode-basis 0 --max-unknown-negative-electrode-basis -1 --required-spec nominal_capacity --required-spec nominal_voltage --min-required-spec-coverage 1.0`
- CI-style smoke gate (deterministic batch + strict unknown-negative gate):
  `python .tools/datasheets/generate_cell_type_datasheet_examples.py --count 10 --strategy diverse --target-dir .battinfo/ci-smoke/cell-types --clean-target --batch-tag ci-smoke-v1 --infer-negative-electrode-basis`
  `python .tools/datasheets/validate_cell_type_datasheets.py --dir .battinfo/ci-smoke/cell-types --profile cell-type-datasheet`
  `python .tools/datasheets/check_datasheet_quality.py --dir .battinfo/ci-smoke/cell-types --report .battinfo/reports/ci-smoke-gate.md --max-empty-specs 0 --max-unknown-manufacturer 0 --max-unknown-chemistry 0 --max-unknown-positive-electrode-basis 0 --max-unknown-negative-electrode-basis 0 --required-spec nominal_capacity --required-spec nominal_voltage --min-required-spec-coverage 1.0`
- Build curation backlog report:
  `python .tools/datasheets/report_datasheet_curation_backlog.py --dir .battinfo/datasheets/top10 --out .battinfo/reports/datasheet-curation-backlog.md --max-list 30`
- Build delta report (baseline vs enriched):
  `python .tools/datasheets/report_datasheet_delta.py --baseline-dir .battinfo/datasheets/pilot100 --enriched-dir .battinfo/datasheets/pilot100-enriched --out .battinfo/reports/pilot100-delta.md`
- Generate first-pass semantic mapping candidates for quantitative properties:
  `python .tools/semantic/generate_semantic_mapping_candidates.py --ontology https://w3id.org/emmo/domain/battery/inferred --sample-json assets/examples/cell-types/A123__ANR26650M1-B.json --out-dir assets/mappings/domain-battery --overwrite`
- Run semantic mapping quality gates and emit review report:
  `python .tools/semantic/check_semantic_mapping_candidates.py --property-map assets/mappings/domain-battery/property_map.candidates.json --unit-map assets/mappings/domain-battery/unit_map.candidates.json --report assets/mappings/domain-battery/quantitative_mapping_gate.md`

Ingestion scaffolding (new)
- Build source manifest from CellInfo + local PDF directory:
  `python .tools/build/build_datasheet_source_manifest.py --cellinfo-dir src/battinfo/data/examples/cells-clean --pdf-dir <path-to-datasheets> --recursive --out .battinfo/ingest/manifests/datasheet-sources.manifest.json --summary-md .battinfo/ingest/manifests/datasheet-sources.summary.md`
- Convert CellInfo records into normalized candidate records:
  `python .tools/ingest/ingest_cellinfo_candidates.py --source-dir src/battinfo/data/examples/cells-clean --target-dir .battinfo/ingest/candidates/cellinfo --clean-target --validate --summary-md .battinfo/ingest/candidates/cellinfo/CELLINFO_CANDIDATES_SUMMARY.md`
- Seed multi-cell PDF candidates from manifest hints:
  `python .tools/ingest/seed_pdf_candidates_from_manifest.py --manifest .battinfo/ingest/manifests/datasheet-sources.manifest.json --target-dir .battinfo/ingest/candidates/pdf-seeded --clean-target`
- Produce dedup/match triage report against existing datasheets:
  `python .tools/ingest/report_candidate_matches.py --candidate-dir .battinfo/ingest/candidates/cellinfo --existing-dir assets/datasheets/cell-types --out .battinfo/ingest/reports/cellinfo-match-report.md --json-out .battinfo/ingest/reports/cellinfo-match-report.json`

Template-first registration workflow
- Generate starter records:
  `battinfo template cell-type --out cell-type.template.json`
  `battinfo template cell-instance --out cell-instance.template.json`
  `battinfo template dataset --out dataset.template.json`
- Register canonical records:
  `battinfo register record --input cell-type.template.json --source-root assets/examples --no-resolve-references --format json`
  `battinfo register record --input cell-instance.template.json --source-root assets/examples --resolve-references --format json`
  `battinfo register record --input dataset.template.json --source-root assets/examples --resolve-references --format json`
- Register in one pass from staging directories:
  `battinfo register batch --source-dir .battinfo/candidates/cell-types --source-dir .battinfo/candidates/cell-instances --source-dir .battinfo/candidates/datasets --source-root assets/examples --resolve-references --format json`

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
- `.tools/` Maintainer-only tooling grouped into `build/`, `datasheets/`, `ingest/`, `library/`, `quality/`, and `semantic/`
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

