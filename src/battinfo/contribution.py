"""
High-level contributor workflow: init → process → publish.

This module wraps the lower-level ingest pipeline with a user-facing interface
designed for researchers who want to share measurement data.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from battinfo.ingest import (
    DATASET_TITLE_LABELS,
    DATE_RE,
    TEMP_RE,
    build_ingest_workspace,
    _infer_csv_kind,
    _resolve_kind_map,
)

CONTRIBUTION_MANIFEST = "battinfo.yaml"
INGEST_MANIFEST = "battinfo.ingest.json"
TEMPLATE_DIR = Path(__file__).parent / "data" / "templates" / "contribution"

# Globs used when the template folder structure (data/, photos/) is in use
CONTRIBUTION_TIMESERIES_GLOB = "data/*.csv"
CONTRIBUTION_PHOTO_GLOBS = ["photos/*.jpg", "photos/*.jpeg", "photos/*.png"]


# ── Init ──────────────────────────────────────────────────────────────────────

def init_contribution(
    output_path: Path,
    *,
    cell_name: str | None = None,
    cell_type_iri: str | None = None,
    lab: str | None = None,
    license: str = "CC-BY-4.0",
    overwrite: bool = False,
) -> Path:
    """Copy the contribution template to *output_path* and patch battinfo.yaml."""
    import re

    output_path = Path(output_path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(
            f"{output_path} already exists. Pass overwrite=True or choose a different name."
        )

    shutil.copytree(TEMPLATE_DIR, output_path, dirs_exist_ok=overwrite)

    manifest_path = output_path / CONTRIBUTION_MANIFEST
    text = manifest_path.read_text(encoding="utf-8")

    def _patch(t: str, key: str, value: str) -> str:
        # Replace the value of a YAML key while preserving surrounding comments.
        return re.sub(
            rf"^({re.escape(key)}:\s*).*$",
            rf'\g<1>"{value}"',
            t,
            flags=re.MULTILINE,
        )

    if cell_name:
        text = _patch(text, "cell_name", cell_name)
    if cell_type_iri:
        text = _patch(text, "cell_type_iri", cell_type_iri)
    if lab:
        text = _patch(text, "lab", lab)
    if license != "CC-BY-4.0":
        text = _patch(text, "license", license)

    manifest_path.write_text(text, encoding="utf-8")
    return output_path


# ── Load / validate manifest ───────────────────────────────────────────────────

def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def load_contribution_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / CONTRIBUTION_MANIFEST
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No {CONTRIBUTION_MANIFEST} found in {root}. "
            f"Run `battinfo dataset init` to create one."
        )
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}


def validate_contribution_manifest(manifest: dict) -> list[str]:
    """Return a list of human-readable error strings (empty = valid)."""
    errors = []
    if not manifest.get("cell_type_iri"):
        errors.append(
            "cell_type_iri is required. Find the IRI at "
            "https://www.battery-genome.org/registry/cell-type"
        )
    if not manifest.get("cell_name"):
        errors.append("cell_name is required (e.g. a serial number or lab label).")
    if not manifest.get("lab"):
        errors.append("lab is required (your institution or lab name).")
    return errors


def _contribution_to_ingest_manifest(manifest: dict, root: Path) -> dict:
    """Convert battinfo.yaml fields to the battinfo.ingest.json format."""
    cell_name = manifest.get("cell_name") or root.name
    lab = manifest.get("lab") or ""
    resource_name = f"{lab} {cell_name}".strip() if lab else cell_name

    return {
        "resource_type": "cell-instance",
        "resource_name": resource_name,
        "resource_iri": manifest.get("cell_iri") or None,
        "type_record": None,  # resolved via cell_type_iri separately
        "license": manifest.get("license") or "CC-BY-4.0",
        "publisher_id": manifest.get("publisher_id") or None,
        "source_version": manifest.get("source_version") or None,
        "rules": {
            "timeseries_glob": [CONTRIBUTION_TIMESERIES_GLOB],
            "photo_glob": CONTRIBUTION_PHOTO_GLOBS,
        },
    }


def _write_ingest_manifest(root: Path, manifest: dict) -> Path:
    ingest = _contribution_to_ingest_manifest(manifest, root)
    path = root / INGEST_MANIFEST
    path.write_text(json.dumps(ingest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# ── Process ───────────────────────────────────────────────────────────────────

def _scan_data_files(root: Path) -> list[Path]:
    return sorted((root / "data").glob("*.csv")) if (root / "data").is_dir() else []


def _describe_csv(path: Path) -> dict[str, str | None]:
    kind_map = _resolve_kind_map({})
    kind = _infer_csv_kind(path, kind_map)
    label = DATASET_TITLE_LABELS.get(kind, kind)
    date_match = DATE_RE.search(path.name)
    temp_match = TEMP_RE.search(path.name)
    return {
        "name": path.name,
        "kind": kind,
        "label": label,
        "date": date_match.group("date") if date_match else None,
        "temp": temp_match.group(1) if temp_match else None,
        "recognised": bool(date_match),
    }


def process_contribution(
    root: Path,
    *,
    clean: bool = False,
    validation_policy: str = "strict",
) -> dict[str, Any]:
    """
    Read battinfo.yaml, validate it, build the workspace, and return a
    summary dict suitable for printing or downstream use.
    """
    root = Path(root).resolve()
    manifest = load_contribution_manifest(root)

    errors = validate_contribution_manifest(manifest)
    csv_files = _scan_data_files(root)
    file_descriptions = [_describe_csv(f) for f in csv_files]
    warnings = [d["name"] for d in file_descriptions if not d["recognised"]]

    result: dict[str, Any] = {
        "root": str(root),
        "cell_name": manifest.get("cell_name"),
        "cell_type_iri": manifest.get("cell_type_iri"),
        "lab": manifest.get("lab"),
        "license": manifest.get("license", "CC-BY-4.0"),
        "files": file_descriptions,
        "warnings": warnings,
        "errors": errors,
        "build": None,
    }

    if errors:
        return result

    # Write the ingest manifest so build_ingest_workspace can find it
    _write_ingest_manifest(root, manifest)

    build = build_ingest_workspace(
        root,
        manifest_path=root / INGEST_MANIFEST,
        clean=clean,
        validation_policy=validation_policy,
        bundle=True,
    )
    result["build"] = build
    return result


# ── Zenodo publish ─────────────────────────────────────────────────────────────

def publish_to_zenodo(
    root: Path,
    *,
    token: str,
    sandbox: bool = False,
    community: str = "battery-genome",
) -> dict[str, Any]:
    """Build (if needed) and publish to Zenodo. Returns deposit metadata."""
    from battinfo.zenodo import ZenodoClient

    root = Path(root).resolve()
    dist = root / ".battinfo" / "ingest" / root.name / "workspace" / "dist"
    intake_path = dist / "registry-intake.json"

    if not intake_path.exists():
        raise FileNotFoundError(
            f"No processed workspace found. Run `battinfo dataset process {root}` first."
        )

    manifest = load_contribution_manifest(root)
    intake = json.loads(intake_path.read_text(encoding="utf-8"))

    cell_type_iri = manifest.get("cell_type_iri")
    cell_name = manifest.get("cell_name", root.name)
    lab = manifest.get("lab", "")
    license_id = manifest.get("license", "CC-BY-4.0")

    title = f"{lab} – {cell_name} battery dataset" if lab else f"{cell_name} battery dataset"
    description = (
        f"Battery measurement dataset for {cell_name}"
        + (f" ({lab})" if lab else "")
        + f", published via BattINFO on {datetime.now(timezone.utc).date().isoformat()}."
    )

    client = ZenodoClient(token=token, sandbox=sandbox)

    # Create the deposit draft
    metadata = {
        "title": title,
        "description": description,
        "upload_type": "dataset",
        "license": license_id.lower(),
        "communities": [{"identifier": community}] if community else [],
        "keywords": _extract_keywords(manifest, intake),
        "related_identifiers": _related_identifiers(cell_type_iri, intake),
    }
    if manifest.get("experimenter"):
        metadata["creators"] = [{"name": manifest["experimenter"]}]

    deposit = client.create_deposit(metadata)
    deposit_id = deposit["id"]

    # Upload dist/ files
    upload_files = _collect_upload_files(dist)
    file_map = client.upload_files(deposit_id, upload_files)

    # Patch distribution URLs to Zenodo links and re-upload intake
    patched_intake = _patch_intake_urls(intake, file_map, dist)
    patched_intake_path = dist / "registry-intake.zenodo.json"
    patched_intake_path.write_text(
        json.dumps(patched_intake, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    client.upload_files(deposit_id, {patched_intake_path: "registry-intake.json"})

    return {
        "deposit_id": deposit_id,
        "deposit_url": deposit.get("links", {}).get("html", ""),
        "doi": deposit.get("doi") or deposit.get("prereserve_doi", {}).get("doi"),
        "files_uploaded": len(file_map),
        "status": "draft",
    }


def _extract_keywords(manifest: dict, intake: dict) -> list[str]:
    keywords = ["battery", "BattINFO"]
    if lab := manifest.get("lab"):
        keywords.append(lab)
    for resource in intake.get("resources", []):
        if resource.get("resource_type") == "dataset":
            sp = resource.get("semantic_payload", {})
            batt = sp.get("battinfo_records", {}).get("dataset", {}).get("dataset", {})
            name = batt.get("name", "")
            for token in ["ici", "rate", "capacity"]:
                if token in name.lower():
                    keywords.append(DATASET_TITLE_LABELS.get(token, token))
    return list(dict.fromkeys(keywords))  # deduplicate, preserve order


def _related_identifiers(cell_type_iri: str | None, intake: dict) -> list[dict]:
    ids = []
    if cell_type_iri:
        ids.append({"identifier": cell_type_iri, "relation": "isSupplementTo", "scheme": "url"})
    for resource in intake.get("resources", []):
        iri = resource.get("canonical_iri")
        if iri and iri not in {d["identifier"] for d in ids}:
            ids.append({"identifier": iri, "relation": "isPartOf", "scheme": "url"})
    return ids


def _collect_upload_files(dist: Path) -> dict[Path, str]:
    """Return {local_path: zenodo_filename} for all publishable dist files."""
    files: dict[Path, str] = {}
    for path in dist.rglob("*"):
        if path.is_file() and path.name != "registry-intake.zenodo.json":
            rel = path.relative_to(dist)
            files[path] = str(rel).replace("\\", "/")
    return files


def _patch_intake_urls(intake: dict, file_map: dict[Path, str], dist: Path) -> dict:
    """Replace local distribution access_urls with Zenodo file links."""
    import copy
    patched = copy.deepcopy(intake)
    url_map = {str(local): zenodo_url for local, zenodo_url in file_map.items()}

    def _walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(v) for v in obj]
        if isinstance(obj, str):
            # Match local paths that appear in distributions
            for local_str, zenodo_url in url_map.items():
                if obj.endswith(Path(local_str).name):
                    return zenodo_url
        return obj

    return _walk(patched)
