from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import (
    BattinfoBundle,
    CellInstance,
    CellType,
    Dataset,
    Test,
    load_publication,
    publish,
    publish_cr2032_dataset_metadata,
    publish_dataset_metadata,
)
from battinfo.bundle import ProvenanceInfo


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_generate_cr2032_dataset_publication(tmp_path: Path) -> None:
    datasheet = tmp_path / "ENERGIZER__CR2032.pdf"
    datasheet.write_bytes(b"%PDF-1.4\n%fake pdf for test\n")

    dataset_dir_a = tmp_path / "energizer-cr2032-202602-dtjrga"
    dataset_dir_b = tmp_path / "energizer-cr2032-202602-wg2h62"
    raw_a = dataset_dir_a / "timeseries" / "raw" / "run-a.ccs"
    raw_b = dataset_dir_b / "timeseries" / "raw" / "run-b.ccs"
    raw_a.parent.mkdir(parents=True)
    raw_b.parent.mkdir(parents=True)
    raw_a.write_text("dummy-a", encoding="utf-8")
    raw_b.write_text("dummy-b", encoding="utf-8")

    staging_root = tmp_path / "staging"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / ".tools" / "semantic" / "generate_cr2032_dataset_publication.py"),
            "--datasheet",
            str(datasheet),
            "--dataset-dir",
            str(dataset_dir_a),
            "--dataset-dir",
            str(dataset_dir_b),
            "--staging-root",
            str(staging_root),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    report = json.loads(result.stdout)
    assert report["status"] == "ok"
    assert report["dataset_count"] == 2

    report_file = _load_json(staging_root / "cr2032-publication-report.json")
    assert report_file["dataset_count"] == 2
    assert Path(report_file["cell_type_path"]).exists()

    assert not (dataset_dir_a / "battinfo").exists()
    assert not (dataset_dir_b / "battinfo").exists()

    bundle_a = BattinfoBundle.from_jsonld(dataset_dir_a / "battinfo.publish.jsonld")
    bundle_b = BattinfoBundle.from_jsonld(dataset_dir_b / "battinfo.publish.jsonld")
    assert bundle_a.cell_type.model == "CR2032"
    assert bundle_b.cell_specification is not None
    assert bundle_a.dataset.access_url == dataset_dir_a.resolve().as_uri()
    assert bundle_b.test.protocol.name == "constant current discharging"
    assert bundle_b.test.instrument == "short Landt cycler"

    publish_a = _load_json(dataset_dir_a / "battinfo.publish.jsonld")
    publish_b = _load_json(dataset_dir_b / "battinfo.publish.jsonld")

    graph_a = publish_a["@graph"]
    graph_b = publish_b["@graph"]

    ids_a = {node["@id"] for node in graph_a if isinstance(node, dict) and isinstance(node.get("@id"), str)}
    ids_b = {node["@id"] for node in graph_b if isinstance(node, dict) and isinstance(node.get("@id"), str)}

    assert report_file["cell_type_id"] in ids_a
    assert report_file["cell_type_id"] in ids_b
    assert any(node.get("@type") == "schema:Dataset" for node in graph_a if isinstance(node, dict))
    assert any(node.get("@type") == "schema:Dataset" for node in graph_b if isinstance(node, dict))

    dataset_nodes_a = [node for node in graph_a if isinstance(node, dict) and node.get("@type") == "schema:Dataset"]
    dataset_nodes_b = [node for node in graph_b if isinstance(node, dict) and node.get("@type") == "schema:Dataset"]
    assert any(node.get("schema:url") == dataset_dir_a.resolve().as_uri() for node in dataset_nodes_a)
    assert any(node.get("schema:url") == dataset_dir_b.resolve().as_uri() for node in dataset_nodes_b)
    assert not any("battinfo" in str(path) for path in report_file["datasets"][0]["dataset_files"])


def test_publish_cr2032_dataset_metadata_api(tmp_path: Path) -> None:
    datasheet = tmp_path / "ENERGIZER__CR2032.pdf"
    datasheet.write_bytes(b"%PDF-1.4\n%fake pdf for test\n")

    dataset_dir = tmp_path / "energizer-cr2032-202602-dtjrga"
    raw = dataset_dir / "timeseries" / "raw" / "run-a.ccs"
    raw.parent.mkdir(parents=True)
    raw.write_text("dummy-a", encoding="utf-8")

    report = publish_cr2032_dataset_metadata(
        datasheet_path=datasheet,
        dataset_dirs=[dataset_dir],
        staging_root=tmp_path / "staging",
    )

    assert report["status"] == "ok"
    assert report["dataset_count"] == 1
    assert Path(report["datasets"][0]["publish_path"]).exists()

    bundle = load_publication(dataset_dir / "battinfo.publish.jsonld")
    assert bundle.cell_type.model == "CR2032"
    assert bundle.cell_specification is not None
    assert bundle.cell_instance.name == dataset_dir.name
    assert bundle.dataset.test_id == report["datasets"][0]["test_id"]
    assert bundle.test.instrument == "short Landt cycler"


def test_publish_dataset_metadata_with_cell_specification(tmp_path: Path) -> None:
    datasheet = tmp_path / "ENERGIZER__CR2032.pdf"
    datasheet.write_bytes(b"%PDF-1.4\n%fake pdf for test\n")

    dataset_dir = tmp_path / "energizer-cr2032-202602-dtjrga"
    raw = dataset_dir / "timeseries" / "raw" / "run-a.ccs"
    raw.parent.mkdir(parents=True)
    raw.write_text("dummy-a", encoding="utf-8")

    report = publish_dataset_metadata(
        cell_specification=ROOT / "src" / "battinfo" / "data" / "library" / "cell-type" / "ENERGIZER__CR2032.json",
        datasheet_path=datasheet,
        dataset_dirs=[dataset_dir],
        staging_root=tmp_path / "staging",
        test_kind="capacity_check",
        protocol_name="constant current discharging",
        instrument_name="short Landt cycler",
    )

    assert report["status"] == "ok"
    assert report["dataset_count"] == 1
    assert report["cell_specification_id"].startswith("https://w3id.org/battinfo/spec/")
    assert Path(report["report_path"]).name == "battinfo-publication-report.json"

    bundle = load_publication(dataset_dir / "battinfo.publish.jsonld")
    assert bundle.cell_specification is not None
    assert bundle.cell_type.model == "CR2032"
    assert bundle.cell_type.cell_specification_id == bundle.cell_specification.id
    assert bundle.test.test_kind == "capacity_check"
    assert bundle.dataset.access_url == dataset_dir.resolve().as_uri()
    assert bundle.test.instrument == "short Landt cycler"

    payload = _load_json(dataset_dir / "battinfo.publish.jsonld")
    graph = [node for node in payload["@graph"] if isinstance(node, dict)]
    instance_node = next(node for node in graph if node.get("@id") == bundle.cell_instance.id)
    type_values = instance_node.get("@type")
    assert isinstance(type_values, list)
    assert bundle.cell_type.id not in type_values
    assert instance_node["hasDescription"]["@id"] == bundle.cell_type.id
    class_node = next(node for node in graph if node.get("@id") == bundle.cell_type.id)
    class_types = class_node["@type"] if isinstance(class_node["@type"], list) else [class_node["@type"]]
    assert "BatteryCellSpecification" in class_types
    assert "schema:CreativeWork" in class_types
    test_node = next(node for node in graph if node.get("@id") == bundle.test.id)
    test_types = test_node["@type"] if isinstance(test_node["@type"], list) else [test_node["@type"]]
    assert "schema:Action" in test_types
    assert "BatteryTest" in test_types
    assert test_node["schema:description"] == "Protocol: constant current discharging"
    assert test_node["schema:instrument"]["schema:name"] == "short Landt cycler"


def test_publish_dataset_metadata_with_cell_type_only(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "example-cell-001"
    raw = dataset_dir / "data" / "run.csv"
    raw.parent.mkdir(parents=True)
    raw.write_text("time,voltage\n0,3.7\n", encoding="utf-8")

    cell_type = CellType(
        id="https://w3id.org/battinfo/spec/1234-5678-9abc-def0",
        name="ExampleCell 21700-A",
        manufacturer="ExampleCell",
        model="21700-A",
        format="cylindrical",
        chemistry="NMC/Graphite",
        size_code="R21700",
        nominal_properties={"nominal_voltage": {"value": 3.7, "unit": "V"}},
        source=ProvenanceInfo(type="manual", url="https://example.org/cells/21700-a", retrieved_at=1771804800),
    )

    report = publish_dataset_metadata(
        cell_type=cell_type,
        dataset_dirs=[dataset_dir],
        staging_root=tmp_path / "staging",
        test_kind="cycle_life",
        protocol_name="cycling",
        dataset_name_template="{cell_type_name} measurements for {dataset_key}",
        emit_bundle_dir=True,
    )

    assert report["status"] == "ok"
    assert report["dataset_count"] == 1
    assert "cell_specification_id" not in report
    assert Path(report["datasets"][0]["bundle_dir"]).exists()
    assert "cell_specification_path" not in report["datasets"][0]

    bundle = load_publication(dataset_dir / "battinfo.publish.jsonld")
    assert bundle.cell_specification is None
    assert bundle.cell_type.name == "ExampleCell 21700-A"
    assert bundle.test.protocol.name == "cycling"
    assert bundle.dataset.name == "ExampleCell 21700-A measurements for example-cell-001"


def test_publish_object_first_api(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "object-first-demo"
    raw = dataset_dir / "measurements" / "run.csv"
    raw.parent.mkdir(parents=True)
    raw.write_text("time,voltage\n0,3.0\n", encoding="utf-8")

    cell_type = CellType(
        manufacturer="Energizer",
        model="CR2032",
        format="coin",
        chemistry="Li-primary",
        size_code="R2032",
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
        path=str(dataset_dir),
        test=test,
        cell=cell,
        name="Energizer CR2032 dataset",
        description="Raw CCS time series for one CR2032 cell.",
        keywords=["battery", "coin cell"],
        creators=[{"type": "Organization", "name": "SINTEF"}],
        publisher={"type": "Organization", "name": "BattINFO"},
        funders=[{"type": "Organization", "name": "Battery Data Alliance"}],
        variable_measured=[{"name": "Voltage", "unit_text": "V"}],
        main_entity=[
            {
                "type": "Table",
                "id": "https://example.org/datasets/cr2032#table",
                "url": "measurements/run.csv",
                "tableSchema": {
                    "id": "https://example.org/datasets/cr2032/table-schema",
                    "columns": [
                        {
                            "name": "voltage",
                            "titles": ["Voltage / V"],
                            "unit_text": "V",
                        }
                    ],
                },
            }
        ],
        distributions=[
            {
                "type": "DataDownload",
                "name": "Primary CSV export",
                "contentUrl": "https://example.org/downloads/cr2032.csv",
                "encodingFormat": "text/csv",
                "checksum": {"algorithm": "sha256", "value": "b" * 64},
            }
        ],
    )

    result = publish(
        cell_type=cell_type,
        cell_instance=cell,
        test=test,
        dataset=dataset,
        emit_bundle_dir=True,
        emit_html_page=True,
    )

    assert result["status"] == "ok"
    assert Path(result["publish_path"]).exists()
    assert Path(result["bundle_dir"]).exists()
    assert Path(result["html_path"]).exists()
    assert result["cell_type_id"].startswith("https://w3id.org/battinfo/spec/")

    loaded = load_publication(dataset_dir / "battinfo.publish.jsonld")
    assert loaded.cell_type.id == result["cell_type_id"]
    assert loaded.cell_instance.cell_type_id == loaded.cell_type.id
    assert loaded.test.cell_instance_id == loaded.cell_instance.id
    assert loaded.dataset.test_id == loaded.test.id
    assert loaded.dataset.access_url == dataset_dir.resolve().as_uri()
    assert loaded.dataset.creators[0]["name"] == "SINTEF"
    assert loaded.dataset.publisher["name"] == "BattINFO"
    assert loaded.dataset.funders[0]["name"] == "Battery Data Alliance"
    assert loaded.dataset.main_entity[0]["type"] == "Table"
    assert loaded.dataset.main_entity[0]["table_schema"]["id"] == "https://example.org/datasets/cr2032/table-schema"
    assert any(dist["content_url"] == "https://example.org/downloads/cr2032.csv" for dist in loaded.dataset.distributions)
    assert loaded.cell_type.model == "CR2032"
    assert loaded.cell_instance.serial_number == "energizer-cr2032-202602-dtjrga"
    assert loaded.test.protocol.name == "constant current discharging"
    assert loaded.test.instrument == "short Landt cycler"

    payload = _load_json(dataset_dir / "battinfo.publish.jsonld")
    dataset_node = next(
        node
        for node in payload["@graph"]
        if isinstance(node, dict) and node.get("@id") == loaded.dataset.id
    )
    assert dataset_node["schema:keywords"] == ["battery", "coin cell"]
    assert dataset_node["schema:funder"][0]["schema:name"] == "Battery Data Alliance"
    main_entity = dataset_node["schema:mainEntity"]
    assert isinstance(main_entity, list)
    assert main_entity[0]["@type"] == "csvw:Table"
    assert main_entity[0]["csvw:tableSchema"]["@id"] == "https://example.org/datasets/cr2032/table-schema"
    assert main_entity[0]["csvw:tableSchema"]["csvw:column"][0]["csvw:name"] == "voltage"
    assert any(
        isinstance(entry, dict) and entry.get("schema:contentUrl") == "https://example.org/downloads/cr2032.csv"
        for entry in dataset_node["schema:distribution"]
    )
    html_text = Path(result["html_path"]).read_text(encoding="utf-8")
    assert "application/ld+json" in html_text
    assert "Energizer CR2032 dataset" in html_text


