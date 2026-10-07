# Scope and capabilities

This page says what BattINFO covers and how mature each part is: what you can rely on today, what works but may still change, and what is in development.

## Modeling scope

BattINFO models the cell level and below. That means materials, electrodes, separators, current collectors, electrolytes and housings, the cells built from them, and the tests, test equipment and datasets around those cells. Modules and packs are on the roadmap; no schema or record type covers them yet.

Tested runtime support is Python 3.11 and 3.12, on Linux and Windows.

## Record types

The library registers 22 record types (`ENTITY_KINDS` in `src/battinfo/entities.py`). Each one has a JSON Schema in `assets/schemas/`, is checked by `battinfo validate`, and emits JSON-LD. Most come in pairs: a spec is the reusable description, such as a datasheet, a formulation or a protocol, and an instance is one physical thing or event that points at its spec. The [record-type pages](records/index.md) give a reference example and the field reference for each family.

| Family | Spec | Instance | Authored with |
|---|---|---|---|
| Cells | `cell-spec` | `cell` | the workspace: `ws.load(...)`, `ws.add("cell", ...)` |
| Tests | `test-protocol` (the test spec) | `test` | the workspace: `ws.template("test-spec", ...)` then `ws.load(...)`, `ws.add("test", ...)` |
| Datasets | none | `dataset` | the workspace (`ws.add("test", data=...)`), or `Dataset` with `save_dataset` |
| Materials | `material-spec` | `material` | the workspace: `ws.add("material_spec", ...)`, `ws.add("material", ...)` |
| Electrodes | `electrode-spec` | `electrode` | the workspace: `ws.add("electrode_spec", ...)`, `ws.add("electrode", ...)` |
| Separators, current collectors, electrolytes, housings | `separator-spec`, `current-collector-spec`, `electrolyte-spec`, `housing-spec` | `separator`, `current-collector`, `electrolyte`, `housing` | `battinfo.api` component functions |
| Equipment | `equipment-spec` | `equipment`, `channel` | the workspace: `ws.add("equipment", ...)` |
| Parameter sets | `parameter-set` | none | the workspace: `ws.add("parameter_set", ...)` |
| Organizations | none | `organization` | `battinfo.api.create_organization` and `save_organization` |

A dataset collection is not a separate type. It is a `dataset` whose `additional_type` includes `DatasetSeries`, and its members point at it with `series_id`; [Publish a dataset collection](howto/publish-a-dataset-collection.md) walks through one.

Not every type travels everywhere yet. `ws.submit()` sends the specs and instances of cells, tests, materials, electrodes and equipment to the registry, along with datasets, channels and parameter sets. The registry cannot register the four component families, so those records stay local, and organization records are not submitted. A Zenodo deposit graph describes components inline on the cell spec that uses them, and it carries manufacturer and publisher nodes on the records that name them instead of separate organization records.

## Supported

These capabilities are covered by tests in CI, documented as supported, and are the primary target for feedback:

- validation of every record type against its JSON Schema, with semantic and cross-reference checks, under the policies `default`, `strict`, `publisher` and `ingest` (`battinfo validate`, `battinfo.validate_record_report`)
- JSON-LD for every record type through `battinfo.record_to_jsonld`, built from the curated property and unit maps and the versioned records context at `https://w3id.org/battinfo/context/records/v1.json`
- authoring with `battinfo.workspace()` for cells, test specs, tests, datasets from local data files, materials, electrodes, equipment and channels, and parameter sets, all saved with deterministic IRIs
- publishing a workspace as a Zenodo deposit (`ws.zenodo()`, which leaves a draft unless `publish=True`) and submitting it to the registry review queue (`ws.submit()`), with `ws.preview_jsonld()` to run the publication checks on the deposit graph beforehand
- single records through the record models (`CellSpec`, `Cell`, `TestSpec`, `Test`, `Dataset`) and `battinfo.publish(...)`
- CLI and `battinfo.api` save, query, index and resolver-publish flows for cell specs, cells, test specs, tests and datasets; `battinfo save record` saves a record of any type from a JSON file
- detailed cell descriptions for coin, cylindrical, single-layer pouch, multilayer pouch and prismatic formats, plus half cells and three-electrode cells through `cell_configuration`
- test records with a controlled `kind` such as `cycling`, `capacity_check`, `rate_capability`, `gitt`, `hppc` or `eis` (the full list is in `assets/schemas/test.schema.json`)
- dataset collections, as described above
- the six guide notebooks in `docs/guides/`, which CI executes

## Preview

Available and expected to work, but interfaces may still be refined:

- Standalone records for separators, current collectors, electrolytes and housings. They validate and emit JSON-LD, but the registry cannot take them yet.
- Organization records that other records point at.
- Reading records and data files from a registry with `battinfo.registry.Registry` ([how-to](howto/read-registry-data.md)). Its method names are expected to stay; the catalog columns may grow.
- The importers and exporters in `battinfo.interop`: BPX, Battery Data Commons, battdat, BattInfoConverter JSON-LD, Discovery, the solid-state database, and the aurora-unicycler, bmgen, PyBaMM and UCP protocol formats. The [interop scorecard](pages/interop-recovery.md) measures how completely the converter and Discovery documents are recovered.
- Reusable cell-spec library workflows (`battinfo library ...`) beyond the descriptor fixtures.

Feedback is welcome; regressions here do not block a release unless they break a supported capability.

## In development

Present but with no stability promise:

- the folder-based CLI batch path (`battinfo push`, `battinfo batch ...`, `battinfo dataset ...`) and registry administration (`battinfo registry ...`)
- folder ingest with `battinfo ingest ...`, whose engine handles only the `cell-instance` resource type so far (see the [ingest manifest contract](guarantees.md#ingest-manifest-contract))
- datasheet tooling under `.tools/datasheets/`, which is maintainer-only and has no public contract
- semantic mapping candidate generation and review (`.tools/semantic/`)
- reference validation for corpora larger than a repository-scale source tree

## Verification

A release is considered ready when:

- the supported workflows install and run from a clean environment (CI builds the wheel and runs `tests/installed_smoke.py` against it)
- supported validation behavior is documented and machine-readable
- CI passes on the supported Python versions
- the top-level docs do not promise more than the preview and in-development items deliver

To run the verification gate locally:

```bash
uv sync --all-extras
uv run python .tools/quality/run_verification.py
```
