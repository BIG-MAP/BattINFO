from __future__ import annotations

import json
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import (
    BatteryCell,
    BatteryCellType,
    BatteryTestType,
    Cell,
    CellType,
    Dataset,
    Test,
    Workspace,
    bom,
    construction,
    electrode,
    electrolyte_recipe,
    material,
    properties,
    quantity,
    separator_spec,
    source,
)


def test_workspace_saves_and_queries_simple_chain(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")
    dataset_file = tmp_path / "inputs" / "energizer-cr2032-capacity.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text("time_s,voltage_v\n0,3.0\n60,2.95\n", encoding="utf-8")

    cell_type = workspace.cell_type(
        manufacturer="Energizer",
        model="CR2032",
        format="coin",
        chemistry="Li-primary",
        size_code="R2032",
        positive_electrode_basis="MnO2",
        negative_electrode_basis="Li-metal",
        specs={
            "nominal_voltage": quantity(3.0, "V"),
            "diameter": quantity(20.0, "mm"),
            "height": quantity(3.2, "mm"),
        },
        source_file="energizer-cr2032.manual.json",
    )
    cell = workspace.cell(
        cell_type,
        serial_number="energizer-cr2032-lot-a-001",
        batch_id="CR2032-2026-02",
        source_type="lab",
    )
    test = workspace.test(
        cell,
        kind="capacity_check",
        protocol="0.2 mA constant-current discharge",
        instrument="Biologic VSP-300",
        status="completed",
    )
    dataset = workspace.dataset(
        cell,
        title="Energizer CR2032 capacity dataset",
        description="Single-cell discharge summary for the workspace test.",
        test=test,
        path=dataset_file,
        license="CC-BY-4.0",
    )

    records = workspace.render()
    assert records["cell_types"][0]["product"]["sizeCode"] == "R2032"
    assert records["cell_instances"][0]["datasets"] == [{"id": records["datasets"][0]["dataset"]["id"], "role": "raw"}]
    assert records["tests"][0]["test"]["dataset_ids"] == [records["datasets"][0]["dataset"]["id"]]
    assert records["datasets"][0]["dataset"]["about"] == [
        records["cell_instances"][0]["cell_instance"]["id"],
        records["tests"][0]["test"]["id"],
    ]
    distribution = records["datasets"][0]["dataset"]["distribution"][0]
    assert distribution["encodingFormat"] == "text/csv"
    assert distribution["checksum"]["algorithm"] == "sha256"
    assert len(distribution["checksum"]["value"]) == 64

    result = workspace.save(validation_policy="strict")
    assert result["index"]["failed"] == 0
    assert result["index"]["cell_type_count"] == 1
    assert result["index"]["cell_instance_count"] == 1
    assert result["index"]["test_count"] == 1
    assert result["index"]["dataset_count"] == 1

    assert workspace.query_cell_types(manufacturer="Energizer", format="coin")[0]["id"] == cell_type.id
    assert workspace.query_cells(type_id=cell_type.id, dataset_id=dataset.id)[0]["id"] == cell.id
    assert workspace.query_tests(kind="capacity_check", cell_id=cell.id)[0]["id"] == test.id
    assert workspace.query_datasets(related_cell_id=cell.id, related_test_id=test.id)[0]["id"] == dataset.id
    assert workspace.query("datasets", related_cell_id=cell.id, related_test_id=test.id)[0]["id"] == dataset.id
    assert workspace.query("cells", type_id=cell_type.id, dataset_id=dataset.id)[0]["id"] == cell.id


def test_workspace_describes_saves_and_queries_detailed_cell(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")

    positive_electrode = electrode(
        bom=bom(
            active_material=material("LiNi0.8Mn0.1Co0.1O2", comment="Primary cathode active material"),
            additive="Carbon black",
            binder="PVDF",
        ),
        loading=quantity(18.5, "mg/cm^2"),
        calendered_density=quantity(3.1, "g/cm3"),
        current_collector="Aluminum foil",
        current_collector_thickness=quantity(15, "um"),
        coating_comment="Slot-die coated on aluminum foil and calendered after drying.",
        comment="Pilot-line cathode coating specification.",
    )
    negative_electrode = electrode(
        bom=bom(
            active_material=[
                material("Graphite"),
                material("Silicon oxide", comment="Small silicon-containing fraction for energy boost"),
            ],
            additive="Carbon black",
            binder=["CMC", "SBR"],
        ),
        loading=quantity(9.8, "mg/cm^2"),
        calendered_density=quantity(1.55, "g/cm3"),
        current_collector="Copper foil",
        current_collector_thickness=quantity(8, "um"),
        coating_comment="Anode recipe used for pilot build lot ML-042.",
        comment="Anode coating processed on the same pilot line as the cathode.",
    )
    electrolyte = electrolyte_recipe(
        family="organic",
        solvents=["EC", "EMC", "DEC"],
        salt="LiPF6",
        salt_concentration=quantity(1.0, "mol/L"),
        additives=["VC", "FEC"],
        solvent_comment="Baseline carbonate solvent blend for pilot pouch program.",
        comment="Electrolyte filled after vacuum drying and final stack insertion.",
    )
    separator = separator_spec(
        material="PP/PE/PP trilayer microporous separator",
        thickness=quantity(20, "um"),
        comment="Commercial trilayer separator cut to match the stacked pouch geometry.",
    )

    specification = workspace.describe_cell(
        manufacturer="AlphaLab",
        model="POUCH-ML-NMC-042",
        format="pouch",
        chemistry="NMC/graphite",
        positive_electrode_basis="NMC811",
        negative_electrode_basis="graphite-silicon",
        positive_electrode=positive_electrode,
        negative_electrode=negative_electrode,
        electrolyte=electrolyte,
        separator=separator,
        construction=construction(
            assembly_type="stacked",
            layering="multilayer",
            layer_count=18,
            comment="Single cell pouch stack built for pilot-line validation.",
        ),
        properties=properties(
            nominal_capacity=quantity(4.2, "Ah"),
            nominal_voltage=quantity(3.7, "V"),
            width=quantity(68.0, "mm"),
            height=quantity(92.0, "mm"),
            thickness=quantity(6.4, "mm"),
        ),
        source=source(
            type="lab",
            name="Pilot pouch build sheet",
            file="pilot-line/POUCH-ML-NMC-042-build-sheet.xlsx",
            retrieved_at=1773201600,
            comment="Entered from pilot-line formulation and assembly records.",
        ),
        specification_comment="Representative multilayer pouch build authored from engineering records.",
        comment="Human-authored detailed cell description for alpha workflow demonstration.",
    )

    results = workspace.save_descriptions()

    assert results["rdf"]["entry_count"] == 1
    assert specification.id is not None
    records = workspace.query_descriptions(format="pouch", model_contains="ML-NMC-042")
    assert len(records) == 1
    assert records[0]["id"] == specification.id
    assert records[0]["construction"]["layer_count"] == 18


def test_workspace_record_test_creates_linked_dataset(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")
    dataset_file = tmp_path / "inputs" / "hppc.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text("step,value\n1,0.0\n2,1.0\n", encoding="utf-8")

    cell_type = workspace.cell_type(
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="LFP",
        size_code="R26650",
        positive_electrode_basis="LFP",
        negative_electrode_basis="graphite",
        specs={"nominal_voltage": quantity(3.3, "V")},
        source_file="a123-anr26650m1-b.manual.json",
    )
    cell = workspace.cell(
        cell_type,
        serial_number="a123-anr26650m1-b-alpha-001",
        batch_id="A123-ALPHA-01",
        source_type="lab",
    )

    test = workspace.record_test(
        cell,
        kind="hppc",
        path=dataset_file,
        instrument="Biologic VSP-300",
        license="CC-BY-4.0",
    )

    result = workspace.save(validation_policy="strict")
    assert result["index"]["test_count"] == 1
    assert result["index"]["dataset_count"] == 1

    rows = workspace.query_tests(kind="hppc", cell_id=cell.id)
    assert len(rows) == 1
    assert rows[0]["id"] == test.id
    assert rows[0]["dataset_ids"]


def test_workspace_add_supports_object_style_authoring_and_dataset_infers_cell_from_test(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")
    dataset_file = tmp_path / "inputs" / "cycle-life.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text("cycle,capacity_ah\n0,2.50\n1,2.48\n", encoding="utf-8")

    cell_type = CellType()
    cell_type.manufacturer = "A123"
    cell_type.model = "ANR26650M1-B"
    cell_type.format = "cylindrical"
    cell_type.chemistry = "Li-ion"
    cell_type.size_code = "R26650"
    cell_type.positive_electrode_basis = "LFP"
    cell_type.negative_electrode_basis = "unknown"
    cell_type.nominal_capacity = quantity(2.5, "Ah")
    cell_type.nominal_voltage = quantity(3.3, "V")

    cell = Cell(cell_type)
    cell.serial_number = "hello-world-001"
    cell.batch_id = "A123-HELLO-01"
    cell.source.type = "lab"

    test = Test(cell)
    test.test_type = BatteryTestType.CYCLE_LIFE
    test.protocol_name = "1C charge / 1C discharge"
    test.instrument_name = "Biologic VSP-300"
    test.status = "completed"

    dataset = Dataset(dataset_file, test=test, license="CC-BY-4.0")
    dataset.name = "A123 hello world cycling dataset"

    workspace.add(cell_type, cell, test, dataset)

    records = workspace.render()
    assert records["cell_types"][0]["specs"]["nominal_capacity"] == {"value": 2.5, "unit": "Ah"}
    assert records["tests"][0]["test"]["cell_id"] == records["cell_instances"][0]["cell_instance"]["id"]
    assert records["tests"][0]["test"]["dataset_ids"] == [records["datasets"][0]["dataset"]["id"]]
    assert records["datasets"][0]["dataset"]["about"] == [
        records["cell_instances"][0]["cell_instance"]["id"],
        records["tests"][0]["test"]["id"],
    ]

    result = workspace.save(validation_policy="strict")
    assert result["index"]["failed"] == 0


def test_workspace_add_dataset_pulls_in_linked_dependencies(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")
    dataset_file = tmp_path / "inputs" / "dataset-only-add.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text("cycle,capacity_ah\n0,2.50\n1,2.48\n", encoding="utf-8")

    cell_type = BatteryCellType(
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        nominal_capacity=quantity(2.5, "Ah"),
        nominal_voltage=quantity(3.3, "V"),
    )
    cell = BatteryCell(
        cell_type,
        serial_number="dataset-only-001",
        batch_id="A123-DATASET-ONLY",
        source={"type": "lab"},
    )
    test = Test(
        cell,
        test_type=BatteryTestType.CYCLE_LIFE,
        protocol={"name": "1C charge / 1C discharge"},
        status="completed",
    )
    dataset = Dataset(
        dataset_file,
        test=test,
        license="CC-BY-4.0",
        name="Dataset-only add flow",
    )

    workspace.add(dataset)

    result = workspace.save(validation_policy="strict")
    assert result["index"]["failed"] == 0
    assert result["index"]["cell_type_count"] == 1
    assert result["index"]["cell_instance_count"] == 1
    assert result["index"]["test_count"] == 1
    assert result["index"]["dataset_count"] == 1
    assert workspace.render()["datasets"][0]["dataset"]["about"][0] == workspace.render()["cell_instances"][0]["cell_instance"]["id"]


def test_workspace_publish_stages_file_backed_dataset(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")
    dataset_file = tmp_path / "inputs" / "energizer-cr2032-capacity.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text("time_s,voltage_v\n0,3.0\n60,2.95\n", encoding="utf-8")

    cell_type = workspace.cell_type(
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
    cell = workspace.cell(cell_type, serial_number="energizer-cr2032-lot-a-001", source_type="lab")
    test = workspace.test(
        cell,
        kind="capacity_check",
        protocol="0.2 mA constant-current discharge",
        instrument="Biologic VSP-300",
        status="completed",
    )
    dataset = workspace.dataset(
        cell,
        title="Energizer CR2032 capacity dataset",
        description="Single-cell discharge summary for the workspace test.",
        test=test,
        path=dataset_file,
        license="CC-BY-4.0",
    )

    publish_result = workspace.publish(dataset)

    publish_path = Path(publish_result["publish_path"])
    payload = json.loads(publish_path.read_text(encoding="utf-8"))
    dataset_node = next(node for node in payload["@graph"] if node.get("@id") == publish_result["dataset_id"])
    distribution_names = {
        entry.get("schema:name")
        for entry in dataset_node.get("schema:distribution", [])
        if isinstance(entry, dict)
    }

    assert publish_path.exists()
    assert Path(publish_result["dataset_dir"]).is_dir()
    assert (Path(publish_result["dataset_dir"]) / dataset_file.name).exists()
    assert publish_result["triple_count"] > 0
    assert dataset.dataset_path == str(dataset_file)
    assert dataset.data_format == "text/csv"
    assert dataset_node["schema:url"] == Path(publish_result["dataset_dir"]).resolve().as_uri()
    assert dataset_file.name in distribution_names


def test_workspace_publish_can_infer_missing_dataset_links_from_workspace(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")
    dataset_file = tmp_path / "inputs" / "cycle-life.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text("cycle,capacity_ah\n0,2.50\n1,2.48\n", encoding="utf-8")

    cell_type = workspace.cell_type(
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
    cell = workspace.cell(cell_type, serial_number="alpha-001", source_type="lab")
    test = workspace.test(
        cell,
        kind="cycle_life",
        protocol="1C charge / 1C discharge",
        instrument="Biologic VSP-300",
        status="completed",
    )
    dataset = workspace.dataset(
        cell,
        title="Cycle life dataset",
        test=test,
        path=dataset_file,
        license="CC-BY-4.0",
    )
    dataset.test = None
    dataset.cell = None

    publish_result = workspace.publish(dataset)

    assert Path(publish_result["publish_path"]).exists()
    assert publish_result["test_id"] is not None
    assert publish_result["cell_instance_id"] is not None
    assert publish_result["cell_type_id"] is not None


def test_battery_cell_design_and_battery_cell_aliases_work_for_object_authoring(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")
    dataset_file = tmp_path / "inputs" / "alias-flow.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text("cycle,capacity_ah\n0,2.50\n", encoding="utf-8")

    cell_design = BatteryCellType()
    cell_design.manufacturer = "A123"
    cell_design.model = "ANR26650M1-B"
    cell_design.format = "cylindrical"
    cell_design.chemistry = "Li-ion"
    cell_design.nominal_capacity = quantity(2.5, "Ah")

    cell = BatteryCell(cell_design)
    cell.serial_number = "alias-001"

    test = Test(cell)
    test.test_type = BatteryTestType.CYCLE_LIFE

    dataset = Dataset(dataset_file, test=test)
    dataset.name = "Alias dataset"

    workspace.add(cell_design, cell, test, dataset)
    records = workspace.render()
    assert records["cell_types"][0]["product"]["model"] == "ANR26650M1-B"
    assert records["datasets"][0]["dataset"]["about"] == [
        records["cell_instances"][0]["cell_instance"]["id"],
        records["tests"][0]["test"]["id"],
    ]


def test_battery_cell_design_accepts_flattened_quantities_in_constructor() -> None:
    cell_design = BatteryCellType(
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        nominal_capacity=quantity(2.5, "Ah"),
        nominal_voltage=quantity(3.3, "V"),
        diameter=quantity(26.0, "mm"),
    )

    assert cell_design.nominal_capacity == {"value": 2.5, "unit": "Ah"}
    assert cell_design.nominal_voltage == {"value": 3.3, "unit": "V"}
    assert cell_design.diameter == {"value": 26.0, "unit": "mm"}
    assert cell_design.nominal_properties["nominal_capacity"] == {"value": 2.5, "unit": "Ah"}


def test_test_uses_enum_backed_test_type_and_rejects_unknown_values() -> None:
    test = Test(test_type=BatteryTestType.HPPC)
    assert test.test_type == BatteryTestType.HPPC
    assert test.test_kind == BatteryTestType.HPPC

    try:
        Test(test_type="made_up_test")
    except Exception as exc:  # noqa: BLE001
        assert "made_up_test" in str(exc)
    else:
        raise AssertionError("Expected invalid test_type to fail validation")


