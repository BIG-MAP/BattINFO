from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import (  # noqa: E402
    Workspace,
    import_converter_jsonld,
    import_converter_jsonld_record,
    import_converter_package,
)
from battinfo.transform import to_jsonld  # noqa: E402
from battinfo.validate import validate_json  # noqa: E402


def _load_fixture() -> dict:
    path = ROOT / "tests" / "fixtures" / "converter" / "coin-cell.converter.sample.jsonld"
    return json.loads(path.read_text(encoding="utf-8"))


def _rated_capacity_procedure(role: str) -> dict:
    if role == "positive":
        task = {
            "@type": "Charging",
            "hasInput": [
                {
                    "@type": "ElectricCurrentDensity",
                    "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 0.1},
                    "hasMeasurementUnit": "emmo:MilliAmperePerSquareCentiMetre",
                },
                {
                    "@type": ["UpperVoltageLimit", "TerminationQuantity"],
                    "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 4.2},
                    "hasMeasurementUnit": "emmo:Volt",
                },
            ],
            "hasNext": {
                "@type": "Hold",
                "hasInput": [
                    {
                        "@type": "Voltage",
                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 4.2},
                        "hasMeasurementUnit": "emmo:Volt",
                    },
                    {
                        "@type": ["LowerCurrentDensityLimit", "TerminationQuantity"],
                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 0.01},
                        "hasMeasurementUnit": "emmo:MilliAmperePerSquareCentiMetre",
                    },
                ],
                "hasNext": {
                    "@type": "Discharging",
                    "hasInput": [
                        {
                            "@type": "ElectricCurrentDensity",
                            "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 0.1},
                            "hasMeasurementUnit": "emmo:MilliAmperePerSquareCentiMetre",
                        },
                        {
                            "@type": ["LowerVoltageLimit", "TerminationQuantity"],
                            "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 2.5},
                            "hasMeasurementUnit": "emmo:Volt",
                        },
                    ],
                },
            },
        }
        test_object = {
            "ElectrochemicalCell": {
                "@type": "ElectrochemicalCell",
                "hasNegativeElectrode": {"@type": "Graphite"},
            }
        }
    else:
        task = {
            "@type": "Discharging",
            "hasInput": [
                {
                    "@type": "ElectricCurrentDensity",
                    "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 0.1},
                    "hasMeasurementUnit": "emmo:MilliAmperePerSquareCentiMetre",
                },
                {
                    "@type": ["LowerVoltageLimit", "TerminationQuantity"],
                    "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 0.01},
                    "hasMeasurementUnit": "emmo:Volt",
                },
            ],
            "hasNext": {
                "@type": "Hold",
                "hasInput": [
                    {
                        "@type": "Voltage",
                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 0.01},
                        "hasMeasurementUnit": "emmo:Volt",
                    },
                    {
                        "@type": ["LowerCurrentDensityLimit", "TerminationQuantity"],
                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 0.01},
                        "hasMeasurementUnit": "emmo:MilliAmperePerSquareCentiMetre",
                    },
                ],
                "hasNext": {
                    "@type": "Charging",
                    "hasInput": [
                        {
                            "@type": "ElectricCurrentDensity",
                            "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 0.1},
                            "hasMeasurementUnit": "emmo:MilliAmperePerSquareCentiMetre",
                        },
                        {
                            "@type": ["LowerVoltageLimit", "TerminationQuantity"],
                            "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 0.01},
                            "hasMeasurementUnit": "emmo:Volt",
                        },
                    ],
                },
            },
        }
        test_object = {
            "ElectrochemicalHalfCell": {
                "@type": "ElectrochemicalHalfCell",
                "hasReferenceElectrode": {"@type": "LithiumElectrode"},
            }
        }

    return {
        "@type": "RatedCapacity",
        "@reverse": {
            "hasOutput": {
                "@type": "BatteryTest",
                "hasTestObject": test_object,
                "hasMeasurementParameter": {
                    "@type": ["ConstantCurrentConstantVoltageCycling"],
                    "rdfs:label": "GeneratedBatteryTestProcedure",
                    "rdfs:comment": "A description of a generated battery testing procedure",
                    "hasTask": task,
                },
            }
        },
    }


def _fixture_with_procedures() -> dict:
    fixture = _load_fixture()
    fixture["hasPositiveElectrode"]["hasMeasuredProperty"] = [
        _rated_capacity_procedure("positive"),
        {
            "@type": "RatedCapacity",
            "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 1.1},
            "hasMeasurementUnit": "emmo:MilliAmpereHourPerSquareCentiMetre",
        },
        {
            "@type": "RatedCapacity",
            "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 160},
            "hasMeasurementUnit": "unit:MilliA-HR-PER-GM",
        },
        fixture["hasPositiveElectrode"]["hasMeasuredProperty"],
    ]
    fixture["hasNegativeElectrode"]["hasMeasuredProperty"] = [
        _rated_capacity_procedure("negative"),
        {
            "@type": "RatedCapacity",
            "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 1.2},
            "hasMeasurementUnit": "emmo:MilliAmpereHourPerSquareCentiMetre",
        },
        {
            "@type": "RatedCapacity",
            "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 350},
            "hasMeasurementUnit": "unit:MilliA-HR-PER-GM",
        },
        fixture["hasNegativeElectrode"]["hasMeasuredProperty"],
    ]
    return fixture


def test_import_converter_jsonld_record_builds_valid_descriptor_record() -> None:
    result = import_converter_jsonld_record(_load_fixture())
    record = result.record

    assert isinstance(record.get("specification"), dict), "converter output should have specification key"

    specification = record["specification"]
    assert specification["format"] == "coin"
    assert specification["size_code"] == "R2032"
    assert specification["positive_electrode_basis"] == "NMC"
    assert specification["negative_electrode_basis"] == "graphite"
    assert specification["chemistry"] == "Li-ion"
    assert specification["model"] == "Empa-bco-000007"
    assert specification["construction"]["assembly_sequence"][-1] == "CellLid"

    assert record["instances"][0]["serial_number"] == "Empa-bco-000007"
    assert specification["positive_electrode"]["coating"]["component"]["active_material"][0]["name"] == "NMC"
    assert specification["positive_electrode"]["coating"]["property"]["thickness"]["unit"] == "um"
    assert specification["negative_electrode"]["current_collector"]["name"] == "Copper"
    assert specification["electrolyte"]["family"] == "organic"
    assert specification["electrolyte"]["salt"]["name"] == "LiPF6"
    assert specification["electrolyte"]["property"]["fill_volume"]["value"] == 100
    assert specification["separator"]["material"] == "PP"
    housing = specification["housing"]
    assert housing["case"]["product_id"] == "2032, SUS316L"
    assert housing["case"]["size_code"] == "R2032"
    assert housing["case"]["material"] == "Stainless steel"
    parts = {part["type"]: part for part in housing["parts"]}
    assert parts["spring"]["property"]["diameter"]["value"] == 15
    assert parts["spacer"]["property"]["thickness"]["value"] == 1.0


def test_import_converter_jsonld_supports_canonical_overrides() -> None:
    result = import_converter_jsonld(
        _load_fixture(),
        manufacturer="ExampleLab",
        model="COIN-LFP-2032",
        chemistry="Li-ion",
        id="https://w3id.org/battinfo/spec/1c4m-7p9q-2k6t-8v3r",
    )
    specification = result.record["specification"]

    assert specification["id"] == "https://w3id.org/battinfo/spec/1c4m-7p9q-2k6t-8v3r"
    assert specification["manufacturer"] == "ExampleLab"
    assert specification["model"] == "COIN-LFP-2032"
    assert specification["chemistry"] == "Li-ion"


def test_imported_converter_record_renders_to_coin_cell_jsonld() -> None:
    result = import_converter_jsonld_record(_load_fixture())
    mapped = to_jsonld(result.record, target="domain-battery")

    assert "@graph" in mapped
    battery_node = mapped["@graph"][0]
    battery_types = battery_node["@type"] if isinstance(battery_node["@type"], list) else [battery_node["@type"]]
    assert "BatteryCellSpecification" in battery_types
    assert "schema:CreativeWork" in battery_types
    physical_types = battery_node["isDescriptionFor"]["@type"]
    if isinstance(physical_types, str):
        physical_types = [physical_types]
    assert "CoinCell" in physical_types
    assert battery_node["schema:model"] == "Empa-bco-000007"
    assert battery_node["hasCase"]["@type"] == "CoinCase"
    assert battery_node["hasCase"]["schema:size"] == "R2032"
    # Coin hardware now uses real EMMO @types (was schema:Thing + additionalType).
    assert battery_node["hasConstituent"][0]["@type"] == "Spring"
    assert mapped["@graph"][1]["schema:serialNumber"] == "Empa-bco-000007"


def test_imported_converter_record_renders_to_converter_compatible_jsonld() -> None:
    result = import_converter_jsonld_record(_load_fixture())
    specification = result.record["specification"]
    specification["housing"]["parts"].append({
        "type": "lid",
        "material": "Stainless steel",
        "coating": "Au",
        "manufacturer": "Empa",
    })
    specification["housing"]["parts"].append({
        "type": "can",
        "material": "Stainless steel",
        "coating": "Ni",
        "supplier": "CaseParts AG",
    })

    mapped = to_jsonld(result.record, target="converter-compatible")

    assert mapped["@type"] == "CoinCell"
    assert mapped["schema:productID"] == "Empa-bco-000007"
    assert mapped["hasPositiveElectrode"]["@type"] == "Electrode"
    assert mapped["hasElectrolyte"]["@type"] == "OrganicElectrolyte"
    comments = mapped["rdfs:comment"] if isinstance(mapped["rdfs:comment"], list) else [mapped["rdfs:comment"]]
    assert any("Cell assembly sequence:" in comment for comment in comments)
    assert mapped["hasCase"]["@type"][0] == "R2032"
    assert mapped["hasCase"]["hasConstituent"][0]["@type"][0] == "CellLid"
    assert mapped["hasConstituent"][0]["@type"] == "Spring"


def test_import_converter_jsonld_record_extracts_linked_test_protocols_and_tests() -> None:
    result = import_converter_jsonld_record(_fixture_with_procedures())

    assert len(result.test_specs) == 2
    assert len(result.tests) == 2

    protocol_validation = validate_json(result.test_specs[0], profile="test-protocol")
    assert protocol_validation.ok, protocol_validation.errors
    test_validation = validate_json(result.tests[0], profile="test")
    assert test_validation.ok, test_validation.errors

    positive_protocol = result.test_specs[0]["test_spec"]
    negative_protocol = result.test_specs[1]["test_spec"]
    assert positive_protocol["kind"] == "capacity_check"
    assert negative_protocol["kind"] == "capacity_check"
    # The EMMO task chain is parsed into the structured, queryable method: the
    # positive-electrode procedure charges first, the negative discharges first.
    pos_method = result.test_specs[0]["method"]
    neg_method = result.test_specs[1]["method"]
    assert pos_method[0]["mode"] == "cc" and pos_method[0]["direction"] == "charge"
    assert neg_method[0]["direction"] == "discharge"
    # A CC charge step carries its cutoff voltage as a structured termination.
    assert pos_method[0]["termination"][0]["quantity"] == "voltage"
    # Free-form test context (reference electrode) is preserved in notes.
    assert any("Li-metal" in note for note in result.test_specs[1]["notes"])
    assert result.tests[0]["test"]["protocol_id"] == result.test_specs[0]["test_spec"]["id"]
    assert result.tests[0]["test"]["cell_id"] == result.record["instances"][0]["id"]


def test_import_converter_package_builds_linked_objects_and_adds_to_workspace(tmp_path: Path) -> None:
    package = import_converter_package(_fixture_with_procedures())

    assert package.specification.id == package.cell_spec.id
    assert package.cell_instance is not None
    assert package.cell_instance.cell_spec_id == package.cell_spec.id
    assert len(package.test_specs) == 2
    assert len(package.tests) == 2
    assert package.tests[0].cell is package.cell_instance
    assert package.tests[0].protocol_entity is package.test_specs[0]

    workspace = Workspace(root=tmp_path / "workspace")
    package.add_to_workspace(workspace)
    results = workspace.save(source_root=tmp_path / "records", build_index=False)

    assert len(results["cell_specs"]) == 1
    assert len(results["cell_instances"]) == 1
    assert len(results["test_specs"]) == 2
    assert len(results["tests"]) == 2
