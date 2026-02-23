from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from battinfo.api import (
    build_index as api_build_index,
    create_cell_instance as api_create_cell_instance,
    create_cell_type_from_datasheet as api_create_cell_type_from_datasheet,
    index_stats as api_index_stats,
    publish_batch as api_publish_batch,
    publish_record as api_publish_record,
    query_cell_instances as api_query_cell_instances,
    query_cell_types as api_query_cell_types,
    query_datasets as api_query_datasets,
)
from battinfo.workflows.map import run_mapping
from battinfo.validate.pydantic import validate_json

app = typer.Typer(add_completion=False, no_args_is_help=True)
query_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Query BattINFO resources.")
create_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Create BattINFO resources.")
publish_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Publish BattINFO resolver artifacts.")
index_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Build and inspect BattINFO indexes.")

app.add_typer(query_app, name="query")
app.add_typer(create_app, name="create")
app.add_typer(publish_app, name="publish")
app.add_typer(index_app, name="index")


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


@app.command()
def validate(
    input_path: Path = typer.Argument(..., exists=True, readable=True),
    profile: str = typer.Option("base", help="Validation profile name."),
) -> None:
    """Validate a JSON document against the canonical schema/profile."""
    data = json.loads(input_path.read_text(encoding="utf-8"))
    result = validate_json(data, profile=profile)

    if result.ok:
        typer.echo("Validation passed.")
        raise typer.Exit(code=0)

    typer.echo("Validation failed.")
    for err in result.errors:
        typer.echo(f"- {err}")
    raise typer.Exit(code=1)


@app.command()
def init(
    project_dir: Path = typer.Argument(...),
    profile: str = typer.Option("base", help="Profile to scaffold."),
) -> None:
    """Create a minimal project scaffold with an example JSON file."""
    project_dir.mkdir(parents=True, exist_ok=True)
    example_path = project_dir / "battinfo.json"
    if not example_path.exists():
        example_path.write_text(
            json.dumps(
                {
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
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    typer.echo(f"Initialized {project_dir}")


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
        "id": doc["cell_type"]["id"],
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


@publish_app.command("record")
def publish_record(
    input_path: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False, readable=True),
    target_root: Path = typer.Option(Path("registry/site"), help="Output artifact root directory."),
    build_jsonld: bool = typer.Option(True, "--build-jsonld/--no-build-jsonld", help="Generate JSON-LD output."),
    build_html: bool = typer.Option(True, "--build-html/--no-build-html", help="Generate HTML output."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate records before publishing."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Publish one record into resolver artifacts."""
    fmt = _check_output_format(output_format)
    try:
        payload = api_publish_record(
            input_path,
            target_root=target_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
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
    target_root: Path = typer.Option(Path("registry/site"), help="Output artifact root directory."),
    glob: str = typer.Option("*.json", help="File glob for batch inputs."),
    build_jsonld: bool = typer.Option(True, "--build-jsonld/--no-build-jsonld", help="Generate JSON-LD output."),
    build_html: bool = typer.Option(True, "--build-html/--no-build-html", help="Generate HTML output."),
    validate: bool = typer.Option(True, "--validate/--no-validate", help="Validate records before publishing."),
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Publish a deterministic batch of records into resolver artifacts."""
    fmt = _check_output_format(output_format)
    kwargs: dict[str, Any] = {
        "target_root": target_root,
        "glob": glob,
        "build_jsonld": build_jsonld,
        "build_html": build_html,
        "validate": validate,
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
    output_format: str = typer.Option("json", "--format", help="Output format: table|json."),
) -> None:
    """Build an index from canonical example resources."""
    fmt = _check_output_format(output_format)
    try:
        payload = api_build_index(source_root=source_root, out_path=out, glob=glob, validate=validate)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    payload = {
        "status": "ok" if payload.get("failed", 0) == 0 else "partial",
        "index_path": str(out),
        "build_timestamp": payload.get("build_timestamp"),
        "cell_type_count": payload.get("cell_type_count", 0),
        "cell_instance_count": payload.get("cell_instance_count", 0),
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
        ["cell_type_count", "cell_instance_count", "dataset_count", "total_count", "failed", "build_timestamp"],
    )
