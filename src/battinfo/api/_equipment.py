"""Equipment + channel families: create builders (IDENTIFIER_POLICY 6.1).

Design rules (ratified — see IDENTIFIER_POLICY.md section 6.1):

- ``equipment-spec`` (the model, e.g. "Neware BTS-4000") mints under the shared
  ``spec/`` namespace like every other reusable description.
- ``equipment`` (the physical unit, "Cycler 1") mints under ``equipment/``.
- ``channel`` (one channel of one unit) is instance-only — there is NO
  channel-spec kind. Channel IRIs are flat (never hierarchical); the parent
  link ``equipment_id`` lives in the record body. Channel uids are minted
  DETERMINISTICALLY from ``(equipment uid, index)`` so registration is
  idempotent.
- Equipment category (cycler/glovebox/...) is DATA (the ``equipment_class``
  string field), never a namespace segment, and battinfo never mints domain
  classes for it (vocab policy section 14).

Import the public surface from ``battinfo.api``, not from this module.
"""
from __future__ import annotations

from typing import Any

from battinfo._util import _citation_url_value
from battinfo.api._components import _org_value
from battinfo.api._records import _assert_id_matches_uid
from battinfo.api._shared import (
    SPEC_IRI_RE,
    _component_iri_re,
    _iri_tail,
    _normalized_dashed_uid,
    _resolved_retrieved_at,
    _to_unix_time,
    _validate_canonical_record,
)
from battinfo.bundle import SCHEMA_VERSION, stamp_provenance
from battinfo.canonical_aliases import record_to_snake_aliases
from battinfo.entities import stable_uid
from battinfo.validate.core import DEFAULT_POLICY

EQUIPMENT_IRI_RE = _component_iri_re("equipment")
CHANNEL_IRI_RE = _component_iri_re("channel")

_STATUS_VALUES = ("active", "maintenance", "retired", "unknown")


def _checked_status(status: str | None) -> str | None:
    if status is None:
        return None
    if status not in _STATUS_VALUES:
        raise ValueError(f"status must be one of {', '.join(_STATUS_VALUES)}; got {status!r}.")
    return status


def _finish_record(
    record: dict[str, Any],
    *,
    source_url: str | None,
    citation: str | None,
    notes: list[str] | None,
) -> dict[str, Any]:
    if source_url is not None:
        record["provenance"]["source_url"] = source_url
    citation_value = _citation_url_value(citation)
    if citation_value is not None:
        record["provenance"]["citation"] = citation_value
    if notes:
        record["notes"] = list(notes)
    return record_to_snake_aliases(record)


def _record_from_equipment_spec(
    *,
    name: str,
    equipment_class: str | None = None,
    model: str | None = None,
    channel_count: int | None = None,
    property: dict[str, Any] | None = None,
    manufacturer: str | dict[str, Any] | None = None,
    supplier: str | dict[str, Any] | None = None,
    product_id: str | None = None,
    comment: str | None = None,
    uid: str | None = None,
    id: str | None = None,
    source_type: str = "datasheet",
    source_url: str | None = None,
    citation: str | None = None,
    retrieved_at: int | str | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    # This kind never existed before the spec/ consolidation: spec/-only, no
    # legacy per-family alternation.
    if id is not None:
        if not SPEC_IRI_RE.fullmatch(id):
            raise ValueError("equipment-spec id must match https://w3id.org/battinfo/spec/{uid}.")
        if uid is not None:
            _assert_id_matches_uid(id, _normalized_dashed_uid(uid))
        entity_id = id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(uid)
        entity_id = f"https://w3id.org/battinfo/spec/{dashed_uid}"

    spec: dict[str, Any] = {"id": entity_id, "short_id": dashed_uid.replace("-", "")[:6], "name": name}
    if equipment_class is not None:
        spec["equipment_class"] = equipment_class
    if model is not None:
        spec["model"] = model
    if channel_count is not None:
        spec["channel_count"] = channel_count
    if property:
        spec["property"] = property
    for org_field, org_input in (("manufacturer", manufacturer), ("supplier", supplier)):
        org = _org_value(org_input)
        if org is not None:
            spec[org_field] = org
    if product_id is not None:
        spec["product_id"] = product_id
    if comment is not None:
        spec["comment"] = comment

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "equipment_spec": spec,
        "provenance": stamp_provenance(
            {"source_type": source_type, "retrieved_at": _resolved_retrieved_at(retrieved_at)}
        ),
    }
    return _finish_record(record, source_url=source_url, citation=citation, notes=notes)


def _record_from_equipment(
    *,
    equipment_spec_id: str,
    serial_number: str | None = None,
    name: str | None = None,
    location: str | None = None,
    commissioned_at: int | str | None = None,
    status: str | None = None,
    property: dict[str, Any] | None = None,
    comment: str | None = None,
    uid: str | None = None,
    id: str | None = None,
    source_type: str = "lab",
    source_url: str | None = None,
    citation: str | None = None,
    retrieved_at: int | str | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    if not SPEC_IRI_RE.fullmatch(equipment_spec_id):
        raise ValueError("equipment_spec_id must match https://w3id.org/battinfo/spec/{uid}.")
    if id is not None:
        if not EQUIPMENT_IRI_RE.fullmatch(id):
            raise ValueError("equipment id must match https://w3id.org/battinfo/equipment/{uid}.")
        if uid is not None:
            _assert_id_matches_uid(id, _normalized_dashed_uid(uid))
        entity_id = id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(uid)
        entity_id = f"https://w3id.org/battinfo/equipment/{dashed_uid}"

    equipment: dict[str, Any] = {
        "id": entity_id,
        "equipment_spec_id": equipment_spec_id,
        "short_id": dashed_uid.replace("-", "")[:6],
    }
    if serial_number is not None:
        equipment["serial_number"] = serial_number
    if name is not None:
        equipment["name"] = name
    if location is not None:
        equipment["location"] = location
    if commissioned_at is not None:
        # Same FlexDate mechanism component instances use for manufactured_at:
        # store Unix seconds when convertible, the original string otherwise.
        converted = _to_unix_time(commissioned_at)
        equipment["commissioned_at"] = converted if converted is not None else commissioned_at
    checked_status = _checked_status(status)
    if checked_status is not None:
        equipment["status"] = checked_status
    if property:
        equipment["property"] = property
    if comment is not None:
        equipment["comment"] = comment

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "equipment": equipment,
        "provenance": stamp_provenance(
            {"source_type": source_type, "retrieved_at": _resolved_retrieved_at(retrieved_at)}
        ),
    }
    return _finish_record(record, source_url=source_url, citation=citation, notes=notes)


def _record_from_channel(
    *,
    equipment_id: str,
    index: int,
    label: str | None = None,
    status: str | None = None,
    property: dict[str, Any] | None = None,
    comment: str | None = None,
    uid: str | None = None,
    id: str | None = None,
    source_type: str = "lab",
    source_url: str | None = None,
    citation: str | None = None,
    retrieved_at: int | str | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    if not EQUIPMENT_IRI_RE.fullmatch(equipment_id):
        raise ValueError("equipment_id must match https://w3id.org/battinfo/equipment/{uid}.")
    if isinstance(index, bool) or not isinstance(index, int) or index < 1:
        raise ValueError("index must be an integer >= 1 (channel numbering is 1-based).")
    if id is not None:
        if not CHANNEL_IRI_RE.fullmatch(id):
            raise ValueError("channel id must match https://w3id.org/battinfo/channel/{uid}.")
        if uid is not None:
            _assert_id_matches_uid(id, _normalized_dashed_uid(uid))
        entity_id = id
        _, dashed_uid = _iri_tail(entity_id)
    elif uid is not None:
        dashed_uid = _normalized_dashed_uid(uid)
        entity_id = f"https://w3id.org/battinfo/channel/{dashed_uid}"
    else:
        # Deterministic identity: the same (equipment, index) always mints the
        # same channel IRI, so re-registration is idempotent.
        _, equipment_uid = _iri_tail(equipment_id)
        dashed_uid = stable_uid(f"channel:{equipment_uid}:{index}")
        entity_id = f"https://w3id.org/battinfo/channel/{dashed_uid}"

    channel: dict[str, Any] = {
        "id": entity_id,
        "equipment_id": equipment_id,
        "index": index,
        "short_id": dashed_uid.replace("-", "")[:6],
    }
    if label is not None:
        channel["label"] = label
    checked_status = _checked_status(status)
    if checked_status is not None:
        channel["status"] = checked_status
    if property:
        channel["property"] = property
    if comment is not None:
        channel["comment"] = comment

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "channel": channel,
        "provenance": stamp_provenance(
            {"source_type": source_type, "retrieved_at": _resolved_retrieved_at(retrieved_at)}
        ),
    }
    return _finish_record(record, source_url=source_url, citation=citation, notes=notes)


def create_equipment_spec(*, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical equipment-spec document (the model, e.g. a cycler model)."""
    record = _record_from_equipment_spec(**fields)
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def create_equipment(*, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical equipment (instance) document (the physical unit)."""
    record = _record_from_equipment(**fields)
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def create_channel(*, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical channel document (one channel of one equipment unit).

    The uid is derived deterministically from ``(equipment uid, index)`` unless
    ``uid``/``id`` is given explicitly, so the same channel always mints the
    same IRI.
    """
    record = _record_from_channel(**fields)
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record
