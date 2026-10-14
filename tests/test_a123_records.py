"""The A123 ANR26650M1-B records hold what the A123 data sheet states.

The flagship cell spec (spec/pge5-wer6-2q82-v9k0) is the record the docs ask
readers to dereference, and it ships in the wheel together with a research copy
and a library copy. The expected values come from the A123 Systems
ANR26650M1-B data sheet, revision MD100113-02 (2012), the revision whose
wording the flagship's raw texts quote.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from battinfo import record_to_jsonld
from battinfo.validate import ValidationPolicy, validate_record_report

ROOT = Path(__file__).resolve().parents[1]
FLAGSHIP = ROOT / "examples" / "cell-spec" / "A123__ANR26650M1-B.json"
RESEARCH = ROOT / "examples" / "cell-spec" / "research" / "a123-anr26650m1-b.detailed.example.json"
EXTENDED = ROOT / "examples" / "cell-spec" / "research" / "extended.example.json"
LIBRARY = ROOT / "src" / "battinfo" / "data" / "library" / "cell-spec" / "A123__ANR26650M1-B.json"

STRICT = ValidationPolicy(name="strict", semantic="error")

# 1 um of aluminium foil (2.70 g/cm3) weighs 0.270 mg/cm2.
ALUMINIUM_MG_PER_CM2_PER_UM = 0.270

# What the data sheet states, as property key -> (number, unit).
DATASHEET = {
    "nominal_capacity": (2.5, "Ah"),
    "minimum_capacity": (2.4, "Ah"),
    "nominal_voltage": (3.3, "V"),
    "ac_internal_resistance": (6.0, "mΩ"),
    "mass": (76.0, "g"),
    "diameter": (26.0, "mm"),
    "height": (65.0, "mm"),
    "charging_voltage": (3.6, "V"),
    "nominal_continuous_charging_current": (2.5, "A"),
    "maximum_continuous_discharging_current": (50.0, "A"),
    "maximum_pulse_discharging_current": (120.0, "A"),
    "operating_temperature_min": (-30.0, "°C"),
    "operating_temperature_max": (55.0, "°C"),
    "minimum_storage_temperature": (-40.0, "°C"),
    "maximum_storage_temperature": (60.0, "°C"),
}

# Keys the data sheet does not support: the standard charge is not a maximum,
# the fast charge is not a pulse, and the operating range is not a discharge
# range alone.
NOT_ON_THE_DATASHEET = {
    "maximum_continuous_charging_current",
    "pulse_charging_current",
    "maximum_pulse_charging_current",
    "minimum_discharging_temperature",
    "maximum_discharging_temperature",
    "internal_resistance",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _number(quantity: dict[str, Any]) -> float | None:
    for key in ("value", "typical_value", "max_value"):
        if quantity.get(key) is not None:
            return float(quantity[key])
    return None


def _library_properties(record: dict[str, Any]) -> dict[str, Any]:
    return record["specification"]["property"]


def _nodes(document: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(document, dict):
        found.append(document)
        for value in document.values():
            found.extend(_nodes(value))
    elif isinstance(document, list):
        for value in document:
            found.extend(_nodes(value))
    return found


def _typed(document: dict[str, Any], label: str) -> list[dict[str, Any]]:
    return [node for node in _nodes(document) if node.get("skos:prefLabel") == label]


def test_flagship_keeps_its_published_iri() -> None:
    assert _load(FLAGSHIP)["cell_spec"]["id"] == "https://w3id.org/battinfo/spec/pge5-wer6-2q82-v9k0"


@pytest.mark.parametrize("key", sorted(DATASHEET))
def test_flagship_property_matches_the_datasheet(key: str) -> None:
    quantity = _load(FLAGSHIP)["properties"].get(key)
    assert quantity is not None, f"{key} is missing from the flagship"
    number, unit = DATASHEET[key]
    assert _number(quantity) == number
    assert quantity["unit"] == unit


def test_flagship_holds_no_value_the_datasheet_does_not_support() -> None:
    record = _load(FLAGSHIP)
    assert NOT_ON_THE_DATASHEET.isdisjoint(record["properties"])
    # Neither an IEC 61960 designation nor a country of manufacture is on the sheet.
    assert "iec_code" not in record["cell_spec"]
    assert "country_of_origin" not in record["cell_spec"]


def test_flagship_pulse_discharge_carries_its_ten_second_duration() -> None:
    quantity = _load(FLAGSHIP)["properties"]["maximum_pulse_discharging_current"]
    assert quantity["conditions"]["duration"] == {"value": 10, "unit": "s"}


def test_flagship_keeps_the_fast_charge_as_a_note() -> None:
    notes = " ".join(_load(FLAGSHIP).get("notes", []))
    assert "10 A to 3.6 V" in notes and "12 min" in notes and "80%" in notes


def test_flagship_validates_under_the_strict_policy() -> None:
    report = validate_record_report(_load(FLAGSHIP), policy=STRICT)
    assert report.ok, [issue.code for issue in report.issues]


def test_flagship_jsonld_claims_no_2_5_a_charging_maximum_and_a_120_a_pulse() -> None:
    document = record_to_jsonld(_load(FLAGSHIP), "cell-spec")

    for node in _typed(document, "MaximumContinuousChargingCurrent"):
        assert node.get("hasNumericalPart", {}).get("hasNumberValue") != 2.5
    pulses = _typed(document, "MaximumPulseDischargingCurrent")
    assert [node["hasNumericalPart"]["hasNumberValue"] for node in pulses] == [120.0]
    assert not _typed(document, "PulseChargingCurrent")


@pytest.mark.parametrize("path", [RESEARCH, EXTENDED, LIBRARY], ids=["research", "extended", "library"])
def test_copy_has_no_alumina_additive(path: Path) -> None:
    assert "Al2O3" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", [RESEARCH, EXTENDED, LIBRARY], ids=["research", "extended", "library"])
def test_copy_aluminium_foil_areal_mass_is_physical(path: Path) -> None:
    for node in _nodes(_load(path)):
        collector = node.get("current_collector")
        if not isinstance(collector, dict) or "Al" not in str(collector.get("name", "")):
            continue
        prop = collector.get("property", {})
        if "areal_mass" in prop and "thickness" in prop:
            bound = prop["thickness"]["value"] * ALUMINIUM_MG_PER_CM2_PER_UM
            assert prop["areal_mass"]["value"] <= bound * 1.05


def test_library_copy_has_a_name() -> None:
    assert _load(LIBRARY)["specification"].get("name") == "A123 ANR26650M1-B"


def test_library_copy_carries_no_unsourced_internals() -> None:
    specification = _load(LIBRARY)["specification"]
    for block in ("positive_electrode", "negative_electrode", "electrolyte", "separator"):
        assert block not in specification, block


@pytest.mark.parametrize(
    ("path", "properties"),
    [
        (RESEARCH, lambda record: record["properties"]),
        (EXTENDED, lambda record: record["properties"]),
        (LIBRARY, _library_properties),
    ],
    ids=["research", "extended", "library"],
)
def test_copy_properties_agree_with_the_flagship(path: Path, properties) -> None:
    flagship = _load(FLAGSHIP)["properties"]
    copy = properties(_load(path))
    assert set(copy) <= set(flagship), sorted(set(copy) - set(flagship))
    for key, quantity in copy.items():
        assert _number(quantity) == _number(flagship[key]), key


@pytest.mark.parametrize("path", [RESEARCH, EXTENDED], ids=["research", "extended"])
def test_research_copy_marks_its_internals_as_illustrative(path: Path) -> None:
    record = _load(path)
    for block in ("positive_electrode", "negative_electrode", "electrolyte", "separator"):
        comment = record[block].get("comment", "")
        assert "Illustrative" in comment, block


HEADER_KEYS = ("chemistry", "positive_electrode_basis", "negative_electrode_basis", "size_code")


def test_library_copy_header_agrees_with_the_flagship() -> None:
    flagship = _load(FLAGSHIP)["cell_spec"]
    specification = _load(LIBRARY)["specification"]
    for key in HEADER_KEYS:
        assert specification.get(key) == flagship.get(key), key
    assert specification.get("format") == flagship.get("cell_format")


@pytest.mark.parametrize("path", [RESEARCH, EXTENDED], ids=["research", "extended"])
def test_research_copy_header_agrees_with_the_flagship_or_says_why_not(path: Path) -> None:
    flagship = _load(FLAGSHIP)["cell_spec"]
    record = _load(path)
    header = record["cell_spec"]
    notes = " ".join(record.get("notes", []))
    for key in HEADER_KEYS:
        if header.get(key) == flagship.get(key):
            continue
        # The data sheet names no negative electrode. A copy whose illustrative
        # internals use graphite may say so in its header, but only if its notes
        # tell the reader where that basis comes from.
        assert key == "negative_electrode_basis", key
        assert "graphite basis in the header belongs to the illustrative internals" in notes


@pytest.mark.parametrize("path", [RESEARCH, EXTENDED], ids=["research", "extended"])
def test_research_copy_electrode_coatings_add_up(path: Path) -> None:
    # Loading divided by coating thickness is the coating density. Where an
    # electrode also states a compaction density, the two must agree.
    record = _load(path)
    for block in ("positive_electrode", "negative_electrode"):
        electrode = record[block]
        density = electrode.get("property", {}).get("compaction_density")
        coating = electrode["coating"]["property"]
        if density is None or "loading" not in coating or "thickness" not in coating:
            continue
        from_loading = coating["loading"]["value"] / (coating["thickness"]["value"] * 1e-4) / 1000
        assert from_loading == pytest.approx(density["value"], rel=0.03), block


def test_extended_copy_fractions_sum_to_one() -> None:
    components = _load(EXTENDED)["positive_electrode"]["coating"]["component"]
    total = sum(
        item["property"]["mass_fraction"]["value"]
        for group in ("active_material", "binder", "additive")
        for item in components.get(group, [])
    )
    assert total == pytest.approx(1.0)
