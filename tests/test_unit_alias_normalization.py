"""ASCII and legacy unit spellings resolve to the same IRI as the canonical symbol.

The curated unit map lists one canonical symbol per unit (µm, mg/cm2, mΩ, °C, ...).
Records written on an ASCII keyboard use um, mg/cm^2, mOhm or degC; before this
normalisation those fell through to schema:unitText and lost the unit link. The
normaliser must accept those spellings on both emitter paths (domain-battery IRIs and
converter-compatible tokens) without rewriting canonical input."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from battinfo.transform import json_to_jsonld as emitter
from battinfo.transform.json_to_jsonld import (
    _converter_unit_token,
    _unit_iri,
    normalize_unit_symbol,
    to_jsonld,
)

ROOT = Path(__file__).resolve().parents[1]
UNIT_MAP = ROOT / "assets" / "mappings" / "domain-battery" / "unit_map.curated.json"


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("um", "µm"),
        ("μm", "µm"),  # Greek mu
        ("micron", "µm"),
        ("mg/cm^2", "mg/cm2"),
        ("mg/cm²", "mg/cm2"),
        ("mg / cm2", "mg/cm2"),
        ("g/cm^3", "g/cm3"),
        ("g/cm³", "g/cm3"),
        ("g/cc", "g/cm3"),
        ("kg/m^3", "kg/m3"),
        ("m^2/g", "m2/g"),
        ("cm^2", "cm2"),
        ("mOhm", "mΩ"),
        ("milliohm", "mΩ"),
        ("Ohm", "Ω"),
        ("ohm", "Ω"),
        ("mPa*s", "mPa.s"),
        ("mPa·s", "mPa.s"),
        ("mPa s", "mPa.s"),
        ("degC", "°C"),
        ("deg C", "°C"),
        ("℃", "°C"),
        ("percent", "%"),
        ("wt%", "%"),
        ("hours", "h"),
        ("sec", "s"),
        ("ml", "mL"),
        ("  V  ", "V"),
    ],
)
def test_alias_normalises_to_canonical_symbol(alias: str, canonical: str) -> None:
    assert normalize_unit_symbol(alias) == canonical


def test_canonical_symbols_pass_through_unchanged() -> None:
    data = json.loads(UNIT_MAP.read_text(encoding="utf-8"))
    for entry in data["mappings"]:
        symbol = entry["symbol"]
        if symbol == "degC":
            continue  # deliberate: degC is an ASCII spelling of °C, same IRI
        assert normalize_unit_symbol(symbol) == symbol, symbol


def test_unknown_unit_is_returned_trimmed_not_invented() -> None:
    assert normalize_unit_symbol(" furlongs ") == "furlongs"
    assert normalize_unit_symbol("") is None
    assert normalize_unit_symbol(None) is None
    assert _unit_iri("furlongs") is None


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("um", "µm"),
        ("mg/cm^2", "mg/cm2"),
        ("g/cm^3", "g/cm3"),
        ("mOhm", "mΩ"),
        ("milliohm", "mΩ"),
        ("Ohm", "Ω"),
        ("mPa*s", "mPa.s"),
        ("degC", "°C"),
        ("deg C", "°C"),
        ("kg/m^3", "kg/m3"),
        ("m^2/g", "m2/g"),
    ],
)
def test_alias_resolves_to_same_iri_as_canonical(alias: str, canonical: str) -> None:
    assert _unit_iri(canonical) is not None
    assert _unit_iri(alias) == _unit_iri(canonical)


def test_degc_and_celsius_share_an_iri() -> None:
    assert _unit_iri("degC") == _unit_iri("°C") == emitter.MANUAL_UNIT_TYPES["°C"]


@pytest.mark.parametrize(
    ("symbol", "fragment"),
    [
        ("1", "EMMO_5ebd5e01_0ed3_49a2_a30d_cd05cbe72978"),
        ("mS/cm", "MilliSiemensPerCentiMetre"),
        ("m2/g", "SquareMetrePerGram"),
        ("g/mol", "GramPerMole"),
        ("mol/kg", "MolPerKilogram"),
        ("nm", "NanoMetre"),
        ("mPa.s", "MilliPascalSecond"),
        ("mg", "MilliGram"),
        ("Hz", "Hertz"),
        ("A/Ah", "AmperePerAmpereHour"),
        ("kg/m3", "KilogramPerCubicMetre"),
        ("cm3", "CubicCentiMetre"),
        ("cm2", "SquareCentiMetre"),
    ],
)
def test_newly_curated_units_resolve(symbol: str, fragment: str) -> None:
    iri = _unit_iri(symbol)
    assert iri is not None and iri.endswith("#" + fragment), (symbol, iri)


def test_new_unit_iris_exist_in_bundled_context() -> None:
    ctx = json.loads(
        (ROOT / "src" / "battinfo" / "data" / "context" / "domain-battery.context.json").read_text(encoding="utf-8")
    )["@context"]
    known = {v if isinstance(v, str) else v.get("@id") for v in ctx.values()}
    # Units added in map version 0.5.0; older entries (Ah, V, ...) predate the label-keyed
    # context and are covered by the mapping-governance tests instead.
    added = {"mS/cm", "m2/g", "g/mol", "mol/kg", "nm", "mPa.s", "mg", "Hz", "A/Ah", "kg/m3", "cm3", "cm2"}
    data = json.loads(UNIT_MAP.read_text(encoding="utf-8"))
    checked = 0
    for entry in data["mappings"]:
        if entry["symbol"] not in added:
            continue
        iri = entry["unit_iri"]
        assert iri in known, f"{entry['symbol']} -> {iri} not in the bundled context"
        checked += 1
    assert checked == len(added)


@pytest.mark.parametrize(
    ("alias", "token"),
    [
        ("um", "emmo:MicroMetre"),
        ("µm", "emmo:MicroMetre"),
        ("mg/cm^2", "unit:MilliGM-PER-CentiM2"),
        ("mg/cm2", "unit:MilliGM-PER-CentiM2"),
        ("degC", "emmo:CelsiusTemperature"),
        ("mPa*s", "unit:MilliPA-SEC"),
        ("g/cm^3", "emmo:GramPerCubicCentiMetre"),
    ],
)
def test_converter_token_lookup_accepts_aliases(alias: str, token: str) -> None:
    assert _converter_unit_token(alias) == token


def _electrode_spec(unit: str) -> dict:
    return {
        "schema_version": "0.1.0",
        "electrode_spec": {
            "id": "https://battinfo.org/spec/electrode/test-alias",
            "name": "alias test electrode",
            "polarity": "positive",
            "coating": {
                "component": {
                    "active_material": [
                        {"name": "LFP", "property": {"mass_fraction": {"value": 0.94, "unit": "1"}}}
                    ]
                },
                "property": {"thickness": {"value": 60, "unit": unit}},
            },
        },
    }


def _find_units(node, out: list) -> None:
    if isinstance(node, dict):
        if "hasMeasurementUnit" in node:
            out.append(node["hasMeasurementUnit"])
        if "schema:unitText" in node:
            out.append(("unitText", node["schema:unitText"]))
        for v in node.values():
            _find_units(v, out)
    elif isinstance(node, list):
        for v in node:
            _find_units(v, out)


def test_end_to_end_ascii_alias_links_unit_iri() -> None:
    ascii_doc = to_jsonld(_electrode_spec("um"), target="domain-battery")
    canon_doc = to_jsonld(_electrode_spec("µm"), target="domain-battery")
    ascii_units: list = []
    canon_units: list = []
    _find_units(ascii_doc, ascii_units)
    _find_units(canon_doc, canon_units)
    assert ascii_units == canon_units
    assert "https://w3id.org/emmo#MicroMetre" in ascii_units
    assert not any(isinstance(u, tuple) for u in ascii_units), ascii_units
