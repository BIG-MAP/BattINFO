"""Only numbers are published as hasNumberValue.

The records contexts type ``hasNumberValue`` as ``xsd:double``, so one number
gets one datatype whatever the JSON-LD processor. The quantity schema still
lets ``value`` be a string "when the source value is not purely numeric", and
the shared quantity emitter copied it into ``hasNumberValue`` as it was. A
component thickness of "about 500" became ``"about 500"^^xsd:double``, an
ill-typed literal: rdflib logged a conversion traceback for it, SPARQL numeric
comparisons failed on it, and Turtle that writes doubles as bare tokens could
not be parsed.

A string that reads as a number is now published as that number. Any other
string is published as ``hasStringValue`` (unless the quantity has its own
``value_text``), with a ``semantic.value_text_only`` warning.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import pytest
from pyld import jsonld as _jsonld

import battinfo
from battinfo.jsonld import _TRANSFORMERS, record_to_jsonld
from battinfo.transform.json_to_jsonld import _descriptor_quantity_node
from battinfo.validate.jsonld import _inline_local_contexts
from battinfo.ws import AuthoringWorkspace

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "src" / "battinfo" / "data" / "examples"
RESEARCH = ROOT / "examples" / "cell-spec" / "research"
HALF_CELL = EXAMPLES / "cell-spec" / "cell-spec-g7hd-4wkq-2mtx-9npf.json"

XSD_DOUBLE = "http://www.w3.org/2001/XMLSchema#double"
HAS_NUMBER_VALUE = "https://w3id.org/emmo#EMMO_faf79f53_749d_40b2_807c_d34244c192f4"
HAS_STRING_VALUE = "https://w3id.org/emmo#EMMO_02face50_43a1_40ce_a909_dfe54d5e186b"


def _warned(fn, *args, **kwargs) -> tuple[Any, list[str]]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = fn(*args, **kwargs)
    return result, [str(w.message) for w in caught]


def _quiet(fn, *args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fn(*args, **kwargs)


def _typed_literals(doc: dict[str, Any], datatype: str) -> list[Any]:
    """Every expanded value object of *doc* with the given datatype."""
    found: list[Any] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            if "@value" in value:
                if value.get("@type") == datatype:
                    found.append(value["@value"])
                return
            for item in value.values():
                walk(item)

    walk(_jsonld.expand(_inline_local_contexts(doc)))
    return found


def _ill_typed(values: list[Any]) -> list[Any]:
    bad = []
    for value in values:
        if isinstance(value, bool):
            bad.append(value)
            continue
        try:
            float(value)
        except (TypeError, ValueError):
            bad.append(value)
    return bad


def _string_values(doc: dict[str, Any]) -> list[str]:
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key == HAS_STRING_VALUE:
                    found.extend(entry["@value"] for entry in item)
                else:
                    walk(item)

    walk(_jsonld.expand(_inline_local_contexts(doc)))
    return found


# ── The shared quantity emitter ───────────────────────────────────────────────


def test_a_value_that_is_not_a_number_is_published_as_text_with_a_warning() -> None:
    node, messages = _warned(_descriptor_quantity_node, "thickness", {"value": "about 500", "unit": "um"})
    assert "hasNumericalPart" not in node
    assert node["hasStringValue"] == "about 500"
    assert node["hasMeasurementUnit"].endswith("MicroMetre")
    assert [m for m in messages if m.startswith("semantic.value_text_only: 'thickness' value 'about 500'")]


@pytest.mark.parametrize(("value", "number"), [("3.6", 3.6), (" 42 ", 42.0), ("1e-3", 0.001), (3, 3), (2.5, 2.5)])
def test_a_value_that_reads_as_a_number_is_that_number(value: Any, number: float) -> None:
    node, messages = _warned(_descriptor_quantity_node, "thickness", {"value": value, "unit": "um"})
    published = node["hasNumericalPart"]["hasNumberValue"]
    assert published == number
    assert not isinstance(published, str)
    assert "hasStringValue" not in node
    assert not [m for m in messages if "value_text_only" in m]


@pytest.mark.parametrize("value", ["nan", "inf", "-Infinity"])
def test_a_string_that_is_not_a_finite_number_is_text(value: str) -> None:
    node = _quiet(_descriptor_quantity_node, "thickness", {"value": value, "unit": "um"})
    assert "hasNumericalPart" not in node
    assert node["hasStringValue"] == value


def test_value_text_wins_over_a_value_that_is_not_a_number() -> None:
    quantity = {"value": "about 500", "value_text": "approx. 500 um", "unit": "um"}
    node = _quiet(_descriptor_quantity_node, "thickness", quantity)
    assert "hasNumericalPart" not in node
    assert node["hasStringValue"] == "approx. 500 um"


def test_a_typical_value_is_the_number_when_the_value_is_text() -> None:
    quantity = {"value": "about 500", "typical_value": 500, "unit": "um"}
    node = _quiet(_descriptor_quantity_node, "thickness", quantity)
    assert node["hasNumericalPart"]["hasNumberValue"] == 500
    assert node["hasStringValue"] == "about 500"


def test_a_text_value_is_not_replaced_by_a_bound() -> None:
    """A single bound is the number of a bound class only when no value is stated."""
    quantity = {"value": "up to 10", "max_value": 10.0, "unit": "A"}
    node = _quiet(_descriptor_quantity_node, "pulse_charging_current", quantity)
    assert "hasNumericalPart" not in node
    assert node["schema:maxValue"] == 10.0
    assert node["hasStringValue"] == "up to 10"


def test_a_fraction_given_as_text_keeps_its_percent_unit_and_no_number() -> None:
    node = _quiet(_descriptor_quantity_node, "porosity", {"value": "about 35", "unit": "%"})
    assert "hasNumericalPart" not in node
    assert node["hasStringValue"] == "about 35"
    assert node["hasMeasurementUnit"].endswith("electrochemistry_8430be19_6cae_4a15_a570_3c15d0d190eb")


def test_a_fraction_given_as_a_numeric_string_is_rescaled() -> None:
    node = _quiet(_descriptor_quantity_node, "porosity", {"value": "35", "unit": "%"})
    assert node["hasNumericalPart"]["hasNumberValue"] == 0.35
    assert "hasStringValue" not in node


# ── Whole records, both context modes and the deposit graph ───────────────────


def _half_cell_with_text_values() -> dict[str, Any]:
    record = json.loads(HALF_CELL.read_text(encoding="utf-8"))
    record["counter_electrode"]["property"] = {
        "thickness": {"value": "about 500", "unit": "um"},
        "porosity": {"value": "about 35", "unit": "%"},
        "diameter": {"value": 16, "unit": "mm"},
    }
    return record


def test_the_record_with_text_values_is_strict_valid() -> None:
    """The schema allows the string, so nothing before the emitter catches it."""
    report = battinfo.validate_record_report(_half_cell_with_text_values(), policy="strict")
    assert list(report.errors) == []


@pytest.mark.parametrize("mode", ["url", "inline"])
def test_record_to_jsonld_writes_no_ill_typed_double(mode: str) -> None:
    doc, messages = _warned(record_to_jsonld, _half_cell_with_text_values(), "cell-spec", context=mode)
    doubles = _typed_literals(doc, XSD_DOUBLE)
    assert 16 in doubles
    assert _ill_typed(doubles) == []
    assert {"about 500", "about 35"} <= set(_string_values(doc))
    assert len([m for m in messages if m.startswith("semantic.value_text_only")]) == 2


def test_the_deposit_graph_writes_no_ill_typed_double(tmp_path: Path) -> None:
    workspace = AuthoringWorkspace(root=tmp_path, registry_url=None)
    workspace.license("cc-by-4.0")
    spec = battinfo.CellSpec(
        manufacturer="Example Lab",
        model="T1",
        format="coin",
        chemistry="li-ion",
        properties={"nominal_capacity": {"value": 3.0, "unit": "mAh"}},
        separator={
            "name": "Glass fibre",
            "material": "glass fibre",
            "property": {"thickness": {"value": "about 260", "unit": "um"}},
        },
    )
    workspace.add("cell", spec=spec, serial_numbers=["T1-01"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        workspace.save()
        deposit = json.loads(Path(workspace.preview_jsonld()).read_text(encoding="utf-8"))
    doubles = _typed_literals(deposit, XSD_DOUBLE)
    assert 3.0 in doubles
    assert _ill_typed(doubles) == []
    assert "about 260" in _string_values(deposit)


def test_every_number_in_the_packaged_examples_is_a_valid_double() -> None:
    kinds = {kind.replace("_", "-") for kind in _TRANSFORMERS}
    checked = 0
    problems: list[str] = []
    for path in sorted(EXAMPLES.rglob("*.json")) + sorted(RESEARCH.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        kind = next((key.replace("_", "-") for key in record if key.replace("_", "-") in kinds), None)
        if kind is None:
            continue
        bad = _ill_typed(_typed_literals(_quiet(record_to_jsonld, record, kind), XSD_DOUBLE))
        problems += [f"{path.name}: {value!r}" for value in bad]
        checked += 1
    assert checked > 100, checked
    assert problems == []
