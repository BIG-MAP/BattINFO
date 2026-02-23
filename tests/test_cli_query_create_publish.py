from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.cli import app


def test_query_cell_types_json() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "query",
            "cell-types",
            "--manufacturer",
            "A123",
            "--chemistry",
            "LFP",
            "--limit",
            "5",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["resource"] == "cell-types"
    assert payload["count"] >= 1


def test_create_cell_instance_from_metadata_and_publish_record(tmp_path: Path) -> None:
    runner = CliRunner()
    out_cell = tmp_path / "cell-instance.json"

    create_result = runner.invoke(
        app,
        [
            "create",
            "cell-instance",
            "--model-name",
            "ANR26650M1-B",
            "--manufacturer",
            "A123",
            "--serial-number",
            "LAB-CLI-001",
            "--uid",
            "3m6k9t2p7x4h9nq8",
            "--out",
            str(out_cell),
            "--format",
            "json",
        ],
    )
    assert create_result.exit_code == 0, create_result.stdout
    created = json.loads(create_result.stdout)
    assert created["status"] == "created"
    assert out_cell.exists()

    publish_root = tmp_path / "site"
    publish_result = runner.invoke(
        app,
        [
            "publish",
            "record",
            "--input",
            str(out_cell),
            "--target-root",
            str(publish_root),
            "--format",
            "json",
        ],
    )
    assert publish_result.exit_code == 0, publish_result.stdout
    published = json.loads(publish_result.stdout)
    assert published["status"] == "published"
    assert (publish_root / "cell" / "3m6k-9t2p-7x4h-9nq8" / "index.json").exists()


def test_publish_batch_json(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "publish",
            "batch",
            "--source-dir",
            str(ROOT / "assets" / "examples" / "cell-types"),
            "--source-dir",
            str(ROOT / "assets" / "examples" / "cell-instances"),
            "--source-dir",
            str(ROOT / "assets" / "examples" / "datasets"),
            "--target-root",
            str(tmp_path / "site"),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["processed"] >= 3
    assert payload["processed"] == payload["published"] + payload["failed"]


def test_index_build_and_stats_json(tmp_path: Path) -> None:
    runner = CliRunner()
    index_path = tmp_path / ".battinfo" / "index.json"

    build_result = runner.invoke(
        app,
        [
            "index",
            "build",
            "--source-root",
            str(ROOT / "assets" / "examples"),
            "--out",
            str(index_path),
            "--format",
            "json",
        ],
    )
    assert build_result.exit_code == 0, build_result.stdout
    build_payload = json.loads(build_result.stdout)
    assert build_payload["status"] in {"ok", "partial"}
    assert build_payload["cell_type_count"] >= 1
    assert build_payload["cell_instance_count"] >= 1
    assert build_payload["dataset_count"] >= 1
    assert index_path.exists()

    stats_result = runner.invoke(
        app,
        [
            "index",
            "stats",
            "--index",
            str(index_path),
            "--format",
            "json",
        ],
    )
    assert stats_result.exit_code == 0, stats_result.stdout
    stats_payload = json.loads(stats_result.stdout)
    assert stats_payload["cell_type_count"] == build_payload["cell_type_count"]
    assert stats_payload["cell_instance_count"] == build_payload["cell_instance_count"]
    assert stats_payload["dataset_count"] == build_payload["dataset_count"]
