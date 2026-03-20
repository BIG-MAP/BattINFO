from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from battinfo.validate.jsonld import validate_jsonld


BATTERY_TYPE_MAP = {
    "cell": "battinfo:BatteryCell",
    "module": "battinfo:BatteryModule",
    "pack": "battinfo:BatteryPack",
    "system": "battinfo:BatterySystem",
}

CORE_PROPERTY_PREDICATES = {
    "nominal_capacity": "battinfo:nominalCapacity",
    "rated_capacity": "battinfo:ratedCapacity",
    "typical_energy": "battinfo:typicalEnergy",
    "rated_energy": "battinfo:ratedEnergy",
    "nominal_voltage": "battinfo:nominalVoltage",
    "charging_voltage": "battinfo:chargingVoltage",
    "discharging_cutoff_voltage": "battinfo:dischargingCutoffVoltage",
    "continuous_charging_current": "battinfo:continuousChargingCurrent",
    "pulse_charging_current": "battinfo:pulseChargingCurrent",
    "continuous_discharging_current": "battinfo:continuousDischargingCurrent",
    "pulse_discharging_current": "battinfo:pulseDischargingCurrent",
    "charging_temperature_min": "battinfo:chargingTemperatureMin",
    "charging_temperature_max": "battinfo:chargingTemperatureMax",
    "discharging_temperature_min": "battinfo:dischargingTemperatureMin",
    "discharging_temperature_max": "battinfo:dischargingTemperatureMax",
    "storage_temperature_min": "battinfo:storageTemperatureMin",
    "storage_temperature_max": "battinfo:storageTemperatureMax",
    "cycle_life": "battinfo:cycleLife",
    "diameter": "battinfo:diameter",
    "height": "battinfo:height",
    "mass": "battinfo:mass",
    "volume": "battinfo:volume",
    "specific_energy": "battinfo:specificEnergy",
    "energy_density": "battinfo:energyDensity",
    "internal_resistance": "battinfo:internalResistance",
    "impedance": "battinfo:impedance",
}

BATTERY_CONTEXT_URL = "https://w3id.org/emmo/domain/battery/context"

MANUAL_PROPERTY_TYPES = {
    "charging_temperature_max": {"term": "MaximumChargingTemperature"},
    "charging_temperature_min": {"term": "MinimumChargingTemperature"},
    "discharging_temperature_max": {"term": "MaximumDischargingTemperature"},
    "discharging_temperature_min": {"term": "MinimumDischargingTemperature"},
    "storage_temperature_max": {"term": "MaximumStorageTemperature"},
    "storage_temperature_min": {"term": "MinimumStorageTemperature"},
}

MANUAL_UNIT_TYPES = {
    "degC": "https://w3id.org/emmo#EMMO_36a9bf69_483b_42fd_8a0c_7ac9206320bc",
    "°C": "https://w3id.org/emmo#EMMO_36a9bf69_483b_42fd_8a0c_7ac9206320bc",
    "milliohm": "https://w3id.org/emmo#MilliOhm",
    "mΩ": "https://w3id.org/emmo#MilliOhm",
    "L": "https://w3id.org/emmo#Litre",
    "kg": "https://w3id.org/emmo#Kilogram",
}
DOI_URL_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/(10\.\S+)$", re.IGNORECASE)
DOI_LITERAL_RE = re.compile(r"^(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)$")

def _snake_to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def _citation_doi_from_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = DOI_URL_RE.match(value.strip())
    if match is None:
        return None
    return match.group(1)


def _citation_url_value(provenance: dict[str, Any] | None) -> str | None:
    if not isinstance(provenance, dict):
        return None
    citation = provenance.get("citation")
    if isinstance(citation, str):
        normalized = citation.strip()
        if normalized:
            extracted = _citation_doi_from_url(normalized)
            if extracted is not None:
                return f"https://doi.org/{extracted}"
            if DOI_LITERAL_RE.fullmatch(normalized):
                return f"https://doi.org/{normalized}"
            return normalized
    citation_doi = provenance.get("citation_doi")
    if isinstance(citation_doi, str):
        normalized = citation_doi.strip()
        if normalized:
            extracted = _citation_doi_from_url(normalized)
            if extracted is not None:
                return f"https://doi.org/{extracted}"
            return f"https://doi.org/{normalized}"
    return None


def _citation_doi_value(provenance: dict[str, Any] | None) -> str | None:
    return _citation_doi_from_url(_citation_url_value(provenance))


def _citation_to_jsonld(provenance: dict[str, Any] | None) -> dict[str, Any] | None:
    citation_url = _citation_url_value(provenance)
    if citation_url is None:
        return None
    node: dict[str, Any] = {"@id": citation_url, "@type": "schema:CreativeWork"}
    citation_doi = _citation_doi_value(provenance)
    if citation_doi is not None:
        node["bibo:doi"] = citation_doi
    return node


def _property_predicate(name: str) -> str:
    return CORE_PROPERTY_PREDICATES.get(name, f"battinfo:{_snake_to_camel(name)}")


def _normalize_term(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _entity_mapping(field: str, value: Any) -> dict[str, Any] | None:
    key = _normalize_term(value)
    if key is None:
        return None
    return _entity_type_map().get(field, {}).get(key)


def _load_mapping_file(*parts: str) -> dict[str, Any]:
    packaged_path = resources.files("battinfo").joinpath("data", "mappings", "domain-battery", *parts)
    if packaged_path.is_file():
        with packaged_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    repo_root = Path(__file__).resolve().parents[3]
    asset_path = repo_root.joinpath("assets", "mappings", "domain-battery", *parts)
    if asset_path.is_file():
        with asset_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    return {"mappings": []}


def _load_profile_file(*parts: str) -> dict[str, Any]:
    packaged_path = resources.files("battinfo").joinpath("data", "profiles", "cell-descriptor", *parts)
    if packaged_path.is_file():
        with packaged_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    return {}


@lru_cache(maxsize=1)
def _property_type_map() -> dict[str, dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}

    for filename in ("property_map.candidates.json", "property_map.curated.json"):
        data = _load_mapping_file(filename)
        for item in data.get("mappings", []):
            key = item.get("key")
            if not isinstance(key, str):
                continue

            term = item.get("class_pref_label") or item.get("class_label")
            iri = item.get("class_iri")
            if isinstance(term, str) and term and isinstance(iri, str) and iri:
                merged.setdefault(key, {"term": term, "iri": iri})

    merged.update(MANUAL_PROPERTY_TYPES)
    return merged


@lru_cache(maxsize=1)
def _descriptor_profile() -> dict[str, Any]:
    return _load_profile_file("profile.json")


@lru_cache(maxsize=1)
def _entity_type_map() -> dict[str, dict[str, dict[str, Any]]]:
    data = _load_mapping_file("entity_type_map.json")
    mappings = data.get("mappings")
    if not isinstance(mappings, dict):
        return {}

    normalized: dict[str, dict[str, dict[str, Any]]] = {}
    for field, field_map in mappings.items():
        if not isinstance(field, str) or not isinstance(field_map, dict):
            continue
        normalized[field] = {}
        for key, value in field_map.items():
            if isinstance(key, str) and isinstance(value, dict):
                normalized[field][key] = value
    return normalized


@lru_cache(maxsize=1)
def _allowed_extension_terms() -> set[str]:
    data = _load_mapping_file("extension_policy.json")
    allowed = set()
    for item in data.get("allowed_extensions", []):
        term = item.get("term")
        if isinstance(term, str) and term:
            allowed.add(term)
    return allowed


@lru_cache(maxsize=1)
def _unit_type_map() -> dict[str, str]:
    merged: dict[str, str] = {}

    for filename in ("unit_map.candidates.json", "unit_map.curated.json"):
        data = _load_mapping_file(filename)
        for item in data.get("mappings", []):
            symbol = item.get("symbol")
            iri = item.get("unit_iri")
            if isinstance(symbol, str) and symbol and isinstance(iri, str) and iri:
                merged.setdefault(symbol, iri)

    merged.update(MANUAL_UNIT_TYPES)
    return merged


def _property_type_term(name: str) -> str:
    mapping = _property_type_map().get(name)
    if mapping and mapping.get("term"):
        return mapping["term"]
    return f"battinfo:{_snake_to_camel(name)}"


def _unit_iri(unit: str | None) -> str | None:
    if not isinstance(unit, str) or not unit:
        return None
    return _unit_type_map().get(unit)


def _epoch_to_iso8601(value: Any) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _value_reference_term(field: str) -> dict[str, Any]:
    return {"@type": "schema:DefinedTerm", "schema:name": field}


def _profile_binding_target(path: str, default: str) -> str:
    bindings = _descriptor_profile().get("field_bindings", {})
    binding = bindings.get(path, {})
    target = binding.get("jsonld_target")
    return target if isinstance(target, str) and target else default


def _descriptor_quantity_node(name: str, quantity: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(quantity, dict):
        return None

    node: dict[str, Any] = {"@type": [_property_type_term(name), "ConventionalProperty"]}

    numeric_parts: list[dict[str, Any]] = []
    for field in ("value", "min_value", "max_value", "typical_value"):
        if quantity.get(field) is None:
            continue
        part: dict[str, Any] = {"@type": "RealData", "hasNumericalValue": quantity[field]}
        if field != "value":
            part["schema:valueReference"] = _value_reference_term(field)
        numeric_parts.append(part)

    if numeric_parts:
        node["hasNumericalPart"] = numeric_parts[0] if len(numeric_parts) == 1 else numeric_parts

    if quantity.get("value_text"):
        node["schema:value"] = quantity["value_text"]

    unit = quantity.get("unit") or quantity.get("unit_text")
    iri = _unit_iri(unit)
    if iri:
        node["hasMeasurementUnit"] = iri
    elif unit:
        node["schema:unitText"] = unit

    return node if len(node) > 1 else None


def _quantity_to_jsonld(quantity: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(quantity, dict):
        return None

    out: dict[str, Any] = {"@type": "schema:QuantitativeValue"}
    has_content = False

    if quantity.get("value") is not None:
        out["schema:value"] = quantity["value"]
        has_content = True
    if quantity.get("min_value") is not None:
        out["schema:minValue"] = quantity["min_value"]
        has_content = True
    if quantity.get("max_value") is not None:
        out["schema:maxValue"] = quantity["max_value"]
        has_content = True
    if quantity.get("typical_value") is not None:
        out["battinfo:typicalValue"] = quantity["typical_value"]
        has_content = True
    if quantity.get("value_text"):
        out["battinfo:valueText"] = quantity["value_text"]
        has_content = True

    unit = quantity.get("unit") or quantity.get("unit_text")
    if unit:
        out["schema:unitText"] = unit
        has_content = True

    unit_uri = quantity.get("unit_uri")
    if unit_uri:
        out["schema:unitCode"] = unit_uri

    return out if has_content else None


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


def _manufacturer_to_jsonld(manufacturer: Any) -> dict[str, Any] | None:
    if isinstance(manufacturer, str) and manufacturer.strip():
        return {"@type": "schema:Organization", "schema:name": manufacturer}
    if isinstance(manufacturer, dict):
        return _agent_to_jsonld(manufacturer)
    return None


def _comment_value(comment: Any) -> list[str] | str | None:
    if isinstance(comment, str) and comment:
        return comment
    if isinstance(comment, list):
        values = [item for item in comment if isinstance(item, str) and item]
        if values:
            return values
    return None


def _merge_text_values(*values: Any) -> list[str] | str | None:
    merged: list[str] = []
    for value in values:
        normalized = _comment_value(value)
        if isinstance(normalized, str):
            merged.append(normalized)
        elif isinstance(normalized, list):
            merged.extend(normalized)
    if not merged:
        return None
    deduped = list(dict.fromkeys(merged))
    return deduped[0] if len(deduped) == 1 else deduped


def _property_value_node(property_id: str, name: str, value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "@type": "schema:PropertyValue",
        "schema:propertyID": property_id,
        "schema:name": name,
        "schema:value": value,
    }


def _descriptor_construction_to_jsonld(construction: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(construction, dict):
        return []

    nodes: list[dict[str, Any]] = []
    for property_id, name in (
        ("construction.assembly_type", "Assembly Type"),
        ("construction.layering", "Layering"),
        ("construction.layer_count", "Layer Count"),
        ("construction.comment", "Construction Comment"),
    ):
        value = construction.get(property_id.rsplit(".", 1)[-1])
        node = _property_value_node(property_id, name, value)
        if node is not None:
            nodes.append(node)
    return nodes


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
            if quantity.get("schema:value") is not None:
                node["schema:value"] = quantity["schema:value"]
            if quantity.get("schema:unitText") is not None:
                node["schema:unitText"] = quantity["schema:unitText"]
            if quantity.get("schema:unitCode"):
                node["schema:unitCode"] = quantity["schema:unitCode"]
        out.append(node)
    return out


def _descriptor_specification_to_jsonld(specification: dict[str, Any]) -> dict[str, Any]:
    manufacturer = specification.get("manufacturer")
    model = specification.get("model")
    manufacturer_target = _profile_binding_target("specification.manufacturer", "schema:manufacturer")
    model_target = _profile_binding_target("specification.model", "schema:model")
    size_code_target = _profile_binding_target("specification.size_code", "schema:size")
    specification_comment_target = _profile_binding_target("specification.comment", "schema:description")
    format_mapping = _entity_mapping("format", specification.get("format")) or {"battery_types": ["BatteryCell"]}
    battery_type_list = list(format_mapping.get("battery_types", ["BatteryCell"]))

    chemistry_mapping = _entity_mapping("chemistry", specification.get("chemistry"))
    if chemistry_mapping:
        battery_type_list.extend(chemistry_mapping.get("battery_types", []))

    positive_electrode = _entity_mapping("positive_electrode_basis", specification.get("positive_electrode_basis"))
    if positive_electrode:
        battery_type_list.extend(positive_electrode.get("battery_types", []))

    negative_electrode = _entity_mapping("negative_electrode_basis", specification.get("negative_electrode_basis"))
    if negative_electrode:
        battery_type_list.extend(negative_electrode.get("battery_types", []))

    battery_type_list.append("schema:ProductModel")
    battery_types_deduped = list(dict.fromkeys(battery_type_list))

    battery: dict[str, Any] = {
        "@id": specification.get("id"),
        "@type": battery_types_deduped if len(battery_types_deduped) > 1 else battery_types_deduped[0],
    }

    if isinstance(manufacturer, str) and manufacturer and isinstance(model, str) and model:
        battery["schema:name"] = f"{manufacturer} {model}"
    elif isinstance(model, str) and model:
        battery["schema:name"] = model

    if isinstance(model, str) and model:
        battery[model_target] = model

    manufacturer_node = _manufacturer_to_jsonld(manufacturer)
    if manufacturer_node:
        battery[manufacturer_target] = manufacturer_node

    if specification.get("size_code"):
        battery[size_code_target] = specification["size_code"]

    if positive_electrode:
        relation = positive_electrode.get("relation")
        node_type = positive_electrode.get("node_type")
        if isinstance(relation, str) and relation and isinstance(node_type, str) and node_type:
            battery[relation] = {"@type": node_type}

    if negative_electrode:
        relation = negative_electrode.get("relation")
        node_type = negative_electrode.get("node_type")
        if isinstance(relation, str) and relation and isinstance(node_type, str) and node_type:
            battery[relation] = {"@type": node_type}

    properties = specification.get("property")
    if isinstance(properties, dict):
        property_nodes: list[dict[str, Any]] = []
        for name, quantity in sorted(properties.items()):
            quant = _descriptor_quantity_node(name, quantity if isinstance(quantity, dict) else {})
            if quant:
                property_nodes.append(quant)
        if property_nodes:
            battery["hasProperty"] = property_nodes

    construction_nodes = _descriptor_construction_to_jsonld(specification.get("construction"))
    if construction_nodes:
        battery["schema:additionalProperty"] = construction_nodes[0] if len(construction_nodes) == 1 else construction_nodes

    comment = _comment_value(specification.get("comment"))
    if comment is not None:
        battery[specification_comment_target] = comment

    return battery


def _descriptor_instances_to_jsonld(instances: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(instances, list):
        return out

    instance_type_target = _profile_binding_target("instances.type", "schema:IndividualProduct")
    instance_name_target = _profile_binding_target("instances.name", "schema:name")
    instance_serial_target = _profile_binding_target("instances.serial_number", "schema:serialNumber")
    instance_comment_target = _profile_binding_target("instances.comment", "schema:description")

    for instance in instances:
        if not isinstance(instance, dict):
            continue
        node: dict[str, Any] = {"@type": instance_type_target}
        if instance.get("id"):
            node["@id"] = instance["id"]
        if instance.get("name"):
            node[instance_name_target] = instance["name"]
        if instance.get("serial_number"):
            node[instance_serial_target] = instance["serial_number"]
        comment = _comment_value(instance.get("comment"))
        if comment is not None:
            node[instance_comment_target] = comment
        out.append(node)
    return out


def _descriptor_provenance_to_jsonld(provenance: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(provenance, dict):
        return None

    node: dict[str, Any] = {"@type": "schema:CreativeWork"}
    if provenance.get("source_url"):
        node["@id"] = provenance["source_url"]
    if provenance.get("source_type"):
        node["schema:additionalType"] = provenance["source_type"]
    if provenance.get("source_name"):
        node["schema:name"] = provenance["source_name"]
    if provenance.get("source_file"):
        node["schema:identifier"] = provenance["source_file"]
    if provenance.get("source_url"):
        node["schema:url"] = provenance["source_url"]
    retrieved_at = _epoch_to_iso8601(provenance.get("retrieved_at"))
    if retrieved_at is not None:
        node["schema:dateModified"] = retrieved_at
    if provenance.get("workflow_version"):
        node["schema:version"] = provenance["workflow_version"]
    comment = _comment_value(provenance.get("comment"))
    if comment is not None:
        node["schema:description"] = comment
    return node if len(node) > 1 else None


def _base_context(
    *,
    include_battinfo: bool = True,
    include_has_battery: bool = True,
    include_has_measurement: bool = True,
    include_has_property: bool = False,
    include_bibo: bool = False,
) -> list[Any]:
    context_entry: dict[str, Any] = {
        "schema": "https://schema.org/",
    }
    if include_bibo:
        context_entry["bibo"] = "http://purl.org/ontology/bibo/"
    if include_battinfo:
        context_entry["battinfo"] = "https://w3id.org/battinfo#"
    if include_has_measurement:
        context_entry["hasMeasurement"] = {"@id": "battinfo:hasMeasurement"}
    if include_has_battery:
        context_entry["hasBattery"] = {"@id": "battinfo:hasBattery", "@type": "@id"}
    return [BATTERY_CONTEXT_URL, context_entry]


def _to_domain_battery_jsonld_legacy(data: dict[str, Any]) -> dict[str, Any]:
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


def _to_domain_battery_jsonld_descriptor(data: dict[str, Any]) -> dict[str, Any]:
    specification = data.get("specification", {})
    battery = _descriptor_specification_to_jsonld(specification if isinstance(specification, dict) else {})
    schema_version_target = _profile_binding_target("schema_version", "schema:schemaVersion")
    comment_target = _profile_binding_target("comment", "schema:description")
    provenance_target = _profile_binding_target("provenance", "schema:isBasedOn")
    instance_relation_target = _profile_binding_target("instances.relation_to_specification", "schema:isVariantOf")

    if data.get("schema_version") is not None:
        battery[schema_version_target] = data.get("schema_version")

    battery[comment_target] = _merge_text_values(battery.get(comment_target), data.get("comment"))
    if battery[comment_target] is None:
        battery.pop(comment_target, None)

    provenance = _descriptor_provenance_to_jsonld(data.get("provenance"))
    if provenance:
        battery[provenance_target] = provenance

    graph_nodes: list[dict[str, Any]] = [battery]

    instances = _descriptor_instances_to_jsonld(data.get("instances"))
    if instances:
        for instance in instances:
            instance[instance_relation_target] = {"@id": battery.get("@id")}
        graph_nodes.extend(instances)

    doc: dict[str, Any] = {
        "@context": _base_context(
            include_battinfo=False,
            include_has_battery=False,
            include_has_measurement=False,
            include_has_property=True,
            include_bibo=_citation_doi_value(data.get("provenance")) is not None,
        ),
        "@graph": graph_nodes,
    }
    citation = _citation_to_jsonld(data.get("provenance"))
    if citation is not None:
        battery["schema:citation"] = citation

    return doc


def _to_domain_battery_jsonld(data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(data.get("specification"), dict) and data.get("schema_version") is not None:
        return _to_domain_battery_jsonld_descriptor(data)
    return _to_domain_battery_jsonld_legacy(data)


def _to_batterypass_jsonld(data: dict[str, Any]) -> dict[str, Any]:
    doc = _to_domain_battery_jsonld(data)
    context = doc.get("@context", [])
    if isinstance(context, list):
        context.append({"batterypass": "https://w3id.org/batterypass#"})
        doc["@context"] = context

    current_type = doc.get("@type")
    if current_type is None:
        doc["@type"] = "batterypass:BatteryPassportRecord"
    elif isinstance(current_type, list):
        doc["@type"] = [*current_type, "batterypass:BatteryPassportRecord"]
    else:
        doc["@type"] = [current_type, "batterypass:BatteryPassportRecord"]
    doc["batterypass:version"] = "1.2.0"
    return doc


def to_jsonld(data: dict[str, Any], target: str = "domain-battery") -> dict[str, Any]:
    """Transform canonical JSON to JSON-LD for a given target."""
    if target == "domain-battery":
        doc = _to_domain_battery_jsonld(data)
    elif target == "batterypass":
        doc = _to_batterypass_jsonld(data)
    else:
        raise ValueError(f"Unknown mapping target '{target}'. Expected 'domain-battery' or 'batterypass'.")
    validation = validate_jsonld(doc)
    if not validation.ok:
        raise ValueError(f"json-ld validation failed: {'; '.join(validation.errors)}")
    return doc

