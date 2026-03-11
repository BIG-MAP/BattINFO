from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.transform.json_to_jsonld import to_jsonld
from battinfo.validate import validate_jsonld


def _load_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _load_golden(path: str) -> dict:
    return json.loads((ROOT / "tests" / "golden" / path).read_text(encoding="utf-8"))


def test_domain_battery_mapping_contains_expected_keys() -> None:
    doc = _load_json("src/battinfo/data/examples/cells/A123_20AH.curated.json")
    mapped = to_jsonld(doc, target="domain-battery")
    golden = _load_golden("domain_battery_a123_20ah.jsonld")
    assert mapped == golden


def test_batterypass_mapping_contains_profile_markers() -> None:
    doc = _load_json("src/battinfo/data/examples/cells/A123_20AH.curated.json")
    mapped = to_jsonld(doc, target="batterypass")
    golden = _load_golden("batterypass_a123_20ah.jsonld")
    assert mapped == golden


def test_descriptor_minimal_maps_to_domain_battery_shape() -> None:
    doc = _load_json("assets/examples/battery-descriptors/minimal.example.json")
    mapped = to_jsonld(doc, target="domain-battery")

    assert "@graph" in mapped
    assert len(mapped["@graph"]) == 1
    battery = mapped["@graph"][0]

    assert battery["@id"] == "https://w3id.org/battinfo/cell-type/pvn1-43h7-rm3e-mjqq"
    assert "BatteryCell" in battery["@type"]
    assert "CylindricalBattery" in battery["@type"]
    assert "LithiumIonBattery" in battery["@type"]
    assert "LithiumIonIronPhosphateBattery" in battery["@type"]
    assert "LithiumIonGraphiteBattery" in battery["@type"]
    assert "schema:ProductModel" in battery["@type"]
    assert battery["schema:schemaVersion"] == "1.0.0"
    assert "hasBattery" not in mapped
    assert battery["schema:name"] == "A123 ANR26650M1-B"
    assert battery["schema:model"] == "ANR26650M1-B"
    assert battery["schema:manufacturer"]["schema:name"] == "A123"
    assert battery["hasPositiveElectrode"]["@type"] == "LithiumIronPhosphateElectrode"
    assert battery["hasNegativeElectrode"]["@type"] == "GraphiteElectrode"
    assert "schema:description" not in battery
    assert "battinfo:cellFormat" not in battery
    assert "battinfo:chemistry" not in battery
    assert "battinfo:positiveElectrodeBasis" not in battery
    assert "battinfo:negativeElectrodeBasis" not in battery


def test_descriptor_a123_maps_top_level_properties_instances_and_provenance() -> None:
    doc = _load_json("assets/examples/battery-descriptors/a123-anr26650m1-b.example.json")
    mapped = to_jsonld(doc, target="domain-battery")

    assert "@graph" in mapped
    assert len(mapped["@graph"]) == 3
    battery = mapped["@graph"][0]
    instances = mapped["@graph"][1:]

    assert battery["@id"] == "https://w3id.org/battinfo/cell-type/9qfb-4wrn-ynwc-ayjw"
    assert "BatteryCell" in battery["@type"]
    assert "CylindricalBattery" in battery["@type"]
    assert battery["schema:isBasedOn"]["@type"] == "schema:CreativeWork"
    assert battery["schema:isBasedOn"]["@id"] == "https://doi.org/10.17632/kxsbr4x3j2.2"
    assert battery["schema:isBasedOn"]["schema:additionalType"] == "measurement"
    assert battery["schema:isBasedOn"]["schema:version"] == "battinfo-ingest-0.2.0"
    assert battery["schema:isBasedOn"]["schema:identifier"] == "ddata/a123/anr26650m1-b/catenaro-2021/battery.json"
    assert battery["schema:isBasedOn"]["schema:dateModified"] == "2026-03-03T16:40:00+00:00"
    assert battery["schema:description"] == [
        "Primary review artifact for BattINFO/BDF battery descriptor structure.",
        "Values are representative and intended for schema/mapping review.",
        "This is the primary end-to-end review file for battery descriptor changes.",
        "Update this file whenever schema or mapping decisions change.",
    ]

    assert battery["schema:size"] == "R26650"
    property_nodes = battery["hasProperty"]
    assert len(property_nodes) == len(doc["specification"]["property"])

    def _node_of_type(type_name: str) -> dict:
        return next(node for node in property_nodes if type_name in node["@type"])

    nominal_capacity = _node_of_type("NominalCapacity")
    assert nominal_capacity["@type"] == ["NominalCapacity", "ConventionalProperty"]
    assert nominal_capacity["hasNumericalPart"]["@type"] == "RealData"
    assert nominal_capacity["hasNumericalPart"]["hasNumericalValue"] == 2.5
    assert nominal_capacity["hasNumericalPart"]["schema:valueReference"] == {
        "@type": "schema:DefinedTerm",
        "schema:name": "typical_value",
    }
    assert nominal_capacity["hasMeasurementUnit"] == "https://w3id.org/emmo#AmpereHour"

    nominal_voltage = _node_of_type("NominalVoltage")
    assert nominal_voltage["hasNumericalPart"]["hasNumericalValue"] == 3.3
    assert nominal_voltage["hasMeasurementUnit"] == "https://w3id.org/emmo#Volt"

    mass = _node_of_type("Mass")
    assert mass["hasNumericalPart"]["hasNumericalValue"] == 76.0
    assert mass["hasMeasurementUnit"] == "https://w3id.org/emmo#Gram"

    impedance = _node_of_type("ElectricImpedance")
    assert impedance["schema:value"] == "5-8 (1 kHz, 50% SOC)"
    assert impedance["hasMeasurementUnit"] == "https://w3id.org/emmo#MilliOhm"

    cycle_life = _node_of_type("CycleLife")
    assert cycle_life["hasNumericalPart"]["hasNumericalValue"] == 2000
    assert cycle_life["hasMeasurementUnit"] == "https://w3id.org/emmo#EMMO_5ebd5e01_0ed3_49a2_a30d_cd05cbe72978"

    charging_temperature_max = _node_of_type("MaximumChargingTemperature")
    assert charging_temperature_max["hasNumericalPart"]["hasNumericalValue"] == 45.0
    assert (
        charging_temperature_max["hasMeasurementUnit"]
        == "https://w3id.org/emmo#EMMO_36a9bf69_483b_42fd_8a0c_7ac9206320bc"
    )

    assert len(instances) == 2
    assert instances[0]["@id"] == "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8"
    assert instances[0]["schema:name"] == "lfp_k1"
    assert instances[0]["@type"] == "schema:IndividualProduct"
    assert instances[0]["schema:isVariantOf"] == {"@id": "https://w3id.org/battinfo/cell-type/9qfb-4wrn-ynwc-ayjw"}
    assert instances[1]["schema:description"] == "Second instance from same procurement lot."


def test_jsonld_validator_rejects_unknown_relative_type() -> None:
    payload = {
        "@context": "https://w3id.org/emmo/domain/battery/context",
        "@graph": [{"@id": "https://example.org/x", "@type": "Real"}],
    }
    result = validate_jsonld(payload)
    assert not result.ok
    assert "relative @type reference 'Real'" in result.errors[0]


def test_descriptor_maps_to_batterypass_shape() -> None:
    doc = _load_json("assets/examples/battery-descriptors/minimal.example.json")
    mapped = to_jsonld(doc, target="batterypass")

    assert mapped["@type"] == "batterypass:BatteryPassportRecord"
    assert "@graph" in mapped
    battery = mapped["@graph"][0]
    assert "BatteryCell" in battery["@type"]
    assert "CylindricalBattery" in battery["@type"]
    assert mapped["batterypass:version"] == "1.2.0"
