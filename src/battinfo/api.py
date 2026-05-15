from __future__ import annotations

import copy
import difflib
import html
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from battinfo.bundle import BatteryTestType, CellProductType
from battinfo.canonical_aliases import record_to_legacy_aliases, record_to_snake_aliases
from battinfo.transform.json_to_jsonld import _descriptor_quantity_node as _jsonld_quantity_node
from battinfo.validate.core import DEFAULT_POLICY, ValidationPolicy
from battinfo.validate.publication import validate_publication_report
from battinfo.validate.pydantic import validate_json
from battinfo.validate.record import validate_record, validate_record_report
from battinfo.validate.references import validate_references_report
from battinfo.validate.schema import validate_schema_data
from battinfo.workflows.map import run_mapping

PathLike = str | Path
TestKind = BatteryTestType

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
TEST_PROTOCOL_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/test-protocol/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)

PACKAGE_ROOT = Path(__file__).resolve().parent
EXAMPLES_ROOT = PACKAGE_ROOT / "data" / "examples"
SCHEMAS_ROOT = PACKAGE_ROOT / "data" / "schemas"

DEFAULT_CELL_TYPES_DIR = EXAMPLES_ROOT / "cell-type"
DEFAULT_CELL_INSTANCES_DIR = EXAMPLES_ROOT / "cell-instances"
DEFAULT_TEST_PROTOCOLS_DIR = EXAMPLES_ROOT / "test-protocols"
DEFAULT_TESTS_DIR = EXAMPLES_ROOT / "tests"
DEFAULT_DATASETS_DIR = EXAMPLES_ROOT / "dataset"
DEFAULT_LIBRARY_CELL_TYPES_DIR = Path(".battinfo") / "library" / "cell-type"
DEFAULT_LIBRARY_RDF_CELL_TYPES_DIR = Path(".battinfo") / "library-rdf" / "cell-type"
DEFAULT_LIBRARY_AGGREGATE_JSONLD = Path(".battinfo") / "ontology" / "library" / "cell-type.jsonld"
DEFAULT_LIBRARY_MANIFEST_JSON = Path(".battinfo") / "library-rdf" / "cell-type.index.json"
DEFAULT_PACKAGED_LIBRARY_CELL_TYPES_DIR = Path("src") / "battinfo" / "data" / "library" / "cell-type"
DEFAULT_PUBLISH_SOURCES = (
    DEFAULT_CELL_TYPES_DIR,
    DEFAULT_CELL_INSTANCES_DIR,
    DEFAULT_TEST_PROTOCOLS_DIR,
    DEFAULT_TESTS_DIR,
    DEFAULT_DATASETS_DIR,
)
DEFAULT_INDEX_SOURCE_ROOT = EXAMPLES_ROOT
DEFAULT_REGISTRATION_SOURCE_ROOT = Path("examples")
TEMPLATE_UID = "0000000000000000"
TEMPLATE_CELL_TYPE_ID = "https://w3id.org/battinfo/cell-type/0000-0000-0000-0000"
TEMPLATE_CELL_ID = "https://w3id.org/battinfo/cell/0000-0000-0000-0000"

REGISTER_MODE_CREATE_ONLY = "create_only"
REGISTER_MODE_UPSERT = "upsert"
REGISTER_MODES = {REGISTER_MODE_CREATE_ONLY, REGISTER_MODE_UPSERT}

DUPLICATE_POLICY_ERROR = "error"
DUPLICATE_POLICY_RETURN_EXISTING = "return_existing"
DUPLICATE_POLICIES = {DUPLICATE_POLICY_ERROR, DUPLICATE_POLICY_RETURN_EXISTING}

_DOI_URL_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/(10\.\S+)$", re.IGNORECASE)
_DOI_LITERAL_RE = re.compile(r"^(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)$")


def _citation_doi_from_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = _DOI_URL_RE.match(value.strip())
    if match is None:
        return None
    return match.group(1)


def _citation_url_value(citation: object = None, citation_doi: object = None) -> str | None:
    if isinstance(citation, str):
        normalized = citation.strip()
        if not normalized:
            return None
        extracted = _citation_doi_from_url(normalized)
        if extracted is not None:
            return f"https://doi.org/{extracted}"
        if _DOI_LITERAL_RE.fullmatch(normalized):
            return f"https://doi.org/{normalized}"
        return normalized
    if isinstance(citation_doi, str):
        normalized = citation_doi.strip()
        if not normalized:
            return None
        extracted = _citation_doi_from_url(normalized)
        if extracted is not None:
            return f"https://doi.org/{extracted}"
        return f"https://doi.org/{normalized}"
    return None


class CellTypeInput(BaseModel):
    """Typed input for saving a new canonical cell-type resource."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1.0"
    id: str | None = None
    uid: str | None = None
    model_name: str
    manufacturer: str
    format: Literal["cylindrical", "prismatic", "pouch", "coin", "other", "unknown"] = "unknown"
    chemistry: str = "unknown"
    product_type: CellProductType | None = None
    positive_electrode_basis: str | None = None
    negative_electrode_basis: str | None = None
    size_code: str | None = None
    iec_code: str | None = None
    country_of_origin: str | None = None
    year: int | None = None
    datasheet_revision: str | None = None
    specs: dict[str, Any] = Field(default_factory=dict)
    source_type: Literal["datasheet", "label", "catalog", "manual", "other"] = "datasheet"
    source_file: str = "manual.json"
    source_url: str | None = None
    citation: str | None = Field(default=None, validation_alias=AliasChoices("citation", "citation_doi"))
    file_hash: str | None = None
    retrieved_at: int | None = None
    notes: list[str] = Field(default_factory=list)


class CellSpecificationInput(BaseModel):
    """Typed input for saving a reusable cell specification for a cell type."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    id: str | None = None
    uid: str | None = None
    manufacturer: str
    model: str
    format: Literal["cylindrical", "prismatic", "pouch", "coin", "other", "unknown"]
    chemistry: str
    product_type: CellProductType | None = None
    positive_electrode_basis: str
    negative_electrode_basis: str
    size_code: str | None = None
    construction: dict[str, Any] = Field(default_factory=dict)
    property: dict[str, Any] = Field(default_factory=dict)
    specification_comment: list[str] = Field(default_factory=list)
    source_type: str = "datasheet"
    source_name: str | None = None
    source_file: str = "manual.json"
    source_url: str | None = None
    citation: str | None = Field(default=None, validation_alias=AliasChoices("citation", "citation_doi"))
    retrieved_at: int | str | None = None
    workflow_version: str | None = None
    provenance_comment: str | None = None
    comment: list[str] = Field(default_factory=list)


class CellInstanceInput(BaseModel):
    """Typed input for saving a new canonical cell-instance resource."""

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
    citation: str | None = Field(default=None, validation_alias=AliasChoices("citation", "citation_doi"))
    retrieved_at: int | str | None = None
    notes: list[str] = Field(default_factory=list)


class DatasetInput(BaseModel):
    """Typed input for saving a new canonical dataset resource."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1.0"
    id: str | None = None
    uid: str | None = None
    title: str
    description: str | None = None
    license: str | None = None
    identifier: Any | None = None
    same_as: list[str] = Field(default_factory=list)
    additional_type: list[str] = Field(default_factory=list)
    version: str | None = None
    keywords: list[str] = Field(default_factory=list)
    creator: list[dict[str, Any]] = Field(default_factory=list)
    publisher: dict[str, Any] | None = None
    funder: list[dict[str, Any]] = Field(default_factory=list)
    citation_list: list[dict[str, Any]] = Field(default_factory=list)
    measurement_techniques: list[str] = Field(default_factory=list)
    measurement_methods: list[str] = Field(default_factory=list)
    variable_measured: list[dict[str, Any]] = Field(default_factory=list)
    is_accessible_for_free: bool | None = None
    conditions_of_access: str | None = None
    in_language: str | None = None
    format: str | None = None
    access_url: str | None = None
    download_url: str | None = None
    created_at: str | None = None
    modified_at: str | None = None
    published_at: str | None = None
    temporal_coverage: str | None = None
    spatial_coverage: str | None = None
    is_based_on: list[str] = Field(default_factory=list)
    included_in_data_catalog: Any | None = None
    main_entity: list[dict[str, Any]] = Field(default_factory=list)
    distribution: list[dict[str, Any]] = Field(default_factory=list)
    checksum_algorithm: Literal["sha256", "sha512", "md5", "other"] | None = None
    checksum_value: str | None = None
    related_cell_ids: list[str] = Field(default_factory=list)
    related_test_ids: list[str] = Field(default_factory=list)
    source_type: Literal["catalog", "measurement", "lab", "simulation", "external", "manual", "other"] = "other"
    source_url: str | None = None
    citation: str | None = Field(default=None, validation_alias=AliasChoices("citation", "citation_doi"))
    retrieved_at: int | None = None
    curated_by: str | None = None
    notes: list[str] = Field(default_factory=list)


class TestInput(BaseModel):
    """Typed input for saving a new canonical test resource."""

    model_config = ConfigDict(extra="forbid")
    __test__ = False

    schema_version: str = "0.1.0"
    id: str | None = None
    uid: str | None = None
    cell_id: str
    name: str
    kind: TestKind
    protocol_id: str | None = None
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
    citation: str | None = Field(default=None, validation_alias=AliasChoices("citation", "citation_doi"))
    source_file: str | None = None
    retrieved_at: int | str | None = None
    workflow_version: str | None = None
    notes: list[str] = Field(default_factory=list)


class TestProtocolInput(BaseModel):
    """Typed input for saving a reusable canonical test-protocol resource."""

    model_config = ConfigDict(extra="forbid")
    __test__ = False

    schema_version: str = "0.1.0"
    id: str | None = None
    uid: str | None = None
    name: str
    kind: TestKind
    description: str | None = None
    version: str | None = None
    protocol_url: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)
    setpoints: dict[str, Any] = Field(default_factory=dict)
    termination_criteria: dict[str, Any] = Field(default_factory=dict)
    measurement_outputs: list[dict[str, Any]] = Field(default_factory=list)
    source_type: Literal["manual", "lab", "simulation", "other"] = "manual"
    source_url: str | None = None
    citation: str | None = Field(default=None, validation_alias=AliasChoices("citation", "citation_doi"))
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
    iec_code: str | None = None,
    country_of_origin: str | None = None,
    year: int | None = None,
    uid: str | None = TEMPLATE_UID,
    source_file: str = "template-cell-type.json",
) -> dict[str, Any]:
    """Build a starter canonical cell-type document for save workflows."""
    draft = CellTypeInput(
        uid=uid,
        model_name=model_name,
        manufacturer=manufacturer,
        chemistry=chemistry,
        format=format,
        iec_code=iec_code,
        country_of_origin=country_of_origin,
        year=year,
        source_file=source_file,
        specs={},
        notes=["Template-generated record. Fill in specs/provenance before saving."],
    )
    return _record_from_cell_type(draft)


def template_cell_type_draft(
    *,
    manufacturer: str = "ExampleManufacturer",
    model_name: str = "MODEL-001",
    chemistry: str = "unknown",
    format: Literal["cylindrical", "prismatic", "pouch", "coin", "other", "unknown"] = "unknown",
    size_code: str | None = None,
    iec_code: str | None = None,
    country_of_origin: str | None = None,
    year: int | None = None,
    positive_electrode_basis: str | None = None,
    negative_electrode_basis: str | None = None,
    datasheet_revision: str | None = None,
) -> dict[str, Any]:
    """Build a starter authoring draft for a hand-edited cell-type JSON file."""
    draft: dict[str, Any] = {
        "manufacturer": manufacturer,
        "model": model_name,
        "format": format,
        "chemistry": chemistry,
        "specs": {},
        "comment": "Template-generated cell-type authoring draft. Fill in trusted values before loading into Workspace.",
    }
    if size_code is not None:
        draft["size_code"] = size_code
    if iec_code is not None:
        draft["iec_code"] = iec_code
    if country_of_origin is not None:
        draft["country_of_origin"] = country_of_origin
    if year is not None:
        draft["year"] = year
    if positive_electrode_basis is not None:
        draft["positive_electrode_basis"] = positive_electrode_basis
    if negative_electrode_basis is not None:
        draft["negative_electrode_basis"] = negative_electrode_basis
    if datasheet_revision is not None:
        draft["datasheet_revision"] = datasheet_revision
    return draft


def template_cell_instance(
    *,
    type_id: str = TEMPLATE_CELL_TYPE_ID,
    source_type: Literal["measurement", "lab", "bms", "other"] = "measurement",
    uid: str | None = TEMPLATE_UID,
) -> dict[str, Any]:
    """Build a starter canonical cell-instance document for save workflows."""
    draft = CellInstanceInput(
        uid=uid,
        type_id=type_id,
        source_type=source_type,
        notes=["Template-generated record. Set type_id/serial_number/datasets before saving."],
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
    """Build a starter canonical dataset document for save workflows."""
    draft = DatasetInput(
        uid=uid,
        title=title,
        source_type=source_type,
        related_cell_ids=related_cell_ids or [TEMPLATE_CELL_ID],
        related_test_ids=related_test_ids or [],
        notes=["Template-generated record. Fill in URL/license/distribution details before saving."],
    )
    return _record_from_dataset(draft)


def template_test(
    *,
    cell_id: str = TEMPLATE_CELL_ID,
    name: str = "Example Test",
    kind: TestKind = BatteryTestType.OTHER,
    source_type: Literal["measurement", "lab", "simulation", "manual", "other"] = "measurement",
    uid: str | None = TEMPLATE_UID,
    dataset_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a starter canonical test document for save workflows."""
    draft = TestInput(
        uid=uid,
        cell_id=cell_id,
        name=name,
        kind=kind,
        source_type=source_type,
        dataset_ids=dataset_ids or [],
        notes=["Template-generated record. Set the concrete cell, protocol, and datasets before saving."],
    )
    return _record_from_test(draft)


def template_test_protocol(
    *,
    name: str = "Example Test Protocol",
    kind: TestKind = BatteryTestType.OTHER,
    source_type: Literal["manual", "lab", "simulation", "other"] = "manual",
    uid: str | None = TEMPLATE_UID,
) -> dict[str, Any]:
    """Build a starter canonical test-protocol document for save workflows."""
    draft = TestProtocolInput(
        uid=uid,
        name=name,
        kind=kind,
        source_type=source_type,
        notes=["Template-generated record. Fill in conditions/setpoints before saving."],
    )
    return _record_from_test_protocol(draft)


def template_test_protocol_draft(
    *,
    name: str = "Example Test Protocol",
    kind: TestKind = BatteryTestType.OTHER,
    version: str | None = None,
    protocol_url: str | None = None,
) -> dict[str, Any]:
    """Build a starter authoring draft for a hand-edited test-protocol JSON file."""
    draft: dict[str, Any] = {
        "name": name,
        "kind": str(kind),
        "conditions": {},
        "setpoints": {},
        "termination_criteria": {},
        "measurement_outputs": [],
        "comment": "Template-generated test-protocol authoring draft. Fill in trusted procedure details before loading into Workspace.",
    }
    if version is not None:
        draft["version"] = version
    if protocol_url is not None:
        draft["protocol_url"] = protocol_url
    return draft


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
    return record_to_legacy_aliases(json.loads(path.read_text(encoding="utf-8")))


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


def _str_fuzzy_match(left: object, right: str | None, threshold: float = 0.80) -> bool:
    """Match a stored value against a query string with tolerance for name variants and typos.

    Passes when:
    - right is None (no filter)
    - either string is a substring of the other (case-insensitive) — catches "LG" vs
      "LG Chem", "Samsung" vs "Samsung SDI", etc.
    - difflib similarity ratio >= threshold — catches single-character typos and
      transpositions like "Energizer" vs "Enegizer"
    """
    if right is None:
        return True
    if left is None:
        return False
    left_s = str(left).lower().strip()
    r = right.lower().strip()
    if r in left_s or left_s in r:
        return True
    return difflib.SequenceMatcher(None, left_s, r).ratio() >= threshold


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
    result = validate_json(doc, profile="cell-descriptor")
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


def _editorial_record_id(*values: object) -> str:
    tokens: list[str] = []
    for raw in values:
        text = str(raw).strip().lower()
        if not text:
            continue
        parts = re.split(r"-{2,}", text)
        for part in parts:
            normalized = re.sub(r"[^a-z0-9]+", "-", part).strip("-")
            if normalized:
                tokens.append(normalized)
    return "--".join(tokens) or "record"


def _comment_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    raise ValueError("comment/notes must be a string or list of strings.")


def _editorial_date_token(value: object) -> str | None:
    unix_time = _to_unix_time(value)
    if unix_time is None:
        return None
    return datetime.fromtimestamp(unix_time, tz=timezone.utc).strftime("%Y%m%d")


def _staging_cell_type_identity(
    source: dict[str, Any] | PathLike,
    draft: CellTypeInput,
) -> dict[str, Any]:
    if isinstance(source, (str, Path)):
        payload = _load_json(_as_path(source))
    else:
        payload = dict(source)
    provenance = payload.get("provenance")
    provenance_map = provenance if isinstance(provenance, Mapping) else {}

    base_record_id = _editorial_record_id(draft.manufacturer, draft.model_name)

    if draft.year is not None:
        resolved = _editorial_record_id(draft.manufacturer, draft.model_name, draft.year)
        return {
            "record_id": resolved,
            "record_id_basis": "year",
            "record_id_hint": resolved,
            "requires_record_id": False,
        }

    revision_candidates = (
        payload.get("datasheet_revision"),
        provenance_map.get("datasheet_revision"),
        provenance_map.get("revision"),
        provenance_map.get("source_id"),
    )
    for candidate in revision_candidates:
        if isinstance(candidate, str) and candidate.strip():
            resolved = _editorial_record_id(draft.manufacturer, draft.model_name, candidate)
            return {
                "record_id": resolved,
                "record_id_basis": "revision",
                "record_id_hint": resolved,
                "requires_record_id": False,
            }

    date_candidates = (
        payload.get("observed_at"),
        payload.get("evidence_date"),
        payload.get("retrieved_at"),
        provenance_map.get("observed_at"),
        provenance_map.get("evidence_date"),
        provenance_map.get("retrieved_at"),
    )
    for candidate in date_candidates:
        date_token = _editorial_date_token(candidate)
        if date_token is not None:
            resolved = _editorial_record_id(draft.manufacturer, draft.model_name, date_token)
            return {
                "record_id": resolved,
                "record_id_basis": "evidence_date",
                "record_id_hint": resolved,
                "requires_record_id": False,
            }

    return {
        "record_id": None,
        "record_id_basis": None,
        "record_id_hint": f"{base_record_id}--<year-or-revision>",
        "requires_record_id": True,
    }


def _staging_cell_type_input(
    source: dict[str, Any] | PathLike,
    *,
    uid: str | None = None,
) -> tuple[CellTypeInput, Path | None]:
    source_path: Path | None = None
    if isinstance(source, (str, Path)):
        source_path = _as_path(source)
        payload = _load_json(source_path)
    else:
        payload = dict(source)

    if isinstance(payload.get("product"), Mapping) or isinstance(payload.get("cell_type"), Mapping):
        record_payload = dict(payload)
        if isinstance(record_payload.get("cell_type"), Mapping) and "product" not in record_payload:
            record_payload["product"] = dict(record_payload["cell_type"])
        product = record_payload.get("product")
        provenance = record_payload.get("provenance")
        if not isinstance(product, Mapping):
            raise ValueError("canonical cell-type record is missing product.")
        manufacturer_obj = product.get("manufacturer")
        manufacturer = manufacturer_obj.get("name") if isinstance(manufacturer_obj, Mapping) else manufacturer_obj
        return (
            CellTypeInput(
                schema_version=str(record_payload.get("schema_version") or "0.1.0"),
                id=product.get("id") if isinstance(product.get("id"), str) else None,
                uid=uid,
                model_name=str(product.get("model") or product.get("model_name") or ""),
                manufacturer=str(manufacturer or ""),
                format=str(product.get("cell_format") or product.get("cellFormat") or product.get("format") or "unknown"),
                chemistry=str(product.get("chemistry") or "unknown"),
                positive_electrode_basis=(product.get("positive_electrode_basis") or product.get("positiveElectrodeBasis"))
                if isinstance(product.get("positive_electrode_basis") or product.get("positiveElectrodeBasis"), str)
                else None,
                negative_electrode_basis=(product.get("negative_electrode_basis") or product.get("negativeElectrodeBasis"))
                if isinstance(product.get("negative_electrode_basis") or product.get("negativeElectrodeBasis"), str)
                else None,
                size_code=(product.get("size_code") if isinstance(product.get("size_code"), str) else product.get("sizeCode") if isinstance(product.get("sizeCode"), str) else None),
                iec_code=(product.get("iec_code") if isinstance(product.get("iec_code"), str) else product.get("iecCode") if isinstance(product.get("iecCode"), str) else None),
                country_of_origin=(product.get("country_of_origin") if isinstance(product.get("country_of_origin"), str) else product.get("countryOfOrigin") if isinstance(product.get("countryOfOrigin"), str) else None),
                year=product.get("year") if isinstance(product.get("year"), int) else None,
                datasheet_revision=(product.get("datasheet_revision") or product.get("datasheetRevision"))
                if isinstance(product.get("datasheet_revision") or product.get("datasheetRevision"), str)
                else None,
                specs=dict(record_payload.get("specs") or {}),
                source_type=str(provenance.get("source_type") or "datasheet") if isinstance(provenance, Mapping) else "datasheet",
                source_file=(
                    str(provenance.get("source_file"))
                    if isinstance(provenance, Mapping) and isinstance(provenance.get("source_file"), str)
                    else source_path.name if source_path is not None else "manual.json"
                ),
                source_url=provenance.get("source_url") if isinstance(provenance, Mapping) and isinstance(provenance.get("source_url"), str) else None,
                citation=provenance.get("citation") if isinstance(provenance, Mapping) and isinstance(provenance.get("citation"), str) else None,
                file_hash=provenance.get("file_hash") if isinstance(provenance, Mapping) and isinstance(provenance.get("file_hash"), str) else None,
                retrieved_at=_to_unix_time(provenance.get("retrieved_at")) if isinstance(provenance, Mapping) else None,
                notes=_comment_list(record_payload.get("notes")),
            ),
            source_path,
        )

    model_name = payload.get("model_name")
    if model_name is None:
        model_name = payload.get("model")
    manufacturer = payload.get("manufacturer")
    format_value = payload.get("format")
    chemistry = payload.get("chemistry")
    if not all(isinstance(value, str) and value.strip() for value in (manufacturer, model_name, format_value, chemistry)):
        raise ValueError("staging cell-type JSON requires non-empty string fields: manufacturer, model/model_name, format, chemistry.")

    specs = payload.get("specs")
    if specs is None:
        specs = payload.get("nominal_properties")
    if specs is None:
        specs = {}
    if not isinstance(specs, Mapping):
        raise ValueError("staging cell-type JSON field 'specs' must be an object when provided.")

    provenance = payload.get("provenance")
    if provenance is None:
        provenance = {}
    if not isinstance(provenance, Mapping):
        raise ValueError("staging cell-type JSON field 'provenance' must be an object when provided.")

    year = payload.get("year")
    parsed_year = year if isinstance(year, int) else int(year) if isinstance(year, str) and year.strip().isdigit() else None
    retrieved_at = payload.get("retrieved_at", provenance.get("retrieved_at"))

    return (
        CellTypeInput(
            uid=uid,
            manufacturer=manufacturer.strip(),
            model_name=str(model_name).strip(),
            chemistry=chemistry.strip(),
            format=format_value.strip(),  # type: ignore[arg-type]
            positive_electrode_basis=payload.get("positive_electrode_basis")
            if isinstance(payload.get("positive_electrode_basis"), str)
            else None,
            negative_electrode_basis=payload.get("negative_electrode_basis")
            if isinstance(payload.get("negative_electrode_basis"), str)
            else None,
            size_code=payload.get("size_code") if isinstance(payload.get("size_code"), str) else None,
            iec_code=payload.get("iec_code") if isinstance(payload.get("iec_code"), str) else None,
            country_of_origin=payload.get("country_of_origin") if isinstance(payload.get("country_of_origin"), str) else None,
            year=parsed_year,
            datasheet_revision=payload.get("datasheet_revision") if isinstance(payload.get("datasheet_revision"), str) else None,
            specs=dict(specs),
            source_type=str(payload.get("source_type", provenance.get("source_type")) or "datasheet"),
            source_file=(
                str(payload.get("source_file", provenance.get("source_file")))
                if isinstance(payload.get("source_file", provenance.get("source_file")), str)
                else source_path.name if source_path is not None else "manual.json"
            ),
            source_url=payload.get("source_url", provenance.get("source_url"))
            if isinstance(payload.get("source_url", provenance.get("source_url")), str)
            else None,
            citation=payload.get("citation", provenance.get("citation"))
            if isinstance(payload.get("citation", provenance.get("citation")), str)
            else None,
            file_hash=payload.get("file_hash", provenance.get("file_hash"))
            if isinstance(payload.get("file_hash", provenance.get("file_hash")), str)
            else None,
            retrieved_at=_to_unix_time(retrieved_at),
            notes=_comment_list(payload.get("notes", payload.get("comment"))),
        ),
        source_path,
    )


def validate_staging_cell_type(
    source: dict[str, Any] | PathLike,
    *,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    """Validate a staging cell-type draft without writing anything to disk.

    Returns a dict with keys ``ok`` (bool), ``source_path``, ``record_id``,
    ``record_id_basis``, ``issues`` (list of validation issue dicts), and
    ``errors`` (list of error-severity issues only).
    """
    draft, source_path = _staging_cell_type_input(source)
    identity = _staging_cell_type_identity(source, draft)
    record = _record_from_cell_type(draft)
    report = validate_record_report(record, policy=validation_policy)
    return {
        "ok": report.ok,
        "source_path": str(source_path) if source_path is not None else None,
        "record_id": identity["record_id"],
        "record_id_basis": identity["record_id_basis"],
        "record_id_hint": identity["record_id_hint"],
        "requires_record_id": identity["requires_record_id"],
        "record": record,
        "issues": [
            {
                "severity": issue.severity,
                "code": issue.code,
                "path": issue.path,
                "message": issue.message,
                "hint": issue.hint,
            }
            for issue in report.issues
        ],
    }


def validate_staging_cell_types(
    *,
    input_dir: PathLike,
    glob: str = "*.json",
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    input_root = _as_path(input_dir)
    if not input_root.exists() or not input_root.is_dir():
        raise ValueError(f"input_dir does not exist: {input_root}")
    results: list[dict[str, Any]] = []
    for path in sorted(input_root.glob(glob)):
        if path.name.startswith("_"):
            continue
        results.append(validate_staging_cell_type(path, validation_policy=validation_policy))
    return {
        "status": "ok",
        "input_dir": str(input_root),
        "processed": len(results),
        "ok": sum(1 for item in results if item["ok"]),
        "failed": sum(1 for item in results if not item["ok"]),
        "results": results,
    }


def _existing_curated_cell_type_id(target_path: Path) -> str | None:
    if not target_path.exists():
        return None
    try:
        payload = _load_json(target_path)
    except Exception:  # noqa: BLE001
        return None
    product = payload.get("product")
    if isinstance(product, Mapping) and isinstance(product.get("id"), str):
        return product["id"]
    return None


def promote_staging_cell_type(
    source: dict[str, Any] | PathLike,
    *,
    curated_root: PathLike,
    record_id: str | None = None,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Promote a validated staging cell-type draft to the curated record store.

    Validates the draft, assigns or resolves the canonical record IRI, writes
    the canonical JSON file to ``curated_root``, and returns a result dict with
    keys ``ok``, ``record_id``, ``path``, ``dry_run``, and ``issues``.

    Pass ``dry_run=True`` to validate and resolve the IRI without writing files.
    """
    draft, source_path = _staging_cell_type_input(source)
    identity = _staging_cell_type_identity(source, draft)
    if record_id is not None:
        resolved_record_id = _editorial_record_id(record_id)
    else:
        resolved_record_id = identity["record_id"]
        if not isinstance(resolved_record_id, str) or not resolved_record_id:
            raise ValueError(
                "staging cell-type does not have a safe automatic record id. "
                f"Provide --record-id explicitly; suggested pattern: {identity['record_id_hint']}."
            )

    curated_root_path = _as_path(curated_root)
    target_path = curated_root_path / resolved_record_id / "record.json"
    existing_id = _existing_curated_cell_type_id(target_path)
    if existing_id is not None:
        draft = draft.model_copy(update={"id": existing_id, "uid": None})

    record = _record_from_cell_type(draft)
    report = validate_record_report(record, policy=validation_policy)
    if not report.ok:
        raise ValueError(f"staging cell-type validation failed: {'; '.join(report.render_errors())}")

    if not dry_run:
        _write_json(target_path, record)
    return {
        "status": "ok",
        "record_id": resolved_record_id,
        "record_id_basis": identity["record_id_basis"] if record_id is None else "manual",
        "source_path": str(source_path) if source_path is not None else None,
        "target_path": str(target_path),
        "record": record,
        "dry_run": dry_run,
    }


def promote_staging_cell_types(
    *,
    input_dir: PathLike,
    curated_root: PathLike,
    glob: str = "*.json",
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    input_root = _as_path(input_dir)
    if not input_root.exists() or not input_root.is_dir():
        raise ValueError(f"input_dir does not exist: {input_root}")
    promoted: list[dict[str, Any]] = []
    for path in sorted(input_root.glob(glob)):
        if path.name.startswith("_"):
            continue
        promoted.append(
            promote_staging_cell_type(
                path,
                curated_root=curated_root,
                validation_policy=validation_policy,
                dry_run=dry_run,
            )
        )
    return {
        "status": "ok",
        "input_dir": str(input_root),
        "curated_root": str(_as_path(curated_root)),
        "processed": len(promoted),
        "dry_run": dry_run,
        "results": promoted,
    }


def _curated_cell_type_source(
    source: dict[str, Any] | PathLike,
) -> tuple[dict[str, Any], Path | None, str | None]:
    source_path: Path | None = None
    if isinstance(source, (str, Path)):
        source_path = _as_path(source)
        payload = _load_json(source_path)
    else:
        payload = dict(source)

    product = payload.get("product")
    if not isinstance(product, Mapping):
        raise ValueError("curated cell-type source must be a canonical record with a top-level product object.")

    inferred_local_id: str | None = None
    if source_path is not None:
        if source_path.name == "record.json" and source_path.parent.name and not source_path.parent.name.startswith("_"):
            inferred_local_id = source_path.parent.name
        elif source_path.stem and not source_path.stem.startswith("_"):
            inferred_local_id = source_path.stem
    return payload, source_path, inferred_local_id


def _curated_cell_type_title(record: Mapping[str, Any]) -> str:
    product = record.get("product")
    if not isinstance(product, Mapping):
        raise ValueError("cell-type record is missing product.")
    manufacturer_obj = product.get("manufacturer")
    manufacturer = manufacturer_obj.get("name") if isinstance(manufacturer_obj, Mapping) else manufacturer_obj
    return str(product.get("name") or f"{manufacturer or 'Battery'} {product.get('model') or 'Cell'}").strip()


def _curated_cell_type_submission_resource(
    *,
    record: Mapping[str, Any],
    source_local_id: str,
    title: str,
) -> dict[str, Any]:
    return {
        "resource_type": "cell_type",
        "source_local_id": source_local_id,
        "title": title,
        "semantic_payload": {
            "@type": "CellType",
            "battinfo_records": {"cell_type": dict(record)},
        },
        "related_resources": [],
        "distributions": [],
    }


def build_curated_cell_type_submission(
    source: dict[str, Any] | PathLike,
    *,
    workspace_id: str,
    publisher_id: str,
    source_version: str,
    source_local_id: str | None = None,
    title: str | None = None,
    publication_mode: str = "canonical-publication",
    source_system: str = "battinfo-records",
    workflow_name: str = "curated-cell-type-publication",
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    record, source_path, inferred_local_id = _curated_cell_type_source(source)
    resolved_source_local_id = source_local_id or inferred_local_id
    if not isinstance(resolved_source_local_id, str) or not resolved_source_local_id.strip():
        raise ValueError("Could not infer source_local_id for curated cell-type source; provide source_local_id explicitly.")

    validation = validate_record(record, policy=validation_policy)
    if not validation.ok:
        raise ValueError(f"curated cell-type validation failed: {'; '.join(validation.errors)}")

    resolved_title = title or _curated_cell_type_title(record)
    generated_at = _now_iso()
    workspace: dict[str, Any] | None = None
    if source_path is not None:
        workspace = {
            "editorial": {
                "record_path": str(source_path),
                "record_id": resolved_source_local_id,
            }
        }

    return {
        "schema_version": "0.1.0",
        "kind": "BattinfoSubmission",
        "submission_mode": "resource",
        "generated_at": generated_at,
        "workspace_id": workspace_id,
        "publisher_id": publisher_id,
        "source_version": source_version,
        "title": resolved_title,
        "publication_intent": {"mode": publication_mode},
        "provenance": {
            "source_system": source_system,
            "workflow_name": workflow_name,
            "generated_at": generated_at,
        },
        "release": {"version": source_version},
        "workspace": workspace,
        "resource": _curated_cell_type_submission_resource(
            record=record,
            source_local_id=resolved_source_local_id,
            title=resolved_title,
        ),
        "artifacts": [],
        "validation": {
            "ok": validation.ok,
            "errors": list(validation.errors),
            "policy": validation.policy,
        },
    }


def submit_publication_package(
    payload: Mapping[str, Any],
    *,
    registry_base_url: str,
    api_key: str,
    api_key_header: str = "X-Battinfo-API-Key",
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    request_url = registry_base_url.rstrip("/") + "/publication-packages"
    request_payload = dict(payload)
    request_body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    request = UrlRequest(
        request_url,
        data=request_body,
        headers={
            "Content-Type": "application/json",
            api_key_header: api_key,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            response_text = response.read().decode("utf-8")
            response_payload = json.loads(response_text) if response_text else None
            return {
                "status": "ok",
                "url": request_url,
                "status_code": response.getcode(),
                "response": response_payload,
            }
    except HTTPError as exc:
        response_text = exc.read().decode("utf-8")
        try:
            detail = json.loads(response_text) if response_text else None
        except json.JSONDecodeError:
            detail = response_text
        raise RuntimeError(f"Registry submission failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Registry submission failed: {exc.reason}") from exc


def publish_curated_cell_type(
    source: dict[str, Any] | PathLike,
    *,
    workspace_id: str,
    publisher_id: str,
    source_version: str,
    registry_base_url: str,
    api_key: str,
    api_key_header: str = "X-Battinfo-API-Key",
    source_local_id: str | None = None,
    title: str | None = None,
    publication_mode: str = "canonical-publication",
    source_system: str = "battinfo-records",
    workflow_name: str = "curated-cell-type-publication",
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    payload = build_curated_cell_type_submission(
        source,
        workspace_id=workspace_id,
        publisher_id=publisher_id,
        source_version=source_version,
        source_local_id=source_local_id,
        title=title,
        publication_mode=publication_mode,
        source_system=source_system,
        workflow_name=workflow_name,
        validation_policy=validation_policy,
    )
    response = submit_publication_package(
        payload,
        registry_base_url=registry_base_url,
        api_key=api_key,
        api_key_header=api_key_header,
        timeout_sec=timeout_sec,
    )
    return {
        "status": response["status"],
        "request": payload,
        "response": response["response"],
        "status_code": response["status_code"],
        "url": response["url"],
    }


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
    if draft.construction:
        specification["construction"] = draft.construction
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
    citation = _citation_url_value(draft.citation)
    if citation is not None:
        provenance["citation"] = citation
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
            "construction": specification.get("construction"),
            "coin_hardware": specification.get("coin_hardware"),
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
        if not _str_fuzzy_match(rec.get("manufacturer"), manufacturer):
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
    cell_types_dir: PathLike = DEFAULT_CELL_TYPES_DIR,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query cell types using practical metadata/property filters."""
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

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
            format_name = product.get("cell_format") or product.get("cellFormat")
            size_code = product.get("size_code") or product.get("sizeCode")
            iec_code = product.get("iec_code") or product.get("iecCode")
            country_of_origin = product.get("country_of_origin") or product.get("countryOfOrigin")
            year = product.get("year")
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
            iec_code = legacy.get("iec_code")
            country_of_origin = legacy.get("country_of_origin")
            year = legacy.get("year")
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
                "iec_code": iec_code,
                "country_of_origin": country_of_origin,
                "year": year,
                "nominal_capacity": _spec_numeric_value(specs, "nominal_capacity"),
                "nominal_voltage": _spec_numeric_value(specs, "nominal_voltage"),
                "specs": specs,
                "source": "cell-type",
                "path": str(path),
            }
        )

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if not _str_fuzzy_match(rec.get("manufacturer"), manufacturer):
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
        dataset_links = doc.get("datasets", [])
        if not isinstance(inst, Mapping):
            continue
        linked_dataset_ids: list[str] = []
        if isinstance(dataset_links, list):
            linked_dataset_ids = [
                item["id"]
                for item in dataset_links
                if isinstance(item, Mapping) and isinstance(item.get("id"), str)
            ]
        elif isinstance(prov, Mapping):
            # Backward compatibility for legacy records that stored dataset links under provenance.
            if isinstance(prov.get("dataset_ids"), list):
                linked_dataset_ids = [item for item in prov["dataset_ids"] if isinstance(item, str)]
            elif isinstance(prov.get("dataset_id"), str):
                linked_dataset_ids = [prov["dataset_id"]]
        rec = {
            "id": inst.get("id"),
            "type_id": inst.get("type_id"),
            "short_id": inst.get("short_id"),
            "serial_number": inst.get("serial_number"),
            "dataset_id": linked_dataset_ids[0] if linked_dataset_ids else None,
            "dataset_ids": linked_dataset_ids,
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
                if isinstance(entry, Mapping) and isinstance(entry.get("encoding_format"), str):
                    dist_format = entry.get("encoding_format")
                    break
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
            "access_url": dataset.get("access_url") or dataset.get("url"),
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
                "protocol_id": test.get("protocol_id"),
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


def query_test_protocols(
    *,
    id: str | None = None,
    kind: str | None = None,
    name_contains: str | None = None,
    source_type: str | None = None,
    directory: PathLike = DEFAULT_TEST_PROTOCOLS_DIR,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query canonical reusable test-protocol metadata records."""
    records: list[dict[str, Any]] = []
    for path in _iter_json_files(_as_path(directory)):
        doc = _load_json(path)
        protocol = doc.get("test_protocol", {})
        prov = doc.get("provenance", {})
        if not isinstance(protocol, Mapping):
            continue
        records.append(
            {
                "id": protocol.get("id"),
                "short_id": protocol.get("short_id"),
                "name": protocol.get("name"),
                "kind": protocol.get("kind"),
                "version": protocol.get("version"),
                "protocol_url": protocol.get("protocol_url"),
                "source_type": prov.get("source_type") if isinstance(prov, Mapping) else None,
                "path": str(path),
                "record": doc,
            }
        )

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if not _str_eq(rec.get("kind"), kind):
            continue
        if not _str_contains(rec.get("name"), name_contains):
            continue
        if not _str_eq(rec.get("source_type"), source_type):
            continue
        filtered.append(rec)

    return _paginate(filtered, limit=limit, offset=offset)


def query(kind: str, /, **filters: Any) -> list[dict[str, Any]]:
    """Query BattINFO resources by explicit kind."""
    normalized = kind.strip().lower().replace("-", "_")

    if normalized in {"cell_type", "cell_types"}:
        return query_cell_types(**filters)
    if normalized in {"cell", "cells", "cell_instance", "cell_instances"}:
        return query_cell_instances(**filters)
    if normalized in {"test_protocol", "test_protocols"}:
        return query_test_protocols(**filters)
    if normalized in {"test", "tests"}:
        return query_tests(**filters)
    if normalized in {"dataset", "datasets"}:
        return query_datasets(**filters)
    if normalized in {"description", "descriptions", "library_cell_type", "library_cell_types"}:
        return query_library_cell_types(**filters)

    raise ValueError(
        "kind must be one of: cell_types, cells, test_protocols, tests, datasets, descriptions."
    )


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
        out["datasets"] = [{"id": dataset_id, "role": "raw"}]

    if validate:
        _validate_schema(out, "cell-instance.schema.json")

    if out_path is not None:
        _write_json(_as_path(out_path), out)
    return out


def _save_entity_path(entity_type: str, uid: str, source_root: Path) -> Path:
    if entity_type == "cell-type":
        return source_root / "cell-type" / f"cell-type-{uid}.json"
    if entity_type == "cell":
        return source_root / "cell-instances" / f"cell-{uid}.json"
    if entity_type == "test-protocol":
        return source_root / "test-protocols" / f"test-protocol-{uid}.json"
    if entity_type == "test":
        return source_root / "tests" / f"test-{uid}.json"
    if entity_type == "dataset":
        return source_root / "dataset" / f"dataset-{uid}.json"
    raise ValueError(f"Unsupported entity type for save path: {entity_type}")


def _iter_entity_files(entity_type: str, source_root: Path) -> list[Path]:
    if entity_type == "cell-type":
        directory = source_root / "cell-type"
    elif entity_type == "cell":
        directory = source_root / "cell-instances"
    elif entity_type == "test-protocol":
        directory = source_root / "test-protocols"
    elif entity_type == "test":
        directory = source_root / "tests"
    elif entity_type == "dataset":
        directory = source_root / "dataset"
    else:
        return []
    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))


def _find_record_path_by_id(entity_id: str, source_root: Path) -> Path | None:
    entity_type, uid = _iri_tail(entity_id)
    expected = _save_entity_path(entity_type, uid, source_root)
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


def _validate_save_mode(mode: str) -> str:
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
    citation = _citation_url_value(draft.citation)
    if citation is not None:
        record["provenance"]["citation"] = citation
    if draft.positive_electrode_basis is not None:
        record["product"]["positiveElectrodeBasis"] = draft.positive_electrode_basis
    if draft.negative_electrode_basis is not None:
        record["product"]["negativeElectrodeBasis"] = draft.negative_electrode_basis
    if draft.size_code is not None:
        record["product"]["sizeCode"] = draft.size_code
    if draft.iec_code is not None:
        record["product"]["iecCode"] = draft.iec_code
    if draft.country_of_origin is not None:
        record["product"]["countryOfOrigin"] = draft.country_of_origin
    if draft.year is not None:
        record["product"]["year"] = draft.year
    if draft.datasheet_revision is not None:
        record["product"]["datasheetRevision"] = draft.datasheet_revision
    if draft.file_hash is not None:
        record["provenance"]["file_hash"] = draft.file_hash
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record_to_snake_aliases(record)


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
    citation = _citation_url_value(draft.citation)
    if citation is not None:
        record["provenance"]["citation"] = citation
    if dataset_ids:
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
        "identifier": draft.identifier if draft.identifier is not None else f"dataset:{dashed_uid}",
        "name": draft.title,
        "url": draft.access_url or draft.source_url or f"https://example.org/dataset/{dashed_uid}",
    }
    if draft.description is not None:
        dataset_obj["description"] = draft.description
    if draft.license is not None:
        dataset_obj["license"] = draft.license
    if draft.same_as:
        dataset_obj["sameAs"] = list(dict.fromkeys(draft.same_as))
    if draft.additional_type:
        dataset_obj["additionalType"] = list(dict.fromkeys(draft.additional_type))
    if draft.version is not None:
        dataset_obj["version"] = draft.version
    if draft.keywords:
        dataset_obj["keywords"] = list(dict.fromkeys(draft.keywords))
    if draft.creator:
        dataset_obj["creator"] = copy.deepcopy(draft.creator)
    if draft.publisher is not None:
        dataset_obj["publisher"] = copy.deepcopy(draft.publisher)
    if draft.funder:
        dataset_obj["funder"] = copy.deepcopy(draft.funder)
    if draft.citation_list:
        dataset_obj["citation"] = copy.deepcopy(draft.citation_list)
    if draft.measurement_techniques:
        dataset_obj["measurementTechnique"] = list(dict.fromkeys(draft.measurement_techniques))
    if draft.measurement_methods:
        dataset_obj["measurementMethod"] = list(dict.fromkeys(draft.measurement_methods))
    if draft.variable_measured:
        dataset_obj["variableMeasured"] = copy.deepcopy(draft.variable_measured)
    if draft.is_accessible_for_free is not None:
        dataset_obj["isAccessibleForFree"] = draft.is_accessible_for_free
    if draft.conditions_of_access is not None:
        dataset_obj["conditionsOfAccess"] = draft.conditions_of_access
    if draft.in_language is not None:
        dataset_obj["inLanguage"] = draft.in_language
    if about_refs:
        dataset_obj["about"] = about_refs
    created_unix = _to_unix_time(draft.created_at) or _now_unix()
    modified_unix = _to_unix_time(draft.modified_at) or created_unix
    published_unix = _to_unix_time(draft.published_at) or created_unix
    dataset_obj["dateCreated"] = created_unix
    dataset_obj["dateModified"] = modified_unix
    dataset_obj["datePublished"] = published_unix
    if draft.temporal_coverage is not None:
        dataset_obj["temporalCoverage"] = draft.temporal_coverage
    if draft.spatial_coverage is not None:
        dataset_obj["spatialCoverage"] = draft.spatial_coverage
    if draft.is_based_on:
        dataset_obj["isBasedOn"] = list(dict.fromkeys(draft.is_based_on))
    if draft.included_in_data_catalog is not None:
        dataset_obj["includedInDataCatalog"] = draft.included_in_data_catalog
    if draft.main_entity:
        dataset_obj["mainEntity"] = copy.deepcopy(draft.main_entity)

    if draft.distribution:
        dataset_obj["distribution"] = copy.deepcopy(draft.distribution)
    elif draft.download_url is not None or draft.format is not None or (draft.checksum_algorithm and draft.checksum_value):
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
    citation = _citation_url_value(draft.citation)
    if citation is not None:
        record["provenance"]["citation"] = citation
    if draft.curated_by is not None:
        record["provenance"]["curated_by"] = draft.curated_by
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record_to_snake_aliases(record)


def _record_from_test(draft: TestInput) -> dict[str, Any]:
    if not CELL_IRI_RE.fullmatch(draft.cell_id):
        raise ValueError("cell_id must match https://w3id.org/battinfo/cell/{uid}.")
    if draft.protocol_id is not None and not TEST_PROTOCOL_IRI_RE.fullmatch(draft.protocol_id):
        raise ValueError("protocol_id must match https://w3id.org/battinfo/test-protocol/{uid}.")
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
    if draft.protocol_id is not None:
        record["test"]["protocol_id"] = draft.protocol_id
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
    citation = _citation_url_value(draft.citation)
    if citation is not None:
        record["provenance"]["citation"] = citation
    if draft.source_file is not None:
        record["provenance"]["source_file"] = draft.source_file
    if draft.workflow_version is not None:
        record["provenance"]["workflow_version"] = draft.workflow_version
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record_to_snake_aliases(record)


def _record_from_test_protocol(draft: TestProtocolInput) -> dict[str, Any]:
    if draft.id is not None:
        if not TEST_PROTOCOL_IRI_RE.fullmatch(draft.id):
            raise ValueError("test-protocol id must match https://w3id.org/battinfo/test-protocol/{uid}.")
        if draft.uid is not None:
            dashed = _normalized_dashed_uid(draft.uid)
            _assert_id_matches_uid(draft.id, dashed)
        entity_id = draft.id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(draft.uid)
        entity_id = f"https://w3id.org/battinfo/test-protocol/{dashed_uid}"

    record: dict[str, Any] = {
        "schema_version": draft.schema_version,
        "test_protocol": {
            "id": entity_id,
            "short_id": dashed_uid.replace("-", "")[:6],
            "identifier": f"test-protocol:{dashed_uid}",
            "name": draft.name,
            "kind": draft.kind,
        },
        "provenance": {
            "source_type": draft.source_type,
            "retrieved_at": _to_unix_time(draft.retrieved_at) or _now_unix(),
        },
    }
    if draft.description is not None:
        record["test_protocol"]["description"] = draft.description
    if draft.version is not None:
        record["test_protocol"]["version"] = draft.version
    if draft.protocol_url is not None:
        record["test_protocol"]["protocol_url"] = draft.protocol_url
    if draft.conditions:
        record["conditions"] = copy.deepcopy(draft.conditions)
    if draft.setpoints:
        record["setpoints"] = copy.deepcopy(draft.setpoints)
    if draft.termination_criteria:
        record["termination_criteria"] = copy.deepcopy(draft.termination_criteria)
    if draft.measurement_outputs:
        record["measurement_outputs"] = copy.deepcopy(draft.measurement_outputs)
    if draft.source_url is not None:
        record["provenance"]["source_url"] = draft.source_url
    citation = _citation_url_value(draft.citation)
    if citation is not None:
        record["provenance"]["citation"] = citation
    if draft.source_file is not None:
        record["provenance"]["source_file"] = draft.source_file
    if draft.workflow_version is not None:
        record["provenance"]["workflow_version"] = draft.workflow_version
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record_to_snake_aliases(record)


def _resolve_references_for_save(doc: dict[str, Any], source_root: Path) -> None:
    report = validate_references_report(doc, source_root, allow_missing=True)
    if report.ok:
        return
    raise ValueError(report.errors[0].message)


def save_record(
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
    """Save one canonical BattINFO resource into local source storage and optional resolver artifacts."""
    mode_normalized = _validate_save_mode(mode)
    duplicate_policy_normalized = _validate_duplicate_policy(duplicate_policy)
    source_root_path = _as_path(source_root)

    doc = _load_json(_as_path(record)) if isinstance(record, (str, Path)) else record
    if validate:
        _validate_canonical_record(doc, policy=validation_policy)

    entity_id = _entity_id(doc)
    entity_type, uid = _iri_tail(entity_id)
    existing_path = _find_record_path_by_id(entity_id, source_root_path)
    target_path = existing_path if existing_path is not None else _save_entity_path(entity_type, uid, source_root_path)

    if resolve_references:
        _resolve_references_for_save(doc, source_root_path)

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


def save_cell_type(
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
    """Save a cell-type from either draft payload or canonical record."""
    from battinfo.bundle import CellType as CellTypeBundle

    if isinstance(draft, (str, Path)):
        loaded = _load_json(_as_path(draft))
        return save_cell_type(
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
        return save_record(
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
        return save_record(
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
    return save_record(
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


def save_cell_instance(
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
    """Save a cell-instance from either draft payload or canonical record."""
    from battinfo.bundle import CellInstance as CellInstanceBundle

    if isinstance(draft, (str, Path)):
        loaded = _load_json(_as_path(draft))
        return save_cell_instance(
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
        return save_record(
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
        return save_record(
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
    return save_record(
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


def save_dataset(
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
    """Save a dataset from either draft payload or canonical record."""
    from battinfo.bundle import Dataset as DatasetBundle

    if isinstance(draft, (str, Path)):
        loaded = _load_json(_as_path(draft))
        return save_dataset(
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
        return save_record(
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
        return save_record(
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
    return save_record(
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


def save_test(
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
    """Save a test from either draft payload or canonical record."""
    from battinfo.bundle import Test as TestBundle

    if isinstance(draft, (str, Path)):
        loaded = _load_json(_as_path(draft))
        return save_test(
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
        return save_record(
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
        return save_record(
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
    return save_record(
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


def save_test_protocol(
    draft: TestProtocolInput | dict[str, Any] | PathLike,
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
    """Save a test protocol from either draft payload or canonical record."""
    from battinfo.bundle import TestProtocol as TestProtocolBundle

    if isinstance(draft, (str, Path)):
        loaded = _load_json(_as_path(draft))
        return save_test_protocol(
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
    if isinstance(draft, TestProtocolBundle):
        return save_record(
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
    if isinstance(draft, Mapping) and isinstance(draft.get("test_protocol"), Mapping):
        return save_record(
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
    draft_model = draft if isinstance(draft, TestProtocolInput) else TestProtocolInput.model_validate(draft)
    record = _record_from_test_protocol(draft_model)
    return save_record(
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


def save_library_cell_type(
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
    """Save a reusable cell specification into the curated library."""
    from battinfo.bundle import CellSpecification as CellSpecificationBundle

    if isinstance(draft, (str, Path)):
        loaded = _load_json(_as_path(draft))
        return save_library_cell_type(
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

    mode_normalized = _validate_save_mode(mode)
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


def save_batch(
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
    """Save a deterministic batch of canonical resources."""
    mode_normalized = _validate_save_mode(mode)
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
                payload = save_record(
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

    if resolve_references and validate and not dry_run:
        link_report = build_index(
            source_root=source_root,
            validate=True,
            validation_policy=validation_policy,
        )
        for failure in link_report["failures"]:
            failures.append(
                {
                    "file": str(failure["file"]),
                    "error": str(failure["error"]),
                }
            )

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
    if isinstance(doc.get("test_protocol"), Mapping) and isinstance(doc["test_protocol"].get("id"), str):
        return doc["test_protocol"]["id"]
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
    if isinstance(doc.get("test_protocol"), Mapping):
        return "test-protocol.schema.json"
    if isinstance(doc.get("test"), Mapping):
        return "test.schema.json"
    if isinstance(doc.get("dataset"), Mapping):
        return "dataset.schema.json"
    raise ValueError("Unsupported record type: expected product/cell_type, cell_instance, test_protocol, test, or dataset.")


def _iri_tail(iri: str) -> tuple[str, str]:
    parts = iri.rstrip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"Invalid IRI: {iri}")
    return parts[-2], parts[-1]


def _schema_identifier_value(value: Any, fallback: str) -> Any:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        property_id = value.get("property_id")
        property_value = value.get("value")
        if isinstance(property_id, str) and isinstance(property_value, str):
            return {
                "@type": "schema:PropertyValue",
                "schema:propertyID": property_id,
                "schema:value": property_value,
            }
    return fallback


def _schema_agent_value(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    agent_type = value.get("type")
    if not isinstance(agent_type, str) or agent_type not in {"Person", "Organization"}:
        agent_type = "Organization"
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    out: dict[str, Any] = {"@type": f"schema:{agent_type}", "schema:name": name}
    if isinstance(value.get("url"), str):
        out["schema:url"] = value["url"]
    if isinstance(value.get("email"), str):
        out["schema:email"] = value["email"]
    if isinstance(value.get("given_name"), str):
        out["schema:givenName"] = value["given_name"]
    if isinstance(value.get("family_name"), str):
        out["schema:familyName"] = value["family_name"]
    if isinstance(value.get("sameAs"), str):
        out["schema:sameAs"] = value["sameAs"]
    if isinstance(value.get("affiliation"), Mapping):
        nested = _schema_agent_value(value["affiliation"])
        if nested is not None:
            out["schema:affiliation"] = nested
    return out


def _schema_data_catalog_value(value: Any) -> Any:
    if isinstance(value, str):
        return {"@id": value} if "://" in value else value
    if not isinstance(value, Mapping):
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    out: dict[str, Any] = {"@type": "schema:DataCatalog", "schema:name": name}
    if isinstance(value.get("id"), str):
        out["@id"] = value["id"]
    if isinstance(value.get("url"), str):
        out["schema:url"] = value["url"]
    if isinstance(value.get("sameAs"), str):
        out["schema:sameAs"] = value["sameAs"]
    if isinstance(value.get("description"), str):
        out["schema:description"] = value["description"]
    return out


def _schema_citation_value(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return None
    out: dict[str, Any] = {"@type": "schema:CreativeWork"}
    if isinstance(value.get("url"), str):
        out["@id"] = value["url"]
        out["schema:url"] = value["url"]
    if isinstance(value.get("name"), str):
        out["schema:name"] = value["name"]
    if isinstance(value.get("kind"), str):
        out["schema:additionalType"] = value["kind"]
    if isinstance(value.get("doi"), str):
        out["battinfo:doi"] = value["doi"]
    if isinstance(value.get("citation_key"), str):
        out["schema:identifier"] = value["citation_key"]
    return out if len(out) > 1 else None


def _schema_variable_measured_value(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    out: dict[str, Any] = {"@type": "schema:PropertyValue", "schema:name": name}
    if isinstance(value.get("description"), str):
        out["schema:description"] = value["description"]
    if isinstance(value.get("unit_text"), str):
        out["schema:unitText"] = value["unit_text"]
    same_as = value.get("sameAs")
    if isinstance(same_as, str):
        out["schema:sameAs"] = same_as
        out["schema:propertyID"] = same_as
    return out


def _schema_distribution_value(value: Any, *, part_of_id: str) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    content_url = value.get("contentUrl")
    encoding_format = value.get("encodingFormat")
    checksum = value.get("checksum")
    if (
        not isinstance(content_url, str)
        and not isinstance(encoding_format, str)
        and not isinstance(checksum, Mapping)
    ):
        return None
    if not (
        isinstance(checksum, Mapping)
        and isinstance(checksum.get("algorithm"), str)
        and checksum["algorithm"].lower() == "sha256"
        and isinstance(checksum.get("value"), str)
    ):
        return None
    out: dict[str, Any] = {"@type": "schema:DataDownload"}
    if isinstance(value.get("name"), str):
        out["schema:name"] = value["name"]
    if isinstance(value.get("description"), str):
        out["schema:description"] = value["description"]
    if isinstance(content_url, str):
        out["schema:contentUrl"] = content_url
    if isinstance(encoding_format, str):
        out["schema:encodingFormat"] = encoding_format
    if isinstance(value.get("contentSize"), str):
        out["schema:contentSize"] = value["contentSize"]
    if isinstance(value.get("accessLevel"), str):
        out["schema:accessLevel"] = value["accessLevel"]
    out["schema:isPartOf"] = {"@id": part_of_id}
    out["schema:sha256"] = checksum["value"]
    return out


def _schema_table_column_value(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    out: dict[str, Any] = {
        "@type": "csvw:Column",
        "csvw:name": name,
    }
    titles = value.get("titles")
    if isinstance(titles, str):
        out["csvw:titles"] = titles
    elif isinstance(titles, list):
        title_values = [item for item in titles if isinstance(item, str)]
        if title_values:
            out["csvw:titles"] = title_values
    if isinstance(value.get("description"), str):
        out["schema:description"] = value["description"]
    if isinstance(value.get("datatype"), str):
        out["csvw:datatype"] = value["datatype"]
    if isinstance(value.get("unit_text"), str):
        out["schema:unitText"] = value["unit_text"]
    same_as = value.get("sameAs")
    if isinstance(same_as, str):
        out["schema:sameAs"] = same_as
        out["schema:propertyID"] = same_as
    required = value.get("required")
    if isinstance(required, bool):
        out["csvw:required"] = required
    return out


def _schema_table_schema_value(value: Any) -> dict[str, Any] | str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return None
    columns = value.get("columns")
    if not isinstance(columns, list):
        return None
    column_nodes = [column for item in columns if (column := _schema_table_column_value(item)) is not None]
    if not column_nodes:
        return None
    out: dict[str, Any] = {
        "@type": "csvw:Schema",
        "csvw:column": column_nodes,
    }
    if isinstance(value.get("id"), str):
        out["@id"] = value["id"]
    if isinstance(value.get("name"), str):
        out["schema:name"] = value["name"]
    if isinstance(value.get("description"), str):
        out["schema:description"] = value["description"]
    primary_key = value.get("primaryKey")
    if isinstance(primary_key, str):
        out["csvw:primaryKey"] = primary_key
    elif isinstance(primary_key, list):
        values = [item for item in primary_key if isinstance(item, str)]
        if values:
            out["csvw:primaryKey"] = values
    return out


def _schema_main_entity_value(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    node_type = value.get("type")
    if isinstance(node_type, str) and ":" in node_type:
        node_type = node_type.split(":", 1)[1]
    if node_type == "Table":
        url = value.get("url")
        table_schema = value.get("tableSchema")
        resolved_table_schema = _schema_table_schema_value(table_schema)
        if not isinstance(url, str) or resolved_table_schema is None:
            return None
        out: dict[str, Any] = {
            "@type": "csvw:Table",
            "csvw:url": url,
            "csvw:tableSchema": resolved_table_schema,
        }
        if isinstance(value.get("id"), str):
            out["@id"] = value["id"]
        if isinstance(value.get("name"), str):
            out["schema:name"] = value["name"]
        if isinstance(value.get("description"), str):
            out["schema:description"] = value["description"]
        return out
    if node_type == "TableGroup":
        table_items = value.get("table")
        if not isinstance(table_items, list):
            return None
        tables = [table for item in table_items if (table := _schema_main_entity_value(item)) is not None]
        if not tables:
            return None
        out = {
            "@type": "csvw:TableGroup",
            "csvw:table": tables,
        }
        if isinstance(value.get("id"), str):
            out["@id"] = value["id"]
        if isinstance(value.get("url"), str):
            out["csvw:url"] = value["url"]
        if isinstance(value.get("name"), str):
            out["schema:name"] = value["name"]
        if isinstance(value.get("description"), str):
            out["schema:description"] = value["description"]
        return out
    return None




_PYBAMM_STEP_EMMO_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^\s*(discharge|rest|charge|hold)\s+at\s+\S+\s+[acwv]", re.I), ""),  # router
    (re.compile(r"^\s*discharge\s+at\s+\S+\s+[cw]", re.I), "ConstantCurrentDischarging"),
    (re.compile(r"^\s*discharge\s+at\s+\S+\s+a\b", re.I), "ConstantCurrentDischarging"),
    (re.compile(r"^\s*charge\s+at\s+\S+\s+[caw]\s+until\s+\S+\s+[va]\b", re.I), "ConstantCurrentConstantVoltageCharging"),
    (re.compile(r"^\s*charge\s+at\s+\S+\s+[cw]", re.I), "ConstantCurrentCharging"),
    (re.compile(r"^\s*charge\s+at\s+\S+\s+a\b", re.I), "ConstantCurrentCharging"),
    (re.compile(r"^\s*hold\s+at\s+\S+\s+v\b", re.I), "ConstantVoltageCharging"),
    (re.compile(r"^\s*rest\b", re.I), "Resting"),
]


def _pybamm_step_emmo_type(step_text: str) -> str | None:
    """Return the EMMO electrochemistry process class for a PyBaMM step string, or None."""
    t = step_text.strip().lower()
    if t.startswith("rest"):
        return "Resting"
    if t.startswith("hold at") and " v" in t:
        return "ConstantVoltageCharging"
    if t.startswith("discharge"):
        return "ConstantCurrentDischarging"
    if t.startswith("charge"):
        # CC-CV if the step has a current condition AND a voltage cut-off
        if re.search(r"until\s+\S+\s*v\b", t):
            return "ConstantCurrentConstantVoltageCharging"
        return "ConstantCurrentCharging"
    return None


_INSTRUMENT_EMMO_MAP: dict[str, str] = {
    # Battery cyclers (galvanostatic instruments)
    "maccor": "BatteryCycler",
    "arbin": "BatteryCycler",
    "neware": "BatteryCycler",
    "landt": "BatteryCycler",
    "basytec": "BatteryCycler",
    "novonix": "BatteryCycler",
    "digatron": "BatteryCycler",
    # Biologic can be either, but VMP/MPG/SP lines are potentiostats/galvanostats
    "biologic": "Potentiostat",
    "vmp": "Potentiostat",
    "mpg": "Potentiostat",
    "sp-": "Potentiostat",
    "hcp": "Potentiostat",
    # Dedicated potentiostats / galvanostats
    "gamry": "Potentiostat",
    "autolab": "Potentiostat",
    "zahner": "Potentiostat",
    "ivium": "Potentiostat",
    "metrohm": "Potentiostat",
    "solartron": "Potentiostat",
    "galvanostat": "Galvanostat",
    "potentiostat": "Potentiostat",
    "cycler": "BatteryCycler",
}


def _instrument_emmo_type(name: str) -> str:
    """Return the EMMO equipment class for a test instrument name string."""
    lower = (name or "").lower()
    for keyword, emmo_class in _INSTRUMENT_EMMO_MAP.items():
        if keyword in lower:
            return emmo_class
    return "MeasuringInstrument"


def _instrument_node(name: str) -> dict[str, Any]:
    """Build an equipment node with EMMO type + schema.org name."""
    return {"@type": _instrument_emmo_type(name), "schema:name": name}


def _pybamm_step_to_jsonld(step_text: str, position: int) -> dict[str, Any]:
    """Convert a single PyBaMM experiment step string to a schema:HowToStep node.

    The step text is stored verbatim so it can be fed directly back into
    pybamm.Experiment(steps).  The EMMO type is added when it can be
    determined unambiguously from the step text.
    """
    emmo_type = _pybamm_step_emmo_type(step_text)
    node_type: str | list[str] = (
        ["schema:HowToStep", emmo_type] if emmo_type else "schema:HowToStep"
    )
    return {
        "@type": node_type,
        "schema:position": position,
        "schema:text": step_text,
    }


def _resolver_jsonld(doc: dict[str, Any]) -> dict[str, Any]:
    entity_iri = _entity_id(doc)
    entity_type, uid = _iri_tail(entity_iri)
    # csvw: is used by _schema_main_entity_value helpers called from the dataset block.
    context = [
        "https://w3id.org/emmo/domain/battery/context",
        {
            "schema": "https://schema.org/",
            "csvw": "http://www.w3.org/ns/csvw#",
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
            "@type": ["BatteryCellSpecification", "schema:CreativeWork"],
            "schema:identifier": uid,
            "schema:name": cell.get("name") or cell.get("model") or cell.get("model_name"),
            "schema:manufacturer": {"@type": "schema:Organization", "schema:name": manufacturer_name},
        }
        product_type = cell.get("productType") or cell.get("product_type")
        if product_type:
            out["schema:additionalType"] = str(product_type)
        size_code = cell.get("sizeCode") or cell.get("size_code")
        if size_code:
            out["schema:size"] = size_code
        # Quantitative specifications as EMMO ConventionalProperty nodes.
        # Chemistry and format are already expressed through @type stacking.
        specs = doc.get("specs") or {}
        if isinstance(specs, Mapping):
            prop_nodes = [
                node
                for key, value in specs.items()
                if isinstance(value, Mapping)
                if (node := _jsonld_quantity_node(key, value)) is not None
            ]
            if prop_nodes:
                out["hasProperty"] = prop_nodes
        return out

    if entity_type == "cell":
        inst = doc["cell_instance"]
        out = {
            "@context": context,
            "@id": entity_iri,
            "@type": ["BatteryCell", "schema:IndividualProduct"],
            "schema:identifier": uid,
            "hasDescription": {"@id": inst.get("type_id")},
            "schema:isVariantOf": {"@id": inst.get("type_id")},
        }
        if inst.get("serial_number"):
            out["schema:serialNumber"] = inst.get("serial_number")
        datasets: list[dict[str, str]] = []
        for dataset in doc.get("datasets", []):
            if isinstance(dataset, Mapping) and isinstance(dataset.get("id"), str):
                datasets.append({"@id": dataset["id"]})
        if datasets:
            out["schema:workExample"] = datasets
        return out

    if entity_type == "test-protocol":
        protocol = doc["test_protocol"]
        out = {
            "@context": context,
            "@id": entity_iri,
            "@type": ["ElectrochemicalTestingProcedure", "schema:HowTo"],
            "schema:identifier": uid,
            "schema:name": protocol.get("name"),
        }
        if protocol.get("description"):
            out["schema:description"] = protocol.get("description")
        if protocol.get("protocol_url"):
            out["schema:url"] = protocol.get("protocol_url")
        if protocol.get("version"):
            out["schema:version"] = protocol.get("version")
        steps = protocol.get("steps")
        if isinstance(steps, list) and steps:
            step_nodes = [
                _pybamm_step_to_jsonld(step_text, position=i + 1)
                for i, step_text in enumerate(steps)
            ]
            out["schema:step"] = step_nodes
        cycles = protocol.get("cycles")
        if isinstance(cycles, int) and cycles > 1:
            out["schema:repeatCount"] = cycles
        return out

    if entity_type == "test":
        test = doc["test"]
        cell_ref = {"@id": test.get("cell_id")}
        out = {
            "@context": context,
            "@id": entity_iri,
            "@type": ["BatteryTest", "schema:Action"],
            "schema:identifier": uid,
            "schema:name": test.get("name"),
            # EMMO-native: the battery cell is an input to the test
            "hasTestObject": cell_ref,
            # schema.org alignment
            "schema:object": cell_ref,
        }
        if test.get("description"):
            out["schema:description"] = test.get("description")
        if test.get("status"):
            out["schema:actionStatus"] = test.get("status")
        if isinstance(test.get("protocol_id"), str):
            protocol_ref = {"@id": test["protocol_id"]}
            out["schema:instrument"] = protocol_ref
        instrument_name = test.get("instrument_name")
        if isinstance(instrument_name, str) and instrument_name:
            equip_node = _instrument_node(instrument_name)
            out["hasTestEquipment"] = equip_node
            out["schema:instrument"] = [out.get("schema:instrument"), equip_node] if "schema:instrument" in out else equip_node
        datasets = test.get("dataset_ids")
        if isinstance(datasets, list):
            refs = [{"@id": did} for did in datasets if isinstance(did, str)]
            if refs:
                result = refs[0] if len(refs) == 1 else refs
                out["hasOutput"] = result
                out["schema:result"] = result
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
            "schema:identifier": _schema_identifier_value(dataset.get("identifier"), uid),
            "schema:name": dataset.get("name") or dataset.get("title"),
            "schema:description": dataset.get("description"),
            "schema:license": dataset.get("license"),
            "schema:encodingFormat": encoding_format or dataset.get("format"),
        }
        if dataset.get("url") or dataset.get("access_url"):
            out["schema:url"] = dataset.get("url") or dataset.get("access_url")
        if isinstance(dataset.get("sameAs"), list):
            same_as = [item for item in dataset["sameAs"] if isinstance(item, str)]
            if same_as:
                out["schema:sameAs"] = same_as
        if isinstance(dataset.get("additionalType"), list):
            additional_type = [item for item in dataset["additionalType"] if isinstance(item, str)]
            if additional_type:
                out["schema:additionalType"] = additional_type
        if isinstance(dataset.get("version"), str):
            out["schema:version"] = dataset["version"]
        if isinstance(dataset.get("keywords"), list):
            keywords = [item for item in dataset["keywords"] if isinstance(item, str)]
            if keywords:
                out["schema:keywords"] = keywords
        creator_value = dataset.get("creator")
        if isinstance(creator_value, list):
            creators = [node for item in creator_value if (node := _schema_agent_value(item)) is not None]
            if creators:
                out["schema:creator"] = creators
        elif isinstance(creator_value, Mapping):
            creator = _schema_agent_value(creator_value)
            if creator is not None:
                out["schema:creator"] = creator
        publisher = _schema_agent_value(dataset.get("publisher"))
        if publisher is not None:
            out["schema:publisher"] = publisher
        funder_value = dataset.get("funder")
        if isinstance(funder_value, list):
            funders = [node for item in funder_value if (node := _schema_agent_value(item)) is not None]
            if funders:
                out["schema:funder"] = funders
        elif isinstance(funder_value, Mapping):
            funder = _schema_agent_value(funder_value)
            if funder is not None:
                out["schema:funder"] = funder
        citation_value = dataset.get("citation")
        if isinstance(citation_value, list):
            citations = [node for item in citation_value if (node := _schema_citation_value(item)) is not None]
            if citations:
                out["schema:citation"] = citations
        else:
            citation = _schema_citation_value(citation_value)
            if citation is not None:
                out["schema:citation"] = citation
        if isinstance(dataset.get("measurementTechnique"), list):
            values = [item for item in dataset["measurementTechnique"] if isinstance(item, str)]
            if values:
                out["schema:measurementTechnique"] = values
        if isinstance(dataset.get("measurementMethod"), list):
            values = [item for item in dataset["measurementMethod"] if isinstance(item, str)]
            if values:
                out["schema:measurementMethod"] = values
        if isinstance(dataset.get("variableMeasured"), list):
            values = [node for item in dataset["variableMeasured"] if (node := _schema_variable_measured_value(item)) is not None]
            if values:
                out["schema:variableMeasured"] = values
        if isinstance(dataset.get("isAccessibleForFree"), bool):
            out["schema:isAccessibleForFree"] = dataset["isAccessibleForFree"]
        if isinstance(dataset.get("conditionsOfAccess"), str):
            out["schema:conditionsOfAccess"] = dataset["conditionsOfAccess"]
        if isinstance(dataset.get("inLanguage"), str):
            out["schema:inLanguage"] = dataset["inLanguage"]
        if dataset.get("dateCreated") is not None:
            out["schema:dateCreated"] = dataset["dateCreated"]
        if dataset.get("dateModified") is not None:
            out["schema:dateModified"] = dataset["dateModified"]
        if dataset.get("datePublished") is not None:
            out["schema:datePublished"] = dataset["datePublished"]
        if isinstance(dataset.get("temporalCoverage"), str):
            out["schema:temporalCoverage"] = dataset["temporalCoverage"]
        if isinstance(dataset.get("spatialCoverage"), str):
            out["schema:spatialCoverage"] = dataset["spatialCoverage"]
        if isinstance(dataset.get("isBasedOn"), list):
            refs = [{"@id": item} for item in dataset["isBasedOn"] if isinstance(item, str)]
            if refs:
                out["schema:isBasedOn"] = refs
        included_in_data_catalog = dataset.get("includedInDataCatalog")
        included_in_data_catalog_value = _schema_data_catalog_value(included_in_data_catalog)
        if included_in_data_catalog_value is not None:
            out["schema:includedInDataCatalog"] = included_in_data_catalog_value
        if isinstance(distribution, list):
            values = [
                node
                for item in distribution
                if (node := _schema_distribution_value(item, part_of_id=entity_iri)) is not None
            ]
            if values:
                out["schema:distribution"] = values
        main_entity = dataset.get("mainEntity")
        if isinstance(main_entity, list):
            values = [node for item in main_entity if (node := _schema_main_entity_value(item)) is not None]
            if values:
                out["schema:mainEntity"] = values
        elif isinstance(main_entity, Mapping):
            value = _schema_main_entity_value(main_entity)
            if value is not None:
                out["schema:mainEntity"] = value
        about = dataset.get("about")
        if isinstance(about, list):
            about_nodes = [{"@id": item} for item in about if isinstance(item, str) and (CELL_IRI_RE.fullmatch(item) or TEST_IRI_RE.fullmatch(item))]
            if about_nodes:
                out["schema:about"] = about_nodes
        else:
            related = dataset.get("related_entities", {})
            if isinstance(related, Mapping):
                cells = related.get("cell_ids")
                if isinstance(cells, list):
                    cell_nodes = [{"@id": cell_id} for cell_id in cells if isinstance(cell_id, str)]
                    if cell_nodes:
                        out["schema:about"] = cell_nodes
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
    test_protocols: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    datasets: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    cell_types_dir = src_root / "cell-type"
    cell_instances_dir = src_root / "cell-instances"
    test_protocols_dir = src_root / "test-protocols"
    tests_dir = src_root / "tests"
    datasets_dir = src_root / "dataset"

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
            dataset_links = doc.get("datasets", [])
            if not isinstance(inst, Mapping) or not isinstance(inst.get("id"), str):
                raise ValueError("missing cell_instance.id")
            linked_dataset_ids: list[str] = []
            if isinstance(dataset_links, list):
                linked_dataset_ids = [
                    item["id"]
                    for item in dataset_links
                    if isinstance(item, Mapping) and isinstance(item.get("id"), str)
                ]
            elif isinstance(prov, Mapping):
                if isinstance(prov.get("dataset_ids"), list):
                    linked_dataset_ids = [item for item in prov["dataset_ids"] if isinstance(item, str)]
                elif isinstance(prov.get("dataset_id"), str):
                    linked_dataset_ids = [prov["dataset_id"]]
            cell_instances.append(
                {
                    "id": inst["id"],
                    "type_id": inst.get("type_id"),
                    "short_id": inst.get("short_id") or _short_id_from_iri(inst["id"]),
                    "dataset_id": linked_dataset_ids[0] if linked_dataset_ids else None,
                    "source_type": prov.get("source_type") if isinstance(prov, Mapping) else None,
                    "path": _relative_or_absolute(path, src_root),
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({"file": _relative_or_absolute(path, src_root), "error": str(exc)})

    for path in sorted(test_protocols_dir.glob(glob)) if test_protocols_dir.exists() else []:
        try:
            doc = _load_json(path)
            if validate:
                _validate_canonical_record(doc, source_root=src_root, policy=validation_policy)
            protocol = doc.get("test_protocol", {})
            prov = doc.get("provenance", {})
            if not isinstance(protocol, Mapping) or not isinstance(protocol.get("id"), str):
                raise ValueError("missing test_protocol.id")
            test_protocols.append(
                {
                    "id": protocol["id"],
                    "short_id": protocol.get("short_id") or _short_id_from_iri(protocol["id"]),
                    "name": protocol.get("name"),
                    "kind": protocol.get("kind"),
                    "version": protocol.get("version"),
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
                    "protocol_id": test.get("protocol_id"),
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
        "test_protocol_count": len(test_protocols),
        "test_count": len(tests),
        "dataset_count": len(datasets),
        "total_count": len(cell_types) + len(cell_instances) + len(test_protocols) + len(tests) + len(datasets),
        "failed": len(failures),
        "failures": failures,
        "cell_types": cell_types,
        "cell_instances": cell_instances,
        "test_protocols": test_protocols,
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
    test_protocol_count = (
        int(doc["test_protocol_count"])
        if isinstance(doc.get("test_protocol_count"), int)
        else len(doc.get("test_protocols", [])) if isinstance(doc.get("test_protocols"), list) else 0
    )
    dataset_count = (
        int(doc["dataset_count"])
        if isinstance(doc.get("dataset_count"), int)
        else len(doc.get("datasets", [])) if isinstance(doc.get("datasets"), list) else 0
    )
    total_count = (
        int(doc["total_count"])
        if isinstance(doc.get("total_count"), int)
        else cell_type_count + cell_instance_count + test_protocol_count + test_count + dataset_count
    )
    failed = int(doc["failed"]) if isinstance(doc.get("failed"), int) else 0

    out = {
        "build_timestamp": doc.get("build_timestamp"),
        "cell_type_count": cell_type_count,
        "cell_instance_count": cell_instance_count,
        "test_protocol_count": test_protocol_count,
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
    "TestProtocolInput",
    "TestInput",
    "build_cell_type_library_rdf",
    "build_index",
    "build_curated_cell_type_submission",
    "create_cell_instance",
    "index_stats",
    "publish_curated_cell_type",
    "publish_batch",
    "publish_record",
    "promote_staging_cell_type",
    "promote_staging_cell_types",
    "query",
    "query_cell_instances",
    "query_library_cell_types",
    "query_cell_types",
    "query_datasets",
    "query_test_protocols",
    "query_tests",
    "save_batch",
    "save_cell_instance",
    "save_cell_type",
    "save_dataset",
    "save_library_cell_type",
    "save_test_protocol",
    "resolve_cell_type_id",
    "save_record",
    "save_test",
    "template_cell_specification",
    "template_cell_instance",
    "template_cell_type_draft",
    "template_cell_type",
    "template_dataset",
    "template_test_protocol_draft",
    "template_test_protocol",
    "template_test",
    "submit_publication_package",
    "validate_staging_cell_type",
    "validate_staging_cell_types",
]

