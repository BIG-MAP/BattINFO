"""Structured, machine-readable test-method model + PyBaMM-string front-end.

A test spec's *descriptive* layer (what the test did, queryable but not executed)
is an ordered list of typed :class:`Step` objects — its ``method``.  Humans author
this with PyBaMM-style experiment strings, which :func:`parse_experiment` compiles
into the structured model; :func:`render_method` is the inverse, turning a method
back into PyBaMM strings for display and round-tripping (:func:`render_experiment`
gives one flat list with every loop unrolled).  :func:`compute_facets`
derives a flat rollup index so agents can filter over a spec cheaply.

The PyBaMM grammar is reimplemented here on purpose: PyBaMM pulls in scipy/casadi
and is far too heavy to import for string parsing.  ``pybamm`` is an optional,
dev-only dependency used solely by conformance tests.

Grammar handled (case-insensitive)::

    (Dis)charge at <C-rate|current|current density|power> [for <time>] [or until <value>] ...
    Hold at <voltage>                                     [for <time>] [or until <value>] ...
    Rest                                                  [for <time>] [or until <value>] ...

Examples::

    "Discharge at C/10 for 10 hours or until 3.3 V"
    "Charge at 1 C until 4.2 V"
    "Hold at 4.2 V until C/50"
    "Discharge at 200 mA for 90 seconds"
    "Charge at 0.1 mA/cm2 until 4.2 V"
    "Hold at 4.2 V until 0.05 mA/cm2"
    "Rest for 30 minutes"

A current density (``mA/cm2``, ``A/m2``, ``mA cm-2``) is a BattINFO extension;
PyBaMM's own grammar has no per-area current.
"""

from __future__ import annotations

import re
import warnings
from decimal import Decimal
from fractions import Fraction
from typing import Any, Optional, Sequence

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    field_validator,
    model_validator,
)

__all__ = [
    "Quantity",
    "Termination",
    "Step",
    "parse_experiment",
    "parse_step",
    "parse_termination",
    "render_step",
    "render_method",
    "render_experiment",
    "compute_facets",
    "ExperimentSyntaxError",
    "STEP_MODES",
    "STEP_DIRECTIONS",
    "TERMINATION_QUANTITIES",
    "TERMINATION_DIRECTIONS",
]

# Controlled vocabularies enforced at construction. These MUST match the enums
# the save-time JSON Schema (data/schemas/test-protocol.schema.json) applies to a
# step/termination, so a model that constructs cannot later be rejected at save
# (the "fail at construction, not at save" principle — see M1 in the 0.8
# readiness report).
STEP_MODES: tuple[str, ...] = ("cc", "cv", "cccv", "cp", "cr", "rest", "eis", "scan", "group")
STEP_DIRECTIONS: tuple[str, ...] = ("charge", "discharge", "hold", "rest", "none")
TERMINATION_QUANTITIES: tuple[str, ...] = ("voltage", "current", "c_rate", "capacity", "soc", "duration")
TERMINATION_DIRECTIONS: tuple[str, ...] = ("below", "above", "elapsed")


# SI prefixes are case-sensitive, as SI writes them: m is milli and M is mega;
# u and µ are both micro. A prefix not listed for a unit raises rather than
# being guessed (case-folding once read 1 MA/m2 as 1 mA/m2, nine orders of
# magnitude off).
_SI_PREFIX: dict[str, Fraction] = {
    "M": Fraction(10**6),
    "k": Fraction(10**3),
    "": Fraction(1),
    "m": Fraction(1, 10**3),
    "µ": Fraction(1, 10**6),
    "u": Fraction(1, 10**6),
    "n": Fraction(1, 10**9),
}
_CURRENT_SYMBOL = {"M": "MA", "k": "kA", "": "A", "m": "mA", "µ": "µA", "u": "µA", "n": "nA"}

# A current stated per area is a current density, whatever key or termination
# quantity it is written under, so the emitters type it as one. Coin-cell
# protocols state currents this way (0.1 mA/cm2). Area prefix -> (unit, in cm2).
_AREA_CM2: dict[str, tuple[str, Fraction]] = {
    "": ("m2", Fraction(10**4)),
    "c": ("cm2", Fraction(1)),
    "m": ("mm2", Fraction(1, 100)),
}
# "mA/cm2", "mA / cm^2", "mA/cm²", and the product forms "mA cm-2", "A.m-2".
# Case-sensitive: a prefix is any one letter, checked below, and the metre must
# be a lower-case m (M is mega).
_AREAL_CURRENT_RE = re.compile(
    r"^(?P<prefix>[^\W\d_]?)(?P<ampere>[Aa])\s*"
    r"(?:/\s*(?P<per>[^\W\d_]?)m\s*\^?\s*2|(?:\s+|\s*[.·*]\s*)(?P<times>[^\W\d_]?)m\s*\^?\s*-\s*2)$"
)


def _check_prefix(prefix: str, letter: str, allowed: Any, unit: str) -> None:
    """Refuse a prefix that is not listed for the unit, and an upper-case
    prefix on a lower-case unit letter ("Ma": mega-ampere, or a mistyped mA?)."""
    if letter.islower() and prefix != prefix.lower():
        raise ExperimentSyntaxError(
            f"Ambiguous unit '{unit}': write it in SI case, for example 'mA' for milliampere "
            "or 'MA' for megaampere."
        )
    if prefix not in allowed:
        known = ", ".join(repr(p) for p in sorted(allowed) if p) or "none"
        raise ExperimentSyntaxError(
            f"Unsupported prefix '{prefix}' in unit '{unit}' (prefixes read here: {known})."
        )


def _current_density_unit(unit: Any) -> tuple[str, Fraction] | None:
    """``(canonical symbol, factor to mA/cm2)`` when ``unit`` is a current per
    area (``mA/cm2``, ``A/m2``, ``mA cm-2``, ...), otherwise ``None``.

    Raises :class:`ExperimentSyntaxError` for a current per area with a prefix
    the grammar does not read, such as ``pA/cm2`` or ``mA/Mm2``."""
    if not isinstance(unit, str):
        return None
    text = unit.strip().replace("²", "2").replace("⁻", "-").replace("−", "-").replace("μ", "µ")
    match = _AREAL_CURRENT_RE.match(text)
    if not match:
        return None
    prefix, area = match.group("prefix"), match.group("per") or match.group("times") or ""
    _check_prefix(prefix, match.group("ampere"), _SI_PREFIX, unit)
    if area not in _AREA_CM2:
        raise ExperimentSyntaxError(
            f"Unsupported area unit '{area}m2' in '{unit}' (read here: m2, cm2, mm2)."
        )
    area_symbol, area_factor = _AREA_CM2[area]
    # Factor to mA/cm2: the prefix factor in A, times 1000 mA per A, per area in cm2.
    return f"{_CURRENT_SYMBOL[prefix]}/{area_symbol}", _SI_PREFIX[prefix] * 1000 / area_factor


def _is_current_density_unit(unit: Any) -> bool:
    """True when ``unit`` is a current per area the grammar reads. Never raises:
    the emitters call it on stored records, where an unreadable unit is left as
    written."""
    try:
        return _current_density_unit(unit) is not None
    except ExperimentSyntaxError:
        return False


def _require_member(value: Any, allowed: tuple[str, ...], field: str) -> Any:
    """Validate ``value`` against a controlled vocabulary at construction time.

    ``None`` passes through (the field is optional); any other value must be one
    of ``allowed`` or a ``ValueError`` naming the valid values is raised. This is
    what makes the model reject a bad enum where it is authored instead of at
    ``ws.save()``."""
    if value is None:
        return value
    if value not in allowed:
        raise ValueError(f"{field} must be one of {list(allowed)}; got {value!r}.")
    return value


class ExperimentSyntaxError(ValueError):
    """Raised when a PyBaMM-style step string cannot be parsed.

    The message points the author at the structured form or a linked actionable
    artifact rather than silently dropping the step.
    """


# ── Model ─────────────────────────────────────────────────────────────────────


class Quantity(BaseModel):
    """A value (or min/max window) with its unit.

    Scalar form: ``{value: 4.2, unit: "V"}``. Window form (aligned with the
    canonical quantity schema's ``min_value``/``max_value`` fields):
    ``{min_value: 2.5, max_value: 4.2, unit: "V"}`` — e.g. a test-spec voltage
    window. At least one of ``value``/``min_value``/``max_value`` is required.
    """

    model_config = ConfigDict(extra="forbid")
    value: Optional[float] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    unit: str

    @model_validator(mode="after")
    def _require_some_value(self) -> "Quantity":
        if self.value is None and self.min_value is None and self.max_value is None:
            raise ValueError(
                "Quantity needs at least one of value, min_value, max_value "
                "(e.g. {'value': 25, 'unit': 'degC'} or "
                "{'min_value': 2.5, 'max_value': 4.2, 'unit': 'V'})."
            )
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValueError(f"Quantity min_value ({self.min_value}) must not exceed max_value ({self.max_value}).")
        return self


class Termination(BaseModel):
    """A single stop condition.  A step's ``termination`` list is any-of (the
    step ends when the first condition is met — PyBaMM's ``or``).

    A current cutoff may be stated per area (``{"quantity": "current", "value":
    0.05, "unit": "mA/cm2"}``); it is a current density and emits as one. A
    current cutoff in a unit of another quantity (``V``, ``Ah``, ``C``) is
    refused in a step string; a stored record or a dict keeps it, and the step
    warns (see :class:`Step`)."""

    model_config = ConfigDict(extra="forbid")
    quantity: str  # voltage | current | c_rate | capacity | soc | duration
    value: float
    unit: str
    direction: Optional[str] = None  # below | above | elapsed (None for duration)

    @field_validator("quantity")
    @classmethod
    def _check_quantity(cls, value: Any) -> Any:
        return _require_member(value, TERMINATION_QUANTITIES, "Termination.quantity")

    @field_validator("direction")
    @classmethod
    def _check_direction(cls, value: Any) -> Any:
        return _require_member(value, TERMINATION_DIRECTIONS, "Termination.direction")


# Units of other quantities, for the current-cutoff unit check:
# lower-cased unit -> (what it measures, the termination quantity to use instead).
# Units not listed here (a specific current such as mA/g, say) are let through.
_OTHER_QUANTITY_UNITS: dict[str, tuple[str, str | None]] = {
    **{u: ("voltage", "voltage") for u in ("v", "mv", "kv", "µv", "uv")},
    **{u: ("C-rate", "c_rate") for u in ("c", "a/ah", "1/h", "h-1")},
    **{u: ("charge", "capacity") for u in ("ah", "mah", "µah", "uah", "as", "mas")},
    **{u: ("time", "duration") for u in ("s", "sec", "min", "h", "hr", "hour", "hours", "minutes", "seconds")},
    **{u: ("dimensionless", "soc") for u in ("1", "%")},
    **{u: ("power", None) for u in ("w", "mw", "kw")},
    **{u: ("resistance", None) for u in ("ohm", "ohms", "mohm", "ω", "mω")},
}


def _other_quantity_of_unit(unit: str) -> tuple[str, str | None] | None:
    """``(what the unit measures, quantity to use)`` when ``unit`` belongs to a
    quantity other than current, otherwise ``None``."""
    return _OTHER_QUANTITY_UNITS.get(unit.strip().lower())


def _foreign_current_unit(term: Termination) -> str | None:
    """What is wrong with a ``current`` cutoff whose unit belongs to another
    quantity, or ``None`` when the cutoff is fine."""
    if term.quantity != "current":
        return None
    other = _other_quantity_of_unit(term.unit)
    if other is None:
        return None
    kind, hint = other
    advice = f" Use quantity '{hint}' for that cutoff." if hint else ""
    return f"a 'current' termination in {term.unit!r}, which is a {kind} unit.{advice}"


def _refuse_foreign_current_units(terminations: Sequence[Termination], text: str) -> None:
    """A step or cutoff written as a string is new authoring: refuse a current
    cutoff in another quantity's unit outright."""
    for term in terminations:
        problem = _foreign_current_unit(term)
        if problem:
            raise ExperimentSyntaxError(f"'{text}' gives {problem}")


# Comparison-string termination shorthand ("Voltage > 4.2", "C-rate < C/50",
# "SOC < 0.05", "Time > 30 min") — the way engineers write cutoffs, and the
# way UCP's `ends` writes them. Parsed at construction into the structured
# form; the stored record never carries the string.
_SHORTHAND_QUANTITY: dict[str, tuple[str, str]] = {
    "voltage": ("voltage", "V"),
    "v": ("voltage", "V"),
    "current": ("current", "A"),
    "i": ("current", "A"),
    # A current cutoff per area is stored as a current in mA/cm2.
    "current density": ("current", "mA/cm2"),
    "current_density": ("current", "mA/cm2"),
    "c-rate": ("c_rate", "A/Ah"),
    "c_rate": ("c_rate", "A/Ah"),
    "crate": ("c_rate", "A/Ah"),
    "rate": ("c_rate", "A/Ah"),
    "capacity": ("capacity", "Ah"),
    "soc": ("soc", "1"),
    "state of charge": ("soc", "1"),
    "time": ("duration", "s"),
    "duration": ("duration", "s"),
}

# The value kinds each left side accepts, where that is more than its quantity:
# a current cutoff may be stated per area, a current-density cutoff only so.
_SHORTHAND_VALUE_KINDS: dict[str, frozenset[str]] = {
    "current": frozenset({"current", "current_density"}),
    "i": frozenset({"current", "current_density"}),
    "current density": frozenset({"current_density"}),
    "current_density": frozenset({"current_density"}),
}

_SHORTHAND_RE = re.compile(r"^\s*(.+?)\s*([<>])=?\s*(.+?)\s*$")


def parse_termination(text: str) -> Termination:
    """Parse a comparison-string termination into the structured form.

    ``"Voltage > 4.2"`` → voltage above 4.2 V; ``"C-rate < C/50"`` → c_rate
    below 0.02 A/Ah; ``"Current < 50 mA"`` → current below 0.05 A;
    ``"Current < 0.05 mA/cm2"`` (or ``"Current density < 0.05"``) → current
    below 0.05 mA/cm2; ``"SOC < 0.05"`` → soc below 0.05; ``"Time > 30 min"``
    → duration 1800 s. The left side names the quantity, the operator gives the
    approach direction (irrelevant for time), and the right side is a number in
    the quantity's canonical unit or any magnitude ``_parse_value`` understands.
    """
    match = _SHORTHAND_RE.match(text or "")
    if not match:
        raise ExperimentSyntaxError(
            f"Could not parse termination '{text}'. Expected e.g. 'Voltage > 4.2', "
            "'C-rate < C/50', 'SOC < 0.05', 'Time > 30 min'."
        )
    lhs, op, rhs = match.group(1).strip().lower(), match.group(2), match.group(3).strip()
    info = _SHORTHAND_QUANTITY.get(lhs)
    if info is None:
        raise ExperimentSyntaxError(
            f"Unknown termination quantity '{match.group(1).strip()}' in '{text}'. "
            f"Known: {sorted(set(q for q, _ in _SHORTHAND_QUANTITY.values()))}."
        )
    quantity, default_unit = info
    if quantity == "duration":
        time_match = _TIME_RE.match(rhs)
        if time_match and time_match.group(2).lower() in _TIME_TABLE:
            seconds = _to_float(time_match.group(1), text) * _TIME_TABLE[time_match.group(2).lower()]
        else:
            seconds = _to_float(rhs, text)
        return Termination(quantity="duration", value=seconds, unit="s", direction="elapsed")
    try:
        value = float(rhs)
        unit = default_unit
    except ValueError:
        kind, qty = _parse_value(rhs)
        if kind not in _SHORTHAND_VALUE_KINDS.get(lhs, frozenset({quantity})):
            named = "current density" if default_unit == "mA/cm2" else quantity
            raise ExperimentSyntaxError(
                f"Termination '{text}' names {named} but its value parses as {kind}."
            ) from None
        value, unit = _require_value(qty, f"Termination '{text}'"), qty.unit
    term = Termination(quantity=quantity, value=value, unit=unit,
                       direction="below" if op == "<" else "above")
    _refuse_foreign_current_units([term], text)
    return term


class Step(BaseModel):
    """One segment of a test method — a charge/discharge/hold/rest/scan step with
    setpoints, any-of stop conditions, and optional sub-steps (when ``mode`` is a group)."""

    model_config = ConfigDict(extra="forbid")

    mode: str  # cc | cv | cccv | cp | cr | rest | eis | scan | group
    step_id: Optional[int] = None  # identifier in the test program/schedule; aligns with BDF step_id
    direction: Optional[str] = None  # charge | discharge | hold | rest | None
    setpoints: dict[str, Quantity] = Field(default_factory=dict)
    termination: list[Termination] = Field(default_factory=list)
    duration: Optional[Quantity] = None
    temperature: Optional[Quantity] = None
    tags: list[str] = Field(default_factory=list)
    description: Optional[str] = None
    # group-only
    count: Optional[int] = None
    steps: list["Step"] = Field(default_factory=list)

    @field_validator("termination", mode="before")
    @classmethod
    def _coerce_termination(cls, value: Any) -> Any:
        # Authoring shorthand: a comparison string (or a bare one outside a
        # list) parses into the structured form at construction.
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list):
            return [parse_termination(item) if isinstance(item, str) else item for item in value]
        return value

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, value: Any) -> Any:
        return _require_member(value, STEP_MODES, "Step.mode")

    @field_validator("direction")
    @classmethod
    def _check_direction(cls, value: Any) -> Any:
        return _require_member(value, STEP_DIRECTIONS, "Step.direction")

    @model_validator(mode="wrap")
    @classmethod
    def _warn_foreign_current_units(cls, data: Any, handler: ModelWrapValidatorHandler["Step"]) -> "Step":
        # A step built from a stored record or a dict may hold a current cutoff
        # in another quantity's unit (published before the check existed, or
        # written by an importer). Refusing it would make the record unreadable,
        # so warn and keep it as written; a step string refuses it instead.
        # A Step instance passed on to another model was checked when it was
        # built, so it does not warn again.
        step = handler(data)
        if not isinstance(data, Step):
            for term in step.termination:
                problem = _foreign_current_unit(term)
                if problem:
                    warnings.warn(f"Step {_step_name(step)} has {problem} It is kept as written.",
                                  UserWarning, stacklevel=2)
        return step


def _step_name(step: Step) -> str:
    """How a warning names a step: its description, its step_id, or its mode."""
    if step.description:
        return repr(step.description)
    if step.step_id is not None:
        return f"with step_id {step.step_id}"
    return f"({step.mode} {step.direction})" if step.direction else f"({step.mode})"


Step.model_rebuild()


# ── Value parsing ───────────────────────────────────────────────────────────

# Units of the step grammar that take a prefix: unit letter (either case) ->
# (quantity kind, canonical unit, prefixes read). The prefix itself is
# case-sensitive (see _SI_PREFIX).
_PREFIXED_UNITS: dict[str, tuple[str, str, frozenset[str]]] = {
    "A": ("current", "A", frozenset(_SI_PREFIX)),
    "W": ("power", "W", frozenset({"", "m"})),
    "V": ("voltage", "V", frozenset({"", "m"})),
}
# Units read without a prefix: lower-cased token -> (quantity kind, canonical unit).
_UNPREFIXED_UNITS: dict[str, tuple[str, str]] = {
    "c": ("c_rate", "A/Ah"),
    "ohm": ("resistance", "Ohm"),
    "ohms": ("resistance", "Ohm"),
    "ω": ("resistance", "Ohm"),  # lowercased Ω (U+03A9 -> U+03C9) after .lower()
}


def _unit_factor(unit: str, text: str) -> tuple[str, str, Fraction]:
    """``(quantity kind, canonical unit, factor)`` for a unit token such as
    ``mA``, ``MA``, ``V`` or ``Ohm``. Raises for an unknown unit or prefix."""
    plain = _UNPREFIXED_UNITS.get(unit.lower())
    if plain is not None:
        return plain[0], plain[1], Fraction(1)
    prefix, letter = unit[:-1].replace("μ", "µ"), unit[-1:]
    base = _PREFIXED_UNITS.get(letter.upper())
    if base is None:
        raise ExperimentSyntaxError(f"Unknown unit '{unit}' in '{text}'.")
    kind, canonical, allowed = base
    _check_prefix(prefix, letter, allowed, unit)
    return kind, canonical, _SI_PREFIX[prefix]

_TIME_TABLE: dict[str, float] = {
    "s": 1.0,
    "sec": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "m": 60.0,
    "min": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
}

_CRATE_DIV_RE = re.compile(r"^([cd])\s*/\s*([\d.]+)$", re.IGNORECASE)
_NUM_UNIT_RE = re.compile(r"^([\d.]+)\s*([a-zA-ZµμΩω]+)$")
_NUM_ANY_UNIT_RE = re.compile(r"^([\d.]+)\s*(\S.*)$")
_TIME_RE = re.compile(r"^([\d.]+)\s*([a-z]+)$", re.IGNORECASE)

# Parsed current densities are normalised to mA/cm2, the unit battery
# protocols state them in.
_CURRENT_DENSITY_UNIT = "mA/cm2"


def _to_float(token: str, text: str) -> float:
    """Coerce a numeric token, raising ``ExperimentSyntaxError`` (the module's
    documented exception) rather than leaking a raw ``ValueError`` when the token
    is malformed — e.g. a multi-dot typo like ``4.2.1`` that the ``[\\d.]+``
    patterns admit but ``float()`` rejects."""
    try:
        return float(token)
    except ValueError:
        raise ExperimentSyntaxError(f"Could not parse number '{token}' in '{text}'.") from None


def _to_fraction(token: str, text: str) -> Fraction:
    """A numeric token as an exact fraction, so unit factors add no float noise
    (3 A/m2 is 0.3 mA/cm2, not 0.30000000000000004)."""
    try:
        return Fraction(token)
    except ValueError:
        raise ExperimentSyntaxError(f"Could not parse number '{token}' in '{text}'.") from None


def _parse_current_density(token: str, text: str) -> Quantity | None:
    """``0.1 mA/cm2``, ``1 A/m2`` or ``0.1 mA cm-2`` -> a quantity in mA/cm2,
    or ``None`` when the token is not a current per area."""
    m = _NUM_ANY_UNIT_RE.match(token)
    unit = _current_density_unit(m.group(2)) if m else None
    if m is None or unit is None:
        return None
    return Quantity(value=float(_to_fraction(m.group(1), text) * unit[1]), unit=_CURRENT_DENSITY_UNIT)


def _parse_value(text: str) -> tuple[str, Quantity]:
    """Parse a magnitude token such as ``C/10``, ``1C``, ``200 mA``,
    ``0.1 mA/cm2`` or ``4.1 V``.

    Returns ``(quantity_kind, Quantity)`` with the value normalised to the
    canonical unit (A, V, W, Ohm; C-rate as A/Ah; current density as mA/cm2).
    Prefixes are case-sensitive: ``1 MA`` is a megaampere, ``1 mA`` a
    milliampere, and a prefix the grammar does not read raises."""
    token = text.strip()
    div = _CRATE_DIV_RE.match(token)
    if div:
        denom = _to_float(div.group(2), text)
        if denom == 0:
            raise ExperimentSyntaxError(f"C-rate divisor cannot be zero: '{text}'.")
        return "c_rate", Quantity(value=1.0 / denom, unit="A/Ah")
    m = _NUM_UNIT_RE.match(token)
    if not m:
        density = _parse_current_density(token, text)
        if density is not None:
            return "current_density", density
        raise ExperimentSyntaxError(
            f"Could not parse value '{text}'. Expected e.g. 'C/10', '1C', '200 mA', '0.1 mA/cm2', '4.1 V'."
        )
    kind, canon_unit, factor = _unit_factor(m.group(2), text)
    return kind, Quantity(value=float(_to_fraction(m.group(1), text) * factor), unit=canon_unit)


def _parse_duration(text: str) -> Quantity:
    """Parse the body of a ``for <n> <time-unit>`` clause to seconds."""
    m = _TIME_RE.match(text.strip())
    if not m or m.group(2).lower() not in _TIME_TABLE:
        raise ExperimentSyntaxError(
            f"Could not parse duration '{text}'. Expected e.g. '30 minutes', '1 hour', '90 seconds'."
        )
    return Quantity(value=_to_float(m.group(1), text) * _TIME_TABLE[m.group(2).lower()], unit="s")


def _require_value(qty: Quantity, context: str) -> float:
    """Step-syntax quantities are always single-valued; min/max windows have no
    meaning inside a parsed step, so reject them with a parse-level error."""
    if qty.value is None:
        raise ExperimentSyntaxError(f"{context} requires a single value, not a min/max window.")
    return qty.value


def _termination_from_value(kind: str, qty: Quantity, direction: str | None) -> Termination:
    """Map a parsed ``until`` value to a termination, inferring approach direction
    from the step's charge/discharge sense when not otherwise determined."""
    if kind == "voltage":
        return Termination(
            quantity="voltage",
            value=_require_value(qty, "A voltage termination"),
            unit=qty.unit,
            direction="above" if direction == "charge" else "below",
        )
    if kind in ("current", "c_rate", "current_density"):
        # Cutoff currents are crossed from above as the cell relaxes/charges taper.
        # A current density is stored as a current cutoff in mA/cm2; the
        # emitters type it as a current-density limit.
        return Termination(
            quantity="current" if kind == "current_density" else kind,
            value=_require_value(qty, "A current termination"),
            unit=qty.unit,
            direction="below",
        )
    raise ExperimentSyntaxError(f"Unsupported termination quantity '{kind}'.")


# ── Step parsing ──────────────────────────────────────────────────────────────

_OP_RE = re.compile(r"^(charge|discharge|hold|rest)\b", re.IGNORECASE)
_AT_RE = re.compile(r"^at\s+", re.IGNORECASE)
_KW_BOUNDARY_RE = re.compile(r"\s+(?:for|until|or)\s+", re.IGNORECASE)
_OR_SPLIT_RE = re.compile(r"\s+or\s+", re.IGNORECASE)

# op + value-kind -> (mode, direction)
_MODE_FOR = {
    ("charge", "current"): ("cc", "charge"),
    ("charge", "current_density"): ("cc", "charge"),
    ("charge", "c_rate"): ("cc", "charge"),
    ("charge", "power"): ("cp", "charge"),
    ("charge", "resistance"): ("cr", "charge"),
    ("charge", "voltage"): ("cv", "charge"),
    ("discharge", "current"): ("cc", "discharge"),
    ("discharge", "current_density"): ("cc", "discharge"),
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
        raise ExperimentSyntaxError(f"Step must start with Charge, Discharge, Hold or Rest: '{text}'.")
    op = op_match.group(1).lower()
    remainder = raw[op_match.end() :].strip()

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
        after_at = remainder[at_match.end() :]
        boundary = _KW_BOUNDARY_RE.search(after_at)
        if boundary:
            value_str, tail = after_at[: boundary.start()], after_at[boundary.start() :]
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
            raise ExperimentSyntaxError(f"Unexpected clause '{clause}' in '{text}'. Expected 'for ...' or 'until ...'.")

    _refuse_foreign_current_units(terminations, text)
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


# Rendering writes every value in the unit it is stated in, so a current
# density stays a current density and a duration in hours stays in hours. A step
# that cannot be written faithfully renders as its description (or a neutral
# label), never as a wrong value.

# Units in which a C-rate value can be written in the C/n form.
_CRATE_UNITS = frozenset({"A/Ah", "C", "1/h", "h-1"})

# Unrolling a loop is bounded, so a corrupt repeat count cannot exhaust memory;
# past this many strings a loop renders as one "Repeat N times: (...)" line.
_MAX_RENDERED_STEPS = 100_000


def _fmt_number(value: float) -> str:
    """Up to 12 significant digits, never in exponent form (the grammar reads
    no exponents). Twelve digits keep every real setpoint and drop float noise
    from unit scaling elsewhere (an importer's 9 * 0.001 is 0.009000000000000001)."""
    text = format(value, ".12g")
    if "e" in text:
        text = format(Decimal(text), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _fmt_crate(value: float) -> str:
    if value >= 1.0 or value <= 0.0:
        return f"{_fmt_number(value)}C"
    inv = 1.0 / value
    rounded = round(inv)
    if rounded > 0 and abs(inv - rounded) < 1e-6:
        return f"C/{rounded}"
    return f"{_fmt_number(value)}C"


def _fmt_quantity(qty: Quantity) -> str:
    """A value with its unit as stated; a window renders as ``lo..hi unit``."""
    if qty.value is None:
        lo = _fmt_number(qty.min_value) if qty.min_value is not None else "?"
        hi = _fmt_number(qty.max_value) if qty.max_value is not None else "?"
        return f"{lo}..{hi} {qty.unit}"
    return f"{_fmt_number(qty.value)} {qty.unit}"


def _fmt_setpoint(kind: str, qty: Quantity) -> str:
    if kind == "c_rate" and qty.value is not None and qty.unit in _CRATE_UNITS:
        return _fmt_crate(qty.value)
    return _fmt_quantity(qty)


def _plural(value: float, word: str) -> str:
    return f"{_fmt_number(value)} {word}" + ("" if value == 1 else "s")


def _fmt_duration(qty: Quantity) -> str:
    if qty.value is None:
        return f"for {_fmt_quantity(qty)}"
    seconds_per_unit = _TIME_TABLE.get(qty.unit.strip().lower())
    if seconds_per_unit is None:
        return f"for {_fmt_quantity(qty)}"  # a unit the grammar has no word for
    if seconds_per_unit == 3600.0:
        return f"for {_plural(qty.value, 'hour')}"
    if seconds_per_unit == 60.0:
        return f"for {_plural(qty.value, 'minute')}"
    # Stated in seconds (the parser's canonical unit): the largest whole unit,
    # so "Rest for 30 minutes" reads back as written.
    seconds = qty.value
    if seconds and seconds % 3600 == 0:
        return f"for {_plural(seconds / 3600, 'hour')}"
    if seconds and seconds % 60 == 0:
        return f"for {_plural(seconds / 60, 'minute')}"
    return f"for {_plural(seconds, 'second')}"


def _fmt_termination(term: Termination) -> str:
    if term.quantity == "duration":
        return _fmt_duration(Quantity(value=term.value, unit=term.unit))
    if term.quantity == "c_rate" and term.unit in _CRATE_UNITS:
        return f"until {_fmt_crate(term.value)}"
    if term.quantity == "soc":
        # The unit alone ("1") would not say the cutoff is a state of charge.
        unit = "" if term.unit == "1" else f" {term.unit}"
        return f"until {_fmt_number(term.value)}{unit} SOC"
    return f"until {_fmt_number(term.value)} {term.unit}"


def _step_label(step: Step) -> str:
    """The fallback for a step the grammar cannot write: its description, or a
    neutral label that asserts nothing it does not know."""
    return step.description or (f"{step.direction} {step.mode}" if step.direction else step.mode)


def _step_head(step: Step) -> str | None:
    """The ``Charge at ...`` / ``Hold at ...`` / ``Rest`` part, or ``None`` when
    the step cannot be written faithfully in the grammar."""
    if step.mode == "rest":
        return "Rest"
    if step.mode == "cv":
        volt = step.setpoints.get("voltage")
        return f"Hold at {_fmt_quantity(volt)}" if volt is not None else "Hold"
    if step.mode not in ("cc", "cp", "cr", "cccv"):
        return None  # eis, scan: PyBaMM has no string form
    if step.direction not in ("charge", "discharge"):
        return None  # writing Charge or Discharge would be a guess
    word = "Charge" if step.direction == "charge" else "Discharge"
    if step.mode == "cccv":
        rate = next((k for k in step.setpoints if k != "voltage"), None)
        volt = step.setpoints.get("voltage")
        rate_str = f" at {_fmt_setpoint(rate, step.setpoints[rate])}" if rate else ""
        volt_str = f" to {_fmt_quantity(volt)} then hold" if volt is not None else ""
        return f"{word}{rate_str}{volt_str}"
    kind = next(iter(step.setpoints), None)
    return f"{word} at {_fmt_setpoint(kind, step.setpoints[kind])}" if kind else word


def _fmt_group(group: Step) -> str:
    """A loop as one line: ``Repeat 3 times: (step; step)``."""
    inner = "; ".join(render_step(s) for s in group.steps)
    if group.count is None:
        return group.description or f"Repeat (count not stated): ({inner})"
    times = "time" if group.count == 1 else "times"
    return f"Repeat {group.count} {times}: ({inner})"


def render_step(step: Step) -> str:
    """Render a single :class:`Step` to a PyBaMM-style string.

    Values keep the units they are stated in, so ``0.05 mA/cm2`` renders as
    ``0.05 mA/cm2`` and a 6 h rest as ``Rest for 6 hours``. The cc/cv/cp/cr/rest
    forms the parser produces read back to the same step. A step the grammar
    cannot express (eis, scan, a cc step with no charge or discharge direction)
    renders as its description or a neutral label rather than a wrong value, and
    a group renders as one ``Repeat N times: (...)`` line, so this never raises
    on a structured method."""
    if step.mode == "group":
        return _fmt_group(step)
    head = _step_head(step)
    if head is None:
        return _step_label(step)
    clauses: list[str] = []
    if step.duration is not None:
        clauses.append(_fmt_duration(step.duration))
    clauses.extend(_fmt_termination(t) for t in step.termination)
    return head + (" " + " or ".join(clauses) if clauses else "")


def _unrollable_count(group: Step) -> int | None:
    """The repeat count of a loop when it can be unrolled (a whole number of at
    least 1), otherwise ``None``."""
    return group.count if group.count is not None and group.count >= 1 else None


def _render_sequence(steps: Sequence[Step]) -> list[str]:
    """Render steps in order, unrolling each loop: its steps repeated ``count``
    times, the way ``pybamm.Experiment([...] * n)`` writes a repeat. A loop
    with no count, or one too large to unroll, stays one ``Repeat`` line."""
    out: list[str] = []
    for step in steps:
        if step.mode != "group":
            out.append(render_step(step))
            continue
        count = _unrollable_count(step)
        inner = _render_sequence(step.steps) if count else []
        if count and len(inner) * count <= _MAX_RENDERED_STEPS:
            out.extend(inner * count)
        else:
            out.append(render_step(step))
    return out


def render_method(steps: Sequence[Step]) -> tuple[list[str], int]:
    """Render a ``method`` back to ``(step_strings, cycles)``.

    A single top-level ``group`` with a count unwraps to ``(inner_strings,
    count)``, the grammar's own repeat form (``parse_experiment(strings,
    cycles)``). Every other loop is unrolled in place."""
    count = _unrollable_count(steps[0]) if len(steps) == 1 and steps[0].mode == "group" else None
    if count:
        return _render_sequence(steps[0].steps), count
    return _render_sequence(steps), 1


def render_experiment(steps: Sequence[Step]) -> list[str]:
    """The whole method as one flat list of PyBaMM-style strings, every loop
    unrolled, which is the list ``pybamm.Experiment`` takes."""
    return _render_sequence(steps)


# ── Facets (derived filter index) ──────────────────────────────────────────


def _iter_leaf_steps(steps: Sequence[Step]):
    for step in steps:
        if step.mode == "group":
            yield from _iter_leaf_steps(step.steps)
        else:
            yield step


_CONTROL_MODE = {"cc": "current", "cv": "voltage", "cccv": "current", "cp": "power", "cr": "resistance"}


def compute_facets(steps: Sequence[Step], conditions: dict[str, Quantity] | None = None) -> dict[str, Any]:
    """Derive a flat, queryable rollup of a method for cheap agent filtering.

    ``modes`` lists leaf-step modes in first-encounter order; ``group`` is
    structure, not a mode, and never appears (a cycling protocol wrapped in a
    repeat group must facet as its cc/cv/rest content, or every ``modes``
    filter misses it — #361). Group nesting stays visible in the method graph
    and the ``has_*`` flags.
    """
    modes: list[str] = []
    directions: set[str] = set()
    control_modes: set[str] = set()
    c_rates: list[float] = []
    voltages: list[float] = []
    temperatures: list[float] = []
    tags: set[str] = set()

    for step in _iter_leaf_steps(steps):
        if step.mode not in modes:
            modes.append(step.mode)
    for step in _iter_leaf_steps(steps):
        if step.direction and step.direction not in ("rest", "hold"):
            directions.add(step.direction)
        if step.mode in _CONTROL_MODE:
            control_modes.add(_CONTROL_MODE[step.mode])
        for key, qty in step.setpoints.items():
            values = [v for v in (qty.value, qty.min_value, qty.max_value) if v is not None]
            if key == "c_rate":
                c_rates.extend(values)
            elif key == "voltage":
                voltages.extend(values)
        for term in step.termination:
            if term.quantity == "voltage":
                voltages.append(term.value)
            elif term.quantity == "c_rate":
                c_rates.append(term.value)
        if step.temperature is not None and step.temperature.value is not None:
            temperatures.append(step.temperature.value)
        tags.update(step.tags)

    for key, qty in (conditions or {}).items():
        if key in ("temperature", "ambient_temperature", "room_temperature"):
            temperatures.extend(v for v in (qty.value, qty.min_value, qty.max_value) if v is not None)

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
