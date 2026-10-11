"""Parameter sets: one source's parameter claims, in two flavours.

A ``parameter-set`` record carries simulation-parameter *claims* (scalar
quantities, tabulated curves, or expression strings). A **claim batch** makes
its claims about exactly one target:

- ``material_kind`` — a generic chemistry from the curated material_kinds
  vocabulary ("graphite", "nmc811"): where literature claims collate;
- ``material_spec_id`` — a specific vendor product/grade;
- ``cell_spec_id`` — a cell spec, for cell-level fitted sets and for the
  electrode/separator/electrolyte build parameters of that design.

Its uid is minted deterministically from (target, scope, name), so
re-importing the same source is idempotent, never a duplicate.

A **parameter file** is one published parameter file (a BPX file): every value
it holds, grouped into ``parts`` (cell, materials, electrodes, separator,
electrolyte, state), on one record linked to the cell it describes
(``cell_spec_id``, ``cell_instance_id``) or marked ``virtual_cell``. Its uid
derives from ``parameters_sha256``, the digest of the file's RFC 8785
canonical form (IDENTIFIER_POLICY 6.3), and it carries the file itself under
``distributions``.

Either way the record-level provenance block carries the source citation and
each claim carries its own provenance class.

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
    CELL_IRI_RE,
    DEFAULT_REGISTRATION_SOURCE_ROOT,
    DUPLICATE_POLICY_ERROR,
    MATERIAL_SPEC_IRI_RE,
    REGISTER_MODE_CREATE_ONLY,
    SPEC_IRI_RE,
    PathLike,
    _iri_tail,
    _normalized_dashed_uid,
    _paginate,
    _query_record_files,
    _resolved_retrieved_at,
    _str_eq,
    _validate_canonical_record,
    _without_minted_identity,
)
from battinfo.bundle import SCHEMA_VERSION, stamp_provenance
from battinfo.canonical_aliases import record_to_snake_aliases
from battinfo.entities import stable_uid
from battinfo.validate.core import DEFAULT_POLICY, ValidationPolicy

_PARAMETER_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PROVENANCE_CLASSES = ("measured", "fitted", "literature", "assumed", "derived")
_SCOPES = ("material", "electrode", "separator", "electrolyte", "cell")
_TARGET_FIELDS = ("material_kind", "material_spec_id", "cell_spec_id")


def _checked_claim(
    claim: Any, index: int, default_provenance_class: str | None, where: str = "claims"
) -> dict[str, Any]:
    """Validate one claim dict beyond what JSON Schema can express."""
    if not isinstance(claim, Mapping):
        raise ValueError(f"{where}[{index}] must be a mapping, got {type(claim).__name__}.")
    out = dict(claim)
    parameter = out.get("parameter")
    if not isinstance(parameter, str) or not _PARAMETER_KEY_RE.fullmatch(parameter):
        raise ValueError(
            f"{where}[{index}].parameter must be a snake_case key (got {parameter!r}). "
            "Known keys: battinfo.parameters.parameter_keys(); unknown keys are "
            "allowed but never count toward model-tier completeness."
        )
    value_fields = [f for f in ("quantity", "curve", "expression") if out.get(f) is not None]
    if len(value_fields) != 1:
        raise ValueError(
            f"{where}[{index}] ({parameter}) must carry exactly one of quantity, "
            f"curve, expression (got {value_fields or 'none'})."
        )
    curve = out.get("curve")
    if curve is not None:
        if not isinstance(curve, Mapping):
            raise ValueError(f"{where}[{index}].curve must be a mapping.")
        xs, ys = curve.get("x"), curve.get("y")
        if not isinstance(xs, list) or not isinstance(ys, list) or len(xs) != len(ys):
            raise ValueError(
                f"{where}[{index}].curve ({parameter}): x and y must be lists of equal length."
            )
        if len(xs) < 2:
            raise ValueError(f"{where}[{index}].curve ({parameter}): need at least 2 points.")
        for name, values in (("x", xs), ("y", ys)):
            for v in values:
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                    raise ValueError(
                        f"{where}[{index}].curve ({parameter}): {name} contains a "
                        f"non-finite or non-numeric value ({v!r})."
                    )
    provenance_class = out.get("provenance_class")
    if provenance_class is None and default_provenance_class is not None:
        provenance_class = default_provenance_class
        out["provenance_class"] = provenance_class
    if provenance_class is not None and provenance_class not in _PROVENANCE_CLASSES:
        raise ValueError(
            f"{where}[{index}].provenance_class must be one of "
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


_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_FILE_LINK_FIELDS = ("cell_spec_id", "cell_instance_id", "virtual_cell")
_PART_FIELDS = frozenset({"part", "phase", "material_kind", "material_spec_id", "claims"})


def parameter_file_uid(parameters_sha256: str) -> str:
    """The uid of a parameter file's record (IDENTIFIER_POLICY 6.3).

    ``stable_uid("parameter-set-file:<parameters_sha256>")``: the IRI names
    the file's parameters, so anyone holding the file can check it against
    the IRI.
    """
    return stable_uid(f"parameter-set-file:{parameters_sha256}")


def _part_label(part: Mapping[str, Any]) -> str:
    phase = part.get("phase")
    return f"{part.get('part')!r}" + (f" (phase {phase!r})" if phase is not None else "")


def _checked_parts(parts: Any, default_provenance_class: str | None) -> list[dict[str, Any]]:
    """Validate a parameter file's parts; return them in canonical part order."""
    from battinfo.materials import material_kind_keys, resolve_material_kind  # noqa: PLC0415
    from battinfo.parameters import MATERIAL_PARTS, PARAMETER_FILE_PARTS  # noqa: PLC0415

    if not isinstance(parts, list) or not parts:
        raise ValueError("parts must be a non-empty list of {part, claims} dicts.")
    checked: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None]] = set()
    for index, part in enumerate(parts):
        if not isinstance(part, Mapping):
            raise ValueError(f"parts[{index}] must be a mapping, got {type(part).__name__}.")
        name = part.get("part")
        if name not in PARAMETER_FILE_PARTS:
            raise ValueError(
                f"parts[{index}].part must be one of {', '.join(PARAMETER_FILE_PARTS)}; got {name!r}."
            )
        unknown = sorted(set(part) - _PART_FIELDS)
        if unknown:
            raise ValueError(f"parts[{index}] ({name}) has unknown fields: {', '.join(unknown)}.")
        phase = part.get("phase")
        if phase is not None and (not isinstance(phase, str) or not phase.strip()):
            raise ValueError(f"parts[{index}].phase must be a non-empty string.")
        if phase is not None and name not in MATERIAL_PARTS:
            raise ValueError(
                f"parts[{index}] ({name}): only a material part ({', '.join(MATERIAL_PARTS)}) has a "
                "phase, the particle phase of a blended electrode."
            )
        if (name, phase) in seen:
            raise ValueError(
                f"parts[{index}]: part {_part_label(part)} appears twice; each (part, phase) "
                "pair names one part of the file."
            )
        seen.add((name, phase))
        out: dict[str, Any] = {"part": name}
        if phase is not None:
            out["phase"] = phase
        kind, spec = part.get("material_kind"), part.get("material_spec_id")
        if kind is not None or spec is not None:
            if name not in MATERIAL_PARTS:
                raise ValueError(
                    f"parts[{index}] ({name}): only a material part "
                    f"({', '.join(MATERIAL_PARTS)}) names a material."
                )
            if kind is not None and spec is not None:
                raise ValueError(
                    f"parts[{index}] ({name}) names its material twice: give material_kind "
                    "or material_spec_id, not both."
                )
            if kind is not None:
                resolved = resolve_material_kind(kind)
                if resolved is None:
                    raise ValueError(
                        f"parts[{index}] ({name}): unknown material kind {kind!r}. Valid kinds: "
                        f"{', '.join(material_kind_keys())}."
                    )
                out["material_kind"] = resolved
            else:
                if not MATERIAL_SPEC_IRI_RE.fullmatch(str(spec)):
                    raise ValueError(
                        f"parts[{index}] ({name}): material_spec_id must be a canonical "
                        "material-spec IRI (https://w3id.org/battinfo/spec/{uid})."
                    )
                out["material_spec_id"] = str(spec)
        claims = part.get("claims")
        if not isinstance(claims, list) or not claims:
            raise ValueError(f"parts[{index}] ({name}) needs a non-empty claims list.")
        out["claims"] = [
            _checked_claim(claim, i, default_provenance_class, where=f"parts[{index}].claims")
            for i, claim in enumerate(claims)
        ]
        checked.append(out)
    order = {part: rank for rank, part in enumerate(PARAMETER_FILE_PARTS)}
    checked.sort(key=lambda item: order[item["part"]])  # stable: phases keep their order
    return checked


def _checksum_hex(entry: Mapping[str, Any]) -> str | None:
    checksum = entry.get("checksum")
    if isinstance(checksum, Mapping) and isinstance(checksum.get("value"), str):
        return checksum["value"]
    return None


def parameter_file_issues(body: Mapping[str, Any]) -> list[tuple[str, str, str, str]]:
    """The rules of a parameter-file record that JSON Schema cannot state.

    Returns ``(code, severity, path, message)`` tuples: an IRI the
    fingerprint does not give, a (part, phase) pair used twice, a runnable
    file that does not name the source's checksum, a mirror whose checksum
    differs from the source's (all errors: integrity, under every
    validation policy), and a runnable file next to a source the official
    parser accepts (a warning: a runnable copy is made only when the parser
    rejects the source). The source and runnable counts are reported too
    (``*_count`` codes), for callers that run without the schema. The
    builder raises on the errors; the record validator reports them.
    """
    issues: list[tuple[str, str, str, str]] = []
    fingerprint = body.get("parameters_sha256")
    if isinstance(fingerprint, str) and _SHA256_HEX_RE.fullmatch(fingerprint):
        expected = f"https://w3id.org/battinfo/spec/{parameter_file_uid(fingerprint)}"
        if body.get("id") != expected:
            issues.append((
                "id_mismatch", "error", "parameter_set.id",
                f"a parameter file's IRI derives from its parameters_sha256 "
                f"(stable_uid('parameter-set-file:' + parameters_sha256), IDENTIFIER_POLICY 6.3): "
                f"it must be {expected}, not {body.get('id')}.",
            ))
    seen: set[tuple[Any, Any]] = set()
    for index, part in enumerate(body.get("parts") or []):
        if not isinstance(part, Mapping):
            continue
        key = (part.get("part"), part.get("phase"))
        if key in seen:
            issues.append((
                "part_repeated", "error", f"parameter_set.parts[{index}]",
                f"part {_part_label(part)} appears twice; each (part, phase) pair names one "
                "part of the file.",
            ))
        seen.add(key)

    distributions = body.get("distributions")
    if not isinstance(distributions, list):
        return issues
    entries = [(i, d) for i, d in enumerate(distributions) if isinstance(d, Mapping)]
    sources = [(i, d) for i, d in entries if d.get("role") == "source"]
    runnables = [(i, d) for i, d in entries if d.get("role") == "runnable"]
    if len(sources) != 1:
        issues.append((
            "source_count", "error", "parameter_set.distributions",
            f"a parameter file carries exactly one source file; found {len(sources)}.",
        ))
    if len(runnables) > 1:
        issues.append((
            "runnable_count", "error", "parameter_set.distributions",
            f"a parameter file carries at most one runnable file; found {len(runnables)}.",
        ))
    if len(sources) != 1:
        return issues
    source = sources[0][1]
    source_hex = _checksum_hex(source)
    for index, entry in entries:
        role = entry.get("role")
        if role == "runnable" and source_hex is not None:
            derived = entry.get("derived_from")
            if derived != f"sha256:{source_hex}":
                issues.append((
                    "runnable_not_from_source", "error",
                    f"parameter_set.distributions[{index}].derived_from",
                    f"a runnable file must name the source it was converted from: derived_from is "
                    f"{derived!r}, the source checksum is 'sha256:{source_hex}'.",
                ))
        elif role == "mirror" and _checksum_hex(entry) != source_hex:
            issues.append((
                "mirror_checksum_differs", "error",
                f"parameter_set.distributions[{index}].checksum",
                "a mirror serves the source's exact bytes, so its checksum must equal the "
                f"source's ({source_hex}).",
            ))
    source_parses = any(
        isinstance(check, Mapping) and check.get("check") == "bpx_parse" and check.get("passed") is True
        for check in source.get("checks") or []
    )
    if runnables and source_parses:
        issues.append((
            "runnable_not_needed", "warning",
            f"parameter_set.distributions[{runnables[0][0]}]",
            "the source carries a passing bpx_parse check, so the official parser reads it as "
            "published: a runnable copy is made only when the parser rejects the source.",
        ))
    return issues


def _record_from_parameter_set(
    *,
    name: str,
    handle: str | None = None,
    claims: list[Any] | None = None,
    parts: list[Any] | None = None,
    material_kind: str | None = None,
    material_spec_id: str | None = None,
    cell_spec_id: str | None = None,
    cell_instance_id: str | None = None,
    virtual_cell: bool = False,
    parameters_sha256: str | None = None,
    scope: str | None = None,
    electrode_polarity: str | None = None,
    model_context: Mapping[str, Any] | None = None,
    annex: Mapping[str, Any] | None = None,
    not_imported: list[str] | None = None,
    distributions: list[Mapping[str, Any]] | None = None,
    supersedes: str | None = None,
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
    license: str | None = None,
) -> dict[str, Any]:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("parameter set needs a non-empty name (convention: '<source> - <target>').")

    if parts is not None:
        body = _parameter_file_body(
            name=name,
            handle=handle,
            parts=parts,
            stray={
                "claims": claims,
                "material_kind": material_kind,
                "material_spec_id": material_spec_id,
                "scope": scope,
                "electrode_polarity": electrode_polarity,
            },
            cell_spec_id=cell_spec_id,
            cell_instance_id=cell_instance_id,
            virtual_cell=virtual_cell,
            parameters_sha256=parameters_sha256,
            uid=uid,
            id=id,
            default_provenance_class=default_provenance_class,
        )
    else:
        file_only = [
            field
            for field, value in (
                ("cell_instance_id", cell_instance_id),
                ("virtual_cell", virtual_cell or None),
                ("parameters_sha256", parameters_sha256),
                ("distributions", distributions or None),
                ("not_imported", not_imported or None),
                ("supersedes", supersedes),
            )
            if value is not None
        ]
        if file_only:
            raise ValueError(
                f"{', '.join(file_only)} belong to a parameter file (pass parts=...); a claim "
                "batch states claims about one target and carries no file."
            )
        body = _claim_batch_body(
            name=name,
            handle=handle,
            claims=claims,
            material_kind=material_kind,
            material_spec_id=material_spec_id,
            cell_spec_id=cell_spec_id,
            scope=scope,
            electrode_polarity=electrode_polarity,
            uid=uid,
            id=id,
            default_provenance_class=default_provenance_class,
        )

    if model_context:
        body["model_context"] = dict(model_context)
    if parts is not None:
        body["parts"] = body.pop("parts")  # after model_context, before the file
    if annex:
        # Source-file extension entries (e.g. a BPX User-defined block),
        # verbatim: no semantics claimed, carried so re-export loses nothing.
        body["annex"] = dict(annex)
    if not_imported:
        # The source file's values the record does not hold, by BPX path.
        if not isinstance(not_imported, list) or not all(
            isinstance(item, str) and item for item in not_imported
        ):
            raise ValueError("not_imported must be a list of BPX paths (non-empty strings).")
        body["not_imported"] = list(dict.fromkeys(not_imported))
    if supersedes is not None:
        if not SPEC_IRI_RE.fullmatch(str(supersedes)):
            raise ValueError("supersedes must be a parameter-set IRI: https://w3id.org/battinfo/spec/{uid}.")
        if supersedes == body["id"]:
            raise ValueError("a parameter file cannot supersede itself: supersedes names an earlier record.")
        body["supersedes"] = str(supersedes)
    if distributions is not None and not isinstance(distributions, list):
        raise TypeError(
            "distributions is a list of parameter-file dicts (entries from "
            f"bpx_file_distribution()), not {type(distributions).__name__}."
        )
    if distributions:
        # The parameter file itself: the source bytes, optionally a declared
        # runnable conversion and mirrors. The schema checks each entry's
        # shape; the cross-entry rules are checked here.
        if not all(isinstance(item, Mapping) for item in distributions):
            raise TypeError("each distributions entry is a parameter-file dict (from bpx_file_distribution()).")
        body["distributions"] = [dict(item) for item in distributions]
        errors = [
            message
            for _code, severity, _path, message in parameter_file_issues(body)
            if severity == "error"
        ]
        if errors:
            raise ValueError("distributions: " + " ".join(errors))
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
    if license is not None:
        record["license"] = license
    return record_to_snake_aliases(record)


def _claim_batch_body(
    *,
    name: str,
    handle: str | None,
    claims: list[Any] | None,
    material_kind: str | None,
    material_spec_id: str | None,
    cell_spec_id: str | None,
    scope: str | None,
    electrode_polarity: str | None,
    uid: str | None,
    id: str | None,
    default_provenance_class: str | None,
) -> dict[str, Any]:
    """A claim batch's body: one source's claims about exactly one target."""
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
        raise ValueError(
            "claims must be a non-empty list of claim dicts (or pass parts=... for a "
            "parameter file)."
        )
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
        **({"handle": handle} if handle is not None else {}),
        target_field: target_value,
        "scope": scope,
        "claims": checked_claims,
    }
    if electrode_polarity is not None:
        body["electrode_polarity"] = electrode_polarity
    return body


def _parameter_file_body(
    *,
    name: str,
    handle: str | None,
    parts: Any,
    stray: Mapping[str, Any],
    cell_spec_id: str | None,
    cell_instance_id: str | None,
    virtual_cell: bool,
    parameters_sha256: str | None,
    uid: str | None,
    id: str | None,
    default_provenance_class: str | None,
) -> dict[str, Any]:
    """A parameter file's body: its parts, its fingerprint and its one cell link."""
    misplaced = [field for field, value in stray.items() if value is not None]
    if misplaced:
        raise ValueError(
            f"{', '.join(misplaced)} belong to a claim batch; a parameter file groups its "
            "claims by part and links one cell."
        )
    if virtual_cell not in (True, False, None):
        raise ValueError(f"virtual_cell must be True or False; got {virtual_cell!r}.")
    links = [
        field
        for field, value in (
            ("cell_spec_id", cell_spec_id),
            ("cell_instance_id", cell_instance_id),
            ("virtual_cell", True if virtual_cell else None),
        )
        if value is not None
    ]
    if len(links) != 1:
        raise ValueError(
            "a parameter file links exactly one of cell_spec_id (the cell design), "
            "cell_instance_id (the one physical cell it was fitted on) or virtual_cell=True "
            f"(no real cell); got {links or 'none'}. BattINFO does not guess which cell a file "
            "describes."
        )
    link_field = links[0]
    if link_field == "cell_spec_id" and not SPEC_IRI_RE.fullmatch(str(cell_spec_id)):
        raise ValueError("cell_spec_id must match https://w3id.org/battinfo/spec/{uid}.")
    if link_field == "cell_instance_id" and not CELL_IRI_RE.fullmatch(str(cell_instance_id)):
        raise ValueError("cell_instance_id must match https://w3id.org/battinfo/cell/{uid}.")
    link_value: Any = {"cell_spec_id": cell_spec_id, "cell_instance_id": cell_instance_id}.get(
        link_field, True
    )

    if not isinstance(parameters_sha256, str) or not _SHA256_HEX_RE.fullmatch(parameters_sha256):
        raise ValueError(
            "a parameter file needs parameters_sha256: the lowercase-hex SHA-256 of the "
            "file's RFC 8785 canonical form (battinfo.interop.bpx_content_digest)."
        )
    dashed_uid = parameter_file_uid(parameters_sha256)
    entity_id = f"https://w3id.org/battinfo/spec/{dashed_uid}"
    given = id if id is not None else (
        f"https://w3id.org/battinfo/spec/{_normalized_dashed_uid(uid)}" if uid is not None else None
    )
    if given is not None and given != entity_id:
        raise ValueError(
            f"a parameter file's IRI derives from its parameters_sha256 ({entity_id}); "
            f"got {given}. Leave id/uid out."
        )

    return {
        "id": entity_id,
        "short_id": dashed_uid.replace("-", "")[:6],
        "name": name.strip(),
        **({"handle": handle} if handle is not None else {}),
        link_field: link_value,
        "parameters_sha256": parameters_sha256,
        "parts": _checked_parts(parts, default_provenance_class),
    }


def create_parameter_set(*, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical parameter-set document: a claim batch or a parameter file.

    A claim batch (``claims=``) targets exactly one of ``material_kind``
    (curated kind key or alias), ``material_spec_id``, ``cell_spec_id``; its
    uid derives deterministically from (target, scope, name), so the same
    source re-imports onto the same IRI.

    A parameter file (``parts=``, one BPX file; build it with
    :meth:`battinfo.interop.BpxParameterImportResult.to_parameter_set`) groups
    its claims by part, names exactly one of ``cell_spec_id``,
    ``cell_instance_id``, ``virtual_cell=True``, and states
    ``parameters_sha256``, from which its uid derives. Its ``distributions``
    hold exactly one source file, at most one runnable conversion that names
    the source's checksum, and mirrors of the source's bytes;
    ``not_imported`` lists the BPX paths of the file's values the record does
    not hold, and ``supersedes`` the record of an earlier file it corrects.

    Each claim carries exactly one of ``quantity`` / ``curve`` /
    ``expression`` plus its ``provenance_class`` (``default_provenance_class=``
    fills claims that omit it).
    """
    record = _record_from_parameter_set(**fields)
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def template_parameter_set(
    *, name: str = "Example source - graphite", uid: str | None = None
) -> dict[str, Any]:
    """Build a starter canonical parameter-set document for save workflows.

    The document has no ``id`` unless *uid* is given; saving it mints the IRI
    from the filled-in target, scope and name.
    """
    record = _record_from_parameter_set(
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
    return record if uid is not None else _without_minted_identity(record)


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
    cell_instance_id: str | None = None,
    scope: str | None = None,
    parameter: str | None = None,
    source_root: PathLike | None = None,
    include_packaged_examples: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query saved parameter sets; the collation entry point.

    ``material_kind`` accepts a kind key or alias. ``material_kind`` and
    ``material_spec_id`` match a claim batch's target or any material part of
    a parameter file, so a search by material finds both. ``parameter``
    filters to sets carrying at least one claim for that (canonical)
    parameter key, in any part. The returned rows carry the full ``record`` so
    results feed straight into :func:`battinfo.parameters.collate_claims`.
    """
    from battinfo.materials import resolve_material_kind  # noqa: PLC0415
    from battinfo.parameters import parameter_set_claim_groups, resolve_parameter  # noqa: PLC0415

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
        groups = parameter_set_claim_groups(body)
        records.append({
            "id": body.get("id"),
            "short_id": body.get("short_id"),
            "name": body.get("name"),
            "material_kind": body.get("material_kind"),
            "material_spec_id": body.get("material_spec_id"),
            "cell_spec_id": body.get("cell_spec_id"),
            "cell_instance_id": body.get("cell_instance_id"),
            "virtual_cell": bool(body.get("virtual_cell")),
            "supersedes": body.get("supersedes"),
            "scope": body.get("scope"),
            "material_kinds": sorted({ctx["material_kind"] for ctx, _ in groups if ctx.get("material_kind")}),
            "material_spec_ids": sorted({
                ctx["material_spec_id"] for ctx, _ in groups if ctx.get("material_spec_id")
            }),
            "parameters": sorted({
                c.get("parameter")
                for _, claims in groups
                for c in claims
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
        if kind_filter is not None and kind_filter not in rec["material_kinds"]:
            continue
        if material_spec_id is not None and material_spec_id not in rec["material_spec_ids"]:
            continue
        if cell_spec_id is not None and rec.get("cell_spec_id") != cell_spec_id:
            continue
        if cell_instance_id is not None and rec.get("cell_instance_id") != cell_instance_id:
            continue
        if scope is not None and rec.get("scope") != scope:
            continue
        if parameter_filter is not None and parameter_filter not in rec.get("parameters", []):
            continue
        filtered.append(rec)
    return _paginate(filtered, limit=limit, offset=offset)
