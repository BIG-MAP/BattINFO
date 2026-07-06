# Changelog

All notable changes to BattINFO are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Fixed

- **The `ws.quickstart()` recipe runs again end to end.** `ws.add("cell", spec=<search
  hit>)` crashed with "Unknown field(s): _canonical_id=, type=" — a search hit carries
  index metadata, not authoring fields, and the stricter unknown-kwarg check (correctly)
  refused it. Hits are now resolved through the referenced-spec path, reusing the
  existing IRI; a plain-string `spec=` gets a one-line fix-it error
  (`spec = ws.search(...)[0]`). A new offline test executes the whole taught sequence
  (convert → search → add cell → add test → save) in CI so this seam cannot rot.
- **`ws` no longer crashes legacy Windows consoles.** User-facing prints carried `→` and
  `⚠️`, which raise `UnicodeEncodeError` on cp1252/cp437 stdout — `ws.convert()` died
  *after* a successful conversion. All printed strings are ASCII now, and a test forbids
  non-ASCII in ws.py print calls.

### Changed

- **`save_*` minting is now idempotent** (beta-hardening 3.3): a record saved without an
  `id`/`uid` mints its IRI deterministically from its natural identity key, using the same
  seeds as the workspace finalizers — so the api and workspace paths mint identical IRIs
  for identical identities, and re-running an identical ingest is a no-op
  (`status: exists`/`updated` with `content_changed: False`) instead of a duplicate corpus.
  Natural keys: cell-spec = manufacturer::model::format::chemistry::size_code;
  cell = cell_spec_id::serial::batch::name; test-spec = kind::name::version;
  test = cell::kind::protocol::name; dataset = cell::test::locator::name. Records with no
  distinguishing identity (e.g. a cell instance with no serial/batch/name) still mint
  randomly — distinct anonymous records never silently dedup. Pass an explicit `uid=` to
  reproduce the old always-random behaviour.

### Deprecated

- The retired `*Input` names import again as **deprecation shims** for one release:
  `CellSpecificationInput`, `CellInstanceInput`, `TestInput`, `DatasetInput`,
  `TestSpecInput`, `TestProtocolInput` resolve to their models with a
  `DeprecationWarning` naming the replacement (PEP 562), so downstream pinners get a
  migration message instead of an `ImportError`. The legacy keyword form
  `publish(cell_spec=..., ...)` also warns — call `publish_publication_package(...)`
  explicitly. The deprecation policy is now written down in CONTRIBUTING.md, and
  RELEASING.md gains a "sweep expiring deprecations" step.
- The `battinfo.publish` **submodule** moved to `battinfo._publish`, ending the
  function/module shadowing where importing the submodule silently rebound the
  `battinfo.publish` attribute from the function to the module. The documented
  surface (`from battinfo import publish`, `PublishResult`) is unchanged.

### Added

- **`ws.submit()` is resumable** (beta-hardening 3.5): every outcome is journaled to
  `.battinfo/submit-journal.jsonl` as it happens, and a record whose identical payload
  already succeeded in a previous run is skipped (`status: skipped_journal`) instead of
  re-POSTed — resuming an interrupted bulk submission re-sends only what is missing.
  Failed records are journaled but retried on resume; changed content re-submits.
  `ws.submit(resume=False)` bypasses the journal. (Transient-failure retry with
  exponential backoff already ships in `submit_publication_package`; HTTP connection
  pooling is deliberately deferred — stdlib-only HTTP, and the planned registry bulk
  endpoint is the right fix for per-request overhead.)
- **`battinfo.bulk_save_session(source_root)`** — a context manager that makes bulk
  ingests fast: the id→path map is scanned once per entity type instead of per save,
  every save keeps it current (so records saved in the batch resolve as references for
  later records), and the per-file fsync is skipped because a bulk batch is re-runnable.
  Measured on the 400-record benchmark (`scripts/bench_bulk_save.py`): 18 → 385
  records/s (21×); a 10k-record ingest completes in under half a minute.
  `Workspace.save()` and `save_batch` (Python + CLI) use it automatically.
- **Every emitted record's provenance block now carries `battinfo_version`** — the version
  of the battinfo library that wrote the record — so records are forensically attributable
  to a build. The stamp is applied at emission (model `to_record()` and the direct api.py
  record builders); an explicitly set value is preserved, so re-serialising another build's
  record does not falsify its origin. All record schemas (packaged and `assets/` sources,
  plus the cell-spec profile fragment) allow the new optional field. Downstream note: the
  registry's vendored schemas need a re-vendor + pin bump when this ships.
- `battinfo.AuthoringWorkspace` is exported by name (previously reachable only via the
  `battinfo.workspace(...)` factory); its docstring now points at the correct engine class.
  A new [Workspace authoring](docs/workspace-authoring.md) doc page mirrors
  `ws.quickstart()`, and QUICKSTART/README carry a "Which surface do I use?" table mapping
  the three entry points (authoring workspace, models + `publish`, `battinfo.Workspace`
  object-graph engine). The internal `WorkspaceManifest` in `workspace_state.py` is renamed
  `WorkspaceStateManifest`, ending the name clash with `local_workspace.WorkspaceManifest`.
- Every field of the five authoring models (`CellSpecification`, `CellInstance`, `Test`,
  `TestSpec`, `Dataset`) and `ProvenanceInfo` now carries a `Field(description=...)`,
  surfacing in `help()`, IDE hover, and `.model_json_schema()`. Descriptions note the flat
  authoring aliases (e.g. `title=` for `Dataset.name`, `kind=` for `test_type`). A test
  gate keeps new fields from shipping undocumented.

### Changed (interop sharp edges)

- `import_discovery_eln` accepts real `.eln` exports (ZIP archives wrapping the crate),
  not just an unpacked crate directory or a bare `ro-crate-metadata.json`.
- Importer JSON parse/read errors now name the offending file (shared
  `load_json_source` across the BDC, BPX, converter, discovery, and protocol importers).
- The aurora-unicycler importer surfaces a present-but-unparseable numeric field as a
  warning on the imported test spec instead of silently ignoring it.
- Batch imports that produce zero records from a real source say so in the package
  warnings instead of returning an empty result silently.

### Changed (validation errors aggregate and teach)

- Save/publish validation failures now report **every** error in one message instead of
  only the first, so a record with three problems is fixed in one pass, not three.
- Canonical record paths in error messages translate back to the authoring vocabulary
  (`cell_spec.cell_format` → `format=`, missing `provenance.source_type` → `source_type=`).
- Quantity-shape errors include a copy-pasteable example
  (`{"nominal_capacity": {"value": 0.0, "unit": "ah"}}`) and point at
  `battinfo properties show <name>` for the accepted units.
- A misspelled keyword argument on any of the five record models now raises a `TypeError`
  with a did-you-mean (`manufacture=` → "did you mean `manufacturer=`?") covering fields,
  aliases, and all spec property names, instead of a bare pydantic extra-field error.

### Changed (nothing accepted is silently dropped)

- `specs=` must be a mapping of property name → value; a list or scalar now raises a
  `TypeError` showing the expected shape (it used to be discarded without a word).
- Provenance kwargs accepted at construction (`source_name=`, `file_hash=`, `curated_by=`,
  `workflow_version=`, provenance `comment`) are now emitted by every record type's
  serializer and read back by `from_record` — previously four of the five serializers
  silently omitted them. All record schemas (assets + packaged copies) accept the full
  provenance field set; each schema's `required` list is unchanged. **Registry note:** the
  vendored schemas in battinfo-registry must be re-synced before records carrying the new
  optional fields will pass its gate.
- Passing a cell/cell-spec object positionally together with a conflicting `cell_id=`/
  `cell_spec_id=` kwarg now raises naming both ids; with a matching id the object is kept
  (it used to be silently discarded whenever the id kwarg was present).

### Changed (record format)

- Every emitted record now carries `schema_version: "0.2.0"`, stamped from a single
  `battinfo.bundle.SCHEMA_VERSION` constant used by the pydantic models, the dict-path
  record builders, and the interop importers. This deliberately supersedes **both** prior
  values: the original `"0.1.0"` (dict-path cell spec/material/component records) and the
  `"1.0.0"` that model-path records had silently picked up during the input-model
  consolidation. Reading a record preserves its stored version; only newly emitted records
  get the new stamp. Downstream consumers should accept `0.1.0`, `1.0.0`, and `0.2.0`.

### Changed (stop fabricating provenance and URLs)

- Records no longer invent `source_file: "manual.json"`: the optional provenance
  `source_file` is now absent unless you (or a real source path) provided it. The CLI
  `--source-file` options default to unset accordingly.
- Serializing a dataset without any URL now raises an actionable error naming
  `access_url` instead of emitting a fabricated `https://example.org/dataset/...`
  placeholder (the schema requires `dcat:accessURL`; a provenance `source_url` also
  satisfies it, and workspace/publication flows still derive it from the dataset path).
  Synthesized distributions likewise reuse real URLs only. Flow-specific handling:
  - the Zenodo package flow stamps the documented `https://zenodo.org/records/ZENODO_RECORD_ID`
    placeholder that `patch_zenodo_urls()` rewrites after upload (the old example.org
    fallback was never patched, publishing fake URLs in harvested bundles);
  - the tolerant BDC importer falls back source_urls → download_urls → a truthful
    `urn:battery-data-commons:record:{id}` catalog URN (with a warning);
  - the Discovery .eln importer uses the dataset's real archive URL;
  - `template_dataset()` exposes `access_url` as a visible replace-me example parameter.
- `source_type` remains schema-required, so save paths still apply the documented
  category defaults (cell spec: `datasheet`, instance/test/ws-dataset: `measurement`,
  dataset dict-path: `other`, test spec: `manual`) when unset — these are deliberate,
  documented defaults, no longer accompanied by a fake source file.

### Changed (breaking — authoring API)

- The per-record-type input classes are retired: the pydantic models are now both the
  canonical source of truth **and** the authoring input. Construct the model directly with the
  same field names you passed before and hand it to the matching `save_*` function.
  - `CellSpecificationInput` → `CellSpecification`
  - `CellInstanceInput` → `CellInstance`
  - `TestInput` → `Test`
  - `DatasetInput` → `Dataset`
  - `TestSpecInput` (and the `TestProtocolInput` alias) → `TestSpec`
- Each model accepts the flat authoring shape directly (e.g. `model_name`, `notes`,
  `source_type`, PyBaMM-style `experiment=[...]`) and normalizes it internally, so most call
  sites change only the class name.

### Added

- A dataset can now relate to multiple cells and tests via `related_cell_ids` /
  `related_test_ids` (previously a single cell/test reference silently dropped the extras).
- Test-spec artifacts are validated as structured `Artifact` objects on save (previously passed
  through unchecked), so a malformed artifact fails fast.

### Fixed

- Dataset `creators`/`funders`/`publisher` entries now preserve `orcid` and classify agents
  carrying an ORCID or given/family name as `Person` (the retired hand-builder passed these
  dicts through verbatim; the model's canonicalizer was silently dropping the ORCID and
  defaulting people to `Organization`).
- `CellInstance.expires_at` is converted to a Unix timestamp at save time, exactly like
  `manufactured_at` (ISO strings previously reached stored records unconverted).
- Provenance `retrieved_at` now accepts ISO datetime strings on every record builder (only the
  test-spec builder converted them before), preserves epoch zero, and raises on an unparseable
  value instead of silently substituting the current time.
- A flat string `citation=` kwarg on `Dataset` is routed to provenance even when an explicit
  `source=` is also given (it previously leaked into the bibliographic `citations` list); an
  already-set `source.citation` wins. List/dict citation values remain bibliographic.
- Timezone-naive timestamps (a bare ISO date such as `"2022-01-15"`, or a time with no offset)
  are now anchored to UTC before conversion. Saved record timestamps
  (`manufactured_at` / `started_at` / `ended_at` / `created_at`) were previously interpreted in
  the authoring machine's local timezone, making the same input non-reproducible across machines;
  an explicit offset is still respected.
- Datasets always emit the schema-required `access_url` (falling back to the provenance URL, then
  a stable id-derived value), so a dataset built directly from the model can no longer serialize
  into a schema-invalid record.

## [0.7.0] — 2026-06-19

First publication of the `battinfo` **Python package** (library + CLI) to PyPI.
The package, CLI, and OWL application ontology now share a single version line,
continued from the prior ontology releases (… 0.5.0, 0.6.0 → **0.7.0**).

### Packaging & release

- First PyPI release of `battinfo` (`pip install battinfo`); requires Python 3.11+.
- Unified the package and ontology on one version; `battinfo.ttl` `owl:versionIRI`/`owl:versionInfo` bumped to 0.7.0.
- Single-sourced the version from `battinfo.__version__` (pyproject `dynamic`), so it can no longer drift across files.
- Added a PyPI trusted-publishing (OIDC) release workflow, `RELEASING.md`, and a `twine check` step in CI.
- Redesigned CI into a publication-grade suite (lint/type, matrix tests, packaging, security/pip-audit + CodeQL, docs build) with the test suite as a pre-publish gate.

### Reliability

- JSON-LD validation, URDNA2015 normalization, and RDF materialization now run **fully offline**. The EMMO domain-battery and battinfo records contexts are resolved from bundled copies for **both** rdflib and PyLD (previously only PyLD/URDNA2015 used the local EMMO copy, and rdflib still fetched contexts over the network). Publishing or validating a record no longer requires a live network connection.
- The test suite is socket-blocked (`pytest-socket`) to enforce offline operation; this also cut test wall-clock roughly 6× by removing context-fetch timeouts.

### Ontology

- Upgraded EMMO dependency pins: domain-battery 0.18.8 → **0.19.0** (introduces `BatterySpecification` class hierarchy)
- Bundled EMMO context patched with 6 new 0.19.0 terms: `BatterySpecification`, `BatteryCellSpecification`, `BatteryModuleSpecification`, `BatteryPackSpecification`, `BatterySystemSpecification`, `BatterySystem`

### Semantic type migration (breaking change for downstream JSON-LD consumers)

- **Cell-type records** (`@type`): replaced EMMO physical stacking + `schema:ProductModel` with `BatteryCellSpecification` (domain-battery 0.19.0 term; subclass of `emmo:Description`)
  - EMMO physical type stacking (format + chemistry + electrode basis) moved to an `isDescriptionFor` anonymous node on the specification
  - `schema:category` and `schema:material` removed (semantically incorrect on an information entity)
- **Cell-instance records**: removed `schema:IndividualProduct`; added `hasDescription` (EMMO) alongside retained `schema:isVariantOf` (schema.org) for backward compatibility
- `bundle.py` bundle loader updated to detect both old (`schema:CreativeWork`) and new (`BatteryCellSpecification` with `schema:about`) cell-specification node formats, and to read `hasDescription` or `schema:isVariantOf` for the cell-type back-reference

### Previous entries (domain-battery 0.18.7 → 0.18.8 cycle)

- Upgraded EMMO dependency pins: domain-battery 0.18.7 → **0.18.8**, domain-electrochemistry 0.33.0 → **0.34.0**
- Bundled EMMO domain-battery context refreshed (4,900+ terms; enables offline JSON-LD processing)
- Added `.tools/quality/check_emmo_versions.py` — reports whether `owl:imports` IRIs in `battinfo.ttl` match the latest upstream releases

### Semantic mapping

- `property_map.curated.json` expanded from 38 → 47 curated entries; version bumped to 0.3.0
  - New: `NominalEnergy`, `typical_energy` (legacy alias → NominalEnergy), `CalendarLife`, `InitialCoulombicEfficiency`, `DCInternalResistance`, `ACInternalResistance`, `SelfDischargeRate`, `StateOfHealth`
  - All IRIs verified against domain-battery 0.18.8 and domain-electrochemistry 0.34.0
- `entity_type_map.json` updated; version bumped to 0.2.0
  - Added chemistry: `na-ion` → `SodiumIonBattery`
  - Added negative electrode: `silicon-graphite` → `SiliconGraphiteElectrode`, `hard-carbon` → `HardCarbonElectrode`
  - Fixed `lco` battery class: was `LithiumIonBattery` (generic), now `LithiumIonCobaltOxideBattery`
  - Fixed `nca`: dropped unresolvable `node_type` reference to non-existent `LithiumNickelCobaltAluminiumOxideElectrode`

### JSON-LD / RDF correctness

- **Resolver JSON-LD** (`_resolver_jsonld`): removed all undefined `battinfo:` terms
  - Cell-type `@type` now uses full EMMO stacking (format + chemistry + electrode basis) plus `schema:ProductModel`
  - Replaced `battinfo:chemistry` / `battinfo:format` with EMMO `@type` stacking; information is now in the type graph, not as bare string predicates
  - Replaced `battinfo:sizeCode` → `schema:size`
  - Cell instance: `battinfo:BatteryCellInstance` → `["BatteryCell", "schema:IndividualProduct"]`; `battinfo:typeId` → `schema:isVariantOf`; `battinfo:serialNumber` → `schema:serialNumber`; `battinfo:hasDataset` → `schema:workExample`
  - Test protocol: `battinfo:BatteryTestProtocol` → `["BatteryTest", "schema:HowTo"]`; `battinfo:testKind` → `schema:category`
  - Test: `battinfo:BatteryCellTest` → `BatteryTest`; `battinfo:aboutCell` → `schema:object`; `battinfo:usesTestProtocol` → `schema:instrument`; `battinfo:hasDataset` → `schema:result`
  - Dataset: `battinfo:aboutCell` / `battinfo:aboutTest` → `schema:about`
- **Descriptor JSON-LD**: removed `schema:valueReference` misuse; each ConventionalProperty node now follows the canonical EMMO single-value pattern
- **Descriptor JSON-LD**: fixed null `@id` bug — when a specification dict has no `id` field, `@id` was silently set to `null`, causing URDNA2015 normalization failures; `@id` is now only emitted when the value is non-null
- **Cell instance `@type`**: now always carries both `BatteryCell` (EMMO scientific type) and `schema:IndividualProduct` (schema.org product type)
- **URDNA2015**: offline EMMO context fallback wired — JSON-LD normalization no longer requires a live network connection
- **rdflib DeprecationWarning**: internal rdflib 7.x warnings no longer surface as false JSON-LD parse errors under `-W error`
- **`publication.py` `PROPERTY_TYPE_MAP`**: `battinfo:RatedEnergy` corrected to `RatedEnergy` (EMMO term); `battinfo:TypicalEnergy` replaced by `NominalEnergy`; added `nominal_energy` entry

### Schemas

- `cell-canonical.schema.json` SpecSet: added `calendar_life`, `nominal_energy`, `dc_internal_resistance`, `ac_internal_resistance`, `self_discharge_rate`, `initial_coulombic_efficiency`, `state_of_health`

### Python API

- `authoring.py`: full rewrite with docstrings on all 8 exported functions (`properties`, `construction`, `source`, `material`, `bom`, `electrode`, `electrolyte_recipe`, `separator_spec`, `cell_description`)
- Dead code removed: `CORE_PROPERTY_PREDICATES` dict and `_property_predicate()` function in `json_to_jsonld.py` (never called)
- `publish()` high-level API: `destination="local"`, `destination="registry"`, `destination="battery-genome"` paths implemented and tested
- `publish_record()` / `save_record()` low-level API: dry-run, upsert, and duplicate-policy modes tested
- Added `py.typed` marker (PEP 561)

### Validation

- Publication validation: `schema:about` reference check now correctly scoped to `@graph` publication packages only; standalone resolver documents may carry cross-document references without triggering a false `reference_missing_node` error

### Tests

- Added `tests/test_authoring.py`: 50 tests covering all `battinfo.authoring` exported functions
- Added entity type mapping tests in `test_mapping_governance.py`: na-ion, LCO, NCA (no node_type), silicon-graphite, hard-carbon
- `test_publish.py` expanded: resolver JSON-LD correctness, `schema:valueReference` absence, cell instance dual `@type`, `publish()` local/registry/battery-genome destinations, `save_record()` lifecycle
- Suite total at release: 938 tests, all passing on Python 3.11/3.12 (Linux + Windows)

---

## [0.1.0-alpha] — 2026-03-01

Initial internal pre-release. Core cell-descriptor validation, mapping, and publication workflows.
