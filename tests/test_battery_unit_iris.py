"""Units battery records use every day get their EMMO unit IRI.

The unit map had no entry for a specific capacity in mAh/g or Ah/kg, an areal
capacity in mAh/cm2, a conductivity in S/cm or a pressure in kPa or MPa, though
the pinned EMMO closure defines all six. The JSON-LD export kept these units as
text (schema:unitText) and validation warned semantic.unit_unmapped, on 11
packaged material specs and 2 electrode specs among others. Unit map 0.5.3 adds
them. Unit map 0.5.4 adds six units that cell-spec validation accepts and the
closure also defines: W/Wh (the example unit of a power-to-energy ratio), kW,
mW, mm2, mm3 and day. Their prefLabels become terms of the v1 records context.
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
NAMESPACES = {"emmo": EMMO, "electrochemistry": "https://w3id.org/emmo/domain/electrochemistry#"}

# Unit map version -> {symbol: compact IRI} of the units it added.
ADDED = {
    "0.5.3": {
        "mAh/g": "emmo:MilliAmpereHourPerGram",
        "Ah/kg": "emmo:AmpereHourPerKilogram",
        "mAh/cm2": "emmo:MilliAmpereHourPerSquareCentiMetre",
        "S/cm": "emmo:SiemensPerCentiMetre",
        "kPa": "emmo:KiloPascal",
        "MPa": "emmo:MegaPascal",
    },
    "0.5.4": {
        "W/Wh": "electrochemistry:WattPerWattHour",
        "kW": "emmo:KiloWatt",
        "mW": "emmo:MilliWatt",
        "mm2": "emmo:SquareMilliMetre",
        "mm3": "emmo:CubicMilliMetre",
        "day": "emmo:Day",
    },
}
UNITS = {symbol: qname for added in ADDED.values() for symbol, qname in added.items()}


def _full(qname: str) -> str:
    prefix, _, name = qname.partition(":")
    return NAMESPACES[prefix] + name


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


@pytest.mark.parametrize(("symbol", "qname"), UNITS.items())
def test_the_unit_resolves_to_its_emmo_unit(symbol: str, qname: str) -> None:
    iri = _full(qname)
    assert _unit_iri(symbol) == iri
    assert resolve_unit_iri(symbol) == qname  # the test-method emitter's lookup
    assert iri in _load(ROOT / "tests" / "fixtures" / "emmo" / "closure-terms.json")["measurement_units"]
    name = qname.partition(":")[2]
    assert _load(DATA / "context" / "domain-battery.context.json")["@context"][name] == iri


@pytest.mark.parametrize("version", ADDED)
def test_the_map_note_names_each_unit(version: str) -> None:
    unit_map = _load(DATA / "mappings" / "domain-battery" / "unit_map.curated.json")
    assert tuple(int(part) for part in unit_map["version"].split(".")) >= (0, 5, 4)
    (note,) = [note for note in unit_map["notes"] if note.startswith(f"{version}:")]
    entries = {entry["symbol"]: entry for entry in unit_map["mappings"]}
    for symbol, qname in ADDED[version].items():
        name = qname.partition(":")[2]
        entry = entries[symbol]
        assert (entry["status"], entry["unit_qname"], entry["unit_pref_label"]) == ("curated", qname, name)
        assert entry["unit_iri"] == _full(qname)
        assert symbol in note and name in note, symbol


@pytest.mark.parametrize("qname", UNITS.values())
def test_the_v1_records_context_defines_the_unit_term(qname: str) -> None:
    name = qname.partition(":")[2]
    assert _load(DATA / "context" / "records.context.v1.json")["@context"][name] == qname


def test_a_power_to_energy_ratio_goes_out_with_its_unit_iri() -> None:
    doc = _load(EXAMPLES / "cell-spec" / "A123__ANR26650M1-B.json")
    doc["properties"]["power_energy_ratio"] = {"value": 30.0, "unit": "W/Wh"}
    doc["properties"]["maximum_power"] = {"value": 1.2, "unit": "kW"}
    emitted = json.dumps(record_to_jsonld(doc, "cell-spec"))
    for qname in ("electrochemistry:WattPerWattHour", "emmo:KiloWatt"):
        assert _full(qname) in emitted or qname in emitted, qname
    assert "W/Wh" not in emitted and '"kW"' not in emitted


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
