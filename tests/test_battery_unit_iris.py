"""Six units battery records use every day get their EMMO unit IRI.

The unit map had no entry for a specific capacity in mAh/g or Ah/kg, an areal
capacity in mAh/cm2, a conductivity in S/cm or a pressure in kPa or MPa, though
the pinned EMMO closure defines all six. The JSON-LD export kept these units as
text (schema:unitText) and validation warned semantic.unit_unmapped, on 11
packaged material specs and 2 electrode specs among others. Unit map 0.5.3 adds
them, and their prefLabels become terms of the v1 records context.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from battinfo.jsonld import record_to_jsonld, resolve_unit_iri
from battinfo.transform.json_to_jsonld import _unit_iri

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src" / "battinfo" / "data"
EXAMPLES = DATA / "examples"
EMMO = "https://w3id.org/emmo#"

UNITS = {
    "mAh/g": "MilliAmpereHourPerGram",
    "Ah/kg": "AmpereHourPerKilogram",
    "mAh/cm2": "MilliAmpereHourPerSquareCentiMetre",
    "S/cm": "SiemensPerCentiMetre",
    "kPa": "KiloPascal",
    "MPa": "MegaPascal",
}


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _quantity(node: Any, type_name: str) -> dict:
    """The one quantity node typed ``type_name`` in an emitted document."""
    found: list[dict] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            types = value.get("@type")
            if type_name in (types if isinstance(types, list) else [types]) and "hasNumericalPart" in value:
                found.append(value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(node)
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize(("symbol", "name"), UNITS.items())
def test_the_unit_resolves_to_its_emmo_unit(symbol: str, name: str) -> None:
    iri = EMMO + name
    assert _unit_iri(symbol) == iri
    assert resolve_unit_iri(symbol) == f"emmo:{name}"  # the test-method emitter's lookup
    assert iri in _load(ROOT / "tests" / "fixtures" / "emmo" / "closure-terms.json")["measurement_units"]
    assert _load(DATA / "context" / "domain-battery.context.json")["@context"][name] == iri


def test_the_map_note_names_each_unit() -> None:
    unit_map = _load(DATA / "mappings" / "domain-battery" / "unit_map.curated.json")
    assert tuple(int(part) for part in unit_map["version"].split(".")) >= (0, 5, 3)
    (note,) = [note for note in unit_map["notes"] if note.startswith("0.5.3:")]
    entries = {entry["symbol"]: entry for entry in unit_map["mappings"]}
    for symbol, name in UNITS.items():
        entry = entries[symbol]
        assert (entry["status"], entry["unit_qname"], entry["unit_pref_label"]) == ("curated", f"emmo:{name}", name)
        assert symbol in note and name in note, symbol


@pytest.mark.parametrize("name", UNITS.values())
def test_the_v1_records_context_defines_the_unit_term(name: str) -> None:
    assert _load(DATA / "context" / "records.context.v1.json")["@context"][name] == f"emmo:{name}"


@pytest.mark.parametrize(("unit", "name"), [("mAh/g", "MilliAmpereHourPerGram"), ("Ah/kg", "AmpereHourPerKilogram")])
def test_a_specific_capacity_goes_out_with_its_unit_iri(unit: str, name: str) -> None:
    doc = _load(EXAMPLES / "material-spec" / "5ms1-9jv8-hr54-mn4e.json")
    doc["material_spec"]["property"]["specific_capacity"]["unit"] = unit
    quantity = _quantity(record_to_jsonld(doc, "material-spec"), "SpecificCapacity")
    assert quantity["hasMeasurementUnit"] == EMMO + name
    assert "schema:unitText" not in quantity


def test_an_areal_capacity_goes_out_with_its_unit_iri() -> None:
    doc = _load(EXAMPLES / "electrode-spec" / "qw3j-we77-zzj1-ya55.json")
    quantity = _quantity(record_to_jsonld(doc, "electrode-spec"), "AreicCapacity")
    assert quantity["hasMeasurementUnit"] == EMMO + "MilliAmpereHourPerSquareCentiMetre"
    assert "schema:unitText" not in quantity


def test_a_capacity_cutoff_in_a_test_method_carries_its_unit_iri() -> None:
    record = {
        "test_spec": {"id": "https://w3id.org/battinfo/spec/0000-0000-0000-0001", "name": "probe", "kind": "cycling"},
        "method": [
            {
                "mode": "cc",
                "direction": "discharge",
                "termination": [{"quantity": "capacity", "value": 300, "unit": "mAh/g", "direction": "above"}],
            }
        ],
    }
    (cutoff,) = record_to_jsonld(record, "test-protocol")["hasTask"][0]["hasTerminationParameter"]
    assert cutoff["hasMeasurementUnit"] == {"@id": "emmo:MilliAmpereHourPerGram"}
    assert "schema:unitText" not in cutoff
