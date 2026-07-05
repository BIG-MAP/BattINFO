from __future__ import annotations

import copy
import difflib
import re
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Mapping, Self

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from battinfo._jsonio import read_record_json as _read_json
from battinfo._jsonio import write_json as _write_json
from battinfo.canonical_aliases import record_to_snake_aliases
from battinfo.testmethod import Quantity, Step, compute_facets, parse_experiment

PathLike = str | Path

# Single source of truth for the ``schema_version`` stamped into every record this
# library emits (cell spec, cell instance, test, test spec, dataset, material, component).
# History: records originally said "0.1.0"; the 2026-07 input-model consolidation
# accidentally forked dataset records to "1.0.0". "0.2.0" deliberately supersedes both —
# bump it here (and CHANGELOG the record-shape change) whenever the emitted record shape
# changes.
SCHEMA_VERSION = "0.2.0"

BUNDLE_MANIFEST_FILENAME = "bundle.json"
CELL_SPECIFICATION_FILENAME = "cell-specification.json"
CELL_SPEC_FILENAME = "cell-spec.json"
CELL_INSTANCE_FILENAME = "cell-instance.json"
TEST_SPEC_FILENAME = "test-spec.json"
TEST_PROTOCOL_FILENAME = TEST_SPEC_FILENAME  # backward compat alias
TEST_FILENAME = "test.json"
DATASET_FILENAME = "dataset.json"
ZENODO_CELL_RECORD_FILENAME = "battinfo.bundle.json"
OWL_CLASS_IRI = "http://www.w3.org/2002/07/owl#Class"
RDFS_SUBCLASS_OF_IRI = "http://www.w3.org/2000/01/rdf-schema#subClassOf"


class BatteryTestType(StrEnum):
    CYCLING = "cycling"
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
    RPT = "rpt"
    QUASI_OCV = "quasi_ocv"
    FIELD = "field"
    DUTY_CYCLE = "duty_cycle"
    WLTP = "wltp"
    NEDC = "nedc"
    SEM = "sem"
    CHARACTERIZATION = "characterization"
    OTHER = "other"


class CellProductType(StrEnum):
    COMMERCIAL = "commercial"
    RESEARCH = "research"
    PROTOTYPE = "prototype"


def _as_path(path: PathLike) -> Path:
    return path if isinstance(path, Path) else Path(path)


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
        if ":" in type_name:
            type_name = type_name.rsplit(":", 1)[-1]
        if type_name == "Diameter":
            return "diameter"
        if type_name == "Height":
            return "height"
        if type_name == "NominalVoltage":
            return "nominal_voltage"
        if type_name == "NominalCapacity":
            return "nominal_capacity"
        if type_name == "TypicalEnergy":
            return "typical_energy"
        if type_name == "RatedEnergy":
            return "rated_energy"
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
    value = numerical.get("hasNumberValue", numerical.get("hasNumericalValue"))
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


def _country_name_value(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, Mapping):
        name = value.get("schema:name") or value.get("name")
        if isinstance(name, str):
            normalized = name.strip()
            return normalized or None
    return None


def _year_value(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if len(normalized) == 4 and normalized.isdigit():
            return int(normalized)
        if len(normalized) >= 4 and normalized[:4].isdigit():
            return int(normalized[:4])
    return None


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


# Flat provenance kwargs every record model absorbs into `source` (see the per-model
# _flat_provenance maps); listed here so the unknown-kwarg check knows them as vocabulary.
_FLAT_PROVENANCE_KEYS = (
    "source_type", "source_name", "source_file", "source_url", "citation",
    "file_hash", "retrieved_at", "workflow_version", "curated_by",
)


def _reject_unknown_kwargs(cls: type[BaseModel], data: Mapping[str, Any], *, extra_allowed: tuple[str, ...] = ()) -> None:
    """Raise a teaching TypeError for kwargs that match no field or alias.

    ``extra="forbid"`` would reject them anyway, but as a pydantic ValidationError that
    names only the stray key. A typo like ``manufacture=`` deserves a did-you-mean.
    Call AFTER the __init__ alias absorption, so only genuine strays remain in *data*."""
    allowed: set[str] = set(extra_allowed)
    for field_name, field_info in cls.model_fields.items():
        allowed.add(field_name)
        alias = field_info.validation_alias
        if isinstance(alias, AliasChoices):
            allowed.update(str(choice) for choice in alias.choices)
        elif isinstance(alias, str):
            allowed.add(alias)
    unknown = [key for key in data if key not in allowed]
    if not unknown:
        return
    parts = []
    for key in unknown:
        close = difflib.get_close_matches(key, sorted(allowed), n=1)
        parts.append(f"{key}=" + (f" (did you mean {close[0]}=?)" if close else ""))
    raise TypeError(
        f"Unknown field(s) for {cls.__name__}: " + ", ".join(parts)
        + f". Run help(battinfo.{cls.__name__}) for the accepted fields."
    )


def _provenance_from_record(provenance: Mapping[str, Any]) -> ProvenanceInfo:
    """Read a record's provenance block back into ProvenanceInfo.

    The inverse of ``_provenance_record`` — reads every field so
    to_record→from_record round-trips are lossless for provenance."""
    return ProvenanceInfo(
        type=provenance.get("source_type"),
        name=provenance.get("source_name"),
        file=provenance.get("source_file"),
        url=provenance.get("source_url"),
        citation=_citation_url_value(provenance.get("citation"), provenance.get("citation_doi")),
        retrieved_at=provenance.get("retrieved_at"),
        workflow_version=provenance.get("workflow_version"),
        file_hash=provenance.get("file_hash"),
        curated_by=provenance.get("curated_by"),
        comment=provenance.get("comment"),
    )


def _provenance_record(source: ProvenanceInfo) -> dict[str, Any]:
    """Serialize a ProvenanceInfo into a record's provenance block.

    Emits EVERY field the model accepts (None omitted) — the single serializer shared by
    all record types, so a provenance value accepted at construction (source_name=,
    file_hash=, ...) can never be silently dropped from the emitted record again."""
    out: dict[str, Any] = {}
    if source.type is not None:
        out["source_type"] = source.type
    if source.name is not None:
        out["source_name"] = source.name
    if source.file is not None:
        out["source_file"] = source.file
    if source.url is not None:
        out["source_url"] = source.url
    citation = _citation_url_value(source.citation)
    if citation is not None:
        out["citation"] = citation
    if source.retrieved_at is not None:
        out["retrieved_at"] = source.retrieved_at
    if source.workflow_version is not None:
        out["workflow_version"] = source.workflow_version
    if source.file_hash is not None:
        out["file_hash"] = source.file_hash
    if source.curated_by is not None:
        out["curated_by"] = source.curated_by
    if source.comment is not None:
        out["comment"] = source.comment
    return out


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


def _coerce_spec_value(value: Any) -> Any:
    """Coerce a SpecValue object to the canonical {"value": ..., "unit": ...} dict.

    Accepts the existing dict format unchanged; converts SpecValue objects from
    bundle_generated so that notebook code can pass either form.
    """
    if value is None or isinstance(value, Mapping):
        return value
    try:
        from battinfo.bundle_generated import SpecValue  # noqa: PLC0415
        if isinstance(value, SpecValue):
            out: dict[str, Any] = {}
            if value.sv_value is not None:
                out["value"] = value.sv_value
            if value.sv_unit is not None:
                out["unit"] = value.sv_unit
            if value.sv_min_value is not None:
                out["min_value"] = value.sv_min_value
            if value.sv_max_value is not None:
                out["max_value"] = value.sv_max_value
            if value.sv_typical_value is not None:
                out["typical_value"] = value.sv_typical_value
            return out
    except ImportError:
        pass
    return value


def _mapping_property(name: str) -> property:
    def getter(self: Any) -> Any:
        return self.properties.get(name)

    def setter(self: Any, value: Any) -> None:
        if value is None:
            self.properties.pop(name, None)
        else:
            self.properties[name] = _coerce_spec_value(value)

    return property(getter, setter)


CELL_TYPE_AUTHORING_PROPERTY_FIELDS: tuple[str, ...] = (
    "nominal_capacity",
    "minimum_capacity",
    "min_capacity",
    "rated_capacity",
    "typical_energy",
    "rated_energy",
    "nominal_voltage",
    "charging_voltage",
    "discharging_cutoff_voltage",
    "specific_energy",
    "energy_density",
    "specific_power",
    "power_density",
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
    "nominal_continuous_charging_current",
    "maximum_continuous_charging_current",
    "pulse_discharging_current",
    "continuous_discharging_current",
    "nominal_continuous_discharging_current",
    "maximum_continuous_discharging_current",
    "minimum_charging_temperature",
    "maximum_charging_temperature",
    "charging_temperature_min",
    "charging_temperature_max",
    "minimum_discharging_temperature",
    "maximum_discharging_temperature",
    "discharging_temperature_min",
    "discharging_temperature_max",
    "minimum_storage_temperature",
    "maximum_storage_temperature",
    "storage_temperature_min",
    "storage_temperature_max",
    "cycle_life",
)


class CellConstruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assembly_type: str | None = None
    layering: str | None = None
    layer_count: int | None = None
    # Electrode-assembly geometry (stack / jelly-roll).
    cathode_sheet_count: int | None = None
    anode_sheet_count: int | None = None
    separator_sheet_count: int | None = None
    winding_turns: float | None = None
    electrode_length: dict[str, Any] | None = None
    jellyroll_volume: dict[str, Any] | None = None
    assembly_sequence: list[str] | None = None
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
    elif any(
        key in value
        for key in (
            "email", "schema:email", "affiliation", "schema:affiliation",
            "orcid", "given_name", "schema:givenName", "family_name", "schema:familyName",
        )
    ):
        out["type"] = "Person"
    else:
        out["type"] = "Organization"
    orcid = value.get("orcid")
    if isinstance(orcid, str) and orcid.strip():
        out["orcid"] = orcid
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
    same_as = value.get("same_as") or value.get("sameAs") or value.get("schema:sameAs")
    if isinstance(same_as, str) and "://" in same_as:
        out["same_as"] = same_as
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
    same_as = value.get("same_as") or value.get("sameAs") or value.get("schema:sameAs")
    if isinstance(same_as, str):
        out["same_as"] = same_as
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
    same_as = value.get("same_as") or value.get("sameAs") or value.get("schema:sameAs")
    if isinstance(same_as, str):
        out["same_as"] = same_as
    property_id = value.get("property_id") or value.get("schema:propertyID")
    if isinstance(property_id, str) and "same_as" not in out:
        out["same_as"] = property_id
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
        ("content_url", ("content_url", "contentUrl", "schema:contentUrl")),
        ("encoding_format", ("encoding_format", "encodingFormat", "schema:encodingFormat")),
        ("content_size", ("content_size", "contentSize", "schema:contentSize")),
        ("access_level", ("access_level", "accessLevel", "schema:accessLevel")),
        # Role of this file within the dataset: "processed" (normalised, e.g. BDF
        # CSV) or "raw" (the original instrument file kept for provenance).
        ("role", ("role",)),
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
    return out if ("content_url" in out or "encoding_format" in out or "checksum" in out) else None


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
    same_as = value.get("same_as") or value.get("sameAs") or value.get("schema:sameAs") or value.get("property_id") or value.get("schema:propertyID")
    if isinstance(same_as, str):
        out["same_as"] = same_as
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
    primary_key = value.get("primary_key") or value.get("primaryKey") or value.get("csvw:primaryKey")
    if isinstance(primary_key, str):
        out["primary_key"] = primary_key
    elif isinstance(primary_key, list):
        values = [str(item) for item in primary_key if isinstance(item, str)]
        if values:
            out["primary_key"] = values
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
    table_schema = value.get("table_schema") or value.get("tableSchema") or value.get("csvw:tableSchema")
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
        "table_schema": copy.deepcopy(table_schema),
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
    table_items = value.get("tables") or value.get("table") or value.get("csvw:table")
    tables = [table for item in _mapping_list(table_items) if (table := _canonical_csvw_table(item)) is not None]
    if not tables:
        return None
    out: dict[str, Any] = {
        "type": "TableGroup",
        "tables": tables,
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
    material_spec_id: str | None = None
    manufacturer: str | None = None
    supplier: str | None = None
    product_id: str | None = None
    molecular_formula: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class Coating(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: dict[str, list[MaterialComponent]] = Field(default_factory=dict)
    manufacturer: str | None = None
    supplier: str | None = None
    product_id: str | None = None
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
    manufacturer: str | None = None
    supplier: str | None = None
    product_id: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class CurrentCollectorTab(BaseModel):
    """An electrode current-collector tab (prismatic/cylindrical/pouch)."""

    model_config = ConfigDict(extra="forbid")

    material: str | None = None
    manufacturer: str | None = None
    supplier: str | None = None
    product_id: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)  # width, thickness, length, weld_width, tape_width
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class Electrode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coating: Coating | None = None
    current_collector: CurrentCollector | None = None
    tab: CurrentCollectorTab | None = None
    manufacturer: str | None = None
    supplier: str | None = None
    product_id: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class SolventMixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: list[MaterialComponent] = Field(default_factory=list)
    manufacturer: str | None = None
    supplier: str | None = None
    product_id: str | None = None
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
    manufacturer: str | None = None
    supplier: str | None = None
    product_id: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class Separator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material: str | None = None
    manufacturer: str | None = None
    supplier: str | None = None
    product_id: str | None = None
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
    manufacturer: str | None = None
    supplier: str | None = None
    product_id: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


# ---------------------------------------------------------------------------
# Housing — format-neutral mechanical enclosure & hardware (E1).
# Each part is a holder with a ``property`` dict, so its quantities ride the
# generic descriptor property emitter. ``Housing`` is the canonical model for
# cell hardware; the legacy coin-specific ``coin_hardware`` dict normalizes into
# it on load (its on-disk retirement is a later coordinated schema migration).
# ---------------------------------------------------------------------------


class Terminal(BaseModel):
    """A cell terminal (prismatic/cylindrical/pouch)."""

    model_config = ConfigDict(extra="forbid")

    polarity: str | None = None  # "positive" | "negative"
    material: str | None = None
    manufacturer: str | None = None
    supplier: str | None = None
    product_id: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)  # width, thickness, weld_width, tape_width, length
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class Seal(BaseModel):
    """A pouch/prismatic seal."""

    model_config = ConfigDict(extra="forbid")

    material: str | None = None
    manufacturer: str | None = None
    supplier: str | None = None
    product_id: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)  # single_channel_thickness, top_corner_thickness
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class Case(BaseModel):
    """The cell case/can. JSON-LD @type is chosen from the cell format."""

    model_config = ConfigDict(extra="forbid")

    size_code: str | None = None
    material: str | None = None
    coating: str | None = None
    manufacturer: str | None = None
    supplier: str | None = None
    product_id: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)  # wall_thickness, weight, available_volume, filling_ratio
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class HardwarePart(BaseModel):
    """A generic discrete hardware part (cap/lid/can/spring/spacer)."""

    model_config = ConfigDict(extra="forbid")

    type: str | None = None  # e.g. "cap", "lid", "can", "spring", "spacer"
    material: str | None = None
    coating: str | None = None
    manufacturer: str | None = None
    supplier: str | None = None
    product_id: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("property", mode="before")
    @classmethod
    def _coerce_property(cls, value: Any) -> Any:
        return _mapping_from_object(value)


class Housing(BaseModel):
    """Format-neutral mechanical enclosure: case, terminals, seals, discrete parts."""

    model_config = ConfigDict(extra="forbid")

    case: Case | None = None
    cap: HardwarePart | None = None
    terminals: list[Terminal] = Field(default_factory=list)
    seals: list[Seal] = Field(default_factory=list)
    parts: list[HardwarePart] = Field(default_factory=list)  # spring/spacer/other
    comment: str | None = None

    def to_mapping(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


_COIN_HARDWARE_PART_KEYS = ("lid", "can", "spring", "spacer")


def _housing_from_coin_hardware(coin_hardware: Any) -> "Housing | None":
    """Migrate a legacy ``coin_hardware`` dict to a :class:`Housing` (case + parts)."""
    if not isinstance(coin_hardware, Mapping) or not coin_hardware:
        return None
    case: Case | None = None
    raw_case = coin_hardware.get("case")
    if isinstance(raw_case, Mapping):
        case = Case(
            size_code=raw_case.get("size_code"),
            material=raw_case.get("material"),
            coating=raw_case.get("coating"),
            manufacturer=raw_case.get("manufacturer"),
            supplier=raw_case.get("supplier"),
            product_id=raw_case.get("product_id"),
            property=dict(raw_case.get("property") or {}),
            comment=raw_case.get("comment"),
        )
    parts: list[HardwarePart] = []
    for key in _COIN_HARDWARE_PART_KEYS:
        raw = coin_hardware.get(key)
        if isinstance(raw, Mapping):
            parts.append(
                HardwarePart(
                    type=key,
                    material=raw.get("material"),
                    coating=raw.get("coating"),
                    manufacturer=raw.get("manufacturer"),
                    supplier=raw.get("supplier"),
                    product_id=raw.get("product_id"),
                    property=dict(raw.get("property") or {}),
                    comment=raw.get("comment"),
                )
            )
    if case is None and not parts:
        return None
    return Housing(case=case, parts=parts)


class BundleJsonModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
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
    # NOTE: This is the merged cell-specification model. It absorbs the former
    # ``CellType`` (authoring API: kwarg-absorbing __init__, _mapping_property
    # descriptors, optional id/name) AND the former datasheet specification model
    # (electrode/electrolyte/separator structure, library record format) — the two
    # describe the same entity, a BatteryCellSpecification, so a single class now
    # serves both the registry record (``cell_spec``/``properties``) and the library
    # record (``specification``/``property``) formats.
    default_filename: ClassVar[str] = CELL_SPEC_FILENAME

    kind: str = "CellSpecification"
    id: str | None = None
    # Transient short id used only to mint the canonical IRI when no id is given; never serialized.
    uid: str | None = Field(default=None, exclude=True, repr=False)
    name: str | None = None
    manufacturer: str = ""
    # Canonical IRI of the manufacturer's organization record. The schema types manufacturer as an
    # Organization object; keeping the name a plain string preserves the fluent authoring API while
    # this optional id carries the org link (previously dropped on save).
    manufacturer_id: str | None = None
    model: str = ""
    format: str = "unknown"
    chemistry: str = "unknown"
    product_type: CellProductType | None = None
    positive_electrode_basis: str | None = None
    negative_electrode_basis: str | None = None
    size_code: str | None = None
    iec_code: str | None = None
    country_of_origin: str | None = None
    rechargeable: bool | None = None
    year: int | None = None
    datasheet_revision: str | None = None
    cell_specification_id: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    # Datasheet structure (merged from the former CellSpecification).
    construction: dict[str, Any] = Field(default_factory=dict)
    positive_electrode: Electrode | None = None
    negative_electrode: Electrode | None = None
    electrolyte: Electrolyte | None = None
    separator: Separator | None = None
    housing: Housing | None = None
    # Optional canonical IRIs of standalone component-spec records this cell-spec references (used
    # instead of, or alongside, the inline holders above). The schema permits these; the model
    # previously dropped them, so only the JSON-LD inline re-map preserved them.
    positive_electrode_spec_id: str | None = None
    negative_electrode_spec_id: str | None = None
    electrolyte_spec_id: str | None = None
    separator_spec_id: str | None = None
    housing_spec_id: str | None = None
    specification_comment: list[str] = Field(default_factory=list)
    bibliography: dict[str, Any] = Field(default_factory=dict)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)
    # Audit note (model-as-source-of-truth): the cell-spec schema also permits `brand`,
    # `battery_category`, `category`, `url`, `additional_type`, `manufacturing_place`, `editorial`,
    # `hazardous_substances`, `critical_raw_materials`, `extinguishing_agent`, `funding`, and
    # `contributor`. These are intentionally NOT modeled here yet: none are authored through this
    # model today, so nothing is lost on save (unlike manufacturer.id / provenance / component refs,
    # which were). `funding`/`contributor` currently attach at the workspace layer, not the record.
    # Add them here (brand/category/… as objects where the schema requires) when a use case arrives.

    @field_validator("construction", "properties", mode="before")
    @classmethod
    def _coerce_mapping_fields(cls, value: Any) -> Any:
        return _mapping_from_object(value)

    @field_validator("positive_electrode", "negative_electrode", "electrolyte", "separator", mode="before")
    @classmethod
    def _coerce_component(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return dict(value)
        return value

    def __init__(self, **data: Any) -> None:
        # Absorb the flatter authoring/input shape (formerly CellSpecificationInput) so one model is
        # both the source of truth and the thing importers/CLI/tests construct directly.
        if "model_name" in data and "model" not in data:
            data["model"] = data.pop("model_name")
        if "notes" in data and "comment" not in data:
            data["comment"] = data.pop("notes")
        _manufacturer = data.get("manufacturer")
        if isinstance(_manufacturer, Mapping):
            data["manufacturer"] = _manufacturer.get("name", "") or ""
            if _manufacturer.get("id") and not data.get("manufacturer_id"):
                data["manufacturer_id"] = _manufacturer["id"]
        # Flat provenance kwargs -> the nested source object.
        _flat_provenance = {
            "source_type": "type", "source_name": "name", "source_file": "file", "source_url": "url",
            "citation": "citation", "file_hash": "file_hash", "retrieved_at": "retrieved_at",
            "workflow_version": "workflow_version", "curated_by": "curated_by",
        }
        if any(key in data for key in _flat_provenance) and "source" not in data:
            data["source"] = {nested: data.pop(flat) for flat, nested in _flat_provenance.items() if flat in data}

        explicit_properties = data.get("properties")
        if explicit_properties is None:
            explicit_properties = {}
        elif isinstance(explicit_properties, Mapping):
            explicit_properties = dict(explicit_properties)
        else:
            explicit_properties = dict(explicit_properties)
        # `specs` is an input alias for `properties`.
        _specs = data.pop("specs", None)
        if _specs is not None and not isinstance(_specs, Mapping):
            raise TypeError(
                "specs= must be a mapping of property name to value, e.g. "
                "specs={'nominal_capacity': {'value': 2.5, 'unit': 'Ah'}}; "
                f"got {type(_specs).__name__}."
            )
        if isinstance(_specs, Mapping):
            for _key, _value in _specs.items():
                explicit_properties.setdefault(_key, _value)

        for field_name in CELL_TYPE_AUTHORING_PROPERTY_FIELDS:
            if field_name in data:
                value = data.pop(field_name)
                if value is not None:
                    explicit_properties[field_name] = _coerce_spec_value(value)

        # Back-compat: the legacy ``coin_hardware`` dict is retired in favour of the
        # format-neutral ``housing`` model. Absorb it on input.
        legacy_coin_hardware = data.pop("coin_hardware", None)
        if legacy_coin_hardware and data.get("housing") is None:
            migrated = _housing_from_coin_hardware(legacy_coin_hardware)
            if migrated is not None:
                data["housing"] = migrated

        data["properties"] = explicit_properties
        _reject_unknown_kwargs(
            type(self), data,
            extra_allowed=("specs", "notes", "coin_hardware",
                           *CELL_TYPE_AUTHORING_PROPERTY_FIELDS, *_FLAT_PROVENANCE_KEYS),
        )
        super().__init__(**data)

    @model_validator(mode="after")
    def _populate_name(self) -> Self:
        if self.name is None:
            text = f"{self.manufacturer} {self.model}".strip()
            self.name = text or None
        return self

    @property
    def specs(self) -> _AttributeMappingProxy:
        return _AttributeMappingProxy(self.properties)

    nominal_capacity = _mapping_property("nominal_capacity")
    minimum_capacity = _mapping_property("minimum_capacity")
    min_capacity = _mapping_property("min_capacity")
    rated_capacity = _mapping_property("rated_capacity")
    typical_energy = _mapping_property("typical_energy")
    rated_energy = _mapping_property("rated_energy")
    nominal_voltage = _mapping_property("nominal_voltage")
    charging_voltage = _mapping_property("charging_voltage")
    discharging_cutoff_voltage = _mapping_property("discharging_cutoff_voltage")
    specific_energy = _mapping_property("specific_energy")
    energy_density = _mapping_property("energy_density")
    specific_power = _mapping_property("specific_power")
    power_density = _mapping_property("power_density")
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
    nominal_continuous_charging_current = _mapping_property("nominal_continuous_charging_current")
    maximum_continuous_charging_current = _mapping_property("maximum_continuous_charging_current")
    pulse_discharging_current = _mapping_property("pulse_discharging_current")
    continuous_discharging_current = _mapping_property("continuous_discharging_current")
    nominal_continuous_discharging_current = _mapping_property("nominal_continuous_discharging_current")
    maximum_continuous_discharging_current = _mapping_property("maximum_continuous_discharging_current")
    minimum_charging_temperature = _mapping_property("minimum_charging_temperature")
    maximum_charging_temperature = _mapping_property("maximum_charging_temperature")
    charging_temperature_min = _mapping_property("charging_temperature_min")
    charging_temperature_max = _mapping_property("charging_temperature_max")
    minimum_discharging_temperature = _mapping_property("minimum_discharging_temperature")
    maximum_discharging_temperature = _mapping_property("maximum_discharging_temperature")
    discharging_temperature_min = _mapping_property("discharging_temperature_min")
    discharging_temperature_max = _mapping_property("discharging_temperature_max")
    minimum_storage_temperature = _mapping_property("minimum_storage_temperature")
    maximum_storage_temperature = _mapping_property("maximum_storage_temperature")
    storage_temperature_min = _mapping_property("storage_temperature_min")
    storage_temperature_max = _mapping_property("storage_temperature_max")
    cycle_life = _mapping_property("cycle_life")

    @classmethod
    def from_record(cls, record: Mapping[str, Any], *, cell_specification_id: str | None = None) -> Self:
        record = record_to_snake_aliases(record)
        product = record.get("cell_spec")
        if not isinstance(product, Mapping):
            raise ValueError("cell-spec record must contain a 'cell_spec' object.")
        provenance = record.get("provenance", {})
        if not isinstance(provenance, Mapping):
            provenance = {}
        manufacturer = product.get("manufacturer")
        manufacturer_name = manufacturer.get("name") if isinstance(manufacturer, Mapping) else manufacturer
        manufacturer_id = manufacturer.get("id") if isinstance(manufacturer, Mapping) else None
        notes = record.get("notes")
        if not isinstance(notes, list):
            notes = []
        raw_pt = product.get("product_type")
        product_type = CellProductType(raw_pt) if isinstance(raw_pt, str) and raw_pt in CellProductType._value2member_map_ else None
        return cls(
            schema_version=str(record.get("schema_version", "1.0.0")),
            id=str(product["id"]),
            name=str(product.get("name") or f"{manufacturer_name} {product.get('model')}"),
            manufacturer=str(manufacturer_name),
            manufacturer_id=manufacturer_id,
            model=str(product["model"]),
            format=str(product.get("cell_format", "unknown")),
            chemistry=str(product.get("chemistry", "unknown")),
            product_type=product_type,
            positive_electrode_basis=product.get("positive_electrode_basis"),
            negative_electrode_basis=product.get("negative_electrode_basis"),
            size_code=product.get("size_code"),
            iec_code=product.get("iec_code"),
            country_of_origin=product.get("country_of_origin"),
            rechargeable=product.get("rechargeable"),
            year=_year_value(product.get("year")),
            datasheet_revision=product.get("datasheet_revision"),
            positive_electrode_spec_id=record.get("positive_electrode_spec_id"),
            negative_electrode_spec_id=record.get("negative_electrode_spec_id"),
            electrolyte_spec_id=record.get("electrolyte_spec_id"),
            separator_spec_id=record.get("separator_spec_id"),
            housing_spec_id=record.get("housing_spec_id"),
            cell_specification_id=cell_specification_id,
            properties=dict(record.get("properties", {})) if isinstance(record.get("properties"), Mapping) else {},
            construction=copy.deepcopy(record.get("construction", {}))
            if isinstance(record.get("construction"), Mapping)
            else {},
            positive_electrode=copy.deepcopy(record.get("positive_electrode")),
            negative_electrode=copy.deepcopy(record.get("negative_electrode")),
            electrolyte=copy.deepcopy(record.get("electrolyte")),
            separator=copy.deepcopy(record.get("separator")),
            housing=copy.deepcopy(record.get("housing"))
            if record.get("housing") is not None
            else _housing_from_coin_hardware(record.get("coin_hardware")),
            specification_comment=[str(item) for item in record.get("specification_comment", [])]
            if isinstance(record.get("specification_comment"), list)
            else [],
            bibliography=dict(record.get("bibliography", {}))
            if isinstance(record.get("bibliography"), Mapping)
            else {},
            source=_provenance_from_record(provenance),
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
            product_type=specification.product_type,
            positive_electrode_basis=specification.positive_electrode_basis,
            negative_electrode_basis=specification.negative_electrode_basis,
            size_code=specification.size_code,
            cell_specification_id=specification.id,
            properties=dict(specification.properties),
            source=ProvenanceInfo(
                type=specification.source.type,
                file=specification.source.file,
                url=specification.source.url,
                citation=_citation_url_value(specification.source.citation),
                retrieved_at=specification.source.retrieved_at,
            ),
            comment=["Generated from the linked CellSpecification."],
        )

    # ── Draft vs. publish-ready ──────────────────────────────────────────────────
    # The model is deliberately tolerant to construct — importers build it from arbitrary external
    # data, and a GUI/notebook fills it in incrementally, so a half-filled spec is a valid *draft*.
    # Publish-readiness — the strictness the former input DTOs enforced at construction time — is a
    # policy applied here, at finalize(), NOT baked into the field types. One model therefore serves
    # both interactive drafting and strict publishing.
    _REQUIRED_FOR_PUBLISH: ClassVar[tuple[tuple[str, str], ...]] = (
        ("id", "id (mint one via publish() or build_publication_package())"),
        ("name", "name"),
        ("manufacturer", "manufacturer"),
        ("model", "model"),
        ("format", "format"),
        ("chemistry", "chemistry"),
    )

    def publish_readiness_problems(self) -> list[str]:
        """The reasons this spec is not yet publish-ready (empty list == ready).

        A field counts as unset if it is None, blank, or the ``"unknown"`` placeholder that tolerant
        construction leaves on ``format``/``chemistry``."""
        problems: list[str] = []
        for field, label in self._REQUIRED_FOR_PUBLISH:
            value = getattr(self, field)
            if value is None or (isinstance(value, str) and value.strip() in {"", "unknown"}):
                problems.append(label)
        return problems

    def is_publishable(self) -> bool:
        """True when every field required to publish is set (never raises — for a GUI/CLI check)."""
        return not self.publish_readiness_problems()

    def finalize(self) -> "CellSpecification":
        """Assert publish-readiness and return self, so ``spec.finalize().to_record()`` reads cleanly.

        Raises listing every still-missing field at once. A draft is valid to hold and to persist via
        ``model_dump``; ``finalize()`` is the gate it must pass to become a published record."""
        problems = self.publish_readiness_problems()
        if problems:
            raise ValueError("CellSpecification is not publish-ready; set: " + ", ".join(problems))
        return self

    def to_record(self) -> dict[str, Any]:
        if self.id is None:
            raise ValueError(
                "CellSpecification has no id yet (it is still a draft). Mint one via publish() or "
                "build_publication_package(); call finalize() to check everything needed to publish."
            )
        if self.name is None:
            raise ValueError("CellSpecification.name is required before serialization.")
        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "cell_spec": {
                "id": self.id,
                "short_id": _short_id(self.id),
                "identifier": _identifier("cell-spec", self.id),
                "name": self.name,
                "model": self.model,
                "manufacturer": {"type": "Organization", "name": self.manufacturer},
                "cell_format": self.format,
                "chemistry": self.chemistry,
            },
            "properties": self.properties,
            "provenance": {},
        }
        if self.product_type is not None:
            record["cell_spec"]["product_type"] = str(self.product_type)
        if self.positive_electrode_basis is not None:
            record["cell_spec"]["positive_electrode_basis"] = self.positive_electrode_basis
        if self.negative_electrode_basis is not None:
            record["cell_spec"]["negative_electrode_basis"] = self.negative_electrode_basis
        if self.size_code is not None:
            record["cell_spec"]["size_code"] = self.size_code
        if self.iec_code is not None:
            record["cell_spec"]["iec_code"] = self.iec_code
        if self.country_of_origin is not None:
            record["cell_spec"]["country_of_origin"] = self.country_of_origin
        if self.rechargeable is not None:
            record["cell_spec"]["rechargeable"] = self.rechargeable
        if self.year is not None:
            record["cell_spec"]["year"] = self.year
        if self.datasheet_revision is not None:
            record["cell_spec"]["datasheet_revision"] = self.datasheet_revision
        if self.manufacturer_id is not None:
            record["cell_spec"]["manufacturer"]["id"] = self.manufacturer_id
        for _ref in ("positive_electrode_spec_id", "negative_electrode_spec_id",
                     "electrolyte_spec_id", "separator_spec_id", "housing_spec_id"):
            _ref_value = getattr(self, _ref)
            if _ref_value is not None:
                record[_ref] = _ref_value  # top-level sibling of cell_spec, per the schema
        record["provenance"] = _provenance_record(self.source)
        if self.bibliography:
            record["bibliography"] = dict(self.bibliography)
        if self.comment:
            record["notes"] = list(self.comment)
        # Datasheet structure lives at the top level of the canonical record (the schema already
        # defines these siblings of `cell_spec`). Emitting it here makes to_record()/from_record()
        # lossless — previously the whole electrode/electrolyte/separator/housing datasheet was
        # silently dropped on save (the "electrode-drop" data-loss bug).
        if self.construction:
            record["construction"] = copy.deepcopy(self.construction)
        if self.positive_electrode is not None:
            record["positive_electrode"] = self.positive_electrode.model_dump(mode="json", exclude_none=True)
        if self.negative_electrode is not None:
            record["negative_electrode"] = self.negative_electrode.model_dump(mode="json", exclude_none=True)
        if self.electrolyte is not None:
            record["electrolyte"] = self.electrolyte.model_dump(mode="json", exclude_none=True)
        if self.separator is not None:
            record["separator"] = self.separator.model_dump(mode="json", exclude_none=True)
        if self.housing is not None:
            record["housing"] = self.housing.model_dump(mode="json", exclude_none=True)
        if self.specification_comment:
            record["specification_comment"] = list(self.specification_comment)
        return record_to_snake_aliases(record)

    # ── Datasheet "library" record format (merged from the former CellSpecification) ──
    @classmethod
    def from_path(cls, path: PathLike) -> Self:
        payload = _read_json(_as_path(path))
        if isinstance(payload.get("specification"), Mapping):
            return cls.from_library_record(payload)
        if isinstance(payload.get("cell_spec"), Mapping):
            return cls.from_record(payload)
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
        raw_pt = specification.get("product_type")
        product_type = CellProductType(raw_pt) if isinstance(raw_pt, str) and raw_pt in CellProductType._value2member_map_ else None
        return cls(
            schema_version=str(record.get("schema_version", "1.0.0")),
            id=str(specification["id"]),
            manufacturer=str(specification["manufacturer"]),
            model=str(specification["model"]),
            format=str(specification["format"]),
            chemistry=str(specification["chemistry"]),
            product_type=product_type,
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
            housing=copy.deepcopy(specification.get("housing"))
            if specification.get("housing") is not None
            else _housing_from_coin_hardware(specification.get("coin_hardware")),
            specification_comment=[str(item) for item in specification_comment],
            source=_provenance_from_record(provenance),
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
        if self.product_type is not None:
            specification["product_type"] = str(self.product_type)
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
        if self.housing is not None:
            specification["housing"] = self.housing.model_dump(mode="json", exclude_none=True)
        if self.specification_comment:
            specification["comment"] = list(self.specification_comment)

        provenance = _provenance_record(self.source)

        out = {
            "schema_version": self.schema_version,
            "specification": specification,
            "provenance": provenance,
        }
        if self.comment:
            out["comment"] = list(self.comment)
        return out



class CellInstance(BundleJsonModel):
    default_filename: ClassVar[str] = CELL_INSTANCE_FILENAME

    kind: str = "CellInstance"
    id: str | None = None
    # Transient short id used only to mint the canonical IRI when no id is given; never serialized.
    uid: str | None = Field(default=None, exclude=True, repr=False)
    name: str | None = None
    cell_spec_id: str | None = None
    cell_spec: CellSpecification | None = Field(default=None, exclude=True, repr=False)
    serial_number: str | None = None
    batch_id: str | None = None
    grade: str | None = None
    manufactured_at: int | str | None = None
    expires_at: int | str | None = None
    measured: dict[str, Any] = Field(default_factory=dict)
    conformance: Conformance | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)

    def __init__(self, cell_spec: CellSpecification | None = None, /, **data: Any) -> None:
        # Absorb the flat authoring/input shape (formerly CellInstanceInput).
        if "notes" in data and "comment" not in data:
            data["comment"] = data.pop("notes")
        _dataset_id = data.pop("dataset_id", None)
        if _dataset_id is not None:
            data["dataset_ids"] = list(dict.fromkeys([*(data.get("dataset_ids") or []), _dataset_id]))
        _flat_provenance = {
            "source_type": "type", "source_name": "name", "source_file": "file", "source_url": "url",
            "citation": "citation", "file_hash": "file_hash", "retrieved_at": "retrieved_at",
            "workflow_version": "workflow_version", "curated_by": "curated_by",
        }
        if any(key in data for key in _flat_provenance) and "source" not in data:
            data["source"] = {nested: data.pop(flat) for flat, nested in _flat_provenance.items() if flat in data}
        if cell_spec is not None:
            if "cell_spec" in data and data["cell_spec"] is not cell_spec:
                raise ValueError(
                    "Pass the cell spec either positionally or as cell_spec=, not both."
                )
            # A positional object used to be silently DISCARDED when cell_spec_id= was
            # also given. Keep the object, but refuse a demonstrable identity conflict.
            _kwarg_id = data.get("cell_spec_id")
            if _kwarg_id is not None and cell_spec.id is not None and _kwarg_id != cell_spec.id:
                raise ValueError(
                    f"Conflicting cell spec references: the positional object has "
                    f"id {cell_spec.id!r} but cell_spec_id={_kwarg_id!r} was also given. "
                    "Pass one or the other."
                )
            data["cell_spec"] = cell_spec
        _reject_unknown_kwargs(
            type(self), data, extra_allowed=("notes", "dataset_id", *_FLAT_PROVENANCE_KEYS)
        )
        super().__init__(**data)

    @model_validator(mode="after")
    def _populate_links(self) -> Self:
        if self.cell_spec_id is None and self.cell_spec is not None and self.cell_spec.id is not None:
            self.cell_spec_id = self.cell_spec.id
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
            name=str(
                cell_instance.get("name")
                or cell_instance.get("serial_number")
                or cell_instance["id"].rstrip("/").split("/")[-1]
            ),
            cell_spec_id=str(cell_instance["cell_spec_id"]),
            serial_number=cell_instance.get("serial_number"),
            batch_id=cell_instance.get("batch_id"),
            grade=cell_instance.get("grade"),
            manufactured_at=cell_instance.get("manufactured_at"),
            expires_at=cell_instance.get("expires_at"),
            measured=dict(record.get("measured", {})) if isinstance(record.get("measured"), Mapping) else {},
            conformance=(
                Conformance.from_record(cell_instance["conformance"])
                if isinstance(cell_instance.get("conformance"), Mapping)
                else None
            ),
            dataset_ids=[str(item) for item in dataset_ids],
            source=_provenance_from_record(provenance),
            comment=[str(item) for item in notes],
        )

    def to_record(self) -> dict[str, Any]:
        if self.id is None:
            raise ValueError("CellInstance.id is required before serialization. Use battinfo.build_publication_package(...) or battinfo.publish(...) to finalize IDs.")
        if self.cell_spec_id is None:
            raise ValueError("CellInstance.cell_spec_id is required before serialization.")
        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "cell_instance": {
                "id": self.id,
                "short_id": _short_id(self.id),
                "cell_spec_id": self.cell_spec_id,
                "name": self.name,
                "serial_number": self.serial_number,
                "batch_id": self.batch_id,
                "grade": self.grade,
                "manufactured_at": self.manufactured_at,
                "expires_at": self.expires_at,
            },
            "provenance": {},
        }
        if self.measured:
            record["measured"] = self.measured
        if self.dataset_ids:
            record["datasets"] = [{"id": dataset_id, "role": "raw"} for dataset_id in self.dataset_ids]
        record["provenance"] = _provenance_record(self.source)
        record["cell_instance"] = {key: value for key, value in record["cell_instance"].items() if value is not None}
        if self.conformance is not None:
            record["cell_instance"]["conformance"] = self.conformance.to_record()
        if self.comment:
            record["notes"] = list(self.comment)
        return record_to_snake_aliases(record)


CONFORMANCE_STATUS_VALUES = ("conformant", "non-conformant", "unknown")

# Conformance is a boolean verdict mapped to W3C EARL outcome values. "unknown"
# is the not-yet-assessed default (EARL's cantTell), not a third verdict. Compact
# CURIEs — the 'earl' prefix is declared in records.context.json.
CONFORMANCE_STATUS_IRI: dict[str, str] = {
    "conformant":     "earl:passed",
    "non-conformant": "earl:failed",
    "unknown":        "earl:cantTell",
}

# Controlled vocabulary for a deviation's broad category. Covers both test executions
# (vs a test spec) and physical cells (vs a cell spec). A free-text `type` carries the
# specific label within a category.
DEVIATION_CATEGORIES = (
    "power_outage",
    "equipment_failure",
    "temperature_excursion",
    "software_error",
    "operator_intervention",
    "premature_termination",
    "communication_loss",
    "parameter_drift",
    "setpoint_deviation",
    "calibration_issue",
    "out_of_tolerance",
    "dimensional",
    "other",
)


class Deviation(BaseModel):
    """A single way a thing departed from the spec that governs it.

    ``category`` is a controlled classification (see DEVIATION_CATEGORIES); ``type`` is
    an optional free-text label naming the specific deviation within that category.
    """

    category: str = "other"
    type: str | None = None
    description: str | None = None
    occurred_at: int | None = None
    duration_s: int | None = None
    step_index: int | None = None
    impact: str | None = None

    @classmethod
    def from_record(cls, data: Mapping[str, Any]) -> "Deviation":
        category = data.get("category")
        type_ = data.get("type")
        # Back-compat: a legacy `type` that names a known category becomes the category.
        if category is None and type_ in DEVIATION_CATEGORIES:
            category, type_ = type_, None
        return cls(
            category=str(category or "other"),
            type=type_,
            description=data.get("description"),
            occurred_at=data.get("occurred_at"),
            duration_s=data.get("duration_s"),
            step_index=data.get("step_index"),
            impact=data.get("impact"),
        )

    def to_record(self) -> dict[str, Any]:
        out: dict[str, Any] = {"category": self.category}
        if self.type is not None:
            out["type"] = self.type
        if self.description is not None:
            out["description"] = self.description
        if self.occurred_at is not None:
            out["occurred_at"] = self.occurred_at
        if self.duration_s is not None:
            out["duration_s"] = self.duration_s
        if self.step_index is not None:
            out["step_index"] = self.step_index
        if self.impact is not None:
            out["impact"] = self.impact
        return out


class Conformance(BaseModel):
    """Assessment of how well a thing followed the spec that governs it.

    Used for a test execution (vs its test spec) and a cell instance (vs its cell spec).
    """

    status: str = "unknown"
    note: str | None = None
    deviations: list[Deviation] = Field(default_factory=list)

    @classmethod
    def from_record(cls, data: Mapping[str, Any]) -> "Conformance":
        deviations = [
            Deviation.from_record(d)
            for d in (data.get("deviations") or [])
            if isinstance(d, Mapping)
        ]
        return cls(
            status=str(data.get("status", "unknown")),
            note=data.get("note"),
            deviations=deviations,
        )

    def to_record(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.note is not None:
            out["note"] = self.note
        if self.deviations:
            out["deviations"] = [d.to_record() for d in self.deviations]
        return out


# Backward-compatible alias — conformance is general, not test-specific.
TestConformance = Conformance


def _prune_empty(obj: Any) -> Any:
    """Recursively drop None and empty list/dict/str values (keeps 0 and False)."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            pruned = _prune_empty(value)
            if pruned is None or pruned == [] or pruned == {} or pruned == "":
                continue
            out[key] = pruned
        return out
    if isinstance(obj, list):
        return [_prune_empty(item) for item in obj]
    return obj


class Artifact(BaseModel):
    """A link to a machine-actionable protocol file (Layer B).

    BattINFO carries and references the file but does not interpret it as
    authority; ``conforms_to`` points downstream tooling at the format spec."""
    model_config = ConfigDict(extra="forbid")

    role: str                              # source_protocol | executed_protocol | vendor_export | simulation_input | other
    format: str                            # key in data/vocab/test-method/artifact-formats.json
    locator: str                           # dataset-relative path | URI | DOI
    media_type: str | None = None
    sha256: str | None = None
    byte_size: int | None = None
    conforms_to: str | None = None
    generated: list[str] = Field(default_factory=list)
    generated_from: str | None = None

    @classmethod
    def from_record(cls, data: Mapping[str, Any]) -> "Artifact":
        return cls.model_validate(dict(data))

    def to_record(self) -> dict[str, Any]:
        return _prune_empty(self.model_dump(mode="json"))


class TestSpec(BundleJsonModel):
    default_filename: ClassVar[str] = TEST_SPEC_FILENAME

    kind: str = "TestSpec"
    __test__ = False
    id: str | None = None
    # Transient short id used only to mint the canonical IRI when no id is given; never serialized.
    uid: str | None = Field(default=None, exclude=True, repr=False)
    name: str | None = None
    test_type: BatteryTestType = Field(
        default=BatteryTestType.OTHER,
        validation_alias=AliasChoices("test_type", "test_kind", "kind"),
    )
    description: str | None = None
    version: str | None = None
    protocol: ProtocolInfo = Field(default_factory=ProtocolInfo)
    # Descriptive layer (canonical structured form of the procedure).
    method: list[Step] = Field(default_factory=list)
    record: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Quantity] = Field(default_factory=dict)
    # Actionable layer.
    artifacts: list[Artifact] = Field(default_factory=list)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)

    def __init__(self, /, **data: Any) -> None:
        # Absorb the flat authoring/input shape (formerly TestSpecInput). The discriminator
        # field `kind` and test_type both alias "kind"; route it to test_type explicitly so
        # the discriminator keeps its default. protocol_url/experiment/steps/cycles are
        # authoring conveniences (experiment/steps/cycles are handled by _coerce_authoring).
        if "kind" in data and "test_type" not in data:
            data["test_type"] = data.pop("kind")
        if "protocol_url" in data and "protocol" not in data:
            data["protocol"] = {"url": data.pop("protocol_url")}
        if "notes" in data and "comment" not in data:
            data["comment"] = data.pop("notes")
        _flat_provenance = {
            "source_type": "type", "source_name": "name", "source_file": "file", "source_url": "url",
            "citation": "citation", "file_hash": "file_hash", "retrieved_at": "retrieved_at",
            "workflow_version": "workflow_version", "curated_by": "curated_by",
        }
        if any(key in data for key in _flat_provenance) and "source" not in data:
            data["source"] = {nested: data.pop(flat) for flat, nested in _flat_provenance.items() if flat in data}
        _reject_unknown_kwargs(
            type(self), data,
            extra_allowed=("kind", "protocol_url", "notes", "experiment", "steps", "cycles",
                           *_FLAT_PROVENANCE_KEYS),
        )
        super().__init__(**data)

    @model_validator(mode="before")
    @classmethod
    def _coerce_authoring(cls, data: Any) -> Any:
        """Accept PyBaMM-style ``experiment``/``steps`` strings (+ ``cycles``) as the
        human authoring interface, parsing them into the canonical ``method``."""
        if not isinstance(data, Mapping):
            return data
        out = dict(data)
        if not out.get("method"):
            source = out.get("experiment")
            if source is None:
                source = out.get("steps")
            if source and all(isinstance(s, str) for s in source):
                cycles = out.get("cycles")
                out["method"] = parse_experiment(
                    list(source), cycles if isinstance(cycles, int) else None
                )
        # Authoring-only keys are not model fields (extra="forbid").
        for key in ("experiment", "steps", "cycles"):
            out.pop(key, None)
        return out

    @field_validator("protocol", mode="before")
    @classmethod
    def _coerce_protocol(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value}
        return value

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
    def experiment(self) -> list[str]:
        """The method rendered back to PyBaMM-style strings (display / round-trip)."""
        from battinfo.testmethod import render_method
        strings, _cycles = render_method(self.method)
        return strings

    def facets(self) -> dict[str, Any]:
        """Derived rollup index of the method for cheap filtering."""
        return compute_facets(self.method, self.conditions)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Self:
        protocol = record.get("test_spec")
        if not isinstance(protocol, Mapping):
            raise ValueError("test-protocol record must contain a 'test_spec' object.")
        provenance = record.get("provenance", {})
        if not isinstance(provenance, Mapping):
            provenance = {}
        notes = record.get("notes")
        if not isinstance(notes, list):
            notes = []
        method = record.get("method")
        if not isinstance(method, list):
            method = []
        conditions = record.get("conditions")
        if not isinstance(conditions, Mapping):
            conditions = {}
        record_settings = record.get("record")
        safety = record.get("safety")
        artifacts = record.get("artifacts")
        if not isinstance(artifacts, list):
            artifacts = []
        return cls(
            schema_version=str(record.get("schema_version", "1.0.0")),
            id=str(protocol["id"]),
            name=str(protocol["name"]),
            test_type=protocol["kind"],
            description=protocol.get("description"),
            version=protocol.get("version"),
            protocol=ProtocolInfo(url=protocol.get("protocol_url")),
            method=[Step.model_validate(s) for s in method if isinstance(s, Mapping)],
            record=dict(record_settings) if isinstance(record_settings, Mapping) else {},
            safety=dict(safety) if isinstance(safety, Mapping) else {},
            conditions=dict(conditions),
            artifacts=[Artifact.from_record(a) for a in artifacts if isinstance(a, Mapping)],
            source=_provenance_from_record(provenance),
            comment=[str(item) for item in notes],
        )

    def to_record(self) -> dict[str, Any]:
        if self.id is None:
            raise ValueError("TestSpec.id is required before serialization.")
        if self.name is None:
            raise ValueError("TestSpec.name is required before serialization.")
        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "test_spec": {
                "id": self.id,
                "short_id": _short_id(self.id),
                "identifier": _identifier("test-protocol", self.id),
                "name": self.name,
                "kind": self.test_type,
            },
            "provenance": {},
        }
        if self.description is not None:
            record["test_spec"]["description"] = self.description
        if self.version is not None:
            record["test_spec"]["version"] = self.version
        if self.protocol.url is not None:
            record["test_spec"]["protocol_url"] = self.protocol.url
        if self.method:
            record["method"] = [_prune_empty(s.model_dump(mode="json")) for s in self.method]
            record["facets"] = self.facets()
        if self.record:
            record["record"] = copy.deepcopy(self.record)
        if self.safety:
            record["safety"] = copy.deepcopy(self.safety)
        if self.conditions:
            record["conditions"] = {
                name: qty.model_dump(mode="json") for name, qty in self.conditions.items()
            }
        if self.artifacts:
            record["artifacts"] = [a.to_record() for a in self.artifacts]
        record["provenance"] = _provenance_record(self.source)
        if self.comment:
            record["notes"] = list(self.comment)
        return record


class Test(BundleJsonModel):
    default_filename: ClassVar[str] = TEST_FILENAME

    kind: str = "Test"
    __test__ = False
    id: str | None = None
    # Transient short id used only to mint the canonical IRI when no id is given; never serialized.
    uid: str | None = Field(default=None, exclude=True, repr=False)
    name: str | None = None
    test_type: BatteryTestType = Field(
        default=BatteryTestType.OTHER,
        validation_alias=AliasChoices("test_type", "test_kind", "kind"),
    )
    protocol_id: str | None = None
    protocol_entity: TestSpec | None = Field(default=None, exclude=True, repr=False)
    cell_instance_id: str | None = None
    cell: CellInstance | None = Field(default=None, exclude=True, repr=False)
    description: str | None = None
    status: str | None = None
    protocol: ProtocolInfo = Field(default_factory=ProtocolInfo)
    instrument: str | None = None
    started_at: int | str | None = None
    ended_at: int | str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    conformance: TestConformance | None = None
    artifacts: list[Artifact] = Field(default_factory=list)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)

    def __init__(self, cell: CellInstance | None = None, /, **data: Any) -> None:
        # Absorb the flat authoring/input shape (formerly TestInput).
        if "cell_id" in data and "cell_instance_id" not in data:
            data["cell_instance_id"] = data.pop("cell_id")
        if "kind" in data and "test_type" not in data:
            data["test_type"] = data.pop("kind")
        if "instrument_name" in data and "instrument" not in data:
            data["instrument"] = data.pop("instrument_name")
        _protocol_name = data.pop("protocol_name", None)
        _protocol_url = data.pop("protocol_url", None)
        if (_protocol_name is not None or _protocol_url is not None) and "protocol" not in data:
            data["protocol"] = {"name": _protocol_name, "url": _protocol_url}
        if "notes" in data and "comment" not in data:
            data["comment"] = data.pop("notes")
        _flat_provenance = {
            "source_type": "type", "source_name": "name", "source_file": "file", "source_url": "url",
            "citation": "citation", "file_hash": "file_hash", "retrieved_at": "retrieved_at",
            "workflow_version": "workflow_version", "curated_by": "curated_by",
        }
        if any(key in data for key in _flat_provenance) and "source" not in data:
            data["source"] = {nested: data.pop(flat) for flat, nested in _flat_provenance.items() if flat in data}
        if cell is not None:
            if "cell" in data and data["cell"] is not cell:
                raise ValueError("Pass the cell either positionally or as cell=, not both.")
            # A positional object used to be silently DISCARDED when cell_id=/
            # cell_instance_id= was also given. Keep the object, but refuse a
            # demonstrable identity conflict.
            _kwarg_id = data.get("cell_instance_id")
            if _kwarg_id is not None and cell.id is not None and _kwarg_id != cell.id:
                raise ValueError(
                    f"Conflicting cell references: the positional object has id {cell.id!r} "
                    f"but cell_id={_kwarg_id!r} was also given. Pass one or the other."
                )
            data["cell"] = cell
        _reject_unknown_kwargs(
            type(self), data,
            extra_allowed=("cell_id", "kind", "instrument_name", "protocol_name",
                           "protocol_url", "notes", *_FLAT_PROVENANCE_KEYS),
        )
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
        raw_conformance = test.get("conformance")
        conformance = (
            TestConformance.from_record(raw_conformance)
            if isinstance(raw_conformance, Mapping)
            else None
        )
        artifacts = record.get("artifacts")
        if not isinstance(artifacts, list):
            artifacts = []
        return cls(
            schema_version=str(record.get("schema_version", "1.0.0")),
            id=str(test["id"]),
            name=str(test["name"]),
            test_type=test["kind"],
            protocol_id=test.get("protocol_id"),
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
            conformance=conformance,
            artifacts=[Artifact.from_record(a) for a in artifacts if isinstance(a, Mapping)],
            source=_provenance_from_record(provenance),
            comment=[str(item) for item in notes],
        )

    def to_record(self) -> dict[str, Any]:
        if self.id is None:
            raise ValueError("Test.id is required before serialization. Use battinfo.build_publication_package(...) or battinfo.publish(...) to finalize IDs.")
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
        if self.protocol_id is not None:
            record["test"]["protocol_id"] = self.protocol_id
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
        if self.conformance is not None:
            record["test"]["conformance"] = self.conformance.to_record()
        if self.artifacts:
            record["artifacts"] = [a.to_record() for a in self.artifacts]
        record["provenance"] = _provenance_record(self.source)
        if self.comment:
            record["notes"] = list(self.comment)
        return record


class Dataset(BundleJsonModel):
    default_filename: ClassVar[str] = DATASET_FILENAME

    kind: str = "Dataset"
    id: str | None = None
    # Transient short id used only to mint the canonical IRI when no id is given; never serialized.
    uid: str | None = Field(default=None, exclude=True, repr=False)
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
    related_cell_ids: list[str] = Field(default_factory=list)
    related_test_ids: list[str] = Field(default_factory=list)
    test: Test | None = Field(default=None, exclude=True, repr=False)
    cell: CellInstance | None = Field(default=None, exclude=True, repr=False)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)

    def __init__(self, path: str | Path | None = None, /, **data: Any) -> None:
        if path is not None and "dataset_path" not in data and "path" not in data:
            data["path"] = str(path)
        # Absorb the flat authoring/input shape (formerly DatasetInput).
        if "title" in data and "name" not in data:
            data["name"] = data.pop("title")
        if "format" in data and "data_format" not in data:
            data["data_format"] = data.pop("format")
        if "citation_list" in data and "citations" not in data:
            data["citations"] = data.pop("citation_list")
        _ck_alg = data.pop("checksum_algorithm", None)
        _ck_val = data.pop("checksum_value", None)
        if (_ck_alg is not None or _ck_val is not None) and "checksum" not in data:
            data["checksum"] = {"algorithm": _ck_alg, "value": _ck_val}
        if "notes" in data and "comment" not in data:
            data["comment"] = data.pop("notes")
        # The dataset citations list aliases "citation"; a flat *string* ``citation`` is the
        # provenance citation (matching the retired DatasetInput, where ``citation: str`` was
        # provenance and the bibliography arrived as a list). Pop it before the alias can
        # capture it — even when an explicit ``source`` is also given, in which case it merges
        # into that source (an already-set source.citation wins).
        _prov_citation = data.pop("citation") if isinstance(data.get("citation"), str) else None
        _flat_provenance = {
            "source_type": "type", "source_name": "name", "source_file": "file",
            "source_url": "url", "file_hash": "file_hash",
            "retrieved_at": "retrieved_at", "workflow_version": "workflow_version",
            "curated_by": "curated_by",
        }
        if any(key in data for key in _flat_provenance) and "source" not in data:
            data["source"] = {nested: data.pop(flat) for flat, nested in _flat_provenance.items() if flat in data}
        if _prov_citation is not None:
            source = data.get("source")
            if source is None:
                data["source"] = {"citation": _prov_citation}
            elif isinstance(source, Mapping):
                merged = dict(source)
                merged.setdefault("citation", _prov_citation)
                data["source"] = merged
            elif isinstance(source, ProvenanceInfo) and source.citation is None:
                data["source"] = source.model_copy(update={"citation": _prov_citation})
        _reject_unknown_kwargs(
            type(self), data,
            extra_allowed=("title", "format", "citation_list", "checksum_algorithm",
                           "checksum_value", "notes", "citation", "path", *_FLAT_PROVENANCE_KEYS),
        )
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
        record = record_to_snake_aliases(record)
        dataset = record.get("dataset")
        if not isinstance(dataset, Mapping):
            raise ValueError("dataset record must contain a 'dataset' object.")
        provenance = record.get("provenance", {})
        if not isinstance(provenance, Mapping):
            provenance = {}
        about = dataset.get("about")
        # to_record() emits the primary cell/test reference first (see there), so the
        # first id of each kind is the primary and the rest are related — reading the
        # FULL list back makes to_record→from_record→to_record a fixed point instead
        # of silently dropping every reference after the first.
        related_cell_id = None
        related_test_id = None
        related_cell_ids: list[str] = []
        related_test_ids: list[str] = []
        if isinstance(about, list):
            for item in about:
                if not isinstance(item, str):
                    continue
                if "/cell/" in item:
                    if related_cell_id is None:
                        related_cell_id = item
                    elif item not in related_cell_ids:
                        related_cell_ids.append(item)
                elif "/test/" in item:
                    if related_test_id is None:
                        related_test_id = item
                    elif item not in related_test_ids:
                        related_test_ids.append(item)
        distribution = dataset.get("distributions")
        checksum = ChecksumInfo()
        data_format = None
        download_url = None
        if isinstance(distribution, list) and distribution and isinstance(distribution[0], Mapping):
            first = distribution[0]
            data_format = first.get("encoding_format")
            download_url = first.get("content_url")
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
            same_as=_string_list(dataset.get("same_as")),
            additional_type=_string_list(dataset.get("additional_type")),
            version=dataset.get("version"),
            keywords=_string_list(dataset.get("keywords")),
            creators=_mapping_list(dataset.get("creators")),
            publisher=_canonical_agent(dataset.get("publisher")),
            funders=_mapping_list(dataset.get("funders")),
            citations=[citation for item in (dataset.get("citations") if isinstance(dataset.get("citations"), list) else [dataset.get("citations")] if dataset.get("citations") is not None else []) if (citation := _canonical_citation(item)) is not None],
            measurement_techniques=_string_list(dataset.get("measurement_techniques")),
            measurement_methods=_string_list(dataset.get("measurement_methods")),
            variable_measured=[variable for item in _mapping_list(dataset.get("variable_measured")) if (variable := _canonical_variable_measured(item)) is not None],
            is_accessible_for_free=dataset.get("is_accessible_for_free") if isinstance(dataset.get("is_accessible_for_free"), bool) else None,
            conditions_of_access=dataset.get("conditions_of_access"),
            in_language=dataset.get("in_language"),
            data_format=data_format,
            dataset_path=dataset_path,
            access_url=dataset.get("access_url"),
            download_url=download_url,
            created_at=dataset.get("created_at"),
            modified_at=dataset.get("modified_at"),
            published_at=dataset.get("published_at"),
            temporal_coverage=dataset.get("temporal_coverage"),
            spatial_coverage=dataset.get("spatial_coverage"),
            is_based_on=_string_list(dataset.get("is_based_on")),
            included_in_data_catalog=_canonical_data_catalog(dataset.get("included_in_data_catalog")),
            main_entity=[entity for item in _mapping_list(dataset.get("main_entity")) if (entity := _canonical_main_entity(item)) is not None],
            distributions=[dist for item in _mapping_list(distribution) if (dist := _canonical_distribution(item)) is not None],
            checksum=checksum,
            cell_instance_id=related_cell_id,
            test_id=related_test_id,
            related_cell_ids=related_cell_ids,
            related_test_ids=related_test_ids,
            source=_provenance_from_record(provenance),
            comment=[str(item) for item in notes],
        )

    def to_record(self) -> dict[str, Any]:
        if self.id is None:
            raise ValueError("Dataset.id is required before serialization. Use battinfo.build_publication_package(...) or battinfo.publish(...) to finalize IDs.")
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
            dataset_obj["same_as"] = list(self.same_as)
        if self.additional_type:
            dataset_obj["additional_type"] = list(self.additional_type)
        if self.version is not None:
            dataset_obj["version"] = self.version
        if self.keywords:
            dataset_obj["keywords"] = list(self.keywords)
        if self.creators:
            dataset_obj["creators"] = copy.deepcopy(self.creators)
        if self.publisher is not None:
            dataset_obj["publisher"] = copy.deepcopy(self.publisher)
        if self.funders:
            dataset_obj["funders"] = copy.deepcopy(self.funders)
        if self.citations:
            dataset_obj["citations"] = copy.deepcopy(self.citations)
        if self.measurement_techniques:
            dataset_obj["measurement_techniques"] = list(self.measurement_techniques)
        if self.measurement_methods:
            dataset_obj["measurement_methods"] = list(self.measurement_methods)
        if self.variable_measured:
            dataset_obj["variable_measured"] = copy.deepcopy(self.variable_measured)
        if self.is_accessible_for_free is not None:
            dataset_obj["is_accessible_for_free"] = self.is_accessible_for_free
        if self.conditions_of_access is not None:
            dataset_obj["conditions_of_access"] = self.conditions_of_access
        if self.in_language is not None:
            dataset_obj["in_language"] = self.in_language
        # access_url is required by the dataset schema (dcat:accessURL). Falling back to a
        # fabricated placeholder URL would publish fake data — fail with the fix instead.
        access_url = self.access_url or self.source.url
        if access_url is None:
            raise ValueError(
                "Dataset.access_url is required to serialize a dataset record: set "
                "access_url= to the landing page or download URL where the data lives "
                "(a provenance source_url also satisfies it; workspace and publication "
                "flows derive it from the dataset path automatically)."
            )
        dataset_obj["access_url"] = access_url
        if self.created_at is not None:
            dataset_obj["created_at"] = self.created_at
        if self.modified_at is not None:
            dataset_obj["modified_at"] = self.modified_at
        elif self.created_at is not None:
            dataset_obj["modified_at"] = self.created_at
        if self.published_at is not None:
            dataset_obj["published_at"] = self.published_at
        elif self.created_at is not None:
            dataset_obj["published_at"] = self.created_at
        if self.temporal_coverage is not None:
            dataset_obj["temporal_coverage"] = self.temporal_coverage
        if self.spatial_coverage is not None:
            dataset_obj["spatial_coverage"] = self.spatial_coverage
        # Primary references come FIRST so from_record() can recover the primary/related
        # split from the flat `about` list (first cell id = primary, rest = related).
        about = list(dict.fromkeys([
            *([self.cell_instance_id] if self.cell_instance_id is not None else []),
            *self.related_cell_ids,
            *([self.test_id] if self.test_id is not None else []),
            *self.related_test_ids,
        ]))
        if about:
            dataset_obj["about"] = about
        if self.is_based_on:
            dataset_obj["is_based_on"] = list(self.is_based_on)
        if self.included_in_data_catalog is not None:
            dataset_obj["included_in_data_catalog"] = self.included_in_data_catalog
        if self.main_entity:
            dataset_obj["main_entity"] = copy.deepcopy(self.main_entity)
        if self.distributions:
            dataset_obj["distributions"] = copy.deepcopy(self.distributions)
        elif self.download_url is not None or self.data_format is not None or self.checksum.value is not None:
            dist: dict[str, Any] = {
                "type": "DataDownload",
                # Non-None: the access_url check above already required one of these.
                "content_url": self.download_url or self.access_url or self.source.url,
                "encoding_format": self.data_format or "application/octet-stream",
            }
            if self.checksum.value is not None:
                dist["checksum"] = {
                    "algorithm": self.checksum.algorithm,
                    "value": self.checksum.value,
                }
            dataset_obj["distributions"] = [dist]

        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "dataset": dataset_obj,
            "provenance": {},
        }
        record["provenance"] = _provenance_record(self.source)
        if self.comment:
            record["notes"] = list(self.comment)
        return record_to_snake_aliases(record)


class BattinfoBundle(BundleJsonModel):
    default_filename: ClassVar[str] = BUNDLE_MANIFEST_FILENAME

    kind: str = "BattinfoBundle"
    bundle_name: str | None = None
    cell_specification: CellSpecification | None = None
    cell_spec: CellSpecification
    cell_instance: CellInstance
    test: Test
    dataset: Dataset
    comment: list[str] = Field(default_factory=list)

    def manifest_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "cell_spec_file": CELL_SPEC_FILENAME,
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
        self.cell_spec.to_path(root / CELL_SPEC_FILENAME)
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
            cell_spec=CellSpecification.from_path(root / str(manifest.get("cell_spec_file", CELL_SPEC_FILENAME))),
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

        def _is_cell_instance(node: Mapping[str, Any]) -> bool:
            # Legacy shapes; or the gold-standard instance node, whose @type is the
            # physical subclass (e.g. CoinCell) but which always links to its spec via
            # hasDescription/conformsTo and lives under the /cell/ namespace.
            if _node_has_type(node, "BatteryCell") or _node_has_type(node, "schema:IndividualProduct"):
                return True
            nid = node.get("@id")
            return (
                isinstance(nid, str) and "/cell/" in nid
                and bool(node.get("hasDescription") or node.get("dcterms:conformsTo"))
            )

        cell_instance_node = next(
            (node for node in graph if _is_cell_instance(node)),
            None,
        )
        cell_spec_id = None
        if cell_instance_node is not None:
            cell_spec_id = next((value for value in _type_values(cell_instance_node) if "/cell-spec/" in value), None)
            if cell_spec_id is None:
                # hasDescription is the current term; schema:isVariantOf is kept for backward compatibility
                cell_spec_id = _ref_id(cell_instance_node.get("hasDescription") or cell_instance_node.get("schema:isVariantOf"))
        cell_spec_node = graph_by_id.get(cell_spec_id) if cell_spec_id is not None else None
        if cell_spec_node is None:
            cell_spec_node = next(
                (
                    node
                    for node in graph
                    if _node_has_type(node, OWL_CLASS_IRI)
                    or _node_has_type(node, "BatteryCellSpecification")
                ),
                None,
            )
        test_node = next(
            (
                node
                for node in graph
                if _node_has_type(node, "BatteryTest")
                or (
                    _node_has_type(node, "schema:Action")
                    and (_ref_id(node.get("hasTestObject")) or _ref_id(node.get("schema:object")))
                )
            ),
            None,
        )
        dataset_node = next(
            (
                node
                for node in graph
                # Never the catalog/container; match the member test-result dataset.
                if not _node_has_type(node, "dcat:Catalog")
                and (
                    _node_has_type(node, "BatteryTestResult")
                    # Gold-standard member: a dcat:Dataset carrying distributions.
                    or (
                        (_node_has_type(node, "dcat:Dataset") or _node_has_type(node, "schema:Dataset"))
                        and bool(node.get("dcat:distribution") or node.get("schema:distribution"))
                    )
                    # Legacy: a schema:Dataset whose about references both a cell and a test.
                    or (
                        _node_has_type(node, "schema:Dataset")
                        and any("/cell/" in ref_id for ref_id in _ref_ids(node.get("schema:about")))
                        and any("/test/" in ref_id for ref_id in _ref_ids(node.get("schema:about")))
                    )
                )
            ),
            None,
        )

        if cell_spec_node is None or cell_instance_node is None or test_node is None or dataset_node is None:
            raise ValueError("Could not reconstruct BattinfoBundle from JSON-LD graph.")

        _cell_spec_id = str(cell_spec_node.get("@id"))
        cell_specification_node = next(
            (
                node
                for node in graph
                if _node_has_type(node, "BatteryCellSpecification")
                and _ref_id(node.get("schema:about")) == _cell_spec_id
            ),
            None,
        )
        if cell_specification_node is None:
            spec_ref_id = _ref_id(cell_spec_node.get("schema:isBasedOn"))
            candidate = graph_by_id.get(spec_ref_id) if spec_ref_id is not None else None
            if isinstance(candidate, Mapping) and _node_has_type(candidate, "BatteryCellSpecification"):
                cell_specification_node = candidate
        if cell_specification_node is None and _node_has_type(cell_spec_node, "BatteryCellSpecification"):
            # The cell_spec node and the cell_specification node are the same entity — a
            # BatteryCellSpecification. When the graph carries a single spec node (the
            # gold-standard shape), it serves as both; there is no separate
            # "cell-spec-only" node to distinguish.
            cell_specification_node = cell_spec_node

        manufacturer_obj = cell_spec_node.get("schema:manufacturer")
        if not isinstance(manufacturer_obj, Mapping) and cell_specification_node is not None:
            manufacturer_obj = cell_specification_node.get("schema:manufacturer")
        manufacturer = (
            manufacturer_obj.get("schema:name")
            if isinstance(manufacturer_obj, Mapping)
            else manufacturer_obj
        )
        properties: dict[str, Any] = {}
        property_source = cell_specification_node if cell_specification_node is not None else cell_spec_node
        for item in property_source.get("hasProperty", []):
            if isinstance(item, Mapping):
                extracted = _extract_property_item(item)
                if extracted is not None:
                    key, value = extracted
                    properties[key] = value

        source_obj = (
            cell_specification_node.get("schema:isBasedOn")
            if cell_specification_node is not None
            else cell_spec_node.get("schema:isBasedOn")
        )
        if not isinstance(source_obj, Mapping):
            source_obj = {}
        subclass_ids = _subclass_ref_ids(cell_spec_node)
        is_desc = cell_spec_node.get("isDescriptionFor")
        is_desc_types = _type_values(is_desc) if isinstance(is_desc, Mapping) else []
        format_value = (
            "coin"
            if "CoinCell" in subclass_ids or _node_has_type(cell_instance_node, "CoinCell") or "CoinCell" in is_desc_types
            else "cylindrical"
            if "CylindricalBattery" in subclass_ids or _node_has_type(cell_instance_node, "CylindricalBattery") or "CylindricalBattery" in is_desc_types
            else "pouch"
            if "PouchCell" in subclass_ids or _node_has_type(cell_instance_node, "PouchCell") or "PouchCell" in is_desc_types
            else "prismatic"
            if "PrismaticBattery" in subclass_ids or _node_has_type(cell_instance_node, "PrismaticBattery") or "PrismaticBattery" in is_desc_types
            else "unknown"
        )
        cell_spec = CellSpecification(
            id=str(cell_spec_node["@id"]),
            name=str(cell_spec_node.get("schema:name") or f"{manufacturer} {cell_spec_node.get('schema:model') or 'unknown'}"),
            manufacturer=str(manufacturer or "unknown"),
            model=str(
                cell_spec_node.get("schema:model")
                or (cell_specification_node.get("schema:model") if isinstance(cell_specification_node, Mapping) else None)
                or cell_spec_node.get("schema:name")
                or "unknown"
            ),
            format=format_value,
            chemistry="unknown",
            size_code=cell_spec_node.get("schema:size") or (cell_specification_node.get("schema:size") if isinstance(cell_specification_node, Mapping) else None),
            country_of_origin=_country_name_value(cell_spec_node.get("schema:countryOfOrigin")),
            year=_year_value(cell_spec_node.get("schema:releaseDate")),
            cell_specification_id=str(cell_specification_node.get("@id")) if isinstance(cell_specification_node, Mapping) else None,
            properties=properties,
            source=ProvenanceInfo(
                type=source_obj.get("schema:additionalType"),
                name=source_obj.get("schema:name"),
                file=source_obj.get("schema:identifier"),
                url=source_obj.get("schema:url") or source_obj.get("@id"),
                citation=_citation_url_value(
                    _ref_id(cell_spec_node.get("schema:citation")) or source_obj.get("schema:citation"),
                    source_obj.get("bibo:doi"),
                ),
                retrieved_at=source_obj.get("schema:dateModified"),
                workflow_version=source_obj.get("schema:version"),
                comment=source_obj.get("schema:description"),
            ),
            comment=_text_list(cell_spec_node.get("schema:description")),
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
                model=str(cell_specification_node.get("schema:model") or cell_spec.model),
                format=cell_spec.format,
                chemistry=cell_spec.chemistry,
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
            cell_spec_id=str(cell_spec_id or cell_spec.id),
            serial_number=cell_instance_node.get("schema:serialNumber"),
        )
        protocol_name, test_description = _protocol_from_description(test_node.get("schema:description"))
        if protocol_name is None:
            # Gold-standard tests record the protocol as schema:measurementTechnique.
            mt = test_node.get("schema:measurementTechnique")
            if isinstance(mt, str):
                protocol_name = mt
            elif isinstance(mt, list) and mt:
                protocol_name = mt[0]
        instrument_name = _instrument_name(test_node.get("schema:instrument"))
        if instrument_name is None:
            # Gold-standard tests carry the instrument via hasTestEquipment, not schema:instrument.
            equip = test_node.get("hasTestEquipment")
            if isinstance(equip, Mapping):
                instrument_name = equip.get("schema:name")
        test = Test(
            id=str(test_node["@id"]),
            name=str(test_node.get("schema:name") or test_node["@id"]),
            test_kind=str(test_node.get("schema:additionalType") or "other"),
            cell_instance_id=str(
                _ref_id(test_node.get("hasTestObject"))
                or _ref_id(test_node.get("schema:object"))
                or _ref_id(test_node.get("schema:about"))
                or cell_instance.id
            ),
            description=test_description,
            status=test_node.get("schema:actionStatus") or test_node.get("schema:creativeWorkStatus"),
            protocol=ProtocolInfo(
                name=protocol_name,
            ),
            instrument=instrument_name,
            dataset_ids=[
                ref_id
                for ref_id in _ref_ids(test_node.get("hasOutput") or test_node.get("schema:result"))
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
            # In the gold-standard shape the dataset→test link lives on the test
            # (prov:generated / hasOutput), not in the dataset's schema:about, so fall
            # back to the reconstructed test/cell-instance of this single-dataset bundle.
            cell_instance_id=next(
                (ref_id for ref_id in _ref_ids(dataset_node.get("schema:about")) if "/cell/" in ref_id),
                None,
            ) or cell_instance.id,
            test_id=next(
                (ref_id for ref_id in _ref_ids(dataset_node.get("schema:about")) if "/test/" in ref_id),
                None,
            ) or str(test_node.get("@id")),
        )
        return cls(
            bundle_name=dataset.name,
            cell_specification=cell_specification,
            cell_spec=cell_spec,
            cell_instance=cell_instance,
            test=test,
            dataset=dataset,
        )


class ZenodoDatasetEntry(BaseModel):
    """One test/dataset entry within a ZenodoCellRecord.

    cell_instances is empty when the contributing cells are not individually
    tracked (aggregate records), or contains one or more CellInstance records
    when per-cell provenance is available.
    """

    model_config = ConfigDict(extra="forbid")

    cell_instances: list[CellInstance] = Field(default_factory=list)
    test: Test
    dataset: Dataset


class ZenodoCellRecord(BaseModel):
    """
    Multi-dataset flat JSON container for a single Zenodo record.

    Serialises to / from battinfo.bundle.json — the file that battery-genome's
    Zenodo harvester ingests.  One record covers one manufacturer × cell model
    and may contain multiple (test, dataset) entries, each optionally annotated
    with one or more CellInstance records.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    kind: str = "BattinfoCellRecord"
    cell_spec: CellSpecification
    cell_specification: CellSpecification | None = None
    datasets: list[ZenodoDatasetEntry]

    def to_flat_json(self, *, zenodo_record_url: str | None = None) -> dict[str, Any]:
        """Serialize for the Zenodo staging package.

        A dataset without an access URL gets *zenodo_record_url* (default
        ``https://zenodo.org/records/ZENODO_RECORD_ID``) — the flow's documented
        placeholder token that ``patch_zenodo_urls()`` rewrites to the real record URL
        after upload. That is where the data will actually live, unlike the retired
        ``example.org`` fallback, which was never patched and published fake URLs.
        """
        placeholder_url = zenodo_record_url or "https://zenodo.org/records/ZENODO_RECORD_ID"

        def _dataset_record(dataset: Dataset) -> dict[str, Any]:
            if dataset.access_url is None and dataset.source.url is None:
                dataset = dataset.model_copy(update={"access_url": placeholder_url})
            return dataset.to_record()

        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "cell_spec": self.cell_spec.to_record(),
        }
        if self.cell_specification is not None:
            payload["cell_specification"] = self.cell_specification.to_library_record()
        payload["datasets"] = [
            {
                "cell_instances": [ci.to_record() for ci in entry.cell_instances],
                "test": entry.test.to_record(),
                "dataset": _dataset_record(entry.dataset),
            }
            for entry in self.datasets
        ]
        return payload

    def to_path(self, path: PathLike, *, zenodo_record_url: str | None = None) -> Path:
        out_path = _as_path(path)
        _write_json(out_path, self.to_flat_json(zenodo_record_url=zenodo_record_url))
        return out_path

    @classmethod
    def from_flat_json(cls, data: Mapping[str, Any]) -> "ZenodoCellRecord":
        data = dict(data)
        cell_spec_raw = data.get("cell_spec")
        if not isinstance(cell_spec_raw, Mapping):
            raise ValueError("ZenodoCellRecord must contain a 'cell_spec' object.")
        datasets_raw = data.get("datasets")
        if not isinstance(datasets_raw, list):
            raise ValueError("ZenodoCellRecord must contain a 'datasets' list.")

        cell_specification: CellSpecification | None = None
        spec_raw = data.get("cell_specification")
        if isinstance(spec_raw, Mapping):
            cell_specification = CellSpecification.from_library_record(spec_raw)

        cell_spec = CellSpecification.from_record(
            cell_spec_raw,
            cell_specification_id=cell_specification.id if cell_specification is not None else None,
        )

        entries: list[ZenodoDatasetEntry] = []
        for i, entry_raw in enumerate(datasets_raw):
            if not isinstance(entry_raw, Mapping):
                raise ValueError(f"datasets[{i}] must be a mapping.")
            test_raw = entry_raw.get("test")
            ds_raw = entry_raw.get("dataset")
            if not isinstance(test_raw, Mapping):
                raise ValueError(f"datasets[{i}].test must be a mapping.")
            if not isinstance(ds_raw, Mapping):
                raise ValueError(f"datasets[{i}].dataset must be a mapping.")
            ci_raws = entry_raw.get("cell_instances") or []
            if not isinstance(ci_raws, list):
                raise ValueError(f"datasets[{i}].cell_instances must be a list.")
            entries.append(ZenodoDatasetEntry(
                cell_instances=[CellInstance.from_record(ci) for ci in ci_raws if isinstance(ci, Mapping)],
                test=Test.from_record(test_raw),
                dataset=Dataset.from_record(ds_raw),
            ))

        return cls(
            schema_version=str(data.get("schema_version", "1.0.0")),
            kind=str(data.get("kind", "BattinfoCellRecord")),
            cell_spec=cell_spec,
            cell_specification=cell_specification,
            datasets=entries,
        )

    @classmethod
    def from_path(cls, path: PathLike) -> "ZenodoCellRecord":
        return cls.from_flat_json(_read_json(_as_path(path)))

    @classmethod
    def from_battinfo_bundles(
        cls,
        bundles: list[BattinfoBundle],
        *,
        cell_specification: CellSpecification | None = None,
    ) -> "ZenodoCellRecord":
        """Build a ZenodoCellRecord from one or more single-dataset BattinfoBundles.

        All bundles must share the same cell_spec (checked by id).
        """
        if not bundles:
            raise ValueError("At least one BattinfoBundle is required.")
        cell_spec = bundles[0].cell_spec
        if any(b.cell_spec.id != cell_spec.id for b in bundles[1:]):
            raise ValueError("All bundles must share the same cell_spec.id.")
        spec = cell_specification or bundles[0].cell_specification
        return cls(
            cell_spec=cell_spec,
            cell_specification=spec,
            datasets=[
                ZenodoDatasetEntry(
                    cell_instances=[b.cell_instance],
                    test=b.test,
                    dataset=b.dataset,
                )
                for b in bundles
            ],
        )


def load_cell_specification(path: PathLike) -> CellSpecification:
    return CellSpecification.from_path(path)


TestProtocol = TestSpec  # backward compat alias


__all__ = [
    "BatteryTestType",
    "BUNDLE_MANIFEST_FILENAME",
    "BattinfoBundle",
    "CELL_INSTANCE_FILENAME",
    "CELL_SPECIFICATION_FILENAME",
    "CELL_SPEC_FILENAME",
    "Coating",
    "CellInstance",
    "CellSpecification",
    "CellSpecification",
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
    "CONFORMANCE_STATUS_VALUES",
    "CONFORMANCE_STATUS_IRI",
    "DEVIATION_CATEGORIES",
    "Deviation",
    "Conformance",
    "TestConformance",
    "TEST_SPEC_FILENAME",
    "TEST_PROTOCOL_FILENAME",
    "TEST_FILENAME",
    "TestSpec",
    "TestProtocol",
    "Test",
    "ZENODO_CELL_RECORD_FILENAME",
    "ZenodoCellRecord",
    "ZenodoDatasetEntry",
]
