"""Materials and component families: inputs, create/save/query, and generated per-family wrappers.

Split from the former monolithic ``battinfo/api.py`` (beta-hardening 4.2);
import the public surface from ``battinfo.api``, not from this module.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Literal, Mapping

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
    lot_id: str | None = None
    batch_id: str | None = None
    supplier: str | dict[str, Any] | None = None
    received_date: int | str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    property: dict[str, Any] = Field(default_factory=dict)
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


def _record_from_material_spec(draft: MaterialSpecInput) -> dict[str, Any]:
    if draft.id is not None:
        if not MATERIAL_SPEC_IRI_RE.fullmatch(draft.id):
            raise ValueError("material spec id must match https://w3id.org/battinfo/spec/{uid}.")
        if draft.uid is not None:
            _assert_id_matches_uid(draft.id, _normalized_dashed_uid(draft.uid))
        entity_id = draft.id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(draft.uid)
        entity_id = f"https://w3id.org/battinfo/spec/{dashed_uid}"

    spec: dict[str, Any] = {
        "id": entity_id,
        "short_id": dashed_uid.replace("-", "")[:6],
        "name": draft.name,
    }
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
        dashed_uid = _normalized_dashed_uid(draft.uid)
        entity_id = f"https://w3id.org/battinfo/material/{dashed_uid}"

    material: dict[str, Any] = {
        "id": entity_id,
        "material_spec_id": draft.material_spec_id,
        "short_id": dashed_uid.replace("-", "")[:6],
    }
    for field_name in ("name", "lot_id", "batch_id"):
        value = getattr(draft, field_name)
        if value is not None:
            material[field_name] = value
    supplier = _org_value(draft.supplier)
    if supplier is not None:
        material["supplier"] = supplier
    if draft.received_date is not None:
        received = _to_unix_time(draft.received_date)
        material["received_date"] = received if received is not None else draft.received_date
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
