# BattINFO Python API

## Where to start

| Goal | Surface to use |
|------|---------------|
| Publish a cell spec or build a linked cell→test→dataset chain from Python objects | [`Workspace`](#workspace-release-export) — the primary authoring surface |
| Turn an existing folder of photos and CSV files into a linked BattINFO submission | [Ingest helpers](#ingest-first-intake) — one-command folder intake |
| Load, query, or save canonical records from disk | [`battinfo.api` helpers](#query-and-save) |
| Author records as JSON files and drive the workflow from the CLI | `LocalWorkspace` — disk-first submission scaffold behind `battinfo workspace ...` |

If you are new here, start with `Workspace`. The [guide notebooks](guides/01-concepts.ipynb)
walk through the full authoring flow end to end.

Scope:
- core: `Workspace`, publication, canonical record save/query/publish/index helpers, and the guide notebooks
- preview: reusable cell-spec library workflows beyond the guide walkthrough fixtures

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
    type_record="battinfo-records/records/cell-spec/google--g20m7--2025/record.json",
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
from pathlib import Path

from battinfo import Cell, CellSpec, Dataset, Test, build_publication_package, load_publication_package

dataset_dir = Path("data/cr2032-run")
dataset_dir.mkdir(parents=True, exist_ok=True)
(dataset_dir / "capacity.csv").write_text("cycle,capacity_ah\n1,0.225\n")

cell_spec = CellSpec(
    manufacturer="Energizer",
    model="CR2032",
    format="coin",
    chemistry="Li-primary",
    size_code="CR2032",
    nominal_voltage={"value": 3.0, "unit": "V"},
)

cell = Cell(
    cell_spec=cell_spec,
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
    path=str(dataset_dir),
    cell=cell,
    test=test,
    name="Energizer CR2032 dataset",
)

report = build_publication_package(
    cell_spec=cell_spec,
    cell_instance=cell,
    test=test,
    dataset=dataset,
)

bundle = load_publication_package(dataset_dir / "battinfo.publish.jsonld")
```

Notes:

- `battinfo.publish.jsonld` remains the foundational Schema.org JSON-LD artifact.
- `ro-crate-metadata.json` is emitted alongside it for RO-Crate alignment.
- `datacite-metadata.json` is emitted alongside it for DataCite-aligned deposit metadata.
- `battinfo.dcat.jsonld` is available as an optional export.
- `CellSpec` is optional provenance support, not required core bundle content.
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
cell_spec = workspace.cell_spec(...)
cell = workspace.cell(cell_spec, ...)
protocol = workspace.test_spec(name="1C Cycle Life at 25 C", kind="cycling", ...)
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

Cell-spec publish shortcut:

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
- The existing package-oriented dataset publication helper remains available via `publish(cell_spec=..., cell_instance=..., test=..., dataset=...)`.

## Load Cell Specs From JSON

If you want to manually define cell specs as JSON first, load them directly into
`Workspace`:

```python
from pathlib import Path

from battinfo import Workspace

workspace = Workspace(root=Path(".battinfo/manual-cell-specs"))

cell_spec = workspace.load_cell_spec("examples/cell-spec/A123__ANR26650M1-B.json")
more_cell_specs = workspace.load_cell_specs(directory="examples/cell-spec")
```

If you want a starter draft file to fill in first, generate one with the API:

```python
from battinfo import template_cell_spec_draft

draft = template_cell_spec_draft(
    manufacturer="A123",
    model_name="ANR26650M1-B",
    chemistry="Li-ion",
    format="cylindrical",
    iec_code="IFpR26650",
)
```

These helpers accept either:

- a simple authoring draft with fields like `manufacturer`, `model`, `format`, `chemistry`, and optional `specs`
- a canonical BattINFO `cell-spec` record with a top-level `cell_spec` object

Draft inputs should omit canonical fields like `id`, `short_id`, and `identifier`.
`Workspace.save()` canonizes those fields and fills default provenance if you did
not provide it.

## Reusable Test Specs

If you want to separate reusable procedures from executed test runs, use
`TestSpec` plus the existing `Test` record:

```python
from battinfo import Workspace

workspace = Workspace(root=".battinfo/test-spec-demo")

protocol = workspace.test_spec(
    name="1C Cycle Life at 25 C",
    kind="cycling",
    version="1.0",
    protocol_url="https://example.org/protocols/cycle-life-1c",
    conditions={"ambient_temperature": {"value": 25.0, "unit": "degC"}},
    experiment=[
        "Charge at 1C until 4.2 V",
        "Discharge at 1C until 2.5 V",
    ],
)

cell_spec = workspace.cell_spec(
    manufacturer="Energizer",
    model="CR2032",
    format="coin",
    chemistry="Li-primary",
)
cell = workspace.cell(cell_spec, serial_number="LAB-001")
test = workspace.test(cell, protocol_ref=protocol, instrument="Biologic VSP-300")
workspace.save()
```

You can also hand-author reusable test-spec JSON first with
`template_test_spec_draft(...)` or load canonical test-spec records with
`Workspace.load_test_spec(...)`.

## Query And Save

The `battinfo.api` helpers remain useful for canonical record workflows:

```python
from battinfo import query_cell_specs, save_cell_instance, template_cell_instance

rows = query_cell_specs(manufacturer="A123", chemistry="LFP", limit=5)

draft = template_cell_instance(cell_spec_id="https://w3id.org/battinfo/spec/3m6k-9t2p-7x4h-9nq8")
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
    "examples/cell-instance/cell-3m6k-9t2p-7x4h-9nq8.json",
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





