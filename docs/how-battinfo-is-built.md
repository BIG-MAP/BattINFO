# How BattINFO is built

An orientation map for someone who knows Python, pydantic, and JSON Schema at
a working level and wants to understand how this package fits together —
before reading source code or contributing. Ten minutes, no ontology
background needed.

## The one-paragraph version

BattINFO turns battery data into **plain JSON files with a contract**. You
author records through pydantic models (or a friendlier workspace wrapper);
each record is saved as a JSON file that validates against a canonical JSON
Schema and carries a permanent identifier; a mapping-driven transform can then
render any record as EMMO-aligned JSON-LD for the semantic web. Everything
else in the package — CLI, importers, publishing, registry client — is
plumbing around that pipeline:

```text
your data ──► authoring surface ──► pydantic models ──► JSON records on disk
                                                              │
                                        JSON Schemas validate ┤
                                                              ▼
                                              JSON-LD (EMMO semantics)
                                                              ▼
                                            Zenodo DOI · Battery Genome registry
```

## Two ideas everything follows

**1. Everything is a spec or an instance.** A *spec* is a reusable
description (a cell product's datasheet, a test protocol); an *instance* is a
physical or concrete realization (the cell on your bench, the test you ran
Tuesday). The record types chain into a provenance line:

```text
cell spec ──► cell ──► test ──► dataset        (+ test spec, materials, components…)
```

Every record type is one entry in a single registry
(`src/battinfo/entities.py`): its JSON discriminator key, its schema file, its
on-disk folder, its IRI namespace. Adding a record type means adding one entry
there — every dispatch table in the package derives from it.

**2. The pydantic models are the single source of truth.** There is no
separate "input DTO" layer: `CellSpecification`, `CellInstance`, `Test`,
`TestSpec`, and `Dataset` (in `src/battinfo/bundle.py`) are simultaneously

- the **authoring input** — construct them with flat datasheet-style kwargs
  (`manufacturer=`, `nominal_capacity={"value": 2.5, "unit": "Ah"}`),
- the **validator** — `extra="forbid"` plus did-you-mean errors, so a typo'd
  field teaches instead of disappearing,
- the **serializer** — `to_record()` / `from_record()` convert to and from the
  canonical JSON shape, losslessly.

If you know pydantic, you already know the core of BattINFO.

## The layers, top to bottom

### Authoring surfaces — three doors into the same house

| Surface | Module | For |
|---|---|---|
| `battinfo.workspace(".")` → `ws.convert() / search / add / save / publish` | `ws.py` | People with **data files** — the blessed, data-first path (`ws.quickstart()` prints the recipe) |
| Models + `battinfo.publish(...)` | `bundle.py`, `_publish.py` | People authoring **spec records** directly in Python |
| `battinfo.Workspace` | `_workspace.py` | The object-graph engine underneath: build linked spec/cell/test/dataset objects, then `save()` mints IRIs and writes everything |

The friendly `AuthoringWorkspace` (door 1) delegates to the engine (door 3);
`save_*`/`query_*` functions in `api.py` are the record-file-level operations
all of them share.

### Records on disk — the actual product

A record is one JSON file: a `schema_version`, one discriminator key holding
the body (`"cell_spec": {...}`), and a `provenance` block (which also carries
`battinfo_version`, stamping which library build wrote it). Files live under a
*source root* (`examples/<type>/…` in this repo; `.battinfo/records/…` in a
workspace). IRIs like `https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq8`
are minted **deterministically** from each record's natural identity
(manufacturer :: model :: … for a spec), so re-running an identical ingest
lands on the same files instead of duplicating them.

### Validation — one contract, three consumers

The canonical JSON Schemas (draft 2020-12) live in
`src/battinfo/data/schemas/` and are enforced in three places, each with a CI
drift gate: this package (`validate/` — schema, then semantic rules,
cross-record references, and optional SHACL), the registry's publish gate
(vendored copy), and the browser validator at battinfo.org/validate (vendored
copy compiled with Ajv). Same record, same verdict, everywhere. Details in
[the infrastructure contract](pages/contract.md).

### The semantic layer — mapping tables, not magic

`record_to_jsonld()` (`jsonld.py` + `transform/`) turns a record into
EMMO-aligned JSON-LD. It is **table-driven**: curated mapping files in
`assets/mappings/domain-battery/` say that the key `nominal_capacity` *is*
`emmo:NominalCapacity` and the unit `"Ah"` *is* `emmo:AmpereHour`. The
transform stacks types (a cylindrical LFP cell is simultaneously
`BatteryCell`, `CylindricalBattery`, `LithiumIronPhosphateBattery`) and emits
the canonical EMMO quantity pattern. No inference, no LLMs, no network —
deterministic output from those tables, which is why the website can show
[real before/after pairs](https://battinfo.org/examples) generated at build
time.

Two files carry the EMMO annotations in Python: `bundle_generated.py` is
generated from LinkML schemas and holds IRI metadata; application code never
imports it directly — `bundle_adapter.py` is the one crossing point.

### Getting data in and out — `interop/` and BDF

Importers (`interop/`) accept records from other ecosystems — BPX, PyBaMM
experiments, aurora-unicycler protocols, Battery Data Commons, converter
JSON-LD, spreadsheet exports — as an adoption funnel: express your existing
data in BattINFO first, adopt natively later. Raw cycler files are a separate
concern: `ws.convert()` (backed by the `bdf` package) normalises instrument
exports into one documented table format before any records exist.

### Publishing — the payoff

`publication.py` builds the publication package (schema.org JSON-LD,
RO-Crate, DataCite); `zenodo.py` archives it for a DOI; `api.py`'s registry
client submits records to the Battery Genome registry (staged for curator
review), with retries, a resumable outcome journal, and structured conflict
responses. `ws.publish()` is the one-call wrapper over all of it.

### The CLI — the same functions, spelled differently

`cli.py` is a typer app; every command wraps a function from `api.py` or the
workspace. Nothing exists "only in the CLI", which is why the
[CLI reference](pages/cli-reference.md) can be generated from the app itself.

## Where things live

```text
src/battinfo/
├── bundle.py            the five record models — START HERE
├── entities.py          the record-type registry (one entry per type)
├── ws.py                AuthoringWorkspace: convert/search/add/save/publish
├── _workspace.py        Workspace engine: object graph, finalize, IRI minting
├── api.py               save_*/query_*/template_* + registry client
├── validate/            schema → semantic → references → SHACL layers
├── jsonld.py, transform/  record → EMMO JSON-LD (mapping-table driven)
├── interop/             importers from other ecosystems
├── publication.py, zenodo.py, _publish.py   publication package, DOI, publish()
├── cli.py               typer CLI over the same api functions
├── data/schemas/        the canonical JSON Schemas (the contract)
├── data/examples/       packaged canonical example records
└── bundle_generated.py + bundle_adapter.py   EMMO-annotated schema layer (generated)
```

Supporting cast: `_jsonio.py` (atomic JSON file I/O), `_record_index.py`
(the bulk-save id→path cache), `canonical_aliases.py` (legacy key
normalisation), `testmethod.py` (structured test-method steps),
`metadata.py` (CSVW/DCAT dataset enrichment).

## How it stays correct

The repo leans hard on **generated-and-drift-checked** artifacts: if two
things must agree, one is generated from the other and a test fails when they
diverge. The guide notebooks and doc snippets execute in CI; the website's
hero recipe is asserted against `ws.quickstart()`; the CLI and schema
reference pages regenerate from the code; the registry and website re-vendor
the schemas behind CI gates. When you change behavior, expect a test to point
at every place the story is told — that is by design.

## Where to go next

- **Use it:** [Guide 06 — publish your first dataset](guides/06-publish-your-data.ipynb)
- **Author records:** [Python API tour](python-api.md) · [API reference](pages/api-reference.rst)
- **Build on it:** [the infrastructure contract](pages/contract.md) · [identifier policy](https://github.com/BIG-MAP/BattINFO/blob/main/IDENTIFIER_POLICY.md)
- **Contribute:** [CONTRIBUTING](https://github.com/BIG-MAP/BattINFO/blob/main/CONTRIBUTING.md)
