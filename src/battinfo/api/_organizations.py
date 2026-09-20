"""Organization records: create/save/query (closes the documented triple gap).

Organizations are the identity records other records point at — manufacturers,
labs, publishers. Design rules:

- Instance-only: there is no organization-spec kind. Records mint under
  ``organization/``.
- NEW uids derive DETERMINISTICALLY from the normalized name, so re-creating
  "A123 Systems" is idempotent and collates instead of duplicating. Existing
  random-minted IRIs stay valid forever (pass ``id=`` to keep one).
- The canonical keys are snake_case (``legal_name``, ``founding_date``, ...);
  the original camelCase spellings are accepted forever as deprecated aliases
  and normalize on round-trip (``canonical_aliases``).
- ``type`` is data from the schema.org-aligned enum (Manufacturer,
  ResearchOrganization, ...), never a namespace.

Import the public surface from ``battinfo.api``, not from this module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from battinfo._jsonio import read_record_json as _load_json
from battinfo._util import _as_path
from battinfo.api._records import _assert_id_matches_uid, save_record
from battinfo.api._shared import (
    DEFAULT_REGISTRATION_SOURCE_ROOT,
    DUPLICATE_POLICY_ERROR,
    REGISTER_MODE_CREATE_ONLY,
    PathLike,
    _component_iri_re,
    _iri_tail,
    _normalized_dashed_uid,
    _paginate,
    _query_record_files,
    _resolved_retrieved_at,
    _str_eq,
    _validate_canonical_record,
)
from battinfo.bundle import SCHEMA_VERSION, stamp_provenance
from battinfo.canonical_aliases import record_to_snake_aliases
from battinfo.entities import stable_uid
from battinfo.validate.core import DEFAULT_POLICY, ValidationPolicy

ORGANIZATION_IRI_RE = _component_iri_re("organization")

_ORGANIZATION_TYPES = (
    "Organization",
    "Corporation",
    "Manufacturer",
    "ResearchOrganization",
    "EducationalOrganization",
    "GovernmentOrganization",
    "NGO",
    "Other",
)


def _record_from_organization(
    *,
    name: str,
    type: str | None = None,  # noqa: A002 - matches the record field, like `id`
    legal_name: str | None = None,
    alternate_name: list[str] | str | None = None,
    url: str | None = None,
    same_as: list[str] | str | None = None,
    location: dict[str, Any] | None = None,
    founding_date: str | None = None,
    dissolution_date: str | None = None,
    parent_organization: str | dict[str, Any] | None = None,
    description: str | None = None,
    uid: str | None = None,
    id: str | None = None,
    source_type: str = "manual",
    source_url: str | None = None,
    retrieved_at: int | str | None = None,
    notes: list[str] | None = None,
    **aliases: Any,
) -> dict[str, Any]:
    # Deprecated camelCase kwargs (legalName=, foundingDate=, ...) normalize
    # through the same table the record loader uses.
    if aliases:
        from battinfo.canonical_aliases import _ORGANIZATION_TO_SNAKE  # noqa: PLC0415

        unknown = [k for k in aliases if k not in _ORGANIZATION_TO_SNAKE]
        if unknown:
            raise TypeError(f"unexpected keyword argument(s): {', '.join(sorted(unknown))}")
        explicit: dict[str, Any] = {
            "name": name, "type": type, "legal_name": legal_name,
            "alternate_name": alternate_name, "url": url, "same_as": same_as,
            "location": location, "founding_date": founding_date,
            "dissolution_date": dissolution_date,
            "parent_organization": parent_organization, "description": description,
            "uid": uid, "id": id, "source_type": source_type,
            "source_url": source_url, "retrieved_at": retrieved_at, "notes": notes,
        }
        for camel, value in aliases.items():
            snake = _ORGANIZATION_TO_SNAKE[camel]
            if explicit.get(snake) not in (None, value):
                raise ValueError(f"{camel}= and {snake}= disagree.")
            explicit[snake] = value
        return _record_from_organization(**explicit)

    if not isinstance(name, str) or not name.strip():
        raise ValueError("organization needs a non-empty name.")
    if type is not None and type not in _ORGANIZATION_TYPES:
        raise ValueError(
            f"type must be one of {', '.join(_ORGANIZATION_TYPES)}; got {type!r}."
        )

    if id is not None:
        if not ORGANIZATION_IRI_RE.fullmatch(id):
            raise ValueError("organization id must match https://w3id.org/battinfo/organization/{uid}.")
        if uid is not None:
            _assert_id_matches_uid(id, _normalized_dashed_uid(uid))
        entity_id = id
        _, dashed_uid = _iri_tail(entity_id)
    elif uid is not None:
        dashed_uid = _normalized_dashed_uid(uid)
        entity_id = f"https://w3id.org/battinfo/organization/{dashed_uid}"
    else:
        # Deterministic identity from the normalized name: the same
        # organization re-created anywhere mints the same IRI.
        dashed_uid = stable_uid(f"organization:{name.strip().lower()}")
        entity_id = f"https://w3id.org/battinfo/organization/{dashed_uid}"

    body: dict[str, Any] = {
        "id": entity_id,
        "short_id": dashed_uid.replace("-", "")[:6],
        "name": name.strip(),
    }
    if type is not None:
        body["type"] = type
    if legal_name is not None:
        body["legal_name"] = legal_name
    if alternate_name is not None:
        body["alternate_name"] = (
            [alternate_name] if isinstance(alternate_name, str) else list(alternate_name)
        )
    if url is not None:
        body["url"] = url
    if same_as is not None:
        body["same_as"] = [same_as] if isinstance(same_as, str) else list(same_as)
    if location is not None:
        body["location"] = dict(location)
    if founding_date is not None:
        body["founding_date"] = founding_date
    if dissolution_date is not None:
        body["dissolution_date"] = dissolution_date
    if parent_organization is not None:
        body["parent_organization"] = (
            parent_organization if isinstance(parent_organization, str) else dict(parent_organization)
        )
    if description is not None:
        body["description"] = description

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "organization": body,
        "provenance": stamp_provenance(
            {"source_type": source_type, "retrieved_at": _resolved_retrieved_at(retrieved_at)}
        ),
    }
    if source_url is not None:
        record["provenance"]["source_url"] = source_url
    if notes:
        record["notes"] = list(notes)
    return record_to_snake_aliases(record)


def create_organization(*, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical organization document (manufacturer, lab, publisher).

    New uids derive deterministically from the normalized ``name`` — creating
    the same organization twice mints the same IRI. Deprecated camelCase
    kwargs (``legalName=`` etc.) are accepted and normalize to the canonical
    snake_case keys.
    """
    record = _record_from_organization(**fields)
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def save_organization(
    draft: dict[str, Any] | PathLike,
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
    """Save an organization from either a kwargs draft or a canonical record."""
    if isinstance(draft, (str, Path)):
        return save_organization(
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
    if isinstance(draft, Mapping) and isinstance(draft.get("organization"), Mapping):
        record = dict(draft)
    elif isinstance(draft, Mapping):
        record = _record_from_organization(**dict(draft))
    else:
        raise TypeError(
            "save_organization expects a canonical record dict, a kwargs draft "
            f"dict, or a path; got {type(draft).__name__}."
        )
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


def query_organizations(
    *,
    id: str | None = None,
    short_id_prefix: str | None = None,
    name: str | None = None,
    type: str | None = None,  # noqa: A002 - matches the record field
    source_root: PathLike | None = None,
    include_packaged_examples: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query saved organizations by id, short-id prefix, name, or type."""
    records: list[dict[str, Any]] = []
    for path, origin in _query_record_files(
        "organization",
        source_root=source_root,
        directory=None,
        include_packaged_examples=include_packaged_examples,
    ):
        doc = _load_json(path)
        body = doc.get("organization")
        if not isinstance(body, Mapping):
            continue
        if id is not None and body.get("id") != id:
            continue
        if short_id_prefix is not None and not str(body.get("short_id", "")).startswith(short_id_prefix):
            continue
        if name is not None and not _str_eq(body.get("name"), name):
            continue
        if type is not None and body.get("type") != type:
            continue
        records.append({
            "id": body.get("id"),
            "short_id": body.get("short_id"),
            "name": body.get("name"),
            "type": body.get("type"),
            "url": body.get("url"),
            "origin": origin,
            "path": str(path),
            "record": doc,
        })
    records.sort(key=lambda r: (str(r.get("name") or ""), str(r.get("id") or "")))
    return _paginate(records, limit=limit, offset=offset)
