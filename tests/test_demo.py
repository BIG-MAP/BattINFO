from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.cli import app
from battinfo.demo import run_demo_pipeline, setup_demo_environment


class _FakeHeaders(dict):
    def get_content_charset(self) -> str:
        return "utf-8"


class _FakeResponse:
    def __init__(self, payload: object, *, url: str) -> None:
        self._payload = payload
        self._url = url
        self.headers = _FakeHeaders()

    def read(self) -> bytes:
        if isinstance(self._payload, bytes):
            return self._payload
        if isinstance(self._payload, str):
            return self._payload.encode("utf-8")
        return json.dumps(self._payload).encode("utf-8")

    def getcode(self) -> int:
        return 200

    def geturl(self) -> str:
        return self._url

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_setup_demo_environment_writes_submission_without_lightweight_metadata(tmp_path: Path) -> None:
    payload = setup_demo_environment(tmp_path / "demo", force=True)

    submission = payload["submission_package"]
    resources = {item["resource_type"]: item for item in submission["resources"]}
    assert Path(payload["submission_package_path"]).exists()
    assert Path(payload["workspace_root"]).exists()
    assert Path(payload["source_root"]).exists()
    assert "metadata" not in resources["cell"]["semantic_payload"]
    assert "metadata" not in resources["test"]["semantic_payload"]
    assert "metadata" not in resources["dataset"]["semantic_payload"]
    assert "battinfo_records" in resources["cell"]["semantic_payload"]
    assert resources["dataset"]["semantic_payload"]["battinfo_records"]["dataset"]["dataset"]["license"] == "CC-BY-4.0"


def test_run_demo_pipeline_publishes_and_checks_platform_page(tmp_path: Path, monkeypatch) -> None:
    response_payload = {
        "kind": "BattinfoSubmissionResult",
        "submission_mode": "bundle",
        "workspace_id": "hello-world",
        "publisher_id": "demo-lab",
        "title": "A123 hello world cycling dataset",
        "source_version": "1.0.0",
        "resource_count": 3,
        "created_count": 3,
        "resources": [],
        "canonical_id_map": {
            "hello-world:cell": "cell-demo-001",
            "hello-world:test": "test-demo-001",
            "hello-world:dataset": "dataset-demo-001",
        },
        "canonical_iri_map": {
            "hello-world:dataset": "https://w3id.org/battinfo/dataset/dataset-demo-001",
        },
    }

    def _fake_submit(request, timeout=30.0):
        return _FakeResponse(response_payload, url=request.full_url)

    def _fake_fetch(request, timeout=30.0):
        url = request.full_url
        if url.endswith("/resources/dataset/dataset-demo-001"):
            return _FakeResponse(
                {
                    "id": "resource-row",
                    "tenant_id": "digibatt",
                    "workspace_id": "hello-world",
                    "registry_resource_id": "resource-row",
                    "registry_version_id": "version-row",
                    "resource_type": "dataset",
                    "canonical_iri": "https://w3id.org/battinfo/dataset/dataset-demo-001",
                    "publisher_id": "demo-lab",
                    "source_local_id": "hello-world:dataset",
                    "source_version": "1.0.0",
                    "title": "A123 hello world cycling dataset",
                    "latest_version": 1,
                    "semantic_payload": {"@type": "Dataset", "metadata": {"license": "CC-BY-4.0"}},
                    "metadata": {"license": "CC-BY-4.0"},
                    "related_resources": [],
                    "distributions": [],
                    "artifact_locations": {},
                    "build_artifact_locations": {},
                    "published_at": "2026-03-24T00:00:00Z",
                },
                url=url,
            )
        if url.endswith("/resources/dataset/dataset-demo-001/page-model"):
            return _FakeResponse(
                {
                    "model_type": "publication-model",
                    "model_version": "1.0",
                    "resource_type": "dataset",
                    "resource_class": "Dataset",
                    "canonical_id": "dataset-demo-001",
                    "canonical_iri": "https://w3id.org/battinfo/dataset/dataset-demo-001",
                    "title": "A123 hello world cycling dataset",
                    "identity": {
                        "publisher_id": "demo-lab",
                        "source_local_id": "hello-world:dataset",
                        "source_version": "1.0.0",
                    },
                    "semantic_payload": {"@type": "Dataset", "metadata": {"license": "CC-BY-4.0"}},
                    "metadata": {"license": "CC-BY-4.0"},
                    "related_resources": [],
                    "distributions": [],
                    "artifacts": {},
                    "provenance": {},
                    "publication_intent": {"mode": "canonical-publication"},
                    "publication": {"status": "published", "version_number": 1},
                    "display": {"summary_fields": [], "metric_fields": []},
                },
                url=url,
            )
        if url.endswith("/registry/dataset/dataset-demo-001"):
            return _FakeResponse(
                "<html><body>A123 hello world cycling dataset dataset-demo-001</body></html>",
                url=url,
            )
        raise AssertionError(f"Unexpected URL requested: {url}")

    monkeypatch.setattr("battinfo.api.urlopen", _fake_submit)
    monkeypatch.setattr("battinfo.demo.urlopen", _fake_fetch)

    payload = run_demo_pipeline(
        tmp_path / "demo",
        registry_base_url="https://registry.example.org",
        api_key="secret",
        platform_base_url="https://www.battery-genome.org",
        force=True,
    )

    assert payload["verification_target"]["resource_type"] == "dataset"
    assert payload["verification_target"]["canonical_id"] == "dataset-demo-001"
    assert payload["registry"]["page_model"]["canonical_id"] == "dataset-demo-001"
    assert payload["platform"]["ok"] is True
    assert payload["platform"]["contains_title"] is True
    assert payload["platform"]["contains_canonical_id"] is True


def test_demo_verify_cli_emits_json(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.setattr(
        "battinfo.cli.run_demo_pipeline",
        lambda *args, **kwargs: {
            "status": "ok",
            "verification_target": {
                "resource_type": "dataset",
                "canonical_id": "dataset-demo-001",
            },
            "registry": {
                "page_model_url": "https://registry.example.org/resources/dataset/dataset-demo-001/page-model",
            },
            "platform": {
                "url": "https://www.battery-genome.org/registry/dataset/dataset-demo-001",
            },
        },
    )

    result = runner.invoke(
        app,
        [
            "demo",
            "verify",
            str(tmp_path / "demo"),
            "--registry-url",
            "https://registry.example.org",
            "--api-key",
            "secret",
            "--platform-url",
            "https://www.battery-genome.org",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["verification_target"]["canonical_id"] == "dataset-demo-001"
