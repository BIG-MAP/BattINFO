from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from battinfo.runtime import recover_notebook_runtime
from battinfo.api import (
    CellSpecificationInput,
    CellInstanceInput,
    CellTypeInput,
    DatasetInput,
    TestInput,
    build_cell_type_library_rdf as api_build_cell_type_library_rdf,
    build_index as api_build_index,
    create_cell_instance as api_create_cell_instance,
    create_cell_type_from_datasheet as api_create_cell_type_from_datasheet,
    index_stats as api_index_stats,
    publish_batch as api_publish_batch,
    publish_record as api_publish_record,
    query_cell_instances as api_query_cell_instances,
    query_library_cell_types as api_query_library_cell_types,
    query_tests as api_query_tests,
    query_cell_types as api_query_cell_types,
    query_datasets as api_query_datasets,
    save_batch as api_save_batch,
    save_cell_instance as api_save_cell_instance,
    save_cell_type as api_save_cell_type,
    save_dataset as api_save_dataset,
    save_library_cell_type as api_save_library_cell_type,
    save_test as api_save_test,
    save_record as api_save_record,
    template_cell_specification as api_template_cell_specification,
    template_cell_instance as api_template_cell_instance,
    template_cell_type as api_template_cell_type,
    template_dataset as api_template_dataset,
    template_test as api_template_test,
)
from battinfo.local_workspace import LocalWorkspace
from battinfo.workflows.map import run_mapping
from battinfo.validate import get_validation_policy
from battinfo.validate.pydantic import validate_json
from battinfo.validate.record import validate_record

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
workspace_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Author BattINFO workspaces on disk.")
notebook_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Notebook runtime recovery helpers.")

app.add_typer(query_app, name="query")
app.add_typer(create_app, name="create")
app.add_typer(publish_app, name="publish")
app.add_typer(index_app, name="index")
app.add_typer(save_app, name="save")
app.add_typer(template_app, name="template")
app.add_typer(library_app, name="library")
app.add_typer(workspace_app, name="workspace")
app.add_typer(notebook_app, name="notebook")
library_app.add_typer(library_query_app, name="query")
library_app.add_typer(library_save_app, name="save")
library_app.add_typer(library_template_app, name="template")


def _emit_json(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False))


def _write_json_file(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
    typer.echo(f"Project root: {payload['project_root']}")
    typer.echo(f"Kernel processes found: {payload['kernel_process_count']}")
    typer.echo(f"Processes terminated: {payload['terminated_pid_count']}")
    typer.echo(f"Processes killed: {payload['killed_pid_count']}")
    typer.echo(f"Remaining processes: {payload['remaining_pid_count']}")
    if payload["cleared_runtime_paths"]:
        typer.echo("Cleared runtime state:")
        for path in payload["cleared_runtime_paths"]:
            typer.echo(f"- {path}")


def _init_example_document(profile: str) -> dict[str, Any]:
    if profile == "battery-descriptor":
        return {
            "schema_version": "1.0.0",
            "specification": {
                "id": "https://w3id.org/battinfo/cell-type/0000-0000-0000-0000",
                "manufacturer": "ExampleManufacturer",
                "model": "MODEL-001",
                "format": "unknown",
                "chemistry": "unknown",
                "positive_electrode_basis": "unknown",
                "negative_electrode_basis": "unknown",
            },
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


@app.command()
def validate(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    profile: str = typer.Option("battery-descriptor", help="Validation profile name."),
    policy: str = typer.Option("default", help="Validation policy: default|strict|publisher|ingest."),
    output_format: str = typer.Option("text", "--format", help="Output format: text|json."),
    source_root: Path | None = typer.Option(
        None,
        "--source-root",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Optional canonical source root for full record validation.",
    ),
) -> None:
    """Validate a JSON document against the canonical schema/profile."""
    data = json.loads(input_path.read_text(encoding="utf-8"))
    policy_name = _check_validation_policy(policy)
    fmt = _check_validation_output_format(output_format)
    if source_root is not None:
        result = validate_record(data, source_root=source_root, policy=policy_name)
    else:
        result = validate_json(data, profile=profile, policy=policy_name)

    if fmt == "json":
        _emit_json(_validation_result_payload(result, profile=profile, source_root=source_root))
        raise typer.Exit(code=0 if result.ok else 1)

    warnings = [issue for issue in result.issues if issue.severity == "warning"]
    if result.ok:
        typer.echo("Validation passed with warnings." if warnings else "Validation passed.")
        for issue in warnings:
            typer.echo(f"- {_render_validation_issue(issue)}")
        raise typer.Exit(code=0)

    typer.echo("Validation failed.")
    for issue in result.issues:
        if issue.severity == "error":
            typer.echo(f"- {_render_validation_issue(issue)}")
    if warnings:
        typer.echo("Warnings:")
        for issue in warnings:
            typer.echo(f"- {_render_validation_issue(issue)}")
    raise typer.Exit(code=1)


@app.command()
def init(
    project_dir: Path = typer.Argument(...),
    profile: str = typer.Option("battery-descriptor", help="Profile to scaffold."),
) -> None:
    """Create a minimal project scaffold with an example JSON file."""
    project_dir.mkdir(parents=True, exist_ok=True)
    example_path = project_dir / "battinfo.json"
    if not example_path.exists():
        example_path.write_text(
            json.dumps(_init_example_document(profile), indent=2),
            encoding="utf-8",
        )
    typer.echo(f"Initialized {project_dir}")


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


@notebook_app.command("recover")
def notebook_recover(
    project_root: Path = typer.Option(Path("."), "--project-root", file_okay=False, dir_okay=True, readable=True),
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
            project_root=project_root,
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


@template_app.command("cell-type")
def template_cell_type(
    manufacturer: str = typer.Option("ExampleManufacturer", help="Manufacturer name."),
    model_name: str = typer.Option("MODEL-001", "--model-name", help="Model name."),
    chemistry: str = typer.Option("unknown", help="Chemistry label."),
    cell_format: str = typer.Option("unknown", "--cell-format", help="Cell format."),
    uid: str | None = typer.Option("0000000000000000", help="Optional 16-char UID."),
    out: Path | None = typer.Option(None, help="Optional output JSON path."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Generate a starter template for a cell-type record."""
    fmt = _check_output_format(output_format)
    try:
        record = api_template_cell_type(
            manufacturer=manufacturer,
            model_name=model_name,
            chemistry=chemistry,
            format=cell_format,  # type: ignore[arg-type]
            uid=uid,
        )
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    if out is not None:
        _write_json_file(out, record)
        payload = {
            "status": "template",
            "resource": "cell-type",
            "id": record["product"]["id"],
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
        "resource": "cell-type",
        "id": record["product"]["id"],
        "path": "",
    }
    _emit_table([payload], ["status", "resource", "id", "path"])


@template_app.command("cell-instance")
def template_cell_instance(
    type_id: str = typer.Option(
        "https://w3id.org/battinfo/cell-type/0000-0000-0000-0000",
        help="Canonical cell-type IRI.",
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
            type_id=type_id,
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


@library_template_app.command("cell-type")
def library_template_cell_type(
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
    """Generate a starter reusable library cell-type specification."""
    fmt = _check_output_format(output_format)
    try:
        record = api_template_cell_specification(
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
            "resource": "library-cell-type",
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
        "resource": "library-cell-type",
        "id": record["specification"]["id"],
        "path": "",
    }
    _emit_table([payload], ["status", "resource", "id", "path"])


@library_query_app.command("cell-types")
def library_query_cell_types(
    id: str | None = typer.Option(None, help="Filter by reusable cell-type IRI."),
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
    library_dir: Path = typer.Option(Path("assets/library/cell-types"), help="Reusable library cell-specification directory."),
    limit: int = typer.Option(50, min=1, help="Maximum rows."),
    offset: int = typer.Option(0, min=0, help="Start offset."),
    output_format: str = typer.Option("table", "--format", help="Output format: table|json."),
) -> None:
    """Query reusable library cell-type specifications."""
    fmt = _check_output_format(output_format)
    rows = api_query_library_cell_types(
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
        "resource": "library-cell-types",
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


@library_save_app.command("cell-type")
def library_save_cell_type(
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
    library_dir: Path = typer.Option(Path("assets/library/cell-types"), help="Reusable library cell-specification directory."),
    packaged_dir: Path = typer.Option(
        Path("src/battinfo/data/library/cell-types"),
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
        Path("assets/library-rdf/cell-types"),
        help="Directory for per-record domain-battery JSON-LD artifacts.",
    ),
    aggregate_jsonld: Path = typer.Option(
        Path("ontology/library/cell-types.jsonld"),
        help="Path for the aggregated library JSON-LD file.",
    ),
    manifest_json: Path = typer.Option(
        Path("assets/library-rdf/cell-types.index.json"),
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
            draft_obj: CellSpecificationInput | dict[str, Any] | Path = input_path
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
            draft_obj = CellSpecificationInput(
                uid=uid,
                manufacturer=manufacturer,
                model=model,
                chemistry=chemistry,
                format=cell_format,  # type: ignore[arg-type]
                positive_electrode_basis=positive_electrode_basis,
                negative_electrode_basis=negative_electrode_basis,
                size_code=size_code,
                property=properties,
                source_type=source_type,
                source_name=source_name,
                source_file=source_file,
                source_url=source_url,
            )
        payload = api_save_library_cell_type(
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
        Path("assets/library/cell-types"),
        "--input-dir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Directory containing reusable library cell-specification JSON files.",
    ),
    output_jsonld_dir: Path = typer.Option(
        Path("assets/library-rdf/cell-types"),
        help="Directory for per-record domain-battery JSON-LD artifacts.",
    ),
    aggregate_jsonld: Path = typer.Option(
        Path("ontology/library/cell-types.jsonld"),
        help="Path for the aggregated library JSON-LD file.",
    ),
    manifest_json: Path = typer.Option(
        Path("assets/library-rdf/cell-types.index.json"),
        help="Path for the generated library manifest JSON.",
    ),
    glob: str = typer.Option("*.json", help="File glob used to select library cell specifications."),
    clean_output: bool = typer.Option(False, "--clean-output", help="Remove existing JSON-LD outputs before writing."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Build domain-battery JSON-LD artifacts for the reusable cell-type library."""
    fmt = _check_output_format(output_format)
    try:
        payload = api_build_cell_type_library_rdf(
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


@query_app.command("cell-types")
def query_cell_types(
    id: str | None = typer.Option(None, help="Filter by canonical cell-type IRI."),
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
    rows = api_query_cell_types(
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
        "resource": "cell-types",
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


@query_app.command("cell-instances")
def query_cell_instances(
    id: str | None = typer.Option(None, help="Filter by canonical cell IRI."),
    type_id: str | None = typer.Option(None, help="Filter by canonical cell-type IRI."),
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
        type_id=type_id,
        short_id_prefix=short_id,
        serial_number=serial_number,
        has_dataset=dataset_bool,
        dataset_id=dataset_id,
        source_type=source_type,
        limit=limit,
        offset=offset,
    )
    payload = {
        "resource": "cell-instances",
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "items": rows,
    }
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table(rows, ["id", "type_id", "short_id", "serial_number", "dataset_id", "source_type"])


@query_app.command("datasets")
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
    """Query canonical datasets."""
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
        "resource": "datasets",
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "items": rows,
    }
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table(rows, ["id", "title", "format", "license", "source_type", "access_url"])


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


@create_app.command("cell-type")
def create_cell_type(
    datasheet: Path = typer.Option(..., exists=True, file_okay=True, dir_okay=False, readable=True),
    uid: str | None = typer.Option(None, help="Optional 16-char UID (dashed or undashed)."),
    out: Path | None = typer.Option(None, help="Optional output JSON path."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate against schema."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Create a canonical cell-type record from datasheet extraction JSON."""
    fmt = _check_output_format(output_format)
    try:
        doc = api_create_cell_type_from_datasheet(datasheet, uid=uid, out_path=out, validate=validate)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    payload = {
        "status": "created",
        "resource": "cell-type",
        "id": doc["product"]["id"],
        "path": str(out) if out else None,
    }
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "resource", "id", "path"])


@create_app.command("cell-instance")
def create_cell_instance(
    type_id: str | None = typer.Option(None, help="Canonical cell-type IRI."),
    cell_type: Path | None = typer.Option(
        None, help="Path to cell-type JSON (alternative to --type-id).", exists=True, file_okay=True, dir_okay=False
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
            type_id=type_id,
            cell_type=cell_type,
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
        "type_id": doc["cell_instance"]["type_id"],
        "path": str(out) if out else None,
    }
    if fmt == "json":
        _emit_json(payload)
        return
    _emit_table([payload], ["status", "resource", "id", "type_id", "path"])


@save_app.command("record")
def save_record(
    input_path: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False, readable=True),
    source_root: Path = typer.Option(
        Path("assets/examples"),
        help="Root directory containing cell-types, cell-instances, and datasets.",
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
        Path("assets/examples"),
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


@save_app.command("cell-type")
def save_cell_type(
    input_path: Path | None = typer.Option(
        None, "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Draft or canonical JSON."
    ),
    manufacturer: str | None = typer.Option(None, help="Manufacturer name (required when --input omitted)."),
    model_name: str | None = typer.Option(None, "--model-name", help="Model name (required when --input omitted)."),
    chemistry: str = typer.Option("unknown", help="Chemistry label."),
    cell_format: str = typer.Option("unknown", "--cell-format", help="Cell format."),
    size_code: str | None = typer.Option(None, help="Optional size code."),
    source_file: str = typer.Option("manual.json", help="Source file label for provenance."),
    source_url: str | None = typer.Option(None, help="Optional source URL."),
    uid: str | None = typer.Option(None, help="Optional 16-char UID (dashed or undashed)."),
    specs_path: Path | None = typer.Option(
        None, "--specs", exists=True, file_okay=True, dir_okay=False, readable=True, help="Optional specs JSON object."
    ),
    source_root: Path = typer.Option(Path("assets/examples"), help="Save source root."),
    mode: str = typer.Option("create_only", help="Save mode: create_only|upsert."),
    duplicate_policy: str = typer.Option("error", help="Duplicate handling: error|return_existing."),
    publish: bool = typer.Option(False, "--publish/--no-publish", help="Publish resolver artifacts after saving."),
    publish_root: Path = typer.Option(Path(".battinfo/resolver-site"), help="Resolver artifact root."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate record before saving."),
    validation_policy: str = typer.Option("default", "--validation-policy", help="Validation policy: default|strict|publisher|ingest."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview save without writing files."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Save a cell-type using either --input JSON or inline draft fields."""
    fmt = _check_output_format(output_format)
    reg_mode = _check_save_mode(mode)
    dup_policy = _check_duplicate_policy(duplicate_policy)
    policy_name = _check_validation_policy(validation_policy)
    try:
        if input_path is not None:
            draft_obj: CellTypeInput | dict[str, Any] | Path = input_path
        else:
            if not manufacturer or not model_name:
                raise ValueError("--manufacturer and --model-name are required when --input is not provided.")
            specs: dict[str, Any] = {}
            if specs_path is not None:
                loaded_specs = json.loads(specs_path.read_text(encoding="utf-8"))
                if not isinstance(loaded_specs, dict):
                    raise ValueError("--specs must point to a JSON object.")
                specs = loaded_specs
            draft_obj = CellTypeInput(
                uid=uid,
                model_name=model_name,
                manufacturer=manufacturer,
                chemistry=chemistry,
                format=cell_format,  # type: ignore[arg-type]
                size_code=size_code,
                specs=specs,
                source_file=source_file,
                source_url=source_url,
            )
        payload = api_save_cell_type(
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
    type_id: str | None = typer.Option(None, help="Canonical cell-type IRI (required when --input omitted)."),
    serial_number: str | None = typer.Option(None, help="Optional serial metadata."),
    dataset_id: list[str] = typer.Option([], "--dataset-id", help="Optional linked dataset IRI. Repeat for multiple."),
    source_type: str = typer.Option("measurement", help="Source type: measurement|lab|bms|other."),
    uid: str | None = typer.Option(None, help="Optional 16-char UID (dashed or undashed)."),
    source_root: Path = typer.Option(Path("assets/examples"), help="Save source root."),
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
            if not type_id:
                raise ValueError("--type-id is required when --input is not provided.")
            draft_obj = CellInstanceInput(
                uid=uid,
                type_id=type_id,
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
    source_root: Path = typer.Option(Path("assets/examples"), help="Save source root."),
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


@save_app.command("test")
def save_test(
    input_path: Path | None = typer.Option(
        None, "--input", exists=True, file_okay=True, dir_okay=False, readable=True, help="Draft or canonical JSON."
    ),
    cell_id: str | None = typer.Option(None, help="Canonical cell-instance IRI (required when --input omitted)."),
    name: str | None = typer.Option(None, help="Test name (required when --input omitted)."),
    kind: str = typer.Option("other", help="Test kind."),
    status: str | None = typer.Option(None, help="Optional test status."),
    protocol_name: str | None = typer.Option(None, help="Optional protocol name."),
    protocol_url: str | None = typer.Option(None, help="Optional protocol URL."),
    instrument_name: str | None = typer.Option(None, help="Optional instrument name."),
    dataset_id: list[str] = typer.Option([], "--dataset-id", help="Linked dataset IRI. Repeat for multiple."),
    source_type: str = typer.Option("measurement", help="Source type: measurement|lab|simulation|manual|other."),
    uid: str | None = typer.Option(None, help="Optional 16-char UID (dashed or undashed)."),
    source_root: Path = typer.Option(Path("assets/examples"), help="Save source root."),
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
        Path("assets/examples"),
        "--source-root",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Root directory containing cell-types, cell-instances, and datasets subdirectories.",
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
        "cell_type_count": payload.get("cell_type_count", 0),
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
            "cell_type_count",
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
        ["cell_type_count", "cell_instance_count", "test_count", "dataset_count", "total_count", "failed", "build_timestamp"],
    )

