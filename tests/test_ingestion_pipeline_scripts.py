from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)


def test_build_manifest_and_seed_pdf_candidates(tmp_path: Path) -> None:
    cellinfo_dir = tmp_path / "cellinfo"
    pdf_dir = tmp_path / "pdfs"
    cellinfo_dir.mkdir()
    pdf_dir.mkdir()

    (cellinfo_dir / "A123_20AH.json").write_text(
        json.dumps(
            {
                "cell": {"manufacturer": "A123", "model_name": "A123_20AH"},
                "specs": {},
            }
        ),
        encoding="utf-8",
    )
    # Same bytes -> checksum duplicate.
    (pdf_dir / "LG__E101A__E72B.pdf").write_bytes(b"%PDF-1.7 duplicate")
    (pdf_dir / "copy.pdf").write_bytes(b"%PDF-1.7 duplicate")

    manifest_path = tmp_path / "manifest.json"
    summary_path = tmp_path / "manifest.md"
    manifest = _run(
        [
            sys.executable,
            ".tools/build/build_datasheet_source_manifest.py",
            "--cellinfo-dir",
            str(cellinfo_dir),
            "--pdf-dir",
            str(pdf_dir),
            "--out",
            str(manifest_path),
            "--summary-md",
            str(summary_path),
        ]
    )
    assert manifest.returncode == 0, manifest.stderr
    assert manifest_path.exists()
    assert summary_path.exists()

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(payload["sources"]) == 3
    multi = [row for row in payload["sources"] if row["source_type"] == "pdf-datasheet" and row["hints"]["contains_multiple_cells"]]
    assert len(multi) == 1
    assert multi[0]["hints"]["models"] == ["E101A", "E72B"]
    duplicates = [row for row in payload["sources"] if row.get("status") == "duplicate"]
    assert len(duplicates) == 1

    seeded_dir = tmp_path / "seeded"
    seeded = _run(
        [
            sys.executable,
            ".tools/ingest/seed_pdf_candidates_from_manifest.py",
            "--manifest",
            str(manifest_path),
            "--target-dir",
            str(seeded_dir),
            "--clean-target",
        ]
    )
    assert seeded.returncode == 0, seeded.stderr
    # 2 variants from LG__E101A__E72B + 1 from copy.pdf
    assert len(list(seeded_dir.glob("*.candidate.json"))) == 3


def test_ingest_cellinfo_candidates_and_match_report(tmp_path: Path) -> None:
    source_dir = tmp_path / "cells-clean"
    source_dir.mkdir()

    (source_dir / "A123_20AH.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "provenance": {"source_type": "curated", "source_id": "cellinfo:A123_20AH"},
                "cell": {
                    "model_name": "A123_20AH",
                    "manufacturer": "A123",
                    "format": "prismatic",
                    "chemistry": "LFP",
                },
                "specs": {
                    "nominal_capacity": {"value": 20.0, "unit": "Ah"},
                    "nominal_voltage": {"value": 3.3, "unit": "V"},
                },
                "quality": {"missing_fields": [], "inferred_fields": [], "warnings": []},
            }
        ),
        encoding="utf-8",
    )

    candidate_dir = tmp_path / "candidates"
    converted = _run(
        [
            sys.executable,
            ".tools/ingest/ingest_cellinfo_candidates.py",
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(candidate_dir),
            "--validate",
            "--clean-target",
        ]
    )
    assert converted.returncode == 0, converted.stderr
    candidate_files = list(candidate_dir.glob("*.candidate.json"))
    assert len(candidate_files) == 1

    existing_dir = tmp_path / "existing"
    existing_dir.mkdir()
    (existing_dir / "example.datasheet.json").write_text(
        json.dumps(
            {
                "version": "1.0.0-draft",
                "status": "draft",
                "product": {
                    "type": "Product",
                    "identifier": "https://w3id.org/battinfo/cell-type/pvn1-43h7-rm3e-mjqq",
                    "short_id": "pvn143",
                    "name": "A123_20AH",
                    "brand": "A123",
                    "manufacturer": "A123",
                    "model": "A123_20AH",
                    "chemistry": "Li-ion",
                    "positive_electrode_basis": "LFP",
                    "negative_electrode_basis": "Graphite",
                    "format": "prismatic",
                    "category": "prismatic battery cell"
                },
                "specs": {
                    "nominal_capacity": {"value": 20.0, "unit": "Ah"},
                    "nominal_voltage": {"value": 3.3, "unit": "V"}
                },
                "lineage": {
                    "source_record": "src/example.json",
                    "source_type": "curated",
                    "source_file": "example.json",
                    "extracted_at": "2026-02-23T00:00:00Z"
                }
            }
        ),
        encoding="utf-8",
    )

    report_md = tmp_path / "match-report.md"
    report_json = tmp_path / "match-report.json"
    matched = _run(
        [
            sys.executable,
            ".tools/ingest/report_candidate_matches.py",
            "--candidate-dir",
            str(candidate_dir),
            "--existing-dir",
            str(existing_dir),
            "--out",
            str(report_md),
            "--json-out",
            str(report_json),
            "--match-threshold",
            "0.80",
        ]
    )
    assert matched.returncode == 0, matched.stderr
    assert report_md.exists()
    assert report_json.exists()
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert payload["candidate_count"] == 1
    assert payload["results"][0]["decision"] == "match_existing"

