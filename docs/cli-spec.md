# BattINFO CLI Specification (First Draft)

## 1. Scope

This specification defines the primary user interaction surface for BattINFO:

- query library resources (`cell-type`, `cell`, `dataset`)
- create new resource instances (starting with `cell-instance`)
- publish validated records into resolver-ready artifacts
- build and inspect local resource indexes

All commands operate on canonical BattINFO resources and enforce identifier policy.

## 2. Global CLI Behavior

Command root:

```text
battinfo <group> <command> [options]
```

Global options:

- `--format {table,json}` output format (default `table` for query, `json` for create/publish status)
- `--quiet` minimal output
- `--verbose` include debug details

Exit codes:

- `0`: success
- `1`: validation or user input error
- `2`: configuration or dependency error
- `3`: internal processing error

## 3. Query Commands

### 3.1 Query Cell Types

```text
battinfo query cell-types [filters...]
```

Filters:

- `--id <cell-type-iri>`
- `--manufacturer <name>`
- `--chemistry <value>`
- `--format <cylindrical|prismatic|pouch|coin|other|unknown>`
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

### 3.2 Query Cell Instances

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
- `--retrieved-after <ISO8601>`
- `--retrieved-before <ISO8601>`
- `--limit <int>` (default `50`)
- `--offset <int>` (default `0`)

Behavior:

- Returns instance IRIs with type links and dataset links.
- `--serial-number` is optional metadata search only.

### 3.3 Query Datasets

```text
battinfo query datasets [filters...]
```

Filters:

- `--id <dataset-iri>`
- `--title-contains <text>`
- `--related-cell-id <cell-iri>`
- `--source-type <measurement|lab|simulation|external|other>`
- `--created-after <ISO8601>`
- `--created-before <ISO8601>`
- `--format <mime-or-label>`
- `--license <string>`
- `--limit <int>` (default `50`)
- `--offset <int>` (default `0`)

Behavior:

- Returns dataset IRIs with title, format, access URL, and related entity links.

### 3.4 Query Output Contract

JSON mode (`--format json`) for all query commands:

```json
{
  "resource": "cell-types",
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

## 4. Create Commands

### 4.1 Create Cell Instance

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
  "path": "assets/examples/cell-instances/cell-3m6k-9t2p-7x4h-9nq8.json"
}
```

## 5. Publish Commands

### 5.1 Publish One Resource

```text
battinfo publish record \
  --input <json-path> \
  [--target-root registry/site] \
  [--build-jsonld true] \
  [--build-html true]
```

Behavior:

- Validates the input record.
- Builds resolver artifacts (`index.json`, `index.jsonld`, `index.html`) under the canonical path.
- Fails fast on invalid IDs or schema violations.

### 5.2 Publish Batch

```text
battinfo publish batch \
  --source-dir <dir> \
  [--glob *.json] \
  [--target-root registry/site]
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

## 6. Index Commands

### 6.1 Build Index

```text
battinfo index build \
  --source-root assets/examples \
  --out .battinfo/index.json
```

### 6.2 Show Index Stats

```text
battinfo index stats \
  --index .battinfo/index.json
```

Minimum stats output:

- `cell_type_count`
- `cell_instance_count`
- `dataset_count`
- `build_timestamp`

## 7. Acceptance Criteria

### Query

- `query cell-types`, `query cell-instances`, `query datasets` implemented.
- Each supports at least 10 meaningful filters.
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

## 8. First Implementation Mapping (Code Layout)

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
