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

from typing import Any

# Kind families that name an ACTIVE material, and the electrode polarity each
# implies. A kind outside these families (a binder, a salt) is a semantic
# warning, not a hard error — tolerant import beats a rejected record.
ACTIVE_KIND_FAMILIES: dict[str, str] = {
    "active_cathode": "positive",
    "active_anode": "negative",
}

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


def electrode_kind_keys() -> list[str]:
    """Sorted active-material kind keys — the values ``electrode_spec.kind`` names.

    A subset of :func:`battinfo.materials.material_kind_keys`: the kinds whose
    family is an active-material family. Any material kind resolves on input
    (tolerant), but only these are *meaningful* for an electrode, so they are
    what the error messages and docs advertise.
    """
    from battinfo.materials import material_kinds

    kinds = material_kinds().get("kinds", {})
    return sorted(
        key for key, entry in kinds.items() if entry.get("family") in ACTIVE_KIND_FAMILIES
    )


def resolve_electrode_kind(value: Any) -> str | None:
    """Resolve an electrode ``kind`` to its canonical material-kind key, or ``None``.

    Delegates to the material vocabulary so every alias the powder accepts
    ("Si/Gr", "NMC 811", "LiFePO4") also works when naming an electrode.
    """
    from battinfo.materials import resolve_material_kind

    return resolve_material_kind(value)


def electrode_kind(value: Any) -> dict[str, Any] | None:
    """Vocabulary entry for an electrode kind, with its derived ``polarity``.

    Returns the material-kind entry (label, family, formula, chemsub, emmo,
    aliases, …) plus ``polarity``, which is ``"positive"``/``"negative"`` for an
    active family and ``None`` otherwise.
    """
    from battinfo.materials import material_kind

    entry = material_kind(value)
    if entry is None:
        return None
    resolved = dict(entry)
    resolved["polarity"] = ACTIVE_KIND_FAMILIES.get(str(entry.get("family")))
    return resolved


def electrode_polarity_for_kind(value: Any) -> str | None:
    """Polarity implied by an electrode kind, or ``None`` when it implies none."""
    entry = electrode_kind(value)
    return entry.get("polarity") if entry is not None else None


def is_active_kind(value: Any) -> bool:
    """True when *value* resolves to a kind in an active-material family."""
    return electrode_polarity_for_kind(value) is not None
