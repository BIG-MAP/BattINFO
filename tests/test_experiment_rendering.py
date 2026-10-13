"""``TestSpec.experiment`` renders the stored method faithfully (Empa evaluation, E-05).

The property is documented as the method rendered back to PyBaMM-style strings
for display and round-tripping, but it forced units by quantity ("until 0.05 A"
for a 0.05 mA/cm2 cutoff), read every duration as seconds ("Rest for 6 seconds"
for a 6 h rest) and rendered a loop as the bare word "group". Anyone
round-tripping through those strings got a cutoff wrong by a factor of about 650
and a rest 3,600 times too short.
"""

from __future__ import annotations

import pytest

import battinfo
from battinfo.testmethod import (
    Quantity,
    Step,
    Termination,
    parse_experiment,
    parse_step,
    render_experiment,
    render_method,
    render_step,
)


def _empa_spec() -> battinfo.TestSpec:
    """The reproduction from the evaluation (scripts/repro/e04_e05_testspec.py)."""
    return battinfo.TestSpec(
        id="https://w3id.org/battinfo/spec/0000-0000-0000-0001",
        name="CCCV at 0.1 mA/cm2",
        kind="cycling",
        source_type="import",
        retrieved_at=1750032000,
        method=[
            {
                "mode": "cc",
                "direction": "charge",
                "setpoints": {"current_density": {"value": 0.1, "unit": "mA/cm2"}},
                "termination": [{"quantity": "voltage", "value": 4.2, "unit": "V", "direction": "above"}],
            },
            {
                "mode": "cv",
                "direction": "hold",
                "setpoints": {"voltage": {"value": 4.2, "unit": "V"}},
                "termination": [{"quantity": "current", "value": 0.05, "unit": "mA/cm2", "direction": "below"}],
            },
            {"mode": "rest", "direction": "rest", "duration": {"value": 6, "unit": "h"}},
            {
                "mode": "group",
                "count": 3,
                "steps": [{"mode": "rest", "direction": "rest", "duration": {"value": 60, "unit": "s"}}],
            },
        ],
    )


def test_the_evaluation_reproduction_renders_what_the_record_says() -> None:
    assert _empa_spec().experiment == [
        "Charge at 0.1 mA/cm2 until 4.2 V",
        "Hold at 4.2 V until 0.05 mA/cm2",
        "Rest for 6 hours",
        "Rest for 1 minute",
        "Rest for 1 minute",
        "Rest for 1 minute",
    ]


# -- Units as stated -------------------------------------------------------------


def test_a_current_density_cutoff_is_never_rendered_as_a_current() -> None:
    hold = Step(
        mode="cv",
        direction="hold",
        setpoints={"voltage": Quantity(value=4.2, unit="V")},
        termination=[Termination(quantity="current", value=0.05, unit="mA/cm2", direction="below")],
    )
    assert render_step(hold) == "Hold at 4.2 V until 0.05 mA/cm2"


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (
            Step(mode="cc", direction="discharge", setpoints={"current": Quantity(value=200, unit="mA")}),
            "Discharge at 200 mA",
        ),
        (Step(mode="cv", direction="hold", setpoints={"voltage": Quantity(value=4200, unit="mV")}), "Hold at 4200 mV"),
        (
            Step(mode="cp", direction="discharge", setpoints={"power": Quantity(value=500, unit="mW")}),
            "Discharge at 500 mW",
        ),
        (
            Step(
                mode="cc",
                direction="charge",
                setpoints={"c_rate": Quantity(value=0.1, unit="A/Ah")},
                termination=[Termination(quantity="capacity", value=150, unit="mAh", direction="above")],
            ),
            "Charge at C/10 until 150 mAh",
        ),
        (
            Step(
                mode="cc",
                direction="discharge",
                setpoints={"c_rate": Quantity(value=1, unit="A/Ah")},
                termination=[Termination(quantity="current", value=20, unit="mA", direction="below")],
            ),
            "Discharge at 1C until 20 mA",
        ),
    ],
)
def test_values_render_in_the_unit_they_are_stated_in(step: Step, expected: str) -> None:
    assert render_step(step) == expected


def test_a_state_of_charge_cutoff_names_its_quantity() -> None:
    step = Step(
        mode="cc",
        direction="discharge",
        setpoints={"c_rate": Quantity(value=1 / 3, unit="A/Ah")},
        termination=[Termination(quantity="soc", value=0.1, unit="1", direction="below")],
    )
    assert render_step(step) == "Discharge at C/3 until 0.1 SOC"


def test_numbers_keep_their_digits_and_never_use_an_exponent() -> None:
    step = Step(
        mode="cc",
        direction="discharge",
        setpoints={"current": Quantity(value=5e-05, unit="A")},
        termination=[Termination(quantity="voltage", value=3.123456789, unit="V", direction="below")],
    )
    assert render_step(step) == "Discharge at 0.00005 A until 3.123456789 V"
    # Float noise from unit scaling does not leak into the text.
    assert render_step(parse_step("Discharge at 9 mA until 3 V")) == "Discharge at 0.009 A until 3 V"


# -- Durations in their unit -------------------------------------------------


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (Quantity(value=6, unit="h"), "Rest for 6 hours"),
        (Quantity(value=1, unit="h"), "Rest for 1 hour"),
        (Quantity(value=90, unit="min"), "Rest for 90 minutes"),
        (Quantity(value=1800, unit="s"), "Rest for 30 minutes"),
        (Quantity(value=7200, unit="s"), "Rest for 2 hours"),
        (Quantity(value=45, unit="s"), "Rest for 45 seconds"),
        (Quantity(value=2, unit="d"), "Rest for 2 d"),
        (Quantity(min_value=1, max_value=2, unit="h"), "Rest for 1..2 h"),
    ],
)
def test_durations_render_in_their_unit(duration: Quantity, expected: str) -> None:
    assert render_step(Step(mode="rest", direction="rest", duration=duration)) == expected


def test_a_duration_cutoff_renders_as_a_for_clause() -> None:
    step = Step(
        mode="cc",
        direction="charge",
        setpoints={"c_rate": Quantity(value=1, unit="A/Ah")},
        termination=[
            Termination(quantity="voltage", value=4.2, unit="V", direction="above"),
            Termination(quantity="duration", value=2, unit="h", direction="elapsed"),
        ],
    )
    assert render_step(step) == "Charge at 1C until 4.2 V or for 2 hours"


# -- Loops -------------------------------------------------------------------


def _cycle() -> list[Step]:
    return parse_experiment(["Charge at 1 C until 4.2 V", "Discharge at 1 C until 2.5 V"])


def test_a_loop_inside_the_method_is_unrolled() -> None:
    method = [parse_step("Rest for 6 hours"), Step(mode="group", count=2, steps=_cycle())]
    strings, cycles = render_method(method)
    assert cycles == 1
    assert strings == [
        "Rest for 6 hours",
        "Charge at 1C until 4.2 V",
        "Discharge at 1C until 2.5 V",
        "Charge at 1C until 4.2 V",
        "Discharge at 1C until 2.5 V",
    ]


def test_experiment_keeps_the_repeat_count_of_a_top_level_loop() -> None:
    """render_method keeps the grammar's own repeat form; experiment unrolls it,
    so the count is never dropped."""
    spec = battinfo.TestSpec(
        name="3 cycles",
        kind="cycling",
        experiment=["Charge at 1 C until 4.2 V", "Discharge at 1 C until 2.5 V"],
        cycles=3,
    )
    strings, cycles = render_method(spec.method)
    assert (strings, cycles) == (["Charge at 1C until 4.2 V", "Discharge at 1C until 2.5 V"], 3)
    assert spec.experiment == strings * 3


def test_nested_loops_unroll_inside_out() -> None:
    inner = Step(mode="group", count=2, steps=[parse_step("Hold at 4.2 V until C/20")])
    outer = Step(mode="group", count=2, steps=[parse_step("Rest for 1 minute"), inner])
    assert render_experiment([parse_step("Rest for 1 hour"), outer]) == [
        "Rest for 1 hour",
        "Rest for 1 minute",
        "Hold at 4.2 V until C/20",
        "Hold at 4.2 V until C/20",
        "Rest for 1 minute",
        "Hold at 4.2 V until C/20",
        "Hold at 4.2 V until C/20",
    ]


def test_a_single_loop_renders_as_one_repeat_line() -> None:
    group = Step(mode="group", count=3, steps=_cycle())
    assert render_step(group) == "Repeat 3 times: (Charge at 1C until 4.2 V; Discharge at 1C until 2.5 V)"


def test_a_loop_without_a_count_is_not_rendered_as_running_once() -> None:
    loop = Step(mode="group", steps=_cycle())
    assert render_experiment([loop]) == [
        "Repeat (count not stated): (Charge at 1C until 4.2 V; Discharge at 1C until 2.5 V)"
    ]
    described = Step(mode="group", steps=_cycle(), description="Formation, repeated until stable")
    assert render_experiment([described]) == ["Formation, repeated until stable"]
    assert render_method([loop]) == (render_experiment([loop]), 1)


@pytest.mark.parametrize("count", [0, -2])
def test_a_loop_with_an_invalid_count_is_shown_not_dropped(count: int) -> None:
    """The schema wants count >= 1; a model built around it must not unroll to nothing."""
    loop = Step(mode="group", count=count, steps=[parse_step("Rest for 1 second")])
    expected = [f"Repeat {count} times: (Rest for 1 second)"]
    assert render_experiment([loop]) == expected
    assert render_method([loop]) == (expected, 1)


def test_an_oversized_loop_stays_one_line() -> None:
    loop = Step(mode="group", count=10**9, steps=[parse_step("Rest for 1 second")])
    assert render_experiment([loop]) == ["Repeat 1000000000 times: (Rest for 1 second)"]


# -- Fallbacks and round trips ------------------------------------------------


def test_a_step_without_a_direction_falls_back_to_its_description() -> None:
    """Writing Charge or Discharge for a step with no direction would be a guess."""
    step = Step(mode="cc", setpoints={"current": Quantity(value=1, unit="mA")}, description="Constant current at 1 mA")
    assert render_step(step) == "Constant current at 1 mA"
    assert render_step(Step(mode="cc", setpoints={"current": Quantity(value=1, unit="mA")})) == "cc"


@pytest.mark.parametrize(
    "strings",
    [
        ["Discharge at 200 mA for 90 seconds or until 3 V"],
        ["Charge at 1 C until 4.2 V", "Hold at 4.2 V until 50 mA", "Rest for 2 hours"],
        ["Discharge at 0.5 W for 6 hours or until 2.8 V"],
    ],
)
def test_parsed_steps_read_back_to_the_same_method(strings: list[str]) -> None:
    method = parse_experiment(strings)
    again = parse_experiment(render_experiment(method))
    strip = [s.model_copy(update={"description": None}) for s in method]
    strip_again = [s.model_copy(update={"description": None}) for s in again]
    assert strip == strip_again


def test_structured_units_read_back_to_the_same_values() -> None:
    """A structured step in mA renders in mA; the parser reads it back in A."""
    step = Step(
        mode="cc",
        direction="discharge",
        setpoints={"current": Quantity(value=200, unit="mA")},
        termination=[Termination(quantity="voltage", value=2500, unit="mV", direction="below")],
        duration=Quantity(value=3, unit="h"),
    )
    back = parse_step(render_step(step))
    assert back.setpoints["current"] == Quantity(value=0.2, unit="A")
    assert back.termination[0].value == pytest.approx(2.5)
    assert back.duration == Quantity(value=10800, unit="s")
