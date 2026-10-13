"""Property keys type as the curated property map says, and only as it says.

``property_map.curated.json`` is the source of truth for property IRIs, and the
``property_map.candidates.json`` beside it is generated review input. The
emitter used to load the candidates first, so a candidate entry won wherever
both files held a key: ``charging_time`` was typed as the Charging process and
``min_capacity`` as Capacity, although the curated map says ChargingTime and
MinimumCapacity. The two nominal continuous current keys were typed only
because the candidate map held them.
"""

from __future__ import annotations

import copy
import json
import sys
import warnings
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pyld import jsonld as _jsonld  # noqa: E402

from battinfo.jsonld import record_to_jsonld  # noqa: E402
from battinfo.transform import json_to_jsonld  # noqa: E402
from battinfo.validate.jsonld import _inline_local_contexts  # noqa: E402

CURATED = ROOT / "src" / "battinfo" / "data" / "mappings" / "domain-battery" / "property_map.curated.json"
A123 = ROOT / "src" / "battinfo" / "data" / "examples" / "cell-spec" / "A123__ANR26650M1-B.json"

ECHEM = "https://w3id.org/emmo/domain/electrochemistry#electrochemistry_"
HAS_PROPERTY = "https://w3id.org/emmo#EMMO_e1097637_70d2_4895_973f_2396f04fa204"

CHARGING_TIME = ECHEM + "a3d54f83_4dc2_4833_acc2_c8652702d9b7"
MINIMUM_CAPACITY = ECHEM + "d3c0078e_c1d3_461e_873d_e5c3adf441c5"
CHARGING_CURRENT = ECHEM + "79551e01_4bc6_4292_916e_08fe28a84600"
DISCHARGING_CURRENT = ECHEM + "e4d666ee_d637_45cd_a904_dc33941ead4f"
RATED_ENERGY = ECHEM + "da215d1a_196a_465f_9de8_89f6fbb76982"
STORED_ENERGY = ECHEM + "46376e5d_9627_4514_9881_9e62083625c3"
# Classes the keys above were typed with before 0.8.0.
CHARGING = ECHEM + "a9873d3d_945b_40ba_b9cd_8dfb64cec88f"
CAPACITY = ECHEM + "791c1915_a791_4450_acd8_7f94764743b5"
NOMINAL_ENERGY = ECHEM + "19e27aa3_0970_43a6_86d3_e3cdd956134d"
MAXIMUM_CONTINUOUS_CHARGING_CURRENT = ECHEM + "39d8a6ee_cd55_4855_8b5b_d42bef95ac78"
MAXIMUM_CONTINUOUS_DISCHARGING_CURRENT = ECHEM + "ba7ac581_0e13_4815_b888_013c378932f5"


def _curated() -> list[dict[str, Any]]:
    return json.loads(CURATED.read_text(encoding="utf-8"))["mappings"]


def test_every_curated_key_resolves_to_its_curated_class() -> None:
    table = json_to_jsonld._property_type_map()
    wrong = {}
    for entry in _curated():
        got = table.get(entry["key"], {})
        want = (entry["class_pref_label"], entry["class_iri"])
        if (got.get("term"), got.get("iri")) != want:
            wrong[entry["key"]] = {"emitted": (got.get("term"), got.get("iri")), "curated": want}
    assert not wrong, wrong


def test_the_candidate_map_never_types_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    tables = {
        "property_map.curated.json": {
            "mappings": [{"key": "xq", "class_iri": "https://example.org/Curated", "class_pref_label": "Curated"}]
        },
        "property_map.candidates.json": {
            "mappings": [
                {"key": "xq", "class_iri": "https://example.org/Candidate", "class_pref_label": "Candidate"},
                {"key": "yq", "class_iri": "https://example.org/CandidateOnly", "class_pref_label": "CandidateOnly"},
            ]
        },
    }
    monkeypatch.setattr(json_to_jsonld, "_load_mapping_file", lambda name: tables.get(name, {"mappings": []}))
    monkeypatch.setattr(json_to_jsonld, "MANUAL_PROPERTY_TYPES", {"xq": {"term": "Manual"}, "zq": {"term": "Manual"}})
    json_to_jsonld._property_type_map.cache_clear()
    try:
        table = json_to_jsonld._property_type_map()
        assert table["xq"] == {"term": "Curated", "iri": "https://example.org/Curated"}
        assert "yq" not in table
        # A hand-kept entry fills a gap in the curated map and never overrides it.
        assert table["zq"] == {"term": "Manual"}
    finally:
        json_to_jsonld._property_type_map.cache_clear()


@pytest.mark.parametrize(
    ("key", "label", "iri"),
    [
        ("nominal_continuous_charging_current", "ChargingCurrent", CHARGING_CURRENT),
        ("nominal_continuous_discharging_current", "DischargingCurrent", DISCHARGING_CURRENT),
    ],
)
def test_the_nominal_continuous_currents_are_curated(key: str, label: str, iri: str) -> None:
    """A standard charge or discharge current is not a maximum, so these keys do
    not share the MaximumContinuous* classes of the maximum keys."""
    (entry,) = [m for m in _curated() if m["key"] == key]
    assert (entry["class_pref_label"], entry["class_iri"]) == (label, iri)
    node = json_to_jsonld._descriptor_quantity_node(key, {"value": 2.5, "unit": "A"})
    assert node is not None and node["@type"][0] == label


def _property_types(record: dict[str, Any]) -> list[set[str]]:
    """The rdf:type IRIs of each hasProperty node, after offline JSON-LD expansion."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        doc = record_to_jsonld(record, "cell-spec")
    found: list[set[str]] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.get(HAS_PROPERTY, []):
                found.append(set(item.get("@type", [])))
            for item in value.values():
                walk(item)

    walk(_jsonld.expand(_inline_local_contexts(doc)))
    return found


@pytest.mark.parametrize(
    ("key", "quantity", "iri", "not_iri"),
    [
        ("charging_time", {"value": 3, "unit": "h"}, CHARGING_TIME, CHARGING),
        ("min_capacity", {"value": 2.3, "unit": "Ah"}, MINIMUM_CAPACITY, CAPACITY),
        (
            "nominal_continuous_charging_current",
            {"value": 2.5, "unit": "A"},
            CHARGING_CURRENT,
            MAXIMUM_CONTINUOUS_CHARGING_CURRENT,
        ),
        (
            "nominal_continuous_discharging_current",
            {"value": 2.5, "unit": "A"},
            DISCHARGING_CURRENT,
            MAXIMUM_CONTINUOUS_DISCHARGING_CURRENT,
        ),
        ("rated_energy", {"value": 8.25, "unit": "Wh"}, RATED_ENERGY, NOMINAL_ENERGY),
        ("certified_usable_energy", {"value": 8.0, "unit": "Wh"}, RATED_ENERGY, NOMINAL_ENERGY),
        ("typical_energy", {"value": 8.4, "unit": "Wh"}, STORED_ENERGY, NOMINAL_ENERGY),
    ],
)
def test_a_cell_spec_key_types_as_its_curated_class(key: str, quantity: dict, iri: str, not_iri: str) -> None:
    record = copy.deepcopy(json.loads(A123.read_text(encoding="utf-8")))
    record["properties"] = {key: quantity}
    (types,) = _property_types(record)
    assert iri in types
    assert not_iri not in types
