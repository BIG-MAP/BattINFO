from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DIR = ROOT / "src" / "battinfo" / "data" / "examples" / "cells-clean"
DEFAULT_TARGET_DIR = ROOT / ".battinfo" / "ingest" / "candidates" / "cellinfo"
SCHEMA_PATH = ROOT / "assets" / "schemas" / "cell-type-candidate.schema.json"

TOKEN_RE = re.compile(r"[^a-z0-9._:-]+")

SPEC_KEY_MAP = {
    "charge_voltage": "charging_voltage",
    "discharge_cutoff_voltage": "discharging_cutoff_voltage",
    "discharge_current": "discharging_current",
    "max_discharge_current": "max_discharging_current",
    "continuous_discharge_current": "continuous_discharging_current",
    "max_charge_current": "max_charging_current",
    "weight": "mass",
    "impedance": "internal_resistance",
    "storage_temperature_range": "storage_temperature",
    "minimum_capacity": "min_capacity",
}

ALLOWED_SPECS = {
    "nominal_capacity",
    "rated_capacity",
    "min_capacity",
    "nominal_energy",
    "nominal_specific_energy",
    "nominal_energy_density",
    "nominal_voltage",
    "charging_voltage",
    "discharging_cutoff_voltage",
    "charging_current",
    "max_charging_current",
    "discharging_current",
    "continuous_discharging_current",
    "max_discharging_current",
    "cycle_life",
    "internal_resistance",
    "mass",
    "height",
    "width",
    "length",
    "thickness",
    "diameter",
    "operating_temperature_charging",
    "operating_temperature_discharging",
    "storage_temperature",
}

UNIT_NORMALIZATION = {
    "g": "g",
    "kg": "kg",
    "v": "V",
    "a": "A",
    "ah": "Ah",
    "wh": "Wh",
    "count": "count",
    "mm": "mm",
    "cm": "cm",
    "m": "m",
    "ohm": "ohm",
    "mohm": "milliohm",
    "mω": "milliohm",
    "mΩ": "milliohm",
    "Ω": "ohm",
    "°c": "degC",
    "℃": "degC",
    "degc": "degC",
    "c": "C",
    "ma": "mA",
    "mg/cm2": "mg/cm^2",
    "g/cm3": "g/cm^3",
}

FORMAT_ALLOWED = {"cylindrical", "prismatic", "pouch", "coin", "other", "unknown"}
CHEMISTRY_FAMILY_CANON = {"li-ion": "Li-ion", "na-ion": "Na-ion", "zn-air": "Zn-air", "ni-mh": "Ni-MH"}
LI_ION_BASIS = {"lfp", "nmc", "nca", "lco", "lmo", "lnmo", "nmca", "nmc/lmo", "lto"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert CellInfo-derived cells-clean records into normalized BattINFO cell-type candidate records."
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR, help="Source cells-clean directory.")
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET_DIR, help="Target candidate directory.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max records to process (0 = all).")
    parser.add_argument(
        "--batch-tag",
        type=str,
        default="cellinfo-candidate-import-v1",
        help="Stored in extensions.x-battinfo-ingest_batch.",
    )
    parser.add_argument("--clean-target", action="store_true", help="Delete existing *.candidate.json files first.")
    parser.add_argument("--dry-run", action="store_true", help="Preview conversion without writing output files.")
    parser.add_argument("--validate", action="store_true", help="Validate output records against candidate schema.")
    parser.add_argument(
        "--summary-md",
        type=Path,
        default=None,
        help="Optional markdown summary report path.",
    )
    return parser.parse_args()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_token(value: str) -> str:
    token = TOKEN_RE.sub("-", value.strip().lower()).strip("-")
    return token or "unknown"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_format(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in FORMAT_ALLOWED:
        return token
    return "unknown"


def _normalize_unit(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        return "unknown"
    return UNIT_NORMALIZATION.get(token.lower(), token)


def _normalize_chemistry(raw_value: Any) -> tuple[str, str]:
    raw = str(raw_value or "").strip()
    token = raw.lower()
    if not token:
        return "unknown", "unknown"
    if token in CHEMISTRY_FAMILY_CANON:
        return CHEMISTRY_FAMILY_CANON[token], "unknown"
    if token in LI_ION_BASIS:
        return "Li-ion", raw.upper() if token != "nmc/lmo" else "NMC/LMO"
    if "lithium titanate" in token:
        return "Li-ion", "LTO"
    if "sodium" in token:
        return "Na-ion", "unknown"
    return raw, "unknown"


def _to_spec_item(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("value", "value_min", "value_max", "value_typical", "value_text"):
        if key in value:
            out[key] = value[key]
    if not any(key in out for key in ("value", "value_min", "value_max", "value_typical", "value_text")):
        return None
    out["unit"] = _normalize_unit(value.get("unit"))
    return out


def _normalize_specs(raw_specs: Any) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(raw_specs, dict):
        return {}, []
    out: dict[str, Any] = {}
    skipped: list[str] = []
    for key, value in raw_specs.items():
        out_key = SPEC_KEY_MAP.get(str(key), str(key))
        if out_key not in ALLOWED_SPECS:
            skipped.append(str(key))
            continue
        spec_item = _to_spec_item(value)
        if spec_item is None:
            skipped.append(str(key))
            continue
        out[out_key] = spec_item
    return out, sorted(set(skipped))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_candidate(path: Path, doc: dict[str, Any], batch_tag: str) -> tuple[dict[str, Any], list[str]]:
    cell = doc.get("cell", {})
    provenance = doc.get("provenance", {})
    quality = doc.get("quality", {})
    specs, skipped_specs = _normalize_specs(doc.get("specs", {}))

    if not isinstance(cell, dict):
        cell = {}
    if not isinstance(provenance, dict):
        provenance = {}
    if not isinstance(quality, dict):
        quality = {}

    model = str(cell.get("model_name") or "unknown-model")
    manufacturer = str(cell.get("manufacturer") or "Unknown")
    chemistry, positive_basis = _normalize_chemistry(cell.get("chemistry"))

    source_checksum = _sha256(path)
    source_document_id = f"src:cellinfo-{source_checksum[:16]}"
    candidate_token = _sanitize_token(path.stem)
    candidate_id = f"candidate:cellinfo:{candidate_token}"

    missing_fields: list[str] = []
    if manufacturer.strip().lower() in {"", "unknown"}:
        missing_fields.append("candidate.product.manufacturer")
    if model.strip().lower() in {"", "unknown", "unknown-model"}:
        missing_fields.append("candidate.product.model")
    if chemistry.strip().lower() in {"", "unknown"}:
        missing_fields.append("candidate.product.chemistry")
    if not specs:
        missing_fields.append("candidate.specs")

    inferred_fields: list[str] = []
    for field in quality.get("inferred_fields", []):
        if isinstance(field, str):
            inferred_fields.append(field)
    fmt = _normalize_format(cell.get("format"))
    if fmt == "unknown":
        inferred_fields.append("candidate.product.format")

    warnings: list[str] = []
    for warning in quality.get("warnings", []):
        if isinstance(warning, str):
            warnings.append(warning)
    if skipped_specs:
        warnings.append(f"Skipped {len(skipped_specs)} unsupported or invalid spec keys.")

    out = {
        "version": "1.0.0",
        "candidate": {
            "candidate_id": candidate_id,
            "source_document_id": source_document_id,
            "source_type": "cellinfo-json",
            "product": {
                "name": model,
                "manufacturer": manufacturer,
                "model": model,
                "chemistry": chemistry,
                "positive_electrode_basis": positive_basis,
                "negative_electrode_basis": "unknown",
                "format": fmt,
                "category": f"{fmt} battery cell" if fmt != "unknown" else "battery cell",
            },
            "specs": specs,
            "split": {
                "is_multi_cell_source": False,
                "variant_index": 0,
                "variant_total": 1,
            },
        },
        "provenance": {
            "extracted_at": _now_iso(),
            "extractor": ".tools/ingest/ingest_cellinfo_candidates.py",
            "extractor_version": "1.0.0",
            "source_record": str(path.resolve()),
            "source_checksum": source_checksum,
        },
        "quality": {
            "missing_fields": sorted(set(missing_fields)),
            "inferred_fields": sorted(set(inferred_fields)),
            "warnings": sorted(set(warnings)),
        },
        "notes": [
            "Candidate record generated from CellInfo-derived cells-clean input.",
            "This is an ingestion-stage record; do not treat as canonical BattINFO publication."
        ],
        "extensions": {
            "x-battinfo-ingest_batch": batch_tag,
            "x-battinfo-source_type": str(provenance.get("source_type", "curated")),
            "x-battinfo-source_id": str(provenance.get("source_id", "")),
            "x-battinfo-skipped_specs": skipped_specs,
        },
    }
    source_url = provenance.get("source_url")
    if isinstance(source_url, str) and source_url.strip():
        out["provenance"]["source_url"] = source_url
    return out, skipped_specs


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _render_summary(total: int, written: int, skipped_specs_total: int, target_dir: Path) -> str:
    lines: list[str] = []
    lines.append("# CellInfo Candidate Import Summary")
    lines.append("")
    lines.append(f"- Source records processed: `{total}`")
    lines.append(f"- Candidate files written: `{written}`")
    lines.append(f"- Total skipped spec keys: `{skipped_specs_total}`")
    lines.append(f"- Output directory: `{_display_path(target_dir)}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    files = sorted(args.source_dir.glob("*.json"))
    if args.limit > 0:
        files = files[: args.limit]
    if not files:
        print(f"[WARN] No input records found in: {_display_path(args.source_dir)}")
        return 0

    if args.clean_target and args.target_dir.exists():
        removed = 0
        for existing in sorted(args.target_dir.glob("*.candidate.json")):
            existing.unlink()
            removed += 1
        print(f"[INFO] Removed {removed} existing candidate file(s) from {_display_path(args.target_dir)}")

    validator = _validator() if args.validate else None
    args.target_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped_specs_total = 0
    for path in files:
        doc = _load_json(path)
        candidate, skipped_specs = _build_candidate(path, doc, batch_tag=args.batch_tag)
        skipped_specs_total += len(skipped_specs)

        if validator is not None:
            errors = sorted(validator.iter_errors(candidate), key=lambda err: list(err.path))
            if errors:
                first = errors[0]
                loc = ".".join(str(part) for part in first.path)
                if loc:
                    print(f"[FAIL] {_display_path(path)} -> {loc}: {first.message}")
                else:
                    print(f"[FAIL] {_display_path(path)} -> {first.message}")
                return 1

        out_path = args.target_dir / f"{path.stem}.candidate.json"
        if args.dry_run:
            print(f"[DRY] Would write {_display_path(out_path)}")
            continue
        out_path.write_text(json.dumps(candidate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written += 1

    print(
        f"[OK] Processed {len(files)} source file(s); "
        f"{'would write' if args.dry_run else 'wrote'} {written if not args.dry_run else len(files)} candidate file(s)."
    )

    if args.summary_md is not None and not args.dry_run:
        args.summary_md.parent.mkdir(parents=True, exist_ok=True)
        args.summary_md.write_text(
            _render_summary(
                total=len(files),
                written=written,
                skipped_specs_total=skipped_specs_total,
                target_dir=args.target_dir,
            ),
            encoding="utf-8",
        )
        print(f"[OK] Wrote summary: {_display_path(args.summary_md)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

