"""Regression tests for three model/schema gaps found authoring the Flores
half-cell OCV dataset (battinfo-records#6 READINESS-REPORT.md):

* M2 - assigning a bare string to a ``str | list[str]``-shaped field exploded it
  into a list of single characters and still passed strict validation.
* Test.conditions - the JSON schema defines ``test.conditions`` but the Test
  model had no such field, so conditions could not be authored via the model.
* M1 - the model accepted enum values the save-time JSON Schema rejects
  (``Step(mode="discharge")``, ``Conformance(status="non_conformant")``, ...),
  so the failure surfaced late at ``ws.save()`` instead of at construction.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.bundle import (  # noqa: E402
    ARTIFACT_ROLES,
    CONFORMANCE_STATUSES,
    DEVIATION_CATEGORIES,
    TEST_STATUSES,
    Artifact,
    BatteryTestType,
    Cell,
    CellSpec,
    Conformance,
    Dataset,
    Deviation,
    Test,
    TestSpec,
)
from battinfo.jsonld import record_to_jsonld  # noqa: E402
from battinfo.testmethod import (  # noqa: E402
    STEP_DIRECTIONS,
    STEP_MODES,
    TERMINATION_DIRECTIONS,
    TERMINATION_QUANTITIES,
    Step,
    Termination,
)

SCHEMA_DIR = ROOT / "src" / "battinfo" / "data" / "schemas"


# ── M2: str | list[str] must never explode into characters ────────────────────

def _record_models() -> dict[type, object]:
    """A minimal, constructible instance of every model that owns list[str] fields."""
    return {
        CellSpec: CellSpec(id="https://w3id.org/battinfo/spec/a", name="a"),
        Cell: Cell(id="https://w3id.org/battinfo/cell/a", name="a"),
        TestSpec: TestSpec(id="https://w3id.org/battinfo/spec/b", name="b"),
        Test: Test(
            id="https://w3id.org/battinfo/test/a",
            name="a",
            cell_id="https://w3id.org/battinfo/cell/a",
            kind="gitt",
        ),
        Dataset: Dataset(id="https://w3id.org/battinfo/dataset/a", name="a"),
        Artifact: Artifact(role="other", format="pybamm", locator="x"),
    }


def _str_list_fields(model: type) -> list[str]:
    return [
        name
        for name, field in model.model_fields.items()
        if field.annotation == list[str]
    ]


def test_every_str_list_field_wraps_a_bare_string_on_assignment() -> None:
    """Sweep every list[str]-shaped field on every record model: assigning a bare
    string must wrap it as [value], never iterate it into single characters."""
    swept: list[str] = []
    for model, obj in _record_models().items():
        fields = _str_list_fields(model)
        assert fields, f"{model.__name__} exposes no list[str] fields to sweep"
        for name in fields:
            setattr(obj, name, "R2032 coin cell")
            got = getattr(obj, name)
            assert got == ["R2032 coin cell"], (
                f"{model.__name__}.{name} exploded a bare string into {got!r}"
            )
            swept.append(f"{model.__name__}.{name}")
    # Guard against a field silently dropping out of the sweep (17 today across
    # CellSpec, Cell, TestSpec, Test, Dataset, Artifact).
    assert len(swept) >= 17, swept


def test_str_list_field_wraps_a_bare_string_at_construction() -> None:
    spec = CellSpec(id="https://w3id.org/battinfo/spec/a", name="a",
                    specification_comment="single note")
    assert spec.specification_comment == ["single note"]
    ds = Dataset(id="https://w3id.org/battinfo/dataset/a", name="a",
                 access_url="https://example.org", same_as="https://doi.org/10.5281/zenodo.1")
    assert ds.same_as == ["https://doi.org/10.5281/zenodo.1"]


def test_specification_comment_does_not_explode_in_record() -> None:
    spec = CellSpec(id="https://w3id.org/battinfo/spec/a", name="a")
    spec.specification_comment = "R2032 coin cell"
    record = spec.to_record()
    assert record["specification_comment"] == ["R2032 coin cell"]


def test_dataset_same_as_does_not_explode_in_record() -> None:
    ds = Dataset(id="https://w3id.org/battinfo/dataset/a", name="a",
                 access_url="https://example.org")
    ds.same_as = "https://doi.org/10.5281/zenodo.1"
    record = ds.to_record()
    assert record["dataset"]["same_as"] == ["https://doi.org/10.5281/zenodo.1"]


# ── Test.conditions: authorable end to end ────────────────────────────────────

def test_test_conditions_round_trip_and_jsonld() -> None:
    test = Test(
        id="https://w3id.org/battinfo/test/a",
        name="a",
        cell_id="https://w3id.org/battinfo/cell/a",
        kind="gitt",
        conditions={
            "temperature": "room temperature",
            "voltage_window": {"value": 4.2, "unit": "V"},
        },
    )
    assert test.conditions["temperature"] == "room temperature"

    record = test.to_record()
    assert record["test"]["conditions"]["temperature"] == "room temperature"
    assert record["test"]["conditions"]["voltage_window"] == {"value": 4.2, "unit": "V"}

    reloaded = Test.from_record(record)
    assert reloaded.conditions == test.conditions

    ld = record_to_jsonld(record, "test", context="inline")
    props = {p["schema:name"]: p for p in ld["schema:additionalProperty"]}
    assert props["temperature"]["schema:value"] == "room temperature"
    assert props["voltage_window"]["schema:value"] == 4.2
    assert props["voltage_window"]["schema:unitText"] == "V"


def test_test_conditions_default_empty_and_omitted() -> None:
    test = Test(id="https://w3id.org/battinfo/test/a", name="a",
                cell_id="https://w3id.org/battinfo/cell/a", kind="gitt")
    assert test.conditions == {}
    assert "conditions" not in test.to_record()["test"]


# ── M1: model enums fail at construction, matching the save-time schema ────────

def test_step_mode_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match=r"Step\.mode must be one of"):
        Step(mode="discharge")
    with pytest.raises(ValueError, match=r"Step\.mode must be one of"):
        Step(mode="charge")
    # The canonical spelling constructs fine.
    assert Step(mode="cc", direction="discharge").direction == "discharge"


def test_step_direction_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match=r"Step\.direction must be one of"):
        Step(mode="cc", direction="up")


def test_termination_enums_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match=r"Termination\.quantity must be one of"):
        Termination(quantity="temperature", value=25, unit="degC")
    with pytest.raises(ValueError, match=r"Termination\.direction must be one of"):
        Termination(quantity="voltage", value=4.2, unit="V", direction="up")


def test_conformance_status_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match=r"Conformance\.status must be one of"):
        Conformance(status="non_conformant")
    assert Conformance(status="non-conformant").status == "non-conformant"


def test_deviation_category_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match=r"Deviation\.category must be one of"):
        Deviation(category="explosion")
    assert Deviation(category="power_outage").category == "power_outage"


def test_test_status_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match=r"Test\.status must be one of"):
        Test(id="https://w3id.org/battinfo/test/a", name="a",
             cell_id="https://w3id.org/battinfo/cell/a", kind="gitt", status="finished")
    assert Test(id="https://w3id.org/battinfo/test/a", name="a",
                cell_id="https://w3id.org/battinfo/cell/a", kind="gitt",
                status="completed").status == "completed"


def test_artifact_role_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match=r"Artifact\.role must be one of"):
        Artifact(role="cycler_program", format="pybamm", locator="x")
    assert Artifact(role="executed_protocol", format="pybamm", locator="x").role == "executed_protocol"


# ── The model enums must equal the save-time schema enums (no future drift) ────

def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_step_and_termination_enums_match_schema() -> None:
    defs = _schema("test-protocol.schema.json")["$defs"]
    step = defs["Step"]["properties"]
    term = defs["Termination"]["properties"]
    assert set(STEP_MODES) == set(step["mode"]["enum"])
    assert set(STEP_DIRECTIONS) == set(step["direction"]["enum"])
    assert set(TERMINATION_QUANTITIES) == set(term["quantity"]["enum"])
    assert set(TERMINATION_DIRECTIONS) == set(term["direction"]["enum"])
    assert set(ARTIFACT_ROLES) == set(defs["Artifact"]["properties"]["role"]["enum"])


def test_test_enums_match_schema() -> None:
    test = _schema("test.schema.json")["properties"]["test"]["properties"]
    assert set(TEST_STATUSES) == set(test["status"]["enum"])
    conformance = test["conformance"]["properties"]
    assert set(CONFORMANCE_STATUSES) == set(conformance["status"]["enum"])
    category = conformance["deviations"]["items"]["properties"]["category"]["enum"]
    assert set(DEVIATION_CATEGORIES) == set(category)
    assert {k.value for k in BatteryTestType} == set(test["kind"]["enum"])
