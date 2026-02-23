# BattINFO Python API (First Draft)

The `battinfo.api` module provides a lightweight Python interface for core workflows:

- query resource libraries
- create canonical records
- publish resolver artifacts
- build/query index summaries

## Install

```bash
python -m pip install -e .
```

## Query

```python
from battinfo.api import query_cell_types, query_cell_instances, query_datasets

cell_types = query_cell_types(
    manufacturer="A123",
    chemistry="LFP",
    nominal_capacity_min=20,
    limit=10,
)

instances = query_cell_instances(has_dataset=True)

datasets = query_datasets(
    related_cell_id="https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8"
)
```

## Create

```python
from battinfo.api import create_cell_type_from_datasheet, create_cell_instance

cell_type = create_cell_type_from_datasheet(
    "assets/examples/cells/A123__ANR26650M1-B.datasheet.json",
    uid="7d9k2m4p8t3x6nq5",
)

cell_instance = create_cell_instance(
    type_id=cell_type["cell_type"]["id"],
    serial_number="LAB-001",  # metadata only
    dataset_id="https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x",
    uid="3m6k9t2p7x4h9nq8",
)
```

You can also instantiate from metadata instead of passing `type_id`:

```python
from battinfo.api import create_cell_instance

cell_instance = create_cell_instance(
    model_name="ANR26650M1-B",
    manufacturer="A123",
    serial_number="LAB-002",
)
```

If metadata matches multiple types, the API raises an error and asks for additional filters or explicit `type_id`.

## Publish

```python
from battinfo.api import publish_record, publish_batch

publish_record(
    "assets/examples/cell-instances/cell-3m6k-9t2p-7x4h-9nq8.json",
    target_root="registry/site",
)

summary = publish_batch(
    source_dirs=[
        "assets/examples/cell-types",
        "assets/examples/cell-instances",
        "assets/examples/datasets",
    ],
    target_root="registry/site",
)
print(summary)
```

`publish_record` writes:

- `index.json`
- `index.jsonld`
- `index.html`

at `registry/site/{entity-type}/{uid}/`.

## Index

```python
from battinfo.api import build_index, index_stats

index = build_index(
    source_root="assets/examples",
    out_path=".battinfo/index.json",
)
print(index["total_count"])

stats = index_stats(".battinfo/index.json")
print(stats)
```

## Identifier Guidance

- Keep canonical identifiers opaque (`https://w3id.org/battinfo/cell-type/{uid}`).
- Do not encode manufacturer/model semantics in IDs.
- Use metadata lookup (`model_name`, `manufacturer`, `chemistry`, etc.) and `short_id` for human workflows.

This preserves persistence while keeping instantiation practical.
