from __future__ import annotations

from typing import Any


BATTERY_TYPE_MAP = {
    "cell": "battinfo:BatteryCell",
    "module": "battinfo:BatteryModule",
    "pack": "battinfo:BatteryPack",
    "system": "battinfo:BatterySystem",
}


def _quantity_to_jsonld(quantity: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(quantity, dict):
        return None
    value = quantity.get("value")
    unit = quantity.get("unit")
    if value is None or unit is None:
        return None

    out: dict[str, Any] = {
        "@type": "schema:QuantitativeValue",
        "schema:value": value,
        "schema:unitText": unit,
    }
    unit_uri = quantity.get("unit_uri")
    if unit_uri:
        out["schema:unitCode"] = unit_uri
    return out


def _agent_to_jsonld(agent: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(agent, dict):
        return None
    out: dict[str, Any] = {"@type": "schema:Organization"}
    if agent.get("name"):
        out["schema:name"] = agent["name"]
    if agent.get("organization"):
        out["schema:legalName"] = agent["organization"]
    if agent.get("email"):
        out["schema:email"] = agent["email"]
    if agent.get("orcid"):
        out["schema:identifier"] = agent["orcid"]
    if len(out) == 1:
        return None
    return out


def _battery_to_jsonld(battery: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "@id": battery.get("id"),
        "@type": BATTERY_TYPE_MAP.get(str(battery.get("type")), "battinfo:Battery"),
    }
    if battery.get("chemistry"):
        out["battinfo:chemistry"] = battery["chemistry"]

    manufacturer = _agent_to_jsonld(battery.get("manufacturer"))
    if manufacturer:
        out["schema:manufacturer"] = manufacturer

    for key, pred in (
        ("nominal_capacity", "battinfo:nominalCapacity"),
        ("nominal_voltage", "battinfo:nominalVoltage"),
        ("mass", "battinfo:mass"),
    ):
        quant = _quantity_to_jsonld(battery.get(key))
        if quant:
            out[pred] = quant
    return out


def _measurements_to_jsonld(measurements: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(measurements, list):
        return out
    for measurement in measurements:
        if not isinstance(measurement, dict):
            continue
        quantity = _quantity_to_jsonld(measurement.get("quantity"))
        node: dict[str, Any] = {"@type": "schema:Observation"}
        if measurement.get("name"):
            node["schema:name"] = measurement["name"]
        if measurement.get("property"):
            node["schema:additionalType"] = measurement["property"]
        if measurement.get("method"):
            node["schema:measurementMethod"] = measurement["method"]
        if measurement.get("timestamp"):
            node["schema:startDate"] = measurement["timestamp"]
        if quantity:
            node["schema:value"] = quantity.get("schema:value")
            node["schema:unitText"] = quantity.get("schema:unitText")
            if quantity.get("schema:unitCode"):
                node["schema:unitCode"] = quantity["schema:unitCode"]
        out.append(node)
    return out


def _base_context() -> list[Any]:
    return [
        "https://w3id.org/emmo/domain/battery/context",
        {
            "schema": "https://schema.org/",
            "battinfo": "https://w3id.org/battinfo#",
            "hasBattery": {"@id": "battinfo:hasBattery", "@type": "@id"},
            "hasMeasurement": {"@id": "battinfo:hasMeasurement"},
        },
    ]


def _to_domain_battery_jsonld(data: dict[str, Any]) -> dict[str, Any]:
    record = data.get("record", {})
    battery = data.get("battery", {})
    measurements = data.get("measurements")

    doc: dict[str, Any] = {
        "@context": _base_context(),
        "@id": record.get("id"),
        "@type": "battinfo:BatteryMetadataRecord",
        "hasBattery": _battery_to_jsonld(battery),
    }
    if record.get("title"):
        doc["schema:name"] = record["title"]
    if record.get("description"):
        doc["schema:description"] = record["description"]
    if record.get("created_at"):
        doc["schema:dateCreated"] = record["created_at"]
    if record.get("source"):
        doc["schema:isBasedOn"] = record["source"]
    if data.get("profile"):
        doc["battinfo:profile"] = data["profile"]

    author = _agent_to_jsonld(record.get("created_by"))
    if author:
        doc["schema:creator"] = author

    measurement_nodes = _measurements_to_jsonld(measurements)
    if measurement_nodes:
        doc["hasMeasurement"] = measurement_nodes
    return doc


def _to_batterypass_jsonld(data: dict[str, Any]) -> dict[str, Any]:
    doc = _to_domain_battery_jsonld(data)
    context = doc.get("@context", [])
    if isinstance(context, list):
        context.append({"batterypass": "https://w3id.org/batterypass#"})
        doc["@context"] = context
    doc["@type"] = ["battinfo:BatteryMetadataRecord", "batterypass:BatteryPassportRecord"]
    doc["batterypass:version"] = "1.2.0"
    return doc


def to_jsonld(data: dict[str, Any], target: str = "domain-battery") -> dict[str, Any]:
    """Transform canonical JSON to JSON-LD for a given target."""
    if target == "domain-battery":
        return _to_domain_battery_jsonld(data)
    if target == "batterypass":
        return _to_batterypass_jsonld(data)
    raise ValueError(f"Unknown mapping target '{target}'. Expected 'domain-battery' or 'batterypass'.")
