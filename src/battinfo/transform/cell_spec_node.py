"""Canonical BatteryCellSpecification JSON-LD node builder (emitter convergence).

One builder produces the cell-spec node used by BOTH publication emitters:

- the resolver artifact path (``battinfo.api`` ``publish_record`` -> ``index.jsonld``)
- the Zenodo / local publication graph (``AuthoringWorkspace._assemble_zenodo_jsonld``
  and ``publication.build_publication_package``)

so the two paths emit byte-identical spec nodes for the same canonical record.

The node shape is the canonical target shape:

- ``@type: ["BatteryCellSpecification", "schema:CreativeWork"]`` — the spec is an
  information artifact, not a physical battery.
- ``isDescriptionFor.@type`` carries the physical EMMO class stack derived from the
  descriptors (format / chemistry / electrode bases / IEC code / rechargeable) via
  ``entity_type_map.json`` — chemistry and format are expressed through @type
  stacking, not as literal predicates.
- Quantities use the EMMO ``hasProperty`` pattern via
  :func:`battinfo.transform.json_to_jsonld._descriptor_quantity_node`
  (list ``@type`` of ``[PropertyClass, co-type]``, ``hasNumericalPart`` typed
  ``RealData``, ``hasMeasurementUnit`` as a bare unit IRI).
- Provenance uses standard vocabularies only (dcterms / PROV-O) — no new
  ``battinfo:`` terms are minted.
"""
from __future__ import annotations

import json
import warnings
from functools import lru_cache
from importlib import resources
from typing import Any, Mapping

from battinfo.transform.json_to_jsonld import (
    _descriptor_quantity_node,
    _entity_mapping,
    _epoch_to_iso8601,
    _load_mapping_file,
    _property_type_map,
    _property_type_term,
)

# Public registry page for a cell spec (human-resolvable mirror of the IRI).
REGISTRY_SPEC_URL_BASE = "https://www.battery-genome.org/registry/spec/"

_COMPACT_PREFIXES: tuple[tuple[str, str], ...] = (
    ("battery:", "https://w3id.org/emmo/domain/battery#"),
    ("electrochemistry:", "https://w3id.org/emmo/domain/electrochemistry#"),
    ("emmo:", "https://w3id.org/emmo#"),
)


def compact_iri(iri: str) -> str:
    """Shorten a full EMMO-family IRI to its compact (prefixed) form."""
    for prefix, base in _COMPACT_PREFIXES:
        if iri.startswith(base):
            return prefix + iri[len(base):]
    return iri


@lru_cache(maxsize=1)
def _domain_battery_context() -> dict[str, Any]:
    """The bundled copy of the https://w3id.org/emmo/domain/battery/context terms."""
    path = resources.files("battinfo").joinpath("data", "context", "domain-battery.context.json")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    context = data.get("@context", data)
    return context if isinstance(context, dict) else {}


# Core classes emitted by the builders whose prefLabels must resolve in an inline
# (records) context.  The kept static table mirrors the table formerly maintained
# inline in AuthoringWorkspace._assemble_zenodo_jsonld.
_STATIC_LABEL_TO_COMPACT: dict[str, str] = {
    "BatteryTest":             "battery:battery_dca7729a_421a_4921_90cf_9692bb9eb081",
    "BatteryCell":             "battery:battery_68ed592a_7924_45d0_a108_94d6275d57f0",
    "BatteryCellSpecification": "battery:battery_1cfbba6c_8824_4932_a23e_2141483acef7",
    "CylindricalBattery":      "battery:battery_ac604ecd_cc60_4b98_b57c_74cd5d3ccd40",
    "PrismaticBattery":        "battery:battery_86c9ca80_de6f_417f_afdc_a7e52fa6322d",
    "PouchCell":               "battery:battery_392b3f47_d62a_4bd4_a819_b58b09b8843a",
    "CoinCell":                "battery:battery_b7fdab58_6e91_4c84_b097_b06eff86a124",
    "LithiumIonBattery":                   "battery:battery_96addc62_ea04_449a_8237_4cd541dd8e5f",
    "LithiumMetalBattery":                 "battery:battery_ada13509_4eed_4e40_a7b1_4cc488144154",
    "SodiumIonBattery":                    "battery:battery_42329a95_03fe_4ec1_83cb_b7e8ed52f68a",
    "AlkalineZincManganeseDioxideBattery": "battery:battery_b572826a_b4e4_4986_b57d_f7b945061f8b",
    "AlkalineCell":                        "battery:battery_50b911f7_c903_4700_9764_c308d8a95470",
    "PrimaryBattery":                      "battery:battery_3b0b0d6e_8b0e_4491_885e_8421d3eb3b69",
    "SecondaryBattery":                    "battery:battery_efc38420_ecbb_42e4_bb3f_208e7c417098",
    # IEC standard size codes — subclasses already defined in domain-battery
    "LR03":   "battery:battery_a5299801_2a8d_4d03_a476_ca2c5e9ca702",  # AAA alkaline
    "LR6":    "battery:battery_6b2540b9_5af6_478a_81ae_583db9636db8",  # AA alkaline
    "LR14":   "battery:battery_d00e842e_ee0b_4e25_bd17_d64d76d69730",  # C alkaline
    "LR20":   "battery:battery_0c9979c2_c981_48ea_a8e1_72bdcb58fd58",  # D alkaline
    "LR1":    "battery:battery_1c0306f5_5698_4874_b6ce_e5cc45a46b91",  # N alkaline
    "CR2032": "battery:battery_b61b96ac_f2f4_4b74_82d5_565fe3a2d88b",  # coin
    "CR2025": "battery:battery_9984642f_c9dc_4b98_94f6_6ffe20cfc014",  # coin
    "LR44":   "battery:battery_d10ff656_f9fd_4b0e_9de9_4812a44ea359",  # button
    "HR6":    "battery:battery_a71a4bf2_dee6_4aa4_8ad4_9f38c261fb84",  # AA NiMH
    "KR6":    "battery:battery_ad7c1d81_9a9f_4174_88ea_3ba3e8f4dbe2",  # AA NiCd
}

# Structure / co-type terms emitted by the shared quantity-node builder that are
# not part of the records context; resolved from the bundled domain-battery context.
_EXTRA_CONTEXT_TERMS: tuple[str, ...] = (
    "RealData",
    "ConventionalProperty",
    "MeasuredProperty",
    "NominalProperty",
    "hasMeasurementParameter",
)


@lru_cache(maxsize=1)
def label_to_compact() -> dict[str, Any]:
    """prefLabel/term -> compact-IRI table for inline JSON-LD contexts.

    Combines (in order): the static core-class table, curated property-class
    prefLabels, curated unit prefLabels, every ``entity_type_map.json``
    ``battery_types`` class resolvable in the bundled domain-battery context, and
    the quantity-node structure terms (``RealData`` etc.).

    Used both to extend the inline publication context and as the "is this class
    context-mappable?" filter for :func:`physical_type_stack`.
    """
    table: dict[str, Any] = dict(_STATIC_LABEL_TO_COMPACT)
    for m in _load_mapping_file("property_map.curated.json").get("mappings", []):
        if m.get("class_iri") and m.get("class_pref_label"):
            table[m["class_pref_label"]] = compact_iri(m["class_iri"])
    for m in _load_mapping_file("unit_map.curated.json").get("mappings", []):
        if m.get("symbol") and m.get("unit_iri") and m.get("unit_pref_label"):
            table[m["unit_pref_label"]] = compact_iri(m["unit_iri"])
    db_context = _domain_battery_context()

    def _resolve(term: str) -> None:
        if term in table:
            return
        value = db_context.get(term)
        if isinstance(value, str):
            table[term] = compact_iri(value)
        elif isinstance(value, Mapping) and isinstance(value.get("@id"), str):
            resolved = dict(value)
            resolved["@id"] = compact_iri(resolved["@id"])
            table[term] = resolved

    for section in _load_mapping_file("entity_type_map.json").get("mappings", {}).values():
        if not isinstance(section, Mapping):
            continue
        for entry in section.values():
            if not isinstance(entry, Mapping):
                continue
            for battery_type in entry.get("battery_types", []):
                if isinstance(battery_type, str):
                    _resolve(battery_type)
    for term in _EXTRA_CONTEXT_TERMS:
        _resolve(term)
    return table


def physical_type_stack(cell_spec: Mapping[str, Any]) -> list[str]:
    """domain-battery class prefLabels describing the physical cell for a spec.

    entity_type_map-driven: format, chemistry, positive/negative electrode basis
    and IEC code each contribute their ``battery_types``; ``rechargeable`` maps to
    SecondaryBattery / PrimaryBattery. Only classes that are context-mappable
    (present in :func:`label_to_compact`) are kept, so every emitted ``@type``
    resolves in both the remote and the inline publication contexts.
    """
    table = label_to_compact()
    types: list[str] = []
    for section, key in (
        ("format", cell_spec.get("cell_format")),
        ("chemistry", cell_spec.get("chemistry")),
        ("positive_electrode_basis", cell_spec.get("positive_electrode_basis")),
        ("negative_electrode_basis", cell_spec.get("negative_electrode_basis")),
        ("iec_code", cell_spec.get("iec_code")),
    ):
        entry = _entity_mapping(section, key) or {}
        for battery_type in entry.get("battery_types", []):
            if battery_type not in types and battery_type in table:
                types.append(battery_type)
    if not types:
        types.append("BatteryCell")
    rechargeable = cell_spec.get("rechargeable")
    if rechargeable is True and "SecondaryBattery" not in types:
        types.append("SecondaryBattery")
    elif rechargeable is False and "PrimaryBattery" not in types:
        types.append("PrimaryBattery")
    return types


def provenance_node(provenance: Any) -> dict[str, Any] | None:
    """A record ``provenance`` block -> a standard-vocabulary provenance node.

    Standard terms only (no minted ``battinfo:`` predicates): source_type ->
    ``dcterms:type``, source_url -> ``prov:hadPrimarySource``, retrieved_at ->
    ``prov:generatedAtTime`` (ISO-8601), citation -> ``dcterms:bibliographicCitation``.
    Returns ``None`` when there is nothing to emit.
    """
    if not isinstance(provenance, Mapping):
        return None
    node: dict[str, Any] = {"@type": "prov:Entity"}
    if provenance.get("source_type"):
        node["dcterms:type"] = provenance["source_type"]
    if provenance.get("source_url"):
        node["prov:hadPrimarySource"] = {"@id": provenance["source_url"]}
    retrieved_at = provenance.get("retrieved_at")
    retrieved_iso = _epoch_to_iso8601(retrieved_at)
    if retrieved_iso is not None:
        node["prov:generatedAtTime"] = retrieved_iso
    elif isinstance(retrieved_at, str) and retrieved_at:
        node["prov:generatedAtTime"] = retrieved_at
    if provenance.get("citation"):
        node["dcterms:bibliographicCitation"] = provenance["citation"]
    return node if len(node) > 1 else None


def cell_spec_property_nodes(
    properties: Any, *, context_label: str = ""
) -> list[dict[str, Any]]:
    """EMMO ``hasProperty`` nodes for a cell-spec ``properties`` mapping.

    Emits the shared quantity-node shape and warns (never silently) at the two
    lossy edges: a key without a curated EMMO mapping is emitted with a
    non-canonical ``battinfo:`` fallback term (``semantic.property_unmapped``),
    and a quantity carrying only ``value_text`` emits no numeric part
    (``semantic.value_text_only``).
    """
    nodes: list[dict[str, Any]] = []
    if not isinstance(properties, Mapping):
        return nodes
    where = f" on {context_label}" if context_label else ""
    for key, quantity in properties.items():
        if not isinstance(quantity, Mapping):
            continue
        if key not in _property_type_map():
            warnings.warn(
                f"semantic.property_unmapped: '{key}'{where} has no curated EMMO "
                f"mapping - it is emitted with the non-canonical fallback term "
                f"'{_property_type_term(str(key))}' in the exported JSON-LD and will "
                "not survive a round-trip import. File a mapping in "
                "assets/mappings/domain-battery/property_map.curated.json.",
                stacklevel=2,
            )
        has_number = any(
            isinstance(quantity.get(field), (int, float)) and not isinstance(quantity.get(field), bool)
            for field in ("value", "typical_value")
        )
        if not has_number and isinstance(quantity.get("value_text"), str):
            warnings.warn(
                f"semantic.value_text_only: '{key}'{where} carries only value_text - "
                "the JSON-LD export emits no numeric quantity value for it.",
                stacklevel=2,
            )
        node = _descriptor_quantity_node(
            str(key), quantity if isinstance(quantity, dict) else dict(quantity)
        )
        if node is not None:
            nodes.append(node)
    return nodes


def _iri_tail(iri: str) -> str:
    return iri.rstrip("/").split("/")[-1] if iri else ""


def build_cell_spec_node(record: Mapping[str, Any]) -> dict[str, Any]:
    """Build the canonical BatteryCellSpecification JSON-LD node for a record.

    ``record`` is a canonical on-disk cell-spec record dict (``cell_spec`` +
    ``properties`` + ``provenance``). Returns the node WITHOUT an ``@context``;
    callers wrap it (resolver) or place it into a ``@graph`` (publication package).
    """
    cell = record.get("cell_spec")
    if not isinstance(cell, Mapping):
        cell = {}
    iri = cell.get("id") or ""
    tail = _iri_tail(str(iri))
    manufacturer = cell.get("manufacturer")
    manufacturer_name = (
        manufacturer.get("name") if isinstance(manufacturer, Mapping) else manufacturer
    )

    node: dict[str, Any] = {
        "@type": ["BatteryCellSpecification", "schema:CreativeWork"],
    }
    if iri:
        node["@id"] = iri
    if tail:
        node["schema:identifier"] = tail
    name = cell.get("name") or cell.get("model") or cell.get("model_name")
    if name:
        node["schema:name"] = name
    if cell.get("model"):
        node["schema:model"] = cell["model"]
    if manufacturer_name:
        node["schema:manufacturer"] = {
            "@type": "schema:Organization",
            "schema:name": manufacturer_name,
        }
    if tail:
        node["schema:url"] = f"{REGISTRY_SPEC_URL_BASE}{tail}"
    # isDescriptionFor links the spec (an information artifact) to an anonymous
    # individual of the correct physical battery type. Chemistry, format,
    # electrode bases and rechargeability are expressed through this @type stack.
    physical_types = physical_type_stack(cell)
    node["isDescriptionFor"] = {
        "@type": physical_types if len(physical_types) > 1 else physical_types[0],
    }
    if name:
        # Human layer: label the anonymous physical individual with the name
        # already in hand, so the typed node reads without EMMO lookups.
        node["isDescriptionFor"]["skos:prefLabel"] = name
    if cell.get("size_code"):
        node["schema:size"] = cell["size_code"]
    if cell.get("iec_code"):
        node["schema:productID"] = cell["iec_code"]
    if cell.get("product_type"):
        node["schema:additionalType"] = str(cell["product_type"])
    brand = cell.get("brand")
    brand_name = brand.get("name") if isinstance(brand, Mapping) else brand
    if isinstance(brand_name, str) and brand_name:
        node["schema:brand"] = {"@type": "schema:Brand", "schema:name": brand_name}
    category = cell.get("battery_category") or cell.get("category")
    if isinstance(category, str) and category:
        node["schema:category"] = category
    if cell.get("country_of_origin"):
        node["schema:countryOfOrigin"] = {
            "@type": "schema:Country",
            "schema:name": cell["country_of_origin"],
        }
    if cell.get("year"):
        node["schema:releaseDate"] = f"{cell['year']}-01-01"
    schema_version = record.get("schema_version") or cell.get("schema_version")
    if schema_version:
        node["schema:schemaVersion"] = schema_version

    property_nodes = cell_spec_property_nodes(
        record.get("properties"), context_label=str(iri or name or "cell-spec")
    )
    if property_nodes:
        node["hasProperty"] = property_nodes

    prov = provenance_node(record.get("provenance"))
    if prov is not None:
        node["dcterms:source"] = prov
    return node
