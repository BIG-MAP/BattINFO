from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import (
    BatteryCell,
    BatteryCellSpecification,
    BatteryTestType,
    Cell,
    CellSpecification,
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

    cell_spec = workspace.cell_spec(
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
        cell_spec,
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
    assert records["cell_specs"][0]["cell_spec"]["size_code"] == "R2032"
    assert records["cell_instances"][0]["datasets"] == [{"id": records["datasets"][0]["dataset"]["id"], "role": "raw"}]
    assert records["tests"][0]["test"]["dataset_ids"] == [records["datasets"][0]["dataset"]["id"]]
    assert records["datasets"][0]["dataset"]["about"] == [
        records["cell_instances"][0]["cell_instance"]["id"],
        records["tests"][0]["test"]["id"],
    ]
    distribution = records["datasets"][0]["dataset"]["distributions"][0]
    assert distribution["encoding_format"] == "text/csv"
    assert distribution["checksum"]["algorithm"] == "sha256"
    assert len(distribution["checksum"]["value"]) == 64

    result = workspace.save(validation_policy="strict")
    assert result["index"]["failed"] == 0
    assert result["index"]["cell_spec_count"] == 1
    assert result["index"]["cell_instance_count"] == 1
    assert result["index"]["test_count"] == 1
    assert result["index"]["dataset_count"] == 1

    assert workspace.query_cell_specs(manufacturer="Energizer", format="coin")[0]["id"] == cell_spec.id
    assert workspace.query_cells(cell_spec_id=cell_spec.id, dataset_id=dataset.id)[0]["id"] == cell.id
    assert workspace.query_tests(kind="capacity_check", cell_id=cell.id)[0]["id"] == test.id
    assert workspace.query_datasets(related_cell_id=cell.id, related_test_id=test.id)[0]["id"] == dataset.id
    assert workspace.query("datasets", related_cell_id=cell.id, related_test_id=test.id)[0]["id"] == dataset.id
    assert workspace.query("cells", cell_spec_id=cell_spec.id, dataset_id=dataset.id)[0]["id"] == cell.id


def test_workspace_loads_cell_spec_from_validated_json_record(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")

    cell_spec = workspace.load_cell_spec(
        ROOT / "examples" / "cell-spec" / "A123__ANR26650M1-B.json"
    )

    assert len(workspace.cell_specs) == 1
    assert cell_spec.manufacturer == "A123"
    assert cell_spec.model == "ANR26650M1-B"
    assert cell_spec.id == "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5"
    assert cell_spec.iec_code == "IFpR26650"
    assert cell_spec.country_of_origin == "United States"
    assert cell_spec.year == 2012


def test_workspace_loads_cell_spec_from_authoring_json_and_canonizes_on_save(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")
    draft_path = tmp_path / "cell-spec" / "A123__ANR26650M1-B.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(
        json.dumps(
            {
                "manufacturer": "A123",
                "model": "ANR26650M1-B",
                "format": "cylindrical",
                "chemistry": "Li-ion",
                "size_code": "R26650",
                "iec_code": "IFpR26650",
                "country_of_origin": "United States",
                "year": 2012,
                "positive_electrode_basis": "LFP",
                "negative_electrode_basis": "graphite",
                "properties": {
                    "nominal_capacity": {"value": 2.5, "unit": "Ah"},
                    "typical_energy": {"value": 8.25, "unit": "Wh"},
                    "rated_energy": {"value": 8.0, "unit": "Wh"},
                    "nominal_voltage": {"value": 3.3, "unit": "V"},
                    "specific_energy": {"value": 130.0, "unit": "Wh/kg"},
                    "energy_density": {"value": 250.0, "unit": "Wh/L"},
                    "specific_power": {"value": 900.0, "unit": "W/kg"},
                    "power_density": {"value": 1700.0, "unit": "W/L"},
                },
                "comment": "Manual authoring draft without canonical identifiers.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    cell_spec = workspace.load_cell_spec(draft_path)

    assert cell_spec.manufacturer == "A123"
    assert cell_spec.model == "ANR26650M1-B"
    assert cell_spec.id is None
    assert cell_spec.source.type is None
    assert cell_spec.source.file is None

    save_result = workspace.save()

    assert save_result["index"]["cell_spec_count"] == 1
    assert isinstance(cell_spec.id, str)
    assert cell_spec.id.startswith("https://w3id.org/battinfo/spec/")
    record_path = tmp_path / "workspace" / "examples" / "cell-spec" / f"cell-spec-{cell_spec.id.rsplit('/', 1)[-1]}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert isinstance(record["cell_spec"]["short_id"], str)
    assert len(record["cell_spec"]["short_id"]) == 6
    assert record["cell_spec"]["identifier"] == f"cell-spec:{cell_spec.id.rsplit('/', 1)[-1]}"
    assert record["cell_spec"]["iec_code"] == "IFpR26650"
    assert record["cell_spec"]["country_of_origin"] == "United States"
    assert record["cell_spec"]["year"] == 2012
    assert record["properties"]["typical_energy"] == {"value": 8.25, "unit": "Wh"}
    assert record["properties"]["rated_energy"] == {"value": 8.0, "unit": "Wh"}
    assert record["properties"]["specific_energy"] == {"value": 130.0, "unit": "Wh/kg"}
    assert record["properties"]["energy_density"] == {"value": 250.0, "unit": "Wh/L"}
    assert record["properties"]["specific_power"] == {"value": 900.0, "unit": "W/kg"}
    assert record["properties"]["power_density"] == {"value": 1700.0, "unit": "W/L"}
    assert record["provenance"]["source_type"] == "datasheet"
    assert record["provenance"]["source_file"] == "manual.json"
    assert isinstance(record["provenance"]["retrieved_at"], int)


def test_workspace_loads_multiple_cell_specs_from_directory(tmp_path: Path) -> None:
    records_dir = tmp_path / "cell-spec"
    records_dir.mkdir(parents=True, exist_ok=True)
    first = {
        "manufacturer": "A123",
        "model": "ANR26650M1-B",
        "chemistry": "LFP",
        "format": "cylindrical",
        "properties": {"nominal_voltage": {"value": 3.3, "unit": "V"}},
    }
    second = {
        "manufacturer": "Energizer",
        "model": "CR2032",
        "chemistry": "Li-primary",
        "format": "coin",
        "iec_code": "CR2032",
        "country_of_origin": "United States",
        "year": 2023,
        "properties": {"nominal_voltage": {"value": 3.0, "unit": "V"}},
        "provenance": {"source_file": "ENERGIZER__CR2032.pdf"},
    }
    (records_dir / "A123__ANR26650M1-B.json").write_text(json.dumps(first, indent=2), encoding="utf-8")
    (records_dir / "ENERGIZER__CR2032.json").write_text(json.dumps(second, indent=2), encoding="utf-8")

    workspace = Workspace(root=tmp_path / "workspace")
    loaded = workspace.load_cell_specs(directory=records_dir)

    assert len(loaded) == 2
    assert {item.manufacturer for item in loaded} == {"A123", "Energizer"}
    assert {item.model for item in loaded} == {"ANR26650M1-B", "CR2032"}
    assert {item.iec_code for item in loaded} == {None, "CR2032"}
    assert {item.country_of_origin for item in loaded} == {None, "United States"}
    assert {item.year for item in loaded} == {None, 2023}
    assert all(item.id is None for item in loaded)


def test_workspace_saves_and_queries_test_protocols(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")

    cell_spec = workspace.cell_spec(
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        source_file="A123__ANR26650M1-B.pdf",
    )
    cell = workspace.cell(cell_spec, serial_number="LAB-001")
    protocol = workspace.test_spec(
        name="1C Cycle Life at 25 C",
        kind="cycling",
        version="1.0",
        protocol_url="https://example.org/protocols/cycle-life-1c",
        experiment=["Charge at 1 C until 4.2 V", "Discharge at 1 C until 2.5 V"],
        cycles=500,
        conditions={"temperature": quantity(25.0, "degC")},
    )
    # PyBaMM-string authoring parsed into the canonical structured method.
    assert protocol.method[0].mode == "group"
    assert protocol.method[0].count == 500
    assert protocol.facets()["c_rates"] == [1.0]
    test = workspace.test(
        cell,
        protocol_ref=protocol,
        instrument="Biologic VSP-300",
        status="completed",
    )

    records = workspace.render()
    assert records["test_specs"][0]["test_spec"]["kind"] == "cycling"
    assert records["tests"][0]["test"]["protocol_id"] == records["test_specs"][0]["test_spec"]["id"]

    result = workspace.save(validation_policy="strict")
    assert result["index"]["test_spec_count"] == 1
    assert workspace.query_test_specs(kind="cycling")[0]["id"] == protocol.id
    assert workspace.query_tests(kind="cycling")[0]["protocol_id"] == protocol.id
    assert test.protocol_id == protocol.id


def test_workspace_test_conformance_round_trip(tmp_path: Path) -> None:
    from battinfo.bundle import Deviation, TestConformance

    workspace = Workspace(root=tmp_path / "workspace")
    cell_spec = workspace.cell_spec(manufacturer="ACME", model="X1", format="cylindrical", chemistry="Li-ion")
    cell = workspace.cell(cell_spec, serial_number="SN-001")
    spec = workspace.test_spec(name="C/5 capacity check", kind="capacity_check")

    conformance = TestConformance(
        status="non-conformant",
        note="Power outage at step 3; 4 min gap before restart.",
        deviations=[
            Deviation(
                type="power_outage",
                description="Mains cut for ~4 min at C/5 discharge",
                occurred_at=1780640000,
                duration_s=240,
                step_index=3,
                impact="minor",
            )
        ],
    )
    workspace.test(cell, protocol_ref=spec, status="completed", conformance=conformance)

    # in-memory round-trip via to_record / from_record
    workspace.save(validation_policy="strict")
    saved_test_records = workspace.query_tests()
    assert len(saved_test_records) == 1
    saved = saved_test_records[0]

    assert saved["conformance"]["status"] == "non-conformant"
    assert saved["conformance"]["note"] == "Power outage at step 3; 4 min gap before restart."
    assert len(saved["conformance"]["deviations"]) == 1
    dev = saved["conformance"]["deviations"][0]
    assert dev["type"] == "power_outage"
    assert dev["duration_s"] == 240
    assert dev["step_index"] == 3
    assert dev["impact"] == "minor"

    # model round-trip

    from battinfo.bundle import Test
    test_dir = tmp_path / "workspace" / "examples" / "test"
    test_files = list(test_dir.glob("*.json"))
    assert len(test_files) == 1
    import json
    reloaded = Test.from_record(json.loads(test_files[0].read_text()))
    assert reloaded.conformance is not None
    assert reloaded.conformance.status == "non-conformant"
    assert len(reloaded.conformance.deviations) == 1
    assert reloaded.conformance.deviations[0].type == "power_outage"
    assert reloaded.conformance.deviations[0].duration_s == 240


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
        coin_hardware={
            "case": {"size_code": "Pouch-custom", "material": "Al laminate"},
        },
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
    assert records[0]["housing"]["case"]["material"] == "Al laminate"


def test_workspace_record_test_creates_linked_dataset(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")
    dataset_file = tmp_path / "inputs" / "hppc.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text("step,value\n1,0.0\n2,1.0\n", encoding="utf-8")

    cell_spec = workspace.cell_spec(
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
        cell_spec,
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

    cell_spec = CellSpecification()
    cell_spec.manufacturer = "A123"
    cell_spec.model = "ANR26650M1-B"
    cell_spec.format = "cylindrical"
    cell_spec.chemistry = "Li-ion"
    cell_spec.size_code = "R26650"
    cell_spec.positive_electrode_basis = "LFP"
    cell_spec.negative_electrode_basis = "unknown"
    cell_spec.nominal_capacity = quantity(2.5, "Ah")
    cell_spec.nominal_voltage = quantity(3.3, "V")

    cell = Cell(cell_spec)
    cell.serial_number = "hello-world-001"
    cell.batch_id = "A123-HELLO-01"
    cell.source.type = "lab"

    test = Test(cell)
    test.test_type = BatteryTestType.CYCLING
    test.protocol_name = "1C charge / 1C discharge"
    test.instrument_name = "Biologic VSP-300"
    test.status = "completed"

    dataset = Dataset(dataset_file, test=test, license="CC-BY-4.0")
    dataset.name = "A123 hello world cycling dataset"

    workspace.add(cell_spec, cell, test, dataset)

    records = workspace.render()
    assert records["cell_specs"][0]["properties"]["nominal_capacity"] == {"value": 2.5, "unit": "Ah"}
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

    cell_spec = BatteryCellSpecification(
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        nominal_capacity=quantity(2.5, "Ah"),
        nominal_voltage=quantity(3.3, "V"),
    )
    cell = BatteryCell(
        cell_spec,
        serial_number="dataset-only-001",
        batch_id="A123-DATASET-ONLY",
        source={"type": "lab"},
    )
    test = Test(
        cell,
        test_type=BatteryTestType.CYCLING,
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
    assert result["index"]["cell_spec_count"] == 1
    assert result["index"]["cell_instance_count"] == 1
    assert result["index"]["test_count"] == 1
    assert result["index"]["dataset_count"] == 1
    assert workspace.render()["datasets"][0]["dataset"]["about"][0] == workspace.render()["cell_instances"][0]["cell_instance"]["id"]


def test_workspace_publish_stages_file_backed_dataset(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")
    dataset_file = tmp_path / "inputs" / "energizer-cr2032-capacity.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text("time_s,voltage_v\n0,3.0\n60,2.95\n", encoding="utf-8")

    cell_spec = workspace.cell_spec(
        manufacturer="Energizer",
        model="CR2032",
        format="coin",
        chemistry="Li-primary",
        size_code="R2032",
        country_of_origin="Japan",
        year=2022,
        positive_electrode_basis="MnO2",
        negative_electrode_basis="Li-metal",
        specs={
            "nominal_voltage": quantity(3.0, "V"),
            "rated_energy": quantity(0.69, "Wh"),
        },
        source_file="energizer-cr2032.manual.json",
    )
    cell = workspace.cell(cell_spec, serial_number="energizer-cr2032-lot-a-001", source_type="lab")
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
    ro_crate_payload = json.loads(Path(publish_result["ro_crate_path"]).read_text(encoding="utf-8"))
    datacite_payload = json.loads(Path(publish_result["datacite_metadata_path"]).read_text(encoding="utf-8"))
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
    assert Path(publish_result["ro_crate_path"]).exists()
    assert Path(publish_result["datacite_metadata_path"]).exists()
    assert publish_result["dcat_export_path"] is None
    assert dataset.dataset_path == str(dataset_file)
    assert dataset.data_format == "text/csv"
    assert dataset_node["schema:url"] == Path(publish_result["dataset_dir"]).resolve().as_uri()
    assert dataset_file.name in distribution_names
    cell_spec_node = next(node for node in payload["@graph"] if node.get("@id") == publish_result["cell_spec_id"])
    assert cell_spec_node["schema:countryOfOrigin"]["schema:name"] == "Japan"
    assert cell_spec_node["schema:releaseDate"] == "2022-01-01"
    property_types = {
        entry.get("@type")
        for entry in cell_spec_node.get("hasProperty", [])
        if isinstance(entry, dict)
    }
    # rated_energy maps to NominalEnergy (no distinct RatedEnergy class in EMMO).
    assert "NominalEnergy" in property_types
    assert ro_crate_payload["@graph"][0]["@id"] == "ro-crate-metadata.json"
    assert datacite_payload["types"]["resourceTypeGeneral"] == "Dataset"
    assert datacite_payload["titles"][0]["title"] == "Energizer CR2032 capacity dataset"


def test_workspace_publish_can_infer_missing_dataset_links_from_workspace(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")
    dataset_file = tmp_path / "inputs" / "cycle-life.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text("cycle,capacity_ah\n0,2.50\n1,2.48\n", encoding="utf-8")

    cell_spec = workspace.cell_spec(
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
    cell = workspace.cell(cell_spec, serial_number="alpha-001", source_type="lab")
    test = workspace.test(
        cell,
        kind="cycling",
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
    assert publish_result["cell_spec_id"] is not None


def test_workspace_build_publication_package_can_emit_dcat_export(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")
    dataset_file = tmp_path / "inputs" / "cycle-life.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text("cycle,capacity_ah\n0,2.50\n1,2.48\n", encoding="utf-8")

    cell_spec = workspace.cell_spec(
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
    cell = workspace.cell(cell_spec, serial_number="alpha-001", source_type="lab")
    test = workspace.test(
        cell,
        kind="cycling",
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

    result = workspace.build_publication_package(dataset, emit_dcat_export=True)
    dcat_payload = json.loads(Path(result["dcat_export_path"]).read_text(encoding="utf-8"))

    assert Path(result["publish_path"]).exists()
    assert Path(result["ro_crate_path"]).exists()
    assert Path(result["datacite_metadata_path"]).exists()
    assert Path(result["dcat_export_path"]).exists()
    assert dcat_payload["@graph"][0]["@type"] == "dcat:Dataset"


def test_workspace_build_release_exports_registry_ready_local_workspace(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")
    dataset_file = tmp_path / "inputs" / "cycle-life.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text("cycle,capacity_ah\n0,2.50\n1,2.48\n", encoding="utf-8")

    cell_spec = workspace.cell_spec(
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
    cell = workspace.cell(cell_spec, serial_number="alpha-001", source_type="lab")
    test = workspace.test(
        cell,
        kind="cycling",
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

    release_root = tmp_path / "release"
    result = workspace.build_submission_package(
        dataset,
        root=release_root,
        registry="digibatt/hello-world",
        publisher_id="demo-lab",
        version="1.0.0",
        title="A123 hello world cycling dataset",
        description="Workspace-built release bundle.",
        force=True,
    )

    manifest = json.loads((release_root / "battinfo-workspace.json").read_text(encoding="utf-8"))
    assert Path(result["submission_package_path"]).exists()
    intake = json.loads(Path(result["submission_package_path"]).read_text(encoding="utf-8"))

    assert manifest["workspace_id"] == "hello-world"
    assert manifest["registry"] == {"tenant": "digibatt", "workspace": "hello-world"}
    assert (release_root / "artifacts" / dataset_file.name).exists()
    assert intake["kind"] == "BattinfoSubmission"
    assert intake["workspace_id"] == "hello-world"
    assert intake["publisher_id"] == "demo-lab"
    assert intake["workspace"]["registry"] == {"tenant": "digibatt", "workspace": "hello-world"}
    assert intake["validation"]["ok"] is True
    assert result["resource_count"] == 3
    assert result["artifact_count"] == 1


def test_battery_cell_design_and_battery_cell_aliases_work_for_object_authoring(tmp_path: Path) -> None:
    workspace = Workspace(root=tmp_path / "workspace")
    dataset_file = tmp_path / "inputs" / "alias-flow.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text("cycle,capacity_ah\n0,2.50\n", encoding="utf-8")

    cell_design = BatteryCellSpecification()
    cell_design.manufacturer = "A123"
    cell_design.model = "ANR26650M1-B"
    cell_design.format = "cylindrical"
    cell_design.chemistry = "Li-ion"
    cell_design.nominal_capacity = quantity(2.5, "Ah")

    cell = BatteryCell(cell_design)
    cell.serial_number = "alias-001"

    test = Test(cell)
    test.test_type = BatteryTestType.CYCLING

    dataset = Dataset(dataset_file, test=test)
    dataset.name = "Alias dataset"

    workspace.add(cell_design, cell, test, dataset)
    records = workspace.render()
    assert records["cell_specs"][0]["cell_spec"]["model"] == "ANR26650M1-B"
    assert records["datasets"][0]["dataset"]["about"] == [
        records["cell_instances"][0]["cell_instance"]["id"],
        records["tests"][0]["test"]["id"],
    ]


def test_battery_cell_design_accepts_flattened_quantities_in_constructor() -> None:
    cell_design = BatteryCellSpecification(
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
    assert cell_design.properties["nominal_capacity"] == {"value": 2.5, "unit": "Ah"}


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






