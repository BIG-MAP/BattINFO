"""Bridge between inline cell-spec component holders and standalone component-specs.

A cell-spec may inline its components (``positive_electrode``/``negative_electrode`` for a
full cell, ``working_electrode``/``counter_electrode`` for a half or three-electrode cell,
``electrolyte``, ``separator``, ``housing``) or reference standalone component-specs by
IRI (``*_spec_id``). These helpers lift the inline holders into standalone
``electrode-spec``/``electrolyte-spec``/``separator-spec``/``housing-spec`` records so a
component can be authored once and referenced from many cells (dedup) — the symmetric
counterpart of :func:`battinfo.materials.extract_material_specs`.

An electrode holder lifts through the electrode-spec builder
(``create_electrode_spec``), so it gets the IRI the builder gives the same
identity. The other families mint from a seed of the holder's name, or of the
cell and the holder's place in it.
"""

from __future__ import annotations

from typing import Any, Mapping

from battinfo.entities import seed_text, stable_uid

# Holder fields the electrode-spec builder takes as its own arguments: the ones
# its identity seed reads (manufacturer, product, grade, processing route) and the
# organizations it normalises. The rest of the holder is passed through as body.
_ELECTRODE_SPEC_FIELDS = ("manufacturer", "supplier", "product_id", "grade", "processing")

# (cell-spec holder key, component family, human label)
_HOLDER_FAMILIES = (
    ("positive_electrode", "electrode", "positive electrode"),
    ("negative_electrode", "electrode", "negative electrode"),
    # Role holders, for a half cell or a three-electrode cell.
    ("working_electrode", "electrode", "working electrode"),
    ("counter_electrode", "electrode", "counter electrode"),
    ("electrolyte", "electrolyte", "electrolyte"),
    ("separator", "separator", "separator"),
    ("housing", "housing", "housing"),
)


def component_spec_from_holder(
    family: str, holder: Mapping[str, Any], *, name: str, uid_seed: str | None = None
) -> dict[str, Any]:
    """Lift an inline component holder to a standalone component-spec record.

    An electrode holder goes through ``create_electrode_spec``: its IRI is the
    one the builder mints for the same identity (producer, product, grade,
    active-material kind, processing route), and its active-material kind is
    read from the coating's first active material when the vocabulary resolves
    it. Any other family's IRI is minted deterministically from *uid_seed* (or
    the name), so the same holder lifts to the same spec IRI across cells and
    the specs de-duplicate. *uid_seed* also pins an electrode's IRI when given.
    """
    if family == "electrode":
        return _electrode_spec_from_holder(holder, name=name, uid_seed=uid_seed)

    from battinfo.api import create_component_spec

    body = {k: v for k, v in holder.items() if k != "name"}
    return create_component_spec(
        family,
        name=name,
        body=body,
        uid=stable_uid(uid_seed or f"{family}-spec:{seed_text(name).lower()}"),
        validate=False,
    )


def _first_active_material_kind(holder: Mapping[str, Any]) -> str | None:
    """The electrode kind of the coating's first active material, when the vocabulary resolves it."""
    from battinfo.electrodes import resolve_electrode_kind

    coating = holder.get("coating")
    component = coating.get("component") if isinstance(coating, Mapping) else None
    active = component.get("active_material") if isinstance(component, Mapping) else None
    first = active[0] if isinstance(active, list) and active else active
    name = first.get("name") if isinstance(first, Mapping) else None
    return resolve_electrode_kind(name) if isinstance(name, str) else None


def _electrode_spec_from_holder(holder: Mapping[str, Any], *, name: str, uid_seed: str | None) -> dict[str, Any]:
    from battinfo.api import create_electrode_spec

    fields: dict[str, Any] = {key: holder[key] for key in _ELECTRODE_SPEC_FIELDS if holder.get(key) is not None}
    body = {k: v for k, v in holder.items() if k != "name" and k not in fields}
    if uid_seed:
        fields["uid"] = stable_uid(uid_seed)
    return create_electrode_spec(
        validate=False,
        name=name,
        active_material_kind=_first_active_material_kind(holder),
        body=body or None,
        **fields,
    )


def extract_component_specs(cell_spec_record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract standalone component-spec records from a cell-spec's inline holders.

    Returns one component-spec per inline holder present
    (positive/negative electrode, electrolyte, separator, housing).
    """
    cell = cell_spec_record.get("cell_spec", {})
    base = cell.get("name") or cell.get("model") or "cell" if isinstance(cell, Mapping) else "cell"
    out: list[dict[str, Any]] = []
    for holder_key, family, label in _HOLDER_FAMILIES:
        holder = cell_spec_record.get(holder_key)
        if isinstance(holder, Mapping) and holder:
            name = holder.get("name") or f"{base} {label}"
            # An electrode mints through its builder's identity; the other
            # families from the cell and the holder's place in it.
            uid_seed = None if family == "electrode" else f"{family}-spec:{seed_text(base)}:{label}"
            out.append(component_spec_from_holder(family, holder, name=name, uid_seed=uid_seed))
    return out
