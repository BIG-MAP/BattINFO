# BattINFO agent guide

Read this before you change code in this repository. It says which API to build on, where each kind of truth lives, which files are generated, and which checks CI runs. The pull-request process and the deprecation policy are in [CONTRIBUTING.md](CONTRIBUTING.md).

## What the repository is

BattINFO is a Python package with a CLI (`battinfo`), plus the JSON Schemas and mapping tables behind it. It validates battery metadata written as plain JSON and emits JSON-LD typed with classes from the EMMO domain-battery and domain-electrochemistry ontologies. The ontologies are normative and are not edited here; `battinfo.ttl` pins the versions a release imports.

Package code is in `src/battinfo/`, schemas and mappings in `assets/`, example records in `examples/`, the Sphinx docs in `docs/` and the guide notebooks in `docs/guides/`. `web/` is the battinfo.org site (Next.js), which vendors the schemas, examples and records context.

## Set up and run the checks

The project uses [uv](https://docs.astral.sh/uv/) with a committed `uv.lock`. It needs Python 3.11 or newer, and CI runs 3.11 and 3.12 on Linux and Windows.

```bash
uv sync --all-extras    # .venv from uv.lock, with the dev, docs and feature extras
uv run pytest -q tests
```

These are the commands CI runs (`.github/workflows/ci.yml` and `docs.yml`). Run the ones your change touches before you commit:

```bash
uv run ruff check src tests scripts .tools
uv run mypy
uv run pytest -q tests --cov=battinfo
uv run python .tools/quality/lint_identifier_policy.py
uv run python scripts/sync_examples.py --check
uv run python scripts/assemble_context.py --check
uv run python scripts/gen_context.py --check
uv run python .tools/quality/run_doc_snippets.py
uv run pytest --nbmake docs/guides/ -q
uv run sphinx-build -b html -W --keep-going docs docs/_build/html
```

The test suite runs with sockets disabled (pytest-socket, set in `pyproject.toml`). Mock network calls; a test that really needs the network opts in with `@pytest.mark.enable_socket`. Coverage has to stay at or above the `fail_under` floor in `pyproject.toml`.

The doc-snippets job executes the code blocks of the pages listed in `SNIPPET_FILES` in `.tools/quality/run_doc_snippets.py`. Add a new how-to page to that list, and put `<!-- doc-snippet: skip -->` on the line above any block that cannot run offline. The Sphinx build turns warnings into errors and needs pandoc on the PATH to render the notebooks.

`.tools/quality/run_verification.py` is a shorter acceptance gate: the three acceptance test files, `tests/installed_smoke.py` and a wheel build. Pass `--report-json <path>` for a machine-readable summary. Key paths are also listed in `.tools/agent/manifest.json`, and `tests/test_agent_readiness.py` checks that those paths exist.

## The record model

Every record is one of 22 entity kinds registered in `ENTITY_KINDS` in `src/battinfo/entities.py`. Each kind has a JSON Schema in `assets/schemas/`, a records folder, an IRI namespace and a JSON-LD emitter. Most come in pairs. A spec is the reusable description (a datasheet, a formulation, a protocol); an instance is one physical thing or one event, and it points at its spec.

| Family | Spec kind | Instance kind |
|---|---|---|
| Cell | `cell-spec` | `cell` |
| Test | `test-protocol` | `test` |
| Material | `material-spec` | `material` |
| Electrode | `electrode-spec` | `electrode` |
| Separator | `separator-spec` | `separator` |
| Current collector | `current-collector-spec` | `current-collector` |
| Electrolyte | `electrolyte-spec` | `electrolyte` |
| Housing | `housing-spec` | `housing` |
| Equipment | `equipment-spec` | `equipment`, `channel` |
| Parameter set | `parameter-set` | none |
| Dataset | none | `dataset` |
| Organization | none | `organization` |

A kind has four names and they do not always agree. The physical cell is entity type `cell`, record key `cell_instance`, folder `cell-instance` and IRI namespace `cell/`. The test protocol is entity type `test-protocol` with record key `test_spec`, and users and the CLI call it a test spec (`battinfo template test-spec`, with `test-protocol` kept as a hidden alias). All spec kinds and `parameter-set` mint IRIs under `https://w3id.org/battinfo/spec/`, so never infer a record's type from its IRI; read the record. Instances use their own noun (`cell/`, `material/`, `channel/` and so on).

When code needs to dispatch on record type, derive it from the registry (`kind_for_doc`, `kind_for_type`, `save_entity_path`) rather than writing another hard-coded list.

Identifiers are deterministic. `stable_uid(seed)` turns an identity seed into the dashed 16-character uid, so saving the same cell, material lot or collection twice lands on the same IRI instead of a duplicate. Minting rules, namespaces and reserved segments are governed by `IDENTIFIER_POLICY.md`; CI checks the cell-spec, cell and dataset example IRIs with `lint_identifier_policy.py`.

Every record body may also carry a `handle`, a display slug unique within one registry workspace (`flores-ocv/graphite-aq-1-063b77-cell`). It is not an identifier: renaming never moves an IRI, and code reads structured fields rather than parsing handles. `battinfo.naming` builds handles and titles from structured parts and holds the kind-word table; the rules are in `docs/howto/name-your-records.md`.

The JSON Schema is the save-time contract and the pydantic models in `src/battinfo/bundle.py` are the authoring surface. A schema property the models cannot reach is data a user cannot write, so `tests/test_schema_model_parity.py` checks that every one is reachable. `SCHEMA_VERSION` in the same file is the `schema_version` stamped on every record.

## Which API to build on

`battinfo.workspace(root)` is the authoring API. It returns an `AuthoringWorkspace` from `src/battinfo/ws.py`, and its methods cover the path from raw files to a published record:

- `ws.convert()` turns raw cycler files into BDF tables (needs the `processing` extra).
- `ws.search(...)` finds existing records, and `ws.load(...)` brings one into the session by reference. Given a draft file written by `ws.template(...)`, `ws.load` authors a new cell spec, test spec or equipment spec instead.
- `ws.add(type, ...)` accepts `cell`, `test`, `equipment`, `material_spec`, `material`, `electrode_spec`, `electrode` and `parameter_set`. A test added with `data=` also gets dataset records for its files.
- `ws.save()` validates under the strict policy by default and writes each record to `<root>/.battinfo/records/<folder>/`.
- Set funding, ORCID and licence once with `ws.project(...)`, `ws.contributor(...)` and `ws.license(...)`; `ws.save()` stamps them onto every record.
- `ws.preview_jsonld()` writes the JSON-LD graph a Zenodo deposit would carry and prints the publication checks. `ws.zenodo()` makes the deposit and leaves a draft unless you pass `publish=True`.
- `ws.submit()` sends what the last `ws.save()` wrote to the registry review queue. `ws.publish()` does save and submit in one call, with a Zenodo deposit first when `zenodo=True`.
- `ws.import_(...)` rebuilds a workspace from a published `battinfo.json`, and `ws.export(fmt)` writes the saved records as RDF.

`help(ws.add)` and `ws.commands()` list the rest. A minimal offline session:

```python
import battinfo

ws = battinfo.workspace("lab", registry_url=None)  # None: no registry lookups
spec = battinfo.CellSpec(
    manufacturer="Example Lab", model="R2032 graphite half cell",
    format="coin", chemistry="li-ion",
)
ws.add("cell", spec=spec, serial_numbers=["C01", "C02"])
ws.add("test", type="cycling", cell="C01")
ws.add("material_spec", name="Graphite SLP30", kind="graphite")
ws.save()            # lab/.battinfo/records/<folder>/*.json
ws.preview_jsonld()  # lab/battinfo.preview.jsonld, then the publication checks
```

The default `registry_url` points at the production registry; pass `registry_url=None` whenever a session must stay offline.

A few record types are written outside the workspace. Separators, current collectors, electrolytes and housings go through `battinfo.api.create_component_spec` and `save_component_spec` (and the `*_component_instance` pair), as in `docs/howto/build-a-cell-from-components.md`. Organizations have `battinfo.api.create_organization` and `save_organization`. Datasets that describe files already archived elsewhere, collection members among them, use the `battinfo.Dataset` model with `battinfo.save_dataset`.

For one record without a workspace, use the record models (`CellSpec`, `Cell`, `TestSpec`, `Test`, `Dataset`) with `battinfo.publish(...)`. Detailed cell composition (bill of materials, electrode coatings, electrolyte recipe) is built with the helpers in `battinfo.authoring`, such as `bom`, `electrode`, `electrolyte_recipe` and `separator_spec`.

Do not build on `battinfo.Workspace`. That name is the object-graph engine behind the workspace, now at `battinfo._workspace.Workspace`; the top-level alias warns and is due to be removed one release after 0.8. The curated top level is the `__all__` list in `src/battinfo/__init__.py`. Other names still import from `battinfo` with a `DeprecationWarning` (`_LAZY_EXPORTS`), so new code imports them from their home module, for example `from battinfo.authoring import bom`. Retired class names such as `CellSpecification` resolve through `_DEPRECATED_ALIASES`.

The workspace is for describing and publishing. Reading published data goes through `battinfo.registry.Registry` (`list`, `get`, `links`, `files`, `download`, `read`, `catalog`), which is provisional in 0.8; `docs/howto/read-registry-data.md` shows it in use. Importers and exporters for other formats (BPX, Battery Data Commons, battdat, BattInfoConverter JSON-LD, Discovery, the solid-state database, and the aurora-unicycler, bmgen, PyBaMM and UCP protocol formats) live in `battinfo.interop`.

The CLI also has a folder-based batch path (`battinfo push`, `battinfo batch ...`, `battinfo dataset ...`, code in `src/battinfo/contribution.py`). The README lists it as in development; new work should go through the workspace.

## Dataset collections

A collection is not a separate kind. It is a `dataset` record with `additional_type=["DatasetSeries"]` (a DCAT 3 dataset series), and each member sets `series_id` to the collection's IRI. Code tests for one with `is_dataset_series()` in `src/battinfo/_util.py`. The collection IRI is seeded from its `access_url` and `name`, so both are frozen once published, and the collection has to be saved before its members. `ws.add("test", data=...)` cannot set `series_id`, so members are written with `battinfo.Dataset` and `battinfo.save_dataset`. The worked example is `docs/howto/publish-a-dataset-collection.md`.

## Where IRIs come from

`assets/mappings/domain-battery/property_map.curated.json` maps property keys to EMMO classes and is the source of truth for property IRIs. Units are in `unit_map.curated.json`, controlled values (format, chemistry, cell configuration, electrode basis) in `entity_type_map.json` and materials in `material_map.json`. The `*.candidates.json` files beside them are generated review input. Do not write ontology IRIs as bare strings in business logic.

BattINFO never mints IRIs for scientific concepts (IDENTIFIER_POLICY.md section 14). A quantity or battery class missing from EMMO is added upstream, and until then the value stays in the JSON record and is left out of the RDF with a `semantic.property_unmapped` warning. The upstream queue is `docs/internal/ontology-additions-needed.md`.

Chemistry labels are a two-level vocabulary of 33 electrochemical couples in the `chemistry` section of `entity_type_map.json`. An entry may name a `broader` label (`li-mno2` under `li-metal`). Older spellings marked `alias_of` (`li-primary`, `alkaline`, `znmno2`) still resolve, and validation flags them with `semantic.controlled_value_superseded`. The generated table is in `docs/pages/property-reference.md`. Half cells type as `BatteryHalfCell` and `HalfCellDevice`, never as `ElectrochemicalHalfCell`.

Emitters and the validator use `src/battinfo/data/context/records.context.v1.json`, the bundled copy of `https://w3id.org/battinfo/context/records/v1.json`, generated by `scripts/gen_context.py`. A published context version must keep its meaning: add terms, do not rename or remove them, and put a breaking change in a new v2 file. When an emitter starts stacking a new class, its term has to reach this file (`EMITTER_CLASS_TERMS` in the script), or `tests/test_jsonld_type_guards.py` fails.

`records.context.json` in the same folder is a different file. `scripts/assemble_context.py` builds it from the `slot_uri` declarations in the LinkML modules under `schema/`, and `tests/test_context_property_iris.py` fails if its property terms disagree with the curated property map.

## Naming keys and labels

- Keys are snake_case.
- Processes take the -ing form: `discharging_capacity`, `charging_c_rate`, `minimum_discharging_temperature`. Older spellings such as `discharge_c_rate` are still read, but new keys do not use them.
- Electrodes are positive and negative (`positive_electrode_basis`, `negative_electrode_basis`), never anode and cathode. `anode_sheet_count` and `cathode_sheet_count` in the construction schema are older exceptions; do not add more.
- A key should say what it holds without a glossary. `value_basis` (nominal, measured, rated or conventional) replaced `co_type`, which is still accepted on read.
- A rename keeps the old name working. Python names warn with a `DeprecationWarning` for one release (see CONTRIBUTING.md), old record keys and labels keep resolving, and either way the change gets a `CHANGELOG.md` entry.

## Sources of truth and generated files

Edit the source, then regenerate. A CI step or a test fails when a generated copy drifts.

| Edit | Generated or copied into | How |
|---|---|---|
| `assets/schemas/` | `src/battinfo/data/schemas/` | copy the file; `tests/test_schema_assets_sync.py` compares the trees |
| `assets/mappings/domain-battery/` | `src/battinfo/data/mappings/domain-battery/` | copy the file; `tests/test_mapping_governance.py` compares them |
| `examples/` | `src/battinfo/data/examples/` | `uv run python scripts/sync_examples.py` |
| `schema/*.yaml` (LinkML) | `src/battinfo/data/context/records.context.json` | `uv run python scripts/assemble_context.py` |
| emitter terms | `src/battinfo/data/context/records.context.v1.json` | `uv run python scripts/gen_context.py` |
| `docs/records/_fragments/`, schemas, emitters | `docs/records/*.md` | `uv run python scripts/gen_reference_records.py` |
| CLI commands | `docs/pages/cli-reference.md` | `uv run python scripts/gen_cli_reference.py` |
| mapping tables | `docs/pages/property-reference.md` | `uv run python scripts/gen_property_reference.py` |
| interop importers | `docs/pages/interop-recovery.md` | `uv run python scripts/gen_interop_recovery.py` |
| records context, LinkML schema | `assets/vocab/battinfo-records.ttl` | `uv run python scripts/gen_battinfo_vocab.py` |
| mapping tables, emitter terms | `assets/vocab/emmo-labels.ttl` | `uv run python scripts/gen_emmo_labels.py` |
| examples, emitters | `web/lib/showcase.generated.ts`, `web/lib/jsonld.generated.ts` | `scripts/gen_web_examples.py`, `scripts/gen_web_jsonld.py` |
| schemas, examples, records context | the other `web/lib/*.generated.ts` files | `npm run sync:schemas`, `sync:examples`, `sync:context` in `web/` |

The record-type pages under `docs/records/` run each authoring snippet against the current library and validate the result under the strict policy. A change to a schema, the API or an emitter that alters a reference record must regenerate that chapter in the same commit.

## Where to write

Transient output goes under `.battinfo/` (gitignored) or a test's temporary directory. Do not edit `src/battinfo/data/` by hand except to copy in a changed schema or mapping table, and edit `examples/` only when the task is about the examples themselves. Keep work logs and planning notes out of commits; `WORK_LOG.md` and `CLAUDE.md` are already in `.gitignore`.

## Key source files

| Path | What it holds |
|---|---|
| `src/battinfo/entities.py` | the entity-kind registry and the uid minting primitive |
| `src/battinfo/ws.py` | `battinfo.workspace()` and `AuthoringWorkspace` |
| `src/battinfo/bundle.py` | the record models and `SCHEMA_VERSION` |
| `src/battinfo/api/` | create, save, query, template and resolver-publish functions |
| `src/battinfo/jsonld.py`, `src/battinfo/transform/` | the JSON-LD emitters (`record_to_jsonld`) |
| `src/battinfo/validate/` | schema, semantic, reference, SHACL and publication validation; policies `default`, `strict`, `publisher` and `ingest` |
| `src/battinfo/registry.py` | the registry reader |
| `src/battinfo/interop/` | importers and exporters for external formats |
| `src/battinfo/cli.py` | the `battinfo` CLI |
| `src/battinfo/contribution.py` | the CLI batch path behind `battinfo push` |
