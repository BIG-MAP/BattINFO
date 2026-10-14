"""Percent values carry the closure's percent unit and keep the basis their spelling states.

The curated unit map gave ``%`` the class WeightPercent and ``vol%`` the class
VolumePercent as their units. Both are PercentQuantity classes in
domain-electrochemistry, quantities rather than units, and the alias table
folded ``wt%`` and ``wt.%`` into a bare ``%``, so a state of charge of 50 %
was published as a weight percent. ``%`` and ``vol%`` now name PercentUnit,
the closure's only percent unit. A spelling that states a basis keeps it:
``wt%`` adds WeightPercent and ``vol%`` VolumePercent as an extra class of the
quantity, where they mean what they say.

The three fraction keys (``porosity``, ``mass_fraction``, ``volume_fraction``)
are published on [0, 1] with UnitOne whatever the percent spelling. The
fraction emitter tested the raw string ``"%"``, so ``percent``, ``wt%`` and
``vol%`` kept 0-100 values, and it skipped the shared quantity path, so
``typical_value``, ``value_text``, ``unit_text``, ``value_basis`` and
``conditions`` were lost. It now goes through the shared path.
"""

from __future__ import annotations

import copy
import json
import re
import warnings
from pathlib import Path
from typing import Any

import pytest
from pyld import jsonld as _jsonld

import battinfo
from battinfo.jsonld import CONTEXT_UNIT_SYMBOLS, record_to_jsonld
from battinfo.transform.json_to_jsonld import _descriptor_property_nodes, _descriptor_quantity_node
from battinfo.validate import validate_record_report
from battinfo.validate.jsonld import _inline_local_contexts, validate_jsonld

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "src" / "battinfo" / "data" / "examples"
CONTEXT_DIR = ROOT / "src" / "battinfo" / "data" / "context"

EMMO = "https://w3id.org/emmo#"
ECHEM = "https://w3id.org/emmo/domain/electrochemistry#electrochemistry_"
PERCENT_UNIT = ECHEM + "8430be19_6cae_4a15_a570_3c15d0d190eb"
WEIGHT_PERCENT = ECHEM + "2c0e66c8_d58d_44b2_b0ce_ba55194bd505"
VOLUME_PERCENT = ECHEM + "db37b358_b2f0_4e06_b6ae_8c56c8fbb6ba"
UNIT_ONE = EMMO + "EMMO_5ebd5e01_0ed3_49a2_a30d_cd05cbe72978"
POROSITY = EMMO + "EMMO_3a6578ac_aee0_43b9_9bc6_1eb208c8c9a9"
MEASURED_PROPERTY = EMMO + "EMMO_873b0ab3_88e6_4054_b901_5531e01f14a4"
HAS_MEASUREMENT_UNIT = EMMO + "EMMO_bed1d005_b04e_4a90_94cf_02bc678a8569"
HAS_NUMERICAL_PART = EMMO + "EMMO_8ef3cd6d_ae58_4a8d_9fc0_ad8f49015cd0"
HAS_NUMBER_VALUE = EMMO + "EMMO_faf79f53_749d_40b2_807c_d34244c192f4"

PLAIN_SPELLINGS = ["%", "percent", "pct", " %"]
MASS_SPELLINGS = ["wt%", "wt.%"]
VOLUME_SPELLINGS = ["vol%", "vol.%", "v/v%"]
FRACTION_TERMS = {"mass_fraction": "MassFraction", "volume_fraction": "VolumeFraction", "porosity": "Porosity"}


def _quiet(fn, *args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fn(*args, **kwargs)


def _warned(fn, *args, **kwargs) -> tuple[Any, list[str]]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = fn(*args, **kwargs)
    return result, [str(w.message) for w in caught]


def _basis_warnings(messages: list[str]) -> list[str]:
    return [m for m in messages if m.startswith("semantic.percent_basis_mismatch")]


# ── Keys other than the fractions: PercentUnit, plus the stated basis ─────────


@pytest.mark.parametrize("spelling", PLAIN_SPELLINGS)
def test_plain_percent_spellings_give_the_percent_unit_and_no_basis(spelling: str) -> None:
    node = _descriptor_quantity_node("state_of_health", {"value": 95, "unit": spelling})
    assert node == {
        "@type": ["StateOfHealth", "ConventionalProperty"],
        "skos:prefLabel": "StateOfHealth",
        "hasNumericalPart": {"@type": "RealData", "hasNumberValue": 95},
        "hasMeasurementUnit": PERCENT_UNIT,
    }


@pytest.mark.parametrize(
    ("spelling", "basis"),
    [(s, "WeightPercent") for s in MASS_SPELLINGS] + [(s, "VolumePercent") for s in VOLUME_SPELLINGS],
)
def test_a_spelling_that_states_a_basis_adds_its_percent_class(spelling: str, basis: str) -> None:
    node = _quiet(_descriptor_quantity_node, "binder_content", {"value": 5, "unit": spelling})
    assert node is not None
    assert node["@type"] == ["ConventionalProperty", basis]
    assert node["hasMeasurementUnit"] == PERCENT_UNIT
    assert node["hasNumericalPart"]["hasNumberValue"] == 5


def test_a_basis_written_in_unit_text_is_kept_too() -> None:
    node = _quiet(_descriptor_quantity_node, "binder_content", {"value": 5, "unit": "%", "unit_text": "wt%"})
    assert node is not None and node["@type"] == ["ConventionalProperty", "WeightPercent"]


def test_a_test_condition_in_percent_uses_the_percent_unit() -> None:
    """A test's state-of-charge condition was published as a weight percent."""
    node = _descriptor_quantity_node("state_of_charge", {"value": 50, "unit": "%"}, term="StateOfCharge")
    assert node is not None
    assert node["hasMeasurementUnit"] == PERCENT_UNIT
    assert node["@type"] == ["StateOfCharge", "ConventionalProperty"]


def test_the_basis_class_expands_and_validates_under_the_publisher_policy() -> None:
    """WeightPercent was a unit term, so the validator refused it as an @type."""
    record = json.loads((EXAMPLES / "separator-spec" / "wgym-4xfa-pws1-ek1b.json").read_text(encoding="utf-8"))
    record["separator_spec"]["property"]["water_content"] = {"value": 0.02, "unit": "wt%"}
    doc = _quiet(record_to_jsonld, record, "separator-spec")
    report = validate_jsonld(doc, policy="publisher")
    assert [issue for issue in report.issues if issue.code.startswith("jsonld.type")] == []
    expanded = json.dumps(_jsonld.expand(_inline_local_contexts(doc)))
    assert WEIGHT_PERCENT in expanded
    assert PERCENT_UNIT in expanded


@pytest.mark.parametrize("spelling", PLAIN_SPELLINGS)
def test_every_plain_percent_spelling_passes_the_unit_check(spelling: str) -> None:
    """The validator knew only % and percent, so a strict save refused pct."""
    record = battinfo.CellSpec(
        id="https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
        manufacturer="Example Lab",
        model="P1",
        format="coin",
        chemistry="li-ion",
        source_type="manual",
        properties={"capacity_fade": {"value": 20, "unit": spelling}},
    ).to_record()
    report = validate_record_report(record, policy="strict")
    assert [issue.message for issue in report.issues if issue.code == "semantic.unit_mismatch"] == []


# ── The fraction keys: [0, 1] with UnitOne whatever the spelling ──────────────


@pytest.mark.parametrize("key", list(FRACTION_TERMS))
@pytest.mark.parametrize("spelling", PLAIN_SPELLINGS + MASS_SPELLINGS + VOLUME_SPELLINGS)
def test_a_fraction_in_any_percent_spelling_rescales_to_unit_one(key: str, spelling: str) -> None:
    (node,) = _quiet(_descriptor_property_nodes, {key: {"value": 41, "unit": spelling}})
    assert node["@type"] == [FRACTION_TERMS[key], "ConventionalProperty"]
    assert node["hasNumericalPart"] == {"@type": "RealData", "hasNumberValue": 0.41}
    assert node["hasMeasurementUnit"] == UNIT_ONE


@pytest.mark.parametrize(
    ("key", "spelling", "warns"),
    [
        ("mass_fraction", "vol%", True),
        ("mass_fraction", "v/v%", True),
        ("mass_fraction", "wt%", False),
        ("mass_fraction", "%", False),
        ("volume_fraction", "wt%", True),
        ("volume_fraction", "wt.%", True),
        ("volume_fraction", "vol%", False),
        ("volume_fraction", "percent", False),
        ("porosity", "wt%", True),
        ("porosity", "vol%", False),
        ("porosity", "%", False),
    ],
)
def test_a_basis_that_contradicts_the_fraction_warns(key: str, spelling: str, warns: bool) -> None:
    nodes, messages = _warned(_descriptor_property_nodes, {key: {"value": 20, "unit": spelling}})
    assert nodes[0]["hasNumericalPart"]["hasNumberValue"] == 0.2
    assert bool(_basis_warnings(messages)) is warns


def test_a_fraction_keeps_typical_value_bounds_and_spread_on_the_same_scale() -> None:
    (node,) = _descriptor_property_nodes(
        {"porosity": {"typical_value": 35, "min_value": 30, "max_value": 40, "standard_deviation": 1.2, "unit": "%"}}
    )
    assert node["hasNumericalPart"]["hasNumberValue"] == 0.35
    assert (node["schema:minValue"], node["schema:maxValue"]) == (0.3, 0.4)
    assert node["schema:valueReference"]["schema:value"] == 0.012
    assert node["hasMeasurementUnit"] == UNIT_ONE


def test_a_fraction_given_as_text_keeps_the_text() -> None:
    (node,) = _descriptor_property_nodes({"porosity": {"value_text": "35-40", "unit_text": "%"}})
    assert node["hasStringValue"] == "35-40"
    assert node["@type"] == ["Porosity", "ConventionalProperty"]


def test_a_fraction_in_unit_text_alone_rescales() -> None:
    """unit_text '%' used to give a unitless 40."""
    (node,) = _descriptor_property_nodes({"porosity": {"value": 40, "unit_text": "%"}})
    assert node["hasNumericalPart"]["hasNumberValue"] == 0.4
    assert node["hasMeasurementUnit"] == UNIT_ONE


def test_a_measured_fraction_keeps_its_basis_and_conditions() -> None:
    (node,) = _descriptor_property_nodes(
        {
            "porosity": {
                "value": 0.4,
                "unit": "1",
                "value_basis": "Measured",
                "conditions": {"temperature": {"value": 25, "unit": "degC"}},
            }
        }
    )
    assert node["@type"] == ["Porosity", "MeasuredProperty"]
    assert node["isOutputOf"]["hasMeasurementParameter"]["skos:prefLabel"] == "temperature"


def test_a_numeric_string_fraction_rescales_and_text_is_left_alone() -> None:
    (node,) = _descriptor_property_nodes({"mass_fraction": {"value": "95", "unit": "%"}})
    assert node["hasNumericalPart"]["hasNumberValue"] == 0.95
    (text,) = _descriptor_property_nodes({"mass_fraction": {"value": "about 95", "unit": "%"}})
    assert text["hasMeasurementUnit"] == PERCENT_UNIT


def test_a_separator_porosity_in_percent_is_published_on_unit_one() -> None:
    record = json.loads((EXAMPLES / "separator-spec" / "wgym-4xfa-pws1-ek1b.json").read_text(encoding="utf-8"))
    record["separator_spec"]["property"]["porosity"] = {
        "value": 41,
        "unit": "percent",
        "value_basis": "Measured",
    }
    doc = _quiet(record_to_jsonld, record, "separator-spec")
    nodes = [
        node
        for top in _jsonld.expand(_inline_local_contexts(doc))
        for described in top.get(EMMO + "EMMO_f702bad4_fc77_41f0_a26d_79f6444fd4f3", [])
        for node in described.get(EMMO + "EMMO_e1097637_70d2_4895_973f_2396f04fa204", [])
        if POROSITY in node.get("@type", [])
    ]
    (porosity,) = nodes
    assert set(porosity["@type"]) == {POROSITY, MEASURED_PROPERTY}
    assert porosity[HAS_MEASUREMENT_UNIT] == [{"@id": UNIT_ONE}]
    (number,) = porosity[HAS_NUMERICAL_PART]
    assert number[HAS_NUMBER_VALUE][0]["@value"] == 0.41


def test_validation_warns_about_a_contradicting_basis_under_every_policy() -> None:
    record = json.loads((EXAMPLES / "separator-spec" / "wgym-4xfa-pws1-ek1b.json").read_text(encoding="utf-8"))
    record["separator_spec"]["property"]["porosity"] = {"value": 41, "unit": "wt%"}
    for policy in ("default", "strict", "publisher"):
        report = validate_record_report(record, policy=policy)
        found = [issue for issue in report.issues if issue.code == "semantic.percent_basis_mismatch"]
        assert len(found) == 1, policy
        assert found[0].severity == "warning"
        assert found[0].path == "separator_spec.property.porosity"
    clean = copy.deepcopy(record)
    clean["separator_spec"]["property"]["porosity"]["unit"] = "vol%"
    report = validate_record_report(clean, policy="strict")
    assert not [issue for issue in report.issues if issue.code == "semantic.percent_basis_mismatch"]


# ── The contexts and the Create page write PercentUnit ────────────────────────


def _expand_with(context: dict[str, Any], value: Any) -> str:
    iri = value["@id"] if isinstance(value, dict) else value
    prefix, _, local = iri.partition(":")
    base = context.get(prefix)
    return base + local if isinstance(base, str) and base.endswith(("#", "/")) else iri


def test_every_percent_term_expands_to_the_percent_unit() -> None:
    v1 = json.loads((CONTEXT_DIR / "records.context.v1.json").read_text(encoding="utf-8"))["@context"]
    flat = json.loads((CONTEXT_DIR / "records.context.json").read_text(encoding="utf-8"))["@context"]
    assert _expand_with(v1, CONTEXT_UNIT_SYMBOLS["%"]) == PERCENT_UNIT
    for context in (v1, flat):
        assert _expand_with(context, context["%"]) == PERCENT_UNIT
    assert _expand_with(v1, v1["PercentUnit"]) == PERCENT_UNIT
    # The two quantity classes keep their terms and their IRIs.
    assert _expand_with(v1, v1["WeightPercent"]) == WEIGHT_PERCENT
    assert _expand_with(v1, v1["VolumePercent"]) == VOLUME_PERCENT


def test_the_create_page_writes_the_percent_unit() -> None:
    source = (ROOT / "web" / "lib" / "create-model.ts").read_text(encoding="utf-8")
    assert re.search(r'"%":\s*ECHEM\s*\+\s*"electrochemistry_8430be19_6cae_4a15_a570_3c15d0d190eb"', source)
    assert 'Percent"' not in source.split("const UNIT_IRI", 1)[1].split("};", 1)[0]


def test_no_packaged_example_publishes_a_percent_quantity_as_a_unit() -> None:
    from battinfo.jsonld import _TRANSFORMERS

    kinds = {kind.replace("_", "-") for kind in _TRANSFORMERS}
    wrong = {WEIGHT_PERCENT, VOLUME_PERCENT, EMMO + "Percent"}
    found: list[str] = []
    for path in sorted(EXAMPLES.rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        kind = next((key.replace("_", "-") for key in record if key.replace("_", "-") in kinds), None)
        if kind is None:
            continue
        text = json.dumps(_quiet(record_to_jsonld, record, kind))
        found.extend(f"{path.name}: {iri}" for iri in wrong if f'"hasMeasurementUnit": "{iri}"' in text)
    assert found == []
