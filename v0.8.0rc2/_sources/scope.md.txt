# Scope and capabilities

This page says what BattINFO covers and how mature each part is: what you can rely on today, what works but may still change, and what is in development.

## Modeling scope

BattINFO models the cell level and below. That means materials, electrodes, separators, current collectors, electrolytes and housings, the cells built from them, and the tests, test equipment and datasets around those cells. Modules and packs are on the roadmap; no schema or record type covers them yet.

Tested runtime support is Python 3.11–3.14, on Linux and Windows. Python 3.15 is not supported yet; the known limitations below say why.

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
- single cell-spec records with `CellSpec` and `battinfo.publish(...)`, and single `Cell`, `TestSpec`, `Test` and `Dataset` records with `save_cell_instance`, `save_test_spec`, `save_test` and `save_dataset`
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
- a Battery Pass crosswalk, from cell records to the Battery Pass Data Model. 0.8.0 has none: the draft `batterypass` mapping target and validation profile are removed, and the draft profile schema stays at its URL, marked withdrawn

## Known limitations in 0.8.0

These gaps were known when 0.8.0 was released. Each is planned for a 0.8.x release or for 0.9; where the release is settled, the line names it and says why the gap can wait, and where there is a way around a gap, the line says how.

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
- `ws.add("test")` takes no as-run `conditions`, notes or `source_url`, although the `Test` model has them.
- Lab labels are not scoped to a lab until 0.9. A cell's IRI comes from its spec and its serial number (or its name, for a cell without one), so two labs that both call a cell of one spec `S1` or `C01` mint one cell IRI, and the tests and datasets on it can share IRIs too. The registry refuses the second lab's record, and `ws.submit()` reports that clash with how to rename or pin the record rather than retrying it as a new version. Use the serial printed on the cell, or a label only your lab uses. For the same reason, `ws.add("test", cell="C01")` can find another lab's `C01` in the registry when your workspace holds no such cell; it prints the cell's publisher, and refuses to choose when several cells match.
- `ws.search(type="cell", serial=...)` fetches the registry's whole cell list on every call; use `serials=[...]` to look up many cells at once.
- Adding tests to a test spec that is already published sends the spec again, and the registry stores an unchanged copy as a new version.
- `ws.pending()` lists submissions newest first, and approving in that order can publish datasets before the tests and cells they describe. Approve specs, cells and tests first.
- Saving unchanged records again marks datasets and cells `[updated]` with new timestamps, and a test rebuilt in a new workspace gets a new `retrieved_at`, so a re-submission can create versions whose content did not change.
- Collection rules are advice, not checks: a member whose `series_id` names a collection that was never saved passes strict validation (only `ws.preview_jsonld()` warns), and a collection with files or an `about` list still saves.
- The Zenodo deposit graph and `record_to_jsonld` describe tests and datasets differently: `schema:about` against `dcterms:subject` for a dataset's cell and test, `prov:used` against `dcterms:conformsTo` for a test's protocol, and different test titles. Neither emits a test's `description`. The deposit graph's equipment and channel nodes carry none of their `property` values, which `record_to_jsonld` emits.
- In JSON-LD, `provenance.retrieved_at` is an untyped `prov:generatedAtTime` literal, not an `xsd:dateTime`.
- A percent value is published with the unit `PercentUnit` from domain-electrochemistry, the only percent unit in the imported ontologies, and its maintainers have yet to confirm it as the long-term IRI. EMMO's own `Percent` unit is outside the imported ontologies, and EMMO 1.0.2 gives it a conversion factor of 1 instead of 0.01. A basis the unit states (`wt%`, `vol%`) is not part of the unit: it rides as an extra `WeightPercent` or `VolumePercent` class on the quantity.
- EMMO has no class for a constant-resistance step or a CC-CV discharge. In a test protocol's JSON-LD a cr or cccv discharge is typed with the parent class `Discharging`, and a cr charge, or a cr or cccv step with no direction, has no class, only its mode as `skos:prefLabel`; validation warns `semantic.method_step_unmapped`.
- A cell record lists its dataset with role `raw` even when the dataset's main file is the processed table.
- `TestSpec.experiment` writes a constant-current step that has a cutoff but no current as "Discharge until 0.9 V", which the step grammar does not read back.
- `ws.save()` prints "ERROR: ... failed validation" for some records it does write, such as a parameter set still minted under `spec/`.
- Display papercuts: `ws.search()` shows manufacturer and model in lower case, `ws.list(verbose=True)` shows cells by file name, the `ws.save()` summary cuts titles at about 36 characters and collapses after 20 records, and `battinfo.naming.title_for()` writes an all-lowercase method in capitals ("CYCLING test").
- Submission reporting: outcomes and journal entries carry an empty `iri`, a deduplicated re-submission is reported as live, and `ws.status()` lists every submission in the shared registry workspace.

### Identifiers

These paths mint IRIs that no other path reproduces. The [identifier policy](https://github.com/BIG-MAP/BattINFO/blob/main/IDENTIFIER_POLICY.md) (section 5.4) keeps them outside the identity contract until 0.9, which moves every minting path onto the shared seed builders in `battinfo.entities`; an IRI they minted in 0.8 stays findable then.

- `create_component_spec`, `create_component_instance` and their per-family wrappers (separators, current collectors, electrolytes and housings), `create_equipment_spec` and `create_equipment` give a record without `uid=` or `id=` a random IRI, a new one on every call, so saving their output again saves a second record. Pass a uid derived from the part's natural key, as [Build a cell from components](howto/build-a-cell-from-components.md) does; `ws.add("equipment")` mints equipment from its spec and serial number.
- The BattInfoConverter, solid-state database and Discovery importers, and the Battery Data Commons bridge, mint from their own seeds. Importing one source again gives the same IRIs, but a cell imported from two sources, or imported and also authored in the workspace, gets two.
- On the batch path, `battinfo batch init` and `battinfo batch add` give a cell without a serial number a random IRI, recorded in its `battinfo.yaml`. Keep that file, or pass `--serials` (or `--iris`).
- The publication package (`publish_publication_package`, `build_publication_package`) and `battinfo batch package` seed a dataset from its folder and title rather than its file, so the same data saved from a workspace gets another dataset IRI, and so does a test with data in the publication package. There, `Dataset(id=...)` and `Test(id=...)` keep an IRI you published. `battinfo batch package` seeds a test from its raw file's path in the cell folder, so it matches the workspace only when the workspace's data file has that path in the workspace folder.
- `battinfo batch init --batch-id` seeds a cell from its serial number and its batch. `ws.add("cell")` takes no batch, so it gives the same cell another IRI unless the batch cell has no batch id; pin one with `iris=` or `--iris`.
- `save_test()` and a save of a record without an id never see a data file, so a test with data files gets another IRI there than in the workspace; pass `id=` (or an `id` in the record). A save of a dataset without an id leaves its cell and test out of its seed, so give a dataset of a test its `id`.

### Linked data at record IRIs

- A record's `https://w3id.org/battinfo/` IRI serves the record body expanded with the v1 records context, not the EMMO model that `battinfo.record_to_jsonld`, `ws.export` and the Zenodo deposit graph write. In that body a quantity key such as `nominal_capacity` is a property named by its EMMO class IRI, with `schema:value` and `schema:unitText`, and the record's own id is a `schema:identifier` literal. For the EMMO model, run `record_to_jsonld` on the record or read the deposit's `battinfo.json`. The record body is not normative, and a future v2 context drops it. Serving the EMMO model at record IRIs is planned for 0.9, since it changes what the registry returns for every published record.
- The registry serves a record as it was stored. Several hundred cell specs and `organization` records published in April 2026 were stored with camelCase keys, such as `cellFormat` and `sameAs`, and keep serving them until they are published again in snake_case under the same IRIs, after the registry update for 0.8.0.

### Command line

- `battinfo dataset` is experimental: its `init`, `process` and `publish` steps cannot take a contribution through to a published dataset in 0.8.0. Publish a dataset from Python with `ws.add("test", data=...)` and `ws.zenodo()` instead.
- `battinfo save batch`, `battinfo publish batch`, `battinfo index build --validate` and the `battinfo editorial` validators exit 0 when records fail validation. Read the failed count, or `ok: false`, in their output, which reports every failure. Planned for 0.8.1.
- On Windows, a command that prints JSON can stop with `UnicodeEncodeError` when its output is redirected or piped and holds a character outside the console's code page, such as Ω. Set `PYTHONUTF8=1` to avoid it. Planned for 0.8.1.
- `battinfo query cell-spec` and `battinfo.api.query_cell_specs` compare the capacity and voltage range filters with the number a record stores, whatever its unit, so a capacity stored in mAh is compared as if it were in Ah. Give the filter in the unit your records use. Planned for 0.8.1; a query changes no record.
- `battinfo save batch` and `battinfo publish batch` without `--source-dir` copy BattINFO's packaged example records into your records root, where queries then list them as `local`. Pass `--source-dir`. Planned for 0.8.1.

### Tutorials

- The tutorials have no "Open in Colab" link in 0.8.0. A hosted notebook service such as Colab starts without BattINFO, so install it in a cell first with the `%pip` line that [Getting started](pages/getting-started.rst) gives; tutorial 6 needs the one with the `processing` extra.

### Records and the Python API

- A record model drops the fields it does not represent when it reads a record and writes it again (`from_record()`, then `to_record()`), such as a cell spec's `brand` and `battery_category`, and nothing warns. Edit such a record as JSON instead. Planned for 0.8.1; only fields the model has no attribute for are lost, and only when the model writes the record back.
- A tuple, set, generator or NumPy array passed to a list field of a record model, such as `links`, `keywords`, `notes` or `creators`, becomes an empty list. Pass a list; a single string is kept. Planned for 0.8.1; a list, the form the documentation uses, is kept as given.
- `ws.convert()` skips a second input file whose output would have the same name as another's in the same run, links the wrong raw file to that output, and keeps a truncated output when run again. It prints a `skip (exists)` line for the second file; rename one of the two inputs. Planned for 0.8.1.
- A cell spec with a `reference_electrode` and no `cell_configuration` is published as a `HalfCellDevice` with two reference electrodes. State `cell_configuration` (`full_cell`, `half_cell` or `three_electrode_cell`) to avoid it. Planned for 0.8.1; every place that infers a half cell does so only when `cell_configuration` is empty, so stating it is enough.
- `ws.import_()` leaves out a property that a deposit states as text only, with `hasStringValue` and no number. Planned for 0.8.1; only the records rebuilt from a deposit lack the value, and the deposit itself keeps it.
- `battinfo.interop.import_bmgen_jsonld` reads steps only from a flat `@graph`, which bmgen does not write, so a real bmgen file imports as a test spec with no steps. Planned for 0.8.1; the importers are in preview.
- `load_publication_package()` recognises seven property classes and reads a cell spec's chemistry back as `unknown`. Planned for 0.8.1; the package's JSON-LD keeps every value, and only the objects rebuilt from it lose them.
- BattINFO writes its progress messages with `print()` rather than the `logging` module and raises built-in exception types, so a caller cannot silence its output through logging or catch its errors by one exception class. Both change in 0.9, since they touch every module.
- `battinfo.bundle_generated`, the model layer generated from the LinkML schema, has been edited by hand since it was generated, and nothing regenerates it; the record models in `battinfo` are the authoring surface. 0.9 regenerates it or retires it.

### Vocabularies and classes

- Material specs for sodium, sulfur, solid electrolytes such as LLZO and LPSCl, and other materials beyond Li-ion fail validation: `material_kinds.json` has no kind for them, and `semantic.material_kind_unknown` is an error under every policy. So Na-ion, Li-S and solid-state cells cannot be described down to their materials yet. Planned for 0.8.1, which adds the kinds the pinned ontologies already have classes for; the registry validates against the same vocabulary, so its copy is updated before that release.
- `typical_energy` is typed `StoredEnergy`, because the ontologies have no class for a typical energy, and an LNMO positive electrode is typed `MetalOxideElectrode`, because its own class is deprecated upstream with no replacement. The electrode's `@type` can move to a new class term once domain-electrochemistry publishes the class. `typical_energy` keeps `StoredEnergy`, because the v1 records context is frozen, until a v2 context.
- No property key holds a maximum C-rate. Give a current in A, or state a C-rate as `charging_c_rate` or `discharging_c_rate` in the conditions of the value it applies to.
- In the JSON-LD of materials and components, which uses the EMMO domain-battery context, numbers carry no datatype, so JSON-LD processors disagree on whether 76.0 is an integer or a double. Records under the v1 records context type them `xsd:double`.
- Not every quantity in a test protocol or a parameter set follows the full EMMO quantity pattern. Temperature conditions in test protocols and `ambient_temperature` in parameter sets are typed only `ConventionalProperty`, with no quantity class, and voltage limits in a test protocol can lack `ConventionalProperty`. The values and units are there. Cell specs, cells, tests, datasets, materials and components follow the full pattern. Planned for 0.8.1.

### Schemas

- From 0.8.0 a schema served under `https://w3id.org/battinfo/schema/` changes in place only in its descriptions, titles and examples ([identifier policy, section 11.1](https://github.com/BIG-MAP/BattINFO/blob/main/IDENTIFIER_POLICY.md#111-served-artifact-immutability)). Any other change, a new optional property included, needs a new versioned schema URL, and the layout of those URLs and what `schema_version` promises are defined in 0.9. Until then no 0.8.x release changes what a schema accepts.

### CLI batch path

- `battinfo push` stops with `FileExistsError` on its flat and sub-folder layouts. Use `battinfo batch upload`, the route that works. Planned for 0.8.2, since `battinfo push` is in development.
- `battinfo batch upload` and `battinfo push` upload only to the Zenodo sandbox, so an upload needs `--sandbox`; without it they stop before contacting Zenodo. They send a sandbox token: `--token`, else `ZENODO_SANDBOX_TOKEN`, else `zenodo_sandbox_token` in the config file (`battinfo config set zenodo_sandbox_token <token>`). Uploads to zenodo.org from the batch path come in 0.8.1, once a retry no longer carries the first upload's record id and the batch path reads the DOI from the deposit; to publish there now, use `ws.zenodo()` from `battinfo.workspace()`.
- Run `battinfo batch package` again before you retry `battinfo batch upload`: a retry of the same staging folder carries the record id of the first upload. The fix comes in 0.8.1.

### Dependencies

- The `processing` extra requires `batterydf[nda,excel,mat]>=0.2.0rc2,<0.3`, so it installs the batterydf 0.2.0 release candidate until batterydf 0.2.0 is published.
- `pyshacl`, which runs the SHACL shapes and is a core dependency, requires `rdflib` below 8 in its release 0.40.1, so battinfo can only be installed next to rdflib 7 until a pyshacl release allows rdflib 8.
- Python 3.15 is not supported yet. `requires-python` has no upper bound, so pip will still try to install battinfo on 3.15, and on Windows without a C compiler that install fails while building PyYAML, which has no wheels for Python 3.15 yet; the error asks for Microsoft Visual C++ 14.0 or greater. Use Python 3.11–3.14.
- The `tabular` extra requires pandas 3.0.5 or later and pyarrow 25 or later, so it cannot be installed into an environment held to pandas 2.
- CI tests Linux and Windows. macOS is not tested until 0.8.1 adds a macOS job.

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
