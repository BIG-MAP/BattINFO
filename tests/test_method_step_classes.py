"""Test-protocol steps and cut-offs type with classes the contexts define.

A step's class comes from ``data/vocab/test-method/step-modes.json``, looked up
by its mode and direction. Four classes that vocabulary named exist in neither
the v1 records context nor the pinned EMMO context (ConstantResistanceCharging,
ConstantResistanceDischarging, ConstantCurrentConstantVoltageDischarging and the
resistance setpoint's ElectricalResistance), and a step whose direction the
vocabulary did not list fell back to ElectrochemicalProcess, which no context
defines either. Every one of them expanded to a relative IRI. Current cut-offs
were the generic TerminationQuantity, although EMMO has LowerCurrentLimit and
UpperCurrentLimit.

The packaged examples hold no constant-resistance, CC-CV or direction-less step
and no current cut-off, so the corpus sweep in test_jsonld_type_guards.py never
saw these. The tests below start from the steps themselves and compare the
expanded class IRIs.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from pyld import jsonld as _jsonld

from battinfo.jsonld import method_step_node, record_to_jsonld
from battinfo.testmethod import parse_experiment
from battinfo.validate import validate_semantic_report
from battinfo.validate.jsonld import _inline_local_contexts
from battinfo.ws import AuthoringWorkspace

EMMO = "https://w3id.org/emmo#"
ECHEM = "https://w3id.org/emmo/domain/electrochemistry#electrochemistry_"
CHAMEO = "https://w3id.org/emmo/domain/characterisation-methodology/chameo#"
SKOS_PREF_LABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"

HAS_TASK = EMMO + "EMMO_70da982d_1810_4b01_9630_a28e216ecd9a"
HAS_CONTROL_PARAMETER = ECHEM + "e55f2798_55c8_4fc5_9abb_2f8ac101f3b8"
HAS_TERMINATION_PARAMETER = ECHEM + "e6a7d617_a581_4782_8374_37d3305e0258"
HAS_MEASUREMENT_UNIT = EMMO + "EMMO_bed1d005_b04e_4a90_94cf_02bc678a8569"

CONSTANT_CURRENT_CHARGING = ECHEM + "83f2b1e9_cb67_4dbf_977f_ba54bbae374f"
CONSTANT_CURRENT_DISCHARGING = ECHEM + "53fe3f58_0802_41cf_af69_4784fc42cc30"
CURRENT_CONTROLLED_PROCESS = ECHEM + "5548f188_df00_4c05_ae98_7846e92efe36"
CONSTANT_POWER_CHARGING = ECHEM + "dcd4a15d_52cf_44fb_b826_df18e4baa89c"
CONSTANT_POWER_DISCHARGING = ECHEM + "a2f65954_1ed8_4faf_9efe_597018d03e8d"
POWER_CONTROLLED_PROCESS = ECHEM + "dc1af38d_438e_40c2_8a68_0d631a8f46f2"
VOLTAGE_HOLD = ECHEM + "f07be701_9d6a_415b_ac6d_63202297a7a1"
CONSTANT_VOLTAGE_CHARGING = ECHEM + "acdeaa89_0e99_4941_8821_d5dea3d34912"
CONSTANT_VOLTAGE_DISCHARGING = ECHEM + "9865e4f9_756d_4d94_a6fd_4102ab795f9e"
CCCV_CHARGING = ECHEM + "0cc8f231_0ce5_467e_9c76_29b2c80349ad"
DISCHARGING = ECHEM + "06d8e1ee_924a_4915_998d_33a69f41dadc"
LINEAR_SCAN_VOLTAMMETRY = CHAMEO + "LinearScanVoltammetry"
OPEN_CIRCUIT_HOLD = CHAMEO + "OpenCircuitHold"

ELECTRIC_RESISTANCE = EMMO + "EMMO_e88f75d6_9a17_4cfc_bdf7_43d7cea5a9a1"
LOWER_CURRENT_LIMIT = ECHEM + "7db845e7_0e5b_47d4_b954_2a2b8e85deea"
UPPER_CURRENT_LIMIT = ECHEM + "3dac5115_6337_40a6_a2ab_317087fe3b45"
LOWER_VOLTAGE_LIMIT = ECHEM + "534dd59c_904c_45d9_8550_ae9d2eb6bbc9"
TERMINATION_QUANTITY = ECHEM + "44a67eb4_52e8_433c_aef7_a928c2b9906c"

SPEC_ID = "https://w3id.org/battinfo/spec/0000-0000-0000-0001"

# (mode, direction, the class the step expands to). None as the direction
# leaves the key out.
TYPED_STEPS = [
    ("cc", "charge", CONSTANT_CURRENT_CHARGING),
    ("cc", "discharge", CONSTANT_CURRENT_DISCHARGING),
    ("cc", "none", CURRENT_CONTROLLED_PROCESS),
    ("cc", None, CURRENT_CONTROLLED_PROCESS),
    ("cc", "hold", CURRENT_CONTROLLED_PROCESS),
    ("cp", "charge", CONSTANT_POWER_CHARGING),
    ("cp", "discharge", CONSTANT_POWER_DISCHARGING),
    ("cp", "none", POWER_CONTROLLED_PROCESS),
    ("cp", None, POWER_CONTROLLED_PROCESS),
    ("cv", "charge", CONSTANT_VOLTAGE_CHARGING),
    ("cv", "discharge", CONSTANT_VOLTAGE_DISCHARGING),
    ("cv", "hold", VOLTAGE_HOLD),
    ("cv", "none", VOLTAGE_HOLD),
    ("cv", None, VOLTAGE_HOLD),
    ("cccv", "charge", CCCV_CHARGING),
    # EMMO has no constant-resistance or CC-CV discharging class: the step
    # types as the published parent.
    ("cccv", "discharge", DISCHARGING),
    ("cr", "discharge", DISCHARGING),
    ("scan", "charge", LINEAR_SCAN_VOLTAMMETRY),
    ("scan", "none", LINEAR_SCAN_VOLTAMMETRY),
    ("scan", None, LINEAR_SCAN_VOLTAMMETRY),
    ("rest", "rest", OPEN_CIRCUIT_HOLD),
    ("rest", None, OPEN_CIRCUIT_HOLD),
]

# Steps no published class fits: no class, a label and a warning.
UNTYPED_STEPS = [
    ("cr", "charge", "cr charge"),
    ("cr", "none", "cr"),
    ("cr", None, "cr"),
    ("cr", "hold", "cr hold"),
    ("cccv", "none", "cccv"),
    ("cccv", None, "cccv"),
]


def _step(mode: str, direction: str | None, **extra: Any) -> dict:
    step: dict[str, Any] = {"mode": mode, **extra}
    if direction is not None:
        step["direction"] = direction
    return step


def _protocol(*steps: dict) -> dict:
    return {"test_spec": {"id": SPEC_ID, "name": "probe", "kind": "cycling"}, "method": list(steps)}


def _quiet(fn, *args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fn(*args, **kwargs)


def _plan(doc: dict) -> dict:
    """The protocol node of an emitted document, expanded offline."""
    expanded = _jsonld.expand(_inline_local_contexts(doc))
    (plan,) = [node for node in expanded if node.get("@id") == SPEC_ID]
    return plan


def _standalone_steps(record: dict) -> list[dict]:
    return _plan(_quiet(record_to_jsonld, record, "test-protocol"))[HAS_TASK]


def _deposit_steps(record: dict) -> list[dict]:
    """The steps as ``ws.preview_jsonld()`` and the Zenodo deposit emit them."""
    doc = _quiet(
        AuthoringWorkspace._assemble_zenodo_jsonld,
        {"cell-spec": [], "cell-instance": [], "test": [], "test-protocol": [record], "dataset": []},
        zenodo_record_id=0,
        prereserved_doi="",
        record_url="https://example.org/records/0",
        data_filenames=[],
        title="t",
        description="d",
    )
    return _plan(doc)[HAS_TASK]


EMITTERS = [_standalone_steps, _deposit_steps]


@pytest.mark.parametrize("emit", EMITTERS, ids=["record_to_jsonld", "deposit"])
@pytest.mark.parametrize(("mode", "direction", "iri"), TYPED_STEPS)
def test_a_step_types_as_its_published_class(emit, mode: str, direction: str | None, iri: str) -> None:
    (step,) = emit(_protocol(_step(mode, direction)))
    assert step["@type"] == [iri]


@pytest.mark.parametrize("emit", EMITTERS, ids=["record_to_jsonld", "deposit"])
@pytest.mark.parametrize(("mode", "direction", "label"), UNTYPED_STEPS)
def test_a_step_no_class_fits_keeps_its_mode_as_a_label(emit, mode: str, direction: str | None, label: str) -> None:
    (step,) = emit(_protocol(_step(mode, direction, description="Load step")))
    assert "@type" not in step
    assert step[SKOS_PREF_LABEL] == [{"@value": label}]


@pytest.mark.parametrize(("mode", "direction", "label"), UNTYPED_STEPS)
def test_the_emitter_warns_when_a_step_gets_no_class(mode: str, direction: str | None, label: str) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        node = method_step_node(_step(mode, direction))
    messages = [str(w.message) for w in caught if issubclass(w.category, UserWarning)]
    assert len(messages) == 1
    assert messages[0].startswith("semantic.method_step_unmapped:")
    assert f"'{label}'" in messages[0]
    assert "@type" not in node


@pytest.mark.parametrize(("mode", "direction", "iri"), TYPED_STEPS)
def test_a_typed_step_does_not_warn(mode: str, direction: str | None, iri: str) -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        method_step_node(_step(mode, direction))
    assert not [w for w in caught if "method_step_unmapped" in str(w.message)]


def test_a_constant_resistance_step_from_a_step_string() -> None:
    """The reproduction from the review: a resistance setpoint and a voltage cut-off."""
    method = parse_experiment(["Discharge at 10 Ohm until 2.5 V"])
    record = _protocol(method[0].model_dump(exclude_none=True))
    for emit in EMITTERS:
        (step,) = emit(record)
        assert step["@type"] == [DISCHARGING]
        (control,) = step[HAS_CONTROL_PARAMETER]
        assert control["@type"] == [ELECTRIC_RESISTANCE]
        assert control[HAS_MEASUREMENT_UNIT] == [{"@id": EMMO + "Ohm"}]
        (cutoff,) = step[HAS_TERMINATION_PARAMETER]
        assert cutoff["@type"] == [LOWER_VOLTAGE_LIMIT]


@pytest.mark.parametrize(
    ("termination", "iri"),
    [
        ({"quantity": "current", "value": 0.05, "unit": "A", "direction": "below"}, LOWER_CURRENT_LIMIT),
        ({"quantity": "current", "value": 50, "unit": "mA", "direction": "below"}, LOWER_CURRENT_LIMIT),
        ({"quantity": "current", "value": 2, "unit": "A", "direction": "above"}, UPPER_CURRENT_LIMIT),
        # A current cut-off with no direction reads as a lower limit, as a
        # voltage cut-off with no direction does.
        ({"quantity": "current", "value": 0.05, "unit": "A"}, LOWER_CURRENT_LIMIT),
        # A current limit is an electric current: a cut-off whose unit belongs to
        # another quantity stays the generic termination quantity.
        ({"quantity": "current", "value": 0.05, "unit": "C", "direction": "below"}, TERMINATION_QUANTITY),
        ({"quantity": "current", "value": 4.0, "unit": "V", "direction": "above"}, TERMINATION_QUANTITY),
        # C-rate and capacity cut-offs have no limit class of their own.
        ({"quantity": "c_rate", "value": 0.02, "unit": "A/Ah", "direction": "below"}, TERMINATION_QUANTITY),
        ({"quantity": "capacity", "value": 2.0, "unit": "Ah", "direction": "above"}, TERMINATION_QUANTITY),
    ],
)
def test_a_cut_off_types_as_its_limit_class(termination: dict, iri: str) -> None:
    record = _protocol(_step("cv", "hold", termination=[termination]))
    for emit in EMITTERS:
        (step,) = emit(record)
        (cutoff,) = step[HAS_TERMINATION_PARAMETER]
        assert cutoff["@type"] == [iri]


def test_steps_inside_a_group_are_typed_by_the_same_table() -> None:
    record = _protocol(
        {
            "mode": "group",
            "count": 2,
            "steps": [_step("cc", "none"), _step("cr", "discharge"), _step("cr", "charge")],
        }
    )
    for emit in EMITTERS:
        (group,) = emit(record)
        inner = group[HAS_TASK]
        assert [s.get("@type") for s in inner] == [[CURRENT_CONTROLLED_PROCESS], [DISCHARGING], None]


# -- validation -----------------------------------------------------------------


def _unmapped(report) -> list[tuple[str, str]]:
    return [(i.severity, i.path) for i in report.issues if i.code == "semantic.method_step_unmapped"]


@pytest.mark.parametrize("policy", ["strict", "publisher", "default", "ingest"])
def test_validation_warns_on_a_step_no_class_fits(policy: str) -> None:
    record = _protocol(
        _step("cc", "charge"),
        _step("cr", "charge"),
        {"mode": "group", "count": 3, "steps": [_step("rest", "rest"), _step("cccv", None)]},
    )
    report = validate_semantic_report(record, policy=policy)
    assert _unmapped(report) == [("warning", "method[1]"), ("warning", "method[2].steps[1]")]
    messages = [i.message for i in report.issues if i.code == "semantic.method_step_unmapped"]
    assert "'cr charge'" in messages[0]
    assert "'cccv'" in messages[1]


@pytest.mark.parametrize(("mode", "direction", "iri"), TYPED_STEPS)
def test_validation_is_silent_on_a_typed_step(mode: str, direction: str | None, iri: str) -> None:
    assert _unmapped(validate_semantic_report(_protocol(_step(mode, direction)), policy="strict")) == []
