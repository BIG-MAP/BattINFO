"""Range quantities keep their bounds in JSON-LD.

The shared quantity emitter read only ``value`` and ``typical_value``. A
quantity given as a range, or as one bound, became a typed EMMO quantity node
with a unit and no number, and nothing warned: the A123 example's 10 A pulse
charging current was published as a MaximumPulseChargingCurrent without a
value. The equipment emitter dropped such quantities altogether, so four of
the MC3000 example's twelve properties never reached the JSON-LD, and channels
emitted no properties at all.

Every quantity node now carries ``schema:minValue`` and ``schema:maxValue``
for its bounds. A single bound is also the number when the curated property
map flags the node's class as that bound (``max_value`` on a Maximum class,
``min_value`` on a Minimum class). A quantity with nothing to publish warns
``semantic.quantity_not_emitted``.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import pytest
from pyld import jsonld as _jsonld

import battinfo
from battinfo.api import create_channel, create_equipment
from battinfo.jsonld import _TRANSFORMERS, record_to_jsonld
from battinfo.transform.json_to_jsonld import _descriptor_quantity_node
from battinfo.validate.jsonld import _inline_local_contexts
from battinfo.ws import AuthoringWorkspace

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "src" / "battinfo" / "data" / "examples"
RESEARCH = ROOT / "examples" / "cell-spec" / "research"

SCHEMA = "https://schema.org/"
ECHEM = "https://w3id.org/emmo/domain/electrochemistry#electrochemistry_"
MAX_PULSE_CHARGING = ECHEM + "1b2a7137_64d4_483a_8437_dcb3bedcb6da"
MAX_PULSE_DISCHARGING = ECHEM + "3e54f9e3_a31d_4821_9bfb_ef953a42c35b"
HAS_NUMBER_VALUE = "https://w3id.org/emmo#EMMO_faf79f53_749d_40b2_807c_d34244c192f4"
HAS_NUMERICAL_PART = "https://w3id.org/emmo#EMMO_8ef3cd6d_ae58_4a8d_9fc0_ad8f49015cd0"


def _quiet(fn, *args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fn(*args, **kwargs)


def _warned(fn, *args, **kwargs) -> tuple[Any, list[str]]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = fn(*args, **kwargs)
    return result, [str(w.message) for w in caught]


# ── The shared quantity emitter ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "quantity", "expected"),
    [
        # Range only, on a class that is not a bound: the bounds and no number.
        (
            "thickness",
            {"min_value": 20, "max_value": 25, "unit": "um"},
            {"schema:minValue": 20, "schema:maxValue": 25},
        ),
        # One bound on the class that names it: the bound is the number too.
        (
            "pulse_charging_current",
            {"max_value": 10.0, "unit": "A"},
            {"number": 10.0, "schema:maxValue": 10.0},
        ),
        ("min_capacity", {"min_value": 2.3, "unit": "Ah"}, {"number": 2.3, "schema:minValue": 2.3}),
        (
            "charging_cutoff_voltage",
            {"max_value": 4.2, "unit": "V"},
            {"number": 4.2, "schema:maxValue": 4.2},
        ),
        # One bound that is not the one the class names: no number.
        ("pulse_charging_current", {"min_value": 1.0, "unit": "A"}, {"schema:minValue": 1.0}),
        ("min_capacity", {"max_value": 2.5, "unit": "Ah"}, {"schema:maxValue": 2.5}),
        # One bound on a class that is no bound: no number.
        ("thickness", {"max_value": 25, "unit": "um"}, {"schema:maxValue": 25}),
        # Two bounds on a bound class: no single number to choose.
        (
            "pulse_charging_current",
            {"min_value": 0.0, "max_value": 10.0, "unit": "A"},
            {"schema:minValue": 0.0, "schema:maxValue": 10.0},
        ),
        # A value with its tolerance band: the value and both bounds.
        (
            "nominal_capacity",
            {"value": 2.5, "min_value": 2.4, "max_value": 2.6, "unit": "Ah"},
            {"number": 2.5, "schema:minValue": 2.4, "schema:maxValue": 2.6},
        ),
        # A typical value with bounds.
        (
            "nominal_voltage",
            {"typical_value": 3.3, "min_value": 2.0, "max_value": 3.6, "unit": "V"},
            {"number": 3.3, "schema:minValue": 2.0, "schema:maxValue": 3.6},
        ),
    ],
)
def test_a_quantity_carries_its_bounds(key: str, quantity: dict, expected: dict) -> None:
    node = _descriptor_quantity_node(key, quantity)
    assert node is not None
    number = expected.get("number")
    if number is None:
        assert "hasNumericalPart" not in node
    else:
        assert node["hasNumericalPart"] == {"@type": "RealData", "hasNumberValue": number}
    for bound in ("schema:minValue", "schema:maxValue"):
        assert node.get(bound) == expected.get(bound), bound
    assert "hasMeasurementUnit" in node


def test_a_quantity_with_nothing_to_publish_warns_and_is_left_out() -> None:
    node, messages = _warned(_descriptor_quantity_node, "thickness", {"unit": "um"})
    assert node is None
    assert any(m.startswith("semantic.quantity_not_emitted: 'thickness'") for m in messages)


def test_the_bound_classes_are_flagged_in_the_curated_map() -> None:
    from battinfo.transform.json_to_jsonld import _bound_classes

    flags = _bound_classes()
    assert flags["MaximumPulseChargingCurrent"] == "max"
    assert flags["MinimumCapacity"] == "min"
    assert flags["UpperVoltageLimit"] == "max"
    assert flags["LowerVoltageLimit"] == "min"
    assert "Thickness" not in flags and "NominalCapacity" not in flags


def _expanded_quantities(doc: dict) -> list[dict]:
    found: list[dict] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            if HAS_NUMERICAL_PART in value or SCHEMA + "minValue" in value or SCHEMA + "maxValue" in value:
                found.append(value)
            for item in value.values():
                walk(item)

    walk(_jsonld.expand(_inline_local_contexts(doc)))
    return found


def test_the_a123_pulse_currents_are_published_with_their_numbers() -> None:
    record = json.loads((RESEARCH / "a123-anr26650m1-b.detailed.example.json").read_text(encoding="utf-8"))
    doc = _quiet(record_to_jsonld, record, "cell-spec")
    by_class = {
        cls: node
        for node in _expanded_quantities(doc)
        for cls in node.get("@type", [])
        if cls in (MAX_PULSE_CHARGING, MAX_PULSE_DISCHARGING)
    }
    for cls, number in ((MAX_PULSE_CHARGING, 10.0), (MAX_PULSE_DISCHARGING, 120.0)):
        node = by_class[cls]
        (part,) = node[HAS_NUMERICAL_PART]
        assert part[HAS_NUMBER_VALUE][0]["@value"] == number
        assert node[SCHEMA + "maxValue"][0]["@value"] == number


def _quantity_nodes(value: Any) -> list[dict]:
    """Every EMMO quantity node of an emitted document (one with a value-basis class)."""
    found: list[dict] = []
    if isinstance(value, list):
        for item in value:
            found.extend(_quantity_nodes(item))
    elif isinstance(value, dict):
        types = value.get("@type")
        types = [types] if isinstance(types, str) else types or []
        if {"ConventionalProperty", "MeasuredProperty"} & set(types):
            found.append(value)
        for key, item in value.items():
            if key != "@context":
                found.extend(_quantity_nodes(item))
    return found


def test_every_quantity_node_in_the_packaged_examples_carries_data() -> None:
    kinds = {kind.replace("_", "-") for kind in _TRANSFORMERS}
    data_keys = ("hasNumericalPart", "hasStringValue", "schema:minValue", "schema:maxValue")
    empty: list[str] = []
    paths = sorted(EXAMPLES.rglob("*.json")) + sorted(RESEARCH.glob("*.json"))
    for path in paths:
        record = json.loads(path.read_text(encoding="utf-8"))
        kind = next((key.replace("_", "-") for key in record if key.replace("_", "-") in kinds), None)
        if kind is None:
            continue
        for node in _quantity_nodes(_quiet(record_to_jsonld, record, kind)):
            if not any(key in node for key in data_keys):
                empty.append(f"{path.name}: {node.get('skos:prefLabel')}")
    assert empty == []


PERCENT_UNIT_IRI = ECHEM + "8430be19_6cae_4a15_a570_3c15d0d190eb"
WEIGHT_PERCENT_IRI = ECHEM + "2c0e66c8_d58d_44b2_b0ce_ba55194bd505"


def _spec_node(deposit: dict[str, Any]) -> dict[str, Any]:
    return next(node for node in deposit["@graph"] if "BatteryCellSpecification" in node["@type"])


def _imported_properties(deposit: dict[str, Any], root: Path) -> dict[str, Any]:
    """The properties ws.import_() reads from a deposit, before any save."""
    path = root / "deposit.battinfo.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(deposit), encoding="utf-8")
    ws = AuthoringWorkspace(root=root, registry_url=None)
    _quiet(ws.import_, str(path))
    (spec,) = ws._ws.cell_specs
    return {key: {k: v for k, v in dict(q).items() if v is not None} for key, q in (spec.properties or {}).items()}


@pytest.fixture(scope="module")
def round_trip(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """save -> preview_jsonld -> import_ -> save for a cell spec with ranges and percents."""
    base = tmp_path_factory.mktemp("ranges")
    source = AuthoringWorkspace(root=base / "source", registry_url=None)
    source.license("cc-by-4.0")
    spec = battinfo.CellSpec(
        manufacturer="Example Lab",
        model="R1",
        format="cylindrical",
        chemistry="li-ion",
        properties={
            "nominal_voltage": {"value": 3.6, "unit": "V"},
            "maximum_pulse_charging_current": {"max_value": 10.0, "unit": "A"},
            # A number equal to its only bound, on classes that name no bound
            # and on a Maximum class given the other bound: the number stays.
            "nominal_capacity": {"value": 3.0, "max_value": 3.0, "unit": "Ah"},
            "nominal_energy": {"value": 10.8, "min_value": 10.8, "unit": "Wh"},
            "continuous_discharging_current": {"value": 20.0, "min_value": 20.0, "unit": "A"},
            # On the Maximum class it names, the bound is the number.
            "continuous_charging_current": {"value": 5.0, "max_value": 5.0, "unit": "A"},
            "height": {"min_value": 64.8, "max_value": 65.2, "unit": "mm"},
            "capacity_fade": {"value": 20.0, "unit": "pct"},
            "state_of_health": {"value": 95.0, "unit": "%"},
            "round_trip_energy_efficiency": {"value": 92.0, "unit": "%"},
        },
    )
    source.add("cell", spec=spec, serial_numbers=["R1-01"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        source.save()
        deposit_path = source.preview_jsonld()
    imported = AuthoringWorkspace(root=base / "imported", registry_url=None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        imported.import_(str(deposit_path))
        imported.save()
    folder = base / "imported" / ".battinfo" / "records" / "cell-spec"
    (record,) = [json.loads(path.read_text(encoding="utf-8")) for path in folder.glob("*.json")]
    return {"deposit": json.loads(deposit_path.read_text(encoding="utf-8")), "imported": record, "base": base}


def test_the_deposit_carries_the_bounds(round_trip: dict[str, Any]) -> None:
    nodes = {
        node["skos:prefLabel"]: node for node in _spec_node(round_trip["deposit"])["isDescriptionFor"]["hasProperty"]
    }
    assert nodes["MaximumPulseChargingCurrent"]["hasNumericalPart"]["hasNumberValue"] == 10.0
    assert nodes["MaximumPulseChargingCurrent"]["schema:maxValue"] == 10.0
    assert (nodes["Height"]["schema:minValue"], nodes["Height"]["schema:maxValue"]) == (64.8, 65.2)
    assert "hasNumericalPart" not in nodes["Height"]
    assert nodes["CapacityFadeRate"]["hasMeasurementUnit"] == PERCENT_UNIT_IRI


def test_save_preview_import_save_keeps_the_bounds(round_trip: dict[str, Any]) -> None:
    properties = round_trip["imported"]["properties"]
    assert properties["maximum_pulse_charging_current"] == {"max_value": 10.0, "unit": "A"}
    assert properties["height"] == {"min_value": 64.8, "max_value": 65.2, "unit": "mm"}
    assert properties["nominal_voltage"] == {"value": 3.6, "unit": "V"}
    # pct is one of the plain percent spellings; it comes back as %.
    assert properties["capacity_fade"] == {"value": 20.0, "unit": "%"}
    assert properties["state_of_health"] == {"value": 95.0, "unit": "%"}


def test_a_number_equal_to_its_only_bound_survives_the_round_trip(round_trip: dict[str, Any]) -> None:
    """The import collapses a number into its bound only where the emitter
    derives the number from that bound: on a class flagged as that bound."""
    properties = round_trip["imported"]["properties"]
    assert properties["nominal_capacity"] == {"value": 3.0, "max_value": 3.0, "unit": "Ah"}
    assert properties["nominal_energy"] == {"value": 10.8, "min_value": 10.8, "unit": "Wh"}
    assert properties["continuous_discharging_current"] == {"value": 20.0, "min_value": 20.0, "unit": "A"}
    assert properties["continuous_charging_current"] == {"max_value": 5.0, "unit": "A"}


def test_the_re_saved_record_publishes_the_same_numbers(round_trip: dict[str, Any], tmp_path: Path) -> None:
    """The second deposit carries every number and bound the first one did."""
    workspace = AuthoringWorkspace(root=round_trip["base"] / "imported", registry_url=None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        second = json.loads(Path(workspace.preview_jsonld(tmp_path / "second.battinfo.json")).read_text("utf-8"))

    def numbers(deposit: dict[str, Any]) -> dict[str, tuple[Any, Any, Any]]:
        return {
            node["skos:prefLabel"]: (
                (node.get("hasNumericalPart") or {}).get("hasNumberValue"),
                node.get("schema:minValue"),
                node.get("schema:maxValue"),
            )
            for node in _spec_node(deposit)["isDescriptionFor"]["hasProperty"]
        }

    first = numbers(round_trip["deposit"])
    assert numbers(second) == first
    assert first["NominalCapacity"] == (3.0, None, 3.0)
    assert first["NominalEnergy"] == (10.8, 10.8, None)
    assert first["MaximumContinuousDischargingCurrent"] == (20.0, 20.0, None)
    assert first["MaximumContinuousChargingCurrent"] == (5.0, None, 5.0)


def test_mass_thickness_and_volume_come_back_under_their_cell_spec_keys(tmp_path: Path) -> None:
    """Mass, Thickness and Volume each have an earlier curated key the cell-spec
    schema refuses (cap_assembly_weight, foil_thickness, available_volume). The
    import read the class back as that key, so the re-save failed strict
    validation."""
    properties = {
        "nominal_voltage": {"value": 3.7, "unit": "V"},
        "mass": {"min_value": 40.0, "max_value": 45.0, "unit": "g"},
        "thickness": {"value": 5.5, "unit": "mm"},
        "volume": {"value": 22.0, "unit": "cm3"},
    }
    source = AuthoringWorkspace(root=tmp_path / "source", registry_url=None)
    source.license("cc-by-4.0")
    spec = battinfo.CellSpec(
        manufacturer="Example Lab", model="P1", format="pouch", chemistry="li-ion", properties=properties
    )
    source.add("cell", spec=spec, serial_numbers=["P1-01"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        source.save()
        deposit_path = source.preview_jsonld()
    imported = AuthoringWorkspace(root=tmp_path / "imported", registry_url=None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        imported.import_(str(deposit_path))
        imported.save()
    folder = tmp_path / "imported" / ".battinfo" / "records" / "cell-spec"
    (record,) = [json.loads(path.read_text(encoding="utf-8")) for path in folder.glob("*.json")]
    assert record["properties"] == properties


def test_import_reads_a_stated_basis_and_an_old_percent_unit_back(round_trip: dict[str, Any]) -> None:
    deposit = json.loads(json.dumps(round_trip["deposit"]))
    nodes = {node["skos:prefLabel"]: node for node in _spec_node(deposit)["isDescriptionFor"]["hasProperty"]}
    nodes["CapacityFadeRate"]["@type"].append("WeightPercent")
    nodes["StateOfHealth"]["@type"].append("VolumePercent")
    # A record published before 0.8.0 wrote % as the WeightPercent class.
    nodes["RoundTripEnergyEfficiency"]["hasMeasurementUnit"] = WEIGHT_PERCENT_IRI
    properties = _imported_properties(deposit, round_trip["base"] / "edited")
    assert properties["capacity_fade"] == {"value": 20.0, "unit": "wt%"}
    assert properties["state_of_health"] == {"value": 95.0, "unit": "vol%"}
    assert properties["round_trip_energy_efficiency"] == {"value": 92.0, "unit": "%"}


def test_a_test_protocol_condition_or_safety_limit_given_as_a_range_keeps_its_bounds() -> None:
    """They were published as a JSON string of the whole quantity."""
    record = json.loads(
        (EXAMPLES / "test-protocol" / "test-protocol-2k9p-7t4r-3m6x-5n1v.json").read_text(encoding="utf-8")
    )
    record["conditions"]["temperature"] = {"min_value": 20.0, "max_value": 30.0, "unit": "degC"}
    record["safety"] = {"cell_voltage": {"max_value": 4.3, "unit": "V"}, "note": {"value_text": "fume hood"}}
    emitted = _additional(record_to_jsonld(record, "test-protocol"))
    assert emitted["temperature"] == {
        "@type": "schema:PropertyValue",
        "schema:name": "temperature",
        "schema:propertyID": "conditions",
        "schema:minValue": 20.0,
        "schema:maxValue": 30.0,
        "schema:unitText": "degC",
    }
    assert emitted["cell_voltage"]["schema:maxValue"] == 4.3
    assert emitted["note"]["schema:value"] == "fume hood"


# ── Equipment and channels ────────────────────────────────────────────────────

MC3000 = EXAMPLES / "equipment-spec" / "rchb-csx8-3vp8-ekcs.json"


def _additional(doc: dict) -> dict[str, dict]:
    values = doc.get("schema:additionalProperty") or []
    values = [values] if isinstance(values, dict) else values
    return {node["schema:name"]: node for node in values}


def test_the_mc3000_example_emits_all_twelve_properties() -> None:
    record = json.loads(MC3000.read_text(encoding="utf-8"))
    emitted = _additional(record_to_jsonld(record, "equipment-spec")["isDescriptionFor"])
    assert set(record["equipment_spec"]["property"]) <= set(emitted)
    assert len(record["equipment_spec"]["property"]) == 12
    charge = emitted["charge_current"]
    assert (charge["schema:minValue"], charge["schema:maxValue"], charge["schema:unitText"]) == (0.05, 3.0, "A")
    assert "schema:value" not in charge
    capacity = emitted["battery_capacity"]
    assert (capacity["schema:minValue"], capacity["schema:maxValue"]) == (0.1, 50.0)
    temperature = emitted["operating_temperature"]
    assert (temperature["schema:minValue"], temperature["schema:maxValue"], temperature["schema:unitText"]) == (
        0,
        40,
        "degC",
    )
    # value_text keeps its unit_text.
    assert emitted["input_power"]["schema:value"] == "DC 11-18V/4A"
    assert emitted["input_power"]["schema:unitText"] == "V/A"
    assert emitted["weight"] == {
        "@type": "schema:PropertyValue",
        "schema:name": "weight",
        "schema:value": 600,
        "schema:unitText": "g",
    }


def test_an_equipment_property_keeps_a_typical_value_and_unit_text() -> None:
    record = json.loads(MC3000.read_text(encoding="utf-8"))
    record["equipment_spec"]["property"] = {
        "resolution": {"typical_value": 1.0, "unit": "mV"},
        "accuracy": {"value": 0.1, "unit_text": "% of full scale"},
        "voltage": {"value": 5.0, "min_value": 0.0, "max_value": 5.0, "unit": "V"},
    }
    emitted = _additional(record_to_jsonld(record, "equipment-spec")["isDescriptionFor"])
    assert emitted["resolution"]["schema:value"] == 1.0
    assert emitted["accuracy"]["schema:unitText"] == "% of full scale"
    assert (emitted["voltage"]["schema:value"], emitted["voltage"]["schema:minValue"]) == (5.0, 0.0)


def test_an_equipment_property_with_nothing_to_publish_warns() -> None:
    record = json.loads(MC3000.read_text(encoding="utf-8"))
    record["equipment_spec"]["property"] = {"current": {"unit": "A"}}
    doc, messages = _warned(record_to_jsonld, record, "equipment-spec")
    assert "current" not in _additional(doc["isDescriptionFor"])
    assert any(m.startswith("semantic.quantity_not_emitted: 'current'") for m in messages)


def test_an_equipment_unit_emits_its_properties_with_bounds() -> None:
    unit = create_equipment(
        uid="bbbb-cccc-dddd-eeee",
        spec_id="https://w3id.org/battinfo/spec/rchb-csx8-3vp8-ekcs",
        serial_number="MC3K-1",
        property={"calibrated_current": {"min_value": 0.05, "max_value": 3.0, "unit": "A"}},
    )
    emitted = _additional(record_to_jsonld(unit, "equipment"))
    assert (emitted["calibrated_current"]["schema:minValue"], emitted["calibrated_current"]["schema:maxValue"]) == (
        0.05,
        3.0,
    )


def test_a_channel_emits_its_properties() -> None:
    channel = create_channel(
        uid="cccc-dddd-eeee-ffff",
        equipment_id="https://w3id.org/battinfo/equipment/bbbb-cccc-dddd-eeee",
        index=2,
        status="active",
        property={
            "current": {"max_value": 3.0, "unit": "A"},
            "voltage_max": {"value": 5.0, "unit": "V"},
        },
    )
    emitted = _additional(record_to_jsonld(channel, "channel"))
    assert set(emitted) == {"status", "current", "voltage_max"}
    assert emitted["current"]["schema:maxValue"] == 3.0
    assert emitted["voltage_max"]["schema:value"] == 5.0


def test_the_equipment_bounds_expand_to_schema_terms() -> None:
    record = json.loads(MC3000.read_text(encoding="utf-8"))
    expanded = json.dumps(_jsonld.expand(_inline_local_contexts(record_to_jsonld(record, "equipment-spec"))))
    assert SCHEMA + "minValue" in expanded and SCHEMA + "maxValue" in expanded
