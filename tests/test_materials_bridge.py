from __future__ import annotations

import json
from pathlib import Path

import battinfo as bi
from battinfo.validate.record import validate_record

ROOT = Path(__file__).resolve().parents[1]


def test_material_spec_from_component_lifts_holder() -> None:
    holder = {"name": "LFP", "molecular_formula": "LiFePO4",
              "property": {"mass_fraction": {"value": 0.94, "unit": "1"}, "particle_d50": {"value": 1.8, "unit": "um"}}}
    spec = bi.material_spec_from_component(holder, material_class="active_material", electrode_polarity="positive")
    body = spec["material_spec"]
    assert body["name"] == "LFP"
    assert body["formula"] == "LiFePO4"
    assert body["material_class"] == "active_material"
    # cell-local fraction dropped; intrinsic property kept
    assert "mass_fraction" not in body.get("property", {})
    assert "particle_d50" in body["property"]
    assert validate_record(spec).ok


def test_material_spec_from_component_is_deterministic() -> None:
    a = bi.material_spec_from_component({"name": "Graphite"})
    b = bi.material_spec_from_component({"name": "graphite"})
    assert a["material_spec"]["id"] == b["material_spec"]["id"]  # name-normalized, stable IRI


def test_extract_material_specs_from_extended_example() -> None:
    rec = json.loads((ROOT / "examples" / "cell-spec" / "research" / "extended.example.json").read_text(encoding="utf-8"))
    specs = bi.extract_material_specs(rec)
    names = {s["material_spec"]["name"] for s in specs}
    assert {"LFP", "Graphite", "PVDF", "Carbon black", "LiPF6", "EC", "EMC"}.issubset(names)
    for spec in specs:
        assert validate_record(spec).ok


def test_link_component_to_spec_adds_reference() -> None:
    holder = {"name": "LFP"}
    spec = bi.material_spec_from_component(holder)
    linked = bi.link_component_to_spec(holder, spec["material_spec"]["id"])
    assert linked["material_spec_id"] == spec["material_spec"]["id"]
