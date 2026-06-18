# Cell Descriptor Integration

## Purpose

This document describes how another system should integrate with the BattINFO cell descriptor today.

The intended consumer is a system such as BDF or any other service that wants:
- validation of battery metadata
- deterministic JSON-LD rendering
- a stable subset that can be relied on operationally

## What To Consume

A consuming system should treat these assets as the integration package:

- profile:
  - `src/battinfo/data/profiles/cell-descriptor/profile.json`
- generated profile fragments:
  - `src/battinfo/data/profiles/cell-descriptor/generated/*.json`
- normative schema:
  - `assets/schemas/cell-descriptor.schema.json`
  - `assets/schemas/modules/common/*.json`
  - `assets/schemas/modules/components/*.json`
- mapping assets:
  - `assets/mappings/domain-battery/entity_type_map.json`
  - `assets/mappings/domain-battery/property_map.candidates.json`
  - `assets/mappings/domain-battery/property_map.curated.json`
  - `assets/mappings/domain-battery/unit_map.candidates.json`
  - `assets/mappings/domain-battery/unit_map.curated.json`
  - `assets/mappings/domain-battery/extension_policy.json`

## Validation Workflow

Validate a descriptor with:

```powershell
python -m battinfo.cli validate examples/cell-descriptors/minimal.example.json
```

Or, if using the installed CLI entrypoint:

```powershell
battinfo validate examples/cell-descriptors/minimal.example.json
```

Expected behavior:
- descriptor validation uses the `cell-descriptor` profile by default
- success means shape-level conformance to the current BattINFO descriptor schema

## Mapping Workflow

Render a descriptor to domain-battery JSON-LD with:

```powershell
battinfo map examples/cell-descriptors/minimal.example.json --target domain-battery --out minimal.domain-battery.jsonld
```

Expected behavior:
- output is deterministic for the stable subset
- output uses:
  - `schema.org` for generic metadata
  - `domain-battery` / `EMMO` for battery-specific semantics

## Stable Subset Expectation

A consuming system should initially rely only on the stable subset documented in:
- `docs/cell-descriptor-stable-subset.md`

If a consumer wants deeper nested structures such as detailed electrodes or electrolyte composition, those should currently be treated as supported but still evolving.

## Review Fixtures

Recommended integration fixtures:
- `examples/cell-descriptors/minimal.example.json`
- `examples/cell-descriptors/a123-anr26650m1-b.example.json`

Generate local JSON-LD review outputs as needed with:
- `battinfo map examples/cell-descriptors/minimal.example.json --target domain-battery --out minimal.domain-battery.review.jsonld`
- `battinfo map examples/cell-descriptors/a123-anr26650m1-b.example.json --target domain-battery --out a123-anr26650m1-b.domain-battery.review.jsonld`

## Consumer Guidance

Consumers should:
- validate BattINFO examples directly
- avoid inventing a parallel schema for the stable subset
- consume the profile and mapping assets rather than copying semantic rules into code
- treat generated profile fragments as the first line of schema/profile conformance checking

## Current Limitations

Current repo-side success state does not yet include:
- full schema generation from the profile layer
- cross-repo BDF cutover
- full semantic governance for every deep nested component block

Those are the next-step items beyond the current stable integration state.


