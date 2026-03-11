# BattINFO Python API

BattINFO currently exposes two practical Python surfaces:

- object-first publication for `CellType -> CellInstance -> Test -> Dataset`
- record/query/registration helpers from `battinfo.api`

Alpha scope:

- core: publication, canonical record registration/query/publish/index helpers
- preview: reusable library and notebook-driven exploratory workflows

## Install

```bash
python -m pip install -e .
```

## Publication

The stable publication path is JSON-LD-first. Build the core object chain, call
`publish(...)`, then reload with `load_publication(...)`.

```python
from battinfo import CellInstance, CellType, Dataset, Test, load_publication, publish

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

report = publish(
    cell_type=cell_type,
    cell_instance=cell,
    test=test,
    dataset=dataset,
)

bundle = load_publication("path/to/dataset-dir/battinfo.publish.jsonld")
```

Notes:

- `battinfo.publish.jsonld` is the portable artifact.
- `CellSpecification` is optional provenance support, not required core bundle content.
- `emit_bundle_dir=True` writes the optional debug JSON files under `dataset_dir/battinfo/`.
- `publish_dataset_metadata(...)` is the generic helper for low-plumbing workflows.
- `publish_cr2032_dataset_metadata(...)` is kept as a CR2032 convenience wrapper.

## Query And Registration

The `battinfo.api` helpers remain useful for canonical record workflows:

```python
from battinfo import query_cell_types, register_cell_instance, template_cell_instance

rows = query_cell_types(manufacturer="A123", chemistry="LFP", limit=5)

draft = template_cell_instance(type_id="https://w3id.org/battinfo/cell-type/3m6k-9t2p-7x4h-9nq8")
draft["cell_instance"]["serial_number"] = "LAB-001"

result = register_cell_instance(
    draft,
    source_root="assets/examples",
    resolve_references=False,
)
```

## Index And Resolver Publishing

```python
from battinfo import build_index, index_stats, publish_record

publish_record(
    "assets/examples/cell-instances/cell-3m6k-9t2p-7x4h-9nq8.json",
    target_root=".battinfo/resolver-site",
)

index = build_index(source_root="assets/examples", out_path=".battinfo/index.json")
stats = index_stats(".battinfo/index.json")
```

## Guidance

- Use `publish(...)` for dataset publication.
- Use `load_publication(...)` to reconstruct Python objects from published JSON-LD.
- Use `BattinfoBundle.to_directory(...)` only for optional debug inspection bundles.
- Prefer opaque BattINFO IRIs under `https://w3id.org/battinfo/`.
- For validation policy and machine-readable issue output, see `docs/validation-contract.md`.
