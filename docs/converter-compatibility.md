# Converter Compatibility

## Purpose

This document defines the first BattINFO-side integration seam for tools such as
BattINFO Converter that already emit BattINFO-flavored JSON-LD.

The goal is not to replace those tools. The goal is to let BattINFO act as the
canonical validation, authoring, and export layer while preserving compatibility
with early-adopter tooling.

## Current Strategy

BattINFO now includes an initial converter import adapter:

- Python API:
  - `battinfo.import_converter_jsonld(...)`
  - `battinfo.import_converter_jsonld_record(...)`
  - `battinfo.import_converter_package(...)`
- implementation:
  - `src/battinfo/interop/converter.py`

The adapter currently targets the BattINFO detailed cell descriptor contract
rather than trying to preserve the converter's raw ontology-path structure.

BattINFO now also supports a second JSON-LD export target for transition work:

- `battinfo.transform.to_jsonld(record, target="converter-compatible")`

This is intentionally separate from the canonical BattINFO `domain-battery`
export so the human-first descriptor model can stay clean while early-adopter
tooling migrates onto the BattINFO package.

## Supported Checkpoint

The current supported BattINFO-side checkpoint for converter integration is:

- import converter coin-cell JSON-LD into linked BattINFO objects with
  `battinfo.import_converter_package(...)`
- add the imported objects directly to `Workspace`
- save canonical BattINFO `cell-type`, `cell-instance`, `test-protocol`, and
  `test` records from those imported objects
- emit either canonical `domain-battery` JSON-LD or
  `converter-compatible` JSON-LD from the imported detailed descriptor record

This is the intended stopping point for the current interop phase. It is enough
to let BattINFO act as the canonical Python package underneath converter-style
tooling without requiring the converter to rewrite its user-facing workflow yet.

## What The Adapter Does Today

- accepts BattINFO Converter coin-cell JSON-LD
- maps the export into a BattINFO detailed descriptor record
- can materialize a linked BattINFO object package suitable for `Workspace.add(...)`
- preserves a physical cell instance reference when `schema:productID` is present
- extracts rated-capacity procedure graphs into linked BattINFO `test-protocol`
  and `test` records when the converter JSON-LD includes those structures
- maps:
  - positive electrode
  - negative electrode
  - electrolyte
  - separator
  - coin-cell case / lid / can / spring / spacer into `specification.housing`
    (the legacy `coin_hardware` dict is retired and auto-migrated into `housing`)
  - coin-cell size code when it can be inferred from the case block
  - assembly sequence into `specification.construction.assembly_sequence`
  - component provenance where the converter exposes manufacturer / supplier / product identifiers
- records lossy areas as warnings and comments instead of silently dropping them

## Current Lossy Areas

The current implementation still does not cover all converter concepts. The main
remaining lossy areas are:

- converter-specific procedure/test fragments that should become linked BattINFO
  test-protocol and test records beyond the currently supported rated-capacity
  procedure shape
- converter flows that also carry datasets or measurement files; the current
  import checkpoint stops at descriptor, instance, protocol, and test objects
- ontology-native terms that do not yet have a stable BattINFO authoring-side
  equivalent

## Why This Direction

This keeps the canonical BattINFO authoring surface clean:

- BattINFO remains human-first at the authoring layer
- BattINFO Converter can become a client of the BattINFO package
- compatibility work happens in a controlled adapter layer
- schema growth is driven by real imported concepts that prove useful

## Round-Trip Status (canonical coin-cell model, 2026-06)

The coin-cell canonical model work (see [coincell-canonical.md](coincell-canonical.md))
brought the integration seam to a verified checkpoint:

- **Lossless converter round-trip.** `import_converter_package(reference) ->
  to_jsonld(..., target="converter-compatible")` reproduces the converter's own
  reference output (`coincell_jsonld_result.json`, Release 3.2.0) with **zero
  property-node loss**. Guarded by `tests/test_coincell_canonical_roundtrip.py`.
- **Two views over one model.** The same imported/authored record exports either as
  the canonical `domain-battery` JSON-LD (dimensionally-correct `AreicCapacity` /
  `DischargingSpecificCapacity`, electrode-level `hasProperty`, `hasProperty` +
  measured/conventional co-type) or as `converter-compatible` JSON-LD (legacy
  `RatedCapacity` overload, `hasMeasuredProperty`) for byte-level converter parity.
- **"Converter imports battinfo" direction proven.** A coin cell authored with the
  BattINFO authoring helpers (`material()` / `electrode()` / `separator_spec()` /
  `electrolyte_recipe()` / `cell_description()`) exports straight to converter-shaped
  JSON-LD — the path a future BattINFO Converter would call instead of its own
  path-walking engine.

### Recommended integration path for BattINFO Converter

```python
import battinfo as bi
from battinfo.transform import to_jsonld

spec = bi.cell_description(...)          # build from the converter's Excel inputs
record = {"schema_version": "1.0.0", "specification": spec.to_json()}
jsonld = to_jsonld(record, target="converter-compatible")
```

The only converter-side work remaining is the Excel-schema → `cell_description(...)`
mapping; the export engine and ontology mappings now live in BattINFO.

## Next Steps

- add the Excel-schema → BattINFO authoring adapter so the converter can delegate
  conversion end to end
- expand converter procedure import beyond the current rated-capacity graph shape
- publish `RatedProperty` in domain-battery, then flip
  `PENDING_CO_TYPE_AVAILABLE["RatedProperty"]` so normalized rated capacities emit
  `[AreicCapacity, RatedProperty]`
- keep the canonical `domain-battery` export stable and grow the
  `converter-compatible` export only as an explicit migration surface
