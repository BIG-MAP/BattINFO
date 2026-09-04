# Guarantees

What the infrastructure promises, and the interfaces you can build against —
three contracts on one page, each for a different reader. Building a platform
or registry **on** BattINFO: start with [the infrastructure
contract](#the-infrastructure-contract). Integrating validation into a
pipeline: [the validation contract](#validation-contract). Feeding bulk data
in from a folder of files: [the ingest manifest
contract](#ingest-manifest-contract).

## The infrastructure contract

This page is for the person deciding whether to *build on* BattINFO: what the
guarantees are, where they are enforced, and what breaks loudly instead of
silently. Everything here is backed by tests or CI gates in this repo or the
registry.

### Records are versioned

Every canonical record carries `schema_version` (currently `0.2.0`, a single
module-level constant). The registry's publish gate validates against pinned,
vendored copies of the same schemas and **flags unknown versions** rather than
guessing. Changes to record shape are CHANGELOG entries, never silent.

Three versions exist in the wild, and consumers should accept all three:

| `schema_version` | What it means |
|---|---|
| `0.1.0` | The original record shape; records published before the 0.2.0 consolidation still carry it |
| `1.0.0` | An interim stamp used briefly before the numbering was consolidated |
| `0.2.0` | The current shape: snake_case keys throughout, `properties` (ex `specs`), organizations use `same_as` |

The differences are additive/renaming only — no field changed meaning. New
records always stamp the current version; old records validate against the
same schemas (the keys they use are all still accepted).

### Records are attributable

Every emitted record's provenance block carries `battinfo_version` — the
library build that wrote it. A malformed record found in a corpus two years
from now is forensically traceable to its producer. Explicitly set values are
preserved, so re-serialising another build's record never falsifies origin.

### Identifiers are deterministic

Records saved without an explicit `uid` mint their IRI from the record's
natural identity key (for a cell spec: manufacturer :: model :: format ::
chemistry :: size code), using the same seeds in every authoring path.
Consequences you can rely on:

- re-running an identical ingest is a **no-op**, never a duplicate corpus;
- the workspace and `save_*` paths mint **identical IRIs** for identical
  identities (tested);
- records with no distinguishing identity still mint randomly — two anonymous
  but physically distinct cells never silently merge.

Governance of the IRI space itself is written down in the
[identifier policy](https://github.com/BIG-MAP/BattINFO/blob/main/IDENTIFIER_POLICY.md).

### One schema contract, three consumers

The canonical JSON Schemas in `src/battinfo/data/schemas/` are enforced in
three places, each with a CI gate against drift:

| Consumer | Mechanism | Drift gate |
|---|---|---|
| `battinfo validate` / `save_*` | jsonschema at save/publish | the test suite |
| Registry publish gate | vendored schemas, fails closed on unknown record types | `schema-drift` CI job pinned to a BattINFO commit |
| [battinfo.org/validate](https://battinfo.org/validate) | vendored schemas compiled with Ajv | web CI: sync check + 103-record agreement corpus |

The same record gets the same structural verdict in all three.

### Bulk operations are safe to automate

- `bulk_save_session` ingests ~400 records/s; a 10k-record ingest takes under
  half a minute and is re-runnable without duplicates.
- `ws.submit()` journals every outcome and resumes interrupted batches,
  re-sending only what is missing; transient registry failures retry with
  exponential backoff.
- Submission content conflicts return a **structured 409** naming the existing
  record, not a bare string.

### Deprecations are announced

Public API removals go through one release of `DeprecationWarning` naming the
replacement — never straight to `ImportError`. The policy lives in
[CONTRIBUTING](https://github.com/BIG-MAP/BattINFO/blob/main/CONTRIBUTING.md);
expiring shims are swept at each release.

## Validation contract

This document defines the validation behavior that consumers can rely on for the supported BattINFO scope.

### Supported Entry Points

Core validation entry points:

- `battinfo validate`
- `battinfo save ... --validate`
- `battinfo publish ... --validate`
- `battinfo index build --validate`
- `battinfo.validate.validate_json(...)`
- `battinfo.validate.validate_record(...)`
- `battinfo.validate.validate_publication(...)`

### Policy Names

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

### Issue Model

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
- `semantic.electrode_holders_mixed` (with `semantic.electrode_role_expected` /
  `semantic.electrode_polarity_expected`: the electrode holders disagree with the
  cell configuration — see [Electrodes](records/half-cells.md))
- `publication.distribution_url_invalid`
- `publication.jsonld_parse_error`

### CLI Contract

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

### Current Boundary

Reference validation is supported against repository-style source trees through `source_root`.

Every `*_id` field on a record body resolves to a record of one expected type, and a reference that resolves to the wrong type is `reference.type_mismatch` rather than a pass. The distinctions the checks enforce are meaningful ones: `cell_instance.cell_spec_id` must be a `cell-spec`, while `cell_instance.working_electrode_id` / `counter_electrode_id` must be `electrode` records — the built batch, not the `electrode-spec` design, which the cell spec already links.

This is sufficient for the core scope, but it is not yet the long-term scalability model for larger external registries or snapshots.

## Ingest manifest contract

`battinfo.ingest.json` is the folder-local manifest for the `battinfo ingest ...`
workflow.

Purpose:
- declare the typed subject being ingested
- point that subject to a curated reusable type record
- provide the minimum publication metadata needed for repeatable ingest
- configure folder scanning rules for attached files

Normative schema: `assets/schemas/ingest-manifest.schema.json`

Packaged runtime copy: `src/battinfo/data/schemas/ingest-manifest.schema.json`

### Scope

This manifest is not the source of truth for reusable type definitions.

Use it for:
- one operational ingest folder
- one typed instance-like resource
- file discovery and publication defaults

Do not use it for:
- curated `cell-spec` authoring
- editing canonical registry output
- replacing the source folder itself

### Required fields

- `resource_type`
  - current allowed value: `cell-instance`
- `type_record`
  - path to the curated reusable type record

### Optional fields

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

### Rules object

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

### Minimal example

```json
{
  "resource_type": "cell-instance",
  "type_record": "battinfo-records/records/cell-spec/google--g20m7--2025/record.json"
}
```

### Practical example

```json
{
  "resource_type": "cell-instance",
  "type_record": "battinfo-records/records/cell-spec/google--g20m7--2025/record.json",
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

### Operational rule

For routine use:
- users edit the ingest folder and `battinfo.ingest.json`
- BattINFO generates the `Workspace`
- users do not treat the generated workspace as the primary long-term source by default

### Current implementation boundary

The manifest contract is designed to expand to other typed resource kinds, but the
current ingest engine only implements:

- `cell-instance`

Additional `resource_type` values should only be added when the ingest engine and
its downstream record-generation logic actually support them.
