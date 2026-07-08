"""Serialize BattINFO records as JSON-LD.

Each record type (cell-spec, cell-instance, test, dataset) is transformed into
valid JSON-LD using the curated property/unit mappings and the BattINFO records
context at ``data/context/records.context.json``.

The output is immediately usable by any JSON-LD processor (e.g. ``pyld``,
``rdflib`` + ``rdflib-jsonld``) to expand into RDF triples.

Usage::

    from battinfo.jsonld import record_to_jsonld
    import json

    raw = json.loads(Path("cell-spec-xyz.json").read_text())
    ld  = record_to_jsonld(raw, "cell-spec")
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_DATA = Path(__file__).parent / "data"
_CONTEXT_PATH = _DATA / "context" / "records.context.json"
_CONTEXT_URL  = "https://w3id.org/battinfo/context/records/v1.json"

# Inline context dict — loaded once so files are self-contained and parseable
# without network access. The URL above is the future hosted reference.
_CONTEXT_INLINE: dict = json.loads(_CONTEXT_PATH.read_text(encoding="utf-8"))["@context"]

# ── Mapping tables (loaded once at module import) ─────────────────────────────

def _load_property_map() -> dict[str, str]:
    path = _DATA / "mappings" / "domain-battery" / "property_map.curated.json"
    raw  = json.loads(path.read_text(encoding="utf-8"))
    return {m["key"]: m["class_iri"] for m in raw["mappings"]}


def _load_unit_map() -> dict[str, str]:
    path = _DATA / "mappings" / "domain-battery" / "unit_map.curated.json"
    raw  = json.loads(path.read_text(encoding="utf-8"))
    return {m["symbol"]: m["unit_iri"] for m in raw["mappings"]}


def _load_entity_type_map() -> dict:
    path = _DATA / "mappings" / "domain-battery" / "entity_type_map.json"
    return json.loads(path.read_text(encoding="utf-8"))["mappings"]


def _load_test_method_vocab() -> dict:
    base = _DATA / "vocab" / "test-method"
    return {
        "step_modes":  json.loads((base / "step-modes.json").read_text(encoding="utf-8"))["modes"],
        "quantities":  json.loads((base / "quantities.json").read_text(encoding="utf-8")),
        "termination": json.loads((base / "termination.json").read_text(encoding="utf-8"))["terminations"],
    }


_PROP_MAP   = _load_property_map()
_UNIT_MAP   = _load_unit_map()
_ENTITY_MAP = _load_entity_type_map()
_METHOD_VOCAB = _load_test_method_vocab()


def _load_test_method_context_terms() -> dict:
    """Pull the EMMO terms a method graph emits (process classes, relations,
    quantity classes) from the curated domain-battery context, so the assembled
    JSON-LD resolves offline without hand-maintaining their IRIs here."""
    db = json.loads((_DATA / "context" / "domain-battery.context.json").read_text(encoding="utf-8"))["@context"]
    wanted = (
        "hasTask", "NumberOfIterations", "hasControlParameter", "hasTerminationParameter", "hasProperty",
        "ConstantCurrentCharging", "ConstantCurrentDischarging",
        "ConstantCurrentConstantVoltageCharging", "ConstantCurrentConstantVoltageDischarging",
        "ConstantPowerCharging", "ConstantPowerDischarging",
        "VoltageHold", "OpenCircuitHold", "IterativeWorkflow",
        "ElectrochemicalImpedanceSpectroscopy", "LinearScanVoltammetry",
        "LowerVoltageLimit", "UpperVoltageLimit", "TerminationQuantity",
        "CRate", "ElectricCurrent", "Voltage", "Power", "ElectricalResistance",
        "Duration", "ConventionalProperty",
    )
    return {t: db[t] for t in wanted if t in db}


TEST_METHOD_CONTEXT_TERMS = _load_test_method_context_terms()


def step_emmo_class(mode: str, direction: str | None) -> str | None:
    """(mode, direction) → EMMO process class prefLabel for a method step @type."""
    entry = _METHOD_VOCAB["step_modes"].get(mode)
    if not entry:
        return None
    dirs = entry.get("directions", {})
    if direction and direction in dirs:
        return dirs[direction]["emmo_class"]
    if len(dirs) == 1:
        return next(iter(dirs.values()))["emmo_class"]
    return None


def setpoint_emmo_class(quantity: str) -> str | None:
    """Setpoint quantity key → EMMO quantity class prefLabel."""
    entry = _METHOD_VOCAB["quantities"]["setpoints"].get(quantity)
    return entry["emmo_class"] if entry else None


def termination_emmo_class(quantity: str, direction: str | None) -> str | None:
    """(termination quantity, direction) → EMMO termination class prefLabel."""
    terms = _METHOD_VOCAB["termination"].get(quantity)
    if not terms:
        return None
    if quantity == "duration":
        return terms.get("elapsed", {}).get("emmo_class")
    if direction and direction in terms:
        return terms[direction]["emmo_class"]
    if "below" in terms:
        return terms["below"]["emmo_class"]
    return None

# ── Test-protocol condition vocabulary (EMMO domain-battery) ──────────────────
# A test protocol's structured conditions are modelled the way the EMMO
# electrochemistry ontology models a test process: controlled inputs via
# `hasControlParameter`, stop conditions via `hasTerminationParameter`, and
# ambient conditions via `hasProperty` — each a typed quantity with the standard
# `hasNumericalPart`/`hasMeasurementUnit` sub-pattern (see the ontology's
# formation_cycling.jsonld example). These maps let the publication builder turn
# a `{value, unit}` authoring entry into that graph, with a `schema:PropertyValue`
# fallback (and a warning) for any name not in the controlled vocabulary.
#
# Authoring group → EMMO relation predicate.
TEST_CONDITION_GROUP_RELATION: dict[str, str] = {
    "setpoints":            "hasControlParameter",
    "termination_criteria": "hasTerminationParameter",
    "conditions":           "hasProperty",
}
TEST_CONDITION_GROUPS = tuple(TEST_CONDITION_GROUP_RELATION)
# Authoring condition key → EMMO quantity-class prefLabel (resolved by the context).
# Temperature has no dedicated quantity class, so it is a generic ConventionalProperty
# (an assigned-by-convention value, e.g. "room temperature" = 20 degC) carrying a label.
TEST_CONDITION_CLASS: dict[str, str] = {
    "c_rate":                     "CRate",
    "crate":                      "CRate",
    "current":                    "ElectricCurrent",
    "discharging_current":        "ElectricCurrent",
    "charging_current":           "ElectricCurrent",
    "voltage":                    "Voltage",
    "discharging_cutoff_voltage": "LowerVoltageLimit",
    "lower_voltage_limit":        "LowerVoltageLimit",
    "charging_cutoff_voltage":    "UpperVoltageLimit",
    "upper_voltage_limit":        "UpperVoltageLimit",
    "duration":                   "Duration",
    "number_of_iterations":       "NumberOfIterations",
    "cycles":                     "NumberOfIterations",
    "temperature":                "ConventionalProperty",
    "ambient_temperature":        "ConventionalProperty",
    "room_temperature":           "ConventionalProperty",
}
# Quantity classes whose @type is generic and so should carry a human rdfs:label.
TEST_CONDITION_GENERIC_CLASSES = frozenset({"ConventionalProperty"})
# Extra unit symbols not in the records context (CRate is current-per-capacity).
TEST_CONDITION_UNIT_IRI: dict[str, str] = {
    "A/Ah":  "electrochemistry:AmperePerAmpereHour",
    "Ah/Ah": "electrochemistry:AmperePerAmpereHour",
    "C":     "electrochemistry:AmperePerAmpereHour",
}
# Context terms the test-protocol model needs that the records context lacks.
# Relations are @id-typed; classes/units map a prefLabel to a compact IRI.
TEST_PROTOCOL_CONTEXT_TERMS: dict[str, Any] = {
    "hasControlParameter": {
        "@id": "electrochemistry:electrochemistry_e55f2798_55c8_4fc5_9abb_2f8ac101f3b8",
        "@type": "@id",
    },
    "hasTerminationParameter": {
        "@id": "electrochemistry:electrochemistry_e6a7d617_a581_4782_8374_37d3305e0258",
        "@type": "@id",
    },
    "ControlProperty":      "electrochemistry:electrochemistry_33e6986c_b35a_4cae_9a94_acb23248065c",
    "ConventionalProperty": "emmo:EMMO_d8aa8e1f_b650_416d_88a0_5118de945456",
    "CRate":                "electrochemistry:electrochemistry_e1fd84eb_acdb_4b2c_b90c_e899d552a3ee",
    "Voltage":              "emmo:EMMO_17b031fb_4695_49b6_bb69_189ec63df3ee",
    "ElectricCurrent":      "emmo:EMMO_c995ae70_3b84_4ebb_bcfc_69e6a281bb88",
    "Duration":             "emmo:EMMO_0adabf6f_7404_44cb_9f65_32d83d8101a3",
    "NumberOfIterations":   "electrochemistry:electrochemistry_88dd2bce_fb17_4705_905d_892681812290",
    "AmperePerAmpereHour":  "electrochemistry:AmperePerAmpereHour",
}

# EMMO battery-type IRIs (from domain-battery.context.json)
_BATTERY_TYPE_IRIS: dict[str, str] = {
    "BatteryCell":         "https://w3id.org/emmo/domain/battery#battery_68ed592a_7924_45d0_a108_94d6275d57f0",
    "CylindricalBattery":  "https://w3id.org/emmo/domain/battery#battery_ac604ecd_cc60_4b98_b57c_74cd5d3ccd40",
    "PrismaticBattery":    "https://w3id.org/emmo/domain/battery#battery_86c9ca80_de6f_417f_afdc_a7e52fa6322d",
    "PouchCell":           "https://w3id.org/emmo/domain/battery#battery_392b3f47_d62a_4bd4_a819_b58b09b8843a",
    "CoinCell":            "https://w3id.org/emmo/domain/battery#battery_b7fdab58_6e91_4c84_b097_b06eff86a124",
    "LithiumIonBattery":   "https://w3id.org/emmo/domain/battery#battery_96addc62_ea04_449a_8237_4cd541dd8e5f",
    "LithiumMetalBattery": "https://w3id.org/emmo/domain/battery#battery_ada13509_4eed_4e40_a7b1_4cc488144154",
    "SodiumIonBattery":    "https://w3id.org/emmo/domain/battery#battery_42329a95_03fe_4ec1_83cb_b7e8ed52f68a",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _compact_iri(iri: str) -> str:
    """Return a compact IRI string (prefix:local) where known, else the full IRI."""
    prefixes = {
        "https://w3id.org/emmo/domain/battery#": "battery:",
        "https://w3id.org/emmo/domain/electrochemistry#": "electrochemistry:",
        "https://w3id.org/emmo#": "emmo:",
    }
    for base, prefix in prefixes.items():
        if iri.startswith(base):
            return prefix + iri[len(base):]
    return iri


def _quantity(value: Any, unit: str) -> dict:
    """Convert {value, unit} to an EMMO quantity node.

    Uses the same EMMO ``hasNumericalPart``/``hasNumberValue``/``hasMeasurementUnit``
    encoding as the published builder (ws.py) — a single, shared quantity serialization
    across publication and validation (no parallel QUDT form).
    """
    node: dict = {"hasNumericalPart": {"hasNumberValue": value}}
    unit_iri = _UNIT_MAP.get(unit)
    if unit_iri:
        node["hasMeasurementUnit"] = {"@id": unit_iri}
    elif unit:
        # Unmapped unit: emit a plain-text literal. hasMeasurementUnit is @id-typed in the
        # records context, so a bare symbol there is coerced to a cwd-relative file:// IRI on
        # RDF export — a portability leak. schema:unitText keeps the symbol as a literal (D-2).
        node["schema:unitText"] = unit
    return node


def _rdf_types_for(cell_format: str, chemistry: str) -> list[str]:
    """Return a list of EMMO IRI strings for the given format and chemistry."""
    types: list[str] = []
    fmt_entry = _ENTITY_MAP.get("format", {}).get((cell_format or "").lower())
    if fmt_entry:
        for t in fmt_entry.get("battery_types", []):
            iri = _BATTERY_TYPE_IRIS.get(t)
            if iri:
                types.append(iri)
    chem_entry = _ENTITY_MAP.get("chemistry", {}).get((chemistry or "").lower())
    if chem_entry:
        for t in chem_entry.get("battery_types", []):
            iri = _BATTERY_TYPE_IRIS.get(t)
            if iri and iri not in types:
                types.append(iri)
    if not types:
        types.append(_BATTERY_TYPE_IRIS["BatteryCell"])
    return types


# ── Per-type transformers ─────────────────────────────────────────────────────

def cell_spec_to_jsonld(record: dict) -> dict:
    """Transform a cell-spec record dict to JSON-LD (canonical spec-node shape).

    Delegates to the shared canonical builder
    (:func:`battinfo.transform.cell_spec_node.build_cell_spec_node`) so
    ``record_to_jsonld`` emits the exact node the resolver artifact and the
    Zenodo/local publication graph emit: ``@type ["BatteryCellSpecification",
    "schema:CreativeWork"]``, the physical EMMO class stack under
    ``isDescriptionFor`` (chemistry/format/electrode bases via @type stacking,
    not literal predicates), quantities as an EMMO ``hasProperty`` array, and a
    standard-vocabulary (dcterms/PROV) provenance node.

    The inline ``@context`` is the records context extended with the
    prefLabel -> compact-IRI table, so every emitted ``@type`` resolves offline.
    """
    # Deferred import: transform.cell_spec_node pulls in the transform stack.
    from battinfo.transform.cell_spec_node import (  # noqa: PLC0415
        build_cell_spec_node,
        label_to_compact,
    )

    if "cell_spec" not in record and "specification" in record:
        record = {**record, "cell_spec": record["specification"]}
    context: dict = dict(_CONTEXT_INLINE)
    context.update(label_to_compact())
    return {"@context": context, **build_cell_spec_node(record)}


def cell_instance_to_jsonld(record: dict) -> dict:
    """Transform a cell-instance record dict to JSON-LD."""
    ci   = record.get("cell_instance") or {}
    prov = record.get("provenance") or {}
    datasets = record.get("datasets") or []

    node: dict = {
        "@context": _CONTEXT_INLINE,
        "@type":    "https://w3id.org/battinfo/Cell",
        "@id":      ci.get("id", ""),
        "schema:serialNumber": ci.get("serial_number"),
    }
    if ci.get("cell_spec_id"):
        node["battinfo:cellSpecification"] = {"@id": ci["cell_spec_id"]}
    if ci.get("batch_id"):
        node["battinfo:batchId"] = ci["batch_id"]
    if ci.get("manufactured_at"):
        node["schema:productionDate"] = ci["manufactured_at"]
    if ci.get("expires_at"):
        node["battinfo:expiresAt"] = ci["expires_at"]
    if datasets:
        node["battinfo:hasDataset"] = [{"@id": d["id"]} for d in datasets if d.get("id")]
    if prov:
        node["battinfo:provenance"] = _provenance(prov)

    return {k: v for k, v in node.items() if v is not None and v != [] and v != {}}


def test_to_jsonld(record: dict) -> dict:
    """Transform a test record dict to JSON-LD."""
    test = record.get("test") or {}
    prov = record.get("provenance") or {}

    node: dict = {
        "@context": _CONTEXT_INLINE,
        "@type":    "https://w3id.org/emmo/domain/battery#battery_dca7729a_421a_4921_90cf_9692bb9eb081",
        "@id":      test.get("id", ""),
        "schema:name": test.get("name"),
        "battinfo:testKind": test.get("kind"),
        "battinfo:instrumentName": test.get("instrument_name"),
        "battinfo:protocolName": test.get("protocol_name"),
        "battinfo:status": test.get("status"),
    }
    if test.get("cell_id"):
        node["battinfo:testedCell"] = {"@id": test["cell_id"]}
    if test.get("protocol_id"):
        node["battinfo:testProtocol"] = {"@id": test["protocol_id"]}
    if test.get("dataset_ids"):
        # Skip None / non-string entries so a partial record never emits {"@id": null}
        # (invalid JSON-LD — @id must be a string IRI).
        node["battinfo:hasDataset"] = [{"@id": d} for d in test["dataset_ids"] if isinstance(d, str) and d]
    if prov:
        node["battinfo:provenance"] = _provenance(prov)

    return {k: v for k, v in node.items() if v is not None and v != [] and v != {}}


def dataset_to_jsonld(record: dict) -> dict:
    """Transform a dataset record dict to JSON-LD."""
    ds   = record.get("dataset") or {}
    prov = record.get("provenance") or {}

    node: dict = {
        "@context": _CONTEXT_INLINE,
        "@type":    "http://www.w3.org/ns/dcat#Dataset",
        "@id":      ds.get("id", ""),
        "dcterms:title": ds.get("name"),
    }
    if ds.get("license"):
        node["dcterms:license"] = {"@id": ds["license"]}
    if ds.get("access_url"):
        node["dcat:accessURL"] = {"@id": ds["access_url"]}
    if ds.get("created_at"):
        node["dcterms:created"] = _epoch_to_iso(ds["created_at"])
    if ds.get("modified_at"):
        node["dcterms:modified"] = _epoch_to_iso(ds["modified_at"])
    about = ds.get("about")
    if about:
        # Tolerate a single IRI string (wrap it) instead of iterating it
        # character-by-character into one bogus @id node per character.
        if isinstance(about, str):
            about = [about]
        subjects = [{"@id": iri} for iri in about if isinstance(iri, str) and iri]
        if subjects:
            node["dcterms:subject"] = subjects

    dists = ds.get("distributions") or []
    if dists:
        ld_dists = []
        for d in dists:
            dist: dict = {"@type": "dcat:Distribution"}
            if d.get("content_url"):
                dist["dcat:downloadURL"] = {"@id": d["content_url"]}
            if d.get("encoding_format"):
                dist["dcat:mediaType"] = d["encoding_format"]
            cs = d.get("checksum")
            if isinstance(cs, Mapping):
                dist["spdx:checksum"] = {
                    "@type": "spdx:Checksum",
                    "spdx:checksumAlgorithm": f"spdx:checksumAlgorithm_{cs.get('algorithm', '')}",
                    "spdx:checksumValue":     cs.get("value", ""),
                }
            ld_dists.append(dist)
        node["dcat:distribution"] = ld_dists

    if prov:
        node["battinfo:provenance"] = _provenance(prov)

    return {k: v for k, v in node.items() if v is not None and v != [] and v != {}}


def _provenance(prov: dict) -> dict:
    out: dict = {}
    if prov.get("source_type"):
        out["battinfo:sourceType"] = prov["source_type"]
    if prov.get("source_file"):
        out["battinfo:sourceFile"] = prov["source_file"]
    if prov.get("source_url"):
        out["battinfo:sourceURL"] = {"@id": prov["source_url"]}
    if prov.get("citation"):
        out["dcterms:bibliographicCitation"] = prov["citation"]
    return out


def funding_to_jsonld(funding: Any) -> dict | None:
    """Convert a record ``funding`` block to a schema.org ``Grant`` node.

    Mirrors the ``funders`` → ``schema:funder`` pattern.  Returns ``None`` when
    there is nothing identifying to emit.  The ``program`` field is intentionally
    not exported — schema.org has no standard term for a funding programme, so it
    is kept only in the native record block (avoids inventing IRIs).
    """
    if not isinstance(funding, dict):
        return None
    out: dict = {"@type": "schema:Grant"}
    if funding.get("id"):
        out["@id"] = funding["id"]
    if funding.get("identifier"):
        out["schema:identifier"] = funding["identifier"]
    if funding.get("name"):
        out["schema:name"] = funding["name"]
    if funding.get("acronym"):
        out["schema:alternateName"] = funding["acronym"]
    funder = funding.get("funder")
    if isinstance(funder, dict) and funder.get("name"):
        out["schema:funder"] = {"@type": "schema:Organization", "schema:name": funder["name"]}
    # Nothing beyond the bare @type → not worth emitting.
    return out if len(out) > 1 else None


def contributor_to_jsonld(contributor: Any) -> list[dict] | None:
    """Convert a record ``contributor`` list to schema.org ``Person`` nodes.

    Each entry is a person who contributed the record to the platform
    (attribution). When an ORCID is present in ``same_as`` it becomes the node's
    ``@id`` (the canonical person identifier). Returns ``None`` when there is
    nothing to emit.
    """
    if not isinstance(contributor, list):
        return None
    out: list[dict] = []
    for person in contributor:
        if not isinstance(person, dict):
            continue
        node: dict = {"@type": "schema:Person"}
        if person.get("same_as"):
            node["@id"] = person["same_as"]
        name = person.get("name")
        if isinstance(name, str) and name.strip():
            node["schema:name"] = name
        aff = person.get("affiliation")
        if isinstance(aff, dict) and aff.get("name"):
            node["schema:affiliation"] = {"@type": "schema:Organization", "schema:name": aff["name"]}
        if len(node) > 1:  # more than the bare @type
            out.append(node)
    return out or None


def _material_to_jsonld(record: dict) -> dict:
    """Transform a material-spec or material (instance) record to JSON-LD.

    Delegates to the domain-battery emitter (EMMO-typed node with
    properties-with-conditions) and returns the single node with its context.
    """
    from battinfo.transform.json_to_jsonld import to_jsonld

    doc = to_jsonld(record, target="domain-battery")
    graph = doc.get("@graph") or []
    node = dict(graph[0]) if graph else {}
    return {"@context": doc.get("@context"), **node}


# Same delegation for component spec/instance records (electrode, separator, …).
_component_to_jsonld = _material_to_jsonld


# ── Public dispatcher ─────────────────────────────────────────────────────────

_TRANSFORMERS = {
    "cell-spec":      cell_spec_to_jsonld,
    "cell_spec":      cell_spec_to_jsonld,
    "cell-instance":  cell_instance_to_jsonld,
    "cell_instance":  cell_instance_to_jsonld,
    "test":           test_to_jsonld,
    "dataset":        dataset_to_jsonld,
    "material-spec":  _material_to_jsonld,
    "material_spec":  _material_to_jsonld,
    "material":       _material_to_jsonld,
    "electrode-spec": _component_to_jsonld,
    "electrode_spec": _component_to_jsonld,
    "electrode":      _component_to_jsonld,
    "separator-spec": _component_to_jsonld,
    "separator_spec": _component_to_jsonld,
    "separator":      _component_to_jsonld,
    "current-collector-spec": _component_to_jsonld,
    "current_collector_spec": _component_to_jsonld,
    "current_collector":      _component_to_jsonld,
    "electrolyte-spec": _component_to_jsonld,
    "electrolyte_spec": _component_to_jsonld,
    "electrolyte":      _component_to_jsonld,
    "housing-spec": _component_to_jsonld,
    "housing_spec": _component_to_jsonld,
    "housing":      _component_to_jsonld,
}


def _epoch_to_iso(value):
    """Records store times as Unix epoch ints; DCMI terms expect date literals.

    Emitting the raw integer typed xsd:integer poisoned DCAT harvesters
    (red-team W3.4). Non-numeric values pass through untouched.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    import datetime as _dt

    return (
        _dt.datetime.fromtimestamp(value, tz=_dt.timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def record_to_jsonld(record: dict, record_type: str) -> dict:
    """Transform a BattINFO plain-JSON record to a JSON-LD document.

    Parameters
    ----------
    record:
        The plain-JSON record dict (as loaded from ``.battinfo/records/``).
    record_type:
        One of ``"cell-spec"``, ``"cell-instance"``, ``"test"``, ``"dataset"``.

    Returns
    -------
    dict
        A JSON-LD document with ``@context``, ``@id``, ``@type``, and
        semantically typed properties using EMMO/schema.org IRIs.

    Example::

        import json
        from battinfo.jsonld import record_to_jsonld

        raw = json.loads(Path("cell-spec-xyz.json").read_text())
        ld  = record_to_jsonld(raw, "cell-spec")
        print(json.dumps(ld, indent=2))
    """
    key = record_type.lower().replace(" ", "-")
    fn  = _TRANSFORMERS.get(key)
    if fn is None:
        raise ValueError(
            f"Unknown record_type {record_type!r}. "
            f"Supported: {sorted({k.replace('_','-') for k in _TRANSFORMERS})}."
        )
    node = fn(record)
    # Funding (workspace grant) → schema:funding/Grant, for every record kind whose
    # node uses the schema.org context. Material/component nodes delegate to the
    # domain-battery emitter (a different context) and are skipped.
    if fn is not _material_to_jsonld:
        grant = funding_to_jsonld(record.get("funding"))
        if grant is not None:
            node["schema:funding"] = grant
        people = contributor_to_jsonld(record.get("contributor"))
        if people is not None:
            node["schema:contributor"] = people
    return node
