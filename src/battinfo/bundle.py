from __future__ import annotations

import copy
import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Mapping, Self

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

PathLike = str | Path

BUNDLE_MANIFEST_FILENAME = "bundle.json"
CELL_SPECIFICATION_FILENAME = "cell-specification.json"
CELL_TYPE_FILENAME = "cell-type.json"
CELL_INSTANCE_FILENAME = "cell-instance.json"
TEST_FILENAME = "test.json"
DATASET_FILENAME = "dataset.json"
OWL_CLASS_IRI = "http://www.w3.org/2002/07/owl#Class"
RDFS_SUBCLASS_OF_IRI = "http://www.w3.org/2000/01/rdf-schema#subClassOf"


class BatteryTestType(StrEnum):
    CYCLE_LIFE = "cycle_life"
    CAPACITY_CHECK = "capacity_check"
    RATE_CAPABILITY = "rate_capability"
    HPPC = "hppc"
    ICI = "ici"
    GITT = "gitt"
    DCIR = "dcir"
    EIS = "eis"
    IMPEDANCE = "impedance"
    CALENDAR_AGEING = "calendar_ageing"
    FORMATION = "formation"
    OTHER = "other"


def _as_path(path: PathLike) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _short_id(entity_id: str) -> str:
    tail = entity_id.rstrip("/").split("/")[-1].replace("-", "")
    return tail[:6]


def _identifier(prefix: str, entity_id: str) -> str:
    tail = entity_id.rstrip("/").split("/")[-1]
    return f"{prefix}:{tail}"


def _id_tail(entity_id: str | None) -> str | None:
    if not entity_id:
        return None
    return entity_id.rstrip("/").split("/")[-1]


def _node_has_type(node: Mapping[str, Any], expected: str) -> bool:
    value = node.get("@type")
    if isinstance(value, str):
        return value == expected
    if isinstance(value, list):
        return expected in value
    return False


def _type_values(node: Mapping[str, Any]) -> list[str]:
    value = node.get("@type")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _graph_nodes(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    graph = payload.get("@graph")
    if isinstance(graph, list):
        return [node for node in graph if isinstance(node, dict)]
    if isinstance(payload, dict):
        return [dict(payload)]
    return []


def _ref_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        ref_id = value.get("@id")
        return str(ref_id) if isinstance(ref_id, str) else None
    if isinstance(value, list):
        for item in value:
            ref_id = _ref_id(item)
            if ref_id is not None:
                return ref_id
    return None


def _text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, (str, int, float))]
    return []


def _instrument_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        name = value.get("schema:name")
        return str(name) if isinstance(name, str) else None
    return None


def _protocol_from_description(value: Any) -> tuple[str | None, str | None]:
    text_items = _text_list(value)
    protocol_name = None
    description_items: list[str] = []
    for item in text_items:
        if item.startswith("Protocol: "):
            protocol_name = item.removeprefix("Protocol: ").strip() or None
        else:
            description_items.append(item)
    if not description_items:
        description = None
    elif len(description_items) == 1:
        description = description_items[0]
    else:
        description = "\n".join(description_items)
    return protocol_name, description


def _ref_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        ref_id = value.get("@id")
        return [str(ref_id)] if isinstance(ref_id, str) else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_ref_ids(item))
        return out
    return []


def _subclass_ref_ids(node: Mapping[str, Any]) -> list[str]:
    return _ref_ids(node.get(RDFS_SUBCLASS_OF_IRI)) + _ref_ids(node.get("rdfs:subClassOf"))


def _unit_from_iri(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if value.endswith("MilliMetre"):
        return "mm"
    if value.endswith("Volt"):
        return "V"
    if value.endswith("AmpereHour"):
        return "Ah"
    if value.endswith("Gram"):
        return "g"
    return value


def _property_key_from_type(value: Any) -> str | None:
    if isinstance(value, str):
        types = [value]
    elif isinstance(value, list):
        types = [item for item in value if isinstance(item, str)]
    else:
        types = []
    for type_name in types:
        if type_name == "Diameter":
            return "diameter"
        if type_name == "Height":
            return "height"
        if type_name == "NominalVoltage":
            return "nominal_voltage"
        if type_name == "NominalCapacity":
            return "nominal_capacity"
        if type_name == "Mass":
            return "mass"
    return None


def _extract_property_item(node: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    key = _property_key_from_type(node.get("@type"))
    if key is None:
        return None
    numerical = node.get("hasNumericalPart")
    if not isinstance(numerical, Mapping):
        return None
    value = numerical.get("hasNumericalValue")
    unit = _unit_from_iri(node.get("hasMeasurementUnit"))
    if value is None or unit is None:
        return None
    return key, {"value": value, "unit": unit}


_DOI_URL_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/(10\.\S+)$", re.IGNORECASE)
_DOI_LITERAL_RE = re.compile(r"^(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)$")


def _citation_doi_from_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = _DOI_URL_RE.match(value.strip())
    if match is None:
        return None
    return match.group(1)


def _citation_url_value(citation: Any = None, citation_doi: Any = None) -> str | None:
    if isinstance(citation, str):
        normalized = citation.strip()
        if not normalized:
            return None
        extracted = _citation_doi_from_url(normalized)
        if extracted is not None:
            return f"https://doi.org/{extracted}"
        if _DOI_LITERAL_RE.fullmatch(normalized):
            return f"https://doi.org/{normalized}"
        return normalized
    if isinstance(citation_doi, str):
        normalized = citation_doi.strip()
        if not normalized:
            return None
        extracted = _citation_doi_from_url(normalized)
        if extracted is not None:
            return f"https://doi.org/{extracted}"
        return f"https://doi.org/{normalized}"
    return None


def _citation_doi_value(citation: Any = None, citation_doi: Any = None) -> str | None:
    citation_url = _citation_url_value(citation, citation_doi)
    return _citation_doi_from_url(citation_url)


class ProvenanceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str | None = None
    name: str | None = None
    file: str | None = None
    url: str | None = None
    citation: str | None = Field(default=None, validation_alias=AliasChoices("citation", "citation_doi"))
    retrieved_at: int | str | None = None
    workflow_version: str | None = None
    file_hash: str | None = None
    curated_by: str | None = None
    comment: str | None = None


class ProtocolInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    url: str | None = None


class ChecksumInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithm: str | None = None
    value: str | None = None


class PropertySet(BaseModel):
    model_config = ConfigDict(extra="allow")

    def to_mapping(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class _AttributeMappingProxy:
    """Small attribute view over a mutable dict for notebook-style authoring."""

    def __init__(self, target: dict[str, Any]) -> None:
        object.__setattr__(self, "_target", target)

    def __getattr__(self, name: str) -> Any:
        target = object.__getattribute__(self, "_target")
        if name in target:
            return target[name]
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        target = object.__getattribute__(self, "_target")
        target[name] = value

    def __delattr__(self, name: str) -> None:
        target = object.__getattribute__(self, "_target")
        if name not in target:
            raise AttributeError(name)
        del target[name]

    def to_mapping(self) -> dict[str, Any]:
        target = object.__getattribute__(self, "_target")
        return dict(target)


def _mapping_property(name: str) -> property:
    def getter(self: Any) -> Any:
        return self.nominal_properties.get(name)

    def setter(self: Any, value: Any) -> None:
        if value is None:
            self.nominal_properties.pop(name, None)
        else:
            self.nominal_properties[name] = value

    return property(getter, setter)


CELL_TYPE_AUTHORING_PROPERTY_FIELDS: tuple[str, ...] = (
    "nominal_capacity",
    "min_capacity",
    "rated_capacity",
    "nominal_voltage",
    "charging_voltage",
    "discharging_cutoff_voltage",
    "internal_resistance",
    "impedance",
    "mass",
    "diameter",
    "height",
    "width",
    "length",
    "thickness",
    "pulse_charging_current",
    "continuous_charging_current",
    "pulse_discharging_current",
    "continuous_discharging_current",
    "charging_temperature_min",
    "charging_temperature_max",
    "discharging_temperature_min",
    "discharging_temperature_max",
    "storage_temperature_min",
    "storage_temperature_max",
    "cycle_life",
)


class CellConstruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assembly_type: str | None = None
    layering: str | None = None
    layer_count: int | None = None
    comment: str | None = None

    def to_mapping(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class BillOfMaterials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_material: list["MaterialComponent"] = Field(default_factory=list)
    binder: list["MaterialComponent"] = Field(default_factory=list)
    additive: list["MaterialComponent"] = Field(default_factory=list)

    def to_mapping(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


def _mapping_from_object(value: Any) -> Any:
    if isinstance(value, (PropertySet, CellConstruction, BillOfMaterials)):
        return value.to_mapping()
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json", exclude_none=True)
        return payload if isinstance(payload, Mapping) else value
    if isinstance(value, Mapping):
        return dict(value)
    return value


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json", exclude_none=True)
        return [copy.deepcopy(dict(payload))] if isinstance(payload, Mapping) else []
    if isinstance(value, Mapping):
        return [copy.deepcopy(dict(value))]
    if isinstance(value, list):
        out: list[dict[str, Any]] = []
        for item in value:
            if isinstance(item, BaseModel):
                payload = item.model_dump(mode="json", exclude_none=True)
                if isinstance(payload, Mapping):
                    out.append(copy.deepcopy(dict(payload)))
            elif isinstance(item, Mapping):
                out.append(copy.deepcopy(dict(item)))
        return out
    return []


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, (str, int, float))]
    return []


def _copy_identifier(value: Any) -> Any:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    if isinstance(value, list):
        out: list[Any] = []
        for item in value:
            if isinstance(item, Mapping):
                out.append(copy.deepcopy(dict(item)))
            elif isinstance(item, (str, int, float)):
                out.append(str(item))
        return out
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def _canonical_agent(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    node_type = value.get("type") or value.get("@type")
    if isinstance(node_type, list):
        node_type = next((item for item in node_type if isinstance(item, str)), None)
    if isinstance(node_type, str) and ":" in node_type:
        node_type = node_type.split(":", 1)[1]
    name = value.get("name") or value.get("schema:name")
    if not isinstance(name, str) or not name.strip():
        return None
    out: dict[str, Any] = {"name": name}
    if isinstance(node_type, str) and node_type in {"Person", "Organization"}:
        out["type"] = node_type
    elif any(key in value for key in ("email", "schema:email", "affiliation", "schema:affiliation")):
        out["type"] = "Person"
    else:
        out["type"] = "Organization"
    email = value.get("email") or value.get("schema:email")
    if isinstance(email, str):
        out["email"] = email
    given_name = value.get("given_name") or value.get("schema:givenName")
    if isinstance(given_name, str):
        out["given_name"] = given_name
    family_name = value.get("family_name") or value.get("schema:familyName")
    if isinstance(family_name, str):
        out["family_name"] = family_name
    url = value.get("url") or value.get("schema:url") or value.get("@id")
    if isinstance(url, str) and "://" in url:
        out["url"] = url
    same_as = value.get("sameAs") or value.get("schema:sameAs")
    if isinstance(same_as, str) and "://" in same_as:
        out["sameAs"] = same_as
    affiliation = value.get("affiliation") or value.get("schema:affiliation")
    if isinstance(affiliation, Mapping):
        nested = _canonical_agent(affiliation)
        if nested is not None:
            out["affiliation"] = nested
    return out


def _canonical_data_catalog(value: Any) -> dict[str, Any] | str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return None
    name = value.get("name") or value.get("schema:name")
    if not isinstance(name, str) or not name.strip():
        return None
    out: dict[str, Any] = {"type": "DataCatalog", "name": name}
    node_id = value.get("id") or value.get("@id")
    if isinstance(node_id, str):
        out["id"] = node_id
    url = value.get("url") or value.get("schema:url")
    if isinstance(url, str):
        out["url"] = url
    same_as = value.get("sameAs") or value.get("schema:sameAs")
    if isinstance(same_as, str):
        out["sameAs"] = same_as
    description = value.get("description") or value.get("schema:description")
    if isinstance(description, str):
        out["description"] = description
    return out


def _canonical_citation(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        return {"url": value}
    if not isinstance(value, Mapping):
        return None
    out: dict[str, Any] = {}
    kind = value.get("kind") or value.get("schema:additionalType")
    if isinstance(kind, str):
        out["kind"] = kind
    name = value.get("name") or value.get("schema:name")
    if isinstance(name, str):
        out["name"] = name
    url = value.get("url") or value.get("@id") or value.get("schema:url")
    if isinstance(url, str):
        out["url"] = url
    doi = value.get("doi") or value.get("bibo:doi")
    if isinstance(doi, str):
        out["doi"] = doi
    citation_key = value.get("citation_key")
    if isinstance(citation_key, str):
        out["citation_key"] = citation_key
    return out or None


def _canonical_variable_measured(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    name = value.get("name") or value.get("schema:name")
    if not isinstance(name, str) or not name.strip():
        return None
    out: dict[str, Any] = {"name": name}
    description = value.get("description") or value.get("schema:description")
    if isinstance(description, str):
        out["description"] = description
    unit_text = value.get("unit_text") or value.get("schema:unitText")
    if isinstance(unit_text, str):
        out["unit_text"] = unit_text
    same_as = value.get("sameAs") or value.get("schema:sameAs")
    if isinstance(same_as, str):
        out["sameAs"] = same_as
    property_id = value.get("property_id") or value.get("schema:propertyID")
    if isinstance(property_id, str) and "sameAs" not in out:
        out["sameAs"] = property_id
    return out


def _canonical_distribution(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    out: dict[str, Any] = {}
    dist_type = value.get("type") or value.get("@type")
    if isinstance(dist_type, str) and ":" in dist_type:
        dist_type = dist_type.split(":", 1)[1]
    if isinstance(dist_type, str):
        out["type"] = dist_type
    for target_key, source_keys in (
        ("name", ("name", "schema:name")),
        ("description", ("description", "schema:description")),
        ("contentUrl", ("contentUrl", "schema:contentUrl")),
        ("encodingFormat", ("encodingFormat", "schema:encodingFormat")),
        ("contentSize", ("contentSize", "schema:contentSize")),
        ("accessLevel", ("accessLevel", "schema:accessLevel")),
    ):
        for source_key in source_keys:
            candidate = value.get(source_key)
            if isinstance(candidate, str):
                out[target_key] = candidate
                break
    checksum = value.get("checksum") or value.get("schema:checksum")
    if isinstance(checksum, Mapping):
        algorithm = checksum.get("algorithm")
        checksum_value = checksum.get("value")
        if isinstance(algorithm, str) and isinstance(checksum_value, str):
            out["checksum"] = {"algorithm": algorithm, "value": checksum_value}
    elif isinstance(value.get("schema:sha256"), str):
        out["checksum"] = {"algorithm": "sha256", "value": value["schema:sha256"]}
    return out if ("contentUrl" in out or "encodingFormat" in out or "checksum" in out) else None


def _canonical_table_column(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    name = value.get("name") or value.get("csvw:name")
    if not isinstance(name, str) or not name.strip():
        return None
    out: dict[str, Any] = {"name": name}
    titles = value.get("titles") or value.get("csvw:titles")
    if isinstance(titles, str) and titles.strip():
        out["titles"] = [titles.strip()]
    elif isinstance(titles, list):
        title_values = [str(item).strip() for item in titles if isinstance(item, str) and str(item).strip()]
        if title_values:
            out["titles"] = title_values
    description = value.get("description") or value.get("schema:description")
    if isinstance(description, str):
        out["description"] = description
    datatype = value.get("datatype") or value.get("csvw:datatype")
    if isinstance(datatype, str):
        out["datatype"] = datatype
    unit_text = value.get("unit_text") or value.get("schema:unitText")
    if isinstance(unit_text, str):
        out["unit_text"] = unit_text
    same_as = value.get("sameAs") or value.get("schema:sameAs") or value.get("property_id") or value.get("schema:propertyID")
    if isinstance(same_as, str):
        out["sameAs"] = same_as
    required = value.get("required") or value.get("csvw:required")
    if isinstance(required, bool):
        out["required"] = required
    return out


def _canonical_table_schema(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    columns = value.get("columns") or value.get("column") or value.get("csvw:column")
    if not isinstance(columns, list):
        return None
    out_columns = [column for item in columns if (column := _canonical_table_column(item)) is not None]
    if not out_columns:
        return None
    out: dict[str, Any] = {"columns": out_columns}
    node_id = value.get("id") or value.get("@id")
    if isinstance(node_id, str):
        out["id"] = node_id
    name = value.get("name") or value.get("schema:name")
    if isinstance(name, str):
        out["name"] = name
    description = value.get("description") or value.get("schema:description")
    if isinstance(description, str):
        out["description"] = description
    primary_key = value.get("primaryKey") or value.get("csvw:primaryKey")
    if isinstance(primary_key, str):
        out["primaryKey"] = primary_key
    elif isinstance(primary_key, list):
        values = [str(item) for item in primary_key if isinstance(item, str)]
        if values:
            out["primaryKey"] = values
    return out


def _canonical_csvw_table(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    node_type = value.get("type") or value.get("@type")
    if isinstance(node_type, str) and ":" in node_type:
        node_type = node_type.split(":", 1)[1]
    if node_type != "Table":
        return None
    url = value.get("url") or value.get("csvw:url")
    if not isinstance(url, str) or not url.strip():
        return None
    table_schema = value.get("tableSchema") or value.get("csvw:tableSchema")
    if isinstance(table_schema, Mapping):
        table_schema = _canonical_table_schema(table_schema)
    elif isinstance(table_schema, str) and table_schema.strip():
        table_schema = table_schema
    else:
        table_schema = None
    if table_schema is None:
        return None
    out: dict[str, Any] = {
        "type": "Table",
        "url": url,
        "tableSchema": copy.deepcopy(table_schema),
    }
    node_id = value.get("id") or value.get("@id")
    if isinstance(node_id, str):
        out["id"] = node_id
    name = value.get("name") or value.get("schema:name")
    if isinstance(name, str):
        out["name"] = name
    description = value.get("description") or value.get("schema:description")
    if isinstance(description, str):
        out["description"] = description
    return out


def _canonical_main_entity(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    table = _canonical_csvw_table(value)
    if table is not None:
        return table
    node_type = value.get("type") or value.get("@type")
    if isinstance(node_type, str) and ":" in node_type:
        node_type = node_type.split(":", 1)[1]
    if node_type != "TableGroup":
        return None
    table_items = value.get("table") or value.get("csvw:table")
    tables = [table for item in _mapping_list(table_items) if (table := _canonical_csvw_table(item)) is not None]
    if not tables:
        return None
    out: dict[str, Any] = {
        "type": "TableGroup",
        "table": tables,
    }
    node_id = value.get("id") or value.get("@id")
    if isinstance(node_id, str):
        out["id"] = node_id
    url = value.get("url") or value.get("csvw:url")
    if isinstance(url, str):
        out["url"] = url
    name = value.get("name") or value.get("schema:name")
    if isinstance(name, str):
        out["name"] = name
    description = value.get("description") or value.get("schema:description")
    if isinstance(description, str):
        out["description"] = description
    return out


class MaterialComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class Coating(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: dict[str, list[MaterialComponent]] = Field(default_factory=dict)
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("component", mode="before")
    @classmethod
    def _coerce_component_groups(cls, value: Any) -> Any:
        value = _mapping_from_object(value)
        if not isinstance(value, Mapping):
            return value
        out: dict[str, list[dict[str, Any] | MaterialComponent]] = {}
        for key, items in value.items():
            if isinstance(items, list):
                out[str(key)] = list(items)
        return out

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class CurrentCollector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class Electrode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coating: Coating | None = None
    current_collector: CurrentCollector | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class SolventMixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: list[MaterialComponent] = Field(default_factory=list)
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class Salt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    cation: str | None = None
    anion: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class Separator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class Electrolyte(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: str | None = None
    solvent_mixture: SolventMixture | None = None
    salt: Salt | None = None
    additive: list[MaterialComponent] = Field(default_factory=list)
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class BundleJsonModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    kind: str

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        return cls.model_validate(dict(payload))

    @classmethod
    def from_path(cls, path: PathLike) -> Self:
        return cls.from_json(_read_json(_as_path(path)))

    def to_path(self, path: PathLike) -> Path:
        out_path = _as_path(path)
        _write_json(out_path, self.to_json())
        return out_path


class CellSpecification(BundleJsonModel):
    default_filename: ClassVar[str] = CELL_SPECIFICATION_FILENAME

    kind: str = "CellSpecification"
    id: str
    manufacturer: str
    model: str
    format: str
    chemistry: str
    positive_electrode_basis: str | None = None
    negative_electrode_basis: str | None = None
    size_code: str | None = None
    construction: dict[str, Any] = Field(default_factory=dict)
    properties: dict[str, Any] = Field(default_factory=dict)
    positive_electrode: Electrode | None = None
    negative_electrode: Electrode | None = None
    electrolyte: Electrolyte | None = None
    separator: Separator | None = None
    specification_comment: list[str] = Field(default_factory=list)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)

    @field_validator("construction", "properties", mode="before")
    @classmethod
    def _coerce_mapping_fields(cls, value: Any) -> Any:
        return _mapping_from_object(value)

    @field_validator("positive_electrode", "negative_electrode", mode="before")
    @classmethod
    def _coerce_electrode(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return dict(value)
        return value

    @field_validator("electrolyte", mode="before")
    @classmethod
    def _coerce_electrolyte(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return dict(value)
        return value

    @field_validator("separator", mode="before")
    @classmethod
    def _coerce_separator(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return dict(value)
        return value

    @classmethod
    def from_path(cls, path: PathLike) -> Self:
        payload = _read_json(_as_path(path))
        if isinstance(payload.get("specification"), Mapping):
            return cls.from_library_record(payload)
        return cls.from_json(payload)

    @classmethod
    def from_library_record(cls, record: Mapping[str, Any]) -> Self:
        specification = record.get("specification", {})
        provenance = record.get("provenance", {})
        if not isinstance(specification, Mapping):
            raise ValueError("cell specification record must contain a 'specification' object.")
        if not isinstance(provenance, Mapping):
            provenance = {}
        specification_comment = specification.get("comment")
        if not isinstance(specification_comment, list):
            specification_comment = []
        comment = record.get("comment")
        if not isinstance(comment, list):
            comment = []
        return cls(
            schema_version=str(record.get("schema_version", "1.0.0")),
            id=str(specification["id"]),
            manufacturer=str(specification["manufacturer"]),
            model=str(specification["model"]),
            format=str(specification["format"]),
            chemistry=str(specification["chemistry"]),
            positive_electrode_basis=specification.get("positive_electrode_basis"),
            negative_electrode_basis=specification.get("negative_electrode_basis"),
            size_code=specification.get("size_code"),
            construction=copy.deepcopy(specification.get("construction", {}))
            if isinstance(specification.get("construction"), Mapping)
            else {},
            properties=dict(specification.get("property", {})) if isinstance(specification.get("property"), Mapping) else {},
            positive_electrode=copy.deepcopy(specification.get("positive_electrode")),
            negative_electrode=copy.deepcopy(specification.get("negative_electrode")),
            electrolyte=copy.deepcopy(specification.get("electrolyte")),
            separator=copy.deepcopy(specification.get("separator")),
            specification_comment=[str(item) for item in specification_comment],
            source=ProvenanceInfo(
                type=provenance.get("source_type"),
                name=provenance.get("source_name"),
                file=provenance.get("source_file"),
                url=provenance.get("source_url"),
                citation=_citation_url_value(provenance.get("citation"), provenance.get("citation_doi")),
                retrieved_at=provenance.get("retrieved_at"),
                workflow_version=provenance.get("workflow_version"),
                comment=provenance.get("comment"),
            ),
            comment=[str(item) for item in comment],
        )

    def to_library_record(self) -> dict[str, Any]:
        specification: dict[str, Any] = {
            "id": self.id,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "format": self.format,
            "chemistry": self.chemistry,
        }
        if self.positive_electrode_basis is not None:
            specification["positive_electrode_basis"] = self.positive_electrode_basis
        if self.negative_electrode_basis is not None:
            specification["negative_electrode_basis"] = self.negative_electrode_basis
        if self.size_code is not None:
            specification["size_code"] = self.size_code
        if self.construction:
            specification["construction"] = copy.deepcopy(self.construction)
        if self.properties:
            specification["property"] = self.properties
        if self.positive_electrode is not None:
            specification["positive_electrode"] = self.positive_electrode.model_dump(mode="json", exclude_none=True)
        if self.negative_electrode is not None:
            specification["negative_electrode"] = self.negative_electrode.model_dump(mode="json", exclude_none=True)
        if self.electrolyte is not None:
            specification["electrolyte"] = self.electrolyte.model_dump(mode="json", exclude_none=True)
        if self.separator is not None:
            specification["separator"] = self.separator.model_dump(mode="json", exclude_none=True)
        if self.specification_comment:
            specification["comment"] = list(self.specification_comment)

        provenance: dict[str, Any] = {}
        if self.source.type is not None:
            provenance["source_type"] = self.source.type
        if self.source.name is not None:
            provenance["source_name"] = self.source.name
        if self.source.file is not None:
            provenance["source_file"] = self.source.file
        if self.source.url is not None:
            provenance["source_url"] = self.source.url
        citation = _citation_url_value(self.source.citation)
        if citation is not None:
            provenance["citation"] = citation
        if self.source.retrieved_at is not None:
            provenance["retrieved_at"] = self.source.retrieved_at
        if self.source.workflow_version is not None:
            provenance["workflow_version"] = self.source.workflow_version
        if self.source.comment is not None:
            provenance["comment"] = self.source.comment

        out = {
            "schema_version": self.schema_version,
            "specification": specification,
            "provenance": provenance,
        }
        if self.comment:
            out["comment"] = list(self.comment)
        return out


class CellType(BundleJsonModel):
    default_filename: ClassVar[str] = CELL_TYPE_FILENAME

    kind: str = "CellType"
    id: str | None = None
    name: str | None = None
    manufacturer: str = ""
    model: str = ""
    format: str = "unknown"
    chemistry: str = "unknown"
    positive_electrode_basis: str | None = None
    negative_electrode_basis: str | None = None
    size_code: str | None = None
    datasheet_revision: str | None = None
    cell_specification_id: str | None = None
    nominal_properties: dict[str, Any] = Field(default_factory=dict)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)

    def __init__(self, **data: Any) -> None:
        explicit_properties = data.get("nominal_properties")
        if explicit_properties is None:
            explicit_properties = {}
        elif isinstance(explicit_properties, Mapping):
            explicit_properties = dict(explicit_properties)
        else:
            explicit_properties = dict(explicit_properties)

        for field_name in CELL_TYPE_AUTHORING_PROPERTY_FIELDS:
            if field_name in data:
                value = data.pop(field_name)
                if value is not None:
                    explicit_properties[field_name] = value

        data["nominal_properties"] = explicit_properties
        super().__init__(**data)

    @model_validator(mode="after")
    def _populate_name(self) -> Self:
        if self.name is None:
            text = f"{self.manufacturer} {self.model}".strip()
            self.name = text or None
        return self

    @property
    def specs(self) -> _AttributeMappingProxy:
        return _AttributeMappingProxy(self.nominal_properties)

    nominal_capacity = _mapping_property("nominal_capacity")
    min_capacity = _mapping_property("min_capacity")
    rated_capacity = _mapping_property("rated_capacity")
    nominal_voltage = _mapping_property("nominal_voltage")
    charging_voltage = _mapping_property("charging_voltage")
    discharging_cutoff_voltage = _mapping_property("discharging_cutoff_voltage")
    internal_resistance = _mapping_property("internal_resistance")
    impedance = _mapping_property("impedance")
    mass = _mapping_property("mass")
    diameter = _mapping_property("diameter")
    height = _mapping_property("height")
    width = _mapping_property("width")
    length = _mapping_property("length")
    thickness = _mapping_property("thickness")
    pulse_charging_current = _mapping_property("pulse_charging_current")
    continuous_charging_current = _mapping_property("continuous_charging_current")
    pulse_discharging_current = _mapping_property("pulse_discharging_current")
    continuous_discharging_current = _mapping_property("continuous_discharging_current")
    charging_temperature_min = _mapping_property("charging_temperature_min")
    charging_temperature_max = _mapping_property("charging_temperature_max")
    discharging_temperature_min = _mapping_property("discharging_temperature_min")
    discharging_temperature_max = _mapping_property("discharging_temperature_max")
    storage_temperature_min = _mapping_property("storage_temperature_min")
    storage_temperature_max = _mapping_property("storage_temperature_max")
    cycle_life = _mapping_property("cycle_life")

    @classmethod
    def from_record(cls, record: Mapping[str, Any], *, cell_specification_id: str | None = None) -> Self:
        product = record.get("product")
        if not isinstance(product, Mapping):
            raise ValueError("cell type record must contain a 'product' object.")
        provenance = record.get("provenance", {})
        if not isinstance(provenance, Mapping):
            provenance = {}
        manufacturer = product.get("manufacturer")
        manufacturer_name = manufacturer.get("name") if isinstance(manufacturer, Mapping) else manufacturer
        notes = record.get("notes")
        if not isinstance(notes, list):
            notes = []
        return cls(
            schema_version=str(record.get("schema_version", "1.0.0")),
            id=str(product["id"]),
            name=str(product.get("name") or f"{manufacturer_name} {product.get('model')}"),
            manufacturer=str(manufacturer_name),
            model=str(product["model"]),
            format=str(product.get("cellFormat", "unknown")),
            chemistry=str(product.get("chemistry", "unknown")),
            positive_electrode_basis=product.get("positiveElectrodeBasis"),
            negative_electrode_basis=product.get("negativeElectrodeBasis"),
            size_code=product.get("sizeCode"),
            datasheet_revision=product.get("datasheetRevision"),
            cell_specification_id=cell_specification_id,
            nominal_properties=dict(record.get("specs", {})) if isinstance(record.get("specs"), Mapping) else {},
            source=ProvenanceInfo(
                type=provenance.get("source_type"),
                file=provenance.get("source_file"),
                url=provenance.get("source_url"),
                citation=_citation_url_value(provenance.get("citation"), provenance.get("citation_doi")),
                retrieved_at=provenance.get("retrieved_at"),
                file_hash=provenance.get("file_hash"),
            ),
            comment=[str(item) for item in notes],
        )

    @classmethod
    def from_cell_specification(
        cls,
        specification: CellSpecification,
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> Self:
        return cls(
            id=id or specification.id,
            name=name or f"{specification.manufacturer} {specification.model}",
            manufacturer=specification.manufacturer,
            model=specification.model,
            format=specification.format,
            chemistry=specification.chemistry,
            positive_electrode_basis=specification.positive_electrode_basis,
            negative_electrode_basis=specification.negative_electrode_basis,
            size_code=specification.size_code,
            cell_specification_id=specification.id,
            nominal_properties=dict(specification.properties),
            source=ProvenanceInfo(
                type=specification.source.type,
                file=specification.source.file,
                url=specification.source.url,
                citation=_citation_url_value(specification.source.citation),
                retrieved_at=specification.source.retrieved_at,
            ),
            comment=["Generated from the linked CellSpecification."],
        )

    def to_record(self) -> dict[str, Any]:
        if self.id is None:
            raise ValueError("CellType.id is required before serialization. Use battinfo.publish(...) to finalize IDs.")
        if self.name is None:
            raise ValueError("CellType.name is required before serialization.")
        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "product": {
                "id": self.id,
                "short_id": _short_id(self.id),
                "identifier": _identifier("cell-type", self.id),
                "name": self.name,
                "model": self.model,
                "manufacturer": {"type": "Organization", "name": self.manufacturer},
                "cellFormat": self.format,
                "chemistry": self.chemistry,
            },
            "specs": self.nominal_properties,
            "provenance": {},
        }
        if self.positive_electrode_basis is not None:
            record["product"]["positiveElectrodeBasis"] = self.positive_electrode_basis
        if self.negative_electrode_basis is not None:
            record["product"]["negativeElectrodeBasis"] = self.negative_electrode_basis
        if self.size_code is not None:
            record["product"]["sizeCode"] = self.size_code
        if self.datasheet_revision is not None:
            record["product"]["datasheetRevision"] = self.datasheet_revision
        if self.source.type is not None:
            record["provenance"]["source_type"] = self.source.type
        if self.source.file is not None:
            record["provenance"]["source_file"] = self.source.file
        if self.source.url is not None:
            record["provenance"]["source_url"] = self.source.url
        citation = _citation_url_value(self.source.citation)
        if citation is not None:
            record["provenance"]["citation"] = citation
        if self.source.retrieved_at is not None:
            record["provenance"]["retrieved_at"] = self.source.retrieved_at
        if self.source.file_hash is not None:
            record["provenance"]["file_hash"] = self.source.file_hash
        if self.comment:
            record["notes"] = list(self.comment)
        return record


class CellInstance(BundleJsonModel):
    default_filename: ClassVar[str] = CELL_INSTANCE_FILENAME

    kind: str = "CellInstance"
    id: str | None = None
    name: str | None = None
    cell_type_id: str | None = None
    cell_type: CellType | None = Field(default=None, exclude=True, repr=False)
    serial_number: str | None = None
    batch_id: str | None = None
    manufactured_at: int | str | None = None
    measured: dict[str, Any] = Field(default_factory=dict)
    dataset_ids: list[str] = Field(default_factory=list)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)

    def __init__(self, cell_type: CellType | None = None, /, **data: Any) -> None:
        if cell_type is not None and "cell_type" not in data and "cell_type_id" not in data:
            data["cell_type"] = cell_type
        super().__init__(**data)

    @model_validator(mode="after")
    def _populate_links(self) -> Self:
        if self.cell_type_id is None and self.cell_type is not None and self.cell_type.id is not None:
            self.cell_type_id = self.cell_type.id
        if self.name is None:
            self.name = self.serial_number or self.batch_id or _id_tail(self.id)
        return self

    @property
    def measurements(self) -> _AttributeMappingProxy:
        return _AttributeMappingProxy(self.measured)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Self:
        cell_instance = record.get("cell_instance")
        if not isinstance(cell_instance, Mapping):
            raise ValueError("cell instance record must contain a 'cell_instance' object.")
        provenance = record.get("provenance", {})
        if not isinstance(provenance, Mapping):
            provenance = {}
        datasets = record.get("datasets")
        dataset_ids: list[str] = []
        if isinstance(datasets, list):
            dataset_ids = [
                str(item["id"])
                for item in datasets
                if isinstance(item, Mapping) and isinstance(item.get("id"), str)
            ]
        elif isinstance(provenance.get("dataset_ids"), list):
            dataset_ids = [str(item) for item in provenance["dataset_ids"] if isinstance(item, str)]
        elif isinstance(provenance.get("dataset_id"), str):
            dataset_ids = [str(provenance["dataset_id"])]
        notes = record.get("notes")
        if not isinstance(notes, list):
            notes = []
        return cls(
            schema_version=str(record.get("schema_version", "1.0.0")),
            id=str(cell_instance["id"]),
            name=str(cell_instance.get("serial_number") or cell_instance["id"].rstrip("/").split("/")[-1]),
            cell_type_id=str(cell_instance["type_id"]),
            serial_number=cell_instance.get("serial_number"),
            batch_id=cell_instance.get("batch_id"),
            manufactured_at=cell_instance.get("manufactured_at"),
            measured=dict(record.get("measured", {})) if isinstance(record.get("measured"), Mapping) else {},
            dataset_ids=[str(item) for item in dataset_ids],
            source=ProvenanceInfo(
                type=provenance.get("source_type"),
                url=provenance.get("source_url"),
                citation=_citation_url_value(provenance.get("citation"), provenance.get("citation_doi")),
                retrieved_at=provenance.get("retrieved_at"),
            ),
            comment=[str(item) for item in notes],
        )

    def to_record(self) -> dict[str, Any]:
        if self.id is None:
            raise ValueError("CellInstance.id is required before serialization. Use battinfo.publish(...) to finalize IDs.")
        if self.cell_type_id is None:
            raise ValueError("CellInstance.cell_type_id is required before serialization.")
        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "cell_instance": {
                "id": self.id,
                "short_id": _short_id(self.id),
                "type_id": self.cell_type_id,
                "serial_number": self.serial_number,
                "batch_id": self.batch_id,
                "manufactured_at": self.manufactured_at,
            },
            "provenance": {},
        }
        if self.measured:
            record["measured"] = self.measured
        if self.dataset_ids:
            record["datasets"] = [{"id": dataset_id, "role": "raw"} for dataset_id in self.dataset_ids]
        if self.source.type is not None:
            record["provenance"]["source_type"] = self.source.type
        if self.source.url is not None:
            record["provenance"]["source_url"] = self.source.url
        citation = _citation_url_value(self.source.citation)
        if citation is not None:
            record["provenance"]["citation"] = citation
        if self.source.retrieved_at is not None:
            record["provenance"]["retrieved_at"] = self.source.retrieved_at
        record["cell_instance"] = {key: value for key, value in record["cell_instance"].items() if value is not None}
        if self.comment:
            record["notes"] = list(self.comment)
        return record


class Test(BundleJsonModel):
    default_filename: ClassVar[str] = TEST_FILENAME

    kind: str = "Test"
    __test__ = False
    id: str | None = None
    name: str | None = None
    test_type: BatteryTestType = Field(
        default=BatteryTestType.OTHER,
        validation_alias=AliasChoices("test_type", "test_kind", "kind"),
    )
    cell_instance_id: str | None = None
    cell: CellInstance | None = Field(default=None, exclude=True, repr=False)
    description: str | None = None
    status: str | None = None
    protocol: ProtocolInfo = Field(default_factory=ProtocolInfo)
    instrument: str | None = None
    started_at: int | str | None = None
    ended_at: int | str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)

    def __init__(self, cell: CellInstance | None = None, /, **data: Any) -> None:
        if cell is not None and "cell" not in data and "cell_instance_id" not in data:
            data["cell"] = cell
        super().__init__(**data)

    @field_validator("protocol", mode="before")
    @classmethod
    def _coerce_protocol(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value}
        return value

    @model_validator(mode="after")
    def _populate_links(self) -> Self:
        if self.cell_instance_id is None and self.cell is not None and self.cell.id is not None:
            self.cell_instance_id = self.cell.id
        if self.name is None:
            base = self.protocol.name or self.test_type
            cell_name = self.cell.name if self.cell is not None else None
            self.name = f"{cell_name} {base}" if cell_name else base
        return self

    @property
    def test_kind(self) -> BatteryTestType:
        return self.test_type

    @test_kind.setter
    def test_kind(self, value: BatteryTestType | str) -> None:
        self.test_type = BatteryTestType(value)

    @property
    def protocol_name(self) -> str | None:
        return self.protocol.name

    @protocol_name.setter
    def protocol_name(self, value: str | None) -> None:
        self.protocol.name = value

    @property
    def protocol_url(self) -> str | None:
        return self.protocol.url

    @protocol_url.setter
    def protocol_url(self, value: str | None) -> None:
        self.protocol.url = value

    @property
    def instrument_name(self) -> str | None:
        return self.instrument

    @instrument_name.setter
    def instrument_name(self, value: str | None) -> None:
        self.instrument = value

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Self:
        test = record.get("test")
        if not isinstance(test, Mapping):
            raise ValueError("test record must contain a 'test' object.")
        provenance = record.get("provenance", {})
        if not isinstance(provenance, Mapping):
            provenance = {}
        notes = record.get("notes")
        if not isinstance(notes, list):
            notes = []
        dataset_ids = test.get("dataset_ids")
        if not isinstance(dataset_ids, list):
            dataset_ids = []
        return cls(
            schema_version=str(record.get("schema_version", "1.0.0")),
            id=str(test["id"]),
            name=str(test["name"]),
            test_type=test["kind"],
            cell_instance_id=str(test["cell_id"]),
            description=test.get("description"),
            status=test.get("status"),
            protocol=ProtocolInfo(
                name=test.get("protocol_name"),
                url=test.get("protocol_url"),
            ),
            instrument=test.get("instrument_name"),
            started_at=test.get("started_at"),
            ended_at=test.get("ended_at"),
            dataset_ids=[str(item) for item in dataset_ids],
            source=ProvenanceInfo(
                type=provenance.get("source_type"),
                file=provenance.get("source_file"),
                url=provenance.get("source_url"),
                citation=_citation_url_value(provenance.get("citation"), provenance.get("citation_doi")),
                retrieved_at=provenance.get("retrieved_at"),
                workflow_version=provenance.get("workflow_version"),
            ),
            comment=[str(item) for item in notes],
        )

    def to_record(self) -> dict[str, Any]:
        if self.id is None:
            raise ValueError("Test.id is required before serialization. Use battinfo.publish(...) to finalize IDs.")
        if self.name is None:
            raise ValueError("Test.name is required before serialization.")
        if self.cell_instance_id is None:
            raise ValueError("Test.cell_instance_id is required before serialization.")
        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "test": {
                "id": self.id,
                "short_id": _short_id(self.id),
                "identifier": _identifier("test", self.id),
                "name": self.name,
                "kind": self.test_type,
                "cell_id": self.cell_instance_id,
            },
            "provenance": {},
        }
        if self.description is not None:
            record["test"]["description"] = self.description
        if self.status is not None:
            record["test"]["status"] = self.status
        if self.protocol.name is not None:
            record["test"]["protocol_name"] = self.protocol.name
        if self.protocol.url is not None:
            record["test"]["protocol_url"] = self.protocol.url
        if self.instrument is not None:
            record["test"]["instrument_name"] = self.instrument
        if self.started_at is not None:
            record["test"]["started_at"] = self.started_at
        if self.ended_at is not None:
            record["test"]["ended_at"] = self.ended_at
        if self.dataset_ids:
            record["test"]["dataset_ids"] = list(self.dataset_ids)
        if self.source.type is not None:
            record["provenance"]["source_type"] = self.source.type
        if self.source.file is not None:
            record["provenance"]["source_file"] = self.source.file
        if self.source.url is not None:
            record["provenance"]["source_url"] = self.source.url
        citation = _citation_url_value(self.source.citation)
        if citation is not None:
            record["provenance"]["citation"] = citation
        if self.source.retrieved_at is not None:
            record["provenance"]["retrieved_at"] = self.source.retrieved_at
        if self.source.workflow_version is not None:
            record["provenance"]["workflow_version"] = self.source.workflow_version
        if self.comment:
            record["notes"] = list(self.comment)
        return record


class Dataset(BundleJsonModel):
    default_filename: ClassVar[str] = DATASET_FILENAME

    kind: str = "Dataset"
    id: str | None = None
    identifier: Any = None
    name: str | None = None
    description: str | None = None
    license: str | None = None
    same_as: list[str] = Field(default_factory=list, validation_alias=AliasChoices("same_as", "sameAs"))
    additional_type: list[str] = Field(default_factory=list, validation_alias=AliasChoices("additional_type", "additionalType"))
    version: str | None = None
    keywords: list[str] = Field(default_factory=list)
    creators: list[dict[str, Any]] = Field(default_factory=list, validation_alias=AliasChoices("creators", "creator"))
    publisher: dict[str, Any] | None = None
    funders: list[dict[str, Any]] = Field(default_factory=list, validation_alias=AliasChoices("funders", "funder"))
    citations: list[dict[str, Any]] = Field(default_factory=list, validation_alias=AliasChoices("citations", "citation"))
    measurement_techniques: list[str] = Field(default_factory=list, validation_alias=AliasChoices("measurement_techniques", "measurementTechnique"))
    measurement_methods: list[str] = Field(default_factory=list, validation_alias=AliasChoices("measurement_methods", "measurementMethod"))
    variable_measured: list[dict[str, Any]] = Field(default_factory=list, validation_alias=AliasChoices("variable_measured", "variableMeasured"))
    is_accessible_for_free: bool | None = Field(default=None, validation_alias=AliasChoices("is_accessible_for_free", "isAccessibleForFree"))
    conditions_of_access: str | None = Field(default=None, validation_alias=AliasChoices("conditions_of_access", "conditionsOfAccess"))
    in_language: str | None = Field(default=None, validation_alias=AliasChoices("in_language", "inLanguage"))
    data_format: str | None = None
    dataset_path: str | None = Field(default=None, validation_alias=AliasChoices("dataset_path", "path"))
    access_url: str | None = None
    download_url: str | None = None
    created_at: int | str | None = Field(default=None, validation_alias=AliasChoices("created_at", "dateCreated"))
    modified_at: int | str | None = Field(default=None, validation_alias=AliasChoices("modified_at", "dateModified"))
    published_at: int | str | None = Field(default=None, validation_alias=AliasChoices("published_at", "datePublished"))
    temporal_coverage: str | None = Field(default=None, validation_alias=AliasChoices("temporal_coverage", "temporalCoverage"))
    spatial_coverage: str | None = Field(default=None, validation_alias=AliasChoices("spatial_coverage", "spatialCoverage"))
    is_based_on: list[str] = Field(default_factory=list, validation_alias=AliasChoices("is_based_on", "isBasedOn"))
    included_in_data_catalog: str | dict[str, Any] | None = Field(default=None, validation_alias=AliasChoices("included_in_data_catalog", "includedInDataCatalog"))
    main_entity: list[dict[str, Any]] = Field(default_factory=list, validation_alias=AliasChoices("main_entity", "mainEntity"))
    distributions: list[dict[str, Any]] = Field(default_factory=list, validation_alias=AliasChoices("distributions", "distribution"))
    checksum: ChecksumInfo = Field(default_factory=ChecksumInfo)
    cell_instance_id: str | None = None
    test_id: str | None = None
    test: Test | None = Field(default=None, exclude=True, repr=False)
    cell: CellInstance | None = Field(default=None, exclude=True, repr=False)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)

    def __init__(self, path: str | Path | None = None, /, **data: Any) -> None:
        if path is not None and "dataset_path" not in data and "path" not in data:
            data["path"] = str(path)
        super().__init__(**data)

    @field_validator("identifier", mode="before")
    @classmethod
    def _coerce_identifier(cls, value: Any) -> Any:
        return _copy_identifier(value)

    @field_validator(
        "same_as",
        "additional_type",
        "keywords",
        "measurement_techniques",
        "measurement_methods",
        "is_based_on",
        mode="before",
    )
    @classmethod
    def _coerce_string_lists(cls, value: Any) -> list[str]:
        return _string_list(value)

    @field_validator("creators", mode="before")
    @classmethod
    def _coerce_creators(cls, value: Any) -> list[dict[str, Any]]:
        return [agent for item in _mapping_list(value) if (agent := _canonical_agent(item)) is not None]

    @field_validator("publisher", mode="before")
    @classmethod
    def _coerce_publisher(cls, value: Any) -> dict[str, Any] | None:
        return _canonical_agent(value)

    @field_validator("funders", mode="before")
    @classmethod
    def _coerce_funders(cls, value: Any) -> list[dict[str, Any]]:
        return [agent for item in _mapping_list(value) if (agent := _canonical_agent(item)) is not None]

    @field_validator("included_in_data_catalog", mode="before")
    @classmethod
    def _coerce_included_in_data_catalog(cls, value: Any) -> dict[str, Any] | str | None:
        return _canonical_data_catalog(value)

    @field_validator("citations", mode="before")
    @classmethod
    def _coerce_citations(cls, value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, (str, Mapping)):
            value = [value]
        if not isinstance(value, list):
            return []
        out: list[dict[str, Any]] = []
        for item in value:
            citation = _canonical_citation(item)
            if citation is not None:
                out.append(citation)
        return out

    @field_validator("variable_measured", mode="before")
    @classmethod
    def _coerce_variable_measured(cls, value: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in _mapping_list(value):
            variable = _canonical_variable_measured(item)
            if variable is not None:
                out.append(variable)
        return out

    @field_validator("distributions", mode="before")
    @classmethod
    def _coerce_distributions(cls, value: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in _mapping_list(value):
            distribution = _canonical_distribution(item)
            if distribution is not None:
                out.append(distribution)
        return out

    @field_validator("main_entity", mode="before")
    @classmethod
    def _coerce_main_entity(cls, value: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in _mapping_list(value):
            main_entity = _canonical_main_entity(item)
            if main_entity is not None:
                out.append(main_entity)
        return out

    @model_validator(mode="after")
    def _populate_links(self) -> Self:
        if self.test_id is None and self.test is not None and self.test.id is not None:
            self.test_id = self.test.id
        if self.cell_instance_id is None:
            if self.cell is not None and self.cell.id is not None:
                self.cell_instance_id = self.cell.id
            elif self.test is not None and self.test.cell_instance_id is not None:
                self.cell_instance_id = self.test.cell_instance_id
        if self.name is None:
            self.name = (
                Path(self.dataset_path).name
                if self.dataset_path is not None
                else self.access_url or _id_tail(self.id)
            )
        if self.modified_at is None:
            self.modified_at = self.created_at
        if self.published_at is None:
            self.published_at = self.created_at
        if self.identifier is None and self.id is not None:
            self.identifier = _identifier("dataset", self.id)
        return self

    @property
    def path(self) -> str | None:
        return self.dataset_path

    @path.setter
    def path(self, value: str | Path | None) -> None:
        self.dataset_path = None if value is None else str(value)

    def with_tabular_data(
        self,
        *,
        data: Any = None,
        columns: list[Any] | None = None,
        column_metadata: Mapping[str, Any] | None = None,
        csvw_url: str | None = None,
        table_schema: str | Mapping[str, Any] | BaseModel | None = None,
        table_id: str | None = None,
        table_name: str | None = None,
        table_description: str | None = None,
        merge_variables: bool = True,
        replace_main_entity: bool = False,
    ) -> Self:
        from battinfo.metadata import enrich_tabular_dataset

        return enrich_tabular_dataset(
            self,
            data=data,
            columns=columns,
            column_metadata=column_metadata,
            csvw_url=csvw_url,
            table_schema=table_schema,
            table_id=table_id,
            table_name=table_name,
            table_description=table_description,
            merge_variables=merge_variables,
            replace_main_entity=replace_main_entity,
        )

    @classmethod
    def from_record(cls, record: Mapping[str, Any], *, dataset_path: str | None = None) -> Self:
        dataset = record.get("dataset")
        if not isinstance(dataset, Mapping):
            raise ValueError("dataset record must contain a 'dataset' object.")
        provenance = record.get("provenance", {})
        if not isinstance(provenance, Mapping):
            provenance = {}
        about = dataset.get("about")
        related_cell_id = None
        related_test_id = None
        if isinstance(about, list):
            for item in about:
                if isinstance(item, str) and "/cell/" in item and related_cell_id is None:
                    related_cell_id = item
                if isinstance(item, str) and "/test/" in item and related_test_id is None:
                    related_test_id = item
        distribution = dataset.get("distribution")
        checksum = ChecksumInfo()
        data_format = None
        download_url = None
        if isinstance(distribution, list) and distribution and isinstance(distribution[0], Mapping):
            first = distribution[0]
            data_format = first.get("encodingFormat")
            download_url = first.get("contentUrl")
            checksum_obj = first.get("checksum")
            if isinstance(checksum_obj, Mapping):
                checksum = ChecksumInfo(
                    algorithm=checksum_obj.get("algorithm"),
                    value=checksum_obj.get("value"),
                )
        notes = record.get("notes")
        if not isinstance(notes, list):
            notes = []
        return cls(
            schema_version=str(record.get("schema_version", "1.0.0")),
            id=str(dataset["id"]),
            identifier=_copy_identifier(dataset.get("identifier")),
            name=str(dataset.get("name") or dataset.get("title") or dataset["id"]),
            description=dataset.get("description"),
            license=dataset.get("license"),
            same_as=_string_list(dataset.get("sameAs")),
            additional_type=_string_list(dataset.get("additionalType")),
            version=dataset.get("version"),
            keywords=_string_list(dataset.get("keywords")),
            creators=_mapping_list(dataset.get("creator")),
            publisher=_canonical_agent(dataset.get("publisher")),
            funders=_mapping_list(dataset.get("funder")),
            citations=[citation for item in (dataset.get("citation") if isinstance(dataset.get("citation"), list) else [dataset.get("citation")] if dataset.get("citation") is not None else []) if (citation := _canonical_citation(item)) is not None],
            measurement_techniques=_string_list(dataset.get("measurementTechnique")),
            measurement_methods=_string_list(dataset.get("measurementMethod")),
            variable_measured=[variable for item in _mapping_list(dataset.get("variableMeasured")) if (variable := _canonical_variable_measured(item)) is not None],
            is_accessible_for_free=dataset.get("isAccessibleForFree") if isinstance(dataset.get("isAccessibleForFree"), bool) else None,
            conditions_of_access=dataset.get("conditionsOfAccess"),
            in_language=dataset.get("inLanguage"),
            data_format=data_format,
            dataset_path=dataset_path,
            access_url=dataset.get("url"),
            download_url=download_url,
            created_at=dataset.get("dateCreated"),
            modified_at=dataset.get("dateModified"),
            published_at=dataset.get("datePublished"),
            temporal_coverage=dataset.get("temporalCoverage"),
            spatial_coverage=dataset.get("spatialCoverage"),
            is_based_on=_string_list(dataset.get("isBasedOn")),
            included_in_data_catalog=_canonical_data_catalog(dataset.get("includedInDataCatalog")),
            main_entity=[entity for item in _mapping_list(dataset.get("mainEntity")) if (entity := _canonical_main_entity(item)) is not None],
            distributions=[dist for item in _mapping_list(distribution) if (dist := _canonical_distribution(item)) is not None],
            checksum=checksum,
            cell_instance_id=related_cell_id,
            test_id=related_test_id,
            source=ProvenanceInfo(
                type=provenance.get("source_type"),
                url=provenance.get("source_url"),
                citation=_citation_url_value(provenance.get("citation"), provenance.get("citation_doi")),
                retrieved_at=provenance.get("retrieved_at"),
                curated_by=provenance.get("curated_by"),
            ),
            comment=[str(item) for item in notes],
        )

    def to_record(self) -> dict[str, Any]:
        if self.id is None:
            raise ValueError("Dataset.id is required before serialization. Use battinfo.publish(...) to finalize IDs.")
        if self.name is None:
            raise ValueError("Dataset.name is required before serialization.")
        dataset_obj: dict[str, Any] = {
            "id": self.id,
            "short_id": _short_id(self.id),
            "identifier": _copy_identifier(self.identifier) or _identifier("dataset", self.id),
            "name": self.name,
        }
        if self.description is not None:
            dataset_obj["description"] = self.description
        if self.license is not None:
            dataset_obj["license"] = self.license
        if self.same_as:
            dataset_obj["sameAs"] = list(self.same_as)
        if self.additional_type:
            dataset_obj["additionalType"] = list(self.additional_type)
        if self.version is not None:
            dataset_obj["version"] = self.version
        if self.keywords:
            dataset_obj["keywords"] = list(self.keywords)
        if self.creators:
            dataset_obj["creator"] = copy.deepcopy(self.creators)
        if self.publisher is not None:
            dataset_obj["publisher"] = copy.deepcopy(self.publisher)
        if self.funders:
            dataset_obj["funder"] = copy.deepcopy(self.funders)
        if self.citations:
            dataset_obj["citation"] = copy.deepcopy(self.citations)
        if self.measurement_techniques:
            dataset_obj["measurementTechnique"] = list(self.measurement_techniques)
        if self.measurement_methods:
            dataset_obj["measurementMethod"] = list(self.measurement_methods)
        if self.variable_measured:
            dataset_obj["variableMeasured"] = copy.deepcopy(self.variable_measured)
        if self.is_accessible_for_free is not None:
            dataset_obj["isAccessibleForFree"] = self.is_accessible_for_free
        if self.conditions_of_access is not None:
            dataset_obj["conditionsOfAccess"] = self.conditions_of_access
        if self.in_language is not None:
            dataset_obj["inLanguage"] = self.in_language
        if self.access_url is not None:
            dataset_obj["url"] = self.access_url
        if self.created_at is not None:
            dataset_obj["dateCreated"] = self.created_at
        if self.modified_at is not None:
            dataset_obj["dateModified"] = self.modified_at
        elif self.created_at is not None:
            dataset_obj["dateModified"] = self.created_at
        if self.published_at is not None:
            dataset_obj["datePublished"] = self.published_at
        elif self.created_at is not None:
            dataset_obj["datePublished"] = self.created_at
        if self.temporal_coverage is not None:
            dataset_obj["temporalCoverage"] = self.temporal_coverage
        if self.spatial_coverage is not None:
            dataset_obj["spatialCoverage"] = self.spatial_coverage
        about: list[str] = []
        if self.cell_instance_id is not None:
            about.append(self.cell_instance_id)
        if self.test_id is not None:
            about.append(self.test_id)
        if about:
            dataset_obj["about"] = about
        if self.is_based_on:
            dataset_obj["isBasedOn"] = list(self.is_based_on)
        if self.included_in_data_catalog is not None:
            dataset_obj["includedInDataCatalog"] = self.included_in_data_catalog
        if self.main_entity:
            dataset_obj["mainEntity"] = copy.deepcopy(self.main_entity)
        if self.distributions:
            dataset_obj["distribution"] = copy.deepcopy(self.distributions)
        elif self.download_url is not None or self.data_format is not None or self.checksum.value is not None:
            dist: dict[str, Any] = {}
            if self.download_url is not None:
                dist["contentUrl"] = self.download_url
            elif self.access_url is not None:
                dist["contentUrl"] = self.access_url
            if self.data_format is not None:
                dist["encodingFormat"] = self.data_format
            if self.checksum.value is not None:
                dist["checksum"] = {
                    "algorithm": self.checksum.algorithm,
                    "value": self.checksum.value,
                }
            dataset_obj["distribution"] = [dist]

        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "dataset": dataset_obj,
            "provenance": {},
        }
        if self.source.type is not None:
            record["provenance"]["source_type"] = self.source.type
        if self.source.url is not None:
            record["provenance"]["source_url"] = self.source.url
        citation = _citation_url_value(self.source.citation)
        if citation is not None:
            record["provenance"]["citation"] = citation
        if self.source.retrieved_at is not None:
            record["provenance"]["retrieved_at"] = self.source.retrieved_at
        if self.source.curated_by is not None:
            record["provenance"]["curated_by"] = self.source.curated_by
        if self.comment:
            record["notes"] = list(self.comment)
        return record


class BattinfoBundle(BundleJsonModel):
    default_filename: ClassVar[str] = BUNDLE_MANIFEST_FILENAME

    kind: str = "BattinfoBundle"
    bundle_name: str | None = None
    cell_specification: CellSpecification | None = None
    cell_type: CellType
    cell_instance: CellInstance
    test: Test
    dataset: Dataset
    comment: list[str] = Field(default_factory=list)

    def manifest_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "cell_type_file": CELL_TYPE_FILENAME,
            "cell_instance_file": CELL_INSTANCE_FILENAME,
            "test_file": TEST_FILENAME,
            "dataset_file": DATASET_FILENAME,
        }
        if self.cell_specification is not None:
            payload["cell_specification_file"] = CELL_SPECIFICATION_FILENAME
        if self.bundle_name is not None:
            payload["bundle_name"] = self.bundle_name
        if self.comment:
            payload["comment"] = list(self.comment)
        return payload

    def to_directory(self, directory: PathLike) -> Path:
        root = _as_path(directory)
        root.mkdir(parents=True, exist_ok=True)
        if self.cell_specification is not None:
            self.cell_specification.to_path(root / CELL_SPECIFICATION_FILENAME)
        self.cell_type.to_path(root / CELL_TYPE_FILENAME)
        self.cell_instance.to_path(root / CELL_INSTANCE_FILENAME)
        self.test.to_path(root / TEST_FILENAME)
        self.dataset.to_path(root / DATASET_FILENAME)
        _write_json(root / BUNDLE_MANIFEST_FILENAME, self.manifest_json())
        return root

    @classmethod
    def from_directory(cls, directory: PathLike) -> Self:
        root = _as_path(directory)
        manifest = _read_json(root / BUNDLE_MANIFEST_FILENAME)
        cell_specification_file = manifest.get("cell_specification_file")
        cell_specification = None
        if isinstance(cell_specification_file, str):
            spec_path = root / cell_specification_file
            if spec_path.exists():
                cell_specification = CellSpecification.from_path(spec_path)
        return cls(
            schema_version=str(manifest.get("schema_version", "1.0.0")),
            bundle_name=manifest.get("bundle_name"),
            cell_specification=cell_specification,
            cell_type=CellType.from_path(root / str(manifest.get("cell_type_file", CELL_TYPE_FILENAME))),
            cell_instance=CellInstance.from_path(root / str(manifest.get("cell_instance_file", CELL_INSTANCE_FILENAME))),
            test=Test.from_path(root / str(manifest.get("test_file", TEST_FILENAME))),
            dataset=Dataset.from_path(root / str(manifest.get("dataset_file", DATASET_FILENAME))),
            comment=[str(item) for item in manifest.get("comment", [])] if isinstance(manifest.get("comment"), list) else [],
        )

    @classmethod
    def from_jsonld(cls, source: Mapping[str, Any] | PathLike) -> Self:
        payload = _read_json(_as_path(source)) if isinstance(source, (str, Path)) else dict(source)
        graph = _graph_nodes(payload)
        graph_by_id = {
            str(node["@id"]): node
            for node in graph
            if isinstance(node.get("@id"), str)
        }

        for node in graph:
            # Backward-compatible reader for older bundle-style JSON-LD payloads.
            if _node_has_type(node, "battinfo:MetadataBundle"):
                return cls(
                    bundle_name=node.get("schema:name") if isinstance(node.get("schema:name"), str) else None,
                    cell_specification=CellSpecification.from_json(node["battinfo:cellSpecificationRecord"])
                    if isinstance(node.get("battinfo:cellSpecificationRecord"), Mapping)
                    else None,
                    cell_type=CellType.from_json(node["battinfo:cellTypeRecord"]),
                    cell_instance=CellInstance.from_json(node["battinfo:cellInstanceRecord"]),
                    test=Test.from_json(node["battinfo:testRecord"]),
                    dataset=Dataset.from_json(node["battinfo:datasetRecord"]),
                    comment=_text_list(node.get("schema:description")),
                )

        cell_instance_node = next((node for node in graph if _node_has_type(node, "battinfo:BatteryCellInstance")), None)
        if cell_instance_node is None:
            cell_instance_node = next(
                (node for node in graph if _node_has_type(node, "schema:IndividualProduct")),
                None,
            )
        cell_type_id = None
        if cell_instance_node is not None:
            cell_type_id = next((value for value in _type_values(cell_instance_node) if "/cell-type/" in value), None)
            if cell_type_id is None:
                cell_type_id = _ref_id(cell_instance_node.get("schema:isVariantOf"))
        cell_type_node = graph_by_id.get(cell_type_id) if cell_type_id is not None else None
        if cell_type_node is None:
            cell_type_node = next(
                (
                    node
                    for node in graph
                    if _node_has_type(node, OWL_CLASS_IRI)
                    or _node_has_type(node, "schema:ProductModel")
                    or _node_has_type(node, "BatteryCell")
                ),
                None,
            )
        test_node = next((node for node in graph if _node_has_type(node, "battinfo:BatteryCellTest")), None)
        if test_node is None:
            test_node = next(
                (
                    node
                    for node in graph
                    if _node_has_type(node, "schema:Action")
                    and (_ref_id(node.get("schema:object")) or _ref_id(node.get("schema:about")))
                ),
                None,
            )
        dataset_node = next(
            (
                node
                for node in graph
                if _node_has_type(node, "schema:Dataset")
                and (
                    (
                        node.get("battinfo:aboutCell") is not None
                        and node.get("battinfo:aboutTest") is not None
                    )
                    or (
                        any("/cell/" in ref_id for ref_id in _ref_ids(node.get("schema:about")))
                        and any("/test/" in ref_id for ref_id in _ref_ids(node.get("schema:about")))
                    )
                )
            ),
            None,
        )

        if cell_type_node is None or cell_instance_node is None or test_node is None or dataset_node is None:
            raise ValueError("Could not reconstruct BattinfoBundle from JSON-LD graph.")

        cell_specification_node = next(
            (
                node
                for node in graph
                if _node_has_type(node, "schema:CreativeWork")
                and (
                    node.get("schema:additionalType") == "cell-specification"
                    or _ref_id(node.get("schema:about")) == str(cell_type_node.get("@id"))
                )
            ),
            None,
        )
        if cell_specification_node is None:
            spec_ref_id = _ref_id(cell_type_node.get("schema:isBasedOn"))
            candidate = graph_by_id.get(spec_ref_id) if spec_ref_id is not None else None
            if isinstance(candidate, Mapping) and _node_has_type(candidate, "schema:CreativeWork"):
                cell_specification_node = candidate

        manufacturer_obj = cell_type_node.get("schema:manufacturer")
        if not isinstance(manufacturer_obj, Mapping) and cell_specification_node is not None:
            manufacturer_obj = cell_specification_node.get("schema:manufacturer")
        manufacturer = (
            manufacturer_obj.get("schema:name")
            if isinstance(manufacturer_obj, Mapping)
            else manufacturer_obj
        )
        properties: dict[str, Any] = {}
        property_source = cell_specification_node if cell_specification_node is not None else cell_type_node
        for item in property_source.get("hasProperty", []):
            if isinstance(item, Mapping):
                extracted = _extract_property_item(item)
                if extracted is not None:
                    key, value = extracted
                    properties[key] = value

        source_obj = (
            cell_specification_node.get("schema:isBasedOn")
            if cell_specification_node is not None
            else cell_type_node.get("schema:isBasedOn")
        )
        if not isinstance(source_obj, Mapping):
            source_obj = {}
        subclass_ids = _subclass_ref_ids(cell_type_node)
        format_value = (
            "coin"
            if "CoinCell" in subclass_ids or _node_has_type(cell_instance_node, "CoinCell")
            else "cylindrical"
            if "CylindricalBattery" in subclass_ids or _node_has_type(cell_instance_node, "CylindricalBattery")
            else "pouch"
            if "PouchCell" in subclass_ids or _node_has_type(cell_instance_node, "PouchCell")
            else "prismatic"
            if "PrismaticBattery" in subclass_ids or _node_has_type(cell_instance_node, "PrismaticBattery")
            else str(cell_type_node.get("schema:category") or cell_specification_node.get("schema:category") if isinstance(cell_specification_node, Mapping) else "unknown")
        )
        cell_type = CellType(
            id=str(cell_type_node["@id"]),
            name=str(cell_type_node.get("schema:name") or f"{manufacturer} {cell_type_node.get('schema:model') or 'unknown'}"),
            manufacturer=str(manufacturer or "unknown"),
            model=str(
                cell_type_node.get("schema:model")
                or (cell_specification_node.get("schema:model") if isinstance(cell_specification_node, Mapping) else None)
                or cell_type_node.get("schema:name")
                or "unknown"
            ),
            format=format_value,
            chemistry=str(
                cell_type_node.get("schema:material")
                or (cell_specification_node.get("schema:material") if isinstance(cell_specification_node, Mapping) else None)
                or "unknown"
            ),
            size_code=cell_type_node.get("schema:size") or (cell_specification_node.get("schema:size") if isinstance(cell_specification_node, Mapping) else None),
            cell_specification_id=str(cell_specification_node.get("@id")) if isinstance(cell_specification_node, Mapping) else None,
            nominal_properties=properties,
            source=ProvenanceInfo(
                type=source_obj.get("schema:additionalType"),
                name=source_obj.get("schema:name"),
                file=source_obj.get("schema:identifier"),
                url=source_obj.get("schema:url") or source_obj.get("@id"),
                citation=_citation_url_value(
                    _ref_id(cell_type_node.get("schema:citation")) or source_obj.get("schema:citation"),
                    source_obj.get("bibo:doi"),
                ),
                retrieved_at=source_obj.get("schema:dateModified"),
                workflow_version=source_obj.get("schema:version"),
                comment=source_obj.get("schema:description"),
            ),
            comment=_text_list(cell_type_node.get("schema:description")),
        )
        cell_specification = None
        if isinstance(cell_specification_node, Mapping):
            spec_manufacturer_obj = cell_specification_node.get("schema:manufacturer")
            spec_manufacturer = (
                spec_manufacturer_obj.get("schema:name")
                if isinstance(spec_manufacturer_obj, Mapping)
                else spec_manufacturer_obj
            )
            cell_specification = CellSpecification(
                id=str(cell_specification_node["@id"]),
                manufacturer=str(spec_manufacturer or manufacturer or "unknown"),
                model=str(cell_specification_node.get("schema:model") or cell_type.model),
                format=str(cell_specification_node.get("schema:category") or cell_type.format),
                chemistry=str(cell_specification_node.get("schema:material") or cell_type.chemistry),
                size_code=cell_specification_node.get("schema:size"),
                properties=properties,
                specification_comment=_text_list(cell_specification_node.get("schema:description")),
                source=ProvenanceInfo(
                    type=source_obj.get("schema:additionalType"),
                    name=source_obj.get("schema:name"),
                    file=source_obj.get("schema:identifier"),
                    url=source_obj.get("schema:url") or source_obj.get("@id"),
                    citation=_citation_url_value(
                        _ref_id(cell_specification_node.get("schema:citation")) or source_obj.get("schema:citation"),
                        source_obj.get("bibo:doi"),
                    ),
                    retrieved_at=source_obj.get("schema:dateModified"),
                    workflow_version=source_obj.get("schema:version"),
                    comment=source_obj.get("schema:description"),
                ),
            )
        cell_instance = CellInstance(
            id=str(cell_instance_node["@id"]),
            name=str(cell_instance_node.get("schema:name") or cell_instance_node["@id"]),
            cell_type_id=str(cell_type_id or cell_type.id),
            serial_number=cell_instance_node.get("schema:serialNumber"),
            batch_id=cell_instance_node.get("battinfo:batchId"),
        )
        protocol_name, test_description = _protocol_from_description(test_node.get("schema:description"))
        instrument_name = _instrument_name(test_node.get("schema:instrument"))
        test = Test(
            id=str(test_node["@id"]),
            name=str(test_node.get("schema:name") or test_node["@id"]),
            test_kind=str(test_node.get("battinfo:testKind") or test_node.get("schema:additionalType") or "other"),
            cell_instance_id=str(
                _ref_id(test_node.get("battinfo:aboutCell"))
                or _ref_id(test_node.get("schema:object"))
                or _ref_id(test_node.get("schema:about"))
                or cell_instance.id
            ),
            description=test_description,
            status=test_node.get("schema:creativeWorkStatus") or test_node.get("schema:actionStatus"),
            protocol=ProtocolInfo(
                name=protocol_name,
            ),
            instrument=instrument_name,
            dataset_ids=[
                ref_id
                for ref_id in (
                    [_ref_id(item) for item in test_node.get("battinfo:hasDataset", [])]
                    + _ref_ids(test_node.get("schema:result"))
                )
                if ref_id is not None
            ],
            started_at=test_node.get("schema:startTime"),
        )
        dataset_distribution = dataset_node.get("schema:distribution")
        first_distribution = dataset_distribution[0] if isinstance(dataset_distribution, list) and dataset_distribution else {}
        dataset_main_entity = dataset_node.get("schema:mainEntity")
        dataset = Dataset(
            id=str(dataset_node["@id"]),
            identifier=_copy_identifier(dataset_node.get("schema:identifier")),
            name=str(dataset_node.get("schema:name") or dataset_node["@id"]),
            description=dataset_node.get("schema:description"),
            license=dataset_node.get("schema:license"),
            same_as=_ref_ids(dataset_node.get("schema:sameAs")),
            additional_type=_text_list(dataset_node.get("schema:additionalType")),
            version=dataset_node.get("schema:version"),
            keywords=_text_list(dataset_node.get("schema:keywords")),
            creators=[agent for item in (dataset_node.get("schema:creator") if isinstance(dataset_node.get("schema:creator"), list) else [dataset_node.get("schema:creator")] if dataset_node.get("schema:creator") is not None else []) if (agent := _canonical_agent(item)) is not None],
            publisher=_canonical_agent(dataset_node.get("schema:publisher")),
            funders=[agent for item in (dataset_node.get("schema:funder") if isinstance(dataset_node.get("schema:funder"), list) else [dataset_node.get("schema:funder")] if dataset_node.get("schema:funder") is not None else []) if (agent := _canonical_agent(item)) is not None],
            citations=[citation for item in (dataset_node.get("schema:citation") if isinstance(dataset_node.get("schema:citation"), list) else [dataset_node.get("schema:citation")] if dataset_node.get("schema:citation") is not None else []) if (citation := _canonical_citation(item)) is not None],
            measurement_techniques=_text_list(dataset_node.get("schema:measurementTechnique")),
            measurement_methods=_text_list(dataset_node.get("schema:measurementMethod")),
            variable_measured=[variable for item in _mapping_list(dataset_node.get("schema:variableMeasured")) if (variable := _canonical_variable_measured(item)) is not None],
            is_accessible_for_free=dataset_node.get("schema:isAccessibleForFree") if isinstance(dataset_node.get("schema:isAccessibleForFree"), bool) else None,
            conditions_of_access=dataset_node.get("schema:conditionsOfAccess"),
            in_language=dataset_node.get("schema:inLanguage"),
            data_format=first_distribution.get("schema:encodingFormat") if isinstance(first_distribution, Mapping) else None,
            access_url=dataset_node.get("schema:url"),
            download_url=first_distribution.get("schema:contentUrl") if isinstance(first_distribution, Mapping) else None,
            created_at=dataset_node.get("schema:dateCreated"),
            modified_at=dataset_node.get("schema:dateModified"),
            published_at=dataset_node.get("schema:datePublished"),
            temporal_coverage=dataset_node.get("schema:temporalCoverage"),
            spatial_coverage=dataset_node.get("schema:spatialCoverage"),
            is_based_on=_ref_ids(dataset_node.get("schema:isBasedOn")) or _text_list(dataset_node.get("schema:isBasedOn")),
            included_in_data_catalog=_canonical_data_catalog(
                _ref_id(dataset_node.get("schema:includedInDataCatalog"))
                or (
                    dataset_node.get("schema:includedInDataCatalog")
                    if isinstance(dataset_node.get("schema:includedInDataCatalog"), (str, Mapping))
                    else None
                )
            ),
            main_entity=[entity for item in _mapping_list(dataset_main_entity) if (entity := _canonical_main_entity(item)) is not None],
            distributions=[dist for item in _mapping_list(dataset_distribution) if (dist := _canonical_distribution(item)) is not None],
            cell_instance_id=(
                _ref_id(dataset_node.get("battinfo:aboutCell"))
                or next((ref_id for ref_id in _ref_ids(dataset_node.get("schema:about")) if "/cell/" in ref_id), None)
            ),
            test_id=(
                _ref_id(dataset_node.get("battinfo:aboutTest"))
                or next((ref_id for ref_id in _ref_ids(dataset_node.get("schema:about")) if "/test/" in ref_id), None)
            ),
        )
        return cls(
            bundle_name=dataset.name,
            cell_specification=cell_specification,
            cell_type=cell_type,
            cell_instance=cell_instance,
            test=test,
            dataset=dataset,
        )


def load_cell_specification(path: PathLike) -> CellSpecification:
    return CellSpecification.from_path(path)


__all__ = [
    "BatteryTestType",
    "BUNDLE_MANIFEST_FILENAME",
    "BattinfoBundle",
    "CELL_INSTANCE_FILENAME",
    "CELL_SPECIFICATION_FILENAME",
    "CELL_TYPE_FILENAME",
    "Coating",
    "CellInstance",
    "CellSpecification",
    "CellType",
    "ChecksumInfo",
    "CurrentCollector",
    "DATASET_FILENAME",
    "Dataset",
    "Electrode",
    "Electrolyte",
    "MaterialComponent",
    "load_cell_specification",
    "ProvenanceInfo",
    "ProtocolInfo",
    "Salt",
    "Separator",
    "SolventMixture",
    "TEST_FILENAME",
    "Test",
]
