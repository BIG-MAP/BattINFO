# Battery Descriptor Standard (Normative v1.0-draft)

## 1. Purpose

This document defines the single normative JSON contract for battery-cell metadata shared across BattINFO and BDF.

The objective is:
- one canonical human-facing schema
- one validation contract
- deterministic downstream conversion to JSON-LD/RDF

Source-of-truth order for the current transition state:
- `domain-battery`
- `ontology/battinfo.ttl`
- `src/battinfo/data/profiles/battery-descriptor/profile.json`
- `assets/schemas/...`
- implementation code

## 2. Normative Source

Normative schema source:
- `assets/schemas/battery-descriptor.schema.json`
- `assets/schemas/modules/common/*.json`
- `assets/schemas/modules/components/*.json`

Profile source:
- `src/battinfo/data/profiles/battery-descriptor/profile.json`
- `src/battinfo/data/profiles/battery-descriptor/generated/*.json`

Packaged runtime copy (must be identical):
- `src/battinfo/data/schemas/battery-descriptor.schema.json`
- `src/battinfo/data/schemas/modules/common/*.json`
- `src/battinfo/data/schemas/modules/components/*.json`

## 3. Canonical Record Shape

Top-level object:
- `schema_version` (required)
- `specification` (required)
- `instances` (optional)
- `provenance` (optional)
- `comment` (optional)

Required minimal `specification` core:
- `id`
- `manufacturer`
- `model`
- `format`
- `chemistry`
- `positive_electrode_basis`
- `negative_electrode_basis`

All deeper details (electrodes, electrolyte, separator, quantities, instance references) are optional extensions on top of this minimal core.

Stable-for-integration subset:
- see `battery-descriptor-stable-subset.md`

## 4. Naming and Quantity Conventions

- Human layer naming uses `snake_case`.
- Quantities are represented as objects aligned to schema.org `QuantitativeValue` conventions with snake_case keys:
  - `value`
  - `min_value`
  - `max_value`
  - `typical_value`
  - `unit` (preferred)
  - `unit_text` (allowed when needed)
- Units should follow Pint-compatible strings where practical.

## 5. Validation and Review Artifacts

Primary review examples:
- `assets/examples/battery-descriptors/minimal.example.json`
- `assets/examples/battery-descriptors/extended.example.json`
- `assets/examples/battery-descriptors/a123-anr26650m1-b.example.json`

Policy:
- Every example above must validate against the normative schema.
- Packaged schema copies must remain byte-identical to normative source files.
- Packaged profile and mapping copies must remain byte-identical to normative source assets.

## 6. Change Policy

- The schema is intentionally forward-extensible through optional fields and nested component blocks.
- Breaking changes to required fields or semantics require a major version increment.
- Non-breaking additions (optional fields) require at least a minor version increment.
