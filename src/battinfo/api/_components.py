"""Materials and component families: inputs, create/save/query, and generated per-family wrappers.

Split from the former monolithic ``battinfo/api.py`` (beta-hardening 4.2);
import the public surface from ``battinfo.api``, not from this module.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from battinfo._jsonio import read_record_json as _load_json
from battinfo._util import _as_path, _citation_url_value
from battinfo.api._records import _assert_id_matches_uid, save_record
from battinfo.api._shared import (
    DATASET_IRI_RE,
    DEFAULT_REGISTRATION_SOURCE_ROOT,
    DUPLICATE_POLICY_ERROR,
    MATERIAL_IRI_RE,
    MATERIAL_SPEC_IRI_RE,
    REGISTER_MODE_CREATE_ONLY,
    TEMPLATE_UID,
    PathLike,
    _component_iri_re,
    _iri_tail,
    _normalized_dashed_uid,
    _paginate,
    _query_record_files,
    _resolved_retrieved_at,
    _spec_iri_re,
    _str_eq,
    _to_unix_time,
    _validate_canonical_record,
)
from battinfo.bundle import (
    SCHEMA_VERSION,
    stamp_provenance,
)
from battinfo.canonical_aliases import record_to_snake_aliases
from battinfo.entities import (
    COMPONENT_FAMILIES,
)
from battinfo.validate.core import DEFAULT_POLICY, ValidationPolicy


class MaterialSpecInput(BaseModel):
    """Typed input for saving a new canonical material-spec resource."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    id: str | None = None
    uid: str | None = None
    name: str
    kind: str | None = None
    grade: str | None = None
    material_class: str | None = None
    electrode_polarity: str | None = None
    formula: str | None = None
    chemistry_family: str | None = None
    emmo_type: str | None = None
    cas_number: str | None = None
    manufacturer: str | dict[str, Any] | None = None
    supplier: str | dict[str, Any] | None = None
    product_id: str | None = None
    composition: dict[str, Any] | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None
    source_type: Literal["datasheet", "manufacturer", "measurement", "lab", "literature", "manual", "other"] = "datasheet"
    source_url: str | None = None
    citation: str | None = Field(default=None, validation_alias=AliasChoices("citation", "citation_doi"))
    retrieved_at: int | str | None = None
    notes: list[str] = Field(default_factory=list)


class MaterialInput(BaseModel):
    """Typed input for saving a new canonical material (instance) resource."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    id: str | None = None
    uid: str | None = None
    material_spec_id: str
    name: str | None = None
    lot_id: str | None = Field(default=None, validation_alias=AliasChoices("lot_id", "lot"))
    batch_id: str | None = None
    supplier: str | dict[str, Any] | None = None
    received_date: int | str | None = None
    opened_date: int | str | None = None
    expires_at: int | str | None = None
    amount: dict[str, Any] | None = None
    storage: str | None = None
    processing: dict[str, Any] | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    property: dict[str, Any] = Field(default_factory=dict)
    source_type: Literal["datasheet", "manufacturer", "measurement", "lab", "literature", "manual", "other"] = "lab"
    source_url: str | None = None
    citation: str | None = Field(default=None, validation_alias=AliasChoices("citation", "citation_doi"))
    retrieved_at: int | str | None = None
    notes: list[str] = Field(default_factory=list)


class ElectrodeSpecInput(BaseModel):
    """Typed input for saving a new canonical electrode-spec resource.

    The coated electrode as a designed artifact. ``kind`` names the ACTIVE
    material (from the curated material-kind vocabulary) and is required;
    ``active_material_spec_id`` is optional, so a purchased electrode whose
    powder provenance is unknown is still expressible.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    id: str | None = None
    uid: str | None = None
    name: str
    kind: str | None = None
    polarity: str | None = None
    grade: str | None = None
    active_material_spec_id: str | None = None
    # Composition. ``composition=`` is the authoring shorthand
    # ({"active": 0.96, "binder": 0.02, "additive": 0.02}); it is expanded into the
    # canonical ``coating.component`` shape a cell-spec already uses, so nothing
    # divergent is ever stored.
    coating: dict[str, Any] | None = None
    composition: dict[str, Any] | None = None
    current_collector: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("current_collector", "collector")
    )
    tab: dict[str, Any] | None = None
    processing: dict[str, Any] | None = None
    manufacturer: str | dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("manufacturer", "producer")
    )
    supplier: str | dict[str, Any] | None = None
    product_id: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None
    comment: str | None = None
    # Accepted for continuity with the generic component API this family
    # graduated from: a raw holder body merged under the explicit fields.
    body: dict[str, Any] | None = None
    source_type: Literal["datasheet", "manufacturer", "measurement", "lab", "literature", "manual", "other"] = "datasheet"
    source_url: str | None = None
    citation: str | None = Field(default=None, validation_alias=AliasChoices("citation", "citation_doi"))
    retrieved_at: int | str | None = None
    notes: list[str] = Field(default_factory=list)


class ElectrodeInput(BaseModel):
    """Typed input for saving a new canonical electrode (instance) resource.

    A physical batch realizing an electrode-spec. As-built actuals go in the OPEN
    ``property`` map — no closed vocabulary.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    id: str | None = None
    uid: str | None = None
    electrode_spec_id: str = Field(
        validation_alias=AliasChoices("electrode_spec_id", "spec_id")
    )
    name: str | None = None
    batch_id: str | None = Field(default=None, validation_alias=AliasChoices("batch_id", "batch"))
    lot_id: str | None = Field(default=None, validation_alias=AliasChoices("lot_id", "lot"))
    supplier: str | dict[str, Any] | None = None
    manufactured_at: int | str | None = None
    received_date: int | str | None = None
    expires_at: int | str | None = None
    amount: dict[str, Any] | None = None
    count: int | None = None
    storage: str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None
    body: dict[str, Any] | None = None
    source_type: Literal["datasheet", "manufacturer", "measurement", "lab", "literature", "manual", "other"] = "lab"
    source_url: str | None = None
    citation: str | None = Field(default=None, validation_alias=AliasChoices("citation", "citation_doi"))
    retrieved_at: int | str | None = None
    notes: list[str] = Field(default_factory=list)


def _org_value(value: str | dict[str, Any] | None) -> dict[str, Any] | None:
    """Coerce a manufacturer/supplier input to a structured Organization object."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return {"type": "Organization", "name": text} if text else None
    if isinstance(value, Mapping):
        org: dict[str, Any] = {"type": "Organization"}
        for key in ("name", "id", "url"):
            if value.get(key) is not None:
                org[key] = value[key]
        return org if org.get("name") else None
    return None


def _resolve_kind_or_raise(explicit: str | None, *fallback_names: str | None) -> str | None:
    """Resolve a material ``kind`` to its canonical key.

    An explicit kind that does not resolve is a hard error listing the valid
    keys (the same UX as any controlled field). When no kind is given, fall back
    to resolving the material name/product through the alias table (tolerant
    authoring: ``create_material_spec(name="LFP")`` derives ``kind="lfp"``).
    Returns ``None`` when nothing resolves, so the required-field schema check
    reports the missing kind with the standard message.
    """
    from battinfo.materials import material_kind_keys, resolve_material_kind

    if explicit is not None and str(explicit).strip():
        resolved = resolve_material_kind(explicit)
        if resolved is None:
            raise ValueError(
                f"Unknown material kind {explicit!r}. Valid kinds: "
                f"{', '.join(material_kind_keys())}. "
                "See battinfo.material_kind_keys() / battinfo.material_kinds()."
            )
        return resolved
    for candidate in fallback_names:
        resolved = resolve_material_kind(candidate)
        if resolved is not None:
            return resolved
    return None


def _material_spec_identity_uid(draft: MaterialSpecInput, kind_key: str | None) -> str:
    """Deterministic content-derived uid for a material spec (fixes H1).

    Mirrors the engine's other five types: the IRI is minted from the spec's
    identity — normalized (manufacturer, product, grade) — so re-authoring the
    same product is a no-op, never a duplicate. Lab-synthesized materials use the
    lab as manufacturer and the recipe/batch-family name as product. Processing
    is NOT part of identity. There is no random-id path.
    """
    from battinfo.entities import stable_uid

    org = _org_value(draft.manufacturer)
    manufacturer = (org or {}).get("name") if org else None
    product = draft.product_id or draft.name
    seed = "::".join(
        [
            "material-spec",
            (manufacturer or "unknown-manufacturer").strip().lower(),
            (product or "unknown-product").strip().lower(),
            (draft.grade or "").strip().lower(),
            kind_key or "",
        ]
    )
    return stable_uid(seed)


def _record_from_material_spec(draft: MaterialSpecInput) -> dict[str, Any]:
    kind_key = _resolve_kind_or_raise(draft.kind, draft.name, draft.product_id)
    if draft.id is not None:
        if not MATERIAL_SPEC_IRI_RE.fullmatch(draft.id):
            raise ValueError("material spec id must match https://w3id.org/battinfo/spec/{uid}.")
        if draft.uid is not None:
            _assert_id_matches_uid(draft.id, _normalized_dashed_uid(draft.uid))
        entity_id = draft.id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        # Deterministic identity: an explicit uid is honored; otherwise the uid is
        # derived from the spec's content so a re-run lands on the same IRI.
        dashed_uid = (
            _normalized_dashed_uid(draft.uid)
            if draft.uid is not None
            else _material_spec_identity_uid(draft, kind_key)
        )
        entity_id = f"https://w3id.org/battinfo/spec/{dashed_uid}"

    spec: dict[str, Any] = {
        "id": entity_id,
        "short_id": dashed_uid.replace("-", "")[:6],
        "name": draft.name,
    }
    if kind_key is not None:
        spec["kind"] = kind_key
    if draft.grade is not None:
        spec["grade"] = draft.grade
    for field_name in (
        "material_class",
        "electrode_polarity",
        "formula",
        "chemistry_family",
        "emmo_type",
        "cas_number",
        "product_id",
        "description",
    ):
        value = getattr(draft, field_name)
        if value is not None:
            spec[field_name] = value
    for org_field in ("manufacturer", "supplier"):
        org = _org_value(getattr(draft, org_field))
        if org is not None:
            spec[org_field] = org
    if draft.composition:
        spec["composition"] = draft.composition
    if draft.property:
        spec["property"] = draft.property

    record: dict[str, Any] = {
        "schema_version": draft.schema_version,
        "material_spec": spec,
        "provenance": stamp_provenance({
            "source_type": draft.source_type,
            "retrieved_at": _resolved_retrieved_at(draft.retrieved_at),
        }),
    }
    if draft.source_url is not None:
        record["provenance"]["source_url"] = draft.source_url
    citation = _citation_url_value(draft.citation)
    if citation is not None:
        record["provenance"]["citation"] = citation
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record_to_snake_aliases(record)


def _record_from_material(draft: MaterialInput) -> dict[str, Any]:
    if not MATERIAL_SPEC_IRI_RE.fullmatch(draft.material_spec_id):
        raise ValueError("material_spec_id must match https://w3id.org/battinfo/spec/{uid}.")
    if draft.id is not None:
        if not MATERIAL_IRI_RE.fullmatch(draft.id):
            raise ValueError("material id must match https://w3id.org/battinfo/material/{uid}.")
        if draft.uid is not None:
            _assert_id_matches_uid(draft.id, _normalized_dashed_uid(draft.uid))
        entity_id = draft.id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        # Deterministic identity from (spec_id, lot): re-authoring the same lot is
        # a no-op. An explicit uid is honored; there is no random-id path.
        if draft.uid is not None:
            dashed_uid = _normalized_dashed_uid(draft.uid)
        else:
            from battinfo.entities import stable_uid

            lot = draft.lot_id or draft.batch_id or draft.name or ""
            dashed_uid = stable_uid(
                "::".join(["material", draft.material_spec_id.strip(), lot.strip()])
            )
        entity_id = f"https://w3id.org/battinfo/material/{dashed_uid}"

    material: dict[str, Any] = {
        "id": entity_id,
        "material_spec_id": draft.material_spec_id,
        "short_id": dashed_uid.replace("-", "")[:6],
    }
    for field_name in ("name", "lot_id", "batch_id", "storage"):
        value = getattr(draft, field_name)
        if value is not None:
            material[field_name] = value
    supplier = _org_value(draft.supplier)
    if supplier is not None:
        material["supplier"] = supplier
    for date_field in ("received_date", "opened_date", "expires_at"):
        raw = getattr(draft, date_field)
        if raw is not None:
            converted = _to_unix_time(raw)
            material[date_field] = converted if converted is not None else raw
    if draft.amount is not None:
        material["amount"] = draft.amount
    if draft.processing:
        material["processing"] = draft.processing
    if draft.dataset_ids:
        for dataset_id in draft.dataset_ids:
            if not DATASET_IRI_RE.fullmatch(dataset_id):
                raise ValueError("dataset_ids entries must match https://w3id.org/battinfo/dataset/{uid}.")
        material["datasets"] = [{"id": dataset_id, "role": "raw"} for dataset_id in draft.dataset_ids]
    if draft.property:
        material["property"] = draft.property

    record: dict[str, Any] = {
        "schema_version": draft.schema_version,
        "material": material,
        "provenance": stamp_provenance({
            "source_type": draft.source_type,
            "retrieved_at": _resolved_retrieved_at(draft.retrieved_at),
        }),
    }
    if draft.source_url is not None:
        record["provenance"]["source_url"] = draft.source_url
    citation = _citation_url_value(draft.citation)
    if citation is not None:
        record["provenance"]["citation"] = citation
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record_to_snake_aliases(record)


# ── Electrodes: the coated electrode as a designed artifact ─────────────────────
#
# The material spec describes the powder; the electrode spec describes the
# electrode. These builders mirror the material ones exactly — deterministic
# content-derived identity, a required curated ``kind``, no random-id path — with
# two deliberate differences: the active-material reference is OPTIONAL (so a
# purchased electrode of known chemistry but unknown powder is expressible), and
# the processing route is part of SPEC identity rather than an instance property.

# Authoring shorthand role -> the canonical coating component group.
_COMPOSITION_ROLES: dict[str, str] = {
    "active": "active_material",
    "active_material": "active_material",
    "binder": "binder",
    "additive": "additive",
    "conductive_additive": "additive",
}
_FRACTION_INPUT_KEYS: tuple[str, ...] = ("mass_fraction", "weight_fraction", "fraction", "weight")


def _fraction_quantity(value: Any) -> dict[str, Any] | None:
    """Coerce a weight-fraction input to the canonical dimensionless quantity."""
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"value": value, "unit": "1"}
    return None


def _composition_component(entry: Any, *, default_name: str | None) -> dict[str, Any] | None:
    """One composition entry -> a canonical material-component holder."""
    if isinstance(entry, str):
        return {"name": entry.strip()} if entry.strip() else None
    if isinstance(entry, (int, float)) and not isinstance(entry, bool):
        if not default_name:
            raise ValueError(
                "composition: a bare weight fraction only works where the name can be "
                "derived (the active material, from kind=). Give a name, e.g. "
                'composition={"binder": {"name": "PVDF", "fraction": 0.02}}.'
            )
        quantity = _fraction_quantity(entry)
        return {"name": default_name, "property": {"mass_fraction": quantity}} if quantity else None
    if isinstance(entry, Mapping):
        holder: dict[str, Any] = {}
        name = entry.get("name") or default_name
        if isinstance(name, str) and name.strip():
            holder["name"] = name.strip()
        for key in ("material_spec_id", "manufacturer", "supplier", "product_id",
                    "molecular_formula", "comment"):
            if entry.get(key) is not None:
                holder[key] = entry[key]
        prop = dict(entry.get("property") or {})
        for key in _FRACTION_INPUT_KEYS:
            if entry.get(key) is not None:
                quantity = _fraction_quantity(entry[key])
                if quantity is not None:
                    prop.setdefault("mass_fraction", quantity)
                break
        if prop:
            holder["property"] = prop
        return holder if holder.get("name") else None
    return None


def _coating_from_composition(
    composition: Mapping[str, Any], *, active_name: str | None
) -> dict[str, Any]:
    """Expand the ``composition=`` shorthand into the canonical coating shape.

    The shape is the one a cell-spec's inline electrode coating already uses
    (``component.active_material / binder / additive``, each a material component
    carrying ``property.mass_fraction``) — the shorthand is an authoring
    convenience, never a second stored shape.
    """
    component: dict[str, list[dict[str, Any]]] = {}
    for key, value in composition.items():
        role = _COMPOSITION_ROLES.get(str(key).strip().lower())
        if role is None:
            raise ValueError(
                f"composition: unknown role {key!r}. Valid roles: "
                f"{', '.join(sorted(set(_COMPOSITION_ROLES)))}."
            )
        entries = value if isinstance(value, list) else [value]
        default_name = active_name if role == "active_material" else None
        built = [
            holder for item in entries
            if (holder := _composition_component(item, default_name=default_name)) is not None
        ]
        if built:
            component.setdefault(role, []).extend(built)
    return {"component": component}


def _current_collector_value(value: Any) -> dict[str, Any] | None:
    """Coerce a current-collector input to the canonical holder shape."""
    if isinstance(value, str):
        return {"name": value.strip()} if value.strip() else None
    if not isinstance(value, Mapping):
        return None
    holder: dict[str, Any] = {}
    name = value.get("name") or value.get("material")
    if isinstance(name, str) and name.strip():
        holder["name"] = name.strip()
    for key in ("material", "form", "material_spec_id", "manufacturer", "supplier", "product_id", "comment"):
        if value.get(key) is not None:
            holder[key] = value[key]
    prop = dict(value.get("property") or {})
    if isinstance(value.get("thickness"), Mapping):
        prop.setdefault("thickness", dict(value["thickness"]))
    if prop:
        holder["property"] = prop
    return holder or None


def _resolve_electrode_kind_or_raise(explicit: str | None, *fallback_names: str | None) -> str | None:
    """Resolve an electrode ``kind`` to its canonical key, or raise listing valid keys.

    Mirrors :func:`_resolve_kind_or_raise`: an explicit kind that does not resolve
    is a hard error; with no explicit kind, the name/product is tried through the
    same alias table so ``create_electrode_spec(name="LFP cathode")`` still lands
    a kind. The advertised valid keys are the ACTIVE-material ones — the kinds
    that mean something for an electrode.
    """
    from battinfo.electrodes import electrode_kind_keys, resolve_electrode_kind

    if explicit is not None and str(explicit).strip():
        resolved = resolve_electrode_kind(explicit)
        if resolved is None:
            raise ValueError(
                f"Unknown electrode kind {explicit!r}. Valid kinds: "
                f"{', '.join(electrode_kind_keys())}. "
                "See battinfo.electrodes.electrode_kind_keys()."
            )
        return resolved
    for candidate in fallback_names:
        resolved = resolve_electrode_kind(candidate)
        if resolved is not None:
            return resolved
    return None


def _electrode_spec_identity_uid(draft: ElectrodeSpecInput, kind_key: str | None) -> str:
    """Deterministic content-derived uid for an electrode spec.

    Identity is (producer, product, grade, kind, processing route). The route is
    in the seed because for an electrode it is a design decision, not a build
    detail — see :func:`battinfo.entities.electrode_spec_identity_seed`.
    """
    from battinfo.entities import electrode_spec_identity_seed, stable_uid

    org = _org_value(draft.manufacturer)
    producer = (org or {}).get("name") if org else None
    route = (draft.processing or {}).get("route") if isinstance(draft.processing, Mapping) else None
    return stable_uid(
        electrode_spec_identity_seed(
            producer=producer,
            product=draft.product_id or draft.name,
            grade=draft.grade,
            kind=kind_key,
            route=route if isinstance(route, str) else None,
        )
    )


def _record_from_electrode_spec(draft: ElectrodeSpecInput) -> dict[str, Any]:
    from battinfo.electrodes import electrode_polarity_for_kind

    kind_key = _resolve_electrode_kind_or_raise(draft.kind, draft.name, draft.product_id)
    if draft.id is not None:
        if not _spec_iri_re("electrode-spec").fullmatch(draft.id):
            raise ValueError("electrode spec id must match https://w3id.org/battinfo/spec/{uid}.")
        if draft.uid is not None:
            _assert_id_matches_uid(draft.id, _normalized_dashed_uid(draft.uid))
        entity_id = draft.id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = (
            _normalized_dashed_uid(draft.uid)
            if draft.uid is not None
            else _electrode_spec_identity_uid(draft, kind_key)
        )
        entity_id = f"https://w3id.org/battinfo/spec/{dashed_uid}"

    if draft.active_material_spec_id is not None and not MATERIAL_SPEC_IRI_RE.fullmatch(
        draft.active_material_spec_id
    ):
        raise ValueError(
            "active_material_spec_id must match https://w3id.org/battinfo/spec/{uid}."
        )

    spec: dict[str, Any] = {
        "id": entity_id,
        "short_id": dashed_uid.replace("-", "")[:6],
        "name": draft.name,
    }
    spec.update(draft.body or {})
    if kind_key is not None:
        spec["kind"] = kind_key
    # Polarity is derived from the kind's family when not authored, so a record
    # never has to state the same fact twice (and cannot disagree with itself).
    polarity = draft.polarity or electrode_polarity_for_kind(kind_key)
    if polarity is not None:
        spec["polarity"] = polarity
    for field_name in ("grade", "active_material_spec_id", "product_id", "description", "comment"):
        value = getattr(draft, field_name)
        if value is not None:
            spec[field_name] = value
    if draft.composition:
        active_entry = None
        if kind_key is not None:
            from battinfo.electrodes import electrode_kind  # noqa: PLC0415

            active_entry = electrode_kind(kind_key)
        active_name = (active_entry or {}).get("label") if active_entry else None
        coating = _coating_from_composition(draft.composition, active_name=active_name)
        if draft.active_material_spec_id is not None:
            for holder in coating["component"].get("active_material", []):
                holder.setdefault("material_spec_id", draft.active_material_spec_id)
        existing = dict(spec.get("coating") or {})
        existing_component = dict(existing.get("component") or {})
        existing_component.update(coating["component"])
        existing["component"] = existing_component
        spec["coating"] = existing
    if draft.coating:
        merged = dict(spec.get("coating") or {})
        merged.update(draft.coating)
        spec["coating"] = merged
    collector = _current_collector_value(draft.current_collector)
    if collector is not None:
        spec["current_collector"] = collector
    if draft.tab:
        spec["tab"] = draft.tab
    if draft.processing:
        spec["processing"] = dict(draft.processing)
    for org_field in ("manufacturer", "supplier"):
        org = _org_value(getattr(draft, org_field))
        if org is not None:
            spec[org_field] = org
    if draft.property:
        spec["property"] = draft.property

    record: dict[str, Any] = {
        "schema_version": draft.schema_version,
        "electrode_spec": spec,
        "provenance": stamp_provenance({
            "source_type": draft.source_type,
            "retrieved_at": _resolved_retrieved_at(draft.retrieved_at),
        }),
    }
    if draft.source_url is not None:
        record["provenance"]["source_url"] = draft.source_url
    citation = _citation_url_value(draft.citation)
    if citation is not None:
        record["provenance"]["citation"] = citation
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record_to_snake_aliases(record)


def _record_from_electrode(draft: ElectrodeInput) -> dict[str, Any]:
    if not _spec_iri_re("electrode-spec").fullmatch(draft.electrode_spec_id):
        raise ValueError("electrode_spec_id must match https://w3id.org/battinfo/spec/{uid}.")
    if draft.id is not None:
        if not _component_iri_re("electrode").fullmatch(draft.id):
            raise ValueError("electrode id must match https://w3id.org/battinfo/electrode/{uid}.")
        if draft.uid is not None:
            _assert_id_matches_uid(draft.id, _normalized_dashed_uid(draft.uid))
        entity_id = draft.id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        if draft.uid is not None:
            dashed_uid = _normalized_dashed_uid(draft.uid)
        else:
            from battinfo.entities import electrode_identity_seed, stable_uid  # noqa: PLC0415

            batch = draft.batch_id or draft.lot_id or draft.name or ""
            dashed_uid = stable_uid(
                electrode_identity_seed(
                    electrode_spec_id=draft.electrode_spec_id, batch=batch
                )
            )
        entity_id = f"https://w3id.org/battinfo/electrode/{dashed_uid}"

    electrode: dict[str, Any] = {
        "id": entity_id,
        "electrode_spec_id": draft.electrode_spec_id,
        "short_id": dashed_uid.replace("-", "")[:6],
    }
    electrode.update(draft.body or {})
    for field_name in ("name", "batch_id", "lot_id", "storage", "comment"):
        value = getattr(draft, field_name)
        if value is not None:
            electrode[field_name] = value
    supplier = _org_value(draft.supplier)
    if supplier is not None:
        electrode["supplier"] = supplier
    for date_field in ("manufactured_at", "received_date", "expires_at"):
        raw = getattr(draft, date_field)
        if raw is not None:
            converted = _to_unix_time(raw)
            electrode[date_field] = converted if converted is not None else raw
    if draft.amount is not None:
        electrode["amount"] = draft.amount
    if draft.count is not None:
        electrode["count"] = draft.count
    if draft.dataset_ids:
        for dataset_id in draft.dataset_ids:
            if not DATASET_IRI_RE.fullmatch(dataset_id):
                raise ValueError("dataset_ids entries must match https://w3id.org/battinfo/dataset/{uid}.")
        electrode["datasets"] = [{"id": dataset_id, "role": "raw"} for dataset_id in draft.dataset_ids]
    if draft.property:
        electrode["property"] = draft.property

    record: dict[str, Any] = {
        "schema_version": draft.schema_version,
        "electrode": electrode,
        "provenance": stamp_provenance({
            "source_type": draft.source_type,
            "retrieved_at": _resolved_retrieved_at(draft.retrieved_at),
        }),
    }
    if draft.source_url is not None:
        record["provenance"]["source_url"] = draft.source_url
    citation = _citation_url_value(draft.citation)
    if citation is not None:
        record["provenance"]["citation"] = citation
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record_to_snake_aliases(record)


def create_electrode_spec(*, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical electrode-spec document from typed fields."""
    record = _record_from_electrode_spec(ElectrodeSpecInput(**fields))
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def create_electrode(*, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical electrode (instance) document from typed fields."""
    record = _record_from_electrode(ElectrodeInput(**fields))
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def save_electrode_spec(
    draft: ElectrodeSpecInput | dict[str, Any] | PathLike,
    *,
    source_root: PathLike = DEFAULT_REGISTRATION_SOURCE_ROOT,
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    resolve_references: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
    stamp: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Save an electrode-spec from either draft payload or canonical record."""
    if isinstance(draft, (str, Path)):
        return save_electrode_spec(
            _load_json(_as_path(draft)),
            source_root=source_root, mode=mode, duplicate_policy=duplicate_policy,
            resolve_references=resolve_references, validate=validate,
            validation_policy=validation_policy, dry_run=dry_run, stamp=stamp,
        )
    if isinstance(draft, ElectrodeSpecInput):
        record = _record_from_electrode_spec(draft)
    elif isinstance(draft, Mapping) and isinstance(draft.get("electrode_spec"), Mapping):
        record = dict(draft)
    else:
        record = _record_from_electrode_spec(ElectrodeSpecInput.model_validate(draft))
    return save_record(
        record,
        source_root=source_root, mode=mode, duplicate_policy=duplicate_policy,
        resolve_references=resolve_references, build_jsonld=False, build_html=False,
        validate=validate, validation_policy=validation_policy, dry_run=dry_run, stamp=stamp,
    )


def save_electrode(
    draft: ElectrodeInput | dict[str, Any] | PathLike,
    *,
    source_root: PathLike = DEFAULT_REGISTRATION_SOURCE_ROOT,
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    resolve_references: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
    stamp: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Save an electrode (instance) from either draft payload or canonical record."""
    if isinstance(draft, (str, Path)):
        return save_electrode(
            _load_json(_as_path(draft)),
            source_root=source_root, mode=mode, duplicate_policy=duplicate_policy,
            resolve_references=resolve_references, validate=validate,
            validation_policy=validation_policy, dry_run=dry_run, stamp=stamp,
        )
    if isinstance(draft, ElectrodeInput):
        record = _record_from_electrode(draft)
    elif isinstance(draft, Mapping) and isinstance(draft.get("electrode"), Mapping):
        record = dict(draft)
    else:
        record = _record_from_electrode(ElectrodeInput.model_validate(draft))
    return save_record(
        record,
        source_root=source_root, mode=mode, duplicate_policy=duplicate_policy,
        resolve_references=resolve_references, build_jsonld=False, build_html=False,
        validate=validate, validation_policy=validation_policy, dry_run=dry_run, stamp=stamp,
    )


def query_electrode_specs(
    *,
    id: str | None = None,
    short_id_prefix: str | None = None,
    name: str | None = None,
    kind: str | None = None,
    polarity: str | None = None,
    manufacturer: str | None = None,
    source_root: PathLike | None = None,
    directory: PathLike | None = None,
    include_packaged_examples: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query reusable electrode specifications.

    Searches YOUR records under ``source_root`` (default: ``./examples``);
    bundled example records only with ``include_packaged_examples=True`` (hits
    labeled ``origin="packaged-example"``). ``directory=`` is a deprecated alias.
    """
    records: list[dict[str, Any]] = []
    for path, origin in _query_record_files(
        "electrode-spec",
        source_root=source_root, directory=directory,
        include_packaged_examples=include_packaged_examples,
    ):
        doc = _load_json(path)
        spec = doc.get("electrode_spec", {})
        if not isinstance(spec, Mapping):
            continue
        records.append({
            "id": spec.get("id"),
            "short_id": spec.get("short_id"),
            "name": spec.get("name"),
            "kind": spec.get("kind"),
            "polarity": spec.get("polarity"),
            "manufacturer": spec.get("manufacturer"),
            "origin": origin,
            "path": str(path),
            "record": doc,
        })

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if short_id_prefix and not str(rec.get("short_id", "")).lower().startswith(short_id_prefix.lower()):
            continue
        if not _str_eq(rec.get("name"), name):
            continue
        if not _str_eq(rec.get("kind"), kind):
            continue
        if not _str_eq(rec.get("polarity"), polarity):
            continue
        if not _str_eq(rec.get("manufacturer"), manufacturer):
            continue
        filtered.append(rec)
    return _paginate(filtered, limit=limit, offset=offset)


def query_electrodes(
    *,
    id: str | None = None,
    electrode_spec_id: str | None = None,
    short_id_prefix: str | None = None,
    batch_id: str | None = None,
    lot_id: str | None = None,
    source_root: PathLike | None = None,
    directory: PathLike | None = None,
    include_packaged_examples: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query physical electrode batches.

    Searches YOUR records under ``source_root`` (default: ``./examples``);
    bundled example records only with ``include_packaged_examples=True``.
    """
    records: list[dict[str, Any]] = []
    for path, origin in _query_record_files(
        "electrode",
        source_root=source_root, directory=directory,
        include_packaged_examples=include_packaged_examples,
    ):
        doc = _load_json(path)
        body = doc.get("electrode", {})
        if not isinstance(body, Mapping):
            continue
        records.append({
            "id": body.get("id"),
            "electrode_spec_id": body.get("electrode_spec_id"),
            "short_id": body.get("short_id"),
            "name": body.get("name"),
            "batch_id": body.get("batch_id"),
            "lot_id": body.get("lot_id"),
            "origin": origin,
            "path": str(path),
            "record": doc,
        })

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if electrode_spec_id is not None and rec.get("electrode_spec_id") != electrode_spec_id:
            continue
        if short_id_prefix and not str(rec.get("short_id", "")).lower().startswith(short_id_prefix.lower()):
            continue
        if not _str_eq(rec.get("batch_id"), batch_id):
            continue
        if not _str_eq(rec.get("lot_id"), lot_id):
            continue
        filtered.append(rec)
    return _paginate(filtered, limit=limit, offset=offset)


def template_electrode_spec(
    *, name: str = "Example Electrode", uid: str | None = TEMPLATE_UID
) -> dict[str, Any]:
    """Build a starter canonical electrode-spec document for save workflows."""
    return _record_from_electrode_spec(
        ElectrodeSpecInput(
            uid=uid,
            name=name,
            notes=["Template-generated record. Set kind/composition/property before saving."],
        )
    )


def template_electrode(
    *,
    electrode_spec_id: str = "https://w3id.org/battinfo/spec/0000-0000-0000-0000",
    uid: str | None = TEMPLATE_UID,
) -> dict[str, Any]:
    """Build a starter canonical electrode (instance) document for save workflows."""
    return _record_from_electrode(
        ElectrodeInput(
            uid=uid,
            electrode_spec_id=electrode_spec_id,
            notes=["Template-generated record. Set electrode_spec_id/batch_id/property before saving."],
        )
    )


def template_material_spec(*, name: str = "Example Material", uid: str | None = TEMPLATE_UID) -> dict[str, Any]:
    """Build a starter canonical material-spec document for save workflows."""
    return _record_from_material_spec(
        MaterialSpecInput(
            uid=uid,
            name=name,
            notes=["Template-generated record. Set name/material_class/formula/property before saving."],
        )
    )


def template_material(
    *,
    material_spec_id: str = "https://w3id.org/battinfo/spec/0000-0000-0000-0000",
    uid: str | None = TEMPLATE_UID,
) -> dict[str, Any]:
    """Build a starter canonical material (instance) document for save workflows."""
    return _record_from_material(
        MaterialInput(
            uid=uid,
            material_spec_id=material_spec_id,
            notes=["Template-generated record. Set material_spec_id/lot_id/property before saving."],
        )
    )


def create_material_spec(*, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical material-spec document from typed fields."""
    record = _record_from_material_spec(MaterialSpecInput(**fields))
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def create_material(*, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical material (instance) document from typed fields."""
    record = _record_from_material(MaterialInput(**fields))
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def save_material_spec(
    draft: MaterialSpecInput | dict[str, Any] | PathLike,
    *,
    source_root: PathLike = DEFAULT_REGISTRATION_SOURCE_ROOT,
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    resolve_references: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
    stamp: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Save a material-spec from either draft payload or canonical record."""
    if isinstance(draft, (str, Path)):
        return save_material_spec(
            _load_json(_as_path(draft)),
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
            stamp=stamp,
        )
    if isinstance(draft, MaterialSpecInput):
        record = _record_from_material_spec(draft)
    elif isinstance(draft, Mapping) and isinstance(draft.get("material_spec"), Mapping):
        record = dict(draft)
    else:
        record = _record_from_material_spec(MaterialSpecInput.model_validate(draft))
    return save_record(
        record,
        source_root=source_root,
        mode=mode,
        duplicate_policy=duplicate_policy,
        resolve_references=resolve_references,
        build_jsonld=False,
        build_html=False,
        validate=validate,
        validation_policy=validation_policy,
        dry_run=dry_run,
        stamp=stamp,
    )


def save_material(
    draft: MaterialInput | dict[str, Any] | PathLike,
    *,
    source_root: PathLike = DEFAULT_REGISTRATION_SOURCE_ROOT,
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    resolve_references: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
    stamp: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Save a material (instance) from either draft payload or canonical record."""
    if isinstance(draft, (str, Path)):
        return save_material(
            _load_json(_as_path(draft)),
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
            stamp=stamp,
        )
    if isinstance(draft, MaterialInput):
        record = _record_from_material(draft)
    elif isinstance(draft, Mapping) and isinstance(draft.get("material"), Mapping):
        record = dict(draft)
    else:
        record = _record_from_material(MaterialInput.model_validate(draft))
    return save_record(
        record,
        source_root=source_root,
        mode=mode,
        duplicate_policy=duplicate_policy,
        resolve_references=resolve_references,
        build_jsonld=False,
        build_html=False,
        validate=validate,
        validation_policy=validation_policy,
        dry_run=dry_run,
        stamp=stamp,
    )


def query_material_specs(
    *,
    id: str | None = None,
    short_id_prefix: str | None = None,
    name: str | None = None,
    material_class: str | None = None,
    formula: str | None = None,
    manufacturer: str | None = None,
    source_type: str | None = None,
    source_root: PathLike | None = None,
    directory: PathLike | None = None,
    include_packaged_examples: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query reusable material specifications.

    Searches YOUR records under ``source_root`` (default: ``./examples``, the
    same root ``save_material_spec`` writes to). BattINFO's bundled example
    materials are only searched with ``include_packaged_examples=True``; those
    hits carry ``origin="packaged-example"`` so they can never masquerade as
    your lab's inventory. ``directory=`` is a deprecated alias.
    """
    records: list[dict[str, Any]] = []
    for path, origin in _query_record_files(
        "material-spec",
        source_root=source_root,
        directory=directory,
        include_packaged_examples=include_packaged_examples,
    ):
        doc = _load_json(path)
        spec = doc.get("material_spec", {})
        prov = doc.get("provenance", {})
        if not isinstance(spec, Mapping):
            continue
        records.append(
            {
                "id": spec.get("id"),
                "short_id": spec.get("short_id"),
                "name": spec.get("name"),
                "material_class": spec.get("material_class"),
                "formula": spec.get("formula"),
                "manufacturer": spec.get("manufacturer"),
                "source_type": prov.get("source_type") if isinstance(prov, Mapping) else None,
                "origin": origin,
                "path": str(path),
                "record": doc,
            }
        )

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if short_id_prefix and not str(rec.get("short_id", "")).lower().startswith(short_id_prefix.lower()):
            continue
        if not _str_eq(rec.get("name"), name):
            continue
        if not _str_eq(rec.get("material_class"), material_class):
            continue
        if not _str_eq(rec.get("formula"), formula):
            continue
        if not _str_eq(rec.get("manufacturer"), manufacturer):
            continue
        if not _str_eq(rec.get("source_type"), source_type):
            continue
        filtered.append(rec)

    return _paginate(filtered, limit=limit, offset=offset)


def query_materials(
    *,
    id: str | None = None,
    material_spec_id: str | None = None,
    short_id_prefix: str | None = None,
    lot_id: str | None = None,
    source_type: str | None = None,
    source_root: PathLike | None = None,
    directory: PathLike | None = None,
    include_packaged_examples: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query physical material lots/batches.

    Searches YOUR records under ``source_root`` (default: ``./examples``);
    bundled example records only with ``include_packaged_examples=True`` (hits
    labeled ``origin="packaged-example"``). ``directory=`` is a deprecated alias.
    """
    records: list[dict[str, Any]] = []
    for path, origin in _query_record_files(
        "material",
        source_root=source_root,
        directory=directory,
        include_packaged_examples=include_packaged_examples,
    ):
        doc = _load_json(path)
        material = doc.get("material", {})
        prov = doc.get("provenance", {})
        if not isinstance(material, Mapping):
            continue
        records.append(
            {
                "id": material.get("id"),
                "material_spec_id": material.get("material_spec_id"),
                "short_id": material.get("short_id"),
                "lot_id": material.get("lot_id"),
                "source_type": prov.get("source_type") if isinstance(prov, Mapping) else None,
                "origin": origin,
                "path": str(path),
                "record": doc,
            }
        )

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if material_spec_id is not None and rec.get("material_spec_id") != material_spec_id:
            continue
        if short_id_prefix and not str(rec.get("short_id", "")).lower().startswith(short_id_prefix.lower()):
            continue
        if not _str_eq(rec.get("lot_id"), lot_id):
            continue
        if not _str_eq(rec.get("source_type"), source_type):
            continue
        filtered.append(rec)

    return _paginate(filtered, limit=limit, offset=offset)


def _record_from_component_spec(
    family: str,
    *,
    name: str,
    body: dict[str, Any] | None = None,
    manufacturer: str | dict[str, Any] | None = None,
    supplier: str | dict[str, Any] | None = None,
    product_id: str | None = None,
    uid: str | None = None,
    id: str | None = None,
    source_type: str = "datasheet",
    source_url: str | None = None,
    citation: str | None = None,
    retrieved_at: int | str | None = None,
    notes: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    legacy_namespace = f"{family.replace('_', '-')}-spec"
    if id is not None:
        # Canonical spec/ form; the superseded per-family form is accepted so
        # pre-consolidation records keep their identity (never break an IRI).
        if not _spec_iri_re(legacy_namespace).fullmatch(id):
            raise ValueError(f"{legacy_namespace} id must match https://w3id.org/battinfo/spec/{{uid}}.")
        if uid is not None:
            _assert_id_matches_uid(id, _normalized_dashed_uid(uid))
        entity_id = id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(uid)
        entity_id = f"https://w3id.org/battinfo/spec/{dashed_uid}"

    spec: dict[str, Any] = {"id": entity_id, "short_id": dashed_uid.replace("-", "")[:6], "name": name}
    spec.update(body or {})
    spec.update({k: v for k, v in extra.items() if v is not None})
    for org_field, org_input in (("manufacturer", manufacturer), ("supplier", supplier)):
        org = _org_value(org_input)
        if org is not None:
            spec[org_field] = org
    if product_id is not None:
        spec["product_id"] = product_id

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        f"{family}_spec": spec,
        "provenance": stamp_provenance({"source_type": source_type, "retrieved_at": _resolved_retrieved_at(retrieved_at)}),
    }
    if source_url is not None:
        record["provenance"]["source_url"] = source_url
    citation_value = _citation_url_value(citation)
    if citation_value is not None:
        record["provenance"]["citation"] = citation_value
    if notes:
        record["notes"] = list(notes)
    return record_to_snake_aliases(record)


def _record_from_component_instance(
    family: str,
    *,
    spec_id: str,
    body: dict[str, Any] | None = None,
    name: str | None = None,
    lot_id: str | None = None,
    supplier: str | dict[str, Any] | None = None,
    dataset_ids: list[str] | None = None,
    uid: str | None = None,
    id: str | None = None,
    source_type: str = "lab",
    source_url: str | None = None,
    citation: str | None = None,
    retrieved_at: int | str | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    base_namespace = family.replace("_", "-")
    spec_namespace = f"{base_namespace}-spec"
    if not _spec_iri_re(spec_namespace).fullmatch(spec_id):
        raise ValueError(f"{family}_spec_id must match https://w3id.org/battinfo/spec/{{uid}}.")
    if id is not None:
        if not _component_iri_re(base_namespace).fullmatch(id):
            raise ValueError(f"{family} id must match https://w3id.org/battinfo/{base_namespace}/{{uid}}.")
        if uid is not None:
            _assert_id_matches_uid(id, _normalized_dashed_uid(uid))
        entity_id = id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(uid)
        entity_id = f"https://w3id.org/battinfo/{base_namespace}/{dashed_uid}"

    instance: dict[str, Any] = {
        "id": entity_id,
        f"{family}_spec_id": spec_id,
        "short_id": dashed_uid.replace("-", "")[:6],
    }
    instance.update(body or {})
    if name is not None:
        instance["name"] = name
    if lot_id is not None:
        instance["lot_id"] = lot_id
    org = _org_value(supplier)
    if org is not None:
        instance["supplier"] = org
    if dataset_ids:
        for dataset_id in dataset_ids:
            if not DATASET_IRI_RE.fullmatch(dataset_id):
                raise ValueError("dataset_ids entries must match https://w3id.org/battinfo/dataset/{uid}.")
        instance["datasets"] = [{"id": dataset_id, "role": "raw"} for dataset_id in dataset_ids]

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        family: instance,
        "provenance": stamp_provenance({"source_type": source_type, "retrieved_at": _resolved_retrieved_at(retrieved_at)}),
    }
    if source_url is not None:
        record["provenance"]["source_url"] = source_url
    citation_value = _citation_url_value(citation)
    if citation_value is not None:
        record["provenance"]["citation"] = citation_value
    if notes:
        record["notes"] = list(notes)
    return record_to_snake_aliases(record)


def create_component_spec(family: str, *, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical component-spec document for a family (electrode, separator, …)."""
    record = _record_from_component_spec(family, **fields)
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def create_component_instance(family: str, *, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical component (instance) document for a family."""
    record = _record_from_component_instance(family, **fields)
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def _save_component(
    record: dict[str, Any] | PathLike,
    *,
    source_root: PathLike = DEFAULT_REGISTRATION_SOURCE_ROOT,
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    resolve_references: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    doc = _load_json(_as_path(record)) if isinstance(record, (str, Path)) else dict(record)
    return save_record(
        doc,
        source_root=source_root,
        mode=mode,
        duplicate_policy=duplicate_policy,
        resolve_references=resolve_references,
        build_jsonld=False,
        build_html=False,
        validate=validate,
        validation_policy=validation_policy,
        dry_run=dry_run,
    )


def save_component_spec(family: str, record: dict[str, Any] | PathLike, **kwargs: Any) -> dict[str, Any]:
    """Save a component-spec record (or path) for a family."""
    return _save_component(record, **kwargs)


def save_component_instance(family: str, record: dict[str, Any] | PathLike, **kwargs: Any) -> dict[str, Any]:
    """Save a component (instance) record (or path) for a family."""
    return _save_component(record, **kwargs)


def _query_component(
    record_key: str,
    files: list[tuple[Path, str]],
    *,
    id: str | None,
    name: str | None,
    short_id_prefix: str | None,
    spec_ref_field: str | None,
    spec_id: str | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path, origin in files:
        doc = _load_json(path)
        body = doc.get(record_key)
        if not isinstance(body, Mapping):
            continue
        rec = {
            "id": body.get("id"),
            "name": body.get("name"),
            "short_id": body.get("short_id"),
            "origin": origin,
            "path": str(path),
            "record": doc,
        }
        if spec_ref_field:
            rec[spec_ref_field] = body.get(spec_ref_field)
        records.append(rec)

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if not _str_eq(rec.get("name"), name):
            continue
        if short_id_prefix and not str(rec.get("short_id", "")).lower().startswith(short_id_prefix.lower()):
            continue
        if spec_id is not None and spec_ref_field and rec.get(spec_ref_field) != spec_id:
            continue
        filtered.append(rec)
    return _paginate(filtered, limit=limit, offset=offset)


def query_component_specs(
    family: str,
    *,
    source_root: PathLike | None = None,
    directory: PathLike | None = None,
    include_packaged_examples: bool = False,
    id: str | None = None,
    name: str | None = None,
    short_id_prefix: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query reusable component specifications for a family.

    Searches YOUR records under ``source_root`` (default: ``./examples``);
    bundled example records only with ``include_packaged_examples=True`` (hits
    labeled ``origin="packaged-example"``). ``directory=`` is a deprecated alias.
    """
    files = _query_record_files(
        f"{family.replace('_', '-')}-spec",
        source_root=source_root,
        directory=directory,
        include_packaged_examples=include_packaged_examples,
    )
    return _query_component(
        f"{family}_spec", files, id=id, name=name, short_id_prefix=short_id_prefix,
        spec_ref_field=None, spec_id=None, limit=limit, offset=offset,
    )


def query_component_instances(
    family: str,
    *,
    source_root: PathLike | None = None,
    directory: PathLike | None = None,
    include_packaged_examples: bool = False,
    id: str | None = None,
    name: str | None = None,
    short_id_prefix: str | None = None,
    spec_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query physical component instances for a family.

    Searches YOUR records under ``source_root`` (default: ``./examples``);
    bundled example records only with ``include_packaged_examples=True`` (hits
    labeled ``origin="packaged-example"``). ``directory=`` is a deprecated alias.
    """
    files = _query_record_files(
        family.replace("_", "-"),
        source_root=source_root,
        directory=directory,
        include_packaged_examples=include_packaged_examples,
    )
    return _query_component(
        family, files, id=id, name=name, short_id_prefix=short_id_prefix,
        spec_ref_field=f"{family}_spec_id", spec_id=spec_id, limit=limit, offset=offset,
    )


def template_component_spec(family: str, *, name: str | None = None, uid: str | None = TEMPLATE_UID) -> dict[str, Any]:
    """Build a starter component-spec document for a family."""
    return _record_from_component_spec(
        family, name=name or f"Example {family}", uid=uid,
        notes=[f"Template-generated {family}-spec. Fill in the holder body before saving."],
    )


def template_component_instance(
    family: str,
    *,
    spec_id: str | None = None,
    uid: str | None = TEMPLATE_UID,
) -> dict[str, Any]:
    """Build a starter component (instance) document for a family."""
    return _record_from_component_instance(
        family, spec_id=spec_id or "https://w3id.org/battinfo/spec/0000-0000-0000-0000", uid=uid,
        notes=[f"Template-generated {family} instance. Set {family}_spec_id before saving."],
    )


# Per-family convenience wrappers (create_electrode_spec, save_electrode_spec, …).
_COMPONENT_WRAPPER_NAMES: list[str] = []
for _family in COMPONENT_FAMILIES:
    for _verb, _generic, _suffix in (
        ("create", create_component_spec, "spec"),
        ("save", save_component_spec, "spec"),
        ("template", template_component_spec, "spec"),
        ("create", create_component_instance, "instance"),
        ("save", save_component_instance, "instance"),
        ("template", template_component_instance, "instance"),
    ):
        _wname = f"{_verb}_{_family}_spec" if _suffix == "spec" else f"{_verb}_{_family}"
        globals()[_wname] = functools.partial(_generic, _family)
        _COMPONENT_WRAPPER_NAMES.append(_wname)
    _qspec = f"query_{_family}_specs"
    _qinst = f"query_{_family}s" if not _family.endswith("s") else f"query_{_family}"
    globals()[_qspec] = functools.partial(query_component_specs, _family)
    globals()[_qinst] = functools.partial(query_component_instances, _family)
    _COMPONENT_WRAPPER_NAMES.extend([_qspec, _qinst])
