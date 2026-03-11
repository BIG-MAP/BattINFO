from __future__ import annotations

import html
import json
import re
import secrets
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field
from battinfo.validate.core import DEFAULT_POLICY, ValidationPolicy
from battinfo.validate.pydantic import validate_json
from battinfo.validate.publication import validate_publication_report
from battinfo.validate.record import validate_record_report
from battinfo.validate.references import validate_references_report
from battinfo.validate.schema import validate_schema_data
from battinfo.workflows.map import run_mapping

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
TEST_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/test/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)

PACKAGE_ROOT = Path(__file__).resolve().parent
EXAMPLES_ROOT = PACKAGE_ROOT / "data" / "examples"
SCHEMAS_ROOT = PACKAGE_ROOT / "data" / "schemas"

DEFAULT_CELLS_CLEAN_DIR = EXAMPLES_ROOT / "cells-clean"
DEFAULT_CELL_TYPES_DIR = EXAMPLES_ROOT / "cell-types"
DEFAULT_CELL_INSTANCES_DIR = EXAMPLES_ROOT / "cell-instances"
DEFAULT_TESTS_DIR = EXAMPLES_ROOT / "tests"
DEFAULT_DATASETS_DIR = EXAMPLES_ROOT / "datasets"
DEFAULT_LIBRARY_CELL_TYPES_DIR = Path("assets") / "library" / "cell-types"
DEFAULT_LIBRARY_RDF_CELL_TYPES_DIR = Path("assets") / "library-rdf" / "cell-types"
DEFAULT_LIBRARY_AGGREGATE_JSONLD = Path("ontology") / "library" / "cell-types.jsonld"
DEFAULT_LIBRARY_MANIFEST_JSON = Path("assets") / "library-rdf" / "cell-types.index.json"
DEFAULT_PACKAGED_LIBRARY_CELL_TYPES_DIR = Path("src") / "battinfo" / "data" / "library" / "cell-types"
DEFAULT_PUBLISH_SOURCES = (
    DEFAULT_CELL_TYPES_DIR,
    DEFAULT_CELL_INSTANCES_DIR,
    DEFAULT_TESTS_DIR,
    DEFAULT_DATASETS_DIR,
)
DEFAULT_INDEX_SOURCE_ROOT = EXAMPLES_ROOT
DEFAULT_REGISTRATION_SOURCE_ROOT = Path("assets") / "examples"
TEMPLATE_UID = "0000000000000000"
TEMPLATE_CELL_TYPE_ID = "https://w3id.org/battinfo/cell-type/0000-0000-0000-0000"
TEMPLATE_CELL_ID = "https://w3id.org/battinfo/cell/0000-0000-0000-0000"

REGISTER_MODE_CREATE_ONLY = "create_only"
REGISTER_MODE_UPSERT = "upsert"
REGISTER_MODES = {REGISTER_MODE_CREATE_ONLY, REGISTER_MODE_UPSERT}

DUPLICATE_POLICY_ERROR = "error"
DUPLICATE_POLICY_RETURN_EXISTING = "return_existing"
DUPLICATE_POLICIES = {DUPLICATE_POLICY_ERROR, DUPLICATE_POLICY_RETURN_EXISTING}


class CellTypeInput(BaseModel):
    """Typed input for registering a new canonical cell-type resource."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1.0"
    id: str | None = None
    uid: str | None = None
    model_name: str
    manufacturer: str
    format: Literal["cylindrical", "prismatic", "pouch", "coin", "other", "unknown"] = "unknown"
    chemistry: str = "unknown"
    positive_electrode_basis: str | None = None
    negative_electrode_basis: str | None = None
    size_code: str | None = None
    datasheet_revision: str | None = None
    specs: dict[str, Any] = Field(default_factory=dict)
    source_type: Literal["datasheet"] = "datasheet"
    source_file: str = "manual.json"
    source_url: str | None = None
    file_hash: str | None = None
    retrieved_at: int | None = None
    notes: list[str] = Field(default_factory=list)


class CellSpecificationInput(BaseModel):
    """Typed input for registering a reusable cell specification for a cell type."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    id: str | None = None
    uid: str | None = None
    manufacturer: str
    model: str
    format: Literal["cylindrical", "prismatic", "pouch", "coin", "other", "unknown"]
    chemistry: str
    positive_electrode_basis: str
    negative_electrode_basis: str
    size_code: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    specification_comment: list[str] = Field(default_factory=list)
    source_type: str = "datasheet"
    source_name: str | None = None
    source_file: str = "manual.json"
    source_url: str | None = None
    retrieved_at: int | str | None = None
    workflow_version: str | None = None
    provenance_comment: str | None = None
    comment: list[str] = Field(default_factory=list)


class CellInstanceInput(BaseModel):
    """Typed input for registering a new canonical cell-instance resource."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1.0"
    id: str | None = None
    uid: str | None = None
    type_id: str
    serial_number: str | None = None
    batch_id: str | None = None
    manufactured_at: int | str | None = None
    measured: dict[str, Any] | None = None
    source_type: Literal["measurement", "lab", "bms", "other"] = "measurement"
    dataset_id: str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    source_url: str | None = None
    retrieved_at: int | str | None = None
    notes: list[str] = Field(default_factory=list)


class DatasetInput(BaseModel):
    """Typed input for registering a new canonical dataset resource."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1.0"
    id: str | None = None
    uid: str | None = None
    title: str
    description: str | None = None
    license: str | None = None
    format: str | None = None
    access_url: str | None = None
    download_url: str | None = None
    created_at: str | None = None
    checksum_algorithm: Literal["sha256", "sha512", "md5", "other"] | None = None
    checksum_value: str | None = None
    related_cell_ids: list[str] = Field(default_factory=list)
    related_test_ids: list[str] = Field(default_factory=list)
    source_type: Literal["catalog", "measurement", "lab", "simulation", "external", "manual", "other"] = "other"
    source_url: str | None = None
    retrieved_at: int | None = None
    curated_by: str | None = None
    notes: list[str] = Field(default_factory=list)


class TestInput(BaseModel):
    """Typed input for registering a new canonical test resource."""

    model_config = ConfigDict(extra="forbid")
    __test__ = False

    schema_version: str = "0.1.0"
    id: str | None = None
    uid: str | None = None
    cell_id: str
    name: str
    kind: Literal["cycle_life", "capacity_check", "rate_capability", "impedance", "calendar_ageing", "formation", "other"]
    description: str | None = None
    status: Literal["planned", "running", "completed", "aborted", "other"] | None = None
    protocol_name: str | None = None
    protocol_url: str | None = None
    instrument_name: str | None = None
    started_at: int | str | None = None
    ended_at: int | str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    source_type: Literal["measurement", "lab", "simulation", "manual", "other"] = "measurement"
    source_url: str | None = None
    source_file: str | None = None
    retrieved_at: int | str | None = None
    workflow_version: str | None = None
    notes: list[str] = Field(default_factory=list)


def template_cell_type(
    *,
    manufacturer: str = "ExampleManufacturer",
    model_name: str = "MODEL-001",
    chemistry: str = "unknown",
    format: Literal["cylindrical", "prismatic", "pouch", "coin", "other", "unknown"] = "unknown",
    uid: str | None = TEMPLATE_UID,
    source_file: str = "template-cell-type.json",
) -> dict[str, Any]:
    """Build a starter canonical cell-type document for registration workflows."""
    draft = CellTypeInput(
        uid=uid,
        model_name=model_name,
        manufacturer=manufacturer,
        chemistry=chemistry,
        format=format,
        source_file=source_file,
        specs={},
        notes=["Template-generated record. Fill in specs/provenance before registration."],
    )
    return _record_from_cell_type(draft)


def template_cell_instance(
    *,
    type_id: str = TEMPLATE_CELL_TYPE_ID,
    source_type: Literal["measurement", "lab", "bms", "other"] = "measurement",
    uid: str | None = TEMPLATE_UID,
) -> dict[str, Any]:
    """Build a starter canonical cell-instance document for registration workflows."""
    draft = CellInstanceInput(
        uid=uid,
        type_id=type_id,
        source_type=source_type,
        notes=["Template-generated record. Set type_id/serial_number/datasets before registration."],
    )
    return _record_from_cell_instance(draft)


def template_dataset(
    *,
    title: str = "Example Dataset",
    source_type: Literal["catalog", "measurement", "lab", "simulation", "external", "manual", "other"] = "other",
    uid: str | None = TEMPLATE_UID,
    related_cell_ids: list[str] | None = None,
    related_test_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a starter canonical dataset document for registration workflows."""
    draft = DatasetInput(
        uid=uid,
        title=title,
        source_type=source_type,
        related_cell_ids=related_cell_ids or [TEMPLATE_CELL_ID],
        related_test_ids=related_test_ids or [],
        notes=["Template-generated record. Fill in URL/license/distribution details before registration."],
    )
    return _record_from_dataset(draft)


def template_test(
    *,
    cell_id: str = TEMPLATE_CELL_ID,
    name: str = "Example Test",
    kind: Literal["cycle_life", "capacity_check", "rate_capability", "impedance", "calendar_ageing", "formation", "other"] = "other",
    source_type: Literal["measurement", "lab", "simulation", "manual", "other"] = "measurement",
    uid: str | None = TEMPLATE_UID,
    dataset_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a starter canonical test document for registration workflows."""
    draft = TestInput(
        uid=uid,
        cell_id=cell_id,
        name=name,
        kind=kind,
        source_type=source_type,
        dataset_ids=dataset_ids or [],
        notes=["Template-generated record. Set the concrete cell, protocol, and datasets before registration."],
    )
    return _record_from_test(draft)


def template_cell_specification(
    *,
    manufacturer: str = "ExampleManufacturer",
    model: str = "MODEL-001",
    chemistry: str = "unknown",
    format: Literal["cylindrical", "prismatic", "pouch", "coin", "other", "unknown"] = "unknown",
    positive_electrode_basis: str = "unknown",
    negative_electrode_basis: str = "unknown",
    uid: str | None = TEMPLATE_UID,
    source_file: str = "template-cell-specification.json",
    source_type: str = "datasheet",
) -> dict[str, Any]:
    """Build a starter reusable cell specification for the cell-type library."""
    draft = CellSpecificationInput(
        uid=uid,
        manufacturer=manufacturer,
        model=model,
        chemistry=chemistry,
        format=format,
        positive_electrode_basis=positive_electrode_basis,
        negative_electrode_basis=negative_electrode_basis,
        source_file=source_file,
        source_type=source_type,
        specification_comment=["Template-generated specification. Fill in trusted specification values."],
        comment=["Template-generated reusable library cell type."],
    )
    return _record_from_cell_specification(draft)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _to_unix_time(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return None
        if txt.isdigit():
            return int(txt)
        try:
            return int(datetime.fromisoformat(txt.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


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


def _quantity_numeric_value(specs: Mapping[str, Any], key: str) -> float | None:
    item = specs.get(key)
    if not isinstance(item, Mapping):
        return None
    for candidate in ("value", "typical_value", "max_value", "min_value"):
        val = item.get(candidate)
        if isinstance(val, (int, float)):
            return float(val)
    return None


def _iter_json_files(directory: Path) -> Iterable[Path]:
    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))


def _find_library_descriptor_path_by_id(entity_id: str, library_root: Path) -> Path | None:
    for path in _iter_json_files(library_root):
        try:
            doc = _load_json(path)
        except Exception:  # noqa: BLE001
            continue
        specification = doc.get("specification")
        if isinstance(specification, Mapping) and specification.get("id") == entity_id:
            return path
    return None


def _validate_cell_specification(doc: dict[str, Any]) -> None:
    result = validate_json(doc, profile="battery-descriptor")
    if result.ok:
        return
    raise ValueError(f"cell-specification validation failed: {'; '.join(result.errors)}")


def _sync_library_packaged_copy(source_path: Path, package_root: Path) -> Path:
    package_root.mkdir(parents=True, exist_ok=True)
    target_path = package_root / source_path.name
    target_path.write_text(source_path.read_text(encoding='utf-8'), encoding='utf-8')
    return target_path


def _library_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9-]+", "_", value.strip())
    token = re.sub(r"_+", "_", token).strip("_-")
    return token or "UNKNOWN"


def _library_cell_type_filename(manufacturer: str, model: str) -> str:
    return f"{_library_token(manufacturer)}__{_library_token(model)}.json"


def _record_from_cell_specification(draft: CellSpecificationInput) -> dict[str, Any]:
    if draft.id is not None:
        if not CELL_TYPE_IRI_RE.fullmatch(draft.id):
            raise ValueError("cell specification id must match https://w3id.org/battinfo/cell-type/{uid}.")
        if draft.uid is not None:
            dashed = _normalized_dashed_uid(draft.uid)
            _assert_id_matches_uid(draft.id, dashed)
        entity_id = draft.id
    else:
        dashed_uid = _normalized_dashed_uid(draft.uid)
        entity_id = f"https://w3id.org/battinfo/cell-type/{dashed_uid}"

    specification: dict[str, Any] = {
        "id": entity_id,
        "manufacturer": draft.manufacturer,
        "model": draft.model,
        "format": draft.format,
        "chemistry": draft.chemistry,
        "positive_electrode_basis": draft.positive_electrode_basis,
        "negative_electrode_basis": draft.negative_electrode_basis,
    }
    if draft.size_code is not None:
        specification["size_code"] = draft.size_code
    if draft.property:
        specification["property"] = draft.property
    if draft.specification_comment:
        specification["comment"] = list(draft.specification_comment)

    provenance: dict[str, Any] = {
        "source_file": draft.source_file,
        "retrieved_at": _to_unix_time(draft.retrieved_at) or _now_unix(),
    }
    if draft.source_type:
        provenance["source_type"] = draft.source_type
    if draft.source_name is not None:
        provenance["source_name"] = draft.source_name
    if draft.source_url is not None:
        provenance["source_url"] = draft.source_url
    if draft.workflow_version is not None:
        provenance["workflow_version"] = draft.workflow_version
    if draft.provenance_comment is not None:
        provenance["comment"] = draft.provenance_comment

    record: dict[str, Any] = {
        "schema_version": draft.schema_version,
        "specification": specification,
        "provenance": provenance,
    }
    if draft.comment:
        record["comment"] = list(draft.comment)
    return record


def query_library_cell_types(
    *,
    id: str | None = None,
    manufacturer: str | None = None,
    model_contains: str | None = None,
    chemistry: str | None = None,
    format: str | None = None,
    size_code: str | None = None,
    positive_electrode_basis: str | None = None,
    negative_electrode_basis: str | None = None,
    nominal_capacity_min: float | None = None,
    nominal_capacity_max: float | None = None,
    nominal_voltage_min: float | None = None,
    nominal_voltage_max: float | None = None,
    property_filters: Mapping[str, tuple[float | None, float | None]] | None = None,
    directory: PathLike = DEFAULT_LIBRARY_CELL_TYPES_DIR,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query reusable library cell-type specifications."""
    records: list[dict[str, Any]] = []

    for path in _iter_json_files(_as_path(directory)):
        doc = _load_json(path)
        specification = doc.get("specification", {})
        provenance = doc.get("provenance", {})
        if not isinstance(specification, Mapping):
            continue

        entity_id = specification.get("id")
        properties = specification.get("property", {})
        rec = {
            "id": entity_id,
            "short_id": _short_id_from_iri(entity_id) if isinstance(entity_id, str) else None,
            "manufacturer": specification.get("manufacturer"),
            "model": specification.get("model"),
            "model_name": specification.get("model"),
            "chemistry": specification.get("chemistry"),
            "format": specification.get("format"),
            "size_code": specification.get("size_code"),
            "positive_electrode_basis": specification.get("positive_electrode_basis"),
            "negative_electrode_basis": specification.get("negative_electrode_basis"),
            "nominal_capacity": _quantity_numeric_value(properties, "nominal_capacity")
            if isinstance(properties, Mapping)
            else None,
            "nominal_voltage": _quantity_numeric_value(properties, "nominal_voltage")
            if isinstance(properties, Mapping)
            else None,
            "source_type": provenance.get("source_type") if isinstance(provenance, Mapping) else None,
            "source_name": provenance.get("source_name") if isinstance(provenance, Mapping) else None,
            "source_file": provenance.get("source_file") if isinstance(provenance, Mapping) else None,
            "path": str(path),
            "property": properties if isinstance(properties, Mapping) else {},
            "record": doc,
        }
        records.append(rec)

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if not _str_eq(rec.get("manufacturer"), manufacturer):
            continue
        if not _str_contains(rec.get("model"), model_contains):
            continue
        if not _str_eq(rec.get("chemistry"), chemistry):
            continue
        if not _str_eq(rec.get("format"), format):
            continue
        if not _str_eq(rec.get("size_code"), size_code):
            continue
        if not _str_eq(rec.get("positive_electrode_basis"), positive_electrode_basis):
            continue
        if not _str_eq(rec.get("negative_electrode_basis"), negative_electrode_basis):
            continue
        if not _in_range(rec.get("nominal_capacity"), nominal_capacity_min, nominal_capacity_max):
            continue
        if not _in_range(rec.get("nominal_voltage"), nominal_voltage_min, nominal_voltage_max):
            continue
        if property_filters:
            properties = rec.get("property")
            if not isinstance(properties, Mapping):
                continue
            failed_property_filter = False
            for key, (minimum, maximum) in property_filters.items():
                if not _in_range(_quantity_numeric_value(properties, key), minimum, maximum):
                    failed_property_filter = True
                    break
            if failed_property_filter:
                continue
        filtered.append(rec)

    return _paginate(filtered, limit=limit, offset=offset)


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
            product = doc.get("product", {})
            specs = doc.get("specs", {})
            if isinstance(product, Mapping):
                cell_id = product.get("id")
                manufacturer_obj = product.get("manufacturer")
                manufacturer_name = (
                    manufacturer_obj.get("name")
                    if isinstance(manufacturer_obj, Mapping)
                    else manufacturer_obj
                )
                model_name = product.get("model")
                format_name = product.get("cellFormat")
                size_code = product.get("sizeCode")
                chemistry_name = product.get("chemistry")
                short_id = product.get("short_id")
            else:
                legacy = doc.get("cell_type", {})
                if not isinstance(legacy, Mapping):
                    continue
                cell_id = legacy.get("id")
                manufacturer_name = legacy.get("manufacturer")
                model_name = legacy.get("model_name")
                format_name = legacy.get("format")
                size_code = legacy.get("size_code")
                chemistry_name = legacy.get("chemistry")
                short_id = legacy.get("short_id")
            if not isinstance(cell_id, str) or cell_id in seen_ids:
                continue
            seen_ids.add(cell_id)
            records.append(
                {
                    "id": cell_id,
                    "short_id": short_id or _short_id_from_iri(cell_id),
                    "model_name": model_name,
                    "manufacturer": manufacturer_name,
                    "chemistry": chemistry_name,
                    "format": format_name,
                    "size_code": size_code,
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
    related_test_id: str | None = None,
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
        related_cells: list[str] = []
        about = dataset.get("about")
        if isinstance(about, list):
            related_cells = [
                item
                for item in about
                if isinstance(item, str) and CELL_IRI_RE.fullmatch(item)
            ]
        elif isinstance(dataset.get("related_entities"), Mapping):
            related = dataset["related_entities"].get("cell_ids")
            if isinstance(related, list):
                related_cells = [item for item in related if isinstance(item, str)]

        dist_format = None
        distribution = dataset.get("distribution")
        if isinstance(distribution, list):
            for entry in distribution:
                if isinstance(entry, Mapping) and isinstance(entry.get("encodingFormat"), str):
                    dist_format = entry.get("encodingFormat")
                    break

        rec = {
            "id": dataset.get("id"),
            "short_id": dataset.get("short_id"),
            "title": dataset.get("name") or dataset.get("title"),
            "name": dataset.get("name") or dataset.get("title"),
            "format": dist_format or dataset.get("format"),
            "license": dataset.get("license"),
            "access_url": dataset.get("url") or dataset.get("access_url"),
            "related_cell_ids": related_cells,
            "related_test_ids": [
                item for item in about if isinstance(item, str) and TEST_IRI_RE.fullmatch(item)
            ] if isinstance(about, list) else [],
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
        if related_test_id is not None and related_test_id not in rec.get("related_test_ids", []):
            continue
        if not _str_eq(rec.get("source_type"), source_type):
            continue
        if not _str_eq(rec.get("format"), format):
            continue
        if not _str_eq(rec.get("license"), license):
            continue
        filtered.append(rec)

    return _paginate(filtered, limit=limit, offset=offset)


def query_tests(
    *,
    id: str | None = None,
    cell_id: str | None = None,
    dataset_id: str | None = None,
    kind: str | None = None,
    source_type: str | None = None,
    directory: PathLike = DEFAULT_TESTS_DIR,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query canonical test metadata records."""
    records: list[dict[str, Any]] = []
    for path in _iter_json_files(_as_path(directory)):
        doc = _load_json(path)
        test = doc.get("test", {})
        prov = doc.get("provenance", {})
        if not isinstance(test, Mapping):
            continue
        dataset_ids = test.get("dataset_ids")
        if not isinstance(dataset_ids, list):
            dataset_ids = []
        records.append(
            {
                "id": test.get("id"),
                "cell_id": test.get("cell_id"),
                "short_id": test.get("short_id"),
                "name": test.get("name"),
                "kind": test.get("kind"),
                "status": test.get("status"),
                "dataset_ids": [item for item in dataset_ids if isinstance(item, str)],
                "source_type": prov.get("source_type") if isinstance(prov, Mapping) else None,
                "path": str(path),
                "record": doc,
            }
        )

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if cell_id is not None and rec.get("cell_id") != cell_id:
            continue
        if dataset_id is not None and dataset_id not in rec.get("dataset_ids", []):
            continue
        if not _str_eq(rec.get("kind"), kind):
            continue
        if not _str_eq(rec.get("source_type"), source_type):
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
    report = validate_schema_data(doc, schema)
    if report.ok:
        return
    first = report.errors[0]
    location = first.path
    if location:
        raise ValueError(f"Schema validation failed at '{location}': {first.message}")
    raise ValueError(f"Schema validation failed: {first.message}")


def _validate_canonical_record(
    doc: dict[str, Any],
    *,
    source_root: Path | None = None,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> None:
    report = validate_record_report(doc, source_root=source_root, policy=policy)
    if report.ok:
        return
    first = report.errors[0]
    if first.code.startswith("schema."):
        prefix = "Schema validation failed"
    elif first.validator == "publication":
        prefix = "Publication validation failed"
    else:
        prefix = "Validation failed"
    if first.path:
        raise ValueError(f"{prefix} at '{first.path}': {first.message}")
    raise ValueError(f"{prefix}: {first.message}")


def _validate_publication_artifact(
    doc: dict[str, Any],
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> None:
    report = validate_publication_report(doc, policy=policy)
    if report.ok:
        return
    first = report.errors[0]
    if first.path:
        raise ValueError(f"Publication validation failed at '{first.path}': {first.message}")
    raise ValueError(f"Publication validation failed: {first.message}")


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
        "product": {
            "id": entity_id,
            "short_id": dashed_uid.replace("-", "")[:6],
            "identifier": f"cell-type:{dashed_uid}",
            "name": f"{manufacturer} {model_name}",
            "model": model_name,
            "manufacturer": {"type": "Organization", "name": manufacturer},
            "cellFormat": (cell.get("format") if isinstance(cell, Mapping) else None) or "unknown",
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
            "retrieved_at": _to_unix_time(
                source.get("extracted_at") if isinstance(source, Mapping) else None
            )
            or _now_unix(),
        },
    }

    if isinstance(cell, Mapping):
        if isinstance(cell.get("size_code"), str):
            out["product"]["sizeCode"] = cell["size_code"]
        if isinstance(cell.get("datasheet_revision"), str):
            out["product"]["datasheetRevision"] = cell["datasheet_revision"]
        if isinstance(cell.get("positive_electrode_basis"), str):
            out["product"]["positiveElectrodeBasis"] = cell["positive_electrode_basis"]
        if isinstance(cell.get("negative_electrode_basis"), str):
            out["product"]["negativeElectrodeBasis"] = cell["negative_electrode_basis"]
    if isinstance(source, Mapping) and isinstance(source.get("file_hash"), str):
        out["provenance"]["file_hash"] = source["file_hash"]

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
        product_obj = cell_type_doc.get("product", {})
        if not isinstance(product_obj, Mapping):
            legacy_obj = cell_type_doc.get("cell_type", {})
            if not isinstance(legacy_obj, Mapping):
                raise ValueError("cell_type document must contain a 'product' object.")
            product_obj = legacy_obj
        embedded_id = product_obj.get("id")
        if not isinstance(embedded_id, str):
            raise ValueError("cell-type id missing in provided cell_type document.")
        if resolved_type_id is not None and embedded_id != resolved_type_id:
            raise ValueError("Provided type_id does not match cell-type id.")
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
            "retrieved_at": _now_unix(),
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


def _registration_entity_path(entity_type: str, uid: str, source_root: Path) -> Path:
    if entity_type == "cell-type":
        return source_root / "cell-types" / f"cell-type-{uid}.json"
    if entity_type == "cell":
        return source_root / "cell-instances" / f"cell-{uid}.json"
    if entity_type == "test":
        return source_root / "tests" / f"test-{uid}.json"
    if entity_type == "dataset":
        return source_root / "datasets" / f"dataset-{uid}.json"
    raise ValueError(f"Unsupported entity type for registration path: {entity_type}")


def _iter_entity_files(entity_type: str, source_root: Path) -> list[Path]:
    if entity_type == "cell-type":
        directory = source_root / "cell-types"
    elif entity_type == "cell":
        directory = source_root / "cell-instances"
    elif entity_type == "test":
        directory = source_root / "tests"
    elif entity_type == "dataset":
        directory = source_root / "datasets"
    else:
        return []
    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))


def _find_record_path_by_id(entity_id: str, source_root: Path) -> Path | None:
    entity_type, uid = _iri_tail(entity_id)
    expected = _registration_entity_path(entity_type, uid, source_root)
    if expected.exists():
        try:
            if _entity_id(_load_json(expected)) == entity_id:
                return expected
        except Exception:  # noqa: BLE001
            pass
    for path in _iter_entity_files(entity_type, source_root):
        if path == expected:
            continue
        try:
            if _entity_id(_load_json(path)) == entity_id:
                return path
        except Exception:  # noqa: BLE001
            continue
    return None


def _validate_register_mode(mode: str) -> str:
    mode_normalized = mode.strip().lower()
    if mode_normalized not in REGISTER_MODES:
        raise ValueError(f"mode must be one of: {', '.join(sorted(REGISTER_MODES))}")
    return mode_normalized


def _validate_duplicate_policy(duplicate_policy: str) -> str:
    policy = duplicate_policy.strip().lower()
    if policy not in DUPLICATE_POLICIES:
        raise ValueError(f"duplicate_policy must be one of: {', '.join(sorted(DUPLICATE_POLICIES))}")
    return policy


def _assert_id_matches_uid(entity_id: str, uid: str) -> None:
    _, parsed_uid = _iri_tail(entity_id)
    if parsed_uid != uid:
        raise ValueError("Provided id and uid do not match.")


def _record_from_cell_type(draft: CellTypeInput) -> dict[str, Any]:
    if draft.id is not None:
        if not CELL_TYPE_IRI_RE.fullmatch(draft.id):
            raise ValueError("cell-type id must match https://w3id.org/battinfo/cell-type/{uid}.")
        if draft.uid is not None:
            dashed = _normalized_dashed_uid(draft.uid)
            _assert_id_matches_uid(draft.id, dashed)
        entity_id = draft.id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(draft.uid)
        entity_id = f"https://w3id.org/battinfo/cell-type/{dashed_uid}"

    record: dict[str, Any] = {
        "schema_version": draft.schema_version,
        "product": {
            "id": entity_id,
            "short_id": dashed_uid.replace("-", "")[:6],
            "identifier": f"cell-type:{dashed_uid}",
            "name": f"{draft.manufacturer} {draft.model_name}",
            "model": draft.model_name,
            "manufacturer": {"type": "Organization", "name": draft.manufacturer},
            "cellFormat": draft.format,
            "chemistry": draft.chemistry,
        },
        "specs": draft.specs,
        "provenance": {
            "source_type": draft.source_type,
            "source_file": draft.source_file,
            "source_url": draft.source_url,
            "retrieved_at": draft.retrieved_at or _now_unix(),
        },
    }
    if draft.positive_electrode_basis is not None:
        record["product"]["positiveElectrodeBasis"] = draft.positive_electrode_basis
    if draft.negative_electrode_basis is not None:
        record["product"]["negativeElectrodeBasis"] = draft.negative_electrode_basis
    if draft.size_code is not None:
        record["product"]["sizeCode"] = draft.size_code
    if draft.datasheet_revision is not None:
        record["product"]["datasheetRevision"] = draft.datasheet_revision
    if draft.file_hash is not None:
        record["provenance"]["file_hash"] = draft.file_hash
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record


def _record_from_cell_instance(draft: CellInstanceInput) -> dict[str, Any]:
    if not CELL_TYPE_IRI_RE.fullmatch(draft.type_id):
        raise ValueError("type_id must match https://w3id.org/battinfo/cell-type/{uid}.")
    if draft.dataset_id is not None and not DATASET_IRI_RE.fullmatch(draft.dataset_id):
        raise ValueError("dataset_id must match https://w3id.org/battinfo/dataset/{uid}.")
    for dataset_id in draft.dataset_ids:
        if not DATASET_IRI_RE.fullmatch(dataset_id):
            raise ValueError("dataset_ids entries must match https://w3id.org/battinfo/dataset/{uid}.")

    if draft.id is not None:
        if not CELL_IRI_RE.fullmatch(draft.id):
            raise ValueError("cell-instance id must match https://w3id.org/battinfo/cell/{uid}.")
        if draft.uid is not None:
            dashed = _normalized_dashed_uid(draft.uid)
            _assert_id_matches_uid(draft.id, dashed)
        entity_id = draft.id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(draft.uid)
        entity_id = f"https://w3id.org/battinfo/cell/{dashed_uid}"

    dataset_ids = list(dict.fromkeys([*draft.dataset_ids, *( [draft.dataset_id] if draft.dataset_id else [])]))
    record: dict[str, Any] = {
        "schema_version": draft.schema_version,
        "cell_instance": {
            "id": entity_id,
            "type_id": draft.type_id,
            "short_id": dashed_uid.replace("-", "")[:6],
        },
        "provenance": {
            "source_type": draft.source_type,
            "retrieved_at": _to_unix_time(draft.retrieved_at) or _now_unix(),
        },
    }
    if draft.serial_number is not None:
        record["cell_instance"]["serial_number"] = draft.serial_number
    if draft.batch_id is not None:
        record["cell_instance"]["batch_id"] = draft.batch_id
    if draft.manufactured_at is not None:
        manufactured_at = _to_unix_time(draft.manufactured_at)
        if manufactured_at is None:
            raise ValueError("manufactured_at must be a Unix timestamp or ISO datetime string.")
        record["cell_instance"]["manufactured_at"] = manufactured_at
    if draft.measured:
        record["measured"] = draft.measured
    if draft.source_url is not None:
        record["provenance"]["source_url"] = draft.source_url
    if dataset_ids:
        record["provenance"]["dataset_ids"] = dataset_ids
        record["provenance"]["dataset_id"] = dataset_ids[0]
        record["datasets"] = [{"id": dataset_id, "role": "raw"} for dataset_id in dataset_ids]
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record


def _record_from_dataset(draft: DatasetInput) -> dict[str, Any]:
    if draft.id is not None:
        if not DATASET_IRI_RE.fullmatch(draft.id):
            raise ValueError("dataset id must match https://w3id.org/battinfo/dataset/{uid}.")
        if draft.uid is not None:
            dashed = _normalized_dashed_uid(draft.uid)
            _assert_id_matches_uid(draft.id, dashed)
        entity_id = draft.id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(draft.uid)
        entity_id = f"https://w3id.org/battinfo/dataset/{dashed_uid}"

    for cell_id in draft.related_cell_ids:
        if not CELL_IRI_RE.fullmatch(cell_id):
            raise ValueError("related_cell_ids entries must match https://w3id.org/battinfo/cell/{uid}.")
    for test_id in draft.related_test_ids:
        if not TEST_IRI_RE.fullmatch(test_id):
            raise ValueError("related_test_ids entries must match https://w3id.org/battinfo/test/{uid}.")

    about_refs = list(dict.fromkeys([*draft.related_cell_ids, *draft.related_test_ids]))

    dataset_obj: dict[str, Any] = {
        "id": entity_id,
        "short_id": dashed_uid.replace("-", "")[:6],
        "identifier": f"dataset:{dashed_uid}",
        "name": draft.title,
        "url": draft.access_url or draft.source_url or f"https://example.org/dataset/{dashed_uid}",
    }
    if draft.description is not None:
        dataset_obj["description"] = draft.description
    if draft.license is not None:
        dataset_obj["license"] = draft.license
    if about_refs:
        dataset_obj["about"] = about_refs
    created_unix = _to_unix_time(draft.created_at) or _now_unix()
    dataset_obj["dateCreated"] = created_unix
    dataset_obj["dateModified"] = created_unix
    dataset_obj["datePublished"] = created_unix

    if draft.download_url is not None or draft.format is not None or (draft.checksum_algorithm and draft.checksum_value):
        distribution: dict[str, Any] = {
            "type": "DataDownload",
            "contentUrl": draft.download_url or draft.access_url or draft.source_url or f"https://example.org/dataset/{dashed_uid}/download",
            "encodingFormat": draft.format or "application/octet-stream",
        }
        if draft.checksum_algorithm and draft.checksum_value:
            distribution["checksum"] = {"algorithm": draft.checksum_algorithm, "value": draft.checksum_value}
        dataset_obj["distribution"] = [distribution]

    if draft.checksum_algorithm and draft.checksum_value:
        dataset_obj.setdefault("distribution", [
            {
                "type": "DataDownload",
                "contentUrl": draft.access_url or draft.source_url or f"https://example.org/dataset/{dashed_uid}/download",
                "encodingFormat": draft.format or "application/octet-stream",
            }
        ])
        first_dist = dataset_obj["distribution"][0]
        if isinstance(first_dist, dict):
            first_dist["checksum"] = {"algorithm": draft.checksum_algorithm, "value": draft.checksum_value}

    record: dict[str, Any] = {
        "schema_version": draft.schema_version,
        "dataset": dataset_obj,
        "provenance": {
            "source_type": draft.source_type,
            "retrieved_at": draft.retrieved_at or _now_unix(),
        },
    }
    if draft.source_url is not None:
        record["provenance"]["source_url"] = draft.source_url
    if draft.curated_by is not None:
        record["provenance"]["curated_by"] = draft.curated_by
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record


def _record_from_test(draft: TestInput) -> dict[str, Any]:
    if not CELL_IRI_RE.fullmatch(draft.cell_id):
        raise ValueError("cell_id must match https://w3id.org/battinfo/cell/{uid}.")
    for dataset_id in draft.dataset_ids:
        if not DATASET_IRI_RE.fullmatch(dataset_id):
            raise ValueError("dataset_ids entries must match https://w3id.org/battinfo/dataset/{uid}.")

    if draft.id is not None:
        if not TEST_IRI_RE.fullmatch(draft.id):
            raise ValueError("test id must match https://w3id.org/battinfo/test/{uid}.")
        if draft.uid is not None:
            dashed = _normalized_dashed_uid(draft.uid)
            _assert_id_matches_uid(draft.id, dashed)
        entity_id = draft.id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(draft.uid)
        entity_id = f"https://w3id.org/battinfo/test/{dashed_uid}"

    record: dict[str, Any] = {
        "schema_version": draft.schema_version,
        "test": {
            "id": entity_id,
            "short_id": dashed_uid.replace("-", "")[:6],
            "identifier": f"test:{dashed_uid}",
            "cell_id": draft.cell_id,
            "name": draft.name,
            "kind": draft.kind,
        },
        "provenance": {
            "source_type": draft.source_type,
            "retrieved_at": _to_unix_time(draft.retrieved_at) or _now_unix(),
        },
    }
    if draft.description is not None:
        record["test"]["description"] = draft.description
    if draft.status is not None:
        record["test"]["status"] = draft.status
    if draft.protocol_name is not None:
        record["test"]["protocol_name"] = draft.protocol_name
    if draft.protocol_url is not None:
        record["test"]["protocol_url"] = draft.protocol_url
    if draft.instrument_name is not None:
        record["test"]["instrument_name"] = draft.instrument_name
    if draft.started_at is not None:
        started_at = _to_unix_time(draft.started_at)
        if started_at is None:
            raise ValueError("started_at must be a Unix timestamp or ISO datetime string.")
        record["test"]["started_at"] = started_at
    if draft.ended_at is not None:
        ended_at = _to_unix_time(draft.ended_at)
        if ended_at is None:
            raise ValueError("ended_at must be a Unix timestamp or ISO datetime string.")
        record["test"]["ended_at"] = ended_at
    if draft.dataset_ids:
        record["test"]["dataset_ids"] = list(dict.fromkeys(draft.dataset_ids))
    if draft.source_url is not None:
        record["provenance"]["source_url"] = draft.source_url
    if draft.source_file is not None:
        record["provenance"]["source_file"] = draft.source_file
    if draft.workflow_version is not None:
        record["provenance"]["workflow_version"] = draft.workflow_version
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record


def _resolve_references_for_registration(doc: dict[str, Any], source_root: Path) -> None:
    report = validate_references_report(doc, source_root)
    if report.ok:
        return
    raise ValueError(report.errors[0].message)


def register_record(
    record: dict[str, Any] | PathLike,
    *,
    source_root: PathLike = DEFAULT_REGISTRATION_SOURCE_ROOT,
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    resolve_references: bool = True,
    publish: bool = False,
    publish_root: PathLike = ".battinfo/resolver-site",
    build_jsonld: bool = True,
    build_html: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Register one canonical BattINFO resource into source storage and optional resolver artifacts."""
    mode_normalized = _validate_register_mode(mode)
    duplicate_policy_normalized = _validate_duplicate_policy(duplicate_policy)
    source_root_path = _as_path(source_root)

    doc = _load_json(_as_path(record)) if isinstance(record, (str, Path)) else record
    if validate:
        validation_root = source_root_path if resolve_references else None
        _validate_canonical_record(doc, source_root=validation_root, policy=validation_policy)

    entity_id = _entity_id(doc)
    entity_type, uid = _iri_tail(entity_id)
    existing_path = _find_record_path_by_id(entity_id, source_root_path)
    target_path = existing_path if existing_path is not None else _registration_entity_path(entity_type, uid, source_root_path)

    if resolve_references:
        _resolve_references_for_registration(doc, source_root_path)

    if existing_path is not None and mode_normalized == REGISTER_MODE_CREATE_ONLY:
        if duplicate_policy_normalized == DUPLICATE_POLICY_RETURN_EXISTING:
            return {
                "status": "exists",
                "id": entity_id,
                "entity_type": entity_type,
                "path": str(existing_path),
                "mode": mode_normalized,
                "published": False,
            }
        raise ValueError(
            f"Resource already exists at {existing_path}. "
            "Use mode='upsert' or duplicate_policy='return_existing'."
        )

    operation = "updated" if existing_path is not None else "created"
    payload: dict[str, Any] = {
        "status": "dry-run" if dry_run else operation,
        "id": entity_id,
        "entity_type": entity_type,
        "path": str(target_path),
        "mode": mode_normalized,
        "published": False,
    }

    if dry_run:
        return payload

    _write_json(target_path, doc)

    if publish:
        publish_result = publish_record(
            doc,
            target_root=publish_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=validation_policy,
        )
        payload["published"] = True
        payload["publish_result"] = publish_result

    return payload


def register_cell_type(
    draft: CellTypeInput | dict[str, Any] | PathLike,
    *,
    source_root: PathLike = DEFAULT_REGISTRATION_SOURCE_ROOT,
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    resolve_references: bool = True,
    publish: bool = False,
    publish_root: PathLike = ".battinfo/resolver-site",
    build_jsonld: bool = True,
    build_html: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Register a cell-type from either draft payload or canonical record."""
    from battinfo.bundle import CellType as CellTypeBundle

    if isinstance(draft, (str, Path)):
        loaded = _load_json(_as_path(draft))
        return register_cell_type(
            loaded,
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
        )
    if isinstance(draft, CellTypeBundle):
        return register_record(
            draft.to_record(),
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
        )
    if isinstance(draft, Mapping) and (
        isinstance(draft.get("product"), Mapping) or isinstance(draft.get("cell_type"), Mapping)
    ):
        return register_record(
            dict(draft),
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
        )
    draft_model = draft if isinstance(draft, CellTypeInput) else CellTypeInput.model_validate(draft)
    record = _record_from_cell_type(draft_model)
    return register_record(
        record,
        source_root=source_root,
        mode=mode,
        duplicate_policy=duplicate_policy,
        resolve_references=resolve_references,
        publish=publish,
        publish_root=publish_root,
        build_jsonld=build_jsonld,
        build_html=build_html,
        validate=validate,
        validation_policy=validation_policy,
        dry_run=dry_run,
    )


def register_cell_instance(
    draft: CellInstanceInput | dict[str, Any] | PathLike,
    *,
    source_root: PathLike = DEFAULT_REGISTRATION_SOURCE_ROOT,
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    resolve_references: bool = True,
    publish: bool = False,
    publish_root: PathLike = ".battinfo/resolver-site",
    build_jsonld: bool = True,
    build_html: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Register a cell-instance from either draft payload or canonical record."""
    from battinfo.bundle import CellInstance as CellInstanceBundle

    if isinstance(draft, (str, Path)):
        loaded = _load_json(_as_path(draft))
        return register_cell_instance(
            loaded,
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
        )
    if isinstance(draft, CellInstanceBundle):
        return register_record(
            draft.to_record(),
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
        )
    if isinstance(draft, Mapping) and isinstance(draft.get("cell_instance"), Mapping):
        return register_record(
            dict(draft),
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
        )
    draft_model = draft if isinstance(draft, CellInstanceInput) else CellInstanceInput.model_validate(draft)
    record = _record_from_cell_instance(draft_model)
    return register_record(
        record,
        source_root=source_root,
        mode=mode,
        duplicate_policy=duplicate_policy,
        resolve_references=resolve_references,
        publish=publish,
        publish_root=publish_root,
        build_jsonld=build_jsonld,
        build_html=build_html,
        validate=validate,
        validation_policy=validation_policy,
        dry_run=dry_run,
    )


def register_dataset(
    draft: DatasetInput | dict[str, Any] | PathLike,
    *,
    source_root: PathLike = DEFAULT_REGISTRATION_SOURCE_ROOT,
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    resolve_references: bool = True,
    publish: bool = False,
    publish_root: PathLike = ".battinfo/resolver-site",
    build_jsonld: bool = True,
    build_html: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Register a dataset from either draft payload or canonical record."""
    from battinfo.bundle import Dataset as DatasetBundle

    if isinstance(draft, (str, Path)):
        loaded = _load_json(_as_path(draft))
        return register_dataset(
            loaded,
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
        )
    if isinstance(draft, DatasetBundle):
        return register_record(
            draft.to_record(),
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
        )
    if isinstance(draft, Mapping) and isinstance(draft.get("dataset"), Mapping):
        return register_record(
            dict(draft),
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
        )
    draft_model = draft if isinstance(draft, DatasetInput) else DatasetInput.model_validate(draft)
    record = _record_from_dataset(draft_model)
    return register_record(
        record,
        source_root=source_root,
        mode=mode,
        duplicate_policy=duplicate_policy,
        resolve_references=resolve_references,
        publish=publish,
        publish_root=publish_root,
        build_jsonld=build_jsonld,
        build_html=build_html,
        validate=validate,
        validation_policy=validation_policy,
        dry_run=dry_run,
    )


def register_test(
    draft: TestInput | dict[str, Any] | PathLike,
    *,
    source_root: PathLike = DEFAULT_REGISTRATION_SOURCE_ROOT,
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    resolve_references: bool = True,
    publish: bool = False,
    publish_root: PathLike = ".battinfo/resolver-site",
    build_jsonld: bool = True,
    build_html: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Register a test from either draft payload or canonical record."""
    from battinfo.bundle import Test as TestBundle

    if isinstance(draft, (str, Path)):
        loaded = _load_json(_as_path(draft))
        return register_test(
            loaded,
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
        )
    if isinstance(draft, TestBundle):
        return register_record(
            draft.to_record(),
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
        )
    if isinstance(draft, Mapping) and isinstance(draft.get("test"), Mapping):
        return register_record(
            dict(draft),
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            publish=publish,
            publish_root=publish_root,
            build_jsonld=build_jsonld,
            build_html=build_html,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
        )
    draft_model = draft if isinstance(draft, TestInput) else TestInput.model_validate(draft)
    record = _record_from_test(draft_model)
    return register_record(
        record,
        source_root=source_root,
        mode=mode,
        duplicate_policy=duplicate_policy,
        resolve_references=resolve_references,
        publish=publish,
        publish_root=publish_root,
        build_jsonld=build_jsonld,
        build_html=build_html,
        validate=validate,
        validation_policy=validation_policy,
        dry_run=dry_run,
    )


def build_cell_type_library_rdf(
    *,
    input_dir: PathLike = DEFAULT_LIBRARY_CELL_TYPES_DIR,
    output_jsonld_dir: PathLike = DEFAULT_LIBRARY_RDF_CELL_TYPES_DIR,
    aggregate_jsonld: PathLike = DEFAULT_LIBRARY_AGGREGATE_JSONLD,
    manifest_json: PathLike = DEFAULT_LIBRARY_MANIFEST_JSON,
    glob: str = "*.json",
    clean_output: bool = False,
) -> dict[str, Any]:
    """Validate reusable cell-type specifications and build domain-battery JSON-LD artifacts."""
    input_dir_path = _as_path(input_dir)
    output_jsonld_dir_path = _as_path(output_jsonld_dir)
    aggregate_jsonld_path = _as_path(aggregate_jsonld)
    manifest_json_path = _as_path(manifest_json)

    if not input_dir_path.exists():
        raise FileNotFoundError(f"input_dir does not exist: {input_dir_path}")

    output_jsonld_dir_path.mkdir(parents=True, exist_ok=True)
    aggregate_jsonld_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_json_path.parent.mkdir(parents=True, exist_ok=True)

    if clean_output:
        for path in sorted(output_jsonld_dir_path.glob("*.jsonld")):
            path.unlink()
        for path in sorted(output_jsonld_dir_path.glob("*.json")):
            path.unlink()

    descriptor_paths = sorted(
        path
        for path in input_dir_path.glob(glob)
        if path.is_file() and path.name.lower() != "readme.md"
    )

    manifest_entries: list[dict[str, Any]] = []
    aggregate_graph: list[dict[str, Any]] = []
    aggregate_context: Any = None

    for path in descriptor_paths:
        descriptor = _load_json(path)
        try:
            _validate_cell_specification(descriptor)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc

        mapped = run_mapping(descriptor, target="domain-battery")
        out_path = output_jsonld_dir_path / f"{path.stem}.jsonld"
        _write_json(out_path, mapped)

        if aggregate_context is None and "@context" in mapped:
            aggregate_context = mapped.get("@context")

        graph_nodes = mapped.get("@graph")
        if isinstance(graph_nodes, list):
            aggregate_graph.extend([node for node in graph_nodes if isinstance(node, Mapping)])

        specification = descriptor.get("specification", {})
        if not isinstance(specification, Mapping):
            specification = {}

        manifest_entries.append(
            {
                "source_json": str(path),
                "output_jsonld": str(out_path),
                "id": specification.get("id"),
                "manufacturer": specification.get("manufacturer"),
                "model": specification.get("model"),
                "format": specification.get("format"),
                "chemistry": specification.get("chemistry"),
            }
        )

    aggregate_payload: dict[str, Any] = {
        "@context": aggregate_context or [],
        "@graph": aggregate_graph,
    }
    manifest_payload = {
        "library_type": "battinfo-cell-type-library",
        "entry_count": len(manifest_entries),
        "source_dir": str(input_dir_path),
        "output_jsonld_dir": str(output_jsonld_dir_path),
        "aggregate_jsonld": str(aggregate_jsonld_path),
        "entries": manifest_entries,
    }

    _write_json(aggregate_jsonld_path, aggregate_payload)
    _write_json(manifest_json_path, manifest_payload)

    return {
        "status": "ok",
        "entry_count": len(manifest_entries),
        "aggregate_jsonld": str(aggregate_jsonld_path),
        "manifest_json": str(manifest_json_path),
        "output_jsonld_dir": str(output_jsonld_dir_path),
    }


def register_library_cell_type(
    draft: CellSpecificationInput | dict[str, Any] | PathLike,
    *,
    library_root: PathLike = DEFAULT_LIBRARY_CELL_TYPES_DIR,
    package_root: PathLike = DEFAULT_PACKAGED_LIBRARY_CELL_TYPES_DIR,
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    validate: bool = True,
    sync_packaged_copy: bool = True,
    build_rdf: bool = False,
    output_jsonld_dir: PathLike = DEFAULT_LIBRARY_RDF_CELL_TYPES_DIR,
    aggregate_jsonld: PathLike = DEFAULT_LIBRARY_AGGREGATE_JSONLD,
    manifest_json: PathLike = DEFAULT_LIBRARY_MANIFEST_JSON,
    glob: str = "*.json",
    clean_output: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Register a reusable cell specification into the curated library."""
    from battinfo.bundle import CellSpecification as CellSpecificationBundle

    if isinstance(draft, (str, Path)):
        loaded = _load_json(_as_path(draft))
        return register_library_cell_type(
            loaded,
            library_root=library_root,
            package_root=package_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            validate=validate,
            sync_packaged_copy=sync_packaged_copy,
            build_rdf=build_rdf,
            output_jsonld_dir=output_jsonld_dir,
            aggregate_jsonld=aggregate_jsonld,
            manifest_json=manifest_json,
            glob=glob,
            clean_output=clean_output,
            dry_run=dry_run,
        )

    if isinstance(draft, CellSpecificationBundle):
        doc = draft.to_library_record()
    elif isinstance(draft, Mapping) and isinstance(draft.get("specification"), Mapping):
        doc = dict(draft)
    else:
        draft_model = draft if isinstance(draft, CellSpecificationInput) else CellSpecificationInput.model_validate(draft)
        doc = _record_from_cell_specification(draft_model)

    if validate:
        _validate_cell_specification(doc)

    mode_normalized = _validate_register_mode(mode)
    duplicate_policy_normalized = _validate_duplicate_policy(duplicate_policy)
    library_root_path = _as_path(library_root)
    package_root_path = _as_path(package_root)

    specification = doc.get("specification", {})
    if not isinstance(specification, Mapping):
        raise ValueError("cell specification record must contain a 'specification' object.")

    entity_id = specification.get("id")
    manufacturer = specification.get("manufacturer")
    model = specification.get("model")
    if not isinstance(entity_id, str) or not CELL_TYPE_IRI_RE.fullmatch(entity_id):
        raise ValueError("cell specification field 'specification.id' must match https://w3id.org/battinfo/cell-type/{uid}.")
    if not isinstance(manufacturer, str) or not manufacturer.strip():
        raise ValueError("cell specification field 'specification.manufacturer' must be a non-empty string.")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("cell specification field 'specification.model' must be a non-empty string.")

    expected_path = library_root_path / _library_cell_type_filename(manufacturer, model)
    existing_path = _find_library_descriptor_path_by_id(entity_id, library_root_path)

    if expected_path.exists() and expected_path != existing_path:
        existing_at_target = _load_json(expected_path)
        existing_target_spec = existing_at_target.get("specification", {})
        existing_target_id = existing_target_spec.get("id") if isinstance(existing_target_spec, Mapping) else None
        if existing_target_id == entity_id:
            existing_path = expected_path
        else:
            raise ValueError(
                f"Library target path already exists with a different record id: {expected_path} ({existing_target_id})."
            )

    if existing_path is not None and existing_path != expected_path:
        raise ValueError(
            f"Library record already exists at {existing_path}, but this manufacturer/model maps to {expected_path}. "
            "Rename the existing file manually before updating the descriptor identity."
        )

    target_path = existing_path if existing_path is not None else expected_path
    package_path = package_root_path / target_path.name

    if existing_path is not None and mode_normalized == REGISTER_MODE_CREATE_ONLY:
        if duplicate_policy_normalized == DUPLICATE_POLICY_RETURN_EXISTING:
            return {
                "status": "exists",
                "id": entity_id,
                "entity_type": "cell-type",
                "path": str(existing_path),
                "package_path": str(package_path) if sync_packaged_copy else None,
                "mode": mode_normalized,
                "synced_package": False,
                "built_rdf": False,
            }
        raise ValueError(
            f"Library record already exists at {existing_path}. "
            "Use mode='upsert' or duplicate_policy='return_existing'."
        )

    operation = "updated" if existing_path is not None else "created"
    payload: dict[str, Any] = {
        "status": "dry-run" if dry_run else operation,
        "id": entity_id,
        "entity_type": "cell-type",
        "path": str(target_path),
        "package_path": str(package_path) if sync_packaged_copy else None,
        "mode": mode_normalized,
        "synced_package": False,
        "built_rdf": False,
    }

    if dry_run:
        return payload

    _write_json(target_path, doc)

    if sync_packaged_copy:
        packaged_copy = _sync_library_packaged_copy(target_path, package_root_path)
        payload["package_path"] = str(packaged_copy)
        payload["synced_package"] = True

    if build_rdf:
        rdf_result = build_cell_type_library_rdf(
            input_dir=library_root_path,
            output_jsonld_dir=output_jsonld_dir,
            aggregate_jsonld=aggregate_jsonld,
            manifest_json=manifest_json,
            glob=glob,
            clean_output=clean_output,
        )
        payload["built_rdf"] = True
        payload["rdf_result"] = rdf_result

    return payload


def register_batch(
    *,
    source_dirs: Sequence[PathLike] = DEFAULT_PUBLISH_SOURCES,
    source_root: PathLike = DEFAULT_REGISTRATION_SOURCE_ROOT,
    glob: str = "*.json",
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    resolve_references: bool = True,
    publish: bool = False,
    publish_root: PathLike = ".battinfo/resolver-site",
    build_jsonld: bool = True,
    build_html: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Register a deterministic batch of canonical resources."""
    mode_normalized = _validate_register_mode(mode)
    duplicate_policy_normalized = _validate_duplicate_policy(duplicate_policy)

    failures: list[dict[str, str]] = []
    processed = 0
    created = 0
    updated = 0
    exists = 0
    dry_run_count = 0

    for src_dir in source_dirs:
        src_path = _as_path(src_dir)
        if not src_path.exists():
            continue
        for path in sorted(src_path.glob(glob)):
            processed += 1
            try:
                payload = register_record(
                    path,
                    source_root=source_root,
                    mode=mode_normalized,
                    duplicate_policy=duplicate_policy_normalized,
                    resolve_references=resolve_references,
                    publish=publish,
                    publish_root=publish_root,
                    build_jsonld=build_jsonld,
                    build_html=build_html,
                    validate=validate,
                    validation_policy=validation_policy,
                    dry_run=dry_run,
                )
                status = payload.get("status")
                if status == "created":
                    created += 1
                elif status == "updated":
                    updated += 1
                elif status == "exists":
                    exists += 1
                elif status == "dry-run":
                    dry_run_count += 1
            except Exception as exc:  # noqa: BLE001
                failures.append({"file": str(path), "error": str(exc)})

    return {
        "status": "ok" if not failures else "partial",
        "processed": processed,
        "created": created,
        "updated": updated,
        "exists": exists,
        "dry_run": dry_run_count,
        "failed": len(failures),
        "failures": failures,
    }


def _entity_id(doc: dict[str, Any]) -> str:
    if isinstance(doc.get("product"), Mapping) and isinstance(doc["product"].get("id"), str):
        return doc["product"]["id"]
    if isinstance(doc.get("cell_type"), Mapping) and isinstance(doc["cell_type"].get("id"), str):
        return doc["cell_type"]["id"]
    if isinstance(doc.get("cell_instance"), Mapping) and isinstance(doc["cell_instance"].get("id"), str):
        return doc["cell_instance"]["id"]
    if isinstance(doc.get("test"), Mapping) and isinstance(doc["test"].get("id"), str):
        return doc["test"]["id"]
    if isinstance(doc.get("dataset"), Mapping) and isinstance(doc["dataset"].get("id"), str):
        return doc["dataset"]["id"]
    raise ValueError("Could not locate canonical entity id in document.")


def _entity_schema_rel_path(doc: dict[str, Any]) -> str:
    if isinstance(doc.get("product"), Mapping):
        return "cell-type.schema.json"
    if isinstance(doc.get("cell_type"), Mapping):
        return "cell-type.schema.json"
    if isinstance(doc.get("cell_instance"), Mapping):
        return "cell-instance.schema.json"
    if isinstance(doc.get("test"), Mapping):
        return "test.schema.json"
    if isinstance(doc.get("dataset"), Mapping):
        return "dataset.schema.json"
    raise ValueError("Unsupported record type: expected product/cell_type, cell_instance, test, or dataset.")


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
        cell = doc.get("product")
        if not isinstance(cell, Mapping):
            cell = doc["cell_type"]
        manufacturer = cell.get("manufacturer")
        if isinstance(manufacturer, Mapping):
            manufacturer_name = manufacturer.get("name")
        else:
            manufacturer_name = manufacturer
        out: dict[str, Any] = {
            "@context": context,
            "@id": entity_iri,
            "@type": "battinfo:BatteryCellType",
            "schema:identifier": uid,
            "schema:name": cell.get("name") or cell.get("model") or cell.get("model_name"),
            "schema:manufacturer": {"@type": "schema:Organization", "schema:name": manufacturer_name},
            "battinfo:chemistry": cell.get("chemistry"),
            "battinfo:format": cell.get("cellFormat") or cell.get("format"),
        }
        if cell.get("sizeCode") or cell.get("size_code"):
            out["battinfo:sizeCode"] = cell.get("sizeCode") or cell.get("size_code")
        if cell.get("positiveElectrodeBasis"):
            out["battinfo:positiveElectrodeBasis"] = cell.get("positiveElectrodeBasis")
        if cell.get("negativeElectrodeBasis"):
            out["battinfo:negativeElectrodeBasis"] = cell.get("negativeElectrodeBasis")
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

    if entity_type == "test":
        test = doc["test"]
        out = {
            "@context": context,
            "@id": entity_iri,
            "@type": "battinfo:BatteryCellTest",
            "schema:identifier": uid,
            "schema:name": test.get("name"),
            "battinfo:aboutCell": {"@id": test.get("cell_id")},
            "battinfo:testKind": test.get("kind"),
        }
        if test.get("description"):
            out["schema:description"] = test.get("description")
        if test.get("status"):
            out["schema:creativeWorkStatus"] = test.get("status")
        datasets = test.get("dataset_ids")
        if isinstance(datasets, list):
            refs = [{"@id": dataset_id} for dataset_id in datasets if isinstance(dataset_id, str)]
            if refs:
                out["battinfo:hasDataset"] = refs
        return out

    if entity_type == "dataset":
        dataset = doc["dataset"]
        distribution = dataset.get("distribution")
        encoding_format = None
        if isinstance(distribution, list):
            for entry in distribution:
                if isinstance(entry, Mapping) and isinstance(entry.get("encodingFormat"), str):
                    encoding_format = entry.get("encodingFormat")
                    break
        out = {
            "@context": context,
            "@id": entity_iri,
            "@type": "schema:Dataset",
            "schema:identifier": uid,
            "schema:name": dataset.get("name") or dataset.get("title"),
            "schema:description": dataset.get("description"),
            "schema:license": dataset.get("license"),
            "schema:encodingFormat": encoding_format or dataset.get("format"),
        }
        if dataset.get("url") or dataset.get("access_url"):
            out["schema:url"] = dataset.get("url") or dataset.get("access_url")
        about = dataset.get("about")
        if isinstance(about, list):
            cells = [cell_id for cell_id in about if isinstance(cell_id, str) and CELL_IRI_RE.fullmatch(cell_id)]
            if cells:
                out["battinfo:aboutCell"] = [{"@id": cell_id} for cell_id in cells]
            tests = [test_id for test_id in about if isinstance(test_id, str) and TEST_IRI_RE.fullmatch(test_id)]
            if tests:
                out["battinfo:aboutTest"] = [{"@id": test_id} for test_id in tests]
        else:
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
    target_root: PathLike = ".battinfo/resolver-site",
    build_jsonld: bool = True,
    build_html: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    """Publish one canonical resource into resolver-ready static artifacts."""
    doc = _load_json(_as_path(record)) if isinstance(record, (str, Path)) else record
    if validate:
        _validate_canonical_record(doc, policy=validation_policy)

    iri = _entity_id(doc)
    entity_type, uid = _iri_tail(iri)
    out_dir = _as_path(target_root) / entity_type / uid
    out_dir.mkdir(parents=True, exist_ok=True)

    written = []
    _write_json(out_dir / "index.json", doc)
    written.append(str(out_dir / "index.json"))
    if build_jsonld:
        resolver_payload = _resolver_jsonld(doc)
        if validate:
            _validate_publication_artifact(resolver_payload, policy=validation_policy)
        _write_json(out_dir / "index.jsonld", resolver_payload)
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
    target_root: PathLike = ".battinfo/resolver-site",
    glob: str = "*.json",
    build_jsonld: bool = True,
    build_html: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
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
                    validation_policy=validation_policy,
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
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    """Build a lightweight searchable index from canonical BattINFO resources."""
    src_root = _as_path(source_root)
    if not src_root.exists():
        raise ValueError(f"source_root does not exist: {src_root}")

    cell_types: list[dict[str, Any]] = []
    cell_instances: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    datasets: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    cell_types_dir = src_root / "cell-types"
    cell_instances_dir = src_root / "cell-instances"
    tests_dir = src_root / "tests"
    datasets_dir = src_root / "datasets"

    for path in sorted(cell_types_dir.glob(glob)) if cell_types_dir.exists() else []:
        try:
            doc = _load_json(path)
            if validate:
                _validate_canonical_record(doc, source_root=src_root, policy=validation_policy)
            product = doc.get("product")
            if isinstance(product, Mapping):
                entity = product
            else:
                legacy = doc.get("cell_type")
                if not isinstance(legacy, Mapping):
                    raise ValueError("missing product.id")
                entity = legacy
            if not isinstance(entity.get("id"), str):
                raise ValueError("missing product.id")
            manufacturer_obj = entity.get("manufacturer")
            manufacturer_name = (
                manufacturer_obj.get("name")
                if isinstance(manufacturer_obj, Mapping)
                else manufacturer_obj
            )
            cell_types.append(
                {
                    "id": entity["id"],
                    "short_id": entity.get("short_id") or _short_id_from_iri(entity["id"]),
                    "manufacturer": manufacturer_name,
                    "model_name": entity.get("model") or entity.get("model_name"),
                    "chemistry": entity.get("chemistry"),
                    "format": entity.get("cellFormat") or entity.get("format"),
                    "path": _relative_or_absolute(path, src_root),
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({"file": _relative_or_absolute(path, src_root), "error": str(exc)})

    for path in sorted(cell_instances_dir.glob(glob)) if cell_instances_dir.exists() else []:
        try:
            doc = _load_json(path)
            if validate:
                _validate_canonical_record(doc, source_root=src_root, policy=validation_policy)
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

    for path in sorted(tests_dir.glob(glob)) if tests_dir.exists() else []:
        try:
            doc = _load_json(path)
            if validate:
                _validate_canonical_record(doc, source_root=src_root, policy=validation_policy)
            test = doc.get("test", {})
            prov = doc.get("provenance", {})
            if not isinstance(test, Mapping) or not isinstance(test.get("id"), str):
                raise ValueError("missing test.id")
            dataset_ids = test.get("dataset_ids")
            tests.append(
                {
                    "id": test["id"],
                    "cell_id": test.get("cell_id"),
                    "short_id": test.get("short_id") or _short_id_from_iri(test["id"]),
                    "name": test.get("name"),
                    "kind": test.get("kind"),
                    "source_type": prov.get("source_type") if isinstance(prov, Mapping) else None,
                    "dataset_ids": [item for item in dataset_ids if isinstance(item, str)] if isinstance(dataset_ids, list) else [],
                    "path": _relative_or_absolute(path, src_root),
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({"file": _relative_or_absolute(path, src_root), "error": str(exc)})

    for path in sorted(datasets_dir.glob(glob)) if datasets_dir.exists() else []:
        try:
            doc = _load_json(path)
            if validate:
                _validate_canonical_record(doc, source_root=src_root, policy=validation_policy)
            dataset = doc.get("dataset", {})
            prov = doc.get("provenance", {})
            if not isinstance(dataset, Mapping) or not isinstance(dataset.get("id"), str):
                raise ValueError("missing dataset.id")
            related_cell_ids: list[str] = []
            about = dataset.get("about")
            if isinstance(about, list):
                related_cell_ids = [
                    item for item in about if isinstance(item, str) and CELL_IRI_RE.fullmatch(item)
                ]
            elif isinstance(dataset.get("related_entities"), Mapping):
                related = dataset["related_entities"].get("cell_ids")
                if isinstance(related, list):
                    related_cell_ids = [item for item in related if isinstance(item, str)]
            dist_format = None
            distribution = dataset.get("distribution")
            if isinstance(distribution, list):
                for entry in distribution:
                    if isinstance(entry, Mapping) and isinstance(entry.get("encodingFormat"), str):
                        dist_format = entry.get("encodingFormat")
                        break
            datasets.append(
                {
                    "id": dataset["id"],
                    "short_id": dataset.get("short_id") or _short_id_from_iri(dataset["id"]),
                    "title": dataset.get("name") or dataset.get("title"),
                    "format": dist_format or dataset.get("format"),
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
        "test_count": len(tests),
        "dataset_count": len(datasets),
        "total_count": len(cell_types) + len(cell_instances) + len(tests) + len(datasets),
        "failed": len(failures),
        "failures": failures,
        "cell_types": cell_types,
        "cell_instances": cell_instances,
        "tests": tests,
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
    test_count = (
        int(doc["test_count"])
        if isinstance(doc.get("test_count"), int)
        else len(doc.get("tests", [])) if isinstance(doc.get("tests"), list) else 0
    )
    dataset_count = (
        int(doc["dataset_count"])
        if isinstance(doc.get("dataset_count"), int)
        else len(doc.get("datasets", [])) if isinstance(doc.get("datasets"), list) else 0
    )
    total_count = (
        int(doc["total_count"])
        if isinstance(doc.get("total_count"), int)
        else cell_type_count + cell_instance_count + test_count + dataset_count
    )
    failed = int(doc["failed"]) if isinstance(doc.get("failed"), int) else 0

    out = {
        "build_timestamp": doc.get("build_timestamp"),
        "cell_type_count": cell_type_count,
        "cell_instance_count": cell_instance_count,
        "test_count": test_count,
        "dataset_count": dataset_count,
        "total_count": total_count,
        "failed": failed,
    }
    if index_path is not None:
        out["index_path"] = index_path
    return out


__all__ = [
    "CellSpecificationInput",
    "CellInstanceInput",
    "CellTypeInput",
    "DatasetInput",
    "TestInput",
    "build_cell_type_library_rdf",
    "build_index",
    "create_cell_instance",
    "create_cell_type_from_datasheet",
    "index_stats",
    "publish_batch",
    "publish_record",
    "query_cell_instances",
    "query_library_cell_types",
    "query_cell_types",
    "query_datasets",
    "query_tests",
    "register_batch",
    "register_cell_instance",
    "register_cell_type",
    "register_dataset",
    "register_library_cell_type",
    "resolve_cell_type_id",
    "register_record",
    "register_test",
    "template_cell_specification",
    "template_cell_instance",
    "template_cell_type",
    "template_dataset",
    "template_test",
]
