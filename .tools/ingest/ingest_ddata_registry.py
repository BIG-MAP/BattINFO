from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import (
    CellInstanceInput,
    CellTypeInput,
    DatasetInput,
    register_cell_instance,
    register_cell_type,
    register_dataset,
)

DEFAULT_DATA_ROOT = ROOT / ".battinfo" / "ddata"
DEFAULT_SOURCE_ROOT = ROOT / ".battinfo" / "ingest" / "ddata-registry"
DEFAULT_REPORT_PATH = ROOT / ".battinfo" / "ingest" / "reports" / "ddata-ingest-report.json"
DEFAULT_BDF_JOBS_PATH = ROOT / ".battinfo" / "ingest" / "reports" / "ddata-bdf-jobs.json"

UID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
SAFE_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest battery metadata into canonical BattINFO registry records and BDF job manifests."
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        help="Root folder containing the source battery metadata hierarchy.",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=DEFAULT_SOURCE_ROOT,
        help="Target root for emitted canonical records (cell-types/cell-instances/datasets).",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="JSON report path for ingest summary and source-to-canonical mapping.",
    )
    parser.add_argument(
        "--bdf-jobs-out",
        type=Path,
        default=DEFAULT_BDF_JOBS_PATH,
        help="JSON path for generated BDF conversion jobs.",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="upsert",
        choices=["create_only", "upsert"],
        help="Registration mode for canonical record emission.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run discovery + planning without writing canonical registry files.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of battery.json files to process.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail with non-zero exit when malformed JSON inputs are detected.",
    )
    return parser.parse_args()


def _now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _safe_token(value: object, fallback: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    token = SAFE_TOKEN_RE.sub("-", text).strip("-")
    return token or fallback


def _stable_uid(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    bits = int.from_bytes(digest, "big")
    chars: list[str] = []
    for _ in range(16):
        chars.append(UID_ALPHABET[bits & 31])
        bits >>= 5
    token = "".join(chars)
    return f"{token[:4]}-{token[4:8]}-{token[8:12]}-{token[12:16]}"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_manufacturer(spec: Mapping[str, Any]) -> str:
    manufacturer = spec.get("manufacturer")
    if isinstance(manufacturer, Mapping):
        name = manufacturer.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(manufacturer, str) and manufacturer.strip():
        return manufacturer.strip()
    return "unknown"


def _parse_model(spec: Mapping[str, Any]) -> str:
    value = spec.get("model")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "unknown-model"


def _parse_form_factor(spec: Mapping[str, Any]) -> str:
    value = spec.get("form_factor")
    if isinstance(value, Mapping):
        shape = value.get("shape")
        if isinstance(shape, str) and shape.strip():
            return shape.strip().lower()
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return "unknown"


def _parse_chemistry(spec: Mapping[str, Any]) -> str:
    value = spec.get("chemistry")
    if isinstance(value, Mapping):
        short = value.get("short")
        if isinstance(short, str) and short.strip():
            return short.strip()
        full = value.get("full")
        if isinstance(full, str) and full.strip():
            return full.strip()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "unknown"


def _first_material(spec: Mapping[str, Any], key: str) -> str | None:
    value = spec.get(key)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _spec_item(value: float | int | None, unit: str) -> dict[str, Any] | None:
    if value is None:
        return None
    return {"value": float(value), "unit": unit}


def _build_cell_type_specs(spec: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    nominal_capacity = spec.get("nominal_capacity_Ah")
    if nominal_capacity is None:
        nominal_capacity = spec.get("rated_capacity_ah")
    nominal_voltage = spec.get("nominal_voltage_V")
    if nominal_voltage is None:
        nominal_voltage = spec.get("nominal_voltage_v")
    mass_g = spec.get("mass_g")
    volume_l = spec.get("volume_l")

    if isinstance(nominal_capacity, (int, float)):
        out["nominal_capacity"] = _spec_item(nominal_capacity, "Ah")
    if isinstance(nominal_voltage, (int, float)):
        out["nominal_voltage"] = _spec_item(nominal_voltage, "V")
    if isinstance(mass_g, (int, float)):
        out["mass"] = _spec_item(float(mass_g) / 1000.0, "kg")
    if isinstance(volume_l, (int, float)):
        out["volume"] = _spec_item(float(volume_l) / 1000.0, "m^3")

    form_factor = spec.get("form_factor")
    dims = spec.get("dimensions_mm")
    if isinstance(form_factor, Mapping):
        shape = str(form_factor.get("shape", "")).strip().lower()
    else:
        shape = str(form_factor or "").strip().lower()
    if isinstance(dims, Mapping):
        if shape == "cylindrical":
            if isinstance(dims.get("diameter"), (int, float)):
                out["diameter"] = _spec_item(float(dims["diameter"]) / 1000.0, "m")
            if isinstance(dims.get("height"), (int, float)):
                out["height"] = _spec_item(float(dims["height"]) / 1000.0, "m")
        else:
            if isinstance(dims.get("length"), (int, float)):
                out["length"] = _spec_item(float(dims["length"]) / 1000.0, "m")
            if isinstance(dims.get("width"), (int, float)):
                out["width"] = _spec_item(float(dims["width"]) / 1000.0, "m")
            if isinstance(dims.get("thickness"), (int, float)):
                out["thickness"] = _spec_item(float(dims["thickness"]) / 1000.0, "m")
    return out


def _legacy_cell_labels(doc: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    cells = doc.get("cells")
    if isinstance(cells, list):
        for item in cells:
            if isinstance(item, Mapping):
                if isinstance(item.get("identifier"), str) and item["identifier"].strip():
                    out.append(item["identifier"].strip())
                elif isinstance(item.get("name"), str) and item["name"].strip():
                    out.append(item["name"].strip())
    names = doc.get("name")
    if isinstance(names, list):
        for value in names:
            if isinstance(value, str) and value.strip():
                out.append(value.strip())
    ids = doc.get("ids")
    if isinstance(ids, list):
        for value in ids:
            if isinstance(value, str) and value.strip():
                out.append(value.strip())

    linked_data = doc.get("linked_data")
    if isinstance(linked_data, Mapping):
        cell_ids = linked_data.get("cell_ids")
        if isinstance(cell_ids, list):
            for value in cell_ids:
                if isinstance(value, str) and value.strip():
                    out.append(value.strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for item in out:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _dataset_candidates(doc: Mapping[str, Any], rel_parent: str, has_contribution: bool) -> list[dict[str, Any]]:
    data = doc.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("datasets"), list):
        out: list[dict[str, Any]] = []
        for item in data["datasets"]:
            if isinstance(item, Mapping):
                out.append(dict(item))
        return out

    # Legacy layout: no explicit datasets in battery.json. Infer one dataset record for dataset-like folders.
    if rel_parent == ".":
        return []
    if has_contribution or rel_parent.count("/") >= 2:
        inferred_id = rel_parent.split("/")[-1]
        return [
            {
                "id": _safe_token(inferred_id),
                "title": inferred_id,
                "path": ".",
                "data_type": "unknown",
                "format": "raw",
                "status": "raw",
                "notes": "Inferred from legacy battery.json without data.datasets.",
            }
        ]
    return []


def _build_bdf_job(
    *,
    dataset_id: str,
    source_battery_file: Path,
    dataset_entry: Mapping[str, Any],
    data_root: Path,
    report_out: Path,
) -> dict[str, Any]:
    battery_dir = source_battery_file.parent
    dataset_path_raw = dataset_entry.get("path")
    if isinstance(dataset_path_raw, str) and dataset_path_raw.strip():
        source_dir = (battery_dir / dataset_path_raw).resolve()
    else:
        source_dir = battery_dir.resolve()

    file_globs: list[str] = []
    raw_globs = dataset_entry.get("file_globs")
    if isinstance(raw_globs, list):
        file_globs = [str(item) for item in raw_globs if isinstance(item, str) and item.strip()]

    files: list[str] = []
    raw_files = dataset_entry.get("files")
    if isinstance(raw_files, list):
        for item in raw_files:
            if isinstance(item, Mapping) and isinstance(item.get("path"), str):
                files.append(item["path"])

    out_dir = report_out.parent / "bdf-output"
    out_file = out_dir / f"{dataset_id.rsplit('/', 1)[-1]}.bdf.h5"

    return {
        "dataset_id": dataset_id,
        "source_battery_file": str(source_battery_file.resolve()),
        "source_root": str(data_root.resolve()),
        "source_dir": str(source_dir),
        "source_globs": file_globs,
        "source_files": files,
        "source_format": dataset_entry.get("format") or "raw",
        "dataset_status": dataset_entry.get("status") or "unknown",
        "conversion_target_format": "bdf",
        "target_path": str(out_file.resolve()),
    }


def main() -> int:
    args = _parse_args()
    data_root = args.data_root.resolve()
    source_root = args.source_root.resolve()
    report_out = args.report_out.resolve()
    bdf_jobs_out = args.bdf_jobs_out.resolve()
    retrieved_at = _now_unix()

    if not data_root.exists():
        raise SystemExit(f"[ERROR] data_root does not exist: {data_root}")

    battery_files = sorted(p for p in data_root.rglob("battery.json") if p.is_file())
    if args.limit is not None:
        battery_files = battery_files[: max(0, args.limit)]

    type_id_by_key: dict[str, str] = {}
    cell_instance_id_by_seed: dict[str, str] = {}
    report_rows: list[dict[str, Any]] = []
    bdf_jobs: list[dict[str, Any]] = []

    created = {"cell_type": 0, "cell_instance": 0, "dataset": 0}
    exists = {"cell_type": 0, "cell_instance": 0, "dataset": 0}
    failed = 0
    skipped_invalid = 0

    for battery_path in battery_files:
        rel_parent = battery_path.parent.relative_to(data_root).as_posix()
        try:
            doc = _load_json(battery_path)
        except Exception as exc:  # noqa: BLE001
            if args.strict:
                failed += 1
                status = "failed"
            else:
                skipped_invalid += 1
                status = "skipped"
            report_rows.append(
                {
                    "battery_file": str(battery_path),
                    "relative_parent": rel_parent,
                    "status": status,
                    "stage": "parse_battery_json",
                    "error": str(exc),
                }
            )
            continue
        spec = doc.get("spec")
        if not isinstance(spec, Mapping):
            report_rows.append(
                {
                    "battery_file": str(battery_path),
                    "status": "skipped",
                    "reason": "missing spec object",
                }
            )
            continue

        manufacturer = _parse_manufacturer(spec)
        model = _parse_model(spec)
        cell_format = _parse_form_factor(spec)
        chemistry = _parse_chemistry(spec)
        positive_basis = _first_material(spec, "pe_materials")
        negative_basis = _first_material(spec, "ne_materials")
        type_seed = f"cell-type|{_safe_token(manufacturer)}|{_safe_token(model)}"
        type_uid = _stable_uid(type_seed)
        type_key = f"{_safe_token(manufacturer)}::{_safe_token(model)}"
        specs = _build_cell_type_specs(spec)

        contribution_path = battery_path.parent / "contribution.json"
        if contribution_path.exists():
            try:
                contribution = _load_json(contribution_path)
            except Exception as exc:  # noqa: BLE001
                if args.strict:
                    failed += 1
                    status = "failed"
                else:
                    skipped_invalid += 1
                    status = "skipped"
                report_rows.append(
                    {
                        "battery_file": str(battery_path),
                        "relative_parent": rel_parent,
                        "status": status,
                        "stage": "parse_contribution_json",
                        "error": str(exc),
                    }
                )
                contribution = {}
        else:
            contribution = {}
        source_url = contribution.get("doi") if isinstance(contribution.get("doi"), str) else None

        type_id = type_id_by_key.get(type_key)
        if type_id is None:
            draft = CellTypeInput(
                uid=type_uid,
                model_name=model,
                manufacturer=manufacturer,
                format=cell_format if cell_format in {"cylindrical", "prismatic", "pouch", "coin", "other", "unknown"} else "unknown",
                chemistry=chemistry,
                positive_electrode_basis=positive_basis,
                negative_electrode_basis=negative_basis,
                specs=specs,
                source_file=str(battery_path),
                source_url=source_url,
                retrieved_at=retrieved_at,
                notes=["Imported from D-data battery metadata."],
            )
            try:
                payload = register_cell_type(
                    draft,
                    source_root=source_root,
                    mode=args.mode,
                    duplicate_policy="return_existing",
                    resolve_references=False,
                    publish=False,
                    validate=True,
                    dry_run=args.dry_run,
                )
                type_id = str(payload["id"])
                type_id_by_key[type_key] = type_id
                status = payload.get("status")
                if status in {"created", "updated"}:
                    created["cell_type"] += 1
                elif status == "exists":
                    exists["cell_type"] += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                report_rows.append(
                    {
                        "battery_file": str(battery_path),
                        "status": "failed",
                        "stage": "register_cell_type",
                        "error": str(exc),
                    }
                )
                continue

        cell_labels = _legacy_cell_labels(doc)
        dataset_entries = _dataset_candidates(doc, rel_parent=rel_parent, has_contribution=contribution_path.exists())

        # Ensure at least one cell instance if datasets exist and no explicit labels were provided.
        if dataset_entries and not cell_labels:
            cell_labels = ["auto-cell-001"]

        cell_ids_for_dataset: list[str] = []
        for idx, label in enumerate(cell_labels):
            cell_seed = f"cell|{type_id}|{_safe_token(label)}|{rel_parent}|{idx + 1}"
            if cell_seed in cell_instance_id_by_seed:
                cell_ids_for_dataset.append(cell_instance_id_by_seed[cell_seed])
                continue
            cell_uid = _stable_uid(cell_seed)
            serial = label if label != "auto-cell-001" else None
            draft = CellInstanceInput(
                uid=cell_uid,
                type_id=type_id,
                serial_number=serial,
                source_type="measurement",
                retrieved_at=retrieved_at,
                notes=["Imported from D-data battery metadata."],
            )
            try:
                payload = register_cell_instance(
                    draft,
                    source_root=source_root,
                    mode=args.mode,
                    duplicate_policy="return_existing",
                    resolve_references=not args.dry_run,
                    publish=False,
                    validate=True,
                    dry_run=args.dry_run,
                )
                cell_id = str(payload["id"])
                cell_instance_id_by_seed[cell_seed] = cell_id
                cell_ids_for_dataset.append(cell_id)
                status = payload.get("status")
                if status in {"created", "updated"}:
                    created["cell_instance"] += 1
                elif status == "exists":
                    exists["cell_instance"] += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                report_rows.append(
                    {
                        "battery_file": str(battery_path),
                        "status": "failed",
                        "stage": "register_cell_instance",
                        "error": str(exc),
                    }
                )

        dataset_results: list[dict[str, Any]] = []
        for dataset_entry in dataset_entries:
            local_id = _safe_token(dataset_entry.get("id") or dataset_entry.get("title") or "dataset")
            dataset_seed = f"dataset|{rel_parent}|{local_id}"
            dataset_uid = _stable_uid(dataset_seed)
            title = dataset_entry.get("title") if isinstance(dataset_entry.get("title"), str) else local_id

            dataset_path_raw = dataset_entry.get("path")
            if isinstance(dataset_path_raw, str) and dataset_path_raw.strip():
                source_dir = (battery_path.parent / dataset_path_raw).resolve()
            else:
                source_dir = battery_path.parent.resolve()
            dataset_url = source_url
            if not dataset_url:
                dataset_url = source_dir.as_uri()

            encoding_format = dataset_entry.get("format") if isinstance(dataset_entry.get("format"), str) else "raw"
            if encoding_format == "raw":
                encoding_format = "application/octet-stream"

            draft = DatasetInput(
                uid=dataset_uid,
                title=title,
                description=f"Imported from D-data: {rel_parent}",
                format=encoding_format,
                access_url=dataset_url,
                source_type="external",
                related_cell_ids=cell_ids_for_dataset,
                source_url=source_url,
                retrieved_at=retrieved_at,
                notes=["Imported from D-data battery metadata."],
            )
            try:
                payload = register_dataset(
                    draft,
                    source_root=source_root,
                    mode=args.mode,
                    duplicate_policy="return_existing",
                    resolve_references=not args.dry_run,
                    publish=False,
                    validate=True,
                    dry_run=args.dry_run,
                )
                dataset_id = str(payload["id"])
                status = payload.get("status")
                if status in {"created", "updated"}:
                    created["dataset"] += 1
                elif status == "exists":
                    exists["dataset"] += 1

                dataset_results.append(
                    {
                        "dataset_id": dataset_id,
                        "local_dataset_id": local_id,
                        "status": status,
                    }
                )

                bdf_jobs.append(
                    _build_bdf_job(
                        dataset_id=dataset_id,
                        source_battery_file=battery_path,
                        dataset_entry=dataset_entry,
                        data_root=data_root,
                        report_out=report_out,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                report_rows.append(
                    {
                        "battery_file": str(battery_path),
                        "status": "failed",
                        "stage": "register_dataset",
                        "error": str(exc),
                    }
                )

        report_rows.append(
            {
                "battery_file": str(battery_path),
                "relative_parent": rel_parent,
                "status": "ok",
                "cell_type_id": type_id,
                "cell_instance_ids": cell_ids_for_dataset,
                "datasets": dataset_results,
            }
        )

    report = {
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_root": str(data_root),
        "source_root": str(source_root),
        "dry_run": bool(args.dry_run),
        "mode": args.mode,
        "battery_file_count": len(battery_files),
        "created": created,
        "exists": exists,
        "failed": failed,
        "skipped_invalid": skipped_invalid,
        "rows": report_rows,
    }

    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[OK] Wrote ingest report: {report_out}")

    bdf_jobs_payload = {
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_root": str(data_root),
        "job_count": len(bdf_jobs),
        "jobs": bdf_jobs,
    }
    bdf_jobs_out.parent.mkdir(parents=True, exist_ok=True)
    bdf_jobs_out.write_text(json.dumps(bdf_jobs_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[OK] Wrote BDF jobs manifest: {bdf_jobs_out}")

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

