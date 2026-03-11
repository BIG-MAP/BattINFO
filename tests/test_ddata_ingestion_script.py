from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)


def test_ingest_ddata_registry_emits_canonical_records_and_bdf_jobs(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    battery_dir = data_root / "acme" / "mx-01"
    battery_dir.mkdir(parents=True)

    (battery_dir / "battery.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "spec": {
                    "manufacturer": "Acme",
                    "model": "MX-01",
                    "chemistry": {"short": "Li-ion"},
                    "form_factor": {"shape": "cylindrical", "format": "18650"},
                    "nominal_voltage_V": 3.6,
                    "nominal_capacity_Ah": 2.6,
                },
                "data": {
                    "datasets": [
                        {
                            "id": "run-0001",
                            "title": "Acme MX-01 run 0001",
                            "path": "data/run-0001",
                            "data_type": "cycling",
                            "format": "raw",
                            "status": "raw",
                            "file_globs": ["data/run-0001/*.csv"],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    (battery_dir / "contribution.json").write_text(
        json.dumps({"doi": "https://doi.org/10.1234/example.doi.1", "license": "CC-BY-4.0"}),
        encoding="utf-8",
    )

    source_root = tmp_path / "registry"
    report_out = tmp_path / "reports" / "ingest-report.json"
    jobs_out = tmp_path / "reports" / "bdf-jobs.json"

    result = _run(
        [
            sys.executable,
            ".tools/ingest/ingest_ddata_registry.py",
            "--data-root",
            str(data_root),
            "--source-root",
            str(source_root),
            "--report-out",
            str(report_out),
            "--bdf-jobs-out",
            str(jobs_out),
        ]
    )
    assert result.returncode == 0, result.stderr
    assert report_out.exists()
    assert jobs_out.exists()

    report = json.loads(report_out.read_text(encoding="utf-8"))
    assert report["battery_file_count"] == 1
    assert report["failed"] == 0
    assert report["created"]["cell_type"] >= 1
    assert report["created"]["cell_instance"] >= 1
    assert report["created"]["dataset"] >= 1

    jobs = json.loads(jobs_out.read_text(encoding="utf-8"))
    assert jobs["job_count"] == 1
    assert jobs["jobs"][0]["conversion_target_format"] == "bdf"

    assert any((source_root / "cell-types").glob("*.json"))
    assert any((source_root / "cell-instances").glob("*.json"))
    assert any((source_root / "datasets").glob("*.json"))

