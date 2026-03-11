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

from battinfo.api import (  # noqa: E402
    CellTypeInput,
    DatasetInput,
    _record_from_cell_type,
    _record_from_dataset,
)

UID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
SAFE_TOKEN_RE = re.compile(r"[^a-z0-9]+")

DEFAULT_DATA_ROOT = ROOT / ".battinfo" / "ddata"
DEFAULT_OUT_ROOT = ROOT / ".battinfo" / "ingest" / "ddata-sidecars"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate battery.json and contribution.json files for contribution folders "
            "using BattINFO canonical schema contracts."
        )
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DEFAULT_DATA_ROOT,
        help="Root folder containing the source data hierarchy.",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=DEFAULT_OUT_ROOT,
        help="Output root for generated files when not using --in-place.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Write generated files directly into D-data contribution directories.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing battery.json/contribution.json in target locations.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max contribution directories to process.",
    )
    return parser.parse_args()


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


def _now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _write_json(path: Path, payload: Mapping[str, Any], overwrite: bool) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def _extract_spec_from_battery_doc(doc: Mapping[str, Any]) -> dict[str, Any] | None:
    if isinstance(doc.get("spec"), Mapping):
        return dict(doc["spec"])

    # Canonical BattINFO battery sidecar already generated.
    if isinstance(doc.get("product"), Mapping):
        product = doc["product"]
        manufacturer = product.get("manufacturer")
        if isinstance(manufacturer, Mapping):
            manufacturer_name = manufacturer.get("name")
        else:
            manufacturer_name = manufacturer
        return {
            "manufacturer": manufacturer_name,
            "model": product.get("model") or product.get("name"),
            "chemistry": product.get("chemistry"),
            "form_factor": {"shape": product.get("cellFormat"), "format": product.get("sizeCode")},
        }
    return None


def _find_nearest_battery_spec(contrib_dir: Path, data_root: Path) -> tuple[dict[str, Any] | None, Path | None]:
    rel_parts = contrib_dir.relative_to(data_root).parts
    manufacturer_dir = data_root / rel_parts[0] if rel_parts else data_root
    current = contrib_dir
    while True:
        candidate = current / "battery.json"
        if candidate.exists():
            # Do not use the root-level battery.json as a global fallback for nested contributions.
            if current == data_root and current != contrib_dir:
                pass
            else:
                doc = _load_json(candidate)
                if isinstance(doc, Mapping):
                    spec = _extract_spec_from_battery_doc(doc)
                    if isinstance(spec, dict):
                        return spec, candidate
        # Stop at manufacturer boundary; avoids leaking metadata across brands.
        if current == manufacturer_dir and current != contrib_dir:
            break
        if current == data_root:
            break
        if current.parent == current:
            break
        current = current.parent
    return None, None


def _infer_spec_from_path(contrib_dir: Path, data_root: Path) -> dict[str, Any]:
    rel_parts = contrib_dir.relative_to(data_root).parts
    manufacturer = rel_parts[0] if len(rel_parts) >= 1 else "unknown"
    model_tokens = [part for part in rel_parts[1:] if part not in {"cell", "module", "pack"}]
    model = model_tokens[0] if model_tokens else "unknown-model"
    return {
        "manufacturer": manufacturer,
        "model": model,
        "chemistry": "unknown",
        "form_factor": {"shape": "unknown"},
    }


def _resolve_spec(contrib_dir: Path, data_root: Path) -> tuple[dict[str, Any], Path | None]:
    spec, path = _find_nearest_battery_spec(contrib_dir, data_root)
    if spec is not None:
        return spec, path
    return _infer_spec_from_path(contrib_dir, data_root), None


def _parse_manufacturer(spec: Mapping[str, Any]) -> str:
    manufacturer = spec.get("manufacturer")
    if isinstance(manufacturer, Mapping):
        name = manufacturer.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(manufacturer, str) and manufacturer.strip():
        return manufacturer.strip()
    return "unknown"


def _parse_model(spec: Mapping[str, Any], fallback: str) -> str:
    model = spec.get("model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    return fallback


def _parse_chemistry(spec: Mapping[str, Any]) -> str:
    chemistry = spec.get("chemistry")
    if isinstance(chemistry, Mapping):
        short = chemistry.get("short")
        if isinstance(short, str) and short.strip():
            return short.strip()
        full = chemistry.get("full")
        if isinstance(full, str) and full.strip():
            return full.strip()
    if isinstance(chemistry, str) and chemistry.strip():
        return chemistry.strip()
    return "unknown"


def _parse_format(spec: Mapping[str, Any]) -> str:
    form_factor = spec.get("form_factor")
    if isinstance(form_factor, Mapping):
        shape = form_factor.get("shape")
        if isinstance(shape, str) and shape.strip():
            return shape.strip().lower()
    if isinstance(form_factor, str) and form_factor.strip():
        return form_factor.strip().lower()
    return "unknown"


def _parse_size_code(spec: Mapping[str, Any]) -> str | None:
    form_factor = spec.get("form_factor")
    if isinstance(form_factor, Mapping):
        value = form_factor.get("format")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


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


def _build_specs(spec: Mapping[str, Any]) -> dict[str, Any]:
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

    return out


def _contribution_seed(contrib_dir: Path, data_root: Path) -> str:
    return contrib_dir.relative_to(data_root).as_posix()


def _build_cell_type_record(
    *,
    spec: Mapping[str, Any],
    source_file: Path,
    source_url: str | None,
    fallback_model: str,
) -> dict[str, Any]:
    manufacturer = _parse_manufacturer(spec)
    model = _parse_model(spec, fallback=fallback_model)
    chemistry = _parse_chemistry(spec)
    cell_format = _parse_format(spec)
    if cell_format not in {"cylindrical", "prismatic", "pouch", "coin", "other", "unknown"}:
        cell_format = "unknown"

    uid = _stable_uid(f"cell-type|{_safe_token(manufacturer)}|{_safe_token(model)}")
    draft = CellTypeInput(
        uid=uid,
        model_name=model,
        manufacturer=manufacturer,
        chemistry=chemistry,
        format=cell_format,
        size_code=_parse_size_code(spec),
        positive_electrode_basis=_first_material(spec, "pe_materials"),
        negative_electrode_basis=_first_material(spec, "ne_materials"),
        specs=_build_specs(spec),
        source_file=str(source_file),
        source_url=source_url,
        retrieved_at=_now_unix(),
        notes=["Generated by .tools/ingest/generate_ddata_sidecars.py"],
    )
    return _record_from_cell_type(draft)


def _build_contribution_record(
    *,
    contrib_dir: Path,
    data_root: Path,
    source_file: Path,
    contribution_doc: Mapping[str, Any] | None,
    cell_type_record: Mapping[str, Any],
) -> dict[str, Any]:
    rel = _contribution_seed(contrib_dir, data_root)
    dataset_uid = _stable_uid(f"dataset|{rel}")

    product = cell_type_record.get("product", {})
    if isinstance(product, Mapping):
        model = product.get("model") or product.get("name") or contrib_dir.name
        manufacturer = product.get("manufacturer")
        if isinstance(manufacturer, Mapping):
            m_name = manufacturer.get("name")
        else:
            m_name = manufacturer
        label = f"{m_name} {model} {contrib_dir.name}".strip()
    else:
        label = contrib_dir.name

    doi_url = None
    license_value = None
    notes: list[str] = ["Generated by .tools/ingest/generate_ddata_sidecars.py"]
    citation_entries: list[dict[str, str]] = []
    if isinstance(contribution_doc, Mapping):
        if isinstance(contribution_doc.get("doi"), str):
            doi_url = contribution_doc["doi"]
        if isinstance(contribution_doc.get("license"), str):
            license_value = contribution_doc["license"]
        citations = contribution_doc.get("citation")
        if isinstance(citations, list):
            for idx, entry in enumerate(citations, start=1):
                if not isinstance(entry, str) or not entry.strip():
                    continue
                citation_entries.append(
                    {
                        "kind": "article",
                        "url": entry.strip(),
                        "citation_key": f"legacy_citation_{idx}",
                    }
                )

    draft = DatasetInput(
        uid=dataset_uid,
        title=label,
        description=f"Contribution metadata for {rel}",
        license=license_value,
        access_url=doi_url or contrib_dir.as_uri(),
        source_type="external",
        source_url=doi_url,
        retrieved_at=_now_unix(),
        notes=notes,
    )
    record = _record_from_dataset(draft)
    if citation_entries:
        record.setdefault("dataset", {})
        if isinstance(record["dataset"], dict):
            record["dataset"]["citation"] = citation_entries
    if isinstance(record.get("dataset"), dict) and isinstance(product, Mapping):
        product_id = product.get("id")
        if isinstance(product_id, str):
            # Keep link without forcing a synthetic cell instance.
            record["dataset"]["isBasedOn"] = [product_id]
    if isinstance(record.get("provenance"), dict):
        record["provenance"]["source_file"] = str(source_file)
    return record


def main() -> int:
    args = _parse_args()
    data_root = args.data_root.resolve()
    out_root = args.out_root.resolve()

    if not data_root.exists():
        raise SystemExit(f"[ERROR] data_root does not exist: {data_root}")

    contribution_paths = sorted(data_root.rglob("contribution.json"))
    if args.limit is not None:
        contribution_paths = contribution_paths[: max(0, args.limit)]

    written = 0
    skipped = 0
    failed = 0
    report_rows: list[dict[str, Any]] = []

    for contribution_path in contribution_paths:
        contrib_dir = contribution_path.parent
        rel_dir = contrib_dir.relative_to(data_root)
        contribution_doc = _load_json(contribution_path)

        spec, battery_source_path = _resolve_spec(contrib_dir, data_root)

        try:
            cell_type = _build_cell_type_record(
                spec=spec,
                source_file=battery_source_path or contribution_path,
                source_url=(
                    contribution_doc.get("doi")
                    if isinstance(contribution_doc, Mapping) and isinstance(contribution_doc.get("doi"), str)
                    else None
                ),
                fallback_model=contrib_dir.parent.name,
            )
            dataset = _build_contribution_record(
                contrib_dir=contrib_dir,
                data_root=data_root,
                source_file=contribution_path,
                contribution_doc=contribution_doc,
                cell_type_record=cell_type,
            )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            report_rows.append(
                {
                    "contribution_file": str(contribution_path),
                    "status": "failed",
                    "error": str(exc),
                }
            )
            continue

        if args.in_place:
            target_dir = contrib_dir
        else:
            target_dir = out_root / rel_dir

        battery_out = target_dir / "battery.json"
        contribution_out = target_dir / "contribution.json"

        wrote_battery = _write_json(battery_out, cell_type, overwrite=args.overwrite)
        wrote_contribution = _write_json(contribution_out, dataset, overwrite=args.overwrite)

        if wrote_battery or wrote_contribution:
            written += int(wrote_battery) + int(wrote_contribution)
            status = "written"
        else:
            skipped += 1
            status = "skipped_exists"

        report_rows.append(
            {
                "contribution_file": str(contribution_path),
                "status": status,
                "battery_out": str(battery_out),
                "contribution_out": str(contribution_out),
                "cell_type_id": cell_type.get("product", {}).get("id") if isinstance(cell_type.get("product"), Mapping) else None,
                "dataset_id": dataset.get("dataset", {}).get("id") if isinstance(dataset.get("dataset"), Mapping) else None,
                "spec_source": str(battery_source_path) if battery_source_path else "path-inferred",
            }
        )

    report = {
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_root": str(data_root),
        "out_root": str(out_root),
        "in_place": bool(args.in_place),
        "processed_contributions": len(contribution_paths),
        "written_files": written,
        "skipped": skipped,
        "failed": failed,
        "rows": report_rows,
    }

    report_path = (out_root if not args.in_place else ROOT / ".battinfo" / "ingest" / "reports") / "ddata-sidecars.report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[OK] Wrote report: {report_path}")
    print(f"[INFO] processed={len(contribution_paths)} written_files={written} skipped={skipped} failed={failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

