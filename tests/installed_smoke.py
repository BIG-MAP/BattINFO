from __future__ import annotations

import json
import tempfile
from pathlib import Path

from typer.testing import CliRunner


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    import battinfo
    from battinfo.cli import app

    assert battinfo.__version__ == "0.1.0"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            str(ROOT / "assets" / "examples" / "battery-descriptors" / "minimal.example.json"),
            "--format",
            "json",
        ],
    )
    if result.exit_code != 0:
        raise RuntimeError(result.stdout)
    validation_payload = json.loads(result.stdout)
    assert validation_payload["ok"] is True
    assert validation_payload["issue_count"] == 0

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_root = Path(tmp_dir)
        publish_dir = tmp_root / "publication"
        publish_dir.mkdir(parents=True, exist_ok=True)
        raw_file = publish_dir / "measurements" / "run.csv"
        raw_file.parent.mkdir(parents=True, exist_ok=True)
        raw_file.write_text("time,voltage\n0,3.0\n", encoding="utf-8")

        cell_type = battinfo.CellType(
            manufacturer="Energizer",
            model="CR2032",
            format="coin",
            chemistry="Li-primary",
            size_code="R2032",
        )
        cell = battinfo.CellInstance(cell_type=cell_type, serial_number="energizer-cr2032-alpha")
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

        publish_result = battinfo.publish(cell_type=cell_type, cell_instance=cell, test=test, dataset=dataset)
        publication_payload = json.loads(Path(publish_result["publish_path"]).read_text(encoding="utf-8"))
        graph = publication_payload["@graph"]
        cell_type_node = next(node for node in graph if node.get("@id") == publish_result["cell_type_id"])
        cell_instance_node = next(node for node in graph if node.get("@id") == publish_result["cell_instance_id"])
        assert "schema:ProductModel" in (
            cell_type_node["@type"] if isinstance(cell_type_node["@type"], list) else [cell_type_node["@type"]]
        )
        assert publish_result["cell_type_id"] not in (
            cell_instance_node["@type"] if isinstance(cell_instance_node["@type"], list) else [cell_instance_node["@type"]]
        )
        assert cell_instance_node["schema:isVariantOf"]["@id"] == publish_result["cell_type_id"]
        test_node = next(node for node in graph if node.get("@id") == publish_result["test_id"])
        test_types = test_node["@type"] if isinstance(test_node["@type"], list) else [test_node["@type"]]
        assert "schema:Action" in test_types
        assert "BatteryTest" in test_types
        bundle = battinfo.load_publication(publish_dir / "battinfo.publish.jsonld")
        assert bundle.dataset is not None

        index_path = tmp_root / "index.json"
        stats = battinfo.build_index(source_root=ROOT / "assets" / "examples", out_path=index_path)
        assert stats["total_count"] >= 4
        assert index_path.exists()


if __name__ == "__main__":
    main()
