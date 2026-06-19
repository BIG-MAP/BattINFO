from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import (
    build_index,
    query_cell_instances,
    query_cell_specs,
    query_datasets,
    query_tests,
    save_cell_instance,
    save_cell_spec,
    save_dataset,
    save_test,
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_scope_examples_cover_simple_cell_tests_and_dataset_links(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    index_path = tmp_path / ".battinfo" / "index.json"

    cell_spec_doc = _load_json(ROOT / "examples" / "cell-spec" / "A123__ANR26650M1-B.json")
    cell_spec_payload = save_cell_spec(
        cell_spec_doc,
        source_root=source_root,
        resolve_references=False,
        validation_policy="strict",
    )
    assert cell_spec_payload["status"] == "created"

    cell_instance_doc = _load_json(ROOT / "examples" / "cell-instance" / "cell-3m6k-9t2p-7x4h-9nq8.json")
    cell_instance_payload = save_cell_instance(
        cell_instance_doc,
        source_root=source_root,
        resolve_references=False,
        validation_policy="strict",
    )
    assert cell_instance_payload["status"] == "created"

    dataset_doc = _load_json(ROOT / "examples" / "dataset" / "dataset-1f8r-6v2k-9p4m-3t7x.json")
    dataset_payload = save_dataset(
        dataset_doc,
        source_root=source_root,
        resolve_references=False,
        validation_policy="strict",
    )
    assert dataset_payload["status"] == "created"

    test_dir = ROOT / "examples" / "test"
    expected_kinds = {"cycling", "rate_capability", "formation", "hppc", "ici", "gitt", "dcir", "eis"}

    # Only the tests linked to this A123 cell instance (the NMC811 fleet showcase test
    # links to a different instance and is validated by test_cell_fleet).
    a123_cell_id = cell_instance_doc["cell_instance"]["id"]
    for path in sorted(test_dir.glob("*.json")):
        doc = _load_json(path)
        if doc.get("test", {}).get("cell_id") != a123_cell_id:
            continue
        payload = save_test(
            doc,
            source_root=source_root,
            resolve_references=False,
            validation_policy="strict",
        )
        assert payload["status"] == "created"

    build_stats = build_index(
        source_root=source_root,
        out_path=index_path,
        validate=True,
        validation_policy="strict",
    )
    assert build_stats["failed"] == 0
    assert build_stats["cell_spec_count"] == 1
    assert build_stats["cell_instance_count"] == 1
    assert build_stats["test_count"] == 8
    assert build_stats["dataset_count"] == 1
    assert index_path.exists()

    cell_rows = query_cell_specs(
        manufacturer="A123",
        format="cylindrical",
        cell_specs_dir=source_root / "cell-spec",
    )
    assert len(cell_rows) == 1
    assert cell_rows[0]["model_name"] == "ANR26650M1-B"
    assert cell_rows[0]["nominal_capacity"] == 2.5

    instance_rows = query_cell_instances(
        directory=source_root / "cell-instance",
        cell_spec_id=cell_spec_doc["cell_spec"]["id"],
        has_dataset=True,
        dataset_id=dataset_doc["dataset"]["id"],
    )
    assert len(instance_rows) == 1
    assert instance_rows[0]["id"] == cell_instance_doc["cell_instance"]["id"]

    observed_kinds = {row["kind"] for row in query_tests(directory=source_root / "test", cell_id=cell_instance_doc["cell_instance"]["id"])}
    assert expected_kinds.issubset(observed_kinds)

    hppc_rows = query_tests(directory=source_root / "test", kind="hppc", dataset_id=dataset_doc["dataset"]["id"])
    assert len(hppc_rows) == 1

    dataset_rows = query_datasets(
        directory=source_root / "dataset",
        related_cell_id=cell_instance_doc["cell_instance"]["id"],
        related_test_id="https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r",
        format="application/x-hdf5",
    )
    assert len(dataset_rows) == 1
    assert dataset_rows[0]["id"] == dataset_doc["dataset"]["id"]



