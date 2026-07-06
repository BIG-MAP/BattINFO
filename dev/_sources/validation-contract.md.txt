# BattINFO Validation Contract

This document defines the validation behavior that consumers can rely on for the supported BattINFO scope.

## Supported Entry Points

Core validation entry points:

- `battinfo validate`
- `battinfo save ... --validate`
- `battinfo publish ... --validate`
- `battinfo index build --validate`
- `battinfo.validate.validate_json(...)`
- `battinfo.validate.validate_record(...)`
- `battinfo.validate.validate_publication(...)`

## Policy Names

BattINFO currently exposes these named validation policies:

- `default`
- `strict`
- `publisher`
- `ingest`

Policy semantics:

- `default`: schema and references are errors; semantic issues default to warnings.
- `strict`: schema, references, and semantic issues are errors.
- `publisher`: publisher-oriented validation with semantic and publication checks as errors.
- `ingest`: schema remains strict while semantic and reference issues can remain warnings during staged cleanup.

## Issue Model

Structured validation issues expose these fields:

- `code`
- `severity`
- `path`
- `message`
- `hint`
- `validator`
- `resource_type`
- `profile`

Severity values:

- `error`
- `warning`

Representative issue codes:

- `schema.required`
- `schema.format.uri`
- `schema.format.date_time`
- `schema.profile_unknown`
- `reference.missing`
- `reference.type_mismatch`
- `semantic.short_id_mismatch`
- `semantic.temporal_order_invalid`
- `publication.distribution_url_invalid`
- `publication.jsonld_parse_error`

## CLI Contract

`battinfo validate` supports:

- `--format text`
- `--format json`

Text mode:

- emits a human-readable pass/fail summary
- includes warnings when validation succeeds with non-fatal issues

JSON mode emits a machine-readable payload with:

- `ok`
- `mode`
- `policy`
- `profile`
- `source_root`
- `issue_count`
- `error_count`
- `warning_count`
- `errors`
- `issues`

Example issue object:

```json
{
  "code": "schema.format.uri",
  "severity": "error",
  "path": "dataset.url",
  "message": "'not-a-uri' is not a 'uri'",
  "hint": null,
  "validator": "format",
  "resource_type": "dataset",
  "profile": null
}
```

Exit codes:

- `0` when no error-severity issues are present
- `1` when one or more error-severity issues are present

## Current Boundary

Reference validation is supported against repository-style source trees through `source_root`.

This is sufficient for the core scope, but it is not yet the long-term scalability model for larger external registries or snapshots.

