from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from battinfo.api import build_curated_cell_type_submission, submit_publication_package
from battinfo.bundle import CellType
from battinfo.config import resolve_destination_config
from battinfo.publication import publish as _legacy_publish
from battinfo.workspace import Workspace

PathLike = str | Path


class PublishResult(BaseModel):
    status: str
    destination: str
    resource_type: str
    canonical_id: str | None = None
    canonical_iri: str | None = None
    page_url: str | None = None
    registry_resource_url: str | None = None
    source_local_id: str | None = None
    workspace_id: str | None = None
    publisher_id: str | None = None
    source_version: str | None = None
    debug_paths: dict[str, str] = Field(default_factory=dict)
    submission_response: dict[str, Any] | None = None


def publish(obj: Any = None, destination: str | None = None, **kwargs: Any) -> PublishResult | dict[str, Any]:
    """Publish a BattINFO object to a named destination.

    The new product surface is `publish(obj, destination=...)`.
    The legacy publication-package call shape is still accepted for backwards
    compatibility and delegated to `battinfo.publication.publish(...)`.
    """

    if _looks_like_legacy_publication_call(obj, destination, kwargs):
        return _legacy_publish(**kwargs)

    if obj is None:
        raise TypeError("publish() requires a BattINFO object or the legacy publication-package keyword arguments.")

    resolved_destination = destination or "local"
    if isinstance(obj, CellType):
        return _publish_cell_type(obj, destination=resolved_destination, **kwargs)

    raise TypeError(
        "publish(obj, destination=...) currently supports CellType objects. "
        "Use the legacy keyword form for dataset publication packages."
    )


def _publish_cell_type(
    cell_type: CellType,
    *,
    destination: str,
    root: PathLike | None = None,
    force: bool = False,
    validation_policy: str = "strict",
    registry_base_url: str | None = None,
    api_key: str | None = None,
    api_key_header: str | None = None,
    platform_base_url: str | None = None,
    workspace_id: str | None = None,
    publisher_id: str | None = None,
    source_version: str | None = None,
) -> PublishResult:
    config = resolve_destination_config(
        destination,
        registry_base_url=registry_base_url,
        api_key=api_key,
        api_key_header=api_key_header,
        platform_base_url=platform_base_url,
        workspace_id=workspace_id,
        publisher_id=publisher_id,
        source_version=source_version,
    )

    workspace_root = Path(root) if root is not None else Path(".battinfo/publish") / _cell_type_slug(cell_type)
    workspace = Workspace(root=workspace_root, clean=force)
    workspace.add(cell_type)
    workspace.save(validation_policy=validation_policy)

    if not isinstance(cell_type.id, str) or not cell_type.id:
        raise RuntimeError("CellType did not receive a canonical id during save().")

    canonical_id = cell_type.id.rsplit("/", 1)[-1]
    record_path = workspace.source_root / "cell-type" / f"cell-type-{canonical_id}.json"
    if not record_path.exists():
        raise FileNotFoundError(f"Expected canonical record to exist at {record_path}")

    debug_paths = {
        "workspace_root": str(workspace.root),
        "canonical_record_path": str(record_path),
    }

    source_local_id = canonical_id
    if config.mode == "local":
        return PublishResult(
            status="ok",
            destination=config.name,
            resource_type="cell_type",
            canonical_id=canonical_id,
            canonical_iri=cell_type.id,
            source_local_id=source_local_id,
            debug_paths=debug_paths,
        )

    resolved_workspace_id = _require_value(config.workspace_id, "workspace_id", destination=config.name)
    resolved_publisher_id = _require_value(config.publisher_id, "publisher_id", destination=config.name)
    resolved_source_version = config.source_version or date.today().isoformat()
    resolved_registry_base_url = _require_value(config.registry_base_url, "registry_base_url", destination=config.name)
    resolved_api_key = _require_value(config.api_key, "api_key", destination=config.name)

    submission_payload = build_curated_cell_type_submission(
        record_path,
        workspace_id=resolved_workspace_id,
        publisher_id=resolved_publisher_id,
        source_version=resolved_source_version,
        source_local_id=source_local_id,
        validation_policy=validation_policy,
    )
    dist_dir = workspace.root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    submission_path = dist_dir / f"submission-package.cell_type.{source_local_id}.json"
    submission_path.write_text(json.dumps(submission_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    debug_paths["submission_package_path"] = str(submission_path)

    submission_result = submit_publication_package(
        submission_payload,
        registry_base_url=resolved_registry_base_url,
        api_key=resolved_api_key,
        api_key_header=config.api_key_header,
    )
    response_payload = submission_result.get("response") or {}
    canonical_id_map = response_payload.get("canonical_id_map")
    canonical_iri_map = response_payload.get("canonical_iri_map")
    published_canonical_id = (
        canonical_id_map.get(source_local_id)
        if isinstance(canonical_id_map, dict) and isinstance(canonical_id_map.get(source_local_id), str)
        else response_payload.get("canonical_id")
    )
    published_canonical_iri = (
        canonical_iri_map.get(source_local_id)
        if isinstance(canonical_iri_map, dict) and isinstance(canonical_iri_map.get(source_local_id), str)
        else response_payload.get("canonical_iri")
    )
    route_resource_type = "cell-type"
    registry_resource_url = (
        resolved_registry_base_url.rstrip("/") + f"/resources/{route_resource_type}/{published_canonical_id}"
        if isinstance(published_canonical_id, str)
        else None
    )
    page_url = None
    if config.mode == "battery-genome" and isinstance(published_canonical_id, str):
        if config.platform_base_url is None:
            raise ValueError(f"platform_base_url is required for destination='{config.name}'.")
        page_url = config.platform_base_url.rstrip("/") + f"/registry/{route_resource_type}/{published_canonical_id}"

    return PublishResult(
        status=submission_result["status"],
        destination=config.name,
        resource_type="cell_type",
        canonical_id=published_canonical_id,
        canonical_iri=published_canonical_iri or cell_type.id,
        page_url=page_url,
        registry_resource_url=registry_resource_url,
        source_local_id=source_local_id,
        workspace_id=resolved_workspace_id,
        publisher_id=resolved_publisher_id,
        source_version=resolved_source_version,
        debug_paths=debug_paths,
        submission_response=response_payload if isinstance(response_payload, dict) else None,
    )


def _looks_like_legacy_publication_call(obj: Any, destination: str | None, kwargs: dict[str, Any]) -> bool:
    if obj is not None or destination is not None:
        return False
    legacy_keys = {"cell_type", "cell_instance", "test", "dataset"}
    return any(key in kwargs for key in legacy_keys)


def _cell_type_slug(cell_type: CellType) -> str:
    parts = [cell_type.manufacturer or "cell", cell_type.model or "type"]
    value = "-".join(parts).strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return slug or "cell-type"


def _require_value(value: str | None, name: str, *, destination: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError(f"{name} is required for destination='{destination}'.")


__all__ = ["PublishResult", "publish"]
