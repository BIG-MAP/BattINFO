from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import (
    CellSpecificationInput,
    CellInstanceInput,
    CellTypeInput,
    DatasetInput,
    TestInput,
    build_cell_type_library_rdf,
    build_index,
    create_cell_instance,
    create_cell_type_from_datasheet,
    index_stats,
    publish_batch,
    publish_record,
    query_cell_instances,
    query_library_cell_types,
    query_tests,
    query_cell_types,
    query_datasets,
    register_batch,
    register_cell_instance,
    register_cell_type,
    register_dataset,
    register_library_cell_type,
    register_record,
    register_test,
    resolve_cell_type_id,
    template_cell_specification,
    template_cell_instance,
    template_cell_type,
    template_dataset,
    template_test,
)
from battinfo.validate import validate_references_report


def test_query_cell_types_by_manufacturer_and_chemistry() -> None:
    rows = query_cell_types(manufacturer="A123", chemistry="LFP", limit=20)
    assert rows
    assert all(r["manufacturer"] == "A123" for r in rows)
    assert all(r["chemistry"] == "LFP" for r in rows)


def test_query_cell_instances_and_datasets() -> None:
    instances = query_cell_instances(has_dataset=True, limit=10)
    datasets = query_datasets(related_cell_id="https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8", limit=10)
    tests = query_tests(cell_id="https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8", limit=10)
    assert instances
    assert datasets
    assert tests


def test_resolve_cell_type_id_from_metadata() -> None:
    resolved = resolve_cell_type_id(model_name="ANR26650M1-B", manufacturer="A123")
    assert resolved.startswith("https://w3id.org/battinfo/cell-type/")


def test_create_cell_type_and_cell_instance(tmp_path: Path) -> None:
    datasheet = ROOT / "assets" / "datasheets" / "cell-types" / "pvn1-43h7-rm3e-mjqq.datasheet.json"
    cell_type = create_cell_type_from_datasheet(datasheet, uid="7d9k2m4p8t3x6nq5")
    assert cell_type["product"]["id"] == "https://w3id.org/battinfo/cell-type/7d9k-2m4p-8t3x-6nq5"

    out_path = tmp_path / "cell-instance.json"
    inst = create_cell_instance(
        type_id=cell_type["product"]["id"],
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
            ROOT / "assets" / "examples" / "tests",
            ROOT / "assets" / "examples" / "datasets",
        ],
        target_root=tmp_path,
    )
    assert summary["processed"] >= 4
    assert summary["processed"] == summary["published"] + summary["failed"]
    assert summary["status"] in {"ok", "partial"}


def test_build_index_and_stats(tmp_path: Path) -> None:
    out = tmp_path / "index.json"
    index = build_index(source_root=ROOT / "assets" / "examples", out_path=out)
    assert out.exists()
    assert index["cell_type_count"] >= 1
    assert index["cell_instance_count"] >= 1
    assert index["test_count"] >= 1
    assert index["dataset_count"] >= 1

    stats = index_stats(out)
    assert stats["cell_type_count"] == index["cell_type_count"]
    assert stats["cell_instance_count"] == index["cell_instance_count"]
    assert stats["test_count"] == index["test_count"]
    assert stats["dataset_count"] == index["dataset_count"]
    assert isinstance(stats["build_timestamp"], str)


def test_build_index_validate_catches_reference_errors(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    cell_instances_dir = source_root / "cell-instances"
    cell_instances_dir.mkdir(parents=True)
    bad_cell_instance = {
        "schema_version": "0.1.0",
        "cell_instance": {
            "id": "https://w3id.org/battinfo/cell/1f8r-6v2k-9p4m-3t7x",
            "type_id": "https://w3id.org/battinfo/cell-type/eysh-4h5s-k4bx-zkgg",
            "short_id": "1f8r6v",
        },
        "provenance": {
            "source_type": "measurement",
            "retrieved_at": 1771804800,
        },
    }
    (cell_instances_dir / "cell-1f8r-6v2k-9p4m-3t7x.json").write_text(
        json.dumps(bad_cell_instance, indent=2),
        encoding="utf-8",
    )

    index = build_index(source_root=source_root, validate=True)
    assert index["failed"] == 1
    assert "Referenced cell_type not found" in index["failures"][0]["error"]


def test_register_resource_drafts_and_duplicate_policy(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"

    cell_type_payload = register_cell_type(
        CellTypeInput(
            uid="3m6k9t2p7x4h9nq8",
            model_name="MN1500",
            manufacturer="Duracell",
            chemistry="Zn-air",
            format="cylindrical",
            source_file="manual-mn1500.json",
        ),
        source_root=source_root,
    )
    assert cell_type_payload["status"] == "created"
    assert cell_type_payload["id"].startswith("https://w3id.org/battinfo/cell-type/")

    exists_payload = register_cell_type(
        CellTypeInput(
            uid="3m6k9t2p7x4h9nq8",
            model_name="MN1500",
            manufacturer="Duracell",
            chemistry="Zn-air",
            format="cylindrical",
            source_file="manual-mn1500.json",
        ),
        source_root=source_root,
        duplicate_policy="return_existing",
    )
    assert exists_payload["status"] == "exists"

    cell_instance_payload = register_cell_instance(
        CellInstanceInput(
            uid="1f8r6v2k9p4m3t7x",
            type_id=cell_type_payload["id"],
            serial_number="LAB-001",
            source_type="lab",
        ),
        source_root=source_root,
        resolve_references=True,
    )
    assert cell_instance_payload["status"] == "created"

    test_payload = register_test(
        TestInput(
            uid="5p7v2n8k4m3t6q9r",
            cell_id=cell_instance_payload["id"],
            name="Duracell MN1500 baseline cycling",
            kind="cycle_life",
            source_type="measurement",
        ),
        source_root=source_root,
        resolve_references=True,
    )
    assert test_payload["status"] == "created"

    dataset_payload = register_dataset(
        DatasetInput(
            uid="8c1h8pk68034vav6",
            title="Duracell MN1500 cycling",
            source_type="measurement",
            related_cell_ids=[cell_instance_payload["id"]],
            related_test_ids=[test_payload["id"]],
            format="application/x-hdf5",
        ),
        source_root=source_root,
        resolve_references=True,
    )
    assert dataset_payload["status"] == "created"
    assert dataset_payload["id"].startswith("https://w3id.org/battinfo/dataset/")


def test_register_cell_instance_missing_reference_raises(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    with pytest.raises(ValueError):
        register_cell_instance(
            CellInstanceInput(
                uid="eysh4h5sk4bxzkgg",
                type_id="https://w3id.org/battinfo/cell-type/pvn1-43h7-rm3e-mjqq",
                source_type="measurement",
            ),
            source_root=source_root,
            resolve_references=True,
        )


def test_register_record_dry_run(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    dry_run_payload = register_record(
        {
            "schema_version": "0.1.0",
            "dataset": {
                "id": "https://w3id.org/battinfo/dataset/87fr-c4vr-wfyh-21td",
                "identifier": "dataset:87fr-c4vr-wfyh-21td",
                "name": "Dry-run dataset",
                "url": "https://example.org/dataset/87fr-c4vr-wfyh-21td",
            },
            "provenance": {
                "source_type": "other",
                "retrieved_at": 1771804800,
            },
        },
        source_root=source_root,
        resolve_references=False,
        dry_run=True,
    )
    assert dry_run_payload["status"] == "dry-run"
    assert not (source_root / "datasets" / "dataset-87fr-c4vr-wfyh-21td.json").exists()


def test_register_record_rejects_invalid_dataset_url_format(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    with pytest.raises(ValueError, match="Schema validation failed"):
        register_record(
            {
                "schema_version": "0.1.0",
                "dataset": {
                    "id": "https://w3id.org/battinfo/dataset/87fr-c4vr-wfyh-21td",
                    "identifier": "dataset:87fr-c4vr-wfyh-21td",
                    "name": "Bad dataset URL",
                    "url": "not-a-uri",
                },
                "provenance": {
                    "source_type": "other",
                    "retrieved_at": 1771804800,
                },
            },
            source_root=source_root,
            resolve_references=False,
            dry_run=True,
        )


def test_register_record_strict_policy_rejects_semantic_issue(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    with pytest.raises(ValueError, match="short_id"):
        register_record(
            {
                "schema_version": "0.1.0",
                "test": {
                    "id": "https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r",
                    "short_id": "xxxxxx",
                    "identifier": "test:5p7v-2n8k-4m3t-6q9r",
                    "cell_id": "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8",
                    "name": "Semantic failure",
                    "kind": "cycle_life",
                },
                "provenance": {
                    "source_type": "measurement",
                    "retrieved_at": 1771804800,
                },
            },
            source_root=source_root,
            resolve_references=False,
            validation_policy="strict",
            dry_run=True,
        )


def test_register_cell_instance_rejects_reference_with_wrong_record_type(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    dataset_payload = register_dataset(
        DatasetInput(
            uid="8c1h8pk68034vav6",
            title="Dataset only",
            source_type="measurement",
            format="application/x-hdf5",
        ),
        source_root=source_root,
        resolve_references=False,
    )
    report = validate_references_report(
        {
            "schema_version": "0.1.0",
            "cell_instance": {
                "id": "https://w3id.org/battinfo/cell/1f8r-6v2k-9p4m-3t7x",
                "identifier": "cell:1f8r-6v2k-9p4m-3t7x",
                "type_id": dataset_payload["id"],
            },
            "provenance": {
                "source_type": "measurement",
            },
        },
        source_root,
    )
    assert not report.ok
    assert report.errors[0].code == "reference.type_mismatch"
    assert "cell_type" in report.errors[0].message


def test_register_batch_summary_and_partial(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"
    batch_root = tmp_path / "batch"
    cell_types_dir = batch_root / "cell-types"
    cell_instances_dir = batch_root / "cell-instances"
    tests_dir = batch_root / "tests"
    datasets_dir = batch_root / "datasets"
    cell_types_dir.mkdir(parents=True)
    cell_instances_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    datasets_dir.mkdir(parents=True)

    cell_type_record = template_cell_type(
        manufacturer="Duracell",
        model_name="MN1500",
        chemistry="Zn-air",
        format="cylindrical",
        uid="3m6k9t2p7x4h9nq8",
    )
    cell_type_path = cell_types_dir / "cell-type.json"
    cell_type_path.write_text(json.dumps(cell_type_record, indent=2), encoding="utf-8")

    cell_instance_record = template_cell_instance(
        type_id=cell_type_record["product"]["id"],
        source_type="lab",
        uid="1f8r6v2k9p4m3t7x",
    )
    cell_instance_path = cell_instances_dir / "cell-instance.json"
    cell_instance_path.write_text(json.dumps(cell_instance_record, indent=2), encoding="utf-8")

    test_record = template_test(
        cell_id=cell_instance_record["cell_instance"]["id"],
        name="MN1500 baseline cycling",
        kind="cycle_life",
        source_type="measurement",
        uid="5p7v2n8k4m3t6q9r",
    )
    test_path = tests_dir / "test.json"
    test_path.write_text(json.dumps(test_record, indent=2), encoding="utf-8")

    dataset_record = template_dataset(
        title="MN1500 dataset",
        source_type="measurement",
        uid="8c1h8pk68034vav6",
        related_cell_ids=[cell_instance_record["cell_instance"]["id"]],
        related_test_ids=[test_record["test"]["id"]],
    )
    dataset_path = datasets_dir / "dataset.json"
    dataset_path.write_text(json.dumps(dataset_record, indent=2), encoding="utf-8")

    summary = register_batch(
        source_dirs=[cell_types_dir, cell_instances_dir, tests_dir, datasets_dir],
        source_root=source_root,
        resolve_references=True,
    )
    assert summary["status"] == "ok"
    assert summary["processed"] == 4
    assert summary["created"] == 4
    assert summary["failed"] == 0

    idempotent = register_batch(
        source_dirs=[cell_types_dir, cell_instances_dir, tests_dir, datasets_dir],
        source_root=source_root,
        duplicate_policy="return_existing",
        resolve_references=True,
    )
    assert idempotent["status"] == "ok"
    assert idempotent["exists"] == 4
    assert idempotent["failed"] == 0

    bad_path = cell_types_dir / "bad.json"
    bad_path.write_text('{"not_a_resource": true}', encoding="utf-8")
    partial = register_batch(
        source_dirs=[cell_types_dir],
        source_root=source_root,
        duplicate_policy="return_existing",
        resolve_references=False,
    )
    assert partial["status"] == "partial"
    assert partial["failed"] == 1
    assert partial["failures"][0]["file"].endswith("bad.json")


def test_template_builders_are_registerable(tmp_path: Path) -> None:
    source_root = tmp_path / "examples"

    cell_type_record = template_cell_type(
        manufacturer="Duracell",
        model_name="MN1500",
        chemistry="Zn-air",
        format="cylindrical",
        uid="3m6k9t2p7x4h9nq8",
    )
    reg_type = register_record(cell_type_record, source_root=source_root, resolve_references=False)
    assert reg_type["status"] == "created"

    cell_instance_record = template_cell_instance(
        type_id=cell_type_record["product"]["id"],
        source_type="lab",
        uid="1f8r6v2k9p4m3t7x",
    )
    reg_cell = register_record(cell_instance_record, source_root=source_root, resolve_references=True)
    assert reg_cell["status"] == "created"

    test_record = template_test(
        cell_id=cell_instance_record["cell_instance"]["id"],
        name="MN1500 baseline cycling",
        kind="cycle_life",
        source_type="measurement",
        uid="5p7v2n8k4m3t6q9r",
    )
    reg_test = register_record(test_record, source_root=source_root, resolve_references=True)
    assert reg_test["status"] == "created"

    dataset_record = template_dataset(
        title="MN1500 dataset",
        source_type="measurement",
        uid="8c1h8pk68034vav6",
        related_cell_ids=[cell_instance_record["cell_instance"]["id"]],
        related_test_ids=[test_record["test"]["id"]],
    )
    reg_dataset = register_record(dataset_record, source_root=source_root, resolve_references=True)
    assert reg_dataset["status"] == "created"


def test_register_query_and_build_library_cell_type(tmp_path: Path) -> None:
    library_root = tmp_path / "library" / "cell-types"
    packaged_root = tmp_path / "package" / "cell-types"
    rdf_root = tmp_path / "library-rdf" / "cell-types"
    aggregate_jsonld = tmp_path / "ontology" / "library" / "cell-types.jsonld"
    manifest_json = tmp_path / "library-rdf" / "cell-types.index.json"

    payload = register_library_cell_type(
        CellSpecificationInput(
            uid="9qfb4wrnynwcayjw",
            manufacturer="A123",
            model="ANR26650M1-B",
            format="cylindrical",
            chemistry="Li-ion",
            positive_electrode_basis="LFP",
            negative_electrode_basis="graphite",
            size_code="R26650",
            property={
                "nominal_capacity": {"typical_value": 2.5, "unit": "Ah"},
                "nominal_voltage": {"value": 3.3, "unit": "V"},
            },
            source_type="datasheet",
            source_file="A123__ANR26650M1-B.pdf",
        ),
        library_root=library_root,
        package_root=packaged_root,
    )
    assert payload["status"] == "created"
    assert Path(payload["path"]).exists()
    assert Path(payload["package_path"]).exists()
    assert payload["synced_package"] is True

    duplicate = register_library_cell_type(
        CellSpecificationInput(
            uid="9qfb4wrnynwcayjw",
            manufacturer="A123",
            model="ANR26650M1-B",
            format="cylindrical",
            chemistry="Li-ion",
            positive_electrode_basis="LFP",
            negative_electrode_basis="graphite",
            source_file="A123__ANR26650M1-B.pdf",
        ),
        library_root=library_root,
        package_root=packaged_root,
        duplicate_policy="return_existing",
    )
    assert duplicate["status"] == "exists"

    rows = query_library_cell_types(
        manufacturer="A123",
        chemistry="Li-ion",
        nominal_capacity_min=2.4,
        nominal_voltage_max=3.4,
        directory=library_root,
    )
    assert len(rows) == 1
    assert rows[0]["model"] == "ANR26650M1-B"
    assert rows[0]["nominal_capacity"] == 2.5

    build_result = build_cell_type_library_rdf(
        input_dir=library_root,
        output_jsonld_dir=rdf_root,
        aggregate_jsonld=aggregate_jsonld,
        manifest_json=manifest_json,
    )
    assert build_result["status"] == "ok"
    assert build_result["entry_count"] == 1
    assert aggregate_jsonld.exists()
    assert manifest_json.exists()
    assert (rdf_root / "A123__ANR26650M1-B.jsonld").exists()

    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    assert manifest["entry_count"] == 1
    assert manifest["entries"][0]["manufacturer"] == "A123"


def test_template_cell_specification_is_registerable(tmp_path: Path) -> None:
    library_root = tmp_path / "library" / "cell-types"
    packaged_root = tmp_path / "package" / "cell-types"

    record = template_cell_specification(
        manufacturer="Energizer",
        model="CR2032",
        chemistry="Li-primary",
        format="coin",
        positive_electrode_basis="MnO2",
        negative_electrode_basis="Li-metal",
        uid="7r2m4q8vk6ntc3pj",
    )
    payload = register_library_cell_type(
        record,
        library_root=library_root,
        package_root=packaged_root,
    )
    assert payload["status"] == "created"
    stored = json.loads(Path(payload["path"]).read_text(encoding="utf-8"))
    assert stored["specification"]["model"] == "CR2032"
