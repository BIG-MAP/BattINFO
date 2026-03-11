from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import (  # noqa: E402
    BattinfoBundle,
    Coating,
    CellInstance,
    CellSpecification,
    CellType,
    CurrentCollector,
    Dataset,
    Electrode,
    Electrolyte,
    MaterialComponent,
    Salt,
    Separator,
    SolventMixture,
    Test,
    derive_cell_type,
    load_cell_specification,
    register_cell_instance,
    register_cell_type,
    register_dataset,
    register_library_cell_type,
    register_test,
)
from battinfo.bundle import ProtocolInfo, ProvenanceInfo  # noqa: E402


def test_bundle_round_trip_and_registration(tmp_path: Path) -> None:
    specification = CellSpecification(
        id="https://w3id.org/battinfo/cell-type/7r2m-4q8v-k6nt-c3pj",
        manufacturer="Energizer",
        model="CR2032",
        format="coin",
        chemistry="Li-primary",
        positive_electrode_basis="MnO2",
        negative_electrode_basis="Li-metal",
        properties={"nominal_voltage": {"value": 3.0, "unit": "V"}},
        source=ProvenanceInfo(
            type="datasheet",
            file="datasheets/ENERGIZER__CR2032.pdf",
            url="https://example.org/datasheets/ENERGIZER__CR2032.pdf",
            retrieved_at=1771804800,
        ),
        comment=["Example bundle specification."],
    )
    cell_type = CellType(
        id="https://w3id.org/battinfo/cell-type/7r2m-4q8v-k6nt-c3pj",
        name="Energizer CR2032",
        manufacturer="Energizer",
        model="CR2032",
        format="coin",
        chemistry="Li-primary",
        positive_electrode_basis="MnO2",
        negative_electrode_basis="Li-metal",
        cell_specification_id=specification.id,
        nominal_properties={"nominal_voltage": {"value": 3.0, "unit": "V"}},
        source=ProvenanceInfo(
            type="datasheet",
            file="datasheets/ENERGIZER__CR2032.pdf",
            url="https://example.org/datasheets/ENERGIZER__CR2032.pdf",
            retrieved_at=1771804800,
        ),
    )
    cell_instance = CellInstance(
        id="https://w3id.org/battinfo/cell/69ca-scxq-6w58-e9tc",
        name="energizer-cr2032-202602-dtjrga",
        cell_type_id=cell_type.id,
        serial_number="energizer-cr2032-202602-dtjrga",
        dataset_ids=["https://w3id.org/battinfo/dataset/gj1y-pn2n-t5pm-gs9c"],
        source=ProvenanceInfo(type="measurement", retrieved_at=1771804801),
    )
    test = Test(
        id="https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r",
        name="energizer-cr2032-202602-dtjrga constant current discharging",
        test_kind="capacity_check",
        cell_instance_id=cell_instance.id,
        protocol=ProtocolInfo(name="constant current discharging"),
        instrument="short Landt cycler",
        dataset_ids=["https://w3id.org/battinfo/dataset/gj1y-pn2n-t5pm-gs9c"],
        source=ProvenanceInfo(type="measurement", retrieved_at=1771804802),
    )
    dataset = Dataset(
        id="https://w3id.org/battinfo/dataset/gj1y-pn2n-t5pm-gs9c",
        name="SINTEF Energizer CR2032 dataset energizer-cr2032-202602-dtjrga",
        data_format="application/vnd.battinfo.dataset-directory",
        dataset_path="..",
        access_url="file:///tmp/energizer-cr2032-202602-dtjrga",
        created_at=1771804803,
        cell_instance_id=cell_instance.id,
        test_id=test.id,
        source=ProvenanceInfo(type="measurement", retrieved_at=1771804803),
    )
    bundle = BattinfoBundle(
        bundle_name="energizer-cr2032-202602-dtjrga",
        cell_type=cell_type,
        cell_instance=cell_instance,
        test=test,
        dataset=dataset,
    )

    bundle_dir = tmp_path / "bundle"
    bundle_with_spec = bundle.model_copy(update={"cell_specification": specification})
    bundle_with_spec.to_directory(bundle_dir)
    loaded = BattinfoBundle.from_directory(bundle_dir)
    assert loaded.cell_specification.model == "CR2032"
    assert loaded.cell_type.nominal_properties["nominal_voltage"]["value"] == 3.0
    assert loaded.cell_instance.serial_number == "energizer-cr2032-202602-dtjrga"
    assert loaded.test.protocol.name == "constant current discharging"
    assert loaded.test.instrument == "short Landt cycler"
    assert loaded.dataset.dataset_path == ".."

    library_payload = register_library_cell_type(
        specification,
        library_root=tmp_path / "library" / "cell-types",
        package_root=tmp_path / "package" / "cell-types",
    )
    assert library_payload["status"] == "created"

    type_payload = register_cell_type(
        loaded.cell_type,
        source_root=tmp_path / "registry",
        resolve_references=False,
    )
    assert type_payload["status"] == "created"

    instance_payload = register_cell_instance(
        loaded.cell_instance,
        source_root=tmp_path / "registry",
        resolve_references=False,
    )
    assert instance_payload["status"] == "created"

    test_payload = register_test(
        loaded.test,
        source_root=tmp_path / "registry",
        resolve_references=False,
    )
    assert test_payload["status"] == "created"

    dataset_payload = register_dataset(
        loaded.dataset,
        source_root=tmp_path / "registry",
        resolve_references=True,
    )
    assert dataset_payload["status"] == "created"


def test_load_cell_specification_from_library_record() -> None:
    spec = load_cell_specification(ROOT / "assets" / "library" / "cell-types" / "A123__ANR26650M1-B.json")

    assert spec.model == "ANR26650M1-B"
    assert spec.positive_electrode is not None
    assert spec.negative_electrode is not None
    assert spec.electrolyte is not None
    assert spec.separator is not None
    assert spec.positive_electrode.coating is not None
    assert spec.positive_electrode.coating.component["active_material"][0].name == "LFP"
    assert spec.electrolyte.salt is not None
    assert spec.electrolyte.salt.name == "LiPF6"
    assert spec.separator.material == "PE/PP trilayer"


def test_derive_cell_type_from_library_record_mapping() -> None:
    spec_record = json.loads((ROOT / "assets" / "library" / "cell-types" / "A123__ANR26650M1-B.json").read_text(encoding="utf-8"))

    cell_type = derive_cell_type(spec_record)

    assert cell_type.id == "https://w3id.org/battinfo/cell-type/9qfb-4wrn-ynwc-ayjw"
    assert cell_type.model == "ANR26650M1-B"
    assert cell_type.positive_electrode_basis == "LFP"
    assert cell_type.negative_electrode_basis == "graphite"
    assert cell_type.nominal_properties["nominal_voltage"]["value"] == 3.3


def test_cell_specification_accepts_nested_objects() -> None:
    spec = CellSpecification(
        id="https://w3id.org/battinfo/cell-type/9qfb-4wrn-ynwc-ayjw",
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        positive_electrode_basis="LFP",
        negative_electrode_basis="graphite",
        properties={"nominal_voltage": {"value": 3.3, "unit": "V"}},
        positive_electrode=Electrode(
            coating=Coating(
                component={
                    "active_material": [
                        MaterialComponent(name="LFP", property={"mass_fraction": {"value": 0.94, "unit": "1"}})
                    ],
                    "binder": [
                        MaterialComponent(name="PVDF", property={"mass_fraction": {"value": 0.03, "unit": "1"}})
                    ],
                },
                property={"thickness": {"value": 66.0, "unit": "um"}},
            ),
            current_collector=CurrentCollector(
                name="Al foil",
                property={"thickness": {"value": 15.0, "unit": "um"}},
            ),
        ),
        electrolyte=Electrolyte(
            family="organic",
            solvent_mixture=SolventMixture(
                component=[
                    MaterialComponent(name="EC", property={"volume_fraction": {"value": 0.3, "unit": "1"}}),
                    MaterialComponent(name="EMC", property={"volume_fraction": {"value": 0.7, "unit": "1"}}),
                ]
            ),
            salt=Salt(
                name="LiPF6",
                cation="Li+",
                anion="PF6-",
                property={"concentration": {"value": 1.0, "unit": "mol/L"}},
            ),
            additive=[MaterialComponent(name="VC", property={"volume_fraction": {"value": 0.02, "unit": "1"}})],
        ),
        separator=Separator(
            material="PE/PP trilayer",
            property={"thickness": {"value": 20.0, "unit": "um"}},
        ),
    )

    record = spec.to_library_record()

    assert record["specification"]["positive_electrode"]["coating"]["component"]["active_material"][0]["name"] == "LFP"
    assert record["specification"]["electrolyte"]["salt"]["name"] == "LiPF6"
    assert record["specification"]["separator"]["material"] == "PE/PP trilayer"
