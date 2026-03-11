from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import (
    CellInstanceInput,
    CellTypeInput,
    DatasetInput,
    TestInput,
    build_index,
    publish_batch,
    register_cell_instance,
    register_cell_type,
    register_dataset,
    register_test,
)


def test_alpha_core_workflow_end_to_end(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    publish_root = tmp_path / "site"
    index_path = tmp_path / ".battinfo" / "index.json"

    cell_type = register_cell_type(
        CellTypeInput(
            uid="3m6k9t2p7x4h9nq8",
            model_name="MN1500",
            manufacturer="Duracell",
            chemistry="Zn-air",
            format="cylindrical",
            source_file="mn1500.json",
        ),
        source_root=source_root,
        validation_policy="strict",
    )
    cell_instance = register_cell_instance(
        CellInstanceInput(
            uid="1f8r6v2k9p4m3t7x",
            type_id=cell_type["id"],
            serial_number="ALPHA-001",
            source_type="lab",
        ),
        source_root=source_root,
        resolve_references=True,
        validation_policy="strict",
    )
    test = register_test(
        TestInput(
            uid="5p7v2n8k4m3t6q9r",
            cell_id=cell_instance["id"],
            name="MN1500 alpha baseline cycling",
            kind="cycle_life",
            source_type="measurement",
        ),
        source_root=source_root,
        resolve_references=True,
        validation_policy="strict",
    )
    dataset = register_dataset(
        DatasetInput(
            uid="8c1h8pk68034vav6",
            title="MN1500 alpha dataset",
            source_type="measurement",
            format="application/x-hdf5",
            related_cell_ids=[cell_instance["id"]],
            related_test_ids=[test["id"]],
        ),
        source_root=source_root,
        resolve_references=True,
        validation_policy="strict",
    )

    publish_summary = publish_batch(
        source_dirs=[
            source_root / "cell-types",
            source_root / "cell-instances",
            source_root / "tests",
            source_root / "datasets",
        ],
        target_root=publish_root,
        validation_policy="publisher",
    )
    assert publish_summary["status"] == "ok"
    assert publish_summary["processed"] == 4
    assert publish_summary["published"] == 4
    assert publish_summary["failed"] == 0

    index = build_index(
        source_root=source_root,
        out_path=index_path,
        validate=True,
        validation_policy="strict",
    )
    assert index["failed"] == 0
    assert index["cell_type_count"] == 1
    assert index["cell_instance_count"] == 1
    assert index["test_count"] == 1
    assert index["dataset_count"] == 1
    assert index_path.exists()

    dataset_uid = dataset["id"].rstrip("/").split("/")[-1]
    published_dataset = publish_root / "dataset" / dataset_uid / "index.jsonld"
    assert published_dataset.exists()
    payload = json.loads(published_dataset.read_text(encoding="utf-8"))
    assert "@id" in payload or "@graph" in payload
