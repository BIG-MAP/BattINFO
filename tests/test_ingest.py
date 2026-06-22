from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.cli import app
from battinfo.ingest import build_ingest_workspace, inspect_ingest_root, publish_ingest_workspace, write_ingest_manifest

EXAMPLE_CELL_TYPE = ROOT / "examples" / "cell-spec" / "A123__ANR26650M1-B.json"


def _make_ingest_root(tmp_path: Path) -> Path:
    ingest_root = tmp_path / "google--g20m7--2025--15qnrp"
    photo_dir = ingest_root / "image" / "photo"
    raw_dir = ingest_root / "timeseries" / "raw"
    photo_dir.mkdir(parents=True)
    raw_dir.mkdir(parents=True)

    (photo_dir / "IMG_0001.jpg").write_bytes(b"fake-jpeg")
    (raw_dir / "sintef__google--g20m7--2025--15qnrp__2026-04-09__rate__25degC.csv").write_text(
        "time_s,voltage_v\n0,4.20\n1,4.18\n",
        encoding="utf-8",
    )
    (raw_dir / "sintef__google--g20m7--2025--15qnrp__2026-04-10__capacity__25degC.csv").write_text(
        "time_s,capacity_ah\n0,0.1\n1,0.2\n",
        encoding="utf-8",
    )
    return ingest_root


def test_inspect_ingest_root_detects_photo_and_csvs(tmp_path: Path) -> None:
    ingest_root = _make_ingest_root(tmp_path)
    payload = inspect_ingest_root(
        ingest_root,
        resource_type="cell-instance",
        type_record=EXAMPLE_CELL_TYPE,
        resource_iri="https://w3id.org/battinfo/cell/15qn-rpd4-xhy7-kx2q",
        license="CC-BY-4.0",
    )

    assert payload["status"] == "ok"
    assert payload["photo_count"] == 1
    assert payload["csv_count"] == 2
    assert payload["type_record"] == str(EXAMPLE_CELL_TYPE)
    assert payload["resource_iri"] == "https://w3id.org/battinfo/cell/15qn-rpd4-xhy7-kx2q"
    assert payload["datasets"][0]["title"] == "Instance photo"
    assert payload["tests"][1]["kind"] == "rate_capability"
    assert payload["tests"][2]["kind"] == "capacity_check"


def test_build_ingest_workspace_bundles_submission_with_preview_image(tmp_path: Path) -> None:
    ingest_root = _make_ingest_root(tmp_path)
    payload = build_ingest_workspace(
        ingest_root,
        resource_type="cell-instance",
        type_record=EXAMPLE_CELL_TYPE,
        resource_iri="https://w3id.org/battinfo/cell/15qn-rpd4-xhy7-kx2q",
        workspace_root=tmp_path / "workspace",
        workspace_id="google-g20m7-instance-demo",
        publisher_id="demo-lab",
        source_version="demo-2026-04-09",
        license="CC-BY-4.0",
        artifact_base_url="http://127.0.0.1:8040",
        clean=True,
        bundle=True,
    )

    assert payload["status"] == "ok"
    assert payload["counts"]["cells"] == 1
    assert payload["counts"]["tests"] == 3
    assert payload["counts"]["datasets"] == 3
    assert Path(payload["submission_package_path"]).exists()

    resources = payload["submission_package"]["resources"]
    cell_resource = next(item for item in resources if item["resource_type"] == "cell")
    preview_image = cell_resource["semantic_payload"]["preview"]["image"]["src"]
    assert preview_image.startswith("http://127.0.0.1:8040/")
    assert preview_image.endswith("/IMG_0001.jpg")
    dataset_relations = [
        relation for relation in cell_resource.get("related_resources", [])
        if relation.get("relationship") == "hasDataset" and relation.get("resource_type") == "dataset"
    ]
    assert len(dataset_relations) == 3, (
        f"expected all 3 datasets (1 photo + 2 CSV) in cell related_resources, got {len(dataset_relations)}"
    )


def test_build_ingest_workspace_keeps_unrecognized_kind_csvs_and_pairs_by_file(tmp_path: Path) -> None:
    """Every timeseries CSV yields its own dataset+test wired to its own file.

    Regression: the build loop zipped tests filtered to ``kind != "other"``
    against all timeseries datasets, so a CSV whose inferred kind was ``other``
    (e.g. ``eis``/``hppc``/``gitt``) was dropped from the bundle AND shifted the
    alignment, wiring the remaining tests' protocol/date onto the wrong files.
    """
    ingest_root = tmp_path / "lab--cellx--2026--abc123"
    photo_dir = ingest_root / "image" / "photo"
    raw_dir = ingest_root / "timeseries" / "raw"
    photo_dir.mkdir(parents=True)
    raw_dir.mkdir(parents=True)
    (photo_dir / "IMG_0001.jpg").write_bytes(b"fake-jpeg")
    for date, token in (("2026-04-01", "eis"), ("2026-04-02", "rate"), ("2026-04-03", "capacity")):
        (raw_dir / f"lab__cellx--2026--abc123__{date}__{token}__25degC.csv").write_text(
            "time_s,voltage_v\n0,4.20\n1,4.18\n",
            encoding="utf-8",
        )

    payload = build_ingest_workspace(
        ingest_root,
        resource_type="cell-instance",
        type_record=EXAMPLE_CELL_TYPE,
        workspace_root=tmp_path / "workspace",
        workspace_id="ingest-pairing-demo",
        publisher_id="demo-lab",
        source_version="demo-2026-04-01",
        artifact_base_url="http://127.0.0.1:8040",
        clean=True,
        bundle=True,
    )

    # All three CSVs survive (eis is no longer dropped): 3 timeseries tests,
    # and 4 datasets total (1 photo + 3 CSV).
    assert payload["counts"]["timeseries_tests"] == 3
    assert payload["counts"]["datasets"] == 4
    dataset_resources = [
        item for item in payload["submission_package"]["resources"] if item.get("resource_type") == "dataset"
    ]
    assert len(dataset_resources) == 4

    # The eis CSV infers to the "other" kind — the exact case the old zip-filter
    # dropped — yet it now contributes a surviving dataset above.
    eis_test = next(item for item in payload["inspection"]["tests"] if "__eis__" in item["source_file"])
    assert eis_test["kind"] == "other"


def test_write_ingest_manifest_supports_folder_only_followup_commands(tmp_path: Path) -> None:
    ingest_root = _make_ingest_root(tmp_path)
    manifest = write_ingest_manifest(
        ingest_root,
        resource_type="cell-instance",
        type_record=EXAMPLE_CELL_TYPE,
        resource_iri="https://w3id.org/battinfo/cell/15qn-rpd4-xhy7-kx2q",
        publisher_id="demo-lab",
        source_version="demo-2026-04-09",
        license="CC-BY-4.0",
    )

    assert manifest["status"] == "ok"
    inspect_payload = inspect_ingest_root(ingest_root)
    assert inspect_payload["type_record"] == str(EXAMPLE_CELL_TYPE)
    assert inspect_payload["publisher_id"] == "demo-lab"
    assert inspect_payload["license"] == "CC-BY-4.0"


def test_publish_ingest_workspace_submits_bundle_and_returns_cell_url(tmp_path: Path, monkeypatch) -> None:
    ingest_root = _make_ingest_root(tmp_path)
    captured: dict[str, object] = {}

    def _fake_submit(payload, **kwargs):
        captured["payload"] = payload
        mapping = {
            resource["source_local_id"]: f"{resource['resource_type']}-demo-{index:03d}"
            for index, resource in enumerate(payload["resources"], start=1)
        }
        return {
            "status": "ok",
            "response": {
                "canonical_id_map": mapping,
            },
        }

    monkeypatch.setattr("battinfo.ingest.submit_publication_package", _fake_submit)

    payload = publish_ingest_workspace(
        ingest_root,
        resource_type="cell-instance",
        type_record=EXAMPLE_CELL_TYPE,
        resource_iri="https://w3id.org/battinfo/cell/15qn-rpd4-xhy7-kx2q",
        workspace_root=tmp_path / "workspace",
        workspace_id="google-g20m7-instance-demo",
        publisher_id="demo-lab",
        source_version="demo-2026-04-09",
        license="CC-BY-4.0",
        artifact_base_url="http://127.0.0.1:8040",
        clean=True,
        registry_base_url="https://registry.example.org",
        api_key="secret",
        platform_base_url="https://www.battery-genome.org",
    )

    assert payload["status"] == "ok"
    assert payload["canonical_ids"]["cell"].startswith("cell-demo-")
    assert payload["registry"]["resource_url"] == (
        f"https://registry.example.org/resources/cell/{payload['canonical_ids']['cell']}"
    )
    assert payload["platform"]["url"] == (
        f"https://www.battery-genome.org/registry/cell/{payload['canonical_ids']['cell']}"
    )
    assert "payload" in captured


def test_publish_ingest_workspace_calls_artifact_uploader_and_sets_access_url(
    tmp_path: Path, monkeypatch
) -> None:
    """artifact_uploader receives (key, source_path) and its return value is set as access_url."""
    ingest_root = _make_ingest_root(tmp_path)
    upload_calls: list[tuple[str, Path]] = []

    def fake_uploader(key: str, source_path: Path) -> str:
        upload_calls.append((key, source_path))
        return f"https://cdn.example.org/{key}"

    def _fake_submit(payload, **kwargs):
        mapping = {
            resource["source_local_id"]: f"{resource['resource_type']}-demo-{index:03d}"
            for index, resource in enumerate(payload["resources"], start=1)
        }
        return {"status": "ok", "response": {"canonical_id_map": mapping}}

    monkeypatch.setattr("battinfo.ingest.submit_publication_package", _fake_submit)

    result = publish_ingest_workspace(
        ingest_root,
        resource_type="cell-instance",
        type_record=EXAMPLE_CELL_TYPE,
        resource_iri="https://w3id.org/battinfo/cell/15qn-rpd4-xhy7-kx2q",
        workspace_root=tmp_path / "workspace",
        workspace_id="google-g20m7-instance-demo",
        publisher_id="demo-lab",
        source_version="demo-2026-04-09",
        license="CC-BY-4.0",
        artifact_base_url="http://127.0.0.1:8040",
        clean=True,
        registry_base_url="https://registry.example.org",
        api_key="secret",
        artifact_uploader=fake_uploader,
    )

    assert result["status"] == "ok"
    # uploader was called once per distribution
    assert len(upload_calls) == 3, f"expected 3 upload calls (1 photo + 2 CSVs), got {len(upload_calls)}"
    # all keys look like "dataset/<short_id>/<filename>"
    for key, src in upload_calls:
        assert key.startswith("dataset/")
        assert src.exists(), f"source_path does not exist: {src}"
    # access_url was set on every distribution in the submitted payload
    # (check via the submission that was built; the monkeypatched submit returns ok)
    resources = result["build"]["submission_package"]["resources"]
    for resource in resources:
        for dist in resource.get("distributions", []):
            assert dist.get("access_url", "").startswith("https://cdn.example.org/"), (
                f"expected CDN access_url on distribution {dist.get('title')}, got {dist.get('access_url')!r}"
            )


def test_ingest_inspect_cli_emits_json(tmp_path: Path) -> None:
    runner = CliRunner()
    ingest_root = _make_ingest_root(tmp_path)
    result = runner.invoke(
        app,
        [
            "ingest",
            "inspect",
            str(ingest_root),
            "--resource-type",
            "cell-instance",
            "--type-record",
            str(EXAMPLE_CELL_TYPE),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["photo_count"] == 1
    assert payload["csv_count"] == 2


def test_ingest_publish_cli_uses_high_level_helper(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    ingest_root = _make_ingest_root(tmp_path)

    monkeypatch.setattr(
        "battinfo.cli.publish_ingest_workspace",
        lambda *args, **kwargs: {
            "status": "ok",
            "resource_type": "cell-instance",
            "build": {"workspace_root": str(tmp_path / "workspace")},
            "canonical_ids": {"cell": "cell-demo-001"},
            "registry": {"page_model_url": "https://registry.example.org/resources/cell/cell-demo-001/page-model"},
            "platform": {"url": "https://www.battery-genome.org/registry/cell/cell-demo-001"},
        },
    )

    result = runner.invoke(
        app,
        [
            "ingest",
            "publish",
            str(ingest_root),
            "--resource-type",
            "cell-instance",
            "--type-record",
            str(EXAMPLE_CELL_TYPE),
            "--registry-url",
            "https://registry.example.org",
            "--api-key",
            "secret",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["canonical_ids"]["cell"] == "cell-demo-001"


def test_ingest_init_cli_writes_manifest_for_fast_followup(tmp_path: Path) -> None:
    runner = CliRunner()
    ingest_root = _make_ingest_root(tmp_path)
    result = runner.invoke(
        app,
        [
            "ingest",
            "init",
            str(ingest_root),
            "--resource-type",
            "cell-instance",
            "--type-record",
            str(EXAMPLE_CELL_TYPE),
            "--resource-iri",
            "https://w3id.org/battinfo/cell/15qn-rpd4-xhy7-kx2q",
            "--publisher-id",
            "demo-lab",
            "--license",
            "CC-BY-4.0",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    manifest_path = Path(payload["manifest_path"])
    assert manifest_path.exists()

    inspect_result = runner.invoke(
        app,
        [
            "ingest",
            "inspect",
            str(ingest_root),
            "--format",
            "json",
        ],
    )
    assert inspect_result.exit_code == 0, inspect_result.stdout
    inspect_payload = json.loads(inspect_result.stdout)
    assert inspect_payload["type_record"] == str(EXAMPLE_CELL_TYPE)
    assert inspect_payload["license"] == "CC-BY-4.0"
