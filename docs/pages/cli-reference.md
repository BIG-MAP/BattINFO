# CLI reference

Every `battinfo` command, generated from the CLI itself (so it cannot drift). All commands and options:

**Usage**:

```console
$ battinfo [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `validate`: Validate a BattINFO record (JSON Schema +...
* `init`: Create a minimal workspace scaffold with...
* `map`: Map canonical JSON to JSON-LD for a target.
* `push`: Publish battery data to Zenodo in one...
* `query`: Query BattINFO resources.
* `create`: Create BattINFO resources.
* `publish`: Publish BattINFO resolver artifacts.
* `index`: Build and inspect BattINFO indexes.
* `save`: Save canonical BattINFO resources locally.
* `template`: Generate starter templates.
* `library`: Manage reusable BattINFO library records.
* `editorial`: Validate and promote battinfo-records...
* `workspace`: Author BattINFO workspaces on disk.
* `notebook`: Notebook runtime recovery helpers.
* `demo`: Scaffold and verify end-to-end BattINFO...
* `ingest`: Register typed resource instances from...
* `registry`: Manage registry tenants, workspaces, and...
* `dataset`: Contribute measurement datasets: init -&gt;...
* `batch`: Scaffold and manage multi-cell batch...
* `config`: Manage user preferences (creator, license,...
* `properties`: Browse valid spec property names and their...

## `battinfo validate`

Validate a BattINFO record (JSON Schema + semantic + SHACL) or a raw JSON profile document.

**Usage**:

```console
$ battinfo validate [OPTIONS] INPUT_PATH
```

**Arguments**:

* `INPUT_PATH`: [required]

**Options**:

* `--profile TEXT`: JSON Schema profile (used only for raw JSON, not full records).  [default: cell-spec]
* `--policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--format TEXT`: Output format: text|json.  [default: text]
* `--source-root DIRECTORY`: Canonical source root for cross-reference validation.
* `--shacl / --no-shacl`: Run SHACL shapes validation (cell-spec records only).  [default: shacl]
* `--help`: Show this message and exit.

## `battinfo init`

Create a minimal workspace scaffold with an example JSON file.

**Usage**:

```console
$ battinfo init [OPTIONS] WORKSPACE_DIR
```

**Arguments**:

* `WORKSPACE_DIR`: [required]

**Options**:

* `--profile TEXT`: Profile to scaffold.  [default: cell-spec]
* `--help`: Show this message and exit.

## `battinfo map`

Map canonical JSON to JSON-LD for a target.

**Usage**:

```console
$ battinfo map [OPTIONS] INPUT_PATH
```

**Arguments**:

* `INPUT_PATH`: [required]

**Options**:

* `--target TEXT`: Mapping target (&#x27;domain-battery&#x27; or &#x27;batterypass&#x27;).  [default: batterypass]
* `--out PATH`: Output JSON-LD path.  [required]
* `--help`: Show this message and exit.

## `battinfo push`

Publish battery data to Zenodo in one command.


Accepts three layouts:
  battinfo push ./flat_files/    --cell-spec &quot;Energizer CR2032&quot;   # groups by filename
  battinfo push ./cell_folders/  --cell-spec &quot;Energizer CR2032&quot;   # one subdir per cell
  battinfo push ./my_batch/                                        # existing batch.yaml


One-time setup:
  battinfo config set creator &quot;Family, Given; Institution&quot;
  battinfo config set zenodo_token &lt;token&gt;

**Usage**:

```console
$ battinfo push [OPTIONS] FOLDER
```

**Arguments**:

* `FOLDER`: Folder containing raw data files or an existing batch.  [required]

**Options**:

* `-t, --cell-spec TEXT`: Cell type, e.g. &#x27;Energizer CR2032&#x27;. Required for unstructured folders.
* `-n, --cells INTEGER`: Number of cells (auto-detected from filenames if omitted).
* `--batch-id TEXT`: Batch / lot identifier.
* `--lab TEXT`: Lab name.
* `--operator TEXT`: Operator name.
* `-c, --creator TEXT`: Creator: &quot;Family, Given; Affiliation&quot;. Falls back to config.
* `--token TEXT`: Zenodo API token. Falls back to config / ZENODO_API_TOKEN.
* `--sandbox`: Upload to sandbox.zenodo.org instead of production.
* `--community TEXT`: Zenodo community. Default: from config.
* `--no-community`: Skip community submission.
* `-y, --yes`: Skip confirmation prompt.
* `--dry-run`: Package only — do not upload.
* `--staging PATH`: Override staging directory.
* `--json`: Emit machine-readable JSON to stdout.
* `--help`: Show this message and exit.

## `battinfo query`

Query BattINFO resources.

**Usage**:

```console
$ battinfo query [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `cell-spec`: Query canonical cell types.
* `cell-instance`: Query canonical cell instances.
* `dataset`: Query canonical dataset records.
* `test-protocol`: Query canonical test protocols.
* `test-spec`: Query canonical test protocols.
* `tests`: Query canonical tests.

### `battinfo query cell-spec`

Query canonical cell types.

**Usage**:

```console
$ battinfo query cell-spec [OPTIONS]
```

**Options**:

* `--id TEXT`: Filter by canonical cell-spec IRI.
* `--manufacturer TEXT`: Filter by manufacturer.
* `--chemistry TEXT`: Filter by chemistry.
* `--cell-format TEXT`: Filter by cell form factor.
* `--model-name-contains TEXT`: Filter by model name substring.
* `--nominal-capacity-min FLOAT`: Filter minimum nominal capacity.
* `--nominal-capacity-max FLOAT`: Filter maximum nominal capacity.
* `--nominal-voltage-min FLOAT`: Filter minimum nominal voltage.
* `--nominal-voltage-max FLOAT`: Filter maximum nominal voltage.
* `--limit INTEGER RANGE`: Maximum rows.  [default: 50; x&gt;=1]
* `--offset INTEGER RANGE`: Start offset.  [default: 0; x&gt;=0]
* `--format TEXT`: Output format: table|json.  [default: table]
* `--help`: Show this message and exit.

### `battinfo query cell-instance`

Query canonical cell instances.

**Usage**:

```console
$ battinfo query cell-instance [OPTIONS]
```

**Options**:

* `--id TEXT`: Filter by canonical cell IRI.
* `--cell-spec-id TEXT`: Filter by canonical cell-spec IRI.
* `--short-id TEXT`: Filter by short-id prefix.
* `--serial-number TEXT`: Filter by serial metadata.
* `--has-dataset TEXT`: Filter by dataset presence: true|false.
* `--dataset-id TEXT`: Filter by linked dataset IRI.
* `--source-type TEXT`: Filter by source type.
* `--limit INTEGER RANGE`: Maximum rows.  [default: 50; x&gt;=1]
* `--offset INTEGER RANGE`: Start offset.  [default: 0; x&gt;=0]
* `--format TEXT`: Output format: table|json.  [default: table]
* `--help`: Show this message and exit.

### `battinfo query dataset`

Query canonical dataset records.

**Usage**:

```console
$ battinfo query dataset [OPTIONS]
```

**Options**:

* `--id TEXT`: Filter by canonical dataset IRI.
* `--title-contains TEXT`: Filter by title substring.
* `--related-cell-id TEXT`: Filter by related cell IRI.
* `--related-test-id TEXT`: Filter by related test IRI.
* `--source-type TEXT`: Filter by source type.
* `--data-format TEXT`: Filter by dataset format.
* `--license TEXT`: Filter by license.
* `--limit INTEGER RANGE`: Maximum rows.  [default: 50; x&gt;=1]
* `--offset INTEGER RANGE`: Start offset.  [default: 0; x&gt;=0]
* `--format TEXT`: Output format: table|json.  [default: table]
* `--help`: Show this message and exit.

### `battinfo query test-protocol`

Query canonical test protocols.

**Usage**:

```console
$ battinfo query test-protocol [OPTIONS]
```

**Options**:

* `--id TEXT`: Filter by canonical test-protocol IRI.
* `--kind TEXT`: Filter by protocol kind.
* `--name-contains TEXT`: Case-insensitive substring filter on protocol name.
* `--source-type TEXT`: Filter by source type.
* `--limit INTEGER RANGE`: Maximum rows.  [default: 50; x&gt;=1]
* `--offset INTEGER RANGE`: Start offset.  [default: 0; x&gt;=0]
* `--format TEXT`: Output format: table|json.  [default: table]
* `--help`: Show this message and exit.

### `battinfo query test-spec`

Query canonical test protocols.

**Usage**:

```console
$ battinfo query test-spec [OPTIONS]
```

**Options**:

* `--id TEXT`: Filter by canonical test-protocol IRI.
* `--kind TEXT`: Filter by protocol kind.
* `--name-contains TEXT`: Case-insensitive substring filter on protocol name.
* `--source-type TEXT`: Filter by source type.
* `--limit INTEGER RANGE`: Maximum rows.  [default: 50; x&gt;=1]
* `--offset INTEGER RANGE`: Start offset.  [default: 0; x&gt;=0]
* `--format TEXT`: Output format: table|json.  [default: table]
* `--help`: Show this message and exit.

### `battinfo query tests`

Query canonical tests.

**Usage**:

```console
$ battinfo query tests [OPTIONS]
```

**Options**:

* `--id TEXT`: Filter by canonical test IRI.
* `--cell-id TEXT`: Filter by related cell-instance IRI.
* `--dataset-id TEXT`: Filter by linked dataset IRI.
* `--kind TEXT`: Filter by test kind.
* `--source-type TEXT`: Filter by source type.
* `--limit INTEGER RANGE`: Maximum rows.  [default: 50; x&gt;=1]
* `--offset INTEGER RANGE`: Start offset.  [default: 0; x&gt;=0]
* `--format TEXT`: Output format: table|json.  [default: table]
* `--help`: Show this message and exit.

## `battinfo create`

Create BattINFO resources.

**Usage**:

```console
$ battinfo create [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `cell-instance`: Create a canonical cell-instance record.

### `battinfo create cell-instance`

Create a canonical cell-instance record.

**Usage**:

```console
$ battinfo create cell-instance [OPTIONS]
```

**Options**:

* `--cell-spec-id TEXT`: Canonical cell-spec IRI.
* `--cell-spec FILE`: Path to cell-spec JSON (alternative to --cell-spec-id).
* `--model-name TEXT`: Resolve type by model name.
* `--manufacturer TEXT`: Resolve type by manufacturer.
* `--chemistry TEXT`: Resolve type by chemistry.
* `--cell-format TEXT`: Resolve type by cell format.
* `--serial-number TEXT`: Optional serial metadata.
* `--dataset-id TEXT`: Optional linked dataset IRI.
* `--source-type TEXT`: Source type: measurement|lab|bms|other.  [default: measurement]
* `--uid TEXT`: Optional 16-char UID (dashed or undashed).
* `--out PATH`: Optional output JSON path.
* `--validate / --no-validate`: Validate against schema.  [default: validate]
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

## `battinfo publish`

Publish BattINFO resolver artifacts.

**Usage**:

```console
$ battinfo publish [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `cell-spec`: Publish one cell type through the...
* `record`: Publish one record into resolver artifacts.
* `batch`: Publish a deterministic batch of records...

### `battinfo publish cell-spec`

Publish one cell type through the simplified BattINFO publish surface.

**Usage**:

```console
$ battinfo publish cell-spec [OPTIONS]
```

**Options**:

* `--input FILE`: Optional JSON draft or canonical cell-spec record to load.
* `--manufacturer TEXT`: Cell manufacturer.
* `--model TEXT`: Cell model.
* `--cell-format TEXT`: Cell format, for example cylindrical or pouch.
* `--chemistry TEXT`: Cell chemistry.
* `--name TEXT`: Optional display name.
* `--size-code TEXT`: Optional size code.
* `--iec-code TEXT`: Optional IEC code.
* `--country-of-origin TEXT`: Optional country of origin.
* `--year INTEGER`: Optional release or production year.
* `--source-type TEXT`: Optional provenance source type.
* `--source-file TEXT`: Optional provenance source file.
* `--destination TEXT`: Publish destination: local|registry|battery-genome|staging|production.  [default: local]
* `--root PATH`: Optional workspace root for generated artifacts.
* `--force`: Replace an existing generated workspace root.
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: strict]
* `--registry-url TEXT`: Optional registry base URL override.
* `--api-key TEXT`: Optional registry API key override.
* `--api-key-header TEXT`: Optional registry API key header.
* `--platform-url TEXT`: Optional Battery Genome base URL override.
* `--workspace-id TEXT`: Optional workspace id override.
* `--publisher-id TEXT`: Optional publisher id override.
* `--source-version TEXT`: Optional source version override.
* `--format TEXT`: Output format: json|text.  [default: json]
* `--help`: Show this message and exit.

### `battinfo publish record`

Publish one record into resolver artifacts.

**Usage**:

```console
$ battinfo publish record [OPTIONS]
```

**Options**:

* `--input FILE`: [required]
* `--target-root PATH`: Output artifact root directory.  [default: .battinfo/resolver-site]
* `--build-jsonld / --no-build-jsonld`: Generate JSON-LD output.  [default: build-jsonld]
* `--build-html / --no-build-html`: Generate HTML output.  [default: build-html]
* `--validate / --no-validate`: Validate records before publishing.  [default: validate]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo publish batch`

Publish a deterministic batch of records into resolver artifacts.

**Usage**:

```console
$ battinfo publish batch [OPTIONS]
```

**Options**:

* `--source-dir DIRECTORY`: One or more source directories. If omitted, API defaults are used.
* `--target-root PATH`: Output artifact root directory.  [default: .battinfo/resolver-site]
* `--glob TEXT`: File glob for batch inputs.  [default: *.json]
* `--build-jsonld / --no-build-jsonld`: Generate JSON-LD output.  [default: build-jsonld]
* `--build-html / --no-build-html`: Generate HTML output.  [default: build-html]
* `--validate / --no-validate`: Validate records before publishing.  [default: validate]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

## `battinfo index`

Build and inspect BattINFO indexes.

**Usage**:

```console
$ battinfo index [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `build`: Build an index from canonical example...
* `stats`: Show index statistics.

### `battinfo index build`

Build an index from canonical example resources.

**Usage**:

```console
$ battinfo index build [OPTIONS]
```

**Options**:

* `--source-root DIRECTORY`: Root directory containing cell-spec, cell-instances, and dataset subdirectories.  [default: examples]
* `--out PATH`: Output index JSON path.  [default: .battinfo/index.json]
* `--glob TEXT`: File glob to include in index build.  [default: *.json]
* `--validate / --no-validate`: Validate records while indexing.  [default: no-validate]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo index stats`

Show index statistics.

**Usage**:

```console
$ battinfo index stats [OPTIONS]
```

**Options**:

* `--index FILE`: Path to index JSON built by `battinfo index build`.  [default: .battinfo/index.json]
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

## `battinfo save`

Save canonical BattINFO resources locally.

**Usage**:

```console
$ battinfo save [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `record`: Save one canonical BattINFO record from JSON.
* `batch`: Save a deterministic batch of canonical...
* `cell-spec`: Save a cell-spec using either --input JSON...
* `cell-instance`: Save a cell-instance using either --input...
* `dataset`: Save a dataset using either --input JSON...
* `test-protocol`: Save a reusable test protocol using either...
* `test-spec`: Save a reusable test protocol using either...
* `test`: Save a test using either --input JSON or...

### `battinfo save record`

Save one canonical BattINFO record from JSON.

**Usage**:

```console
$ battinfo save record [OPTIONS]
```

**Options**:

* `--input FILE`: [required]
* `--source-root PATH`: Root directory containing cell-spec, cell-instances, and dataset.  [default: examples]
* `--mode TEXT`: Save mode: create_only|upsert.  [default: create_only]
* `--duplicate-policy TEXT`: Duplicate handling: error|return_existing.  [default: error]
* `--resolve-references / --no-resolve-references`: Best-effort reference checks at save time; full link integrity is enforced by batch/index validation.  [default: resolve-references]
* `--publish / --no-publish`: Publish resolver artifacts after saving.  [default: no-publish]
* `--publish-root PATH`: Resolver artifact root.  [default: .battinfo/resolver-site]
* `--build-jsonld / --no-build-jsonld`: Publish JSON-LD artifact.  [default: build-jsonld]
* `--build-html / --no-build-html`: Publish HTML artifact.  [default: build-html]
* `--validate / --no-validate`: Validate record before saving.  [default: validate]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--dry-run`: Preview save without writing files.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo save batch`

Save a deterministic batch of canonical JSON records.

**Usage**:

```console
$ battinfo save batch [OPTIONS]
```

**Options**:

* `--source-dir DIRECTORY`: One or more source directories. If omitted, API defaults are used.
* `--source-root PATH`: Root directory containing canonical resources for save targets.  [default: examples]
* `--glob TEXT`: File glob for batch inputs.  [default: *.json]
* `--mode TEXT`: Save mode: create_only|upsert.  [default: create_only]
* `--duplicate-policy TEXT`: Duplicate handling: error|return_existing.  [default: error]
* `--resolve-references / --no-resolve-references`: Allow deferred writes, then validate the resulting source tree as a set.  [default: resolve-references]
* `--publish / --no-publish`: Publish resolver artifacts after saving.  [default: no-publish]
* `--publish-root PATH`: Resolver artifact root.  [default: .battinfo/resolver-site]
* `--build-jsonld / --no-build-jsonld`: Publish JSON-LD artifact.  [default: build-jsonld]
* `--build-html / --no-build-html`: Publish HTML artifact.  [default: build-html]
* `--validate / --no-validate`: Validate records before saving.  [default: validate]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--dry-run`: Preview save without writing files.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo save cell-spec`

Save a cell-spec using either --input JSON or inline draft fields.

**Usage**:

```console
$ battinfo save cell-spec [OPTIONS]
```

**Options**:

* `--input FILE`: Draft or canonical JSON.
* `--manufacturer TEXT`: Manufacturer name (required when --input omitted).
* `--model-name TEXT`: Model name (required when --input omitted).
* `--chemistry TEXT`: Chemistry label.  [default: unknown]
* `--cell-format TEXT`: Cell format.  [default: unknown]
* `--size-code TEXT`: Optional size code.
* `--country-of-origin TEXT`: Optional country of origin.
* `--year INTEGER`: Optional model or release year.
* `--source-file TEXT`: Source file label for provenance (recorded only when given).
* `--source-url TEXT`: Optional source URL.
* `--uid TEXT`: Optional 16-char UID (dashed or undashed).
* `--specs FILE`: Optional specs JSON object.
* `--source-root PATH`: Save source root.  [default: examples]
* `--mode TEXT`: Save mode: create_only|upsert.  [default: create_only]
* `--duplicate-policy TEXT`: Duplicate handling: error|return_existing.  [default: error]
* `--publish / --no-publish`: Publish resolver artifacts after saving.  [default: no-publish]
* `--publish-root PATH`: Resolver artifact root.  [default: .battinfo/resolver-site]
* `--validate / --no-validate`: Validate record before saving.  [default: validate]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--dry-run`: Preview save without writing files.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo save cell-instance`

Save a cell-instance using either --input JSON or inline draft fields.

**Usage**:

```console
$ battinfo save cell-instance [OPTIONS]
```

**Options**:

* `--input FILE`: Draft or canonical JSON.
* `--cell-spec-id TEXT`: Canonical cell-spec IRI (required when --input omitted).
* `--serial-number TEXT`: Optional serial metadata.
* `--dataset-id TEXT`: Optional linked dataset IRI. Repeat for multiple.
* `--source-type TEXT`: Source type: measurement|lab|bms|other.  [default: measurement]
* `--uid TEXT`: Optional 16-char UID (dashed or undashed).
* `--source-root PATH`: Save source root.  [default: examples]
* `--mode TEXT`: Save mode: create_only|upsert.  [default: create_only]
* `--duplicate-policy TEXT`: Duplicate handling: error|return_existing.  [default: error]
* `--resolve-references / --no-resolve-references`: Resolve linked IDs against source_root.  [default: resolve-references]
* `--publish / --no-publish`: Publish resolver artifacts after saving.  [default: no-publish]
* `--publish-root PATH`: Resolver artifact root.  [default: .battinfo/resolver-site]
* `--validate / --no-validate`: Validate record before saving.  [default: validate]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--dry-run`: Preview save without writing files.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo save dataset`

Save a dataset using either --input JSON or inline draft fields.

**Usage**:

```console
$ battinfo save dataset [OPTIONS]
```

**Options**:

* `--input FILE`: Draft or canonical JSON.
* `--title TEXT`: Dataset title (required when --input omitted).
* `--description TEXT`: Dataset description.
* `--license TEXT`: Dataset license.
* `--data-format TEXT`: Dataset format string.
* `--access-url TEXT`: Dataset access URL.
* `--source-type TEXT`: Source type: measurement|lab|simulation|external|other.  [default: other]
* `--related-cell-id TEXT`: Related cell IRI. Repeat for multiple.
* `--related-test-id TEXT`: Related test IRI. Repeat for multiple.
* `--checksum-algorithm TEXT`: Checksum algorithm (sha256|sha512|md5|other).
* `--checksum-value TEXT`: Checksum value.
* `--uid TEXT`: Optional 16-char UID (dashed or undashed).
* `--source-root PATH`: Save source root.  [default: examples]
* `--mode TEXT`: Save mode: create_only|upsert.  [default: create_only]
* `--duplicate-policy TEXT`: Duplicate handling: error|return_existing.  [default: error]
* `--resolve-references / --no-resolve-references`: Resolve linked IDs against source_root.  [default: resolve-references]
* `--publish / --no-publish`: Publish resolver artifacts after saving.  [default: no-publish]
* `--publish-root PATH`: Resolver artifact root.  [default: .battinfo/resolver-site]
* `--validate / --no-validate`: Validate record before saving.  [default: validate]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--dry-run`: Preview save without writing files.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo save test-protocol`

Save a reusable test protocol using either --input JSON or inline draft fields.

**Usage**:

```console
$ battinfo save test-protocol [OPTIONS]
```

**Options**:

* `--input FILE`: Draft or canonical JSON.
* `--name TEXT`: Protocol name (required when --input omitted).
* `--kind TEXT`: Test kind.  [default: other]
* `--description TEXT`: Optional protocol description.
* `--version TEXT`: Optional protocol version.
* `--protocol-url TEXT`: Optional protocol URL.
* `--source-type TEXT`: Source type: manual|lab|simulation|other.  [default: manual]
* `--uid TEXT`: Optional 16-char UID (dashed or undashed).
* `--source-root PATH`: Save source root.  [default: examples]
* `--mode TEXT`: Save mode: create_only|upsert.  [default: create_only]
* `--duplicate-policy TEXT`: Duplicate handling: error|return_existing.  [default: error]
* `--resolve-references / --no-resolve-references`: Resolve linked IDs against source_root.  [default: resolve-references]
* `--publish / --no-publish`: Publish resolver artifacts after saving.  [default: no-publish]
* `--publish-root PATH`: Resolver artifact root.  [default: .battinfo/resolver-site]
* `--validate / --no-validate`: Validate record before saving.  [default: validate]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--dry-run`: Preview save without writing files.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo save test-spec`

Save a reusable test protocol using either --input JSON or inline draft fields.

**Usage**:

```console
$ battinfo save test-spec [OPTIONS]
```

**Options**:

* `--input FILE`: Draft or canonical JSON.
* `--name TEXT`: Protocol name (required when --input omitted).
* `--kind TEXT`: Test kind.  [default: other]
* `--description TEXT`: Optional protocol description.
* `--version TEXT`: Optional protocol version.
* `--protocol-url TEXT`: Optional protocol URL.
* `--source-type TEXT`: Source type: manual|lab|simulation|other.  [default: manual]
* `--uid TEXT`: Optional 16-char UID (dashed or undashed).
* `--source-root PATH`: Save source root.  [default: examples]
* `--mode TEXT`: Save mode: create_only|upsert.  [default: create_only]
* `--duplicate-policy TEXT`: Duplicate handling: error|return_existing.  [default: error]
* `--resolve-references / --no-resolve-references`: Resolve linked IDs against source_root.  [default: resolve-references]
* `--publish / --no-publish`: Publish resolver artifacts after saving.  [default: no-publish]
* `--publish-root PATH`: Resolver artifact root.  [default: .battinfo/resolver-site]
* `--validate / --no-validate`: Validate record before saving.  [default: validate]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--dry-run`: Preview save without writing files.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo save test`

Save a test using either --input JSON or inline draft fields.

**Usage**:

```console
$ battinfo save test [OPTIONS]
```

**Options**:

* `--input FILE`: Draft or canonical JSON.
* `--cell-id TEXT`: Canonical cell-instance IRI (required when --input omitted).
* `--name TEXT`: Test name (required when --input omitted).
* `--kind TEXT`: Test kind.  [default: other]
* `--protocol-id TEXT`: Optional reusable test-protocol IRI.
* `--status TEXT`: Optional test status.
* `--protocol-name TEXT`: Optional protocol name.
* `--protocol-url TEXT`: Optional protocol URL.
* `--instrument-name TEXT`: Optional instrument name.
* `--dataset-id TEXT`: Linked dataset IRI. Repeat for multiple.
* `--source-type TEXT`: Source type: measurement|lab|simulation|manual|other.  [default: measurement]
* `--uid TEXT`: Optional 16-char UID (dashed or undashed).
* `--source-root PATH`: Save source root.  [default: examples]
* `--mode TEXT`: Save mode: create_only|upsert.  [default: create_only]
* `--duplicate-policy TEXT`: Duplicate handling: error|return_existing.  [default: error]
* `--resolve-references / --no-resolve-references`: Resolve linked IDs against source_root.  [default: resolve-references]
* `--publish / --no-publish`: Publish resolver artifacts after saving.  [default: no-publish]
* `--publish-root PATH`: Resolver artifact root.  [default: .battinfo/resolver-site]
* `--validate / --no-validate`: Validate record before saving.  [default: validate]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--dry-run`: Preview save without writing files.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

## `battinfo template`

Generate starter templates.

**Usage**:

```console
$ battinfo template [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `cell-spec`: Generate a starter template for a...
* `cell-spec-draft`: Generate a starter authoring draft for a...
* `cell-instance`: Generate a starter template for a...
* `dataset`: Generate a starter template for a dataset...
* `test-protocol`: Generate a starter template for a reusable...
* `test-spec`: Generate a starter template for a reusable...
* `test`: Generate a starter template for a test...

### `battinfo template cell-spec`

Generate a starter template for a cell-spec record.

**Usage**:

```console
$ battinfo template cell-spec [OPTIONS]
```

**Options**:

* `--manufacturer TEXT`: Manufacturer name.  [default: ExampleManufacturer]
* `--model-name TEXT`: Model name.  [default: MODEL-001]
* `--chemistry TEXT`: Chemistry label.  [default: unknown]
* `--cell-format TEXT`: Cell format.  [default: unknown]
* `--country-of-origin TEXT`: Optional country of origin.
* `--year INTEGER`: Optional model or release year.
* `--uid TEXT`: Optional 16-char UID.  [default: 0000000000000000]
* `--out PATH`: Optional output JSON path.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo template cell-spec-draft`

Generate a starter authoring draft for a hand-edited cell-spec JSON file.

**Usage**:

```console
$ battinfo template cell-spec-draft [OPTIONS]
```

**Options**:

* `--manufacturer TEXT`: Manufacturer name placeholder.  [default: ExampleManufacturer]
* `--model-name TEXT`: Model name placeholder.  [default: MODEL-001]
* `--chemistry TEXT`: Chemistry label placeholder.  [default: unknown]
* `--cell-format TEXT`: Cell format placeholder.  [default: unknown]
* `--size-code TEXT`: Optional size code placeholder.
* `--iec-code TEXT`: Optional IEC code placeholder.
* `--country-of-origin TEXT`: Optional country of origin placeholder.
* `--year INTEGER`: Optional model or release year placeholder.
* `--positive-electrode-basis TEXT`: Optional positive electrode basis placeholder.
* `--negative-electrode-basis TEXT`: Optional negative electrode basis placeholder.
* `--datasheet-revision TEXT`: Optional datasheet revision placeholder.
* `--out PATH`: Optional output JSON path.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo template cell-instance`

Generate a starter template for a cell-instance record.

**Usage**:

```console
$ battinfo template cell-instance [OPTIONS]
```

**Options**:

* `--cell-spec-id TEXT`: Canonical cell-spec IRI.  [default: https://w3id.org/battinfo/spec/0000-0000-0000-0000]
* `--source-type TEXT`: Source type: measurement|lab|bms|other.  [default: measurement]
* `--uid TEXT`: Optional 16-char UID.  [default: 0000000000000000]
* `--out PATH`: Optional output JSON path.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo template dataset`

Generate a starter template for a dataset record.

**Usage**:

```console
$ battinfo template dataset [OPTIONS]
```

**Options**:

* `--title TEXT`: Dataset title.  [default: Example Dataset]
* `--source-type TEXT`: Source type: measurement|lab|simulation|external|other.  [default: other]
* `--uid TEXT`: Optional 16-char UID.  [default: 0000000000000000]
* `--related-cell-id TEXT`: Related cell IRI. Repeat for multiple.  [default: https://w3id.org/battinfo/cell/0000-0000-0000-0000]
* `--related-test-id TEXT`: Related test IRI. Repeat for multiple.
* `--out PATH`: Optional output JSON path.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo template test-protocol`

Generate a starter template for a reusable test-protocol record.

**Usage**:

```console
$ battinfo template test-protocol [OPTIONS]
```

**Options**:

* `--name TEXT`: Human-readable protocol name.  [default: Example Test Protocol]
* `--kind TEXT`: Test kind.  [default: other]
* `--source-type TEXT`: Source type: manual|lab|simulation|other.  [default: manual]
* `--uid TEXT`: Optional 16-char UID.  [default: 0000000000000000]
* `--out PATH`: Optional output JSON path.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo template test-spec`

Generate a starter template for a reusable test-protocol record.

**Usage**:

```console
$ battinfo template test-spec [OPTIONS]
```

**Options**:

* `--name TEXT`: Human-readable protocol name.  [default: Example Test Protocol]
* `--kind TEXT`: Test kind.  [default: other]
* `--source-type TEXT`: Source type: manual|lab|simulation|other.  [default: manual]
* `--uid TEXT`: Optional 16-char UID.  [default: 0000000000000000]
* `--out PATH`: Optional output JSON path.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo template test`

Generate a starter template for a test record.

**Usage**:

```console
$ battinfo template test [OPTIONS]
```

**Options**:

* `--cell-id TEXT`: Canonical cell-instance IRI under test.  [default: https://w3id.org/battinfo/cell/0000-0000-0000-0000]
* `--name TEXT`: Human-readable test name.  [default: Example Test]
* `--kind TEXT`: Test kind.  [default: other]
* `--source-type TEXT`: Source type: measurement|lab|simulation|manual|other.  [default: measurement]
* `--uid TEXT`: Optional 16-char UID.  [default: 0000000000000000]
* `--dataset-id TEXT`: Linked dataset IRI. Repeat for multiple.
* `--out PATH`: Optional output JSON path.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

## `battinfo library`

Manage reusable BattINFO library records.

**Usage**:

```console
$ battinfo library [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `build-rdf`: Build domain-battery JSON-LD artifacts for...
* `query`: Query reusable library records.
* `save`: Save reusable BattINFO library records...
* `template`: Generate reusable library templates.

### `battinfo library build-rdf`

Build domain-battery JSON-LD artifacts for the reusable cell-spec library.

**Usage**:

```console
$ battinfo library build-rdf [OPTIONS]
```

**Options**:

* `--input-dir DIRECTORY`: Directory containing reusable library cell-specification JSON files.  [default: .battinfo/library/cell-spec]
* `--output-jsonld-dir PATH`: Directory for per-record domain-battery JSON-LD artifacts.  [default: .battinfo/library-rdf/cell-spec]
* `--aggregate-jsonld PATH`: Path for the aggregated library JSON-LD file.  [default: .battinfo/library/cell-spec.jsonld]
* `--manifest-json PATH`: Path for the generated library manifest JSON.  [default: .battinfo/library-rdf/cell-spec.index.json]
* `--glob TEXT`: File glob used to select library cell specifications.  [default: *.json]
* `--clean-output`: Remove existing JSON-LD outputs before writing.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo library query`

Query reusable library records.

**Usage**:

```console
$ battinfo library query [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `cell-spec`: Query reusable library cell-spec...

#### `battinfo library query cell-spec`

Query reusable library cell-spec specifications.

**Usage**:

```console
$ battinfo library query cell-spec [OPTIONS]
```

**Options**:

* `--id TEXT`: Filter by reusable cell-spec IRI.
* `--manufacturer TEXT`: Filter by manufacturer.
* `--model-contains TEXT`: Filter by model substring.
* `--chemistry TEXT`: Filter by chemistry.
* `--cell-format TEXT`: Filter by cell form factor.
* `--size-code TEXT`: Filter by size code.
* `--positive-electrode-basis TEXT`: Filter by positive electrode basis.
* `--negative-electrode-basis TEXT`: Filter by negative electrode basis.
* `--nominal-capacity-min FLOAT`: Filter minimum nominal capacity.
* `--nominal-capacity-max FLOAT`: Filter maximum nominal capacity.
* `--nominal-voltage-min FLOAT`: Filter minimum nominal voltage.
* `--nominal-voltage-max FLOAT`: Filter maximum nominal voltage.
* `--library-dir PATH`: Reusable library cell-specification directory.  [default: .battinfo/library/cell-spec]
* `--limit INTEGER RANGE`: Maximum rows.  [default: 50; x&gt;=1]
* `--offset INTEGER RANGE`: Start offset.  [default: 0; x&gt;=0]
* `--format TEXT`: Output format: table|json.  [default: table]
* `--help`: Show this message and exit.

### `battinfo library save`

Save reusable BattINFO library records locally.

**Usage**:

```console
$ battinfo library save [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `cell-spec`: Save a reusable library cell type from...

#### `battinfo library save cell-spec`

Save a reusable library cell type from cell-specification JSON or inline fields.

**Usage**:

```console
$ battinfo library save cell-spec [OPTIONS]
```

**Options**:

* `--input FILE`: Draft or canonical cell-specification JSON.
* `--manufacturer TEXT`: Manufacturer name (required when --input omitted).
* `--model TEXT`: Model name (required when --input omitted).
* `--chemistry TEXT`: Chemistry label.  [default: unknown]
* `--cell-format TEXT`: Cell format.  [default: unknown]
* `--positive-electrode-basis TEXT`: Positive electrode basis (required when --input omitted).
* `--negative-electrode-basis TEXT`: Negative electrode basis (required when --input omitted).
* `--size-code TEXT`: Optional size code.
* `--source-type TEXT`: Source type label.  [default: datasheet]
* `--source-name TEXT`: Optional source name.
* `--source-file TEXT`: Source file label for provenance (recorded only when given).
* `--source-url TEXT`: Optional source URL.
* `--uid TEXT`: Optional 16-char UID (dashed or undashed).
* `--property FILE`: Optional JSON object for cell-specification specification.property.
* `--library-dir PATH`: Reusable library cell-specification directory.  [default: .battinfo/library/cell-spec]
* `--packaged-dir PATH`: Packaged reusable library cell-specification directory.  [default: src/battinfo/data/library/cell-spec]
* `--mode TEXT`: Save mode: create_only|upsert.  [default: create_only]
* `--duplicate-policy TEXT`: Duplicate handling: error|return_existing.  [default: error]
* `--validate / --no-validate`: Validate cell specification before saving.  [default: validate]
* `--sync-packaged-copy / --no-sync-packaged-copy`: Sync the saved cell specification into package data.  [default: sync-packaged-copy]
* `--build-rdf / --no-build-rdf`: Build JSON-LD library artifacts after saving.  [default: no-build-rdf]
* `--output-jsonld-dir PATH`: Directory for per-record domain-battery JSON-LD artifacts.  [default: .battinfo/library-rdf/cell-spec]
* `--aggregate-jsonld PATH`: Path for the aggregated library JSON-LD file.  [default: .battinfo/library/cell-spec.jsonld]
* `--manifest-json PATH`: Path for the generated library manifest JSON.  [default: .battinfo/library-rdf/cell-spec.index.json]
* `--clean-output`: Clean existing JSON-LD outputs before rebuilding.
* `--dry-run`: Preview save without writing files.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo library template`

Generate reusable library templates.

**Usage**:

```console
$ battinfo library template [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `cell-spec`: Generate a starter reusable library...

#### `battinfo library template cell-spec`

Generate a starter reusable library cell-spec specification.

**Usage**:

```console
$ battinfo library template cell-spec [OPTIONS]
```

**Options**:

* `--manufacturer TEXT`: Manufacturer name.  [default: ExampleManufacturer]
* `--model TEXT`: Model name.  [default: MODEL-001]
* `--chemistry TEXT`: Chemistry label.  [default: unknown]
* `--cell-format TEXT`: Cell format.  [default: unknown]
* `--positive-electrode-basis TEXT`: Positive electrode basis.  [default: unknown]
* `--negative-electrode-basis TEXT`: Negative electrode basis.  [default: unknown]
* `--uid TEXT`: Optional 16-char UID.  [default: 0000000000000000]
* `--out PATH`: Optional output JSON path.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

## `battinfo editorial`

Validate and promote battinfo-records style staging drafts.

**Usage**:

```console
$ battinfo editorial [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `validate-staging-cell-spec`: Validate one single-file staging cell-spec...
* `validate-staging-cell-spec-batch`: Validate all staging cell-spec drafts in a...
* `promote-staging-cell-spec`: Promote one staging cell-spec draft into...
* `promote-staging-cell-spec-batch`: Promote all staging cell-spec drafts into...
* `validate-staging-dataset`: Validate one staging dataset record and...
* `validate-staging-dataset-batch`: Validate all staging dataset records in a...
* `promote-staging-dataset`: Promote one staging dataset record into...
* `promote-staging-dataset-batch`: Promote all staging dataset records into...
* `build-curated-cell-spec-submission`: Build a registry publication package for...
* `publish-curated-cell-spec`: Publish one curated cell-spec record to...

### `battinfo editorial validate-staging-cell-spec`

Validate one single-file staging cell-spec draft and preview its canonical record.

**Usage**:

```console
$ battinfo editorial validate-staging-cell-spec [OPTIONS]
```

**Options**:

* `--input FILE`: Staging JSON draft.  [required]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo editorial validate-staging-cell-spec-batch`

Validate all staging cell-spec drafts in a directory.

**Usage**:

```console
$ battinfo editorial validate-staging-cell-spec-batch [OPTIONS]
```

**Options**:

* `--input-dir DIRECTORY`: Directory of staging JSON drafts.  [required]
* `--glob TEXT`: Glob for staging drafts.  [default: *.json]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo editorial promote-staging-cell-spec`

Promote one staging cell-spec draft into records/cell-spec/&lt;record-id&gt;/record.json.

**Usage**:

```console
$ battinfo editorial promote-staging-cell-spec [OPTIONS]
```

**Options**:

* `--input FILE`: Staging JSON draft.  [required]
* `--curated-root PATH`: Curated cell-spec root.  [default: records/cell-spec]
* `--record-id TEXT`: Override the curated record id.
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--dry-run`: Preview promotion without writing files.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo editorial promote-staging-cell-spec-batch`

Promote all staging cell-spec drafts into curated record.json directories.

**Usage**:

```console
$ battinfo editorial promote-staging-cell-spec-batch [OPTIONS]
```

**Options**:

* `--input-dir DIRECTORY`: Directory of staging JSON drafts.  [required]
* `--curated-root PATH`: Curated cell-spec root.  [default: records/cell-spec]
* `--glob TEXT`: Glob for staging drafts.  [default: *.json]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--dry-run`: Preview promotion without writing files.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo editorial validate-staging-dataset`

Validate one staging dataset record and preview its curated record id.

**Usage**:

```console
$ battinfo editorial validate-staging-dataset [OPTIONS]
```

**Options**:

* `--input FILE`: Staging dataset JSON record.  [required]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo editorial validate-staging-dataset-batch`

Validate all staging dataset records in a directory.

**Usage**:

```console
$ battinfo editorial validate-staging-dataset-batch [OPTIONS]
```

**Options**:

* `--input-dir DIRECTORY`: Directory of staging dataset records.  [required]
* `--glob TEXT`: Glob for staging records.  [default: *.json]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo editorial promote-staging-dataset`

Promote one staging dataset record into records/dataset/&lt;record-id&gt;/record.json.

**Usage**:

```console
$ battinfo editorial promote-staging-dataset [OPTIONS]
```

**Options**:

* `--input FILE`: Staging dataset JSON record.  [required]
* `--curated-root PATH`: Curated dataset root.  [default: records/dataset]
* `--record-id TEXT`: Override the curated record id.
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--dry-run`: Preview promotion without writing files.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo editorial promote-staging-dataset-batch`

Promote all staging dataset records into curated record.json directories.

**Usage**:

```console
$ battinfo editorial promote-staging-dataset-batch [OPTIONS]
```

**Options**:

* `--input-dir DIRECTORY`: Directory of staging dataset records.  [required]
* `--curated-root PATH`: Curated dataset root.  [default: records/dataset]
* `--glob TEXT`: Glob for staging records.  [default: *.json]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--dry-run`: Preview promotion without writing files.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo editorial build-curated-cell-spec-submission`

Build a registry publication package for one curated cell-spec record.

**Usage**:

```console
$ battinfo editorial build-curated-cell-spec-submission [OPTIONS]
```

**Options**:

* `--input FILE`: Curated cell-spec record.json or equivalent canonical JSON.  [required]
* `--workspace-id TEXT`: Registry workspace id.  [required]
* `--publisher-id TEXT`: Registry publisher id.  [required]
* `--source-version TEXT`: Registry source_version for this publication run.  [required]
* `--source-local-id TEXT`: Override source_local_id; defaults to the curated record id inferred from the path.
* `--title TEXT`: Override submission title.
* `--publication-mode TEXT`: Publication intent mode.  [default: canonical-publication]
* `--source-system TEXT`: Submission provenance source_system.  [default: battinfo-records]
* `--workflow-name TEXT`: Submission provenance workflow_name.  [default: curated-cell-spec-publication]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--out PATH`: Optional path to write the generated submission package JSON.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

### `battinfo editorial publish-curated-cell-spec`

Publish one curated cell-spec record to battinfo-registry.

**Usage**:

```console
$ battinfo editorial publish-curated-cell-spec [OPTIONS]
```

**Options**:

* `--input FILE`: Curated cell-spec record.json or equivalent canonical JSON.  [required]
* `--workspace-id TEXT`: Registry workspace id.  [required]
* `--publisher-id TEXT`: Registry publisher id.  [required]
* `--source-version TEXT`: Registry source_version for this publication run.  [required]
* `--registry-url TEXT`: Registry base URL, for example http://127.0.0.1:8000.  [required]
* `--api-key TEXT`: Registry submission API key.  [required]
* `--api-key-header TEXT`: Registry submission API key header.  [default: X-Battinfo-API-Key]
* `--source-local-id TEXT`: Override source_local_id; defaults to the curated record id inferred from the path.
* `--title TEXT`: Override submission title.
* `--publication-mode TEXT`: Publication intent mode.  [default: canonical-publication]
* `--source-system TEXT`: Submission provenance source_system.  [default: battinfo-records]
* `--workflow-name TEXT`: Submission provenance workflow_name.  [default: curated-cell-spec-publication]
* `--validation-policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: default]
* `--timeout-sec FLOAT`: HTTP timeout in seconds.  [default: 30.0]
* `--out PATH`: Optional path to write the generated submission package JSON before posting.
* `--format TEXT`: Output format: table|json.  [default: json]
* `--help`: Show this message and exit.

## `battinfo workspace`

Author BattINFO workspaces on disk.

**Usage**:

```console
$ battinfo workspace [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `init`: Initialize a disk-backed BattINFO...
* `validate`: Validate a disk-backed BattINFO workspace...
* `bundle`: Bundle a disk-backed BattINFO workspace...

### `battinfo workspace init`

Initialize a disk-backed BattINFO workspace scaffold.

**Usage**:

```console
$ battinfo workspace init [OPTIONS] WORKSPACE_DIR
```

**Arguments**:

* `WORKSPACE_DIR`: [required]

**Options**:

* `--force`: Overwrite an existing non-empty workspace directory.
* `--format TEXT`: Output format: json|text.  [default: json]
* `--help`: Show this message and exit.

### `battinfo workspace validate`

Validate a disk-backed BattINFO workspace and write dist/validation-report.json.

**Usage**:

```console
$ battinfo workspace validate [OPTIONS] WORKSPACE_DIR
```

**Arguments**:

* `WORKSPACE_DIR`: [required]

**Options**:

* `--policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: strict]
* `--format TEXT`: Output format: json|text.  [default: json]
* `--help`: Show this message and exit.

### `battinfo workspace bundle`

Bundle a disk-backed BattINFO workspace into dist artifacts.

**Usage**:

```console
$ battinfo workspace bundle [OPTIONS] WORKSPACE_DIR
```

**Arguments**:

* `WORKSPACE_DIR`: [required]

**Options**:

* `--policy TEXT`: Validation policy: default|strict|publisher|ingest.  [default: strict]
* `--format TEXT`: Output format: json|text.  [default: json]
* `--help`: Show this message and exit.

## `battinfo notebook`

Notebook runtime recovery helpers.

**Usage**:

```console
$ battinfo notebook [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `recover`: Recover from a stuck VS Code notebook...

### `battinfo notebook recover`

Recover from a stuck VS Code notebook restart by stopping repo-local ipykernel processes.

**Usage**:

```console
$ battinfo notebook recover [OPTIONS]
```

**Options**:

* `--workspace-root DIRECTORY`: [default: .]
* `--venv-path PATH`: Relative or absolute venv root.  [default: .venv]
* `--clear-local-runtime / --keep-local-runtime`: Remove local .jupyter-runtime-test state after stopping kernels.  [default: clear-local-runtime]
* `--force-kill / --no-force-kill`: Force-kill repo-local notebook kernels that do not exit after terminate().  [default: force-kill]
* `--format TEXT`: Output format: json|text.  [default: json]
* `--help`: Show this message and exit.

## `battinfo demo`

Scaffold and verify end-to-end BattINFO demos.

**Usage**:

```console
$ battinfo demo [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `setup`: Author a BattINFO demo environment from...
* `verify`: Run the BattINFO demo pipeline through...

### `battinfo demo setup`

Author a BattINFO demo environment from Python objects and write a submission package.

**Usage**:

```console
$ battinfo demo setup [OPTIONS] [ROOT]
```

**Arguments**:

* `[ROOT]`: [default: .battinfo/demo-e2e]

**Options**:

* `--registry TEXT`: Registry tenant/workspace slug.  [default: digibatt/hello-world]
* `--publisher-id TEXT`: Publisher id used for the generated submission package.  [default: demo-lab]
* `--version TEXT`: Release version and submission source_version.  [default: 1.0.0]
* `--force`: Replace the existing demo root before regenerating it.
* `--format TEXT`: Output format: json|text.  [default: json]
* `--help`: Show this message and exit.

### `battinfo demo verify`

Run the BattINFO demo pipeline through registry publication and optional platform verification.

**Usage**:

```console
$ battinfo demo verify [OPTIONS] [ROOT]
```

**Arguments**:

* `[ROOT]`: [default: .battinfo/demo-e2e]

**Options**:

* `--registry-url TEXT`: Registry base URL, for example http://127.0.0.1:8000.  [required]
* `--api-key TEXT`: Registry submission API key.  [required]
* `--platform-url TEXT`: Optional Battery Genome base URL, for example https://www.battery-genome.org.
* `--registry TEXT`: Registry tenant/workspace slug.  [default: digibatt/hello-world]
* `--publisher-id TEXT`: Publisher id used for the generated submission package.  [default: demo-lab]
* `--version TEXT`: Release version and submission source_version.  [default: 1.0.0]
* `--api-key-header TEXT`: Registry submission API key header.  [default: X-Battinfo-API-Key]
* `--timeout-sec FLOAT`: Timeout window for registry and platform checks.  [default: 30.0]
* `--poll-interval-sec FLOAT`: Polling interval while waiting for responses.  [default: 1.0]
* `--force`: Replace the existing demo root before regenerating it.
* `--format TEXT`: Output format: json|text.  [default: json]
* `--help`: Show this message and exit.

## `battinfo ingest`

Register typed resource instances from folder-based evidence.

**Usage**:

```console
$ battinfo ingest [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `inspect`: Inspect one ingest folder and infer...
* `init`: Write battinfo.ingest.json so later...
* `build`: Create the linked ingest workspace from...
* `publish`: Build and publish one ingest workspace in...

### `battinfo ingest inspect`

Inspect one ingest folder and infer tests/datasets without writing any records.

**Usage**:

```console
$ battinfo ingest inspect [OPTIONS] INGEST_ROOT
```

**Arguments**:

* `INGEST_ROOT`: [required]

**Options**:

* `--resource-type TEXT`: Typed ingest subject. Today: cell-instance.  [default: cell-instance]
* `--type-record PATH`: Curated type record path.
* `--manifest PATH`: Optional battinfo.ingest.json path.
* `--resource-iri TEXT`: Existing BattINFO resource IRI to preserve.
* `--resource-name TEXT`: Human-facing instance label.
* `--workspace-id TEXT`: Workspace id used for bundling/publication.
* `--publisher-id TEXT`: Publisher id used for bundling/publication.
* `--source-version TEXT`: Submission source version.
* `--license TEXT`: Dataset license to apply.
* `--format TEXT`: Output format: json|text.  [default: json]
* `--help`: Show this message and exit.

### `battinfo ingest init`

Write battinfo.ingest.json so later build/publish commands only need the folder path.

**Usage**:

```console
$ battinfo ingest init [OPTIONS] INGEST_ROOT
```

**Arguments**:

* `INGEST_ROOT`: [required]

**Options**:

* `--resource-type TEXT`: Typed ingest subject. Today: cell-instance.  [default: cell-instance]
* `--type-record PATH`: Curated type record path.
* `--manifest PATH`: Where to write battinfo.ingest.json.
* `--resource-iri TEXT`: Existing BattINFO resource IRI to preserve.
* `--resource-name TEXT`: Human-facing instance label.
* `--workspace-id TEXT`: Workspace id used for bundling/publication.
* `--publisher-id TEXT`: Publisher id used for bundling/publication.
* `--source-version TEXT`: Submission source version.
* `--license TEXT`: Dataset license to apply.
* `--force`: Overwrite an existing manifest.
* `--format TEXT`: Output format: json|text.  [default: json]
* `--help`: Show this message and exit.

### `battinfo ingest build`

Create the linked ingest workspace from one evidence folder.

**Usage**:

```console
$ battinfo ingest build [OPTIONS] INGEST_ROOT
```

**Arguments**:

* `INGEST_ROOT`: [required]

**Options**:

* `--resource-type TEXT`: Typed ingest subject. Today: cell-instance.  [default: cell-instance]
* `--type-record PATH`: Curated type record path.
* `--manifest PATH`: Optional battinfo.ingest.json path.
* `--workspace-root PATH`: Where to write the authored workspace.
* `--resource-iri TEXT`: Existing BattINFO resource IRI to preserve.
* `--resource-name TEXT`: Human-facing instance label.
* `--workspace-id TEXT`: Workspace id used for bundling/publication.
* `--tenant TEXT`: Optional tenant id recorded in the workspace manifest.
* `--publisher-id TEXT`: Publisher id used for bundling/publication.
* `--source-version TEXT`: Submission source version.
* `--license TEXT`: Dataset license to apply.
* `--artifact-base-url TEXT`: Optional public base URL for packaged artifact files.
* `--force`: Replace the existing workspace root before regenerating it.
* `--bundle / --no-bundle`: Also build the submission package after authoring the workspace.  [default: bundle]
* `--validation-policy TEXT`: Validation policy: strict|set|quick.  [default: strict]
* `--format TEXT`: Output format: json|text.  [default: json]
* `--help`: Show this message and exit.

### `battinfo ingest publish`

Build and publish one ingest workspace in a single command.

Registry credentials and artifact storage are read from environment
variables when not supplied as flags:


  BATTINFO_REGISTRY_URL          registry base URL
  BATTINFO_API_KEY               publisher API key
  BATTINFO_STORAGE_BUCKET        S3/R2 bucket name (enables artifact upload)
  BATTINFO_STORAGE_ENDPOINT_URL  S3-compatible endpoint (for R2, Minio, etc.)
  BATTINFO_STORAGE_ACCESS_KEY_ID
  BATTINFO_STORAGE_SECRET_ACCESS_KEY
  BATTINFO_STORAGE_PUBLIC_BASE_URL  public CDN base URL for artifact links

**Usage**:

```console
$ battinfo ingest publish [OPTIONS] INGEST_ROOT
```

**Arguments**:

* `INGEST_ROOT`: [required]

**Options**:

* `--registry-url TEXT`: Registry base URL. Env: BATTINFO_REGISTRY_URL.
* `--api-key TEXT`: Registry submission API key. Env: BATTINFO_API_KEY.
* `--resource-type TEXT`: Typed ingest subject. Today: cell-instance.  [default: cell-instance]
* `--type-record PATH`: Curated type record path.
* `--manifest PATH`: Optional battinfo.ingest.json path.
* `--workspace-root PATH`: Where to write the authored workspace.
* `--resource-iri TEXT`: Existing BattINFO resource IRI to preserve.
* `--resource-name TEXT`: Human-facing instance label.
* `--workspace-id TEXT`: Workspace id used for bundling/publication.
* `--tenant TEXT`: Optional tenant id recorded in the workspace manifest.
* `--publisher-id TEXT`: Publisher id used for publication.
* `--source-version TEXT`: Submission source version.
* `--license TEXT`: Dataset license to apply.
* `--artifact-base-url TEXT`: Public base URL for packaged artifact files. Env: BATTINFO_STORAGE_PUBLIC_BASE_URL.
* `--platform-url TEXT`: Optional Battery Genome base URL.
* `--api-key-header TEXT`: Registry API key header.  [default: X-Battinfo-API-Key]
* `--timeout-sec FLOAT`: Registry submission timeout in seconds.  [default: 300.0]
* `--force`: Replace the existing workspace root before regenerating it.
* `--validation-policy TEXT`: Validation policy: strict|set|quick.  [default: strict]
* `--process-artifacts`: Convert timeseries CSVs to BDF and generate static/interactive plots. Requires battinfo.
* `--format TEXT`: Output format: json|text.  [default: json]
* `--help`: Show this message and exit.

## `battinfo registry`

Manage registry tenants, workspaces, and publishers.

**Usage**:

```console
$ battinfo registry [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `bootstrap`: Idempotently create a tenant, workspace,...

### `battinfo registry bootstrap`

Idempotently create a tenant, workspace, and publisher on the registry.

Writes the publisher API key to --api-key-file (or BATTINFO_API_KEY_FILE)
when a new publisher is created.  Safe to re-run; existing resources
return HTTP 409 and are silently accepted.


Required env vars (or pass as flags):
  BATTINFO_REGISTRY_URL    registry base URL
  BATTINFO_ADMIN_TOKEN     registry admin token

**Usage**:

```console
$ battinfo registry bootstrap [OPTIONS]
```

**Options**:

* `--tenant-id TEXT`: Tenant id to create or verify.  [default: battinfo]
* `--tenant-name TEXT`: Tenant display name.  [default: BattINFO]
* `--workspace-id TEXT`: Workspace id to create or verify.  [required]
* `--workspace-name TEXT`: Workspace display name (defaults to workspace-id).
* `--publisher-id TEXT`: Publisher id to create or verify.  [required]
* `--publisher-name TEXT`: Publisher display name (defaults to publisher-id).
* `--api-key-file PATH`: File to write the publisher API key to. Env: BATTINFO_API_KEY_FILE.
* `--registry-url TEXT`: Registry base URL. Env: BATTINFO_REGISTRY_URL.
* `--admin-token TEXT`: Registry admin token. Env: BATTINFO_ADMIN_TOKEN.
* `--format TEXT`: Output format: json|text.  [default: text]
* `--help`: Show this message and exit.

## `battinfo dataset`

Contribute measurement datasets: init -&gt; process -&gt; publish.

**Usage**:

```console
$ battinfo dataset [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `init`: Create a new dataset contribution folder...
* `process`: Validate metadata, infer tests from data...
* `publish`: Publish the processed contribution folder.

### `battinfo dataset init`

Create a new dataset contribution folder with template and instructions.


After running this command:
  1. Open battinfo.yaml and fill in the required fields.
  2. Put your CSV data files in the data/ sub-folder.
     Name them: YYYY-MM-DD__testtype__temperature.csv
     e.g. 2026-03-05__ici__25degC.csv
  3. Run:  battinfo dataset process &lt;folder&gt;

**Usage**:

```console
$ battinfo dataset init [OPTIONS] OUTPUT
```

**Arguments**:

* `OUTPUT`: Path for the new contribution folder.  [required]

**Options**:

* `-n, --cell-name TEXT`: Short label for this cell (e.g. serial number).
* `--cell-spec-iri TEXT`: BattINFO cell-spec IRI.
* `--lab TEXT`: Your institution or lab name.
* `--license TEXT`: Data licence identifier.  [default: CC-BY-4.0]
* `--force`: Overwrite an existing folder.
* `--help`: Show this message and exit.

### `battinfo dataset process`

Validate metadata, infer tests from data files, and build the submission package.

Accepts either a single cell folder (with battinfo.yaml) or a batch
folder (with batch.yaml).  When given a batch folder, all cell
sub-folders are processed automatically.

**Usage**:

```console
$ battinfo dataset process [OPTIONS] FOLDER
```

**Arguments**:

* `FOLDER`: [required]

**Options**:

* `--force`: Rebuild from scratch.
* `--validation-policy TEXT`: strict|set|quick  [default: strict]
* `--json`: Emit machine-readable JSON to stdout.
* `--help`: Show this message and exit.

### `battinfo dataset publish`

Publish the processed contribution folder.


Options:
  --zenodo      Upload to Zenodo (creates a draft for your review)
  --sandbox     Use the Zenodo sandbox for testing
  --token       Your Zenodo personal access token
                (or set the ZENODO_TOKEN environment variable)

Get a Zenodo token at:
  https://zenodo.org/account/settings/applications/tokens/new/
  Required scopes: deposit:write

**Usage**:

```console
$ battinfo dataset publish [OPTIONS] FOLDER
```

**Arguments**:

* `FOLDER`: [required]

**Options**:

* `--zenodo`: Publish to Zenodo (creates a draft deposit).
* `--sandbox`: Use the Zenodo sandbox (for testing).
* `--token TEXT`: Zenodo API token. Env: ZENODO_TOKEN.
* `--community TEXT`: Zenodo community identifier.  [default: battery-genome]
* `--no-community`: Skip community submission.
* `--help`: Show this message and exit.

## `battinfo batch`

Scaffold and manage multi-cell batch contributions.

**Usage**:

```console
$ battinfo batch [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `init`: Scaffold a multi-cell batch directory.
* `add`: Add more cells to an existing batch...
* `status`: Show the current state of a batch at a...
* `package`: Build a flat Zenodo upload package from a...
* `upload`: Upload a staged Zenodo package to Zenodo...

### `battinfo batch init`

Scaffold a multi-cell batch directory.


Creates one sub-folder per cell, each with:
  battinfo.yaml   &lt;- pre-filled cell identity and provenance
  data/           &lt;- drop raw CSV/data files here
  photos/         &lt;- optional microscopy or label images


After running this command:
  1. Drop data files into each cell&#x27;s  data/  folder.
     Name them: YYYY-MM-DD__testtype__temperature.csv
     e.g. 2025-06-01__capacity_check__25degC.csv
  2. Edit battinfo.yaml in each cell folder if you have more metadata.
  3. Process each cell:  battinfo dataset process &lt;cell-folder&gt;

**Usage**:

```console
$ battinfo batch init [OPTIONS] OUTPUT_DIR
```

**Arguments**:

* `OUTPUT_DIR`: Directory to create for this batch.  [required]

**Options**:

* `-t, --cell-spec TEXT`: Cell type IRI or name, e.g. &quot;Energizer CR2032&quot;.  [required]
* `-n, --count INTEGER`: Number of cells received.  [required]
* `--batch-id TEXT`: Batch / lot identifier.
* `--lab TEXT`: Institution or lab name.
* `--operator TEXT`: Person who operated the test equipment.
* `--project TEXT`: Project name or ID this batch belongs to.
* `--license TEXT`: SPDX licence identifier.  [default: CC-BY-4.0]
* `--iris TEXT`: Comma-separated list of pre-assigned BattINFO cell IRIs (one per cell).
* `--serials TEXT`: Comma-separated serial numbers (one per cell, used as folder names).
* `--force`: Overwrite an existing output directory.
* `--help`: Show this message and exit.

### `battinfo batch add`

Add more cells to an existing batch directory.


Reads batch.yaml to inherit cell type, lab, operator, and project.
New cells are numbered after the existing ones.
Provide --batch-id / --operator / --project to override for the new cells.
Updates the count in batch.yaml automatically.

**Usage**:

```console
$ battinfo batch add [OPTIONS] BATCH_DIR
```

**Arguments**:

* `BATCH_DIR`: Existing batch directory.  [required]

**Options**:

* `-n, --count INTEGER`: Number of additional cells to add.  [required]
* `--batch-id TEXT`: Override batch / lot ID for the new cells.
* `--lab TEXT`: Override lab name for the new cells.
* `--operator TEXT`: Override operator for the new cells.
* `--project TEXT`: Override project for the new cells.
* `--license TEXT`: Override SPDX licence for the new cells.
* `--iris TEXT`: Comma-separated pre-assigned BattINFO cell IRIs for the new cells.
* `--serials TEXT`: Comma-separated serial numbers for the new cells.
* `--help`: Show this message and exit.

### `battinfo batch status`

Show the current state of a batch at a glance.

Reports how many cells have data, how many are annotated, BDF conversion
status, and what to run next.

**Usage**:

```console
$ battinfo batch status [OPTIONS] BATCH_DIR
```

**Arguments**:

* `BATCH_DIR`: Batch directory.  [required]

**Options**:

* `--json`: Emit machine-readable JSON to stdout.
* `--help`: Show this message and exit.

### `battinfo batch package`

Build a flat Zenodo upload package from a batch of cells.


Discovers all cell sub-folders, collects raw data files, and produces:
  staging/
    battinfo.bundle.json    &lt;- harvest ingestion target
    battinfo.publish.jsonld &lt;- full semantic graph
    ro-crate-metadata.json  &lt;- file inventory with placeholder URLs
    dataset-001.csv         &lt;- raw cycler files (canonical naming)
    dataset-001.bdf.parquet &lt;- BDF converted (if present)
    ...


After packaging, upload with:
  battinfo batch upload &lt;staging-dir&gt; --token $ZENODO_TOKEN --sandbox

**Usage**:

```console
$ battinfo batch package [OPTIONS] BATCH_DIR
```

**Arguments**:

* `BATCH_DIR`: Batch directory created by `batch init`.  [required]

**Options**:

* `-s, --staging PATH`: Output directory for the Zenodo package. Default: &lt;batch-dir&gt;/staging/.
* `-c, --creator TEXT`: Creator: &quot;Family, Given; Affiliation&quot;. Repeat for multiple. Falls back to `battinfo config set creator`.
* `--community TEXT`: Zenodo community. Default: value from config or battinfo-reference.
* `--no-community`: Skip community submission.
* `--placeholder TEXT`: Placeholder token for Zenodo record ID in URLs.  [default: ZENODO_RECORD_ID]
* `--json`: Emit machine-readable JSON to stdout.
* `--help`: Show this message and exit.

### `battinfo batch upload`

Upload a staged Zenodo package to Zenodo (or sandbox).


Workflow:
  1. Creates an empty deposit to obtain the pre-reserved record ID.
  2. Patches placeholder URLs in staged files with the real record ID.
  3. Uploads all files to the deposit.
  4. Sets metadata (title, keywords, community, creators).
  5. Leaves as draft for review, or publishes if --publish is set.


The deposit URL is printed at the end -- open it to review and publish.

**Usage**:

```console
$ battinfo batch upload [OPTIONS] STAGING_DIR
```

**Arguments**:

* `STAGING_DIR`: Staging directory produced by `batch package`.  [required]

**Options**:

* `--token TEXT`: Zenodo API token. Env: ZENODO_API_TOKEN.
* `--sandbox`: Use Zenodo sandbox (sandbox.zenodo.org).
* `--community TEXT`: Zenodo community. Default: value from config or battinfo-reference.
* `--no-community`: Skip community submission.
* `-c, --creator TEXT`: Creator: &quot;Family, Given; Affiliation&quot;. Repeat for multiple. Falls back to `battinfo config set creator`.
* `--publish`: Publish immediately (default: leave as draft).
* `--placeholder TEXT`: Placeholder token used in package.  [default: ZENODO_RECORD_ID]
* `--json`: Emit machine-readable JSON to stdout.
* `--help`: Show this message and exit.

## `battinfo config`

Manage user preferences (creator, license, community).

**Usage**:

```console
$ battinfo config [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `set`: Set a user preference that is applied as...
* `show`: Show current user preferences.

### `battinfo config set`

Set a user preference that is applied as the default across all commands.


Examples:
  battinfo config set creator &quot;Clark, Simon; SINTEF&quot;
  battinfo config set creator &quot;Clark, Simon; SINTEF | Smith, Jane; NTNU&quot;
  battinfo config set license CC-BY-4.0
  battinfo config set community battinfo-reference

**Usage**:

```console
$ battinfo config set [OPTIONS] KEY VALUE
```

**Arguments**:

* `KEY`: Config key: creator, license, community, zenodo_token.  [required]
* `VALUE`: Value to store.  [required]

**Options**:

* `--help`: Show this message and exit.

### `battinfo config show`

Show current user preferences.

**Usage**:

```console
$ battinfo config show [OPTIONS]
```

**Options**:

* `--help`: Show this message and exit.

## `battinfo properties`

Browse valid spec property names and their accepted units.

**Usage**:

```console
$ battinfo properties [OPTIONS] COMMAND [ARGS]...
```

**Options**:

* `--help`: Show this message and exit.

**Commands**:

* `list`: List all valid spec property names with...
* `show`: Show valid units and an example entry for...

### `battinfo properties list`

List all valid spec property names with their accepted units.

**Usage**:

```console
$ battinfo properties list [OPTIONS]
```

**Options**:

* `--category TEXT`: Filter by category (e.g. capacity, voltage, current).
* `--format TEXT`: Output format: table|json.  [default: table]
* `--help`: Show this message and exit.

### `battinfo properties show`

Show valid units and an example entry for a single spec property.

**Usage**:

```console
$ battinfo properties show [OPTIONS] NAME
```

**Arguments**:

* `NAME`: Spec property name (e.g. nominal_capacity).  [required]

**Options**:

* `--format TEXT`: Output format: table|json.  [default: table]
* `--help`: Show this message and exit.
