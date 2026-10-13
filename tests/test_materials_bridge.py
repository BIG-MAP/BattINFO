from __future__ import annotations

import json
from pathlib import Path

import battinfo as bi
from battinfo.validate.record import validate_record

ROOT = Path(__file__).resolve().parents[1]


def test_material_spec_from_component_lifts_holder() -> None:
    holder = {
        "name": "LFP",
        "molecular_formula": "LiFePO4",
        "property": {"mass_fraction": {"value": 0.94, "unit": "1"}, "particle_d50": {"value": 1.8, "unit": "um"}},
    }
    spec = bi.material_spec_from_component(holder, material_class="active_material")
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
    rec = json.loads(
        (ROOT / "examples" / "cell-spec" / "research" / "extended.example.json").read_text(encoding="utf-8")
    )
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


def test_graphite_from_two_suppliers_lifts_to_two_specs(tmp_path: Path) -> None:
    """The bridge mints through the material-spec seed, not the lower-cased name."""
    imerys = {"name": "Graphite", "manufacturer": "Imerys", "product_id": "SLP30"}
    btr = {"name": "Graphite", "manufacturer": "BTR", "product_id": "BFC-18"}
    record = {
        "positive_electrode": {"coating": {"component": {"active_material": [imerys]}}},
        "negative_electrode": {"coating": {"component": {"active_material": [btr]}}},
    }
    lifted = {
        spec["material_spec"]["manufacturer"]["name"]: spec["material_spec"]
        for spec in bi.extract_material_specs(record)
    }
    assert sorted(lifted) == ["BTR", "Imerys"]
    ws = bi.workspace(tmp_path, registry_url=None)
    for holder in (imerys, btr):
        added = ws.add("material_spec", **holder)[0]["material_spec"]
        assert lifted[holder["manufacturer"]]["id"] == added["id"]
        assert added["kind"] == "graphite"


def test_graphite_and_graphite_from_one_supplier_still_merge() -> None:
    record = {
        "positive_electrode": {
            "coating": {"component": {"active_material": [{"name": "Graphite", "manufacturer": "Imerys"}]}}
        },
        "negative_electrode": {
            "coating": {"component": {"active_material": [{"name": "graphite", "manufacturer": "Imerys"}]}}
        },
    }
    assert len(bi.extract_material_specs(record)) == 1


def test_an_explicit_uid_seed_still_wins() -> None:
    from battinfo.entities import stable_uid

    spec = bi.material_spec_from_component({"name": "Graphite"}, uid_seed="lab-graphite")
    assert spec["material_spec"]["id"].endswith(stable_uid("lab-graphite"))
