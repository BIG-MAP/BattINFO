"""A quantity's ``value`` holds a number only; text belongs in ``value_text``.

The shared quantity schema and the base schema's Quantity accepted any string
as ``value``, so 19 of 22 record kinds passed strict validation with text there,
the cell-spec conditions map included, and the emitters wrote that text as
``hasNumberValue``. Now strict validation refuses it, the emitters write
``hasNumberValue`` for finite real numbers only and send text to
``hasStringValue``, the converter importer reads ``hasStringValue`` into
``value_text``, and the places that read older records back (``ws.import_``,
``ws.load``, the spec given to ``ws.add("equipment")`` and the upsert in
``save_record``) turn a numeric string into the number and move other text to
``value_text`` with a warning.
"""

from __future__ import annotations

import copy
import json
import math
import warnings
from pathlib import Path
from typing import Any, Callable

import pytest

import battinfo
from battinfo._util import is_real_number, number_from_text
from battinfo.api import REGISTER_MODE_UPSERT, save_record
from battinfo.api._records import _compare_with_saved
from battinfo.canonical_aliases import migrate_quantity_values
from battinfo.validate import validate_record_report
from battinfo.validate.schema import build_validator
from battinfo.ws import AuthoringWorkspace

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "src" / "battinfo" / "data" / "examples"
CELL_SPEC = EXAMPLES / "cell-spec" / "A123__ANR26650M1-B.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── Strict validation ─────────────────────────────────────────────────────────


def _material_spec(quantity: dict) -> tuple[dict, str]:
    doc = _load(EXAMPLES / "material-spec" / "gwck-k5kf-ae1f-gfgc.json")
    doc["material_spec"]["property"]["true_density"] = quantity
    return doc, "material_spec.property.true_density"


def _test_condition(quantity: dict) -> tuple[dict, str]:
    doc = _load(EXAMPLES / "test" / "test-5p7v-2n8k-4m3t-6q9r.json")
    doc["test"]["conditions"] = {"ambient_temperature": quantity}
    return doc, "test.conditions.ambient_temperature"


def _parameter_set_claim(quantity: dict) -> tuple[dict, str]:
    doc = _load(EXAMPLES / "parameter-set" / "parameter-set-6bpa-4qet-046r-1zzk.json")
    claim = doc["parameter_set"]["parts"][0]["claims"][0]
    assert claim["parameter"] == "reference_temperature"
    claim["quantity"] = quantity
    return doc, "parameter_set.parts.0.claims.0.quantity"


def _cell_spec_condition(quantity: dict) -> tuple[dict, str]:
    doc = _load(CELL_SPEC)
    doc["properties"]["nominal_capacity"]["conditions"] = {"temperature": quantity}
    return doc, "properties.nominal_capacity.conditions.temperature"


HOLDERS: dict[str, Callable[[dict], tuple[dict, str]]] = {
    "material spec": _material_spec,
    "test condition": _test_condition,
    "parameter-set claim": _parameter_set_claim,
    "cell-spec conditions map": _cell_spec_condition,
}
UNITS = {
    "material spec": "g/cm3",
    "test condition": "degC",
    "parameter-set claim": "K",
    "cell-spec conditions map": "degC",
}


@pytest.mark.parametrize("holder", sorted(HOLDERS))
@pytest.mark.parametrize("text", ["2.5", "25 XX"])
def test_a_string_value_fails_strict_validation(holder: str, text: str) -> None:
    doc, path = HOLDERS[holder]({"value": text, "unit": UNITS[holder]})
    report = validate_record_report(doc, policy="strict")
    assert not report.ok
    [issue] = [i for i in report.errors if i.path == f"{path}.value"]
    assert issue.code == "schema.type"
    # The message says where text goes now.
    assert "value_text" in issue.message


@pytest.mark.parametrize("holder", sorted(HOLDERS))
def test_text_in_value_text_and_a_number_in_value_pass(holder: str) -> None:
    for quantity in ({"value": 2.5, "unit": UNITS[holder]}, {"value_text": "about 25", "unit": UNITS[holder]}):
        doc, _ = HOLDERS[holder](quantity)
        report = validate_record_report(doc, policy="strict")
        assert report.ok, [(i.path, i.message) for i in report.errors]


def test_the_base_schema_quantity_takes_a_number_only() -> None:
    validator = build_validator({"$ref": "https://w3id.org/battinfo/schema/battinfo.base.schema.json#/$defs/Quantity"})
    assert list(validator.iter_errors({"value": 2.5, "unit": "Ah"})) == []
    assert list(validator.iter_errors({"value_text": "about 2.5", "unit": "Ah"})) == []
    [error] = validator.iter_errors({"value": "2.5", "unit": "Ah"})
    assert error.validator == "type"


# ── Emitters: hasNumberValue carries finite real numbers only ─────────────────


def _numbers(node: Any) -> list[Any]:
    """Every hasNumberValue under *node*."""
    found: list[Any] = []
    if isinstance(node, dict):
        if "hasNumberValue" in node:
            found.append(node["hasNumberValue"])
        for child in node.values():
            found.extend(_numbers(child))
    elif isinstance(node, list):
        for child in node:
            found.extend(_numbers(child))
    return found


def test_the_descriptor_quantity_node_sends_text_to_has_string_value() -> None:
    from battinfo.transform.json_to_jsonld import _descriptor_quantity_node

    node = _descriptor_quantity_node("nominal_capacity", {"value": "2.5", "unit": "Ah"})
    assert node is not None
    assert _numbers(node) == []
    assert node["hasStringValue"] == "2.5"

    both = _descriptor_quantity_node("nominal_capacity", {"value": "about 2.5", "value_text": "2.4-2.6", "unit": "Ah"})
    assert both is not None and both["hasStringValue"] == ["2.4-2.6", "about 2.5"]

    number = _descriptor_quantity_node("nominal_capacity", {"value": 2.5, "unit": "Ah"})
    assert number is not None and _numbers(number) == [2.5] and "hasStringValue" not in number


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_the_descriptor_quantity_node_never_writes_a_non_finite_or_boolean_number(value: Any) -> None:
    from battinfo.transform.json_to_jsonld import _descriptor_quantity_node

    node = _descriptor_quantity_node("nominal_capacity", {"value": value, "typical_value": 2.4, "unit": "Ah"})
    # The typical value stands in; the bad value is not emitted.
    assert node is not None and _numbers(node) == [2.4]


def test_condition_nodes_send_text_to_has_string_value() -> None:
    from battinfo.transform.json_to_jsonld import _descriptor_quantity_node

    measured = {
        "value": 2.4,
        "unit": "Ah",
        "value_basis": "Measured",
        "conditions": {"temperature": {"value": "25 XX", "unit": "degC"}},
    }
    node = _descriptor_quantity_node("nominal_capacity", measured)
    assert node is not None
    [parameter] = [node["isOutputOf"]["hasMeasurementParameter"]]
    assert parameter["hasStringValue"] == "25 XX"
    assert _numbers(parameter) == []


def test_the_test_and_protocol_emitters_send_text_to_has_string_value() -> None:
    from battinfo.jsonld import _quantity, condition_quantity_node, typed_quantity_node

    condition = condition_quantity_node("temperature", "25 degC", "degC")
    assert condition is not None and condition["hasStringValue"] == "25 degC" and _numbers(condition) == []
    assert _numbers(condition_quantity_node("temperature", 25, "degC")) == [25]
    # Neither a number nor text: the caller falls back to schema:PropertyValue.
    assert condition_quantity_node("temperature", True, "degC") is None

    step = typed_quantity_node("Voltage", "4.2", "V")
    assert step["hasStringValue"] == "4.2" and _numbers(step) == []

    quantity = _quantity("3.7", "V")
    assert quantity["hasStringValue"] == "3.7" and _numbers(quantity) == []
    assert _numbers(_quantity(3.7, "V")) == [3.7]


def test_the_component_emitters_neither_coerce_nor_scale_text() -> None:
    from battinfo.transform.json_to_jsonld import (
        _converter_quantity_node,
        _emmo_quantity_node,
        _fraction_quantity_node,
    )

    fraction = _fraction_quantity_node("MassFraction", {"value": "95", "unit": "%"})
    assert fraction is not None and fraction["hasStringValue"] == "95" and _numbers(fraction) == []
    assert _numbers(_fraction_quantity_node("MassFraction", {"value": 95, "unit": "%"})) == [0.95]

    emmo = _emmo_quantity_node("Porosity", {"value": "0.3", "unit": "1"})
    assert emmo is not None and emmo["hasStringValue"] == "0.3" and _numbers(emmo) == []
    assert _emmo_quantity_node("Porosity", {"value": math.nan, "unit": "1"}) is None

    converter = _converter_quantity_node("density", {"value": "1.2", "unit": "g/cm3"})
    assert converter is not None and converter["hasStringValue"] == "1.2" and _numbers(converter) == []


def test_the_component_emitters_write_value_text() -> None:
    from battinfo.transform.json_to_jsonld import _emmo_quantity_node, _fraction_quantity_node

    for unit in ("1", "%"):
        node = _fraction_quantity_node("MassFraction", {"value_text": "about 92", "unit": unit})
        assert node is not None and node["hasStringValue"] == "about 92" and _numbers(node) == []
    beside = _fraction_quantity_node("MassFraction", {"value": 92, "value_text": "nominal", "unit": "%"})
    assert beside is not None and _numbers(beside) == [0.92] and beside["hasStringValue"] == "nominal"
    emmo = _emmo_quantity_node("Thickness", {"value_text": "thin", "unit": "um"})
    assert emmo is not None and emmo["hasStringValue"] == "thin" and _numbers(emmo) == []
    assert _fraction_quantity_node("MassFraction", {"unit": "1"}) is None


def test_a_component_fraction_given_as_text_reaches_the_json_ld() -> None:
    from battinfo.transform.json_to_jsonld import to_jsonld

    doc = _load(ROOT / "examples" / "cell-spec" / "research" / "coin-detailed.example.json")
    component = doc["positive_electrode"]["coating"]["component"]["active_material"][0]
    component["property"]["mass_fraction"] = {"value_text": "about 92", "unit": "1"}
    assert validate_record_report(doc, policy="strict").ok
    assert "about 92" in json.dumps(to_jsonld(doc))


def test_the_publication_property_node_sends_text_to_has_string_value() -> None:
    from battinfo.publication import _cell_spec_property_node

    node = _cell_spec_property_node("nominal_capacity", {"value": "2.5", "unit": "Ah"})
    assert node is not None and node["hasStringValue"] == "2.5" and _numbers(node) == []
    assert _numbers(_cell_spec_property_node("nominal_capacity", {"value": 2.5, "unit": "Ah"})) == [2.5]


# ── The converter importer ────────────────────────────────────────────────────


def test_the_converter_importer_reads_text_into_value_text() -> None:
    from battinfo.interop.converter import _mapped_properties, _quantity_text

    assert _quantity_text({"hasStringValue": "about 2", "hasMeasurementUnit": "emmo:Volt"}) == {
        "value_text": "about 2",
        "unit": "V",
    }
    assert _quantity_text({"hasNumericalPart": {"hasNumberValue": "2"}, "hasMeasurementUnit": "emmo:Volt"}) == {
        "value": 2.0,
        "unit": "V",
    }
    assert _quantity_text({"hasStringValue": "  "}) is None

    properties = _mapped_properties(
        [
            {"@type": "Density", "hasStringValue": "dense", "hasMeasurementUnit": "emmo:GramPerCubicCentiMetre"},
            {"@type": "Diameter", "hasNumericalPart": {"hasNumberValue": 15}, "hasMeasurementUnit": "emmo:MicroMetre"},
        ]
    )
    assert properties["density"]["value_text"] == "dense" and "value" not in properties["density"]
    assert properties["diameter"]["value"] == 15


# ── Reading older records: the shared migration ───────────────────────────────


@pytest.mark.parametrize(
    "text,number",
    [("2.5", 2.5), (" 3 ", 3), ("-1e-3", -0.001), ("+.5", 0.5), ("25.", 25.0)],
)
def test_number_from_text_reads_plain_decimal_numbers(text: str, number: float) -> None:
    result = number_from_text(text)
    assert result == number
    assert type(result) is type(number)


@pytest.mark.parametrize(
    "text",
    ["", " ", "2.5 V", "n/a", "2,5", "1_000", "0x10", "nan", "inf", "1e400", ">1000", "٣", "２.５"],
)
def test_number_from_text_leaves_text_alone(text: str) -> None:
    assert number_from_text(text) is None


def test_is_real_number() -> None:
    assert all(is_real_number(v) for v in (0, 2, 2.5, -1e-9, 10**400))
    assert not any(is_real_number(v) for v in (True, False, None, "2.5", math.nan, math.inf, -math.inf, [1], 1j))


def test_numpy_numbers_are_real_numbers_as_validation_counts_them() -> None:
    """JSON Schema's number type takes any real number, numpy scalars included,
    so the emitters write them as numbers too."""
    np = pytest.importorskip("numpy")
    from battinfo.transform.json_to_jsonld import _descriptor_quantity_node

    assert all(is_real_number(v) for v in (np.int64(5), np.float32(2.5), np.float64(2.5)))
    assert not any(is_real_number(v) for v in (np.bool_(True), np.float32("nan"), np.float64("inf")))
    node = _descriptor_quantity_node("nominal_capacity", {"value": np.float32(2.5), "unit": "Ah"})
    assert node is not None and _numbers(node) == [np.float32(2.5)]


def test_migrate_quantity_values_turns_numbers_into_numbers_and_moves_text() -> None:
    record = {
        "material_spec": {
            "property": {
                "true_density": {"value": "2.26", "unit": "g/cm3"},
                "specific_capacity": {
                    "value": "about 360",
                    "unit": "mAh/g",
                    "conditions": {"temperature": {"value": "25", "unit": "degC"}},
                },
            }
        },
        "distributions": [{"checksum": {"algorithm": "sha256", "value": "abc123"}}],
        "identifier": {"property_id": "doi", "value": "10.1000/1"},
    }
    notes = migrate_quantity_values(record)
    prop = record["material_spec"]["property"]
    assert prop["true_density"] == {"value": 2.26, "unit": "g/cm3"}
    # value_text takes the place value had.
    assert list(prop["specific_capacity"]) == ["value_text", "unit", "conditions"]
    assert prop["specific_capacity"]["value_text"] == "about 360"
    assert prop["specific_capacity"]["conditions"]["temperature"]["value"] == 25
    # Strings that are not quantities are left as they are.
    assert record["distributions"][0]["checksum"]["value"] == "abc123"
    assert record["identifier"]["value"] == "10.1000/1"
    # One note per text value moved; a numeric string needs none.
    assert notes == ["material_spec.property.specific_capacity.value: moved the text 'about 360' to value_text"]


def test_migrate_quantity_values_joins_value_text_and_drops_blank_text() -> None:
    held = {"value": "3.6-3.7", "value_text": "at 25 C", "unit": "V"}
    blank = {"value": "  ", "value_text": "about 3", "unit": "V"}
    same = {"value": "about 3", "value_text": "about 3", "unit": "V"}
    notes = migrate_quantity_values({"a": held, "b": blank, "c": same})
    # Neither text is lost: the one from value comes first.
    assert held == {"value_text": "3.6-3.7; at 25 C", "unit": "V"}
    assert blank == {"value_text": "about 3", "unit": "V"}
    assert same == {"value_text": "about 3", "unit": "V"}
    assert notes == [
        "a.value: joined the text '3.6-3.7' to value_text, which now reads '3.6-3.7; at 25 C'",
        "b.value: dropped the blank text '  '",
        "c.value: moved the text 'about 3' to value_text",
    ]


def test_migrate_quantity_values_walks_lists() -> None:
    claims = [{"parameter": "p", "quantity": {"value": "1.5", "unit": "V"}}]
    assert migrate_quantity_values(claims, "claims") == []
    assert claims[0]["quantity"]["value"] == 1.5


# ── ws.import_ ────────────────────────────────────────────────────────────────

RECORD_URL = "https://zenodo.org/records/1"


def _deposit_graph(root: Path) -> dict:
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.license("cc-by-4.0")
    spec = battinfo.CellSpec(
        manufacturer="Example Lab",
        model="R2032",
        format="coin",
        chemistry="li-ion",
        properties={
            "nominal_capacity": {"value": 0.005, "unit": "Ah"},
            "nominal_voltage": {"value": 3.7, "unit": "V"},
        },
    )
    ws.add("cell", spec=spec, serial_numbers=["C01"])
    ws.save()
    return ws._build_zenodo_jsonld(
        zenodo_record_id=1,
        prereserved_doi="10.5281/zenodo.1",
        record_url=RECORD_URL,
        data_filenames=[],
        title="Text values",
        creators=[{"name": "Doe, Jane"}],
    )


def _property_nodes(graph: dict) -> dict[str, dict]:
    """The deposit's cell-spec property nodes, by the label the emitter gives them."""
    [spec] = [n for n in graph["@graph"] if "BatteryCellSpecification" in (n.get("@type") or [])]
    nodes = spec["isDescriptionFor"]["hasProperty"]
    return {node["skos:prefLabel"]: node for node in nodes}


def test_import_reads_a_deposit_with_text_in_has_number_value(tmp_path: Path) -> None:
    graph = _deposit_graph(tmp_path / "source")
    nodes = _property_nodes(graph)
    # A deposit written before 0.8.0 could carry text in hasNumberValue.
    nodes["NominalCapacity"]["hasNumericalPart"]["hasNumberValue"] = "0.005"
    nodes["NominalVoltage"]["hasNumericalPart"]["hasNumberValue"] = "about 3.7"
    path = tmp_path / "battinfo.json"
    path.write_text(json.dumps(graph), encoding="utf-8")

    ws = AuthoringWorkspace(root=tmp_path / "imported", registry_url=None)
    with pytest.warns(UserWarning, match="moved the text 'about 3.7' to value_text"):
        ws.import_(str(path))
    result = ws.save()  # strict by default
    assert result["index"]["failures"] == []

    [saved] = [_load(p) for p in (tmp_path / "imported" / ".battinfo" / "records" / "cell-spec").glob("*.json")]
    properties = saved["properties"]
    assert properties["nominal_capacity"]["value"] == 0.005
    assert isinstance(properties["nominal_capacity"]["value"], float)
    assert properties["nominal_voltage"] == {"value_text": "about 3.7", "unit": "V"}


# ── ws.load ───────────────────────────────────────────────────────────────────


def test_load_reads_text_out_of_a_cell_spec_draft(tmp_path: Path) -> None:
    draft = {
        "manufacturer": "Example Lab",
        "model": "R2032",
        "format": "coin",
        "chemistry": "li-ion",
        "properties": {
            "nominal_capacity": {
                "value": "0.005",
                "unit": "Ah",
                "value_basis": "Measured",
                "conditions": {"temperature": {"value": "25", "unit": "degC"}},
            },
            "nominal_voltage": {"value": "about 3.7", "unit": "V"},
        },
    }
    path = tmp_path / "lab.cell-spec.json"
    path.write_text(json.dumps(draft), encoding="utf-8")
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with pytest.warns(UserWarning, match="lab.cell-spec.json held text"):
        spec = ws.load(path)
    assert spec.properties["nominal_capacity"]["value"] == 0.005
    assert spec.properties["nominal_capacity"]["conditions"]["temperature"]["value"] == 25
    assert spec.properties["nominal_voltage"] == {"value_text": "about 3.7", "unit": "V"}
    ws.add("cell", spec=spec, serial_numbers=["C01"])
    assert ws.save()["index"]["failures"] == []


def test_load_reads_text_out_of_the_component_quantities_of_a_cell_spec_draft(tmp_path: Path) -> None:
    detailed = _load(ROOT / "examples" / "cell-spec" / "research" / "coin-detailed.example.json")
    positive = detailed["positive_electrode"]
    positive["coating"]["component"]["active_material"][0]["property"]["mass_fraction"] = {"value": "0.92", "unit": "1"}
    positive["coating"]["property"]["thickness"] = {"value": "about 55", "unit": "um"}
    draft = {
        "manufacturer": "Example Lab",
        "model": "COIN-1",
        "format": "coin",
        "chemistry": "li-ion",
        "properties": {"nominal_voltage": {"value": "3.2", "unit": "V"}},
        "positive_electrode": positive,
    }
    path = tmp_path / "lab.cell-spec.json"
    path.write_text(json.dumps(draft), encoding="utf-8")
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with pytest.warns(
        UserWarning, match=r"positive_electrode\.coating\.property\.thickness\.value: moved the text 'about 55'"
    ):
        spec = ws.load(path)
    assert spec.positive_electrode is not None
    coating = spec.positive_electrode.model_dump(exclude_none=True)["coating"]
    assert coating["component"]["active_material"][0]["property"]["mass_fraction"] == {"value": 0.92, "unit": "1"}
    assert coating["property"]["thickness"] == {"value_text": "about 55", "unit": "um"}
    assert spec.properties["nominal_voltage"] == {"value": 3.2, "unit": "V"}
    ws.add("cell", spec=spec, serial_numbers=["C01"])
    assert ws.save()["index"]["failures"] == []  # strict by default


def test_load_reads_text_out_of_an_equipment_spec_draft(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    path = ws.template("equipment-spec", name="Cycler", manufacturer="Example", model="C1", channel_count=2)
    draft = _load(path)
    draft["property"]["channel_voltage_max"] = {"value": "4.35", "unit": "V"}
    draft["property"]["charge_current"] = {"value": "adjustable", "unit": "A"}
    path.write_text(json.dumps(draft), encoding="utf-8")
    with pytest.warns(UserWarning, match="moved the text 'adjustable' to value_text"):
        record = ws.load(path)
    prop = record["equipment_spec"]["property"]
    assert prop["channel_voltage_max"] == {"value": 4.35, "unit": "V"}
    assert prop["charge_current"] == {"value_text": "adjustable", "unit": "A"}
    report = validate_record_report(record, policy="strict")
    assert report.ok, [i.message for i in report.errors]


def _equipment_spec_saved_with_text(tmp_path: Path) -> tuple[AuthoringWorkspace, Path, dict]:
    """A workspace whose saved equipment spec holds text in two quantity values, as 0.7 could write it."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    draft = ws.template("equipment-spec", name="Cycler", manufacturer="Example", model="C1", channel_count=2)
    ws.add("equipment", spec=ws.load(draft), serial_number="A1")
    [path] = (tmp_path / ".battinfo" / "records" / "equipment-spec").glob("*.json")
    older = _load(path)
    older["equipment_spec"]["property"] = {
        "channel_voltage_max": {"value": "4.35", "unit": "V"},
        "charge_current": {"value": "adjustable", "unit": "A"},
    }
    path.write_text(json.dumps(older, indent=2), encoding="utf-8")
    return ws, path, older


@pytest.mark.parametrize("given", ["iri", "saved file", "other file", "dict"])
def test_adding_equipment_reads_text_out_of_the_spec_it_is_given(tmp_path: Path, given: str) -> None:
    ws, saved_path, older = _equipment_spec_saved_with_text(tmp_path)
    passed = copy.deepcopy(older)
    if given == "iri":
        spec: Any = older["equipment_spec"]["id"]
    elif given == "saved file":
        spec = saved_path
    elif given == "other file":
        spec = saved_path.replace(tmp_path / "cycler.equipment-spec.json")
    else:
        saved_path.unlink()
        spec = passed

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ws.add("equipment", spec=spec, serial_number="B")
    moved = [str(w.message) for w in caught if "held text" in str(w.message)]
    # Said once, whether the spec was read from the saved copy, another file or a dict.
    assert len(moved) == 1, moved
    assert "equipment_spec.property.charge_current.value: moved the text 'adjustable' to value_text" in moved[0]
    assert "channel_voltage_max" not in moved[0]  # a numeric string becomes the number without a note

    rewritten = _load(saved_path)
    prop = rewritten["equipment_spec"]["property"]
    assert prop["channel_voltage_max"] == {"value": 4.35, "unit": "V"}
    assert prop["charge_current"] == {"value_text": "adjustable", "unit": "A"}
    report = validate_record_report(rewritten, policy="strict")
    assert report.ok, [i.message for i in report.errors]
    assert ws.save()["index"]["failures"] == []  # strict by default
    if given == "dict":
        assert passed == older  # the caller's dict is left as it was


def test_load_of_a_search_hit_reads_text_out_of_the_referenced_spec(tmp_path: Path) -> None:
    record = _load(CELL_SPEC)
    record["properties"]["nominal_capacity"]["value"] = "2.5"
    record["properties"]["nominal_voltage"]["value"] = "about 3.3"
    published = copy.deepcopy(record)
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    hit = {"type": "cell-spec", "id": record["cell_spec"]["id"], "_record": record}
    with pytest.warns(UserWarning, match="moved the text 'about 3.3' to value_text"):
        spec = ws.load(hit)
    assert spec.id == record["cell_spec"]["id"]
    assert spec.properties["nominal_capacity"]["value"] == 2.5
    assert spec.properties["nominal_voltage"]["value_text"] == "about 3.3"
    assert "value" not in spec.properties["nominal_voltage"]
    # The hit itself is left as it was found.
    assert record == published


# ── save_record upsert ────────────────────────────────────────────────────────


def _saved_path(root: Path) -> Path:
    [path] = (root / "cell-spec").glob("*.json")
    return path


def test_an_upsert_over_a_record_saved_with_text_in_value_is_unchanged_and_rewritten(tmp_path: Path) -> None:
    doc = _load(CELL_SPEC)
    save_record(doc, source_root=tmp_path, mode=REGISTER_MODE_UPSERT, publish=False)
    path = _saved_path(tmp_path)

    # The copy on disk, as an older version could have written it.
    older = _load(path)
    older["properties"]["nominal_capacity"]["value"] = "2.5"
    older["properties"]["cycle_life"] = {
        "value": ">1000",
        **{k: v for k, v in older["properties"]["cycle_life"].items() if k != "value_text"},
    }
    path.write_text(json.dumps(older, indent=2), encoding="utf-8")
    assert _compare_with_saved(path, doc) == (False, True)

    with pytest.warns(
        UserWarning, match=r"properties\.cycle_life\.value: moved the text '>1000' to value_text"
    ) as caught:
        again = save_record(_load(CELL_SPEC), source_root=tmp_path, mode=REGISTER_MODE_UPSERT, publish=False)
    # The numeric string is read as the number without a note.
    assert "nominal_capacity" not in str(caught[0].message)
    assert again["status"] == "updated"
    assert again["content_changed"] is False
    rewritten = _load(path)
    assert rewritten["properties"]["nominal_capacity"]["value"] == 2.5
    assert rewritten["properties"]["cycle_life"]["value_text"] == ">1000"
    assert "value" not in rewritten["properties"]["cycle_life"]
    assert validate_record_report(rewritten, policy="strict").ok

    # Once the copy is up to date, an identical upsert writes nothing.
    assert _compare_with_saved(path, doc) == (False, False)
    stamp = path.stat().st_mtime_ns
    with warnings.catch_warnings(record=True) as quiet:
        warnings.simplefilter("always")
        save_record(_load(CELL_SPEC), source_root=tmp_path, mode=REGISTER_MODE_UPSERT, publish=False)
    assert path.stat().st_mtime_ns == stamp
    assert not [w for w in quiet if "held text" in str(w.message)]
