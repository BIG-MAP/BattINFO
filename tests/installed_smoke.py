from __future__ import annotations

import json
import tempfile
from pathlib import Path

from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    import battinfo
    from battinfo.cli import app

    assert battinfo.__version__ == "0.8.0"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            str(ROOT / "examples" / "cell-spec" / "research" / "minimal.example.json"),
            "--format",
            "json",
        ],
    )
    if result.exit_code != 0:
        raise RuntimeError(result.stdout)
    validation_payload = json.loads(result.stdout)
    assert validation_payload["ok"] is True
    assert validation_payload["error_count"] == 0, validation_payload
    # pyshacl is a core dependency, so even a core install runs the SHACL shapes.
    assert all(issue["code"] != "shacl.unavailable" for issue in validation_payload["issues"]), validation_payload

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_root = Path(tmp_dir)
        publish_dir = tmp_root / "publication"
        publish_dir.mkdir(parents=True, exist_ok=True)
        raw_file = publish_dir / "measurements" / "run.csv"
        raw_file.parent.mkdir(parents=True, exist_ok=True)
        raw_file.write_text("time,voltage\n0,3.0\n", encoding="utf-8")

        cell_spec = battinfo.CellSpec(
            manufacturer="Energizer",
            model="CR2032",
            format="coin",
            chemistry="Li-primary",
            size_code="R2032",
        )
        cell = battinfo.Cell(cell_spec=cell_spec, serial_number="energizer-cr2032-001")
        test = battinfo.Test(
            cell=cell,
            kind="capacity_check",
            protocol="constant current discharging",
            instrument="short Landt cycler",
            status="completed",
        )
        dataset = battinfo.Dataset(
            path=str(publish_dir),
            cell=cell,
            test=test,
            name="Installed smoke dataset",
        )

        publish_result = battinfo.publish_publication_package(
            cell_spec=cell_spec, cell_instance=cell, test=test, dataset=dataset
        )
        publication_payload = json.loads(Path(publish_result["publish_path"]).read_text(encoding="utf-8"))
        graph = publication_payload["@graph"]
        cell_spec_node = next(node for node in graph if node.get("@id") == publish_result["cell_spec_id"])
        cell_instance_node = next(node for node in graph if node.get("@id") == publish_result["cell_instance_id"])
        cell_spec_types = (
            cell_spec_node["@type"] if isinstance(cell_spec_node["@type"], list) else [cell_spec_node["@type"]]
        )
        assert "BatteryCellSpecification" in cell_spec_types
        assert "schema:CreativeWork" in cell_spec_types
        assert publish_result["cell_spec_id"] not in (
            cell_instance_node["@type"]
            if isinstance(cell_instance_node["@type"], list)
            else [cell_instance_node["@type"]]
        )
        assert cell_instance_node["hasDescription"]["@id"] == publish_result["cell_spec_id"]
        test_node = next(node for node in graph if node.get("@id") == publish_result["test_id"])
        test_types = test_node["@type"] if isinstance(test_node["@type"], list) else [test_node["@type"]]
        assert "schema:Action" in test_types
        assert "BatteryTest" in test_types
        bundle = battinfo.load_publication(publish_dir / "battinfo.publish.jsonld")
        assert bundle.dataset is not None

        index_path = tmp_root / "index.json"
        stats = battinfo.build_index(source_root=ROOT / "examples", out_path=index_path)
        assert stats["total_count"] >= 4
        assert index_path.exists()

    check_batch_path()


def check_batch_path() -> None:
    """Run batch init, dataset process and batch package on a cell spec packaged with battinfo."""
    from contextlib import chdir

    import yaml

    import battinfo
    from battinfo.cli import app

    packaged = Path(battinfo.__file__).resolve().parent / "data" / "library" / "cell-spec"
    spec = json.loads(sorted(packaged.glob("*.json"))[0].read_text(encoding="utf-8"))["specification"]
    runner = CliRunner()
    # Run in a new temporary folder: neither the checkout's src/ nor a local
    # .battinfo/library can stand in for the library inside the package.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir, chdir(tmp_dir):
        result = runner.invoke(
            app,
            ["batch", "init", "batch", "--cell-spec", spec["id"], "--count", "1", "--serials", "S1", "--lab", "Lab"],
        )
        assert result.exit_code == 0, result.output
        manifest = yaml.safe_load(Path("batch", "batch.yaml").read_text(encoding="utf-8"))
        assert (manifest["manufacturer"], manifest["model"]) == (spec["manufacturer"], spec["model"]), manifest

        Path("batch", "s1", "2025-06-01__capacity_check__25degC.csv").write_text(
            "time,voltage\n0,3.0\n1,2.9\n", encoding="utf-8"
        )
        result = runner.invoke(app, ["dataset", "process", "batch"])
        assert result.exit_code == 0, result.output

        result = runner.invoke(app, ["batch", "package", "batch", "--creator", "Smoke, Test; Lab", "--no-community"])
        assert result.exit_code == 0, result.output
        bundle = json.loads(Path("batch", "staging", "battinfo.bundle.json").read_text(encoding="utf-8"))
        cell_spec = bundle["cell_spec"]["cell_spec"]
        assert cell_spec["id"] == spec["id"], cell_spec
        assert (cell_spec["manufacturer"]["name"], cell_spec["model"]) == (spec["manufacturer"], spec["model"]), (
            cell_spec
        )


if __name__ == "__main__":
    main()
