# BattINFO Python API

BattINFO currently exposes four practical Python surfaces:

- object-first publication packaging for `CellType -> CellInstance -> TestProtocol -> Test -> Dataset`
- the human-facing `Workspace` helper for linked canonical records, save/query, publish, and release export
- `Project`, a compatibility wrapper around one `Workspace` for project-shaped workflows
- record/query/save helpers from `battinfo.api`

`LocalWorkspace` is related but separate. It is the disk-first release scaffold used
by `battinfo workspace ...` for one publication bundle authored from JSON resource
files on disk.

## Choosing Between `Workspace`, `Project`, and `LocalWorkspace`

- Use `Workspace` for object-first Python authoring when you want to build linked BattINFO records, save them, query them locally, publish JSON-LD, or export a registry-ready release workspace.
- Use `Project` only when you need compatibility with the older project-shaped wrapper API.
- Use `LocalWorkspace` when you want an explicit on-disk workspace contract with `battinfo-workspace.json`, resource JSON files, and the `battinfo workspace validate` and `battinfo workspace bundle` CLI flow.

In short: `Workspace` is now the primary Python authoring surface, `Project` is a
compatibility wrapper over it, and `LocalWorkspace` remains the disk-first submission
workflow.

Alpha scope:

- core: publication, canonical record save/query/publish/index helpers, and the alpha walkthrough notebooks
- preview: reusable library workflows beyond the alpha walkthrough fixtures

## Install

```bash
python -m pip install -e .
```

## Publication Package

The stable publication path is Schema.org JSON-LD first. Build the core object
chain, call `build_publication_package(...)`, then reload with
`load_publication_package(...)`.

```python
from battinfo import CellInstance, CellType, Dataset, Test, build_publication_package, load_publication_package

cell_type = CellType(
    manufacturer="Energizer",
    model="CR2032",
    format="coin",
    chemistry="Li-primary",
    size_code="CR2032",
    nominal_properties={"nominal_voltage": {"value": 3.0, "unit": "V"}},
)

cell = CellInstance(
    cell_type=cell_type,
    serial_number="energizer-cr2032-202602-dtjrga",
)

test = Test(
    cell=cell,
    kind="capacity_check",
    protocol="constant current discharging",
    instrument="short Landt cycler",
    status="completed",
)

dataset = Dataset(
    path="path/to/dataset-dir",
    cell=cell,
    test=test,
    name="Energizer CR2032 dataset",
)

report = build_publication_package(
    cell_type=cell_type,
    cell_instance=cell,
    test=test,
    dataset=dataset,
)

bundle = load_publication_package("path/to/dataset-dir/battinfo.publish.jsonld")
```

Notes:

- `battinfo.publish.jsonld` remains the foundational Schema.org JSON-LD artifact.
- `ro-crate-metadata.json` is emitted alongside it for RO-Crate alignment.
- `datacite-metadata.json` is emitted alongside it for DataCite-aligned deposit metadata.
- `battinfo.dcat.jsonld` is available as an optional export.
- `CellSpecification` is optional provenance support, not required core bundle content.
- `emit_bundle_dir=True` writes the optional debug JSON files under `dataset_dir/battinfo/`.
- `publish_dataset_metadata(...)` is the generic helper for low-plumbing workflows.
- `publish_cr2032_dataset_metadata(...)` is kept as a CR2032 convenience wrapper.

## Workspace Release Export

Use `Workspace` directly when you want a disk-backed submission workspace or a
registry-ready submission package without instantiating `LocalWorkspace`
yourself.

```python
from pathlib import Path

from battinfo import Workspace

workspace = Workspace(root=Path(".battinfo/demo"))
cell_type = workspace.cell_type(...)
cell = workspace.cell(cell_type, ...)
protocol = workspace.test_protocol(name="1C Cycle Life at 25 C", kind="cycle_life", ...)
test = workspace.test(cell, protocol_ref=protocol, ...)
dataset = workspace.dataset(cell, title="Cycle life dataset", test=test, path="data/cycle-life.csv")

workspace.save()
workspace.build_publication_package(dataset)

release = workspace.export_submission_workspace(
    dataset,
    registry="digibatt/hello-world",
    publisher_id="demo-lab",
    version="1.0.0",
)

submission = workspace.build_submission_package(
    dataset,
    registry="digibatt/hello-world",
    publisher_id="demo-lab",
    version="1.0.0",
    root=Path(".battinfo/demo-release"),
)
```

Use `LocalWorkspace` directly only when the disk workspace itself is your source of
truth or when you are driving the `battinfo workspace ...` CLI.

## Load Cell Types From JSON

If you want to manually define cell types as JSON first, load them directly into
`Workspace`:

```python
from pathlib import Path

from battinfo import Workspace

workspace = Workspace(root=Path(".battinfo/manual-cell-types"))

cell_type = workspace.load_cell_type("cell-types/A123__ANR26650M1-B.json")
more_cell_types = workspace.load_cell_types(directory="cell-types")
```

If you want a starter draft file to fill in first, generate one with the API:

```python
from battinfo import template_cell_type_draft

draft = template_cell_type_draft(
    manufacturer="A123",
    model_name="ANR26650M1-B",
    chemistry="Li-ion",
    format="cylindrical",
    iec_code="IFpR26650",
)
```

These helpers accept either:

- a simple authoring draft with fields like `manufacturer`, `model`, `format`, `chemistry`, and optional `specs`
- a canonical BattINFO `cell-type` record with a top-level `product` object

Draft inputs should omit canonical fields like `id`, `short_id`, and `identifier`.
`Workspace.save()` canonizes those fields and fills default provenance if you did
not provide it.

## Reusable Test Protocols

If you want to separate reusable procedures from executed test runs, use
`TestProtocol` plus the existing `Test` record:

```python
from battinfo import Workspace

workspace = Workspace(root=".battinfo/test-protocol-demo")

protocol = workspace.test_protocol(
    name="1C Cycle Life at 25 C",
    kind="cycle_life",
    version="1.0",
    protocol_url="https://example.org/protocols/cycle-life-1c",
    conditions={"ambient_temperature": {"value": 25.0, "unit": "degC"}},
    setpoints={"charge_rate": {"value": 1.0, "unit": "C"}},
)

cell = workspace.cell(workspace.cell_type(...), serial_number="LAB-001")
test = workspace.test(cell, protocol_ref=protocol, instrument="Biologic VSP-300")
workspace.save()
```

You can also hand-author reusable protocol JSON first with
`template_test_protocol_draft(...)` or load canonical protocol records with
`Workspace.load_test_protocol(...)`.

## Query And Save

The `battinfo.api` helpers remain useful for canonical record workflows:

```python
from battinfo import query_cell_types, save_cell_instance, template_cell_instance

rows = query_cell_types(manufacturer="A123", chemistry="LFP", limit=5)

draft = template_cell_instance(type_id="https://w3id.org/battinfo/cell-type/3m6k-9t2p-7x4h-9nq8")
draft["cell_instance"]["serial_number"] = "LAB-001"

result = save_cell_instance(
    draft,
    source_root="examples",
    resolve_references=False,
)
```

Migration note:
- local canonical record writes now use `save*`
- local `register*` names were removed and reserved for future registry communication

## Index And Resolver Publishing

```python
from battinfo import build_index, index_stats, publish_record

publish_record(
    "examples/cell-instances/cell-3m6k-9t2p-7x4h-9nq8.json",
    target_root=".battinfo/resolver-site",
)

index = build_index(source_root="examples", out_path=".battinfo/index.json")
stats = index_stats(".battinfo/index.json")
```

## Guidance

- Use `build_publication_package(...)` for local publication-package generation.
- Use `publish(...)` as the compatibility alias for the same operation.
- Use `Workspace.export_submission_workspace(...)` or `Workspace.build_submission_package(...)` for registry-ready submission handoff from Python workflows.
- Use `Workspace.export_release(...)` and `Workspace.build_release(...)` as compatibility aliases.
- Use `load_publication_package(...)` to reconstruct Python objects from the publication package.
- Use `load_publication(...)` as the compatibility alias for the same operation.
- Use `BattinfoBundle.to_directory(...)` only for optional debug inspection bundles.
- Prefer opaque BattINFO IRIs under `https://w3id.org/battinfo/`.
- For validation policy and machine-readable issue output, see `docs/validation-contract.md`.


