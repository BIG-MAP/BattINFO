"""Electrode kinds: the active-material axis of the electrode model.

The material model describes the powder; the electrode model describes the
electrode. An ``electrode-spec`` therefore does not re-declare a chemistry of its
own — it names the **active material kind** from the same curated
:mod:`battinfo.materials` vocabulary the powder uses, so a graphite anode built
from an unknown supplier's powder and one built from an authored material-spec
aggregate on the same axis.

That is the point of making ``kind`` required but ``active_material_spec_id``
optional: a purchased electrode whose powder provenance nobody knows is still a
first-class, queryable record.

Polarity is *derived* from the kind's family (``active_cathode`` -> positive,
``active_anode`` -> negative) rather than authored twice, so a record cannot
claim an LFP anode by typo.
"""

from __future__ import annotations

import re
from typing import Any

# The one load-bearing role in the kind vocabulary. A kind without it (a
# binder, a salt) is a semantic warning as an electrode kind, not a hard
# error — tolerant import beats a rejected record. Roles are informative and
# system-relative; in particular the vocabulary does NOT encode which side an
# active material sits on (graphite is the positive electrode of every
# lithium-counter half cell), so polarity is authored on the electrode or
# implied by the cell, never derived from the kind.
ACTIVE_MATERIAL_ROLE = "active_material"

#: Polarity -> the EMMO electrode-side class stacked onto an electrode node's
#: ``@type``. Lives here, in a leaf module, so the JSON-LD emitter and the JSON-LD
#: term validator read ONE table: the validator can never reject a type the
#: emitter produces.
ELECTRODE_POLARITY_TYPES: dict[str, str] = {
    "positive": "PositiveElectrode",
    "negative": "NegativeElectrode",
}

#: Electrode processing routes. Unlike a material lot's ``processing`` (which is
#: an instance property — the same powder can be carbon-coated or not), an
#: electrode's route is part of the DESIGN: an aqueous-processed electrode is a
#: different spec from an NMP-processed one, and the identity seed says so.
PROCESSING_ROUTES: tuple[str, ...] = ("aqueous", "nmp", "dry", "other")

#: Electrode ROLE -> the relation a cell uses to name the electrode playing it.
#: Role is assigned by the cell, not carried by the electrode: the same disc is a
#: working electrode in one build and a counter electrode in another, so the
#: relation belongs to the cell that placed it.
ELECTRODE_ROLE_RELATIONS: dict[str, str] = {
    "working": "hasWorkingElectrode",
    "counter": "hasCounterElectrode",
}

#: Cell configurations with no polarity to assign. Their electrodes are named by
#: role instead (upstream ruling, BIG-MAP/BattINFO#345). Written in both the
#: underscore form the schema enum uses and the hyphenated form the entity map is
#: keyed on, because both spellings reach this table.
ROLELESS_CONFIGURATIONS: frozenset[str] = frozenset(
    {"half_cell", "half-cell", "three_electrode_cell", "three-electrode-cell", "three-electrode"}
)

#: The configurations in which one electrode closes the circuit AND serves as the
#: potential reference, so the counter electrode carries both role classes.
_HALF_CELL_CONFIGURATIONS: frozenset[str] = frozenset({"half_cell", "half-cell"})


def normalize_cell_configuration(value: Any) -> str | None:
    """Lower-cased, hyphenated cell configuration, or ``None``.

    ``"Half Cell"``, ``"half_cell"`` and ``"half-cell"`` all read as
    ``"half-cell"``, so a configuration written in any of the spellings the stack
    carries (schema enum, entity-map key, free text) reaches the same rule.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    return re.sub(r"[\s_,/]+", "-", value.strip().lower())


def electrode_role_types(role: str, configuration: Any = None) -> list[str]:
    """EMMO ``@type`` classes for an electrode placed in *role* by a cell.

    ``"working"`` is always ``WorkingElectrode``. ``"counter"`` is
    ``CounterElectrode``, plus ``ReferenceElectrode`` in a half cell: a half cell
    has no third electrode, so its counter electrode IS its reference (the
    ``HalfCellDevice`` axiom, and why the three role classes are non-disjoint
    upstream). That is a second class on the one electrode, never a second
    electrode.

    The single implementation of that rule. The cell-spec holder emitter, the
    cell-instance emitters and the deposit-graph builder all call it, so a cell
    cannot say one thing about its counter electrode in one artifact and another
    thing in the next.
    """
    if role == "working":
        return ["WorkingElectrode"]
    if role != "counter":
        raise ValueError(
            f"Unknown electrode role {role!r}. Known roles: {sorted(ELECTRODE_ROLE_RELATIONS)}."
        )
    if normalize_cell_configuration(configuration) in _HALF_CELL_CONFIGURATIONS:
        return ["CounterElectrode", "ReferenceElectrode"]
    return ["CounterElectrode"]


def electrode_role_link(role: str, electrode_id: str, configuration: Any = None) -> dict[str, Any]:
    """A cell's reference to the physical electrode it built into *role*.

    A linked node, not an inline copy: the ``@id`` is the electrode record's own
    IRI, so the electrode's chemistry, design link and as-built values stay on the
    electrode record and merge onto this node by ``@id``. The ``@type`` here is the
    role the cell assigned — the one thing the electrode record cannot know.
    """
    types = electrode_role_types(role, configuration)
    return {"@id": electrode_id, "@type": types[0] if len(types) == 1 else types}


def electrode_kind_keys() -> list[str]:
    """Sorted active-material kind keys — the values ``electrode_spec.kind`` names.

    A subset of :func:`battinfo.materials.material_kind_keys`: the kinds whose
    roles include ``active_material``. Any material kind resolves on input
    (tolerant), but only these are *meaningful* for an electrode, so they are
    what the error messages and docs advertise.
    """
    from battinfo.materials import material_kinds

    kinds = material_kinds().get("kinds", {})
    return sorted(
        key for key, entry in kinds.items() if ACTIVE_MATERIAL_ROLE in (entry.get("roles") or ())
    )


def resolve_electrode_kind(value: Any) -> str | None:
    """Resolve an electrode ``kind`` to its canonical material-kind key, or ``None``.

    Delegates to the material vocabulary so every alias the powder accepts
    ("Si/Gr", "NMC 811", "LiFePO4") also works when naming an electrode.
    """
    from battinfo.materials import resolve_material_kind

    return resolve_material_kind(value)


def electrode_kind(value: Any) -> dict[str, Any] | None:
    """Vocabulary entry for an electrode kind (label, roles, formula, chemsub,
    emmo, aliases, …), or ``None`` for an unknown kind.

    Deliberately carries no polarity: which side an active material sits on is
    a fact about the cell it is built into, not about the material.
    """
    from battinfo.materials import material_kind

    entry = material_kind(value)
    if entry is None:
        return None
    return dict(entry)


def is_active_kind(value: Any) -> bool:
    """True when *value* resolves to a kind in the active-material family."""
    entry = electrode_kind(value)
    return entry is not None and ACTIVE_MATERIAL_ROLE in (entry.get("roles") or ())
