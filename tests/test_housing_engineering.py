"""Tests for the engineering cell-description layer (E1-E5):

- Housing model (Case / Cap / Terminal / Seal / HardwarePart) + format-typed JSON-LD
- CurrentCollectorTab on the electrode
- CellConstruction stack/winding fields -> ElectrodeStack / JellyRoll
- legacy coin_hardware -> housing migration adapter and round-trip
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import CellSpec  # noqa: E402
from battinfo.authoring import (  # noqa: E402
    bom,
    case,
    cell_description,
    construction,
    electrode,
    hardware_part,
    housing,
    material,
    properties,
    seal,
    tab,
    terminal,
)
from battinfo.transform.json_to_jsonld import to_jsonld  # noqa: E402


def _battery_node(spec: CellSpec) -> dict:
    """Export a spec to validated domain-battery JSON-LD and return the battery node."""
    spec_dict = spec.to_json()
    if "properties" in spec_dict and "property" not in spec_dict:
        spec_dict["property"] = spec_dict["properties"]
    doc = to_jsonld({"schema_version": "1.0.0", "specification": spec_dict}, target="domain-battery")
    return doc["@graph"][0]


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _prop_types(node: dict) -> set[str]:
    types: set[str] = set()
    for prop in _as_list(node.get("hasProperty")):
        if isinstance(prop, dict):
            t = prop.get("@type")
            types.update(t if isinstance(t, list) else [t])
    return types


# --------------------------------------------------------------------------- #
# Housing model
# --------------------------------------------------------------------------- #


def _prismatic_housing():
    return housing(
        case=case(material="Aluminium", size_code="173x115x45",
                  weight={"value": 115, "unit": "g"}, available_volume={"value": 778, "unit": "cm3"}),
        cap=hardware_part("cap", material="Aluminium", weight={"value": 113, "unit": "g"}),
        terminals=[
            terminal(polarity="positive", material="Aluminium", width={"value": 50, "unit": "mm"}),
            terminal(polarity="negative", material="Copper", width={"value": 50, "unit": "mm"}),
        ],
        seals=[seal(thickness={"value": 0.26, "unit": "mm"})],
    )


def _prismatic_spec(housing_model=None, construction_model=None):
    return cell_description(
        id="https://w3id.org/battinfo/spec/eng-prism",
        manufacturer="EngCo", model="prism-100Ah", format="prismatic", chemistry="li-ion",
        positive_electrode_basis="lfp", negative_electrode_basis="graphite",
        housing=housing_model, construction=construction_model,
        properties=properties(nominal_capacity={"value": 100, "unit": "Ah"}),
    )


def test_housing_round_trips_through_library_record() -> None:
    spec = _prismatic_spec(housing_model=_prismatic_housing())
    restored = CellSpec.from_library_record(spec.to_library_record())

    assert restored.housing is not None
    assert restored.housing.case.material == "Aluminium"
    assert restored.housing.case.size_code == "173x115x45"
    assert restored.housing.cap.type == "cap"
    assert len(restored.housing.terminals) == 2
    assert {t.polarity for t in restored.housing.terminals} == {"positive", "negative"}
    assert restored.housing.seals[0].property["thickness"]["value"] == 0.26


def test_housing_emits_format_typed_case_and_constituents() -> None:
    battery = _battery_node(_prismatic_spec(housing_model=_prismatic_housing()))

    case_node = battery["hasCase"]
    assert "PrismaticCase" in (case_node["@type"] if isinstance(case_node["@type"], list) else [case_node["@type"]])
    assert case_node["schema:size"] == "173x115x45"
    assert {"Volume", "Mass"} <= _prop_types(case_node)

    terminals = _as_list(battery.get("hasTerminal"))
    assert {t.get("schema:additionalType") for t in terminals} == {"positive", "negative"}
    assert all(t["@type"] == "Terminal" for t in terminals)

    constituent_types = {
        t for node in _as_list(battery.get("hasConstituent")) if isinstance(node, dict)
        for t in (_as_list(node.get("@type")))
    }
    assert "Seal" in constituent_types
    assert "CellLid" in constituent_types  # cap


def test_case_type_follows_cell_format() -> None:
    expected = {"prismatic": "PrismaticCase", "pouch": "PouchCase", "cylindrical": "CylindricalCase"}
    for fmt, case_type in expected.items():
        spec = cell_description(
            id=f"https://w3id.org/battinfo/spec/{fmt}", manufacturer="M", model=fmt, format=fmt,
            chemistry="li-ion", positive_electrode_basis="lfp", negative_electrode_basis="graphite",
            housing=housing(case=case(material="Aluminium")),
        )
        battery = _battery_node(spec)
        types = battery["hasCase"]["@type"]
        assert case_type in (types if isinstance(types, list) else [types])


# --------------------------------------------------------------------------- #
# CurrentCollectorTab
# --------------------------------------------------------------------------- #


def test_electrode_tab_round_trips_and_emits() -> None:
    spec = cell_description(
        id="https://w3id.org/battinfo/spec/eng-tab", manufacturer="EngCo", model="tab", format="prismatic",
        chemistry="li-ion", positive_electrode_basis="lfp", negative_electrode_basis="graphite",
        positive_electrode=electrode(
            bom=bom(active_material=material("LFP")), current_collector="Aluminium foil",
            tab=tab(material="Aluminium", width={"value": 50, "unit": "mm"}, thickness={"value": 0.65, "unit": "mm"}),
        ),
    )
    restored = CellSpec.from_library_record(spec.to_library_record())
    assert restored.positive_electrode.tab.material == "Aluminium"
    assert restored.positive_electrode.tab.property["width"]["value"] == 50

    battery = _battery_node(spec)
    tab_node = battery["hasPositiveElectrode"]["hasCurrentCollectorTab"]
    assert tab_node["@type"] == "CurrentCollectorTab"
    assert tab_node["schema:material"] == "Aluminium"
    assert {"Width", "Thickness"} <= _prop_types(tab_node)


# --------------------------------------------------------------------------- #
# Construction stack / jelly-roll
# --------------------------------------------------------------------------- #


def _assembly_node(battery: dict, type_name: str) -> dict | None:
    for node in _as_list(battery.get("hasConstituent")):
        if isinstance(node, dict) and node.get("@type") == type_name:
            return node
    return None


def test_stacked_construction_emits_electrode_stack() -> None:
    spec = _prismatic_spec(construction_model=construction(
        assembly_type="stacked", cathode_sheet_count=127, anode_sheet_count=130,
        separator_sheet_count=258, electrode_length={"value": 155, "unit": "mm"}))
    battery = _battery_node(spec)
    stack = _assembly_node(battery, "ElectrodeStack")
    assert stack is not None, "expected an ElectrodeStack constituent"
    assert "Length" in _prop_types(stack)
    counts = {p["schema:name"]: p["schema:value"] for p in _as_list(stack.get("schema:additionalProperty"))}
    assert counts.get("Cathode Sheet Count") == 127
    assert counts.get("Separator Sheet Count") == 258


def test_wound_construction_emits_jellyroll() -> None:
    spec = cell_description(
        id="https://w3id.org/battinfo/spec/eng-roll", manufacturer="EngCo", model="roll", format="cylindrical",
        chemistry="li-ion", positive_electrode_basis="nca", negative_electrode_basis="graphite",
        construction=construction(assembly_type="wound", layering="jelly-roll", winding_turns=28,
                                  jellyroll_volume={"value": 663, "unit": "cm3"}),
    )
    battery = _battery_node(spec)
    roll = _assembly_node(battery, "JellyRoll")
    assert roll is not None, "expected a JellyRoll constituent"
    assert "Volume" in _prop_types(roll)


# --------------------------------------------------------------------------- #
# Legacy coin_hardware -> housing migration
# --------------------------------------------------------------------------- #


def test_legacy_coin_hardware_kwarg_migrates_to_housing() -> None:
    spec = cell_description(
        id="https://w3id.org/battinfo/spec/eng-coin", manufacturer="M", model="coin", format="coin",
        chemistry="li-ion", positive_electrode_basis="lfp", negative_electrode_basis="graphite",
        coin_hardware={
            "case": {"size_code": "R2032", "material": "Stainless steel"},
            "spring": {"property": {"diameter": {"value": 15, "unit": "mm"}}},
            "spacer": {"property": {"thickness": {"value": 1.0, "unit": "mm"}}},
        },
    )
    assert spec.housing is not None
    assert spec.housing.case.size_code == "R2032"
    parts = {p.type: p for p in spec.housing.parts}
    assert parts["spring"].property["diameter"]["value"] == 15
    assert parts["spacer"].property["thickness"]["value"] == 1.0


def test_legacy_coin_hardware_record_loads_into_housing() -> None:
    record = {
        "schema_version": "1.0.0",
        "specification": {
            "id": "https://w3id.org/battinfo/spec/eng-legacy", "manufacturer": "M", "model": "legacy",
            "format": "coin", "chemistry": "li-ion",
            "coin_hardware": {"case": {"size_code": "R2032", "material": "Stainless steel"},
                              "spring": {"property": {"diameter": {"value": 15, "unit": "mm"}}}},
        },
        "provenance": {},
    }
    spec = CellSpec.from_library_record(record)
    assert spec.housing is not None
    assert spec.housing.case.material == "Stainless steel"
    # On re-serialization the on-disk key is `housing`, not the retired `coin_hardware`.
    out = spec.to_library_record()["specification"]
    assert "coin_hardware" not in out
    assert out["housing"]["case"]["size_code"] == "R2032"


def test_coin_housing_still_emits_case_and_hardware() -> None:
    """The coin descriptor path keeps emitting a case + spring/spacer from the migrated housing."""
    spec = cell_description(
        id="https://w3id.org/battinfo/spec/eng-coin2", manufacturer="M", model="coin2", format="coin",
        chemistry="li-ion", positive_electrode_basis="lfp", negative_electrode_basis="graphite",
        coin_hardware={"case": {"size_code": "R2032", "material": "Stainless steel"},
                       "spring": {"property": {"diameter": {"value": 15, "unit": "mm"}}}},
    )
    battery = _battery_node(spec)
    assert battery["hasCase"]["schema:size"] == "R2032"
    assert battery.get("hasConstituent") is not None


def test_cell_spec_record_with_inline_housing_classifies_as_record() -> None:
    """A cell_spec record carrying an inline housing must emit as the record, not
    misroute to the standalone-component (housing) emitter.

    Regression: the dispatch sniffed component families (housing/electrode/...)
    before the record's own cell_spec key, so a fully-loaded cell_spec got the
    invalid fallback @type 'Case' and JSON-LD validation failed.
    """
    import warnings

    from battinfo.jsonld import record_to_jsonld
    from battinfo.validate.jsonld import validate_jsonld_report

    record = {
        "schema_version": "0.2.0",
        "cell_spec": {
            "id": "https://w3id.org/battinfo/spec/eng-inline-0001",
            "name": "Inline", "model": "M",
            "manufacturer": {"type": "Organization", "name": "A"},
            "cell_format": "cylindrical", "chemistry": "Li-ion",
        },
        "housing": {
            "cell_format": "cylindrical",
            "case": {"material": "steel", "size_code": "18650"},
            "parts": [{"type": "can", "material": "steel"}, {"type": "vent"}],
        },
        "properties": {"nominal_capacity": {"value": 2.5, "unit": "Ah"}},
        "provenance": {"source_type": "datasheet", "source_file": "x.pdf"},
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = record_to_jsonld(record, "cell-spec")
    types = out["@type"] if isinstance(out["@type"], list) else [out["@type"]]
    assert "BatteryCellSpecification" in types, types
    errors = [i.message for i in validate_jsonld_report(out).issues if i.severity == "error"]
    assert not errors, errors


def test_housing_spec_save_gate_accepts_vent_part() -> None:
    """A safety vent is standard cylindrical hardware; the housing-spec save gate
    must accept parts[].type == 'vent' (previously only expressible as 'other')."""
    from battinfo.validate.schema import schema_for_rel_path, validate_schema_data

    schema = schema_for_rel_path("housing-spec.schema.json")
    enum = schema["$defs"]["HardwarePart"]["properties"]["type"]["enum"]
    assert "vent" in enum

    record = {
        "schema_version": "0.2.0",
        "housing_spec": {
            "id": "https://w3id.org/battinfo/housing-spec/aaaa-bbbb-cccc-dddd",
            "name": "vented can", "cell_format": "cylindrical",
            "case": {"material": "steel"},
            "parts": [{"type": "vent"}],
        },
        "provenance": {"source_type": "datasheet", "source_file": "x.pdf"},
    }
    report = validate_schema_data(record, schema)
    errors = [i.message for i in report.issues if i.severity == "error"]
    assert not errors, errors
