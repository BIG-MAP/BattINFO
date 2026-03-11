from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)


def _write_candidate_maps(tmp_path: Path) -> tuple[Path, Path]:
    property_map = tmp_path / "property_map.candidates.json"
    unit_map = tmp_path / "unit_map.candidates.json"
    property_map.write_text(
        json.dumps(
            {
                "mappings": [
                    {
                        "key": "nominal_voltage",
                        "status": "candidate",
                        "class_iri": "https://example.org/NominalVoltage",
                        "class_pref_label": "NominalVoltage",
                        "confidence": 1.0,
                    },
                    {
                        "key": "storage_temperature_max",
                        "status": "unmapped",
                        "class_iri": None,
                        "class_pref_label": None,
                        "confidence": 0.0,
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    unit_map.write_text(
        json.dumps(
            {
                "mappings": [
                    {
                        "symbol": "V",
                        "status": "candidate",
                        "unit_iri": "https://example.org/Volt",
                        "unit_pref_label": "Volt",
                        "confidence": 1.0,
                    },
                    {
                        "symbol": "Ah",
                        "status": "unmapped",
                        "unit_iri": None,
                        "unit_pref_label": None,
                        "confidence": 0.0,
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return property_map, unit_map


def test_semantic_mapping_gate_fails_on_unmapped(tmp_path: Path) -> None:
    property_map, unit_map = _write_candidate_maps(tmp_path)
    report = tmp_path / "gate.md"

    result = _run(
        [
            sys.executable,
            ".tools/semantic/check_semantic_mapping_candidates.py",
            "--property-map",
            str(property_map),
            "--unit-map",
            str(unit_map),
            "--report",
            str(report),
            "--max-unmapped-properties",
            "0",
            "--max-unmapped-units",
            "0",
        ]
    )
    assert result.returncode == 1
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "Result: `FAIL`" in text
    assert "`storage_temperature_max`" in text
    assert "`Ah`" in text


def test_semantic_mapping_gate_passes_with_relaxed_thresholds(tmp_path: Path) -> None:
    property_map, unit_map = _write_candidate_maps(tmp_path)
    report = tmp_path / "gate.md"

    result = _run(
        [
            sys.executable,
            ".tools/semantic/check_semantic_mapping_candidates.py",
            "--property-map",
            str(property_map),
            "--unit-map",
            str(unit_map),
            "--report",
            str(report),
            "--max-unmapped-properties",
            "2",
            "--max-unmapped-units",
            "2",
            "--max-low-confidence-properties",
            "2",
            "--max-low-confidence-units",
            "2",
        ]
    )
    assert result.returncode == 0, result.stderr
    text = report.read_text(encoding="utf-8")
    assert "Result: `PASS`" in text

