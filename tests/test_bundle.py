from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import (  # noqa: E402
    BattinfoBundle,
    BillOfMaterials,
    CellConstruction,
    Coating,
    CellInstance,
    CellSpecification,
    CellType,
    CurrentCollector,
    Dataset,
    Electrode,
    Electrolyte,
    MaterialComponent,
    PropertySet,
    Salt,
    Separator,
    SolventMixture,
    Test,
    derive_cell_type,
    load_cell_specification,
    save_cell_instance,
    save_cell_type,
    save_dataset,
    save_library_cell_type,
    save_test,
)
from battinfo.bundle import ProtocolInfo, ProvenanceInfo  # noqa: E402


def test_bundle_round_trip_and_save(tmp_path: Path) -> None:
    specification = CellSpecification(
        id="https://w3id.org/battinfo/cell-type/7r2m-4q8v-k6nt-c3pj",
        manufacturer="Energizer",
        model="CR2032",
        format="coin",
        chemistry="Li-primary",
        positive_electrode_basis="MnO2",
        negative_electrode_basis="Li-metal",
        construction={"assembly_type": "stacked", "layering": "not_applicable"},
        properties={"nominal_voltage": {"value": 3.0, "unit": "V"}},
        source=ProvenanceInfo(
            type="datasheet",
            file="datasheets/ENERGIZER__CR2032.pdf",
            url="https://example.org/datasheets/ENERGIZER__CR2032.pdf",
            citation="https://doi.org/10.1016/j.jpowsour.2024.123456",
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
            citation="https://doi.org/10.1016/j.jpowsour.2024.123456",
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
    assert loaded.cell_specification.construction["assembly_type"] == "stacked"
    assert loaded.cell_specification.source.citation == "https://doi.org/10.1016/j.jpowsour.2024.123456"
    assert loaded.cell_type.nominal_properties["nominal_voltage"]["value"] == 3.0
    assert loaded.cell_type.source.citation == "https://doi.org/10.1016/j.jpowsour.2024.123456"
    assert loaded.cell_instance.serial_number == "energizer-cr2032-202602-dtjrga"
    assert loaded.test.protocol.name == "constant current discharging"
    assert loaded.test.instrument == "short Landt cycler"
    assert loaded.dataset.dataset_path == ".."

    library_payload = save_library_cell_type(
        specification,
        library_root=tmp_path / "library" / "cell-types",
        package_root=tmp_path / "package" / "cell-types",
    )
    assert library_payload["status"] == "created"

    type_payload = save_cell_type(
        loaded.cell_type,
        source_root=tmp_path / "registry",
        resolve_references=False,
    )
    assert type_payload["status"] == "created"

    instance_payload = save_cell_instance(
        loaded.cell_instance,
        source_root=tmp_path / "registry",
        resolve_references=False,
    )
    assert instance_payload["status"] == "created"
    cell_instance_record = json.loads(Path(instance_payload["path"]).read_text(encoding="utf-8"))
    assert "dataset_id" not in cell_instance_record.get("provenance", {})
    assert cell_instance_record["datasets"] == [{"id": "https://w3id.org/battinfo/dataset/gj1y-pn2n-t5pm-gs9c", "role": "raw"}]

    test_payload = save_test(
        loaded.test,
        source_root=tmp_path / "registry",
        resolve_references=False,
    )
    assert test_payload["status"] == "created"

    dataset_payload = save_dataset(
        loaded.dataset,
        source_root=tmp_path / "registry",
        resolve_references=True,
    )
    assert dataset_payload["status"] == "created"


def test_dataset_round_trip_preserves_rich_metadata() -> None:
    dataset = Dataset(
        id="https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x",
        identifier={"property_id": "doi", "value": "10.1000/example-dataset"},
        name="Rich metadata dataset",
        description="Dataset with discovery-oriented metadata.",
        license="https://creativecommons.org/licenses/by/4.0/",
        same_as=["https://example.org/datasets/rich-metadata"],
        additional_type=["https://schema.org/MediaObject"],
        version="2026.03",
        keywords=["battery", "cycling"],
        creators=[
            {
                "type": "Person",
                "name": "Ada Lovelace",
                "given_name": "Ada",
                "family_name": "Lovelace",
                "sameAs": "https://orcid.org/0000-0000-0000-0001",
                "email": "ada@example.org",
                "affiliation": {
                    "type": "Organization",
                    "name": "Example Lab",
                    "sameAs": "https://ror.org/03yrm5c26",
                },
            }
        ],
        publisher={
            "type": "Organization",
            "name": "Example Publisher",
            "url": "https://example.org",
            "sameAs": "https://ror.org/04t3en479",
        },
        funders=[
            {
                "type": "Organization",
                "name": "Battery Research Council",
                "sameAs": "https://ror.org/02mhbdp94",
            }
        ],
        citations=[{"name": "Reference article", "url": "https://doi.org/10.1000/reference", "doi": "10.1000/reference"}],
        measurement_techniques=["electrochemical cycling"],
        measurement_methods=["constant current"],
        variable_measured=[{"name": "Voltage", "unit_text": "V", "sameAs": "https://qudt.org/vocab/quantitykind/Voltage"}],
        is_accessible_for_free=True,
        conditions_of_access="open",
        in_language="en",
        access_url="https://example.org/datasets/rich-metadata",
        created_at=1771804803,
        modified_at=1771804900,
        published_at=1771805000,
        temporal_coverage="2026-01-01/2026-01-31",
        spatial_coverage="Trondheim",
        is_based_on=["https://example.org/protocols/cycling"],
        included_in_data_catalog={
            "type": "DataCatalog",
            "id": "https://example.org/catalog",
            "name": "Example Battery Catalog",
            "url": "https://example.org/catalog",
            "sameAs": "https://example.org/catalog/about",
        },
        main_entity=[
            {
                "type": "Table",
                "id": "https://example.org/datasets/rich-metadata#table",
                "url": "raw.parquet",
                "tableSchema": {
                    "id": "https://example.org/datasets/rich-metadata/schema",
                    "columns": [
                        {
                            "name": "voltage",
                            "titles": ["Voltage / V"],
                            "sameAs": "https://qudt.org/vocab/quantitykind/Voltage",
                            "unit_text": "V",
                        }
                    ],
                },
            }
        ],
        distributions=[
            {
                "type": "DataDownload",
                "name": "raw parquet",
                "contentUrl": "https://example.org/datasets/rich-metadata/raw.parquet",
                "encodingFormat": "application/x-parquet",
                "checksum": {"algorithm": "sha256", "value": "a" * 64},
            }
        ],
        cell_instance_id="https://w3id.org/battinfo/cell/69ca-scxq-6w58-e9tc",
        test_id="https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r",
        source=ProvenanceInfo(type="measurement", url="https://example.org/source", retrieved_at=1771805001),
        comment=["Round-trip me."],
    )

    record = dataset.to_record()
    loaded = Dataset.from_record(record)

    assert loaded.identifier == {"property_id": "doi", "value": "10.1000/example-dataset"}
    assert loaded.same_as == ["https://example.org/datasets/rich-metadata"]
    assert loaded.creators[0]["name"] == "Ada Lovelace"
    assert loaded.creators[0]["sameAs"] == "https://orcid.org/0000-0000-0000-0001"
    assert loaded.creators[0]["given_name"] == "Ada"
    assert loaded.publisher["name"] == "Example Publisher"
    assert loaded.publisher["sameAs"] == "https://ror.org/04t3en479"
    assert loaded.funders[0]["name"] == "Battery Research Council"
    assert loaded.funders[0]["sameAs"] == "https://ror.org/02mhbdp94"
    assert loaded.citations[0]["doi"] == "10.1000/reference"
    assert loaded.variable_measured[0]["name"] == "Voltage"
    assert loaded.main_entity[0]["type"] == "Table"
    assert loaded.main_entity[0]["tableSchema"]["id"] == "https://example.org/datasets/rich-metadata/schema"
    assert loaded.main_entity[0]["tableSchema"]["columns"][0]["sameAs"] == "https://qudt.org/vocab/quantitykind/Voltage"
    assert loaded.distributions[0]["contentUrl"] == "https://example.org/datasets/rich-metadata/raw.parquet"
    assert loaded.distributions[0]["checksum"]["value"] == "a" * 64
    assert loaded.included_in_data_catalog["name"] == "Example Battery Catalog"
    assert loaded.included_in_data_catalog["sameAs"] == "https://example.org/catalog/about"


def test_load_cell_specification_from_library_record() -> None:
    spec = load_cell_specification(ROOT / "src" / "battinfo" / "data" / "library" / "cell-types" / "A123__ANR26650M1-B.json")

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
    spec_record = json.loads((ROOT / "src" / "battinfo" / "data" / "library" / "cell-types" / "A123__ANR26650M1-B.json").read_text(encoding="utf-8"))

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
        construction={"assembly_type": "wound", "layering": "multilayer", "layer_count": 28},
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
    assert record["specification"]["construction"]["assembly_type"] == "wound"


def test_cell_specification_accepts_human_first_helper_objects() -> None:
    spec = CellSpecification(
        id="https://w3id.org/battinfo/cell-type/4f2m-8k7p-1t9x-6q3r",
        manufacturer="AlphaLab",
        model="POUCH-ML-NMC-042",
        format="pouch",
        chemistry="NMC/graphite",
        positive_electrode_basis="NMC811",
        negative_electrode_basis="graphite-silicon",
        construction=CellConstruction(
            assembly_type="stacked",
            layering="multilayer",
            layer_count=18,
            comment="Single cell pouch stack built for pilot-line validation.",
        ),
        properties=PropertySet(
            nominal_capacity={"value": 4.2, "unit": "Ah"},
            nominal_voltage={"value": 3.7, "unit": "V"},
        ),
        positive_electrode=Electrode(
            coating=Coating(
                component=BillOfMaterials(
                    active_material=[MaterialComponent(name="LiNi0.8Mn0.1Co0.1O2")],
                    binder=[MaterialComponent(name="PVDF")],
                    additive=[MaterialComponent(name="Carbon black")],
                ),
                property=PropertySet(loading={"value": 18.5, "unit": "mg/cm^2"}),
            ),
            current_collector=CurrentCollector(
                name="Aluminum foil",
                property=PropertySet(thickness={"value": 15, "unit": "um"}),
            ),
        ),
        electrolyte=Electrolyte(
            family="organic",
            salt=Salt(
                name="LiPF6",
                property=PropertySet(concentration={"value": 1.0, "unit": "mol/L"}),
            ),
        ),
        separator=Separator(
            material="PP/PE/PP trilayer microporous separator",
            property=PropertySet(thickness={"value": 20.0, "unit": "um"}),
        ),
        source=ProvenanceInfo(type="lab", retrieved_at=1773201600),
    )

    record = spec.to_library_record()

    assert record["specification"]["construction"]["layer_count"] == 18
    assert record["specification"]["positive_electrode"]["coating"]["component"]["additive"][0]["name"] == "Carbon black"
    assert record["specification"]["electrolyte"]["salt"]["property"]["concentration"]["value"] == 1.0


