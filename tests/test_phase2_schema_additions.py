"""Phase-2 authoring additions to the record schemas and models.

Covers the additive schema changes (SpecItem co_type/conditions, coating roles,
inline separator fields, typed housing/tab, construction module, current-collector
material/form, Terminal.type) and the two sanctioned tightenings (FlexDate pattern,
test.conditions as quantities).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from battinfo.authoring import bom, case, cell_description, electrode, housing, properties, separator_spec, terminal
from battinfo.bundle import CellSpecification, Separator, _coerce_spec_value
from battinfo.bundle_adapter import _dict_to_spec_value, _spec_value_to_dict
from battinfo.bundle_generated import SpecValue
from battinfo.transform.json_to_jsonld import to_jsonld

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "assets" / "schemas"


def _registry() -> Registry:
    registry = Registry()
    for path in sorted(SCHEMAS.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc.get("$id"), str):
            registry = registry.with_resource(doc["$id"], Resource.from_contents(doc))
    return registry


def _validator(schema_file: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / schema_file).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=_registry())


def _errors(schema_file: str, doc: dict) -> list[str]:
    return [e.message for e in _validator(schema_file).iter_errors(doc)]


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _battery_node(spec: CellSpecification) -> dict:
    return to_jsonld(spec.to_library_record(), target="domain-battery")["@graph"][0]


SPEC_IRI = "https://w3id.org/battinfo/spec/0123-4567-89ab-cdef"


def _cell_spec_record(**overrides) -> dict:
    record = {
        "schema_version": "0.7.0",
        "cell_spec": {
            "id": SPEC_IRI,
            "name": "Acme A1",
            "model": "A1",
            "manufacturer": {"name": "Acme"},
            "cell_format": "prismatic",
            "chemistry": "Li-ion",
        },
        "provenance": {"source_type": "datasheet"},
    }
    record.update(overrides)
    return record


# --------------------------------------------------------------------------- #
# A.1 SpecItem co_type + conditions
# --------------------------------------------------------------------------- #


def test_spec_item_accepts_value_basis_and_conditions() -> None:
    record = _cell_spec_record(
        properties={
            "nominal_capacity": {
                "value": 100,
                "unit": "Ah",
                "value_basis": "Rated",
                "conditions": {
                    "discharging_c_rate": {"value": 0.2, "unit": "C"},
                    "temperature": {"value": 25, "unit": "degC"},
                },
            }
        }
    )
    assert _errors("cell-spec.schema.json", record) == []

    bad = _cell_spec_record(properties={"nominal_capacity": {"value": 1, "unit": "Ah", "co_type": "Guessed"}})
    assert _errors("cell-spec.schema.json", bad)

    # Condition entries must themselves be quantities (value + unit).
    bad = _cell_spec_record(properties={"nominal_capacity": {"value": 1, "unit": "Ah", "conditions": {"temperature": {"value": 25}}}})
    assert _errors("cell-spec.schema.json", bad)


def test_cell_property_co_type_and_conditions_reach_jsonld() -> None:
    spec = cell_description(
        id=SPEC_IRI, manufacturer="Acme", model="A1", format="prismatic", chemistry="li-ion",
        positive_electrode_basis="lfp", negative_electrode_basis="graphite",
        properties=properties(
            nominal_capacity={
                "value": 100, "unit": "Ah", "co_type": "Measured",
                "conditions": {"discharging_c_rate": {"value": 0.2, "unit": "C"}},
            },
            rated_capacity={"value": 98, "unit": "Ah", "co_type": "Rated"},
        ),
    )
    # Round-trips through the library record unchanged.
    restored = CellSpecification.from_library_record(spec.to_library_record())
    assert restored.properties["nominal_capacity"]["co_type"] == "Measured"
    assert restored.properties["nominal_capacity"]["conditions"]["discharging_c_rate"]["unit"] == "C"

    battery = _battery_node(spec)
    nodes = {tuple(_as_list(n["@type"])): n for n in _as_list(battery.get("hasProperty"))}
    nominal = next(n for types, n in nodes.items() if "MeasuredProperty" in types)
    param = nominal["hasMeasurementParameter"]
    assert "CRate" in _as_list(param["@type"])
    assert param["hasNumericalPart"]["hasNumberValue"] == 0.2
    # RatedProperty is not published in EMMO yet: Rated is exported as ConventionalProperty.
    others = [n for n in nodes.values() if n is not nominal]
    assert others and all("ConventionalProperty" in _as_list(n["@type"]) for n in others)


def test_spec_value_model_round_trips_value_basis_and_conditions() -> None:
    payload = {"value": 3.2, "unit": "V", "value_basis": "Nominal", "conditions": {"temperature": {"value": 25, "unit": "degC"}}}
    sv = _dict_to_spec_value(payload)
    assert isinstance(sv, SpecValue)
    assert _spec_value_to_dict(sv) == payload
    assert _coerce_spec_value(sv) == payload

    # The deprecated co_type alias is still read, and normalizes on the way out.
    legacy = dict(payload)
    legacy["co_type"] = legacy.pop("value_basis")
    assert _spec_value_to_dict(_dict_to_spec_value(legacy)) == payload


# --------------------------------------------------------------------------- #
# A.2 coating roles
# --------------------------------------------------------------------------- #


def test_conductive_additive_and_other_additive_emit_like_additive() -> None:
    spec = cell_description(
        id=SPEC_IRI, manufacturer="Acme", model="A1", format="pouch", chemistry="li-ion",
        positive_electrode_basis="nmc811", negative_electrode_basis="graphite",
        positive_electrode=electrode(
            bom=bom(active_material="NMC811", binder="PVDF", conductive_additive="Carbon black", other_additive="CMC"),
        ),
    )
    library_record = spec.to_library_record()
    component = spec.to_record()["positive_electrode"]["coating"]["component"]
    assert [m["name"] for m in component["conductive_additive"]] == ["Carbon black"]
    assert [m["name"] for m in component["other_additive"]] == ["CMC"]
    assert "additive" not in component  # empty legacy slot is not written

    record = _cell_spec_record(positive_electrode=spec.to_record()["positive_electrode"])
    assert _errors("cell-spec.schema.json", record) == []

    coating = _battery_node(spec)["hasPositiveElectrode"]["hasCoating"]
    conductive = _as_list(coating["hasConductiveAdditive"])
    assert [n["schema:name"] for n in conductive] == ["Carbon black"]
    assert "ConductiveAdditive" in _as_list(conductive[0]["@type"])
    other = _as_list(coating["hasAdditive"])
    assert [n["schema:name"] for n in other] == ["CMC"]

    converter = to_jsonld(library_record, target="converter-compatible")
    conv_coating = converter["hasPositiveElectrode"]["hasCoating"]
    assert conv_coating["hasConductiveAdditive"]["@type"] == "ConductiveAdditive" or "ConductiveAdditive" in _as_list(
        conv_coating["hasConductiveAdditive"]["@type"]
    )


def test_legacy_additive_and_conductive_additive_accumulate() -> None:
    spec = cell_description(
        id=SPEC_IRI, manufacturer="Acme", model="A1", format="pouch", chemistry="li-ion",
        positive_electrode_basis="nmc811", negative_electrode_basis="graphite",
        positive_electrode=electrode(bom=bom(active_material="NMC811", additive="Carbon black", conductive_additive="CNT")),
    )
    coating = _battery_node(spec)["hasPositiveElectrode"]["hasCoating"]
    assert sorted(n["schema:name"] for n in _as_list(coating["hasConductiveAdditive"])) == ["CNT", "Carbon black"]


def test_material_class_accepts_thickener_and_dispersant() -> None:
    enum = json.loads((SCHEMAS / "material-spec.schema.json").read_text(encoding="utf-8"))["properties"]["material_spec"]["properties"]["material_class"]["enum"]
    assert {"thickener", "dispersant", "conductive_additive"} <= set(enum)


# --------------------------------------------------------------------------- #
# A.3 inline separator, A.4 typed housing / tab, A.5 construction module
# --------------------------------------------------------------------------- #


def test_inline_separator_carries_spec_fields() -> None:
    sep = separator_spec(
        material="polypropylene", name="Celgard 2400", structure="monolayer", coating="Al2O3",
        material_spec_id="https://w3id.org/battinfo/material-spec/0123-4567-89ab-cdef",
        thickness={"value": 25, "unit": "um"},
    )
    assert isinstance(sep, Separator)
    record = _cell_spec_record(separator=sep.model_dump(mode="json", exclude_none=True))
    assert _errors("cell-spec.schema.json", record) == []
    bad = _cell_spec_record(separator={"material": "PP", "structure": "quadlayer"})
    assert _errors("cell-spec.schema.json", bad)


def test_typed_housing_validates_and_rejects_unknown_keys() -> None:
    hsg = housing(
        case=case(material="Aluminium", size_code="173x115x45", wall_thickness={"value": 0.8, "unit": "mm"}),
        terminals=[terminal(polarity="positive", type="threaded_post", material="Aluminium", width={"value": 50, "unit": "mm"})],
    )
    record = _cell_spec_record(housing=hsg.to_mapping())
    assert _errors("cell-spec.schema.json", record) == []

    assert _errors("cell-spec.schema.json", _cell_spec_record(housing={"lid": {"material": "steel"}}))
    assert _errors("cell-spec.schema.json", _cell_spec_record(housing={"terminals": [{"type": "clip"}]}))

    # The housing-spec record reuses the same part definitions.
    housing_spec = {
        "schema_version": "0.7.0",
        "housing_spec": {
            "id": "https://w3id.org/battinfo/housing-spec/0123-4567-89ab-cdef",
            "name": "Prismatic can",
            **{k: v for k, v in hsg.to_mapping().items()},
        },
        "provenance": {"source_type": "manual"},
    }
    assert _errors("housing-spec.schema.json", housing_spec) == []


def test_typed_tab_validates_property_map_only() -> None:
    tab = {"material": "Aluminium", "property": {"width": {"value": 50, "unit": "mm"}, "weld_width": {"value": 8, "unit": "mm"}}}
    record = _cell_spec_record(positive_electrode={"current_collector": {"name": "Al foil", "material": "Al", "form": "foil"}, "tab": tab})
    assert _errors("cell-spec.schema.json", record) == []
    bad = _cell_spec_record(positive_electrode={"current_collector": {"name": "Al foil"}, "tab": {"width": {"value": 50, "unit": "mm"}}})
    assert _errors("cell-spec.schema.json", bad)
    bad = _cell_spec_record(positive_electrode={"current_collector": {"name": "Al foil", "form": "ribbon"}})
    assert _errors("cell-spec.schema.json", bad)


def test_construction_module_types_quantities() -> None:
    ok = _cell_spec_record(construction={"assembly_type": "wound", "winding_turns": 20, "electrode_length": {"value": 1.55, "unit": "m"}})
    assert _errors("cell-spec.schema.json", ok) == []
    bad = _cell_spec_record(construction={"electrode_length": {"length": 1.55}})
    assert _errors("cell-spec.schema.json", bad)


def test_specification_module_aligns_with_cell_spec_identity() -> None:
    spec = json.loads((SCHEMAS / "modules" / "components" / "specification.schema.json").read_text(encoding="utf-8"))
    assert spec["required"] == ["id", "name", "model", "manufacturer", "cell_format", "chemistry"]
    assert "/battinfo/spec/" in spec["properties"]["id"]["pattern"]
    assert spec["properties"]["housing"]["$ref"] == "housing.schema.json"
    assert spec["properties"]["construction"]["$ref"] == "construction.schema.json"


# --------------------------------------------------------------------------- #
# A.6 / B tightenings: FlexDate pattern, test.conditions as quantities
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value,valid", [
    ("2024", True), ("2024-03", True), ("2024-03-15", True), (1700000000, True),
    ("2024-3-5", False), ("15/03/2024", False), ("yesterday", False), ("2024-03-15T10:00:00Z", False),
])
def test_flexdate_pattern(value, valid) -> None:
    record = {
        "schema_version": "0.7.0",
        "cell_instance": {
            "id": "https://w3id.org/battinfo/cell/0123-4567-89ab-cdef",
            "cell_spec_id": SPEC_IRI,
            "manufactured_at": value,
        },
        "provenance": {"source_type": "lab"},
    }
    assert (_errors("cell-instance.schema.json", record) == []) is valid
    material = {
        "schema_version": "0.7.0",
        "material": {
            "id": "https://w3id.org/battinfo/material/0123-4567-89ab-cdef",
            "material_spec_id": "https://w3id.org/battinfo/material-spec/0123-4567-89ab-cdef",
            "received_date": value,
        },
        "provenance": {"source_type": "lab"},
    }
    assert (_errors("material.schema.json", material) == []) is valid


def test_test_conditions_must_be_quantities() -> None:
    base = {
        "schema_version": "0.7.0",
        "test": {
            "id": "https://w3id.org/battinfo/test/0123-4567-89ab-cdef",
            "cell_id": "https://w3id.org/battinfo/cell/0123-4567-89ab-cdef",
            "name": "cycling run 1",
            "kind": "cycling",
        },
        "provenance": {"source_type": "lab", "retrieved_at": 1700000000},
    }
    ok = json.loads(json.dumps(base))
    ok["test"]["conditions"] = {"ambient_temperature": {"value": 25, "unit": "degC"}}
    assert _errors("test.schema.json", ok) == []
    bad = json.loads(json.dumps(base))
    bad["test"]["conditions"] = {"ambient_temperature": "25 C"}
    assert _errors("test.schema.json", bad)
