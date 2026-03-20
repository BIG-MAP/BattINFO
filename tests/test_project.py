from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import Project, quantity


def _write_csv(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_project_save_open_and_extend_same_cell(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    dataset_a = _write_csv(tmp_path / "inputs" / "cycle-life-a.csv", "cycle,capacity_ah\n0,2.50\n1,2.48\n")
    dataset_b = _write_csv(tmp_path / "inputs" / "cycle-life-b.csv", "cycle,capacity_ah\n2,2.46\n3,2.44\n")

    project = Project(
        project_root,
        name="hello-world",
        title="Hello World Project",
        description="Simple evolving project for BattINFO.",
        tenant="digibatt",
        publisher="demo-lab",
        version="0.1.0",
    )
    cell_type = project.cell_type(
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        size_code="R26650",
        positive_electrode_basis="LFP",
        negative_electrode_basis="graphite",
        specs={"nominal_voltage": quantity(3.3, "V")},
        source_file="a123-anr26650m1-b.manual.json",
    )
    cell = project.cell(
        cell_type,
        serial_number="hello-world-001",
        batch_id="A123-HELLO-01",
        source_type="lab",
    )
    test_a = project.test(
        cell,
        kind="cycle_life",
        protocol="1C charge / 1C discharge",
        instrument="Biologic VSP-300",
        status="completed",
    )
    project.dataset(
        cell,
        title="Cycle life dataset A",
        description="First cycle life dataset.",
        test=test_a,
        path=dataset_a,
        license="CC-BY-4.0",
    )

    save_a = project.save()
    assert save_a["status"] == "ok"
    assert save_a["artifact_count"] == 1
    assert (project_root / "battinfo-project.json").exists()

    reopened = Project.open(project_root)
    assert reopened.name == "hello-world"
    assert reopened.publisher == "demo-lab"
    assert len(reopened.cell_types) == 1
    assert len(reopened.cells) == 1
    assert len(reopened.tests) == 1
    assert len(reopened.datasets) == 1
    assert reopened.datasets[0].test is not None
    assert reopened.datasets[0].cell is not None
    assert Path(str(reopened.datasets[0].dataset_path)).exists()

    test_b = reopened.test(
        reopened.cells[0],
        kind="rate_capability",
        protocol="C/5, 1C, 2C discharge sequence",
        instrument="Arbin LBT-21084",
        status="completed",
    )
    reopened.dataset(
        reopened.cells[0],
        title="Cycle life dataset B",
        description="Second dataset added after reopening.",
        test=test_b,
        path=dataset_b,
        license="CC-BY-4.0",
    )

    save_b = reopened.save()
    assert save_b["status"] == "ok"
    assert save_b["artifact_count"] == 2

    reopened_again = Project.open(project_root)
    assert len(reopened_again.cell_types) == 1
    assert len(reopened_again.cells) == 1
    assert len(reopened_again.tests) == 2
    assert len(reopened_again.datasets) == 2
    assert all(dataset.test is not None for dataset in reopened_again.datasets)
    assert all(dataset.cell is not None for dataset in reopened_again.datasets)
    assert all(Path(str(dataset.dataset_path)).exists() for dataset in reopened_again.datasets)
    assert {Path(str(dataset.dataset_path)).name for dataset in reopened_again.datasets} == {
        "cycle-life-a.csv",
        "cycle-life-b.csv",
    }


def test_project_bundle_writes_registry_intake_for_multi_record_project(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    dataset_a = _write_csv(tmp_path / "inputs" / "hppc-a.csv", "step,voltage_v\n1,3.30\n2,3.12\n")
    dataset_b = _write_csv(tmp_path / "inputs" / "hppc-b.csv", "step,voltage_v\n1,3.28\n2,3.10\n")

    project = Project(
        project_root,
        name="baseline-campaign",
        title="Baseline Campaign",
        description="Multi-record project bundle",
        tenant="digibatt",
        publisher="demo-lab",
        version="1.0.0",
    )
    cell_type = project.cell_type(
        manufacturer="Energizer",
        model="CR2032",
        format="coin",
        chemistry="Li-primary",
        size_code="R2032",
        positive_electrode_basis="MnO2",
        negative_electrode_basis="Li-metal",
        specs={"nominal_voltage": quantity(3.0, "V")},
        source_file="energizer-cr2032.manual.json",
    )
    cell = project.cell(
        cell_type,
        serial_number="cr2032-001",
        batch_id="CR2032-ALPHA",
        source_type="lab",
    )
    test_a = project.test(
        cell,
        kind="capacity_check",
        protocol="0.2 mA constant-current discharge",
        instrument="Biologic VSP-300",
        status="completed",
    )
    project.dataset(
        cell,
        title="Capacity dataset",
        test=test_a,
        path=dataset_a,
        license="CC-BY-4.0",
    )
    test_b = project.test(
        cell,
        kind="hppc",
        protocol="short pulse train",
        instrument="Arbin LBT-21084",
        status="completed",
    )
    project.dataset(
        cell,
        title="Pulse power dataset",
        test=test_b,
        path=dataset_b,
        license="CC-BY-4.0",
    )

    bundle = project.bundle()

    submission_package_path = Path(bundle["submission_package_path"])
    registry_intake_path = Path(bundle["registry_intake_path"])
    validation_report_path = Path(bundle["validation_report_path"])
    normalized_dir = Path(bundle["normalized_dir"])
    assert bundle["status"] == "ok"
    assert submission_package_path.exists()
    assert registry_intake_path.exists()
    assert validation_report_path.exists()
    assert (normalized_dir / "cell-types").is_dir()
    assert (normalized_dir / "cell-instances").is_dir()
    assert (normalized_dir / "tests").is_dir()
    assert (normalized_dir / "datasets").is_dir()

    intake = json.loads(registry_intake_path.read_text(encoding="utf-8"))
    assert intake["kind"] == "BattinfoSubmission"
    assert intake["submission_mode"] == "bundle"
    assert intake["project_id"] == "baseline-campaign"
    assert intake["publisher_id"] == "demo-lab"
    assert intake["workspace"]["registry"] == {"tenant": "digibatt", "project": "baseline-campaign"}
    assert intake["validation"]["ok"] is True
    assert len(intake["resources"]) == 5
    assert len(intake["artifacts"]) == 2

    cell_resources = [item for item in intake["resources"] if item["resource_type"] == "cell"]
    test_resources = [item for item in intake["resources"] if item["resource_type"] == "test"]
    dataset_resources = [item for item in intake["resources"] if item["resource_type"] == "dataset"]
    assert len(cell_resources) == 1
    assert len(test_resources) == 2
    assert len(dataset_resources) == 2
    assert "cell_type" in cell_resources[0]["semantic_payload"]["battinfo_records"]
    cell_local_id = cell_resources[0]["source_local_id"]
    test_related = {item["source_local_id"] for resource in test_resources for item in resource["related_resources"]}
    dataset_related = {item["source_local_id"] for resource in dataset_resources for item in resource["related_resources"] if item["resource_type"] == "cell"}
    assert test_related == {cell_local_id}
    assert dataset_related == {cell_local_id}

    dataset_resource = dataset_resources[0]
    relationships = {item["relationship"] for item in dataset_resource["related_resources"]}
    assert relationships == {"aboutCell", "generatedByTest"}
    test_local_ids = {item["source_local_id"] for item in test_resources}
    assert {item["source_local_id"] for item in dataset_resource["related_resources"] if item["resource_type"] == "test"} <= test_local_ids
    distribution = dataset_resource["distributions"][0]
    assert distribution["package_path"].startswith("artifacts/datasets/")
    assert distribution["access_url"].startswith("file:")
    assert distribution["immutable"] is False


def test_project_bundle_can_emit_single_dataset_submission(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    dataset_file = _write_csv(tmp_path / "inputs" / "cycle-life.csv", "cycle,capacity_ah\n0,2.50\n1,2.48\n")

    project = Project(
        project_root,
        name="hello-world",
        title="Hello World Project",
        tenant="digibatt",
        publisher="demo-lab",
        version="0.1.0",
    )
    cell_type = project.cell_type(
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        size_code="R26650",
        positive_electrode_basis="LFP",
        negative_electrode_basis="graphite",
        specs={"nominal_voltage": quantity(3.3, "V")},
        source_file="a123-anr26650m1-b.manual.json",
    )
    cell = project.cell(cell_type, serial_number="hello-world-001", source_type="lab")
    test = project.test(
        cell,
        kind="cycle_life",
        protocol="1C charge / 1C discharge",
        instrument="Biologic VSP-300",
        status="completed",
    )
    dataset = project.dataset(
        cell,
        title="Cycle life dataset",
        test=test,
        path=dataset_file,
        license="CC-BY-4.0",
    )

    submission = project.bundle(dataset)

    assert Path(submission["submission_package_path"]).exists()
    payload = json.loads(Path(submission["submission_package_path"]).read_text(encoding="utf-8"))
    assert submission["submission_mode"] == "resource"
    assert submission["resource_type"] == "dataset"
    assert submission["resource_count"] == 1
    assert submission["artifact_count"] == 1
    assert payload["submission_mode"] == "resource"
    assert payload["resource"]["resource_type"] == "dataset"
    assert payload["resource"]["related_resources"][0]["resource_type"] == "cell"
    assert payload["resource"]["related_resources"][1]["resource_type"] == "test"
    assert payload["artifacts"][0]["path"].startswith("artifacts/datasets/")


def test_project_bundle_can_emit_single_cell_type_submission(tmp_path: Path) -> None:
    project = Project(
        tmp_path / "project",
        name="cell-library",
        title="Cell Library",
        tenant="digibatt",
        publisher="demo-lab",
        version="0.1.0",
    )
    cell_type = project.cell_type(
        manufacturer="Energizer",
        model="CR2032",
        format="coin",
        chemistry="Li-primary",
        size_code="R2032",
        positive_electrode_basis="MnO2",
        negative_electrode_basis="Li-metal",
        specs={"nominal_voltage": quantity(3.0, "V")},
        source_file="energizer-cr2032.manual.json",
    )

    submission = project.bundle(cell_type)

    assert Path(submission["submission_package_path"]).exists()
    payload = json.loads(Path(submission["submission_package_path"]).read_text(encoding="utf-8"))
    assert submission["submission_mode"] == "resource"
    assert submission["resource_type"] == "cell_type"
    assert submission["artifact_count"] == 0
    assert payload["submission_mode"] == "resource"
    assert payload["resource"]["resource_type"] == "cell_type"
    assert payload["resource"]["semantic_payload"]["battinfo_records"]["cell_type"]["product"]["model"] == "CR2032"
