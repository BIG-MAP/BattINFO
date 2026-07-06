"""Staging validate/promote flows and the curated submission-envelope builders.

Split from the former monolithic ``battinfo/api.py`` (beta-hardening 4.2);
import the public surface from ``battinfo.api``, not from this module.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from battinfo._jsonio import read_record_json as _load_json
from battinfo._jsonio import write_json as _write_json
from battinfo._util import _as_path, _now_iso
from battinfo.api._records import _record_from_cell_spec
from battinfo.api._shared import PathLike, _comment_list, _editorial_date_token, _editorial_record_id, _to_unix_time
from battinfo.bundle import (
    SCHEMA_VERSION,
    CellSpec,
)
from battinfo.canonical_aliases import record_to_snake_aliases
from battinfo.validate.core import DEFAULT_POLICY, ValidationPolicy
from battinfo.validate.record import validate_record


def _validate_record_report(record, *, policy):  # noqa: ANN001, ANN202
    """Validate via ``battinfo.api`` so tests that monkeypatch
    ``battinfo.api.validate_record_report`` keep affecting the staging flows,
    as they did when this code lived in the monolithic api module."""
    import battinfo.api as _facade  # noqa: PLC0415

    return _facade.validate_record_report(record, policy=policy)


def _staging_cell_spec_identity(
    source: dict[str, Any] | PathLike,
    draft: CellSpec,
) -> dict[str, Any]:
    if isinstance(source, (str, Path)):
        payload = _load_json(_as_path(source))
    else:
        payload = dict(source)
    provenance = payload.get("provenance")
    provenance_map = provenance if isinstance(provenance, Mapping) else {}

    base_record_id = _editorial_record_id(draft.manufacturer, draft.model)

    if draft.year is not None:
        resolved = _editorial_record_id(draft.manufacturer, draft.model, draft.year)
        return {
            "record_id": resolved,
            "record_id_basis": "year",
            "record_id_hint": resolved,
            "requires_record_id": False,
        }

    revision_candidates = (
        payload.get("datasheet_revision"),
        provenance_map.get("datasheet_revision"),
        provenance_map.get("revision"),
        provenance_map.get("source_id"),
    )
    for candidate in revision_candidates:
        if isinstance(candidate, str) and candidate.strip():
            resolved = _editorial_record_id(draft.manufacturer, draft.model, candidate)
            return {
                "record_id": resolved,
                "record_id_basis": "revision",
                "record_id_hint": resolved,
                "requires_record_id": False,
            }

    date_candidates = (
        payload.get("observed_at"),
        payload.get("evidence_date"),
        payload.get("retrieved_at"),
        provenance_map.get("observed_at"),
        provenance_map.get("evidence_date"),
        provenance_map.get("retrieved_at"),
    )
    for candidate in date_candidates:
        date_token = _editorial_date_token(candidate)
        if date_token is not None:
            resolved = _editorial_record_id(draft.manufacturer, draft.model, date_token)
            return {
                "record_id": resolved,
                "record_id_basis": "evidence_date",
                "record_id_hint": resolved,
                "requires_record_id": False,
            }

    return {
        "record_id": None,
        "record_id_basis": None,
        "record_id_hint": f"{base_record_id}--<year-or-revision>",
        "requires_record_id": True,
    }


def _staging_cell_spec_input(
    source: dict[str, Any] | PathLike,
    *,
    uid: str | None = None,
) -> tuple[CellSpec, Path | None]:
    source_path: Path | None = None
    if isinstance(source, (str, Path)):
        source_path = _as_path(source)
        payload = _load_json(source_path)
    else:
        payload = dict(source)

    if isinstance(payload.get("cell_spec"), Mapping) or isinstance(payload.get("cell_spec"), Mapping):
        record_payload = dict(payload)
        if isinstance(record_payload.get("cell_spec"), Mapping) and "cell_spec" not in record_payload:
            record_payload["cell_spec"] = dict(record_payload["cell_spec"])
        product = record_payload.get("cell_spec")
        provenance = record_payload.get("provenance")
        if not isinstance(product, Mapping):
            raise ValueError("canonical cell-spec record is missing product.")
        manufacturer_obj = product.get("manufacturer")
        manufacturer = manufacturer_obj.get("name") if isinstance(manufacturer_obj, Mapping) else manufacturer_obj
        return (
            CellSpec(
                schema_version=str(record_payload.get("schema_version") or "0.1.0"),
                id=product.get("id") if isinstance(product.get("id"), str) else None,
                uid=uid,
                model_name=str(product.get("model") or product.get("model_name") or ""),
                manufacturer=str(manufacturer or ""),
                format=str(product.get("cell_format") or product.get("cell_format") or product.get("format") or "unknown"),
                chemistry=str(product.get("chemistry") or "unknown"),
                positive_electrode_basis=(product.get("positive_electrode_basis") or product.get("positive_electrode_basis"))
                if isinstance(product.get("positive_electrode_basis") or product.get("positive_electrode_basis"), str)
                else None,
                negative_electrode_basis=(product.get("negative_electrode_basis") or product.get("negative_electrode_basis"))
                if isinstance(product.get("negative_electrode_basis") or product.get("negative_electrode_basis"), str)
                else None,
                size_code=(product.get("size_code") if isinstance(product.get("size_code"), str) else product.get("size_code") if isinstance(product.get("size_code"), str) else None),
                iec_code=(product.get("iec_code") if isinstance(product.get("iec_code"), str) else product.get("iec_code") if isinstance(product.get("iec_code"), str) else None),
                country_of_origin=(product.get("country_of_origin") if isinstance(product.get("country_of_origin"), str) else product.get("country_of_origin") if isinstance(product.get("country_of_origin"), str) else None),
                year=product.get("year") if isinstance(product.get("year"), int) else None,
                datasheet_revision=(product.get("datasheet_revision") or product.get("datasheet_revision"))
                if isinstance(product.get("datasheet_revision") or product.get("datasheet_revision"), str)
                else None,
                specs=dict(record_payload.get("properties") or {}),
                source_type=str(provenance.get("source_type")) if isinstance(provenance, Mapping) and provenance.get("source_type") else None,
                source_file=(
                    str(provenance.get("source_file"))
                    if isinstance(provenance, Mapping) and isinstance(provenance.get("source_file"), str)
                    else source_path.name if source_path is not None else None
                ),
                source_url=provenance.get("source_url") if isinstance(provenance, Mapping) and isinstance(provenance.get("source_url"), str) else None,
                citation=provenance.get("citation") if isinstance(provenance, Mapping) and isinstance(provenance.get("citation"), str) else None,
                file_hash=provenance.get("file_hash") if isinstance(provenance, Mapping) and isinstance(provenance.get("file_hash"), str) else None,
                retrieved_at=_to_unix_time(provenance.get("retrieved_at")) if isinstance(provenance, Mapping) else None,
                notes=_comment_list(record_payload.get("notes")),
            ),
            source_path,
        )

    model_name = payload.get("model_name")
    if model_name is None:
        model_name = payload.get("model")
    manufacturer = payload.get("manufacturer")
    format_value = payload.get("format")
    chemistry = payload.get("chemistry")
    if not all(isinstance(value, str) and value.strip() for value in (manufacturer, model_name, format_value, chemistry)):
        raise ValueError("staging cell-spec JSON requires non-empty string fields: manufacturer, model/model_name, format, chemistry.")

    specs = payload.get("properties")
    if specs is None:
        specs = {}
    if not isinstance(specs, Mapping):
        raise ValueError("staging cell-spec JSON field 'properties' must be an object when provided.")

    provenance = payload.get("provenance")
    if provenance is None:
        provenance = {}
    if not isinstance(provenance, Mapping):
        raise ValueError("staging cell-spec JSON field 'provenance' must be an object when provided.")

    year = payload.get("year")
    parsed_year = year if isinstance(year, int) else int(year) if isinstance(year, str) and year.strip().isdigit() else None
    retrieved_at = payload.get("retrieved_at", provenance.get("retrieved_at"))

    return (
        CellSpec(
            uid=uid,
            manufacturer=manufacturer.strip(),
            model_name=str(model_name).strip(),
            chemistry=chemistry.strip(),
            format=format_value.strip(),  # type: ignore[arg-type]
            positive_electrode_basis=payload.get("positive_electrode_basis")
            if isinstance(payload.get("positive_electrode_basis"), str)
            else None,
            negative_electrode_basis=payload.get("negative_electrode_basis")
            if isinstance(payload.get("negative_electrode_basis"), str)
            else None,
            size_code=payload.get("size_code") if isinstance(payload.get("size_code"), str) else None,
            iec_code=payload.get("iec_code") if isinstance(payload.get("iec_code"), str) else None,
            country_of_origin=payload.get("country_of_origin") if isinstance(payload.get("country_of_origin"), str) else None,
            year=parsed_year,
            datasheet_revision=payload.get("datasheet_revision") if isinstance(payload.get("datasheet_revision"), str) else None,
            specs=dict(specs),
            source_type=str(payload.get("source_type", provenance.get("source_type")) or "") or None,
            source_file=(
                str(payload.get("source_file", provenance.get("source_file")))
                if isinstance(payload.get("source_file", provenance.get("source_file")), str)
                else source_path.name if source_path is not None else None
            ),
            source_url=payload.get("source_url", provenance.get("source_url"))
            if isinstance(payload.get("source_url", provenance.get("source_url")), str)
            else None,
            citation=payload.get("citation", provenance.get("citation"))
            if isinstance(payload.get("citation", provenance.get("citation")), str)
            else None,
            file_hash=payload.get("file_hash", provenance.get("file_hash"))
            if isinstance(payload.get("file_hash", provenance.get("file_hash")), str)
            else None,
            retrieved_at=_to_unix_time(retrieved_at),
            notes=_comment_list(payload.get("notes", payload.get("comment"))),
        ),
        source_path,
    )


def validate_staging_cell_spec(
    source: dict[str, Any] | PathLike,
    *,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    """Validate a staging cell-spec draft without writing anything to disk.

    Returns a dict with keys ``ok`` (bool), ``source_path``, ``record_id``,
    ``record_id_basis``, ``issues`` (list of validation issue dicts), and
    ``errors`` (list of error-severity issues only).
    """
    draft, source_path = _staging_cell_spec_input(source)
    identity = _staging_cell_spec_identity(source, draft)
    record = _record_from_cell_spec(draft)
    report = _validate_record_report(record, policy=validation_policy)
    return {
        "ok": report.ok,
        "source_path": str(source_path) if source_path is not None else None,
        "record_id": identity["record_id"],
        "record_id_basis": identity["record_id_basis"],
        "record_id_hint": identity["record_id_hint"],
        "requires_record_id": identity["requires_record_id"],
        "record": record,
        "issues": [
            {
                "severity": issue.severity,
                "code": issue.code,
                "path": issue.path,
                "message": issue.message,
                "hint": issue.hint,
            }
            for issue in report.issues
        ],
    }


def validate_staging_cell_specs(
    *,
    input_dir: PathLike,
    glob: str = "*.json",
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    input_root = _as_path(input_dir)
    if not input_root.exists() or not input_root.is_dir():
        raise ValueError(f"input_dir does not exist: {input_root}")
    results: list[dict[str, Any]] = []
    for path in sorted(input_root.glob(glob)):
        if path.name.startswith("_"):
            continue
        results.append(validate_staging_cell_spec(path, validation_policy=validation_policy))
    return {
        "status": "ok",
        "input_dir": str(input_root),
        "processed": len(results),
        "ok": sum(1 for item in results if item["ok"]),
        "failed": sum(1 for item in results if not item["ok"]),
        "results": results,
    }


def _existing_curated_cell_spec_id(target_path: Path) -> str | None:
    if not target_path.exists():
        return None
    try:
        payload = _load_json(target_path)
    except Exception:  # noqa: BLE001
        return None
    product = payload.get("cell_spec")
    if isinstance(product, Mapping) and isinstance(product.get("id"), str):
        return product["id"]
    return None


def promote_staging_cell_spec(
    source: dict[str, Any] | PathLike,
    *,
    curated_root: PathLike,
    record_id: str | None = None,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Promote a validated staging cell-spec draft to the curated record store.

    Validates the draft, assigns or resolves the canonical record IRI, writes
    the canonical JSON file to ``curated_root``, and returns a result dict with
    keys ``ok``, ``record_id``, ``path``, ``dry_run``, and ``issues``.

    Pass ``dry_run=True`` to validate and resolve the IRI without writing files.
    """
    draft, source_path = _staging_cell_spec_input(source)
    identity = _staging_cell_spec_identity(source, draft)
    if record_id is not None:
        resolved_record_id = _editorial_record_id(record_id)
    else:
        resolved_record_id = identity["record_id"]
        if not isinstance(resolved_record_id, str) or not resolved_record_id:
            raise ValueError(
                "staging cell-spec does not have a safe automatic record id. "
                f"Provide --record-id explicitly; suggested pattern: {identity['record_id_hint']}."
            )

    curated_root_path = _as_path(curated_root)
    target_path = curated_root_path / resolved_record_id / "record.json"
    existing_id = _existing_curated_cell_spec_id(target_path)
    if existing_id is not None:
        draft = draft.model_copy(update={"id": existing_id, "uid": None})

    record = _record_from_cell_spec(draft)
    report = _validate_record_report(record, policy=validation_policy)
    if not report.ok:
        raise ValueError(f"staging cell-spec validation failed: {'; '.join(report.render_errors())}")

    if not dry_run:
        _write_json(target_path, record)
    return {
        "status": "ok",
        "record_id": resolved_record_id,
        "record_id_basis": identity["record_id_basis"] if record_id is None else "manual",
        "source_path": str(source_path) if source_path is not None else None,
        "target_path": str(target_path),
        "record": record,
        "dry_run": dry_run,
    }


def promote_staging_cell_specs(
    *,
    input_dir: PathLike,
    curated_root: PathLike,
    glob: str = "*.json",
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    input_root = _as_path(input_dir)
    if not input_root.exists() or not input_root.is_dir():
        raise ValueError(f"input_dir does not exist: {input_root}")
    promoted: list[dict[str, Any]] = []
    for path in sorted(input_root.glob(glob)):
        if path.name.startswith("_"):
            continue
        promoted.append(
            promote_staging_cell_spec(
                path,
                curated_root=curated_root,
                validation_policy=validation_policy,
                dry_run=dry_run,
            )
        )
    return {
        "status": "ok",
        "input_dir": str(input_root),
        "curated_root": str(_as_path(curated_root)),
        "processed": len(promoted),
        "dry_run": dry_run,
        "results": promoted,
    }


# ── Staging dataset promotion ─────────────────────────────────────────────────
# Datasets carry their own canonical IRI and `bdc:` identifier, so promotion is
# simpler than cell-spec: no manufacturer/model token derivation. Citations (the
# dataset↔publication links) pass through unchanged into the curated record.

def _staging_dataset_input(source: dict[str, Any] | PathLike) -> tuple[dict[str, Any], Path | None]:
    """Load a staging dataset record (a ``{schema_version, dataset, provenance}`` doc)."""
    source_path: Path | None = None
    if isinstance(source, (str, Path)):
        source_path = _as_path(source)
        payload = _load_json(source_path)
    else:
        payload = record_to_snake_aliases(dict(source))
    if not isinstance(payload.get("dataset"), Mapping):
        raise ValueError("staging dataset record must have a top-level 'dataset' object.")
    return payload, source_path


def _dataset_record_id(value: str) -> str:
    """Canonical curated id for a dataset, preserving the bdc scheme (e.g. 'bdc_000001').

    Unlike ``_editorial_record_id`` (which hyphenates underscores for descriptive
    cell-spec slugs), this keeps the dataset's own identifier intact, stripping only
    a leading namespace prefix such as ``bdc:``.
    """
    token = value.strip().lower()
    if ":" in token:
        token = token.split(":", 1)[-1]
    return re.sub(r"[^a-z0-9_-]+", "-", token).strip("-_")


def _staging_dataset_identity(payload: Mapping[str, Any], source_path: Path | None) -> dict[str, Any]:
    """Resolve the curated record id for a dataset from its identifier/short_id/filename."""
    dataset = payload.get("dataset")
    dataset = dataset if isinstance(dataset, Mapping) else {}
    record_id: str | None = None
    basis = "none"
    for key, source_basis in (("identifier", "identifier"), ("short_id", "short_id")):
        raw = dataset.get(key)
        if isinstance(raw, str) and raw.strip():
            candidate = _dataset_record_id(raw)
            if candidate:
                record_id, basis = candidate, source_basis
                break
    if record_id is None and source_path is not None and source_path.stem and not source_path.stem.startswith("_"):
        candidate = _dataset_record_id(source_path.stem)
        if candidate:
            record_id, basis = candidate, "filename"
    return {
        "record_id": record_id,
        "record_id_basis": basis,
        "record_id_hint": "bdc_000001",
        "requires_record_id": record_id is None,
    }


def validate_staging_dataset(
    source: dict[str, Any] | PathLike,
    *,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    """Validate a staging dataset record without writing anything to disk."""
    payload, source_path = _staging_dataset_input(source)
    identity = _staging_dataset_identity(payload, source_path)
    report = _validate_record_report(payload, policy=validation_policy)
    return {
        "ok": report.ok,
        "source_path": str(source_path) if source_path is not None else None,
        "record_id": identity["record_id"],
        "record_id_basis": identity["record_id_basis"],
        "record_id_hint": identity["record_id_hint"],
        "requires_record_id": identity["requires_record_id"],
        "record": payload,
        "issues": [
            {
                "severity": issue.severity,
                "code": issue.code,
                "path": issue.path,
                "message": issue.message,
                "hint": issue.hint,
            }
            for issue in report.issues
        ],
    }


def validate_staging_datasets(
    *,
    input_dir: PathLike,
    glob: str = "*.json",
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    """Validate every staging dataset record in a directory."""
    input_root = _as_path(input_dir)
    if not input_root.exists() or not input_root.is_dir():
        raise ValueError(f"input_dir does not exist: {input_root}")
    results: list[dict[str, Any]] = []
    for path in sorted(input_root.glob(glob)):
        if path.name.startswith("_"):
            continue
        results.append(validate_staging_dataset(path, validation_policy=validation_policy))
    return {
        "status": "ok",
        "input_dir": str(input_root),
        "processed": len(results),
        "ok": sum(1 for item in results if item["ok"]),
        "failed": sum(1 for item in results if not item["ok"]),
        "results": results,
    }


def promote_staging_dataset(
    source: dict[str, Any] | PathLike,
    *,
    curated_root: PathLike,
    record_id: str | None = None,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Promote a validated staging dataset record into the curated record store.

    The curated id is taken from the record's own identifier (or ``record_id`` if
    given). Writes ``curated_root/<record-id>/record.json``. Pass ``dry_run=True``
    to validate + resolve the id without writing files.
    """
    payload, source_path = _staging_dataset_input(source)
    identity = _staging_dataset_identity(payload, source_path)
    if record_id is not None:
        resolved_record_id = _dataset_record_id(record_id)
    else:
        resolved_record_id = identity["record_id"]
        if not isinstance(resolved_record_id, str) or not resolved_record_id:
            raise ValueError(
                "staging dataset does not have a safe automatic record id. "
                f"Provide --record-id explicitly; suggested pattern: {identity['record_id_hint']}."
            )

    report = _validate_record_report(payload, policy=validation_policy)
    if not report.ok:
        raise ValueError(f"staging dataset validation failed: {'; '.join(report.render_errors())}")

    curated_root_path = _as_path(curated_root)
    target_path = curated_root_path / resolved_record_id / "record.json"
    if not dry_run:
        _write_json(target_path, payload)
    return {
        "status": "ok",
        "record_id": resolved_record_id,
        "record_id_basis": identity["record_id_basis"] if record_id is None else "manual",
        "source_path": str(source_path) if source_path is not None else None,
        "target_path": str(target_path),
        "record": payload,
        "dry_run": dry_run,
    }


def promote_staging_datasets(
    *,
    input_dir: PathLike,
    curated_root: PathLike,
    glob: str = "*.json",
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Promote every staging dataset record in a directory."""
    input_root = _as_path(input_dir)
    if not input_root.exists() or not input_root.is_dir():
        raise ValueError(f"input_dir does not exist: {input_root}")
    promoted: list[dict[str, Any]] = []
    for path in sorted(input_root.glob(glob)):
        if path.name.startswith("_"):
            continue
        promoted.append(
            promote_staging_dataset(
                path,
                curated_root=curated_root,
                validation_policy=validation_policy,
                dry_run=dry_run,
            )
        )
    return {
        "status": "ok",
        "input_dir": str(input_root),
        "curated_root": str(_as_path(curated_root)),
        "processed": len(promoted),
        "dry_run": dry_run,
        "results": promoted,
    }


def _curated_cell_spec_source(
    source: dict[str, Any] | PathLike,
) -> tuple[dict[str, Any], Path | None, str | None]:
    source_path: Path | None = None
    if isinstance(source, (str, Path)):
        source_path = _as_path(source)
        payload = _load_json(source_path)
    else:
        payload = dict(source)

    product = payload.get("cell_spec")
    if not isinstance(product, Mapping):
        raise ValueError("curated cell-spec source must be a canonical record with a top-level product object.")

    inferred_local_id: str | None = None
    if source_path is not None:
        if source_path.name == "record.json" and source_path.parent.name and not source_path.parent.name.startswith("_"):
            inferred_local_id = source_path.parent.name
        elif source_path.stem and not source_path.stem.startswith("_"):
            inferred_local_id = source_path.stem
    return payload, source_path, inferred_local_id


def _curated_cell_spec_title(record: Mapping[str, Any]) -> str:
    product = record.get("cell_spec")
    if not isinstance(product, Mapping):
        raise ValueError("cell-spec record is missing product.")
    manufacturer_obj = product.get("manufacturer")
    manufacturer = manufacturer_obj.get("name") if isinstance(manufacturer_obj, Mapping) else manufacturer_obj
    return str(product.get("name") or f"{manufacturer or 'Battery'} {product.get('model') or 'Cell'}").strip()


def build_submission_envelope(
    *,
    resource_type: str,
    records: Mapping[str, Mapping[str, Any]],
    rdf_type: str | None,
    workspace_id: str,
    publisher_id: str,
    source_version: str,
    source_local_id: str,
    title: str,
    publication_mode: str,
    source_system: str,
    workflow_name: str,
    related_resources: Sequence[dict[str, Any]] | None = None,
    distributions: Sequence[dict[str, Any]] | None = None,
    preview: dict[str, Any] | None = None,
    workspace: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The ONE submission-envelope builder (beta-hardening 4.3).

    Every path that talks to the registry — the authoring workspace, the
    curated editorial pipeline, and anything future — builds its envelope
    here, so the shape can never fork again. Callers differ only in the
    fields that SHOULD differ: publication mode, provenance system/workflow,
    the embedded records, and the validation verdict.
    """
    generated_at = _now_iso()
    semantic_payload: dict[str, Any] = {}
    if rdf_type:
        semantic_payload["@type"] = rdf_type
    semantic_payload["battinfo_records"] = {k: dict(v) for k, v in records.items()}
    if preview:
        semantic_payload["preview"] = preview
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "BattinfoSubmission",
        "submission_mode": "resource",
        "generated_at": generated_at,
        "workspace_id": workspace_id,
        "publisher_id": publisher_id,
        "source_version": source_version,
        "title": title,
        "publication_intent": {"mode": publication_mode},
        "provenance": {
            "source_system": source_system,
            "workflow_name": workflow_name,
            "generated_at": generated_at,
        },
        "release": {"version": source_version},
        "workspace": workspace,
        "resource": {
            "resource_type": resource_type,
            "source_local_id": source_local_id,
            "title": title,
            "semantic_payload": semantic_payload,
            "related_resources": list(related_resources or []),
            "distributions": list(distributions or []),
        },
        "artifacts": [],
        "validation": validation or {"ok": True, "errors": [], "policy": "default"},
    }


def _curated_cell_spec_submission_resource(
    *,
    record: Mapping[str, Any],
    source_local_id: str,
    title: str,
) -> dict[str, Any]:
    return {
        "resource_type": "cell_spec",
        "source_local_id": source_local_id,
        "title": title,
        "semantic_payload": {
            "@type": "CellSpec",
            "battinfo_records": {"cell_spec": dict(record)},
        },
        "related_resources": [],
        "distributions": [],
    }


def build_curated_cell_spec_submission(
    source: dict[str, Any] | PathLike,
    *,
    workspace_id: str,
    publisher_id: str,
    source_version: str,
    source_local_id: str | None = None,
    title: str | None = None,
    publication_mode: str = "canonical-publication",
    source_system: str = "battinfo-records",
    workflow_name: str = "curated-cell-spec-publication",
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    record, source_path, inferred_local_id = _curated_cell_spec_source(source)
    resolved_source_local_id = source_local_id or inferred_local_id
    if not isinstance(resolved_source_local_id, str) or not resolved_source_local_id.strip():
        raise ValueError("Could not infer source_local_id for curated cell-spec source; provide source_local_id explicitly.")

    validation = validate_record(record, policy=validation_policy)
    if not validation.ok:
        raise ValueError(f"curated cell-spec validation failed: {'; '.join(validation.errors)}")

    resolved_title = title or _curated_cell_spec_title(record)
    workspace: dict[str, Any] | None = None
    if source_path is not None:
        workspace = {
            "editorial": {
                "record_path": str(source_path),
                "record_id": resolved_source_local_id,
            }
        }

    return build_submission_envelope(
        resource_type="cell_spec",
        records={"cell_spec": record},
        rdf_type="CellSpec",
        workspace_id=workspace_id,
        publisher_id=publisher_id,
        source_version=source_version,
        source_local_id=resolved_source_local_id,
        title=resolved_title,
        publication_mode=publication_mode,
        source_system=source_system,
        workflow_name=workflow_name,
        workspace=workspace,
        validation={
            "ok": validation.ok,
            "errors": list(validation.errors),
            "policy": validation.policy,
        },
    )
