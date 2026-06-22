"""Regression tests: numeric values serialized as strings must be coerced, not
stored verbatim or crashed on (audit theme B).

Interop readers commonly receive JSON-LD / CSV / spreadsheet numbers as strings
("6e-05", "15", "95"). The readers must coerce them to numbers (and drop
non-numeric placeholders) so a string never reaches arithmetic or a quantity
.value.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.interop.converter import _quantity_value  # noqa: E402
from battinfo.interop.discovery import _find_property  # noqa: E402
from battinfo.transform.json_to_jsonld import to_jsonld  # noqa: E402


def test_discovery_find_property_coerces_string_number_to_float() -> None:
    node = {"hasProperty": [{
        "@type": ["Volume"],
        "name": "Electrolyte volume",
        "hasNumericalPart": {"hasNumericalValue": "6e-05"},
        "hasMeasurementUnit": "",
    }]}
    res = _find_property(node, "Volume", "Electrolyte volume")
    assert res is not None
    assert res["value"] == 6e-05
    assert isinstance(res["value"], float)  # not the string "6e-05"


def test_discovery_find_property_skips_non_numeric_value() -> None:
    node = {"hasProperty": [{
        "@type": ["Volume"],
        "name": "Electrolyte volume",
        "hasNumericalPart": {"hasNumericalValue": "not-a-number"},
        "hasMeasurementUnit": "",
    }]}
    assert _find_property(node, "Volume", "Electrolyte volume") is None


def test_converter_quantity_value_coerces_numbers_and_drops_placeholders() -> None:
    assert _quantity_value({"hasNumericalPart": {"hasNumberValue": "15"}}) == 15.0
    assert _quantity_value({"hasNumericalPart": {"hasNumberValue": 3.2}}) == 3.2
    assert _quantity_value({"hasNumericalPart": {"hasNumberValue": "n/a"}}) is None
    # A genuine string-valued property is still preserved.
    assert _quantity_value({"hasStringValue": "blue"}) == "blue"


def test_json_to_jsonld_string_percent_fraction_does_not_crash() -> None:
    record = {
        "schema_version": "1.0",
        "specification": {
            "id": "c1", "format": "pouch",
            "positive_electrode": {"coating": {"component": {"active_material": [
                {"name": "NMC", "property": {"mass_fraction": {"value": "95", "unit": "%"}}}
            ]}}},
        },
    }
    # Must not raise TypeError on `value / 100`; "95" % -> 0.95 fraction.
    out = to_jsonld(record, target="domain-battery")
    assert "95" not in str(out.get("@type", ""))  # sanity: produced a document
    assert out is not None
