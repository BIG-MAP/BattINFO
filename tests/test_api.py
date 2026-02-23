from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import (
    build_index,
    create_cell_instance,
    create_cell_type_from_datasheet,
    index_stats,
    publish_batch,
    publish_record,
    query_cell_instances,
    query_cell_types,
    query_datasets,
    resolve_cell_type_id,
)


def test_query_cell_types_by_manufacturer_and_chemistry() -> None:
    rows = query_cell_types(manufacturer="A123", chemistry="LFP", limit=20)
    assert rows
    assert all(r["manufacturer"] == "A123" for r in rows)
    assert all(r["chemistry"] == "LFP" for r in rows)


def test_query_cell_instances_and_datasets() -> None:
    instances = query_cell_instances(has_dataset=True, limit=10)
    datasets = query_datasets(related_cell_id="https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8", limit=10)
    assert instances
    assert datasets


def test_resolve_cell_type_id_from_metadata() -> None:
    resolved = resolve_cell_type_id(model_name="ANR26650M1-B", manufacturer="A123")
    assert resolved.startswith("https://w3id.org/battinfo/cell-type/")


def test_create_cell_type_and_cell_instance(tmp_path: Path) -> None:
    datasheet = ROOT / "assets" / "examples" / "cells" / "A123__ANR26650M1-B.datasheet.json"
    cell_type = create_cell_type_from_datasheet(datasheet, uid="7d9k2m4p8t3x6nq5")
    assert cell_type["cell_type"]["id"] == "https://w3id.org/battinfo/cell-type/7d9k-2m4p-8t3x-6nq5"

    out_path = tmp_path / "cell-instance.json"
    inst = create_cell_instance(
        type_id=cell_type["cell_type"]["id"],
        uid="3m6k9t2p7x4h9nq8",
        serial_number="LAB-001",
        dataset_id="https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x",
        out_path=out_path,
    )
    assert inst["cell_instance"]["id"] == "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8"
    assert out_path.exists()


def test_publish_record_writes_artifacts(tmp_path: Path) -> None:
    src = ROOT / "assets" / "examples" / "cell-instances" / "cell-3m6k-9t2p-7x4h-9nq8.json"
    result = publish_record(src, target_root=tmp_path)

    out_dir = tmp_path / "cell" / "3m6k-9t2p-7x4h-9nq8"
    assert result["status"] == "published"
    assert out_dir.exists()
    assert (out_dir / "index.json").exists()
    assert (out_dir / "index.jsonld").exists()
    assert (out_dir / "index.html").exists()


def test_publish_batch_summary(tmp_path: Path) -> None:
    summary = publish_batch(
        source_dirs=[
            ROOT / "assets" / "examples" / "cell-types",
            ROOT / "assets" / "examples" / "cell-instances",
            ROOT / "assets" / "examples" / "datasets",
        ],
        target_root=tmp_path,
    )
    assert summary["processed"] >= 3
    assert summary["processed"] == summary["published"] + summary["failed"]
    assert summary["status"] in {"ok", "partial"}


def test_build_index_and_stats(tmp_path: Path) -> None:
    out = tmp_path / "index.json"
    index = build_index(source_root=ROOT / "assets" / "examples", out_path=out)
    assert out.exists()
    assert index["cell_type_count"] >= 1
    assert index["cell_instance_count"] >= 1
    assert index["dataset_count"] >= 1

    stats = index_stats(out)
    assert stats["cell_type_count"] == index["cell_type_count"]
    assert stats["cell_instance_count"] == index["cell_instance_count"]
    assert stats["dataset_count"] == index["dataset_count"]
    assert isinstance(stats["build_timestamp"], str)
