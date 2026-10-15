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

New records always stamp the current version. The value names a record shape, not a revision of the schemas: records of all three versions are checked against the one set of schemas served under `https://w3id.org/battinfo/schema/`, and those schemas changed in place before 0.8.0, as the [erratum to section 11.1 of the identifier policy](https://github.com/BIG-MAP/BattINFO/blob/main/IDENTIFIER_POLICY.md#erratum-changes-made-in-place-before-080) lists. So a record written before 0.8.0 does not always validate against the 0.8.0 schemas. The schemas no longer take `specs` or `sameAs`, so a `0.1.0` record that uses them fails (some other older spellings, such as `legalName` and `co_type`, are still accepted), and so does a record with text in a quantity's `value` or a date string that is not `YYYY`, `YYYY-MM` or `YYYY-MM-DD`. battinfo's record models still accept `specs` and `sameAs` as input and write the current names, and its readers move text in `value` to `value_text`, so reading such a record with battinfo and saving it again fixes both; a date string in another form has to be rewritten. From the v0.8.0 tag the schemas served at each URL no longer change, apart from their descriptions; what a new `schema_version` value will say about the schemas is to be defined in 0.9.

### Records are attributable

Every emitted record's provenance block carries `battinfo_version` — the
library build that wrote it. A malformed record found in a corpus two years
from now is forensically traceable to its producer. Explicitly set values are
preserved, so re-serialising another build's record never falsifies origin.

### Identifiers are deterministic

Records saved without an explicit `uid` mint their IRI on your machine from the
record's natural identity key, through one primitive (`entities.stable_uid`)
and the shared seed builders in `battinfo.entities`. A cell spec's key is its
manufacturer, model, format, chemistry and size code; a cell's is its spec and
its serial number (or name); a test's is its cell, kind, protocol and run.
Free text in a key is normalised first (surrounding and repeated whitespace, a
no-break space and a decomposed accent change nothing, case does), and a
chemistry counts by its vocabulary key, so `Li-ion` and `LI-ION` are one cell
spec. Consequences you can rely on:

- re-running an identical ingest is a **no-op**, never a duplicate corpus;
- running the same `ws.load()` or `ws.add()` call again in one session, as a notebook does when a cell is re-run, reuses the record the session already holds instead of adding a copy;
- an IRI a record already has (pinned, imported, or given by an earlier save, in this session or an earlier one in the same folder, a cell spec or test saved before 0.8.0 included) never moves when a record with the same identity fields joins: the newcomer is minted from its content. A record saved by an earlier session is recognised by its content, so one you edit in the same save in which such a newcomer joins is minted from its content too; pin it;
- a test's IRI names one run on one cell, told apart by its protocol and its first data file (or, for a test without data, a start time you pass, else the name you give it), so a later run with its own data, start time or name never takes an earlier run's IRI, and renaming a test with data or a start time keeps its IRI; a title BattINFO generates (`C01 cycling`) never enters, and a save refuses to let a test with none of these replace a saved run with another instrument or time window;
- the workspace, its engine, a save without an id, and the `save_*` and `create_*` functions for cell specs, cells, test specs, tests without data files, materials, electrodes, channels, parameter sets and organizations mint **identical IRIs** for identical identities, and so do the workspace, its engine and `save_dataset` for datasets, the publication package for cell specs and cells, and the batch path for a cell with a serial number (with `ws.add("cell")` only when the batch cell has no batch id) (`tests/test_idempotent_minting.py`); `tests/test_golden_iris.py` fails if any path's IRI moves without a changelog entry;
- records with no distinguishing identity still mint randomly — two anonymous
  but physically distinct cells never silently merge.

Some paths are outside this until 0.9, which moves every minting path onto
`battinfo.entities` and keeps the IRIs they minted in 0.8 findable (section 5
of the identifier policy):

- the component and equipment builders (`create_component_spec`,
  `create_component_instance`, their per-family wrappers, `create_equipment_spec`
  and `create_equipment`) give a record without `uid=` or `id=` a random IRI,
  a new one on every call;
- `battinfo batch init` and `battinfo batch add` give a cell without a serial
  number a random IRI, recorded in its `battinfo.yaml`;
- the interop importers (BattInfoConverter, the solid-state database,
  Discovery and the Battery Data Commons bridge) mint from their own seeds:
  stable when the same source is imported again, but not the IRIs the
  workspace gives the same records;
- the publication package and `battinfo batch package` seed a dataset from its
  folder and title, not its file, so its dataset IRI differs from the
  workspace's, and the publication package does the same for the run of a
  test with data;
- `battinfo batch package` seeds a test from its raw file's path in the cell
  folder, so it matches the workspace's test only when the workspace's data
  file has that path in the workspace folder;
- `save_test()` and a save without an id never see a data file, so they give
  a test with data another IRI than the workspace does, and a save without an
  id leaves a dataset's cell and test out of its seed.

The [known limitations](scope.md#identifiers) say what to do on each of these
paths.

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
- A record whose IRI another publisher already holds comes back from `ws.submit()` as a `conflict` outcome that names the IRI and that publisher and says how to rename or pin the record. It is not retried as a new version.

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
- `publisher`: publisher-oriented validation with semantic and publication checks as errors. A deposit graph that the SHACL publication shapes could not check is an error too, so it is never published unchecked.
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
- `semantic.chemistry_electrode_conflict` (the negative electrode basis contradicts the chemistry, such as lithium metal in a full `li-ion` cell or graphite in a `li-metal` one; see the chemistry labels in the [property keys reference](pages/property-reference.md))
- `semantic.percent_basis_mismatch` (a warning under every policy: a fraction's percent unit states the other basis, such as `vol%` on a `mass_fraction` or `wt%` on a `volume_fraction` or a `porosity`; see the units in the [property keys reference](pages/property-reference.md))
- `semantic.method_step_unmapped` (a warning under every policy: no published EMMO process class fits a test-protocol step, such as a constant-resistance charge or a cr or cccv step with no direction, so the JSON-LD export gives it none; see [Tests](records/tests.md))
- `semantic.handle_kind_word_expected` (a warning under every policy: the record's `handle` does not end with its type's kind word; see [Name your records](howto/name-your-records.md))
- `semantic.schema_version_superseded` and `semantic.schema_version_unknown` (warnings under every policy: the record's `schema_version` is one an earlier release wrote, `0.1.0` or `1.0.0`, or one this release does not know at all; the current version is `0.2.0`)
- `semantic.timestamp_implausible` (a warning under every policy: a `*_at` Unix time outside 2000 to 2100) and `semantic.timestamp_out_of_range` (a `*_at` number that cannot be a Unix time in seconds, because it falls outside the years 1 to 9999 as a time in milliseconds does; an error under the strict and publisher policies, a warning under the others)
- `jsonld.type_term_unknown` (an error under every policy: a bare `@type` that the document's own `@context` does not define as a class, so it would expand to a machine-local IRI; `record_to_jsonld` raises on it for every record type)
- `publication.distribution_url_invalid`
- `jsonld.parse_error` (the JSON-LD could not be parsed into an RDF dataset)
- `publication.shacl_unavailable`, `publication.shapes_not_found` and `publication.shacl_runtime_error` (the SHACL publication shapes could not check a deposit graph because pyshacl could not be imported, the shapes file is missing or pyshacl failed: an error under the `publisher` policy, which `ws.zenodo()` applies before it mints a DOI, and a warning under the others)

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
