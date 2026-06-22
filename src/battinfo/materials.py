"""Bridge between embedded material holders and standalone material-spec records.

A cell-spec embeds materials inline (``positive_electrode.coating.component``,
``electrolyte.salt`` / ``solvent_mixture`` / ``additive``, ``separator``). The
standalone ``material-spec`` record type is the reusable, IRI-addressable form.
These helpers convert between the two so a material can be authored once and
referenced from many cells (dedup), without rewiring the cell-spec fleet.
"""

from __future__ import annotations

import warnings
from typing import Any, Mapping

from battinfo._workspace import _stable_uid

# Cell-cell-specific composition fractions are not intrinsic material properties,
# so they are dropped when lifting an embedded holder to a standalone spec.
_CELL_LOCAL_PROPERTY_KEYS = {"mass_fraction", "volume_fraction", "weight_fraction"}


def _component_dict(component: Any) -> dict[str, Any]:
    if hasattr(component, "model_dump"):
        return {k: v for k, v in component.model_dump().items() if v is not None}
    if isinstance(component, Mapping):
        return dict(component)
    raise TypeError("component must be a MaterialComponent or mapping")


def _as_material_list(value: Any) -> list:
    """Normalise a material group to a list, tolerating a single embedded mapping.

    Authoring a one-material group as a bare dict (``component={"active_material":
    {"name": "LFP"}}``) instead of a list previously iterated the dict's *keys*,
    silently dropping the material. Wrap a lone mapping into a one-element list.
    """
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list):
        return value
    return []


def _intrinsic_property(prop: Any) -> dict[str, Any]:
    # Tolerate a single-element list wrapping the property mapping rather than
    # silently dropping it.
    if isinstance(prop, list) and len(prop) == 1 and isinstance(prop[0], Mapping):
        prop = prop[0]
    if not isinstance(prop, Mapping):
        return {}
    return {k: v for k, v in prop.items() if k not in _CELL_LOCAL_PROPERTY_KEYS}


def material_spec_from_component(
    component: Any,
    *,
    material_class: str | None = None,
    electrode_polarity: str | None = None,
    uid_seed: str | None = None,
) -> dict[str, Any]:
    """Lift an embedded material holder to a standalone material-spec record.

    The IRI is minted deterministically from the material name (or *uid_seed*),
    so the same material lifts to the same spec IRI across cells — enabling dedup.
    Cell-local composition fractions are dropped; intrinsic properties are kept.
    """
    from battinfo.api import create_material_spec

    holder = _component_dict(component)
    name = holder.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("component must have a non-empty name")

    fields: dict[str, Any] = {
        "uid": _stable_uid(uid_seed or f"material-spec:{name.strip().lower()}"),
        "name": name,
        "property": _intrinsic_property(holder.get("property")),
    }
    if holder.get("molecular_formula"):
        fields["formula"] = holder["molecular_formula"]
    for key in ("manufacturer", "supplier", "product_id"):
        if holder.get(key):
            fields[key] = holder[key]
    if material_class:
        fields["material_class"] = material_class
    if electrode_polarity:
        fields["electrode_polarity"] = electrode_polarity
    return create_material_spec(validate=False, **fields)


def link_component_to_spec(component: Any, material_spec_id: str) -> dict[str, Any]:
    """Return a copy of an embedded holder that references a standalone spec by IRI."""
    holder = _component_dict(component)
    holder["material_spec_id"] = material_spec_id
    return holder


def _iter_embedded_materials(cell_spec_record: Mapping[str, Any]):
    """Yield (holder_dict, material_class, electrode_polarity) for every embedded material."""
    data = cell_spec_record
    # Electrode coatings: active_material / binder / additive
    group_class = {
        "active_material": "active_material",
        "binder": "binder",
        "additive": "conductive_additive",
    }
    for electrode_key, polarity in (("positive_electrode", "positive"), ("negative_electrode", "negative")):
        electrode = data.get(electrode_key)
        if not isinstance(electrode, Mapping):
            continue
        coating = electrode.get("coating")
        component = coating.get("component") if isinstance(coating, Mapping) else None
        if isinstance(component, Mapping):
            for group, mclass in group_class.items():
                for item in _as_material_list(component.get(group)):
                    if isinstance(item, Mapping) and item.get("name"):
                        pol = polarity if group == "active_material" else "none"
                        yield item, mclass, pol
        collector = electrode.get("current_collector")
        if isinstance(collector, Mapping) and collector.get("name"):
            yield collector, "current_collector", "none"

    electrolyte = data.get("electrolyte")
    if isinstance(electrolyte, Mapping):
        salt = electrolyte.get("salt")
        if isinstance(salt, Mapping) and salt.get("name"):
            yield salt, "electrolyte_salt", "none"
        solvent_mixture = electrolyte.get("solvent_mixture")
        if isinstance(solvent_mixture, Mapping):
            for item in _as_material_list(solvent_mixture.get("component")):
                if isinstance(item, Mapping) and item.get("name"):
                    yield item, "electrolyte_solvent", "none"
        for item in _as_material_list(electrolyte.get("additive")):
            if isinstance(item, Mapping) and item.get("name"):
                yield item, "electrolyte_additive", "none"

    separator = data.get("separator")
    if isinstance(separator, Mapping) and isinstance(separator.get("material"), str):
        yield {"name": separator["material"]}, "separator_material", "none"


def extract_material_specs(cell_spec_record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract de-duplicated standalone material-spec records from a cell-spec record.

    Walks electrode coatings, the electrolyte, and the separator, lifting each
    embedded material to a material-spec. Materials are de-duplicated by name
    (case-insensitive), so a material shared across electrodes yields one spec.
    """
    seen: dict[str, dict[str, Any]] = {}
    seen_identity: dict[str, tuple[Any, dict[str, Any]]] = {}
    for holder, mclass, polarity in _iter_embedded_materials(cell_spec_record):
        key = str(holder["name"]).strip().lower()
        identity = (holder.get("molecular_formula"), _intrinsic_property(holder.get("property")))
        if key in seen:
            # Name-based dedup is intentional (e.g. "Graphite"/"graphite" → one spec),
            # but two materials that share a name yet differ in formula / intrinsic
            # properties are genuinely distinct — surface that rather than silently
            # dropping one's data.
            if identity != seen_identity[key]:
                warnings.warn(
                    f"extract_material_specs: multiple materials named {holder['name']!r} differ in "
                    f"formula/intrinsic properties; keeping the first and dropping the rest. "
                    f"Give them distinct names to retain both.",
                    stacklevel=2,
                )
            continue
        seen[key] = material_spec_from_component(
            holder, material_class=mclass, electrode_polarity=polarity
        )
        seen_identity[key] = identity
    return list(seen.values())
