"""% is a plain percent; wt% keeps the weight-percent unit.

The curated unit map used to send % to electrochemistry:WeightPercent, so a
state-of-charge cutoff or an efficiency stated in % was typed as a mass
fraction. EMMO 1.0.2 has a plain percent unit (emmo:Percent, symbol %, QUDT
unit:PERCENT), which % now maps to; wt% is listed on its own.
"""
from __future__ import annotations

import json
from pathlib import Path

from battinfo.jsonld import record_to_jsonld, resolve_unit_iri
from battinfo.transform.json_to_jsonld import _unit_iri, normalize_unit_symbol

ROOT = Path(__file__).resolve().parents[1]
PERCENT = "https://w3id.org/emmo#Percent"
WEIGHT_PERCENT = (
    "https://w3id.org/emmo/domain/electrochemistry#electrochemistry_2c0e66c8_d58d_44b2_b0ce_ba55194bd505"
)


def test_percent_is_the_emmo_percent_unit() -> None:
    assert _unit_iri("%") == PERCENT
    assert _unit_iri("percent") == PERCENT
    assert resolve_unit_iri("%") == "emmo:Percent"


def test_weight_percent_keeps_its_own_unit() -> None:
    assert normalize_unit_symbol("wt%") == "wt%"
    assert normalize_unit_symbol("wt.%") == "wt%"
    assert _unit_iri("wt%") == WEIGHT_PERCENT
    assert _unit_iri("wt.%") == WEIGHT_PERCENT
    assert resolve_unit_iri("wt%").endswith("2c0e66c8_d58d_44b2_b0ce_ba55194bd505")


def test_state_of_charge_cutoff_in_percent_is_not_a_weight_percent() -> None:
    record = {
        "test_spec": {"id": "https://w3id.org/battinfo/spec/0000-0000-0000-0002", "name": "probe", "kind": "cycling"},
        "method": [{
            "mode": "cc", "direction": "discharge",
            "setpoints": {"c_rate": {"value": 1, "unit": "C"}},
            "termination": [{"quantity": "soc", "value": 20, "unit": "%", "direction": "below"}],
        }],
    }
    term = record_to_jsonld(record, "test-protocol")["hasTask"][0]["hasTerminationParameter"][0]
    assert term["hasMeasurementUnit"] == {"@id": "emmo:Percent"}


def test_both_copies_of_the_unit_map_agree_on_percent() -> None:
    for root in (ROOT / "assets", ROOT / "src" / "battinfo" / "data"):
        table = json.loads((root / "mappings" / "domain-battery" / "unit_map.curated.json").read_text(encoding="utf-8"))
        by_symbol = {entry["symbol"]: entry["unit_iri"] for entry in table["mappings"]}
        assert by_symbol["%"] == PERCENT
        assert by_symbol["wt%"] == WEIGHT_PERCENT
