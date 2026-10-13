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
| Parameter sets | none | `parameter-set` (minted under `dataset/`) | the workspace: `ws.add("parameter_set", ...)` |
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

## Known limitations in 0.8.0

These gaps were known when 0.8.0 was released and are planned for 0.8.x or 0.9. Where there is a way around one, the line says how.

### BPX parameter files

- Blended electrodes (BPX `Particle` blocks) are not modelled: the import names them in a warning and in the record's `not_imported`, and `to_bpx` returns `complete=False` for such a file.
- The initial hysteresis state, `Degradation` blocks and `Validation` curves stay in the source file and are listed in `not_imported`.
- Curve claims, such as an OCP table, are `schema:PropertyValue` nodes with no EMMO class.
- In a cell spec's JSON-LD, `electrode_area` and `external_surface_area` are both an `Area` node labelled "Area", so only the value tells them apart. Parameter sets name the key in `schema:propertyID`.
- `to_parameter_set(provenance_classes=...)` silently ignores the name of a part the file does not have.

### Workspace and submission

- `Registry.get` returns the registry's entry, not the record, and no helper extracts the record yet; [Get the record out of an entry](howto/read-registry-data.md#get-the-record-out-of-an-entry) shows the one line that does.
- A new version of a published dataset made with `Dataset.from_record` loses the curve-preview files unless you copy them across from the registry entry, and nothing warns you; [Make a new version of a published dataset](howto/read-registry-data.md#make-a-new-version-of-a-published-dataset) shows how.
- `save_dataset` resolves a dataset's cell and test only against the workspace and the registry records the workspace has looked up, which never include tests, so a new version that keeps a published test link needs `resolve_references=False`.
- Once `ws.save()` or `ws.add("equipment")` has written records in a session, `ws.submit()` sends only those, even with `submit_all=True`. Submit records written by `save_dataset` or the other `save_*` functions from a new workspace object.
- `ws.add("test")` takes no as-run `conditions`, start or end time, notes or `source_url`, although the `Test` model has them.
- `ws.search(type="cell", serial=...)` fetches the registry's whole cell list on every call; use `serials=[...]` to look up many cells at once.
- Adding tests to a test spec that is already published sends the spec again, and the registry stores an unchanged copy as a new version.
- `ws.pending()` lists submissions newest first, and approving in that order can publish datasets before the tests and cells they describe. Approve specs, cells and tests first.
- Saving unchanged records again marks datasets and cells `[updated]` with new timestamps, and a test rebuilt in a new workspace gets a new `retrieved_at`, so a re-submission can create versions whose content did not change.
- Collection rules are advice, not checks: a member whose `series_id` names a collection that was never saved passes strict validation (only `ws.preview_jsonld()` warns), and a collection with files or an `about` list still saves.
- The Zenodo deposit graph and `record_to_jsonld` describe tests and datasets differently: `schema:about` against `dcterms:subject` for a dataset's cell and test, `prov:used` against `dcterms:conformsTo` for a test's protocol, and different test titles. Neither emits a test's `description`.
- In JSON-LD, `provenance.retrieved_at` is an untyped `prov:generatedAtTime` literal, not an `xsd:dateTime`.
- A value in `%` or `vol%` is typed with `WeightPercent` or `VolumePercent`, which EMMO defines as quantities rather than units, because EMMO's `Percent` unit is outside the imported ontologies (and EMMO 1.0.2 gives it a conversion factor of 1 instead of 0.01).
- A cell record lists its dataset with role `raw` even when the dataset's main file is the processed table.
- `TestSpec.experiment` writes a constant-current step that has a cutoff but no current as "Discharge until 0.9 V", which the step grammar does not read back.
- `ws.save()` prints "ERROR: ... failed validation" for some records it does write, such as a parameter set still minted under `spec/`.
- Display papercuts: `ws.search()` shows manufacturer and model in lower case, `ws.list(verbose=True)` shows cells by file name, the `ws.save()` summary cuts titles at about 36 characters and collapses after 20 records, and `battinfo.naming.title_for()` writes an all-lowercase method in capitals ("CYCLING test").
- Submission reporting: outcomes and journal entries carry an empty `iri`, a deduplicated re-submission is reported as live, and `ws.status()` lists every submission in the shared registry workspace.

### Dependencies

- The `processing` extra requires `batterydf[nda,excel,mat]>=0.2.0rc2,<0.3`, so it installs the batterydf 0.2.0 release candidate until batterydf 0.2.0 is published.

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
