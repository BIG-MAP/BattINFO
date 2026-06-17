from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from battinfo.ingest import inspect_ingest_root, write_ingest_manifest

ROOT = Path(__file__).resolve().parents[1]


def _schema_registry(schema_root: Path) -> Registry:
    registry = Registry()
    for path in sorted(schema_root.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        schema_id = doc.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, Resource.from_contents(doc))
    return registry


def _make_ingest_root(tmp_path: Path) -> Path:
    ingest_root = tmp_path / "google--g20m7--2025--15qnrp"
    (ingest_root / "image" / "photo").mkdir(parents=True)
    (ingest_root / "timeseries" / "raw").mkdir(parents=True)
    return ingest_root


def test_ingest_manifest_schema_files_are_synced_between_assets_and_package() -> None:
    assets_path = ROOT / "assets" / "schemas" / "ingest-manifest.schema.json"
    package_path = ROOT / "src" / "battinfo" / "data" / "schemas" / "ingest-manifest.schema.json"

    assert package_path.exists(), f"Missing packaged schema copy: {package_path}"

    assets_doc = json.loads(assets_path.read_text(encoding="utf-8"))
    package_doc = json.loads(package_path.read_text(encoding="utf-8"))
    assert assets_doc == package_doc, "Schema drift detected for ingest-manifest.schema.json"


def test_written_ingest_manifest_validates_against_normative_schema(tmp_path: Path) -> None:
    ingest_root = _make_ingest_root(tmp_path)
    manifest_report = write_ingest_manifest(
        ingest_root,
        resource_type="cell-instance",
        type_record="battinfo-records/records/cell-spec/google--g20m7--2025/record.json",
        resource_iri="https://w3id.org/battinfo/cell/15qn-rpd4-xhy7-kx2q",
        publisher_id="demo-lab",
        license="CC-BY-4.0",
    )

    schema_root = ROOT / "src" / "battinfo" / "data" / "schemas"
    schema_doc = json.loads((schema_root / "ingest-manifest.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema_doc, registry=_schema_registry(schema_root))

    manifest_doc = json.loads(Path(manifest_report["manifest_path"]).read_text(encoding="utf-8"))
    errors = sorted(validator.iter_errors(manifest_doc), key=lambda err: list(err.path))
    assert not errors, errors[0].message if errors else "unexpected validation error"


def test_inspect_ingest_root_rejects_manifest_outside_contract(tmp_path: Path) -> None:
    ingest_root = _make_ingest_root(tmp_path)
    manifest_path = ingest_root / "battinfo.ingest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "resource_type": "cell-instance",
                "cell_spec": "battinfo-records/records/cell-spec/google--g20m7--2025/record.json"
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid ingest manifest"):
        inspect_ingest_root(ingest_root)
