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
    _infer_csv_kind,
    _resolve_kind_map,
    build_ingest_workspace,
)

# Extended token → BatteryTestType mapping for package_batch file scanning.
# Keys are lowercase substrings matched against the filename.
_FILENAME_KIND_MAP: dict[str, str] = {
    "capacity_check": "capacity_check",
    "capacity": "capacity_check",
    "rate_capability": "rate_capability",
    "rate": "rate_capability",
    "cycle_life": "cycling",
    "cycling": "cycling",
    "cycle": "cycling",
    "ici": "ici",
    "hppc": "hppc",
    "gitt": "gitt",
    "dcir": "dcir",
    "eis": "eis",
    "impedance": "eis",
    "calendar": "calendar_ageing",
    "formation": "formation",
}

CONTRIBUTION_MANIFEST = "battinfo.yaml"
ANNOTATIONS_MANIFEST = "battinfo-annotations.yaml"
INGEST_MANIFEST = "battinfo.ingest.json"
TEMPLATE_DIR = Path(__file__).parent / "data" / "templates" / "contribution"

# Globs used when the template folder structure (data/, photos/) is in use
CONTRIBUTION_TIMESERIES_GLOB = "data/**/*.csv"
CONTRIBUTION_PHOTO_GLOBS = ["photos/*.jpg", "photos/*.jpeg", "photos/*.png"]


# ── Init ──────────────────────────────────────────────────────────────────────

def init_contribution(
    output_path: Path,
    *,
    cell_name: str | None = None,
    cell_spec_iri: str | None = None,
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
    if cell_spec_iri:
        text = _patch(text, "cell_spec_iri", cell_spec_iri)
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
    if not manifest.get("cell_spec_iri"):
        errors.append(
            "cell_spec_iri is required. Find the IRI at "
            "https://www.battery-genome.org/registry/cell-spec"
        )
    if not manifest.get("cell_name"):
        errors.append("cell_name is required (e.g. a serial number or lab label).")
    if not manifest.get("lab"):
        errors.append("lab is required (your institution or lab name).")
    return errors


def _resolve_type_record_path(cell_spec_iri: str) -> str | None:
    """Return the absolute path to the library record.json for a cell-spec IRI."""
    from battinfo.api import DEFAULT_LIBRARY_CELL_TYPES_DIR, query_library_cell_specs
    from battinfo.publication import DEFAULT_CR2032_LIBRARY_SPEC

    packaged_lib = DEFAULT_CR2032_LIBRARY_SPEC.parent
    for directory in (packaged_lib, DEFAULT_LIBRARY_CELL_TYPES_DIR):
        results = query_library_cell_specs(id=cell_spec_iri, directory=directory)
        if results:
            return results[0]["path"]
    return None


def _contribution_to_ingest_manifest(manifest: dict, root: Path) -> dict:
    """Convert battinfo.yaml fields to the battinfo.ingest.json format."""
    cell_name = manifest.get("cell_name") or root.name
    lab = manifest.get("lab") or ""
    resource_name = f"{lab} {cell_name}".strip() if lab else cell_name

    cell_spec_iri = manifest.get("cell_spec_iri") or ""
    type_record = _resolve_type_record_path(cell_spec_iri) if cell_spec_iri else None

    return {
        "resource_type": "cell-instance",
        "resource_name": resource_name,
        "resource_iri": manifest.get("cell_iri") or None,
        "type_record": type_record,
        "license": manifest.get("license") or "CC-BY-4.0",
        "publisher_id": manifest.get("publisher_id") or None,
        "source_version": manifest.get("source_version") or None,
        "rules": {
            "timeseries_glob": [CONTRIBUTION_TIMESERIES_GLOB],
            "photo_glob": CONTRIBUTION_PHOTO_GLOBS,
        },
    }


def _write_ingest_manifest(root: Path, manifest: dict) -> Path:
    ingest = {k: v for k, v in _contribution_to_ingest_manifest(manifest, root).items() if v is not None}
    path = root / INGEST_MANIFEST
    path.write_text(json.dumps(ingest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# ── Process ───────────────────────────────────────────────────────────────────

def _is_battinfo_internal(path: Path, root: Path) -> bool:
    """True if path is inside a battinfo-managed folder that should not be scanned."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return any(part.startswith(".") or part == "staging" for part in rel.parts)


def _scan_data_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in _RAW_EXTENSIONS
        and not _is_battinfo_internal(p, root)
    )


def _describe_data_file(path: Path) -> dict[str, str | None]:
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


# ── Annotation sidecar ────────────────────────────────────────────────────────

def _load_annotations(root: Path) -> dict[str, dict]:
    """Return existing annotation entries keyed by filename."""
    path = root / ANNOTATIONS_MANIFEST
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore[import-untyped]
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = {}
        for e in doc.get("files", []):
            if not isinstance(e, dict) or "file" not in e:
                continue
            # Coerce all values to str so datetime.date objects (from YAML parsing)
            # don't leak into Rich tables or JSON output.
            entries[e["file"]] = {k: str(v) if v is not None else None for k, v in e.items()}
        return entries
    except Exception:
        return {}


def _write_annotations(
    root: Path,
    file_descriptions: list[dict],
    bdf_test_types: dict[str, str | None] | None = None,
) -> tuple[Path, bool]:
    """Write/update battinfo-annotations.yaml.

    Preserves any existing manual edits; adds entries for new files.
    Returns (path, needs_review) where needs_review is True if any entry
    still has a '?' value.
    """

    existing = _load_annotations(root)
    entries = []
    needs_review = False

    for desc in file_descriptions:
        name = desc["name"]
        if name in existing:
            entry = dict(existing[name])
        else:
            entry = {"file": name}
            date_val = desc["date"] or "?"
            temp_val = desc["temp"] or "?"
            # Filename inference first, then BDF column inference as fallback
            if desc["recognised"]:
                kind_val = desc["kind"]
            elif bdf_test_types and bdf_test_types.get(name):
                kind_val = bdf_test_types[name]
            else:
                kind_val = "?"
            entry["test_type"] = kind_val
            entry["date"] = date_val
            entry["temperature_degC"] = temp_val

        if "?" in (str(v) for v in entry.values()):
            needs_review = True
        entries.append(entry)

    # Preserve entries for files that still exist even if not in current scan
    for name, entry in existing.items():
        if not any(e["file"] == name for e in entries):
            entries.append(entry)

    # yaml.dump doesn't support comment keys — write manually
    lines = ["# Review entries marked '?' and fill in the missing values.\n", "files:\n"]
    for entry in entries:
        lines.append(f"  - file: {entry['file']}\n")
        for k, v in entry.items():
            if k == "file":
                continue
            lines.append(f"    {k}: {v}\n")
    path = root / ANNOTATIONS_MANIFEST
    path.write_text("".join(lines), encoding="utf-8")
    return path, needs_review


def _apply_annotations(file_descriptions: list[dict], root: Path) -> list[dict]:
    """Merge annotation file values into file_descriptions in-place copy."""
    existing = _load_annotations(root)
    result = []
    for desc in file_descriptions:
        entry = existing.get(desc["name"], {})
        merged = dict(desc)
        if entry.get("test_type") and entry["test_type"] != "?":
            merged["kind"] = entry["test_type"]
            merged["label"] = DATASET_TITLE_LABELS.get(entry["test_type"], entry["test_type"])
            merged["recognised"] = True
        if entry.get("date") and entry["date"] != "?":
            merged["date"] = entry["date"]
            merged["recognised"] = True
        if entry.get("temperature_degC") and str(entry["temperature_degC"]) != "?":
            merged["temp"] = str(entry["temperature_degC"])
        result.append(merged)
    return result


def process_contribution(
    root: Path,
    *,
    clean: bool = False,
    validation_policy: str = "strict",
    bundle: bool = True,
) -> dict[str, Any]:
    """
    Read battinfo.yaml, validate it, build the workspace, and return a
    summary dict suitable for printing or downstream use.

    When ``bundle=False`` the workspace is built but not bundled into a
    registry-intake package.  Use this for batch→Zenodo workflows where
    bundling is handled by :func:`package_batch`.
    """
    root = Path(root).resolve()
    manifest = load_contribution_manifest(root)

    errors = validate_contribution_manifest(manifest)
    raw_files = _scan_data_files(root)
    file_descriptions = [_describe_data_file(f) for f in raw_files]

    # Convert to BDF first so inferred test types can fill annotation blanks
    conversions: dict[str, str | None] = {}
    bdf_test_types: dict[str, str | None] = {}
    if not errors:
        try:
            from battinfo.processing import convert_raw_to_bdf
            for raw in raw_files:
                bdf_path, inferred_type = convert_raw_to_bdf(raw)
                conversions[raw.name] = str(bdf_path) if bdf_path else None
                bdf_test_types[raw.name] = inferred_type
        except Exception:
            pass

    # Generate / update annotation sidecar; BDF types fill any '?' entries
    annotations_path, needs_review = _write_annotations(
        root, file_descriptions, bdf_test_types=bdf_test_types or None
    )
    file_descriptions = _apply_annotations(file_descriptions, root)
    warnings = [d["name"] for d in file_descriptions if not d["recognised"]]

    result: dict[str, Any] = {
        "root": str(root),
        "cell_name": manifest.get("cell_name"),
        "cell_spec_iri": manifest.get("cell_spec_iri"),
        "lab": manifest.get("lab"),
        "license": manifest.get("license", "CC-BY-4.0"),
        "files": file_descriptions,
        "warnings": warnings,
        "errors": errors,
        "build": None,
        "conversions": conversions,
        "bdf_test_types": bdf_test_types,
        "annotations_path": str(annotations_path),
        "needs_review": needs_review,
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
        bundle=bundle,
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

    cell_spec_iri = manifest.get("cell_spec_iri")
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
        "related_identifiers": _related_identifiers(cell_spec_iri, intake),
    }
    operator = manifest.get("operator") or manifest.get("experimenter")
    if operator:
        metadata["creators"] = [{"name": operator}]

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


def _related_identifiers(cell_spec_iri: str | None, intake: dict) -> list[dict]:
    ids = []
    if cell_spec_iri:
        ids.append({"identifier": cell_spec_iri, "relation": "isSupplementTo", "scheme": "url"})
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


# ── Shipment init ──────────────────────────────────────────────────────────────

BATCH_MANIFEST = "batch.yaml"
_CELL_TYPE_IRI_PATTERN = (
    r"^https://w3id\.org/battinfo/(?:cell|spec)/[0-9a-hjkmnp-tv-z]{4}"
    r"(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)


def _resolve_cell_spec_for_batch(cell_spec: str) -> tuple[str, str, str, str]:
    """Return (iri, display_name, manufacturer, model) for a cell-spec query.

    Accepts either a full BattINFO IRI or a free-text query like
    ``"Energizer CR2032"`` / ``"Energizer/CR2032"``.  Searches the packaged
    library first, then the local workspace library as a fallback.
    """
    import re

    from battinfo.api import DEFAULT_LIBRARY_CELL_TYPES_DIR, query_library_cell_specs
    from battinfo.publication import DEFAULT_CR2032_LIBRARY_SPEC

    packaged_lib = DEFAULT_CR2032_LIBRARY_SPEC.parent
    is_iri = bool(re.fullmatch(_CELL_TYPE_IRI_PATTERN, cell_spec.strip()))

    if is_iri:
        iri = cell_spec.strip()
        for directory in (packaged_lib, DEFAULT_LIBRARY_CELL_TYPES_DIR):
            results = query_library_cell_specs(id=iri, directory=directory)
            if results:
                r = results[0]
                return iri, f"{r['manufacturer']} {r['model']}", r["manufacturer"], r["model"]
        return iri, iri.rstrip("/").split("/")[-1], "", ""

    query = cell_spec.strip().replace("/", " ")
    parts = query.split(None, 1)
    manufacturer = parts[0] if parts else query
    model = parts[1] if len(parts) > 1 else None

    results = []
    for directory in (packaged_lib, DEFAULT_LIBRARY_CELL_TYPES_DIR):
        results = query_library_cell_specs(
            manufacturer=manufacturer,
            model_contains=model,
            directory=directory,
        )
        if results:
            break

    if not results:
        raise ValueError(
            f"No cell type found matching {cell_spec!r}. "
            "Check the library or pass the IRI directly."
        )
    if len(results) > 1:
        options = "\n".join(
            f"  {r['manufacturer']} {r['model']}  ({r['id']})" for r in results[:5]
        )
        raise ValueError(
            f"Multiple cell types match {cell_spec!r}. "
            f"Be more specific or pass the IRI directly.\n{options}"
        )

    r = results[0]
    return r["id"], f"{r['manufacturer']} {r['model']}", r["manufacturer"], r["model"]


def _slugify(text: str) -> str:
    """Lower-case, spaces → hyphens, strip non-alphanumeric."""
    import re
    return re.sub(r"[^a-z0-9-]", "", re.sub(r"\s+", "-", text.lower().strip()))


def _cell_short_id(cell_iri: str) -> str:
    """Extract the 6-character short ID from a cell instance IRI."""
    return cell_iri.rstrip("/").split("/")[-1].replace("-", "")[:6]


def _cell_folder_name(
    cell_iri: str,
    manufacturer: str,
    model: str,
    serial_number: str | None = None,
) -> str:
    """Build a folder name: manufacturer-Model-shortid.

    Uses the serial number as the folder name when provided (slugified).
    Otherwise derives the name from the cell instance IRI short ID.
    """
    if serial_number:
        slug = _slugify(serial_number)
        if slug:
            return slug
    mfr = _slugify(manufacturer)
    short_id = _cell_short_id(cell_iri)
    parts = [p for p in (mfr, model, short_id) if p]
    return "-".join(parts) if parts else short_id


def _generate_cell_iri(
    cell_spec_iri: str,
    batch_id: str | None,
    index: int,
    serial_number: str | None = None,
) -> str:
    """Mint a deterministic cell instance IRI.

    The seed is stable: same cell_spec + batch + serial (or index) always
    produces the same IRI, so re-running init on an existing batch is safe.
    """
    from battinfo.publication import _entity_iri
    seed_parts = [cell_spec_iri, batch_id or "batch"]
    if serial_number:
        seed_parts.append(serial_number)
    else:
        seed_parts.append(str(index))
    return _entity_iri("cell", "::".join(seed_parts))


_CELL_YAML_TEMPLATE = """\
# BattINFO cell contribution manifest
# ─────────────────────────────────────────────────────────────────────────────
# 1. Review the fields below (everything above the dashed line).
# 2. Drop your data files into this folder.
# 3. Run: battinfo dataset process <batch-folder>
# ─────────────────────────────────────────────────────────────────────────────

cell_name: {cell_name!r}
batch_id: {batch_id}
lab: {lab}
operator: {operator}
project: {project}
license: {license!r}

# ── Managed by battinfo — do not edit below ──────────────────────────────────
cell_spec_iri: {cell_spec_iri!r}
cell_iri: {cell_iri}
publisher_id: null
source_version: null
"""


def init_batch(
    output_dir: Path,
    cell_spec: str,
    count: int,
    *,
    batch_id: str | None = None,
    lab: str | None = None,
    operator: str | None = None,
    project: str | None = None,
    license: str = "CC-BY-4.0",
    cell_iris: list[str] | None = None,
    serial_numbers: list[str] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Scaffold a multi-cell batch directory.

    Creates one sub-folder per cell under *output_dir*, each pre-populated
    with a ``battinfo.yaml`` manifest and a ``data/`` folder and
    ``data/eis/`` sub-directories.

    Args:
        output_dir: Root directory to create (must not exist unless
                    *overwrite* is True).
        cell_spec: BattINFO cell-spec IRI **or** a free-text query like
                   ``"Energizer CR2032"`` — resolved via the library.
        count: Number of cell instances to scaffold.
        batch_id: Batch / lot identifier stamped on every manifest.
        lab: Institution name stamped on every manifest.
        operator: Person who operates the test equipment (stamped on every
                  manifest).
        project: Project name or ID this batch belongs to.
        license: SPDX licence identifier (default ``CC-BY-4.0``).
        cell_iris: Pre-assigned BattINFO cell IRIs, one per cell (length
                   must equal *count* when provided).
        serial_numbers: Known serial numbers, one per cell.  Used as
                        folder names when provided.
        overwrite: Allow writing into an existing directory.

    Returns:
        Dict with ``output_dir``, ``cell_spec_iri``, ``cell_spec_name``,
        ``count``, and ``cells`` (list of per-cell dicts).
    """
    output_dir = Path(output_dir).resolve()

    if cell_iris is not None and len(cell_iris) != count:
        raise ValueError(
            f"cell_iris length ({len(cell_iris)}) must equal count ({count})."
        )
    if serial_numbers is not None and len(serial_numbers) != count:
        raise ValueError(
            f"serial_numbers length ({len(serial_numbers)}) must equal count ({count})."
        )

    cell_spec_iri, cell_spec_name, manufacturer, model = _resolve_cell_spec_for_batch(cell_spec)

    if output_dir.exists() and not overwrite:
        raise FileExistsError(
            f"{output_dir} already exists. Pass overwrite=True or choose a different path."
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── batch.yaml ─────────────────────────────────────────────────────────────
    shipment_meta: dict[str, Any] = {
        "cell_spec_iri": cell_spec_iri,
        "cell_spec_name": cell_spec_name,
        "manufacturer": manufacturer,
        "model": model,
        "count": count,
        "batch_id": batch_id,
        "lab": lab,
        "operator": operator,
        "project": project,
        "license": license,
    }
    _write_yaml(output_dir / BATCH_MANIFEST, shipment_meta)

    # ── per-cell folders ───────────────────────────────────────────────────────
    cells: list[dict[str, Any]] = []
    for i in range(count):
        sn = serial_numbers[i].strip() if serial_numbers else None
        cell_iri = (
            cell_iris[i]
            if cell_iris
            else _generate_cell_iri(cell_spec_iri, batch_id, i, sn)
        )
        folder_name = _cell_folder_name(cell_iri, manufacturer, model, sn)
        cell_name = sn or folder_name

        cell_dir = output_dir / folder_name
        cell_dir.mkdir(exist_ok=True)
        cell_dir.mkdir(parents=True, exist_ok=True)
        (cell_dir / "photos").mkdir(exist_ok=True)

        manifest_text = _CELL_YAML_TEMPLATE.format(
            cell_name=cell_name,
            cell_spec_iri=cell_spec_iri,
            cell_iri=repr(cell_iri),
            batch_id=repr(batch_id) if batch_id else "null",
            lab=repr(lab) if lab else "null",
            operator=repr(operator) if operator else "null",
            project=repr(project) if project else "null",
            license=license,
        )
        (cell_dir / CONTRIBUTION_MANIFEST).write_text(manifest_text, encoding="utf-8")

        cells.append({
            "folder": folder_name,
            "cell_name": cell_name,
            "cell_iri": cell_iri,
        })

    return {
        "output_dir": str(output_dir),
        "cell_spec_iri": cell_spec_iri,
        "cell_spec_name": cell_spec_name,
        "count": count,
        "cells": cells,
    }


def load_batch_manifest(batch_dir: Path) -> dict[str, Any]:
    """Load and return the batch.yaml manifest from *batch_dir*."""
    manifest_path = Path(batch_dir) / BATCH_MANIFEST
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"No {BATCH_MANIFEST} found in {batch_dir}. "
            "Run `battinfo batch init` first."
        )
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}


def add_to_batch(
    batch_dir: Path,
    count: int,
    *,
    batch_id: str | None = None,
    lab: str | None = None,
    operator: str | None = None,
    project: str | None = None,
    license: str | None = None,
    cell_iris: list[str] | None = None,
    serial_numbers: list[str] | None = None,
) -> dict[str, Any]:
    """Add *count* more cell folders to an existing batch directory.

    Reads ``batch.yaml`` to inherit cell type, lab, operator, project and
    current count.  New cell folders are numbered sequentially after the
    existing ones.  Any keyword argument that is not None overrides the
    corresponding value from ``batch.yaml`` for the new cells only.

    Updates ``count`` in ``batch.yaml`` after creating the new folders.

    Args:
        batch_dir: Root directory created by ``init_batch``.
        count: Number of additional cells to add.
        batch_id: Override batch / lot ID for the new cells.
        lab: Override lab name for the new cells.
        operator: Override operator for the new cells.
        project: Override project for the new cells.
        license: Override licence for the new cells.
        cell_iris: Pre-assigned IRIs for the new cells (length must equal
                   *count* when provided).
        serial_numbers: Serial numbers for the new cells, used as folder
                        names (length must equal *count* when provided).

    Returns:
        Dict with ``batch_dir``, ``added``, ``new_cells``, and updated
        ``total_count``.
    """
    batch_dir = Path(batch_dir).resolve()

    if cell_iris is not None and len(cell_iris) != count:
        raise ValueError(
            f"cell_iris length ({len(cell_iris)}) must equal count ({count})."
        )
    if serial_numbers is not None and len(serial_numbers) != count:
        raise ValueError(
            f"serial_numbers length ({len(serial_numbers)}) must equal count ({count})."
        )

    manifest = load_batch_manifest(batch_dir)

    cell_spec_iri: str = manifest["cell_spec_iri"]
    cell_spec_name: str = manifest.get("cell_spec_name", "")
    manufacturer: str = manifest.get("manufacturer", "")
    model: str = manifest.get("model", "")
    existing_count: int = int(manifest.get("count") or 0)

    effective_batch_id = batch_id if batch_id is not None else manifest.get("batch_id")
    effective_lab = lab if lab is not None else manifest.get("lab")
    effective_operator = operator if operator is not None else manifest.get("operator")
    effective_project = project if project is not None else manifest.get("project")
    effective_license = license if license is not None else manifest.get("license", "CC-BY-4.0")

    new_cells: list[dict[str, Any]] = []
    for i in range(count):
        sn = serial_numbers[i].strip() if serial_numbers else None
        cell_iri = (
            cell_iris[i]
            if cell_iris
            else _generate_cell_iri(cell_spec_iri, effective_batch_id, existing_count + i, sn)
        )
        folder_name = _cell_folder_name(cell_iri, manufacturer, model, sn)
        cell_name = sn or folder_name

        cell_dir = batch_dir / folder_name
        if cell_dir.exists():
            raise FileExistsError(
                f"{cell_dir} already exists. "
                "Remove it or choose different serial numbers."
            )
        cell_dir.mkdir()
        cell_dir.mkdir(parents=True, exist_ok=True)
        (cell_dir / "photos").mkdir()

        manifest_text = _CELL_YAML_TEMPLATE.format(
            cell_name=cell_name,
            cell_spec_iri=cell_spec_iri,
            cell_iri=repr(cell_iri),
            batch_id=repr(effective_batch_id) if effective_batch_id else "null",
            lab=repr(effective_lab) if effective_lab else "null",
            operator=repr(effective_operator) if effective_operator else "null",
            project=repr(effective_project) if effective_project else "null",
            license=effective_license,
        )
        (cell_dir / CONTRIBUTION_MANIFEST).write_text(manifest_text, encoding="utf-8")
        new_cells.append({"folder": folder_name, "cell_name": cell_name, "cell_iri": cell_iri})

    manifest["count"] = existing_count + count
    _write_yaml(batch_dir / BATCH_MANIFEST, manifest)

    return {
        "batch_dir": str(batch_dir),
        "added": count,
        "new_cells": new_cells,
        "total_count": existing_count + count,
        "cell_spec_iri": cell_spec_iri,
        "cell_spec_name": cell_spec_name,
    }


# ── Batch package ──────────────────────────────────────────────────────────────

# File extensions treated as raw data (not BDF output)
_RAW_EXTENSIONS = {".csv", ".nda", ".ndax", ".ccs", ".txt", ".xlsx", ".mpt", ".mpr", ".idf", ".dta"}


def _group_files_by_cell(folder: Path) -> dict[str, list[Path]]:
    """Detect cell groupings from a flat folder of raw data files.

    Tries a series of filename patterns to find a consistent numeric token
    that identifies the cell/channel number.  Falls back to treating all
    files as a single cell if no pattern matches.

    Returns an ordered dict mapping cell_key (e.g. ``"1"``, ``"2"``) to a
    list of :class:`Path` objects for that cell's files.
    """
    import re

    raw = [
        f for f in sorted(folder.iterdir())
        if f.is_file()
        and f.suffix.lower() in _RAW_EXTENSIONS
        and not _is_battinfo_internal(f, folder)
    ]
    if not raw:
        return {}
    if len(raw) == 1:
        return {"1": raw}

    # Patterns tried in order — first one that matches ALL files and yields
    # more than one group is used.
    _CELL_PATTERNS = [
        # Named prefix: Channel_1, CH-2, Cell3, Unit_04, ch1
        r'(?:channel|ch|cell|unit|c)[-_]?0*(\d+)',
        # Trailing number before extension: test_C01.csv → 1, run003.nda → 3
        r'[-_]0*(\d+)$',
        # Leading number: 1_test.csv, 01_run.nda
        r'^0*(\d+)[-_]',
        # Any isolated number: test_1_25degC.csv → position matters below
    ]

    for pattern in _CELL_PATTERNS:
        groups: dict[str, list[Path]] = {}
        matched = 0
        for f in raw:
            m = re.search(pattern, f.stem, re.IGNORECASE)
            if m:
                key = str(int(m.group(1)))  # normalise leading zeros
                groups.setdefault(key, []).append(f)
                matched += 1
        if matched == len(raw) and len(groups) > 1:
            # Sort groups by numeric key
            return dict(sorted(groups.items(), key=lambda kv: int(kv[0])))

    # Last resort: find the numeric token that has the most variation across
    # files while keeping all other tokens constant.
    tokens_per_file = []
    for f in raw:
        tokens_per_file.append(re.findall(r'\d+', f.stem))

    if tokens_per_file:
        n_tokens = min(len(t) for t in tokens_per_file)
        for pos in range(n_tokens):
            values = [t[pos] for t in tokens_per_file if len(t) > pos]
            unique = set(int(v) for v in values)
            if len(unique) > 1 and len(unique) == len(raw):
                groups = {}
                for f, t in zip(raw, tokens_per_file):
                    key = str(int(t[pos]))
                    groups.setdefault(key, []).append(f)
                return dict(sorted(groups.items(), key=lambda kv: int(kv[0])))

    # Cannot detect grouping — treat as single cell
    return {"1": raw}


def _collect_data_files(cell_dir: Path) -> list[tuple[Path, Path | None]]:
    """Return (raw_file, bdf_or_None) pairs from a cell folder.

    Scans the cell folder recursively, skipping battinfo-internal paths
    (``.battinfo/``, ``staging/``).  For each raw file, checks for a sibling
    ``<stem>.bdf.parquet`` file.
    """
    pairs: list[tuple[Path, Path | None]] = []
    for raw in sorted(cell_dir.rglob("*")):
        if not raw.is_file():
            continue
        if raw.suffix.lower() not in _RAW_EXTENSIONS:
            continue
        if _is_battinfo_internal(raw, cell_dir):
            continue
        bdf = raw.parent / (raw.stem + ".bdf.parquet")
        pairs.append((raw, bdf if bdf.exists() else None))
    return pairs


def _test_kind_from_path(path: Path, subdir_name: str = "") -> str:
    """Infer BatteryTestType string from filename tokens.

    Falls back to the containing folder name as a hint (e.g. legacy ``eis/``
    sub-folder) when no filename token matches.
    """
    name_lower = path.stem.lower()
    for token, kind in _FILENAME_KIND_MAP.items():
        if token in name_lower:
            return kind
    # Legacy subdirectory hint
    if subdir_name in _FILENAME_KIND_MAP:
        return _FILENAME_KIND_MAP[subdir_name]
    return "other"


def _load_cell_spec_for_batch(cell_spec_iri: str) -> tuple[Any, Any]:
    """Return (CellSpecification, CellSpecification | None) for a cell-spec IRI.

    Searches the packaged library first, then the local workspace library.
    Falls back to a minimal CellSpecification carrying only the IRI.
    """
    from battinfo.api import DEFAULT_LIBRARY_CELL_TYPES_DIR, query_library_cell_specs
    from battinfo.bundle import CellSpecification
    from battinfo.publication import DEFAULT_CR2032_LIBRARY_SPEC

    packaged_lib = DEFAULT_CR2032_LIBRARY_SPEC.parent
    for directory in (packaged_lib, DEFAULT_LIBRARY_CELL_TYPES_DIR):
        results = query_library_cell_specs(id=cell_spec_iri, directory=directory)
        if results:
            spec = CellSpecification.from_library_record(results[0]["record"])
            ct = CellSpecification.from_cell_specification(spec, id=cell_spec_iri)
            return ct, spec
    return CellSpecification(id=cell_spec_iri), None


def package_batch(
    batch_dir: Path,
    staging_dir: Path | None = None,
    *,
    creators: list[dict[str, Any]],
    community: str | None = "battinfo-reference",
    zenodo_record_id_placeholder: str = "ZENODO_RECORD_ID",
) -> dict[str, Any]:
    """Collect all cells in a batch into a flat Zenodo upload package.

    Reads ``batch.yaml``, discovers all cell sub-folders, collects raw data
    files from each cell's ``data/timeseries/`` and ``data/eis/`` directories,
    builds a :class:`ZenodoCellRecord`, and calls :func:`build_zenodo_package`
    to produce the staging directory.

    Args:
        batch_dir: Root directory created by ``init_batch``.
        staging_dir: Output directory for the Zenodo package.  Defaults to
                     ``<batch_dir>/staging/``.
        creators: Zenodo creator list, e.g.
                  ``[{"name": "Clark, Simon", "affiliation": "SINTEF"}]``.
        community: Zenodo community identifier for submission.
        zenodo_record_id_placeholder: Placeholder token embedded in URLs
                                      before upload.

    Returns:
        The result dict from :func:`build_zenodo_package` (``staging_dir``,
        ``bundle_path``, ``publish_path``, ``ro_crate_path``,
        ``staged_data_files``, ``file_url_map``, etc.) plus
        ``cell_count``, ``entry_count``.
    """
    from battinfo.bundle import (
        CellInstance,
        Dataset,
        ProvenanceInfo,
        Test,
        ZenodoCellRecord,
        ZenodoDatasetEntry,
    )
    from battinfo.publication import (
        _finalize_cell_instance,
        _finalize_cell_spec,
        _finalize_dataset,
        _finalize_test,
        build_zenodo_package,
    )

    if not creators:
        raise ValueError("creators must be a non-empty list.")

    batch_dir = Path(batch_dir).resolve()
    manifest = load_batch_manifest(batch_dir)
    cell_spec_iri: str = manifest["cell_spec_iri"]

    raw_cell_spec, cell_spec = _load_cell_spec_for_batch(cell_spec_iri)
    cell_spec = _finalize_cell_spec(raw_cell_spec, cell_specification=cell_spec)

    # Discover cell sub-folders: any directory with a battinfo.yaml
    cell_dirs = sorted(
        d for d in batch_dir.iterdir()
        if d.is_dir() and (d / CONTRIBUTION_MANIFEST).exists()
    )
    if not cell_dirs:
        raise ValueError(
            f"No cell folders with {CONTRIBUTION_MANIFEST!r} found in {batch_dir}. "
            "Run `battinfo batch init` first."
        )

    entries: list[ZenodoDatasetEntry] = []
    file_sets: list[tuple[Path | None, Path | None]] = []
    # Fail closed on duplicate cell IRIs across folders (e.g. two cells sharing a
    # serial / cell_name): publishing both would silently overwrite one on ingest.
    # A unique cell IRI is necessary but NOT sufficient — distinct data files within one
    # cell can still mint colliding test IRIs, so the test seed below carries a per-file
    # discriminator and build_zenodo_package asserts test/dataset @id uniqueness.
    seen_cell_iris: dict[str, str] = {}

    for cell_dir in cell_dirs:
        cell_manifest = yaml.safe_load(
            (cell_dir / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8")
        ) or {}

        raw_ci = CellInstance(
            id=cell_manifest.get("cell_iri") or None,
            cell_spec_id=cell_spec.id,
            name=cell_manifest.get("cell_name"),
            serial_number=cell_manifest.get("cell_name"),
            batch_id=cell_manifest.get("batch_id") or manifest.get("batch_id"),
            source=ProvenanceInfo(
                type="measurement",
                url=(cell_dir / "data").resolve().as_uri(),
            ),
        )
        ci = _finalize_cell_instance(raw_ci, cell_spec=cell_spec, dataset_dir=cell_dir)
        if ci.id is not None:
            prior = seen_cell_iris.get(ci.id)
            if prior is not None:
                raise ValueError(
                    f"Cell folders {prior!r} and {cell_dir.name!r} resolve to the same cell IRI "
                    f"({ci.id}) — two cells must not share a serial / cell_name within a batch, or "
                    "one would silently overwrite the other on ingest. Give each cell a unique serial."
                )
            seen_cell_iris[ci.id] = cell_dir.name

        pairs = _collect_data_files(cell_dir)
        if not pairs:
            continue

        for raw_path, bdf_path in pairs:
            subdir_name = raw_path.parent.name
            test_kind = _test_kind_from_path(raw_path, subdir_name)
            # raw_path.stem is unique per file in the folder, so two same-kind data files
            # in one cell mint distinct test IRIs. The filename date alone is insufficient:
            # undated same-kind files previously collided onto one test @id and overwrote
            # each other on ingest.
            test_name = f"{ci.name or cell_dir.name} {test_kind} {raw_path.stem}"

            raw_test = Test(
                cell_instance_id=ci.id,
                name=test_name,
                test_kind=test_kind,
                source=ProvenanceInfo(type="measurement"),
            )
            test = _finalize_test(raw_test, cell_instance=ci, dataset_dir=cell_dir)

            ds_name = f"{cell_spec.name} {ci.name or cell_dir.name} {raw_path.stem}"
            raw_ds = Dataset(
                name=ds_name,
                cell_instance_id=ci.id,
                test_id=test.id,
                source=ProvenanceInfo(type="measurement"),
            )
            ds = _finalize_dataset(raw_ds, cell_instance=ci, test=test, dataset_dir=cell_dir)

            entries.append(ZenodoDatasetEntry(
                cell_instances=[ci],
                test=test,
                dataset=ds,
            ))
            file_sets.append((raw_path, bdf_path))

    if not entries:
        raise ValueError(
            "No raw data files found. "
            "Add data files to the data/ folder in each cell folder."
        )

    record = ZenodoCellRecord(
        cell_spec=cell_spec,
        cell_specification=cell_spec,
        datasets=entries,
    )

    if staging_dir is None:
        staging_dir = batch_dir / "staging"

    result = build_zenodo_package(
        record,
        staging_dir,
        file_sets,
        zenodo_record_id_placeholder=zenodo_record_id_placeholder,
    )
    result["cell_count"] = len(cell_dirs)
    result["entry_count"] = len(entries)
    return result


# ── Push (end-to-end) ─────────────────────────────────────────────────────────

def push_batch(
    folder: Path,
    cell_spec: str | None = None,
    staging_dir: Path | None = None,
    *,
    creators: list[dict[str, Any]],
    zenodo_token: str | None = None,
    sandbox: bool = False,
    community: str | None = "battinfo-reference",
    confirm: bool = True,
    dry_run: bool = False,
    n_cells: int | None = None,
    batch_id: str | None = None,
    lab: str | None = None,
    operator: str | None = None,
) -> dict[str, Any]:
    """End-to-end: detect/init batch -> process -> package -> upload.

    Handles three input layouts:

    1. **Already a battinfo batch** (folder contains ``batch.yaml``): skips
       init, processes all cell sub-folders.
    2. **Sub-folder layout** (folder contains sub-directories each with raw
       files, no ``batch.yaml``): treats each sub-directory as one cell.
    3. **Flat folder** (raw files at root level): groups by filename pattern,
       creates cell sub-folders, moves files, then proceeds.

    Returns a summary dict with keys: ``status``, ``zenodo_url``, ``cells``,
    ``files``, ``staging_dir``.  When *dry_run* is ``True`` returns the same
    dict with ``status="dry_run"`` and no Zenodo upload.
    """
    import shutil

    folder = Path(folder).resolve()

    # ── Detect layout ──────────────────────────────────────────────────────────
    is_batch = (folder / BATCH_MANIFEST).exists()
    has_cell_subdirs = not is_batch and any(
        (d / CONTRIBUTION_MANIFEST).exists()
        for d in folder.iterdir()
        if d.is_dir()
    )

    if not is_batch and not has_cell_subdirs:
        # Flat or sub-folder layout — need to create batch structure
        if cell_spec is None:
            raise ValueError(
                "cell_spec is required when folder is not already a battinfo batch. "
                "Pass cell_spec='Manufacturer Model'."
            )

        # Check if sub-directories contain raw files (sub-folder layout)
        subdirs_with_files = [
            d for d in sorted(folder.iterdir())
            if d.is_dir()
            and not _is_battinfo_internal(d, folder)
            and any(f.suffix.lower() in _RAW_EXTENSIONS for f in d.iterdir() if f.is_file())
        ]

        if subdirs_with_files:
            # Sub-folder layout: each subdir becomes a cell
            groups = {d.name: list(sorted(
                f for f in d.iterdir()
                if f.is_file() and f.suffix.lower() in _RAW_EXTENSIONS
            )) for d in subdirs_with_files}
        else:
            # Flat layout: group by filename pattern then move
            groups = _group_files_by_cell(folder)
            if not groups:
                raise ValueError(f"No raw data files found in {folder}.")

            # Move files into cell sub-folders
            cell_count = n_cells or len(groups)
            result_init = init_batch(
                folder,
                cell_spec,
                cell_count,
                batch_id=batch_id,
                lab=lab,
                operator=operator,
                overwrite=False,
            )
            for (cell_key, files), cell_info in zip(
                sorted(groups.items(), key=lambda kv: int(kv[0])),
                result_init["cells"],
            ):
                dest = folder / cell_info["folder"]
                for f in files:
                    shutil.move(str(f), str(dest / f.name))
            is_batch = True

        if not is_batch:
            # Sub-folder layout: init batch over the existing sub-dirs
            result_init = init_batch(
                folder,
                cell_spec,
                len(subdirs_with_files),
                batch_id=batch_id,
                lab=lab,
                operator=operator,
                overwrite=False,
            )
            # Move each subdir's files into the corresponding cell folder
            for subdir, cell_info in zip(subdirs_with_files, result_init["cells"]):
                dest = folder / cell_info["folder"]
                for f in subdir.iterdir():
                    if f.is_file() and f.suffix.lower() in _RAW_EXTENSIONS:
                        shutil.move(str(f), str(dest / f.name))
            is_batch = True

    # ── Process all cells ──────────────────────────────────────────────────────
    cell_dirs = sorted(
        d for d in folder.iterdir()
        if d.is_dir() and (d / CONTRIBUTION_MANIFEST).exists()
    )
    for cell_dir in cell_dirs:
        process_contribution(cell_dir, bundle=False)

    # ── Package ────────────────────────────────────────────────────────────────
    if staging_dir is None:
        staging_dir = folder / "staging"

    pkg = package_batch(
        folder,
        staging_dir,
        creators=creators,
        community=community,
    )

    summary: dict[str, Any] = {
        "status": "dry_run" if dry_run else "pending_upload",
        "staging_dir": pkg["staging_dir"],
        "cells": pkg["cell_count"],
        "files": pkg["entry_count"],
        "zenodo_url": None,
    }

    if dry_run or not zenodo_token:
        return summary

    # ── Upload ─────────────────────────────────────────────────────────────────
    from battinfo.zenodo import upload_zenodo_package

    upload_result = upload_zenodo_package(
        staging_dir,
        creators,
        token=zenodo_token,
        sandbox=sandbox,
        community=community,
        publish=False,
    )
    summary["status"] = "draft"
    summary["zenodo_url"] = upload_result.get("deposit_url") or upload_result.get("html_url")
    return summary
