# Cell Descriptor Stable Subset

## Purpose

This document defines the stable BattINFO cell-descriptor subset that is ready for use in real systems.

This subset is intended to be:
- versioned
- validated in CI
- mapped deterministically to JSON-LD
- safe for external integration

## Stable Status

Status: `stable-for-integration`

Source:
- `src/battinfo/data/profiles/cell-descriptor/profile.json`

The stable subset is the contract BattINFO expects real systems to rely on first.

## Stable Top-Level Fields

Stable top-level fields:
- `schema_version`
- `specification`
- `instances`
- `provenance`
- `comment`

## Stable `specification` Fields

Stable `specification` fields:
- `id`
- `manufacturer`
- `model`
- `format`
- `chemistry`
- `positive_electrode_basis`
- `negative_electrode_basis`
- `size_code`
- `property`
- `comment`

## Stable Common Modules

The following common modules are part of the stable subset:
- quantity object
- quantitative property maps
- instance references
- provenance object

These are currently governed through:
- `src/battinfo/data/profiles/cell-descriptor/profile.json`
- generated profile fragments under `src/battinfo/data/profiles/cell-descriptor/generated/`
- normative schema modules under `assets/schemas/`

## Deliberately Not Yet Declared Stable

The following deeper structures are supported but not yet declared part of the stable integration subset:
- `positive_electrode`
- `negative_electrode`
- `electrolyte`
- `separator`
- deeper material/component nesting under those structures

These may still evolve as the profile layer expands.

## Runtime Guarantees

For the stable subset, BattINFO currently guarantees:
- validation with `battinfo validate`
- deterministic JSON-LD rendering with `battinfo map --target domain-battery`
- schema/profile/mapping drift detection in CI
- packaged copies matching normative assets for the stable profile and mapping layer

## Change Policy

For the stable subset:
- breaking changes require a major version increment
- additive optional fields require at least a minor version increment
- semantic remapping of stable fields requires an explicit review and versioned change

## Review Fixtures

Primary fixtures for stable-subset review:
- `examples/cell-descriptors/minimal.example.json`
- `examples/cell-descriptors/a123-anr26650m1-b.example.json`

Generate review JSON-LD locally when needed instead of treating it as committed source data.


