from __future__ import annotations

import html
import json
import re
import secrets
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

PathLike = str | Path

UID_UNDASHED_RE = re.compile(r"^[0-9a-hjkmnp-tv-z]{16}$")
UID_DASHED_RE = re.compile(r"^[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$")
UID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"

CELL_TYPE_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/cell-type/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)
CELL_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/cell/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)
DATASET_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/dataset/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)

PACKAGE_ROOT = Path(__file__).resolve().parent
EXAMPLES_ROOT = PACKAGE_ROOT / "data" / "examples"
SCHEMAS_ROOT = PACKAGE_ROOT / "data" / "schemas"

DEFAULT_CELLS_CLEAN_DIR = EXAMPLES_ROOT / "cells-clean"
DEFAULT_CELL_TYPES_DIR = EXAMPLES_ROOT / "cell-types"
DEFAULT_CELL_INSTANCES_DIR = EXAMPLES_ROOT / "cell-instances"
DEFAULT_DATASETS_DIR = EXAMPLES_ROOT / "datasets"
DEFAULT_PUBLISH_SOURCES = (
    DEFAULT_CELL_TYPES_DIR,
    DEFAULT_CELL_INSTANCES_DIR,
    DEFAULT_DATASETS_DIR,
)
DEFAULT_INDEX_SOURCE_ROOT = EXAMPLES_ROOT


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_path(path: PathLike) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _normalized_dashed_uid(value: str | None = None) -> str:
    if value is None:
        token = "".join(secrets.choice(UID_ALPHABET) for _ in range(16))
        return "-".join((token[:4], token[4:8], token[8:12], token[12:16]))

    token = value.strip().lower().replace("-", "")
    token = token.replace("o", "0").replace("i", "1").replace("l", "1")
    if not UID_UNDASHED_RE.fullmatch(token):
        raise ValueError("UID must be 16 Crockford Base32 characters (dashed or undashed).")
    return "-".join((token[:4], token[4:8], token[8:12], token[12:16]))


def _short_id_from_iri(iri: str) -> str:
    tail = iri.rstrip("/").split("/")[-1]
    return tail.replace("-", "")[:6]


def _str_eq(left: object, right: str | None) -> bool:
    if right is None:
        return True
    if left is None:
        return False
    return str(left).lower() == right.lower()


def _str_contains(value: object, needle: str | None) -> bool:
    if needle is None:
        return True
    if value is None:
        return False
    return needle.lower() in str(value).lower()


def _in_range(value: float | None, minimum: float | None, maximum: float | None) -> bool:
    if minimum is not None and (value is None or value < minimum):
        return False
    if maximum is not None and (value is None or value > maximum):
        return False
    return True


def _paginate(items: list[dict[str, Any]], limit: int, offset: int) -> list[dict[str, Any]]:
    if offset < 0:
        offset = 0
    if limit <= 0:
        return []
    return items[offset : offset + limit]


def _spec_numeric_value(specs: Mapping[str, Any], key: str) -> float | None:
    item = specs.get(key)
    if not isinstance(item, Mapping):
        return None
    for candidate in ("value", "value_typical", "value_max", "value_min"):
        val = item.get(candidate)
        if isinstance(val, (int, float)):
            return float(val)
    return None


def _iter_json_files(directory: Path) -> Iterable[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))


def query_cell_types(
    *,
    id: str | None = None,
    manufacturer: str | None = None,
    chemistry: str | None = None,
    format: str | None = None,
    model_name_contains: str | None = None,
    nominal_capacity_min: float | None = None,
    nominal_capacity_max: float | None = None,
    nominal_voltage_min: float | None = None,
    nominal_voltage_max: float | None = None,
    spec_filters: Mapping[str, tuple[float | None, float | None]] | None = None,
    include_cells_clean: bool = True,
    include_cell_types: bool = True,
    cells_clean_dir: PathLike = DEFAULT_CELLS_CLEAN_DIR,
    cell_types_dir: PathLike = DEFAULT_CELL_TYPES_DIR,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query cell types using practical metadata/property filters."""
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    if include_cells_clean:
        for path in _iter_json_files(_as_path(cells_clean_dir)):
            doc = _load_json(path)
            cell = doc.get("cell", {})
            specs = doc.get("specs", {})
            if not isinstance(cell, Mapping):
                continue
            cell_id = cell.get("id")
            if not isinstance(cell_id, str) or cell_id in seen_ids:
                continue
            seen_ids.add(cell_id)
            records.append(
                {
                    "id": cell_id,
                    "short_id": _short_id_from_iri(cell_id),
                    "model_name": cell.get("model_name"),
                    "manufacturer": cell.get("manufacturer"),
                    "chemistry": cell.get("chemistry"),
                    "format": cell.get("format"),
                    "size_code": cell.get("size_code"),
                    "nominal_capacity": _spec_numeric_value(specs, "nominal_capacity"),
                    "nominal_voltage": _spec_numeric_value(specs, "nominal_voltage"),
                    "specs": specs,
                    "source": "cells-clean",
                    "path": str(path),
                }
            )

    if include_cell_types:
        for path in _iter_json_files(_as_path(cell_types_dir)):
            doc = _load_json(path)
            cell_type = doc.get("cell_type", {})
            specs = doc.get("specs", {})
            if not isinstance(cell_type, Mapping):
                continue
            cell_id = cell_type.get("id")
            if not isinstance(cell_id, str) or cell_id in seen_ids:
                continue
            seen_ids.add(cell_id)
            records.append(
                {
                    "id": cell_id,
                    "short_id": cell_type.get("short_id") or _short_id_from_iri(cell_id),
                    "model_name": cell_type.get("model_name"),
                    "manufacturer": cell_type.get("manufacturer"),
                    "chemistry": cell_type.get("chemistry"),
                    "format": cell_type.get("format"),
                    "size_code": cell_type.get("size_code"),
                    "nominal_capacity": _spec_numeric_value(specs, "nominal_capacity"),
                    "nominal_voltage": _spec_numeric_value(specs, "nominal_voltage"),
                    "specs": specs,
                    "source": "cell-types",
                    "path": str(path),
                }
            )

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if not _str_eq(rec.get("manufacturer"), manufacturer):
            continue
        if not _str_eq(rec.get("chemistry"), chemistry):
            continue
        if not _str_eq(rec.get("format"), format):
            continue
        if not _str_contains(rec.get("model_name"), model_name_contains):
            continue
        if not _in_range(rec.get("nominal_capacity"), nominal_capacity_min, nominal_capacity_max):
            continue
        if not _in_range(rec.get("nominal_voltage"), nominal_voltage_min, nominal_voltage_max):
            continue

        if spec_filters:
            specs = rec.get("specs", {})
            if not isinstance(specs, Mapping):
                continue
            matches = True
            for key, bounds in spec_filters.items():
                minimum, maximum = bounds
                if not _in_range(_spec_numeric_value(specs, key), minimum, maximum):
                    matches = False
                    break
            if not matches:
                continue

        filtered.append(rec)

    return _paginate(filtered, limit=limit, offset=offset)


def query_cell_instances(
    *,
    id: str | None = None,
    type_id: str | None = None,
    short_id_prefix: str | None = None,
    serial_number: str | None = None,
    has_dataset: bool | None = None,
    dataset_id: str | None = None,
    source_type: str | None = None,
    directory: PathLike = DEFAULT_CELL_INSTANCES_DIR,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query physical cell instances."""
    records: list[dict[str, Any]] = []
    for path in _iter_json_files(_as_path(directory)):
        doc = _load_json(path)
        inst = doc.get("cell_instance", {})
        prov = doc.get("provenance", {})
        if not isinstance(inst, Mapping):
            continue
        rec = {
            "id": inst.get("id"),
            "type_id": inst.get("type_id"),
            "short_id": inst.get("short_id"),
            "serial_number": inst.get("serial_number"),
            "dataset_id": prov.get("dataset_id") if isinstance(prov, Mapping) else None,
            "source_type": prov.get("source_type") if isinstance(prov, Mapping) else None,
            "path": str(path),
            "record": doc,
        }
        records.append(rec)

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if type_id is not None and rec.get("type_id") != type_id:
            continue
        if short_id_prefix and not str(rec.get("short_id", "")).lower().startswith(short_id_prefix.lower()):
            continue
        if not _str_eq(rec.get("serial_number"), serial_number):
            continue
        if not _str_eq(rec.get("source_type"), source_type):
            continue
        if dataset_id is not None and rec.get("dataset_id") != dataset_id:
            continue
        if has_dataset is True and not rec.get("dataset_id"):
            continue
        if has_dataset is False and rec.get("dataset_id"):
            continue
        filtered.append(rec)

    return _paginate(filtered, limit=limit, offset=offset)


def query_datasets(
    *,
    id: str | None = None,
    title_contains: str | None = None,
    related_cell_id: str | None = None,
    source_type: str | None = None,
    format: str | None = None,
    license: str | None = None,
    directory: PathLike = DEFAULT_DATASETS_DIR,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query dataset metadata records."""
    records: list[dict[str, Any]] = []
    for path in _iter_json_files(_as_path(directory)):
        doc = _load_json(path)
        dataset = doc.get("dataset", {})
        prov = doc.get("provenance", {})
        if not isinstance(dataset, Mapping):
            continue
        related_entities = dataset.get("related_entities")
        related_cells = []
        if isinstance(related_entities, Mapping):
            related = related_entities.get("cell_ids")
            if isinstance(related, list):
                related_cells = [item for item in related if isinstance(item, str)]

        rec = {
            "id": dataset.get("id"),
            "short_id": dataset.get("short_id"),
            "title": dataset.get("title"),
            "format": dataset.get("format"),
            "license": dataset.get("license"),
            "access_url": dataset.get("access_url"),
            "related_cell_ids": related_cells,
            "source_type": prov.get("source_type") if isinstance(prov, Mapping) else None,
            "path": str(path),
            "record": doc,
        }
        records.append(rec)

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if not _str_contains(rec.get("title"), title_contains):
            continue
        if related_cell_id is not None and related_cell_id not in rec.get("related_cell_ids", []):
            continue
        if not _str_eq(rec.get("source_type"), source_type):
            continue
        if not _str_eq(rec.get("format"), format):
            continue
        if not _str_eq(rec.get("license"), license):
            continue
        filtered.append(rec)

    return _paginate(filtered, limit=limit, offset=offset)


def resolve_cell_type_id(
    *,
    type_id: str | None = None,
    model_name: str | None = None,
    manufacturer: str | None = None,
    chemistry: str | None = None,
    format: str | None = None,
    exact_model: bool = True,
    limit: int = 50,
) -> str:
    """Resolve a unique `cell-type` IRI from metadata filters."""
    if type_id is not None:
        if not CELL_TYPE_IRI_RE.fullmatch(type_id):
            raise ValueError("type_id must match https://w3id.org/battinfo/cell-type/{uid}.")
        return type_id

    matches = query_cell_types(
        manufacturer=manufacturer,
        chemistry=chemistry,
        format=format,
        model_name_contains=model_name,
        limit=limit,
        offset=0,
    )
    if model_name and exact_model:
        matches = [m for m in matches if _str_eq(m.get("model_name"), model_name)]

    if not matches:
        raise ValueError("No cell-type match found. Refine metadata filters or pass type_id explicitly.")

    if len(matches) > 1:
        ids = [str(m.get("id")) for m in matches[:5]]
        raise ValueError(
            "Multiple cell-type matches found. Add more filters or pass type_id. "
            f"Examples: {ids}"
        )
    only = matches[0].get("id")
    if not isinstance(only, str):
        raise ValueError("Resolved match does not contain a valid id.")
    return only


@lru_cache(maxsize=1)
def _schema_registry() -> Registry:
    resources_by_id: list[tuple[str, Resource]] = []
    for schema_path in SCHEMAS_ROOT.rglob("*.json"):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema_id = schema.get("$id")
        if isinstance(schema_id, str) and schema_id:
            resources_by_id.append((schema_id, Resource.from_contents(schema)))
    return Registry().with_resources(resources_by_id)


@lru_cache(maxsize=1)
def _allowed_spec_keys() -> set[str]:
    schema = json.loads((SCHEMAS_ROOT / "cell-canonical.schema.json").read_text(encoding="utf-8"))
    spec_props = schema.get("$defs", {}).get("SpecSet", {}).get("properties", {})
    return {key for key in spec_props if isinstance(key, str)}


def _sanitize_raw(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    out: dict[str, Any] = {}
    for key in ("text", "page", "confidence"):
        if key in raw:
            out[key] = raw[key]
    return out or None


def _sanitize_spec_item(item: object) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None

    candidate: object = item
    if isinstance(item.get("spec"), Mapping):
        candidate = item["spec"]
    elif isinstance(item.get("cycles"), Mapping):
        candidate = item["cycles"]

    if not isinstance(candidate, Mapping):
        return None

    out: dict[str, Any] = {}
    for key in ("value", "value_min", "value_max", "value_typical", "value_text", "unit"):
        if key in candidate:
            out[key] = candidate[key]
    raw = _sanitize_raw(candidate.get("raw"))
    if raw is not None:
        out["raw"] = raw

    has_value = any(key in out for key in ("value", "value_min", "value_max", "value_typical", "value_text"))
    if "unit" not in out or not has_value:
        return None
    return out


def _sanitize_range_spec(item: object) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None
    out: dict[str, Any] = {}
    min_item = _sanitize_spec_item(item.get("min"))
    max_item = _sanitize_spec_item(item.get("max"))
    raw = _sanitize_raw(item.get("raw"))
    if min_item is not None:
        out["min"] = min_item
    if max_item is not None:
        out["max"] = max_item
    if raw is not None:
        out["raw"] = raw
    return out or None


def _sanitize_specset(specs: object) -> dict[str, Any]:
    if not isinstance(specs, Mapping):
        return {}
    allowed = _allowed_spec_keys()
    out: dict[str, Any] = {}
    for key, value in specs.items():
        if key in allowed:
            if key.endswith("_temperature_range"):
                cleaned_range = _sanitize_range_spec(value)
                if cleaned_range is not None:
                    out[key] = cleaned_range
                continue
            cleaned_item = _sanitize_spec_item(value)
            if cleaned_item is not None:
                out[key] = cleaned_item
    return out


def _validate_schema(doc: dict[str, Any], schema_rel_path: str) -> None:
    schema = json.loads((SCHEMAS_ROOT / schema_rel_path).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=_schema_registry())
    errors = sorted(validator.iter_errors(doc), key=lambda err: list(err.path))
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(p) for p in first.path)
    if location:
        raise ValueError(f"Schema validation failed at '{location}': {first.message}")
    raise ValueError(f"Schema validation failed: {first.message}")


def create_cell_type_from_datasheet(
    datasheet: dict[str, Any] | PathLike,
    *,
    uid: str | None = None,
    out_path: PathLike | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    """Create a canonical cell-type document from a datasheet extraction."""
    source_doc: dict[str, Any]
    source_filename: str | None = None
    if isinstance(datasheet, (str, Path)):
        data_path = _as_path(datasheet)
        source_doc = _load_json(data_path)
        source_filename = data_path.name
    else:
        source_doc = datasheet

    cell = source_doc.get("cell", {})
    specs = source_doc.get("specs", {})
    source = source_doc.get("source", {})

    manufacturer = (
        cell.get("manufacturer") if isinstance(cell, Mapping) else None
    ) or (source.get("manufacturer") if isinstance(source, Mapping) else None) or "Unknown"
    model_name = (
        cell.get("model_name") if isinstance(cell, Mapping) else None
    ) or (source.get("model_name") if isinstance(source, Mapping) else None) or "unknown"

    dashed_uid = _normalized_dashed_uid(uid)
    entity_id = f"https://w3id.org/battinfo/cell-type/{dashed_uid}"

    out: dict[str, Any] = {
        "schema_version": "0.1.0",
        "cell_type": {
            "id": entity_id,
            "short_id": dashed_uid.replace("-", "")[:6],
            "model_name": model_name,
            "manufacturer": manufacturer,
            "format": (cell.get("format") if isinstance(cell, Mapping) else None) or "unknown",
            "chemistry": (cell.get("chemistry") if isinstance(cell, Mapping) else None) or "unknown",
        },
        "specs": _sanitize_specset(specs),
        "provenance": {
            "source_type": "datasheet",
            "source_file": (
                source.get("filename") if isinstance(source, Mapping) else None
            )
            or source_filename
            or "unknown.json",
            "source_url": source.get("source_url") if isinstance(source, Mapping) else None,
            "file_hash": source.get("file_hash") if isinstance(source, Mapping) else None,
            "retrieved_at": (
                source.get("extracted_at") if isinstance(source, Mapping) else None
            )
            or _now_iso(),
        },
    }

    if isinstance(cell, Mapping):
        if isinstance(cell.get("size_code"), str):
            out["cell_type"]["size_code"] = cell["size_code"]
        if isinstance(cell.get("datasheet_revision"), str):
            out["cell_type"]["datasheet_revision"] = cell["datasheet_revision"]

    if validate:
        _validate_schema(out, "cell-type.schema.json")

    if out_path is not None:
        _write_json(_as_path(out_path), out)
    return out


def create_cell_instance(
    *,
    type_id: str | None = None,
    cell_type: dict[str, Any] | PathLike | None = None,
    model_name: str | None = None,
    manufacturer: str | None = None,
    chemistry: str | None = None,
    format: str | None = None,
    serial_number: str | None = None,
    dataset_id: str | None = None,
    source_type: str = "measurement",
    uid: str | None = None,
    out_path: PathLike | None = None,
    validate: bool = True,
) -> dict[str, Any]:
    """Create a physical cell-instance document.

    You can pass a canonical `type_id`, a `cell_type` document/path, or metadata filters
    (`model_name`, `manufacturer`, ...) to resolve the type.
    """
    resolved_type_id = type_id

    if cell_type is not None:
        cell_type_doc: dict[str, Any]
        if isinstance(cell_type, (str, Path)):
            cell_type_doc = _load_json(_as_path(cell_type))
        else:
            cell_type_doc = cell_type
        cell_type_obj = cell_type_doc.get("cell_type", {})
        if not isinstance(cell_type_obj, Mapping):
            raise ValueError("cell_type document must contain a 'cell_type' object.")
        embedded_id = cell_type_obj.get("id")
        if not isinstance(embedded_id, str):
            raise ValueError("cell_type.id missing in provided cell_type document.")
        if resolved_type_id is not None and embedded_id != resolved_type_id:
            raise ValueError("Provided type_id does not match cell_type.id.")
        resolved_type_id = embedded_id

    resolved_type_id = resolve_cell_type_id(
        type_id=resolved_type_id,
        model_name=model_name,
        manufacturer=manufacturer,
        chemistry=chemistry,
        format=format,
    )

    if source_type not in {"measurement", "lab", "bms", "other"}:
        raise ValueError("source_type must be one of: measurement, lab, bms, other.")

    if dataset_id is not None and not DATASET_IRI_RE.fullmatch(dataset_id):
        raise ValueError("dataset_id must match https://w3id.org/battinfo/dataset/{uid}.")

    dashed_uid = _normalized_dashed_uid(uid)
    instance_id = f"https://w3id.org/battinfo/cell/{dashed_uid}"

    out: dict[str, Any] = {
        "schema_version": "0.1.0",
        "cell_instance": {
            "id": instance_id,
            "type_id": resolved_type_id,
            "short_id": dashed_uid.replace("-", "")[:6],
        },
        "provenance": {
            "source_type": source_type,
            "retrieved_at": _now_iso(),
        },
    }
    if serial_number:
        out["cell_instance"]["serial_number"] = serial_number
    if dataset_id:
        out["provenance"]["dataset_id"] = dataset_id
        out["provenance"]["dataset_ids"] = [dataset_id]
        out["datasets"] = [{"id": dataset_id, "role": "raw"}]

    if validate:
        _validate_schema(out, "cell-instance.schema.json")

    if out_path is not None:
        _write_json(_as_path(out_path), out)
    return out


def _entity_id(doc: dict[str, Any]) -> str:
    if isinstance(doc.get("cell_type"), Mapping) and isinstance(doc["cell_type"].get("id"), str):
        return doc["cell_type"]["id"]
    if isinstance(doc.get("cell_instance"), Mapping) and isinstance(doc["cell_instance"].get("id"), str):
        return doc["cell_instance"]["id"]
    if isinstance(doc.get("dataset"), Mapping) and isinstance(doc["dataset"].get("id"), str):
        return doc["dataset"]["id"]
    raise ValueError("Could not locate canonical entity id in document.")


def _entity_schema_rel_path(doc: dict[str, Any]) -> str:
    if isinstance(doc.get("cell_type"), Mapping):
        return "cell-type.schema.json"
    if isinstance(doc.get("cell_instance"), Mapping):
        return "cell-instance.schema.json"
    if isinstance(doc.get("dataset"), Mapping):
        return "dataset.schema.json"
    raise ValueError("Unsupported record type: expected cell_type, cell_instance, or dataset.")


def _iri_tail(iri: str) -> tuple[str, str]:
    parts = iri.rstrip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"Invalid IRI: {iri}")
    return parts[-2], parts[-1]


def _resolver_jsonld(doc: dict[str, Any]) -> dict[str, Any]:
    entity_iri = _entity_id(doc)
    entity_type, uid = _iri_tail(entity_iri)
    context = [
        "https://w3id.org/emmo/domain/battery/context",
        {
            "schema": "https://schema.org/",
            "battinfo": "https://w3id.org/battinfo#",
        },
    ]

    if entity_type == "cell-type":
        cell = doc["cell_type"]
        out: dict[str, Any] = {
            "@context": context,
            "@id": entity_iri,
            "@type": "battinfo:BatteryCellType",
            "schema:identifier": uid,
            "schema:name": cell.get("model_name"),
            "schema:manufacturer": {"@type": "schema:Organization", "schema:name": cell.get("manufacturer")},
            "battinfo:chemistry": cell.get("chemistry"),
            "battinfo:format": cell.get("format"),
        }
        if cell.get("size_code"):
            out["battinfo:sizeCode"] = cell.get("size_code")
        return out

    if entity_type == "cell":
        inst = doc["cell_instance"]
        out = {
            "@context": context,
            "@id": entity_iri,
            "@type": "battinfo:BatteryCellInstance",
            "schema:identifier": uid,
            "battinfo:typeId": {"@id": inst.get("type_id")},
        }
        if inst.get("serial_number"):
            out["battinfo:serialNumber"] = inst.get("serial_number")
        datasets: list[dict[str, str]] = []
        for dataset in doc.get("datasets", []):
            if isinstance(dataset, Mapping) and isinstance(dataset.get("id"), str):
                datasets.append({"@id": dataset["id"]})
        if datasets:
            out["battinfo:hasDataset"] = datasets
        return out

    if entity_type == "dataset":
        dataset = doc["dataset"]
        out = {
            "@context": context,
            "@id": entity_iri,
            "@type": "schema:Dataset",
            "schema:identifier": uid,
            "schema:name": dataset.get("title"),
            "schema:description": dataset.get("description"),
            "schema:license": dataset.get("license"),
            "schema:encodingFormat": dataset.get("format"),
        }
        if dataset.get("access_url"):
            out["schema:url"] = dataset.get("access_url")
        related = dataset.get("related_entities", {})
        if isinstance(related, Mapping):
            cells = related.get("cell_ids")
            if isinstance(cells, list):
                out["battinfo:aboutCell"] = [{"@id": cell_id} for cell_id in cells if isinstance(cell_id, str)]
        return out

    raise ValueError(f"Unsupported entity type '{entity_type}' for {entity_iri}.")


def _resolver_html(doc: dict[str, Any]) -> str:
    entity_iri = _entity_id(doc)
    entity_type, uid = _iri_tail(entity_iri)
    pretty = html.escape(json.dumps(doc, indent=2, ensure_ascii=False))
    title = html.escape(f"BattINFO {entity_type} {uid}")
    iri_escaped = html.escape(entity_iri)
    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\" />\n"
        f"  <title>{title}</title>\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
        "  <style>body{font-family:Arial,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;line-height:1.5}"
        "code,pre{background:#f6f8fa;border-radius:4px}pre{padding:1rem;overflow:auto}"
        "a{color:#0b5fff;text-decoration:none}a:hover{text-decoration:underline}</style>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{title}</h1>\n"
        f"  <p><strong>Canonical IRI:</strong> <code>{iri_escaped}</code></p>\n"
        "  <p>\n"
        "    <a href=\"index.json\">JSON</a> |\n"
        "    <a href=\"index.jsonld\">JSON-LD</a>\n"
        "  </p>\n"
        "  <h2>Metadata</h2>\n"
        f"  <pre>{pretty}</pre>\n"
        "</body>\n"
        "</html>\n"
    )


def publish_record(
    record: dict[str, Any] | PathLike,
    *,
    target_root: PathLike = "registry/site",
    build_jsonld: bool = True,
    build_html: bool = True,
    validate: bool = True,
) -> dict[str, Any]:
    """Publish one canonical resource into resolver-ready static artifacts."""
    doc = _load_json(_as_path(record)) if isinstance(record, (str, Path)) else record
    if validate:
        _validate_schema(doc, _entity_schema_rel_path(doc))

    iri = _entity_id(doc)
    entity_type, uid = _iri_tail(iri)
    out_dir = _as_path(target_root) / entity_type / uid
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    _write_json(out_dir / "index.json", doc)
    written.append(str(out_dir / "index.json"))
    if build_jsonld:
        _write_json(out_dir / "index.jsonld", _resolver_jsonld(doc))
        written.append(str(out_dir / "index.jsonld"))
    if build_html:
        (out_dir / "index.html").write_text(_resolver_html(doc), encoding="utf-8")
        written.append(str(out_dir / "index.html"))

    return {
        "status": "published",
        "id": iri,
        "entity_type": entity_type,
        "uid": uid,
        "output_dir": str(out_dir),
        "files": written,
    }


def publish_batch(
    *,
    source_dirs: Sequence[PathLike] = DEFAULT_PUBLISH_SOURCES,
    target_root: PathLike = "registry/site",
    glob: str = "*.json",
    build_jsonld: bool = True,
    build_html: bool = True,
    validate: bool = True,
) -> dict[str, Any]:
    """Publish a deterministic batch of canonical resources."""
    failures: list[dict[str, str]] = []
    published = 0
    processed = 0

    for src_dir in source_dirs:
        src_path = _as_path(src_dir)
        if not src_path.exists():
            continue
        for path in sorted(src_path.glob(glob)):
            processed += 1
            try:
                publish_record(
                    path,
                    target_root=target_root,
                    build_jsonld=build_jsonld,
                    build_html=build_html,
                    validate=validate,
                )
                published += 1
            except Exception as exc:  # noqa: BLE001
                failures.append({"file": str(path), "error": str(exc)})

    return {
        "status": "ok" if not failures else "partial",
        "processed": processed,
        "published": published,
        "failed": len(failures),
        "failures": failures,
    }


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def build_index(
    *,
    source_root: PathLike = DEFAULT_INDEX_SOURCE_ROOT,
    out_path: PathLike | None = None,
    glob: str = "*.json",
    validate: bool = False,
) -> dict[str, Any]:
    """Build a lightweight searchable index from canonical BattINFO resources."""
    src_root = _as_path(source_root)
    if not src_root.exists():
        raise ValueError(f"source_root does not exist: {src_root}")

    cell_types: list[dict[str, Any]] = []
    cell_instances: list[dict[str, Any]] = []
    datasets: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    cell_types_dir = src_root / "cell-types"
    cell_instances_dir = src_root / "cell-instances"
    datasets_dir = src_root / "datasets"

    for path in sorted(cell_types_dir.glob(glob)) if cell_types_dir.exists() else []:
        try:
            doc = _load_json(path)
            if validate:
                _validate_schema(doc, "cell-type.schema.json")
            cell_type = doc.get("cell_type", {})
            if not isinstance(cell_type, Mapping) or not isinstance(cell_type.get("id"), str):
                raise ValueError("missing cell_type.id")
            cell_types.append(
                {
                    "id": cell_type["id"],
                    "short_id": cell_type.get("short_id") or _short_id_from_iri(cell_type["id"]),
                    "manufacturer": cell_type.get("manufacturer"),
                    "model_name": cell_type.get("model_name"),
                    "chemistry": cell_type.get("chemistry"),
                    "format": cell_type.get("format"),
                    "path": _relative_or_absolute(path, src_root),
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({"file": _relative_or_absolute(path, src_root), "error": str(exc)})

    for path in sorted(cell_instances_dir.glob(glob)) if cell_instances_dir.exists() else []:
        try:
            doc = _load_json(path)
            if validate:
                _validate_schema(doc, "cell-instance.schema.json")
            inst = doc.get("cell_instance", {})
            prov = doc.get("provenance", {})
            if not isinstance(inst, Mapping) or not isinstance(inst.get("id"), str):
                raise ValueError("missing cell_instance.id")
            cell_instances.append(
                {
                    "id": inst["id"],
                    "type_id": inst.get("type_id"),
                    "short_id": inst.get("short_id") or _short_id_from_iri(inst["id"]),
                    "dataset_id": prov.get("dataset_id") if isinstance(prov, Mapping) else None,
                    "source_type": prov.get("source_type") if isinstance(prov, Mapping) else None,
                    "path": _relative_or_absolute(path, src_root),
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({"file": _relative_or_absolute(path, src_root), "error": str(exc)})

    for path in sorted(datasets_dir.glob(glob)) if datasets_dir.exists() else []:
        try:
            doc = _load_json(path)
            if validate:
                _validate_schema(doc, "dataset.schema.json")
            dataset = doc.get("dataset", {})
            prov = doc.get("provenance", {})
            if not isinstance(dataset, Mapping) or not isinstance(dataset.get("id"), str):
                raise ValueError("missing dataset.id")
            related_entities = dataset.get("related_entities")
            related_cell_ids: list[str] = []
            if isinstance(related_entities, Mapping):
                related = related_entities.get("cell_ids")
                if isinstance(related, list):
                    related_cell_ids = [item for item in related if isinstance(item, str)]
            datasets.append(
                {
                    "id": dataset["id"],
                    "short_id": dataset.get("short_id") or _short_id_from_iri(dataset["id"]),
                    "title": dataset.get("title"),
                    "format": dataset.get("format"),
                    "license": dataset.get("license"),
                    "source_type": prov.get("source_type") if isinstance(prov, Mapping) else None,
                    "related_cell_ids": related_cell_ids,
                    "path": _relative_or_absolute(path, src_root),
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({"file": _relative_or_absolute(path, src_root), "error": str(exc)})

    out: dict[str, Any] = {
        "build_timestamp": _now_iso(),
        "source_root": str(src_root),
        "cell_type_count": len(cell_types),
        "cell_instance_count": len(cell_instances),
        "dataset_count": len(datasets),
        "total_count": len(cell_types) + len(cell_instances) + len(datasets),
        "failed": len(failures),
        "failures": failures,
        "cell_types": cell_types,
        "cell_instances": cell_instances,
        "datasets": datasets,
    }

    if out_path is not None:
        _write_json(_as_path(out_path), out)

    return out


def index_stats(index: dict[str, Any] | PathLike) -> dict[str, Any]:
    """Return normalized index statistics from an index object or file path."""
    doc: dict[str, Any]
    index_path: str | None = None
    if isinstance(index, (str, Path)):
        index_path = str(_as_path(index))
        doc = _load_json(_as_path(index))
    else:
        doc = index

    cell_type_count = (
        int(doc["cell_type_count"])
        if isinstance(doc.get("cell_type_count"), int)
        else len(doc.get("cell_types", [])) if isinstance(doc.get("cell_types"), list) else 0
    )
    cell_instance_count = (
        int(doc["cell_instance_count"])
        if isinstance(doc.get("cell_instance_count"), int)
        else len(doc.get("cell_instances", [])) if isinstance(doc.get("cell_instances"), list) else 0
    )
    dataset_count = (
        int(doc["dataset_count"])
        if isinstance(doc.get("dataset_count"), int)
        else len(doc.get("datasets", [])) if isinstance(doc.get("datasets"), list) else 0
    )
    total_count = (
        int(doc["total_count"])
        if isinstance(doc.get("total_count"), int)
        else cell_type_count + cell_instance_count + dataset_count
    )
    failed = int(doc["failed"]) if isinstance(doc.get("failed"), int) else 0

    out = {
        "build_timestamp": doc.get("build_timestamp"),
        "cell_type_count": cell_type_count,
        "cell_instance_count": cell_instance_count,
        "dataset_count": dataset_count,
        "total_count": total_count,
        "failed": failed,
    }
    if index_path is not None:
        out["index_path"] = index_path
    return out


__all__ = [
    "build_index",
    "create_cell_instance",
    "create_cell_type_from_datasheet",
    "index_stats",
    "publish_batch",
    "publish_record",
    "query_cell_instances",
    "query_cell_types",
    "query_datasets",
    "resolve_cell_type_id",
]
