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


# EMMO domain-battery context.  The w3id.org redirect resolves to the latest
# published context; EMMO does not publish versioned context IRIs separately from
# the ontology.  Context terms use UUID-based IRIs so additions are backward-
# compatible.  The version of domain-battery this codebase was validated against
# is recorded in ontology/battinfo.ttl (owl:imports) and in this comment: 0.18.7.
BATTERY_CONTEXT_URL = "https://w3id.org/emmo/domain/battery/context"

MANUAL_PROPERTY_TYPES = {
    "minimum_capacity": {"term": "MinimumCapacity"},
    "maximum_charging_temperature": {"term": "MaximumChargingTemperature"},
    "minimum_charging_temperature": {"term": "MinimumChargingTemperature"},
    "maximum_discharging_temperature": {"term": "MaximumDischargingTemperature"},
    "minimum_discharging_temperature": {"term": "MinimumDischargingTemperature"},
    "maximum_storage_temperature": {"term": "MaximumStorageTemperature"},
    "minimum_storage_temperature": {"term": "MinimumStorageTemperature"},
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
    "mol/L": "https://w3id.org/emmo#MolePerLitre",
}
CONVERTER_LABEL_TO_TYPE = {label: type_name for type_name, label in {
    "Aluminium": "Aluminium",
    "CarbonBlack": "Carbon black",
    "Copper": "Copper",
    "EthylMethylCarbonate": "EMC",
    "EthyleneCarbonate": "EC",
    "FluoroethyleneCarbonate": "FEC",
    "Graphite": "Graphite",
    "LithiumBisfluorosulfonylimide": "LiFSI",
    "LithiumElectrode": "Li-metal",
    "LithiumHexafluorophosphate": "LiPF6",
    "LithiumIronPhosphate": "LFP",
    "LithiumNickelManganeseCobaltOxide": "NMC",
    "Polypropylene": "PP",
    "PolyvinylideneFluoride": "PVDF",
    "StainlessSteel": "Stainless steel",
    "TrisTrimethylsilyPhosphite": "TMSPi",
    "VinyleneCarbonate": "VC",
}.items()}
CONVERTER_UNIT_TEXT_TO_TOKEN = {
    "C": "emmo:CelsiusTemperature",
    "%": "unit:PERCENT",
    "g/cm3": "emmo:GramPerCubicCentiMetre",
    "mPa.s": "unit:MilliPA-SEC",
    "mS/cm": "unit:MilliS-PER-CentiM",
    "mm": "unit:MilliM",
    "mol/L": "unit:MOL-PER-L",
    "uL": "unit:MicroL",
    "um": "emmo:MicroMetre",
}
CONVERTER_PROPERTY_TYPES = {
    "concentration": "AmountConcentration",
    "conductivity": "ElectrolyticConductivity",
    "d50_particle_size": "D50ParticleSize",
    "density": "Density",
    "diameter": "Diameter",
    "fill_volume": "Volume",
    "loading": "MassLoading",
    "mass_fraction": "MassFraction",
    "porosity": "Porosity",
    "temperature": "CelsiusTemperature",
    "thickness": "Thickness",
    "viscosity": "DynamicViscosity",
    "volume_fraction": "VolumeFraction",
}
CONVERTER_COATING_PROPERTY_TYPES = {
    **CONVERTER_PROPERTY_TYPES,
    "thickness": "CalenderedCoatingThickness",
}
CONVERTER_FAMILY_TYPES = {
    "aqueous": "AqueousElectrolyte",
    "gel": "GelElectrolyte",
    "hybrid": "HybridElectrolyte",
    "ionic_liquid": "IonicLiquidElectrolyte",
    "organic": "OrganicElectrolyte",
    "solid": "SolidElectrolyte",
}
CONVERTER_FORMAT_TYPES = {
    "coin": "CoinCell",
    "cylindrical": "CylindricalBattery",
    "pouch": "PouchCell",
    "prismatic": "PrismaticBattery",
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
def _material_name_map() -> dict[str, str]:
    """Return a dict mapping lowercase aliases to EMMO class terms."""
    data = _load_mapping_file("material_map.json")
    result: dict[str, str] = {}
    for item in data.get("mappings", []):
        emmo_class = item.get("emmo_class")
        if not isinstance(emmo_class, str) or not emmo_class:
            continue
        symbol = item.get("symbol", "")
        if symbol:
            result[symbol.lower()] = emmo_class
        for alias in item.get("aliases", []):
            if isinstance(alias, str) and alias:
                result[alias.lower()] = emmo_class
    return result


def _material_emmo_class(name: str) -> str | None:
    """Resolve a material name to its EMMO class term, or None if unknown."""
    if not isinstance(name, str) or not name:
        return None
    return _material_name_map().get(name.strip().lower())


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



def _profile_binding_target(path: str, default: str) -> str:
    bindings = _descriptor_profile().get("field_bindings", {})
    binding = bindings.get(path, {})
    target = binding.get("jsonld_target")
    return target if isinstance(target, str) and target else default


def _descriptor_quantity_node(name: str, quantity: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(quantity, dict):
        return None

    node: dict[str, Any] = {"@type": [_property_type_term(name), "ConventionalProperty"]}

    # Emit the primary (nominal/typical) value only.  EMMO's canonical pattern for a
    # ConventionalProperty is a single RealData node; a range (min/max) is correctly
    # represented as separate hasProperty entries with distinct EMMO property classes
    # (e.g. MinimumCapacity alongside NominalCapacity).  Min/max bounds are preserved
    # in the canonical JSON record and are available to JSON consumers.
    primary = quantity.get("value") if quantity.get("value") is not None else quantity.get("typical_value")
    if primary is not None:
        node["hasNumericalPart"] = {"@type": "RealData", "hasNumericalValue": primary}

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


def _agent_text_node(name: Any) -> dict[str, Any] | None:
    if isinstance(name, str) and name.strip():
        return {"@type": "schema:Organization", "schema:name": name}
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
        ("construction.assembly_sequence", "Assembly Sequence"),
        ("construction.layering", "Layering"),
        ("construction.layer_count", "Layer Count"),
        ("construction.comment", "Construction Comment"),
    ):
        value = construction.get(property_id.rsplit(".", 1)[-1])
        node = _property_value_node(property_id, name, value)
        if node is not None:
            nodes.append(node)
    return nodes


def _hardware_measured_properties(properties: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(properties, dict):
        return []
    out: list[dict[str, Any]] = []
    for name, quantity in sorted(properties.items()):
        node = _descriptor_quantity_node(name, quantity if isinstance(quantity, dict) else {})
        if node is not None:
            out.append(node)
    return out


def _descriptor_coin_hardware_to_jsonld(coin_hardware: dict[str, Any] | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not isinstance(coin_hardware, dict):
        return None, []

    case_node = None
    case = coin_hardware.get("case")
    if isinstance(case, dict):
        case_node = {}
        if case.get("size_code"):
            case_node["schema:size"] = case["size_code"]
        if case.get("material"):
            case_node["schema:material"] = case["material"]
        manufacturer_node = _manufacturer_to_jsonld(case.get("manufacturer"))
        if manufacturer_node is not None:
            case_node["schema:manufacturer"] = manufacturer_node
        supplier_node = _agent_text_node(case.get("supplier"))
        if supplier_node is not None:
            case_node["schema:supplier"] = supplier_node
        if case.get("product_id"):
            case_node["schema:productID"] = case["product_id"]
        measured = _hardware_measured_properties(case.get("property"))
        if measured:
            case_node["hasMeasuredProperty"] = measured[0] if len(measured) == 1 else measured
        if case.get("comment"):
            case_node["schema:description"] = case["comment"]
        case_constituents: list[dict[str, Any]] = []
        if case.get("lid_coating"):
            case_constituents.append(
                {
                    "@type": "schema:Thing",
                    "schema:additionalType": "CellLid",
                    "hasCoating": {"schema:material": case["lid_coating"]},
                }
            )
        if case.get("can_coating"):
            case_constituents.append(
                {
                    "@type": "schema:Thing",
                    "schema:additionalType": "CellCan",
                    "hasCoating": {"schema:material": case["can_coating"]},
                }
            )
        for type_name, component in (("CellLid", coin_hardware.get("lid")), ("CellCan", coin_hardware.get("can"))):
            if not isinstance(component, dict):
                continue
            node: dict[str, Any] = {"@type": "schema:Thing", "schema:additionalType": type_name}
            if component.get("material"):
                node["schema:material"] = component["material"]
            if component.get("coating"):
                node["hasCoating"] = {"schema:material": component["coating"]}
            manufacturer_node = _manufacturer_to_jsonld(component.get("manufacturer"))
            if manufacturer_node is not None:
                node["schema:manufacturer"] = manufacturer_node
            supplier_node = _agent_text_node(component.get("supplier"))
            if supplier_node is not None:
                node["schema:supplier"] = supplier_node
            if component.get("product_id"):
                node["schema:productID"] = component["product_id"]
            measured = _hardware_measured_properties(component.get("property"))
            if measured:
                node["hasMeasuredProperty"] = measured[0] if len(measured) == 1 else measured
            if component.get("comment"):
                node["schema:description"] = component["comment"]
            if len(node) > 1:
                case_constituents.append(node)
        if case_constituents:
            case_node["hasConstituent"] = case_constituents[0] if len(case_constituents) == 1 else case_constituents
        if not case_node:
            case_node = None

    extra_nodes: list[dict[str, Any]] = []
    for name, type_name in (("spring", "Spring"), ("spacer", "Spacer")):
        component = coin_hardware.get(name)
        if not isinstance(component, dict):
            continue
        node: dict[str, Any] = {"@type": "schema:Thing", "schema:additionalType": type_name}
        if component.get("material"):
            node["schema:material"] = component["material"]
        manufacturer_node = _manufacturer_to_jsonld(component.get("manufacturer"))
        if manufacturer_node is not None:
            node["schema:manufacturer"] = manufacturer_node
        supplier_node = _agent_text_node(component.get("supplier"))
        if supplier_node is not None:
            node["schema:supplier"] = supplier_node
        if component.get("product_id"):
            node["schema:productID"] = component["product_id"]
        measured = _hardware_measured_properties(component.get("property"))
        if measured:
            node["hasMeasuredProperty"] = measured[0] if len(measured) == 1 else measured
        if component.get("comment"):
            node["schema:description"] = component["comment"]
        if len(node) > 1:
            extra_nodes.append(node)

    return case_node, extra_nodes


def _converter_quantity_node(
    name: str,
    quantity: dict[str, Any] | None,
    *,
    property_types: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(quantity, dict) or quantity.get("value") is None:
        return None
    type_name = (property_types or CONVERTER_PROPERTY_TYPES).get(name)
    if type_name is None:
        return None
    node: dict[str, Any] = {
        "@type": type_name,
        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": quantity["value"]},
    }
    unit_token = CONVERTER_UNIT_TEXT_TO_TOKEN.get(str(quantity.get("unit") or quantity.get("unit_text") or ""))
    if unit_token is not None:
        node["hasMeasurementUnit"] = unit_token
    return node


def _converter_measured_properties(
    properties: dict[str, Any] | None,
    *,
    property_types: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(properties, dict):
        return []
    out: list[dict[str, Any]] = []
    for name, quantity in sorted(properties.items()):
        node = _converter_quantity_node(name, quantity if isinstance(quantity, dict) else None, property_types=property_types)
        if node is not None:
            out.append(node)
    return out


def _converter_component_metadata(node: dict[str, Any], component: dict[str, Any]) -> None:
    manufacturer_node = _agent_text_node(component.get("manufacturer"))
    if manufacturer_node is not None:
        node["schema:manufacturer"] = manufacturer_node
    supplier_node = _agent_text_node(component.get("supplier"))
    if supplier_node is not None:
        node["schema:supplier"] = supplier_node
    if component.get("product_id"):
        node["schema:productID"] = component["product_id"]
    if component.get("comment"):
        node["rdfs:comment"] = component["comment"]


def _converter_named_node(
    component: dict[str, Any],
    *,
    wrapper_type: str | None = None,
    property_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    type_name = CONVERTER_LABEL_TO_TYPE.get(str(component.get("name") or ""), None)
    if wrapper_type and type_name:
        node: dict[str, Any] = {"@type": [wrapper_type, type_name]}
    elif wrapper_type:
        node = {"@type": wrapper_type}
    elif type_name:
        node = {"@type": type_name}
    else:
        node = {"@type": "schema:Thing"}
        if component.get("name"):
            node["schema:name"] = component["name"]
    _converter_component_metadata(node, component)
    measured = _converter_measured_properties(component.get("property"), property_types=property_types)
    if measured:
        node["hasMeasuredProperty"] = measured[0] if len(measured) == 1 else measured
    return node


def _converter_electrode_node(electrode: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(electrode, dict):
        return None
    node: dict[str, Any] = {"@type": "Electrode"}
    _converter_component_metadata(node, electrode)
    collector = electrode.get("current_collector")
    if isinstance(collector, dict):
        node["hasCurrentCollector"] = _converter_named_node(collector, wrapper_type="CurrentCollector")
    coating = electrode.get("coating")
    if isinstance(coating, dict):
        coating_node: dict[str, Any] = {"@type": "ElectrodeCoating"}
        _converter_component_metadata(coating_node, coating)
        component_groups = coating.get("component")
        if isinstance(component_groups, dict):
            if isinstance(component_groups.get("active_material"), list):
                items = [
                    _converter_named_node(item, property_types=CONVERTER_PROPERTY_TYPES)
                    for item in component_groups["active_material"]
                    if isinstance(item, dict)
                ]
                items = [item for item in items if item]
                if items:
                    coating_node["hasActiveMaterial"] = items[0] if len(items) == 1 else items
            if isinstance(component_groups.get("binder"), list):
                items = [
                    _converter_named_node(item, wrapper_type="Binder", property_types=CONVERTER_PROPERTY_TYPES)
                    for item in component_groups["binder"]
                    if isinstance(item, dict)
                ]
                items = [item for item in items if item]
                if items:
                    coating_node["hasBinder"] = items[0] if len(items) == 1 else items
            if isinstance(component_groups.get("additive"), list):
                items = [
                    _converter_named_node(item, wrapper_type="ConductiveAdditive", property_types=CONVERTER_PROPERTY_TYPES)
                    for item in component_groups["additive"]
                    if isinstance(item, dict)
                ]
                items = [item for item in items if item]
                if items:
                    coating_node["hasConductiveAdditive"] = items[0] if len(items) == 1 else items
        measured = _converter_measured_properties(coating.get("property"), property_types=CONVERTER_COATING_PROPERTY_TYPES)
        if measured:
            coating_node["hasMeasuredProperty"] = measured[0] if len(measured) == 1 else measured
        node["hasCoating"] = coating_node
    measured = _converter_measured_properties(electrode.get("property"), property_types=CONVERTER_PROPERTY_TYPES)
    if measured:
        node["hasMeasuredProperty"] = measured[0] if len(measured) == 1 else measured
    return node


def _converter_electrolyte_node(electrolyte: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(electrolyte, dict):
        return None
    node: dict[str, Any] = {"@type": CONVERTER_FAMILY_TYPES.get(str(electrolyte.get("family")), "OrganicElectrolyte")}
    _converter_component_metadata(node, electrolyte)
    solvent_mixture = electrolyte.get("solvent_mixture")
    if isinstance(solvent_mixture, dict) and isinstance(solvent_mixture.get("component"), list):
        constituents = [
            _converter_named_node(item, property_types=CONVERTER_PROPERTY_TYPES)
            for item in solvent_mixture["component"]
            if isinstance(item, dict)
        ]
        constituents = [item for item in constituents if item]
        if constituents:
            solvent_node: dict[str, Any] = {"@type": "Solvent", "hasConstituent": constituents[0] if len(constituents) == 1 else constituents}
            _converter_component_metadata(solvent_node, solvent_mixture)
            node["hasSolvent"] = solvent_node
    solute_node: dict[str, Any] | None = None
    salt = electrolyte.get("salt")
    if isinstance(salt, dict):
        solute_component = _converter_named_node(salt, property_types=CONVERTER_PROPERTY_TYPES)
        solute_node = {"@type": "Solute", "hasConstituent": solute_component}
    additives = electrolyte.get("additive")
    if isinstance(additives, list):
        additive_items = [
            _converter_named_node(item, property_types=CONVERTER_PROPERTY_TYPES)
            for item in additives
            if isinstance(item, dict)
        ]
        additive_items = [item for item in additive_items if item]
        if additive_items:
            if solute_node is None:
                solute_node = {"@type": "Solute"}
            solute_node["hasAdditive"] = {
                "@type": "Additive",
                "hasConstituent": additive_items[0] if len(additive_items) == 1 else additive_items,
            }
    if solute_node is not None:
        node["hasSolute"] = solute_node
    measured = _converter_measured_properties(electrolyte.get("property"), property_types=CONVERTER_PROPERTY_TYPES)
    if measured:
        node["hasMeasuredProperty"] = measured[0] if len(measured) == 1 else measured
    return node


def _converter_separator_node(separator: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(separator, dict):
        return None
    material_type = CONVERTER_LABEL_TO_TYPE.get(str(separator.get("material") or ""), None)
    node: dict[str, Any] = {"@type": ["Separator", material_type] if material_type else "Separator"}
    if not material_type and separator.get("material"):
        node["schema:material"] = separator["material"]
    _converter_component_metadata(node, separator)
    measured = _converter_measured_properties(separator.get("property"), property_types=CONVERTER_PROPERTY_TYPES)
    if measured:
        node["hasMeasuredProperty"] = measured[0] if len(measured) == 1 else measured
    return node


def _converter_coin_hardware_nodes(coin_hardware: dict[str, Any] | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not isinstance(coin_hardware, dict):
        return None, []
    case_node = None
    case = coin_hardware.get("case")
    if isinstance(case, dict):
        type_values: list[str] = []
        if isinstance(case.get("size_code"), str) and case["size_code"]:
            type_values.append(case["size_code"])
        material_type = CONVERTER_LABEL_TO_TYPE.get(str(case.get("material") or ""), None)
        if material_type is not None:
            type_values.append(material_type)
        case_node = {"@type": type_values if len(type_values) > 1 else (type_values[0] if type_values else "schema:Thing")}
        if not material_type and case.get("material"):
            case_node["schema:material"] = case["material"]
        _converter_component_metadata(case_node, case)
        measured = _converter_measured_properties(case.get("property"), property_types=CONVERTER_PROPERTY_TYPES)
        if measured:
            case_node["hasMeasuredProperty"] = measured[0] if len(measured) == 1 else measured
        case_constituents: list[dict[str, Any]] = []
        for key, type_name, legacy_coating_key in (
            ("lid", "CellLid", "lid_coating"),
            ("can", "CellCan", "can_coating"),
        ):
            component = coin_hardware.get(key)
            if not isinstance(component, dict) and not case.get(legacy_coating_key):
                continue
            node: dict[str, Any] = {"@type": type_name}
            if isinstance(component, dict):
                material_type = CONVERTER_LABEL_TO_TYPE.get(str(component.get("material") or ""), None)
                if material_type is not None:
                    node["@type"] = [type_name, material_type]
                elif component.get("material"):
                    node["schema:material"] = component["material"]
                _converter_component_metadata(node, component)
                measured = _converter_measured_properties(component.get("property"), property_types=CONVERTER_PROPERTY_TYPES)
                if measured:
                    node["hasMeasuredProperty"] = measured[0] if len(measured) == 1 else measured
                coating = component.get("coating")
                if coating:
                    node["hasCoating"] = {"schema:material": coating}
            elif case.get(legacy_coating_key):
                node["hasCoating"] = {"schema:material": case[legacy_coating_key]}
            case_constituents.append(node)
        if case_constituents:
            case_node["hasConstituent"] = case_constituents[0] if len(case_constituents) == 1 else case_constituents
    extra_nodes: list[dict[str, Any]] = []
    for key, type_name in (("spring", "Spring"), ("spacer", "Spacer")):
        component = coin_hardware.get(key)
        if not isinstance(component, dict):
            continue
        node: dict[str, Any] = {"@type": type_name}
        material_type = CONVERTER_LABEL_TO_TYPE.get(str(component.get("material") or ""), None)
        if material_type is not None:
            node["@type"] = [type_name, material_type]
        elif component.get("material"):
            node["schema:material"] = component["material"]
        _converter_component_metadata(node, component)
        measured = _converter_measured_properties(component.get("property"), property_types=CONVERTER_PROPERTY_TYPES)
        if measured:
            node["hasMeasuredProperty"] = measured[0] if len(measured) == 1 else measured
        extra_nodes.append(node)
    return case_node, extra_nodes


def _battery_to_jsonld(battery: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "@type": BATTERY_TYPE_MAP.get(str(battery.get("type")), "battinfo:Battery"),
    }
    battery_id = battery.get("id")
    if battery_id is not None:
        out["@id"] = battery_id
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


_ELECTROLYTE_FAMILY_TYPES: dict[str, str] = {
    "organic": "OrganicElectrolyte",
    "aqueous": "AqueousElectrolyte",
    "ionic_liquid": "IonicLiquidElectrolyte",
    "polymer": "PolymerElectrolyte",
    "solid": "SolidElectrolyte",
}

# Electrode BOM role → EMMO relation predicate and role class.
# The additive slot in electrode coatings is conventionally a conductive additive (e.g. carbon black).
_ELECTRODE_ROLE_MAP: dict[str, dict[str, str]] = {
    "active_material": {"relation": "hasActiveMaterial", "role_class": "ActiveMaterial"},
    "binder":          {"relation": "hasBinder",         "role_class": "Binder"},
    "additive":        {"relation": "hasConductiveAdditive", "role_class": "ConductiveAdditive"},
}

# UnitOne IRI — used for dimensionless fraction quantities (MassFraction, VolumeFraction, Porosity).
# Fraction values stored as percentages (0–100) are converted to the [0, 1] range on output.
_UNIT_ONE_IRI = "https://w3id.org/emmo#EMMO_5ebd5e01_0ed3_49a2_a30d_cd05cbe72978"

# Recognized current-collector form factors and their EMMO class terms.
_CC_FORM_FACTOR_MAP: dict[str, str] = {
    "foil": "Foil",
    "perforated foil": "PerforatedFoil",
    "expanded mesh": "ExpandedMesh",
    "woven mesh": "WovenMesh",
    "mesh": "WovenMesh",
    "electrospun mesh": "ElectrospunMesh",
}

# Recognized current-collector substrate materials and their EMMO class terms.
_CC_MATERIAL_MAP: dict[str, str] = {
    "aluminium": "Aluminium",
    "aluminum": "Aluminium",
    "copper": "Copper",
    "nickel": "Nickel",
    "steel": "Steel",
    "stainless steel": "StainlessSteel",
    "titanium": "Titanium",
    "carbon": "Carbon",
}


def _emmo_quantity_node(
    emmo_type: str,
    quantity: dict[str, Any],
    unit_iri_override: str | None = None,
) -> dict[str, Any] | None:
    """Build a ConventionalProperty node with an explicit EMMO type (bypasses the property map)."""
    if not isinstance(quantity, dict):
        return None
    value = quantity.get("value")
    if value is None:
        return None
    node: dict[str, Any] = {
        "@type": [emmo_type, "ConventionalProperty"],
        "hasNumericalPart": {"@type": "RealData", "hasNumericalValue": value},
    }
    unit = quantity.get("unit")
    iri = unit_iri_override or _unit_iri(unit)
    if iri:
        node["hasMeasurementUnit"] = iri
    elif unit:
        node["schema:unitText"] = unit
    return node


def _fraction_quantity_node(emmo_type: str, quantity: dict[str, Any]) -> dict[str, Any] | None:
    """Build a ConventionalProperty node for a dimensionless fraction (MassFraction, VolumeFraction).

    When the stored unit is '%', the value is converted from the 0–100 percentage range to the
    [0, 1] range and hasMeasurementUnit is set to UnitOne (dimensionless).  Other units are passed
    through to the standard unit map lookup.
    """
    if not isinstance(quantity, dict):
        return None
    value = quantity.get("value")
    if value is None:
        return None
    unit = quantity.get("unit", "")
    if unit == "%":
        return {
            "@type": [emmo_type, "ConventionalProperty"],
            "hasNumericalPart": {"@type": "RealData", "hasNumericalValue": round(value / 100, 6)},
            "hasMeasurementUnit": _UNIT_ONE_IRI,
        }
    return _emmo_quantity_node(emmo_type, quantity)


def _parse_current_collector_types(name: str) -> list[str]:
    """Parse a current collector name into EMMO @type classes.

    Examples:
        'Aluminium foil'     → ['CurrentCollector', 'Aluminium', 'Foil']
        'Copper foil'        → ['CurrentCollector', 'Copper', 'Foil']
        'Aluminium mesh'     → ['CurrentCollector', 'Aluminium', 'WovenMesh']
    """
    types: list[str] = ["CurrentCollector"]
    name_lower = name.strip().lower()
    # Collect material class first (single word lookup)
    mat_class: str | None = None
    for word in name_lower.split():
        mat_class = _CC_MATERIAL_MAP.get(word)
        if mat_class:
            types.append(mat_class)
            name_lower = name_lower.replace(word, "").strip()
            break
    # Then check for multi-word form factors (longest match first)
    for form, emmo_class in sorted(_CC_FORM_FACTOR_MAP.items(), key=lambda x: -len(x[0])):
        if form in name_lower:
            types.append(emmo_class)
            break
    return types


def _typed_constituent_node(
    mat: dict[str, Any],
    role_class: str,
    _unused_fraction_type: str = "",
) -> dict[str, Any] | None:
    """Build a typed constituent node combining a material EMMO class with a functional role class.

    @type becomes [MaterialClass, RoleClass] when the material name resolves in material_map,
    or just [RoleClass] when it does not.
    """
    if not isinstance(mat, dict):
        return None
    name = mat.get("name")
    if not name:
        return None

    mat_class = _material_emmo_class(name)
    node_type: str | list[str] = [mat_class, role_class] if mat_class else role_class
    node: dict[str, Any] = {"@type": node_type, "schema:name": name}

    prop = mat.get("property", {})
    if isinstance(prop, dict):
        q: dict[str, Any] | None = None
        if (mf := prop.get("mass_fraction")) is not None:
            q = _fraction_quantity_node("MassFraction", mf)
        elif (vf := prop.get("volume_fraction")) is not None:
            q = _fraction_quantity_node("VolumeFraction", vf)
        elif (conc := prop.get("concentration")) is not None:
            q = _emmo_quantity_node("AmountConcentration", conc)
        if q:
            node["hasProperty"] = q

    if comment := mat.get("comment"):
        node["schema:description"] = comment
    return node


def _descriptor_electrode_coating_to_jsonld(coating: dict[str, Any] | None) -> dict[str, Any] | None:
    """Convert an electrode coating dict to an ElectrodeCoating node.

    Uses role-specific EMMO predicates (hasActiveMaterial, hasBinder, hasConductiveAdditive)
    and stacks material + role classes on each constituent node.
    """
    if not isinstance(coating, dict):
        return None
    node: dict[str, Any] = {"@type": "ElectrodeCoating"}
    components = coating.get("component", {})
    if isinstance(components, dict):
        for role, role_cfg in _ELECTRODE_ROLE_MAP.items():
            mats = components.get(role, [])
            if not isinstance(mats, list):
                mats = [mats] if mats else []
            role_nodes = [
                c for mat in mats
                if (c := _typed_constituent_node(mat, role_cfg["role_class"], "MassFraction")) is not None
            ]
            if role_nodes:
                node[role_cfg["relation"]] = role_nodes[0] if len(role_nodes) == 1 else role_nodes

    prop = coating.get("property", {})
    emmo_props: list[dict[str, Any]] = []
    if isinstance(prop, dict):
        loading = prop.get("loading")
        if loading:
            q = _emmo_quantity_node("ActiveMassLoading", loading)
            if q:
                emmo_props.append(q)
        cal_density = prop.get("calendered_density")
        if cal_density:
            q = _emmo_quantity_node("CalenderedDensity", cal_density)
            if q:
                emmo_props.append(q)
    if emmo_props:
        node["hasProperty"] = emmo_props[0] if len(emmo_props) == 1 else emmo_props

    comment = coating.get("comment")
    if comment:
        node["schema:description"] = comment
    return node if len(node) > 1 else None


def _descriptor_current_collector_to_jsonld(cc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Convert a current collector dict to a typed CurrentCollector node.

    The name (e.g. 'Aluminium foil') is parsed to build an @type list that stacks the
    substrate material and physical form onto CurrentCollector:
        'Aluminium foil' → ['CurrentCollector', 'Aluminium', 'Foil']
    """
    if not isinstance(cc, dict):
        return None
    name = cc.get("name", "")
    cc_types = _parse_current_collector_types(name) if name else ["CurrentCollector"]
    node: dict[str, Any] = {"@type": cc_types if len(cc_types) > 1 else cc_types[0]}
    if name:
        node["schema:name"] = name
    prop = cc.get("property", {})
    if isinstance(prop, dict):
        thickness = prop.get("thickness")
        if thickness:
            q = _emmo_quantity_node("Thickness", thickness)
            if q:
                node["hasProperty"] = q
    return node if len(node) > 1 else None


def _descriptor_electrolyte_to_jsonld(electrolyte: dict[str, Any] | None) -> dict[str, Any] | None:
    """Convert an electrolyte dict to a typed electrolyte node.

    Uses hasSolute for the dissolved salt, hasSolvent for solvent components, and
    hasAdditive for electrolyte additives.  Each component receives material + role @type stacking.
    """
    if not isinstance(electrolyte, dict):
        return None
    family = (electrolyte.get("family") or "").lower().replace("-", "_")
    elyte_type = _ELECTROLYTE_FAMILY_TYPES.get(family, "ElectrolyteSolution")
    node: dict[str, Any] = {"@type": elyte_type}

    salt = electrolyte.get("salt")
    if isinstance(salt, dict) and salt.get("name"):
        salt_node = _typed_constituent_node(salt, "Solute", "Concentration")
        if salt_node:
            node["hasSolute"] = salt_node

    solvent_mixture = electrolyte.get("solvent_mixture", {})
    solvent_nodes = [
        c for s in (solvent_mixture.get("component", []) if isinstance(solvent_mixture, dict) else [])
        if (c := _typed_constituent_node(s, "Solvent", "VolumeFraction")) is not None
    ]
    if solvent_nodes:
        node["hasSolvent"] = solvent_nodes[0] if len(solvent_nodes) == 1 else solvent_nodes

    additive_nodes = [
        c for a in (electrolyte.get("additive") or [])
        if (c := _typed_constituent_node(a, "ElectrolyteAdditive", "MassFraction")) is not None
    ]
    if additive_nodes:
        node["hasAdditive"] = additive_nodes[0] if len(additive_nodes) == 1 else additive_nodes

    comment = electrolyte.get("comment")
    if comment:
        node["schema:description"] = comment
    return node if len(node) > 1 else None


def _descriptor_separator_to_jsonld(separator: dict[str, Any] | None) -> dict[str, Any] | None:
    """Convert a separator dict to a typed Separator node with thickness and porosity properties."""
    if not isinstance(separator, dict):
        return None
    mat_name = separator.get("material")
    mat_class = _material_emmo_class(mat_name) if mat_name else None
    sep_type: str | list[str] = [mat_class, "Separator"] if mat_class else "Separator"
    node: dict[str, Any] = {"@type": sep_type}
    if mat_name:
        node["schema:name"] = mat_name
    prop = separator.get("property", {})
    sep_props: list[dict[str, Any]] = []
    if isinstance(prop, dict):
        thickness = prop.get("thickness")
        if thickness:
            q = _emmo_quantity_node("Thickness", thickness)
            if q:
                sep_props.append(q)
        porosity = prop.get("porosity")
        if porosity:
            q = _fraction_quantity_node("Porosity", porosity)
            if q:
                sep_props.append(q)
    if sep_props:
        node["hasProperty"] = sep_props
    comment = separator.get("comment")
    if comment:
        node["schema:description"] = comment
    return node if len(node) > 1 else None


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

    battery_types_deduped = list(dict.fromkeys(battery_type_list))
    physical_type: str | list[str] = battery_types_deduped[0] if len(battery_types_deduped) == 1 else battery_types_deduped

    battery: dict[str, Any] = {
        "@type": ["BatteryCellSpecification", "schema:CreativeWork"],
        "isDescriptionFor": {"@type": physical_type},
    }
    product_type = specification.get("product_type")
    if isinstance(product_type, str) and product_type:
        battery["schema:additionalType"] = product_type
    spec_id = specification.get("id")
    if spec_id is not None:
        battery["@id"] = spec_id

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

    for electrode_mapping, data_key in (
        (positive_electrode, "positive_electrode"),
        (negative_electrode, "negative_electrode"),
    ):
        if not electrode_mapping:
            continue
        relation = electrode_mapping.get("relation")
        node_type = electrode_mapping.get("node_type")
        if not isinstance(relation, str) or not relation:
            continue
        electrode_node: dict[str, Any] = {}
        if isinstance(node_type, str) and node_type:
            electrode_node["@type"] = node_type
        electrode_data = specification.get(data_key)
        if isinstance(electrode_data, dict):
            coating = _descriptor_electrode_coating_to_jsonld(electrode_data.get("coating"))
            if coating:
                electrode_node["hasCoating"] = coating
            cc = _descriptor_current_collector_to_jsonld(electrode_data.get("current_collector"))
            if cc:
                electrode_node["hasCurrentCollector"] = cc
        if electrode_node:
            battery[relation] = electrode_node

    electrolyte_node = _descriptor_electrolyte_to_jsonld(specification.get("electrolyte"))
    if electrolyte_node:
        battery["hasElectrolyte"] = electrolyte_node

    separator_node = _descriptor_separator_to_jsonld(specification.get("separator"))
    if separator_node:
        battery["hasSeparator"] = separator_node

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

    if specification.get("format") == "coin":
        case_node, extra_hardware_nodes = _descriptor_coin_hardware_to_jsonld(specification.get("coin_hardware"))
        if case_node is not None:
            battery["hasCase"] = case_node
        if extra_hardware_nodes:
            battery["hasConstituent"] = extra_hardware_nodes[0] if len(extra_hardware_nodes) == 1 else extra_hardware_nodes

    comment = _comment_value(specification.get("comment"))
    if comment is not None:
        battery[specification_comment_target] = comment

    return battery


def _descriptor_instances_to_jsonld(instances: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(instances, list):
        return out

    instance_types: list[str] = ["BatteryCell", "schema:IndividualProduct"]
    instance_name_target = _profile_binding_target("instances.name", "schema:name")
    instance_serial_target = _profile_binding_target("instances.serial_number", "schema:serialNumber")
    instance_comment_target = _profile_binding_target("instances.comment", "schema:description")

    for instance in instances:
        if not isinstance(instance, dict):
            continue
        node: dict[str, Any] = {"@type": instance_types}
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
        "@type": "battinfo:BatteryMetadataRecord",
        "hasBattery": _battery_to_jsonld(battery),
    }
    record_id = record.get("id")
    if record_id is not None:
        doc["@id"] = record_id
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
    instance_relation_target = _profile_binding_target("instances.relation_to_specification", "hasDescription")
    _SCHEMA_IS_VARIANT_OF = "schema:isVariantOf"

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
            instance[_SCHEMA_IS_VARIANT_OF] = {"@id": battery.get("@id")}
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


def _to_converter_compatible_jsonld(data: dict[str, Any]) -> dict[str, Any]:
    specification = data.get("specification")
    if not isinstance(specification, dict):
        raise ValueError("converter-compatible export currently supports BattINFO detailed cell descriptor records only.")

    root_type = CONVERTER_FORMAT_TYPES.get(str(specification.get("format")), "CoinCell")
    doc: dict[str, Any] = {
        "@context": [
            BATTERY_CONTEXT_URL,
            {
                "schema": "https://schema.org",
                "emmo": "https://w3id.org/emmo#",
                "unit": "https://qudt.org/vocab/unit/",
                "rdfs": "https://www.w3.org/TR/rdf-schema/#ch_comment",
            },
        ],
        "@type": root_type,
    }
    if data.get("schema_version"):
        doc["schema:version"] = data["schema_version"]
    instances = data.get("instances")
    if isinstance(instances, list) and instances:
        first = instances[0] if isinstance(instances[0], dict) else {}
        product_id = first.get("serial_number") or first.get("name")
        if product_id:
            doc["schema:productID"] = product_id
    elif specification.get("model"):
        doc["schema:productID"] = specification["model"]
    manufacturer_node = _agent_text_node(specification.get("manufacturer"))
    if manufacturer_node is not None:
        doc["schema:manufacturer"] = manufacturer_node

    root_comments: list[str] = []
    if isinstance(data.get("comment"), list):
        root_comments.extend([item for item in data["comment"] if isinstance(item, str) and item])
    if isinstance(specification.get("comment"), list):
        root_comments.extend([item for item in specification["comment"] if isinstance(item, str) and item])
    construction = specification.get("construction")
    if isinstance(construction, dict):
        sequence = construction.get("assembly_sequence")
        if isinstance(sequence, list):
            ordered = [str(item).strip() for item in sequence if str(item).strip()]
            if ordered:
                root_comments.append(f"Cell assembly sequence: {', '.join(ordered)}")
        elif construction.get("comment"):
            root_comments.append(f"Cell assembly sequence: {construction['comment']}")
    if root_comments:
        deduped = list(dict.fromkeys(root_comments))
        doc["rdfs:comment"] = deduped[0] if len(deduped) == 1 else deduped

    positive = _converter_electrode_node(specification.get("positive_electrode"))
    if positive is not None:
        doc["hasPositiveElectrode"] = positive
    negative = _converter_electrode_node(specification.get("negative_electrode"))
    if negative is not None:
        doc["hasNegativeElectrode"] = negative
    electrolyte = _converter_electrolyte_node(specification.get("electrolyte"))
    if electrolyte is not None:
        doc["hasElectrolyte"] = electrolyte
    separator = _converter_separator_node(specification.get("separator"))
    if separator is not None:
        doc["hasSeparator"] = separator
    case_node, extra_nodes = _converter_coin_hardware_nodes(specification.get("coin_hardware"))
    if case_node is not None:
        doc["hasCase"] = case_node
    if extra_nodes:
        doc["hasConstituent"] = extra_nodes[0] if len(extra_nodes) == 1 else extra_nodes
    return doc


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
    elif target == "converter-compatible":
        return _to_converter_compatible_jsonld(data)
    else:
        raise ValueError(
            f"Unknown mapping target '{target}'. Expected 'domain-battery', 'batterypass', or 'converter-compatible'."
        )
    validation = validate_jsonld(doc)
    if not validation.ok:
        raise ValueError(f"json-ld validation failed: {'; '.join(validation.errors)}")
    return doc

