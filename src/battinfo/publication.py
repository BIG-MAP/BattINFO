from __future__ import annotations

import html
import hashlib
import json
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlparse

from rdflib import Dataset as RdfDataset

from battinfo.bundle import BattinfoBundle, CellInstance, CellSpecification, CellType, Dataset, ProtocolInfo, ProvenanceInfo, Test
from battinfo.validate.core import PUBLISHER_POLICY, ValidationPolicy
from battinfo.validate.pydantic import validate_json
from battinfo.validate.publication import validate_publication_report

PathLike = str | Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CR2032_DATASHEET = Path("ENERGIZER__CR2032.pdf")
DEFAULT_CR2032_LIBRARY_SPEC = ROOT / "assets" / "library" / "cell-types" / "ENERGIZER__CR2032.json"
DEFAULT_CR2032_DATASET_DIRS: tuple[Path, ...] = ()
DEFAULT_PUBLISH_FILENAME = "battinfo.publish.jsonld"
DEFAULT_RO_CRATE_METADATA_FILENAME = "ro-crate-metadata.json"
DEFAULT_DATACITE_METADATA_FILENAME = "datacite-metadata.json"
DEFAULT_DCAT_EXPORT_FILENAME = "battinfo.dcat.jsonld"
DEFAULT_PUBLICATION_REPORT_FILENAME = "battinfo-publication-report.json"
DEFAULT_CR2032_REPORT_FILENAME = "cr2032-publication-report.json"
DEFAULT_REPORT_FILENAME = DEFAULT_CR2032_REPORT_FILENAME
DOMAIN_BATTERY_CONTEXT_URL = "https://w3id.org/emmo/domain/battery/context"
RO_CRATE_CONTEXT_URL = "https://w3id.org/ro/crate/1.2/context"
RO_CRATE_PROFILE_URL = "https://w3id.org/ro/crate/1.2"
OWL_CLASS_IRI = "http://www.w3.org/2002/07/owl#Class"
RDFS_SUBCLASS_OF_IRI = "http://www.w3.org/2000/01/rdf-schema#subClassOf"
UID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"

PROPERTY_TYPE_MAP = {
    "diameter": "Diameter",
    "height": "Height",
    "mass": "Mass",
    "nominal_capacity": "NominalCapacity",
    "typical_energy": "TypicalEnergy",
    "rated_energy": "RatedEnergy",
    "nominal_voltage": "NominalVoltage",
}
UNIT_IRI_MAP = {
    "Ah": "https://qudt.org/vocab/unit/AmpereHour",
    "V": "https://qudt.org/vocab/unit/Volt",
    "g": "https://qudt.org/vocab/unit/Gram",
    "mm": "https://qudt.org/vocab/unit/MilliMetre",
}
CELL_SUBCLASS_MAP = {
    "coin": "CoinCell",
    "cylindrical": "CylindricalBattery",
    "pouch": "PouchCell",
    "prismatic": "PrismaticBattery",
}
DOI_URL_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/(10\.\S+)$", re.IGNORECASE)
DOI_LITERAL_RE = re.compile(r"^(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)$")


def _as_path(path: PathLike) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _triple_count(payload: Mapping[str, Any]) -> int:
    dataset = RdfDataset()
    dataset.parse(data=json.dumps(payload), format="json-ld")
    return len(dataset)


def _tail_id(entity_id: str) -> str:
    return entity_id.rstrip("/").split("/")[-1]


def _now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_uid(seed: str) -> str:
    value = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:16], "big")
    chars: list[str] = []
    for _ in range(16):
        value, remainder = divmod(value, 32)
        chars.append(UID_ALPHABET[remainder])
    token = "".join(reversed(chars))
    return "-".join((token[:4], token[4:8], token[8:12], token[12:16]))


def _entity_iri(entity_type: str, seed: str) -> str:
    return f"https://w3id.org/battinfo/{entity_type}/{_stable_uid(seed)}"


def _cell_specification_iri(entity_id: str) -> str:
    if "/cell-specification/" in entity_id:
        return entity_id
    if "/cell-type/" in entity_id:
        return entity_id.replace("/cell-type/", "/cell-specification/")
    return _entity_iri("cell-specification", entity_id)


def _cell_type_iri(entity_id: str) -> str:
    if "/cell-type/" in entity_id:
        return entity_id
    if "/cell-specification/" in entity_id:
        return entity_id.replace("/cell-specification/", "/cell-type/")
    return _entity_iri("cell-type", entity_id)


def _with_default(value: str | None, fallback: str) -> str:
    text = (value or "").strip()
    return text or fallback


def _without_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _citation_doi_from_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = DOI_URL_RE.match(value.strip())
    if match is None:
        return None
    return match.group(1)


def _citation_url_value(source: ProvenanceInfo) -> str | None:
    if source.citation:
        extracted = _citation_doi_from_url(source.citation)
        if extracted is not None:
            return f"https://doi.org/{extracted}"
        if DOI_LITERAL_RE.fullmatch(source.citation):
            return f"https://doi.org/{source.citation}"
        return source.citation
    return None


def _citation_doi_value(source: ProvenanceInfo) -> str | None:
    return _citation_doi_from_url(_citation_url_value(source))


def _upsert_graph_node(graph: list[dict[str, Any]], node: dict[str, Any]) -> None:
    node_id = node.get("@id")
    if not isinstance(node_id, str):
        graph.append(node)
        return
    for existing in graph:
        if existing.get("@id") == node_id:
            existing.update(node)
            return
    graph.append(node)


def _quantity_to_spec_item(quantity: Any) -> dict[str, Any] | None:
    if not isinstance(quantity, Mapping):
        return None
    out: dict[str, Any] = {}
    if "value" in quantity:
        out["value"] = quantity["value"]
    if "typical_value" in quantity:
        out["value_typical"] = quantity["typical_value"]
    if "min_value" in quantity:
        out["value_min"] = quantity["min_value"]
    if "max_value" in quantity:
        out["value_max"] = quantity["max_value"]
    if "value_text" in quantity:
        out["value_text"] = quantity["value_text"]
    if "unit" in quantity:
        out["unit"] = quantity["unit"]
    has_value = any(key in out for key in ("value", "value_typical", "value_min", "value_max", "value_text"))
    if not has_value or "unit" not in out:
        return None
    return out


def _specification_properties_to_cell_type_specs(properties: Any) -> dict[str, Any]:
    if not isinstance(properties, Mapping):
        return {}
    out: dict[str, Any] = {}
    for key, value in properties.items():
        cleaned = _quantity_to_spec_item(value)
        if cleaned is not None:
            out[str(key)] = cleaned
    return out


class _FormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _format_template(template: str | None, context: Mapping[str, str]) -> str | None:
    if template is None:
        return None
    return template.format_map(_FormatDict({key: str(value) for key, value in context.items()})).strip()


def _append_unique(values: list[str], value: str | None) -> list[str]:
    out = list(values)
    if value is not None and value not in out:
        out.append(value)
    return out


def _path_from_file_uri(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path_text = unquote(parsed.path)
    if parsed.netloc:
        path_text = f"//{parsed.netloc}{path_text}"
    if path_text.startswith("/") and len(path_text) > 2 and path_text[2] == ":":
        path_text = path_text[1:]
    return Path(path_text)


def _resolve_dataset_dir(dataset: Dataset) -> Path:
    if dataset.dataset_path:
        return _as_path(dataset.dataset_path)
    if dataset.access_url:
        path = _path_from_file_uri(dataset.access_url)
        if path is not None:
            return path
    raise ValueError("Dataset must define a local path via Dataset(path=...) or dataset_path before publication.")


def _discover_dataset_files(dataset_dir: Path, dataset_glob: str, publish_filename: str) -> list[Path]:
    return [
        path
        for path in sorted(dataset_dir.glob(dataset_glob))
        if path.is_file() and "battinfo" not in path.parts and path.name != publish_filename
    ]


def _distribution_entries(dataset_dir: Path, files: list[Path]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in files:
        guessed_format, _ = mimetypes.guess_type(path.name)
        entries.append(
            {
                "@type": "schema:DataDownload",
                "schema:name": path.name,
                "schema:contentUrl": path.resolve().as_uri(),
                "schema:encodingFormat": guessed_format or "application/octet-stream",
                "schema:sha256": _sha256(path),
                "schema:isPartOf": {"@id": dataset_dir.resolve().as_uri()},
            }
        )
    return entries


def _schema_distribution_node(value: Mapping[str, Any], *, part_of_id: str) -> dict[str, Any] | None:
    content_url = value.get("contentUrl")
    encoding_format = value.get("encodingFormat")
    checksum = value.get("checksum")
    if not isinstance(content_url, str) and not isinstance(encoding_format, str) and not isinstance(checksum, Mapping):
        return None
    node: dict[str, Any] = {"@type": "schema:DataDownload"}
    name = value.get("name")
    if isinstance(name, str):
        node["schema:name"] = name
    description = value.get("description")
    if isinstance(description, str):
        node["schema:description"] = description
    if isinstance(content_url, str):
        node["schema:contentUrl"] = content_url
    if isinstance(encoding_format, str):
        node["schema:encodingFormat"] = encoding_format
    content_size = value.get("contentSize")
    if isinstance(content_size, str):
        node["schema:contentSize"] = content_size
    access_level = value.get("accessLevel")
    if isinstance(access_level, str):
        node["schema:accessLevel"] = access_level
    node["schema:isPartOf"] = {"@id": part_of_id}
    if isinstance(checksum, Mapping) and isinstance(checksum.get("algorithm"), str) and isinstance(checksum.get("value"), str):
        if checksum["algorithm"].lower() == "sha256":
            node["schema:sha256"] = checksum["value"]
        else:
            node["schema:checksum"] = {
                "@type": "schema:PropertyValue",
                "schema:propertyID": checksum["algorithm"],
                "schema:value": checksum["value"],
            }
    return node


def _publication_distribution_entries(dataset: Dataset, dataset_dir: Path, files: list[Path]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    seen_content_urls: set[str] = set()
    for item in dataset.distributions:
        node = _schema_distribution_node(item, part_of_id=dataset_dir.resolve().as_uri())
        if node is None:
            continue
        content_url = node.get("schema:contentUrl")
        if isinstance(content_url, str):
            seen_content_urls.add(content_url)
        entries.append(node)
    for node in _distribution_entries(dataset_dir, files):
        content_url = node.get("schema:contentUrl")
        if isinstance(content_url, str) and content_url in seen_content_urls:
            continue
        entries.append(node)
    return entries


def _schema_identifier_value(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        property_id = value.get("property_id")
        prop_value = value.get("value")
        if isinstance(property_id, str) and isinstance(prop_value, str):
            return {
                "@type": "schema:PropertyValue",
                "schema:propertyID": property_id,
                "schema:value": prop_value,
            }
        return None
    if isinstance(value, list):
        out: list[Any] = []
        for item in value:
            converted = _schema_identifier_value(item)
            if converted is not None:
                out.append(converted)
        return out or None
    return None


def _schema_agent_node(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    agent_type = value.get("type")
    if not isinstance(agent_type, str):
        agent_type = "Organization"
    if agent_type not in {"Person", "Organization"}:
        agent_type = "Organization"
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    node: dict[str, Any] = {
        "@type": f"schema:{agent_type}",
        "schema:name": name,
    }
    url = value.get("url")
    if isinstance(url, str):
        node["schema:url"] = url
    email = value.get("email")
    if isinstance(email, str):
        node["schema:email"] = email
    given_name = value.get("given_name")
    if isinstance(given_name, str):
        node["schema:givenName"] = given_name
    family_name = value.get("family_name")
    if isinstance(family_name, str):
        node["schema:familyName"] = family_name
    same_as = value.get("sameAs")
    if isinstance(same_as, str):
        node["schema:sameAs"] = same_as
    affiliation = value.get("affiliation")
    if isinstance(affiliation, Mapping):
        nested = _schema_agent_node(affiliation)
        if nested is not None:
            node["schema:affiliation"] = nested
    return node


def _schema_country_node(value: Any) -> dict[str, Any] | str | None:
    if not isinstance(value, str):
        return None
    name = value.strip()
    if not name:
        return None
    return {
        "@type": "schema:Country",
        "schema:name": name,
    }


def _schema_release_date_from_year(value: Any) -> str | None:
    if isinstance(value, int):
        return f"{value:04d}-01-01"
    return None


def _schema_data_catalog_node(value: Any) -> Any:
    if isinstance(value, str):
        return {"@id": value} if "://" in value else value
    if not isinstance(value, Mapping):
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    node: dict[str, Any] = {
        "@type": "schema:DataCatalog",
        "schema:name": name,
    }
    node_id = value.get("id")
    if isinstance(node_id, str):
        node["@id"] = node_id
    url = value.get("url")
    if isinstance(url, str):
        node["schema:url"] = url
    same_as = value.get("sameAs")
    if isinstance(same_as, str):
        node["schema:sameAs"] = same_as
    description = value.get("description")
    if isinstance(description, str):
        node["schema:description"] = description
    return node


def _schema_citation_value(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return None
    node: dict[str, Any] = {"@type": "schema:CreativeWork"}
    url = value.get("url")
    if isinstance(url, str):
        node["@id"] = url
        node["schema:url"] = url
    name = value.get("name")
    if isinstance(name, str):
        node["schema:name"] = name
    kind = value.get("kind")
    if isinstance(kind, str):
        node["schema:additionalType"] = kind
    doi = value.get("doi")
    if isinstance(doi, str):
        node["bibo:doi"] = doi
    citation_key = value.get("citation_key")
    if isinstance(citation_key, str):
        node["schema:identifier"] = citation_key
    return node


def _schema_variable_measured(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for value in values:
        name = value.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        node: dict[str, Any] = {
            "@type": "schema:PropertyValue",
            "schema:name": name,
        }
        description = value.get("description")
        if isinstance(description, str):
            node["schema:description"] = description
        unit_text = value.get("unit_text")
        if isinstance(unit_text, str):
            node["schema:unitText"] = unit_text
        same_as = value.get("sameAs")
        if isinstance(same_as, str):
            node["schema:sameAs"] = same_as
            node["schema:propertyID"] = same_as
        out.append(node)
    return out


def _schema_table_column_node(value: Mapping[str, Any]) -> dict[str, Any] | None:
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    node: dict[str, Any] = {
        "@type": "csvw:Column",
        "csvw:name": name,
    }
    titles = value.get("titles")
    if isinstance(titles, str):
        node["csvw:titles"] = titles
    elif isinstance(titles, list):
        title_values = [item for item in titles if isinstance(item, str)]
        if title_values:
            node["csvw:titles"] = title_values
    description = value.get("description")
    if isinstance(description, str):
        node["schema:description"] = description
    datatype = value.get("datatype")
    if isinstance(datatype, str):
        node["csvw:datatype"] = datatype
    unit_text = value.get("unit_text")
    if isinstance(unit_text, str):
        node["schema:unitText"] = unit_text
    same_as = value.get("sameAs")
    if isinstance(same_as, str):
        node["schema:sameAs"] = same_as
        node["schema:propertyID"] = same_as
    required = value.get("required")
    if isinstance(required, bool):
        node["csvw:required"] = required
    return node


def _schema_table_schema_node(value: Any) -> dict[str, Any] | str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return None
    columns = value.get("columns")
    if not isinstance(columns, list):
        return None
    column_nodes = [column for item in columns if isinstance(item, Mapping) and (column := _schema_table_column_node(item)) is not None]
    if not column_nodes:
        return None
    node: dict[str, Any] = {
        "@type": "csvw:Schema",
        "csvw:column": column_nodes,
    }
    if isinstance(value.get("id"), str):
        node["@id"] = value["id"]
    if isinstance(value.get("name"), str):
        node["schema:name"] = value["name"]
    if isinstance(value.get("description"), str):
        node["schema:description"] = value["description"]
    primary_key = value.get("primaryKey")
    if isinstance(primary_key, str):
        node["csvw:primaryKey"] = primary_key
    elif isinstance(primary_key, list):
        values = [item for item in primary_key if isinstance(item, str)]
        if values:
            node["csvw:primaryKey"] = values
    return node


def _schema_main_entity_node(value: Mapping[str, Any]) -> dict[str, Any] | None:
    node_type = value.get("type")
    if isinstance(node_type, str) and ":" in node_type:
        node_type = node_type.split(":", 1)[1]
    if node_type == "Table":
        url = value.get("url")
        table_schema = value.get("tableSchema")
        resolved_table_schema = _schema_table_schema_node(table_schema)
        if not isinstance(url, str) or resolved_table_schema is None:
            return None
        node: dict[str, Any] = {
            "@type": "csvw:Table",
            "csvw:url": url,
            "csvw:tableSchema": resolved_table_schema,
        }
        if isinstance(value.get("id"), str):
            node["@id"] = value["id"]
        if isinstance(value.get("name"), str):
            node["schema:name"] = value["name"]
        if isinstance(value.get("description"), str):
            node["schema:description"] = value["description"]
        return node
    if node_type == "TableGroup":
        table_items = value.get("table")
        if not isinstance(table_items, list):
            return None
        tables = [table for item in table_items if isinstance(item, Mapping) and (table := _schema_main_entity_node(item)) is not None]
        if not tables:
            return None
        node = {
            "@type": "csvw:TableGroup",
            "csvw:table": tables,
        }
        if isinstance(value.get("id"), str):
            node["@id"] = value["id"]
        if isinstance(value.get("url"), str):
            node["csvw:url"] = value["url"]
        if isinstance(value.get("name"), str):
            node["schema:name"] = value["name"]
        if isinstance(value.get("description"), str):
            node["schema:description"] = value["description"]
        return node
    return None


def _publication_html(payload: Mapping[str, Any], *, title: str | None = None) -> str:
    graph = payload.get("@graph")
    if isinstance(graph, list):
        dataset_node = next(
            (
                node
                for node in graph
                if isinstance(node, Mapping) and (
                    node.get("@type") == "schema:Dataset"
                    or (isinstance(node.get("@type"), list) and "schema:Dataset" in node.get("@type"))
                )
            ),
            None,
        )
    else:
        dataset_node = payload if isinstance(payload, Mapping) else None
    doc_title = title
    if doc_title is None and isinstance(dataset_node, Mapping):
        name = dataset_node.get("schema:name")
        if isinstance(name, str):
            doc_title = name
    if doc_title is None:
        doc_title = "BattINFO Publication"
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\" />\n"
        f"  <title>{html.escape(doc_title)}</title>\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
        "  <script type=\"application/ld+json\">\n"
        f"{payload_json}\n"
        "  </script>\n"
        "</head>\n"
        "<body></body>\n"
        "</html>\n"
    )


def save_publication_html(
    payload: Mapping[str, Any] | PathLike,
    out_path: PathLike,
    *,
    title: str | None = None,
) -> Path:
    data = _load_json(_as_path(payload)) if isinstance(payload, (str, Path)) else dict(payload)
    out = _as_path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_publication_html(data, title=title), encoding="utf-8")
    return out


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if len(text) >= 10:
            return text[:10]
    return None


def _publication_year(value: Any) -> str:
    iso_date = _iso_date(value)
    if iso_date is not None:
        return iso_date[:4]
    return str(datetime.now(timezone.utc).year)


def _agent_name(agent: Mapping[str, Any] | None) -> str | None:
    if not isinstance(agent, Mapping):
        return None
    name = agent.get("name") or agent.get("schema:name")
    return str(name) if isinstance(name, str) and name.strip() else None


def _agent_affiliations(agent: Mapping[str, Any]) -> list[dict[str, str]]:
    value = agent.get("affiliation")
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    out: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, Mapping):
            name = _agent_name(item)
            if name is not None:
                out.append({"name": name})
    return out


def _agent_same_as(agent: Mapping[str, Any]) -> str | None:
    value = agent.get("sameAs") or agent.get("schema:sameAs")
    return str(value) if isinstance(value, str) and value.strip() else None


def _datacite_creators(dataset: Dataset) -> list[dict[str, Any]]:
    creators: list[dict[str, Any]] = []
    for agent in dataset.creators:
        if not isinstance(agent, Mapping):
            continue
        name = _agent_name(agent)
        if name is None:
            continue
        creator: dict[str, Any] = {"name": name}
        same_as = _agent_same_as(agent)
        if isinstance(same_as, str) and "orcid.org/" in same_as:
            creator["nameIdentifiers"] = [
                {
                    "nameIdentifier": same_as,
                    "nameIdentifierScheme": "ORCID",
                    "schemeUri": "https://orcid.org",
                }
            ]
        affiliations = _agent_affiliations(agent)
        if affiliations:
            creator["affiliation"] = affiliations
        creators.append(creator)
    return creators


def _datacite_publisher(dataset: Dataset) -> str:
    publisher = _agent_name(dataset.publisher) if isinstance(dataset.publisher, Mapping) else None
    return publisher or "BattINFO"


def _datacite_metadata(dataset: Dataset, *, dataset_dir: Path) -> dict[str, Any]:
    publication_year = _publication_year(dataset.published_at or dataset.created_at)
    metadata: dict[str, Any] = {
        "types": {
            "resourceType": "Battery test dataset",
            "resourceTypeGeneral": "Dataset",
        },
        "titles": [{"title": dataset.name or dataset_dir.name}],
        "creators": _datacite_creators(dataset),
        "publisher": _datacite_publisher(dataset),
        "publicationYear": publication_year,
        "url": dataset.access_url or dataset_dir.resolve().as_uri(),
    }
    if dataset.description is not None:
        metadata["descriptions"] = [{"description": dataset.description, "descriptionType": "Abstract"}]
    if dataset.license is not None:
        rights: dict[str, Any] = {"rights": dataset.license}
        if dataset.license.startswith("http://") or dataset.license.startswith("https://"):
            rights["rightsUri"] = dataset.license
        metadata["rightsList"] = [rights]
    if dataset.keywords:
        metadata["subjects"] = [{"subject": keyword} for keyword in dataset.keywords]
    if dataset.version is not None:
        metadata["version"] = dataset.version
    if dataset.data_format is not None:
        metadata["formats"] = [dataset.data_format]
    return metadata


def _publication_file_nodes(dataset_dir: Path, *, publish_filename: str, datacite_filename: str, dcat_filename: str | None) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for filename, media_type in (
        (publish_filename, "application/ld+json"),
        (DEFAULT_RO_CRATE_METADATA_FILENAME, "application/ld+json"),
        (datacite_filename, "application/json"),
        (dcat_filename, "application/ld+json" if dcat_filename is not None else None),
    ):
        if filename is None or media_type is None:
            continue
        path = dataset_dir / filename
        if not path.exists():
            continue
        nodes.append(
            {
                "@id": filename,
                "@type": "File",
                "name": path.name,
                "encodingFormat": media_type,
                "contentSize": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return nodes


def _ro_crate_metadata(
    dataset: Dataset,
    *,
    dataset_dir: Path,
    dataset_files: list[Path],
    publish_filename: str,
    datacite_filename: str,
    dcat_filename: str | None = None,
) -> dict[str, Any]:
    has_part = [{"@id": path.relative_to(dataset_dir).as_posix()} for path in dataset_files]
    has_part.extend({"@id": node["@id"]} for node in _publication_file_nodes(dataset_dir, publish_filename=publish_filename, datacite_filename=datacite_filename, dcat_filename=dcat_filename))
    root_dataset: dict[str, Any] = {
        "@id": "./",
        "@type": "Dataset",
        "name": dataset.name or dataset_dir.name,
        "description": dataset.description,
        "license": dataset.license,
        "hasPart": has_part,
    }
    if dataset.creators:
        creators = [creator for creator in dataset.creators if isinstance(creator, Mapping)]
        if creators:
            root_dataset["creator"] = creators
    if isinstance(dataset.publisher, Mapping):
        root_dataset["publisher"] = dict(dataset.publisher)
    if dataset.keywords:
        root_dataset["keywords"] = list(dataset.keywords)
    if dataset.version is not None:
        root_dataset["version"] = dataset.version

    graph: list[dict[str, Any]] = [
        {
            "@id": DEFAULT_RO_CRATE_METADATA_FILENAME,
            "@type": "CreativeWork",
            "about": {"@id": "./"},
            "conformsTo": {"@id": RO_CRATE_PROFILE_URL},
        },
        _without_none(root_dataset),
    ]
    for path in dataset_files:
        relpath = path.relative_to(dataset_dir).as_posix()
        graph.append(
            {
                "@id": relpath,
                "@type": "File",
                "name": path.name,
                "encodingFormat": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "contentSize": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    graph.extend(_publication_file_nodes(dataset_dir, publish_filename=publish_filename, datacite_filename=datacite_filename, dcat_filename=dcat_filename))
    return {
        "@context": RO_CRATE_CONTEXT_URL,
        "@graph": graph,
    }


def _dcat_agent_node(agent: Mapping[str, Any] | None) -> dict[str, Any] | None:
    name = _agent_name(agent)
    if name is None:
        return None
    node: dict[str, Any] = {"@type": "foaf:Agent", "foaf:name": name}
    same_as = _agent_same_as(agent) if isinstance(agent, Mapping) else None
    if same_as is not None:
        node["foaf:page"] = {"@id": same_as}
    return node


def _dcat_export(dataset: Dataset, *, dataset_dir: Path, dataset_files: list[Path]) -> dict[str, Any]:
    dataset_id = dataset.id or dataset_dir.resolve().as_uri()
    graph: list[dict[str, Any]] = []
    distribution_refs: list[dict[str, str]] = []
    for index, path in enumerate(dataset_files, start=1):
        relpath = path.relative_to(dataset_dir).as_posix()
        dist_id = f"{dataset_id}#distribution-{index}"
        distribution_refs.append({"@id": dist_id})
        graph.append(
            {
                "@id": dist_id,
                "@type": "dcat:Distribution",
                "dct:title": path.name,
                "dcat:accessURL": {"@id": path.resolve().as_uri()},
                "dcat:downloadURL": {"@id": path.resolve().as_uri()},
                "dcat:mediaType": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "dcat:byteSize": path.stat().st_size,
            }
        )
    dataset_node: dict[str, Any] = {
        "@id": dataset_id,
        "@type": "dcat:Dataset",
        "dct:title": dataset.name or dataset_dir.name,
        "dcat:landingPage": {"@id": dataset.access_url or dataset_dir.resolve().as_uri()},
        "dcat:distribution": distribution_refs,
    }
    if dataset.description is not None:
        dataset_node["dct:description"] = dataset.description
    if dataset.license is not None:
        dataset_node["dct:license"] = {"@id": dataset.license} if dataset.license.startswith(("http://", "https://")) else dataset.license
    if dataset.keywords:
        dataset_node["dcat:keyword"] = list(dataset.keywords)
    if dataset.created_at is not None:
        dataset_node["dct:issued"] = _iso_date(dataset.created_at)
    if dataset.modified_at is not None:
        dataset_node["dct:modified"] = _iso_date(dataset.modified_at)
    creator = _dcat_agent_node(dataset.creators[0]) if dataset.creators else None
    if creator is not None:
        dataset_node["dct:creator"] = creator
    publisher = _dcat_agent_node(dataset.publisher) if isinstance(dataset.publisher, Mapping) else None
    if publisher is not None:
        dataset_node["dct:publisher"] = publisher
    graph.insert(0, _without_none(dataset_node))
    return {
        "@context": ["https://www.w3.org/ns/dcat.jsonld", {"foaf": "http://xmlns.com/foaf/0.1/"}],
        "@graph": graph,
    }


def _dataset_jsonld_node(
    dataset: Dataset,
    files: list[Path],
    dataset_dir: Path,
    test_id: str,
    cell_id: str,
) -> dict[str, Any]:
    about_refs = [{"@id": cell_id}, {"@id": test_id}]
    node: dict[str, Any] = {
        "@id": dataset.id,
        "@type": "schema:Dataset",
        "schema:identifier": _schema_identifier_value(dataset.identifier),
        "schema:name": dataset.name,
        "schema:description": dataset.description,
        "schema:url": dataset.access_url or dataset_dir.resolve().as_uri(),
        "schema:about": about_refs,
        "schema:distribution": _publication_distribution_entries(dataset, dataset_dir, files),
    }
    if dataset.license is not None:
        node["schema:license"] = dataset.license
    if dataset.same_as:
        node["schema:sameAs"] = list(dataset.same_as)
    if dataset.additional_type:
        node["schema:additionalType"] = list(dataset.additional_type)
    if dataset.version is not None:
        node["schema:version"] = dataset.version
    if dataset.keywords:
        node["schema:keywords"] = list(dataset.keywords)
    if dataset.creators:
        creators = [creator for item in dataset.creators if (creator := _schema_agent_node(item)) is not None]
        if creators:
            node["schema:creator"] = creators
    if dataset.publisher is not None:
        publisher = _schema_agent_node(dataset.publisher)
        if publisher is not None:
            node["schema:publisher"] = publisher
    if dataset.funders:
        funders = [funder for item in dataset.funders if (funder := _schema_agent_node(item)) is not None]
        if funders:
            node["schema:funder"] = funders
    if dataset.citations:
        citations = [citation for item in dataset.citations if (citation := _schema_citation_value(item)) is not None]
        if citations:
            node["schema:citation"] = citations
    if dataset.measurement_techniques:
        node["schema:measurementTechnique"] = list(dataset.measurement_techniques)
    if dataset.measurement_methods:
        node["schema:measurementMethod"] = list(dataset.measurement_methods)
    if dataset.variable_measured:
        variable_measured = _schema_variable_measured(dataset.variable_measured)
        if variable_measured:
            node["schema:variableMeasured"] = variable_measured
    if dataset.is_accessible_for_free is not None:
        node["schema:isAccessibleForFree"] = dataset.is_accessible_for_free
    if dataset.conditions_of_access is not None:
        node["schema:conditionsOfAccess"] = dataset.conditions_of_access
    if dataset.in_language is not None:
        node["schema:inLanguage"] = dataset.in_language
    if dataset.created_at is not None:
        node["schema:dateCreated"] = dataset.created_at
    if dataset.modified_at is not None:
        node["schema:dateModified"] = dataset.modified_at
    if dataset.published_at is not None:
        node["schema:datePublished"] = dataset.published_at
    if dataset.temporal_coverage is not None:
        node["schema:temporalCoverage"] = dataset.temporal_coverage
    if dataset.spatial_coverage is not None:
        node["schema:spatialCoverage"] = dataset.spatial_coverage
    if dataset.is_based_on:
        node["schema:isBasedOn"] = list(dataset.is_based_on)
    if dataset.included_in_data_catalog is not None:
        included_in_data_catalog = _schema_data_catalog_node(dataset.included_in_data_catalog)
        if included_in_data_catalog is not None:
            node["schema:includedInDataCatalog"] = included_in_data_catalog
    if dataset.main_entity:
        main_entity = [
            main_entity_node
            for item in dataset.main_entity
            if (main_entity_node := _schema_main_entity_node(item)) is not None
        ]
        if main_entity:
            node["schema:mainEntity"] = main_entity
    return _without_none(node)


def _test_jsonld_node(test_record: Mapping[str, Any], dataset_id: str) -> dict[str, Any]:
    test = test_record["test"]
    description_value = test.get("description")
    protocol_name = test.get("protocol_name")
    if description_value is None and protocol_name is not None:
        description_value = f"Protocol: {protocol_name}"
    elif description_value is not None and protocol_name is not None:
        description_value = [description_value, f"Protocol: {protocol_name}"]
    node: dict[str, Any] = {
        "@id": test["id"],
        "@type": ["schema:Action", "BatteryTest"],
        "schema:identifier": test.get("identifier"),
        "schema:name": test.get("name"),
        "schema:description": description_value,
        "schema:object": {"@id": test["cell_id"]},
        "schema:result": {"@id": dataset_id},
    }
    if test.get("instrument_name") is not None:
        node["schema:instrument"] = {
            "@type": "schema:Thing",
            "schema:name": test["instrument_name"],
        }
    if test.get("status") is not None:
        node["schema:actionStatus"] = test.get("status")
    if test.get("kind") is not None:
        node["schema:additionalType"] = test.get("kind")
    if test.get("started_at") is not None:
        node["schema:startTime"] = test["started_at"]
    return _without_none(node)


def _cell_instance_summary_node(cell_instance_record: Mapping[str, Any], label: str, cell_type: CellType) -> dict[str, Any]:
    inst = cell_instance_record["cell_instance"]
    type_list = ["schema:IndividualProduct", "BatteryCell"]
    subclass_term = CELL_SUBCLASS_MAP.get(cell_type.format)
    if subclass_term is not None:
        type_list.append(subclass_term)
    node: dict[str, Any] = {
        "@id": inst["id"],
        "@type": type_list,
        "schema:identifier": inst.get("short_id"),
        "schema:name": label,
        "schema:description": "Dataset-local cell instance included in the publication graph.",
        "schema:isVariantOf": {"@id": inst["type_id"]},
    }
    if inst.get("serial_number"):
        node["schema:serialNumber"] = inst["serial_number"]
    return _without_none(node)


def _schema_source_node(source: ProvenanceInfo) -> dict[str, Any] | None:
    node: dict[str, Any] = {}
    if source.url is not None:
        node["@id"] = source.url
        node["schema:url"] = source.url
    if source.type is not None:
        node["schema:additionalType"] = source.type
    if source.name is not None:
        node["schema:name"] = source.name
    if source.file is not None:
        node["schema:identifier"] = source.file
    if source.retrieved_at is not None:
        node["schema:dateModified"] = source.retrieved_at
    if source.workflow_version is not None:
        node["schema:version"] = source.workflow_version
    if source.comment is not None:
        node["schema:description"] = source.comment
    return node or None


def _schema_citation_node(source: ProvenanceInfo) -> dict[str, Any] | None:
    citation_url = _citation_url_value(source)
    if citation_url is None:
        return None
    node: dict[str, Any] = {"@id": citation_url, "@type": "schema:CreativeWork"}
    citation_doi = _citation_doi_value(source)
    if citation_doi is not None:
        node["bibo:doi"] = citation_doi
    return node


def _cell_type_property_node(name: str, quantity: Any) -> dict[str, Any] | None:
    if not isinstance(quantity, Mapping):
        return None
    type_name = PROPERTY_TYPE_MAP.get(name)
    if type_name is None:
        return None
    value = (
        quantity.get("value")
        if "value" in quantity
        else quantity.get("value_typical")
        if "value_typical" in quantity
        else quantity.get("value_max")
        if "value_max" in quantity
        else quantity.get("value_min")
    )
    unit = quantity.get("unit")
    if value is None or not isinstance(unit, str):
        return None
    node: dict[str, Any] = {
        "@type": type_name,
        "hasNumericalPart": {"@type": "RealData", "hasNumericalValue": value},
    }
    unit_iri = UNIT_IRI_MAP.get(unit, unit)
    if unit_iri:
        node["hasMeasurementUnit"] = unit_iri
    return node


def _cell_type_jsonld_node(cell_type: CellType, *, cell_specification: CellSpecification | None = None) -> dict[str, Any]:
    type_list = ["schema:ProductModel", "BatteryCell"]
    subclass_term = CELL_SUBCLASS_MAP.get(cell_type.format)
    if subclass_term is not None:
        type_list.append(subclass_term)
    node: dict[str, Any] = {
        "@id": cell_type.id,
        "@type": type_list,
        "schema:identifier": _tail_id(cell_type.id),
        "schema:name": cell_type.name,
        "schema:model": cell_type.model,
        "schema:manufacturer": {
            "@type": "schema:Organization",
            "schema:name": cell_type.manufacturer,
        },
        "schema:category": cell_type.format,
        "schema:material": cell_type.chemistry,
        "schema:schemaVersion": cell_type.schema_version,
    }
    if cell_type.size_code is not None:
        node["schema:size"] = cell_type.size_code
    country_node = _schema_country_node(cell_type.country_of_origin)
    if country_node is not None:
        node["schema:countryOfOrigin"] = country_node
    release_date = _schema_release_date_from_year(cell_type.year)
    if release_date is not None:
        node["schema:releaseDate"] = release_date
    if cell_type.comment:
        node["schema:description"] = list(cell_type.comment)
    if cell_specification is not None:
        node["schema:isBasedOn"] = {"@id": cell_specification.id}
    else:
        source_node = _schema_source_node(cell_type.source)
        if source_node is not None:
            node["schema:isBasedOn"] = source_node
        properties = [
            property_node
            for key, value in cell_type.nominal_properties.items()
            if (property_node := _cell_type_property_node(key, value)) is not None
        ]
        if properties:
            node["hasProperty"] = properties
    citation_node = _schema_citation_node(cell_type.source)
    if citation_node is not None:
        node["schema:citation"] = citation_node
    return _without_none(node)


def _cell_specification_jsonld_node(cell_specification: CellSpecification, *, cell_type: CellType) -> dict[str, Any]:
    descriptions = list(cell_specification.specification_comment) + [
        comment for comment in cell_specification.comment if comment not in cell_specification.specification_comment
    ]
    properties = [
        property_node
        for key, value in cell_specification.properties.items()
        if (property_node := _cell_type_property_node(str(key), value)) is not None
    ]
    node: dict[str, Any] = {
        "@id": cell_specification.id,
        "@type": "schema:CreativeWork",
        "schema:identifier": _tail_id(cell_specification.id),
        "schema:additionalType": "cell-specification",
        "schema:name": f"{cell_specification.manufacturer} {cell_specification.model} specification",
        "schema:about": {"@id": cell_type.id},
        "schema:model": cell_specification.model,
        "schema:manufacturer": {
            "@type": "schema:Organization",
            "schema:name": cell_specification.manufacturer,
        },
        "schema:category": cell_specification.format,
        "schema:material": cell_specification.chemistry,
        "schema:schemaVersion": cell_specification.schema_version,
    }
    if cell_specification.size_code is not None:
        node["schema:size"] = cell_specification.size_code
    if descriptions:
        node["schema:description"] = descriptions
    if properties:
        node["hasProperty"] = properties
    source_node = _schema_source_node(cell_specification.source)
    if source_node is not None:
        node["schema:isBasedOn"] = source_node
    citation_node = _schema_citation_node(cell_specification.source)
    if citation_node is not None:
        node["schema:citation"] = citation_node
    return _without_none(node)


def _publication_graph(
    *,
    cell_type: CellType,
    cell_specification: CellSpecification | None,
    cell_instance_record: dict[str, Any],
    test_record: dict[str, Any],
    dataset_record: dict[str, Any],
    dataset: Dataset,
    dataset_dir: Path,
    dataset_files: list[Path],
    instance_label: str,
) -> dict[str, Any]:
    include_bibo = any(
        _citation_doi_value(source) is not None
        for source in (
            cell_specification.source if cell_specification is not None else None,
            cell_type.source,
        )
        if source is not None
    )
    include_csvw = bool(dataset.main_entity)
    graph = [_cell_type_jsonld_node(cell_type, cell_specification=cell_specification)]
    if cell_specification is not None:
        graph.append(_cell_specification_jsonld_node(cell_specification, cell_type=cell_type))

    _upsert_graph_node(graph, _cell_instance_summary_node(cell_instance_record, label=instance_label, cell_type=cell_type))
    _upsert_graph_node(graph, _test_jsonld_node(test_record, dataset_id=dataset_record["dataset"]["id"]))
    _upsert_graph_node(
        graph,
        _dataset_jsonld_node(
            dataset,
            files=dataset_files,
            dataset_dir=dataset_dir,
            test_id=test_record["test"]["id"],
            cell_id=cell_instance_record["cell_instance"]["id"],
        )
    )
    _upsert_graph_node(
        graph,
        {
            "@id": dataset_dir.resolve().as_uri(),
            "@type": "schema:Dataset",
            "schema:name": dataset_dir.name,
            "schema:url": dataset_dir.resolve().as_uri(),
            "schema:hasPart": [{"@id": dataset_record["dataset"]["id"]}],
        }
    )
    context: Any
    if include_bibo or include_csvw:
        context_entries: list[Any] = [DOMAIN_BATTERY_CONTEXT_URL]
        local_context: dict[str, str] = {}
        if include_bibo:
            local_context["bibo"] = "http://purl.org/ontology/bibo/"
        if include_csvw:
            local_context["csvw"] = "http://www.w3.org/ns/csvw#"
        context_entries.append(local_context)
        context = context_entries
    else:
        context = DOMAIN_BATTERY_CONTEXT_URL
    return {
        "@context": context,
        "@graph": graph,
    }


def _normalize_cell_specification(
    source: CellSpecification | Mapping[str, Any] | PathLike,
    *,
    datasheet_path: Path | None = None,
) -> CellSpecification:
    if isinstance(source, CellSpecification):
        spec = source.model_copy(deep=True)
    else:
        payload = _load_json(_as_path(source)) if isinstance(source, (str, Path)) else dict(source)
        if isinstance(payload.get("specification"), Mapping):
            result = validate_json(payload, profile="cell-descriptor")
            if not result.ok:
                raise ValueError(f"cell specification validation failed: {'; '.join(result.errors)}")
            spec = CellSpecification.from_library_record(payload)
        else:
            spec = CellSpecification.from_json(payload)
    if datasheet_path is not None:
        spec.source = spec.source.model_copy(
            update={
                "type": "datasheet",
                "name": datasheet_path.name,
                "file": str(datasheet_path),
                "url": datasheet_path.resolve().as_uri(),
                "retrieved_at": _now_unix(),
            }
        )
    spec.id = _cell_specification_iri(spec.id)
    return spec


def _normalize_cell_type(source: CellType | Mapping[str, Any] | PathLike) -> CellType:
    if isinstance(source, CellType):
        return source.model_copy(deep=True)
    payload = _load_json(_as_path(source)) if isinstance(source, (str, Path)) else dict(source)
    if isinstance(payload.get("product"), Mapping):
        return CellType.from_record(payload)
    return CellType.from_json(payload)


def _build_cell_type_from_specification(cell_specification: CellSpecification) -> CellType:
    return CellType(
        id=_cell_type_iri(cell_specification.id),
        name=f"{cell_specification.manufacturer} {cell_specification.model}",
        manufacturer=cell_specification.manufacturer,
        model=cell_specification.model,
        chemistry=cell_specification.chemistry,
        format=cell_specification.format,
        positive_electrode_basis=cell_specification.positive_electrode_basis,
        negative_electrode_basis=cell_specification.negative_electrode_basis,
        size_code=cell_specification.size_code,
        cell_specification_id=cell_specification.id,
        nominal_properties=_specification_properties_to_cell_type_specs(cell_specification.properties),
        source=ProvenanceInfo(
            type=cell_specification.source.type,
            name=cell_specification.source.name,
            file=cell_specification.source.file,
            url=cell_specification.source.url,
            retrieved_at=cell_specification.source.retrieved_at,
            workflow_version=cell_specification.source.workflow_version,
            comment=cell_specification.source.comment,
        ),
        comment=["Generated from the linked CellSpecification for publication packaging."],
    )


def derive_cell_type(
    source: CellSpecification | Mapping[str, Any] | PathLike,
    *,
    datasheet_path: PathLike | None = None,
) -> CellType:
    datasheet = _as_path(datasheet_path) if datasheet_path is not None else None
    normalized = _normalize_cell_specification(source, datasheet_path=datasheet)
    return _finalize_cell_type(
        _build_cell_type_from_specification(normalized),
        cell_specification=normalized,
    )


def _finalize_cell_type(
    cell_type: CellType,
    *,
    cell_specification: CellSpecification | None = None,
) -> CellType:
    finalized = cell_type.model_copy(deep=True)
    if finalized.id is None:
        finalized.id = (
            _cell_type_iri(cell_specification.id)
            if cell_specification is not None
            else _entity_iri(
                "cell-type",
                "::".join(
                    [
                        _with_default(finalized.manufacturer, "unknown-manufacturer"),
                        _with_default(finalized.model, "unknown-model"),
                        _with_default(finalized.format, "unknown-format"),
                        _with_default(finalized.chemistry, "unknown-chemistry"),
                        finalized.size_code or "",
                    ]
                ),
            )
        )
    if finalized.name is None:
        finalized.name = f"{finalized.manufacturer} {finalized.model}"
    if cell_specification is not None and finalized.source == ProvenanceInfo():
        finalized.source = cell_specification.source.model_copy(deep=True)
    if cell_specification is not None and finalized.cell_specification_id is None:
        finalized.cell_specification_id = cell_specification.id
    return finalized


def _finalize_cell_instance(
    cell_instance: CellInstance,
    *,
    cell_type: CellType,
    dataset_dir: Path,
    dataset_id: str | None = None,
) -> CellInstance:
    finalized = cell_instance.model_copy(deep=True, update={"cell_type": None})
    if finalized.cell_type_id is None:
        finalized.cell_type_id = cell_type.id
    if finalized.name is None:
        finalized.name = finalized.serial_number or finalized.batch_id or dataset_dir.name
    if finalized.id is None:
        finalized.id = _entity_iri(
            "cell",
            "::".join(
                [
                    _with_default(finalized.cell_type_id, "unknown-cell-type"),
                    finalized.serial_number or "",
                    finalized.batch_id or "",
                    _with_default(finalized.name, dataset_dir.name),
                ]
            ),
        )
    finalized.dataset_ids = _append_unique(finalized.dataset_ids, dataset_id)
    source = finalized.source.model_copy(deep=True)
    if source.type is None:
        source.type = "measurement"
    if source.url is None:
        source.url = dataset_dir.resolve().as_uri()
    if source.retrieved_at is None:
        source.retrieved_at = _now_unix()
    finalized.source = source
    return finalized


def _finalize_test(
    test: Test,
    *,
    cell_instance: CellInstance,
    dataset_dir: Path,
    dataset_id: str | None = None,
) -> Test:
    finalized = test.model_copy(deep=True, update={"cell": None})
    if finalized.cell_instance_id is None:
        finalized.cell_instance_id = cell_instance.id
    protocol_name = finalized.protocol.name or "test"
    if finalized.name is None:
        finalized.name = f"{cell_instance.name} {protocol_name}"
    if finalized.id is None:
        finalized.id = _entity_iri(
            "test",
            "::".join(
                [
                    _with_default(finalized.cell_instance_id, "unknown-cell"),
                    _with_default(finalized.test_kind, "other"),
                    protocol_name,
                    _with_default(finalized.name, "test"),
                ]
            ),
        )
    finalized.dataset_ids = _append_unique(finalized.dataset_ids, dataset_id)
    source = finalized.source.model_copy(deep=True)
    if source.type is None:
        source.type = "measurement"
    if source.url is None:
        source.url = dataset_dir.resolve().as_uri()
    if source.retrieved_at is None:
        source.retrieved_at = _now_unix()
    finalized.source = source
    return finalized


def _finalize_dataset(
    dataset: Dataset,
    *,
    cell_instance: CellInstance,
    test: Test,
    dataset_dir: Path,
) -> Dataset:
    finalized = dataset.model_copy(deep=True, update={"cell": None, "test": None})
    if finalized.dataset_path is None:
        finalized.dataset_path = str(dataset_dir)
    if finalized.access_url is None:
        finalized.access_url = dataset_dir.resolve().as_uri()
    if finalized.cell_instance_id is None:
        finalized.cell_instance_id = cell_instance.id
    if finalized.test_id is None:
        finalized.test_id = test.id
    if finalized.name is None:
        finalized.name = dataset_dir.name
    if finalized.created_at is None:
        finalized.created_at = _now_unix()
    if finalized.id is None:
        finalized.id = _entity_iri(
            "dataset",
            "::".join(
                [
                    _with_default(finalized.cell_instance_id, "unknown-cell"),
                    dataset_dir.resolve().as_uri(),
                    _with_default(finalized.name, dataset_dir.name),
                ]
            ),
        )
    source = finalized.source.model_copy(deep=True)
    if source.type is None:
        source.type = "measurement"
    if source.url is None:
        source.url = dataset_dir.resolve().as_uri()
    if source.retrieved_at is None:
        source.retrieved_at = finalized.created_at
    finalized.source = source
    return finalized


def _finalize_publication_bundle(
    *,
    cell_type: CellType,
    cell_instance: CellInstance,
    test: Test,
    dataset: Dataset,
    cell_specification: CellSpecification | None = None,
) -> tuple[BattinfoBundle, Path]:
    dataset_dir = _resolve_dataset_dir(dataset)
    finalized_cell_type = _finalize_cell_type(cell_type, cell_specification=cell_specification)
    finalized_cell_instance = _finalize_cell_instance(
        cell_instance,
        cell_type=finalized_cell_type,
        dataset_dir=dataset_dir,
    )
    finalized_test = _finalize_test(
        test,
        cell_instance=finalized_cell_instance,
        dataset_dir=dataset_dir,
    )
    finalized_dataset = _finalize_dataset(
        dataset,
        cell_instance=finalized_cell_instance,
        test=finalized_test,
        dataset_dir=dataset_dir,
    )
    finalized_cell_instance.dataset_ids = _append_unique(finalized_cell_instance.dataset_ids, finalized_dataset.id)
    finalized_test.dataset_ids = _append_unique(finalized_test.dataset_ids, finalized_dataset.id)

    bundle_name = dataset_dir.name
    return (
        BattinfoBundle(
            bundle_name=bundle_name,
            cell_type=finalized_cell_type,
            cell_instance=finalized_cell_instance,
            test=finalized_test,
            dataset=finalized_dataset,
            comment=["Bundle generated for dataset publication."],
        ),
        dataset_dir,
    )


def publish(
    *,
    cell_type: CellType,
    cell_instance: CellInstance,
    test: Test,
    dataset: Dataset,
    cell_specification: CellSpecification | Mapping[str, Any] | PathLike | None = None,
    datasheet_path: PathLike | None = None,
    publish_filename: str = DEFAULT_PUBLISH_FILENAME,
    html_filename: str = "index.html",
    dataset_glob: str = "**/*",
    emit_bundle_dir: bool = False,
    emit_html_page: bool = False,
    emit_ro_crate_metadata: bool = True,
    emit_datacite_metadata: bool = True,
    emit_dcat_export: bool = False,
    ro_crate_filename: str = DEFAULT_RO_CRATE_METADATA_FILENAME,
    datacite_filename: str = DEFAULT_DATACITE_METADATA_FILENAME,
    dcat_filename: str = DEFAULT_DCAT_EXPORT_FILENAME,
    validation_policy: ValidationPolicy | str = PUBLISHER_POLICY,
) -> dict[str, Any]:
    datasheet = _as_path(datasheet_path) if datasheet_path is not None else None
    if datasheet is not None and not datasheet.exists():
        raise FileNotFoundError(f"datasheet does not exist: {datasheet}")

    normalized_cell_specification = (
        _normalize_cell_specification(cell_specification, datasheet_path=datasheet)
        if cell_specification is not None
        else None
    )
    if (
        normalized_cell_specification is not None
        and cell_type.id is not None
        and cell_type.id != _cell_type_iri(normalized_cell_specification.id)
    ):
        raise ValueError("cell_type.id must match the class IRI derived from cell_specification.id when both are provided.")

    bundle, dataset_dir = _finalize_publication_bundle(
        cell_type=cell_type,
        cell_instance=cell_instance,
        test=test,
        dataset=dataset,
        cell_specification=normalized_cell_specification,
    )
    if not dataset_dir.exists():
        raise FileNotFoundError(f"dataset_dir does not exist: {dataset_dir}")

    dataset_files = _discover_dataset_files(dataset_dir, dataset_glob, publish_filename)
    publish_payload = _publication_graph(
        cell_type=bundle.cell_type,
        cell_specification=normalized_cell_specification,
        cell_instance_record=bundle.cell_instance.to_record(),
        test_record=bundle.test.to_record(),
        dataset_record=bundle.dataset.to_record(),
        dataset=bundle.dataset,
        dataset_dir=dataset_dir,
        dataset_files=dataset_files,
        instance_label=bundle.cell_instance.name or dataset_dir.name,
    )
    validation = validate_publication_report(publish_payload, policy=validation_policy)
    if not validation.ok:
        raise ValueError(f"Publication validation failed: {'; '.join(validation.render_errors())}")
    publish_path = dataset_dir / publish_filename
    _write_json(publish_path, publish_payload)

    datacite_path = None
    if emit_datacite_metadata:
        datacite_path = dataset_dir / datacite_filename
        _write_json(datacite_path, _datacite_metadata(bundle.dataset, dataset_dir=dataset_dir))

    dcat_path = None
    if emit_dcat_export:
        dcat_path = dataset_dir / dcat_filename
        _write_json(dcat_path, _dcat_export(bundle.dataset, dataset_dir=dataset_dir, dataset_files=dataset_files))

    ro_crate_path = None
    if emit_ro_crate_metadata:
        ro_crate_path = dataset_dir / ro_crate_filename
        _write_json(
            ro_crate_path,
            _ro_crate_metadata(
                bundle.dataset,
                dataset_dir=dataset_dir,
                dataset_files=dataset_files,
                publish_filename=publish_filename,
                datacite_filename=datacite_filename,
                dcat_filename=dcat_filename if emit_dcat_export else None,
            ),
        )

    result = {
        "status": "ok",
        "generated_at": _now_iso(),
        "dataset_dir": str(dataset_dir),
        "dataset_files": [str(path) for path in dataset_files],
        "publish_path": str(publish_path),
        "triple_count": _triple_count(publish_payload),
        "cell_type_id": bundle.cell_type.id,
        "cell_instance_id": bundle.cell_instance.id,
        "test_id": bundle.test.id,
        "dataset_id": bundle.dataset.id,
        "ro_crate_path": str(ro_crate_path) if ro_crate_path is not None else None,
        "datacite_metadata_path": str(datacite_path) if datacite_path is not None else None,
        "dcat_export_path": str(dcat_path) if dcat_path is not None else None,
    }
    if emit_html_page:
        html_path = save_publication_html(
            publish_payload,
            dataset_dir / html_filename,
            title=bundle.dataset.name or bundle.bundle_name,
        )
        result["html_path"] = str(html_path)
    if normalized_cell_specification is not None:
        result["cell_specification_id"] = normalized_cell_specification.id
    if emit_bundle_dir:
        bundle_with_spec = (
            bundle.model_copy(update={"cell_specification": normalized_cell_specification})
            if normalized_cell_specification is not None
            else bundle
        )
        bundle_dir = bundle_with_spec.to_directory(dataset_dir / "battinfo")
        result["bundle_dir"] = str(bundle_dir)
        result["bundle_manifest_path"] = str(bundle_dir / "bundle.json")
    return result


def build_publication_package(
    *,
    cell_type: CellType,
    cell_instance: CellInstance,
    test: Test,
    dataset: Dataset,
    cell_specification: CellSpecification | Mapping[str, Any] | PathLike | None = None,
    datasheet_path: PathLike | None = None,
    publish_filename: str = DEFAULT_PUBLISH_FILENAME,
    html_filename: str = "index.html",
    dataset_glob: str = "**/*",
    emit_bundle_dir: bool = False,
    emit_html_page: bool = False,
    emit_ro_crate_metadata: bool = True,
    emit_datacite_metadata: bool = True,
    emit_dcat_export: bool = False,
    ro_crate_filename: str = DEFAULT_RO_CRATE_METADATA_FILENAME,
    datacite_filename: str = DEFAULT_DATACITE_METADATA_FILENAME,
    dcat_filename: str = DEFAULT_DCAT_EXPORT_FILENAME,
    validation_policy: ValidationPolicy | str = PUBLISHER_POLICY,
) -> dict[str, Any]:
    """Preferred name for locally building a publication package on disk."""

    return publish(
        cell_type=cell_type,
        cell_instance=cell_instance,
        test=test,
        dataset=dataset,
        cell_specification=cell_specification,
        datasheet_path=datasheet_path,
        publish_filename=publish_filename,
        html_filename=html_filename,
        dataset_glob=dataset_glob,
        emit_bundle_dir=emit_bundle_dir,
        emit_html_page=emit_html_page,
        emit_ro_crate_metadata=emit_ro_crate_metadata,
        emit_datacite_metadata=emit_datacite_metadata,
        emit_dcat_export=emit_dcat_export,
        ro_crate_filename=ro_crate_filename,
        datacite_filename=datacite_filename,
        dcat_filename=dcat_filename,
        validation_policy=validation_policy,
    )


def publish_dataset_metadata(
    *,
    dataset_dirs: list[PathLike],
    staging_root: PathLike,
    cell_type: CellType | Mapping[str, Any] | PathLike | None = None,
    cell_specification: CellSpecification | Mapping[str, Any] | PathLike | None = None,
    datasheet_path: PathLike | None = None,
    test_kind: str = "other",
    protocol_name: str | None = None,
    instrument_name: str | None = None,
    test_status: str | None = "completed",
    instance_name_template: str = "{dataset_key}",
    serial_number_template: str | None = "{dataset_key}",
    batch_id_template: str | None = "{dataset_key}",
    test_name_template: str | None = None,
    dataset_name_template: str | None = None,
    dataset_description_template: str | None = None,
    dataset_license: str | None = None,
    dataset_format: str = "application/vnd.battinfo.dataset-directory",
    publish_filename: str = DEFAULT_PUBLISH_FILENAME,
    html_filename: str = "index.html",
    report_filename: str = DEFAULT_PUBLICATION_REPORT_FILENAME,
    dataset_glob: str = "**/*",
    emit_bundle_dir: bool = False,
    emit_html_page: bool = False,
    validation_policy: ValidationPolicy | str = PUBLISHER_POLICY,
) -> dict[str, Any]:
    staging_root = _as_path(staging_root)
    dataset_dir_paths = [_as_path(path) for path in dataset_dirs]
    datasheet = _as_path(datasheet_path) if datasheet_path is not None else None

    if datasheet is not None and not datasheet.exists():
        raise FileNotFoundError(f"datasheet does not exist: {datasheet}")
    if not dataset_dir_paths:
        raise ValueError("At least one dataset directory must be provided.")
    for dataset_dir in dataset_dir_paths:
        if not dataset_dir.exists():
            raise FileNotFoundError(f"dataset_dir does not exist: {dataset_dir}")

    if cell_specification is None and cell_type is None:
        raise ValueError("Provide either cell_specification or cell_type.")

    normalized_cell_specification = (
        _normalize_cell_specification(cell_specification, datasheet_path=datasheet)
        if cell_specification is not None
        else None
    )
    normalized_cell_type = (
        _normalize_cell_type(cell_type)
        if cell_type is not None
        else _build_cell_type_from_specification(normalized_cell_specification)
    )
    normalized_cell_type = _finalize_cell_type(
        normalized_cell_type,
        cell_specification=normalized_cell_specification,
    )
    if normalized_cell_specification is not None and normalized_cell_type.id != _cell_type_iri(normalized_cell_specification.id):
        raise ValueError("cell_type.id must match the class IRI derived from cell_specification.id when both are provided.")

    report_path = staging_root / report_filename
    shared_root = staging_root / "shared"
    cell_type_path = normalized_cell_type.to_path(shared_root / "cell-type.json")
    type_id = normalized_cell_type.id

    dataset_results: list[dict[str, Any]] = []
    for dataset_dir in dataset_dir_paths:
        dataset_key = dataset_dir.name
        context = {
            "dataset_key": dataset_key,
            "cell_type_id": normalized_cell_type.id,
            "cell_type_name": normalized_cell_type.name,
            "manufacturer": normalized_cell_type.manufacturer,
            "model": normalized_cell_type.model,
            "protocol_name": protocol_name or "test",
            "instrument_name": instrument_name or "",
            "test_kind": test_kind,
        }
        instance_name = _format_template(instance_name_template, context) or dataset_key
        serial_number = _format_template(serial_number_template, context)
        batch_id = _format_template(batch_id_template, context)
        resolved_test_name = _format_template(test_name_template, context) or f"{dataset_key} {protocol_name or 'test'}"
        resolved_dataset_name = (
            _format_template(dataset_name_template, context) or f"{normalized_cell_type.name} dataset {dataset_key}"
        )
        resolved_dataset_description = (
            _format_template(dataset_description_template, context)
            or f"Dataset directory packaged with self-contained BattINFO publication metadata for {normalized_cell_type.name}."
        )

        retrieved_at = _now_unix()
        source = ProvenanceInfo(type="measurement", url=dataset_dir.resolve().as_uri(), retrieved_at=retrieved_at)
        cell_instance = CellInstance(
            name=instance_name,
            cell_type=normalized_cell_type,
            serial_number=serial_number,
            batch_id=batch_id,
            source=source,
            comment=[f"Generated from dataset directory {dataset_dir.name}."],
        )
        test = Test(
            name=resolved_test_name,
            test_kind=test_kind,
            cell=cell_instance,
            status=test_status,
            protocol=ProtocolInfo(name=protocol_name),
            instrument=instrument_name,
            source=source.model_copy(deep=True),
            comment=["Generated from the BattINFO publication helper."],
        )
        dataset = Dataset(
            path=str(dataset_dir),
            name=resolved_dataset_name,
            description=resolved_dataset_description,
            license=dataset_license,
            data_format=dataset_format,
            created_at=retrieved_at,
            cell=cell_instance,
            test=test,
            source=source.model_copy(deep=True),
            comment=["Generated from the BattINFO publication helper."],
        )
        publish_result = publish(
            cell_type=normalized_cell_type,
            cell_specification=normalized_cell_specification,
            cell_instance=cell_instance,
            test=test,
            dataset=dataset,
            publish_filename=publish_filename,
            html_filename=html_filename,
            dataset_glob=dataset_glob,
            emit_bundle_dir=emit_bundle_dir,
            emit_html_page=emit_html_page,
            validation_policy=validation_policy,
        )

        result_entry = {
            "dataset_dir": str(dataset_dir),
            "dataset_files": list(publish_result["dataset_files"]),
            "cell_instance_id": publish_result["cell_instance_id"],
            "test_id": publish_result["test_id"],
            "dataset_id": publish_result["dataset_id"],
            "publish_path": publish_result["publish_path"],
        }
        if emit_html_page:
            result_entry["html_path"] = publish_result["html_path"]
        if emit_bundle_dir:
            result_entry.update(
                {
                    "bundle_dir": publish_result["bundle_dir"],
                    "bundle_manifest_path": publish_result["bundle_manifest_path"],
                    "cell_type_path": str(Path(publish_result["bundle_dir"]) / "cell-type.json"),
                    "cell_instance_path": str(Path(publish_result["bundle_dir"]) / "cell-instance.json"),
                    "test_path": str(Path(publish_result["bundle_dir"]) / "test.json"),
                    "dataset_path": str(Path(publish_result["bundle_dir"]) / "dataset.json"),
                }
            )
            if normalized_cell_specification is not None:
                result_entry["cell_specification_path"] = str(Path(publish_result["bundle_dir"]) / "cell-specification.json")
        dataset_results.append(result_entry)

    report = {
        "status": "ok",
        "generated_at": _now_iso(),
        "staging_root": str(staging_root),
        "cell_type_id": type_id,
        "cell_type_path": str(cell_type_path),
        "dataset_count": len(dataset_results),
        "datasets": dataset_results,
    }
    if datasheet is not None:
        report["datasheet"] = str(datasheet)
    if normalized_cell_specification is not None:
        report["cell_specification_id"] = normalized_cell_specification.id
    _write_json(report_path, report)
    report["report_path"] = str(report_path)
    return report


def publish_cr2032_dataset_metadata(
    *,
    datasheet_path: PathLike = DEFAULT_CR2032_DATASHEET,
    dataset_dirs: list[PathLike] | None = None,
    staging_root: PathLike,
    library_spec_path: PathLike = DEFAULT_CR2032_LIBRARY_SPEC,
    publish_filename: str = DEFAULT_PUBLISH_FILENAME,
    html_filename: str = "index.html",
    report_filename: str = DEFAULT_CR2032_REPORT_FILENAME,
    dataset_glob: str = "**/*",
    emit_bundle_dir: bool = False,
    emit_html_page: bool = False,
    validation_policy: ValidationPolicy | str = PUBLISHER_POLICY,
) -> dict[str, Any]:
    dataset_dir_paths = [_as_path(path) for path in (dataset_dirs or DEFAULT_CR2032_DATASET_DIRS)]
    if not dataset_dir_paths:
        raise ValueError("publish_cr2032_dataset_metadata() requires at least one dataset directory.")
    return publish_dataset_metadata(
        cell_specification=library_spec_path,
        datasheet_path=datasheet_path,
        dataset_dirs=dataset_dir_paths,
        staging_root=staging_root,
        test_kind="capacity_check",
        protocol_name="constant current discharging",
        instrument_name="short Landt cycler",
        test_status="completed",
        instance_name_template="{dataset_key}",
        serial_number_template="{dataset_key}",
        batch_id_template="{dataset_key}",
        test_name_template="{dataset_key} constant current discharging",
        dataset_name_template="{cell_type_name} dataset {dataset_key}",
        dataset_description_template=(
            "Dataset directory packaged with self-contained BattINFO publication metadata for one "
            "{cell_type_name} constant-current discharge run."
        ),
        publish_filename=publish_filename,
        html_filename=html_filename,
        report_filename=report_filename,
        dataset_glob=dataset_glob,
        emit_bundle_dir=emit_bundle_dir,
        emit_html_page=emit_html_page,
        validation_policy=validation_policy,
    )


def load_publication(path: PathLike) -> BattinfoBundle:
    return BattinfoBundle.from_jsonld(path)


def load_publication_package(path: PathLike) -> BattinfoBundle:
    """Preferred name for loading a locally built publication package."""

    return load_publication(path)


__all__ = [
    "DEFAULT_CR2032_DATASET_DIRS",
    "DEFAULT_CR2032_DATASHEET",
    "DEFAULT_CR2032_LIBRARY_SPEC",
    "DEFAULT_DATACITE_METADATA_FILENAME",
    "DEFAULT_DCAT_EXPORT_FILENAME",
    "DEFAULT_CR2032_REPORT_FILENAME",
    "DEFAULT_PUBLISH_FILENAME",
    "DEFAULT_PUBLICATION_REPORT_FILENAME",
    "DEFAULT_REPORT_FILENAME",
    "DEFAULT_RO_CRATE_METADATA_FILENAME",
    "build_publication_package",
    "derive_cell_type",
    "load_publication",
    "load_publication_package",
    "publish",
    "publish_cr2032_dataset_metadata",
    "publish_dataset_metadata",
    "save_publication_html",
]

