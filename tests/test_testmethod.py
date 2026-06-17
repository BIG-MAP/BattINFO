"""Tests for the PyBaMM-string front-end and structured test-method model."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.testmethod import (  # noqa: E402
    ExperimentSyntaxError,
    Quantity,
    Step,
    compute_facets,
    parse_experiment,
    parse_step,
    render_method,
    render_step,
)


def test_parse_cc_discharge_crate_division() -> None:
    step = parse_step("Discharge at C/10 for 10 hours or until 3.3 V")
    assert step.mode == "cc"
    assert step.direction == "discharge"
    assert step.setpoints["c_rate"].value == pytest.approx(0.1)
    assert step.setpoints["c_rate"].unit == "A/Ah"
    assert step.duration.value == pytest.approx(36000.0)  # 10 h
    assert len(step.termination) == 1
    term = step.termination[0]
    assert (term.quantity, term.direction) == ("voltage", "below")
    assert term.value == pytest.approx(3.3)
    assert step.description == "Discharge at C/10 for 10 hours or until 3.3 V"


def test_parse_charge_voltage_termination_is_upper() -> None:
    step = parse_step("Charge at 1 C until 4.2 V")
    assert step.mode == "cc" and step.direction == "charge"
    assert step.setpoints["c_rate"].value == pytest.approx(1.0)
    assert step.termination[0].direction == "above"


def test_parse_hold_until_crate() -> None:
    step = parse_step("Hold at 4.2 V until C/50")
    assert step.mode == "cv" and step.direction == "hold"
    assert step.setpoints["voltage"].value == pytest.approx(4.2)
    assert step.termination[0].quantity == "c_rate"
    assert step.termination[0].value == pytest.approx(0.02)


def test_parse_current_milliamp_normalised() -> None:
    step = parse_step("Discharge at 200 mA for 90 seconds")
    assert step.setpoints["current"].value == pytest.approx(0.2)
    assert step.setpoints["current"].unit == "A"
    assert step.duration.value == pytest.approx(90.0)


def test_parse_power_and_rest() -> None:
    p = parse_step("Discharge at 5 W for 0.5 hours")
    assert p.mode == "cp" and p.setpoints["power"].value == pytest.approx(5.0)
    r = parse_step("Rest for 30 minutes")
    assert r.mode == "rest" and r.duration.value == pytest.approx(1800.0)
    assert not r.setpoints


def test_parse_errors_are_explicit() -> None:
    with pytest.raises(ExperimentSyntaxError):
        parse_step("Teleport at 9000 W")
    with pytest.raises(ExperimentSyntaxError):
        parse_step("Charge at 1 C until banana")
    with pytest.raises(ExperimentSyntaxError):
        parse_step("Charge at C/0")


def test_cycles_wraps_in_group() -> None:
    method = parse_experiment(
        ["Charge at 1 C until 4.2 V", "Discharge at 1 C until 2.5 V"], cycles=3
    )
    assert len(method) == 1
    grp = method[0]
    assert grp.mode == "group" and grp.count == 3
    assert [s.direction for s in grp.steps] == ["charge", "discharge"]


def _strip_descriptions(steps: list[Step]) -> list[Step]:
    """Structural copy ignoring the preserved human phrasing on ``description``."""
    out = []
    for s in steps:
        c = s.model_copy(deep=True)
        c.description = None
        c.steps = _strip_descriptions(c.steps)
        out.append(c)
    return out


@pytest.mark.parametrize(
    "strings,cycles",
    [
        (["Discharge at C/10 until 3.3 V"], None),
        (["Charge at 1 C until 4.2 V", "Hold at 4.2 V until C/50",
          "Discharge at 0.5 C until 2.5 V"], None),
        (["Charge at 200 mA until 4.1 V", "Rest for 30 minutes"], 5),
        (["Discharge at 5 W for 1 hour or until 3 V"], None),
    ],
)
def test_render_parse_roundtrip_is_stable(strings, cycles) -> None:
    """parse -> render -> parse must reproduce the structured method (modulo the
    human phrasing kept on ``description``)."""
    method1 = parse_experiment(strings, cycles)
    rendered, out_cycles = render_method(method1)
    method2 = parse_experiment(rendered, out_cycles)
    assert _strip_descriptions(method1) == _strip_descriptions(method2)


def test_render_crate_forms() -> None:
    assert render_step(parse_step("Discharge at C/10 until 3 V")).startswith("Discharge at C/10")
    assert render_step(parse_step("Discharge at 2 C until 3 V")).startswith("Discharge at 2C")


def test_render_is_total_for_non_pybamm_modes() -> None:
    """render_step must never raise on a structured method (eis/scan/cccv) — the
    .experiment property and the bundle adapter depend on this."""
    eis = Step(mode="eis", direction="hold",
               setpoints={"start_frequency": Quantity(value=1e5, unit="Hz")})
    assert isinstance(render_step(eis), str)  # no crash
    cccv = Step(mode="cccv", direction="charge",
                setpoints={"c_rate": Quantity(value=1.0, unit="A/Ah"),
                           "voltage": Quantity(value=4.2, unit="V")})
    assert "hold" in render_step(cccv).lower()
    strings, _ = render_method([eis])
    assert strings and isinstance(strings[0], str)


def test_facets_rollup() -> None:
    method = parse_experiment(
        ["Charge at 1 C until 4.2 V", "Hold at 4.2 V until C/50",
         "Rest for 10 minutes", "Discharge at 0.5 C until 2.5 V"],
        cycles=3,
    )
    facets = compute_facets(method)
    assert facets["has_cv_hold"] is True
    assert facets["has_rest"] is True
    assert facets["has_eis"] is False
    assert set(facets["directions"]) == {"charge", "discharge"}
    assert facets["control_modes"] == ["current", "voltage"]
    assert facets["c_rates"] == [0.02, 0.5, 1.0]
    assert facets["voltage_window_V"] == [2.5, 4.2]
    assert facets["modes"] == ["group"]
