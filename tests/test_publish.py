from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

publish_module = importlib.import_module("battinfo._publish")
from battinfo import CellSpec, PublishResult, publish
from battinfo.api import publish_record, save_record


def _sample_cell_spec() -> CellSpec:
    return CellSpec(
        manufacturer="Google",
        model="G20M7",
        format="pouch",
        chemistry="Li-ion",
        size_code="P0000",
    )


def test_publish_cell_spec_local_writes_canonical_record(tmp_path: Path) -> None:
    result = publish(_sample_cell_spec(), destination="local", root=tmp_path / "publish-local", force=True)

    assert isinstance(result, PublishResult)
    assert result.status == "ok"
    assert result.destination == "local"
    assert result.resource_type == "cell_spec"
    assert result.canonical_id is not None
    assert result.canonical_iri == f"https://w3id.org/battinfo/spec/{result.canonical_id}"

    canonical_record_path = Path(result.debug_paths["canonical_record_path"])
    assert canonical_record_path.exists()
    payload = json.loads(canonical_record_path.read_text(encoding="utf-8"))
    assert payload["cell_spec"]["manufacturer"]["name"] == "Google"
    assert payload["cell_spec"]["model"] == "G20M7"


def test_publish_cell_spec_registry_builds_submission_and_returns_registry_url(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_submit(payload, *, registry_base_url, api_key, api_key_header="X-Battinfo-API-Key", timeout_sec=30.0):
        captured["payload"] = payload
        captured["registry_base_url"] = registry_base_url
        captured["api_key"] = api_key
        captured["api_key_header"] = api_key_header
        captured["timeout_sec"] = timeout_sec
        source_local_id = payload["resource"]["source_local_id"]
        return {
            "status": "ok",
            "response": {
                "canonical_id_map": {source_local_id: "registry-cell-spec-001"},
                "canonical_iri_map": {
                    source_local_id: "https://w3id.org/battinfo/cell/registry-cell-spec-001",
                },
            },
        }

    monkeypatch.setattr(publish_module, "submit_publication_package", _fake_submit)

    result = publish(
        _sample_cell_spec(),
        destination="registry",
        root=tmp_path / "publish-registry",
        force=True,
        registry_base_url="https://registry.example.org",
        api_key="secret",
        workspace_id="hello-world",
        publisher_id="demo-lab",
        source_version="2026-03-24",
    )

    assert isinstance(result, PublishResult)
    assert result.status == "ok"
    assert result.destination == "registry"
    assert result.canonical_id == "registry-cell-spec-001"
    assert result.canonical_iri == "https://w3id.org/battinfo/cell/registry-cell-spec-001"
    assert result.registry_resource_url == "https://registry.example.org/resources/cell-spec/registry-cell-spec-001"
    assert result.page_url is None
    assert result.workspace_id == "hello-world"
    assert result.publisher_id == "demo-lab"
    assert result.source_version == "2026-03-24"

    submission_path = Path(result.debug_paths["submission_package_path"])
    assert submission_path.exists()
    submission_payload = json.loads(submission_path.read_text(encoding="utf-8"))
    assert submission_payload["workspace_id"] == "hello-world"
    assert submission_payload["publisher_id"] == "demo-lab"
    assert "metadata" not in submission_payload["resource"]["semantic_payload"]
    assert "battinfo_records" in submission_payload["resource"]["semantic_payload"]

    captured_payload = captured["payload"]
    assert isinstance(captured_payload, dict)
    assert captured["registry_base_url"] == "https://registry.example.org"
    assert captured["api_key"] == "secret"
    assert captured_payload["resource"]["source_local_id"] == result.source_local_id


def test_publish_cell_spec_battery_genome_returns_page_url(tmp_path: Path, monkeypatch) -> None:
    def _fake_submit(payload, *, registry_base_url, api_key, api_key_header="X-Battinfo-API-Key", timeout_sec=30.0):
        source_local_id = payload["resource"]["source_local_id"]
        return {
            "status": "ok",
            "response": {
                "canonical_id_map": {source_local_id: "registry-cell-spec-002"},
                "canonical_iri_map": {
                    source_local_id: "https://w3id.org/battinfo/cell/registry-cell-spec-002",
                },
            },
        }

    monkeypatch.setattr(publish_module, "submit_publication_package", _fake_submit)

    result = publish(
        _sample_cell_spec(),
        destination="battery-genome",
        root=tmp_path / "publish-battery-genome",
        force=True,
        registry_base_url="https://registry.example.org",
        api_key="secret",
        platform_base_url="https://battery-genome.org",
        workspace_id="hello-world",
        publisher_id="demo-lab",
        source_version="2026-03-24",
    )

    assert result.destination == "battery-genome"
    assert result.canonical_id == "registry-cell-spec-002"
    assert result.registry_resource_url == "https://registry.example.org/resources/cell-spec/registry-cell-spec-002"
    assert result.page_url == "https://battery-genome.org/registry/cell-spec/registry-cell-spec-002"


def test_publish_preserves_legacy_publication_package_call_shape(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def _fake_legacy_publish(**kwargs):
        calls.append(dict(kwargs))
        return {"status": "ok", "kind": "legacy-publication-package"}

    monkeypatch.setattr(publish_module, "_legacy_publish", _fake_legacy_publish)

    result = publish(
        cell_spec="cell-spec",
        cell_instance="cell-instance",
        test="test",
        dataset="dataset",
    )

    assert result == {"status": "ok", "kind": "legacy-publication-package"}
    assert calls == [
        {
            "cell_spec": "cell-spec",
            "cell_instance": "cell-instance",
            "test": "test",
            "dataset": "dataset",
        }
    ]


def test_publish_requires_object_or_legacy_keywords() -> None:
    with pytest.raises(TypeError, match="requires a BattINFO object"):
        publish()


# ---------------------------------------------------------------------------
# publish_record() — low-level API
# ---------------------------------------------------------------------------

_EXAMPLE_CELL_TYPE = ROOT / "examples" / "cell-spec" / "A123__ANR26650M1-B.json"
_EXAMPLE_CELL_INSTANCE = ROOT / "examples" / "cell-instance" / "cell-3m6k-9t2p-7x4h-9nq8.json"
_EXAMPLE_DATASET = ROOT / "examples" / "dataset" / "dataset-1f8r-6v2k-9p4m-3t7x.json"
_EXAMPLE_TEST_PROTOCOL = ROOT / "examples" / "test-protocol" / "test-protocol-8r2m-4v6k-9p3t-7n5x.json"


def test_publish_record_cell_spec_writes_three_files(tmp_path: Path) -> None:
    result = publish_record(_EXAMPLE_CELL_TYPE, target_root=tmp_path)

    assert result["status"] == "published"
    assert result["entity_type"] == "cell-spec"
    files = result["files"]
    assert any(f.endswith("index.json") for f in files)
    assert any(f.endswith("index.jsonld") for f in files)
    assert any(f.endswith("index.html") for f in files)
    out_dir = Path(result["output_dir"])
    assert (out_dir / "index.json").exists()
    assert (out_dir / "index.jsonld").exists()
    assert (out_dir / "index.html").exists()


def test_publish_record_jsonld_is_valid_json_ld(tmp_path: Path) -> None:
    publish_record(_EXAMPLE_CELL_TYPE, target_root=tmp_path)
    jsonld_files = list(tmp_path.rglob("index.jsonld"))
    assert jsonld_files, "No index.jsonld produced"
    doc = json.loads(jsonld_files[0].read_text(encoding="utf-8"))
    assert "@context" in doc


def test_publish_record_cell_spec_is_battery_cell_specification(tmp_path: Path) -> None:
    publish_record(_EXAMPLE_CELL_TYPE, target_root=tmp_path)
    jsonld_files = list(tmp_path.rglob("index.jsonld"))
    doc = json.loads(jsonld_files[0].read_text(encoding="utf-8"))
    types = doc["@type"] if isinstance(doc["@type"], list) else [doc["@type"]]
    assert "BatteryCellSpecification" in types, "@type must include BatteryCellSpecification"
    assert "schema:CreativeWork" in types, "@type must include schema:CreativeWork for schema.org alignment"


def test_descriptor_instance_nodes_have_dual_type() -> None:
    """Cell instance nodes must carry both BatteryCell (EMMO) and schema:IndividualProduct (schema.org)."""
    from battinfo.transform.json_to_jsonld import _descriptor_instances_to_jsonld
    nodes = _descriptor_instances_to_jsonld([
        {"id": "https://w3id.org/battinfo/cell/test1", "name": "cell-1"},
    ])
    assert len(nodes) == 1
    types = nodes[0]["@type"]
    if isinstance(types, str):
        types = [types]
    assert "BatteryCell" in types, "BatteryCell (EMMO) must be in @type"
    assert "schema:IndividualProduct" in types, "schema:IndividualProduct (schema.org) must be in @type"


def test_publish_record_jsonld_has_no_value_reference(tmp_path: Path) -> None:
    """schema:valueReference must not appear in published JSON-LD (removed misuse)."""
    publish_record(_EXAMPLE_CELL_TYPE, target_root=tmp_path)
    jsonld_files = list(tmp_path.rglob("index.jsonld"))
    doc = json.loads(jsonld_files[0].read_text(encoding="utf-8"))
    raw = json.dumps(doc)
    assert "valueReference" not in raw, "schema:valueReference must not appear in published output"


def test_publish_record_skip_jsonld(tmp_path: Path) -> None:
    result = publish_record(_EXAMPLE_CELL_TYPE, target_root=tmp_path, build_jsonld=False)
    files = result["files"]
    assert any(f.endswith("index.json") for f in files)
    assert not any(f.endswith("index.jsonld") for f in files)


def test_publish_record_skip_html(tmp_path: Path) -> None:
    result = publish_record(_EXAMPLE_CELL_TYPE, target_root=tmp_path, build_html=False)
    files = result["files"]
    assert not any(f.endswith("index.html") for f in files)


def test_publish_record_returns_correct_uid(tmp_path: Path) -> None:
    doc = json.loads(_EXAMPLE_CELL_TYPE.read_text(encoding="utf-8"))
    result = publish_record(doc, target_root=tmp_path)
    assert result["uid"] == doc["cell_spec"]["id"].split("/")[-1]


def test_publish_record_dataset(tmp_path: Path) -> None:
    result = publish_record(_EXAMPLE_DATASET, target_root=tmp_path)
    assert result["status"] == "published"
    assert result["entity_type"] == "dataset"


def test_publish_record_test_protocol(tmp_path: Path) -> None:
    result = publish_record(_EXAMPLE_TEST_PROTOCOL, target_root=tmp_path)
    assert result["status"] == "published"
    assert result["entity_type"] == "test-protocol"


# ---------------------------------------------------------------------------
# save_record() — dry-run and duplicate handling
# ---------------------------------------------------------------------------

def test_save_record_dry_run_does_not_write(tmp_path: Path) -> None:
    doc = json.loads(_EXAMPLE_CELL_TYPE.read_text(encoding="utf-8"))
    result = save_record(doc, source_root=tmp_path / "src", dry_run=True)
    assert result["status"] == "dry-run"
    # Nothing written
    assert not any(tmp_path.rglob("*.json"))


def test_save_record_creates_file(tmp_path: Path) -> None:
    doc = json.loads(_EXAMPLE_CELL_TYPE.read_text(encoding="utf-8"))
    result = save_record(doc, source_root=tmp_path / "src")
    assert result["status"] == "created"
    assert Path(result["path"]).exists()


def test_save_record_duplicate_error_by_default(tmp_path: Path) -> None:
    doc = json.loads(_EXAMPLE_CELL_TYPE.read_text(encoding="utf-8"))
    save_record(doc, source_root=tmp_path / "src")
    with pytest.raises(ValueError, match="already exists"):
        save_record(doc, source_root=tmp_path / "src")


def test_save_record_upsert_mode_updates(tmp_path: Path) -> None:
    doc = json.loads(_EXAMPLE_CELL_TYPE.read_text(encoding="utf-8"))
    save_record(doc, source_root=tmp_path / "src")
    result = save_record(doc, source_root=tmp_path / "src", mode="upsert")
    assert result["status"] == "updated"


def test_save_record_duplicate_policy_return_existing(tmp_path: Path) -> None:
    doc = json.loads(_EXAMPLE_CELL_TYPE.read_text(encoding="utf-8"))
    save_record(doc, source_root=tmp_path / "src")
    result = save_record(doc, source_root=tmp_path / "src", duplicate_policy="return_existing")
    assert result["status"] == "exists"

