from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from battinfo.api import submit_publication_package
from battinfo.workspace import Workspace, quantity

DEFAULT_DEMO_ROOT = Path(".battinfo/demo-e2e")
DEFAULT_DEMO_REGISTRY = "digibatt/hello-world"
DEFAULT_DEMO_PUBLISHER = "demo-lab"
DEFAULT_DEMO_VERSION = "1.0.0"


def setup_demo_environment(
    root: str | Path = DEFAULT_DEMO_ROOT,
    *,
    registry: str = DEFAULT_DEMO_REGISTRY,
    publisher_id: str = DEFAULT_DEMO_PUBLISHER,
    version: str = DEFAULT_DEMO_VERSION,
    force: bool = False,
) -> dict[str, Any]:
    root_path = Path(root)
    workspace_root = root_path / "workspace"
    release_root = root_path / "release"

    workspace = Workspace(root=workspace_root, clean=force)
    dataset_file = workspace.root / "inputs" / "cycle-life.csv"
    dataset_file.parent.mkdir(parents=True, exist_ok=True)
    dataset_file.write_text(
        "cycle_index,capacity_ah,voltage_v\n0,2.50,3.30\n1,2.48,3.28\n",
        encoding="utf-8",
    )

    cell_type = workspace.cell_type(
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        size_code="R26650",
        positive_electrode_basis="LFP",
        negative_electrode_basis="graphite",
        specs={
            "nominal_capacity": quantity(2.5, "Ah"),
            "nominal_voltage": quantity(3.3, "V"),
        },
        source_file="a123-anr26650m1-b.manual.json",
    )
    cell = workspace.cell(cell_type, serial_number="demo-hello-world-001", batch_id="A123-DEMO-01", source_type="lab")
    test = workspace.test(
        cell,
        kind="cycle_life",
        protocol="1C charge / 1C discharge",
        instrument="Biologic VSP-300",
        status="completed",
    )
    dataset = workspace.dataset(
        cell,
        title="A123 hello world cycling dataset",
        test=test,
        path=dataset_file,
        license="CC-BY-4.0",
        description="Small BattINFO demo dataset used to verify the Python-to-registry pipeline.",
    )

    save_report = workspace.save(validation_policy="strict")
    submission_report = workspace.build_submission_package(
        dataset,
        root=release_root,
        registry=registry,
        publisher_id=publisher_id,
        version=version,
        title=dataset.name or "BattINFO demo dataset",
        description=dataset.description,
        force=force,
    )
    submission_package_path = Path(submission_report["submission_package_path"])
    submission_package = json.loads(submission_package_path.read_text(encoding="utf-8"))
    resources = submission_package.get("resources", [])

    return {
        "status": "ok",
        "demo_root": str(root_path),
        "workspace_root": str(workspace.root),
        "source_root": str(workspace.source_root),
        "release_root": str(release_root),
        "input_dataset_path": str(dataset_file),
        "save_report": save_report,
        "submission_report": submission_report,
        "submission_package_path": str(submission_package_path),
        "submission_package": submission_package,
        "workspace_id": submission_package.get("workspace_id"),
        "publisher_id": submission_package.get("publisher_id"),
        "source_version": submission_package.get("source_version"),
        "resource_types": [item.get("resource_type") for item in resources if isinstance(item, dict)],
    }


def run_demo_pipeline(
    root: str | Path = DEFAULT_DEMO_ROOT,
    *,
    registry_base_url: str,
    api_key: str,
    platform_base_url: str | None = None,
    registry: str = DEFAULT_DEMO_REGISTRY,
    publisher_id: str = DEFAULT_DEMO_PUBLISHER,
    version: str = DEFAULT_DEMO_VERSION,
    api_key_header: str = "X-Battinfo-API-Key",
    timeout_sec: float = 30.0,
    poll_interval_sec: float = 1.0,
    force: bool = False,
) -> dict[str, Any]:
    demo = setup_demo_environment(
        root,
        registry=registry,
        publisher_id=publisher_id,
        version=version,
        force=force,
    )
    submission_payload = demo["submission_package"]

    submission_result = submit_publication_package(
        submission_payload,
        registry_base_url=registry_base_url,
        api_key=api_key,
        api_key_header=api_key_header,
        timeout_sec=timeout_sec,
    )
    response_payload = submission_result.get("response") or {}
    target = _verification_target(submission_payload, response_payload)
    route_resource_type = str(target["resource_type"]).replace("_", "-")

    registry_resource_url = (
        registry_base_url.rstrip("/") + f"/resources/{route_resource_type}/{target['canonical_id']}"
    )
    registry_page_model_url = registry_resource_url + "/page-model"
    resource_payload = _poll_json(registry_resource_url, timeout_sec=timeout_sec, poll_interval_sec=poll_interval_sec)
    page_model_payload = _poll_json(registry_page_model_url, timeout_sec=timeout_sec, poll_interval_sec=poll_interval_sec)

    platform_check: dict[str, Any] | None = None
    if platform_base_url is not None:
        platform_url = platform_base_url.rstrip("/") + f"/registry/{route_resource_type}/{target['canonical_id']}"
        page_html = _poll_text(
            platform_url,
            timeout_sec=timeout_sec,
            poll_interval_sec=poll_interval_sec,
            required_substrings=[str(target["canonical_id"]), str(target["title"])],
        )
        platform_check = {
            "url": platform_url,
            "ok": True,
            "contains_title": str(target["title"]) in page_html,
            "contains_canonical_id": str(target["canonical_id"]) in page_html,
        }

    return {
        "status": "ok",
        "demo": demo,
        "submission": submission_result,
        "verification_target": target,
        "registry": {
            "resource_url": registry_resource_url,
            "page_model_url": registry_page_model_url,
            "resource": resource_payload,
            "page_model": page_model_payload,
        },
        "platform": platform_check,
    }


def _verification_target(submission_payload: dict[str, Any], response_payload: dict[str, Any]) -> dict[str, Any]:
    resources = submission_payload.get("resources")
    if not isinstance(resources, list):
        resource = submission_payload.get("resource")
        resources = [resource] if isinstance(resource, dict) else []

    preferred_order = {"dataset": 0, "cell_type": 1, "cell": 2, "test": 3}
    ordered_resources = sorted(
        [item for item in resources if isinstance(item, dict)],
        key=lambda item: preferred_order.get(str(item.get("resource_type")), len(preferred_order)),
    )
    if not ordered_resources:
        raise ValueError("submission package did not contain any resources to verify.")

    target = ordered_resources[0]
    source_local_id = str(target.get("source_local_id"))
    canonical_id_map = response_payload.get("canonical_id_map")
    canonical_iri_map = response_payload.get("canonical_iri_map")
    canonical_id = None
    canonical_iri = None
    if isinstance(canonical_id_map, dict):
        canonical_id = canonical_id_map.get(source_local_id)
    if isinstance(canonical_iri_map, dict):
        canonical_iri = canonical_iri_map.get(source_local_id)
    if canonical_id is None:
        canonical_id = response_payload.get("canonical_id")
    if canonical_iri is None:
        canonical_iri = response_payload.get("canonical_iri")
    if not isinstance(canonical_id, str) or not canonical_id:
        raise RuntimeError("registry submission did not return a canonical_id for the verification target.")

    return {
        "resource_type": target.get("resource_type"),
        "source_local_id": source_local_id,
        "title": target.get("title"),
        "canonical_id": canonical_id,
        "canonical_iri": canonical_iri,
    }


def _poll_json(url: str, *, timeout_sec: float, poll_interval_sec: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    last_error: Exception | None = None
    while True:
        try:
            payload = _fetch_json(url, timeout_sec=timeout_sec)
            if isinstance(payload, dict):
                return payload
            raise RuntimeError(f"expected JSON object from {url}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if time.monotonic() >= deadline:
                break
            time.sleep(poll_interval_sec)
    raise RuntimeError(f"Timed out fetching JSON from {url}: {last_error}") from last_error


def _poll_text(
    url: str,
    *,
    timeout_sec: float,
    poll_interval_sec: float,
    required_substrings: list[str],
) -> str:
    deadline = time.monotonic() + timeout_sec
    last_error: Exception | None = None
    while True:
        try:
            payload = _fetch_text(url, timeout_sec=timeout_sec)
            if all(fragment in payload for fragment in required_substrings):
                return payload
            missing = [fragment for fragment in required_substrings if fragment not in payload]
            raise RuntimeError(f"missing expected page content: {missing}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if time.monotonic() >= deadline:
                break
            time.sleep(poll_interval_sec)
    raise RuntimeError(f"Timed out fetching page from {url}: {last_error}") from last_error


def _fetch_json(url: str, *, timeout_sec: float) -> dict[str, Any]:
    request = UrlRequest(url, headers={"Accept": "application/json"})
    response_text = _fetch_response_text(request, timeout_sec=timeout_sec)
    payload = json.loads(response_text) if response_text else {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object from {url}")
    return payload


def _fetch_text(url: str, *, timeout_sec: float) -> str:
    request = UrlRequest(url, headers={"Accept": "text/html,application/xhtml+xml"})
    return _fetch_response_text(request, timeout_sec=timeout_sec)


def _fetch_response_text(request: UrlRequest, *, timeout_sec: float) -> str:
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Request failed with HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Request failed: {exc.reason}") from exc


__all__ = [
    "DEFAULT_DEMO_PUBLISHER",
    "DEFAULT_DEMO_REGISTRY",
    "DEFAULT_DEMO_ROOT",
    "DEFAULT_DEMO_VERSION",
    "run_demo_pipeline",
    "setup_demo_environment",
]
