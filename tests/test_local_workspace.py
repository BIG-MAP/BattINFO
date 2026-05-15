from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import BatteryCell, BatteryCellType, BatteryTestType, BattinfoBundle, Dataset, Test, publish, quantity
from battinfo.cli import app
from battinfo.local_workspace import WORKSPACE_FILENAME, LocalWorkspace


def _build_sample_objects(tmp_path: Path) -> tuple[BatteryCellType, BatteryCell, Test, Dataset]:
    dataset_file = tmp_path / "inputs" / "a123-cycle-life.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text(
        "cycle_index,capacity_ah,voltage_v\n0,2.50,3.30\n1,2.48,3.28\n",
        encoding="utf-8",
    )
    cell_design = BatteryCellType(
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        size_code="R26650",
        positive_electrode_basis="LFP",
        negative_electrode_basis="unknown",
        nominal_capacity=quantity(2.5, "Ah"),
        nominal_voltage=quantity(3.3, "V"),
        source={"file": "a123-manual.json"},
    )
    cell = BatteryCell(
        cell_design,
        serial_number="hello-world-001",
        batch_id="A123-HELLO-01",
        source={"type": "lab"},
    )
    test = Test(
        cell,
        test_type=BatteryTestType.CYCLE_LIFE,
        protocol={"name": "1C charge / 1C discharge"},
        instrument="Biologic VSP-300",
        status="completed",
    )
    dataset = Dataset(
        dataset_file,
        test=test,
        data_format="text/csv",
        license="CC-BY-4.0",
        name="A123 hello world cycling dataset",
        description="Small sandbox dataset created by the BattINFO hello world notebook.",
    )
    return cell_design, cell, test, dataset


def test_workspace_cli_init_validate_bundle_happy_path(tmp_path: Path) -> None:
    runner = CliRunner()
    workspace_dir = tmp_path / "my-release"

    init_result = runner.invoke(app, ["workspace", "init", str(workspace_dir), "--format", "json"])
    assert init_result.exit_code == 0, init_result.stdout
    init_payload = json.loads(init_result.stdout)
    assert init_payload["status"] == "initialized"
    assert (workspace_dir / WORKSPACE_FILENAME).exists()

    validate_result = runner.invoke(app, ["workspace", "validate", str(workspace_dir), "--format", "json"])
    assert validate_result.exit_code == 0, validate_result.stdout
    validate_payload = json.loads(validate_result.stdout)
    assert validate_payload["ok"] is True
    assert validate_payload["error_count"] == 0
    assert (workspace_dir / "dist" / "validation-report.json").exists()

    bundle_result = runner.invoke(app, ["workspace", "bundle", str(workspace_dir), "--format", "json"])
    assert bundle_result.exit_code == 0, bundle_result.stdout
    bundle_payload = json.loads(bundle_result.stdout)
    assert bundle_payload["status"] == "ok"

    registry_intake_path = workspace_dir / "dist" / "registry-intake.json"
    submission_package_path = workspace_dir / "dist" / "submission-package.json"
    zenodo_metadata_path = workspace_dir / "dist" / "zenodo-metadata.json"
    normalized_dir = workspace_dir / "dist" / "normalized"
    assert submission_package_path.exists()
    assert registry_intake_path.exists()
    assert zenodo_metadata_path.exists()
    assert (normalized_dir / "cell-type" / "cell-type.json").exists()
    assert (normalized_dir / "cell-instances" / "cell.json").exists()
    assert (normalized_dir / "tests" / "test.json").exists()
    assert (normalized_dir / "dataset" / "dataset.json").exists()
    normalized_dataset = json.loads((normalized_dir / "dataset" / "dataset.json").read_text(encoding="utf-8"))
    assert normalized_dataset["provenance"]["citation"] == "https://doi.org/10.5281/zenodo.1234567"

    registry_intake = json.loads(registry_intake_path.read_text(encoding="utf-8"))
    assert registry_intake["kind"] == "BattinfoSubmission"
    assert registry_intake["submission_mode"] == "bundle"
    assert registry_intake["workspace_id"] == "cr2032-baseline"
    assert registry_intake["publisher_id"] == "demo-lab"
    assert registry_intake["workspace"]["registry"] == {"tenant": "digibatt", "workspace": "cr2032-baseline"}
    assert registry_intake["release"]["community"] == "digibatt"
    assert registry_intake["release"]["doi"] == "10.5281/zenodo.1234567"
    assert registry_intake["validation"]["ok"] is True
    resources = {item["resource_type"]: item for item in registry_intake["resources"]}
    assert "metadata" not in resources["cell"]["semantic_payload"]
    assert "metadata" not in resources["test"]["semantic_payload"]
    assert "metadata" not in resources["dataset"]["semantic_payload"]
    assert resources["test"]["semantic_payload"]["battinfo_records"]["test"]["test"]["cell_id"] == resources["cell"]["semantic_payload"]["battinfo_records"]["cell"]["cell_instance"]["id"]
    assert resources["dataset"]["semantic_payload"]["battinfo_records"]["dataset"]["dataset"]["about"] == [
        resources["cell"]["semantic_payload"]["battinfo_records"]["cell"]["cell_instance"]["id"],
        resources["test"]["semantic_payload"]["battinfo_records"]["test"]["test"]["id"],
    ]
    assert resources["dataset"]["related_resources"][1]["relationship"] == "generatedByTest"
    assert registry_intake["artifacts"][0]["path"] == "artifacts/cycling.csv"

    zenodo_metadata = json.loads(zenodo_metadata_path.read_text(encoding="utf-8"))
    assert zenodo_metadata["metadata"]["title"] == "DigiBatt CR2032 baseline dataset"
    assert zenodo_metadata["metadata"]["communities"] == [{"identifier": "digibatt"}]
    assert zenodo_metadata["metadata"]["version"] == "1.0.0"


def test_workspace_validate_reports_missing_distribution_file(tmp_path: Path) -> None:
    runner = CliRunner()
    workspace_dir = tmp_path / "my-release"

    init_result = runner.invoke(app, ["workspace", "init", str(workspace_dir), "--format", "json"])
    assert init_result.exit_code == 0, init_result.stdout

    dataset_path = workspace_dir / "resources" / "dataset.json"
    dataset_doc = json.loads(dataset_path.read_text(encoding="utf-8"))
    dataset_doc["dataset"]["distribution"]["path"] = "artifacts/missing.csv"
    dataset_path.write_text(json.dumps(dataset_doc, indent=2) + "\n", encoding="utf-8")

    validate_result = runner.invoke(app, ["workspace", "validate", str(workspace_dir), "--format", "json"])
    assert validate_result.exit_code == 1, validate_result.stdout
    validate_payload = json.loads(validate_result.stdout)
    assert validate_payload["ok"] is False
    assert validate_payload["issues"][0]["code"] == "workspace.invalid"
    assert "missing.csv" in validate_payload["issues"][0]["message"]


def test_notebook_recover_cli_reports_json_payload(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()

    monkeypatch.setattr(
        "battinfo.cli.recover_notebook_runtime",
        lambda **kwargs: {
            "status": "ok",
            "workspace_root": str(tmp_path),
            "venv_python": str(tmp_path / ".venv" / "Scripts" / "python.exe"),
            "scanned_processes": 4,
            "kernel_process_count": 1,
            "terminated_pid_count": 1,
            "killed_pid_count": 0,
            "terminated_pids": [1234],
            "killed_pids": [],
            "remaining_pid_count": 0,
            "remaining_pids": [],
            "cleared_runtime_paths": [str(tmp_path / ".jupyter-runtime-test")],
        },
    )

    result = runner.invoke(app, ["notebook", "recover", "--workspace-root", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["kernel_process_count"] == 1
    assert payload["cleared_runtime_paths"] == [str(tmp_path / ".jupyter-runtime-test")]


def test_local_workspace_object_flow_clone_and_intake_rehydration(tmp_path: Path) -> None:
    cell_design, cell, test, dataset = _build_sample_objects(tmp_path)

    workspace = LocalWorkspace.init(tmp_path / "release-v1", force=True)
    workspace.capture(
        cell_design,
        cell,
        test,
        dataset,
        registry="digibatt/hello-world",
        version="1.0.0",
        description="First sandbox publication-ready release.",
        zenodo={
            "title": "A123 hello world cycling dataset",
            "description": "Sandbox metadata for a first publication.",
            "creators": [{"name": "BattINFO Maintainers"}],
            "keywords": ["battery", "a123", "cycling"],
            "license": "CC-BY-4.0",
        },
    )

    bundle_v1 = workspace.bundle(policy="strict")
    assert Path(bundle_v1["submission_package_path"]).exists()
    assert Path(bundle_v1["registry_intake_path"]).exists()
    assert (workspace.root / "artifacts" / "a123-cycle-life.csv").exists()
    assert workspace.read_json("dist/registry-intake.json")["kind"] == "BattinfoSubmission"
    manifest_v1 = workspace.read_json("battinfo-workspace.json")
    assert manifest_v1["workspace_id"] == "hello-world"
    assert manifest_v1["release"]["community"] == "digibatt"
    assert manifest_v1["title"] == "A123 hello world cycling dataset"
    assert manifest_v1["publisher_id"] == "demo-lab"

    workspace.record_zenodo_release(
        doi="10.5072/zenodo.1234567",
        record_url="https://sandbox.zenodo.org/records/1234567",
        download_url="https://sandbox.zenodo.org/records/1234567/files/a123-cycle-life.csv",
        version="1.0.0",
        community="digibatt",
    )
    updated = workspace.load_objects()
    assert updated["release"].doi == "10.5072/zenodo.1234567"
    assert updated["dataset"].access_url == "https://sandbox.zenodo.org/records/1234567"
    assert updated["dataset"].source.citation == "https://doi.org/10.5072/zenodo.1234567"

    release_v2 = workspace.new_version(tmp_path / "release-v2", version="1.1.0", force=True)
    reloaded = release_v2.load_objects()
    assert reloaded["release"].version == "1.1.0"
    assert reloaded["release"].doi is None
    assert reloaded["dataset"].source.citation is None
    reloaded["dataset"].name = "A123 hello world cycling dataset v2"
    reloaded["dataset"].description = "Versioned update with a refreshed dataset title."
    release_v2.capture(
        reloaded["cell_design"],
        reloaded["cell"],
        reloaded["test"],
        reloaded["dataset"],
        version="1.1.0",
        zenodo={
            "keywords": ["battery", "a123", "cycling", "update"],
        },
    )
    release_v2_manifest = release_v2.read_json("battinfo-workspace.json")
    assert release_v2_manifest["workspace_id"] == "hello-world"
    assert release_v2_manifest["registry"] == {"tenant": "digibatt", "workspace": "hello-world"}
    assert not (release_v2.root / "dist").exists()
    bundle_v2 = release_v2.bundle(policy="strict")
    intake_workspace = LocalWorkspace.import_registry_intake(
        tmp_path / "rehydrated-from-intake",
        bundle_v2["submission_package_path"],
        force=True,
        capture_artifact=False,
    )
    intake_objects = intake_workspace.load_objects()
    assert intake_objects["dataset"].test_id == intake_objects["test"].id
    assert intake_objects["dataset"].cell_instance_id == intake_objects["cell"].id
    assert intake_objects["dataset"].access_url is None or isinstance(intake_objects["dataset"].access_url, str)


def test_local_workspace_sandbox_and_write_text_helpers(tmp_path: Path) -> None:
    workspace = LocalWorkspace.sandbox("helper-demo", root=tmp_path, force=True)
    written = workspace.write_text("inputs/demo.csv", "x,y\n1,2\n")
    assert written == workspace.path("inputs/demo.csv")
    assert written.exists()
    assert written.read_text(encoding="utf-8") == "x,y\n1,2\n"


def test_local_workspace_rehydrates_from_publication_bundle(tmp_path: Path) -> None:
    cell_design, cell, test, dataset = _build_sample_objects(tmp_path)
    publish_root = tmp_path / "publication"
    publish_root.mkdir(parents=True, exist_ok=True)
    raw_file = publish_root / "measurements" / "a123-cycle-life.csv"
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(
        "cycle_index,capacity_ah,voltage_v\n0,2.50,3.30\n1,2.48,3.28\n",
        encoding="utf-8",
    )
    dataset.dataset_path = str(publish_root)
    dataset.access_url = publish_root.resolve().as_uri()
    dataset.download_url = None
    dataset.data_format = "application/vnd.battinfo.dataset-directory"

    publish(cell_type=cell_design, cell_instance=cell, test=test, dataset=dataset)
    publication_path = publish_root / "battinfo.publish.jsonld"
    assert publication_path.exists()

    workspace = LocalWorkspace.import_publication(
        tmp_path / "rehydrated-from-publication",
        publication_path,
        registry="digibatt/hello-world",
        workspace_id="publication-import",
        title="Publication import workspace",
        description="Workspace recreated from a publication bundle.",
        release={"version": "1.0.0", "community": "digibatt"},
        force=True,
        capture_artifact=False,
    )
    objects = workspace.load_objects()
    assert objects["cell_design"].model == "ANR26650M1-B"
    assert objects["test"].cell_instance_id == objects["cell"].id
    assert objects["dataset"].test_id == objects["test"].id


def test_local_workspace_rehydrates_from_registry_export_wrapper(tmp_path: Path) -> None:
    cell_design, cell, test, dataset = _build_sample_objects(tmp_path)
    workspace = LocalWorkspace.from_bundle(
        tmp_path / "source-workspace",
        workspace_id="hello-world",
        title="Hello World Workspace",
        registry="digibatt/hello-world",
        publisher_id="demo-lab",
        bundle=BattinfoBundle(
            bundle_name="hello-world",
            cell_type=cell_design,
            cell_instance=cell,
            test=test,
            dataset=dataset,
        ),
        release={"version": "1.0.0", "community": "digibatt"},
        force=True,
        capture_artifact=True,
    )
    submission = json.loads(Path(workspace.bundle(policy="strict")["submission_package_path"]).read_text(encoding="utf-8"))
    export_payload = {
        "workspace_id": submission["workspace_id"],
        "publisher_id": submission["publisher_id"],
        "source_version": submission["source_version"],
        "raw_submission": submission,
        "normalized_export": {
            "kind": "BattinfoWorkspaceExport",
            "workspace_id": submission["workspace_id"],
            "publisher_id": submission["publisher_id"],
            "source_version": submission["source_version"],
            "workspace": submission["workspace"],
            "release": submission["release"],
            "resources": [
                {
                    "resource_type": item["resource_type"],
                    "source_local_id": item["source_local_id"],
                    "title": item["title"],
                    "semantic_payload": item["semantic_payload"],
                    "related_resources": item["related_resources"],
                    "distributions": item["distributions"],
                }
                for item in submission["resources"]
            ],
            "artifacts": submission["artifacts"],
            "validation": submission["validation"],
        },
    }

    rehydrated = LocalWorkspace.from_submission_package(
        tmp_path / "rehydrated-from-export",
        export_payload,
        force=True,
        capture_artifact=False,
    )
    objects = rehydrated.load_objects()
    assert objects["cell_design"].model == cell_design.model
    assert objects["cell"].serial_number == cell.serial_number
    assert objects["test"].cell_instance_id == objects["cell"].id
    assert objects["dataset"].test_id == objects["test"].id
    assert objects["dataset"].cell_instance_id == objects["cell"].id



