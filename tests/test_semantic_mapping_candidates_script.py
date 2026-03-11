from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)


def test_generate_semantic_mapping_candidates_from_local_ontology(tmp_path: Path) -> None:
    ontology_path = tmp_path / "ontology.ttl"
    keys_path = tmp_path / "keys.json"
    sample_path = tmp_path / "sample.json"
    out_dir = tmp_path / "out"

    ontology_path.write_text(
        """
@prefix ex: <https://example.org/onto#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

ex:Energy a owl:Class ; rdfs:label "Energy" .
ex:Mass a owl:Class ; rdfs:label "Mass" .
ex:NominalVoltage a owl:Class ; rdfs:label "Nominal Voltage" .
ex:Joule a owl:Class ; rdfs:label "Joule" .
ex:Volt a owl:Class ; rdfs:label "Volt" .
ex:Kilogram a owl:Class ; rdfs:label "Kilogram" .
""".strip(),
        encoding="utf-8",
    )
    keys_path.write_text(json.dumps(["energy", "mass", "nominal_voltage"], indent=2), encoding="utf-8")
    sample_path.write_text(
        json.dumps(
            {
                "property": {
                    "energy": {"value": 90.2, "unit": "J"},
                    "nominal_voltage": {"value": 3.3, "unit": "V"},
                    "mass": {"value": 0.076, "unit": "kg"},
                }
            }
        ),
        encoding="utf-8",
    )

    result = _run(
        [
            sys.executable,
            ".tools/semantic/generate_semantic_mapping_candidates.py",
            "--ontology",
            str(ontology_path),
            "--keys-file",
            str(keys_path),
            "--sample-json",
            str(sample_path),
            "--out-dir",
            str(out_dir),
            "--overwrite",
        ]
    )
    assert result.returncode == 0, result.stderr

    property_map_path = out_dir / "property_map.candidates.json"
    unit_map_path = out_dir / "unit_map.candidates.json"
    report_path = out_dir / "quantitative_mapping_report.md"
    assert property_map_path.exists()
    assert unit_map_path.exists()
    assert report_path.exists()

    property_map = json.loads(property_map_path.read_text(encoding="utf-8"))
    entries = {row["key"]: row for row in property_map["mappings"]}
    assert entries["energy"]["status"] == "candidate"
    assert entries["energy"]["class_iri"].endswith("#Energy")
    assert entries["nominal_voltage"]["class_iri"].endswith("#NominalVoltage")

    unit_map = json.loads(unit_map_path.read_text(encoding="utf-8"))
    units = {row["symbol"]: row for row in unit_map["mappings"]}
    assert units["J"]["status"] == "candidate"
    assert units["J"]["unit_iri"].endswith("#Joule")
    assert units["V"]["unit_iri"].endswith("#Volt")
    assert units["kg"]["unit_iri"].endswith("#Kilogram")

    report = report_path.read_text(encoding="utf-8")
    assert "Quantitative Property Mapping Candidate Report" in report
    assert "`energy`" in report



