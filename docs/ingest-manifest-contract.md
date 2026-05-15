# Ingest Manifest Contract

`battinfo.ingest.json` is the folder-local manifest for the `battinfo ingest ...`
workflow.

Purpose:
- declare the typed subject being ingested
- point that subject to a curated reusable type record
- provide the minimum publication metadata needed for repeatable ingest
- configure folder scanning rules for attached files

Normative schema:
- [ingest-manifest.schema.json](/c:/Users/simonc/Documents/Github-local/battery-genome/BattINFO/assets/schemas/ingest-manifest.schema.json)

Packaged runtime copy:
- [ingest-manifest.schema.json](/c:/Users/simonc/Documents/Github-local/battery-genome/BattINFO/src/battinfo/data/schemas/ingest-manifest.schema.json)

## Scope

This manifest is not the source of truth for reusable type definitions.

Use it for:
- one operational ingest folder
- one typed instance-like resource
- file discovery and publication defaults

Do not use it for:
- curated `cell-type` authoring
- editing canonical registry output
- replacing the source folder itself

## Required fields

- `resource_type`
  - current allowed value: `cell-instance`
- `type_record`
  - path to the curated reusable type record

## Optional fields

- `resource_iri`
  - preserved canonical IRI for the ingested resource when already assigned
- `resource_name`
  - human-facing instance label used as the default generated serial/name
- `workspace_id`
  - registry workspace id used during bundle/publish
- `publisher_id`
  - publisher id used during bundle/publish
- `source_version`
  - submission version string written into generated workspace/package state
- `license`
  - default dataset license
- `rules`
  - file discovery and filename-to-test-kind inference overrides

## Rules object

`rules` currently supports:

- `photo_glob`
  - string or string array
  - default:
    - `image/photo/*.jpg`
    - `image/photo/*.jpeg`
    - `image/photo/*.png`
- `timeseries_glob`
  - string or string array
  - default:
    - `timeseries/raw/*.csv`
- `test_kind_from_filename`
  - object mapping lowercase filename tokens to BattINFO test kinds
  - default:
    - `rate -> rate_capability`
    - `ici -> ici`
    - `capacity -> capacity_check`

## Minimal example

```json
{
  "resource_type": "cell-instance",
  "type_record": "battinfo-records/records/cell-type/google--g20m7--2025/record.json"
}
```

## Practical example

```json
{
  "resource_type": "cell-instance",
  "type_record": "battinfo-records/records/cell-type/google--g20m7--2025/record.json",
  "resource_iri": "https://w3id.org/battinfo/cell/15qn-rpd4-xhy7-kx2q",
  "resource_name": "google--g20m7--2025--15qnrp",
  "workspace_id": "google-g20m7-instance-demo",
  "publisher_id": "demo-lab",
  "source_version": "2026-04-10",
  "license": "CC-BY-4.0",
  "rules": {
    "photo_glob": [
      "image/photo/*.jpg",
      "image/photo/*.jpeg",
      "image/photo/*.png"
    ],
    "timeseries_glob": [
      "timeseries/raw/*.csv"
    ],
    "test_kind_from_filename": {
      "rate": "rate_capability",
      "ici": "ici",
      "capacity": "capacity_check"
    }
  }
}
```

## Operational rule

For routine use:
- users edit the ingest folder and `battinfo.ingest.json`
- BattINFO generates the `Workspace`
- users do not treat the generated workspace as the primary long-term source by default

## Current implementation boundary

The manifest contract is designed to expand to other typed resource kinds, but the
current ingest engine only implements:

- `cell-instance`

Additional `resource_type` values should only be added when the ingest engine and
its downstream record-generation logic actually support them.
