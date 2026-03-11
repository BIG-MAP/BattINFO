from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)


def test_generate_ddata_sidecars_outputs_canonical_battery_and_contribution(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    battery_root = data_root / "acme" / "mx-01"
    contribution_dir = battery_root / "paper-2026"
    contribution_dir.mkdir(parents=True)

    (battery_root / "battery.json").write_text(
        json.dumps(
            {
                "spec": {
                    "manufacturer": "Acme",
                    "model": "MX-01",
                    "chemistry": {"short": "Li-ion"},
                    "form_factor": {"shape": "cylindrical", "format": "18650"},
                    "nominal_voltage_V": 3.6,
                    "nominal_capacity_Ah": 2.6,
                }
            }
        ),
        encoding="utf-8",
    )
    (contribution_dir / "contribution.json").write_text(
        json.dumps(
            {
                "doi": "https://doi.org/10.1000/example-1",
                "license": "https://creativecommons.org/licenses/by/4.0/",
                "citation": ["https://doi.org/10.1000/article-1"],
            }
        ),
        encoding="utf-8",
    )

    out_root = tmp_path / "generated"
    result = _run(
        [
            sys.executable,
            ".tools/ingest/generate_ddata_sidecars.py",
            "--data-root",
            str(data_root),
            "--out-root",
            str(out_root),
            "--overwrite",
        ]
    )
    assert result.returncode == 0, result.stderr

    battery_out = out_root / "acme" / "mx-01" / "paper-2026" / "battery.json"
    contribution_out = out_root / "acme" / "mx-01" / "paper-2026" / "contribution.json"
    assert battery_out.exists()
    assert contribution_out.exists()

    battery_doc = json.loads(battery_out.read_text(encoding="utf-8"))
    assert "product" in battery_doc
    assert battery_doc["product"]["model"] == "MX-01"
    assert battery_doc["product"]["manufacturer"]["name"] == "Acme"

    contrib_doc = json.loads(contribution_out.read_text(encoding="utf-8"))
    assert "dataset" in contrib_doc
    assert contrib_doc["dataset"]["name"].startswith("Acme MX-01")
    assert contrib_doc["dataset"]["url"] == "https://doi.org/10.1000/example-1"

