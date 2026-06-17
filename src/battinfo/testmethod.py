"""Structured, machine-readable test-method model + PyBaMM-string front-end.

A test spec's *descriptive* layer (what the test did, queryable but not executed)
is an ordered list of typed :class:`Step` objects — its ``method``.  Humans author
this with PyBaMM-style experiment strings, which :func:`parse_experiment` compiles
into the structured model; :func:`render_method` is the inverse, turning a method
back into PyBaMM strings for display and round-tripping.  :func:`compute_facets`
derives a flat rollup index so agents can filter over a spec cheaply.

The PyBaMM grammar is reimplemented here on purpose: PyBaMM pulls in scipy/casadi
and is far too heavy to import for string parsing.  ``pybamm`` is an optional,
dev-only dependency used solely by conformance tests.

Grammar handled (case-insensitive)::

    (Dis)charge at <C-rate|current|power> [for <time>] [or until <value>] ...
    Hold at <voltage>                     [for <time>] [or until <value>] ...
    Rest                                  [for <time>] [or until <value>] ...

Examples::

    "Discharge at C/10 for 10 hours or until 3.3 V"
    "Charge at 1 C until 4.2 V"
    "Hold at 4.2 V until C/50"
    "Discharge at 200 mA for 90 seconds"
    "Rest for 30 minutes"
"""
from __future__ import annotations

import re
from typing import Any, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Quantity",
    "Termination",
    "Step",
    "parse_experiment",
    "parse_step",
    "render_step",
    "render_method",
    "compute_facets",
    "ExperimentSyntaxError",
]


class ExperimentSyntaxError(ValueError):
    """Raised when a PyBaMM-style step string cannot be parsed.

    The message points the author at the structured form or a linked actionable
    artifact rather than silently dropping the step.
    """


# ── Model ─────────────────────────────────────────────────────────────────────

class Quantity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float
    unit: str


class Termination(BaseModel):
    """A single stop condition.  A step's ``termination`` list is any-of (the
    step ends when the first condition is met — PyBaMM's ``or``)."""
    model_config = ConfigDict(extra="forbid")
    quantity: str                      # voltage | current | c_rate | capacity | duration
    value: float
    unit: str
    direction: Optional[str] = None    # below | above | elapsed (None for duration)


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str                          # cc | cv | cccv | cp | cr | rest | eis | scan | group
    direction: Optional[str] = None    # charge | discharge | hold | rest | None
    setpoints: dict[str, Quantity] = Field(default_factory=dict)
    termination: list[Termination] = Field(default_factory=list)
    duration: Optional[Quantity] = None
    temperature: Optional[Quantity] = None
    period: Optional[dict[str, Any]] = None
    tags: list[str] = Field(default_factory=list)
    description: Optional[str] = None
    # group-only
    count: Optional[int] = None
    steps: list["Step"] = Field(default_factory=list)


Step.model_rebuild()


# ── Value parsing ───────────────────────────────────────────────────────────

# unit token (lower-cased) -> (quantity-kind, canonical unit, scale-to-canonical)
_UNIT_TABLE: dict[str, tuple[str, str, float]] = {
    "a": ("current", "A", 1.0),
    "ma": ("current", "A", 1e-3),
    "c": ("c_rate", "A/Ah", 1.0),
    "w": ("power", "W", 1.0),
    "mw": ("power", "W", 1e-3),
    "v": ("voltage", "V", 1.0),
    "mv": ("voltage", "V", 1e-3),
    "ohm": ("resistance", "Ohm", 1.0),
    "ohms": ("resistance", "Ohm", 1.0),
    "Ω": ("resistance", "Ohm", 1.0),
}

_TIME_TABLE: dict[str, float] = {
    "s": 1.0, "sec": 1.0, "second": 1.0, "seconds": 1.0,
    "m": 60.0, "min": 60.0, "minute": 60.0, "minutes": 60.0,
    "h": 3600.0, "hr": 3600.0, "hour": 3600.0, "hours": 3600.0,
}

_CRATE_DIV_RE = re.compile(r"^([cd])\s*/\s*([\d.]+)$", re.IGNORECASE)
_NUM_UNIT_RE = re.compile(r"^([\d.]+)\s*([a-zΩ]+)$", re.IGNORECASE)
_TIME_RE = re.compile(r"^([\d.]+)\s*([a-z]+)$", re.IGNORECASE)


def _parse_value(text: str) -> tuple[str, Quantity]:
    """Parse a magnitude token such as ``C/10``, ``1C``, ``200 mA`` or ``4.1 V``.

    Returns ``(quantity_kind, Quantity)`` with the value normalised to the
    canonical unit (A, V, W, Ohm; C-rate as A/Ah)."""
    token = text.strip()
    div = _CRATE_DIV_RE.match(token)
    if div:
        denom = float(div.group(2))
        if denom == 0:
            raise ExperimentSyntaxError(f"C-rate divisor cannot be zero: '{text}'.")
        return "c_rate", Quantity(value=1.0 / denom, unit="A/Ah")
    m = _NUM_UNIT_RE.match(token)
    if not m:
        raise ExperimentSyntaxError(
            f"Could not parse value '{text}'. Expected e.g. 'C/10', '1C', '200 mA', '4.1 V'."
        )
    number = float(m.group(1))
    unit_key = m.group(2).lower()
    if unit_key not in _UNIT_TABLE:
        raise ExperimentSyntaxError(f"Unknown unit '{m.group(2)}' in '{text}'.")
    kind, canon_unit, scale = _UNIT_TABLE[unit_key]
    return kind, Quantity(value=number * scale, unit=canon_unit)


def _parse_duration(text: str) -> Quantity:
    """Parse the body of a ``for <n> <time-unit>`` clause to seconds."""
    m = _TIME_RE.match(text.strip())
    if not m or m.group(2).lower() not in _TIME_TABLE:
        raise ExperimentSyntaxError(
            f"Could not parse duration '{text}'. Expected e.g. '30 minutes', '1 hour', '90 seconds'."
        )
    return Quantity(value=float(m.group(1)) * _TIME_TABLE[m.group(2).lower()], unit="s")


def _termination_from_value(kind: str, qty: Quantity, direction: str | None) -> Termination:
    """Map a parsed ``until`` value to a termination, inferring approach direction
    from the step's charge/discharge sense when not otherwise determined."""
    if kind == "voltage":
        return Termination(quantity="voltage", value=qty.value, unit=qty.unit,
                           direction="above" if direction == "charge" else "below")
    if kind in ("current", "c_rate"):
        # Cutoff currents are crossed from above as the cell relaxes/charges taper.
        return Termination(quantity=kind, value=qty.value, unit=qty.unit, direction="below")
    raise ExperimentSyntaxError(f"Unsupported termination quantity '{kind}'.")


# ── Step parsing ──────────────────────────────────────────────────────────────

_OP_RE = re.compile(r"^(charge|discharge|hold|rest)\b", re.IGNORECASE)
_AT_RE = re.compile(r"^at\s+", re.IGNORECASE)
_KW_BOUNDARY_RE = re.compile(r"\s+(?:for|until|or)\s+", re.IGNORECASE)
_OR_SPLIT_RE = re.compile(r"\s+or\s+", re.IGNORECASE)

# op + value-kind -> (mode, direction)
_MODE_FOR = {
    ("charge", "current"): ("cc", "charge"),
    ("charge", "c_rate"): ("cc", "charge"),
    ("charge", "power"): ("cp", "charge"),
    ("charge", "resistance"): ("cr", "charge"),
    ("charge", "voltage"): ("cv", "charge"),
    ("discharge", "current"): ("cc", "discharge"),
    ("discharge", "c_rate"): ("cc", "discharge"),
    ("discharge", "power"): ("cp", "discharge"),
    ("discharge", "resistance"): ("cr", "discharge"),
    ("discharge", "voltage"): ("cv", "discharge"),
    ("hold", "voltage"): ("cv", "hold"),
}


def parse_step(text: str) -> Step:
    """Parse a single PyBaMM-style experiment string into a :class:`Step`.

    The original string is preserved on ``Step.description`` so the human-authored
    phrasing survives alongside the structured form."""
    raw = text.strip()
    op_match = _OP_RE.match(raw)
    if not op_match:
        raise ExperimentSyntaxError(
            f"Step must start with Charge, Discharge, Hold or Rest: '{text}'."
        )
    op = op_match.group(1).lower()
    remainder = raw[op_match.end():].strip()

    mode: str
    direction: str | None
    setpoints: dict[str, Quantity] = {}

    if op == "rest":
        mode, direction = "rest", "rest"
        tail = remainder
    else:
        at_match = _AT_RE.match(remainder)
        if not at_match:
            raise ExperimentSyntaxError(f"'{op}' step requires 'at <value>': '{text}'.")
        after_at = remainder[at_match.end():]
        boundary = _KW_BOUNDARY_RE.search(after_at)
        if boundary:
            value_str, tail = after_at[:boundary.start()], after_at[boundary.start():]
        else:
            value_str, tail = after_at, ""
        kind, qty = _parse_value(value_str)
        key = (op, kind)
        if key not in _MODE_FOR:
            raise ExperimentSyntaxError(f"Cannot {op} at a {kind} value: '{text}'.")
        mode, direction = _MODE_FOR[key]
        setpoints[kind] = qty

    duration: Quantity | None = None
    terminations: list[Termination] = []
    for clause in _OR_SPLIT_RE.split(tail.strip()):
        clause = clause.strip()
        if not clause:
            continue
        low = clause.lower()
        if low.startswith("for "):
            duration = _parse_duration(clause[4:])
        elif low.startswith("until "):
            kind, qty = _parse_value(clause[6:])
            terminations.append(_termination_from_value(kind, qty, direction))
        else:
            raise ExperimentSyntaxError(
                f"Unexpected clause '{clause}' in '{text}'. Expected 'for ...' or 'until ...'."
            )

    return Step(
        mode=mode,
        direction=direction,
        setpoints=setpoints,
        termination=terminations,
        duration=duration,
        description=raw,
    )


def parse_experiment(steps: Sequence[str], cycles: int | None = None) -> list[Step]:
    """Compile a list of PyBaMM-style strings into a structured ``method``.

    When ``cycles`` > 1 the whole sequence is wrapped in a single ``group`` step
    (EMMO ``IterativeWorkflow``), matching PyBaMM's ``experiment * cycles``."""
    parsed = [parse_step(s) for s in steps]
    if cycles is not None and cycles > 1:
        return [Step(mode="group", count=int(cycles), steps=parsed)]
    return parsed


# ── Rendering (inverse of parsing) ──────────────────────────────────────────

def _fmt_number(value: float) -> str:
    return f"{value:g}"


def _fmt_crate(value: float) -> str:
    if value >= 1.0:
        return f"{_fmt_number(value)}C"
    inv = 1.0 / value
    rounded = round(inv)
    if rounded > 0 and abs(inv - rounded) < 1e-6:
        return f"C/{rounded}"
    return f"{_fmt_number(value)}C"


def _fmt_setpoint(kind: str, qty: Quantity) -> str:
    if kind == "c_rate":
        return _fmt_crate(qty.value)
    if kind == "current":
        return f"{_fmt_number(qty.value)} A"
    if kind == "power":
        return f"{_fmt_number(qty.value)} W"
    if kind == "resistance":
        return f"{_fmt_number(qty.value)} Ohm"
    if kind == "voltage":
        return f"{_fmt_number(qty.value)} V"
    return f"{_fmt_number(qty.value)} {qty.unit}"


def _fmt_duration(qty: Quantity) -> str:
    seconds = qty.value
    if seconds % 3600 == 0:
        return f"for {_fmt_number(seconds / 3600)} hours"
    if seconds % 60 == 0:
        return f"for {_fmt_number(seconds / 60)} minutes"
    return f"for {_fmt_number(seconds)} seconds"


def _fmt_termination(term: Termination) -> str:
    if term.quantity == "c_rate":
        return f"until {_fmt_crate(term.value)}"
    suffix = {"voltage": "V", "current": "A", "capacity": "Ah"}.get(term.quantity, term.unit)
    return f"until {_fmt_number(term.value)} {suffix}"


def render_step(step: Step) -> str:
    """Render a single :class:`Step` to a PyBaMM-style string.

    Best-effort: modes PyBaMM cannot express (eis, scan, cccv, a non-top-level
    group) render to a readable label rather than raising, so this never crashes
    on a structured method. The cc/cv/cp/cr/rest forms round-trip exactly."""
    if step.mode == "rest":
        head = "Rest"
    elif step.mode == "cv":
        volt = step.setpoints.get("voltage")
        head = f"Hold at {_fmt_number(volt.value)} V" if volt else "Hold"
    elif step.mode in ("cc", "cp", "cr"):
        word = "Charge" if step.direction == "charge" else "Discharge"
        kind = next(iter(step.setpoints), None)
        head = f"{word} at {_fmt_setpoint(kind, step.setpoints[kind])}" if kind else word
    elif step.mode == "cccv":
        word = "Charge" if step.direction == "charge" else "Discharge"
        rate = next((k for k in step.setpoints if k != "voltage"), None)
        volt = step.setpoints.get("voltage")
        rate_str = f" at {_fmt_setpoint(rate, step.setpoints[rate])}" if rate else ""
        volt_str = f" to {_fmt_number(volt.value)} V then hold" if volt else ""
        head = f"{word}{rate_str}{volt_str}"
    else:
        # eis / scan / group / unknown — not PyBaMM-expressible; use a label.
        return step.description or (f"{step.direction} {step.mode}".strip() if step.direction else step.mode)

    clauses: list[str] = []
    if step.duration is not None:
        clauses.append(_fmt_duration(step.duration))
    clauses.extend(_fmt_termination(t) for t in step.termination)
    return head + (" " + " or ".join(clauses) if clauses else "")


def render_method(steps: Sequence[Step]) -> tuple[list[str], int]:
    """Render a ``method`` back to ``(step_strings, cycles)``.

    A single top-level ``group`` is unwrapped to ``(inner_strings, count)``;
    otherwise the steps render flat with ``cycles == 1``."""
    if len(steps) == 1 and steps[0].mode == "group":
        group = steps[0]
        return [render_step(s) for s in group.steps], int(group.count or 1)
    return [render_step(s) for s in steps], 1


# ── Facets (derived filter index) ──────────────────────────────────────────

def _iter_leaf_steps(steps: Sequence[Step]):
    for step in steps:
        if step.mode == "group":
            yield from _iter_leaf_steps(step.steps)
        else:
            yield step


_CONTROL_MODE = {"cc": "current", "cv": "voltage", "cccv": "current",
                 "cp": "power", "cr": "resistance"}


def compute_facets(steps: Sequence[Step],
                   conditions: dict[str, Quantity] | None = None) -> dict[str, Any]:
    """Derive a flat, queryable rollup of a method for cheap agent filtering."""
    modes: list[str] = []
    directions: set[str] = set()
    control_modes: set[str] = set()
    c_rates: list[float] = []
    voltages: list[float] = []
    temperatures: list[float] = []
    tags: set[str] = set()

    for step in steps:
        if step.mode not in modes:
            modes.append(step.mode)
    for step in _iter_leaf_steps(steps):
        if step.direction and step.direction not in ("rest", "hold"):
            directions.add(step.direction)
        if step.mode in _CONTROL_MODE:
            control_modes.add(_CONTROL_MODE[step.mode])
        for key, qty in step.setpoints.items():
            if key == "c_rate":
                c_rates.append(qty.value)
            elif key == "voltage":
                voltages.append(qty.value)
        for term in step.termination:
            if term.quantity == "voltage":
                voltages.append(term.value)
            elif term.quantity == "c_rate":
                c_rates.append(term.value)
        if step.temperature is not None:
            temperatures.append(step.temperature.value)
        tags.update(step.tags)

    for key, qty in (conditions or {}).items():
        if key in ("temperature", "ambient_temperature", "room_temperature"):
            temperatures.append(qty.value)

    leaf_modes = {s.mode for s in _iter_leaf_steps(steps)}
    facets: dict[str, Any] = {
        "modes": modes,
        "directions": sorted(directions),
        "control_modes": sorted(control_modes),
        "has_cv_hold": "cv" in leaf_modes or "cccv" in leaf_modes,
        "has_rest": "rest" in leaf_modes,
        "has_eis": "eis" in leaf_modes,
    }
    if c_rates:
        facets["c_rates"] = sorted(set(c_rates))
    if voltages:
        facets["voltage_window_V"] = [min(voltages), max(voltages)]
    if temperatures:
        facets["temperatures"] = sorted(set(temperatures))
    if tags:
        facets["tags"] = sorted(tags)
    return facets
