from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / ".battinfo" / "ingest" / "manifests" / "datasheet-sources.manifest.json"
DEFAULT_TARGET_DIR = ROOT / ".battinfo" / "ingest" / "candidates" / "pdf-seeded"

TOKEN_RE = re.compile(r"[^a-z0-9._:-]+")
FILE_TOKEN_RE = re.compile(r"[^a-z0-9._-]+")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed PDF candidate records from datasource manifest hints (manufacturer/models from filenames)."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="Source manifest JSON path.")
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET_DIR, help="Output candidate directory.")
    parser.add_argument(
        "--batch-tag",
        type=str,
        default="pdf-seeded-candidates-v1",
        help="Stored in extensions.x-battinfo-ingest_batch.",
    )
    parser.add_argument("--clean-target", action="store_true", help="Delete existing *.candidate.json files first.")
    parser.add_argument("--dry-run", action="store_true", help="Preview outputs without writing files.")
    return parser.parse_args()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(value: str) -> str:
    return (TOKEN_RE.sub("-", value.strip().lower()).strip("-") or "unknown")


def _sanitize_filename(value: str) -> str:
    return (FILE_TOKEN_RE.sub("-", value.strip().lower()).strip("-") or "unknown")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _models_from_hints(source: dict[str, Any]) -> list[str]:
    hints = source.get("hints", {})
    if not isinstance(hints, dict):
        return []
    models = hints.get("models")
    if not isinstance(models, list):
        return []
    out: list[str] = []
    for model in models:
        if isinstance(model, str):
            token = model.strip()
            if token:
                out.append(token)
    return out


def _manufacturer_hint(source: dict[str, Any]) -> str:
    hints = source.get("hints", {})
    if not isinstance(hints, dict):
        return "Unknown"
    manufacturer = hints.get("manufacturer")
    if isinstance(manufacturer, str) and manufacturer.strip():
        return manufacturer.strip()
    return "Unknown"


def _make_candidate(source: dict[str, Any], model: str, index: int, total: int, batch_tag: str) -> dict[str, Any]:
    source_id = str(source.get("source_id", "src:unknown"))
    manufacturer = _manufacturer_hint(source)
    candidate_id = f"candidate:pdf:{_sanitize(source_id)}:{_sanitize(model)}:{index}"
    return {
        "version": "1.0.0",
        "candidate": {
            "candidate_id": candidate_id,
            "source_document_id": source_id,
            "source_type": "pdf-datasheet",
            "product": {
                "name": model,
                "manufacturer": manufacturer,
                "model": model,
                "chemistry": "unknown",
                "positive_electrode_basis": "unknown",
                "negative_electrode_basis": "unknown",
                "format": "unknown",
                "category": "battery cell"
            },
            "specs": {},
            "split": {
                "is_multi_cell_source": total > 1,
                "variant_index": index,
                "variant_total": total,
                "variant_label": model
            }
        },
        "provenance": {
            "extracted_at": _now_iso(),
            "extractor": ".tools/ingest/seed_pdf_candidates_from_manifest.py",
            "extractor_version": "1.0.0",
            "source_record": str(source.get("path", "")),
            "source_checksum": str(source.get("checksum_sha256", "")),
        },
        "quality": {
            "missing_fields": [
                "candidate.product.chemistry",
                "candidate.product.positive_electrode_basis",
                "candidate.product.negative_electrode_basis",
                "candidate.specs"
            ],
            "inferred_fields": [
                "candidate.product.model"
            ],
            "warnings": [
                "Seeded from filename hints only. Manual or parser-based enrichment required."
            ]
        },
        "notes": [
            "This is a seeded candidate from PDF filename metadata.",
            "Run extraction/parsing to populate quantitative specs before publication."
        ],
        "extensions": {
            "x-battinfo-ingest_batch": batch_tag,
            "x-battinfo-seed_mode": "filename-hints"
        }
    }


def main() -> int:
    args = _parse_args()
    manifest = _load_json(args.manifest)
    sources = manifest.get("sources", [])
    if not isinstance(sources, list):
        print(f"[ERROR] Invalid manifest structure: {_display_path(args.manifest)}")
        return 1

    pdf_sources = [row for row in sources if isinstance(row, dict) and row.get("source_type") == "pdf-datasheet"]
    if not pdf_sources:
        print("[WARN] No pdf-datasheet source records in manifest.")
        return 0

    if args.clean_target and args.target_dir.exists():
        removed = 0
        for existing in sorted(args.target_dir.glob("*.candidate.json")):
            existing.unlink()
            removed += 1
        print(f"[INFO] Removed {removed} existing candidate file(s) from {_display_path(args.target_dir)}")

    args.target_dir.mkdir(parents=True, exist_ok=True)

    to_write: list[tuple[Path, dict[str, Any]]] = []
    for source in pdf_sources:
        models = _models_from_hints(source)
        if not models:
            models = [Path(str(source.get("file_name", "unknown.pdf"))).stem]
        total = len(models)
        for index, model in enumerate(models):
            candidate = _make_candidate(source, model=model, index=index, total=total, batch_tag=args.batch_tag)
            source_token = _sanitize_filename(str(source.get("source_id", "src:unknown")))
            file_token = _sanitize_filename(model)
            out_path = args.target_dir / f"{source_token}__{file_token}__{index}.candidate.json"
            to_write.append((out_path, candidate))

    if args.dry_run:
        for out_path, _ in to_write[:20]:
            print(f"[DRY] Would write {_display_path(out_path)}")
        if len(to_write) > 20:
            print(f"[DRY] ... and {len(to_write) - 20} more candidate file(s)")
        print(f"[OK] Prepared {len(to_write)} seeded candidate record(s) from {len(pdf_sources)} PDF source file(s).")
        return 0

    for out_path, candidate in to_write:
        out_path.write_text(json.dumps(candidate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[OK] Wrote {len(to_write)} seeded candidate file(s) to {_display_path(args.target_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

