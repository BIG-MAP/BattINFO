from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import PublishResult
from battinfo.cli import app


def test_query_cell_specs_json() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "query",
            "cell-spec",
            "--manufacturer",
            "A123",
            "--chemistry",
            "Li-ion",
            "--limit",
            "5",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["resource"] == "cell-spec"
    assert payload["count"] >= 1


def test_query_tests_json() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "query",
            "tests",
            "--kind",
            "hppc",
            "--limit",
            "5",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["resource"] == "tests"
    assert payload["count"] >= 1
    assert all(item["kind"] == "hppc" for item in payload["items"])


def test_query_test_protocols_json() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "query",
            "test-protocol",
            "--kind",
            "cycling",
            "--limit",
            "5",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["resource"] == "test-protocol"
    assert payload["count"] >= 1
    assert all(item["kind"] == "cycling" for item in payload["items"])


def test_query_tests_by_cell_and_dataset_json() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "query",
            "tests",
            "--cell-id",
            "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8",
            "--dataset-id",
            "https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["resource"] == "tests"
    assert payload["count"] >= 1
    assert all(item["cell_id"] == "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8" for item in payload["items"])
    assert all("https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x" in item["dataset_ids"] for item in payload["items"])


def test_query_datasets_by_related_cell_and_test_json() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "query",
            "dataset",
            "--related-cell-id",
            "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8",
            "--related-test-id",
            "https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["resource"] == "dataset"
    assert payload["count"] >= 1
    assert all(
        "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8" in item["related_cell_ids"] for item in payload["items"]
    )
    assert all(
        "https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r" in item["related_test_ids"] for item in payload["items"]
    )


def test_publish_cell_spec_cli_json(monkeypatch) -> None:
    runner = CliRunner()

    monkeypatch.setattr(
        "battinfo.cli.publish_object",
        lambda *args, **kwargs: PublishResult(
            status="ok",
            destination="local",
            resource_type="cell_spec",
            canonical_id="cell-spec-001",
            canonical_iri="https://w3id.org/battinfo/cell/cell-spec-001",
            source_local_id="cell-spec-001",
            debug_paths={"canonical_record_path": "C:/tmp/cell-spec.json"},
        ),
    )

    result = runner.invoke(
        app,
        [
            "publish",
            "cell-spec",
            "--manufacturer",
            "Google",
            "--model",
            "G20M7",
            "--cell-format",
            "pouch",
            "--chemistry",
            "Li-ion",
            "--destination",
            "local",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["destination"] == "local"
    assert payload["canonical_id"] == "cell-spec-001"
    assert payload["resource_type"] == "cell_spec"


def test_publish_cell_spec_cli_accepts_input_file(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    input_path = tmp_path / "cell-spec.json"
    input_path.write_text(
        json.dumps(
            {
                "manufacturer": "Google",
                "model": "G20M7",
                "format": "pouch",
                "chemistry": "Li-ion",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "battinfo.cli.publish_object",
        lambda cell_spec, **kwargs: PublishResult(
            status="ok",
            destination=kwargs["destination"],
            resource_type="cell_spec",
            canonical_id="cell-spec-002",
            canonical_iri="https://w3id.org/battinfo/cell/cell-spec-002",
            page_url="https://battery-genome.org/registry/cell-spec/cell-spec-002",
            source_local_id="cell-spec-002",
            debug_paths={"canonical_record_path": "C:/tmp/cell-spec.json"},
        ),
    )

    result = runner.invoke(
        app,
        [
            "publish",
            "cell-spec",
            "--input",
            str(input_path),
            "--destination",
            "battery-genome",
            "--registry-url",
            "https://registry.example.org",
            "--api-key",
            "secret",
            "--platform-url",
            "https://battery-genome.org",
            "--workspace-id",
            "hello-world",
            "--publisher-id",
            "demo-lab",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["destination"] == "battery-genome"
    assert payload["page_url"] == "https://battery-genome.org/registry/cell-spec/cell-spec-002"


def test_save_record_with_resolve_references_defers_missing_targets(tmp_path: Path) -> None:
    runner = CliRunner()
    source_root = tmp_path / "examples"
    cell_instance_path = tmp_path / "cell-instance.json"
    cell_instance_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "cell_instance": {
                    "id": "https://w3id.org/battinfo/cell/1f8r-6v2k-9p4m-3t7x",
                    "cell_spec_id": "https://w3id.org/battinfo/spec/eysh-4h5s-k4bx-zkgg",
                    "short_id": "1f8r6v",
                },
                "provenance": {
                    "source_type": "measurement",
                    "retrieved_at": 1771804800,
                },
                "datasets": [
                    {
                        "id": "https://w3id.org/battinfo/dataset/87fr-c4vr-wfyh-21td",
                        "role": "raw",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "save",
            "record",
            "--input",
            str(cell_instance_path),
            "--source-root",
            str(source_root),
            "--resolve-references",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "created"


def test_validate_defaults_to_battery_descriptor_profile() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            str(ROOT / "examples" / "cell-spec" / "research" / "minimal.example.json"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "Validation passed." in result.stdout


def test_template_cell_spec_draft_json() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "template",
            "cell-spec-draft",
            "--manufacturer",
            "A123",
            "--model-name",
            "ANR26650M1-B",
            "--chemistry",
            "Li-ion",
            "--cell-format",
            "cylindrical",
            "--iec-code",
            "IFpR26650",
            "--country-of-origin",
            "United States",
            "--year",
            "2012",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["manufacturer"] == "A123"
    assert payload["model"] == "ANR26650M1-B"
    assert payload["iec_code"] == "IFpR26650"
    assert payload["country_of_origin"] == "United States"
    assert payload["year"] == 2012
    assert "cell_spec" not in payload


def test_template_cell_spec_draft_writes_file(tmp_path: Path) -> None:
    runner = CliRunner()
    out = tmp_path / "cell-spec.draft.json"
    result = runner.invoke(
        app,
        [
            "template",
            "cell-spec-draft",
            "--out",
            str(out),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "template"
    assert payload["resource"] == "cell-spec-draft"
    assert out.exists()
    draft = json.loads(out.read_text(encoding="utf-8"))
    assert draft["model"] == "MODEL-001"
    assert "cell_spec" not in draft


def test_template_test_protocol_json() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "template",
            "test-protocol",
            "--name",
            "1C Cycle Life at 25 C",
            "--kind",
            "cycling",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["test_spec"]["name"] == "1C Cycle Life at 25 C"
    assert payload["test_spec"]["kind"] == "cycling"


def test_save_test_protocol_and_test_with_protocol_id(tmp_path: Path) -> None:
    runner = CliRunner()
    source_root = tmp_path / "examples"

    cell_spec_path = tmp_path / "cell-spec.json"
    cell_spec_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "cell_spec": {
                    "id": "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
                    "short_id": "7d9k2m",
                    "identifier": "cell-spec:7d9k-2m4p-8t3x-6nq5",
                    "name": "A123 ANR26650M1-B",
                    "model": "ANR26650M1-B",
                    "manufacturer": {
                        "type": "Organization",
                        "name": "A123"
                    },
                    "cell_format": "cylindrical",
                    "chemistry": "Li-ion"
                },
                "properties": {},
                "provenance": {
                    "source_type": "datasheet",
                    "source_file": "A123__ANR26650M1-B.pdf",
                    "retrieved_at": 1773811200
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["save", "record", "--input", str(cell_spec_path), "--source-root", str(source_root), "--format", "json"],
    )
    assert result.exit_code == 0, result.stdout

    cell_result = runner.invoke(
        app,
        [
            "save",
            "cell-instance",
            "--cell-spec-id",
            "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
            "--uid",
            "3m6k9t2p7x4h9nq8",
            "--source-root",
            str(source_root),
            "--mode",
            "upsert",
            "--format",
            "json",
        ],
    )
    assert cell_result.exit_code == 0, cell_result.stdout
    cell_payload = json.loads(cell_result.stdout)

    protocol_result = runner.invoke(
        app,
        [
            "save",
            "test-protocol",
            "--name",
            "1C Cycle Life at 25 C",
            "--kind",
            "cycling",
            "--uid",
            "8r2m4v6k9p3t7n5x",
            "--source-root",
            str(source_root),
            "--mode",
            "upsert",
            "--format",
            "json",
        ],
    )
    assert protocol_result.exit_code == 0, protocol_result.stdout
    protocol_payload = json.loads(protocol_result.stdout)

    test_result = runner.invoke(
        app,
        [
            "save",
            "test",
            "--cell-id",
            cell_payload["id"],
            "--name",
            "A123 cycle life run",
            "--kind",
            "cycling",
            "--protocol-id",
            protocol_payload["id"],
            "--source-root",
            str(source_root),
            "--mode",
            "upsert",
            "--format",
            "json",
        ],
    )
    assert test_result.exit_code == 0, test_result.stdout
    test_payload = json.loads(test_result.stdout)
    assert test_payload["entity_type"] == "test"


def test_validate_json_output_success() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            str(ROOT / "examples" / "cell-spec" / "research" / "minimal.example.json"),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "profile"
    assert payload["profile"] == "cell-spec"
    assert payload["issue_count"] == 0


def test_validate_can_run_canonical_record_validation_with_source_root() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            str(ROOT / "examples" / "dataset" / "dataset-1f8r-6v2k-9p4m-3t7x.json"),
            "--source-root",
            str(ROOT / "examples"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "Validation passed." in result.stdout


def test_validate_json_output_includes_warnings_on_success() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        warn_path = Path("warn-test.json")
        source = json.loads(
            (ROOT / "examples" / "test" / "test-5p7v-2n8k-4m3t-6q9r.json").read_text(encoding="utf-8")
        )
        source["test"]["short_id"] = "xxxxxx"
        warn_path.write_text(json.dumps(source, indent=2), encoding="utf-8")
        result = runner.invoke(
            app,
            [
                "validate",
                str(warn_path),
                "--source-root",
                str(ROOT / "examples"),
                "--format",
                "json",
            ],
        )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "record"
    assert payload["warning_count"] >= 1
    assert any(issue["code"] == "semantic.short_id_mismatch" for issue in payload["issues"])


def test_validate_strict_policy_fails_on_semantic_issue() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        bad_path = Path("bad-test.json")
        source = json.loads(
            (ROOT / "examples" / "test" / "test-5p7v-2n8k-4m3t-6q9r.json").read_text(encoding="utf-8")
        )
        source["test"]["short_id"] = "xxxxxx"
        bad_path.write_text(json.dumps(source, indent=2), encoding="utf-8")
        result = runner.invoke(
            app,
            [
                "validate",
                str(bad_path),
                "--source-root",
                str(ROOT / "examples"),
                "--policy",
                "strict",
            ],
        )
    assert result.exit_code == 1, result.stdout
    assert "Validation failed." in result.stdout
    assert "short_id" in result.stdout


def test_validate_json_output_failure_has_structured_issue_metadata() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        bad_path = Path("bad-test.json")
        source = json.loads(
            (ROOT / "examples" / "test" / "test-5p7v-2n8k-4m3t-6q9r.json").read_text(encoding="utf-8")
        )
        source["test"]["short_id"] = "xxxxxx"
        bad_path.write_text(json.dumps(source, indent=2), encoding="utf-8")
        result = runner.invoke(
            app,
            [
                "validate",
                str(bad_path),
                "--source-root",
                str(ROOT / "examples"),
                "--policy",
                "strict",
                "--format",
                "json",
            ],
        )
    assert result.exit_code == 1, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error_count"] >= 1
    assert any(issue["code"] == "semantic.short_id_mismatch" for issue in payload["issues"])


def test_save_record_strict_policy_fails_on_semantic_issue(tmp_path: Path) -> None:
    runner = CliRunner()
    bad_path = tmp_path / "bad-test.json"
    source = json.loads(
        (ROOT / "examples" / "test" / "test-5p7v-2n8k-4m3t-6q9r.json").read_text(encoding="utf-8")
    )
    source["test"]["short_id"] = "xxxxxx"
    bad_path.write_text(json.dumps(source, indent=2), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "save",
            "record",
            "--input",
            str(bad_path),
            "--source-root",
            str(tmp_path / "examples"),
            "--no-resolve-references",
            "--validation-policy",
            "strict",
            "--dry-run",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 1, result.stdout
    assert "short_id" in result.stdout


def test_init_defaults_to_battery_descriptor_scaffold(tmp_path: Path) -> None:
    runner = CliRunner()
    workspace_dir = tmp_path / "descriptor-workspace"

    result = runner.invoke(app, ["init", str(workspace_dir)])
    assert result.exit_code == 0, result.stdout

    scaffold_path = workspace_dir / "battinfo.json"
    assert scaffold_path.exists()
    scaffold = json.loads(scaffold_path.read_text(encoding="utf-8"))
    assert scaffold["schema_version"] == "1.0.0"
    assert scaffold["cell_spec"]["id"] == "https://w3id.org/battinfo/spec/0000-0000-0000-0000"
    assert scaffold["cell_spec"]["manufacturer"]["name"] == "ExampleManufacturer"


def test_map_descriptor_example_to_domain_battery_jsonld(tmp_path: Path) -> None:
    runner = CliRunner()
    out_path = tmp_path / "minimal.domain-battery.jsonld"

    result = runner.invoke(
        app,
        [
            "map",
            str(ROOT / "examples" / "cell-spec" / "research" / "minimal.example.json"),
            "--target",
            "domain-battery",
            "--out",
            str(out_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert out_path.exists()

    mapped = json.loads(out_path.read_text(encoding="utf-8"))
    assert "@graph" in mapped
    battery = mapped["@graph"][0]
    battery_types = battery["@type"] if isinstance(battery["@type"], list) else [battery["@type"]]
    assert "BatteryCellSpecification" in battery_types
    assert "schema:CreativeWork" in battery_types
    physical_types = battery["isDescriptionFor"]["@type"]
    if isinstance(physical_types, str):
        physical_types = [physical_types]
    assert "BatteryCell" in physical_types
    assert "CylindricalBattery" in physical_types
    assert "LithiumIonBattery" in physical_types
    assert battery["schema:name"] == "A123 ANR26650M1-B"


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
            str(ROOT / "examples" / "cell-spec"),
            "--source-dir",
            str(ROOT / "examples" / "cell-instance"),
            "--source-dir",
            str(ROOT / "examples" / "test"),
            "--source-dir",
            str(ROOT / "examples" / "dataset"),
            "--target-root",
            str(tmp_path / "site"),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["processed"] >= 4
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
            str(ROOT / "examples"),
            "--out",
            str(index_path),
            "--format",
            "json",
        ],
    )
    assert build_result.exit_code == 0, build_result.stdout
    build_payload = json.loads(build_result.stdout)
    assert build_payload["status"] in {"ok", "partial"}
    assert build_payload["cell_spec_count"] >= 1
    assert build_payload["cell_instance_count"] >= 1
    assert build_payload["test_count"] >= 1
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
    assert stats_payload["cell_spec_count"] == build_payload["cell_spec_count"]
    assert stats_payload["cell_instance_count"] == build_payload["cell_instance_count"]
    assert stats_payload["test_count"] == build_payload["test_count"]
    assert stats_payload["dataset_count"] == build_payload["dataset_count"]


def test_save_cli_flow_json(tmp_path: Path) -> None:
    runner = CliRunner()
    source_root = tmp_path / "examples"

    reg_type = runner.invoke(
        app,
        [
            "save",
            "cell-spec",
            "--manufacturer",
            "Duracell",
            "--model-name",
            "MN1500",
            "--chemistry",
            "Zn-air",
            "--cell-format",
            "cylindrical",
            "--uid",
            "3m6k9t2p7x4h9nq8",
            "--source-file",
            "manual-mn1500.json",
            "--source-root",
            str(source_root),
            "--format",
            "json",
        ],
    )
    assert reg_type.exit_code == 0, reg_type.stdout
    type_payload = json.loads(reg_type.stdout)
    assert type_payload["status"] == "created"
    cell_spec_id = type_payload["id"]

    reg_cell = runner.invoke(
        app,
        [
            "save",
            "cell-instance",
            "--cell-spec-id",
            cell_spec_id,
            "--uid",
            "1f8r6v2k9p4m3t7x",
            "--serial-number",
            "LAB-CLI-001",
            "--source-type",
            "lab",
            "--source-root",
            str(source_root),
            "--format",
            "json",
        ],
    )
    assert reg_cell.exit_code == 0, reg_cell.stdout
    cell_payload = json.loads(reg_cell.stdout)
    assert cell_payload["status"] == "created"

    reg_test = runner.invoke(
        app,
        [
            "save",
            "test",
            "--cell-id",
            cell_payload["id"],
            "--name",
            "MN1500 CLI baseline cycling",
            "--kind",
            "cycling",
            "--source-type",
            "measurement",
            "--uid",
            "5p7v2n8k4m3t6q9r",
            "--source-root",
            str(source_root),
            "--format",
            "json",
        ],
    )
    assert reg_test.exit_code == 0, reg_test.stdout
    test_payload = json.loads(reg_test.stdout)
    assert test_payload["status"] == "created"

    reg_dataset = runner.invoke(
        app,
        [
            "save",
            "dataset",
            "--title",
            "MN1500 CLI Dataset",
            "--source-type",
            "measurement",
            "--uid",
            "8c1h8pk68034vav6",
            "--related-cell-id",
            cell_payload["id"],
            "--related-test-id",
            test_payload["id"],
            "--source-root",
            str(source_root),
            "--format",
            "json",
        ],
    )
    assert reg_dataset.exit_code == 0, reg_dataset.stdout
    dataset_payload = json.loads(reg_dataset.stdout)
    assert dataset_payload["status"] == "created"


def test_save_batch_cli_json(tmp_path: Path) -> None:
    runner = CliRunner()
    source_root = tmp_path / "examples"
    batch_root = tmp_path / "batch"
    cell_specs_dir = batch_root / "cell-spec"
    cell_instances_dir = batch_root / "cell-instance"
    tests_dir = batch_root / "test"
    datasets_dir = batch_root / "dataset"
    cell_specs_dir.mkdir(parents=True)
    cell_instances_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    datasets_dir.mkdir(parents=True)

    type_uid = "3m6k9t2p7x4h9nq8"
    type_iri = "https://w3id.org/battinfo/spec/3m6k-9t2p-7x4h-9nq8"
    cell_uid = "1f8r6v2k9p4m3t7x"
    cell_iri = "https://w3id.org/battinfo/cell/1f8r-6v2k-9p4m-3t7x"
    test_iri = "https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r"
    dataset_uid = "8c1h8pk68034vav6"

    t_type = runner.invoke(
        app,
        [
            "template",
            "cell-spec",
            "--manufacturer",
            "Duracell",
            "--model-name",
            "MN1500",
            "--chemistry",
            "Zn-air",
            "--cell-format",
            "cylindrical",
            "--uid",
            type_uid,
            "--out",
            str(cell_specs_dir / "cell-spec.json"),
            "--format",
            "json",
        ],
    )
    assert t_type.exit_code == 0, t_type.stdout

    t_cell = runner.invoke(
        app,
        [
            "template",
            "cell-instance",
            "--cell-spec-id",
            type_iri,
            "--source-type",
            "lab",
            "--uid",
            cell_uid,
            "--out",
            str(cell_instances_dir / "cell-instance.json"),
            "--format",
            "json",
        ],
    )
    assert t_cell.exit_code == 0, t_cell.stdout

    t_test = runner.invoke(
        app,
        [
            "template",
            "test",
            "--cell-id",
            cell_iri,
            "--name",
            "MN1500 Batch baseline cycling",
            "--kind",
            "cycling",
            "--source-type",
            "measurement",
            "--uid",
            "5p7v2n8k4m3t6q9r",
            "--out",
            str(tests_dir / "test.json"),
            "--format",
            "json",
        ],
    )
    assert t_test.exit_code == 0, t_test.stdout

    t_dataset = runner.invoke(
        app,
        [
            "template",
            "dataset",
            "--title",
            "MN1500 Batch Dataset",
            "--source-type",
            "measurement",
            "--uid",
            dataset_uid,
            "--related-cell-id",
            cell_iri,
            "--related-test-id",
            test_iri,
            "--out",
            str(datasets_dir / "dataset.json"),
            "--format",
            "json",
        ],
    )
    assert t_dataset.exit_code == 0, t_dataset.stdout

    reg_batch = runner.invoke(
        app,
        [
            "save",
            "batch",
            "--source-dir",
            str(cell_specs_dir),
            "--source-dir",
            str(cell_instances_dir),
            "--source-dir",
            str(tests_dir),
            "--source-dir",
            str(datasets_dir),
            "--source-root",
            str(source_root),
            "--resolve-references",
            "--format",
            "json",
        ],
    )
    assert reg_batch.exit_code == 0, reg_batch.stdout
    batch_payload = json.loads(reg_batch.stdout)
    assert batch_payload["status"] == "ok"
    assert batch_payload["processed"] == 4
    assert batch_payload["created"] == 4
    assert batch_payload["failed"] == 0

    reg_batch_again = runner.invoke(
        app,
        [
            "save",
            "batch",
            "--source-dir",
            str(cell_specs_dir),
            "--source-dir",
            str(cell_instances_dir),
            "--source-dir",
            str(tests_dir),
            "--source-dir",
            str(datasets_dir),
            "--source-root",
            str(source_root),
            "--resolve-references",
            "--duplicate-policy",
            "return_existing",
            "--format",
            "json",
        ],
    )
    assert reg_batch_again.exit_code == 0, reg_batch_again.stdout
    batch_payload_again = json.loads(reg_batch_again.stdout)
    assert batch_payload_again["exists"] == 4
    assert batch_payload_again["failed"] == 0


def test_template_cli_then_save_record(tmp_path: Path) -> None:
    runner = CliRunner()
    source_root = tmp_path / "examples"
    cell_spec_path = tmp_path / "cell-spec.template.json"
    cell_instance_path = tmp_path / "cell-instance.template.json"
    dataset_path = tmp_path / "dataset.template.json"
    test_path = tmp_path / "test.template.json"

    t_type = runner.invoke(
        app,
        [
            "template",
            "cell-spec",
            "--manufacturer",
            "Duracell",
            "--model-name",
            "MN1500",
            "--chemistry",
            "Zn-air",
            "--cell-format",
            "cylindrical",
            "--uid",
            "3m6k9t2p7x4h9nq8",
            "--out",
            str(cell_spec_path),
            "--format",
            "json",
        ],
    )
    assert t_type.exit_code == 0, t_type.stdout
    assert cell_spec_path.exists()

    reg_type = runner.invoke(
        app,
        [
            "save",
            "record",
            "--input",
            str(cell_spec_path),
            "--source-root",
            str(source_root),
            "--no-resolve-references",
            "--format",
            "json",
        ],
    )
    assert reg_type.exit_code == 0, reg_type.stdout
    type_payload = json.loads(reg_type.stdout)

    t_cell = runner.invoke(
        app,
        [
            "template",
            "cell-instance",
            "--cell-spec-id",
            type_payload["id"],
            "--source-type",
            "lab",
            "--uid",
            "1f8r6v2k9p4m3t7x",
            "--out",
            str(cell_instance_path),
            "--format",
            "json",
        ],
    )
    assert t_cell.exit_code == 0, t_cell.stdout
    assert cell_instance_path.exists()

    reg_cell = runner.invoke(
        app,
        [
            "save",
            "record",
            "--input",
            str(cell_instance_path),
            "--source-root",
            str(source_root),
            "--resolve-references",
            "--format",
            "json",
        ],
    )
    assert reg_cell.exit_code == 0, reg_cell.stdout
    cell_payload = json.loads(reg_cell.stdout)

    t_test = runner.invoke(
        app,
        [
            "template",
            "test",
            "--cell-id",
            cell_payload["id"],
            "--name",
            "MN1500 Template baseline cycling",
            "--kind",
            "cycling",
            "--uid",
            "5p7v2n8k4m3t6q9r",
            "--out",
            str(test_path),
            "--format",
            "json",
        ],
    )
    assert t_test.exit_code == 0, t_test.stdout
    assert test_path.exists()

    reg_test = runner.invoke(
        app,
        [
            "save",
            "record",
            "--input",
            str(test_path),
            "--source-root",
            str(source_root),
            "--resolve-references",
            "--format",
            "json",
        ],
    )
    assert reg_test.exit_code == 0, reg_test.stdout
    test_payload = json.loads(reg_test.stdout)

    t_dataset = runner.invoke(
        app,
        [
            "template",
            "dataset",
            "--title",
            "MN1500 Template Dataset",
            "--source-type",
            "measurement",
            "--uid",
            "8c1h8pk68034vav6",
            "--related-cell-id",
            cell_payload["id"],
            "--related-test-id",
            test_payload["id"],
            "--out",
            str(dataset_path),
            "--format",
            "json",
        ],
    )
    assert t_dataset.exit_code == 0, t_dataset.stdout
    assert dataset_path.exists()

    reg_dataset = runner.invoke(
        app,
        [
            "save",
            "record",
            "--input",
            str(dataset_path),
            "--source-root",
            str(source_root),
            "--resolve-references",
            "--format",
            "json",
        ],
    )
    assert reg_dataset.exit_code == 0, reg_dataset.stdout
    dataset_payload = json.loads(reg_dataset.stdout)
    assert dataset_payload["status"] == "created"


def test_library_cli_template_save_query_build_rdf(tmp_path: Path) -> None:
    runner = CliRunner()
    template_path = tmp_path / "A123__ANR26650M1-B.json"
    library_root = tmp_path / "library" / "cell-spec"
    packaged_root = tmp_path / "package" / "cell-spec"
    rdf_root = tmp_path / "library-rdf" / "cell-spec"
    aggregate_jsonld = tmp_path / "ontology" / "library" / "cell-spec.jsonld"
    manifest_json = tmp_path / "library-rdf" / "cell-spec.index.json"

    template_result = runner.invoke(
        app,
        [
            "library",
            "template",
            "cell-spec",
            "--manufacturer",
            "A123",
            "--model",
            "ANR26650M1-B",
            "--chemistry",
            "Li-ion",
            "--cell-format",
            "cylindrical",
            "--positive-electrode-basis",
            "LFP",
            "--negative-electrode-basis",
            "graphite",
            "--uid",
            "9qfb4wrnynwcayjw",
            "--out",
            str(template_path),
            "--format",
            "json",
        ],
    )
    assert template_result.exit_code == 0, template_result.stdout
    template_payload = json.loads(template_result.stdout)
    assert template_payload["status"] == "template"
    assert template_path.exists()

    template_doc = json.loads(template_path.read_text(encoding="utf-8"))
    template_doc["specification"]["property"] = {
        "nominal_capacity": {"typical_value": 2.5, "unit": "Ah"},
        "nominal_voltage": {"value": 3.3, "unit": "V"},
    }
    template_path.write_text(json.dumps(template_doc, indent=2) + "\n", encoding="utf-8")

    save_result = runner.invoke(
        app,
        [
            "library",
            "save",
            "cell-spec",
            "--input",
            str(template_path),
            "--library-dir",
            str(library_root),
            "--packaged-dir",
            str(packaged_root),
            "--format",
            "json",
        ],
    )
    assert save_result.exit_code == 0, save_result.stdout
    save_payload = json.loads(save_result.stdout)
    assert save_payload["status"] == "created"
    assert Path(save_payload["path"]).exists()
    assert Path(save_payload["package_path"]).exists()

    query_result = runner.invoke(
        app,
        [
            "library",
            "query",
            "cell-spec",
            "--manufacturer",
            "A123",
            "--library-dir",
            str(library_root),
            "--format",
            "json",
        ],
    )
    assert query_result.exit_code == 0, query_result.stdout
    query_payload = json.loads(query_result.stdout)
    assert query_payload["resource"] == "library-cell-spec"
    assert query_payload["count"] == 1
    assert query_payload["items"][0]["model"] == "ANR26650M1-B"

    build_result = runner.invoke(
        app,
        [
            "library",
            "build-rdf",
            "--input-dir",
            str(library_root),
            "--output-jsonld-dir",
            str(rdf_root),
            "--aggregate-jsonld",
            str(aggregate_jsonld),
            "--manifest-json",
            str(manifest_json),
            "--format",
            "json",
        ],
    )
    assert build_result.exit_code == 0, build_result.stdout
    build_payload = json.loads(build_result.stdout)
    assert build_payload["status"] == "ok"
    assert build_payload["entry_count"] == 1
    assert aggregate_jsonld.exists()
    assert manifest_json.exists()







