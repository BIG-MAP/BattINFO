# Python API overview

How the Python surface is organized. For the full symbol-by-symbol reference,
see the [generated API reference](pages/api-reference.rst); for the layered
architecture, see [How BattINFO is built](how-battinfo-is-built.md).

## Where to start

| Goal | Surface to use |
|------|---------------|
| Turn lab data into published, linked records | `battinfo.workspace(...)` — the one object for the whole journey |
| Describe a battery product (a datasheet as data) | The `CellSpec` record class + the `publish` shortcut |
| Author research-grade composition (materials, electrodes, electrolyte) | `battinfo.authoring` — see [Tutorial 5](guides/05-descriptors.ipynb) |
| Load, query, save, or resolver-publish canonical records | `battinfo.api` helpers |
| Turn a folder of photos and CSVs into a linked submission | `battinfo.ingest` — one-command folder intake |
| Drive everything from the shell | The `battinfo` CLI — see the [CLI reference](pages/cli-reference.md) |

If you are new here, start with the [tutorials](pages/guides.rst) — six
notebooks that walk the whole story end to end.

The curated top-level namespace (`import battinfo`) exposes the record classes, the
workspace, publishing, and validation — everything else lives in its home
module (`battinfo.api`, `battinfo.authoring`, `battinfo.materials`, ...) and
is documented there.

## The workspace

`battinfo.workspace(root)` is the data-first surface: convert raw cycler
files, register cells, link tests and data, save validated records with
stable IRIs, and publish — to the registry review queue and, with
`zenodo=True`, to a citable DOI.

<!-- doc-snippet: skip -->
```python
import battinfo

ws = battinfo.workspace(".")

ws.convert()                              # raw cycler files → tidy BDF tables
spec = ws.search("samsung inr21700 50e")[0]   # reuse the registry's identity
ws.add("cell", spec=spec, serial_numbers=["S1", "S2"])
ws.add("test", type="cycling", cell="S1", data="bdf/S1.bdf.csv")
ws.save()
ws.publish(note="My cycling campaign, 2026")
```

`ws.quickstart()` prints the full recipe, including login and funding
attribution (`ws.project(...)`, `ws.contributor(...)`).
[Tutorial 3](guides/03-linked-records.ipynb) builds the chain step by step;
[Tutorial 6](guides/06-publish-your-data.ipynb) runs it from a raw cycler
export.

Drafts and templates: `ws.template("cell-spec", ...)` /
`ws.template("test-spec", ...)` write skeleton draft files; `ws.load(path)`
authors them into the session. `ws.load(ws.search(...)[0])` references an
existing registry record instead (reused, never re-published).

## Record classes

`CellSpec`, `Cell`, `TestSpec`, `Test`, and `Dataset` are the record types as
pydantic classes — the single source of truth for authoring and for what is on
disk. For a standalone cell-spec record, `publish` is the shortcut:

```python
from battinfo import CellSpec, publish

cell_spec = CellSpec(
    manufacturer="Google",
    model="G20M7",
    format="pouch",
    chemistry="Li-ion",
)

local_result = publish(cell_spec, destination="local")
registry_result = publish(
    cell_spec,
    destination="registry",
    registry_base_url="https://registry.example.org",
    api_key="...",
    workspace_id="hello-world",
    publisher_id="demo-lab",
)
```

- `destination="local"` writes the canonical BattINFO record and returns its path in `debug_paths`.
- `destination="registry"` also generates the submission package and submits it to `battinfo-registry`.
- `destination="battery-genome"` additionally returns the expected Battery Genome page URL when `platform_base_url` is configured.

## Publication package (record-classes path)

When you hold the four core record objects in Python and want the local publication
artifacts without a workspace, build the package directly:

```python
from pathlib import Path

from battinfo import Cell, CellSpec, Dataset, Test, build_publication_package, load_publication_package

dataset_dir = Path("data/cr2032-run")
dataset_dir.mkdir(parents=True, exist_ok=True)
(dataset_dir / "capacity.csv").write_text("cycle,capacity_ah\n1,0.225\n")

cell_spec = CellSpec(manufacturer="Energizer", model="CR2032", format="coin", chemistry="Li-primary")
cell = Cell(cell_spec=cell_spec, serial_number="energizer-cr2032-202602-dtjrga")
test = Test(cell=cell, kind="capacity_check", protocol="constant current discharging", status="completed")
dataset = Dataset(path=str(dataset_dir), cell=cell, test=test, name="Energizer CR2032 dataset")

report = build_publication_package(
    cell_spec=cell_spec, cell_instance=cell, test=test, dataset=dataset,
)
bundle = load_publication_package(dataset_dir / "battinfo.publish.jsonld")
```

Notes:

- `battinfo.publish.jsonld` is the foundational Schema.org JSON-LD artifact.
- `ro-crate-metadata.json` and `datacite-metadata.json` are emitted alongside it.
- `battinfo.dcat.jsonld` is available as an optional export.

## Query and save (`battinfo.api`)

Canonical-record helpers for scripted workflows:

```python
from battinfo import query_cell_specs, save_cell_instance
from battinfo.api import template_cell_instance

rows = query_cell_specs(manufacturer="A123", chemistry="LFP", limit=5)

draft = template_cell_instance(cell_spec_id="https://w3id.org/battinfo/spec/3m6k-9t2p-7x4h-9nq8")
draft["cell_instance"]["serial_number"] = "LAB-001"

result = save_cell_instance(draft, source_root="examples", resolve_references=False)
```

Draft inputs omit canonical fields like `id`, `short_id`, and `identifier` —
saving canonizes them and fills default provenance.

## Index and resolver publishing (`battinfo.api`)

```python
from battinfo.api import build_index, index_stats, publish_record

publish_record(
    "examples/cell-instance/cell-3m6k-9t2p-7x4h-9nq8.json",
    target_root=".battinfo/resolver-site",
)

index = build_index(source_root="examples", out_path=".battinfo/index.json")
stats = index_stats(".battinfo/index.json")
```

## Ingest-first intake (`battinfo.ingest`)

One-command registration for a typed resource instance plus its evidence
files (photos become photo datasets; CSVs become a `Test` plus a `Dataset`):

```python
from battinfo.ingest import build_ingest_workspace, publish_ingest_workspace, write_ingest_manifest
```

The folder-local `battinfo.ingest.json` manifest carries stable ingest
metadata; its shape is defined by
[the ingest manifest contract](ingest-manifest-contract.md) and validated
against `assets/schemas/ingest-manifest.schema.json`.
`resource_type="cell-instance"` is the currently implemented subject.

## Advanced: the internal engine

`battinfo.workspace(...)` and the record classes are facades over an internal
authoring engine (`battinfo._workspace.Workspace`) that also powers
submission-package export and release workflows. New code should not build on
the engine directly — its surface is large, uncurated, and free to change;
everything the tutorials and this page show goes through the stable facades.
If you maintain older code that imports `Workspace` from `battinfo`, you will
see a deprecation message pointing at the replacement for each call.

## Guidance

- Prefer `battinfo.workspace(...)` for anything that ends in publishing.
- Prefer opaque BattINFO IRIs under `https://w3id.org/battinfo/`.
- For validation policy and machine-readable issue output, see [the validation contract](validation-contract.md).
- For submission-envelope internals, see [the contract explanation page](pages/contract.md).
