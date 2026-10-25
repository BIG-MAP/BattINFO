from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from importlib import resources
from typing import Any, Mapping

from battinfo._util import is_dataset_series
from battinfo.canonical_aliases import record_to_snake_aliases
from battinfo.entities import kind_for_doc
from battinfo.namespace import RecordIri, parse_record_iri, record_base, record_iri
from battinfo.naming import is_valid_handle, kind_word
from battinfo.validate.core import (
    DEFAULT_POLICY,
    ValidationIssue,
    ValidationPolicy,
    ValidationReport,
    ValidationResult,
    get_validation_policy,
)

# Units each spec property accepts, as canonical symbols: the spelling the curated
# unit map uses, which normalize_unit_symbol makes of accepted alternatives such as
# 'um', 'mOhm', 'degC' or 'g/cm³'. Symbols are case-sensitive, because case can change
# magnitude: 'mV' is a millivolt and 'MV' a megavolt. The first symbol of each entry
# is the example the CLI and validation hints show. All symbols of one property have
# the same dimension, and every cell-spec property has an entry
# (tests/test_spec_units.py checks both).
SPEC_UNIT_COMPATIBILITY: dict[str, tuple[str, ...]] = {
    # Material properties (material-spec / material `property` map)
    "specific_capacity": ("mAh/g", "Ah/kg"),
    "specific_discharge_capacity": ("mAh/g", "Ah/kg"),
    "first_cycle_efficiency": ("%",),
    "true_density": ("g/cm3", "kg/m3"),
    "tap_density": ("g/cm3", "kg/m3"),
    "density": ("g/cm3", "kg/m3"),
    "bet_surface_area": ("m2/g",),
    "particle_size_d10": ("µm", "nm"),
    "particle_size_d50": ("µm", "nm"),
    "particle_size_d90": ("µm", "nm"),
    "average_voltage": ("V", "mV"),
    "molar_mass": ("g/mol", "kg/mol"),
    "discharging_capacity": ("Ah", "mAh"),
    "charging_capacity": ("Ah", "mAh"),
    "nominal_capacity": ("Ah", "mAh"),
    "minimum_capacity": ("Ah", "mAh"),
    "min_capacity": ("Ah", "mAh"),
    "rated_capacity": ("Ah", "mAh"),
    "typical_capacity": ("Ah", "mAh"),
    "discharging_energy": ("Wh", "kWh", "mWh"),
    "charging_energy": ("Wh", "kWh", "mWh"),
    "typical_energy": ("Wh", "kWh", "mWh"),
    "rated_energy": ("Wh", "kWh", "mWh"),
    "nominal_energy": ("Wh", "kWh", "mWh"),
    "certified_usable_energy": ("Wh", "kWh", "mWh"),
    "nominal_voltage": ("V", "mV"),
    "charging_voltage": ("V", "mV"),
    "charging_cutoff_voltage": ("V", "mV"),
    "discharging_cutoff_voltage": ("V", "mV"),
    "upper_voltage_limit": ("V", "mV"),
    "specific_energy": ("Wh/kg",),
    "energy_density": ("Wh/L",),
    "specific_power": ("W/kg", "mW/g"),
    "power_density": ("W/L",),
    "internal_resistance": ("mΩ", "Ω"),
    "impedance": ("mΩ", "Ω"),
    "dc_internal_resistance": ("mΩ", "Ω"),
    "ac_internal_resistance": ("mΩ", "Ω"),
    "mass": ("g", "kg", "mg"),
    "volume": ("L", "mL", "cm3", "mm3"),
    "electrode_area": ("cm2", "m2", "mm2"),
    "external_surface_area": ("cm2", "m2", "mm2"),
    # Currents only. A C-rate has the dimension 1/time, so 'C' is refused here, with a
    # hint that names the charging_c_rate or discharging_c_rate condition key.
    "pulse_charging_current": ("A", "mA"),
    "continuous_charging_current": ("A", "mA"),
    "nominal_continuous_charging_current": ("A", "mA"),
    "maximum_continuous_charging_current": ("A", "mA"),
    "maximum_pulse_charging_current": ("A", "mA"),
    "pulse_discharging_current": ("A", "mA"),
    "continuous_discharging_current": ("A", "mA"),
    "nominal_continuous_discharging_current": ("A", "mA"),
    "maximum_continuous_discharging_current": ("A", "mA"),
    "maximum_pulse_discharging_current": ("A", "mA"),
    "charging_time": ("h", "min", "s"),
    # 'count' and '1' are both EMMO's UnitOne; 'cycles' is accepted as a spelling of 'count'.
    "cycle_life": ("count", "1"),
    "cycle_life_c_rate": ("A/Ah",),
    # 'days' is accepted as a spelling of 'day', the one of these with an EMMO unit.
    "calendar_life": ("year", "years", "month", "months", "day"),
    "capacity_fade": ("%",),
    "capacity_threshold_exhaustion": ("%",),
    "power_capability": ("W", "kW", "mW"),
    "maximum_power": ("W", "kW", "mW"),
    "power_energy_ratio": ("W/Wh", "kW/kWh"),
    "round_trip_energy_efficiency": ("%",),
    "round_trip_energy_efficiency_50pct": ("%",),
    "initial_coulombic_efficiency": ("%",),
    "state_of_health": ("%",),
    # A rate: the share of capacity lost per unit of time. A bare '%' has no time base
    # and is refused.
    "self_discharge_rate": ("%/month", "%/week", "%/day", "%/year", "%/h", "%/hour"),
    "diameter": ("mm", "cm", "m", "µm"),
    "height": ("mm", "cm", "m", "µm"),
    "width": ("mm", "cm", "m", "µm"),
    "length": ("mm", "cm", "m", "µm"),
    "thickness": ("mm", "cm", "m", "µm"),
    "minimum_charging_temperature": ("°C", "K"),
    "maximum_charging_temperature": ("°C", "K"),
    "charging_temperature_min": ("°C", "K"),
    "charging_temperature_max": ("°C", "K"),
    "minimum_discharging_temperature": ("°C", "K"),
    "maximum_discharging_temperature": ("°C", "K"),
    "discharging_temperature_min": ("°C", "K"),
    "discharging_temperature_max": ("°C", "K"),
    "minimum_storage_temperature": ("°C", "K"),
    "maximum_storage_temperature": ("°C", "K"),
    "storage_temperature_min": ("°C", "K"),
    "storage_temperature_max": ("°C", "K"),
    "operating_temperature_min": ("°C", "K"),
    "operating_temperature_max": ("°C", "K"),
}

# Spellings normalize_unit_symbol leaves as they are, with the symbols they stand for.
# A spelling is accepted on a property that allows one of those symbols, and the
# unit_unmapped warning names that symbol, which is the one the unit map knows.
_UNIT_SPELLINGS: dict[str, tuple[str, ...]] = {
    # Degree Celsius on a temperature; a C-rate on cycle_life_c_rate. A current
    # allows neither, so 'C' on a current is refused.
    "C": ("°C", "A/Ah"),
    "cycle": ("count",),
    "cycles": ("count",),
    "days": ("day",),
    "Wh/lt": ("Wh/L",),
    "Wh/liter": ("Wh/L",),
    "W/lt": ("W/L",),
    "W/liter": ("W/L",),
}

# Units of a C-rate (dimension 1/time), compared without case. On a current they get
# a hint that names the C-rate condition key instead of a bare mismatch.
_C_RATE_UNITS = frozenset({"c", "a/ah", "1/h", "h-1"})

# Units an SI prefix letter can stand before, compared without case. A case variant
# that turns the prefix 'm' (milli) into 'M' (mega), or the reverse, in front of one
# of these changes the value a billionfold ('MV' for 'mV'); in 'min', 'mol' or
# 'month' the 'm' is no prefix.
_PREFIXABLE_UNITS = frozenset(
    {"a", "ah", "v", "w", "wh", "ω", "ohm", "ohms", "m", "m2", "m3", "g", "l", "s", "pa", "j", "hz"}
)
_UNIT_FACTOR_SPLIT = re.compile(r"[/.·*()]")

PAIRED_SPEC_RANGES: tuple[tuple[str, str], ...] = (
    ("minimum_charging_temperature", "maximum_charging_temperature"),
    ("charging_temperature_min", "charging_temperature_max"),
    ("minimum_discharging_temperature", "maximum_discharging_temperature"),
    ("discharging_temperature_min", "discharging_temperature_max"),
    ("minimum_storage_temperature", "maximum_storage_temperature"),
    ("storage_temperature_min", "storage_temperature_max"),
    ("minimum_capacity", "nominal_capacity"),
    ("min_capacity", "nominal_capacity"),
)

# Plausibility bounds: (min_inclusive, max_inclusive) per (spec_name, canonical unit symbol).
# These are loose sanity checks — clearly-impossible values only — not chemistry-specific.
# All comparisons use the numeric value as-is in the stated unit (no conversion).
SPEC_PLAUSIBILITY_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    # Material properties — loose sanity bounds catching decimal/units typos
    # (1 Ah/kg is 1 mAh/g, so the two specific-capacity units share one bound).
    "specific_capacity": {"mAh/g": (0.0, 4000.0), "Ah/kg": (0.0, 4000.0)},
    "specific_discharge_capacity": {"mAh/g": (0.0, 4000.0), "Ah/kg": (0.0, 4000.0)},
    "first_cycle_efficiency": {"%": (0.0, 100.0)},
    "true_density": {"g/cm3": (0.1, 25.0), "kg/m3": (100.0, 25000.0)},
    "tap_density": {"g/cm3": (0.1, 25.0), "kg/m3": (100.0, 25000.0)},
    "density": {"g/cm3": (0.1, 25.0), "kg/m3": (100.0, 25000.0)},
    "bet_surface_area": {"m2/g": (0.0, 5000.0)},
    "particle_size_d10": {"µm": (0.001, 1000.0), "nm": (1.0, 1_000_000.0)},
    "particle_size_d50": {"µm": (0.001, 1000.0), "nm": (1.0, 1_000_000.0)},
    "particle_size_d90": {"µm": (0.001, 1000.0), "nm": (1.0, 1_000_000.0)},
    "average_voltage": {"V": (0.0, 6.0), "mV": (0.0, 6000.0)},
    "molar_mass": {"g/mol": (1.0, 2_000_000.0), "kg/mol": (0.001, 2000.0)},
    # Voltages — catches decimal-shift errors (e.g. 35 V instead of 3.5 V)
    "nominal_voltage": {"V": (0.3, 5.5), "mV": (300.0, 5500.0)},
    "charging_voltage": {"V": (0.3, 6.0), "mV": (300.0, 6000.0)},
    "discharging_cutoff_voltage": {"V": (0.0, 5.0), "mV": (0.0, 5000.0)},
    "charging_cutoff_voltage": {"V": (1.0, 6.0)},
    "upper_voltage_limit": {"V": (1.0, 6.0)},
    # Capacity — catches Ah/mAh confusion and orders-of-magnitude typos
    "discharging_capacity": {"Ah": (1e-4, 2000.0), "mAh": (0.1, 2_000_000.0)},
    "charging_capacity": {"Ah": (1e-4, 2000.0), "mAh": (0.1, 2_000_000.0)},
    "nominal_capacity": {"Ah": (1e-4, 2000.0), "mAh": (0.1, 2_000_000.0)},
    "minimum_capacity": {"Ah": (1e-4, 2000.0), "mAh": (0.1, 2_000_000.0)},
    "min_capacity": {"Ah": (1e-4, 2000.0), "mAh": (0.1, 2_000_000.0)},
    "rated_capacity": {"Ah": (1e-4, 2000.0), "mAh": (0.1, 2_000_000.0)},
    "typical_capacity": {"Ah": (1e-4, 2000.0), "mAh": (0.1, 2_000_000.0)},
    # Energy
    "discharging_energy": {"Wh": (1e-4, 200_000.0), "kWh": (1e-7, 200.0)},
    "charging_energy": {"Wh": (1e-4, 200_000.0), "kWh": (1e-7, 200.0)},
    "nominal_energy": {"Wh": (1e-4, 200_000.0), "kWh": (1e-7, 200.0)},
    "typical_energy": {"Wh": (1e-4, 200_000.0), "kWh": (1e-7, 200.0)},
    "rated_energy": {"Wh": (1e-4, 200_000.0), "kWh": (1e-7, 200.0)},
    "certified_usable_energy": {"Wh": (1e-4, 200_000.0), "kWh": (1e-7, 200.0)},
    # Specific energy / energy density — bounded by known cell chemistry physics
    "specific_energy": {"Wh/kg": (1.0, 1000.0)},
    "energy_density": {"Wh/L": (1.0, 2500.0)},
    # Physical dimensions — single-cell bounds
    "mass": {"g": (0.05, 70_000.0), "kg": (5e-5, 70.0)},
    "diameter": {"mm": (0.5, 500.0)},
    "height": {"mm": (0.3, 2000.0)},
    "width": {"mm": (0.3, 2000.0)},
    "length": {"mm": (0.3, 2000.0)},
    "thickness": {"mm": (0.05, 200.0)},
    # Cycle life — catches 10x typos (100000 cycles instead of 10000)
    "cycle_life": {"count": (1, 100_000), "1": (1, 100_000)},
    # Efficiency / fade — must be a percentage
    "round_trip_energy_efficiency": {"%": (0.0, 100.0)},
    "round_trip_energy_efficiency_50pct": {"%": (0.0, 100.0)},
    "capacity_fade": {"%": (0.0, 100.0)},
    "capacity_threshold_exhaustion": {"%": (0.0, 100.0)},
    "initial_coulombic_efficiency": {"%": (0.0, 100.0)},
    "state_of_health": {"%": (0.0, 100.0)},
}

CELL_IRI_PREFIX = record_base() + "cell/"
CELL_TYPE_IRI_PREFIX = record_base() + "spec/"  # cell specs use the spec/ namespace
# A material dataset (powder XRD, say) is about a material lot or its material
# spec rather than a cell; material specs share the spec/ namespace.
MATERIAL_IRI_PREFIX = record_base() + "material/"

INTERNAL_IDENTIFIER_PREFIX: dict[str, tuple[str, ...]] = {
    "cell-spec": ("cell_spec", "cell_spec"),
    "cell": ("cell_instance",),
    "test": ("test",),
    "dataset": ("dataset",),
}

SIZE_CODE_PATTERN = re.compile(r"^[RP][A-Za-z0-9]+(?:[/-][A-Za-z0-9]+)*$")


def _load_mapping_json(*parts: str) -> dict[str, Any]:
    path = resources.files("battinfo")
    for part in ("data", "mappings", "domain-battery", *parts):
        path = path.joinpath(part)  # single-arg joinpath: multi-arg is Python 3.11+
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def _controlled_value_map() -> dict[str, set[str]]:
    raw = _load_mapping_json("entity_type_map.json")
    mappings = raw.get("mappings", {})
    out: dict[str, set[str]] = {}
    for key in ("format", "chemistry", "positive_electrode_basis", "negative_electrode_basis"):
        values = mappings.get(key, {})
        if isinstance(values, Mapping):
            out[key] = {str(name).strip().lower() for name in values.keys()}
        else:
            out[key] = set()
    return out


@lru_cache(maxsize=1)
def _controlled_value_aliases() -> dict[str, dict[str, tuple[str, str]]]:
    """Older spellings that still resolve: ``{field: {alias: (use_instead, why)}}``."""
    mappings = _load_mapping_json("entity_type_map.json").get("mappings", {})
    out: dict[str, dict[str, tuple[str, str]]] = {}
    for key, values in mappings.items():
        if not isinstance(values, Mapping):
            continue
        for name, entry in values.items():
            if isinstance(entry, Mapping) and isinstance(entry.get("alias_of"), str):
                out.setdefault(key, {})[str(name).strip().lower()] = (
                    entry["alias_of"],
                    str(entry.get("note") or ""),
                )
    return out


def _entity_from_doc(doc: dict[str, Any]) -> tuple[str, Mapping[str, Any]] | None:
    for resource_type, keys in INTERNAL_IDENTIFIER_PREFIX.items():
        for key in keys:
            value = doc.get(key)
            if isinstance(value, Mapping):
                return resource_type, value
    return None


def _iri_uid(entity_id: str) -> str | None:
    parts = entity_id.rstrip("/").split("/")
    if len(parts) < 2:
        return None
    return parts[-1]


def _short_uid(entity_id: str) -> str | None:
    uid = _iri_uid(entity_id)
    if uid is None:
        return None
    return uid.replace("-", "")[:6]


def _numeric_spec_value(item: Mapping[str, Any]) -> float | None:
    value = item.get("value")
    if isinstance(value, (int, float)):
        return float(value)
    for key in ("typical_value", "max_value", "min_value"):
        candidate = item.get(key)
        if isinstance(candidate, (int, float)):
            return float(candidate)
    return None


def _unit_token(item: Mapping[str, Any]) -> str | None:
    """The unit a quantity states, trimmed. Case is kept: 'mV' and 'MV' differ a billionfold."""
    for key in ("unit", "unit_text", "unit_code"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _unit_forms(unit: str) -> list[str]:
    """The unit as the JSON-LD emitter reads it, then the same without spaces ('W h' is 'Wh')."""
    from battinfo.transform.json_to_jsonld import normalize_unit_symbol  # noqa: PLC0415

    forms: list[str] = []
    for candidate in (unit, unit.replace(" ", "")):
        symbol = normalize_unit_symbol(candidate)
        if symbol and symbol not in forms:
            forms.append(symbol)
    return forms


def _casefold_index(pairs: list[tuple[str, str]]) -> dict[str, tuple[str, str] | None]:
    """``{spelling.casefold(): (spelling, symbol)}``; None where two symbols share a key."""
    index: dict[str, tuple[str, str] | None] = {}
    for spelling, symbol in pairs:
        key = spelling.casefold()
        if key not in index:
            index[key] = (spelling, symbol)
            continue
        known = index[key]
        if known is not None and known[1] != symbol:
            index[key] = None
    return index


@lru_cache(maxsize=None)
def _spellings_by_casefold(allowed: tuple[str, ...]) -> dict[str, tuple[str, str] | None]:
    """Each spelling of the allowed symbols, keyed without case: the symbols themselves,
    the aliases normalize_unit_symbol turns into them, and the entries of _UNIT_SPELLINGS."""
    from battinfo.transform.json_to_jsonld import _UNIT_ALIASES  # noqa: PLC0415

    pairs = [(symbol, symbol) for symbol in allowed]
    pairs += [(alias, symbol) for alias, symbol in _UNIT_ALIASES.items() if symbol in allowed]
    pairs += [
        (spelling, target) for spelling, targets in _UNIT_SPELLINGS.items() for target in targets if target in allowed
    ]
    return _casefold_index(pairs)


@lru_cache(maxsize=1)
def _unit_map_by_casefold() -> dict[str, tuple[str, str] | None]:
    """Each symbol of the unit map and each alias of one, keyed without case."""
    from battinfo.transform.json_to_jsonld import _UNIT_ALIASES, _unit_type_map, normalize_unit_symbol  # noqa: PLC0415

    pairs = [(symbol, normalize_unit_symbol(symbol) or symbol) for symbol in _unit_type_map()]
    pairs += list(_UNIT_ALIASES.items())
    return _casefold_index(pairs)


def _turns_milli_into_mega(written: str, spelling: str) -> bool:
    """Whether ``spelling`` reads the SI prefix 'm' (milli) of ``written`` as 'M' (mega)
    in front of a unit: 'MPa' for 'mPa'."""
    for got, want in zip(_UNIT_FACTOR_SPLIT.split(written), _UNIT_FACTOR_SPLIT.split(spelling)):
        if (
            len(got) > 1
            and len(want) > 1
            and (got[0], want[0]) == ("m", "M")
            and want[1:].casefold() in _PREFIXABLE_UNITS
        ):
            return True
    return False


def _swaps_milli_and_mega(written: str, spelling: str) -> bool:
    """Whether ``written`` reads the SI prefix 'm' (milli) of ``spelling`` as 'M' (mega),
    or the reverse, in front of a unit: 'MV' for 'mV', 'MAh/g' for 'mAh/g'."""
    return _turns_milli_into_mega(written, spelling) or _turns_milli_into_mega(spelling, written)


def _match_spec_unit(unit: str, allowed: tuple[str, ...]) -> tuple[str, str] | None:
    """The allowed symbol a written unit stands for, and how it was written.

    The second item is 'symbol' (the symbol, or a spelling normalize_unit_symbol turns
    into it, such as 'um' or 'degC'), 'spelling' (an entry of _UNIT_SPELLINGS, such as
    'cycles'), 'case' (another case that keeps the magnitude, such as 'ah') or
    'magnitude' (another case that swaps milli and mega, such as 'MV' for 'mV').
    None means the unit stands for none of the allowed symbols.
    """
    forms = _unit_forms(unit)
    for form in forms:
        if form in allowed:
            return form, "symbol"
    for form in forms:
        for target in _UNIT_SPELLINGS.get(form, ()):
            if target in allowed:
                return target, "spelling"
    index = _spellings_by_casefold(allowed)
    for form in (unit, *forms):
        hit = index.get(form.casefold())
        if hit is not None:
            spelling, symbol = hit
            return symbol, "magnitude" if _swaps_milli_and_mega(form, spelling) else "case"
    return None


def _changes_a_one_letter_symbol(written: str, spelling: str) -> bool:
    """Whether ``spelling`` changes the case of a one-letter factor of ``written``.

    Case alone tells such symbols apart: 'M' (molar) and 'm' (metre), 'S' (siemens)
    and 's' (second).
    """
    for got, want in zip(_UNIT_FACTOR_SPLIT.split(written), _UNIT_FACTOR_SPLIT.split(spelling)):
        if len(got) == 1 and got != want:
            return True
    return False


def _unit_map_match(unit: str) -> str | None:
    """The unit-map symbol ``unit`` matches once case is ignored, when exactly one does.

    A match that could change what the unit means is never offered: one that swaps
    the prefixes milli and mega in either direction ('mPa' does not get 'MPa', a
    billion times more, nor 'MΩ' get 'mΩ'), or that changes the case of a one-letter
    symbol ('M' does not get 'm', nor 'S' get 's').
    """
    from battinfo.transform.json_to_jsonld import _unit_iri  # noqa: PLC0415

    for form in (unit, *_unit_forms(unit)):
        hit = _unit_map_by_casefold().get(form.casefold())
        if (
            hit is not None
            and _unit_iri(hit[1]) is not None
            and not _swaps_milli_and_mega(form, hit[0])
            and not _changes_a_one_letter_symbol(form, hit[0])
        ):
            return hit[1]
    return None


def _unit_mismatch_message(spec_name: str, unit: str, allowed: tuple[str, ...], match: tuple[str, str] | None) -> str:
    """Why ``unit`` is refused on ``spec_name``, with the fix where one is known."""
    valid = ", ".join(allowed)
    if match is not None:  # a case variant that swaps the prefixes milli and mega
        return (
            f"unit '{unit}' is not compatible with spec '{spec_name}': unit symbols are case-sensitive, and the "
            f"prefix 'M' (mega) is 10^9 times 'm' (milli). Did you mean '{match[0]}'? (valid: {valid})"
        )
    forms = {form.casefold() for form in _unit_forms(unit)}
    if spec_name.endswith("_current") and forms & _C_RATE_UNITS:
        rate_key = "discharging_c_rate" if "discharging" in spec_name else "charging_c_rate"
        return (
            f"unit '{unit}' is not compatible with spec '{spec_name}' (valid: {valid}): '{unit}' gives a C-rate, "
            "not a current. Give the current in A, which is the C-rate times the nominal capacity in Ah, or "
            f"state the C-rate as '{rate_key}' in the conditions of the value it applies to."
        )
    if spec_name == "self_discharge_rate" and "%" in forms:
        return (
            f"unit '{unit}' is not compatible with spec 'self_discharge_rate' (valid: {valid}): a self-discharge "
            "rate is the share of capacity lost per unit of time, so give the time base, as in '%/month'."
        )
    return f"unit '{unit}' is not compatible with spec '{spec_name}' (valid: {valid})."


def _warn_unit_unmapped(
    unit: str,
    symbol: str | None,
    path: str,
    issues: list[ValidationIssue],
    resource_type: str | None,
) -> None:
    """Warn semantic.unit_unmapped, under every policy, when ``unit`` gets no EMMO unit IRI.

    The JSON-LD export then writes the unit as text (schema:unitText) only. ``symbol``
    is the accepted symbol the unit stands for, when the property has a unit check;
    the warning names it when the unit is spelled another way ('ah' for 'Ah'). For a
    property without a unit check it offers the unit-map symbol that matches once case
    is ignored, unless that could change what the unit means (see ``_unit_map_match``).
    """
    from battinfo.transform.json_to_jsonld import _unit_iri, normalize_unit_symbol  # noqa: PLC0415

    if _unit_iri(unit) is not None:
        return
    text_only = f"'{unit}' gets no EMMO unit IRI, so the JSON-LD export keeps it as text (schema:unitText) only."
    file_mapping = "file a mapping in assets/mappings/domain-battery/unit_map.curated.json."
    if symbol is not None and symbol != normalize_unit_symbol(unit):
        if _unit_iri(symbol) is not None:
            message = f"write '{symbol}'; {text_only}"
        else:
            message = f"{text_only} Write it '{symbol}', and {file_mapping}"
    else:
        guess = _unit_map_match(unit) if symbol is None else None
        message = f"did you mean '{guess}'? {text_only}" if guess else f"{text_only} To give it one, {file_mapping}"
    _append_issue(
        issues,
        code="semantic.unit_unmapped",
        severity="warning",
        path=path,
        message=message,
        resource_type=resource_type,
    )


def _check_spec_unit(
    spec_name: str,
    unit: str,
    path: str,
    issues: list[ValidationIssue],
    resource_type: str | None,
    issue_severity: str,
) -> str | None:
    """Check the unit of one property; return the symbol it stands for, or None when refused.

    A unit of another dimension, or a case variant that swaps the prefixes milli and
    mega ('MV' for 'mV'), is semantic.unit_mismatch, an error under strict. A unit the
    property accepts but that gets no EMMO unit IRI is the semantic.unit_unmapped
    warning, as is any unit without one on a property that has no unit check.
    """
    allowed = SPEC_UNIT_COMPATIBILITY.get(spec_name)
    if allowed is None:
        _warn_unit_unmapped(unit, None, path, issues, resource_type)
        forms = _unit_forms(unit)
        return forms[0] if forms else None
    match = _match_spec_unit(unit, allowed)
    if match is None or match[1] == "magnitude":
        _append_issue(
            issues,
            code="semantic.unit_mismatch",
            severity=issue_severity,
            path=path,
            message=_unit_mismatch_message(spec_name, unit, allowed, match),
            resource_type=resource_type,
        )
        return None
    _warn_unit_unmapped(unit, match[0], path, issues, resource_type)
    return match[0]


def _append_issue(
    issues: list[ValidationIssue],
    *,
    code: str,
    severity: str,
    path: str,
    message: str,
    resource_type: str | None,
) -> None:
    issues.append(
        ValidationIssue(
            code=code,
            severity=severity,  # type: ignore[arg-type]
            path=path,
            message=message,
            validator="semantic",
            resource_type=resource_type,
        )
    )


def _validate_identifier_consistency(
    doc: dict[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    issue_severity: str,
) -> None:
    entity = _entity_from_doc(doc)
    if entity is None:
        return
    entity_type, record = entity
    entity_id = record.get("id")
    if not isinstance(entity_id, str):
        return
    expected_short = _short_uid(entity_id)
    short_id = record.get("short_id")
    if expected_short and isinstance(short_id, str) and short_id != expected_short:
        _append_issue(
            issues,
            code="semantic.short_id_mismatch",
            severity=issue_severity,
            path=f"{entity_type}.short_id",
            message=f"short_id '{short_id}' must match the first 6 undashed UID characters '{expected_short}'.",
            resource_type=resource_type,
        )
    identifier = record.get("identifier")
    expected_uid = _iri_uid(entity_id)
    expected_prefix = f"{entity_type}:"
    if isinstance(identifier, str) and identifier.startswith(expected_prefix) and expected_uid is not None:
        actual_uid = identifier.split(":", 1)[1]
        if actual_uid != expected_uid:
            _append_issue(
                issues,
                code="semantic.identifier_uid_mismatch",
                severity=issue_severity,
                path=f"{entity_type}.identifier",
                message=f"identifier '{identifier}' must use UID '{expected_uid}' to match id '{entity_id}'.",
                resource_type=resource_type,
            )


def _validate_handle_kind_word(doc: dict[str, Any], issues: list[ValidationIssue]) -> None:
    """Nudge a handle toward the naming convention: it ends with its kind word.

    Always a warning, never an error, under every policy: the grammar itself is
    enforced by the schema pattern, and a handle that breaks only the layout
    convention is still a usable handle. A collection (a dataset series) and an
    organization are the roots their records are grouped under (a collection's
    members, a manufacturer's products) and carry no kind word, so they are not
    checked.
    """
    kind = kind_for_doc(doc)
    if kind is None:
        return
    body = doc.get(kind.record_key)
    if not isinstance(body, Mapping):
        return
    handle = body.get("handle")
    if not is_valid_handle(handle):
        return  # absent, or a schema error already
    if kind.entity_type == "dataset" and is_dataset_series(body.get("additional_type")):
        return
    if kind.entity_type == "organization":
        return
    expected = kind_word(kind.entity_type)
    last_segment = str(handle).rsplit("/", 1)[-1]
    if expected is None or last_segment == expected or last_segment.endswith(f"-{expected}"):
        return
    _append_issue(
        issues,
        code="semantic.handle_kind_word_expected",
        severity="warning",
        path=f"{kind.record_key}.handle",
        message=(
            f"handle '{handle}' should end with '{expected}', the kind word for a "
            f"{kind.entity_type} record (e.g. '<group>/<subject>-{expected}'). "
            "battinfo.naming.handle_for() builds handles that follow the convention."
        ),
        resource_type=kind.entity_type,
    )


def _validate_schema_version(doc: dict[str, Any], issues: list[ValidationIssue]) -> None:
    """Warn when a record's ``schema_version`` is not the one this release writes.

    The JSON Schema checks only the form (``1.2.3``). A version an earlier
    release wrote still reads, and is flagged as superseded; any other version,
    a newer one included, may use fields this release reads differently or not
    at all. Always a warning, never an error, under every policy.
    """
    from battinfo.bundle import SCHEMA_VERSION, SUPERSEDED_SCHEMA_VERSIONS  # noqa: PLC0415

    kind = kind_for_doc(doc)
    version = doc.get("schema_version")
    if kind is None or not isinstance(version, str) or not version.strip() or version == SCHEMA_VERSION:
        return
    if version in SUPERSEDED_SCHEMA_VERSIONS:
        code = "semantic.schema_version_superseded"
        message = (
            f"schema_version '{version}' was written by an earlier BattINFO release. It still reads; "
            f"records written now carry '{SCHEMA_VERSION}'."
        )
    else:
        known = ", ".join(f"'{v}'" for v in (SCHEMA_VERSION, *SUPERSEDED_SCHEMA_VERSIONS))
        code = "semantic.schema_version_unknown"
        message = (
            f"schema_version '{version}' is not a record version this BattINFO release knows ({known}); "
            "its fields may be read differently or not at all."
        )
    _append_issue(
        issues,
        code=code,
        severity="warning",
        path="schema_version",
        message=message,
        resource_type=kind.entity_type,
    )


def _validate_controlled_values(
    doc: dict[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
) -> None:
    product = doc.get("cell_spec")
    if not isinstance(product, Mapping):
        return
    value_map = _controlled_value_map()
    field_map = {
        "cell_format": "format",
        "chemistry": "chemistry",
        "positive_electrode_basis": "positive_electrode_basis",
        "negative_electrode_basis": "negative_electrode_basis",
    }
    for field, mapping_key in field_map.items():
        value = product.get(field)
        if not isinstance(value, str):
            continue
        normalized = value.strip().lower()
        if not normalized or normalized == "unknown":
            continue
        if normalized not in value_map.get(mapping_key, set()):
            _append_issue(
                issues,
                code="semantic.controlled_value_unmapped",
                severity="warning",
                path=f"product.{field}",
                message=f"value '{value}' is not present in the controlled mapping for '{mapping_key}'.",
                resource_type=resource_type,
            )
            continue
        superseded = _controlled_value_aliases().get(mapping_key, {}).get(normalized)
        if superseded is not None:
            use_instead, why = superseded
            _append_issue(
                issues,
                code="semantic.controlled_value_superseded",
                severity="warning",
                path=f"product.{field}",
                message=(
                    f"value '{value}' still resolves, but '{use_instead}' is the label to use for "
                    f"'{mapping_key}'. {why}"
                ).strip(),
                resource_type=resource_type,
            )


def _validate_chemistry_electrode_agreement(
    doc: dict[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    issue_severity: str,
) -> None:
    """A cell spec's negative electrode basis must agree with its chemistry.

    The rule reads what the record states, not the classes it emits: the
    chemistry decides the battery classes, so the emitted stack of a li-ion cell
    with a lithium-metal negative looks valid while the record contradicts
    itself. A couple defined by its negative electrode (lithium metal for
    li-metal and the couples under it, zinc for the zinc couples) must have
    that electrode, and such an electrode makes a full cell one of those
    couples. Lithium as the counter electrode of a half cell or a
    three-electrode cell is no contradiction. The policy's hard severity: an
    error under strict and publisher, a warning otherwise.
    """
    product = doc.get("cell_spec")
    if not isinstance(product, Mapping):
        return
    from battinfo.transform.json_to_jsonld import chemistry_electrode_conflicts  # noqa: PLC0415

    for message in chemistry_electrode_conflicts(product):
        _append_issue(
            issues,
            code="semantic.chemistry_electrode_conflict",
            severity=issue_severity,
            path="cell_spec.negative_electrode_basis",
            message=message,
            resource_type=resource_type,
        )


# Electrode holders on a cell-spec, by family. The polarity holders describe a
# full cell; the role holders describe a cell that has no polarity to assign.
_POLARITY_ELECTRODE_FIELDS = ("positive_electrode", "negative_electrode")
_ROLE_ELECTRODE_FIELDS = ("working_electrode", "counter_electrode")
_ROLELESS_CONFIGURATIONS = {"half_cell", "half-cell", "three_electrode_cell", "three-electrode-cell", "three-electrode"}


def _populated_electrode_fields(doc: Mapping[str, Any], fields: tuple[str, ...]) -> list[str]:
    """The electrode holders of *fields* this record actually populates.

    An inline holder and its ``*_spec_id`` sibling both place an electrode, so
    both count. Holders may sit at the record top level (the schema's shape) or
    inside the ``cell_spec`` body (older payloads), so both are read.
    """
    product = doc.get("cell_spec")
    body: Mapping[str, Any] = product if isinstance(product, Mapping) else {}
    found: list[str] = []
    for field in fields:
        for key in (field, f"{field}_spec_id"):
            value = doc.get(key)
            if value is None:
                value = body.get(key)
            if isinstance(value, Mapping) and value:
                found.append(key)
            elif isinstance(value, str) and value.strip():
                found.append(key)
    return found


def _validate_electrode_role_coherence(
    doc: dict[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
) -> None:
    """The electrode holders must match the cell configuration.

    Upstream ruling: do not use polarity in a half cell — name the electrodes by
    role (working / counter / reference) instead. So a ``half_cell`` or
    ``three_electrode_cell`` belongs in ``working_electrode`` /
    ``counter_electrode``, and a ``full_cell`` in ``positive_electrode`` /
    ``negative_electrode``.

    Warnings, never errors: the funnel stays tolerant, and both holder families
    round-trip and emit whatever the configuration says. What is never allowed is
    silence — a record that mixes the two families, or that names its electrodes
    against its own stated configuration, says so here.
    """
    product = doc.get("cell_spec")
    if not isinstance(product, Mapping):
        return
    configuration = product.get("cell_configuration")
    configuration = configuration.strip().lower() if isinstance(configuration, str) else None
    if configuration is None and product.get("reference_electrode"):
        # The emitter's own fallback: an unstated configuration with a reference
        # electrode reads as a half cell, so the coherence check reads it that way too.
        configuration = "half_cell"
    roleless = configuration in _ROLELESS_CONFIGURATIONS

    polarity_fields = _populated_electrode_fields(doc, _POLARITY_ELECTRODE_FIELDS)
    role_fields = _populated_electrode_fields(doc, _ROLE_ELECTRODE_FIELDS)
    if not polarity_fields and not role_fields:
        return

    stated = f"cell_configuration '{configuration}'" if configuration else "an unstated cell_configuration"
    if polarity_fields and role_fields:
        preferred, discouraged = (
            (_ROLE_ELECTRODE_FIELDS, polarity_fields) if roleless else (_POLARITY_ELECTRODE_FIELDS, role_fields)
        )
        _append_issue(
            issues,
            code="semantic.electrode_holders_mixed",
            severity="warning",
            path=discouraged[0],
            message=(
                f"this cell-spec populates both polarity holders ({', '.join(polarity_fields)}) "
                f"and role holders ({', '.join(role_fields)}); with {stated} the electrodes "
                f"belong in {' / '.join(preferred)}. Two families describing one electrode "
                "emit two nodes in the JSON-LD - keep one."
            ),
            resource_type=resource_type,
        )
        return

    if polarity_fields and roleless:
        _append_issue(
            issues,
            code="semantic.electrode_role_expected",
            severity="warning",
            path=polarity_fields[0],
            message=(
                f"{stated} has no positive/negative polarity to assign, but this cell-spec "
                f"names its electrodes by polarity ({', '.join(polarity_fields)}). Use "
                "working_electrode / counter_electrode (and reference_electrode for a "
                "three-electrode cell) instead."
            ),
            resource_type=resource_type,
        )
    elif role_fields and not roleless:
        _append_issue(
            issues,
            code="semantic.electrode_polarity_expected",
            severity="warning",
            path=role_fields[0],
            message=(
                f"{stated} is read as a full cell, whose electrodes have a polarity, but this "
                f"cell-spec names its electrodes by role ({', '.join(role_fields)}). Use "
                "positive_electrode / negative_electrode, or state "
                "cell_configuration='half_cell' / 'three_electrode_cell' if that is what this is."
            ),
            resource_type=resource_type,
        )


def _validate_material_kind(
    doc: dict[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    issue_severity: str,
) -> None:
    """A material-spec's ``kind`` must resolve to the curated vocabulary.

    The kind is the Battery Genome's aggregation axis, so an authored spec is
    required to carry one. It is enforced here rather than as a JSON-schema
    required field so tolerant flows (lifting embedded materials, interop import)
    still structurally validate while the strict authoring gate rejects a spec
    with no kind:

    - kind present but unknown -> hard error listing the valid keys (the
      save-time rejection); create_material_spec also raises on an explicit
      unknown kind, so this is the backstop for hand-built records;
    - kind missing -> the policy's hard severity (error under strict / ws.save,
      warning under default) so blessed authoring requires it.
    """
    spec = doc.get("material_spec")
    if not isinstance(spec, Mapping):
        return
    from battinfo.materials import material_kind_keys, resolve_material_kind

    kind = spec.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        _append_issue(
            issues,
            code="semantic.material_kind_missing",
            severity=issue_severity,
            path="material_spec.kind",
            message=(
                "material spec has no kind. Set a Level-1 kind from the curated "
                f"vocabulary. Valid kinds: {', '.join(material_kind_keys())}."
            ),
            resource_type=resource_type,
        )
        return
    if resolve_material_kind(kind) is None:
        _append_issue(
            issues,
            code="semantic.material_kind_unknown",
            severity="error",
            path="material_spec.kind",
            message=(f"unknown material kind '{kind}'. Valid kinds: {', '.join(material_kind_keys())}."),
            resource_type=resource_type,
        )


def _validate_electrode_kind(
    doc: dict[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    issue_severity: str,
) -> None:
    """An electrode-spec's ``kind`` must name an active material from the vocabulary.

    Same contract as :func:`_validate_material_kind`, on the same axis: the
    electrode's kind is the ACTIVE material it is built from, so a graphite anode
    aggregates with every other graphite anode whether or not its powder was
    authored as a material-spec. Enforced here rather than as a JSON-schema
    required field so tolerant import still validates structurally.

    A kind that resolves but is not an active material (a binder, a salt) is a
    warning, not an error: the record is still usable and the author, not the
    validator, is best placed to fix the mix-up.
    """
    spec = doc.get("electrode_spec")
    if not isinstance(spec, Mapping):
        return
    from battinfo.electrodes import (
        electrode_kind_keys,
        is_active_kind,
        resolve_electrode_kind,
    )

    kind = spec.get("active_material_kind", spec.get("kind"))
    if not isinstance(kind, str) or not kind.strip():
        _append_issue(
            issues,
            code="semantic.electrode_kind_missing",
            severity=issue_severity,
            path="electrode_spec.active_material_kind",
            message=(
                "electrode spec has no active_material_kind. Set the active material's "
                f"kind from the curated vocabulary. Valid kinds: {', '.join(electrode_kind_keys())}."
            ),
            resource_type=resource_type,
        )
        return
    if resolve_electrode_kind(kind) is None:
        _append_issue(
            issues,
            code="semantic.electrode_kind_unknown",
            severity="error",
            path="electrode_spec.active_material_kind",
            message=(f"unknown electrode kind '{kind}'. Valid kinds: {', '.join(electrode_kind_keys())}."),
            resource_type=resource_type,
        )
        return
    if not is_active_kind(kind):
        _append_issue(
            issues,
            code="semantic.electrode_kind_not_active",
            severity="warning",
            path="electrode_spec.active_material_kind",
            message=(
                f"electrode kind '{kind}' is not an active material. An electrode's kind "
                "names what it stores charge with, not its binder or additive. Valid "
                f"kinds: {', '.join(electrode_kind_keys())}."
            ),
            resource_type=resource_type,
        )
        return
    # No kind-vs-polarity check: the vocabulary no longer assigns a side to an
    # active material (system-relative — graphite is the positive electrode of
    # a lithium-counter half cell), so an authored polarity cannot conflict
    # with the kind.


def _validate_size_code(
    doc: dict[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    issue_severity: str,
) -> None:
    product = doc.get("cell_spec")
    if not isinstance(product, Mapping):
        return
    size_code = product.get("size_code")
    if not isinstance(size_code, str) or not size_code.strip():
        return
    normalized = size_code.strip()
    if not SIZE_CODE_PATTERN.fullmatch(normalized):
        _append_issue(
            issues,
            code="semantic.size_code_invalid",
            severity=issue_severity,
            path="product.size_code",
            message="sizeCode must start with 'R' or 'P', for example 'R26650', 'P20/50/50', or 'P20-50-50'.",
            resource_type=resource_type,
        )
        return

    format_value = product.get("cell_format")
    if not isinstance(format_value, str):
        return
    format_key = format_value.strip().lower()
    prefix = normalized[0]
    expected_prefix = None
    if format_key in {"coin", "cylindrical"}:
        expected_prefix = "R"
    elif format_key in {"pouch", "prismatic"}:
        expected_prefix = "P"
    if expected_prefix is not None and prefix != expected_prefix:
        _append_issue(
            issues,
            code="semantic.size_code_prefix_mismatch",
            severity=issue_severity,
            path="product.size_code",
            message=f"sizeCode '{size_code}' must start with '{expected_prefix}' for cellFormat '{format_value}'.",
            resource_type=resource_type,
        )


def _validate_spec_plausibility(
    spec_name: str,
    spec_value: Mapping[str, Any],
    symbol: str | None,
    path: str,
    issues: list[ValidationIssue],
    resource_type: str | None,
) -> None:
    """Warn on a value outside the loose bounds for its property, in the unit symbol it uses."""
    if symbol is None:
        return
    bounds = SPEC_PLAUSIBILITY_BOUNDS.get(spec_name, {}).get(symbol)
    if bounds is None:
        return
    lo, hi = bounds
    # Check every numeric value in the spec against the bounds.
    for value_key in ("value", "typical_value", "min_value", "max_value"):
        raw = spec_value.get(value_key)
        if not isinstance(raw, (int, float)):
            continue
        v = float(raw)
        if v < lo or v > hi:
            _append_issue(
                issues,
                code="semantic.value_out_of_plausible_range",
                severity="warning",
                path=f"{path}.{value_key}",
                message=(
                    f"value {v} {symbol} for '{spec_name}' is outside the plausible range "
                    f"[{lo}, {hi}] {symbol}. Verify units and magnitude."
                ),
                resource_type=resource_type,
            )


@lru_cache(maxsize=1)
def _curated_property_map() -> dict[str, str]:
    """key -> EMMO class IRI from the packaged curated property map."""
    path = resources.files("battinfo").joinpath("data", "mappings", "domain-battery", "property_map.curated.json")
    with path.open("r", encoding="utf-8") as fh:
        doc = json.load(fh)
    return {m["key"]: m.get("class_iri", "") for m in doc.get("mappings", [])}


@lru_cache(maxsize=1)
def _component_property_terms() -> frozenset[str]:
    """Property keys the component emitters resolve WITHOUT the curated map.

    Derived from ``COMPONENT_PROPERTY_TERM_TABLES`` — the transform's own
    registry of every holder ``property`` term table — rather than by naming the
    tables here, so this set cannot drift from what the JSON-LD emitters accept.
    Listing them by hand is what let ``_ELECTRODE_PROPERTY_TERMS`` be added to
    the emitter without reaching the validator, which then warned that a mapped
    ``areal_capacity`` had no mapping.

    The set is a union across holders, not a per-holder table: a key any
    component emitter maps is accepted on every component. That is deliberately
    permissive (a coating term on an electrolyte body does not warn) and matches
    the behaviour this check has always had.
    """
    from battinfo.transform.json_to_jsonld import COMPONENT_PROPERTY_TERM_TABLES

    return frozenset(key for table in COMPONENT_PROPERTY_TERM_TABLES for key in table)


def _validate_property_mappability(
    specs: Mapping[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    *,
    path_prefix: str = "properties",
    extra_known: frozenset[str] = frozenset(),
) -> None:
    """Warn where a schema-valid property will not survive the JSON-LD export.

    Red-team finding: a record could be fully valid and still lose data on the
    semantic path with no signal - unmapped keys vanished, text-only values
    vanished, and two aliases of one EMMO class collapsed to a single node.
    """
    prop_map = _curated_property_map()
    class_to_keys: dict[str, list[str]] = {}
    for key, value in specs.items():
        if not isinstance(value, Mapping):
            continue
        class_iri = prop_map.get(key)
        if class_iri is None and key in extra_known:
            continue
        if class_iri is None:
            from battinfo.transform.json_to_jsonld import _property_type_term

            hand_kept = _property_type_term(str(key))
            if hand_kept:
                outcome = f"the JSON-LD export types it with the hand-kept class '{hand_kept}'."
            else:
                outcome = (
                    "the JSON-LD export gives it no quantity class, only its "
                    "value-basis class (for example ConventionalProperty) with the "
                    "key as its label, so tools looking for a specific quantity "
                    "will not find it."
                )
            _append_issue(
                issues,
                code="semantic.property_unmapped",
                severity="warning",
                path=f"{path_prefix}.{key}",
                message=(
                    f"'{key}' is schema-valid but has no curated EMMO mapping - "
                    f"{outcome} File a mapping in "
                    "assets/mappings/domain-battery/property_map.curated.json."
                ),
                resource_type=resource_type,
            )
            continue
        if class_iri:
            class_to_keys.setdefault(class_iri, []).append(key)
        has_number = any(
            isinstance(value.get(k), (int, float)) and not isinstance(value.get(k), bool)
            for k in ("value", "typical_value", "min_value", "max_value")
        )
        if not has_number and isinstance(value.get("value_text"), str):
            _append_issue(
                issues,
                code="semantic.value_text_only",
                severity="warning",
                path=f"{path_prefix}.{key}",
                message=(
                    f"'{key}' carries only value_text - the JSON-LD export emits "
                    "numeric quantities, so this property will be OMITTED there."
                ),
                resource_type=resource_type,
            )
    for class_iri, keys in class_to_keys.items():
        if len(keys) > 1:
            _append_issue(
                issues,
                code="semantic.property_alias_collision",
                severity="warning",
                path=f"{path_prefix}.{keys[1]}",
                message=(
                    f"{keys} all map to the same EMMO class ({class_iri.rsplit('#', 1)[-1]}); "
                    "only one quantity node survives in JSON-LD - keep a single alias."
                ),
                resource_type=resource_type,
            )


def _validate_specs(
    specs: Mapping[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    issue_severity: str,
    *,
    path_prefix: str = "properties",
) -> None:
    """Units, plausibility and ranges of a property map; issue paths start with ``path_prefix``."""
    symbols: dict[str, str] = {}
    for spec_name, spec_value in specs.items():
        if not isinstance(spec_value, Mapping):
            continue
        path = f"{path_prefix}.{spec_name}"
        # Non-finite numerics (NaN / +-Infinity) are caught record-wide by
        # _walk_non_finite (called from validate_semantic_report), so nested
        # quantities are covered too, not just flat specs.
        unit = _unit_token(spec_value)
        symbol = _check_spec_unit(spec_name, unit, path, issues, resource_type, issue_severity) if unit else None
        if symbol is not None:
            symbols[spec_name] = symbol

        _validate_spec_plausibility(spec_name, spec_value, symbol, path, issues, resource_type)

        min_value = spec_value.get("min_value")
        max_value = spec_value.get("max_value")
        typical_value = spec_value.get("typical_value")
        if (
            isinstance(min_value, (int, float))
            and isinstance(max_value, (int, float))
            and float(min_value) > float(max_value)
        ):
            _append_issue(
                issues,
                code="semantic.range_invalid",
                severity=issue_severity,
                path=path,
                message=f"min_value {min_value} must be <= max_value {max_value}.",
                resource_type=resource_type,
            )
        if (
            isinstance(typical_value, (int, float))
            and isinstance(min_value, (int, float))
            and isinstance(max_value, (int, float))
            and not (float(min_value) <= float(typical_value) <= float(max_value))
        ):
            _append_issue(
                issues,
                code="semantic.range_invalid",
                severity=issue_severity,
                path=f"{path}.typical_value",
                message=f"typical_value {typical_value} must fall between min_value {min_value} and max_value {max_value}.",
                resource_type=resource_type,
            )

    for lower_key, upper_key in PAIRED_SPEC_RANGES:
        lower = specs.get(lower_key)
        upper = specs.get(upper_key)
        if not isinstance(lower, Mapping) or not isinstance(upper, Mapping):
            continue
        lower_num = _numeric_spec_value(lower)
        upper_num = _numeric_spec_value(upper)
        if lower_num is None or upper_num is None:
            continue
        # Compare the symbols the units stand for, so '°C' and 'degC' are one unit.
        lower_unit = symbols.get(lower_key) or _unit_token(lower)
        upper_unit = symbols.get(upper_key) or _unit_token(upper)
        if lower_unit and upper_unit and lower_unit != upper_unit:
            _append_issue(
                issues,
                code="semantic.unit_mismatch",
                severity=issue_severity,
                path=f"{path_prefix}.{lower_key}",
                message=f"paired specs '{lower_key}' and '{upper_key}' must use the same unit.",
                resource_type=resource_type,
            )
            continue
        if lower_num > upper_num:
            _append_issue(
                issues,
                code="semantic.range_invalid",
                severity=issue_severity,
                path=f"{path_prefix}.{lower_key}",
                message=f"spec '{lower_key}' value {lower_num} must be <= '{upper_key}' value {upper_num}.",
                resource_type=resource_type,
            )


def _validate_dataset_semantics(
    dataset: Mapping[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    issue_severity: str,
) -> None:
    about = dataset.get("about")
    related_entities = dataset.get("related_entities")
    has_battery_link = False
    if isinstance(about, list):
        has_battery_link = any(
            isinstance(item, str) and item.startswith((CELL_IRI_PREFIX, CELL_TYPE_IRI_PREFIX, MATERIAL_IRI_PREFIX))
            for item in about
        )
    elif isinstance(related_entities, Mapping):
        cell_ids = related_entities.get("cell_ids")
        if isinstance(cell_ids, list):
            has_battery_link = any(isinstance(item, str) and item.startswith(CELL_IRI_PREFIX) for item in cell_ids)
    # A series-flavored dataset (dcat:DatasetSeries) is a grouping record: its
    # member datasets carry the cell links and point here via series_id, so
    # requiring a direct cell link on the collection would force redundancy.
    # A collection MAY still state cells/specs in `about`; it just isn't made to.
    if not has_battery_link and not is_dataset_series(dataset.get("additional_type")):
        _append_issue(
            issues,
            code="semantic.dataset_missing_cell_link",
            severity=issue_severity,
            path="dataset.about",
            message="dataset must reference at least one BattINFO cell, material or spec IRI in about.",
            resource_type=resource_type,
        )

    created = dataset.get("created_at")
    modified = dataset.get("modified_at")
    published = dataset.get("published_at")
    if isinstance(created, int) and isinstance(modified, int) and modified < created:
        _append_issue(
            issues,
            code="semantic.temporal_order_invalid",
            severity=issue_severity,
            path="dataset.modified_at",
            message=f"modified_at {modified} must be >= created_at {created}.",
            resource_type=resource_type,
        )
    if isinstance(created, int) and isinstance(published, int) and published < created:
        _append_issue(
            issues,
            code="semantic.temporal_order_invalid",
            severity=issue_severity,
            path="dataset.published_at",
            message=f"published_at {published} must be >= created_at {created}.",
            resource_type=resource_type,
        )

    distributions = dataset.get("distributions")
    if isinstance(distributions, list):
        for idx, distribution in enumerate(distributions):
            if not isinstance(distribution, Mapping):
                continue
            checksum = distribution.get("checksum")
            if not isinstance(checksum, Mapping):
                continue
            algorithm = checksum.get("algorithm")
            value = checksum.get("value")
            if not isinstance(algorithm, str) or not isinstance(value, str):
                continue
            expected_length = {"sha256": 64, "sha512": 128, "md5": 32}.get(algorithm.lower())
            if expected_length is None:
                continue
            is_hex = all(ch in "0123456789abcdefABCDEF" for ch in value)
            if len(value) != expected_length or not is_hex:
                _append_issue(
                    issues,
                    code="semantic.checksum_invalid",
                    severity=issue_severity,
                    path=f"dataset.distributions[{idx}].checksum.value",
                    message=f"checksum for algorithm '{algorithm}' must be {expected_length} hex characters.",
                    resource_type=resource_type,
                )


def _validate_test_semantics(
    test: Mapping[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    issue_severity: str,
) -> None:
    started = test.get("started_at")
    ended = test.get("ended_at")
    if isinstance(started, int) and isinstance(ended, int) and ended < started:
        _append_issue(
            issues,
            code="semantic.temporal_order_invalid",
            severity=issue_severity,
            path="test.ended_at",
            message=f"ended_at {ended} must be >= started_at {started}.",
            resource_type=resource_type,
        )


# Kelvin spellings, compared without case ('K', 'Kelvin', 'KEL'); "kel" is the
# UN/CEFACT code.
_KELVIN_UNITS = frozenset({"k", "kelvin", "kel"})


def _validate_ambient_temperature_unit(
    doc: Mapping[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
) -> None:
    """Warn when an ambient temperature is given in kelvin.

    The records context types ``ambient_temperature`` as AmbientCelsiusTemperature,
    so a value in kelvin would be published as a Celsius temperature. A test
    protocol plans its conditions at the top level, a test records them as run.
    """
    test = doc.get("test")
    holders = [("conditions", doc.get("conditions"))]
    if isinstance(test, Mapping):
        holders.append(("test.conditions", test.get("conditions")))
    for prefix, conditions in holders:
        quantity = conditions.get("ambient_temperature") if isinstance(conditions, Mapping) else None
        unit = _unit_token(quantity) if isinstance(quantity, Mapping) else None
        if unit is None or unit.casefold() not in _KELVIN_UNITS:
            continue
        _append_issue(
            issues,
            code="semantic.ambient_temperature_kelvin",
            severity="warning",
            path=f"{prefix}.ambient_temperature",
            message=(
                "ambient_temperature is given in kelvin, but the records context types it as "
                "AmbientCelsiusTemperature, a Celsius temperature. Give the value in degC."
            ),
            resource_type=resource_type,
        )


def _validate_method_step_classes(
    doc: Mapping[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
) -> None:
    """Warn where a test-protocol step will be emitted without a class.

    EMMO has no class for some steps: a constant-resistance charge, and a cr or
    cccv step with no charge or discharge direction. The JSON-LD export keeps
    such a step with its parameters and its mode as a label, but gives it no
    ``@type``, as it does for a property key with no mapped class
    (``semantic.property_unmapped``). Steps inside a repeated group are checked
    too.
    """
    from battinfo.jsonld import unmapped_step_reason

    def walk(steps: Any, prefix: str) -> None:
        if not isinstance(steps, list):
            return
        for idx, step in enumerate(steps):
            if not isinstance(step, Mapping):
                continue
            path = f"{prefix}[{idx}]"
            if step.get("mode") == "group":
                walk(step.get("steps"), f"{path}.steps")
                continue
            reason = unmapped_step_reason(step)
            if reason:
                _append_issue(
                    issues,
                    code="semantic.method_step_unmapped",
                    severity="warning",
                    path=path,
                    message=reason,
                    resource_type=resource_type,
                )

    walk(doc.get("method"), "method")


_EPOCH_MIN = 946684800  # 2000-01-01
_EPOCH_MAX = 4102444800  # 2100-01-01
# The Unix times a date can be made of: 0001-01-01T00:00:00Z to 9999-12-31T23:59:59Z.
_EPOCH_FIRST = -62135596800
_EPOCH_LAST = 253402300799


def _walk_epoch_plausibility(
    value: Any,
    path: str,
    issues: list[ValidationIssue],
    resource_type: str | None,
    hard_issue_severity: str = "warning",
) -> None:
    """Warn on any ``*_at`` epoch field outside 2000..2100.

    A 1970 timestamp on a citable record is always converter/import garbage
    (e.g. an epoch that was divided by 1000 upstream), yet it is schema-valid;
    this is the loud channel the red-team review found missing.

    A time no date can be made of, most often one in milliseconds (past the
    year 9999 as seconds), is ``semantic.timestamp_out_of_range`` instead, at
    the policy's hard severity: an error under the strict and publisher
    policies, so ``ws.save()`` stops it. A deposit graph would have to leave
    such a time out.
    """
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if (
                isinstance(key, str)
                and key.endswith("_at")
                and isinstance(item, (int, float))
                and not isinstance(item, bool)
                and item != 0
                # Compared as they are: float() of a very large int overflows.
                and not (_EPOCH_MIN <= item <= _EPOCH_MAX)
            ):
                if not (_EPOCH_FIRST <= item <= _EPOCH_LAST):
                    _append_issue(
                        issues,
                        code="semantic.timestamp_out_of_range",
                        severity=hard_issue_severity,
                        path=child,
                        message=(
                            f"{key} = {item} cannot be a Unix time in seconds: it falls outside the "
                            "years 1 to 9999, as a time in milliseconds does. Give it in seconds; a "
                            "deposit graph leaves it out."
                        ),
                        resource_type=resource_type,
                    )
                    continue
                _append_issue(
                    issues,
                    code="semantic.timestamp_implausible",
                    severity="warning",
                    path=child,
                    message=(
                        f"{key} = {item} is outside 2000-2100 as a Unix epoch "
                        "- likely a unit error upstream (ms vs s, or a /1000 bug). "
                        "Verify the source data before publishing."
                    ),
                    resource_type=resource_type,
                )
            else:
                _walk_epoch_plausibility(item, child, issues, resource_type, hard_issue_severity)
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            _walk_epoch_plausibility(item, f"{path}[{idx}]", issues, resource_type, hard_issue_severity)


def _walk_non_finite(
    value: Any,
    path: str,
    issues: list[ValidationIssue],
    resource_type: str | None,
) -> None:
    """Recursively flag any non-finite float (NaN / +-Infinity) anywhere in the record.

    Non-finite numerics are never valid measurements and are not JSON-serialisable
    (RFC 8259), so they are a hard error regardless of policy or nesting depth. This
    catches values a flat specs check misses — e.g. an electrode coating's nested
    ``property.loading.value`` reached via create_component_spec.
    """
    if isinstance(value, bool):
        return
    if isinstance(value, float) and not math.isfinite(value):
        label = path or "<root>"
        _append_issue(
            issues,
            code="semantic.value_not_finite",
            severity="error",
            path=label,
            message=f"value at '{label}' is not finite (NaN/Infinity); not a valid measurement.",
            resource_type=resource_type,
        )
    elif isinstance(value, Mapping):
        for key, sub in value.items():
            _walk_non_finite(sub, f"{path}.{key}" if path else str(key), issues, resource_type)
    elif isinstance(value, (list, tuple)):
        for index, sub in enumerate(value):
            _walk_non_finite(sub, f"{path}[{index}]", issues, resource_type)


def _walk_percent_basis(
    value: Any,
    path: str,
    issues: list[ValidationIssue],
    resource_type: str | None,
) -> None:
    """Warn where a fraction's percent unit states the other basis.

    ``mass_fraction`` is by mass, ``volume_fraction`` and ``porosity`` by
    volume, wherever they sit in the record. ``vol%`` on a mass fraction or
    ``wt%`` on a volume fraction contradicts the key; the JSON-LD export
    publishes the value on [0, 1] and drops the stated basis. A warning under
    every policy, from the same check the emitter warns with.
    """
    from battinfo.transform.json_to_jsonld import percent_basis_conflict  # noqa: PLC0415

    if isinstance(value, Mapping):
        for key, sub in value.items():
            sub_path = f"{path}.{key}" if path else str(key)
            problem = percent_basis_conflict(str(key), sub)
            if problem:
                _append_issue(
                    issues,
                    code="semantic.percent_basis_mismatch",
                    severity="warning",
                    path=sub_path,
                    message=problem,
                    resource_type=resource_type,
                )
            _walk_percent_basis(sub, sub_path, issues, resource_type)
    elif isinstance(value, (list, tuple)):
        for index, sub in enumerate(value):
            _walk_percent_basis(sub, f"{path}[{index}]", issues, resource_type)


def _validate_substance_resolution(
    doc: Mapping[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
) -> None:
    """Warn when an electrolyte component names a substance the vocabulary
    cannot resolve. Never an error: honest records with obscure or proprietary
    substances save fine; the warning is what makes the unidentified backlog
    visible (readiness panel counts it). A resolvable-but-unstamped name is NOT
    flagged - enrichment sweeps can stamp it mechanically at any time."""
    from battinfo.substances import AmbiguousSubstanceError, resolve, suggest

    def _check(component: Any, slot: str, path: str) -> None:
        if not isinstance(component, Mapping):
            return
        name = component.get("name")
        if not isinstance(name, str) or not name.strip() or component.get("inchikey"):
            return
        try:
            resolved = resolve(name, slot=slot)
        except AmbiguousSubstanceError:
            _append_issue(
                issues,
                code="semantic.substance_ambiguous",
                severity="warning",
                path=path,
                message=f"substance name '{name}' is ambiguous even for slot '{slot}'.",
                resource_type=resource_type,
            )
            return
        if resolved is None:
            hint = suggest(name)
            hint_text = f" Did you mean: {', '.join(hint)}?" if hint else ""
            _append_issue(
                issues,
                code="semantic.substance_unresolved",
                severity="warning",
                path=path,
                message=(
                    f"substance '{name}' is not in the substances vocabulary; the record "
                    f"saves without chemical identity (no InChIKey).{hint_text}"
                ),
                resource_type=resource_type,
            )

    electrolyte_bodies: list[tuple[Mapping[str, Any], str]] = []
    spec_body = doc.get("electrolyte_spec")
    if isinstance(spec_body, Mapping):
        electrolyte_bodies.append((spec_body, "electrolyte_spec"))
    cell_body = doc.get("cell_spec")
    if isinstance(cell_body, Mapping) and isinstance(cell_body.get("electrolyte"), Mapping):
        electrolyte_bodies.append((cell_body["electrolyte"], "cell_spec.electrolyte"))

    for body, prefix in electrolyte_bodies:
        salts = body.get("salt")
        if isinstance(salts, list):
            for idx, salt in enumerate(salts):
                _check(salt, "salt", f"{prefix}.salt[{idx}]")
        else:
            _check(salts, "salt", f"{prefix}.salt")
        mixture = body.get("solvent_mixture")
        if isinstance(mixture, Mapping):
            for idx, comp in enumerate(mixture.get("component") or []):
                _check(comp, "solvent", f"{prefix}.solvent_mixture.component[{idx}]")
        for idx, comp in enumerate(body.get("additive") or []):
            _check(comp, "additive", f"{prefix}.additive[{idx}]")


def _old_form_record_iri(value: object) -> RecordIri | None:
    """*value* taken apart as a record IRI of the old form, the only form validated until the schemas accept both."""
    parsed = parse_record_iri(value)
    return parsed if parsed is not None and parsed.prefix is None else None


def _list_or_empty(value: Any) -> list[Any]:
    """The value when it is a list, else an empty list: a malformed field is a schema
    finding, never a crash in the semantic pass."""
    return value if isinstance(value, list) else []


def _validate_parameter_set_identity(
    body: Mapping[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    policy_name: str,
) -> None:
    """A parameter set's IRI against the namespace move of 2026-10-11 (IDENTIFIER_POLICY 6.3).

    A record minted under spec/ before then is legacy: it stays readable, so
    it is a warning, except under the publisher policy, where it is an error
    because nothing is published under spec/ any more. The message names the
    dataset/ IRI its replacement mints. A record that names its own IRI in
    ``supersedes``, or carries a uid it had under spec/ (the uid of the
    record it supersedes, or the one the seeds of the time give its fields,
    whether or not it names that record), is an error under every policy: a
    uid is never reused (section 10).
    """
    from battinfo.api._parameters import legacy_parameter_set_uid, parameter_set_uid  # noqa: PLC0415

    record_id = body.get("id")
    own = _old_form_record_iri(record_id)
    if own is None:
        return  # the schema reports a malformed id
    if own.segment == "spec":
        replacement_uid = parameter_set_uid(body)
        replacement = (
            f"its replacement is https://w3id.org/battinfo/dataset/{replacement_uid}, a new record "
            "minted from the current seeds that supersedes this one"
            if replacement_uid is not None
            else "a new version is a new dataset/ record that supersedes this one"
        )
        _append_issue(
            issues,
            code="semantic.parameter_set_legacy_namespace",
            severity="error" if policy_name == "publisher" else "warning",
            path="parameter_set.id",
            message=(
                f"{record_id} was minted under spec/, before parameter sets moved to dataset/ on "
                "2026-10-11 (IDENTIFIER_POLICY 6.3). The record stays readable, but nothing is "
                f"published under spec/ any more: {replacement}, which "
                "battinfo.api.supersede_parameter_set(record) builds."
            ),
            resource_type=resource_type,
        )
    supersedes = body.get("supersedes")
    if isinstance(supersedes, str) and supersedes == record_id:
        _append_issue(
            issues,
            code="semantic.parameter_set_supersedes_itself",
            severity="error",
            path="parameter_set.supersedes",
            message=(
                f"supersedes names this record's own IRI ({record_id}); it names the earlier record this one replaces."
            ),
            resource_type=resource_type,
        )
        return
    old = _old_form_record_iri(supersedes)
    if old is not None and old.uid == own.uid:
        _append_issue(
            issues,
            code="semantic.parameter_set_uid_reused",
            severity="error",
            path="parameter_set.id",
            message=(
                f"this record reuses the uid {own.uid} of the record it supersedes "
                f"({supersedes}). A uid is never reused, not even under another namespace "
                "(IDENTIFIER_POLICY 6.3 and 10): leave id out so the record mints its own uid "
                "from the current seeds, or build it with battinfo.api.supersede_parameter_set()."
            ),
            resource_type=resource_type,
        )
        return
    if own.segment == "dataset" and own.uid == legacy_parameter_set_uid(body):
        legacy_iri = record_iri("spec", own.uid)
        replacement_uid = parameter_set_uid(body)
        _append_issue(
            issues,
            code="semantic.parameter_set_uid_reused",
            severity="error",
            path="parameter_set.id",
            message=(
                f"this record reuses the uid {own.uid} of {legacy_iri}, the IRI the seeds of "
                "before 2026-10-11 give these fields under spec/. A uid is never reused, not even "
                "under another namespace (IDENTIFIER_POLICY 6.3 and 10): the dataset/ record for "
                f"these fields is https://w3id.org/battinfo/dataset/{replacement_uid}, minted from "
                f"the current seeds, with supersedes naming {legacy_iri}; "
                "battinfo.api.supersede_parameter_set() builds it from the spec/ record."
            ),
            resource_type=resource_type,
        )


def _validate_parameter_set_semantics(
    body: Mapping[str, Any],
    issues: list[ValidationIssue],
    resource_type: str | None,
    policy_name: str,
) -> None:
    """Claim mappability, plus the parameter-file rules JSON Schema cannot state.

    The parameter-file rules are integrity rules (the IRI must be the one
    the fingerprint gives, a runnable copy must name its source, a mirror
    must be the source's bytes, a part appears once), so they are errors
    under every policy. A parameter file with no source file is fine for
    local work and an error for publishing (ruling 2026-10-11): nothing
    under the default policy, a warning under strict, an error under the
    publisher policy.
    """
    _validate_parameter_set_identity(body, issues, resource_type, policy_name)
    # Parameter-set claims emit through the same quantity nodes as properties,
    # so an unmapped parameter key gets the same warning. Fraction keys resolve
    # through the emitter's own table, as they do for properties.
    from battinfo.transform.json_to_jsonld import _FRACTION_PROPERTY_TERMS

    fraction_keys = frozenset(_FRACTION_PROPERTY_TERMS)
    claim_lists: list[tuple[str, Any]] = [("parameter_set.claims", body.get("claims"))]
    for part_idx, part in enumerate(_list_or_empty(body.get("parts"))):
        if isinstance(part, Mapping):
            claim_lists.append((f"parameter_set.parts[{part_idx}].claims", part.get("claims")))
    for prefix, claims in claim_lists:
        if not isinstance(claims, list):
            continue
        for idx, claim in enumerate(claims):
            if (
                isinstance(claim, Mapping)
                and isinstance(claim.get("parameter"), str)
                and isinstance(claim.get("quantity"), Mapping)
            ):
                _validate_property_mappability(
                    {claim["parameter"]: claim["quantity"]},
                    issues,
                    resource_type,
                    path_prefix=f"{prefix}[{idx}]",
                    extra_known=fraction_keys,
                )
                _validate_transport_placeholder(claim, f"{prefix}[{idx}]", issues, resource_type)

    if "parts" not in body and "distributions" not in body:
        return
    from battinfo.api._parameters import parameter_file_issues  # noqa: PLC0415

    for code, severity, path, message in parameter_file_issues(body):
        if code.endswith("_count"):
            continue  # the schema's contains/maxContains rules report these
        _append_issue(
            issues,
            code=f"semantic.parameter_file_{code}",
            severity="error" if severity == "error" else "warning",
            path=path,
            message=message,
            resource_type=resource_type,
        )
    if "parts" in body and policy_name in ("strict", "publisher"):
        distributions = body.get("distributions")
        has_source = isinstance(distributions, list) and any(
            isinstance(entry, Mapping) and entry.get("role") == "source" for entry in distributions
        )
        if not has_source:
            _append_issue(
                issues,
                code="semantic.parameter_file_no_source",
                severity="error" if policy_name == "publisher" else "warning",
                path="parameter_set.distributions",
                message=(
                    "a parameter file is published with its file: attach the source under "
                    "distributions (bpx_file_distribution(path, content_url=...)), so its IRI "
                    "resolves to a file with exactly these parameters."
                ),
                resource_type=resource_type,
            )


def _validate_transport_placeholder(
    claim: Mapping[str, Any],
    path: str,
    issues: list[ValidationIssue],
    resource_type: str | None,
) -> None:
    """Warn on a zero or negative scalar of a transport parameter a model needs positive.

    Such a value is a placeholder (a BPX file that keeps the real model in
    User-defined, for example), not one anyone obtained. The record keeps it
    as its source states it; the warning fires on every check of the record,
    so a reader of the saved record learns what the import warned about.
    """
    from battinfo.parameters import _nonpositive_transport_value  # noqa: PLC0415

    value = _nonpositive_transport_value(claim)
    if value is None:
        return
    unit = claim["quantity"].get("unit")
    _append_issue(
        issues,
        code="semantic.parameter_transport_not_positive",
        severity="warning",
        path=f"{path}.quantity.value",
        message=(
            f"claim '{claim['parameter']}' is {value!r}{f' {unit}' if unit else ''}: a physics model "
            "needs this transport parameter positive, so a zero or negative value is usually a "
            "placeholder for a model kept elsewhere. The value stays as its source states it; check "
            "the source before using it."
        ),
        resource_type=resource_type,
    )


def validate_semantic_report(
    doc: dict[str, Any],
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationReport:
    doc = record_to_snake_aliases(doc)
    resolved_policy = get_validation_policy(policy) if isinstance(policy, str) else policy
    if resolved_policy.semantic == "off":
        return ValidationReport(policy=resolved_policy)

    issues: list[ValidationIssue] = []
    entity = _entity_from_doc(doc)
    resource_type = entity[0] if entity is not None else None
    hard_issue_severity = "error" if resolved_policy.semantic == "error" else "warning"

    _validate_identifier_consistency(doc, issues, resource_type, hard_issue_severity)
    _validate_schema_version(doc, issues)
    _validate_handle_kind_word(doc, issues)
    _validate_controlled_values(doc, issues, resource_type)
    _validate_chemistry_electrode_agreement(doc, issues, resource_type, hard_issue_severity)
    _validate_electrode_role_coherence(doc, issues, resource_type)
    _validate_material_kind(doc, issues, resource_type, hard_issue_severity)
    _validate_electrode_kind(doc, issues, resource_type, hard_issue_severity)
    _validate_size_code(doc, issues, resource_type, hard_issue_severity)
    _validate_substance_resolution(doc, issues, resource_type)
    # Non-finite numerics are invalid anywhere in the record (RFC 8259); walk the
    # whole doc so nested quantities (electrode coating, etc.) are caught, not just
    # flat specs.
    _walk_non_finite(doc, "", issues, resource_type)
    _walk_epoch_plausibility(doc, "", issues, resource_type, hard_issue_severity)
    _walk_percent_basis(doc, "", issues, resource_type)

    specs = doc.get("properties")
    if isinstance(specs, Mapping):
        _validate_specs(specs, issues, resource_type, hard_issue_severity)
        _validate_property_mappability(specs, issues, resource_type)

    # material-spec / material carry their quantities under <body>.property
    for body_key in ("material_spec", "material", "electrode_spec", "electrode"):
        body = doc.get(body_key)
        if isinstance(body, Mapping) and isinstance(body.get("property"), Mapping):
            _validate_specs(
                body["property"], issues, resource_type, hard_issue_severity, path_prefix=f"{body_key}.property"
            )

    # Every component body's property block gets the mappability check, with the
    # transform's own holder term tables (fraction, descriptor, coating,
    # electrode, material) treated as known — they resolve without the curated
    # map. Coating properties resolve through the coating term table, so
    # electrode coatings are checked too.
    _component_known = _component_property_terms()

    def _check_props(block: Any, prefix: str) -> None:
        """Run the mappability check on ``block['property']`` when present."""
        if isinstance(block, Mapping) and isinstance(block.get("property"), Mapping):
            _validate_property_mappability(
                block["property"],
                issues,
                resource_type,
                path_prefix=f"{prefix}.property",
                extra_known=_component_known,
            )

    for body_key in (
        "material_spec",
        "material",
        "electrode_spec",
        "electrode",
        # Inline electrode bodies carried directly on a cell spec (not just the
        # standalone electrode records) emit fallback terms too, so check them.
        "positive_electrode",
        "negative_electrode",
        "working_electrode",
        "counter_electrode",
        "electrolyte_spec",
        "electrolyte",
        "separator_spec",
        "separator",
        "current_collector_spec",
        "current_collector",
        "housing_spec",
        "housing",
        "equipment_spec",
        "equipment",
        "channel",
    ):
        body = doc.get(body_key)
        if not isinstance(body, Mapping):
            continue
        _check_props(body, body_key)
        coating = body.get("coating")
        if isinstance(coating, Mapping):
            _check_props(coating, f"{body_key}.coating")
            # Material-component nesting: coating.component.<group>[].property
            # (active_material, binder, additive, ...). Each item is a holder whose
            # property block rides the same generic emitter.
            component = coating.get("component")
            if isinstance(component, Mapping):
                for group, items in component.items():
                    if not isinstance(items, list):
                        continue
                    for idx, item in enumerate(items):
                        _check_props(item, f"{body_key}.coating.component.{group}[{idx}]")
        # Housing sub-parts each carry an independent property block that would
        # otherwise emit unlabeled fallback terms with no warning.
        _check_props(body.get("case"), f"{body_key}.case")
        for idx, seal in enumerate(body.get("seals") or []):
            _check_props(seal, f"{body_key}.seals[{idx}]")
        for idx, part in enumerate(_list_or_empty(body.get("parts"))):
            _check_props(part, f"{body_key}.parts[{idx}]")

    parameter_set = doc.get("parameter_set")
    if isinstance(parameter_set, Mapping):
        _validate_parameter_set_semantics(parameter_set, issues, resource_type, resolved_policy.name)

    dataset = doc.get("dataset")
    if isinstance(dataset, Mapping):
        _validate_dataset_semantics(dataset, issues, resource_type, hard_issue_severity)

    test = doc.get("test")
    if isinstance(test, Mapping):
        _validate_test_semantics(test, issues, resource_type, hard_issue_severity)
    _validate_ambient_temperature_unit(doc, issues, resource_type)
    _validate_method_step_classes(doc, issues, resource_type)

    return ValidationReport(issues=tuple(issues), policy=resolved_policy)


def validate_semantic(
    doc: dict[str, Any],
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationResult:
    return validate_semantic_report(doc, policy=policy).to_result()
