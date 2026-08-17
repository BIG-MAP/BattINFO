"""Parameter sets: claim batches from one source about one target.

A ``parameter-set`` record carries simulation-parameter *claims* (scalar
quantities, tabulated curves, or expression strings) about exactly one target:

- ``material_kind`` — a generic chemistry from the curated material_kinds
  vocabulary ("graphite", "nmc811"): where literature claims collate;
- ``material_spec_id`` — a specific vendor product/grade;
- ``cell_spec_id`` — a cell spec, for cell-level fitted sets and for the
  electrode/separator/electrolyte build parameters of that design.

One source (paper, BPX file, lab fit) = one record; the record-level
provenance block carries the source citation, each claim carries its own
provenance class. The uid is minted deterministically from (target, name) so
re-importing the same source is idempotent, never a duplicate.

Import the public surface from ``battinfo.api``, not from this module.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from battinfo._jsonio import read_record_json as _load_json
from battinfo._util import _as_path, _citation_url_value
from battinfo.api._records import _assert_id_matches_uid, save_record
from battinfo.api._shared import (
    DEFAULT_REGISTRATION_SOURCE_ROOT,
    DUPLICATE_POLICY_ERROR,
    MATERIAL_SPEC_IRI_RE,
    REGISTER_MODE_CREATE_ONLY,
    SPEC_IRI_RE,
    TEMPLATE_UID,
    PathLike,
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

_PARAMETER_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PROVENANCE_CLASSES = ("measured", "fitted", "literature", "assumed", "derived")
_SCOPES = ("material", "electrode", "separator", "electrolyte", "cell")
_TARGET_FIELDS = ("material_kind", "material_spec_id", "cell_spec_id")


def _checked_claim(claim: Any, index: int, default_provenance_class: str | None) -> dict[str, Any]:
    """Validate one claim dict beyond what JSON Schema can express."""
    if not isinstance(claim, Mapping):
        raise ValueError(f"claims[{index}] must be a mapping, got {type(claim).__name__}.")
    out = dict(claim)
    parameter = out.get("parameter")
    if not isinstance(parameter, str) or not _PARAMETER_KEY_RE.fullmatch(parameter):
        raise ValueError(
            f"claims[{index}].parameter must be a snake_case key (got {parameter!r}). "
            "Known keys: battinfo.parameters.parameter_keys(); unknown keys are "
            "allowed but never count toward model-tier completeness."
        )
    value_fields = [f for f in ("quantity", "curve", "expression") if out.get(f) is not None]
    if len(value_fields) != 1:
        raise ValueError(
            f"claims[{index}] ({parameter}) must carry exactly one of quantity, "
            f"curve, expression (got {value_fields or 'none'})."
        )
    curve = out.get("curve")
    if curve is not None:
        if not isinstance(curve, Mapping):
            raise ValueError(f"claims[{index}].curve must be a mapping.")
        xs, ys = curve.get("x"), curve.get("y")
        if not isinstance(xs, list) or not isinstance(ys, list) or len(xs) != len(ys):
            raise ValueError(
                f"claims[{index}].curve ({parameter}): x and y must be lists of equal length."
            )
        if len(xs) < 2:
            raise ValueError(f"claims[{index}].curve ({parameter}): need at least 2 points.")
        for name, values in (("x", xs), ("y", ys)):
            for v in values:
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                    raise ValueError(
                        f"claims[{index}].curve ({parameter}): {name} contains a "
                        f"non-finite or non-numeric value ({v!r})."
                    )
    provenance_class = out.get("provenance_class")
    if provenance_class is None and default_provenance_class is not None:
        provenance_class = default_provenance_class
        out["provenance_class"] = provenance_class
    if provenance_class is not None and provenance_class not in _PROVENANCE_CLASSES:
        raise ValueError(
            f"claims[{index}].provenance_class must be one of "
            f"{', '.join(_PROVENANCE_CLASSES)}; got {provenance_class!r}."
        )
    return out


def _resolved_target(
    material_kind: str | None,
    material_spec_id: str | None,
    cell_spec_id: str | None,
) -> tuple[str, str]:
    """Validate the exactly-one-target rule; return (field, value)."""
    given = [
        (field, value)
        for field, value in (
            ("material_kind", material_kind),
            ("material_spec_id", material_spec_id),
            ("cell_spec_id", cell_spec_id),
        )
        if value is not None
    ]
    if len(given) != 1:
        raise ValueError(
            "a parameter set targets exactly one of material_kind, "
            f"material_spec_id, cell_spec_id (got {[f for f, _ in given] or 'none'})."
        )
    field, value = given[0]
    if field == "material_kind":
        from battinfo.materials import material_kind_keys, resolve_material_kind  # noqa: PLC0415

        resolved = resolve_material_kind(value)
        if resolved is None:
            raise ValueError(
                f"unknown material kind {value!r}. Valid kinds: "
                f"{', '.join(material_kind_keys())}."
            )
        return field, resolved
    if field == "material_spec_id":
        if not MATERIAL_SPEC_IRI_RE.fullmatch(str(value)):
            raise ValueError(
                "material_spec_id must be a canonical material-spec IRI "
                "(https://w3id.org/battinfo/spec/{uid})."
            )
        return field, str(value)
    if not SPEC_IRI_RE.fullmatch(str(value)):
        raise ValueError("cell_spec_id must match https://w3id.org/battinfo/spec/{uid}.")
    return field, str(value)


def _record_from_parameter_set(
    *,
    name: str,
    claims: list[Any],
    material_kind: str | None = None,
    material_spec_id: str | None = None,
    cell_spec_id: str | None = None,
    scope: str | None = None,
    electrode_polarity: str | None = None,
    model_context: Mapping[str, Any] | None = None,
    default_provenance_class: str | None = None,
    description: str | None = None,
    comment: str | None = None,
    uid: str | None = None,
    id: str | None = None,
    source_type: str = "literature",
    source_url: str | None = None,
    citation: str | None = None,
    citation_doi: str | None = None,
    retrieved_at: int | str | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("parameter set needs a non-empty name (convention: '<source> - <target>').")
    target_field, target_value = _resolved_target(material_kind, material_spec_id, cell_spec_id)

    if scope is None:
        scope = "material" if target_field in ("material_kind", "material_spec_id") else "cell"
    if scope not in _SCOPES:
        raise ValueError(f"scope must be one of {', '.join(_SCOPES)}; got {scope!r}.")
    if electrode_polarity is not None:
        if electrode_polarity not in ("positive", "negative"):
            raise ValueError("electrode_polarity must be 'positive' or 'negative'.")
        if scope != "electrode":
            raise ValueError("electrode_polarity only applies to scope='electrode' claims.")

    if not isinstance(claims, list) or not claims:
        raise ValueError("claims must be a non-empty list of claim dicts.")
    checked_claims = [
        _checked_claim(claim, i, default_provenance_class) for i, claim in enumerate(claims)
    ]

    if id is not None:
        if not SPEC_IRI_RE.fullmatch(id):
            raise ValueError("parameter-set id must match https://w3id.org/battinfo/spec/{uid}.")
        if uid is not None:
            _assert_id_matches_uid(id, _normalized_dashed_uid(uid))
        entity_id = id
        _, dashed_uid = _iri_tail(entity_id)
    elif uid is not None:
        dashed_uid = _normalized_dashed_uid(uid)
        entity_id = f"https://w3id.org/battinfo/spec/{dashed_uid}"
    else:
        # Deterministic identity: the same (target, scope side, name) always
        # mints the same IRI, so re-importing a source is idempotent.
        seed_parts = ["parameter-set", target_value, scope]
        if electrode_polarity:
            seed_parts.append(electrode_polarity)
        seed_parts.append(name.strip().lower())
        dashed_uid = stable_uid(":".join(seed_parts))
        entity_id = f"https://w3id.org/battinfo/spec/{dashed_uid}"

    body: dict[str, Any] = {
        "id": entity_id,
        "short_id": dashed_uid.replace("-", "")[:6],
        "name": name.strip(),
        target_field: target_value,
        "scope": scope,
        "claims": checked_claims,
    }
    if electrode_polarity is not None:
        body["electrode_polarity"] = electrode_polarity
    if model_context:
        body["model_context"] = dict(model_context)
    if description is not None:
        body["description"] = description
    if comment is not None:
        body["comment"] = comment

    provenance: dict[str, Any] = {
        "source_type": source_type,
        "retrieved_at": _resolved_retrieved_at(retrieved_at),
    }
    if citation_doi is not None:
        provenance["citation_doi"] = citation_doi
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "parameter_set": body,
        "provenance": stamp_provenance(provenance),
    }
    if source_url is not None:
        record["provenance"]["source_url"] = source_url
    citation_value = _citation_url_value(citation)
    if citation_value is not None:
        record["provenance"]["citation"] = citation_value
    if notes:
        record["notes"] = list(notes)
    return record_to_snake_aliases(record)


def create_parameter_set(*, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical parameter-set document (one source's claims about one target).

    Target is exactly one of ``material_kind`` (curated kind key or alias),
    ``material_spec_id``, ``cell_spec_id``. Each claim carries exactly one of
    ``quantity`` / ``curve`` / ``expression`` plus its ``provenance_class``
    (``default_provenance_class=`` fills claims that omit it). The uid derives
    deterministically from (target, scope, name), so the same source re-imports
    onto the same IRI.
    """
    record = _record_from_parameter_set(**fields)
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def template_parameter_set(
    *, name: str = "Example source - graphite", uid: str | None = TEMPLATE_UID
) -> dict[str, Any]:
    """Build a starter canonical parameter-set document for save workflows."""
    return _record_from_parameter_set(
        name=name,
        uid=uid,
        material_kind="graphite",
        claims=[
            {
                "parameter": "specific_capacity",
                "quantity": {"value": 372.0, "unit": "mAh/g"},
                "provenance_class": "literature",
            }
        ],
        notes=["Template-generated record. Set target/claims/citation before saving."],
    )


def save_parameter_set(
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
    """Save a parameter set from either a kwargs draft or a canonical record."""
    if isinstance(draft, (str, Path)):
        return save_parameter_set(
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
    if isinstance(draft, Mapping) and isinstance(draft.get("parameter_set"), Mapping):
        record = dict(draft)
    elif isinstance(draft, Mapping):
        record = _record_from_parameter_set(**dict(draft))
    else:
        raise TypeError(
            "save_parameter_set expects a canonical record dict, a kwargs draft "
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


def query_parameter_sets(
    *,
    id: str | None = None,
    short_id_prefix: str | None = None,
    name: str | None = None,
    material_kind: str | None = None,
    material_spec_id: str | None = None,
    cell_spec_id: str | None = None,
    scope: str | None = None,
    parameter: str | None = None,
    source_root: PathLike | None = None,
    include_packaged_examples: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query saved parameter sets; the collation entry point.

    ``material_kind`` accepts a kind key or alias. ``parameter`` filters to
    sets carrying at least one claim for that (canonical) parameter key. The
    returned rows carry the full ``record`` so results feed straight into
    :func:`battinfo.parameters.collate_claims`.
    """
    from battinfo.materials import resolve_material_kind  # noqa: PLC0415
    from battinfo.parameters import resolve_parameter  # noqa: PLC0415

    kind_filter = resolve_material_kind(material_kind) if material_kind is not None else None
    if material_kind is not None and kind_filter is None:
        kind_filter = material_kind  # unknown kind: filter verbatim, matches nothing curated
    parameter_filter = (resolve_parameter(parameter) or parameter) if parameter is not None else None

    records: list[dict[str, Any]] = []
    for path, origin in _query_record_files(
        "parameter-set",
        source_root=source_root,
        directory=None,
        include_packaged_examples=include_packaged_examples,
    ):
        doc = _load_json(path)
        body = doc.get("parameter_set")
        if not isinstance(body, Mapping):
            continue
        records.append({
            "id": body.get("id"),
            "short_id": body.get("short_id"),
            "name": body.get("name"),
            "material_kind": body.get("material_kind"),
            "material_spec_id": body.get("material_spec_id"),
            "cell_spec_id": body.get("cell_spec_id"),
            "scope": body.get("scope"),
            "parameters": sorted({
                c.get("parameter")
                for c in body.get("claims", [])
                if isinstance(c, Mapping) and c.get("parameter")
            }),
            "origin": origin,
            "path": str(path),
            "record": doc,
        })

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if short_id_prefix and not str(rec.get("short_id", "")).lower().startswith(
            short_id_prefix.lower()
        ):
            continue
        if not _str_eq(rec.get("name"), name):
            continue
        if kind_filter is not None and rec.get("material_kind") != kind_filter:
            continue
        if material_spec_id is not None and rec.get("material_spec_id") != material_spec_id:
            continue
        if cell_spec_id is not None and rec.get("cell_spec_id") != cell_spec_id:
            continue
        if scope is not None and rec.get("scope") != scope:
            continue
        if parameter_filter is not None and parameter_filter not in rec.get("parameters", []):
            continue
        filtered.append(rec)
    return _paginate(filtered, limit=limit, offset=offset)
