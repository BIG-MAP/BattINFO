# BattINFO CLI Specification (Alpha Scope)

## 1. Scope

This specification defines the primary user interaction surface for BattINFO:

- query canonical resources (`cell-type`, `cell-instance`, `test`, `dataset`)
- create new resource instances
- publish validated records into resolver-ready artifacts
- build and inspect local resource indexes

All commands operate on canonical BattINFO resources and enforce identifier policy.

## 2. Global CLI Behavior

Command root:

```text
battinfo <group> <command> [options]
```

Global options:

- command-specific `--format` options are used where supported

Exit codes:

- `0`: success
- `1`: validation or user input error
- `2`: configuration or dependency error
- `3`: internal processing error

## 3. Validation Command

### 3.1 Validate Documents

```text
battinfo validate <input-path> [options]
```

Options:

- `--profile <profile-name>` for profile/schema validation
- `--source-root <dir>` for canonical record validation with reference checks
- `--policy <default|strict|publisher|ingest>`
- `--format <text|json>`

Behavior:

- validates a schema/profile document when `--source-root` is omitted
- validates a canonical record when `--source-root` is provided
- emits machine-readable structured issue output in JSON mode
- returns success when only warning-severity issues are present

JSON output contract:

```json
{
  "ok": true,
  "mode": "profile",
  "policy": "default",
  "profile": "cell-descriptor",
  "source_root": null,
  "issue_count": 0,
  "error_count": 0,
  "warning_count": 0,
  "errors": [],
  "issues": []
}
```

## 4. Query Commands

### 4.1 Query Cell Types

```text
battinfo query cell-type [filters...]
```

Filters:

- `--id <cell-type-iri>`
- `--manufacturer <name>`
- `--chemistry <value>`
- `--cell-format <cylindrical|prismatic|pouch|coin|other|unknown>`
- `--model-name-contains <text>`
- `--nominal-capacity-min <number>`
- `--nominal-capacity-max <number>`
- `--nominal-voltage-min <number>`
- `--nominal-voltage-max <number>`
- `--limit <int>` (default `50`)
- `--offset <int>` (default `0`)

Behavior:

- Supports exact filters and numeric range filters.
- Returns canonical `cell-type` IRIs and summary metadata.
- Range filters apply to normalized canonical fields in `specs`.

### 4.2 Query Cell Instances

```text
battinfo query cell-instances [filters...]
```

Filters:

- `--id <cell-iri>`
- `--type-id <cell-type-iri>`
- `--short-id <prefix>`
- `--serial-number <string>` (metadata only, non-canonical)
- `--has-dataset <true|false>`
- `--dataset-id <dataset-iri>`
- `--source-type <measurement|lab|bms|other>`
- `--limit <int>` (default `50`)
- `--offset <int>` (default `0`)

Behavior:

- Returns instance IRIs with type links and dataset links.
- `--serial-number` is optional metadata search only.

### 4.3 Query Datasets

```text
battinfo query dataset [filters...]
```

Filters:

- `--id <dataset-iri>`
- `--title-contains <text>`
- `--related-cell-id <cell-iri>`
- `--related-test-id <test-iri>`
- `--source-type <measurement|lab|simulation|external|other>`
- `--data-format <mime-or-label>`
- `--license <string>`
- `--limit <int>` (default `50`)
- `--offset <int>` (default `0`)

Behavior:

- Returns dataset IRIs with title, format, access URL, and related entity links.

### 4.4 Query Tests

```text
battinfo query tests [filters...]
```

Filters:

- `--id <test-iri>`
- `--cell-id <cell-iri>`
- `--dataset-id <dataset-iri>`
- `--kind <test-kind>`
- `--source-type <measurement|lab|simulation|manual|other>`
- `--limit <int>` (default `50`)
- `--offset <int>` (default `0`)

Behavior:

- Returns canonical test IRIs with cell links, dataset links, and summary test metadata.

### 4.5 Query Output Contract

JSON mode (`--format json`) for all query commands:

```json
{
  "resource": "cell-type",
  "count": 2,
  "limit": 50,
  "offset": 0,
  "items": [
    {
      "id": "https://w3id.org/battinfo/cell-type/7d9k-2m4p-8t3x-6nq5",
      "short_id": "7d9k2m",
      "manufacturer": "A123",
      "model_name": "ANR26650M1-B"
    }
  ]
}
```

## 5. Create Commands

### 5.1 Create Cell Instance

```text
battinfo create cell-instance \
  --type-id <cell-type-iri> \
  [--serial-number <value>] \
  [--dataset-id <dataset-iri>] \
  [--source-type <measurement|lab|bms|other>] \
  [--out <path>]
```

Behavior:

- Mints a policy-compliant `cell/{uid}` IRI.
- Validates generated record against `cell-instance.schema.json`.
- Writes JSON to `--out` or prints JSON to stdout if omitted.

Output contract:

```json
{
  "status": "created",
  "id": "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8",
  "type_id": "https://w3id.org/battinfo/cell-type/7d9k-2m4p-8t3x-6nq5",
  "path": "examples/cell-instances/cell-3m6k-9t2p-7x4h-9nq8.json"
}
```

### 5.2 Register Canonical Resources

Registration is the primary workflow for creating canonical BattINFO resources in source storage.

```text
battinfo save record --input <json-path> [options]
battinfo save cell-type [--input <json-path> | inline-fields...] [options]
battinfo save cell-instance [--input <json-path> | inline-fields...] [options]
battinfo save dataset [--input <json-path> | inline-fields...] [options]
battinfo save batch --source-dir <dir> [--source-dir <dir> ...] [options]
```

Common options:

- `--source-root <dir>` (default `examples`)
- `--mode <create_only|upsert>`
- `--duplicate-policy <error|return_existing>`
- `--dry-run`
- `--publish/--no-publish`
- `--resolve-references/--no-resolve-references`

Behavior:

- Validates against schema profile.
- Mints or verifies canonical identifier.
- Enforces duplicate/idempotency policy.
- Optionally publishes resolver artifacts.

Typical result:

```json
{
  "status": "created",
  "entity_type": "cell-type",
  "id": "https://w3id.org/battinfo/cell-type/3m6k-9t2p-7x4h-9nq8",
  "path": "examples/cell-type/cell-type-3m6k-9t2p-7x4h-9nq8.json",
  "mode": "create_only",
  "published": false
}
```

Batch result:

```json
{
  "status": "ok",
  "processed": 30,
  "created": 30,
  "updated": 0,
  "exists": 0,
  "dry_run": 0,
  "failed": 0,
  "failures": []
}
```

### 5.3 Generate Starter Templates

```text
battinfo template cell-type [options]
battinfo template cell-instance [options]
battinfo template dataset [options]
```

Behavior:

- Generates minimal canonical JSON records suitable for edit + save.
- Writes to `--out` when provided; otherwise prints JSON to stdout.
- Defaults use placeholder IRIs/UIDs (`0000-0000-0000-0000`) for easy replacement.

## 6. Publish Commands

### 6.1 Publish One Resource

```text
battinfo publish record \
  --input <json-path> \
  [--target-root .battinfo/resolver-site] \
  [--build-jsonld true] \
  [--build-html true]
```

Behavior:

- Validates the input record.
- Builds resolver artifacts (`index.json`, `index.jsonld`, `index.html`) under the canonical path.
- Fails fast on invalid IDs or schema violations.

### 6.2 Publish Batch

```text
battinfo publish batch \
  --source-dir <dir> \
  [--glob *.json] \
  [--target-root .battinfo/resolver-site]
```

Behavior:

- Processes matching records in deterministic order.
- Produces summary report with counts for success/failure.

Output contract:

```json
{
  "status": "ok",
  "processed": 100,
  "published": 98,
  "failed": 2,
  "failures": [
    {
      "file": "bad-record.json",
      "error": "invalid cell_instance.id"
    }
  ]
}
```

## 7. Index Commands

### 7.1 Build Index

```text
battinfo index build \
  --source-root examples \
  --out .battinfo/index.json
```

### 7.2 Show Index Stats

```text
battinfo index stats \
  --index .battinfo/index.json
```

Minimum stats output:

- `cell_type_count`
- `cell_instance_count`
- `dataset_count`
- `build_timestamp`

## 8. Acceptance Criteria

### Query

- `query cell-type`, `query cell-instances`, `query tests`, and `query dataset` implemented.
- Each command supports meaningful resource-specific filters.
- JSON output contract stable and documented.

### Create

- `create cell-instance` mints policy-compliant IDs.
- Generated record validates against schema.
- Optional serial metadata accepted but not used in canonical identity.

### Publish

- `publish record` and `publish batch` implemented.
- Generates resolver artifacts in canonical path layout.
- Produces machine-readable summary report.

### Index

- `index build` and `index stats` implemented.
- Index output includes at least cell-type/cell-instance/dataset counts plus build timestamp.

### Reliability

- Covered by tests in `tests/`.
- Included in CI checks.
- Error messages are actionable and path-specific.

## 9. First Implementation Mapping (Code Layout)

Suggested modules:

- `src/battinfo/workflows/query.py`
- `src/battinfo/workflows/create.py`
- `src/battinfo/workflows/publish.py`
- `src/battinfo/index/build.py`
- `src/battinfo/index/query.py`

CLI wiring:

- extend `src/battinfo/cli.py` with Typer sub-apps:
  - `query`
  - `create`
  - `publish`
  - `index`






