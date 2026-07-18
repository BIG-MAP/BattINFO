"""publish_record/publish_batch and the resolver JSON-LD / HTML artifact builders.

Split from the former monolithic ``battinfo/api.py`` (beta-hardening 4.2);
import the public surface from ``battinfo.api``, not from this module.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from battinfo._emmo_instruments import _instrument_node
from battinfo._jsonio import read_record_json as _load_json
from battinfo._jsonio import write_json as _write_json
from battinfo._util import _as_path
from battinfo.api._shared import (
    CELL_IRI_RE,
    DEFAULT_PUBLISH_SOURCES,
    TEST_IRI_RE,
    PathLike,
    _entity_id,
    _iri_tail,
    _logical_entity_type_from_doc,
    _validate_canonical_record,
    _validate_publication_artifact,
)
from battinfo.transform.cell_spec_node import build_cell_spec_node
from battinfo.validate.core import DEFAULT_POLICY, ValidationPolicy


def _schema_identifier_value(value: Any, fallback: str) -> Any:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        property_id = value.get("property_id")
        property_value = value.get("value")
        if isinstance(property_id, str) and isinstance(property_value, str):
            return {
                "@type": "schema:PropertyValue",
                "schema:propertyID": property_id,
                "schema:value": property_value,
            }
    return fallback


def _schema_agent_value(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    agent_type = value.get("type")
    if not isinstance(agent_type, str) or agent_type not in {"Person", "Organization"}:
        agent_type = "Organization"
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    out: dict[str, Any] = {"@type": f"schema:{agent_type}", "schema:name": name}
    if isinstance(value.get("url"), str):
        out["schema:url"] = value["url"]
    if isinstance(value.get("email"), str):
        out["schema:email"] = value["email"]
    if isinstance(value.get("given_name"), str):
        out["schema:givenName"] = value["given_name"]
    if isinstance(value.get("family_name"), str):
        out["schema:familyName"] = value["family_name"]
    if isinstance(value.get("same_as"), str):
        out["schema:sameAs"] = value["same_as"]
    if isinstance(value.get("affiliation"), Mapping):
        nested = _schema_agent_value(value["affiliation"])
        if nested is not None:
            out["schema:affiliation"] = nested
    return out


def _schema_data_catalog_value(value: Any) -> Any:
    if isinstance(value, str):
        return {"@id": value} if "://" in value else value
    if not isinstance(value, Mapping):
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    out: dict[str, Any] = {"@type": "schema:DataCatalog", "schema:name": name}
    if isinstance(value.get("id"), str):
        out["@id"] = value["id"]
    if isinstance(value.get("url"), str):
        out["schema:url"] = value["url"]
    if isinstance(value.get("same_as"), str):
        out["schema:sameAs"] = value["same_as"]
    if isinstance(value.get("description"), str):
        out["schema:description"] = value["description"]
    return out


def _schema_citation_value(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return None
    out: dict[str, Any] = {"@type": "schema:CreativeWork"}
    if isinstance(value.get("url"), str):
        out["@id"] = value["url"]
        out["schema:url"] = value["url"]
    if isinstance(value.get("name"), str):
        out["schema:name"] = value["name"]
    if isinstance(value.get("kind"), str):
        out["schema:additionalType"] = value["kind"]
    identifiers: list[Any] = []
    if isinstance(value.get("doi"), str):
        # Standard form (no battinfo: predicate): a typed PropertyValue identifier.
        identifiers.append(
            {
                "@type": "schema:PropertyValue",
                "schema:propertyID": "doi",
                "schema:value": value["doi"],
            }
        )
    if isinstance(value.get("citation_key"), str):
        identifiers.append(value["citation_key"])
    if identifiers:
        out["schema:identifier"] = identifiers[0] if len(identifiers) == 1 else identifiers
    return out if len(out) > 1 else None


def _schema_variable_measured_value(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    out: dict[str, Any] = {"@type": "schema:PropertyValue", "schema:name": name}
    if isinstance(value.get("description"), str):
        out["schema:description"] = value["description"]
    if isinstance(value.get("unit_text"), str):
        out["schema:unitText"] = value["unit_text"]
    same_as = value.get("same_as")
    if isinstance(same_as, str):
        out["schema:sameAs"] = same_as
        out["schema:propertyID"] = same_as
    return out


def _schema_distribution_value(value: Any, *, part_of_id: str) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    content_url = value.get("content_url")
    encoding_format = value.get("encoding_format")
    checksum = value.get("checksum")
    if (
        not isinstance(content_url, str)
        and not isinstance(encoding_format, str)
        and not isinstance(checksum, Mapping)
    ):
        return None
    if not (
        isinstance(checksum, Mapping)
        and isinstance(checksum.get("algorithm"), str)
        and checksum["algorithm"].lower() == "sha256"
        and isinstance(checksum.get("value"), str)
    ):
        return None
    out: dict[str, Any] = {"@type": "schema:DataDownload"}
    if isinstance(value.get("name"), str):
        out["schema:name"] = value["name"]
    if isinstance(value.get("description"), str):
        out["schema:description"] = value["description"]
    if isinstance(content_url, str):
        out["schema:contentUrl"] = content_url
    if isinstance(encoding_format, str):
        out["schema:encodingFormat"] = encoding_format
    if isinstance(value.get("contentSize"), str):
        out["schema:contentSize"] = value["contentSize"]
    if isinstance(value.get("accessLevel"), str):
        out["schema:accessLevel"] = value["accessLevel"]
    out["schema:isPartOf"] = {"@id": part_of_id}
    out["schema:sha256"] = checksum["value"]
    return out


def _schema_table_column_value(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    out: dict[str, Any] = {
        "@type": "csvw:Column",
        "csvw:name": name,
    }
    titles = value.get("titles")
    if isinstance(titles, str):
        out["csvw:titles"] = titles
    elif isinstance(titles, list):
        title_values = [item for item in titles if isinstance(item, str)]
        if title_values:
            out["csvw:titles"] = title_values
    if isinstance(value.get("description"), str):
        out["schema:description"] = value["description"]
    if isinstance(value.get("datatype"), str):
        out["csvw:datatype"] = value["datatype"]
    if isinstance(value.get("unit_text"), str):
        out["schema:unitText"] = value["unit_text"]
    same_as = value.get("same_as")
    if isinstance(same_as, str):
        out["schema:sameAs"] = same_as
        out["schema:propertyID"] = same_as
    required = value.get("required")
    if isinstance(required, bool):
        out["csvw:required"] = required
    return out


def _schema_table_schema_value(value: Any) -> dict[str, Any] | str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return None
    columns = value.get("columns")
    if not isinstance(columns, list):
        return None
    column_nodes = [column for item in columns if (column := _schema_table_column_value(item)) is not None]
    if not column_nodes:
        return None
    out: dict[str, Any] = {
        "@type": "csvw:Schema",
        "csvw:column": column_nodes,
    }
    if isinstance(value.get("id"), str):
        out["@id"] = value["id"]
    if isinstance(value.get("name"), str):
        out["schema:name"] = value["name"]
    if isinstance(value.get("description"), str):
        out["schema:description"] = value["description"]
    primary_key = value.get("primary_key") or value.get("primaryKey")
    if isinstance(primary_key, str):
        out["csvw:primaryKey"] = primary_key
    elif isinstance(primary_key, list):
        values = [item for item in primary_key if isinstance(item, str)]
        if values:
            out["csvw:primaryKey"] = values
    return out


def _schema_main_entity_value(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    node_type = value.get("type")
    if isinstance(node_type, str) and ":" in node_type:
        node_type = node_type.split(":", 1)[1]
    if node_type == "Table":
        url = value.get("url")
        table_schema = value.get("table_schema") or value.get("tableSchema")
        resolved_table_schema = _schema_table_schema_value(table_schema)
        if not isinstance(url, str) or resolved_table_schema is None:
            return None
        out: dict[str, Any] = {
            "@type": "csvw:Table",
            "csvw:url": url,
            "csvw:tableSchema": resolved_table_schema,
        }
        if isinstance(value.get("id"), str):
            out["@id"] = value["id"]
        if isinstance(value.get("name"), str):
            out["schema:name"] = value["name"]
        if isinstance(value.get("description"), str):
            out["schema:description"] = value["description"]
        return out
    if node_type == "TableGroup":
        table_items = value.get("tables") or value.get("table")
        if not isinstance(table_items, list):
            return None
        tables = [table for item in table_items if (table := _schema_main_entity_value(item)) is not None]
        if not tables:
            return None
        out = {
            "@type": "csvw:TableGroup",
            "csvw:table": tables,
        }
        if isinstance(value.get("id"), str):
            out["@id"] = value["id"]
        if isinstance(value.get("url"), str):
            out["csvw:url"] = value["url"]
        if isinstance(value.get("name"), str):
            out["schema:name"] = value["name"]
        if isinstance(value.get("description"), str):
            out["schema:description"] = value["description"]
        return out
    return None




_PYBAMM_STEP_EMMO_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^\s*(discharge|rest|charge|hold)\s+at\s+\S+\s+[acwv]", re.I), ""),  # router
    (re.compile(r"^\s*discharge\s+at\s+\S+\s+[cw]", re.I), "ConstantCurrentDischarging"),
    (re.compile(r"^\s*discharge\s+at\s+\S+\s+a\b", re.I), "ConstantCurrentDischarging"),
    (re.compile(r"^\s*charge\s+at\s+\S+\s+[caw]\s+until\s+\S+\s+[va]\b", re.I), "ConstantCurrentConstantVoltageCharging"),
    (re.compile(r"^\s*charge\s+at\s+\S+\s+[cw]", re.I), "ConstantCurrentCharging"),
    (re.compile(r"^\s*charge\s+at\s+\S+\s+a\b", re.I), "ConstantCurrentCharging"),
    (re.compile(r"^\s*hold\s+at\s+\S+\s+v\b", re.I), "ConstantVoltageCharging"),
    (re.compile(r"^\s*rest\b", re.I), "Resting"),
]


def _pybamm_step_emmo_type(step_text: str) -> str | None:
    """Return the EMMO electrochemistry process class for a PyBaMM step string, or None."""
    t = step_text.strip().lower()
    if t.startswith("rest"):
        return "Resting"
    if t.startswith("hold at") and " v" in t:
        return "ConstantVoltageCharging"
    if t.startswith("discharge"):
        return "ConstantCurrentDischarging"
    if t.startswith("charge"):
        # CC-CV if the step has a current condition AND a voltage cut-off
        if re.search(r"until\s+\S+\s*v\b", t):
            return "ConstantCurrentConstantVoltageCharging"
        return "ConstantCurrentCharging"
    return None


def _pybamm_step_to_jsonld(step_text: str, position: int) -> dict[str, Any]:
    """Convert a single PyBaMM experiment step string to a schema:HowToStep node.

    The step text is stored verbatim so it can be fed directly back into
    pybamm.Experiment(steps).  The EMMO type is added when it can be
    determined unambiguously from the step text.
    """
    emmo_type = _pybamm_step_emmo_type(step_text)
    node_type: str | list[str] = (
        ["schema:HowToStep", emmo_type] if emmo_type else "schema:HowToStep"
    )
    return {
        "@type": node_type,
        "schema:position": position,
        "schema:text": step_text,
    }


def _resolver_jsonld(doc: dict[str, Any]) -> dict[str, Any]:
    entity_iri = _entity_id(doc)
    _, uid = _iri_tail(entity_iri)
    entity_type = _logical_entity_type_from_doc(doc)
    # csvw: is used by _schema_main_entity_value helpers called from the dataset block.
    # battinfo: is the fallback-term prefix used by unmapped-property quantity nodes
    # (dcterms:/prov: for the provenance node already resolve via the remote context).
    context = [
        "https://w3id.org/emmo/domain/battery/context",
        {
            "schema": "https://schema.org/",
            "csvw": "http://www.w3.org/ns/csvw#",
            "battinfo": "https://w3id.org/battinfo/",
            "skos": "http://www.w3.org/2004/02/skos/core#",
        },
    ]

    if entity_type == "cell-spec":
        # Shared canonical builder — the same node the Zenodo/local publication
        # graph emits, so resolver and package spec nodes are byte-identical.
        out: dict[str, Any] = {"@context": context, **build_cell_spec_node(doc)}
        return out

    if entity_type == "cell":
        inst = doc["cell_instance"]
        out = {
            "@context": context,
            "@id": entity_iri,
            "@type": ["BatteryCell", "schema:IndividualProduct"],
            "schema:identifier": uid,
            "hasDescription": {"@id": inst.get("cell_spec_id")},
            "schema:isVariantOf": {"@id": inst.get("cell_spec_id")},
        }
        if inst.get("serial_number"):
            out["schema:serialNumber"] = inst.get("serial_number")
        datasets: list[dict[str, str]] = []
        for dataset in doc.get("datasets", []):
            if isinstance(dataset, Mapping) and isinstance(dataset.get("id"), str):
                datasets.append({"@id": dataset["id"]})
        if datasets:
            out["schema:workExample"] = datasets
        return out

    if entity_type == "test-protocol":
        protocol = doc["test_spec"]
        out = {
            "@context": context,
            "@id": entity_iri,
            "@type": ["ElectrochemicalTestingProcedure", "schema:HowTo"],
            "schema:identifier": uid,
            "schema:name": protocol.get("name"),
        }
        if protocol.get("description"):
            out["schema:description"] = protocol.get("description")
        if protocol.get("protocol_url"):
            out["schema:url"] = protocol.get("protocol_url")
        if protocol.get("version"):
            out["schema:version"] = protocol.get("version")
        steps = protocol.get("steps")
        if isinstance(steps, list) and steps:
            step_nodes = [
                _pybamm_step_to_jsonld(step_text, position=i + 1)
                for i, step_text in enumerate(steps)
            ]
            out["schema:step"] = step_nodes
        cycles = protocol.get("cycles")
        if isinstance(cycles, int) and cycles > 1:
            out["schema:repeatCount"] = cycles
        return out

    if entity_type == "test":
        test = doc["test"]
        cell_ref = {"@id": test.get("cell_id")}
        out = {
            "@context": context,
            "@id": entity_iri,
            "@type": ["BatteryTest", "schema:Action", "prov:Activity"],
            "schema:identifier": uid,
            "schema:name": test.get("name"),
            # EMMO-native: the battery cell is an input to the test
            "hasTestObject": cell_ref,
            # schema.org alignment
            "schema:object": cell_ref,
        }
        if test.get("description"):
            out["schema:description"] = test.get("description")
        if test.get("status"):
            out["schema:actionStatus"] = test.get("status")
        if isinstance(test.get("protocol_id"), str):
            protocol_ref = {"@id": test["protocol_id"]}
            out["schema:instrument"] = protocol_ref
        instrument_name = test.get("instrument_name")
        equipment_id = test.get("equipment_id")
        if isinstance(instrument_name, str) and instrument_name:
            equip_node = _instrument_node(instrument_name)
            if isinstance(equipment_id, str) and equipment_id:
                # Registered equipment: the node carries its canonical IRI so the
                # instrument is a resolvable entity, not an anonymous label.
                equip_node["@id"] = equipment_id
            out["hasTestEquipment"] = equip_node
            out["schema:instrument"] = [out.get("schema:instrument"), equip_node] if "schema:instrument" in out else equip_node
        elif isinstance(equipment_id, str) and equipment_id:
            equip_node = {"@id": equipment_id}
            out["hasTestEquipment"] = equip_node
            out["schema:instrument"] = [out.get("schema:instrument"), equip_node] if "schema:instrument" in out else equip_node
        channel_id = test.get("channel_id")
        if isinstance(channel_id, str) and channel_id:
            # The channel the test ran on: the activity used that equipment part.
            out["prov:used"] = {"@id": channel_id}
        datasets = test.get("dataset_ids")
        if isinstance(datasets, list):
            refs = [{"@id": did} for did in datasets if isinstance(did, str)]
            if refs:
                result = refs[0] if len(refs) == 1 else refs
                out["hasOutput"] = result
                out["schema:result"] = result
        return out

    if entity_type == "dataset":
        dataset = doc["dataset"]
        distribution = dataset.get("distributions") or dataset.get("distribution")
        encoding_format = None
        if isinstance(distribution, list):
            for entry in distribution:
                if isinstance(entry, Mapping) and isinstance(entry.get("encoding_format"), str):
                    encoding_format = entry.get("encoding_format")
                    break
        out = {
            "@context": context,
            "@id": entity_iri,
            "@type": "schema:Dataset",
            "schema:identifier": _schema_identifier_value(dataset.get("identifier"), uid),
            "schema:name": dataset.get("name") or dataset.get("title"),
            "schema:description": dataset.get("description"),
            "schema:license": dataset.get("license"),
            "schema:encodingFormat": encoding_format or dataset.get("format"),
        }
        if dataset.get("access_url"):
            out["schema:url"] = dataset.get("access_url")
        if isinstance(dataset.get("same_as"), list):
            same_as = [item for item in dataset["same_as"] if isinstance(item, str)]
            if same_as:
                out["schema:sameAs"] = same_as
        if isinstance(dataset.get("additional_type"), list):
            additional_type = [item for item in dataset["additional_type"] if isinstance(item, str)]
            if additional_type:
                out["schema:additionalType"] = additional_type
        if isinstance(dataset.get("version"), str):
            out["schema:version"] = dataset["version"]
        if isinstance(dataset.get("keywords"), list):
            keywords = [item for item in dataset["keywords"] if isinstance(item, str)]
            if keywords:
                out["schema:keywords"] = keywords
        creator_value = dataset.get("creators")
        if isinstance(creator_value, list):
            creators = [node for item in creator_value if (node := _schema_agent_value(item)) is not None]
            if creators:
                out["schema:creator"] = creators
        elif isinstance(creator_value, Mapping):
            creator = _schema_agent_value(creator_value)
            if creator is not None:
                out["schema:creator"] = creator
        publisher = _schema_agent_value(dataset.get("publisher"))
        if publisher is not None:
            out["schema:publisher"] = publisher
        funder_value = dataset.get("funders")
        if isinstance(funder_value, list):
            funders = [node for item in funder_value if (node := _schema_agent_value(item)) is not None]
            if funders:
                out["schema:funder"] = funders
        elif isinstance(funder_value, Mapping):
            funder = _schema_agent_value(funder_value)
            if funder is not None:
                out["schema:funder"] = funder
        citation_value = dataset.get("citations")
        if isinstance(citation_value, list):
            citations = [node for item in citation_value if (node := _schema_citation_value(item)) is not None]
            if citations:
                out["schema:citation"] = citations
        else:
            citation = _schema_citation_value(citation_value)
            if citation is not None:
                out["schema:citation"] = citation
        if isinstance(dataset.get("measurement_techniques"), list):
            values = [item for item in dataset["measurement_techniques"] if isinstance(item, str)]
            if values:
                out["schema:measurementTechnique"] = values
        if isinstance(dataset.get("measurement_methods"), list):
            values = [item for item in dataset["measurement_methods"] if isinstance(item, str)]
            if values:
                out["schema:measurementMethod"] = values
        if isinstance(dataset.get("variable_measured"), list):
            values = [node for item in dataset["variable_measured"] if (node := _schema_variable_measured_value(item)) is not None]
            if values:
                out["schema:variableMeasured"] = values
        if isinstance(dataset.get("is_accessible_for_free"), bool):
            out["schema:isAccessibleForFree"] = dataset["is_accessible_for_free"]
        if isinstance(dataset.get("conditions_of_access"), str):
            out["schema:conditionsOfAccess"] = dataset["conditions_of_access"]
        if isinstance(dataset.get("in_language"), str):
            out["schema:inLanguage"] = dataset["in_language"]
        if dataset.get("created_at") is not None:
            out["schema:dateCreated"] = dataset["created_at"]
        if dataset.get("modified_at") is not None:
            out["schema:dateModified"] = dataset["modified_at"]
        if dataset.get("published_at") is not None:
            out["schema:datePublished"] = dataset["published_at"]
        if isinstance(dataset.get("temporal_coverage"), str):
            out["schema:temporalCoverage"] = dataset["temporal_coverage"]
        if isinstance(dataset.get("spatial_coverage"), str):
            out["schema:spatialCoverage"] = dataset["spatial_coverage"]
        if isinstance(dataset.get("is_based_on"), list):
            refs = [{"@id": item} for item in dataset["is_based_on"] if isinstance(item, str)]
            if refs:
                out["schema:isBasedOn"] = refs
        included_in_data_catalog = dataset.get("included_in_data_catalog")
        included_in_data_catalog_value = _schema_data_catalog_value(included_in_data_catalog)
        if included_in_data_catalog_value is not None:
            out["schema:includedInDataCatalog"] = included_in_data_catalog_value
        if isinstance(distribution, list):
            values = [
                node
                for item in distribution
                if (node := _schema_distribution_value(item, part_of_id=entity_iri)) is not None
            ]
            if values:
                out["schema:distribution"] = values
        main_entity = dataset.get("main_entity")
        if isinstance(main_entity, list):
            values = [node for item in main_entity if (node := _schema_main_entity_value(item)) is not None]
            if values:
                out["schema:mainEntity"] = values
        elif isinstance(main_entity, Mapping):
            value = _schema_main_entity_value(main_entity)
            if value is not None:
                out["schema:mainEntity"] = value
        about = dataset.get("about")
        if isinstance(about, list):
            about_nodes = [{"@id": item} for item in about if isinstance(item, str) and (CELL_IRI_RE.fullmatch(item) or TEST_IRI_RE.fullmatch(item))]
            if about_nodes:
                out["schema:about"] = about_nodes
        else:
            related = dataset.get("related_entities", {})
            if isinstance(related, Mapping):
                cells = related.get("cell_ids")
                if isinstance(cells, list):
                    cell_nodes = [{"@id": cell_id} for cell_id in cells if isinstance(cell_id, str)]
                    if cell_nodes:
                        out["schema:about"] = cell_nodes
        return out

    raise ValueError(f"Unsupported entity type '{entity_type}' for {entity_iri}.")


def _resolver_html(doc: dict[str, Any]) -> str:
    entity_iri = _entity_id(doc)
    entity_type, uid = _iri_tail(entity_iri)
    pretty = html.escape(json.dumps(doc, indent=2, ensure_ascii=False))
    title = html.escape(f"BattINFO {entity_type} {uid}")
    iri_escaped = html.escape(entity_iri)
    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\" />\n"
        f"  <title>{title}</title>\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
        "  <style>body{font-family:Arial,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;line-height:1.5}"
        "code,pre{background:#f6f8fa;border-radius:4px}pre{padding:1rem;overflow:auto}"
        "a{color:#0b5fff;text-decoration:none}a:hover{text-decoration:underline}</style>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{title}</h1>\n"
        f"  <p><strong>Canonical IRI:</strong> <code>{iri_escaped}</code></p>\n"
        "  <p>\n"
        "    <a href=\"index.json\">JSON</a> |\n"
        "    <a href=\"index.jsonld\">JSON-LD</a>\n"
        "  </p>\n"
        "  <h2>Metadata</h2>\n"
        f"  <pre>{pretty}</pre>\n"
        "</body>\n"
        "</html>\n"
    )


def publish_record(
    record: dict[str, Any] | PathLike,
    *,
    target_root: PathLike = ".battinfo/resolver-site",
    build_jsonld: bool = True,
    build_html: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    """Publish one canonical resource into resolver-ready static artifacts."""
    doc = _load_json(_as_path(record)) if isinstance(record, (str, Path)) else record
    if validate:
        _validate_canonical_record(doc, policy=validation_policy)

    iri = _entity_id(doc)
    namespace, uid = _iri_tail(iri)
    logical_type = _logical_entity_type_from_doc(doc)
    out_dir = _as_path(target_root) / namespace / uid
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    _write_json(out_dir / "index.json", doc)
    written.append(str(out_dir / "index.json"))
    if build_jsonld:
        resolver_payload = _resolver_jsonld(doc)
        if validate:
            _validate_publication_artifact(resolver_payload, policy=validation_policy)
        _write_json(out_dir / "index.jsonld", resolver_payload)
        written.append(str(out_dir / "index.jsonld"))
    if build_html:
        (out_dir / "index.html").write_text(_resolver_html(doc), encoding="utf-8")
        written.append(str(out_dir / "index.html"))

    return {
        "status": "published",
        "id": iri,
        "entity_type": logical_type,
        "uid": uid,
        "output_dir": str(out_dir),
        "files": written,
    }


def publish_batch(
    *,
    source_dirs: Sequence[PathLike] = DEFAULT_PUBLISH_SOURCES,
    target_root: PathLike = ".battinfo/resolver-site",
    glob: str = "*.json",
    build_jsonld: bool = True,
    build_html: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    """Publish a deterministic batch of canonical resources."""
    failures: list[dict[str, str]] = []
    published = 0
    processed = 0

    for src_dir in source_dirs:
        src_path = _as_path(src_dir)
        if not src_path.exists():
            continue
        for path in sorted(src_path.glob(glob)):
            processed += 1
            try:
                publish_record(
                    path,
                    target_root=target_root,
                    build_jsonld=build_jsonld,
                    build_html=build_html,
                    validate=validate,
                    validation_policy=validation_policy,
                )
                published += 1
            except Exception as exc:  # noqa: BLE001
                failures.append({"file": str(path), "error": str(exc)})

    return {
        "status": "ok" if not failures else "partial",
        "processed": processed,
        "published": published,
        "failed": len(failures),
        "failures": failures,
    }
