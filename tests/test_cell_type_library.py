from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_build_cell_type_library_rdf_from_descriptor(tmp_path: Path) -> None:
    input_dir = tmp_path / "cell-type"
    output_jsonld_dir = tmp_path / "library-rdf" / "cell-type"
    aggregate_jsonld = tmp_path / "ontology" / "library" / "cell-type.jsonld"
    manifest_json = tmp_path / "library-rdf" / "cell-type.index.json"

    input_dir.mkdir(parents=True)
    descriptor = _load_json(ROOT / "examples" / "cell-type" / "examples" / "minimal.example.json")
    (input_dir / "minimal.json").write_text(json.dumps(descriptor, indent=2) + "\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / ".tools" / "build" / "build_cell_type_library_rdf.py"),
            "--input-dir",
            str(input_dir),
            "--output-jsonld-dir",
            str(output_jsonld_dir),
            "--aggregate-jsonld",
            str(aggregate_jsonld),
            "--manifest-json",
            str(manifest_json),
            "--clean-output",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    record_jsonld = _load_json(output_jsonld_dir / "minimal.jsonld")
    aggregate_payload = _load_json(aggregate_jsonld)
    manifest_payload = _load_json(manifest_json)

    expected_id = descriptor["product"]["id"]
    expected_manufacturer = descriptor["product"]["manufacturer"]["name"]
    expected_model = descriptor["product"]["model"]

    assert "@graph" in record_jsonld
    assert record_jsonld["@graph"][0]["@id"] == expected_id

    assert aggregate_payload["@graph"]
    assert aggregate_payload["@graph"][0]["@id"] == expected_id

    assert manifest_payload["entry_count"] == 1
    assert manifest_payload["entries"][0]["id"] == expected_id
    assert manifest_payload["entries"][0]["manufacturer"] == expected_manufacturer
    assert manifest_payload["entries"][0]["model"] == expected_model




