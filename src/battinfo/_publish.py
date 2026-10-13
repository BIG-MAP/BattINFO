from __future__ import annotations

import json
import re
import warnings
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from battinfo._workspace import Workspace
from battinfo.api import build_curated_cell_spec_submission, submit_publication_package
from battinfo.bundle import CellSpec
from battinfo.config import resolve_destination_config
from battinfo.publication import publish as _legacy_publish

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


# The keywords of battinfo.publication.publish(), which the deprecated
# publish(cell_spec=..., cell_instance=..., test=..., dataset=...) form passes on.
# validation_policy is a parameter of both forms.
_LEGACY_CORE_KEYWORDS = frozenset({"cell_spec", "cell_instance", "test", "dataset"})
_LEGACY_KEYWORDS = _LEGACY_CORE_KEYWORDS | frozenset({
    "cell_specification",
    "datasheet_path",
    "publish_filename",
    "html_filename",
    "dataset_glob",
    "emit_bundle_dir",
    "emit_html_page",
    "emit_ro_crate_metadata",
    "emit_datacite_metadata",
    "emit_dcat_export",
    "ro_crate_filename",
    "datacite_filename",
    "dcat_filename",
})


def publish(
    obj: Any = None,
    destination: str | None = None,
    *,
    root: PathLike | None = None,
    force: bool = False,
    validation_policy: str | None = None,
    registry_base_url: str | None = None,
    api_key: str | None = None,
    api_key_header: str | None = None,
    platform_base_url: str | None = None,
    workspace_id: str | None = None,
    publisher_id: str | None = None,
    source_version: str | None = None,
    **legacy: Any,
) -> PublishResult | dict[str, Any]:
    """Publish a BattINFO object to a named destination.

    ``publish(cell_spec, destination="local")`` saves the record in a
    workspace folder; ``"registry"``, ``"battery-genome"``, ``"staging"`` and
    ``"production"`` also submit it. Only ``CellSpec`` objects are supported.

    Parameters
    ----------
    root:
        The workspace folder. Defaults to
        ``.battinfo/publish/<manufacturer>-<model>`` in the current folder.
    force:
        Delete ``root`` first and build it again. Refused (``UnsafeDeleteError``,
        a ``ValueError``) for a folder BattINFO did not create, for the
        ``.battinfo`` folder where ``battinfo.workspace()`` keeps a project's
        records, and for the home or working folder.
    validation_policy:
        Validation policy for the saved record. Defaults to ``"strict"``.
    registry_base_url, api_key, api_key_header, platform_base_url, workspace_id, publisher_id, source_version:
        Override the destination's configured values.

    Notes
    -----
    The deprecated form ``publish(cell_spec=..., cell_instance=..., test=...,
    dataset=...)`` still builds a dataset publication package, with a
    ``DeprecationWarning``, and accepts only the keywords of
    ``battinfo.publish_publication_package()``. It will be removed in 0.9.0.
    """

    if obj is None and destination is None and _LEGACY_CORE_KEYWORDS & legacy.keys():
        new_form = {
            "root": root,
            "force": force or None,
            "registry_base_url": registry_base_url,
            "api_key": api_key,
            "api_key_header": api_key_header,
            "platform_base_url": platform_base_url,
            "workspace_id": workspace_id,
            "publisher_id": publisher_id,
            "source_version": source_version,
        }
        _refuse_keywords(
            [name for name, value in new_form.items() if value is not None]
            + [name for name in legacy if name not in _LEGACY_KEYWORDS],
            "publish(cell_spec=..., cell_instance=..., test=..., dataset=...)",
            " That form takes the keywords of battinfo.publish_publication_package() only.",
        )
        warnings.warn(
            "Calling battinfo.publish(cell_spec=..., cell_instance=..., test=..., dataset=...) "
            "relies on implicit keyword sniffing; call battinfo.publish_publication_package(...) "
            "(the same operation, explicitly) instead. The implicit dispatch will be removed "
            "in 0.9.0.",
            DeprecationWarning,
            stacklevel=2,
        )
        if validation_policy is not None:
            legacy["validation_policy"] = validation_policy
        return _legacy_publish(**legacy)
    _refuse_keywords(legacy, "publish()")

    if obj is None:
        raise TypeError("publish() requires a BattINFO object or the legacy publication-package keyword arguments.")

    resolved_destination = destination or "local"
    if isinstance(obj, CellSpec):
        return _publish_cell_spec(
            obj,
            destination=resolved_destination,
            root=root,
            force=force,
            validation_policy=validation_policy or "strict",
            registry_base_url=registry_base_url,
            api_key=api_key,
            api_key_header=api_key_header,
            platform_base_url=platform_base_url,
            workspace_id=workspace_id,
            publisher_id=publisher_id,
            source_version=source_version,
        )

    raise TypeError(
        "publish(obj, destination=...) currently supports CellSpec objects. "
        "Use battinfo.publish_publication_package(...) for dataset publication packages."
    )


def _refuse_keywords(names: Iterable[str], call: str, hint: str = "") -> None:
    unexpected = sorted(names)
    if unexpected:
        listed = ", ".join(repr(name) for name in unexpected)
        plural = "s" if len(unexpected) > 1 else ""
        raise TypeError(f"{call} got unexpected keyword argument{plural} {listed}.{hint}")


def default_publish_root(cell_spec: CellSpec) -> Path:
    """The folder ``publish(cell_spec)`` builds in when no ``root`` is given."""
    return Path(".battinfo/publish") / _cell_spec_slug(cell_spec)


def _publish_cell_spec(
    cell_spec: CellSpec,
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

    workspace_root = Path(root) if root is not None else default_publish_root(cell_spec)
    workspace = Workspace(root=workspace_root, clean=force, generated=True)
    workspace.add(cell_spec)
    workspace.save(validation_policy=validation_policy)

    if not isinstance(cell_spec.id, str) or not cell_spec.id:
        raise RuntimeError("CellSpec did not receive a canonical id during save().")

    canonical_id = cell_spec.id.rsplit("/", 1)[-1]
    record_path = workspace.source_root / "cell-spec" / f"cell-spec-{canonical_id}.json"
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
            resource_type="cell_spec",
            canonical_id=canonical_id,
            canonical_iri=cell_spec.id,
            source_local_id=source_local_id,
            debug_paths=debug_paths,
        )

    resolved_workspace_id = _require_value(config.workspace_id, "workspace_id", destination=config.name)
    resolved_publisher_id = _require_value(config.publisher_id, "publisher_id", destination=config.name)
    resolved_source_version = config.source_version or date.today().isoformat()
    resolved_registry_base_url = _require_value(config.registry_base_url, "registry_base_url", destination=config.name)
    resolved_api_key = _require_value(config.api_key, "api_key", destination=config.name)

    submission_payload = build_curated_cell_spec_submission(
        record_path,
        workspace_id=resolved_workspace_id,
        publisher_id=resolved_publisher_id,
        source_version=resolved_source_version,
        source_local_id=source_local_id,
        validation_policy=validation_policy,
    )
    dist_dir = workspace.root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    submission_path = dist_dir / f"submission-package.cell_spec.{source_local_id}.json"
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
    route_resource_type = "cell-spec"
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
        resource_type="cell_spec",
        canonical_id=published_canonical_id,
        canonical_iri=published_canonical_iri or cell_spec.id,
        page_url=page_url,
        registry_resource_url=registry_resource_url,
        source_local_id=source_local_id,
        workspace_id=resolved_workspace_id,
        publisher_id=resolved_publisher_id,
        source_version=resolved_source_version,
        debug_paths=debug_paths,
        submission_response=response_payload if isinstance(response_payload, dict) else None,
    )


def _cell_spec_slug(cell_spec: CellSpec) -> str:
    parts = [cell_spec.manufacturer or "cell", cell_spec.model or "type"]
    value = "-".join(parts).strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return slug or "cell-spec"


def _require_value(value: str | None, name: str, *, destination: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError(f"{name} is required for destination='{destination}'.")


__all__ = ["PublishResult", "publish"]
