"""Guard: the published v1 records context must agree with the curated maps.

``records.context.v1.json`` is the context every emitter uses and the file
served at https://w3id.org/battinfo/context/records/v1.json. It is append-only,
so it does not follow later changes to the curated property map or the class
table on its own. Before 0.8.0 that let eight terms drift: six kept a private
``battinfo:`` mint after domain-electrochemistry 0.37.1 added the real classes,
``capacity_fade`` kept the superseded CapacityFade phenomenon, and
``PrismaticBattery`` kept an IRI the battery ontology deprecated. They were
corrected in place (``PRE_RELEASE_CORRECTIONS`` in scripts/gen_context.py), and
so, later, were ``degC`` (bound to EMMO's class for the programming language C)
and ``TemperatureCoefficientOfTheOpenCircuitVoltage`` (bound to CoatingThickness).
An audit of every record-body term before the first release corrected fifteen
more (owner rulings 2026-10-13), checked term by term below.

These tests fail when the curated sources and v1 disagree again. After 0.8.0
the fix is a v2 context, not another edit to v1.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from pyld import jsonld as _jsonld
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDFS

from battinfo.jsonld import CONTEXT_UNIT_SYMBOLS
from battinfo.transform.cell_spec_node import label_to_compact
from battinfo.validate.jsonld import _inline_local_contexts

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json"
BUNDLED = ROOT / "src" / "battinfo" / "data" / "context" / "domain-battery.context.json"
CURATED = ROOT / "src" / "battinfo" / "data" / "mappings" / "domain-battery" / "property_map.curated.json"
CLOSURE_TERMS = ROOT / "tests" / "fixtures" / "emmo" / "closure-terms.json"

EMMO = "https://w3id.org/emmo#"
ECHEM = "https://w3id.org/emmo/domain/electrochemistry#electrochemistry_"
XSD_DOUBLE = "http://www.w3.org/2001/XMLSchema#double"
HAS_TEST_OBJECT = ECHEM + "5998f7c1_d8e3_4c55_8170_c358e1b0c93c"
HAS_TEST_EQUIPMENT = ECHEM + "52702560_2034_4369_ab7f_28e8bb32680c"


def _v1() -> dict:
    return json.loads(V1.read_text(encoding="utf-8"))["@context"]


def _bundled() -> dict:
    return json.loads(BUNDLED.read_text(encoding="utf-8"))["@context"]


def _expander(ctx: dict):
    prefixes = {k: v for k, v in ctx.items() if isinstance(v, str) and v.endswith(("#", "/"))}

    def expand(value):
        if isinstance(value, dict):
            value = value.get("@id")
        if isinstance(value, str) and ":" in value and not value.startswith(("http://", "https://")):
            prefix, local = value.split(":", 1)
            if prefix in prefixes:
                return prefixes[prefix] + local
        return value

    return expand


def test_v1_property_terms_match_curated_map() -> None:
    ctx = _v1()
    expand = _expander(ctx)
    curated = json.loads(CURATED.read_text(encoding="utf-8"))["mappings"]
    mismatches = [
        (m["key"], expand(ctx[m["key"]]), m["class_iri"])
        for m in curated
        if m["key"] in ctx and expand(ctx[m["key"]]) != m["class_iri"]
    ]
    assert not mismatches, (
        "records.context.v1.json disagrees with property_map.curated.json. "
        f"After 0.8.0 this needs a v2 context: {mismatches}"
    )


def test_v1_class_terms_match_class_table() -> None:
    ctx = _v1()
    expand = _expander(ctx)
    table = label_to_compact()
    mismatches = [
        (term, expand(ctx[term]), expand(value))
        for term, value in table.items()
        if term in ctx and expand(ctx[term]) != expand(value)
    ]
    assert not mismatches, (
        "records.context.v1.json disagrees with the class table (label_to_compact). "
        f"After 0.8.0 this needs a v2 context: {mismatches}"
    )


def test_v1_has_no_private_mint_for_a_curated_property() -> None:
    ctx = _v1()
    curated = {m["key"] for m in json.loads(CURATED.read_text(encoding="utf-8"))["mappings"]}
    private = sorted(k for k in curated if isinstance(ctx.get(k), str) and ctx[k].startswith("battinfo:"))
    assert not private, f"curated properties still mapped to private battinfo: terms in v1: {private}"


def test_v1_terms_named_after_an_emmo_label_expand_like_the_pinned_context() -> None:
    """A v1 term spelled like a label of the bundled EMMO context names the same IRI.

    hasTestObject and hasTestEquipment named domain-battery duplicates that carry
    no definition, and WattPerLitre a QUDT IRI that does not dereference.
    """
    ctx, bundled = _v1(), _bundled()
    expand, expand_bundled = _expander(ctx), _expander(bundled)
    prefixes = {k for k, v in ctx.items() if isinstance(v, str) and v.endswith(("#", "/"))}
    # Bound outside EMMO on purpose: the record classes Dataset (dcat:Dataset) and
    # Material (a battinfo: record class), and note (a schema:description).
    elsewhere = {"Dataset", "Material", "note"}
    wrong = {
        term: (expand(value), expand_bundled(bundled[term]))
        for term, value in ctx.items()
        if term in bundled
        and term not in prefixes
        and term not in elsewhere
        and not term.startswith("@")
        and expand(value) != expand_bundled(bundled[term])
    }
    assert not wrong, wrong


# Record-body keys the curated property map does not hold, with the label of the
# EMMO term each one expands to in v1 (looked up in the bundled EMMO context).
_RECORD_LAYER_TERMS = {
    "loading": "MassLoading",
    "dry_thickness": "DryCoatingThickness",
    "areal_capacity": "AreicCapacity",
    "mass_fraction": "MassFraction",
    "duration": "Duration",
    "c_rate": "CRate",
    "count": "NumberOfEntities",
    "formula": "ChemicalFormula",
    "electrode_polarity": "Polarity",
    # All packaged values are in degC; a kelvin value warns semantic.ambient_temperature_kelvin.
    "ambient_temperature": "AmbientCelsiusTemperature",
    # Links to another record are relations, never the class of the target.
    "cell_id": "hasTestObject",
    "working_electrode_id": "hasWorkingElectrode",
    "working_electrode_spec_id": "hasWorkingElectrode",
    "active_material_spec_id": "hasActiveMaterial",
    # Component keys written with the class of the component, the class-as-predicate
    # pattern every quantity key of the record-body layer follows. Whether that layer
    # moves to relations is a question for a v2 context.
    "solvent": "Solvent",
    "coating": "Coating",
    "active_material": "ActiveMaterial",
    "binder": "Binder",
    "additive": "Additive",
    "working_electrode": "WorkingElectrode",
    "counter_electrode": "CounterElectrode",
    "reference_electrode": "ReferenceElectrode",
    "positive_electrode": "PositiveElectrode",
    "negative_electrode": "NegativeElectrode",
}


def _record_layer_keys(ctx: dict) -> dict[str, Any]:
    """Every snake_case v1 key that expands into an EMMO namespace, prefixes and unit symbols aside."""
    expand = _expander(ctx)
    out = {}
    for key, value in ctx.items():
        iri = expand(value)
        if (
            re.fullmatch(r"[a-z][a-z0-9_]*", key)
            and key not in CONTEXT_UNIT_SYMBOLS
            and isinstance(iri, str)
            and iri.startswith("https://w3id.org/emmo")
            and not iri.endswith(("#", "/"))
        ):
            out[key] = iri
    return out


def test_every_record_layer_key_expands_to_its_expected_emmo_term() -> None:
    """Covers the record-body keys the curated map does not hold. Before 0.8.0 the
    two nominal continuous currents expanded to the maximum-current classes,
    cell_id to an undefined duplicate relation and active_material_spec_id, a
    link, to the ActiveMaterial class."""
    ctx, bundled = _v1(), _bundled()
    expand_bundled = _expander(bundled)
    curated = {m["key"] for m in json.loads(CURATED.read_text(encoding="utf-8"))["mappings"]}
    keys = _record_layer_keys(ctx)
    unchecked = sorted(set(keys) - curated - set(_RECORD_LAYER_TERMS))
    assert not unchecked, f"record-body keys of v1 with no expected EMMO term: {unchecked}"
    wrong = {
        key: (keys.get(key), label, expand_bundled(bundled[label]))
        for key, label in _RECORD_LAYER_TERMS.items()
        if keys.get(key) != expand_bundled(bundled[label])
    }
    assert not wrong, wrong


@pytest.mark.parametrize(
    ("term", "iri", "kind"),
    [
        ("%", ECHEM + "8430be19_6cae_4a15_a570_3c15d0d190eb", None),
        ("nominal_continuous_charging_current", ECHEM + "79551e01_4bc6_4292_916e_08fe28a84600", None),
        ("nominal_continuous_discharging_current", ECHEM + "e4d666ee_d637_45cd_a904_dc33941ead4f", None),
        ("rated_energy", ECHEM + "da215d1a_196a_465f_9de8_89f6fbb76982", None),
        ("certified_usable_energy", ECHEM + "da215d1a_196a_465f_9de8_89f6fbb76982", None),
        ("typical_energy", ECHEM + "46376e5d_9627_4514_9881_9e62083625c3", None),
        ("WattPerLitre", EMMO + "WattPerLitre", None),
        ("hasTestObject", HAS_TEST_OBJECT, "@id"),
        ("hasTestEquipment", HAS_TEST_EQUIPMENT, "@id"),
        ("cell_id", HAS_TEST_OBJECT, "@id"),
        ("ambient_temperature", ECHEM + "abd08921_6f3b_4a48_811e_7685c58aec0b", None),
        ("id", "https://schema.org/identifier", None),
        ("hasNumberValue", EMMO + "EMMO_faf79f53_749d_40b2_807c_d34244c192f4", XSD_DOUBLE),
        ("hasNumericalValue", EMMO + "EMMO_faf79f53_749d_40b2_807c_d34244c192f4", XSD_DOUBLE),
        ("active_material_spec_id", ECHEM + "860aa941_5ff9_4452_8a16_7856fad07bee", "@id"),
        # Deprecated upstream and no longer emitted, but v1 keeps every term it published.
        ("LithiumNickelManganeseOxideElectrode", ECHEM + "41ddf723_245f_4ce8_b9b1_7d9b3b9eea7d", None),
    ],
)
def test_v1_term_after_the_pre_release_audit(term: str, iri: str, kind: str | None) -> None:
    ctx = _v1()
    expand = _expander(ctx)
    value = ctx[term]
    declared = value.get("@type") if isinstance(value, dict) else None
    if isinstance(declared, str) and declared != "@id":
        declared = expand(declared)
    assert (expand(value), declared) == (iri, kind)


def test_the_unit_terms_of_v1_name_units_of_the_pinned_closure() -> None:
    """% named emmo:Percent, which the pinned chain does not import, and
    WattPerLitre a QUDT IRI that does not dereference."""
    units = set(json.loads(CLOSURE_TERMS.read_text(encoding="utf-8"))["measurement_units"])
    ctx = _v1()
    expand = _expander(ctx)
    assert {term: expand(ctx[term]) in units for term in ("%", "WattPerLitre")} == {"%": True, "WattPerLitre": True}


# Classes the fixed test-method and current-collector emitters write, and the
# classes the audit's rulings bring in through the curated maps.
_ADDED_CLASS_TERMS = (
    "Charging",
    "Discharging",
    "ElectricResistance",
    "CurrentControlledProcess",
    "PowerControlledProcess",
    "LowerCurrentLimit",
    "UpperCurrentLimit",
    "ConstantVoltageCharging",
    "ConstantVoltageDischarging",
    "Mesh",
    "Foam",
    "RatedEnergy",
    "StoredEnergy",
    "MetalOxideElectrode",
)


@pytest.mark.parametrize("term", _ADDED_CLASS_TERMS)
def test_v1_defines_the_class(term: str) -> None:
    ctx, bundled = _v1(), _bundled()
    assert term in ctx
    assert _expander(ctx)(ctx[term]) == _expander(bundled)(bundled[term])


def _gen_context():
    spec = importlib.util.spec_from_file_location("gen_context", ROOT / "scripts" / "gen_context.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_hand_kept_class_terms_name_the_classes_of_the_pinned_context() -> None:
    gen = _gen_context()
    ctx, bundled = _v1(), _bundled()
    expand, expand_bundled = _expander(ctx), _expander(bundled)
    wrong = {
        term: (expand(value), expand_bundled(bundled.get(term)))
        for term, value in gen.EMITTER_CLASS_TERMS.items()
        if expand(value) != expand_bundled(bundled.get(term))
    }
    assert not wrong, wrong


def _nquads(doc: dict) -> str:
    expanded = _jsonld.expand(_inline_local_contexts(doc))
    return _jsonld.normalize(expanded, {"algorithm": "URDNA2015", "format": "application/n-quads"})


def test_a_number_gets_one_datatype_however_it_is_written() -> None:
    """Under pyld 3, 76.0 expanded to xsd:integer, while pyld 2 and rdflib gave
    xsd:double, so one datasheet value became two different RDF terms."""

    def quantity(value: float) -> dict:
        return {
            "@context": "https://w3id.org/battinfo/context/records/v1.json",
            "@id": "https://example.org/q",
            "hasNumericalPart": {"@type": "RealData", "hasNumberValue": value},
        }

    as_int, as_float = _nquads(quantity(76)), _nquads(quantity(76.0))
    assert as_int == as_float
    assert f'"7.6E1"^^<{XSD_DOUBLE}>' in as_int


SH = Namespace("http://www.w3.org/ns/shacl#")
PROV = Namespace("http://www.w3.org/ns/prov#")
_DOMAIN_BATTERY_HAS_TEST_OBJECT = URIRef(
    "https://w3id.org/emmo/domain/battery#battery_da3b3f28_aaad_4d67_b674_df47e109fb8b"
)


@pytest.mark.parametrize(
    "shapes",
    [
        ROOT / "assets" / "shapes" / "publication.shapes.ttl",
        ROOT / "src" / "battinfo" / "data" / "shapes" / "publication.shapes.ttl",
    ],
)
def test_the_publish_gate_requires_the_test_object_relation_v1_writes(shapes: Path) -> None:
    """The BatteryTest shape and the context name the same relation, or every
    published test fails the gate."""
    ctx = _v1()
    relation = URIRef(_expander(ctx)(ctx["hasTestObject"]))
    paths = set(Graph().parse(shapes, format="turtle").objects(None, SH.path))
    assert relation in paths
    assert _DOMAIN_BATTERY_HAS_TEST_OBJECT not in paths


def test_the_interop_axiom_is_stated_on_the_test_object_relation_v1_writes() -> None:
    ctx = _v1()
    relation = URIRef(_expander(ctx)(ctx["hasTestObject"]))
    graph = Graph().parse(ROOT / "assets" / "ontology" / "interop-mappings.ttl", format="turtle")
    assert (relation, RDFS.subPropertyOf, PROV.used) in graph
    assert (_DOMAIN_BATTERY_HAS_TEST_OBJECT, RDFS.subPropertyOf, PROV.used) not in graph
