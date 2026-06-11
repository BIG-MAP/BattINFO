from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from battinfo.api import submit_publication_package
from battinfo.validate.schema import build_validator, schema_for_rel_path
from battinfo._workspace import Workspace

PathLike = str | Path

DEFAULT_INGEST_MANIFEST = "battinfo.ingest.json"
DEFAULT_PHOTO_GLOBS = ("image/photo/*.jpg", "image/photo/*.jpeg", "image/photo/*.png")
DEFAULT_TIMESERIES_GLOBS = ("timeseries/raw/*.csv",)
DEFAULT_TEST_KIND_FROM_FILENAME = {
    "rate": "rate_capability",
    "ici": "ici",
    "capacity": "capacity_check",
}
DEFAULT_TEST_LABELS = {
    "rate_capability": "Rate capability",
    "ici": "ICI",
    "capacity_check": "Capacity check",
    "other": "Other",
}
# Short labels used in dataset record titles (cell-type + label + temp + date format)
DATASET_TITLE_LABELS = {
    "rate_capability": "Rate",
    "ici": "ICI",
    "capacity_check": "Capacity",
    "other": "Other",
}
DATE_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})")
TEMP_RE = re.compile(r"(\d+(?:[.,]\d+)?deg[CF])", re.IGNORECASE)


def _as_path(path: PathLike) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _slugify(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return value or "ingest"


def _mtime_to_unix(path: Path) -> int:
    return int(path.stat().st_mtime)


def _date_to_unix(date_text: str) -> int:
    return int(datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _drop_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


@lru_cache(maxsize=1)
def _ingest_manifest_validator():
    return build_validator(schema_for_rel_path("ingest-manifest.schema.json"))


def _validate_manifest_doc(doc: dict[str, Any], *, source_path: Path) -> dict[str, Any]:
    errors = sorted(_ingest_manifest_validator().iter_errors(doc), key=lambda err: list(err.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path)
        location = f" at {path}" if path else ""
        raise ValueError(f"invalid ingest manifest {source_path}{location}: {first.message}")
    return doc


def _load_manifest(ingest_root: Path, manifest_path: Path | None) -> dict[str, Any]:
    candidates: list[Path] = []
    if manifest_path is not None:
        candidates.append(manifest_path)
    candidates.append(ingest_root / DEFAULT_INGEST_MANIFEST)
    for candidate in candidates:
        if candidate.exists():
            return _validate_manifest_doc(json.loads(candidate.read_text(encoding="utf-8")), source_path=candidate)
    return {}


def _default_manifest_payload(
    *,
    resource_type: str | None = None,
    type_record: PathLike | None = None,
    resource_iri: str | None = None,
    resource_name: str | None = None,
    workspace_id: str | None = None,
    publisher_id: str | None = None,
    source_version: str | None = None,
    license: str | None = None,
) -> dict[str, Any]:
    return _drop_none({
        "resource_type": resource_type or "cell-instance",
        "type_record": str(type_record) if type_record is not None else None,
        "resource_iri": resource_iri,
        "resource_name": resource_name,
        "workspace_id": workspace_id,
        "publisher_id": publisher_id,
        "source_version": source_version,
        "license": license,
        "rules": {
            "photo_glob": list(DEFAULT_PHOTO_GLOBS),
            "timeseries_glob": list(DEFAULT_TIMESERIES_GLOBS),
            "test_kind_from_filename": dict(DEFAULT_TEST_KIND_FROM_FILENAME),
        },
    })


def _pick_first(*values: Any) -> Any:
    for value in values:
        if isinstance(value, str):
            if value.strip():
                return value
        elif value is not None:
            return value
    return None


def _resolve_globs(manifest: dict[str, Any], key: str, default: tuple[str, ...]) -> list[str]:
    rules = manifest.get("rules")
    if isinstance(rules, dict):
        candidate = rules.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return [candidate.strip()]
        if isinstance(candidate, list):
            values = [str(item).strip() for item in candidate if str(item).strip()]
            if values:
                return values
    return list(default)


def _resolve_kind_map(manifest: dict[str, Any]) -> dict[str, str]:
    mapping = dict(DEFAULT_TEST_KIND_FROM_FILENAME)
    rules = manifest.get("rules")
    if isinstance(rules, dict) and isinstance(rules.get("test_kind_from_filename"), dict):
        for key, value in rules["test_kind_from_filename"].items():
            if isinstance(key, str) and isinstance(value, str) and key.strip() and value.strip():
                mapping[key.strip().lower()] = value.strip()
    return mapping


def _scan_paths(ingest_root: Path, globs: list[str]) -> list[Path]:
    discovered: list[Path] = []
    seen: set[Path] = set()
    for pattern in globs:
        for path in sorted(ingest_root.glob(pattern)):
            if path.is_file():
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    discovered.append(path)
    return discovered


def _infer_csv_kind(path: Path, kind_map: dict[str, str]) -> str:
    name = path.name.lower()
    for token, kind in kind_map.items():
        if token in name:
            return kind
    return "other"


def _infer_date_text(path: Path) -> str | None:
    match = DATE_RE.search(path.name)
    return match.group("date") if match else None


def _infer_temp_text(path: Path) -> str | None:
    match = TEMP_RE.search(path.name)
    return match.group(1) if match else None


def _dataset_title(resource_name: str | None, kind: str, path: Path, date_text: str | None) -> str:
    """Build a human-readable dataset title: 'Cell ICI 25degC dataset 2026-03-05'."""
    short_label = DATASET_TITLE_LABELS.get(kind, DATASET_TITLE_LABELS["other"])
    temp = _infer_temp_text(path)
    suffix = date_text or path.stem
    parts = [p for p in [resource_name, short_label, temp, "dataset", suffix] if p]
    return " ".join(parts)


def _label_for_kind(kind: str) -> str:
    return DEFAULT_TEST_LABELS.get(kind, kind.replace("_", " ").title())


def _distribution_public_url(package_path: str | None, artifact_base_url: str | None) -> str | None:
    if artifact_base_url is None or package_path is None:
        return None
    normalized = package_path.replace("\\", "/").lstrip("/")
    if normalized.startswith("artifacts/"):
        normalized = normalized[len("artifacts/") :]
    return artifact_base_url.rstrip("/") + "/" + normalized


def _normalize_resource_type(resource_type: str | None) -> str:
    resolved = (resource_type or "cell-instance").strip().lower()
    if resolved != "cell-instance":
        raise NotImplementedError(
            f"resource_type '{resolved}' is not implemented yet. Supported today: cell-instance."
        )
    return resolved


def write_ingest_manifest(
    ingest_root: PathLike,
    *,
    manifest_path: PathLike | None = None,
    resource_type: str = "cell-instance",
    type_record: PathLike | None = None,
    resource_iri: str | None = None,
    resource_name: str | None = None,
    workspace_id: str | None = None,
    publisher_id: str | None = None,
    source_version: str | None = None,
    license: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    root = _as_path(ingest_root)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"ingest_root does not exist: {root}")

    target = _as_path(manifest_path) if manifest_path is not None else (root / DEFAULT_INGEST_MANIFEST)
    if target.exists() and not overwrite:
        raise FileExistsError(f"manifest already exists: {target}")

    payload = _default_manifest_payload(
        resource_type=resource_type,
        type_record=type_record,
        resource_iri=resource_iri,
        resource_name=resource_name or root.name,
        workspace_id=workspace_id or _slugify(root.name),
        publisher_id=publisher_id,
        source_version=source_version,
        license=license,
    )
    _write_json(target, payload)
    return {
        "status": "ok",
        "manifest_path": str(target),
        "ingest_root": str(root),
        "manifest": payload,
    }


def inspect_ingest_root(
    ingest_root: PathLike,
    *,
    manifest_path: PathLike | None = None,
    resource_type: str | None = None,
    type_record: PathLike | None = None,
    resource_iri: str | None = None,
    resource_name: str | None = None,
    license: str | None = None,
    workspace_id: str | None = None,
    publisher_id: str | None = None,
    source_version: str | None = None,
) -> dict[str, Any]:
    root = _as_path(ingest_root)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"ingest_root does not exist: {root}")

    manifest = _load_manifest(root, _as_path(manifest_path) if manifest_path is not None else None)
    if manifest_path is not None and not _as_path(manifest_path).exists():
        raise FileNotFoundError(f"manifest does not exist: {manifest_path}")

    resolved_resource_type = _pick_first(resource_type, manifest.get("resource_type"), "cell-instance")
    resolved_type_record = _pick_first(type_record, manifest.get("type_record"))
    resolved_resource_iri = _pick_first(resource_iri, manifest.get("resource_iri"))
    resolved_resource_name = _pick_first(resource_name, manifest.get("resource_name"), root.name)
    resolved_license = _pick_first(license, manifest.get("license"))
    resolved_workspace_id = _pick_first(workspace_id, manifest.get("workspace_id"), _slugify(root.name))
    resolved_publisher_id = _pick_first(publisher_id, manifest.get("publisher_id"))
    resolved_source_version = _pick_first(source_version, manifest.get("source_version"))

    photo_globs = _resolve_globs(manifest, "photo_glob", DEFAULT_PHOTO_GLOBS)
    csv_globs = _resolve_globs(manifest, "timeseries_glob", DEFAULT_TIMESERIES_GLOBS)
    kind_map = _resolve_kind_map(manifest)

    photo_files = _scan_paths(root, photo_globs)
    csv_files = _scan_paths(root, csv_globs)

    tests: list[dict[str, Any]] = []
    datasets: list[dict[str, Any]] = []

    for index, photo_path in enumerate(photo_files, start=1):
        dataset_title = "Instance photo" if len(photo_files) == 1 else f"Instance photo {index}"
        tests.append(
            {
                "kind": "other",
                "name": "Instance photography" if len(photo_files) == 1 else f"Instance photography {index}",
                "source_file": photo_path.name,
                "path": str(photo_path),
            }
        )
        datasets.append(
            {
                "role": "photo",
                "title": dataset_title,
                "path": str(photo_path),
                "format": photo_path.suffix.lower(),
                "hero_candidate": index == 1,
            }
        )

    for csv_path in csv_files:
        kind = _infer_csv_kind(csv_path, kind_map)
        label = _label_for_kind(kind)
        date_text = _infer_date_text(csv_path)
        suffix = date_text or csv_path.stem
        tests.append(
            {
                "kind": kind,
                "name": f"{label} {suffix}",
                "source_file": csv_path.name,
                "path": str(csv_path),
            }
        )
        datasets.append(
            {
                "role": "timeseries",
                "kind": kind,
                "title": _dataset_title(resolved_resource_name, kind, csv_path, date_text),
                "path": str(csv_path),
                "format": "text/csv",
                "hero_candidate": False,
            }
        )

    return {
        "status": "ok",
        "ingest_root": str(root),
        "manifest_path": str((_as_path(manifest_path) if manifest_path is not None else (root / DEFAULT_INGEST_MANIFEST)))
        if (
            manifest_path is not None
            or (root / DEFAULT_INGEST_MANIFEST).exists()
        )
        else None,
        "resource_type": str(resolved_resource_type),
        "type_record": str(resolved_type_record) if resolved_type_record is not None else None,
        "resource_iri": resolved_resource_iri,
        "resource_name": resolved_resource_name,
        "workspace_id": resolved_workspace_id,
        "publisher_id": resolved_publisher_id,
        "source_version": resolved_source_version,
        "license": resolved_license,
        "photo_count": len(photo_files),
        "csv_count": len(csv_files),
        "photo_files": [str(path) for path in photo_files],
        "csv_files": [str(path) for path in csv_files],
        "tests": tests,
        "datasets": datasets,
        "hero_image_path": str(photo_files[0]) if photo_files else None,
    }


def _prepare_live_submission_payload(
    submission_payload: dict[str, Any],
    *,
    artifact_base_url: str | None,
    hero_alt: str,
    hero_caption: str,
) -> dict[str, Any]:
    resources = submission_payload.get("resources")
    if not isinstance(resources, list):
        return submission_payload

    cell_resource: dict[str, Any] | None = None
    photo_dataset_resource: dict[str, Any] | None = None
    photo_public_url: str | None = None
    all_dataset_resources: list[dict[str, Any]] = []

    for resource in resources:
        if not isinstance(resource, dict):
            continue
        if resource.get("resource_type") == "cell":
            cell_resource = resource
        if resource.get("resource_type") == "dataset":
            all_dataset_resources.append(resource)

        distributions = resource.get("distributions")
        if not isinstance(distributions, list):
            continue
        for distribution in distributions:
            if not isinstance(distribution, dict):
                continue
            public_url = _distribution_public_url(distribution.get("package_path"), artifact_base_url)
            if public_url is not None:
                distribution["access_url"] = public_url
                if resource.get("resource_type") == "dataset":
                    semantic_payload = resource.get("semantic_payload")
                    if isinstance(semantic_payload, dict):
                        battinfo_records = semantic_payload.get("battinfo_records")
                        if isinstance(battinfo_records, dict):
                            dataset_record = battinfo_records.get("dataset")
                            if isinstance(dataset_record, dict):
                                dataset_payload = dataset_record.get("dataset")
                                if isinstance(dataset_payload, dict):
                                    dataset_payload["access_url"] = public_url
                                    dataset_distributions = dataset_payload.get("distributions")
                                    if isinstance(dataset_distributions, list) and dataset_distributions:
                                        first_distribution = dataset_distributions[0]
                                        if isinstance(first_distribution, dict):
                                            first_distribution["content_url"] = public_url
                                provenance = dataset_record.get("provenance")
                                if isinstance(provenance, dict):
                                    provenance["source_url"] = public_url
            effective_url = public_url or distribution.get("access_url")
            if (
                resource.get("resource_type") == "dataset"
                and distribution.get("media_type") == "image/jpeg"
                and isinstance(effective_url, str)
            ):
                photo_dataset_resource = resource
                photo_public_url = effective_url

    if cell_resource is not None and photo_dataset_resource is not None and photo_public_url is not None:
        semantic_payload = cell_resource.get("semantic_payload")
        if isinstance(semantic_payload, dict):
            preview = semantic_payload.get("preview")
            if not isinstance(preview, dict):
                preview = {}
                semantic_payload["preview"] = preview
            preview["image"] = {
                "src": photo_public_url,
                "alt": hero_alt,
                "caption": hero_caption,
            }

    if cell_resource is not None and all_dataset_resources:
        related_resources = cell_resource.get("related_resources")
        if isinstance(related_resources, list):
            existing_ids = {
                item.get("source_local_id")
                for item in related_resources
                if isinstance(item, dict)
            }
            for dataset_resource in all_dataset_resources:
                source_local_id = dataset_resource.get("source_local_id")
                if isinstance(source_local_id, str) and source_local_id not in existing_ids:
                    related_resources.append(
                        {
                            "relationship": "hasDataset",
                            "resource_type": "dataset",
                            "source_local_id": source_local_id,
                            "title": dataset_resource.get("title"),
                        }
                    )
                    existing_ids.add(source_local_id)

    return submission_payload


def build_ingest_workspace(
    ingest_root: PathLike,
    *,
    resource_type: str = "cell-instance",
    type_record: PathLike | None = None,
    manifest_path: PathLike | None = None,
    resource_iri: str | None = None,
    resource_name: str | None = None,
    workspace_root: PathLike | None = None,
    workspace_id: str | None = None,
    tenant: str | None = None,
    publisher_id: str | None = None,
    source_version: str | None = None,
    license: str | None = None,
    artifact_base_url: str | None = None,
    clean: bool = False,
    validation_policy: str = "strict",
    bundle: bool = True,
) -> dict[str, Any]:
    inspection = inspect_ingest_root(
        ingest_root,
        manifest_path=manifest_path,
        resource_type=resource_type,
        type_record=type_record,
        resource_iri=resource_iri,
        resource_name=resource_name,
        license=license,
        workspace_id=workspace_id,
        publisher_id=publisher_id,
        source_version=source_version,
    )
    resolved_resource_type = _normalize_resource_type(str(inspection["resource_type"]))
    if inspection["type_record"] is None:
        raise ValueError("type_record is required. Provide --type-record or define it in battinfo.ingest.json.")

    ingest_path = _as_path(ingest_root)
    resolved_workspace_root = (
        _as_path(workspace_root)
        if workspace_root is not None
        else Path(".battinfo") / "ingest" / _slugify(ingest_path.name) / "workspace"
    )
    resolved_source_version = str(inspection["source_version"] or datetime.now(timezone.utc).date().isoformat())
    resolved_publisher_id = inspection["publisher_id"]
    resolved_workspace_id = inspection["workspace_id"]

    workspace = Workspace(
        root=resolved_workspace_root,
        name=str(resolved_workspace_id),
        title=f"{inspection['resource_name']} ingest workspace",
        description=f"Ingest workspace for {inspection['resource_name']}.",
        tenant=tenant,
        publisher=resolved_publisher_id,
        version=resolved_source_version,
        clean=clean,
    )

    if resolved_resource_type != "cell-instance":
        raise NotImplementedError(
            f"resource_type '{resolved_resource_type}' is not implemented yet. Supported today: cell-instance."
        )

    cell_type_obj = workspace.load_cell_type(str(inspection["type_record"]))
    cell = workspace.cell(
        cell_type_obj,
        serial_number=str(inspection["resource_name"]),
        source_type="lab",
        source_url=ingest_path.resolve().as_uri(),
        comment=[f"Ingested files sourced from {ingest_path}."],
    )
    cell.name = str(inspection["resource_name"])
    if inspection["resource_iri"] is not None:
        cell.id = str(inspection["resource_iri"])

    created_photo_tests = 0
    created_csv_tests = 0

    for photo_entry in [item for item in inspection["datasets"] if item["role"] == "photo"]:
        photo_path = Path(str(photo_entry["path"]))
        created_photo_tests += 1
        test_name = "Instance photography" if created_photo_tests == 1 else f"Instance photography {created_photo_tests}"
        photo_test = workspace.test(
            cell,
            kind="other",
            name=test_name,
            protocol="Instance photography",
            instrument="Camera",
            status="completed",
            started_at=_mtime_to_unix(photo_path),
            source_type="measurement",
            source_url=photo_path.resolve().as_uri(),
            source_file=photo_path.name,
        )
        workspace.dataset(
            cell,
            title=str(photo_entry["title"]),
            description="Standalone photo evidence for the ingested physical instance.",
            test=photo_test,
            path=photo_path,
            format="image/jpeg" if photo_path.suffix.lower() in {".jpg", ".jpeg"} else None,
            license=str(inspection["license"]) if inspection["license"] is not None else None,
            created_at=_mtime_to_unix(photo_path),
            source_type="measurement",
            source_url=photo_path.resolve().as_uri(),
            comment=["Standalone instance photo dataset."],
        )

    for test_entry, dataset_entry in zip(
        [item for item in inspection["tests"] if item["kind"] != "other"],
        [item for item in inspection["datasets"] if item["role"] == "timeseries"],
        strict=False,
    ):
        csv_path = Path(str(dataset_entry["path"]))
        date_text = _infer_date_text(csv_path)
        created_csv_tests += 1
        started_at = _date_to_unix(date_text) if date_text is not None else _mtime_to_unix(csv_path)
        test = workspace.test(
            cell,
            kind=str(test_entry["kind"]),
            name=str(test_entry["name"]),
            protocol=f"{_label_for_kind(str(test_entry['kind']))} at 25 degC",
            instrument="Cycler",
            status="completed",
            started_at=started_at,
            source_type="measurement",
            source_url=csv_path.resolve().as_uri(),
            source_file=csv_path.name,
        )
        workspace.dataset(
            cell,
            title=str(dataset_entry["title"]),
            description=f"Raw {_label_for_kind(str(test_entry['kind'])).lower()} data for {inspection['resource_name']}.",
            test=test,
            path=csv_path,
            format="text/csv",
            license=str(inspection["license"]) if inspection["license"] is not None else None,
            created_at=_mtime_to_unix(csv_path),
            source_type="measurement",
            source_url=csv_path.resolve().as_uri(),
            comment=[f"Derived from ingest folder {ingest_path.name}."],
        )

    save_report = workspace.save_workspace()
    check_report = workspace.check_workspace(policy=validation_policy)
    if not check_report["ok"]:
        raise RuntimeError(json.dumps(check_report, indent=2, ensure_ascii=False))

    payload: dict[str, Any] = {
        "status": "ok",
        "inspection": inspection,
        "resource_type": resolved_resource_type,
        "workspace_root": str(resolved_workspace_root),
        "save_report": save_report,
        "validation": check_report,
        "counts": {
            "cell_types": len(workspace.cell_types),
            "cells": len(workspace.cells),
            "tests": len(workspace.tests),
            "datasets": len(workspace.datasets),
            "photo_tests": created_photo_tests,
            "timeseries_tests": created_csv_tests,
        },
    }

    if bundle:
        if resolved_workspace_id is None or not str(resolved_workspace_id).strip():
            raise ValueError("workspace_id is required to bundle an ingest workspace.")
        if resolved_publisher_id is None or not str(resolved_publisher_id).strip():
            raise ValueError("publisher_id is required to bundle an ingest workspace.")
        bundle_report = workspace.bundle_workspace(policy=validation_policy)
        submission_package_path = Path(bundle_report["submission_package_path"])
        submission_payload = json.loads(submission_package_path.read_text(encoding="utf-8"))
        submission_payload = _prepare_live_submission_payload(
            submission_payload,
            artifact_base_url=artifact_base_url,
            hero_alt=f"{inspection['resource_name']} instance photo",
            hero_caption="Standalone instance photo dataset used as the Battery Genome cell hero image.",
        )
        _write_json(submission_package_path, submission_payload)
        payload["bundle_report"] = bundle_report
        payload["submission_package_path"] = str(submission_package_path)
        payload["submission_package"] = submission_payload

    return payload


def _upload_workspace_artifacts(
    submission_package: dict[str, Any],
    ingest_root: Path,
    uploader: Callable[[str, Path], str],
    processor: Callable[[Path, Path], Any] | None = None,
) -> None:
    """Upload distribution files and write access_url on each distribution in-place.

    For timeseries distributions, if *processor* is provided it is called as
    ``processor(raw_csv_path, work_dir) -> ProcessedTimeseries`` before uploading.
    The BDF CSV, static PNG, and interactive HTML outputs are added as additional
    distributions on the same dataset resource and uploaded alongside the raw file.
    The storage layout is:

        timeseries/raw/<short_id>/<filename>        ← raw CSV (as before)
        timeseries/bdf/<short_id>/<stem>.bdf.csv    ← BDF-normalised CSV
        timeseries/plot/<short_id>/<stem>.png        ← static voltage/time plot
        timeseries/plot/<short_id>/<stem>.html       ← interactive HTML (Plotly)

    Args:
        submission_package: The submission package dict (mutated in-place).
        ingest_root: Root directory to search for source files by filename.
        uploader: Callable ``(key, source_path) -> access_url``.
        processor: Optional callable ``(raw_csv_path, work_dir) -> ProcessedTimeseries``.
            Import :func:`battinfo.processing.process_timeseries_csv` to use the
            built-in processor, or supply your own.
    """
    with tempfile.TemporaryDirectory(prefix="battinfo-processing-") as _tmpdir:
        work_dir = Path(_tmpdir)

        for resource in submission_package.get("resources", []):
            if not isinstance(resource, dict):
                continue
            distributions = resource.get("distributions", [])
            if not isinstance(distributions, list):
                continue

            extra_distributions: list[dict[str, Any]] = []

            for distribution in distributions:
                if not isinstance(distribution, dict):
                    continue
                package_path = distribution.get("package_path")
                if not package_path:
                    continue
                key = package_path.replace("\\", "/").lstrip("/")
                if key.startswith("artifacts/"):
                    key = key[len("artifacts/"):]
                filename = Path(key).name
                matches = list(ingest_root.rglob(filename))
                if not matches:
                    continue
                raw_path = matches[0]
                distribution["access_url"] = uploader(key, raw_path)

                # Process timeseries distributions when a processor is supplied.
                # Keys follow the layout dataset/<short_id>/<filename> (or
                # timeseries/raw/<short_id>/<filename> if the ingest builder
                # uses that scheme).  Detect CSV files regardless of prefix.
                is_timeseries = (
                    processor is not None
                    and resource.get("resource_type") == "dataset"
                    and filename.lower().endswith(".csv")
                )
                if not is_timeseries:
                    continue

                # Derive the short_id from the storage key.
                # Handles both "dataset/<id>/file" and "timeseries/raw/<id>/file".
                parts = key.split("/")
                short_id = parts[-2] if len(parts) >= 3 else Path(key).stem

                try:
                    processed = processor(raw_path, work_dir / short_id)
                except Exception:
                    continue

                # BDF CSV → timeseries/bdf/<short_id>/<stem>.bdf.csv
                if processed.bdf_path is not None and processed.bdf_path.exists():
                    bdf_key = f"timeseries/bdf/{short_id}/{processed.bdf_path.name}"
                    bdf_url = uploader(bdf_key, processed.bdf_path)
                    extra_distributions.append({
                        "title": f"{distribution.get('title', filename)} (BDF)",
                        "access_url": bdf_url,
                        "media_type": "text/csv",
                        "role": "bdf",
                    })

                # Static PNG → timeseries/plot/<short_id>/<stem>.png
                if processed.plot_png_path is not None and processed.plot_png_path.exists():
                    png_key = f"timeseries/plot/{short_id}/{processed.plot_png_path.name}"
                    png_url = uploader(png_key, processed.plot_png_path)
                    extra_distributions.append({
                        "title": f"{distribution.get('title', filename)} (plot)",
                        "access_url": png_url,
                        "media_type": "image/png",
                        "role": "plot_static",
                    })
                    # Set as preview image on the dataset's semantic_payload
                    semantic_payload = resource.get("semantic_payload")
                    if isinstance(semantic_payload, dict):
                        semantic_payload.setdefault("preview", {})["image"] = {
                            "src": png_url,
                            "alt": distribution.get("title", filename),
                        }

                    # Propagate thumbnail to every other resource in the bundle
                    # that references this dataset via related_resources, so it
                    # shows up on cell/test pages as the dataset's preview image.
                    dataset_local_id = resource.get("source_local_id")
                    if dataset_local_id:
                        for other_resource in submission_package.get("resources", []):
                            if other_resource is resource:
                                continue
                            for rel in other_resource.get("related_resources", []):
                                if rel.get("source_local_id") == dataset_local_id:
                                    rel.setdefault("preview", {})["thumbnail"] = {
                                        "src": png_url,
                                        "alt": distribution.get("title", filename),
                                    }

                # Plotly JSON → timeseries/plot/<short_id>/<stem>.plot.json
                if processed.plot_json_path is not None and processed.plot_json_path.exists():
                    json_key = f"timeseries/plot/{short_id}/{processed.plot_json_path.name}"
                    json_url = uploader(json_key, processed.plot_json_path)
                    extra_distributions.append({
                        "title": f"{distribution.get('title', filename)} (interactive)",
                        "access_url": json_url,
                        "media_type": "application/json",
                        "role": "plot_data",
                    })

            distributions.extend(extra_distributions)


def publish_ingest_workspace(
    ingest_root: PathLike,
    *,
    resource_type: str = "cell-instance",
    type_record: PathLike | None = None,
    manifest_path: PathLike | None = None,
    resource_iri: str | None = None,
    resource_name: str | None = None,
    workspace_root: PathLike | None = None,
    workspace_id: str | None = None,
    tenant: str | None = None,
    publisher_id: str | None = None,
    source_version: str | None = None,
    license: str | None = None,
    artifact_base_url: str | None = None,
    clean: bool = False,
    validation_policy: str = "strict",
    artifact_uploader: Callable[[str, Path], str] | None = None,
    artifact_processor: Callable[[Path, Path], Any] | None = None,
    registry_base_url: str | None = None,
    api_key: str | None = None,
    api_key_header: str = "X-Battinfo-API-Key",
    platform_base_url: str | None = None,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    """Build an ingest workspace and publish it to the registry.

    If ``artifact_uploader`` is provided it is called for every distribution
    that has a ``package_path`` before the submission is sent to the registry.
    The callable receives ``(key: str, source_path: Path)`` and must return the
    public access URL for the uploaded file.

    If ``artifact_processor`` is provided it is called for each timeseries
    CSV distribution as ``processor(raw_csv_path, work_dir) -> ProcessedTimeseries``
    before upload.  The built-in processor is
    :func:`battinfo.processing.process_timeseries_csv` (requires
    ``battinfo[processing]``).  The processor generates a BDF-normalised CSV,
    a static PNG plot, and an interactive HTML plot; all three are uploaded to
    the object store alongside the raw file.
    """
    if registry_base_url is None or not registry_base_url.strip():
        raise ValueError("registry_base_url is required for ingest publication.")
    if api_key is None or not api_key.strip():
        raise ValueError("api_key is required for ingest publication.")

    build = build_ingest_workspace(
        ingest_root,
        resource_type=resource_type,
        type_record=type_record,
        manifest_path=manifest_path,
        resource_iri=resource_iri,
        resource_name=resource_name,
        workspace_root=workspace_root,
        workspace_id=workspace_id,
        tenant=tenant,
        publisher_id=publisher_id,
        source_version=source_version,
        license=license,
        artifact_base_url=artifact_base_url,
        clean=clean,
        validation_policy=validation_policy,
        bundle=True,
    )
    submission_payload = build["submission_package"]

    if artifact_uploader is not None:
        _upload_workspace_artifacts(
            submission_payload,
            _as_path(ingest_root),
            artifact_uploader,
            processor=artifact_processor,
        )

    submit_result = submit_publication_package(
        submission_payload,
        registry_base_url=registry_base_url,
        api_key=api_key,
        api_key_header=api_key_header,
        timeout_sec=timeout_sec,
    )
    response_payload = submit_result.get("response") or {}
    canonical_id_map = response_payload.get("canonical_id_map") if isinstance(response_payload, dict) else {}
    resources = submission_payload.get("resources", [])
    cell_resource = next((item for item in resources if isinstance(item, dict) and item.get("resource_type") == "cell"), None)
    dataset_resources = [item for item in resources if isinstance(item, dict) and item.get("resource_type") == "dataset"]
    cell_source_local_id = cell_resource.get("source_local_id") if isinstance(cell_resource, dict) else None
    cell_canonical_id = canonical_id_map.get(cell_source_local_id) if isinstance(canonical_id_map, dict) else None

    dataset_canonical_ids = {
        str(item.get("source_local_id")): canonical_id_map.get(item.get("source_local_id"))
        for item in dataset_resources
        if isinstance(canonical_id_map, dict) and isinstance(item.get("source_local_id"), str)
    }

    page_url = None
    if isinstance(cell_canonical_id, str) and platform_base_url is not None:
        page_url = platform_base_url.rstrip("/") + f"/registry/cell/{cell_canonical_id}"

    registry_resource_url = None
    if isinstance(cell_canonical_id, str):
        registry_resource_url = registry_base_url.rstrip("/") + f"/resources/cell/{cell_canonical_id}"

    return {
        "status": "ok",
        "resource_type": build["resource_type"],
        "build": build,
        "submission": submit_result,
        "registry": {
            "resource_url": registry_resource_url,
            "page_model_url": f"{registry_resource_url}/page-model" if registry_resource_url is not None else None,
        },
        "platform": {
            "url": page_url,
        } if page_url is not None else None,
        "canonical_ids": {
            "cell": cell_canonical_id,
            "datasets": dataset_canonical_ids,
        },
    }


__all__ = [
    "DEFAULT_INGEST_MANIFEST",
    "build_ingest_workspace",
    "inspect_ingest_root",
    "publish_ingest_workspace",
    "write_ingest_manifest",
]
