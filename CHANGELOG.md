# Changelog

All notable changes to BattINFO are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

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
- Total: 291 tests, all passing

---

## [0.1.0-alpha] — 2026-03-01 (initial alpha)

Initial alpha release. Core cell-descriptor validation, mapping, and publication workflows.
