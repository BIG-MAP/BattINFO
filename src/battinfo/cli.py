from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from battinfo._jsonio import write_json as _write_json_file
from battinfo.api import (
    CellInstanceInput,
    CellSpecificationInput,
    DatasetInput,
    TestInput,
    TestSpecInput,
)
from battinfo.api import (
    build_cell_spec_library_rdf as api_build_cell_spec_library_rdf,
)
from battinfo.api import (
    build_curated_cell_spec_submission as api_build_curated_cell_spec_submission,
)
from battinfo.api import (
    build_index as api_build_index,
)
from battinfo.api import (
    create_cell_instance as api_create_cell_instance,
)
from battinfo.api import (
    index_stats as api_index_stats,
)
from battinfo.api import (
    promote_staging_cell_spec as api_promote_staging_cell_spec,
)
from battinfo.api import (
    promote_staging_cell_specs as api_promote_staging_cell_specs,
)
from battinfo.api import (
    promote_staging_dataset as api_promote_staging_dataset,
)
from battinfo.api import (
    promote_staging_datasets as api_promote_staging_datasets,
)
from battinfo.api import (
    publish_batch as api_publish_batch,
)
from battinfo.api import (
    publish_curated_cell_spec as api_publish_curated_cell_spec,
)
from battinfo.api import (
    publish_record as api_publish_record,
)
from battinfo.api import (
    query_cell_instances as api_query_cell_instances,
)
from battinfo.api import (
    query_cell_specs as api_query_cell_specs,
)
from battinfo.api import (
    query_datasets as api_query_datasets,
)
from battinfo.api import (
    query_library_cell_specs as api_query_library_cell_specs,
)
from battinfo.api import (
    query_test_specs as api_query_test_specs,
)
from battinfo.api import (
    query_tests as api_query_tests,
)
from battinfo.api import (
    save_batch as api_save_batch,
)
from battinfo.api import (
    save_cell_instance as api_save_cell_instance,
)
from battinfo.api import (
    save_cell_spec as api_save_cell_spec,
)
from battinfo.api import (
    save_dataset as api_save_dataset,
)
from battinfo.api import (
    save_library_cell_spec as api_save_library_cell_spec,
)
from battinfo.api import (
    save_record as api_save_record,
)
from battinfo.api import (
    save_test as api_save_test,
)
from battinfo.api import (
    save_test_spec as api_save_test_spec,
)
from battinfo.api import (
    template_cell_instance as api_template_cell_instance,
)
from battinfo.api import (
    template_cell_spec as api_template_cell_spec,
)
from battinfo.api import (
    template_cell_spec_draft as api_template_cell_spec_draft,
)
from battinfo.api import (
    template_dataset as api_template_dataset,
)
from battinfo.api import (
    template_library_cell_spec as api_template_library_cell_spec,
)
from battinfo.api import (
    template_test as api_template_test,
)
from battinfo.api import (
    template_test_spec as api_template_test_spec,
)
from battinfo.api import (
    validate_staging_cell_spec as api_validate_staging_cell_spec,
)
from battinfo.api import (
    validate_staging_cell_specs as api_validate_staging_cell_specs,
)
from battinfo.api import (
    validate_staging_dataset as api_validate_staging_dataset,
)
from battinfo.api import (
    validate_staging_datasets as api_validate_staging_datasets,
)
from battinfo.bundle import CellSpecification
from battinfo.demo import run_demo_pipeline, setup_demo_environment
from battinfo.entities import ENTITY_KINDS
from battinfo.ingest import build_ingest_workspace, inspect_ingest_root, publish_ingest_workspace, write_ingest_manifest
from battinfo.local_workspace import LocalWorkspace
from battinfo.publish import publish as publish_object
from battinfo.runtime import recover_notebook_runtime
from battinfo.storage import build_uploader_from_env
from battinfo.validate import get_validation_policy
from battinfo.validate.pydantic import validate_json
from battinfo.validate.record import validate_record_report
from battinfo.workflows.map import run_mapping

app = typer.Typer(add_completion=False, no_args_is_help=True)
query_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Query BattINFO resources.")
create_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Create BattINFO resources.")
publish_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Publish BattINFO resolver artifacts.")
index_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Build and inspect BattINFO indexes.")
save_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Save canonical BattINFO resources locally.")
template_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Generate starter templates.")
library_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Manage reusable BattINFO library records.")
library_query_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Query reusable library records.")
library_save_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Save reusable BattINFO library records locally.")
library_template_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Generate reusable library templates.")
editorial_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Validate and promote battinfo-records style staging drafts.")
workspace_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Author BattINFO workspaces on disk.")
notebook_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Notebook runtime recovery helpers.")
demo_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Scaffold and verify end-to-end BattINFO demos.")
ingest_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Register typed resource instances from folder-based evidence.")
registry_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Manage registry tenants, workspaces, and publishers.")
dataset_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Contribute measurement datasets: init -> process -> publish.")
batch_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Scaffold and manage multi-cell batch contributions.")
config_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Manage user preferences (creator, license, community).")
specs_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Browse valid spec property names and their accepted units.")

app.add_typer(query_app, name="query")
app.add_typer(create_app, name="create")
app.add_typer(publish_app, name="publish")
app.add_typer(index_app, name="index")
app.add_typer(save_app, name="save")
app.add_typer(template_app, name="template")
app.add_typer(library_app, name="library")
app.add_typer(editorial_app, name="editorial")
app.add_typer(workspace_app, name="workspace")
app.add_typer(notebook_app, name="notebook")
app.add_typer(demo_app, name="demo")
app.add_typer(ingest_app, name="ingest")
app.add_typer(registry_app, name="registry")
app.add_typer(dataset_app, name="dataset")
app.add_typer(batch_app, name="batch")
app.add_typer(config_app, name="config")
app.add_typer(specs_app, name="properties")
library_app.add_typer(library_query_app, name="query")
library_app.add_typer(library_save_app, name="save")
library_app.add_typer(library_template_app, name="template")


def _emit_json(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False))


def _emit_table(items: list[dict[str, Any]], columns: list[str]) -> None:
    if not items:
        typer.echo("No results.")
        return
    headers = columns
    widths = [len(h) for h in headers]
    rows: list[list[str]] = []
    for item in items:
        row = [str(item.get(col, "")) for col in columns]
        rows.append(row)
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))
    header_line = " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers)))
    sep_line = "-+-".join("-" * widths[i] for i in range(len(headers)))
    typer.echo(header_line)
    typer.echo(sep_line)
    for row in rows:
        typer.echo(" | ".join(row[i].ljust(widths[i]) for i in range(len(headers))))


def _parse_optional_bool(raw: str | None, option_name: str) -> bool | None:
    if raw is None:
        return None
    val = raw.strip().lower()
    if val in {"true", "1", "yes"}:
        return True
    if val in {"false", "0", "no"}:
        return False
    raise typer.BadParameter(f"{option_name} must be one of: true, false")


def _check_output_format(output_format: str) -> str:
    fmt = output_format.lower().strip()
    if fmt not in {"json", "table"}:
        raise typer.BadParameter("--format must be 'json' or 'table'.")
    return fmt


def _check_validation_output_format(output_format: str) -> str:
    fmt = output_format.lower().strip()
    if fmt not in {"text", "json"}:
        raise typer.BadParameter("--format must be 'text' or 'json'.")
    return fmt


def _check_save_mode(mode: str) -> str:
    value = mode.lower().strip()
    if value not in {"create_only", "upsert"}:
        raise typer.BadParameter("--mode must be 'create_only' or 'upsert'.")
    return value


def _check_duplicate_policy(duplicate_policy: str) -> str:
    value = duplicate_policy.lower().strip()
    if value not in {"error", "return_existing"}:
        raise typer.BadParameter("--duplicate-policy must be 'error' or 'return_existing'.")
    return value


def _check_validation_policy(policy: str) -> str:
    try:
        resolved = get_validation_policy(policy)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    return resolved.name


def _check_workspace_output_format(output_format: str) -> str:
    fmt = output_format.lower().strip()
    if fmt not in {"json", "text"}:
        raise typer.BadParameter("--format must be 'json' or 'text'.")
    return fmt


def _render_notebook_recovery(payload: dict[str, Any]) -> None:
    typer.echo(f"Workspace root: {payload['workspace_root']}")
    typer.echo(f"Kernel processes found: {payload['kernel_process_count']}")
    typer.echo(f"Processes terminated: {payload['terminated_pid_count']}")
    typer.echo(f"Processes killed: {payload['killed_pid_count']}")
    typer.echo(f"Remaining processes: {payload['remaining_pid_count']}")
    if payload["cleared_runtime_paths"]:
        typer.echo("Cleared runtime state:")
        for path in payload["cleared_runtime_paths"]:
            typer.echo(f"- {path}")


def _load_cell_spec_input(path: Path) -> CellSpecification:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload.get("cell_spec"), dict):
        return CellSpecification.from_record(payload)
    return CellSpecification(**payload)


def _init_example_document(profile: str) -> dict[str, Any]:
    if profile == "cell-spec":
        return {
            "schema_version": "1.0.0",
            "cell_spec": {
                "id": "https://w3id.org/battinfo/spec/0000-0000-0000-0000",
                "name": "ExampleManufacturer MODEL-001",
                "manufacturer": {"type": "Organization", "name": "ExampleManufacturer"},
                "model": "MODEL-001",
                "cell_format": "unknown",
                "chemistry": "unknown",
                "positive_electrode_basis": "unknown",
                "negative_electrode_basis": "unknown",
            },
            "provenance": {"source_type": "manual"},
        }

    return {
        "battinfo_version": "0.1.0",
        "profile": profile,
        "record": {
            "id": "urn:uuid:example",
            "title": "Example battery record",
            "created_at": "2026-01-27T00:00:00Z",
        },
        "battery": {
            "id": "battery-001",
            "type": "cell",
            "chemistry": "LFP",
        },
    }


def _validation_issue_payload(issue: Any) -> dict[str, Any]:
    return {
        "code": issue.code,
        "severity": issue.severity,
        "path": issue.path,
        "message": issue.message,
        "hint": issue.hint,
        "validator": issue.validator,
        "resource_type": issue.resource_type,
        "profile": issue.profile,
    }


def _validation_result_payload(
    result: Any,
    *,
    profile: str | None,
    source_root: Path | None,
) -> dict[str, Any]:
    issues = [_validation_issue_payload(issue) for issue in result.issues]
    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")
    return {
        "ok": result.ok,
        "mode": "record" if source_root is not None else "profile",
        "policy": result.policy,
        "profile": None if source_root is not None else profile,
        "source_root": str(source_root) if source_root is not None else None,
        "issue_count": len(issues),
        "error_count": error_count,
        "warning_count": warning_count,
        "errors": result.errors,
        "issues": issues,
    }


def _render_validation_issue(issue: Any) -> str:
    location = f"{issue.path}: " if issue.path else ""
    return f"[{issue.code}] {location}{issue.message}"


def _safe_echo(text: str) -> None:
    """typer.echo with a fallback for terminals that cannot encode all Unicode characters."""
    import sys  # noqa: PLC0415
    try:
        typer.echo(text)
    except UnicodeEncodeError:
        enc = (getattr(sys.stdout, "encoding", None) or "ascii")
        safe = text.encode(enc, errors="replace").decode(enc, errors="replace")
        sys.stdout.write(safe + "\n")
        sys.stdout.flush()


_RECORD_TYPE_KEYS = frozenset(kind.record_key for kind in ENTITY_KINDS)


def _is_full_record(data: dict) -> bool:
    """Return True if *data* looks like a full BattINFO record (not a raw JSON Schema target)."""
    return bool(_RECORD_TYPE_KEYS & data.keys())


@app.command()
def validate(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    profile: str = typer.Option("cell-spec", help="JSON Schema profile (used only for raw JSON, not full records)."),
    policy: str = typer.Option("default", help="Validation policy: default|strict|publisher|ingest."),
    output_format: str = typer.Option("text", "--format", help="Output format: text|json."),
    source_root: Path | None = typer.Option(
        None,
        "--source-root",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Canonical source root for cross-reference validation.",
    ),
    shacl: bool = typer.Option(True, "--shacl/--no-shacl", help="Run SHACL shapes validation (cell-spec records only)."),
) -> None:
    """Validate a BattINFO record (JSON Schema + semantic + SHACL) or a raw JSON profile document."""
    data = json.loads(input_path.read_text(encoding="utf-8"))
    policy_name = _check_validation_policy(policy)
    fmt = _check_validation_output_format(output_format)

    if _is_full_record(data) or source_root is not None:
        # Full record validation: JSON Schema + semantic + SHACL + (optional) references.
        report = validate_record_report(data, source_root=source_root, policy=policy_name)
        if not shacl:
            # Strip any SHACL issues if disabled.
            from battinfo.validate.core import ValidationReport  # noqa: PLC0415
            report = ValidationReport(
                issues=tuple(i for i in report.issues if i.validator != "shacl"),
                policy=report.policy,
            )
        result = report.to_result()
    else:
        # Raw JSON Schema profile validation only (no semantic / SHACL).
        result = validate_json(data, profile=profile, policy=policy_name)

    if fmt == "json":
        _emit_json(_validation_result_payload(result, profile=profile, source_root=source_root))
        raise typer.Exit(code=0 if result.ok else 1)

    warnings = [issue for issue in result.issues if issue.severity == "warning"]
    if result.ok:
        typer.echo("Validation passed with warnings." if warnings else "Validation passed.")
        for issue in warnings:
            _safe_echo(f"- {_render_validation_issue(issue)}")
        raise typer.Exit(code=0)

    typer.echo("Validation failed.")
    for issue in result.issues:
        if issue.severity == "error":
            _safe_echo(f"- {_render_validation_issue(issue)}")
    if warnings:
        typer.echo("Warnings:")
        for issue in warnings:
            _safe_echo(f"- {_render_validation_issue(issue)}")
    raise typer.Exit(code=1)


@app.command()
def init(
    workspace_dir: Path = typer.Argument(...),
    profile: str = typer.Option("cell-spec", help="Profile to scaffold."),
) -> None:
    """Create a minimal workspace scaffold with an example JSON file."""
    workspace_dir.mkdir(parents=True, exist_ok=True)
    example_path = workspace_dir / "battinfo.json"
    if not example_path.exists():
        example_path.write_text(
            json.dumps(_init_example_document(profile), indent=2),
            encoding="utf-8",
        )
    typer.echo(f"Initialized {workspace_dir}")


@workspace_app.command("init")
def workspace_init(
    workspace_dir: Path = typer.Argument(...),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing non-empty workspace directory."),
    output_format: str = typer.Option("json", "--format", help="Output format: json|text."),
) -> None:
    """Initialize a disk-backed BattINFO workspace scaffold."""
    fmt = _check_workspace_output_format(output_format)
    try:
        workspace = LocalWorkspace.init(workspace_dir, force=force)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    payload = {
        "status": "initialized",
        "workspace_root": str(workspace.root),
        "manifest_path": str(workspace.manifest_path),
    }
    if fmt == "json":
        _emit_json(payload)
        return
    typer.echo(f"Initialized workspace at {workspace.root}")


@workspace_app.command("validate")
def workspace_validate(
    workspace_dir: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, readable=True),
    policy: str = typer.Option("strict", help="Validation policy: default|strict|publisher|ingest."),
    output_format: str = typer.Option("json", "--format", help="Output format: json|text."),
) -> None:
    """Validate a disk-backed BattINFO workspace and write dist/validation-report.json."""
    fmt = _check_workspace_output_format(output_format)
    policy_name = _check_validation_policy(policy)
    report = LocalWorkspace(workspace_dir).validate(policy=policy_name, write_report=True)

    if fmt == "json":
        _emit_json(report)
    else:
        typer.echo("Validation passed." if report["ok"] else "Validation failed.")
        typer.echo(f"Report: {Path(workspace_dir) / 'dist' / 'validation-report.json'}")
        typer.echo(f"Issues: {report['issue_count']}")
    raise typer.Exit(code=0 if report["ok"] else 1)


@workspace_app.command("bundle")
def workspace_bundle(
    workspace_dir: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, readable=True),
    policy: str = typer.Option("strict", help="Validation policy: default|strict|publisher|ingest."),
    output_format: str = typer.Option("json", "--format", help="Output format: json|text."),
) -> None:
    """Bundle a disk-backed BattINFO workspace into dist artifacts."""
    fmt = _check_workspace_output_format(output_format)
    policy_name = _check_validation_policy(policy)
    try:
        payload = LocalWorkspace(workspace_dir).bundle(policy=policy_name)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if fmt == "json":
        _emit_json(payload)
        return
    typer.echo(f"Bundled workspace at {workspace_dir}")
    typer.echo(f"Registry intake: {payload['registry_intake_path']}")


@demo_app.command("setup")
def demo_setup(
    root: Path = typer.Argument(Path(".battinfo/demo-e2e")),
    registry: str = typer.Option("digibatt/hello-world", help="Registry tenant/workspace slug."),
    publisher_id: str = typer.Option("demo-lab", help="Publisher id used for the generated submission package."),
    version: str = typer.Option("1.0.0", help="Release version and submission source_version."),
    force: bool = typer.Option(False, "--force", help="Replace the existing demo root before regenerating it."),
    output_format: str = typer.Option("json", "--format", help="Output format: json|text."),
) -> None:
    """Author a BattINFO demo environment from Python objects and write a submission package."""
    fmt = _check_workspace_output_format(output_format)
    try:
        payload = setup_demo_environment(
            root,
            registry=registry,
            publisher_id=publisher_id,
            version=version,
            force=force,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if fmt == "json":
        _emit_json(payload)
        return
    typer.echo(f"Demo root: {payload['demo_root']}")
    typer.echo(f"Workspace root: {payload['workspace_root']}")
    typer.echo(f"Submission package: {payload['submission_package_path']}")


@demo_app.command("verify")
def demo_verify(
    root: Path = typer.Argument(Path(".battinfo/demo-e2e")),
    registry_url: str = typer.Option(..., "--registry-url", help="Registry base URL, for example http://127.0.0.1:8000."),
    api_key: str = typer.Option(..., "--api-key", help="Registry submission API key."),
    platform_url: str | None = typer.Option(
        None,
        "--platform-url",
        help="Optional Battery Genome base URL, for example https://www.battery-genome.org.",
    ),
    registry: str = typer.Option("digibatt/hello-world", help="Registry tenant/workspace slug."),
    publisher_id: str = typer.Option("demo-lab", help="Publisher id used for the generated submission package."),
    version: str = typer.Option("1.0.0", help="Release version and submission source_version."),
    api_key_header: str = typer.Option("X-Battinfo-API-Key", "--api-key-header", help="Registry submission API key header."),
    timeout_sec: float = typer.Option(30.0, "--timeout-sec", help="Timeout window for registry and platform checks."),
    poll_interval_sec: float = typer.Option(1.0, "--poll-interval-sec", help="Polling interval while waiting for responses."),
    force: bool = typer.Option(False, "--force", help="Replace the existing demo root before regenerating it."),
    output_format: str = typer.Option("json", "--format", help="Output format: json|text."),
) -> None:
    """Run the BattINFO demo pipeline through registry publication and optional platform verification."""
    fmt = _check_workspace_output_format(output_format)
    try:
        payload = run_demo_pipeline(
            root,
            registry_base_url=registry_url,
            api_key=api_key,
            platform_base_url=platform_url,
            registry=registry,
            publisher_id=publisher_id,
            version=version,
            api_key_header=api_key_header,
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
            force=force,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if fmt == "json":
        _emit_json(payload)
        return
    target = payload["verification_target"]
    typer.echo(f"Published {target['resource_type']} {target['canonical_id']}")
    typer.echo(f"Registry page model: {payload['registry']['page_model_url']}")
    if payload["platform"] is not None:
        typer.echo(f"Battery Genome page: {payload['platform']['url']}")


@ingest_app.command("inspect")
def ingest_inspect(
    ingest_root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, readable=True),
    resource_type: str = typer.Option("cell-instance", "--resource-type", help="Typed ingest subject. Today: cell-instance."),
    type_record: Path | None = typer.Option(None, "--type-record", help="Curated type record path."),
    manifest: Path | None = typer.Option(None, "--manifest", help="Optional battinfo.ingest.json path."),
    resource_iri: str | None = typer.Option(None, "--resource-iri", help="Existing BattINFO resource IRI to preserve."),
    resource_name: str | None = typer.Option(None, "--resource-name", help="Human-facing instance label."),
    workspace_id: str | None = typer.Option(None, "--workspace-id", help="Workspace id used for bundling/publication."),
    publisher_id: str | None = typer.Option(None, "--publisher-id", help="Publisher id used for bundling/publication."),
    source_version: str | None = typer.Option(None, "--source-version", help="Submission source version."),
    license: str | None = typer.Option(None, "--license", help="Dataset license to apply."),
    output_format: str = typer.Option("json", "--format", help="Output format: json|text."),
) -> None:
    """Inspect one ingest folder and infer tests/datasets without writing any records."""
    fmt = _check_workspace_output_format(output_format)
    try:
        payload = inspect_ingest_root(
            ingest_root,
            manifest_path=manifest,
            resource_type=resource_type,
            type_record=type_record,
            resource_iri=resource_iri,
            resource_name=resource_name,
            workspace_id=workspace_id,
            publisher_id=publisher_id,
            source_version=source_version,
            license=license,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if fmt == "json":
        _emit_json(payload)
        return
    typer.echo(f"Ingest root: {payload['ingest_root']}")
    typer.echo(f"Resource type: {payload['resource_type']}")
    typer.echo(f"Type record: {payload['type_record']}")
    typer.echo(f"Resource name: {payload['resource_name']}")
    typer.echo(f"Photos: {payload['photo_count']}")
    typer.echo(f"CSV datasets: {payload['csv_count']}")
    typer.echo(f"Workspace id: {payload['workspace_id']}")


@ingest_app.command("init")
def ingest_init(
    ingest_root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, readable=True),
    resource_type: str = typer.Option("cell-instance", "--resource-type", help="Typed ingest subject. Today: cell-instance."),
    type_record: Path | None = typer.Option(None, "--type-record", help="Curated type record path."),
    manifest: Path | None = typer.Option(None, "--manifest", help="Where to write battinfo.ingest.json."),
    resource_iri: str | None = typer.Option(None, "--resource-iri", help="Existing BattINFO resource IRI to preserve."),
    resource_name: str | None = typer.Option(None, "--resource-name", help="Human-facing instance label."),
    workspace_id: str | None = typer.Option(None, "--workspace-id", help="Workspace id used for bundling/publication."),
    publisher_id: str | None = typer.Option(None, "--publisher-id", help="Publisher id used for bundling/publication."),
    source_version: str | None = typer.Option(None, "--source-version", help="Submission source version."),
    license: str | None = typer.Option(None, "--license", help="Dataset license to apply."),
    overwrite: bool = typer.Option(False, "--force", help="Overwrite an existing manifest."),
    output_format: str = typer.Option("json", "--format", help="Output format: json|text."),
) -> None:
    """Write battinfo.ingest.json so later build/publish commands only need the folder path."""
    fmt = _check_workspace_output_format(output_format)
    try:
        payload = write_ingest_manifest(
            ingest_root,
            manifest_path=manifest,
            resource_type=resource_type,
            type_record=type_record,
            resource_iri=resource_iri,
            resource_name=resource_name,
            workspace_id=workspace_id,
            publisher_id=publisher_id,
            source_version=source_version,
            license=license,
            overwrite=overwrite,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if fmt == "json":
        _emit_json(payload)
        return
    typer.echo(f"Manifest: {payload['manifest_path']}")
    typer.echo(f"Ingest root: {payload['ingest_root']}")


@ingest_app.command("build")
def ingest_build(
    ingest_root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, readable=True),
    resource_type: str = typer.Option("cell-instance", "--resource-type", help="Typed ingest subject. Today: cell-instance."),
    type_record: Path | None = typer.Option(None, "--type-record", help="Curated type record path."),
    manifest: Path | None = typer.Option(None, "--manifest", help="Optional battinfo.ingest.json path."),
    workspace_root: Path | None = typer.Option(None, "--workspace-root", help="Where to write the authored workspace."),
    resource_iri: str | None = typer.Option(None, "--resource-iri", help="Existing BattINFO resource IRI to preserve."),
    resource_name: str | None = typer.Option(None, "--resource-name", help="Human-facing instance label."),
    workspace_id: str | None = typer.Option(None, "--workspace-id", help="Workspace id used for bundling/publication."),
    tenant: str | None = typer.Option(None, "--tenant", help="Optional tenant id recorded in the workspace manifest."),
    publisher_id: str | None = typer.Option(None, "--publisher-id", help="Publisher id used for bundling/publication."),
    source_version: str | None = typer.Option(None, "--source-version", help="Submission source version."),
    license: str | None = typer.Option(None, "--license", help="Dataset license to apply."),
    artifact_base_url: str | None = typer.Option(None, "--artifact-base-url", help="Optional public base URL for packaged artifact files."),
    clean: bool = typer.Option(False, "--force", help="Replace the existing workspace root before regenerating it."),
    bundle: bool = typer.Option(True, "--bundle/--no-bundle", help="Also build the submission package after authoring the workspace."),
    validation_policy: str = typer.Option("strict", "--validation-policy", help="Validation policy: strict|set|quick."),
    output_format: str = typer.Option("json", "--format", help="Output format: json|text."),
) -> None:
    """Create the linked ingest workspace from one evidence folder."""
    fmt = _check_workspace_output_format(output_format)
    try:
        payload = build_ingest_workspace(
            ingest_root,
            resource_type=resource_type,
            type_record=type_record,
            manifest_path=manifest,
            resource_iri=resource_iri,
            resource_name=resource_name,
            workspace_root=workspace_root,
            workspace_id=workspace_id,
            tenant=tenant,
            publisher_id=publisher_id,
            source_version=source_version,
            license=license,
            artifact_base_url=artifact_base_url,
            clean=clean,
            validation_policy=validation_policy,
            bundle=bundle,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if fmt == "json":
        _emit_json(payload)
        return
    typer.echo(f"Resource type: {payload['resource_type']}")
    typer.echo(f"Workspace root: {payload['workspace_root']}")
    typer.echo(f"Cells: {payload['counts']['cells']}")
    typer.echo(f"Tests: {payload['counts']['tests']}")
    typer.echo(f"Datasets: {payload['counts']['datasets']}")
    if payload.get("submission_package_path") is not None:
        typer.echo(f"Submission package: {payload['submission_package_path']}")


@ingest_app.command("publish")
def ingest_publish(
    ingest_root: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, readable=True),
    registry_url: str | None = typer.Option(None, "--registry-url", help="Registry base URL. Env: BATTINFO_REGISTRY_URL."),
    api_key: str | None = typer.Option(None, "--api-key", help="Registry submission API key. Env: BATTINFO_API_KEY."),
    resource_type: str = typer.Option("cell-instance", "--resource-type", help="Typed ingest subject. Today: cell-instance."),
    type_record: Path | None = typer.Option(None, "--type-record", help="Curated type record path."),
    manifest: Path | None = typer.Option(None, "--manifest", help="Optional battinfo.ingest.json path."),
    workspace_root: Path | None = typer.Option(None, "--workspace-root", help="Where to write the authored workspace."),
    resource_iri: str | None = typer.Option(None, "--resource-iri", help="Existing BattINFO resource IRI to preserve."),
    resource_name: str | None = typer.Option(None, "--resource-name", help="Human-facing instance label."),
    workspace_id: str | None = typer.Option(None, "--workspace-id", help="Workspace id used for bundling/publication."),
    tenant: str | None = typer.Option(None, "--tenant", help="Optional tenant id recorded in the workspace manifest."),
    publisher_id: str | None = typer.Option(None, "--publisher-id", help="Publisher id used for publication."),
    source_version: str | None = typer.Option(None, "--source-version", help="Submission source version."),
    license: str | None = typer.Option(None, "--license", help="Dataset license to apply."),
    artifact_base_url: str | None = typer.Option(None, "--artifact-base-url", help="Public base URL for packaged artifact files. Env: BATTINFO_STORAGE_PUBLIC_BASE_URL."),
    platform_url: str | None = typer.Option(None, "--platform-url", help="Optional Battery Genome base URL."),
    api_key_header: str = typer.Option("X-Battinfo-API-Key", "--api-key-header", help="Registry API key header."),
    timeout_sec: float = typer.Option(300.0, "--timeout-sec", help="Registry submission timeout in seconds."),
    clean: bool = typer.Option(False, "--force", help="Replace the existing workspace root before regenerating it."),
    validation_policy: str = typer.Option("strict", "--validation-policy", help="Validation policy: strict|set|quick."),
    process_artifacts: bool = typer.Option(False, "--process-artifacts", help="Convert timeseries CSVs to BDF and generate static/interactive plots. Requires battinfo[processing]."),
    output_format: str = typer.Option("json", "--format", help="Output format: json|text."),
) -> None:
    """Build and publish one ingest workspace in a single command.

    Registry credentials and artifact storage are read from environment
    variables when not supplied as flags:

    \b
      BATTINFO_REGISTRY_URL          registry base URL
      BATTINFO_API_KEY               publisher API key
      BATTINFO_STORAGE_BUCKET        S3/R2 bucket name (enables artifact upload)
      BATTINFO_STORAGE_ENDPOINT_URL  S3-compatible endpoint (for R2, Minio, etc.)
      BATTINFO_STORAGE_ACCESS_KEY_ID
      BATTINFO_STORAGE_SECRET_ACCESS_KEY
      BATTINFO_STORAGE_PUBLIC_BASE_URL  public CDN base URL for artifact links
    """
    import os

    resolved_registry_url = registry_url or os.environ.get("BATTINFO_REGISTRY_URL", "").strip()
    if not resolved_registry_url:
        typer.echo("Registry URL is required. Pass --registry-url or set BATTINFO_REGISTRY_URL.")
        raise typer.Exit(code=1)

    resolved_api_key = api_key or os.environ.get("BATTINFO_API_KEY", "").strip()
    if not resolved_api_key:
        typer.echo("API key is required. Pass --api-key or set BATTINFO_API_KEY.")
        raise typer.Exit(code=1)

    # Resolve artifact_base_url from env if not passed
    resolved_artifact_base_url = artifact_base_url or os.environ.get("BATTINFO_STORAGE_PUBLIC_BASE_URL", "").strip() or None

    # Wire artifact uploader from env when storage is configured
    uploader = build_uploader_from_env()

    # Wire timeseries processor when --process-artifacts is set
    processor = None
    if process_artifacts:
        try:
            from battinfo.processing import process_timeseries_csv
            processor = process_timeseries_csv
        except ImportError:
            typer.echo(
                "Warning: --process-artifacts requires battinfo[processing]. "
                "Install with: pip install 'battinfo[processing]'"
            )

    fmt = _check_workspace_output_format(output_format)
    try:
        payload = publish_ingest_workspace(
            ingest_root,
            resource_type=resource_type,
            type_record=type_record,
            manifest_path=manifest,
            resource_iri=resource_iri,
            resource_name=resource_name,
            workspace_root=workspace_root,
            workspace_id=workspace_id,
            tenant=tenant,
            publisher_id=publisher_id,
            source_version=source_version,
            license=license,
            artifact_base_url=resolved_artifact_base_url,
            clean=clean,
            validation_policy=validation_policy,
            registry_base_url=resolved_registry_url,
            api_key=resolved_api_key,
            api_key_header=api_key_header,
            artifact_uploader=uploader,
            artifact_processor=processor,
            platform_base_url=platform_url,
            timeout_sec=timeout_sec,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if fmt == "json":
        _emit_json(payload)
        return
    typer.echo(f"Resource type: {payload['resource_type']}")
    typer.echo(f"Workspace root: {payload['build']['workspace_root']}")
    typer.echo(f"Primary canonical id: {payload['canonical_ids']['cell']}")
    if payload["registry"]["page_model_url"] is not None:
        typer.echo(f"Registry page model: {payload['registry']['page_model_url']}")
    if payload["platform"] is not None:
        typer.echo(f"Battery Genome page: {payload['platform']['url']}")


@notebook_app.command("recover")
def notebook_recover(
    workspace_root: Path = typer.Option(Path("."), "--workspace-root", file_okay=False, dir_okay=True, readable=True),
    venv_path: Path = typer.Option(Path(".venv"), "--venv-path", help="Relative or absolute venv root."),
    clear_local_runtime: bool = typer.Option(
        True,
        "--clear-local-runtime/--keep-local-runtime",
        help="Remove local .jupyter-runtime-test state after stopping kernels.",
    ),
    force_kill: bool = typer.Option(
        True,
        "--force-kill/--no-force-kill",
        help="Force-kill repo-local notebook kernels that do not exit after terminate().",
    ),
    output_format: str = typer.Option("json", "--format", help="Output format: json|text."),
) -> None:
    """Recover from a stuck VS Code notebook restart by stopping repo-local ipykernel processes."""
    fmt = _check_workspace_output_format(output_format)
    try:
        payload = recover_notebook_runtime(
            workspace_root=workspace_root,
            venv_path=venv_path,
            clear_local_runtime=clear_local_runtime,
            force_kill=force_kill,
        )
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if fmt == "json":
        _emit_json(payload)
        return
    _render_notebook_recovery(payload)


@app.command()
def map(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    target: str = typer.Option("batterypass", help="Mapping target ('domain-battery' or 'batterypass')."),
    out: Path = typer.Option(..., help="Output JSON-LD path."),
) -> None:
    """Map canonical JSON to JSON-LD for a target."""
    data = json.loads(input_path.read_text(encoding="utf-8"))
    try:
        mapped = run_mapping(data, target=target)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from exc

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(mapped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    typer.echo(f"Wrote JSON-LD mapping to {out}")


@template_app.command("cell-spec")
def template_cell_spec(
    manufacturer: str = typer.Option("ExampleManufacturer", help="Manufacturer name."),
    model_name: str = typer.Option("MODEL-001", "--model-name", help="Model name."),
    chemistry: str = typer.Option("unknown", help="Chemistry label."),
    cell_format: str = typer.Option("unknown", "--cell-format", help="Cell format."),
    country_of_origin: str | None = typer.Option(None, "--country-of-origin", help="Optional country of origin."),
    year: int | None = typer.Option(None, help="Optional model or release year."),
    uid: str | None = typer.Option("0000000000000000", help="Optional 16-char UID."),
    out: Path | None = typer.Option(None, help="Optional output JSON path."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Generate a starter template for a cell-spec record."""
    fmt = _check_output_format(output_format)
    try:
        record = api_template_cell_spec(
            manufacturer=manufacturer,
            model_name=model_name,
            chemistry=chemistry,
            format=cell_format,  # type: ignore[arg-type]
            country_of_origin=country_of_origin,
            year=year,
            uid=uid,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if out is not None:
        _write_json_file(out, record)
        payload = {
            "status": "template",
            "resource": "cell-spec",
            "id": record["cell_spec"]["id"],
            "path": str(out),
        }
        if fmt == "json":
            _emit_json(payload)
            return
        _emit_table([payload], ["status", "resource", "id", "path"])
        return

    if fmt == "json":
        _emit_json(record)
        return
    payload = {
        "status": "template",
        "resource": "cell-spec",
        "id": record["cell_spec"]["id"],
        "path": "",
    }
    _emit_table([payload], ["status", "resource", "id", "path"])


@template_app.command("cell-spec-draft")
def template_cell_spec_draft(
    manufacturer: str = typer.Option("ExampleManufacturer", help="Manufacturer name placeholder."),
    model_name: str = typer.Option("MODEL-001", "--model-name", help="Model name placeholder."),
    chemistry: str = typer.Option("unknown", help="Chemistry label placeholder."),
    cell_format: str = typer.Option("unknown", "--cell-format", help="Cell format placeholder."),
    size_code: str | None = typer.Option(None, help="Optional size code placeholder."),
    iec_code: str | None = typer.Option(None, help="Optional IEC code placeholder."),
    country_of_origin: str | None = typer.Option(None, "--country-of-origin", help="Optional country of origin placeholder."),
    year: int | None = typer.Option(None, help="Optional model or release year placeholder."),
    positive_electrode_basis: str | None = typer.Option(None, help="Optional positive electrode basis placeholder."),
    negative_electrode_basis: str | None = typer.Option(None, help="Optional negative electrode basis placeholder."),
    datasheet_revision: str | None = typer.Option(None, help="Optional datasheet revision placeholder."),
    out: Path | None = typer.Option(None, help="Optional output JSON path."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Generate a starter authoring draft for a hand-edited cell-spec JSON file."""
    fmt = _check_output_format(output_format)
    record = api_template_cell_spec_draft(
        manufacturer=manufacturer,
        model_name=model_name,
        chemistry=chemistry,
        format=cell_format,  # type: ignore[arg-type]
        size_code=size_code,
        iec_code=iec_code,
        country_of_origin=country_of_origin,
        year=year,
        positive_electrode_basis=positive_electrode_basis,
        negative_electrode_basis=negative_electrode_basis,
        datasheet_revision=datasheet_revision,
    )

    if out is not None:
        _write_json_file(out, record)
        payload = {
            "status": "template",
            "resource": "cell-spec-draft",
            "path": str(out),
        }
        if fmt == "json":
            _emit_json(payload)
            return
        _emit_table([payload], ["status", "resource", "path"])
        return

    if fmt == "json":
        _emit_json(record)
        return
    payload = {
        "status": "template",
        "resource": "cell-spec-draft",
        "path": "",
    }
    _emit_table([payload], ["status", "resource", "path"])


@template_app.command("cell-instance")
def template_cell_instance(
    cell_spec_id: str = typer.Option(
        "https://w3id.org/battinfo/spec/0000-0000-0000-0000",
        help="Canonical cell-spec IRI.",
    ),
    source_type: str = typer.Option("measurement", help="Source type: measurement|lab|bms|other."),
    uid: str | None = typer.Option("0000000000000000", help="Optional 16-char UID."),
    out: Path | None = typer.Option(None, help="Optional output JSON path."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Generate a starter template for a cell-instance record."""
    fmt = _check_output_format(output_format)
    try:
        record = api_template_cell_instance(
            cell_spec_id=cell_spec_id,
            source_type=source_type,  # type: ignore[arg-type]
            uid=uid,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if out is not None:
        _write_json_file(out, record)
        payload = {
            "status": "template",
            "resource": "cell-instance",
            "id": record["cell_instance"]["id"],
            "path": str(out),
        }
        if fmt == "json":
            _emit_json(payload)
            return
        _emit_table([payload], ["status", "resource", "id", "path"])
        return

    if fmt == "json":
        _emit_json(record)
        return
    payload = {
        "status": "template",
        "resource": "cell-instance",
        "id": record["cell_instance"]["id"],
        "path": "",
    }
    _emit_table([payload], ["status", "resource", "id", "path"])


@template_app.command("dataset")
def template_dataset(
    title: str = typer.Option("Example Dataset", help="Dataset title."),
    source_type: str = typer.Option("other", help="Source type: measurement|lab|simulation|external|other."),
    uid: str | None = typer.Option("0000000000000000", help="Optional 16-char UID."),
    related_cell_id: list[str] = typer.Option(
        ["https://w3id.org/battinfo/cell/0000-0000-0000-0000"],
        "--related-cell-id",
        help="Related cell IRI. Repeat for multiple.",
    ),
    related_test_id: list[str] = typer.Option([], "--related-test-id", help="Related test IRI. Repeat for multiple."),
    out: Path | None = typer.Option(None, help="Optional output JSON path."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Generate a starter template for a dataset record."""
    fmt = _check_output_format(output_format)
    try:
        record = api_template_dataset(
            title=title,
            source_type=source_type,  # type: ignore[arg-type]
            uid=uid,
            related_cell_ids=related_cell_id,
            related_test_ids=related_test_id,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if out is not None:
        _write_json_file(out, record)
        payload = {
            "status": "template",
            "resource": "dataset",
            "id": record["dataset"]["id"],
            "path": str(out),
        }
        if fmt == "json":
            _emit_json(payload)
            return
        _emit_table([payload], ["status", "resource", "id", "path"])
        return

    if fmt == "json":
        _emit_json(record)
        return
    payload = {
        "status": "template",
        "resource": "dataset",
        "id": record["dataset"]["id"],
        "path": "",
    }
    _emit_table([payload], ["status", "resource", "id", "path"])


@template_app.command("test-protocol")
def template_test_spec(
    name: str = typer.Option("Example Test Protocol", help="Human-readable protocol name."),
    kind: str = typer.Option("other", help="Test kind."),
    source_type: str = typer.Option("manual", help="Source type: manual|lab|simulation|other."),
    uid: str | None = typer.Option("0000000000000000", help="Optional 16-char UID."),
    out: Path | None = typer.Option(None, help="Optional output JSON path."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Generate a starter template for a reusable test-protocol record."""
    fmt = _check_output_format(output_format)
    try:
        record = api_template_test_spec(
            name=name,
            kind=kind,  # type: ignore[arg-type]
            source_type=source_type,  # type: ignore[arg-type]
            uid=uid,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if out is not None:
        _write_json_file(out, record)
        payload = {
            "status": "template",
            "resource": "test-protocol",
            "id": record["test_spec"]["id"],
            "path": str(out),
        }
        if fmt == "json":
            _emit_json(payload)
            return
        _emit_table([payload], ["status", "resource", "id", "path"])
        return

    if fmt == "json":
        _emit_json(record)
        return
    payload = {
        "status": "template",
        "resource": "test-protocol",
        "id": record["test_spec"]["id"],
        "path": "",
    }
    _emit_table([payload], ["status", "resource", "id", "path"])


@template_app.command("test")
def template_test(
    cell_id: str = typer.Option(
        "https://w3id.org/battinfo/cell/0000-0000-0000-0000",
        help="Canonical cell-instance IRI under test.",
    ),
    name: str = typer.Option("Example Test", help="Human-readable test name."),
    kind: str = typer.Option("other", help="Test kind."),
    source_type: str = typer.Option("measurement", help="Source type: measurement|lab|simulation|manual|other."),
    uid: str | None = typer.Option("0000000000000000", help="Optional 16-char UID."),
    dataset_id: list[str] = typer.Option([], "--dataset-id", help="Linked dataset IRI. Repeat for multiple."),
    out: Path | None = typer.Option(None, help="Optional output JSON path."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Generate a starter template for a test record."""
    fmt = _check_output_format(output_format)
    try:
        record = api_template_test(
            cell_id=cell_id,
            name=name,
            kind=kind,  # type: ignore[arg-type]
            source_type=source_type,  # type: ignore[arg-type]
            uid=uid,
            dataset_ids=dataset_id,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if out is not None:
        _write_json_file(out, record)
        payload = {
            "status": "template",
            "resource": "test",
            "id": record["test"]["id"],
            "path": str(out),
        }
        if fmt == "json":
            _emit_json(payload)
            return
        _emit_table([payload], ["status", "resource", "id", "path"])
        return

    if fmt == "json":
        _emit_json(record)
        return
    payload = {
        "status": "template",
        "resource": "test",
        "id": record["test"]["id"],
        "path": "",
    }
    _emit_table([payload], ["status", "resource", "id", "path"])


@library_template_app.command("cell-spec")
def library_template_cell_spec(
    manufacturer: str = typer.Option("ExampleManufacturer", help="Manufacturer name."),
    model: str = typer.Option("MODEL-001", help="Model name."),
    chemistry: str = typer.Option("unknown", help="Chemistry label."),
    cell_format: str = typer.Option("unknown", "--cell-format", help="Cell format."),
    positive_electrode_basis: str = typer.Option("unknown", help="Positive electrode basis."),
    negative_electrode_basis: str = typer.Option("unknown", help="Negative electrode basis."),
    uid: str | None = typer.Option("0000000000000000", help="Optional 16-char UID."),
    out: Path | None = typer.Option(None, help="Optional output JSON path."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Generate a starter reusable library cell-spec specification."""
    fmt = _check_output_format(output_format)
    try:
        record = api_template_library_cell_spec(
            manufacturer=manufacturer,
            model=model,
            chemistry=chemistry,
            format=cell_format,  # type: ignore[arg-type]
            positive_electrode_basis=positive_electrode_basis,
            negative_electrode_basis=negative_electrode_basis,
            uid=uid,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if out is not None:
        _write_json_file(out, record)
        payload = {
            "status": "template",
            "resource": "library-cell-spec",
            "id": record["specification"]["id"],
            "path": str(out),
        }
        if fmt == "json":
            _emit_json(payload)
            return
        _emit_table([payload], ["status", "resource", "id", "path"])
        return

    if fmt == "json":
        _emit_json(record)
        return
    payload = {
        "status": "template",
        "resource": "library-cell-spec",
        "id": record["specification"]["id"],
        "path": "",
    }
    _emit_table([payload], ["status", "resource", "id", "path"])


@library_query_app.command("cell-spec")
def library_query_cell_specs(
    id: str | None = typer.Option(None, help="Filter by reusable cell-spec IRI."),
    manufacturer: str | None = typer.Option(None, help="Filter by manufacturer."),
    model_contains: str | None = typer.Option(None, help="Filter by model substring."),
    chemistry: str | None = typer.Option(None, help="Filter by chemistry."),
    cell_format: str | None = typer.Option(None, "--cell-format", help="Filter by cell form factor."),
    size_code: str | None = typer.Option(None, help="Filter by size code."),
    positive_electrode_basis: str | None = typer.Option(None, help="Filter by positive electrode basis."),
    negative_electrode_basis: str | None = typer.Option(None, help="Filter by negative electrode basis."),
    nominal_capacity_min: float | None = typer.Option(None, help="Filter minimum nominal capacity."),
    nominal_capacity_max: float | None = typer.Option(None, help="Filter maximum nominal capacity."),
    nominal_voltage_min: float | None = typer.Option(None, help="Filter minimum nominal voltage."),
    nominal_voltage_max: float | None = typer.Option(None, help="Filter maximum nominal voltage."),
    library_dir: Path = typer.Option(Path(".battinfo/library/cell-spec"), help="Reusable library cell-specification directory."),
    limit: int = typer.Option(50, min=1, help="Maximum rows."),
    offset: int = typer.Option(0, min=0, help="Start offset."),
    output_format: str = typer.Option("table", "--format", help="Output format: table|json."),
) -> None:
    """Query reusable library cell-spec specifications."""
    fmt = _check_output_format(output_format)
    rows = api_query_library_cell_specs(
        id=id,
        manufacturer=manufacturer,
        model_contains=model_contains,
        chemistry=chemistry,
        format=cell_format,
        size_code=size_code,
        positive_electrode_basis=positive_electrode_basis,
        negative_electrode_basis=negative_electrode_basis,
        nominal_capacity_min=nominal_capacity_min,
        nominal_capacity_max=nominal_capacity_max,
        nominal_voltage_min=nominal_voltage_min,
        nominal_voltage_max=nominal_voltage_max,
        directory=library_dir,
        limit=limit,
        offset=offset,
    )
    payload = {
        "resource": "library-cell-spec",
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "items": rows,
    }
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table(
        rows,
        ["id", "manufacturer", "model", "chemistry", "format", "nominal_capacity", "nominal_voltage", "source_type"],
    )


@library_save_app.command("cell-spec")
def library_save_cell_spec(
    input_path: Path | None = typer.Option(
        None, "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Draft or canonical cell-specification JSON."
    ),
    manufacturer: str | None = typer.Option(None, help="Manufacturer name (required when --input omitted)."),
    model: str | None = typer.Option(None, help="Model name (required when --input omitted)."),
    chemistry: str = typer.Option("unknown", help="Chemistry label."),
    cell_format: str = typer.Option("unknown", "--cell-format", help="Cell format."),
    positive_electrode_basis: str | None = typer.Option(
        None, help="Positive electrode basis (required when --input omitted)."
    ),
    negative_electrode_basis: str | None = typer.Option(
        None, help="Negative electrode basis (required when --input omitted)."
    ),
    size_code: str | None = typer.Option(None, help="Optional size code."),
    source_type: str = typer.Option("datasheet", help="Source type label."),
    source_name: str | None = typer.Option(None, help="Optional source name."),
    source_file: str = typer.Option("manual.json", help="Source file label for provenance."),
    source_url: str | None = typer.Option(None, help="Optional source URL."),
    uid: str | None = typer.Option(None, help="Optional 16-char UID (dashed or undashed)."),
    property_path: Path | None = typer.Option(
        None,
        "--property",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Optional JSON object for cell-specification specification.property.",
    ),
    library_dir: Path = typer.Option(Path(".battinfo/library/cell-spec"), help="Reusable library cell-specification directory."),
    packaged_dir: Path = typer.Option(
        Path("src/battinfo/data/library/cell-spec"),
        help="Packaged reusable library cell-specification directory.",
    ),
    mode: str = typer.Option("create_only", help="Save mode: create_only|upsert."),
    duplicate_policy: str = typer.Option("error", help="Duplicate handling: error|return_existing."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate cell specification before saving."),
    sync_packaged_copy: bool = typer.Option(
        True, "--sync-packaged-copy/--no-sync-packaged-copy", help="Sync the saved cell specification into package data."
    ),
    build_rdf: bool = typer.Option(False, "--build-rdf/--no-build-rdf", help="Build JSON-LD library artifacts after saving."),
    output_jsonld_dir: Path = typer.Option(
        Path(".battinfo/library-rdf/cell-spec"),
        help="Directory for per-record domain-battery JSON-LD artifacts.",
    ),
    aggregate_jsonld: Path = typer.Option(
        Path(".battinfo/library/cell-spec.jsonld"),
        help="Path for the aggregated library JSON-LD file.",
    ),
    manifest_json: Path = typer.Option(
        Path(".battinfo/library-rdf/cell-spec.index.json"),
        help="Path for the generated library manifest JSON.",
    ),
    clean_output: bool = typer.Option(False, "--clean-output", help="Clean existing JSON-LD outputs before rebuilding."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview save without writing files."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Save a reusable library cell type from cell-specification JSON or inline fields."""
    fmt = _check_output_format(output_format)
    reg_mode = _check_save_mode(mode)
    dup_policy = _check_duplicate_policy(duplicate_policy)
    try:
        if input_path is not None:
            draft_obj: dict[str, Any] | Path = input_path
        else:
            if not manufacturer or not model or not positive_electrode_basis or not negative_electrode_basis:
                raise ValueError(
                    "--manufacturer, --model, --positive-electrode-basis, and --negative-electrode-basis "
                    "are required when --input is not provided."
                )
            properties: dict[str, Any] = {}
            if property_path is not None:
                loaded_property = json.loads(property_path.read_text(encoding="utf-8"))
                if not isinstance(loaded_property, dict):
                    raise ValueError("--property must point to a JSON object.")
                properties = loaded_property
            # Flat library-specification dict; save_library_cell_spec normalises it into a record.
            draft_obj = {
                "uid": uid,
                "manufacturer": manufacturer,
                "model": model,
                "chemistry": chemistry,
                "format": cell_format,
                "positive_electrode_basis": positive_electrode_basis,
                "negative_electrode_basis": negative_electrode_basis,
                "size_code": size_code,
                "property": properties,
                "source_type": source_type,
                "source_name": source_name,
                "source_file": source_file,
                "source_url": source_url,
            }
        payload = api_save_library_cell_spec(
            draft_obj,
            library_root=library_dir,
            package_root=packaged_dir,
            mode=reg_mode,
            duplicate_policy=dup_policy,
            validate=validate,
            sync_packaged_copy=sync_packaged_copy,
            build_rdf=build_rdf,
            output_jsonld_dir=output_jsonld_dir,
            aggregate_jsonld=aggregate_jsonld,
            manifest_json=manifest_json,
            clean_output=clean_output,
            dry_run=dry_run,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "id", "path", "package_path", "mode", "built_rdf"])


@library_app.command("build-rdf")
def library_build_rdf(
    input_dir: Path = typer.Option(
        Path(".battinfo/library/cell-spec"),
        "--input-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Directory containing reusable library cell-specification JSON files.",
    ),
    output_jsonld_dir: Path = typer.Option(
        Path(".battinfo/library-rdf/cell-spec"),
        help="Directory for per-record domain-battery JSON-LD artifacts.",
    ),
    aggregate_jsonld: Path = typer.Option(
        Path(".battinfo/library/cell-spec.jsonld"),
        help="Path for the aggregated library JSON-LD file.",
    ),
    manifest_json: Path = typer.Option(
        Path(".battinfo/library-rdf/cell-spec.index.json"),
        help="Path for the generated library manifest JSON.",
    ),
    glob: str = typer.Option("*.json", help="File glob used to select library cell specifications."),
    clean_output: bool = typer.Option(False, "--clean-output", help="Remove existing JSON-LD outputs before writing."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Build domain-battery JSON-LD artifacts for the reusable cell-spec library."""
    fmt = _check_output_format(output_format)
    try:
        payload = api_build_cell_spec_library_rdf(
            input_dir=input_dir,
            output_jsonld_dir=output_jsonld_dir,
            aggregate_jsonld=aggregate_jsonld,
            manifest_json=manifest_json,
            glob=glob,
            clean_output=clean_output,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "entry_count", "output_jsonld_dir", "aggregate_jsonld", "manifest_json"])


@query_app.command("cell-spec")
def query_cell_specs(
    id: str | None = typer.Option(None, help="Filter by canonical cell-spec IRI."),
    manufacturer: str | None = typer.Option(None, help="Filter by manufacturer."),
    chemistry: str | None = typer.Option(None, help="Filter by chemistry."),
    cell_format: str | None = typer.Option(None, "--cell-format", help="Filter by cell form factor."),
    model_name_contains: str | None = typer.Option(None, help="Filter by model name substring."),
    nominal_capacity_min: float | None = typer.Option(None, help="Filter minimum nominal capacity."),
    nominal_capacity_max: float | None = typer.Option(None, help="Filter maximum nominal capacity."),
    nominal_voltage_min: float | None = typer.Option(None, help="Filter minimum nominal voltage."),
    nominal_voltage_max: float | None = typer.Option(None, help="Filter maximum nominal voltage."),
    limit: int = typer.Option(50, min=1, help="Maximum rows."),
    offset: int = typer.Option(0, min=0, help="Start offset."),
    output_format: str = typer.Option("table", "--format", help="Output format: table|json."),
) -> None:
    """Query canonical cell types."""
    fmt = _check_output_format(output_format)
    rows = api_query_cell_specs(
        id=id,
        manufacturer=manufacturer,
        chemistry=chemistry,
        format=cell_format,
        model_name_contains=model_name_contains,
        nominal_capacity_min=nominal_capacity_min,
        nominal_capacity_max=nominal_capacity_max,
        nominal_voltage_min=nominal_voltage_min,
        nominal_voltage_max=nominal_voltage_max,
        limit=limit,
        offset=offset,
    )
    payload = {
        "resource": "cell-spec",
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "items": rows,
    }
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table(
        rows,
        ["id", "manufacturer", "model_name", "chemistry", "format", "nominal_capacity", "nominal_voltage"],
    )


@query_app.command("cell-instance")
def query_cell_instances(
    id: str | None = typer.Option(None, help="Filter by canonical cell IRI."),
    cell_spec_id: str | None = typer.Option(None, help="Filter by canonical cell-spec IRI."),
    short_id: str | None = typer.Option(None, help="Filter by short-id prefix."),
    serial_number: str | None = typer.Option(None, help="Filter by serial metadata."),
    has_dataset: str | None = typer.Option(None, help="Filter by dataset presence: true|false."),
    dataset_id: str | None = typer.Option(None, help="Filter by linked dataset IRI."),
    source_type: str | None = typer.Option(None, help="Filter by source type."),
    limit: int = typer.Option(50, min=1, help="Maximum rows."),
    offset: int = typer.Option(0, min=0, help="Start offset."),
    output_format: str = typer.Option("table", "--format", help="Output format: table|json."),
) -> None:
    """Query canonical cell instances."""
    fmt = _check_output_format(output_format)
    dataset_bool = _parse_optional_bool(has_dataset, "--has-dataset")
    rows = api_query_cell_instances(
        id=id,
        cell_spec_id=cell_spec_id,
        short_id_prefix=short_id,
        serial_number=serial_number,
        has_dataset=dataset_bool,
        dataset_id=dataset_id,
        source_type=source_type,
        limit=limit,
        offset=offset,
    )
    payload = {
        "resource": "cell-instance",
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "items": rows,
    }
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table(rows, ["id", "cell_spec_id", "short_id", "serial_number", "dataset_id", "source_type"])


@query_app.command("dataset")
def query_datasets(
    id: str | None = typer.Option(None, help="Filter by canonical dataset IRI."),
    title_contains: str | None = typer.Option(None, help="Filter by title substring."),
    related_cell_id: str | None = typer.Option(None, help="Filter by related cell IRI."),
    related_test_id: str | None = typer.Option(None, help="Filter by related test IRI."),
    source_type: str | None = typer.Option(None, help="Filter by source type."),
    data_format: str | None = typer.Option(None, "--data-format", help="Filter by dataset format."),
    license: str | None = typer.Option(None, help="Filter by license."),
    limit: int = typer.Option(50, min=1, help="Maximum rows."),
    offset: int = typer.Option(0, min=0, help="Start offset."),
    output_format: str = typer.Option("table", "--format", help="Output format: table|json."),
) -> None:
    """Query canonical dataset records."""
    fmt = _check_output_format(output_format)
    rows = api_query_datasets(
        id=id,
        title_contains=title_contains,
        related_cell_id=related_cell_id,
        related_test_id=related_test_id,
        source_type=source_type,
        format=data_format,
        license=license,
        limit=limit,
        offset=offset,
    )
    payload = {
        "resource": "dataset",
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "items": rows,
    }
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table(rows, ["id", "title", "format", "license", "source_type", "access_url"])


@query_app.command("test-protocol")
def query_test_specs(
    id: str | None = typer.Option(None, help="Filter by canonical test-protocol IRI."),
    kind: str | None = typer.Option(None, help="Filter by protocol kind."),
    name_contains: str | None = typer.Option(None, help="Case-insensitive substring filter on protocol name."),
    source_type: str | None = typer.Option(None, help="Filter by source type."),
    limit: int = typer.Option(50, min=1, help="Maximum rows."),
    offset: int = typer.Option(0, min=0, help="Start offset."),
    output_format: str = typer.Option("table", "--format", help="Output format: table|json."),
) -> None:
    """Query canonical test protocols."""
    fmt = _check_output_format(output_format)
    rows = api_query_test_specs(
        id=id,
        kind=kind,
        name_contains=name_contains,
        source_type=source_type,
        limit=limit,
        offset=offset,
    )
    payload = {
        "resource": "test-protocol",
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "items": rows,
    }
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table(rows, ["id", "name", "kind", "version", "source_type"])


@query_app.command("tests")
def query_tests(
    id: str | None = typer.Option(None, help="Filter by canonical test IRI."),
    cell_id: str | None = typer.Option(None, help="Filter by related cell-instance IRI."),
    dataset_id: str | None = typer.Option(None, help="Filter by linked dataset IRI."),
    kind: str | None = typer.Option(None, help="Filter by test kind."),
    source_type: str | None = typer.Option(None, help="Filter by source type."),
    limit: int = typer.Option(50, min=1, help="Maximum rows."),
    offset: int = typer.Option(0, min=0, help="Start offset."),
    output_format: str = typer.Option("table", "--format", help="Output format: table|json."),
) -> None:
    """Query canonical tests."""
    fmt = _check_output_format(output_format)
    rows = api_query_tests(
        id=id,
        cell_id=cell_id,
        dataset_id=dataset_id,
        kind=kind,
        source_type=source_type,
        limit=limit,
        offset=offset,
    )
    payload = {
        "resource": "tests",
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "items": rows,
    }
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table(rows, ["id", "cell_id", "name", "kind", "status", "source_type"])


@create_app.command("cell-instance")
def create_cell_instance(
    cell_spec_id: str | None = typer.Option(None, help="Canonical cell-spec IRI."),
    cell_spec: Path | None = typer.Option(
        None, help="Path to cell-spec JSON (alternative to --cell-spec-id).", exists=True, file_okay=True, dir_okay=False
    ),
    model_name: str | None = typer.Option(None, help="Resolve type by model name."),
    manufacturer: str | None = typer.Option(None, help="Resolve type by manufacturer."),
    chemistry: str | None = typer.Option(None, help="Resolve type by chemistry."),
    cell_format: str | None = typer.Option(None, "--cell-format", help="Resolve type by cell format."),
    serial_number: str | None = typer.Option(None, help="Optional serial metadata."),
    dataset_id: str | None = typer.Option(None, help="Optional linked dataset IRI."),
    source_type: str = typer.Option("measurement", help="Source type: measurement|lab|bms|other."),
    uid: str | None = typer.Option(None, help="Optional 16-char UID (dashed or undashed)."),
    out: Path | None = typer.Option(None, help="Optional output JSON path."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate against schema."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Create a canonical cell-instance record."""
    fmt = _check_output_format(output_format)
    try:
        doc = api_create_cell_instance(
            cell_spec_id=cell_spec_id,
            cell_spec=cell_spec,
            model_name=model_name,
            manufacturer=manufacturer,
            chemistry=chemistry,
            format=cell_format,
            serial_number=serial_number,
            dataset_id=dataset_id,
            source_type=source_type,
            uid=uid,
            out_path=out,
            validate=validate,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    payload = {
        "status": "created",
        "resource": "cell-instance",
        "id": doc["cell_instance"]["id"],
        "cell_spec_id": doc["cell_instance"]["cell_spec_id"],
        "path": str(out) if out else None,
    }
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "resource", "id", "cell_spec_id", "path"])


@save_app.command("record")
def save_record(
    input_path: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False, readable=True),
    source_root: Path = typer.Option(
        Path("examples"),
        help="Root directory containing cell-spec, cell-instances, and dataset.",
    ),
    mode: str = typer.Option("create_only", help="Save mode: create_only|upsert."),
    duplicate_policy: str = typer.Option("error", help="Duplicate handling: error|return_existing."),
    resolve_references: bool = typer.Option(
        True,
        "--resolve-references/--no-resolve-references",
        help="Best-effort reference checks at save time; full link integrity is enforced by batch/index validation.",
    ),
    publish: bool = typer.Option(False, "--publish/--no-publish", help="Publish resolver artifacts after saving."),
    publish_root: Path = typer.Option(Path(".battinfo/resolver-site"), help="Resolver artifact root."),
    build_jsonld: bool = typer.Option(True, "--build-jsonld/--no-build-jsonld", help="Publish JSON-LD artifact."),
    build_html: bool = typer.Option(True, "--build-html/--no-build-html", help="Publish HTML artifact."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate record before saving."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview save without writing files."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Save one canonical BattINFO record from JSON."""
    fmt = _check_output_format(output_format)
    reg_mode = _check_save_mode(mode)
    dup_policy = _check_duplicate_policy(duplicate_policy)
    policy_name = _check_validation_policy(validation_policy)
    try:
        payload = api_save_record(
            input_path,
            source_root=source_root,
            mode=reg_mode,
            duplicate_policy=dup_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=policy_name,
            dry_run=dry_run,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "entity_type", "id", "path", "mode", "published"])


@save_app.command("batch")
def save_batch(
    source_dir: list[Path] = typer.Option(
        [],
        "--source-dir",
        help="One or more source directories. If omitted, API defaults are used.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
    ),
    source_root: Path = typer.Option(
        Path("examples"),
        help="Root directory containing canonical resources for save targets.",
    ),
    glob: str = typer.Option("*.json", help="File glob for batch inputs."),
    mode: str = typer.Option("create_only", help="Save mode: create_only|upsert."),
    duplicate_policy: str = typer.Option("error", help="Duplicate handling: error|return_existing."),
    resolve_references: bool = typer.Option(
        True,
        "--resolve-references/--no-resolve-references",
        help="Allow deferred writes, then validate the resulting source tree as a set.",
    ),
    publish: bool = typer.Option(False, "--publish/--no-publish", help="Publish resolver artifacts after saving."),
    publish_root: Path = typer.Option(Path(".battinfo/resolver-site"), help="Resolver artifact root."),
    build_jsonld: bool = typer.Option(True, "--build-jsonld/--no-build-jsonld", help="Publish JSON-LD artifact."),
    build_html: bool = typer.Option(True, "--build-html/--no-build-html", help="Publish HTML artifact."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate records before saving."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview save without writing files."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Save a deterministic batch of canonical JSON records."""
    fmt = _check_output_format(output_format)
    reg_mode = _check_save_mode(mode)
    dup_policy = _check_duplicate_policy(duplicate_policy)
    policy_name = _check_validation_policy(validation_policy)
    kwargs: dict[str, Any] = {
        "source_root": source_root,
        "glob": glob,
        "mode": reg_mode,
        "duplicate_policy": dup_policy,
        "resolve_references": resolve_references,
        "publish": publish,
        "publish_root": publish_root,
        "build_jsonld": build_jsonld,
        "build_html": build_html,
        "validate": validate,
        "validation_policy": policy_name,
        "dry_run": dry_run,
    }
    if source_dir:
        kwargs["source_dirs"] = source_dir
    payload = api_save_batch(**kwargs)
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "processed", "created", "updated", "exists", "dry_run", "failed"])


@save_app.command("cell-spec")
def save_cell_spec(
    input_path: Path | None = typer.Option(
        None, "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Draft or canonical JSON."
    ),
    manufacturer: str | None = typer.Option(None, help="Manufacturer name (required when --input omitted)."),
    model_name: str | None = typer.Option(None, "--model-name", help="Model name (required when --input omitted)."),
    chemistry: str = typer.Option("unknown", help="Chemistry label."),
    cell_format: str = typer.Option("unknown", "--cell-format", help="Cell format."),
    size_code: str | None = typer.Option(None, help="Optional size code."),
    country_of_origin: str | None = typer.Option(None, "--country-of-origin", help="Optional country of origin."),
    year: int | None = typer.Option(None, help="Optional model or release year."),
    source_file: str = typer.Option("manual.json", help="Source file label for provenance."),
    source_url: str | None = typer.Option(None, help="Optional source URL."),
    uid: str | None = typer.Option(None, help="Optional 16-char UID (dashed or undashed)."),
    specs_path: Path | None = typer.Option(
        None, "--specs", exists=True, file_okay=True, dir_okay=False, readable=True, help="Optional specs JSON object."
    ),
    source_root: Path = typer.Option(Path("examples"), help="Save source root."),
    mode: str = typer.Option("create_only", help="Save mode: create_only|upsert."),
    duplicate_policy: str = typer.Option("error", help="Duplicate handling: error|return_existing."),
    publish: bool = typer.Option(False, "--publish/--no-publish", help="Publish resolver artifacts after saving."),
    publish_root: Path = typer.Option(Path(".battinfo/resolver-site"), help="Resolver artifact root."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate record before saving."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview save without writing files."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Save a cell-spec using either --input JSON or inline draft fields."""
    fmt = _check_output_format(output_format)
    reg_mode = _check_save_mode(mode)
    dup_policy = _check_duplicate_policy(duplicate_policy)
    policy_name = _check_validation_policy(validation_policy)
    try:
        if input_path is not None:
            draft_obj: CellSpecificationInput | dict[str, Any] | Path = input_path
        else:
            if not manufacturer or not model_name:
                raise ValueError("--manufacturer and --model-name are required when --input is not provided.")
            specs: dict[str, Any] = {}
            if specs_path is not None:
                loaded_specs = json.loads(specs_path.read_text(encoding="utf-8"))
                if not isinstance(loaded_specs, dict):
                    raise ValueError("--specs must point to a JSON object.")
                specs = loaded_specs
            draft_obj = CellSpecificationInput(
                uid=uid,
                model_name=model_name,
                manufacturer=manufacturer,
                chemistry=chemistry,
                format=cell_format,  # type: ignore[arg-type]
                size_code=size_code,
                country_of_origin=country_of_origin,
                year=year,
                specs=specs,
                source_file=source_file,
                source_url=source_url,
            )
        payload = api_save_cell_spec(
            draft_obj,
            source_root=source_root,
            mode=reg_mode,
            duplicate_policy=dup_policy,
            resolve_references=False,
            publish=publish,
            publish_root=publish_root,
            validate=validate,
            validation_policy=policy_name,
            dry_run=dry_run,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "entity_type", "id", "path", "mode", "published"])


@save_app.command("cell-instance")
def save_cell_instance(
    input_path: Path | None = typer.Option(
        None, "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Draft or canonical JSON."
    ),
    cell_spec_id: str | None = typer.Option(None, help="Canonical cell-spec IRI (required when --input omitted)."),
    serial_number: str | None = typer.Option(None, help="Optional serial metadata."),
    dataset_id: list[str] = typer.Option([], "--dataset-id", help="Optional linked dataset IRI. Repeat for multiple."),
    source_type: str = typer.Option("measurement", help="Source type: measurement|lab|bms|other."),
    uid: str | None = typer.Option(None, help="Optional 16-char UID (dashed or undashed)."),
    source_root: Path = typer.Option(Path("examples"), help="Save source root."),
    mode: str = typer.Option("create_only", help="Save mode: create_only|upsert."),
    duplicate_policy: str = typer.Option("error", help="Duplicate handling: error|return_existing."),
    resolve_references: bool = typer.Option(
        True, "--resolve-references/--no-resolve-references", help="Resolve linked IDs against source_root."
    ),
    publish: bool = typer.Option(False, "--publish/--no-publish", help="Publish resolver artifacts after saving."),
    publish_root: Path = typer.Option(Path(".battinfo/resolver-site"), help="Resolver artifact root."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate record before saving."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview save without writing files."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Save a cell-instance using either --input JSON or inline draft fields."""
    fmt = _check_output_format(output_format)
    reg_mode = _check_save_mode(mode)
    dup_policy = _check_duplicate_policy(duplicate_policy)
    policy_name = _check_validation_policy(validation_policy)
    try:
        if input_path is not None:
            draft_obj: CellInstanceInput | dict[str, Any] | Path = input_path
        else:
            if not cell_spec_id:
                raise ValueError("--cell-spec-id is required when --input is not provided.")
            draft_obj = CellInstanceInput(
                uid=uid,
                cell_spec_id=cell_spec_id,
                serial_number=serial_number,
                source_type=source_type,  # type: ignore[arg-type]
                dataset_id=(dataset_id[0] if dataset_id else None),
                dataset_ids=(dataset_id[1:] if len(dataset_id) > 1 else []),
            )
        payload = api_save_cell_instance(
            draft_obj,
            source_root=source_root,
            mode=reg_mode,
            duplicate_policy=dup_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            validate=validate,
            validation_policy=policy_name,
            dry_run=dry_run,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "entity_type", "id", "path", "mode", "published"])


@save_app.command("dataset")
def save_dataset(
    input_path: Path | None = typer.Option(
        None, "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Draft or canonical JSON."
    ),
    title: str | None = typer.Option(None, help="Dataset title (required when --input omitted)."),
    description: str | None = typer.Option(None, help="Dataset description."),
    license: str | None = typer.Option(None, help="Dataset license."),
    data_format: str | None = typer.Option(None, "--data-format", help="Dataset format string."),
    access_url: str | None = typer.Option(None, help="Dataset access URL."),
    source_type: str = typer.Option("other", help="Source type: measurement|lab|simulation|external|other."),
    related_cell_id: list[str] = typer.Option([], "--related-cell-id", help="Related cell IRI. Repeat for multiple."),
    related_test_id: list[str] = typer.Option([], "--related-test-id", help="Related test IRI. Repeat for multiple."),
    checksum_algorithm: str | None = typer.Option(None, help="Checksum algorithm (sha256|sha512|md5|other)."),
    checksum_value: str | None = typer.Option(None, help="Checksum value."),
    uid: str | None = typer.Option(None, help="Optional 16-char UID (dashed or undashed)."),
    source_root: Path = typer.Option(Path("examples"), help="Save source root."),
    mode: str = typer.Option("create_only", help="Save mode: create_only|upsert."),
    duplicate_policy: str = typer.Option("error", help="Duplicate handling: error|return_existing."),
    resolve_references: bool = typer.Option(
        True, "--resolve-references/--no-resolve-references", help="Resolve linked IDs against source_root."
    ),
    publish: bool = typer.Option(False, "--publish/--no-publish", help="Publish resolver artifacts after saving."),
    publish_root: Path = typer.Option(Path(".battinfo/resolver-site"), help="Resolver artifact root."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate record before saving."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview save without writing files."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Save a dataset using either --input JSON or inline draft fields."""
    fmt = _check_output_format(output_format)
    reg_mode = _check_save_mode(mode)
    dup_policy = _check_duplicate_policy(duplicate_policy)
    policy_name = _check_validation_policy(validation_policy)
    try:
        if input_path is not None:
            draft_obj: DatasetInput | dict[str, Any] | Path = input_path
        else:
            if not title:
                raise ValueError("--title is required when --input is not provided.")
            if bool(checksum_algorithm) != bool(checksum_value):
                raise ValueError("--checksum-algorithm and --checksum-value must be provided together.")
            draft_obj = DatasetInput(
                uid=uid,
                title=title,
                description=description,
                license=license,
                format=data_format,
                access_url=access_url,
                source_type=source_type,  # type: ignore[arg-type]
                related_cell_ids=related_cell_id,
                related_test_ids=related_test_id,
                checksum_algorithm=checksum_algorithm,  # type: ignore[arg-type]
                checksum_value=checksum_value,
            )
        payload = api_save_dataset(
            draft_obj,
            source_root=source_root,
            mode=reg_mode,
            duplicate_policy=dup_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            validate=validate,
            validation_policy=policy_name,
            dry_run=dry_run,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "entity_type", "id", "path", "mode", "published"])


@save_app.command("test-protocol")
def save_test_spec(
    input_path: Path | None = typer.Option(
        None, "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Draft or canonical JSON."
    ),
    name: str | None = typer.Option(None, help="Protocol name (required when --input omitted)."),
    kind: str = typer.Option("other", help="Test kind."),
    description: str | None = typer.Option(None, help="Optional protocol description."),
    version: str | None = typer.Option(None, help="Optional protocol version."),
    protocol_url: str | None = typer.Option(None, help="Optional protocol URL."),
    source_type: str = typer.Option("manual", help="Source type: manual|lab|simulation|other."),
    uid: str | None = typer.Option(None, help="Optional 16-char UID (dashed or undashed)."),
    source_root: Path = typer.Option(Path("examples"), help="Save source root."),
    mode: str = typer.Option("create_only", help="Save mode: create_only|upsert."),
    duplicate_policy: str = typer.Option("error", help="Duplicate handling: error|return_existing."),
    resolve_references: bool = typer.Option(
        True, "--resolve-references/--no-resolve-references", help="Resolve linked IDs against source_root."
    ),
    publish: bool = typer.Option(False, "--publish/--no-publish", help="Publish resolver artifacts after saving."),
    publish_root: Path = typer.Option(Path(".battinfo/resolver-site"), help="Resolver artifact root."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate record before saving."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview save without writing files."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Save a reusable test protocol using either --input JSON or inline draft fields."""
    fmt = _check_output_format(output_format)
    reg_mode = _check_save_mode(mode)
    dup_policy = _check_duplicate_policy(duplicate_policy)
    policy_name = _check_validation_policy(validation_policy)
    try:
        if input_path is not None:
            draft_obj: TestSpecInput | dict[str, Any] | Path = input_path
        else:
            if not name:
                raise ValueError("--name is required when --input is not provided.")
            draft_obj = TestSpecInput(
                uid=uid,
                name=name,
                kind=kind,  # type: ignore[arg-type]
                description=description,
                version=version,
                protocol_url=protocol_url,
                source_type=source_type,  # type: ignore[arg-type]
            )
        payload = api_save_test_spec(
            draft_obj,
            source_root=source_root,
            mode=reg_mode,
            duplicate_policy=dup_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            validate=validate,
            validation_policy=policy_name,
            dry_run=dry_run,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "entity_type", "id", "path", "mode", "published"])


@save_app.command("test")
def save_test(
    input_path: Path | None = typer.Option(
        None, "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Draft or canonical JSON."
    ),
    cell_id: str | None = typer.Option(None, help="Canonical cell-instance IRI (required when --input omitted)."),
    name: str | None = typer.Option(None, help="Test name (required when --input omitted)."),
    kind: str = typer.Option("other", help="Test kind."),
    protocol_id: str | None = typer.Option(None, help="Optional reusable test-protocol IRI."),
    status: str | None = typer.Option(None, help="Optional test status."),
    protocol_name: str | None = typer.Option(None, help="Optional protocol name."),
    protocol_url: str | None = typer.Option(None, help="Optional protocol URL."),
    instrument_name: str | None = typer.Option(None, help="Optional instrument name."),
    dataset_id: list[str] = typer.Option([], "--dataset-id", help="Linked dataset IRI. Repeat for multiple."),
    source_type: str = typer.Option("measurement", help="Source type: measurement|lab|simulation|manual|other."),
    uid: str | None = typer.Option(None, help="Optional 16-char UID (dashed or undashed)."),
    source_root: Path = typer.Option(Path("examples"), help="Save source root."),
    mode: str = typer.Option("create_only", help="Save mode: create_only|upsert."),
    duplicate_policy: str = typer.Option("error", help="Duplicate handling: error|return_existing."),
    resolve_references: bool = typer.Option(
        True, "--resolve-references/--no-resolve-references", help="Resolve linked IDs against source_root."
    ),
    publish: bool = typer.Option(False, "--publish/--no-publish", help="Publish resolver artifacts after saving."),
    publish_root: Path = typer.Option(Path(".battinfo/resolver-site"), help="Resolver artifact root."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate record before saving."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview save without writing files."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Save a test using either --input JSON or inline draft fields."""
    fmt = _check_output_format(output_format)
    reg_mode = _check_save_mode(mode)
    dup_policy = _check_duplicate_policy(duplicate_policy)
    policy_name = _check_validation_policy(validation_policy)
    try:
        if input_path is not None:
            draft_obj: TestInput | dict[str, Any] | Path = input_path
        else:
            if not cell_id or not name:
                raise ValueError("--cell-id and --name are required when --input is not provided.")
            draft_obj = TestInput(
                uid=uid,
                cell_id=cell_id,
                name=name,
                kind=kind,  # type: ignore[arg-type]
                protocol_id=protocol_id,
                status=status,  # type: ignore[arg-type]
                protocol_name=protocol_name,
                protocol_url=protocol_url,
                instrument_name=instrument_name,
                dataset_ids=dataset_id,
                source_type=source_type,  # type: ignore[arg-type]
            )
        payload = api_save_test(
            draft_obj,
            source_root=source_root,
            mode=reg_mode,
            duplicate_policy=dup_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            validate=validate,
            validation_policy=policy_name,
            dry_run=dry_run,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "entity_type", "id", "path", "mode", "published"])


@editorial_app.command("validate-staging-cell-spec")
def validate_staging_cell_spec(
    input_path: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Staging JSON draft."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Validate one single-file staging cell-spec draft and preview its canonical record."""
    fmt = _check_output_format(output_format)
    policy_name = _check_validation_policy(validation_policy)
    try:
        payload = api_validate_staging_cell_spec(input_path, validation_policy=policy_name)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["ok", "record_id", "record_id_basis", "requires_record_id", "source_path"])


@editorial_app.command("validate-staging-cell-spec-batch")
def validate_staging_cell_specs(
    input_dir: Path = typer.Option(..., "--input-dir", exists=True, file_okay=False, dir_okay=True, readable=True, help="Directory of staging JSON drafts."),
    glob: str = typer.Option("*.json", help="Glob for staging drafts."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Validate all staging cell-spec drafts in a directory."""
    fmt = _check_output_format(output_format)
    policy_name = _check_validation_policy(validation_policy)
    try:
        payload = api_validate_staging_cell_specs(
            input_dir=input_dir,
            glob=glob,
            validation_policy=policy_name,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    summary = {
        "status": payload["status"],
        "input_dir": payload["input_dir"],
        "processed": payload["processed"],
        "ok": payload["ok"],
        "failed": payload["failed"],
    }
    _emit_table([summary], ["status", "input_dir", "processed", "ok", "failed"])


@editorial_app.command("promote-staging-cell-spec")
def promote_staging_cell_spec(
    input_path: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Staging JSON draft."),
    curated_root: Path = typer.Option(Path("records/cell-spec"), help="Curated cell-spec root."),
    record_id: str | None = typer.Option(None, "--record-id", help="Override the curated record id."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview promotion without writing files."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Promote one staging cell-spec draft into records/cell-spec/<record-id>/record.json."""
    fmt = _check_output_format(output_format)
    policy_name = _check_validation_policy(validation_policy)
    try:
        payload = api_promote_staging_cell_spec(
            input_path,
            curated_root=curated_root,
            record_id=record_id,
            validation_policy=policy_name,
            dry_run=dry_run,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "record_id", "record_id_basis", "source_path", "target_path", "dry_run"])


@editorial_app.command("promote-staging-cell-spec-batch")
def promote_staging_cell_specs(
    input_dir: Path = typer.Option(..., "--input-dir", exists=True, file_okay=False, dir_okay=True, readable=True, help="Directory of staging JSON drafts."),
    curated_root: Path = typer.Option(Path("records/cell-spec"), help="Curated cell-spec root."),
    glob: str = typer.Option("*.json", help="Glob for staging drafts."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview promotion without writing files."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Promote all staging cell-spec drafts into curated record.json directories."""
    fmt = _check_output_format(output_format)
    policy_name = _check_validation_policy(validation_policy)
    try:
        payload = api_promote_staging_cell_specs(
            input_dir=input_dir,
            curated_root=curated_root,
            glob=glob,
            validation_policy=policy_name,
            dry_run=dry_run,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    summary = {
        "status": payload["status"],
        "input_dir": payload["input_dir"],
        "curated_root": payload["curated_root"],
        "processed": payload["processed"],
        "dry_run": payload["dry_run"],
    }
    _emit_table([summary], ["status", "input_dir", "curated_root", "processed", "dry_run"])


@editorial_app.command("validate-staging-dataset")
def validate_staging_dataset(
    input_path: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Staging dataset JSON record."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Validate one staging dataset record and preview its curated record id."""
    fmt = _check_output_format(output_format)
    policy_name = _check_validation_policy(validation_policy)
    try:
        payload = api_validate_staging_dataset(input_path, validation_policy=policy_name)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["ok", "record_id", "record_id_basis", "requires_record_id", "source_path"])


@editorial_app.command("validate-staging-dataset-batch")
def validate_staging_datasets(
    input_dir: Path = typer.Option(..., "--input-dir", exists=True, file_okay=False, dir_okay=True, readable=True, help="Directory of staging dataset records."),
    glob: str = typer.Option("*.json", help="Glob for staging records."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Validate all staging dataset records in a directory."""
    fmt = _check_output_format(output_format)
    policy_name = _check_validation_policy(validation_policy)
    try:
        payload = api_validate_staging_datasets(
            input_dir=input_dir,
            glob=glob,
            validation_policy=policy_name,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    summary = {
        "status": payload["status"],
        "input_dir": payload["input_dir"],
        "processed": payload["processed"],
        "ok": payload["ok"],
        "failed": payload["failed"],
    }
    _emit_table([summary], ["status", "input_dir", "processed", "ok", "failed"])


@editorial_app.command("promote-staging-dataset")
def promote_staging_dataset(
    input_path: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Staging dataset JSON record."),
    curated_root: Path = typer.Option(Path("records/dataset"), help="Curated dataset root."),
    record_id: str | None = typer.Option(None, "--record-id", help="Override the curated record id."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview promotion without writing files."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Promote one staging dataset record into records/dataset/<record-id>/record.json."""
    fmt = _check_output_format(output_format)
    policy_name = _check_validation_policy(validation_policy)
    try:
        payload = api_promote_staging_dataset(
            input_path,
            curated_root=curated_root,
            record_id=record_id,
            validation_policy=policy_name,
            dry_run=dry_run,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "record_id", "record_id_basis", "source_path", "target_path", "dry_run"])


@editorial_app.command("promote-staging-dataset-batch")
def promote_staging_datasets(
    input_dir: Path = typer.Option(..., "--input-dir", exists=True, file_okay=False, dir_okay=True, readable=True, help="Directory of staging dataset records."),
    curated_root: Path = typer.Option(Path("records/dataset"), help="Curated dataset root."),
    glob: str = typer.Option("*.json", help="Glob for staging records."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview promotion without writing files."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Promote all staging dataset records into curated record.json directories."""
    fmt = _check_output_format(output_format)
    policy_name = _check_validation_policy(validation_policy)
    try:
        payload = api_promote_staging_datasets(
            input_dir=input_dir,
            curated_root=curated_root,
            glob=glob,
            validation_policy=policy_name,
            dry_run=dry_run,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    summary = {
        "status": payload["status"],
        "input_dir": payload["input_dir"],
        "curated_root": payload["curated_root"],
        "processed": payload["processed"],
        "dry_run": payload["dry_run"],
    }
    _emit_table([summary], ["status", "input_dir", "curated_root", "processed", "dry_run"])


@editorial_app.command("build-curated-cell-spec-submission")
def build_curated_cell_spec_submission(
    input_path: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Curated cell-spec record.json or equivalent canonical JSON."),
    workspace_id: str = typer.Option(..., "--workspace-id", help="Registry workspace id."),
    publisher_id: str = typer.Option(..., help="Registry publisher id."),
    source_version: str = typer.Option(..., help="Registry source_version for this publication run."),
    source_local_id: str | None = typer.Option(None, help="Override source_local_id; defaults to the curated record id inferred from the path."),
    title: str | None = typer.Option(None, help="Override submission title."),
    publication_mode: str = typer.Option("canonical-publication", help="Publication intent mode."),
    source_system: str = typer.Option("battinfo-records", help="Submission provenance source_system."),
    workflow_name: str = typer.Option("curated-cell-spec-publication", help="Submission provenance workflow_name."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    out_path: Path | None = typer.Option(None, "--out", help="Optional path to write the generated submission package JSON."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Build a registry publication package for one curated cell-spec record."""
    fmt = _check_output_format(output_format)
    policy_name = _check_validation_policy(validation_policy)
    try:
        payload = api_build_curated_cell_spec_submission(
            input_path,
            workspace_id=workspace_id,
            publisher_id=publisher_id,
            source_version=source_version,
            source_local_id=source_local_id,
            title=title,
            publication_mode=publication_mode,
            source_system=source_system,
            workflow_name=workflow_name,
            validation_policy=policy_name,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if out_path is not None:
        _write_json_file(out_path, payload)
    if fmt == "json":
        _emit_json(payload)
        return
    resource = payload.get("resource") if isinstance(payload, dict) else None
    summary = {
        "workspace_id": workspace_id,
        "publisher_id": payload.get("publisher_id"),
        "source_version": payload.get("source_version"),
        "resource_type": resource.get("resource_type") if isinstance(resource, dict) else None,
        "source_local_id": resource.get("source_local_id") if isinstance(resource, dict) else None,
        "out_path": str(out_path) if out_path is not None else "",
    }
    _emit_table([summary], ["workspace_id", "publisher_id", "source_version", "resource_type", "source_local_id", "out_path"])


@editorial_app.command("publish-curated-cell-spec")
def publish_curated_cell_spec(
    input_path: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Curated cell-spec record.json or equivalent canonical JSON."),
    workspace_id: str = typer.Option(..., "--workspace-id", help="Registry workspace id."),
    publisher_id: str = typer.Option(..., help="Registry publisher id."),
    source_version: str = typer.Option(..., help="Registry source_version for this publication run."),
    registry_url: str = typer.Option(..., "--registry-url", help="Registry base URL, for example http://127.0.0.1:8000."),
    api_key: str = typer.Option(..., "--api-key", help="Registry submission API key."),
    api_key_header: str = typer.Option("X-Battinfo-API-Key", "--api-key-header", help="Registry submission API key header."),
    source_local_id: str | None = typer.Option(None, help="Override source_local_id; defaults to the curated record id inferred from the path."),
    title: str | None = typer.Option(None, help="Override submission title."),
    publication_mode: str = typer.Option("canonical-publication", help="Publication intent mode."),
    source_system: str = typer.Option("battinfo-records", help="Submission provenance source_system."),
    workflow_name: str = typer.Option("curated-cell-spec-publication", help="Submission provenance workflow_name."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    timeout_sec: float = typer.Option(30.0, "--timeout-sec", help="HTTP timeout in seconds."),
    out_path: Path | None = typer.Option(None, "--out", help="Optional path to write the generated submission package JSON before posting."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Publish one curated cell-spec record to battinfo-registry."""
    fmt = _check_output_format(output_format)
    policy_name = _check_validation_policy(validation_policy)
    try:
        if out_path is not None:
            request_payload = api_build_curated_cell_spec_submission(
                input_path,
                workspace_id=workspace_id,
                publisher_id=publisher_id,
                source_version=source_version,
                source_local_id=source_local_id,
                title=title,
                publication_mode=publication_mode,
                source_system=source_system,
                workflow_name=workflow_name,
                validation_policy=policy_name,
            )
            _write_json_file(out_path, request_payload)
        payload = api_publish_curated_cell_spec(
            input_path,
            workspace_id=workspace_id,
            publisher_id=publisher_id,
            source_version=source_version,
            registry_base_url=registry_url,
            api_key=api_key,
            api_key_header=api_key_header,
            source_local_id=source_local_id,
            title=title,
            publication_mode=publication_mode,
            source_system=source_system,
            workflow_name=workflow_name,
            validation_policy=policy_name,
            timeout_sec=timeout_sec,
        )
    except (ValueError, RuntimeError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    response_payload = payload.get("response") if isinstance(payload, dict) else None
    summary = {
        "status": payload.get("status"),
        "status_code": payload.get("status_code"),
        "submission_mode": response_payload.get("submission_mode") if isinstance(response_payload, dict) else None,
        "resource_count": response_payload.get("resource_count") if isinstance(response_payload, dict) else None,
        "created_count": response_payload.get("created_count") if isinstance(response_payload, dict) else None,
    }
    _emit_table([summary], ["status", "status_code", "submission_mode", "resource_count", "created_count"])


@publish_app.command("cell-spec")
def publish_cell_spec(
    input_path: Path | None = typer.Option(
        None,
        "--input",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Optional JSON draft or canonical cell-spec record to load.",
    ),
    manufacturer: str | None = typer.Option(None, help="Cell manufacturer."),
    model: str | None = typer.Option(None, help="Cell model."),
    cell_format: str | None = typer.Option(None, "--cell-format", help="Cell format, for example cylindrical or pouch."),
    chemistry: str | None = typer.Option(None, help="Cell chemistry."),
    name: str | None = typer.Option(None, help="Optional display name."),
    size_code: str | None = typer.Option(None, "--size-code", help="Optional size code."),
    iec_code: str | None = typer.Option(None, "--iec-code", help="Optional IEC code."),
    country_of_origin: str | None = typer.Option(None, "--country-of-origin", help="Optional country of origin."),
    year: int | None = typer.Option(None, help="Optional release or production year."),
    source_type: str | None = typer.Option(None, "--source-type", help="Optional provenance source type."),
    source_file: str | None = typer.Option(None, "--source-file", help="Optional provenance source file."),
    destination: str = typer.Option("local", help="Publish destination: local|registry|battery-genome|staging|production."),
    root: Path | None = typer.Option(None, "--root", help="Optional workspace root for generated artifacts."),
    force: bool = typer.Option(False, "--force", help="Replace an existing generated workspace root."),
    validation_policy: str = typer.Option("strict", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    registry_url: str | None = typer.Option(None, "--registry-url", help="Optional registry base URL override."),
    api_key: str | None = typer.Option(None, "--api-key", help="Optional registry API key override."),
    api_key_header: str | None = typer.Option(None, "--api-key-header", help="Optional registry API key header."),
    platform_url: str | None = typer.Option(None, "--platform-url", help="Optional Battery Genome base URL override."),
    workspace_id: str | None = typer.Option(None, "--workspace-id", help="Optional workspace id override."),
    publisher_id: str | None = typer.Option(None, "--publisher-id", help="Optional publisher id override."),
    source_version: str | None = typer.Option(None, "--source-version", help="Optional source version override."),
    output_format: str = typer.Option("json", "--format", help="Output format: json|text."),
) -> None:
    """Publish one cell type through the simplified BattINFO publish surface."""
    fmt = _check_workspace_output_format(output_format)
    try:
        if input_path is not None:
            cell_spec = _load_cell_spec_input(input_path)
        else:
            if not all(isinstance(value, str) and value.strip() for value in (manufacturer, model, cell_format, chemistry)):
                raise typer.BadParameter(
                    "Provide --input or all of --manufacturer, --model, --cell-format, and --chemistry."
                )
            cell_spec = CellSpecification(
                manufacturer=manufacturer.strip(),
                model=model.strip(),
                format=cell_format.strip(),
                chemistry=chemistry.strip(),
                name=name,
                size_code=size_code,
                iec_code=iec_code,
                country_of_origin=country_of_origin,
                year=year,
                source={"type": source_type, "file": source_file},
            )

        result = publish_object(
            cell_spec,
            destination=destination,
            root=root,
            force=force,
            validation_policy=_check_validation_policy(validation_policy),
            registry_base_url=registry_url,
            api_key=api_key,
            api_key_header=api_key_header,
            platform_base_url=platform_url,
            workspace_id=workspace_id,
            publisher_id=publisher_id,
            source_version=source_version,
        )
    except typer.BadParameter:
        raise
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    payload = result.model_dump(mode="json")
    if fmt == "json":
        _emit_json(payload)
        return

    typer.echo(f"Published cell type to {payload['destination']}")
    typer.echo(f"Canonical id: {payload.get('canonical_id')}")
    typer.echo(f"Canonical IRI: {payload.get('canonical_iri')}")
    if payload.get("registry_resource_url"):
        typer.echo(f"Registry resource: {payload['registry_resource_url']}")
    if payload.get("page_url"):
        typer.echo(f"Battery Genome page: {payload['page_url']}")


@publish_app.command("record")
def publish_record(
    input_path: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False, readable=True),
    target_root: Path = typer.Option(Path(".battinfo/resolver-site"), help="Output artifact root directory."),
    build_jsonld: bool = typer.Option(True, "--build-jsonld/--no-build-jsonld", help="Generate JSON-LD output."),
    build_html: bool = typer.Option(True, "--build-html/--no-build-html", help="Generate HTML output."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate records before publishing."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Publish one record into resolver artifacts."""
    fmt = _check_output_format(output_format)
    policy_name = _check_validation_policy(validation_policy)
    try:
        payload = api_publish_record(
            input_path,
            target_root=target_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=policy_name,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "entity_type", "id", "output_dir"])


@publish_app.command("batch")
def publish_batch(
    source_dir: list[Path] = typer.Option(
        [],
        "--source-dir",
        help="One or more source directories. If omitted, API defaults are used.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
    ),
    target_root: Path = typer.Option(Path(".battinfo/resolver-site"), help="Output artifact root directory."),
    glob: str = typer.Option("*.json", help="File glob for batch inputs."),
    build_jsonld: bool = typer.Option(True, "--build-jsonld/--no-build-jsonld", help="Generate JSON-LD output."),
    build_html: bool = typer.Option(True, "--build-html/--no-build-html", help="Generate HTML output."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate records before publishing."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Publish a deterministic batch of records into resolver artifacts."""
    fmt = _check_output_format(output_format)
    policy_name = _check_validation_policy(validation_policy)
    kwargs: dict[str, Any] = {
        "target_root": target_root,
        "glob": glob,
        "build_jsonld": build_jsonld,
        "build_html": build_html,
        "validate": validate,
        "validation_policy": policy_name,
    }
    if source_dir:
        kwargs["source_dirs"] = source_dir
    payload = api_publish_batch(**kwargs)
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "processed", "published", "failed"])


@index_app.command("build")
def index_build(
    source_root: Path = typer.Option(
        Path("examples"),
        "--source-root",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Root directory containing cell-spec, cell-instances, and dataset subdirectories.",
    ),
    out: Path = typer.Option(Path(".battinfo/index.json"), help="Output index JSON path."),
    glob: str = typer.Option("*.json", help="File glob to include in index build."),
    validate: bool = typer.Option(False, "--validate/--no-validate", help="Validate records while indexing."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Build an index from canonical example resources."""
    fmt = _check_output_format(output_format)
    policy_name = _check_validation_policy(validation_policy)
    try:
        payload = api_build_index(
            source_root=source_root,
            out_path=out,
            glob=glob,
            validate=validate,
            validation_policy=policy_name,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    payload = {
        "status": "ok" if payload.get("failed", 0) == 0 else "partial",
        "index_path": str(out),
        "build_timestamp": payload.get("build_timestamp"),
        "cell_spec_count": payload.get("cell_spec_count", 0),
        "cell_instance_count": payload.get("cell_instance_count", 0),
        "test_count": payload.get("test_count", 0),
        "dataset_count": payload.get("dataset_count", 0),
        "total_count": payload.get("total_count", 0),
        "failed": payload.get("failed", 0),
    }
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table(
        [payload],
        [
            "status",
            "cell_spec_count",
            "cell_instance_count",
            "test_count",
            "dataset_count",
            "total_count",
            "failed",
            "index_path",
        ],
    )


@index_app.command("stats")
def index_stats(
    index_path: Path = typer.Option(
        Path(".battinfo/index.json"),
        "--index",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to index JSON built by `battinfo index build`.",
    ),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Show index statistics."""
    fmt = _check_output_format(output_format)
    payload = api_index_stats(index_path)
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table(
        [payload],
        ["cell_spec_count", "cell_instance_count", "test_count", "dataset_count", "total_count", "failed", "build_timestamp"],
    )


# ── registry commands ─────────────────────────────────────────────────────────

@registry_app.command("bootstrap")
def registry_bootstrap(
    tenant_id: str = typer.Option("battinfo", "--tenant-id", help="Tenant id to create or verify."),
    tenant_name: str = typer.Option("BattINFO", "--tenant-name", help="Tenant display name."),
    workspace_id: str = typer.Option(..., "--workspace-id", help="Workspace id to create or verify."),
    workspace_name: str | None = typer.Option(None, "--workspace-name", help="Workspace display name (defaults to workspace-id)."),
    publisher_id: str = typer.Option(..., "--publisher-id", help="Publisher id to create or verify."),
    publisher_name: str | None = typer.Option(None, "--publisher-name", help="Publisher display name (defaults to publisher-id)."),
    api_key_file: Path | None = typer.Option(None, "--api-key-file", help="File to write the publisher API key to. Env: BATTINFO_API_KEY_FILE."),
    registry_url: str | None = typer.Option(None, "--registry-url", help="Registry base URL. Env: BATTINFO_REGISTRY_URL."),
    admin_token: str | None = typer.Option(None, "--admin-token", help="Registry admin token. Env: BATTINFO_ADMIN_TOKEN."),
    output_format: str = typer.Option("text", "--format", help="Output format: json|text."),
) -> None:
    """Idempotently create a tenant, workspace, and publisher on the registry.

    Writes the publisher API key to --api-key-file (or BATTINFO_API_KEY_FILE)
    when a new publisher is created.  Safe to re-run; existing resources
    return HTTP 409 and are silently accepted.

    \b
    Required env vars (or pass as flags):
      BATTINFO_REGISTRY_URL    registry base URL
      BATTINFO_ADMIN_TOKEN     registry admin token
    """
    import json as _json
    import os
    import urllib.error
    import urllib.request

    resolved_url = registry_url or os.environ.get("BATTINFO_REGISTRY_URL", "").strip()
    if not resolved_url:
        typer.echo("Registry URL is required. Pass --registry-url or set BATTINFO_REGISTRY_URL.")
        raise typer.Exit(code=1)

    resolved_token = admin_token or os.environ.get("BATTINFO_ADMIN_TOKEN", "").strip()
    if not resolved_token:
        typer.echo("Admin token is required. Pass --admin-token or set BATTINFO_ADMIN_TOKEN.")
        raise typer.Exit(code=1)

    resolved_key_file: Path | None = api_key_file
    if resolved_key_file is None:
        env_path = os.environ.get("BATTINFO_API_KEY_FILE", "").strip()
        resolved_key_file = Path(env_path) if env_path else None

    def _api(method: str, path: str, data: dict) -> tuple[int, dict]:
        url = resolved_url.rstrip("/") + path
        body = _json.dumps(data).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Battinfo-Admin-Token": resolved_token,
        }
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, _json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, _json.loads(exc.read())

    results: dict[str, str] = {}

    # Tenant
    s, _ = _api("POST", "/tenants", {"tenant_id": tenant_id, "display_name": tenant_name})
    results["tenant"] = "created" if s in (200, 201) else "exists" if s == 409 else f"error-{s}"
    if s not in (200, 201, 409):
        typer.echo(f"Tenant creation failed [{s}]")
        raise typer.Exit(code=1)

    # Workspace
    s, _ = _api("POST", "/workspaces", {
        "workspace_id": workspace_id,
        "tenant_id": tenant_id,
        "display_name": workspace_name or workspace_id,
    })
    results["workspace"] = "created" if s in (200, 201) else "exists" if s == 409 else f"error-{s}"
    if s not in (200, 201, 409):
        typer.echo(f"Workspace creation failed [{s}]")
        raise typer.Exit(code=1)

    # Publisher
    s, body = _api("POST", "/publishers", {
        "publisher_id": publisher_id,
        "workspace_id": workspace_id,
        "display_name": publisher_name or publisher_id,
    })
    results["publisher"] = "created" if s in (200, 201) else "exists" if s == 409 else f"error-{s}"
    if s not in (200, 201, 409):
        typer.echo(f"Publisher creation failed [{s}]")
        raise typer.Exit(code=1)

    api_key: str | None = body.get("api_key") if s in (200, 201) else None

    if api_key and resolved_key_file:
        resolved_key_file.write_text(api_key, encoding="utf-8")
        results["api_key_file"] = str(resolved_key_file)

    fmt = _check_output_format(output_format)
    if fmt == "json":
        _emit_json({**results, "api_key": api_key})
        return

    for resource, status in results.items():
        typer.echo(f"  {resource:12s} {status}")
    if api_key:
        typer.echo(f"\n  API key: {api_key}")
        if resolved_key_file:
            typer.echo(f"  Saved to: {resolved_key_file}")
        else:
            typer.echo("  (pass --api-key-file or set BATTINFO_API_KEY_FILE to save it)")


# ── Dataset contribution commands ─────────────────────────────────────────────

@dataset_app.command("init")
def dataset_init(
    output: Path = typer.Argument(..., help="Path for the new contribution folder."),
    cell_name: str | None = typer.Option(None, "--cell-name", "-n", help="Short label for this cell (e.g. serial number)."),
    cell_spec_iri: str | None = typer.Option(None, "--cell-spec-iri", help="BattINFO cell-spec IRI."),
    lab: str | None = typer.Option(None, "--lab", help="Your institution or lab name."),
    license: str = typer.Option("CC-BY-4.0", "--license", help="Data licence identifier."),
    overwrite: bool = typer.Option(False, "--force", help="Overwrite an existing folder."),
) -> None:
    """Create a new dataset contribution folder with template and instructions.

    \b
    After running this command:
      1. Open battinfo.yaml and fill in the required fields.
      2. Put your CSV data files in the data/ sub-folder.
         Name them: YYYY-MM-DD__testtype__temperature.csv
         e.g. 2026-03-05__ici__25degC.csv
      3. Run:  battinfo dataset process <folder>
    """
    from battinfo.contribution import init_contribution

    try:
        path = init_contribution(
            output,
            cell_name=cell_name,
            cell_spec_iri=cell_spec_iri,
            lab=lab,
            license=license,
            overwrite=overwrite,
        )
    except (FileExistsError, OSError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Created contribution folder: {path}")
    typer.echo(f"  1. Edit {path / 'battinfo.yaml'}")
    typer.echo(f"  2. Add CSV files to {path / 'data'}/")
    typer.echo(f"  3. Run: battinfo dataset process {path}")


def _process_single_cell(
    folder: Path,
    *,
    clean: bool,
    validation_policy: str,
    console: Any,
    bundle: bool = True,
) -> tuple[bool, dict]:
    """Process one cell contribution folder.  Returns (success, result_dict)."""
    from rich import box
    from rich.table import Table

    from battinfo.contribution import process_contribution

    try:
        result = process_contribution(
            folder, clean=clean, validation_policy=validation_policy, bundle=bundle,
        )
    except FileNotFoundError as exc:
        console.print(f"  [red]Error:[/red] {exc}")
        return False, {}
    except (RuntimeError, ValueError) as exc:
        console.print(f"  [red]Error:[/red] {exc}")
        return False, {}

    if result["errors"]:
        console.print("  [red]Manifest errors -- fix battinfo.yaml:[/red]")
        for err in result["errors"]:
            console.print(f"    x  {err}")
        return False, result

    files = result["files"]
    conversions: dict = result.get("conversions") or {}
    if not files:
        console.print("  [yellow]Warning:[/yellow] No data files found in data/")
    else:
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold",
                      show_edge=False, pad_edge=True)
        table.add_column("File")
        table.add_column("Test type")
        table.add_column("Temp")
        table.add_column("Date")
        table.add_column("BDF")
        table.add_column("")
        for f in files:
            ok = f["recognised"]
            bdf_result = conversions.get(f["name"])
            if f["name"] not in conversions:
                bdf_cell = "--"
            elif bdf_result:
                bdf_cell = "[green]ok[/green]"
            else:
                bdf_cell = "[yellow]skip[/yellow]"
            table.add_row(
                f["name"],
                f["label"] if ok else "--",
                f["temp"] or "--",
                f["date"] or "--",
                bdf_cell,
                "[green]ok[/green]" if ok else "[yellow]?[/yellow]",
            )
        console.print(table)

    if result.get("needs_review"):
        annotations_path = result.get("annotations_path", "battinfo-annotations.yaml")
        console.print(f"  [yellow]Action needed:[/yellow] fill in '?' entries in {Path(annotations_path).name}")

    build = result.get("build")
    if not bundle:
        file_count = len([f for f in files if f["recognised"]])
        bdf_count = sum(1 for v in conversions.values() if v)
        bdf_note = f", {bdf_count} converted to BDF" if conversions else ""
        console.print(f"  [green]OK[/green]  {file_count} file(s) recognised{bdf_note}")
        return True, result
    if build:
        counts = build.get("counts", {})
        console.print(
            f"  [green]OK[/green]  "
            f"{counts.get('datasets', 0)} dataset(s), "
            f"{counts.get('tests', 0)} test(s)"
        )
        return True, result
    else:
        console.print("  [red]Build did not complete.[/red]")
        return False, result


@dataset_app.command("process")
def dataset_process(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    clean: bool = typer.Option(False, "--force", help="Rebuild from scratch."),
    validation_policy: str = typer.Option("strict", "--validation-policy", help="strict|set|quick"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
) -> None:
    """Validate metadata, infer tests from data files, and build the submission package.

    Accepts either a single cell folder (with battinfo.yaml) or a batch
    folder (with batch.yaml).  When given a batch folder, all cell
    sub-folders are processed automatically.
    """
    from rich.console import Console

    from battinfo.contribution import BATCH_MANIFEST, CONTRIBUTION_MANIFEST

    console = Console(highlight=False, quiet=json_output)

    # ── Batch directory: iterate all cell sub-folders ──────────────────────────
    if (folder / BATCH_MANIFEST).exists():
        cell_dirs = sorted(
            d for d in folder.iterdir()
            if d.is_dir() and (d / CONTRIBUTION_MANIFEST).exists()
        )
        if not cell_dirs:
            if json_output:
                typer.echo(json.dumps({"ok": True, "cells": [], "ok_count": 0, "fail_count": 0}))
            else:
                console.print("[yellow]No cell folders with battinfo.yaml found.[/yellow]")
            raise typer.Exit(code=0)

        if not json_output:
            console.print()
            console.print(f"[bold]Batch:[/bold] {folder.name}  ({len(cell_dirs)} cell(s))")
            console.print()

        ok_count = 0
        fail_count = 0
        cell_results = []

        for i, cell_dir in enumerate(cell_dirs, 1):
            if not json_output:
                console.print(f"[bold][{i}/{len(cell_dirs)}][/bold] {cell_dir.name}")
            success, cell_result = _process_single_cell(
                cell_dir, clean=clean, validation_policy=validation_policy,
                console=console, bundle=False,
            )
            if json_output:
                cell_results.append({
                    "folder": cell_dir.name,
                    "ok": success,
                    "files": len(cell_result.get("files", [])),
                    "needs_review": cell_result.get("needs_review", False),
                    "errors": cell_result.get("errors", []),
                    "conversions": {k: bool(v) for k, v in cell_result.get("conversions", {}).items()},
                })
            if success:
                ok_count += 1
            else:
                fail_count += 1
            if not json_output:
                console.print()

        if json_output:
            typer.echo(json.dumps({
                "ok": fail_count == 0,
                "ok_count": ok_count,
                "fail_count": fail_count,
                "cells": cell_results,
            }))
        else:
            if fail_count == 0:
                console.print(f"[green]All {ok_count} cell(s) processed successfully.[/green]")
                console.print()
                console.print("Build Zenodo package with:")
                console.print(f"  [bold]battinfo batch package {folder} --creator \"Name; Institution\"[/bold]")
            else:
                console.print(
                    f"[green]{ok_count} ok[/green]  [red]{fail_count} failed[/red] -- "
                    "fix the errors above and re-run."
                )

        if fail_count > 0:
            raise typer.Exit(code=1)
        console.print()
        return

    # ── Single cell folder ─────────────────────────────────────────────────────
    if not (folder / CONTRIBUTION_MANIFEST).exists():
        if json_output:
            typer.echo(json.dumps({"ok": False, "error": f"No {CONTRIBUTION_MANIFEST} found in {folder}"}))
        else:
            console.print(
                f"[red]Error:[/red] No {CONTRIBUTION_MANIFEST} found in {folder}. "
                "Run `battinfo dataset init` to create one, or point at a batch folder."
            )
        raise typer.Exit(code=1)

    if not json_output:
        console.print()
        console.print("[bold]BattINFO Dataset Processor[/bold]")
        console.print()

    success, cell_result = _process_single_cell(folder, clean=clean, validation_policy=validation_policy, console=console)

    if json_output:
        typer.echo(json.dumps({
            "ok": success,
            "folder": str(folder),
            "files": len(cell_result.get("files", [])),
            "needs_review": cell_result.get("needs_review", False),
            "errors": cell_result.get("errors", []),
        }))
    else:
        if not success:
            raise typer.Exit(code=1)
        console.print("Ready to publish. Run:")
        console.print(f"  [bold]battinfo dataset publish {folder} --zenodo --token YOUR_TOKEN[/bold]")
        console.print()

    if not success:
        raise typer.Exit(code=1)


@dataset_app.command("publish")
def dataset_publish(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    zenodo: bool = typer.Option(False, "--zenodo", help="Publish to Zenodo (creates a draft deposit)."),
    sandbox: bool = typer.Option(False, "--sandbox", help="Use the Zenodo sandbox (for testing)."),
    token: str | None = typer.Option(None, "--token", help="Zenodo API token. Env: ZENODO_TOKEN."),
    community: str = typer.Option("battery-genome", "--community", help="Zenodo community identifier."),
    no_community: bool = typer.Option(False, "--no-community", help="Skip community submission."),
) -> None:
    """Publish the processed contribution folder.

    \b
    Options:
      --zenodo      Upload to Zenodo (creates a draft for your review)
      --sandbox     Use the Zenodo sandbox for testing
      --token       Your Zenodo personal access token
                    (or set the ZENODO_TOKEN environment variable)

    Get a Zenodo token at:
      https://zenodo.org/account/settings/applications/tokens/new/
      Required scopes: deposit:write
    """
    import os

    from rich.console import Console

    from battinfo.contribution import publish_to_zenodo

    console = Console()

    if not zenodo:
        console.print("[yellow]Nothing to do.[/yellow] Pass --zenodo to upload to Zenodo.")
        raise typer.Exit(code=0)

    resolved_token = token or os.environ.get("ZENODO_TOKEN", "").strip()
    if not resolved_token:
        console.print("[red]Error:[/red] Zenodo token required. Pass --token or set ZENODO_TOKEN.")
        raise typer.Exit(code=1)

    resolved_community = "" if no_community else community

    console.print()
    console.print(f"[bold]Uploading to {'Zenodo Sandbox' if sandbox else 'Zenodo'}...[/bold]")
    console.print()

    try:
        result = publish_to_zenodo(
            folder,
            token=resolved_token,
            sandbox=sandbox,
            community=resolved_community,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except Exception as exc:
        console.print(f"[red]Upload failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print("[green]Deposit created (draft).[/green]")
    console.print(f"  DOI:     {result.get('doi') or '(assigned on publication)'}")
    console.print(f"  Files:   {result['files_uploaded']} uploaded")
    console.print("  Review and publish at:")
    console.print(f"  [bold]{result['deposit_url']}[/bold]")
    console.print()
    console.print("The deposit is a [bold]draft[/bold] -- review it on Zenodo before clicking Publish.")
    console.print()


# ── batch commands ─────────────────────────────────────────────────────────────

@batch_app.command("init")
def batch_init(
    output_dir: Path = typer.Argument(..., help="Directory to create for this batch."),
    cell_spec: str = typer.Option(..., "--cell-spec", "-t", help='Cell type IRI or name, e.g. "Energizer CR2032".'),
    count: int = typer.Option(..., "--count", "-n", help="Number of cells received."),
    batch_id: str | None = typer.Option(None, "--batch-id", help="Batch / lot identifier."),
    lab: str | None = typer.Option(None, "--lab", help="Institution or lab name."),
    operator: str | None = typer.Option(None, "--operator", help="Person who operated the test equipment."),
    project: str | None = typer.Option(None, "--project", help="Project name or ID this batch belongs to."),
    license: str = typer.Option("CC-BY-4.0", "--license", help="SPDX licence identifier."),
    iris: str | None = typer.Option(
        None,
        "--iris",
        help="Comma-separated list of pre-assigned BattINFO cell IRIs (one per cell).",
    ),
    serials: str | None = typer.Option(
        None,
        "--serials",
        help="Comma-separated serial numbers (one per cell, used as folder names).",
    ),
    overwrite: bool = typer.Option(False, "--force", help="Overwrite an existing output directory."),
) -> None:
    """Scaffold a multi-cell batch directory.

    \b
    Creates one sub-folder per cell, each with:
      battinfo.yaml   <- pre-filled cell identity and provenance
      data/           <- drop raw CSV/data files here
      photos/         <- optional microscopy or label images

    \b
    After running this command:
      1. Drop data files into each cell's  data/  folder.
         Name them: YYYY-MM-DD__testtype__temperature.csv
         e.g. 2025-06-01__capacity_check__25degC.csv
      2. Edit battinfo.yaml in each cell folder if you have more metadata.
      3. Process each cell:  battinfo dataset process <cell-folder>
    """
    from battinfo.contribution import init_batch

    cell_iris_list = [s.strip() for s in iris.split(",")] if iris else None
    serial_list = [s.strip() for s in serials.split(",")] if serials else None

    try:
        result = init_batch(
            output_dir,
            cell_spec=cell_spec,
            count=count,
            batch_id=batch_id,
            lab=lab,
            operator=operator,
            project=project,
            license=license,
            cell_iris=cell_iris_list,
            serial_numbers=serial_list,
            overwrite=overwrite,
        )
    except (FileExistsError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Initialised batch: {result['output_dir']}")
    typer.echo(f"  Cell type : {result['cell_spec_name']}  ({result['cell_spec_iri']})")
    typer.echo(f"  Cells     : {result['count']}")
    typer.echo()
    for cell in result["cells"]:
        iri_note = f"  [{cell['cell_iri']}]" if cell.get("cell_iri") else ""
        typer.echo(f"  {cell['folder']}/  {iri_note}")
    typer.echo()
    typer.echo("Next steps:")
    typer.echo("  1. Drop data files into each cell's  data/  sub-folder.")
    typer.echo(f"  2. Run:  battinfo dataset process {output_dir}/<cell-folder>")


@batch_app.command("add")
def batch_add(
    batch_dir: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, help="Existing batch directory."),
    count: int = typer.Option(..., "--count", "-n", help="Number of additional cells to add."),
    batch_id: str | None = typer.Option(None, "--batch-id", help="Override batch / lot ID for the new cells."),
    lab: str | None = typer.Option(None, "--lab", help="Override lab name for the new cells."),
    operator: str | None = typer.Option(None, "--operator", help="Override operator for the new cells."),
    project: str | None = typer.Option(None, "--project", help="Override project for the new cells."),
    license: str | None = typer.Option(None, "--license", help="Override SPDX licence for the new cells."),
    iris: str | None = typer.Option(
        None,
        "--iris",
        help="Comma-separated pre-assigned BattINFO cell IRIs for the new cells.",
    ),
    serials: str | None = typer.Option(
        None,
        "--serials",
        help="Comma-separated serial numbers for the new cells.",
    ),
) -> None:
    """Add more cells to an existing batch directory.

    \b
    Reads batch.yaml to inherit cell type, lab, operator, and project.
    New cells are numbered after the existing ones.
    Provide --batch-id / --operator / --project to override for the new cells.
    Updates the count in batch.yaml automatically.
    """
    from battinfo.contribution import add_to_batch

    cell_iris_list = [s.strip() for s in iris.split(",")] if iris else None
    serial_list = [s.strip() for s in serials.split(",")] if serials else None

    try:
        result = add_to_batch(
            batch_dir,
            count,
            batch_id=batch_id,
            lab=lab,
            operator=operator,
            project=project,
            license=license,
            cell_iris=cell_iris_list,
            serial_numbers=serial_list,
        )
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Added {result['added']} cell(s) to {result['batch_dir']}")
    typer.echo(f"  Cell type  : {result['cell_spec_name']}  ({result['cell_spec_iri']})")
    typer.echo(f"  New total  : {result['total_count']}")
    typer.echo()
    for cell in result["new_cells"]:
        iri_note = f"  [{cell['cell_iri']}]" if cell.get("cell_iri") else ""
        typer.echo(f"  {cell['folder']}/  {iri_note}")
    typer.echo()
    typer.echo("Next steps:")
    typer.echo("  1. Drop data files into each new cell folder.")
    typer.echo(f"  2. Run:  battinfo dataset process {batch_dir}")


@batch_app.command("status")
def batch_status(
    batch_dir: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, help="Batch directory."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
) -> None:
    """Show the current state of a batch at a glance.

    Reports how many cells have data, how many are annotated, BDF conversion
    status, and what to run next.
    """
    import re as _re

    from rich.console import Console

    from battinfo.contribution import (
        BATCH_MANIFEST,
        CONTRIBUTION_MANIFEST,
        _collect_data_files,
        _scan_data_files,
        load_batch_manifest,
    )

    console = Console(highlight=False)

    if not (batch_dir / BATCH_MANIFEST).exists():
        msg = f"No {BATCH_MANIFEST} found. Is this a batch directory?"
        if json_output:
            typer.echo(json.dumps({"ok": False, "error": msg}))
        else:
            console.print(f"[red]Error:[/red] {msg}")
        raise typer.Exit(code=1)

    manifest = load_batch_manifest(batch_dir)
    cell_dirs = sorted(
        d for d in batch_dir.iterdir()
        if d.is_dir() and (d / CONTRIBUTION_MANIFEST).exists()
    )
    total = len(cell_dirs)

    _DATE_RE = _re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})")
    has_data = sum(1 for d in cell_dirs if _scan_data_files(d))
    needs_annotation = 0
    bdf_pending = 0
    for d in cell_dirs:
        raw_files = _scan_data_files(d)
        if not raw_files:
            continue
        if any(not _DATE_RE.search(f.name) for f in raw_files):
            needs_annotation += 1
        pairs = _collect_data_files(d)
        if any(bdf is None for _, bdf in pairs):
            bdf_pending += 1

    staging_exists = (batch_dir / "staging").exists()

    if has_data < total:
        next_cmd = f"battinfo dataset process {batch_dir}"
    elif needs_annotation > 0:
        next_cmd = f"battinfo dataset process {batch_dir}"
    elif not staging_exists:
        next_cmd = f"battinfo batch package {batch_dir}"
    else:
        next_cmd = f"battinfo batch upload {batch_dir / 'staging'} --token $ZENODO_TOKEN --sandbox"

    if json_output:
        typer.echo(json.dumps({
            "batch_dir": str(batch_dir),
            "cell_spec": manifest.get("cell_spec_name", manifest.get("cell_spec_iri")),
            "total_cells": total,
            "cells_with_data": has_data,
            "needs_annotation": needs_annotation,
            "bdf_pending": bdf_pending,
            "staged": staging_exists,
            "ok": True,
            "ready": has_data == total and needs_annotation == 0 and staging_exists,
            "next_command": next_cmd,
        }))
        return

    def _status(ok: bool) -> str:
        return "[green]ok[/green]" if ok else "[yellow]--[/yellow]"

    console.print()
    console.print(f"[bold]Batch:[/bold] {batch_dir.name}")
    console.print(f"  Cell type  : {manifest.get('cell_spec_name', manifest.get('cell_spec_iri', '?'))}")
    console.print(f"  Cells      : {total}")
    console.print()
    console.print(f"  Cells with data      : {has_data}/{total}  {_status(has_data == total)}")
    console.print(f"  Need annotation      : {needs_annotation}/{total}  {_status(needs_annotation == 0)}")
    console.print(f"  BDF conversion done  : {total - bdf_pending}/{total}  {_status(bdf_pending == 0)}")
    console.print(f"  Package staged       : {'yes' if staging_exists else 'no'}  {_status(staging_exists)}")
    console.print()
    console.print(f"[bold]Next:[/bold]  {next_cmd}")
    console.print()


@batch_app.command("package")
def batch_package(
    batch_dir: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, help="Batch directory created by `batch init`."),
    staging_dir: Path | None = typer.Option(None, "--staging", "-s", help="Output directory for the Zenodo package. Default: <batch-dir>/staging/."),
    creator: list[str] | None = typer.Option(
        None,
        "--creator",
        "-c",
        help='Creator: "Family, Given; Affiliation". Repeat for multiple. Falls back to `battinfo config set creator`.',
    ),
    community: str | None = typer.Option(None, "--community", help="Zenodo community. Default: value from config or battinfo-reference."),
    no_community: bool = typer.Option(False, "--no-community", help="Skip community submission."),
    placeholder: str = typer.Option("ZENODO_RECORD_ID", "--placeholder", help="Placeholder token for Zenodo record ID in URLs."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
) -> None:
    """Build a flat Zenodo upload package from a batch of cells.

    \b
    Discovers all cell sub-folders, collects raw data files, and produces:
      staging/
        battinfo.bundle.json    <- harvest ingestion target
        battinfo.publish.jsonld <- full semantic graph
        ro-crate-metadata.json  <- file inventory with placeholder URLs
        dataset-001.csv         <- raw cycler files (canonical naming)
        dataset-001.bdf.parquet <- BDF converted (if present)
        ...

    \b
    After packaging, upload with:
      battinfo batch upload <staging-dir> --token $ZENODO_TOKEN --sandbox
    """
    from battinfo.config import load_user_config, resolve_creators
    from battinfo.contribution import package_batch

    creators = resolve_creators(creator)
    if not creators:
        typer.echo(
            "Error: no creator specified. Pass --creator or run:\n"
            "  battinfo config set creator \"Family, Given; Institution\"",
            err=True,
        )
        raise typer.Exit(code=1)

    cfg = load_user_config()
    effective_community = None if no_community else (community or cfg.get("community", "battinfo-reference"))

    try:
        result = package_batch(
            batch_dir,
            staging_dir,
            creators=creators,
            community=effective_community,
            zenodo_record_id_placeholder=placeholder,
        )
    except (FileNotFoundError, ValueError) as exc:
        if json_output:
            typer.echo(json.dumps({"ok": False, "error": str(exc)}))
        else:
            typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    staging = result["staging_dir"]
    if json_output:
        typer.echo(json.dumps({
            "ok": True,
            "staging_dir": staging,
            "cell_count": result["cell_count"],
            "entry_count": result["entry_count"],
            "file_count": len(result["staged_data_files"]),
            "files": [Path(staging, f).name for f in result["staged_data_files"]],
        }))
        return

    typer.echo(f"Package built: {staging}")
    typer.echo(f"  Cells       : {result['cell_count']}")
    typer.echo(f"  Datasets    : {result['entry_count']}")
    typer.echo(f"  Data files  : {len(result['staged_data_files'])}")
    typer.echo()
    typer.echo("Files in staging directory:")
    for fname in sorted(Path(staging).iterdir()):
        typer.echo(f"  {fname.name}")
    typer.echo()
    typer.echo("Upload to Zenodo sandbox with:")
    typer.echo(f"  battinfo batch upload {staging} --token $ZENODO_TOKEN --sandbox")


@batch_app.command("upload")
def batch_upload(
    staging_dir: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True, help="Staging directory produced by `batch package`."),
    token: str | None = typer.Option(None, "--token", help="Zenodo API token. Env: ZENODO_API_TOKEN."),
    sandbox: bool = typer.Option(False, "--sandbox", help="Use Zenodo sandbox (sandbox.zenodo.org)."),
    community: str | None = typer.Option(None, "--community", help="Zenodo community. Default: value from config or battinfo-reference."),
    no_community: bool = typer.Option(False, "--no-community", help="Skip community submission."),
    creator: list[str] | None = typer.Option(
        None,
        "--creator",
        "-c",
        help='Creator: "Family, Given; Affiliation". Repeat for multiple. Falls back to `battinfo config set creator`.',
    ),
    publish: bool = typer.Option(False, "--publish", help="Publish immediately (default: leave as draft)."),
    placeholder: str = typer.Option("ZENODO_RECORD_ID", "--placeholder", help="Placeholder token used in package."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
) -> None:
    """Upload a staged Zenodo package to Zenodo (or sandbox).

    \b
    Workflow:
      1. Creates an empty deposit to obtain the pre-reserved record ID.
      2. Patches placeholder URLs in staged files with the real record ID.
      3. Uploads all files to the deposit.
      4. Sets metadata (title, keywords, community, creators).
      5. Leaves as draft for review, or publishes if --publish is set.

    \b
    The deposit URL is printed at the end -- open it to review and publish.
    """

    from battinfo.config import load_user_config, resolve_creators, resolve_zenodo_token
    from battinfo.zenodo import upload_zenodo_package

    resolved_token = resolve_zenodo_token(token)
    if not resolved_token:
        typer.echo(
            "Error: Zenodo token required. Pass --token, set ZENODO_API_TOKEN, or run:\n"
            "  battinfo config set zenodo_token <token>",
            err=True,
        )
        raise typer.Exit(code=1)

    creators = resolve_creators(creator)
    if not creators:
        typer.echo(
            "Error: no creator specified. Pass --creator or run:\n"
            "  battinfo config set creator \"Family, Given; Institution\"",
            err=True,
        )
        raise typer.Exit(code=1)

    cfg = load_user_config()
    effective_community = None if no_community else (community or cfg.get("community", "battinfo-reference"))

    if not json_output:
        target = "Zenodo Sandbox" if sandbox else "Zenodo"
        typer.echo(f"Uploading to {target}...")

    try:
        result = upload_zenodo_package(
            staging_dir,
            creators,
            token=resolved_token,
            sandbox=sandbox,
            community=effective_community,
            publish=publish,
            zenodo_record_id_placeholder=placeholder,
        )
    except Exception as exc:
        if json_output:
            typer.echo(json.dumps({"ok": False, "error": str(exc)}))
        else:
            typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(json.dumps({
            "ok": True,
            "record_id": result.get("record_id"),
            "doi": result.get("doi"),
            "deposit_url": result.get("deposit_url"),
            "files": len(result.get("uploaded_files", [])),
            "published": result.get("published", False),
        }))
        return

    typer.echo()
    typer.echo("[OK] Deposit created.")
    typer.echo(f"  Record ID  : {result['record_id']}")
    typer.echo(f"  DOI        : {result['doi']}")
    typer.echo(f"  Files      : {len(result['uploaded_files'])}")
    typer.echo(f"  Published  : {'yes' if result['published'] else 'no (draft)'}")
    typer.echo()
    typer.echo("Review at:")
    typer.echo(f"  {result['deposit_url']}")
    if not result["published"]:
        typer.echo()
        typer.echo("The deposit is a draft. Review it on Zenodo before clicking Publish.")


# ── Push (end-to-end single command) ──────────────────────────────────────────

@app.command("push")
def push(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True,
                                  help="Folder containing raw data files or an existing batch."),
    cell_spec: str | None = typer.Option(None, "--cell-spec", "-t",
                                         help="Cell type, e.g. 'Energizer CR2032'. Required for unstructured folders."),
    cells: int | None = typer.Option(None, "--cells", "-n",
                                     help="Number of cells (auto-detected from filenames if omitted)."),
    batch_id: str | None = typer.Option(None, "--batch-id", help="Batch / lot identifier."),
    lab: str | None = typer.Option(None, "--lab", help="Lab name."),
    operator: str | None = typer.Option(None, "--operator", help="Operator name."),
    creator: list[str] | None = typer.Option(None, "--creator", "-c",
                                              help='Creator: "Family, Given; Affiliation". Falls back to config.'),
    token: str | None = typer.Option(None, "--token", help="Zenodo API token. Falls back to config / ZENODO_API_TOKEN."),
    sandbox: bool = typer.Option(False, "--sandbox", help="Upload to sandbox.zenodo.org instead of production."),
    community: str | None = typer.Option(None, "--community", help="Zenodo community. Default: from config."),
    no_community: bool = typer.Option(False, "--no-community", help="Skip community submission."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Package only — do not upload."),
    staging: Path | None = typer.Option(None, "--staging", help="Override staging directory."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
) -> None:
    """Publish battery data to Zenodo in one command.

    \b
    Accepts three layouts:
      battinfo push ./flat_files/    --cell-spec "Energizer CR2032"   # groups by filename
      battinfo push ./cell_folders/  --cell-spec "Energizer CR2032"   # one subdir per cell
      battinfo push ./my_batch/                                        # existing batch.yaml

    \b
    One-time setup:
      battinfo config set creator "Family, Given; Institution"
      battinfo config set zenodo_token <token>
    """
    from rich.console import Console

    from battinfo.config import load_user_config, resolve_creators, resolve_zenodo_token
    from battinfo.contribution import BATCH_MANIFEST, _group_files_by_cell, push_batch

    console = Console(highlight=False)
    cfg = load_user_config()

    def _err(msg: str) -> None:
        if json_output:
            typer.echo(json.dumps({"ok": False, "error": msg}))
        else:
            console.print(f"[red]Error:[/red] {msg}")
        raise typer.Exit(code=1)

    creators = resolve_creators(creator)
    if not creators:
        _err('no creator specified. Pass --creator or run: battinfo config set creator "Family, Given; Institution"')

    resolved_token = resolve_zenodo_token(token)
    if not dry_run and not resolved_token:
        _err("Zenodo token required. Pass --token or run: battinfo config set zenodo_token <token>")

    effective_community = None if no_community else (community or cfg.get("community", "battinfo-reference"))

    # ── Preview (human mode only) ──────────────────────────────────────────────
    is_batch = (folder / BATCH_MANIFEST).exists()
    if not is_batch and not cell_spec:
        msg = "--cell-spec is required for unstructured folders."
        if json_output:
            typer.echo(json.dumps({"ok": False, "error": msg}))
        else:
            console.print(f"[red]Error:[/red] {msg}")
        raise typer.Exit(code=1)

    if not json_output:
        console.print()
        console.print(f"[bold]Push:[/bold] {folder}")
        if cell_spec:
            console.print(f"  Cell type : {cell_spec}")
        if not is_batch:
            groups = _group_files_by_cell(folder)
            if groups:
                file_count = sum(len(v) for v in groups.values())
                console.print(f"  Cells     : {len(groups)} (detected from {file_count} file(s))")
                for key, files in list(groups.items())[:4]:
                    console.print(f"    Cell {key}: {', '.join(f.name for f in files[:3])}" +
                                   ("..." if len(files) > 3 else ""))
                if len(groups) > 4:
                    console.print(f"    ... and {len(groups) - 4} more cells")
        creator_str = ", ".join(c["name"] for c in creators)
        console.print(f"  Creator(s): {creator_str}")
        target = "Zenodo Sandbox" if sandbox else "Zenodo"
        console.print(f"  Upload to : {'(dry run)' if dry_run else target}")
        console.print()

    # Skip confirm when --json, --yes, dry-run, or non-interactive (piped/agent)
    import sys as _sys
    non_interactive = json_output or yes or dry_run or not _sys.stdin.isatty()
    if not non_interactive:
        confirm = typer.confirm("Proceed?", default=False)
        if not confirm:
            console.print("Aborted.")
            raise typer.Exit(code=0)

    # ── Execute ────────────────────────────────────────────────────────────────
    try:
        result = push_batch(
            folder,
            cell_spec=cell_spec,
            staging_dir=staging,
            creators=creators,
            zenodo_token=resolved_token,
            sandbox=sandbox,
            community=effective_community,
            confirm=False,
            dry_run=dry_run,
            n_cells=cells,
            batch_id=batch_id,
            lab=lab,
            operator=operator,
        )
    except (FileNotFoundError, ValueError) as exc:
        if json_output:
            typer.echo(json.dumps({"ok": False, "error": str(exc)}))
        else:
            console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(json.dumps({
            "ok": True,
            "status": result.get("status"),
            "cells": result.get("cells"),
            "files": result.get("files"),
            "staging_dir": result.get("staging_dir"),
            "zenodo_url": result.get("zenodo_url"),
        }))
        return

    console.print(f"[green]Done.[/green]  {result['cells']} cell(s), {result['files']} dataset(s)")
    console.print(f"  Staging : {result['staging_dir']}")
    if result.get("zenodo_url"):
        console.print(f"  Draft   : {result['zenodo_url']}")
        console.print()
        console.print("Review and publish at the URL above.")
    elif dry_run:
        console.print()
        console.print("Dry run complete. Upload with:")
        console.print(f"  battinfo batch upload {result['staging_dir']} --sandbox")
    console.print()


# ── Config commands ────────────────────────────────────────────────────────────

@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key: creator, license, community, zenodo_token."),
    value: str = typer.Argument(..., help="Value to store."),
) -> None:
    """Set a user preference that is applied as the default across all commands.

    \b
    Examples:
      battinfo config set creator "Clark, Simon; SINTEF"
      battinfo config set creator "Clark, Simon; SINTEF | Smith, Jane; NTNU"
      battinfo config set license CC-BY-4.0
      battinfo config set community battinfo-reference
    """
    from battinfo.config import USER_CONFIG_PATH, set_user_config_value
    try:
        set_user_config_value(key, value)
        typer.echo(f"Set {key} = {value!r}  (saved to {USER_CONFIG_PATH})")
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@config_app.command("show")
def config_show() -> None:
    """Show current user preferences."""
    from battinfo.config import USER_CONFIG_PATH, load_user_config
    cfg = load_user_config()
    if not cfg:
        typer.echo(f"No config file at {USER_CONFIG_PATH}")
        typer.echo("Set defaults with: battinfo config set creator \"Family, Given; Institution\"")
        return
    typer.echo(f"Config file: {USER_CONFIG_PATH}")
    typer.echo()
    for k, v in sorted(cfg.items()):
        typer.echo(f"  {k}: {v}")


# ---------------------------------------------------------------------------
# specs — discover valid spec property names and accepted units
# ---------------------------------------------------------------------------

_SPEC_CATEGORIES: dict[str, str] = {
    "nominal_capacity": "capacity",
    "minimum_capacity": "capacity",
    "min_capacity": "capacity",
    "rated_capacity": "capacity",
    "typical_energy": "energy",
    "rated_energy": "energy",
    "nominal_energy": "energy",
    "specific_energy": "energy",
    "energy_density": "energy",
    "nominal_voltage": "voltage",
    "charging_voltage": "voltage",
    "discharging_cutoff_voltage": "voltage",
    "specific_power": "power",
    "power_density": "power",
    "internal_resistance": "resistance",
    "impedance": "resistance",
    "dc_internal_resistance": "resistance",
    "mass": "mass/dimensions",
    "volume": "mass/dimensions",
    "diameter": "mass/dimensions",
    "height": "mass/dimensions",
    "width": "mass/dimensions",
    "length": "mass/dimensions",
    "thickness": "mass/dimensions",
    "pulse_charging_current": "current",
    "continuous_charging_current": "current",
    "nominal_continuous_charging_current": "current",
    "maximum_continuous_charging_current": "current",
    "pulse_discharging_current": "current",
    "continuous_discharging_current": "current",
    "nominal_continuous_discharging_current": "current",
    "maximum_continuous_discharging_current": "current",
    "charging_time": "time",
    "minimum_charging_temperature": "temperature",
    "maximum_charging_temperature": "temperature",
    "charging_temperature_min": "temperature",
    "charging_temperature_max": "temperature",
    "minimum_discharging_temperature": "temperature",
    "maximum_discharging_temperature": "temperature",
    "discharging_temperature_min": "temperature",
    "discharging_temperature_max": "temperature",
    "minimum_storage_temperature": "temperature",
    "maximum_storage_temperature": "temperature",
    "storage_temperature_min": "temperature",
    "storage_temperature_max": "temperature",
    "cycle_life": "lifecycle",
    "calendar_life": "lifecycle",
}


def _all_specs_data() -> list[dict[str, Any]]:
    from battinfo.validate.schema import schema_for_rel_path
    from battinfo.validate.semantic import SPEC_UNIT_COMPATIBILITY

    schema = schema_for_rel_path("cell-canonical.schema.json")
    all_names = sorted(schema["$defs"]["SpecSet"]["properties"].keys())
    rows = []
    for name in all_names:
        units = SPEC_UNIT_COMPATIBILITY.get(name)
        if units:
            ascii_units = sorted(u for u in units if u.isascii())
            display_units = ", ".join(ascii_units) if ascii_units else ", ".join(sorted(units))
        else:
            display_units = "any"
        rows.append({
            "name": name,
            "category": _SPEC_CATEGORIES.get(name, "other"),
            "valid_units": display_units,
        })
    return rows


@specs_app.command("list")
def specs_list(
    category: str | None = typer.Option(None, help="Filter by category (e.g. capacity, voltage, current)."),
    output_format: str = typer.Option("table", "--format", help="Output format: table|json."),
) -> None:
    """List all valid spec property names with their accepted units."""
    fmt = _check_output_format(output_format)
    rows = _all_specs_data()
    if category:
        rows = [r for r in rows if r["category"] == category]
        if not rows:
            typer.echo(f"No specs found for category '{category}'.")
            raise typer.Exit(code=1)
    if fmt == "json":
        _emit_json(rows)
        return
    _emit_table(rows, ["name", "category", "valid_units"])


@specs_app.command("show")
def specs_show(
    name: str = typer.Argument(..., help="Spec property name (e.g. nominal_capacity)."),
    output_format: str = typer.Option("table", "--format", help="Output format: table|json."),
) -> None:
    """Show valid units and an example entry for a single spec property."""
    from battinfo.validate.semantic import SPEC_UNIT_COMPATIBILITY

    fmt = _check_output_format(output_format)
    rows = _all_specs_data()
    match = next((r for r in rows if r["name"] == name), None)
    if match is None:
        typer.echo(f"Unknown spec '{name}'. Run 'battinfo specs list' to see all valid names.")
        raise typer.Exit(code=1)

    units = SPEC_UNIT_COMPATIBILITY.get(name)
    canonical_unit = sorted(units)[0] if units else "<unit>"
    example = {"value": 0.0, "unit": canonical_unit}

    detail = {
        "name": match["name"],
        "category": match["category"],
        "valid_units": match["valid_units"],
        "example": {match["name"]: example},
    }
    if fmt == "json":
        _emit_json(detail)
        return
    typer.echo(f"name:        {detail['name']}")
    typer.echo(f"category:    {detail['category']}")
    typer.echo(f"valid units: {detail['valid_units']}")
    typer.echo(f"example:     {json.dumps(detail['example'])}")
