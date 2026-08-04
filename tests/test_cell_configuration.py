"""Explicit cell_configuration: authoring, save gate, and JSON-LD typing.

The emitter has typed half-cells from the ``reference_electrode`` marker since the
domain-battery 0.20.1 import. That heuristic is a guess; ``cell_configuration`` is
the statement. These tests pin both, and the precedence between them.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import battinfo
from battinfo.bundle import CellConfiguration, CellSpec
from battinfo.jsonld import record_to_jsonld
from battinfo.transform.cell_spec_node import physical_type_stack

_BASE = {"cell_format": "coin", "chemistry": "li-ion", "positive_electrode_basis": "lfp"}


@pytest.mark.parametrize(
    ("configuration", "expected"),
    [
        ("half_cell", ("BatteryHalfCell", "HalfCellDevice")),
        ("three_electrode_cell", ("ThreeElectrodeCellDevice",)),
        ("full_cell", ()),
    ],
)
def test_each_configuration_value_types_the_cell(configuration: str, expected: tuple[str, ...]) -> None:
    types = physical_type_stack({**_BASE, "cell_configuration": configuration})
    for cls in expected:
        assert cls in types, f"{configuration}: expected {cls} in {types}"
    # A device class is never invented for a configuration that does not name one.
    if not expected:
        assert not {"BatteryHalfCell", "HalfCellDevice", "ThreeElectrodeCellDevice"} & set(types)
    # Never the electrode-plus-electrolyte class, whatever the configuration.
    assert "ElectrochemicalHalfCell" not in types


def test_reference_electrode_heuristic_still_applies_when_unstated() -> None:
    types = physical_type_stack({**_BASE, "reference_electrode": "lithium"})
    assert "BatteryHalfCell" in types and "HalfCellDevice" in types, types


def test_explicit_full_cell_beats_the_reference_electrode_heuristic() -> None:
    """A three-electrode full cell records a reference electrode and is still a
    full cell — the stated configuration wins over the marker."""
    types = physical_type_stack(
        {**_BASE, "reference_electrode": "lithium", "cell_configuration": "full_cell"}
    )
    assert "BatteryHalfCell" not in types and "HalfCellDevice" not in types, types


def test_explicit_three_electrode_beats_the_heuristic() -> None:
    types = physical_type_stack(
        {**_BASE, "reference_electrode": "lithium", "cell_configuration": "three_electrode_cell"}
    )
    assert "ThreeElectrodeCellDevice" in types, types
    assert "BatteryHalfCell" not in types


def test_descriptor_path_agrees_with_the_canonical_path() -> None:
    from battinfo.transform.json_to_jsonld import _descriptor_specification_to_jsonld

    node = _descriptor_specification_to_jsonld(
        {"format": "coin", "chemistry": "li-ion", "cell_configuration": "three_electrode_cell"}
    )
    assert "ThreeElectrodeCellDevice" in node["isDescriptionFor"]["@type"]


# ── authoring + persistence ────────────────────────────────────────────────────

def test_authoring_round_trips_through_save_and_emission(tmp_path: Path) -> None:
    ws = battinfo.workspace(str(tmp_path))
    draft = ws.template(
        "cell-spec", manufacturer="Lab", model="HC-1", format="coin", chemistry="li-ion",
        cell_configuration="half_cell", reference_electrode="lithium",
    )
    ws.load(draft)
    ws.save()   # strict validation: the save gate must accept the enum value

    written = next((tmp_path / ".battinfo" / "records" / "cell-spec").glob("*.json"))
    record = json.loads(written.read_text(encoding="utf-8"))
    assert record["cell_spec"]["cell_configuration"] == "half_cell"
    assert record["cell_spec"]["reference_electrode"] == "lithium"

    back = CellSpec.from_record(record)
    assert back.cell_configuration is CellConfiguration.HALF_CELL
    assert back.reference_electrode == "lithium"

    types = record_to_jsonld(record, "cell-spec")["isDescriptionFor"]["@type"]
    assert "BatteryHalfCell" in types and "HalfCellDevice" in types


def test_save_gate_rejects_a_value_outside_the_enum(tmp_path: Path) -> None:
    from battinfo.validate.record import validate_record

    ws = battinfo.workspace(str(tmp_path))
    ws.load(ws.template("cell-spec", manufacturer="Lab", model="X", format="coin", chemistry="li-ion"))
    ws.save()
    written = next((tmp_path / ".battinfo" / "records" / "cell-spec").glob("*.json"))
    record = json.loads(written.read_text(encoding="utf-8"))

    record["cell_spec"]["cell_configuration"] = "quarter_cell"
    report = validate_record(record, policy="strict")
    assert not report.ok
    assert any("cell_configuration" in issue.path for issue in report.issues)


def test_configuration_is_optional_and_absent_by_default(tmp_path: Path) -> None:
    ws = battinfo.workspace(str(tmp_path))
    ws.load(ws.template("cell-spec", manufacturer="Lab", model="X", format="coin", chemistry="li-ion"))
    ws.save()
    written = next((tmp_path / ".battinfo" / "records" / "cell-spec").glob("*.json"))
    record = json.loads(written.read_text(encoding="utf-8"))
    assert "cell_configuration" not in record["cell_spec"]


def test_model_and_json_schema_agree_on_the_enum() -> None:
    from importlib import resources

    schema_file = resources.files("battinfo").joinpath("data", "schemas", "cell-spec.schema.json")
    with schema_file.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    values = schema["properties"]["cell_spec"]["properties"]["cell_configuration"]["enum"]
    assert set(values) == {c.value for c in CellConfiguration}
    from battinfo.bundle_generated import CellConfiguration as GeneratedCellConfiguration

    assert {c.value for c in GeneratedCellConfiguration} == set(values)
