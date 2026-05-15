# BattINFO Python API

BattINFO currently exposes four practical Python surfaces:

- object-first publication packaging for `CellType -> CellInstance -> TestProtocol -> Test -> Dataset`
- the human-facing `Workspace` helper for linked canonical records, save/query, publish, and release export
- the ingest-first helpers for turning one evidence folder into a linked `Workspace`
- record/query/save helpers from `battinfo.api`

`LocalWorkspace` is related but separate. It is the disk-first release scaffold used
by `battinfo workspace ...` for one publication bundle authored from JSON resource
files on disk.

## Choosing Between `Workspace` and `LocalWorkspace`

- Use `Workspace` for object-first Python authoring when you want to build linked BattINFO records, save them, query them locally, publish JSON-LD, or export a registry-ready release workspace.
- Use `LocalWorkspace` when you want an explicit on-disk workspace contract with `battinfo-workspace.json`, resource JSON files, and the `battinfo workspace validate` and `battinfo workspace bundle` CLI flow.

In short: `Workspace` is the primary Python authoring surface, and
`LocalWorkspace` remains the disk-first submission workflow.

If the user already has an instance folder with photos and CSV datasets, prefer the
ingest-first helpers over hand-building `Workspace` objects. That is the fastest
path for routine intake.

Alpha scope:

- core: publication, canonical record save/query/publish/index helpers, and the alpha walkthrough notebooks
- preview: reusable library workflows beyond the alpha walkthrough fixtures

## Install

```bash
python -m pip install -e .
```

## Ingest-First Intake

Use the ingest helpers when you want one-command registration for a typed
resource instance plus its evidence files.

```python
from battinfo import build_ingest_workspace, publish_ingest_workspace, write_ingest_manifest

write_ingest_manifest(
    r"D:\cell_phone\novonix\google--g20m7--2025--15qnrp",
    resource_type="cell-instance",
    type_record="battinfo-records/records/cell-type/google--g20m7--2025/record.json",
    resource_iri="https://w3id.org/battinfo/cell/15qn-rpd4-xhy7-kx2q",
    publisher_id="demo-lab",
    license="CC-BY-4.0",
)

build = build_ingest_workspace(
    r"D:\cell_phone\novonix\google--g20m7--2025--15qnrp",
    resource_type="cell-instance",
    workspace_id="google-g20m7-instance-demo",
    source_version="demo-2026-04-09",
    artifact_base_url="http://127.0.0.1:8040",
)

published = publish_ingest_workspace(
    r"D:\cell_phone\novonix\google--g20m7--2025--15qnrp",
    resource_type="cell-instance",
    workspace_id="google-g20m7-instance-demo",
    source_version="demo-2026-04-09",
    registry_base_url="https://registry.example.org",
    api_key="...",
    platform_base_url="https://www.battery-genome.org",
)
```

Behavior today:

- the folder-local `battinfo.ingest.json` manifest carries stable ingest metadata
- `resource_type="cell-instance"` is the currently implemented typed ingest subject
- one photo becomes one standalone photo dataset
- one CSV becomes one `Test` plus one `Dataset`
- the first photo dataset becomes the Battery Genome hero image for the cell page
- the returned payload includes the canonical cell id plus registry/platform URLs

Contract note:

- the manifest shape is defined by `docs/ingest-manifest-contract.md`
- runtime validation uses `assets/schemas/ingest-manifest.schema.json`

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

Use `Workspace` directly when you want the primary BattINFO authoring surface and
also need a disk-backed submission workspace or a registry-ready submission
package without instantiating `LocalWorkspace` yourself.

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

Submission note:

- BattINFO-generated submission packages are now transport envelopes around canonical BattINFO records.
- The package still carries workflow and release fields such as `workspace_id`, `publisher_id`, `source_version`, and `publication_intent`.
- BattINFO no longer duplicates lightweight display metadata inside the submission `semantic_payload`; `battinfo-registry` derives normalized page metadata from `battinfo_records`.

Terminology note:

- The BattINFO authoring surface uses `workspace_id`.
- `battinfo-registry` now uses `workspace_id` as well, so the publication boundary is vocabulary-aligned end to end.

Cell-type publish shortcut:

```python
from battinfo import CellType, publish

cell_type = CellType(
    manufacturer="Google",
    model="G20M7",
    format="pouch",
    chemistry="Li-ion",
)

local_result = publish(cell_type, destination="local")
registry_result = publish(
    cell_type,
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
- The existing package-oriented dataset publication helper remains available via `publish(cell_type=..., cell_instance=..., test=..., dataset=...)`.

## Load Cell Types From JSON

If you want to manually define cell types as JSON first, load them directly into
`Workspace`:

```python
from pathlib import Path

from battinfo import Workspace

workspace = Workspace(root=Path(".battinfo/manual-cell-types"))

cell_type = workspace.load_cell_type("cell-type/A123__ANR26650M1-B.json")
more_cell_types = workspace.load_cell_types(directory="cell-type")
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
- Use `setup_demo_environment(...)` to scaffold a repeatable demo workspace and submission package from Python-authored objects.
- Use `run_demo_pipeline(...)` to publish the demo through a registry and optionally verify the Battery Genome `/registry/...` page.
- Use `Workspace.export_release(...)` and `Workspace.build_release(...)` as compatibility aliases.
- Use `load_publication_package(...)` to reconstruct Python objects from the publication package.
- Use `load_publication(...)` as the compatibility alias for the same operation.
- Use `BattinfoBundle.to_directory(...)` only for optional debug inspection bundles.
- Prefer opaque BattINFO IRIs under `https://w3id.org/battinfo/`.
- For validation policy and machine-readable issue output, see `docs/validation-contract.md`.





