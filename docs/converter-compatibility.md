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
  - coin-cell case / lid / can / spring / spacer into `specification.coin_hardware`
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

## Next Steps

- add more golden fixtures from BattINFO Converter
- expand converter procedure import beyond the current rated-capacity graph shape
- expand canonical BattINFO authoring helpers for richer component provenance
- keep the canonical `domain-battery` export stable and grow the
  `converter-compatible` export only as an explicit migration surface
