"""Serialize BattINFO records as JSON-LD.

Each record type (cell-spec, cell-instance, test, test-protocol, dataset) is
transformed into valid JSON-LD using the curated property/unit mappings and the
BattINFO records context at ``data/context/records.context.json``.

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
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

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
        # Characterisation-method classes a test protocol types itself with
        # (see TEST_METHOD_CLASS). Pulled from the same bundled context, so the
        # emitter, the hosted context and the validator allowlist cannot drift.
        *TEST_METHOD_CLASS.values(),
    )
    return {t: db[t] for t in wanted if t in db}


# Test-protocol ``kind`` -> characterisation-method class prefLabel. Only kinds whose
# method has a published class are mapped; anything else keeps the untyped plan node.
# Every prefLabel below is verified against domain-electrochemistry 0.37.2 (which
# imports chameo) and resolves in the bundled domain-battery context.
TEST_METHOD_CLASS: dict[str, str] = {
    "gitt":            "GalvanostaticIntermittentTitrationTechnique",
    "quasi_ocv":       "PseudoOpenCircuitVoltageMethod",
    "eis":             "ElectrochemicalImpedanceSpectroscopy",
    "impedance":       "ElectrochemicalImpedanceSpectroscopy",
    "hppc":            "HPPC",
    "cycling":         "CyclingTest",
    "rate_capability": "CRateTest",
    "capacity_check":  "CapacityTest",
    "formation":       "FormationCycling",
}


TEST_METHOD_CONTEXT_TERMS = _load_test_method_context_terms()


def test_method_class(kind: Any) -> str | None:
    """A protocol/test ``kind`` -> its EMMO characterisation-method class, or ``None``.

    Tolerant of the spellings importers produce ("GITT", "rate-capability",
    "quasi OCV"); an unmapped kind returns ``None`` and the caller emits an
    untyped plan node rather than inventing a class.
    """
    if not isinstance(kind, str) or not kind.strip():
        return None
    key = re.sub(r"[\s\-]+", "_", kind.strip().lower())
    cls = TEST_METHOD_CLASS.get(key)
    # Only offer a class the bundled context can actually resolve.
    return cls if cls in TEST_METHOD_CONTEXT_TERMS else None


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


# ── Test-protocol node builder ────────────────────────────────────────────────
# One implementation, two consumers: ``test_protocol_to_jsonld`` (a standalone
# record document) and the publication graph builder in ``ws.py`` (the same node
# as a graph member). Keeping it here is what keeps the two in parity — the
# publication path had the only implementation, which is why record_to_jsonld
# had no test-protocol emitter at all (readiness finding M5).


def _unit_pref_labels() -> dict[str, tuple[str, str]]:
    """{unit symbol -> (unit IRI, prefLabel)} from the curated unit map."""
    path = _DATA / "mappings" / "domain-battery" / "unit_map.curated.json"
    out: dict[str, tuple[str, str]] = {}
    if not path.exists():
        return out
    for m in json.loads(path.read_text(encoding="utf-8")).get("mappings", []):
        if m.get("symbol") and m.get("unit_iri") and m.get("unit_pref_label"):
            out[m["symbol"]] = (m["unit_iri"], m["unit_pref_label"])
    return out


_UNIT_PREF_LABELS = _unit_pref_labels()


def resolve_unit_iri(unit_symbol: str) -> str | None:
    """Unit symbol -> compact unit IRI, across the curated maps, the records
    context (V, mA, degC, ...) and the test-condition extras (A/Ah for C-rate)."""
    if not unit_symbol:
        return None
    labelled = _UNIT_PREF_LABELS.get(unit_symbol)
    if labelled:
        return _compact_iri(labelled[0])
    if unit_symbol in _UNIT_MAP:
        return _compact_iri(_UNIT_MAP[unit_symbol])
    ctx_val = _CONTEXT_INLINE.get(unit_symbol)
    if isinstance(ctx_val, str) and (":" in ctx_val or ctx_val.startswith("http")):
        return ctx_val
    return TEST_CONDITION_UNIT_IRI.get(unit_symbol)


def condition_quantity_node(key: str, value: Any, unit_symbol: str) -> dict | None:
    """A test condition -> EMMO quantity node (the ``@type`` comes from the
    controlled vocabulary), or ``None`` if the key is unmapped — the caller then
    falls back to ``schema:PropertyValue``."""
    cls = TEST_CONDITION_CLASS.get(str(key).lower())
    if not cls:
        return None
    node: dict = {"@type": cls, "hasNumericalPart": {"hasNumberValue": value}}
    # A generic class (e.g. ConventionalProperty for temperature) needs a human
    # label to say *which* property it is.
    if cls in TEST_CONDITION_GENERIC_CLASSES:
        node["rdfs:label"] = str(key).replace("_", " ")
    unit_iri = resolve_unit_iri(unit_symbol) if unit_symbol else (
        # C-rate is dimensionless-by-symbol; default to AmperePerAmpereHour.
        TEST_CONDITION_UNIT_IRI["A/Ah"] if cls == "CRate" else None
    )
    if unit_iri:
        node["hasMeasurementUnit"] = {"@id": unit_iri}
    return node


def typed_quantity_node(emmo_class: str, value: Any, unit_symbol: str) -> dict:
    """An EMMO quantity node with an explicit ``@type`` (used for method steps)."""
    node: dict = {"@type": emmo_class, "hasNumericalPart": {"hasNumberValue": value}}
    unit_iri = resolve_unit_iri(unit_symbol) if unit_symbol else None
    if unit_iri:
        node["hasMeasurementUnit"] = {"@id": unit_iri}
    return node


def method_step_node(step: Mapping[str, Any]) -> dict:
    """A descriptive method step -> EMMO process node.

    Groups become an ``IterativeWorkflow`` with ``NumberOfIterations`` + nested
    ``hasTask``; leaf steps carry ``hasControlParameter`` /
    ``hasTerminationParameter`` / ``hasProperty``.
    """
    mode = step.get("mode")
    if mode == "group":
        gnode: dict = {"@type": step_emmo_class("group", None) or "IterativeWorkflow"}
        count = step.get("count")
        if isinstance(count, int):
            gnode["NumberOfIterations"] = {"hasNumericalPart": {"hasNumberValue": count}}
        gnode["hasTask"] = [method_step_node(s) for s in (step.get("steps") or []) if isinstance(s, Mapping)]
        return gnode

    node: dict = {"@type": step_emmo_class(str(mode or ""), step.get("direction")) or "ElectrochemicalProcess"}
    if step.get("description"):
        node["rdfs:label"] = step["description"]
    controls: list = []
    for key, qty in (step.get("setpoints") or {}).items():
        qcls = setpoint_emmo_class(key) or TEST_CONDITION_CLASS.get(str(key).lower())
        if qcls and isinstance(qty, Mapping) and qty.get("value") is not None:
            controls.append(typed_quantity_node(qcls, qty["value"], qty.get("unit", "")))
    if controls:
        node["hasControlParameter"] = controls
    terminations: list = []
    for term in (step.get("termination") or []):
        if not isinstance(term, Mapping):
            continue
        tcls = termination_emmo_class(str(term.get("quantity") or ""), term.get("direction"))
        if tcls and term.get("value") is not None:
            terminations.append(typed_quantity_node(tcls, term["value"], term.get("unit", "")))
    duration = step.get("duration")
    if isinstance(duration, Mapping) and duration.get("value") is not None:
        dcls = termination_emmo_class("duration", "elapsed") or "Duration"
        terminations.append(typed_quantity_node(dcls, duration["value"], duration.get("unit", "")))
    if terminations:
        node["hasTerminationParameter"] = terminations
    temperature = step.get("temperature")
    if isinstance(temperature, Mapping) and temperature.get("value") is not None:
        tnode = condition_quantity_node("temperature", temperature["value"], temperature.get("unit", ""))
        if tnode is not None:
            node["hasProperty"] = [tnode]
    return node


def protocol_property_value(name: str, value: Any, group: str = "") -> dict:
    """Labelled ``schema:PropertyValue`` fallback for anything outside the
    controlled condition vocabulary. ``group`` rides ``schema:propertyID`` so a
    consumer can still tell a safety limit from an ambient condition."""
    node: dict = {"@type": "schema:PropertyValue", "schema:name": name}
    if group:
        node["schema:propertyID"] = group
    if isinstance(value, Mapping):
        if value.get("value") is not None:
            node["schema:value"] = value["value"]
            if value.get("unit"):
                node["schema:unitText"] = value["unit"]
        else:
            node["schema:value"] = json.dumps(dict(value), ensure_ascii=False, sort_keys=True)
    else:
        node["schema:value"] = value
    return node


def artifact_distribution_node(art: Mapping[str, Any], *, locator_url: Callable[[str], Any] | None = None) -> dict:
    """An actionable artifact link -> a ``dcat:Distribution`` node, so the runnable
    protocol file is machine-discoverable alongside the descriptive method.

    *locator_url* resolves a workspace-relative locator to its hosted URL; the
    publication path injects one (files being uploaded resolve to the deposit),
    and the standalone record path leaves the locator as authored.
    """
    node: dict = {"@type": "dcat:Distribution"}
    role = art.get("role")
    fmt = art.get("format")
    title = (role or "").replace("_", " ")
    if fmt:
        title = f"{title} ({fmt})".strip()
    if title:
        node["dcterms:title"] = title
    loc = art.get("locator")
    if loc:
        if locator_url is not None:
            node["dcat:downloadURL"] = locator_url(str(loc))
        else:
            node["dcat:downloadURL"] = (
                {"@id": str(loc)} if str(loc).startswith(("http://", "https://")) else str(loc)
            )
    if art.get("media_type"):
        node["dcat:mediaType"] = art["media_type"]
    ct = art.get("conforms_to")
    if ct:
        node["dcterms:conformsTo"] = (
            {"@id": ct} if str(ct).startswith(("http://", "https://")) else ct
        )
    if isinstance(art.get("byte_size"), int):
        node["dcat:byteSize"] = art["byte_size"]
    # Standard vocabulary (no custom battinfo: terms): the artifact role is a
    # dcterms:type, the format token a dcterms:format, the checksum an spdx:Checksum.
    if role:
        node["dcterms:type"] = role
    if fmt:
        node["dcterms:format"] = fmt
    if art.get("sha256"):
        node["spdx:checksum"] = {
            "@type": "spdx:Checksum",
            "spdx:algorithm": "spdx:checksumAlgorithm_sha256",
            "spdx:checksumValue": art["sha256"],
        }
    return node


def test_protocol_node(
    record: Mapping[str, Any],
    *,
    locator_url: Callable[[str], Any] | None = None,
) -> dict | None:
    """A test-protocol record -> its publication-graph node (no ``@context``).

    PROV-O: the thing a ``prov:used`` plan-link targets is a ``prov:Plan``;
    ``schema:HowTo`` is the schema.org analog for a procedure. Where the
    protocol's kind names a published characterisation method (GITT, pseudo-OCV,
    EIS, ...), that class joins the ``@type`` so the plan is queryable as the
    method it is. Returns ``None`` when the record carries no protocol IRI.
    """
    raw_spec = record.get("test_spec")
    spec: Mapping[str, Any] = raw_spec if isinstance(raw_spec, Mapping) else {}
    iri = spec.get("id")
    if not isinstance(iri, str) or not iri:
        return None

    types: list = ["prov:Plan", "schema:HowTo"]
    method_class = test_method_class(spec.get("kind"))
    if method_class:
        types.append(method_class)
    node: dict = {"@type": types, "@id": iri}
    if spec.get("name"):
        node["schema:name"] = spec["name"]
    if spec.get("kind"):
        node["schema:additionalType"] = spec["kind"]
    if spec.get("description"):
        node["schema:description"] = spec["description"]

    # ── Descriptive method -> EMMO process graph (queryable) ──────────────────
    # The ordered method becomes a hasTask chain of typed step nodes, each
    # carrying hasControlParameter / hasTerminationParameter / hasProperty.
    method = record.get("method") or []
    if isinstance(method, list) and method:
        node["hasTask"] = [method_step_node(s) for s in method if isinstance(s, Mapping)]

    props: list = []
    fallback: list = []
    conditions = record.get("conditions")
    if isinstance(conditions, Mapping):
        for name, raw_value in conditions.items():
            value = raw_value.get("value") if isinstance(raw_value, Mapping) else raw_value
            unit = raw_value.get("unit", "") if isinstance(raw_value, Mapping) else ""
            qnode = condition_quantity_node(name, value, unit) if value is not None else None
            if qnode is not None:
                props.append(qnode)
            else:
                fallback.append(protocol_property_value(name, raw_value, "conditions"))
    if props:
        node["hasProperty"] = props
    # Global safety limits (max_voltage_V, max_temperature_degC, ...) are part of
    # the protocol; emit each as a labelled PropertyValue so none is dropped.
    safety = record.get("safety")
    if isinstance(safety, Mapping):
        for key, value in safety.items():
            if value is not None:
                fallback.append(protocol_property_value(str(key), value, "safety"))
    if fallback:
        node["schema:additionalProperty"] = fallback

    # Actionable layer: link runnable protocol files as distributions.
    artifacts = record.get("artifacts")
    if isinstance(artifacts, list) and artifacts:
        node["dcat:distribution"] = [
            artifact_distribution_node(a, locator_url=locator_url) for a in artifacts if isinstance(a, Mapping)
        ]
    return node


def test_protocol_context() -> dict:
    """The ``@context`` a standalone test-protocol document needs.

    The records context plus the prefLabel -> compact-IRI class table and the
    method/protocol vocabulary — the same layering the publication graph uses, so
    a protocol resolves identically standalone and inside a deposit.
    """
    from battinfo.transform.cell_spec_node import label_to_compact  # noqa: PLC0415

    context: dict = dict(_CONTEXT_INLINE)
    context.update(label_to_compact())
    for term, value in TEST_PROTOCOL_CONTEXT_TERMS.items():
        context.setdefault(term, value)
    for term, value in TEST_METHOD_CONTEXT_TERMS.items():
        context.setdefault(term, value)
    return context


def test_protocol_to_jsonld(record: dict) -> dict:
    """Transform a test-protocol (test-spec) record dict to JSON-LD."""
    node = test_protocol_node(record) or {"@type": ["prov:Plan", "schema:HowTo"], "@id": ""}
    prov = record.get("provenance") or {}
    if prov:
        node["dcterms:source"] = _provenance(prov)
    return {"@context": test_protocol_context(), **node}


# EMMO battery-type IRIs (from domain-battery.context.json)
_BATTERY_TYPE_IRIS: dict[str, str] = {
    "BatteryCell":         "https://w3id.org/emmo/domain/battery#battery_68ed592a_7924_45d0_a108_94d6275d57f0",
    "CylindricalBattery":  "https://w3id.org/emmo/domain/battery#battery_ac604ecd_cc60_4b98_b57c_74cd5d3ccd40",
    # Underscore-named twin minted in domain-battery 0.20.2; the hyphen-named
    # original is deprecated upstream (dcterms:isReplacedBy, issue #73).
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
    """Transform a cell-instance record dict to JSON-LD.

    Standard vocabularies only (IDENTIFIER_POLICY.md section 14): the physical
    cell is an EMMO ``BatteryCell`` (+ ``schema:IndividualProduct``), the link
    to its spec uses EMMO ``hasDescription`` mirrored by ``schema:isVariantOf``
    (the same pair the resolver emits), the batch id rides in a
    ``schema:identifier`` PropertyValue, and datasets hang off
    ``schema:workExample`` — no ``battinfo:`` predicates.
    """
    ci   = record.get("cell_instance") or {}
    prov = record.get("provenance") or {}
    datasets = record.get("datasets") or []

    node: dict = {
        "@context": _CONTEXT_INLINE,
        "@type":    ["BatteryCell", "schema:IndividualProduct"],
        "@id":      ci.get("id", ""),
        "schema:serialNumber": ci.get("serial_number"),
    }
    if ci.get("cell_spec_id"):
        node["hasDescription"] = {"@id": ci["cell_spec_id"]}
        node["schema:isVariantOf"] = {"@id": ci["cell_spec_id"]}
    if ci.get("batch_id"):
        node["schema:identifier"] = {
            "@type": "schema:PropertyValue",
            "schema:propertyID": "batch_id",
            "schema:value": ci["batch_id"],
        }
    if ci.get("manufactured_at"):
        node["schema:productionDate"] = ci["manufactured_at"]
    if ci.get("expires_at"):
        node["schema:expires"] = ci["expires_at"]
    if datasets:
        node["schema:workExample"] = [{"@id": d["id"]} for d in datasets if d.get("id")]
    if prov:
        node["dcterms:source"] = _provenance(prov)

    return {k: v for k, v in node.items() if v is not None and v != [] and v != {}}


def test_to_jsonld(record: dict) -> dict:
    """Transform a test record dict to JSON-LD.

    Standard vocabularies only (IDENTIFIER_POLICY.md section 14): the test is a
    ``BatteryTest`` / ``schema:Action`` / ``prov:Activity``; its kind is a
    ``schema:additionalType``, the instrument a ``schema:instrument``, the
    protocol name a ``schema:measurementTechnique`` (the term the round-trip
    importer already reads — ``schema:name`` carries the test's own name), the
    status a ``schema:actionStatus``, the tested cell the EMMO
    ``hasTestObject``, the protocol reference a ``dcterms:conformsTo``, and
    produced datasets ``schema:result`` — no ``battinfo:`` predicates.
    """
    test = record.get("test") or {}
    prov = record.get("provenance") or {}

    node: dict = {
        "@context": _CONTEXT_INLINE,
        "@type":    ["BatteryTest", "schema:Action", "prov:Activity"],
        "@id":      test.get("id", ""),
        "schema:name": test.get("name"),
        "schema:additionalType": test.get("kind"),
        "schema:instrument": test.get("instrument_name"),
        "schema:measurementTechnique": test.get("protocol_name"),
        "schema:actionStatus": test.get("status"),
    }
    if test.get("cell_id"):
        node["hasTestObject"] = {"@id": test["cell_id"]}
    # Equipment/channel provenance: a registered equipment unit becomes a real
    # hasTestEquipment node (its IRI + the instrument display name), and the
    # channel the test ran on rides prov:used (the node is a prov:Activity).
    if test.get("equipment_id"):
        equip: dict = {"@id": test["equipment_id"]}
        if test.get("instrument_name"):
            equip["schema:name"] = test["instrument_name"]
        node["hasTestEquipment"] = equip
    if test.get("channel_id"):
        node["prov:used"] = {"@id": test["channel_id"]}
    if test.get("protocol_id"):
        node["dcterms:conformsTo"] = {"@id": test["protocol_id"]}
    if test.get("dataset_ids"):
        # Skip None / non-string entries so a partial record never emits {"@id": null}
        # (invalid JSON-LD — @id must be a string IRI).
        node["schema:result"] = [{"@id": d} for d in test["dataset_ids"] if isinstance(d, str) and d]
    conditions = test.get("conditions")
    if isinstance(conditions, Mapping) and conditions:
        # Per-execution conditions are an open snake_case map (temperature,
        # voltage window, C-rate, ...); values may be scalars, strings, or
        # {value, unit} quantities. Emit each as a standards-only
        # schema:PropertyValue (the same shape the cell-instance batch_id and the
        # protocol-condition fallback already use) hung off schema:additionalProperty.
        props: list[dict] = []
        for name in sorted(conditions):
            value = conditions[name]
            pv: dict = {"@type": "schema:PropertyValue", "schema:name": name}
            if isinstance(value, Mapping) and "value" in value:
                pv["schema:value"] = value.get("value")
                if value.get("unit"):
                    pv["schema:unitText"] = value["unit"]
            else:
                pv["schema:value"] = value
            props.append(pv)
        node["schema:additionalProperty"] = props
    if prov:
        node["dcterms:source"] = _provenance(prov)

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
        node["dcterms:source"] = _provenance(prov)

    return {k: v for k, v in node.items() if v is not None and v != [] and v != {}}


def _provenance(prov: dict) -> dict:
    """Record ``provenance`` block -> the SAME standard-vocabulary (dcterms/PROV)
    node the shared canonical builder emits, so every emitter produces one
    provenance shape. ``source_file`` stays in the canonical JSON record only
    (no standard term; the publication path already omits it)."""
    from battinfo.transform.cell_spec_node import provenance_node  # noqa: PLC0415

    return provenance_node(prov) or {}


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
    "test-protocol":  test_protocol_to_jsonld,
    "test_protocol":  test_protocol_to_jsonld,
    "test-spec":      test_protocol_to_jsonld,
    "test_spec":      test_protocol_to_jsonld,
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


def record_to_jsonld(record: dict, record_type: str, *, context: str = "url") -> dict:
    """Transform a BattINFO plain-JSON record to a JSON-LD document.

    Parameters
    ----------
    record:
        The plain-JSON record dict (as loaded from ``.battinfo/records/``).
    record_type:
        One of ``"cell-spec"``, ``"cell-instance"``, ``"test"``,
        ``"test-protocol"``, ``"dataset"``, ``"material-spec"``/``"material"``,
        or a component spec/instance type.
    context:
        ``"url"`` (default) references the hosted context (``_CONTEXT_URL``)
        with a one-line ``@context`` — the hosted document carries the full
        vocabulary, so the record a reader sees stays simple. Resolved offline
        by the bundled copy. ``"inline"`` embeds the full records ``@context``
        so the document is self-contained — use it for archival exports that
        must validate with no network (Zenodo packages inline). Both expand to
        the same graph. Records that emit a domain-battery (EMMO) context —
        materials and components — are unaffected by ``"url"``.

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
        # Record-level license (FAIR R1.1) → dcterms:license, the same convention
        # the dataset emitter uses. Cell specs/instances/tests carry it at the
        # record top level (stamped from the workspace default); datasets carry it
        # on the dataset body and emit it from dataset_to_jsonld, so this only
        # reaches the non-dataset record kinds.
        if record.get("license") and "dcterms:license" not in node:
            node["dcterms:license"] = {"@id": record["license"]}
    if context == "url" and isinstance(node.get("@context"), dict):
        # Swap the inline records context for the hosted reference. Only the
        # records-context nodes (a dict @context) are affected; material/component
        # nodes carry a domain-battery context and are left as-is.
        node = {"@context": _CONTEXT_URL, **{k: v for k, v in node.items() if k != "@context"}}
    return node
