---
orphan: true
---

<!-- This file is INCLUDED at the top of pages/api-reference.rst (the single
     "Python API" reference page); it is not a standalone document. -->

How the Python surface is organized — the generated symbol-by-symbol
reference follows below; for the layered architecture, see
{doc}`How BattINFO is built <../how-battinfo-is-built>`.

## Where to start

| Goal | Surface to use |
|------|---------------|
| Turn lab data into published, linked records | `battinfo.workspace(...)` — the one object for the whole journey |
| Describe a battery product (a datasheet as data) | The `CellSpec` record class + the `publish` shortcut |
| Author research-grade composition (materials, electrodes, electrolyte) | `battinfo.authoring` — see {doc}`Tutorial 5 <../guides/05-descriptors>` |
| Load, query, save, or resolver-publish canonical records | `battinfo.api` helpers |
| Turn a folder of photos and CSVs into a linked submission | `battinfo.ingest` — one-command folder intake |
| Read or write another format (BPX, Battery Data Commons, battdat, protocol files) | `battinfo.interop` importers and exporters |
| Script validation, saving, and publishing from the shell | The `battinfo` CLI — see the {doc}`CLI reference </pages/cli-reference>` |

If you are new here, start with the {doc}`tutorials </pages/guides>` — six
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
ws.add("cell", spec=spec, serial_numbers=["MYLAB-50E-001", "MYLAB-50E-002"])   # serials only your lab uses
ws.add("test", type="cycling", cell="MYLAB-50E-001", data="bdf/MYLAB-50E-001.bdf.csv")
ws.save()
ws.publish(note="My cycling campaign, 2026")
```

`ws.quickstart()` prints the full recipe, including login and funding
attribution (`ws.project(...)`, `ws.contributor(...)`).
{doc}`Tutorial 3 <../guides/03-linked-records>` builds the chain step by step;
{doc}`Tutorial 6 <../guides/06-publish-your-data>` runs it from a raw cycler
export.

Drafts and templates: `ws.template("cell-spec", ...)` /
`ws.template("test-spec", ...)` write skeleton draft files; `ws.load(path)`
authors them into the session. `ws.load(ws.search(...)[0])` references an
existing registry record instead (reused, never re-published).

## Record classes

`CellSpec`, `Cell`, `TestSpec`, `Test`, and `Dataset` are the record types as pydantic classes, written by hand in `bundle.py`. You author records with them, and every save validates the record against the JSON Schema, which is the save-time contract. For a standalone cell-spec record, `publish` is the shortcut:

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

- `publish` takes a `CellSpec` only. A `Cell`, `TestSpec`, `Test` or `Dataset` is saved with `save_cell_instance`, `save_test_spec`, `save_test` or `save_dataset`, which mint its IRI; the "Query and save" section below shows one.
- `destination="local"` writes the canonical BattINFO record and returns its path in `debug_paths`.
- `destination="registry"` also generates the submission package and submits it to `battinfo-registry`.
- `destination="battery-genome"` additionally returns the expected Battery Genome page URL when `platform_base_url` is configured.
- `root=` is the folder the record is built in, by default `.battinfo/publish/<manufacturer>-<model>` under the current folder. `force=True` deletes that folder first and builds it again. It deletes only a folder BattINFO created, which holds a `.battinfo-generated` file, or one built by an earlier version that holds only what BattINFO writes there, down to the file names in `examples/`, `dist/` and its other record and report folders. For any other folder, such as one that also holds a file of yours (a JSON file included), for the `.battinfo` folder where `battinfo.workspace()` keeps a project's records, and for the home or working folder, it raises a `ValueError` (`UnsafeDeleteError`) and deletes nothing. The error names what is in the way.

## Publication package (record-classes path)

When you hold the four core record objects in Python and want the local publication
artifacts without a workspace, build the package directly:

```python
from pathlib import Path

from battinfo import Cell, CellSpec, Dataset, Test, build_publication_package, load_publication_package

dataset_dir = Path("data/cr2032-run")
dataset_dir.mkdir(parents=True, exist_ok=True)
(dataset_dir / "capacity.csv").write_text("cycle,capacity_ah\n1,0.225\n")

cell_spec = CellSpec(manufacturer="Energizer", model="CR2032", format="coin", chemistry="li-mno2", rechargeable=False)
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
- `load_publication_package` reads a package back into the record objects. Units come back as they were written. Of the cell spec's properties it reads the dimensions, mass, nominal capacity and nominal voltage, and it gives the chemistry as `unknown`.

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
{doc}`the ingest manifest contract <../guarantees>` and validated
against `assets/schemas/ingest-manifest.schema.json`.
`resource_type="cell-instance"` is the currently implemented subject.

## Other formats (`battinfo.interop`)

Importers and exporters for formats other tools write: BPX parameter files (`from_bpx_parameters`, `to_bpx`, `upgrade_bpx`, `check_bpx`), Battery Data Commons records (`import_bdc_record`, `to_bdc_record`), battdat datasets (`from_battdat`), BattInfoConverter JSON-LD (`import_converter_jsonld`), Discovery spreadsheets (`import_discovery_xlsx`), the solid-state battery database (`from_solid_state_db_row`), and the aurora-unicycler, bmgen, PyBaMM and UCP protocol formats (`import_aurora_unicycler`, `import_bmgen_jsonld`, `import_pybamm_experiment`, `import_ucp`). An importer returns BattINFO records, or a result object that holds them with warnings naming what it could not read; nothing is saved or published until you do it.

A BPX file becomes one parameter-set record, and `to_bpx` rebuilds the file from it:

```python
from battinfo.interop import from_bpx_parameters, to_bpx

bpx = {
    "Header": {"BPX": "1.1.0", "Title": "Example cell", "Model": "Partial"},
    "Parameterisation": {
        "Cell": {"Nominal cell capacity [A.h]": 5.0, "Electrode area [m2]": 0.1},
        "Negative electrode": {"Particle radius [m]": 5.86e-6, "Thickness [m]": 8.52e-5},
    },
}
result = from_bpx_parameters(bpx)
record = result.to_parameter_set(virtual_cell=True, materials={"negative": "graphite"})
print([part["part"] for part in record["parameter_set"]["parts"]])
print(to_bpx(record).bpx == bpx)  # True
```

{doc}`Publish a BPX parameter file </howto/publish-a-bpx-parameter-file>` takes a file from disk to a published record, and the {doc}`interop scorecard </pages/interop-recovery>` measures how completely BattInfoConverter and Discovery JSON-LD exports reach canonical records.

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
- For validation policy and machine-readable issue output, see {doc}`the validation contract <../guarantees>`.
- For submission-envelope internals, see {doc}`the infrastructure contract <../guarantees>`.
