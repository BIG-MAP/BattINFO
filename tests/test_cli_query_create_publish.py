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


def test_validate_defaults_to_battery_descriptor_profile() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            str(ROOT / "assets" / "examples" / "battery-descriptors" / "minimal.example.json"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "Validation passed." in result.stdout


def test_validate_json_output_success() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            str(ROOT / "assets" / "examples" / "battery-descriptors" / "minimal.example.json"),
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["mode"] == "profile"
    assert payload["profile"] == "battery-descriptor"
    assert payload["issue_count"] == 0


def test_validate_can_run_canonical_record_validation_with_source_root() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "validate",
            str(ROOT / "assets" / "examples" / "datasets" / "dataset-1f8r-6v2k-9p4m-3t7x.json"),
            "--source-root",
            str(ROOT / "assets" / "examples"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "Validation passed." in result.stdout


def test_validate_json_output_includes_warnings_on_success() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        warn_path = Path("warn-test.json")
        source = json.loads(
            (ROOT / "assets" / "examples" / "tests" / "test-5p7v-2n8k-4m3t-6q9r.json").read_text(encoding="utf-8")
        )
        source["test"]["short_id"] = "xxxxxx"
        warn_path.write_text(json.dumps(source, indent=2), encoding="utf-8")
        result = runner.invoke(
            app,
            [
                "validate",
                str(warn_path),
                "--source-root",
                str(ROOT / "assets" / "examples"),
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
            (ROOT / "assets" / "examples" / "tests" / "test-5p7v-2n8k-4m3t-6q9r.json").read_text(encoding="utf-8")
        )
        source["test"]["short_id"] = "xxxxxx"
        bad_path.write_text(json.dumps(source, indent=2), encoding="utf-8")
        result = runner.invoke(
            app,
            [
                "validate",
                str(bad_path),
                "--source-root",
                str(ROOT / "assets" / "examples"),
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
            (ROOT / "assets" / "examples" / "tests" / "test-5p7v-2n8k-4m3t-6q9r.json").read_text(encoding="utf-8")
        )
        source["test"]["short_id"] = "xxxxxx"
        bad_path.write_text(json.dumps(source, indent=2), encoding="utf-8")
        result = runner.invoke(
            app,
            [
                "validate",
                str(bad_path),
                "--source-root",
                str(ROOT / "assets" / "examples"),
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


def test_register_record_strict_policy_fails_on_semantic_issue(tmp_path: Path) -> None:
    runner = CliRunner()
    bad_path = tmp_path / "bad-test.json"
    source = json.loads(
        (ROOT / "assets" / "examples" / "tests" / "test-5p7v-2n8k-4m3t-6q9r.json").read_text(encoding="utf-8")
    )
    source["test"]["short_id"] = "xxxxxx"
    bad_path.write_text(json.dumps(source, indent=2), encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "register",
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
    project_dir = tmp_path / "descriptor-project"

    result = runner.invoke(app, ["init", str(project_dir)])
    assert result.exit_code == 0, result.stdout

    scaffold_path = project_dir / "battinfo.json"
    assert scaffold_path.exists()
    scaffold = json.loads(scaffold_path.read_text(encoding="utf-8"))
    assert scaffold["schema_version"] == "1.0.0"
    assert scaffold["specification"]["id"] == "https://w3id.org/battinfo/cell-type/0000-0000-0000-0000"
    assert scaffold["specification"]["manufacturer"] == "ExampleManufacturer"


def test_map_descriptor_example_to_domain_battery_jsonld(tmp_path: Path) -> None:
    runner = CliRunner()
    out_path = tmp_path / "minimal.domain-battery.jsonld"

    result = runner.invoke(
        app,
        [
            "map",
            str(ROOT / "assets" / "examples" / "battery-descriptors" / "minimal.example.json"),
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
    assert "BatteryCell" in battery["@type"]
    assert "CylindricalBattery" in battery["@type"]
    assert "LithiumIonBattery" in battery["@type"]
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
            str(ROOT / "assets" / "examples" / "cell-types"),
            "--source-dir",
            str(ROOT / "assets" / "examples" / "cell-instances"),
            "--source-dir",
            str(ROOT / "assets" / "examples" / "tests"),
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
    assert stats_payload["cell_type_count"] == build_payload["cell_type_count"]
    assert stats_payload["cell_instance_count"] == build_payload["cell_instance_count"]
    assert stats_payload["test_count"] == build_payload["test_count"]
    assert stats_payload["dataset_count"] == build_payload["dataset_count"]


def test_register_cli_flow_json(tmp_path: Path) -> None:
    runner = CliRunner()
    source_root = tmp_path / "examples"

    reg_type = runner.invoke(
        app,
        [
            "register",
            "cell-type",
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
    type_id = type_payload["id"]

    reg_cell = runner.invoke(
        app,
        [
            "register",
            "cell-instance",
            "--type-id",
            type_id,
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
            "register",
            "test",
            "--cell-id",
            cell_payload["id"],
            "--name",
            "MN1500 CLI baseline cycling",
            "--kind",
            "cycle_life",
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
            "register",
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


def test_register_batch_cli_json(tmp_path: Path) -> None:
    runner = CliRunner()
    source_root = tmp_path / "examples"
    batch_root = tmp_path / "batch"
    cell_types_dir = batch_root / "cell-types"
    cell_instances_dir = batch_root / "cell-instances"
    tests_dir = batch_root / "tests"
    datasets_dir = batch_root / "datasets"
    cell_types_dir.mkdir(parents=True)
    cell_instances_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    datasets_dir.mkdir(parents=True)

    type_uid = "3m6k9t2p7x4h9nq8"
    type_iri = "https://w3id.org/battinfo/cell-type/3m6k-9t2p-7x4h-9nq8"
    cell_uid = "1f8r6v2k9p4m3t7x"
    cell_iri = "https://w3id.org/battinfo/cell/1f8r-6v2k-9p4m-3t7x"
    test_iri = "https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r"
    dataset_uid = "8c1h8pk68034vav6"

    t_type = runner.invoke(
        app,
        [
            "template",
            "cell-type",
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
            str(cell_types_dir / "cell-type.json"),
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
            "--type-id",
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
            "cycle_life",
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
            "register",
            "batch",
            "--source-dir",
            str(cell_types_dir),
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
            "register",
            "batch",
            "--source-dir",
            str(cell_types_dir),
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


def test_template_cli_then_register_record(tmp_path: Path) -> None:
    runner = CliRunner()
    source_root = tmp_path / "examples"
    cell_type_path = tmp_path / "cell-type.template.json"
    cell_instance_path = tmp_path / "cell-instance.template.json"
    dataset_path = tmp_path / "dataset.template.json"
    test_path = tmp_path / "test.template.json"

    t_type = runner.invoke(
        app,
        [
            "template",
            "cell-type",
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
            str(cell_type_path),
            "--format",
            "json",
        ],
    )
    assert t_type.exit_code == 0, t_type.stdout
    assert cell_type_path.exists()

    reg_type = runner.invoke(
        app,
        [
            "register",
            "record",
            "--input",
            str(cell_type_path),
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
            "--type-id",
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
            "register",
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
            "cycle_life",
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
            "register",
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
            "register",
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


def test_library_cli_template_register_query_build_rdf(tmp_path: Path) -> None:
    runner = CliRunner()
    template_path = tmp_path / "A123__ANR26650M1-B.json"
    library_root = tmp_path / "library" / "cell-types"
    packaged_root = tmp_path / "package" / "cell-types"
    rdf_root = tmp_path / "library-rdf" / "cell-types"
    aggregate_jsonld = tmp_path / "ontology" / "library" / "cell-types.jsonld"
    manifest_json = tmp_path / "library-rdf" / "cell-types.index.json"

    template_result = runner.invoke(
        app,
        [
            "library",
            "template",
            "cell-type",
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

    register_result = runner.invoke(
        app,
        [
            "library",
            "register",
            "cell-type",
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
    assert register_result.exit_code == 0, register_result.stdout
    register_payload = json.loads(register_result.stdout)
    assert register_payload["status"] == "created"
    assert Path(register_payload["path"]).exists()
    assert Path(register_payload["package_path"]).exists()

    query_result = runner.invoke(
        app,
        [
            "library",
            "query",
            "cell-types",
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
    assert query_payload["resource"] == "library-cell-types"
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
