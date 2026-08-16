"""Bridge between embedded material holders and standalone material-spec records.

A cell-spec embeds materials inline (``positive_electrode.coating.component``,
``electrolyte.salt`` / ``solvent_mixture`` / ``additive``, ``separator``). The
standalone ``material-spec`` record type is the reusable, IRI-addressable form.
These helpers convert between the two so a material can be authored once and
referenced from many cells (dedup), without rewiring the cell-spec fleet.
"""

from __future__ import annotations

import json
import warnings
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Mapping

from battinfo._workspace import _stable_uid

# ── Level 1: MaterialKind vocabulary ────────────────────────────────────────────
#
# Kinds are a shipped, versioned, curated vocabulary (governed by PR), NOT a
# user-authored record type — the genome's cross-dataset promise requires every
# publisher to converge on ONE identifier for "graphite". A material-spec's
# required ``kind`` resolves through here (aliases included); an unresolvable kind
# is a save-time error listing the valid keys, the same UX as any controlled field.


def _load_material_kinds_file() -> dict[str, Any]:
    packaged_path = resources.files("battinfo").joinpath("data", "vocab", "material_kinds.json")
    if packaged_path.is_file():
        with packaged_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    repo_root = Path(__file__).resolve().parents[2]
    asset_path = repo_root.joinpath("src", "battinfo", "data", "vocab", "material_kinds.json")
    if asset_path.is_file():
        with asset_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    return {"version": "0", "families": [], "kinds": {}}


@lru_cache(maxsize=1)
def _material_kinds_data() -> dict[str, Any]:
    return _load_material_kinds_file()


@lru_cache(maxsize=1)
def _material_kind_alias_index() -> dict[str, str]:
    """Map every lowercased key/label/alias to its canonical kind key."""
    index: dict[str, str] = {}
    kinds = _material_kinds_data().get("kinds", {})
    for key, entry in kinds.items():
        index[key.lower()] = key
        label = entry.get("label")
        if isinstance(label, str) and label.strip():
            index.setdefault(label.strip().lower(), key)
        for alias in entry.get("aliases", []) or []:
            if isinstance(alias, str) and alias.strip():
                index.setdefault(alias.strip().lower(), key)
    return index


def material_kinds() -> dict[str, Any]:
    """Return the curated MaterialKind vocabulary (Level 1), as a deep copy.

    Shape: ``{"version", "families": [...], "kinds": {"<key>": {"label",
    "family", "formula"?, "chemsub"?, "emmo"?, "aliases": [...],
    "reference_properties"?}}}``. ``chemsub`` is the material's canonical
    semantic identity — its chemical-substance domain-ontology class IRI.
    """
    import copy

    return copy.deepcopy(_material_kinds_data())


def material_kind_keys() -> list[str]:
    """Sorted list of canonical MaterialKind keys (the valid ``kind`` values)."""
    return sorted(_material_kinds_data().get("kinds", {}))


def resolve_material_kind(value: Any) -> str | None:
    """Resolve a kind key / label / alias to its canonical key, or ``None``.

    Case-insensitive; tolerant of the aliases in the vocabulary ("NMC 811",
    "LiNi0.8Mn0.1Co0.1O2", "Si/Gr"). Returns ``None`` for an unknown value so
    callers can raise a helpful save-time error.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    return _material_kind_alias_index().get(value.strip().lower())


def material_kind(value: Any) -> dict[str, Any] | None:
    """Return the vocabulary entry for a kind key/alias (with its canonical key), or ``None``."""
    key = resolve_material_kind(value)
    if key is None:
        return None
    entry = dict(_material_kinds_data()["kinds"][key])
    entry["key"] = key
    return entry


# ── External identity anchors ──────────────────────────────────────────────────
#
# A kind's ``chemsub`` class is its EMMO identity; these are the identifiers the
# rest of materials science already uses for the same substance. Resolving them to
# dereferenceable IRIs lets a consumer join a BattINFO material to Wikidata,
# PubChem or the Materials Project without a lookup table.
#
# ``inchikey`` and ``cas_rn`` are carried as literals only: neither has a canonical,
# freely-dereferenceable IRI form, so neither is emitted as ``skos:exactMatch``.
# InChIKeys are also NOT guessed — molecular-species curation is a later pass.
EXTERNAL_ID_IRI_TEMPLATES: dict[str, str] = {
    "wikidata_qid": "http://www.wikidata.org/entity/{}",
    "pubchem_cid": "https://pubchem.ncbi.nlm.nih.gov/compound/{}",
    "mp_id": "https://next-gen.materialsproject.org/materials/{}",
}
EXTERNAL_ID_FIELDS: tuple[str, ...] = ("wikidata_qid", "inchikey", "pubchem_cid", "mp_id", "cas_rn")


def material_kind_exact_match_iris(entry: Mapping[str, Any] | None) -> list[str]:
    """Dereferenceable IRIs for a kind entry's external identity anchors.

    Ordered by :data:`EXTERNAL_ID_IRI_TEMPLATES` so emission is deterministic.
    Absent anchors yield nothing — an anchor is only ever present when verified.
    """
    if not isinstance(entry, Mapping):
        return []
    iris: list[str] = []
    for field, template in EXTERNAL_ID_IRI_TEMPLATES.items():
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            iris.append(template.format(value.strip()))
    return iris

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
    # Role holders carry no polarity: a half cell or a three-electrode cell has
    # none to assign, so their active materials are extracted with "none" rather
    # than a guessed side.
    for electrode_key, polarity in (
        ("positive_electrode", "positive"),
        ("negative_electrode", "negative"),
        ("working_electrode", "none"),
        ("counter_electrode", "none"),
    ):
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
