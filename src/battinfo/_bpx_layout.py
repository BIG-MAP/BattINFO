"""The BPX v0.x -> v1 layout conversion, as one pure function.

BPX 1.0 added a top-level ``State`` block. The initial and ambient
temperatures left ``Parameterisation.Cell``, the initial electrolyte
concentration left ``Parameterisation.Electrolyte`` (renamed), and Cell's
lumped thermal conductivity left the schema; every parser since 1.0 rejects a
file that keeps them in the old places, and a 0.x file only loads after a
conversion. :func:`to_v1_layout` is that conversion. BattINFO uses it for
``upgrade_bpx`` (the runnable copy of a file the parser rejects) and for the
v1 export of a record read from a v0.x-layout file, so both give the same
document.

The battinfo-registry vendors this module verbatim, as it vendors
``battinfo._jcs``, to check that a runnable copy is the layout conversion of
its source. So it imports the standard library only and nothing from
battinfo: edit it here and re-vendor.

The conversion matches the bpx package's own migration
(``bpx.convert_v0_to_v1``) where that migration applies, with two
differences. The lumped thermal conductivity moves to ``User-defined``
unchanged, where the bpx package drops it; the bpx parser itself asks for it
there. And a ``State`` block already in the file is merged, not replaced: a
value set both there and in the old place is refused unless the two agree.
The State values the bpx migration adds when a v0.x file lacks them are
added here too, and named in the list of changes:

- ``Initial state-of-charge`` 1;
- ``Ambient temperature [K]``: Cell's reference temperature, else 298.15 K;
- ``Initial temperature [K]``: the ambient temperature.

The initial electrolyte concentration moves when the file has one and is
never invented.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Mapping

__all__ = [
    "DEFAULT_TARGET_VERSION",
    "THERMAL_CONDUCTIVITY",
    "V1_STATE_MOVES",
    "is_v0_layout",
    "to_v1_layout",
    "uses_v1_layout",
    "v0_layout_fields",
    "version_tuple",
]

#: ``Header.BPX`` a conversion writes unless asked for another 1.x version.
DEFAULT_TARGET_VERSION = "1.1.0"

#: The fields BPX 1.0 moved out of Parameterisation into the top-level State
#: block: (block, v0.x key, State section, v1 key).
V1_STATE_MOVES: tuple[tuple[str, str, str, str], ...] = (
    ("Cell", "Initial temperature [K]", "Initial conditions", "Initial temperature [K]"),
    ("Cell", "Ambient temperature [K]", "Thermal environment", "Ambient temperature [K]"),
    (
        "Electrolyte",
        "Initial concentration [mol.m-3]",
        "Initial conditions",
        "Initial electrolyte concentration [mol.m-3]",
    ),
)

#: Cell's lumped thermal conductivity is not part of the BPX 1.0+ schema; the
#: parser asks for it in User-defined instead, under the same key.
THERMAL_CONDUCTIVITY = "Thermal conductivity [W.m-1.K-1]"

_REFERENCE_TEMPERATURE = "Reference temperature [K]"
_DEFAULT_TEMPERATURE_K = 298.15
_INITIAL = "Initial conditions"
_THERMAL = "Thermal environment"
_SOC = "Initial state-of-charge"
_INITIAL_TEMPERATURE = "Initial temperature [K]"
_AMBIENT_TEMPERATURE = "Ambient temperature [K]"
_INITIAL_CONCENTRATION = "Initial electrolyte concentration [mol.m-3]"

# The order the bpx migration writes State in; other keys follow in their own order.
_SECTION_ORDER = (_INITIAL, _THERMAL)
_KEY_ORDER = {
    _INITIAL: (_SOC, _INITIAL_TEMPERATURE, _INITIAL_CONCENTRATION),
    _THERMAL: (_AMBIENT_TEMPERATURE,),
}


def version_tuple(version: Any) -> tuple[int, ...]:
    """A comparable prefix tuple from a BPX version (``"1.1.0"``, ``1.0``); ``()`` when unparseable."""
    if isinstance(version, bool):
        return ()
    parts: list[int] = []
    for piece in str(version).strip().split("."):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts)


def uses_v1_layout(version: Any) -> bool:
    """Whether a declared BPX version means the v1 layout (major version 1 or later).

    The same cut the official parser makes (``bpx._migrations.is_legacy_bpx``):
    the State block arrived with BPX 1.0, not 1.1.
    """
    parts = version_tuple(version)
    return bool(parts) and parts[0] >= 1


def v0_layout_fields(document: Mapping[str, Any]) -> list[str]:
    """The fields of ``document`` that sit where only the v0.x layout puts them."""
    parameterisation = document.get("Parameterisation")
    if not isinstance(parameterisation, Mapping):
        return []
    found: list[str] = []
    for block_name, key, _section, _new_key in V1_STATE_MOVES:
        block = parameterisation.get(block_name)
        if isinstance(block, Mapping) and key in block:
            found.append(f"{block_name}.{key}")
    cell = parameterisation.get("Cell")
    if isinstance(cell, Mapping) and THERMAL_CONDUCTIVITY in cell:
        found.append(f"Cell.{THERMAL_CONDUCTIVITY}")
    return found


def is_v0_layout(document: Mapping[str, Any]) -> bool:
    """Whether ``document`` uses the v0.x layout: it declares a 0.x version or holds an old field."""
    header = document.get("Header")
    declared = header.get("BPX") if isinstance(header, Mapping) else None
    parts = version_tuple(declared)
    return (bool(parts) and parts[0] < 1) or bool(v0_layout_fields(document))


def _json_kind(value: Any) -> str:
    """How a JSON value reads in an error message: null, an array, a string, ..."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, (list, tuple)):
        return "an array"
    return f"a {type(value).__name__}"


def _object_at(container: dict[str, Any], key: str, where: str, why: str) -> dict[str, Any]:
    value = container.setdefault(key, {})
    if not isinstance(value, dict):
        raise ValueError(
            f"BPX {where} is {_json_kind(value)}, not an object, so {why}. "
            f"Make {where} an object (or remove it) and try again."
        )
    return value


def _checked_target(target_version: str) -> str:
    parts = version_tuple(target_version)
    if (
        not isinstance(target_version, str)
        or len(parts) < 2
        or parts[0] != 1
        or ".".join(map(str, parts)) != target_version
    ):
        raise ValueError(
            "the v1 layout is written as a 1.x version such as '1.1.0'; "
            f"target_version is {target_version!r}."
        )
    return target_version


def _number_text(value: Any) -> str:
    return json.dumps(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else repr(value)


def to_v1_layout(
    document: Mapping[str, Any], target_version: str = DEFAULT_TARGET_VERSION
) -> tuple[dict[str, Any], list[str]]:
    """Rewrite a v0.x-layout BPX document in the v1 layout: ``(new document, changes)``.

    A document uses the v0.x layout when it declares a 0.x version or holds a
    field in an old place (a temperature in Cell, the initial concentration
    in Electrolyte, a thermal conductivity in Cell), whatever version it
    declares. Such a document comes back with those fields moved into State
    (thermal conductivity into User-defined), the State values the bpx
    package's migration adds when absent added, and ``Header.BPX`` set to
    ``target_version`` (a 1.x version). Every move, every added value and the
    header change is one entry in ``changes``.

    A document already in the v1 layout comes back unchanged with no
    changes, its declared version kept. The input is never mutated. A value
    set both in State and in its old place is refused unless the two are
    equal, and so is a document declaring a major version beyond 1 that
    holds old fields: there is no right answer to pick.
    """
    if not isinstance(document, Mapping):
        raise ValueError(f"a BPX document is a JSON object, not {_json_kind(document)}.")
    out: dict[str, Any] = copy.deepcopy(dict(document))
    header = out.get("Header")
    if not isinstance(header, dict):
        raise ValueError("BPX document has no Header block.")
    declared = header.get("BPX")
    declared_parts = version_tuple(declared)
    if not declared_parts:
        raise ValueError(f"BPX Header.BPX {declared!r} is not a version number.")
    target = _checked_target(target_version)
    if not is_v0_layout(out):
        return out, []
    if declared_parts[0] > 1:
        raise ValueError(
            f"BPX {declared} declares a version newer than the 1.x layout this conversion knows, "
            f"yet holds v0.x fields ({', '.join(v0_layout_fields(out))}); refusing to guess."
        )

    changes: list[str] = []
    parameterisation = out.get("Parameterisation")
    if parameterisation is None:
        parameterisation = {}
    if not isinstance(parameterisation, dict):
        raise ValueError(f"BPX Parameterisation is {_json_kind(parameterisation)}, not an object.")
    cell = parameterisation.get("Cell")
    reference = cell.get(_REFERENCE_TEMPERATURE) if isinstance(cell, dict) else None

    state = _object_at(out, "State", "State", "the State values cannot be written into it")
    for block_name, key, section, new_key in V1_STATE_MOVES:
        block = parameterisation.get(block_name)
        if not isinstance(block, dict) or key not in block:
            continue
        target_section = _object_at(
            state, section, f"State.{section}", f"{block_name}.{key} cannot move into it"
        )
        value = block.pop(key)
        if new_key in target_section:
            if target_section[new_key] != value:
                raise ValueError(
                    f"BPX State.{section}.{new_key} is {_number_text(target_section[new_key])} and "
                    f"{block_name}.{key} is {_number_text(value)}; refusing to choose between them."
                )
            changes.append(f"{block_name}.{key} dropped: State.{section}.{new_key} holds the same value")
            continue
        target_section[new_key] = value
        changes.append(f"{block_name}.{key} -> State.{section}.{new_key}")

    if isinstance(cell, dict) and THERMAL_CONDUCTIVITY in cell:
        user_defined = _object_at(
            parameterisation,
            "User-defined",
            "User-defined",
            f"Cell.{THERMAL_CONDUCTIVITY} cannot move into it",
        )
        value = cell.pop(THERMAL_CONDUCTIVITY)
        if THERMAL_CONDUCTIVITY not in user_defined:
            user_defined[THERMAL_CONDUCTIVITY] = value
            changes.append(f"Cell.{THERMAL_CONDUCTIVITY} -> User-defined.{THERMAL_CONDUCTIVITY}")
        elif user_defined[THERMAL_CONDUCTIVITY] == value:
            changes.append(
                f"Cell.{THERMAL_CONDUCTIVITY} dropped: User-defined already holds the same value"
            )
        else:
            raise ValueError(
                f"BPX Cell.{THERMAL_CONDUCTIVITY} is {_number_text(value)} but User-defined holds "
                f"{_number_text(user_defined[THERMAL_CONDUCTIVITY])} under the same key; refusing to "
                "choose between them."
            )

    # The State values a v1 file states and the v0.x layout has no field for,
    # resolved the way bpx.convert_v0_to_v1 resolves them.
    initial = _object_at(state, _INITIAL, f"State.{_INITIAL}", "the initial conditions cannot be written")
    thermal = _object_at(state, _THERMAL, f"State.{_THERMAL}", "the ambient temperature cannot be written")
    if _SOC not in initial:
        initial[_SOC] = 1
        changes.append(f"added State.{_INITIAL}.{_SOC} = 1 (the v0.x layout states none)")
    if _AMBIENT_TEMPERATURE not in thermal:
        if reference is not None:
            thermal[_AMBIENT_TEMPERATURE] = reference
            why = f"Cell.{_REFERENCE_TEMPERATURE}"
        else:
            thermal[_AMBIENT_TEMPERATURE] = _DEFAULT_TEMPERATURE_K
            why = "no ambient or reference temperature in the file"
        changes.append(
            f"added State.{_THERMAL}.{_AMBIENT_TEMPERATURE} = "
            f"{_number_text(thermal[_AMBIENT_TEMPERATURE])} ({why})"
        )
    if _INITIAL_TEMPERATURE not in initial:
        initial[_INITIAL_TEMPERATURE] = thermal[_AMBIENT_TEMPERATURE]
        changes.append(
            f"added State.{_INITIAL}.{_INITIAL_TEMPERATURE} = "
            f"{_number_text(initial[_INITIAL_TEMPERATURE])} (the ambient temperature)"
        )
    out["State"] = _ordered_state(state)

    if header.get("BPX") != target:
        changes.append(f"Header.BPX {json.dumps(declared)} -> {json.dumps(target)}")
        header["BPX"] = target
    return out, changes


def _ordered_state(state: dict[str, Any]) -> dict[str, Any]:
    """State with its sections and known keys in the order the bpx migration writes them."""
    ordered: dict[str, Any] = {}
    for section in (*_SECTION_ORDER, *(s for s in state if s not in _SECTION_ORDER)):
        if section not in state:
            continue
        fields = state[section]
        known = _KEY_ORDER.get(section, ())
        if isinstance(fields, dict):
            fields = {
                key: fields[key]
                for key in (*known, *(k for k in fields if k not in known))
                if key in fields
            }
        ordered[section] = fields
    return ordered
