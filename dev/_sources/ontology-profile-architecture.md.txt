# BattINFO / Domain-Battery Target Architecture

## 1. Purpose

This document defines the target architecture for BattINFO, `domain-battery`, and downstream consumers such as BDF.

The architecture is designed to meet these goals:
- `domain-battery` remains the source of semantic truth
- BattINFO remains the normative human-facing cell descriptor contract
- deterministic JSON-LD/RDF generation is preserved
- ontology, profile, schema, and code can scale without becoming independent competing sources of truth

## 2. Source-of-Truth Hierarchy

The hierarchy is strict:

1. `domain-battery`
   - canonical semantic ontology for battery-domain meaning
2. `battinfo.ttl`
   - application ontology / profile ontology that imports `domain-battery`
   - defines BattINFO-specific constraints and extensions
3. BattINFO profile artifacts
   - human-facing profile definitions derived from `battinfo.ttl`
   - generation inputs for schema and mapping behavior
4. Generated runtime artifacts
   - JSON Schema
   - JSON-LD mapping tables and contexts
   - packaged schema/data copies
5. Examples and tests
6. Python implementation

Code is not allowed to invent semantic policy that is not represented in the ontology/profile layer.

## 3. Repository Responsibilities

### 3.1 `domain-battery`

`domain-battery` is responsible for reusable battery-domain semantics:
- classes such as `BatteryCell`, `CylindricalBattery`, `LithiumIonBattery`
- relations such as `hasProperty`, `hasPositiveElectrode`, `hasNegativeElectrode`
- quantitative property classes
- unit alignment and imported measurement semantics
- SHACL shapes for core semantic validity where appropriate

`domain-battery` should contain terms that are domain concepts even if BattINFO is the first consumer.

### 3.2 BattINFO

BattINFO is responsible for the application layer:
- the normative human JSON contract
- the BattINFO application ontology (`battinfo.ttl`)
- application/profile constraints over `domain-battery`
- JSON Schema and mapping artifacts generated from the profile layer
- deterministic transformation from human JSON to JSON-LD/RDF
- examples, tests, CLI, and migration tooling

BattINFO should only define terms that do not belong in the reusable domain ontology.

### 3.3 BDF

BDF should not define an independent battery metadata contract.

BDF should consume:
- the BattINFO JSON contract
- the BattINFO profile artifacts
- the generated schema and semantic mapping behavior

## 4. Target BattINFO Layout

Target BattINFO layout:

- `battinfo.ttl`
  - BattINFO application ontology
  - imports `domain-battery`
  - declares BattINFO-specific extensions only

- `src/battinfo/data/profiles/cell-descriptor/`
  - profile definitions for the BattINFO cell descriptor
  - required/optional fields
  - cardinalities
  - controlled value sets
  - field-to-term bindings
  - extension policy

- `assets/mappings/domain-battery/`
  - normative mapping tables used to render ontology-aligned JSON-LD
  - reviewed and versioned

- `assets/schemas/`
  - generated or semi-generated JSON Schema artifacts for the human contract

- `src/battinfo/data/`
  - packaged copies of schemas and mapping assets
  - must remain byte-identical to normative source assets

- `src/battinfo/transform/json_to_jsonld.py`
  - renderer/orchestrator only
  - reads profile artifacts and mapping tables
  - should not embed policy except minimal fallback handling

- `tests/`
  - schema conformance
  - mapping table integrity
  - semantic output snapshots
  - extension policy gates

## 5. What Goes In `domain-battery` vs `battinfo.ttl`

Put a term in `domain-battery` if it is:
- a real battery-domain concept
- reusable outside BattINFO
- part of the semantic conceptual model

Put a term in `battinfo.ttl` if it is:
- specific to BattINFO authoring or workflow
- document/profile/application-layer behavior
- a controlled extension not appropriate for the core domain ontology

Examples:

- `domain-battery`
  - battery classes
  - electrode classes
  - chemistry classes
  - property classes
  - core object properties

- `battinfo.ttl`
  - explicit application/profile terms
  - profile-specific instance-linking policy if not suitable for `domain-battery`
  - compatibility bridge terms during migration

Promotion rule:
- if a BattINFO term becomes broadly reusable or conceptually core, move it into `domain-battery`

## 6. BattINFO Profile Design

The BattINFO cell descriptor profile should be the operational contract layer between ontology and human JSON.

It should define:
- top-level shape
- required minimal core
- allowed nested structures
- key naming policy (`snake_case`)
- quantity model rules
- controlled value bindings where needed
- which fields map to ontology classes vs annotation terms
- which fields are allowed BattINFO extensions

The profile is the place where semantic constraints become a human-facing contract.

## 7. Generated Artifacts

The following artifacts should be generated or derived from the profile layer wherever practical:

- `assets/schemas/cell-descriptor.schema.json`
- `assets/schemas/modules/common/*.json`
- `assets/schemas/modules/components/*.json`
- JSON-LD rendering tables
- profile reference tables in documentation
- packaged copies under `src/battinfo/data/...`

Generated artifacts must not become hand-maintained semantic sources of truth.

## 8. Mapping Strategy

Mapping behavior should be data-driven.

Use normative mapping tables for:
- entity type enrichment
  - `format`
  - `chemistry`
  - `positive_electrode_basis`
  - `negative_electrode_basis`
- quantitative property keys
- units
- allowed extension terms

Suggested mapping assets:

- `assets/mappings/domain-battery/entity_type_map.json`
- `assets/mappings/domain-battery/property_map.candidates.json`
- `assets/mappings/domain-battery/property_map.curated.json`
- `assets/mappings/domain-battery/unit_map.candidates.json`
- `assets/mappings/domain-battery/unit_map.curated.json`
- `assets/mappings/domain-battery/extension_policy.json`

## 9. Validation Stack

Validation should happen at three layers:

1. JSON shape validation
   - JSON Schema

2. Profile validation
   - required/optional fields
   - controlled value sets
   - semantic binding completeness

3. RDF/semantic validation
   - generated JSON-LD / RDF checked against ontology/profile expectations
   - SHACL where appropriate

This prevents JSON shape correctness from being mistaken for semantic correctness.

## 10. Extension Policy

BattINFO extensions are allowed, but they must be explicit and minimal.

Rules:
- prefer `domain-battery` terms first
- then `schema.org`
- then `prov:`, `rdfs:`, `skos:`, `dcterms:`
- only then use a BattINFO-specific term

Every allowed BattINFO extension should be listed in `extension_policy.json` with:
- term
- justification
- status
- migration intent

## 11. Change Workflow

Recommended workflow for semantic changes:

1. Decide whether the concept belongs in `domain-battery` or `battinfo.ttl`
2. Update ontology/profile sources
3. Regenerate derived artifacts
4. update examples
5. run schema/profile/mapping tests
6. cut BDF compatibility updates if needed

The reverse workflow is not allowed. Do not start with ad hoc code or schema edits and retrofit ontology meaning later.

## 12. Immediate Implementation Plan

Recommended next implementation sequence:

1. Create `battinfo.ttl`
   - import `domain-battery`
   - declare existing BattINFO-specific extension terms explicitly

2. Create `assets/mappings/domain-battery/entity_type_map.json`
   - move inline `format` / `chemistry` / electrode basis enrichments into data

3. Create `assets/mappings/domain-battery/extension_policy.json`
   - document the allowed extension layer

4. Refactor the JSON-LD transformer
   - load entity mapping and extension policy from data assets
   - keep transformation logic declarative

5. Add tests for mapping governance
   - no unapproved `battinfo:` terms in `domain-battery` output
   - required basis values must have entity mappings

6. Later, generate JSON Schema from the BattINFO profile layer
   - or introduce a generation pipeline if full generation is not immediately practical

## 13. Target End State

The target end state is:

- `domain-battery` defines the semantics
- `battinfo.ttl` defines the application/profile layer
- BattINFO JSON is the normative human authoring contract
- schema and mapping artifacts are generated or tightly derived
- BDF consumes BattINFO artifacts directly
- Python code renders and validates; it does not define semantics

This architecture keeps most maintenance in ontology/profile assets while preserving a practical human-facing JSON contract.

