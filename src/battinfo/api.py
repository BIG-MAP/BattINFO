from __future__ import annotations

import copy
import difflib
import functools
import html
import json
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from battinfo._jsonio import read_record_json as _load_json
from battinfo._jsonio import write_json as _write_json
from battinfo.bundle import BatteryTestType, CellProductType, CellSpecification
from battinfo.canonical_aliases import record_to_snake_aliases
from battinfo.entities import (
    COMPONENT_FAMILIES,
    ENTITY_KINDS,
    entity_id_from_doc,
    entity_types_for_namespace,
    iter_entity_files,
    kind_for_doc,
    save_entity_path,
)
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

SPEC_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/spec/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)
CELL_SPEC_IRI_RE = SPEC_IRI_RE
TEST_PROTOCOL_IRI_RE = SPEC_IRI_RE
CELL_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/cell/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)
DATASET_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/dataset/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)
TEST_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/test/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)
MATERIAL_SPEC_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/material-spec/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)
MATERIAL_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/material/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)

PACKAGE_ROOT = Path(__file__).resolve().parent
EXAMPLES_ROOT = PACKAGE_ROOT / "data" / "examples"
SCHEMAS_ROOT = PACKAGE_ROOT / "data" / "schemas"

DEFAULT_CELL_TYPES_DIR = EXAMPLES_ROOT / "cell-spec"
DEFAULT_CELL_INSTANCES_DIR = EXAMPLES_ROOT / "cell-instance"
DEFAULT_TEST_PROTOCOLS_DIR = EXAMPLES_ROOT / "test-protocol"
DEFAULT_TESTS_DIR = EXAMPLES_ROOT / "test"
DEFAULT_DATASETS_DIR = EXAMPLES_ROOT / "dataset"
DEFAULT_MATERIAL_SPECS_DIR = EXAMPLES_ROOT / "material-spec"
DEFAULT_MATERIALS_DIR = EXAMPLES_ROOT / "material"
DEFAULT_LIBRARY_CELL_TYPES_DIR = Path(".battinfo") / "library" / "cell-spec"
DEFAULT_LIBRARY_RDF_CELL_TYPES_DIR = Path(".battinfo") / "library-rdf" / "cell-spec"
DEFAULT_LIBRARY_AGGREGATE_JSONLD = Path(".battinfo") / "library" / "cell-spec.jsonld"
DEFAULT_LIBRARY_MANIFEST_JSON = Path(".battinfo") / "library-rdf" / "cell-spec.index.json"
DEFAULT_PACKAGED_LIBRARY_CELL_TYPES_DIR = Path("src") / "battinfo" / "data" / "library" / "cell-spec"
DEFAULT_PUBLISH_SOURCES = tuple(EXAMPLES_ROOT / kind.subdir for kind in ENTITY_KINDS)
DEFAULT_INDEX_SOURCE_ROOT = EXAMPLES_ROOT
DEFAULT_REGISTRATION_SOURCE_ROOT = Path("examples")
TEMPLATE_UID = "0000000000000000"
TEMPLATE_CELL_SPEC_ID = "https://w3id.org/battinfo/spec/0000-0000-0000-0000"
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


class CellSpecificationInput(BaseModel):
    """Typed input for saving a new canonical cell-spec resource."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1.0"
    id: str | None = None
    uid: str | None = None
    model_name: str
    manufacturer: str | dict[str, Any]
    format: Literal["cylindrical", "prismatic", "pouch", "coin", "other", "unknown"] = "unknown"
    chemistry: str = "unknown"
    product_type: CellProductType | None = None
    positive_electrode_basis: str | None = None
    negative_electrode_basis: str | None = None
    positive_electrode_spec_id: str | None = None
    negative_electrode_spec_id: str | None = None
    electrolyte_spec_id: str | None = None
    separator_spec_id: str | None = None
    housing_spec_id: str | None = None
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


# NOTE: the former ``CellDatasheetInput`` (a thin, lossy library-input model that could only
# carry construction/property dicts) has been retired. Detailed specs are authored via
# ``cell_description()`` → ``CellSpecification`` bundle, or supplied as a library-format dict;
# both flow through ``save_library_cell_spec`` / ``_library_record_from_input``.


class CellInstanceInput(BaseModel):
    """Typed input for saving a new canonical cell-instance resource."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1.0"
    id: str | None = None
    uid: str | None = None
    cell_spec_id: str
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


class TestSpecInput(BaseModel):
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
    experiment: list[str] = Field(default_factory=list)   # PyBaMM-style strings (authoring)
    cycles: int | None = None
    method: list[dict[str, Any]] = Field(default_factory=list)  # pre-built structured method
    record: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    source_type: Literal["manual", "lab", "simulation", "import", "other"] = "manual"
    source_url: str | None = None
    citation: str | None = Field(default=None, validation_alias=AliasChoices("citation", "citation_doi"))
    source_file: str | None = None
    retrieved_at: int | str | None = None
    workflow_version: str | None = None
    notes: list[str] = Field(default_factory=list)


def template_cell_spec(
    *,
    manufacturer: str = "ExampleManufacturer",
    model_name: str = "MODEL-001",
    chemistry: str = "unknown",
    format: Literal["cylindrical", "prismatic", "pouch", "coin", "other", "unknown"] = "unknown",
    iec_code: str | None = None,
    country_of_origin: str | None = None,
    year: int | None = None,
    uid: str | None = TEMPLATE_UID,
    source_file: str = "template-cell-spec.json",
) -> dict[str, Any]:
    """Build a starter canonical cell-spec document for save workflows."""
    draft = CellSpecificationInput(
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
    return _record_from_cell_spec(draft)


def template_cell_spec_draft(
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
    """Build a starter authoring draft for a hand-edited cell-spec JSON file."""
    specs = _draft_specs_for_format(format)
    draft: dict[str, Any] = {
        "manufacturer": manufacturer,
        "model": model_name,
        "format": format,
        "chemistry": chemistry,
        "properties": specs,
        "comment": (
            "Template-generated cell-spec authoring draft. "
            "Edit values and remove entries that don't apply. "
            "Run 'battinfo specs list' to see all available properties and their valid units."
        ),
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


def _draft_specs_for_format(
    cell_format: str,
) -> dict[str, Any]:
    """Return example specs pre-filled with realistic placeholders for the given cell format."""
    def qty(value: float, unit: str) -> dict[str, Any]:
        return {"value": value, "unit": unit}

    specs: dict[str, Any] = {
        "nominal_capacity": qty(0.0, "Ah"),
        "nominal_voltage": qty(0.0, "V"),
        "mass": qty(0.0, "g"),
        "internal_resistance": qty(0.0, "mohm"),
        "maximum_continuous_discharging_current": qty(0.0, "A"),
        "cycle_life": qty(0, "count"),
    }

    if cell_format == "cylindrical":
        specs["diameter"] = qty(0.0, "mm")
        specs["height"] = qty(0.0, "mm")
    elif cell_format in ("prismatic", "pouch"):
        specs["width"] = qty(0.0, "mm")
        specs["height"] = qty(0.0, "mm")
        specs["thickness"] = qty(0.0, "mm")
    elif cell_format == "coin":
        specs["diameter"] = qty(0.0, "mm")
        specs["thickness"] = qty(0.0, "mm")

    return specs


def template_cell_instance(
    *,
    cell_spec_id: str = TEMPLATE_CELL_SPEC_ID,
    source_type: Literal["measurement", "lab", "bms", "other"] = "measurement",
    uid: str | None = TEMPLATE_UID,
) -> dict[str, Any]:
    """Build a starter canonical cell-instance document for save workflows."""
    draft = CellInstanceInput(
        uid=uid,
        cell_spec_id=cell_spec_id,
        source_type=source_type,
        notes=["Template-generated record. Set cell_spec_id/serial_number/datasets before saving."],
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


def template_test_spec(
    *,
    name: str = "Example Test Protocol",
    kind: TestKind = BatteryTestType.OTHER,
    source_type: Literal["manual", "lab", "simulation", "other"] = "manual",
    uid: str | None = TEMPLATE_UID,
) -> dict[str, Any]:
    """Build a starter canonical test-protocol document for save workflows."""
    draft = TestSpecInput(
        uid=uid,
        name=name,
        kind=kind,
        source_type=source_type,
        experiment=["Discharge at C/10 until 2.5 V"],
        notes=["Template-generated record. Replace the example experiment / conditions before saving."],
    )
    return _record_from_test_protocol(draft)


def template_test_spec_draft(
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
        "experiment": ["Charge at 1 C until 4.2 V", "Hold at 4.2 V until C/50", "Discharge at 1 C until 2.5 V"],
        "cycles": 1,
        "conditions": {"temperature": {"value": 25, "unit": "degC"}},
        "record": {},
        "safety": {},
        "artifacts": [],
        "comment": "Template-generated test-protocol authoring draft. Replace the example experiment with the real PyBaMM-style steps before loading into Workspace.",
    }
    if version is not None:
        draft["version"] = version
    if protocol_url is not None:
        draft["protocol_url"] = protocol_url
    return draft


def template_library_cell_spec(
    *,
    manufacturer: str = "ExampleManufacturer",
    model: str = "MODEL-001",
    chemistry: str = "unknown",
    format: Literal["cylindrical", "prismatic", "pouch", "coin", "other", "unknown"] = "unknown",
    positive_electrode_basis: str = "unknown",
    negative_electrode_basis: str = "unknown",
    uid: str | None = TEMPLATE_UID,
    source_file: str = "template-library-cell-spec.json",
    source_type: str = "datasheet",
) -> dict[str, Any]:
    """Build a starter detailed cell specification (library record).

    Detailed specs are normally authored via ``cell_description()``; this is the flat
    template for the library record (fill in the electrode/electrolyte/separator structure).
    """
    return _library_record_from_input(
        {
            "uid": uid,
            "manufacturer": manufacturer,
            "model": model,
            "chemistry": chemistry,
            "format": format,
            "positive_electrode_basis": positive_electrode_basis,
            "negative_electrode_basis": negative_electrode_basis,
            "source_file": source_file,
            "source_type": source_type,
            "specification_comment": ["Template-generated specification. Fill in trusted specification values."],
            "comment": ["Template-generated reusable library cell spec."],
        }
    )


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
    # Specification-format docs (internal library format) are not validated against the
    # cell-spec schema — their structure is enforced by CellSpecificationInput upstream.
    if isinstance(doc.get("specification"), Mapping):
        return
    result = validate_json(doc, profile="cell-spec")
    if result.ok:
        return
    raise ValueError(f"cell-specification validation failed: {'; '.join(result.errors)}")


def _cell_spec_record_to_library_format(doc: dict[str, Any]) -> dict[str, Any]:
    """Convert a cell-spec format record (product key) to the internal specification format."""
    if "specification" in doc or "cell_spec" not in doc:
        return doc
    product = doc.get("cell_spec", {})
    mfr = product.get("manufacturer", {})
    mfr_name = mfr.get("name") if isinstance(mfr, Mapping) else str(mfr) if mfr else ""
    specification: dict[str, Any] = {
        "id": product.get("id"),
        "manufacturer": mfr_name,
        "model": product.get("model", ""),
        "format": product.get("cell_format", "unknown"),
        "chemistry": product.get("chemistry", "unknown"),
    }
    for src, dst in [
        ("positive_electrode_basis", "positive_electrode_basis"),
        ("negative_electrode_basis", "negative_electrode_basis"),
        ("size_code", "size_code"),
        ("product_type", "product_type"),
    ]:
        if product.get(src) is not None:
            specification[dst] = product[src]
    if "properties" in doc:
        specification["property"] = doc["properties"]
    for field in ("construction", "positive_electrode", "negative_electrode",
                  "electrolyte", "separator", "housing"):
        if field in doc:
            specification[field] = doc[field]
    if "notes" in doc:
        specification["comment"] = doc["notes"]
    return {
        "schema_version": doc.get("schema_version", "1.0.0"),
        "specification": specification,
        "provenance": doc.get("provenance"),
        "comment": doc.get("notes"),
    }


def _sync_library_packaged_copy(source_path: Path, package_root: Path) -> Path:
    package_root.mkdir(parents=True, exist_ok=True)
    target_path = package_root / source_path.name
    target_path.write_text(source_path.read_text(encoding='utf-8'), encoding='utf-8')
    return target_path


def _library_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9-]+", "_", value.strip())
    token = re.sub(r"_+", "_", token).strip("_-")
    return token or "UNKNOWN"


def _library_cell_spec_filename(manufacturer: str, model: str) -> str:
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


def _staging_cell_spec_identity(
    source: dict[str, Any] | PathLike,
    draft: CellSpecificationInput,
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


def _staging_cell_spec_input(
    source: dict[str, Any] | PathLike,
    *,
    uid: str | None = None,
) -> tuple[CellSpecificationInput, Path | None]:
    source_path: Path | None = None
    if isinstance(source, (str, Path)):
        source_path = _as_path(source)
        payload = _load_json(source_path)
    else:
        payload = dict(source)

    if isinstance(payload.get("cell_spec"), Mapping) or isinstance(payload.get("cell_spec"), Mapping):
        record_payload = dict(payload)
        if isinstance(record_payload.get("cell_spec"), Mapping) and "cell_spec" not in record_payload:
            record_payload["cell_spec"] = dict(record_payload["cell_spec"])
        product = record_payload.get("cell_spec")
        provenance = record_payload.get("provenance")
        if not isinstance(product, Mapping):
            raise ValueError("canonical cell-spec record is missing product.")
        manufacturer_obj = product.get("manufacturer")
        manufacturer = manufacturer_obj.get("name") if isinstance(manufacturer_obj, Mapping) else manufacturer_obj
        return (
            CellSpecificationInput(
                schema_version=str(record_payload.get("schema_version") or "0.1.0"),
                id=product.get("id") if isinstance(product.get("id"), str) else None,
                uid=uid,
                model_name=str(product.get("model") or product.get("model_name") or ""),
                manufacturer=str(manufacturer or ""),
                format=str(product.get("cell_format") or product.get("cell_format") or product.get("format") or "unknown"),
                chemistry=str(product.get("chemistry") or "unknown"),
                positive_electrode_basis=(product.get("positive_electrode_basis") or product.get("positive_electrode_basis"))
                if isinstance(product.get("positive_electrode_basis") or product.get("positive_electrode_basis"), str)
                else None,
                negative_electrode_basis=(product.get("negative_electrode_basis") or product.get("negative_electrode_basis"))
                if isinstance(product.get("negative_electrode_basis") or product.get("negative_electrode_basis"), str)
                else None,
                size_code=(product.get("size_code") if isinstance(product.get("size_code"), str) else product.get("size_code") if isinstance(product.get("size_code"), str) else None),
                iec_code=(product.get("iec_code") if isinstance(product.get("iec_code"), str) else product.get("iec_code") if isinstance(product.get("iec_code"), str) else None),
                country_of_origin=(product.get("country_of_origin") if isinstance(product.get("country_of_origin"), str) else product.get("country_of_origin") if isinstance(product.get("country_of_origin"), str) else None),
                year=product.get("year") if isinstance(product.get("year"), int) else None,
                datasheet_revision=(product.get("datasheet_revision") or product.get("datasheet_revision"))
                if isinstance(product.get("datasheet_revision") or product.get("datasheet_revision"), str)
                else None,
                specs=dict(record_payload.get("properties") or {}),
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
        raise ValueError("staging cell-spec JSON requires non-empty string fields: manufacturer, model/model_name, format, chemistry.")

    specs = payload.get("properties")
    if specs is None:
        specs = {}
    if not isinstance(specs, Mapping):
        raise ValueError("staging cell-spec JSON field 'properties' must be an object when provided.")

    provenance = payload.get("provenance")
    if provenance is None:
        provenance = {}
    if not isinstance(provenance, Mapping):
        raise ValueError("staging cell-spec JSON field 'provenance' must be an object when provided.")

    year = payload.get("year")
    parsed_year = year if isinstance(year, int) else int(year) if isinstance(year, str) and year.strip().isdigit() else None
    retrieved_at = payload.get("retrieved_at", provenance.get("retrieved_at"))

    return (
        CellSpecificationInput(
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


def validate_staging_cell_spec(
    source: dict[str, Any] | PathLike,
    *,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    """Validate a staging cell-spec draft without writing anything to disk.

    Returns a dict with keys ``ok`` (bool), ``source_path``, ``record_id``,
    ``record_id_basis``, ``issues`` (list of validation issue dicts), and
    ``errors`` (list of error-severity issues only).
    """
    draft, source_path = _staging_cell_spec_input(source)
    identity = _staging_cell_spec_identity(source, draft)
    record = _record_from_cell_spec(draft)
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


def validate_staging_cell_specs(
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
        results.append(validate_staging_cell_spec(path, validation_policy=validation_policy))
    return {
        "status": "ok",
        "input_dir": str(input_root),
        "processed": len(results),
        "ok": sum(1 for item in results if item["ok"]),
        "failed": sum(1 for item in results if not item["ok"]),
        "results": results,
    }


def _existing_curated_cell_spec_id(target_path: Path) -> str | None:
    if not target_path.exists():
        return None
    try:
        payload = _load_json(target_path)
    except Exception:  # noqa: BLE001
        return None
    product = payload.get("cell_spec")
    if isinstance(product, Mapping) and isinstance(product.get("id"), str):
        return product["id"]
    return None


def promote_staging_cell_spec(
    source: dict[str, Any] | PathLike,
    *,
    curated_root: PathLike,
    record_id: str | None = None,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Promote a validated staging cell-spec draft to the curated record store.

    Validates the draft, assigns or resolves the canonical record IRI, writes
    the canonical JSON file to ``curated_root``, and returns a result dict with
    keys ``ok``, ``record_id``, ``path``, ``dry_run``, and ``issues``.

    Pass ``dry_run=True`` to validate and resolve the IRI without writing files.
    """
    draft, source_path = _staging_cell_spec_input(source)
    identity = _staging_cell_spec_identity(source, draft)
    if record_id is not None:
        resolved_record_id = _editorial_record_id(record_id)
    else:
        resolved_record_id = identity["record_id"]
        if not isinstance(resolved_record_id, str) or not resolved_record_id:
            raise ValueError(
                "staging cell-spec does not have a safe automatic record id. "
                f"Provide --record-id explicitly; suggested pattern: {identity['record_id_hint']}."
            )

    curated_root_path = _as_path(curated_root)
    target_path = curated_root_path / resolved_record_id / "record.json"
    existing_id = _existing_curated_cell_spec_id(target_path)
    if existing_id is not None:
        draft = draft.model_copy(update={"id": existing_id, "uid": None})

    record = _record_from_cell_spec(draft)
    report = validate_record_report(record, policy=validation_policy)
    if not report.ok:
        raise ValueError(f"staging cell-spec validation failed: {'; '.join(report.render_errors())}")

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


def promote_staging_cell_specs(
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
            promote_staging_cell_spec(
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


# ── Staging dataset promotion ─────────────────────────────────────────────────
# Datasets carry their own canonical IRI and `bdc:` identifier, so promotion is
# simpler than cell-spec: no manufacturer/model token derivation. Citations (the
# dataset↔publication links) pass through unchanged into the curated record.

def _staging_dataset_input(source: dict[str, Any] | PathLike) -> tuple[dict[str, Any], Path | None]:
    """Load a staging dataset record (a ``{schema_version, dataset, provenance}`` doc)."""
    source_path: Path | None = None
    if isinstance(source, (str, Path)):
        source_path = _as_path(source)
        payload = _load_json(source_path)
    else:
        payload = record_to_snake_aliases(dict(source))
    if not isinstance(payload.get("dataset"), Mapping):
        raise ValueError("staging dataset record must have a top-level 'dataset' object.")
    return payload, source_path


def _dataset_record_id(value: str) -> str:
    """Canonical curated id for a dataset, preserving the bdc scheme (e.g. 'bdc_000001').

    Unlike ``_editorial_record_id`` (which hyphenates underscores for descriptive
    cell-spec slugs), this keeps the dataset's own identifier intact, stripping only
    a leading namespace prefix such as ``bdc:``.
    """
    token = value.strip().lower()
    if ":" in token:
        token = token.split(":", 1)[-1]
    return re.sub(r"[^a-z0-9_-]+", "-", token).strip("-_")


def _staging_dataset_identity(payload: Mapping[str, Any], source_path: Path | None) -> dict[str, Any]:
    """Resolve the curated record id for a dataset from its identifier/short_id/filename."""
    dataset = payload.get("dataset")
    dataset = dataset if isinstance(dataset, Mapping) else {}
    record_id: str | None = None
    basis = "none"
    for key, source_basis in (("identifier", "identifier"), ("short_id", "short_id")):
        raw = dataset.get(key)
        if isinstance(raw, str) and raw.strip():
            candidate = _dataset_record_id(raw)
            if candidate:
                record_id, basis = candidate, source_basis
                break
    if record_id is None and source_path is not None and source_path.stem and not source_path.stem.startswith("_"):
        candidate = _dataset_record_id(source_path.stem)
        if candidate:
            record_id, basis = candidate, "filename"
    return {
        "record_id": record_id,
        "record_id_basis": basis,
        "record_id_hint": "bdc_000001",
        "requires_record_id": record_id is None,
    }


def validate_staging_dataset(
    source: dict[str, Any] | PathLike,
    *,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    """Validate a staging dataset record without writing anything to disk."""
    payload, source_path = _staging_dataset_input(source)
    identity = _staging_dataset_identity(payload, source_path)
    report = validate_record_report(payload, policy=validation_policy)
    return {
        "ok": report.ok,
        "source_path": str(source_path) if source_path is not None else None,
        "record_id": identity["record_id"],
        "record_id_basis": identity["record_id_basis"],
        "record_id_hint": identity["record_id_hint"],
        "requires_record_id": identity["requires_record_id"],
        "record": payload,
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


def validate_staging_datasets(
    *,
    input_dir: PathLike,
    glob: str = "*.json",
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    """Validate every staging dataset record in a directory."""
    input_root = _as_path(input_dir)
    if not input_root.exists() or not input_root.is_dir():
        raise ValueError(f"input_dir does not exist: {input_root}")
    results: list[dict[str, Any]] = []
    for path in sorted(input_root.glob(glob)):
        if path.name.startswith("_"):
            continue
        results.append(validate_staging_dataset(path, validation_policy=validation_policy))
    return {
        "status": "ok",
        "input_dir": str(input_root),
        "processed": len(results),
        "ok": sum(1 for item in results if item["ok"]),
        "failed": sum(1 for item in results if not item["ok"]),
        "results": results,
    }


def promote_staging_dataset(
    source: dict[str, Any] | PathLike,
    *,
    curated_root: PathLike,
    record_id: str | None = None,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Promote a validated staging dataset record into the curated record store.

    The curated id is taken from the record's own identifier (or ``record_id`` if
    given). Writes ``curated_root/<record-id>/record.json``. Pass ``dry_run=True``
    to validate + resolve the id without writing files.
    """
    payload, source_path = _staging_dataset_input(source)
    identity = _staging_dataset_identity(payload, source_path)
    if record_id is not None:
        resolved_record_id = _dataset_record_id(record_id)
    else:
        resolved_record_id = identity["record_id"]
        if not isinstance(resolved_record_id, str) or not resolved_record_id:
            raise ValueError(
                "staging dataset does not have a safe automatic record id. "
                f"Provide --record-id explicitly; suggested pattern: {identity['record_id_hint']}."
            )

    report = validate_record_report(payload, policy=validation_policy)
    if not report.ok:
        raise ValueError(f"staging dataset validation failed: {'; '.join(report.render_errors())}")

    curated_root_path = _as_path(curated_root)
    target_path = curated_root_path / resolved_record_id / "record.json"
    if not dry_run:
        _write_json(target_path, payload)
    return {
        "status": "ok",
        "record_id": resolved_record_id,
        "record_id_basis": identity["record_id_basis"] if record_id is None else "manual",
        "source_path": str(source_path) if source_path is not None else None,
        "target_path": str(target_path),
        "record": payload,
        "dry_run": dry_run,
    }


def promote_staging_datasets(
    *,
    input_dir: PathLike,
    curated_root: PathLike,
    glob: str = "*.json",
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Promote every staging dataset record in a directory."""
    input_root = _as_path(input_dir)
    if not input_root.exists() or not input_root.is_dir():
        raise ValueError(f"input_dir does not exist: {input_root}")
    promoted: list[dict[str, Any]] = []
    for path in sorted(input_root.glob(glob)):
        if path.name.startswith("_"):
            continue
        promoted.append(
            promote_staging_dataset(
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


def _curated_cell_spec_source(
    source: dict[str, Any] | PathLike,
) -> tuple[dict[str, Any], Path | None, str | None]:
    source_path: Path | None = None
    if isinstance(source, (str, Path)):
        source_path = _as_path(source)
        payload = _load_json(source_path)
    else:
        payload = dict(source)

    product = payload.get("cell_spec")
    if not isinstance(product, Mapping):
        raise ValueError("curated cell-spec source must be a canonical record with a top-level product object.")

    inferred_local_id: str | None = None
    if source_path is not None:
        if source_path.name == "record.json" and source_path.parent.name and not source_path.parent.name.startswith("_"):
            inferred_local_id = source_path.parent.name
        elif source_path.stem and not source_path.stem.startswith("_"):
            inferred_local_id = source_path.stem
    return payload, source_path, inferred_local_id


def _curated_cell_spec_title(record: Mapping[str, Any]) -> str:
    product = record.get("cell_spec")
    if not isinstance(product, Mapping):
        raise ValueError("cell-spec record is missing product.")
    manufacturer_obj = product.get("manufacturer")
    manufacturer = manufacturer_obj.get("name") if isinstance(manufacturer_obj, Mapping) else manufacturer_obj
    return str(product.get("name") or f"{manufacturer or 'Battery'} {product.get('model') or 'Cell'}").strip()


def _curated_cell_spec_submission_resource(
    *,
    record: Mapping[str, Any],
    source_local_id: str,
    title: str,
) -> dict[str, Any]:
    return {
        "resource_type": "cell_spec",
        "source_local_id": source_local_id,
        "title": title,
        "semantic_payload": {
            "@type": "CellSpecification",
            "battinfo_records": {"cell_spec": dict(record)},
        },
        "related_resources": [],
        "distributions": [],
    }


def build_curated_cell_spec_submission(
    source: dict[str, Any] | PathLike,
    *,
    workspace_id: str,
    publisher_id: str,
    source_version: str,
    source_local_id: str | None = None,
    title: str | None = None,
    publication_mode: str = "canonical-publication",
    source_system: str = "battinfo-records",
    workflow_name: str = "curated-cell-spec-publication",
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> dict[str, Any]:
    record, source_path, inferred_local_id = _curated_cell_spec_source(source)
    resolved_source_local_id = source_local_id or inferred_local_id
    if not isinstance(resolved_source_local_id, str) or not resolved_source_local_id.strip():
        raise ValueError("Could not infer source_local_id for curated cell-spec source; provide source_local_id explicitly.")

    validation = validate_record(record, policy=validation_policy)
    if not validation.ok:
        raise ValueError(f"curated cell-spec validation failed: {'; '.join(validation.errors)}")

    resolved_title = title or _curated_cell_spec_title(record)
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
        "resource": _curated_cell_spec_submission_resource(
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


class RegistryError(RuntimeError):
    """Base class for registry submission failures.

    Subclasses :class:`RuntimeError` so existing ``except RuntimeError`` handlers
    (e.g. ``ws._do_submit``) keep working unchanged.
    """

    def __init__(self, message: str, *, status_code: int | None = None, response_body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class RegistryClientError(RegistryError):
    """Terminal client-side failure (HTTP 4xx except 429, or a malformed response).

    The request will not succeed if retried as-is, so it is raised immediately.
    """


class RegistryTransientError(RegistryError):
    """Transient failure (connection error, timeout, HTTP 429/5xx).

    Safe to retry; raised only after the retry budget is exhausted.
    """


# HTTP statuses worth retrying: rate-limiting plus the standard transient 5xx set.
_REGISTRY_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
# Body-level statuses that mean "the registry rejected this record" even on a 2xx.
_REGISTRY_REJECTED_BODY_STATUS = frozenset({"failed", "rejected", "error"})
# Cap embedded response bodies so a misbehaving/echoing registry can't blow up
# (or leak large headers into) the raised error message.
_REGISTRY_ERROR_BODY_LIMIT = 500

_SECRET_TOKEN_RE = re.compile(r"bk_(?:live|test)_[A-Za-z0-9._-]+")


def _scrub_secret(text: str, api_key: str) -> str:
    """Redact the api_key (and any bk_live_/bk_test_ token) from a registry response body before
    it is embedded in an exception message — defence in depth against a registry that echoes it
    (A-6). The key is header-only in requests, so this only matters if the registry misbehaves."""
    if api_key:
        text = text.replace(api_key, "***")
    return _SECRET_TOKEN_RE.sub("***", text)


def submit_publication_package(
    payload: Mapping[str, Any],
    *,
    registry_base_url: str,
    api_key: str,
    api_key_header: str = "X-Battinfo-API-Key",
    timeout_sec: float = 30.0,
    max_attempts: int = 3,
    backoff_sec: float = 0.5,
) -> dict[str, Any]:
    """POST a publication package to the registry, defending against a hostile/cold registry.

    Retries transient failures (connection/timeout, HTTP 429/5xx) with exponential
    backoff up to ``max_attempts``; never retries other 4xx (raised immediately as
    :class:`RegistryClientError`). A 2xx with a non-JSON body, or a body-level
    ``failed``/``rejected``/``error`` status, is surfaced rather than reported as a
    blanket success. Every failure raises a :class:`RegistryError` subclass — which
    is a :class:`RuntimeError`, so existing callers keep working.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    request_url = registry_base_url.rstrip("/") + "/publication-packages"
    request_payload = dict(payload)
    request_body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", api_key_header: api_key}

    last_transient: RegistryTransientError | None = None
    for attempt in range(max_attempts):
        request = UrlRequest(request_url, data=request_body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout_sec) as response:
                status_code = response.getcode()
                # errors="replace": a non-UTF-8 2xx body must not raise a bare
                # UnicodeDecodeError (a ValueError) that escapes the caller's
                # `except RuntimeError`; the body is only used for JSON/error text.
                response_text = _scrub_secret(response.read().decode("utf-8", errors="replace"), api_key)
            try:
                response_payload = json.loads(response_text) if response_text else None
            except json.JSONDecodeError as exc:
                # A 2xx carrying an HTML/proxy/cold-start body is NOT a success.
                raise RegistryClientError(
                    f"Registry returned a non-JSON response (HTTP {status_code}): "
                    f"{response_text[:_REGISTRY_ERROR_BODY_LIMIT]!r}",
                    status_code=status_code,
                    response_body=response_text[:_REGISTRY_ERROR_BODY_LIMIT],
                ) from exc
            if response_payload is not None and not isinstance(response_payload, dict):
                # A 2xx whose JSON body is a scalar/list rather than an object is not
                # a valid submission response; surface it as a typed RuntimeError
                # rather than passing a non-mapping through to callers that do
                # `(result["response"] or {}).get(...)` (which would raise AttributeError
                # and escape the caller's `except RuntimeError`, aborting the batch).
                raise RegistryClientError(
                    f"Registry returned a non-object JSON response (HTTP {status_code}): "
                    f"{response_text[:_REGISTRY_ERROR_BODY_LIMIT]!r}",
                    status_code=status_code,
                    response_body=response_text[:_REGISTRY_ERROR_BODY_LIMIT],
                )
            body_status = None
            if isinstance(response_payload, dict):
                raw_status = response_payload.get("status")
                if isinstance(raw_status, str):
                    body_status = raw_status.lower()
            outer_status = "failed" if body_status in _REGISTRY_REJECTED_BODY_STATUS else "ok"
            return {
                "status": outer_status,
                "url": request_url,
                "status_code": status_code,
                "response": response_payload,
            }
        except HTTPError as exc:
            body = _scrub_secret(exc.read().decode("utf-8", errors="replace")[:_REGISTRY_ERROR_BODY_LIMIT], api_key)
            try:
                detail: Any = json.loads(body) if body else None
            except json.JSONDecodeError:
                detail = body
            message = f"Registry submission failed with HTTP {exc.code}: {detail}"
            if exc.code in _REGISTRY_RETRYABLE_STATUS:
                last_transient = RegistryTransientError(message, status_code=exc.code, response_body=body)
            else:
                # Other 4xx (incl. 409 conflict, 422 validation) won't succeed on a
                # retry; raise now. The "HTTP <code>" text is preserved so the
                # caller's existing 409 handling still matches.
                raise RegistryClientError(message, status_code=exc.code, response_body=body) from exc
        except (URLError, TimeoutError, OSError) as exc:
            # Read-timeouts surface as a bare socket.timeout/TimeoutError (an OSError,
            # NOT a URLError), so the original URLError-only catch let them escape and
            # abort the whole batch. OSError is the safe superset.
            reason = getattr(exc, "reason", exc)
            last_transient = RegistryTransientError(f"Registry submission failed (network/timeout): {reason}")

        # Reached only on a transient failure: back off, then the loop retries
        # unless the attempt budget is exhausted.
        if attempt + 1 < max_attempts and backoff_sec > 0:
            time.sleep(backoff_sec * (2 ** attempt))
    # Only reachable via the transient path. Use an explicit raise (not assert,
    # which `python -O` strips) since this is load-bearing control flow.
    if last_transient is None:  # pragma: no cover - defensive; max_attempts >= 1
        raise RegistryClientError("Registry submission made no attempts")
    raise last_transient


def publish_curated_cell_spec(
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
    workflow_name: str = "curated-cell-spec-publication",
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    payload = build_curated_cell_spec_submission(
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


# Specification fields carried through from a flat library-input dict. Unlike the retired
# CellDatasheetInput, this accepts the FULL physical structure, not just construction/property.
_LIBRARY_SPEC_OPTIONAL_FIELDS = (
    "size_code", "construction", "property", "positive_electrode", "negative_electrode",
    "electrolyte", "separator", "housing",
)


def _library_record_from_input(draft: Mapping[str, Any]) -> dict[str, Any]:
    """Build a library cell-spec record from a flat dict of specification fields.

    Accepts the full specification surface (manufacturer/model/identity + construction,
    property, and the electrode/electrolyte/separator/housing structure). Detailed specs
    are normally authored via ``cell_description()`` and saved as a ``CellSpecification``
    bundle; this is the dict/CLI entry point for the same library record.
    """
    draft_id = draft.get("id")
    uid = draft.get("uid")
    if draft_id is not None:
        if not CELL_SPEC_IRI_RE.fullmatch(draft_id):
            raise ValueError("cell specification id must match https://w3id.org/battinfo/spec/{uid}.")
        if uid is not None:
            _assert_id_matches_uid(draft_id, _normalized_dashed_uid(uid))
        entity_id = draft_id
    else:
        entity_id = f"https://w3id.org/battinfo/spec/{_normalized_dashed_uid(uid)}"

    specification: dict[str, Any] = {
        "id": entity_id,
        "manufacturer": draft.get("manufacturer"),
        "model": draft.get("model"),
        "format": draft.get("format"),
        "chemistry": draft.get("chemistry"),
        "positive_electrode_basis": draft.get("positive_electrode_basis"),
        "negative_electrode_basis": draft.get("negative_electrode_basis"),
    }
    for key in _LIBRARY_SPEC_OPTIONAL_FIELDS:
        value = draft.get(key)
        if value:
            specification[key] = value
    if draft.get("specification_comment"):
        specification["comment"] = list(draft["specification_comment"])

    provenance: dict[str, Any] = {
        "source_file": draft.get("source_file", "manual.json"),
        "retrieved_at": _to_unix_time(draft.get("retrieved_at")) or _now_unix(),
    }
    if draft.get("source_type"):
        provenance["source_type"] = draft["source_type"]
    if draft.get("source_name") is not None:
        provenance["source_name"] = draft["source_name"]
    if draft.get("source_url") is not None:
        provenance["source_url"] = draft["source_url"]
    citation = _citation_url_value(draft.get("citation"))
    if citation is not None:
        provenance["citation"] = citation
    if draft.get("workflow_version") is not None:
        provenance["workflow_version"] = draft["workflow_version"]
    if draft.get("provenance_comment") is not None:
        provenance["comment"] = draft["provenance_comment"]

    record: dict[str, Any] = {
        "schema_version": draft.get("schema_version", "1.0.0"),
        "specification": specification,
        "provenance": provenance,
    }
    if draft.get("comment"):
        record["comment"] = list(draft["comment"])
    return record


def query_library_cell_specs(
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
    """Query reusable library cell-spec specifications."""
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
            "housing": specification.get("housing"),
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


def query_cell_specs(
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
    cell_specs_dir: PathLike = DEFAULT_CELL_TYPES_DIR,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query cell types using practical metadata/property filters."""
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for path in _iter_json_files(_as_path(cell_specs_dir)):
        doc = _load_json(path)
        product = doc.get("cell_spec", {})
        specs = doc.get("properties", {})
        if isinstance(product, Mapping):
            cell_id = product.get("id")
            manufacturer_obj = product.get("manufacturer")
            manufacturer_name = (
                manufacturer_obj.get("name")
                if isinstance(manufacturer_obj, Mapping)
                else manufacturer_obj
            )
            model_name = product.get("model")
            format_name = product.get("cell_format") or product.get("cell_format")
            size_code = product.get("size_code") or product.get("size_code")
            iec_code = product.get("iec_code") or product.get("iec_code")
            country_of_origin = product.get("country_of_origin") or product.get("country_of_origin")
            year = product.get("year")
            chemistry_name = product.get("chemistry")
            short_id = product.get("short_id")
        else:
            legacy = doc.get("cell_spec", {})
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
                "properties": specs,
                "source": "cell-spec",
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
            specs = rec.get("properties", {})
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
    cell_spec_id: str | None = None,
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
            "cell_spec_id": inst.get("cell_spec_id"),
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
        if cell_spec_id is not None and rec.get("cell_spec_id") != cell_spec_id:
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
        distribution = dataset.get("distributions") or dataset.get("distribution")
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
                "conformance": test.get("conformance"),
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


def query_test_specs(
    *,
    id: str | None = None,
    kind: str | None = None,
    name_contains: str | None = None,
    source_type: str | None = None,
    mode: str | None = None,
    direction: str | None = None,
    tag: str | None = None,
    c_rate: float | None = None,
    has_cv_hold: bool | None = None,
    has_rest: bool | None = None,
    has_eis: bool | None = None,
    directory: PathLike = DEFAULT_TEST_PROTOCOLS_DIR,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query canonical reusable test-protocol metadata records.

    Beyond identity filters, the ``mode`` / ``direction`` / ``tag`` / ``c_rate`` /
    ``has_cv_hold`` / ``has_rest`` / ``has_eis`` filters match against the derived
    ``facets`` rollup, so an agent can find protocols by what their method *does*
    (e.g. all specs with a CV hold, or any using C/2)."""
    records: list[dict[str, Any]] = []
    for path in _iter_json_files(_as_path(directory)):
        doc = _load_json(path)
        protocol = doc.get("test_spec", {})
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
                "facets": doc.get("facets") if isinstance(doc.get("facets"), Mapping) else {},
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
        if not _matches_facets(rec.get("facets") or {}, mode=mode, direction=direction,
                               tag=tag, c_rate=c_rate, has_cv_hold=has_cv_hold,
                               has_rest=has_rest, has_eis=has_eis):
            continue
        filtered.append(rec)

    return _paginate(filtered, limit=limit, offset=offset)


def _matches_facets(facets: Mapping[str, Any], *, mode: str | None, direction: str | None,
                    tag: str | None, c_rate: float | None, has_cv_hold: bool | None,
                    has_rest: bool | None, has_eis: bool | None) -> bool:
    """True if the derived facets satisfy every supplied method-shape filter."""
    if mode is not None and mode not in (facets.get("modes") or []):
        return False
    if direction is not None and direction not in (facets.get("directions") or []):
        return False
    if tag is not None and tag not in (facets.get("tags") or []):
        return False
    if c_rate is not None and not any(
        abs(float(c) - float(c_rate)) < 1e-9 for c in (facets.get("c_rates") or [])
    ):
        return False
    for flag, key in ((has_cv_hold, "has_cv_hold"), (has_rest, "has_rest"), (has_eis, "has_eis")):
        if flag is not None and bool(facets.get(key)) != bool(flag):
            return False
    return True


def query(kind: str, /, **filters: Any) -> list[dict[str, Any]]:
    """Query BattINFO resources by explicit kind."""
    normalized = kind.strip().lower().replace("-", "_")

    if normalized in {"cell_spec", "cell_specs"}:
        return query_cell_specs(**filters)
    if normalized in {"cell", "cells", "cell_instance", "cell_instances"}:
        return query_cell_instances(**filters)
    if normalized in {"test_spec", "test_specs"}:
        return query_test_specs(**filters)
    if normalized in {"test", "tests"}:
        return query_tests(**filters)
    if normalized in {"dataset", "datasets"}:
        return query_datasets(**filters)
    if normalized in {"description", "descriptions", "library_cell_spec", "library_cell_specs"}:
        return query_library_cell_specs(**filters)

    raise ValueError(
        "kind must be one of: cell_specs, cells, test_specs, tests, datasets, descriptions."
    )


def resolve_cell_spec_id(
    *,
    cell_spec_id: str | None = None,
    model_name: str | None = None,
    manufacturer: str | None = None,
    chemistry: str | None = None,
    format: str | None = None,
    exact_model: bool = True,
    limit: int = 50,
) -> str:
    """Resolve a unique `cell-spec` IRI from metadata filters."""
    if cell_spec_id is not None:
        if not CELL_SPEC_IRI_RE.fullmatch(cell_spec_id):
            raise ValueError("cell_spec_id must match https://w3id.org/battinfo/spec/{uid}.")
        return cell_spec_id

    matches = query_cell_specs(
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
        raise ValueError("No cell-spec match found. Refine metadata filters or pass cell_spec_id explicitly.")

    if len(matches) > 1:
        ids = [str(m.get("id")) for m in matches[:5]]
        raise ValueError(
            "Multiple cell-spec matches found. Add more filters or pass cell_spec_id. "
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
    cell_spec_id: str | None = None,
    cell_spec: dict[str, Any] | PathLike | None = None,
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

    You can pass a canonical `cell_spec_id`, a `cell_spec` document/path, or metadata filters
    (`model_name`, `manufacturer`, ...) to resolve the type.
    """
    resolved_cell_spec_id = cell_spec_id

    if cell_spec is not None:
        cell_spec_doc: dict[str, Any]
        if isinstance(cell_spec, (str, Path)):
            cell_spec_doc = _load_json(_as_path(cell_spec))
        else:
            cell_spec_doc = cell_spec
        product_obj = cell_spec_doc.get("cell_spec", {})
        if not isinstance(product_obj, Mapping):
            raise ValueError("cell_spec document must contain a 'cell_spec' object.")
        embedded_id = product_obj.get("id")
        if not isinstance(embedded_id, str):
            raise ValueError("cell-spec id missing in provided cell_spec document.")
        if resolved_cell_spec_id is not None and embedded_id != resolved_cell_spec_id:
            raise ValueError("Provided cell_spec_id does not match cell-spec id.")
        resolved_cell_spec_id = embedded_id

    resolved_cell_spec_id = resolve_cell_spec_id(
        cell_spec_id=resolved_cell_spec_id,
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
            "cell_spec_id": resolved_cell_spec_id,
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
    return save_entity_path(entity_type, uid, source_root)


def _iter_entity_files(entity_type: str, source_root: Path) -> list[Path]:
    return iter_entity_files(entity_type, source_root)


def _logical_entity_type_from_doc(doc: Mapping[str, Any]) -> str:
    """Return the logical entity type from document structure, independent of IRI namespace."""
    kind = kind_for_doc(doc)
    if kind is None:
        raise ValueError(
            "Cannot determine entity type: expected cell_spec, cell_instance, test_spec, "
            "test, dataset, material_spec, or material key."
        )
    return kind.entity_type


def _candidate_types_for_namespace(namespace: str) -> list[str]:
    """Map an IRI namespace to the candidate internal entity types to search."""
    return entity_types_for_namespace(namespace)


def _find_record_path_by_id(entity_id: str, source_root: Path) -> Path | None:
    namespace, uid = _iri_tail(entity_id)
    for entity_type in _candidate_types_for_namespace(namespace):
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


def _record_from_cell_spec(draft: CellSpecificationInput) -> dict[str, Any]:
    if draft.id is not None:
        if not CELL_SPEC_IRI_RE.fullmatch(draft.id):
            raise ValueError("cell spec id must match https://w3id.org/battinfo/spec/{uid}.")
        if draft.uid is not None:
            dashed = _normalized_dashed_uid(draft.uid)
            _assert_id_matches_uid(draft.id, dashed)
        entity_id = draft.id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(draft.uid)
        entity_id = f"https://w3id.org/battinfo/spec/{dashed_uid}"

    manufacturer_org = _org_value(draft.manufacturer)
    manufacturer_name = manufacturer_org["name"] if manufacturer_org else str(draft.manufacturer)
    record: dict[str, Any] = {
        "schema_version": draft.schema_version,
        "cell_spec": {
            "id": entity_id,
            "short_id": dashed_uid.replace("-", "")[:6],
            "identifier": f"cell-spec:{dashed_uid}",
            "name": f"{manufacturer_name} {draft.model_name}",
            "model": draft.model_name,
            "manufacturer": manufacturer_org or {"type": "Organization", "name": str(draft.manufacturer)},
            "cell_format": draft.format,
            "chemistry": draft.chemistry,
        },
        "properties": draft.specs,
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
        record["cell_spec"]["positive_electrode_basis"] = draft.positive_electrode_basis
    if draft.negative_electrode_basis is not None:
        record["cell_spec"]["negative_electrode_basis"] = draft.negative_electrode_basis
    if draft.size_code is not None:
        record["cell_spec"]["size_code"] = draft.size_code
    if draft.iec_code is not None:
        record["cell_spec"]["iec_code"] = draft.iec_code
    if draft.country_of_origin is not None:
        record["cell_spec"]["country_of_origin"] = draft.country_of_origin
    if draft.year is not None:
        record["cell_spec"]["year"] = draft.year
    if draft.datasheet_revision is not None:
        record["cell_spec"]["datasheet_revision"] = draft.datasheet_revision
    if draft.file_hash is not None:
        record["provenance"]["file_hash"] = draft.file_hash
    # Component-spec references (top-level siblings of the inline holders).
    _COMPONENT_SPEC_REF_PATTERNS = {
        "positive_electrode_spec_id": "electrode-spec",
        "negative_electrode_spec_id": "electrode-spec",
        "electrolyte_spec_id": "electrolyte-spec",
        "separator_spec_id": "separator-spec",
        "housing_spec_id": "housing-spec",
    }
    for field_name, namespace in _COMPONENT_SPEC_REF_PATTERNS.items():
        value = getattr(draft, field_name)
        if value is not None:
            if not _component_iri_re(namespace).fullmatch(value):
                raise ValueError(f"{field_name} must match https://w3id.org/battinfo/{namespace}/{{uid}}.")
            record[field_name] = value
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record_to_snake_aliases(record)


def _record_from_cell_instance(draft: CellInstanceInput) -> dict[str, Any]:
    if not CELL_SPEC_IRI_RE.fullmatch(draft.cell_spec_id):
        raise ValueError("cell_spec_id must match https://w3id.org/battinfo/spec/{uid}.")
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
            "cell_spec_id": draft.cell_spec_id,
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
        dataset_obj["same_as"] = list(dict.fromkeys(draft.same_as))
    if draft.additional_type:
        dataset_obj["additional_type"] = list(dict.fromkeys(draft.additional_type))
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
        dataset_obj["main_entity"] = copy.deepcopy(draft.main_entity)

    if draft.distribution:
        dataset_obj["distributions"] = copy.deepcopy(draft.distribution)
    elif draft.download_url is not None or draft.format is not None or (draft.checksum_algorithm and draft.checksum_value):
        distribution: dict[str, Any] = {
            "type": "DataDownload",
            "content_url": draft.download_url or draft.access_url or draft.source_url or f"https://example.org/dataset/{dashed_uid}/download",
            "encoding_format": draft.format or "application/octet-stream",
        }
        if draft.checksum_algorithm and draft.checksum_value:
            distribution["checksum"] = {"algorithm": draft.checksum_algorithm, "value": draft.checksum_value}
        dataset_obj["distributions"] = [distribution]

    if draft.checksum_algorithm and draft.checksum_value:
        dataset_obj.setdefault("distributions", [
            {
                "type": "DataDownload",
                "content_url": draft.access_url or draft.source_url or f"https://example.org/dataset/{dashed_uid}/download",
                "encoding_format": draft.format or "application/octet-stream",
            }
        ])
        first_dist = dataset_obj["distributions"][0]
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
        raise ValueError("protocol_id must match https://w3id.org/battinfo/spec/{uid}.")
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


def _record_from_test_protocol(draft: TestSpecInput) -> dict[str, Any]:
    if draft.id is not None:
        if not TEST_PROTOCOL_IRI_RE.fullmatch(draft.id):
            raise ValueError("test protocol id must match https://w3id.org/battinfo/spec/{uid}.")
        if draft.uid is not None:
            dashed = _normalized_dashed_uid(draft.uid)
            _assert_id_matches_uid(draft.id, dashed)
        entity_id = draft.id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(draft.uid)
        entity_id = f"https://w3id.org/battinfo/spec/{dashed_uid}"

    record: dict[str, Any] = {
        "schema_version": draft.schema_version,
        "test_spec": {
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
        record["test_spec"]["description"] = draft.description
    if draft.version is not None:
        record["test_spec"]["version"] = draft.version
    if draft.protocol_url is not None:
        record["test_spec"]["protocol_url"] = draft.protocol_url
    if draft.conditions:
        record["conditions"] = copy.deepcopy(draft.conditions)
    if draft.record:
        record["record"] = copy.deepcopy(draft.record)
    if draft.safety:
        record["safety"] = copy.deepcopy(draft.safety)
    # Descriptive method: a pre-built structured `method` wins, else parse the
    # PyBaMM-style `experiment` strings (the default human authoring interface).
    from battinfo.bundle import _prune_empty  # noqa: PLC0415
    from battinfo.testmethod import Quantity, Step, compute_facets, parse_experiment  # noqa: PLC0415
    method_objs: list[Step] = []
    if draft.method:
        method_objs = [Step.model_validate(s) for s in draft.method]
    elif draft.experiment:
        method_objs = parse_experiment(list(draft.experiment), draft.cycles)
    if method_objs:
        record["method"] = [_prune_empty(s.model_dump(mode="json")) for s in method_objs]
        # Carry authored conditions (e.g. temperature) into the facet rollup so the
        # API save path matches TestSpec.facets() — otherwise facets.temperatures is dropped.
        facet_conditions = {
            key: Quantity(value=value["value"], unit=value["unit"])
            for key, value in (draft.conditions or {}).items()
            if isinstance(value, Mapping) and "value" in value and "unit" in value
        }
        record["facets"] = compute_facets(method_objs, facet_conditions)
    if draft.artifacts:
        record["artifacts"] = [copy.deepcopy(a) for a in draft.artifacts]
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
    _, uid = _iri_tail(entity_id)
    entity_type = _logical_entity_type_from_doc(doc)
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


def save_cell_spec(
    draft: CellSpecificationInput | dict[str, Any] | PathLike,
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
    """Save a cell-spec from either draft payload or canonical record."""
    from battinfo.bundle import CellSpecification as CellSpecificationBundle

    if isinstance(draft, (str, Path)):
        loaded = _load_json(_as_path(draft))
        return save_cell_spec(
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
    if isinstance(draft, CellSpecificationBundle):
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
        isinstance(draft.get("cell_spec"), Mapping) or isinstance(draft.get("cell_spec"), Mapping)
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
    draft_model = draft if isinstance(draft, CellSpecificationInput) else CellSpecificationInput.model_validate(draft)
    record = _record_from_cell_spec(draft_model)
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


def save_test_spec(
    draft: TestSpecInput | dict[str, Any] | PathLike,
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
    from battinfo.bundle import TestSpec

    if isinstance(draft, (str, Path)):
        loaded = _load_json(_as_path(draft))
        return save_test_spec(
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
    if isinstance(draft, TestSpec):
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
    if isinstance(draft, Mapping) and isinstance(draft.get("test_spec"), Mapping):
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
    draft_model = draft if isinstance(draft, TestSpecInput) else TestSpecInput.model_validate(draft)
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


def build_cell_spec_library_rdf(
    *,
    input_dir: PathLike = DEFAULT_LIBRARY_CELL_TYPES_DIR,
    output_jsonld_dir: PathLike = DEFAULT_LIBRARY_RDF_CELL_TYPES_DIR,
    aggregate_jsonld: PathLike = DEFAULT_LIBRARY_AGGREGATE_JSONLD,
    manifest_json: PathLike = DEFAULT_LIBRARY_MANIFEST_JSON,
    glob: str = "*.json",
    clean_output: bool = False,
) -> dict[str, Any]:
    """Validate reusable cell-spec specifications and build domain-battery JSON-LD artifacts."""
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

        normalised = _cell_spec_record_to_library_format(descriptor)
        specification = normalised.get("specification", {})
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
        "library_type": "battinfo-cell-spec-library",
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


def save_library_cell_spec(
    draft: "CellSpecification | dict[str, Any] | PathLike",
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
        return save_library_cell_spec(
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
    elif isinstance(draft, Mapping) and isinstance(draft.get("cell_spec"), Mapping):
        # Cell-type format: validate first, then normalise to the internal specification format.
        if validate:
            _validate_cell_specification(dict(draft))
        doc = _cell_spec_record_to_library_format(dict(draft))
    elif isinstance(draft, Mapping) and isinstance(draft.get("specification"), Mapping):
        doc = dict(draft)
    else:
        # Flat dict of specification fields (CLI inline options / hand-authored JSON).
        doc = _library_record_from_input(dict(draft))

    if validate and not isinstance(doc.get("specification"), Mapping):
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
    if not isinstance(entity_id, str) or not CELL_SPEC_IRI_RE.fullmatch(entity_id):
        raise ValueError("cell specification field 'specification.id' must match https://w3id.org/battinfo/spec/{uid}.")
    if not isinstance(manufacturer, str) or not manufacturer.strip():
        raise ValueError("cell specification field 'specification.manufacturer' must be a non-empty string.")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("cell specification field 'specification.model' must be a non-empty string.")

    expected_path = library_root_path / _library_cell_spec_filename(manufacturer, model)
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
                "entity_type": "cell-spec",
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
        "entity_type": "cell-spec",
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
        rdf_result = build_cell_spec_library_rdf(
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
    entity_id = entity_id_from_doc(doc)
    if entity_id is None:
        raise ValueError("Could not locate canonical entity id in document.")
    return entity_id


def _entity_schema_rel_path(doc: dict[str, Any]) -> str:
    kind = kind_for_doc(doc)
    if kind is None:
        raise ValueError(
            "Unsupported record type: expected cell_spec, cell_instance, test_spec, "
            "test, dataset, material_spec, or material."
        )
    return kind.schema_file


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
    if isinstance(value.get("same_as"), str):
        out["schema:sameAs"] = value["same_as"]
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
    if isinstance(value.get("same_as"), str):
        out["schema:sameAs"] = value["same_as"]
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
    same_as = value.get("same_as")
    if isinstance(same_as, str):
        out["schema:sameAs"] = same_as
        out["schema:propertyID"] = same_as
    return out


def _schema_distribution_value(value: Any, *, part_of_id: str) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    content_url = value.get("content_url")
    encoding_format = value.get("encoding_format")
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
    same_as = value.get("same_as")
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
    primary_key = value.get("primary_key") or value.get("primaryKey")
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
        table_schema = value.get("table_schema") or value.get("tableSchema")
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
        table_items = value.get("tables") or value.get("table")
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
    _, uid = _iri_tail(entity_iri)
    entity_type = _logical_entity_type_from_doc(doc)
    # csvw: is used by _schema_main_entity_value helpers called from the dataset block.
    context = [
        "https://w3id.org/emmo/domain/battery/context",
        {
            "schema": "https://schema.org/",
            "csvw": "http://www.w3.org/ns/csvw#",
        },
    ]

    if entity_type == "cell-spec":
        cell = doc.get("cell_spec")
        if not isinstance(cell, Mapping):
            cell = doc["cell_spec"]
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
        product_type = cell.get("product_type") or cell.get("product_type")
        if product_type:
            out["schema:additionalType"] = str(product_type)
        size_code = cell.get("size_code") or cell.get("size_code")
        if size_code:
            out["schema:size"] = size_code
        # Quantitative specifications as EMMO ConventionalProperty nodes.
        # Chemistry and format are already expressed through @type stacking.
        specs = doc.get("properties") or {}
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
            "hasDescription": {"@id": inst.get("cell_spec_id")},
            "schema:isVariantOf": {"@id": inst.get("cell_spec_id")},
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
        protocol = doc["test_spec"]
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
            "@type": ["BatteryTest", "schema:Action", "prov:Activity"],
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
        distribution = dataset.get("distributions") or dataset.get("distribution")
        encoding_format = None
        if isinstance(distribution, list):
            for entry in distribution:
                if isinstance(entry, Mapping) and isinstance(entry.get("encoding_format"), str):
                    encoding_format = entry.get("encoding_format")
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
        if dataset.get("access_url"):
            out["schema:url"] = dataset.get("access_url")
        if isinstance(dataset.get("same_as"), list):
            same_as = [item for item in dataset["same_as"] if isinstance(item, str)]
            if same_as:
                out["schema:sameAs"] = same_as
        if isinstance(dataset.get("additional_type"), list):
            additional_type = [item for item in dataset["additional_type"] if isinstance(item, str)]
            if additional_type:
                out["schema:additionalType"] = additional_type
        if isinstance(dataset.get("version"), str):
            out["schema:version"] = dataset["version"]
        if isinstance(dataset.get("keywords"), list):
            keywords = [item for item in dataset["keywords"] if isinstance(item, str)]
            if keywords:
                out["schema:keywords"] = keywords
        creator_value = dataset.get("creators")
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
        funder_value = dataset.get("funders")
        if isinstance(funder_value, list):
            funders = [node for item in funder_value if (node := _schema_agent_value(item)) is not None]
            if funders:
                out["schema:funder"] = funders
        elif isinstance(funder_value, Mapping):
            funder = _schema_agent_value(funder_value)
            if funder is not None:
                out["schema:funder"] = funder
        citation_value = dataset.get("citations")
        if isinstance(citation_value, list):
            citations = [node for item in citation_value if (node := _schema_citation_value(item)) is not None]
            if citations:
                out["schema:citation"] = citations
        else:
            citation = _schema_citation_value(citation_value)
            if citation is not None:
                out["schema:citation"] = citation
        if isinstance(dataset.get("measurement_techniques"), list):
            values = [item for item in dataset["measurement_techniques"] if isinstance(item, str)]
            if values:
                out["schema:measurementTechnique"] = values
        if isinstance(dataset.get("measurement_methods"), list):
            values = [item for item in dataset["measurement_methods"] if isinstance(item, str)]
            if values:
                out["schema:measurementMethod"] = values
        if isinstance(dataset.get("variable_measured"), list):
            values = [node for item in dataset["variable_measured"] if (node := _schema_variable_measured_value(item)) is not None]
            if values:
                out["schema:variableMeasured"] = values
        if isinstance(dataset.get("is_accessible_for_free"), bool):
            out["schema:isAccessibleForFree"] = dataset["is_accessible_for_free"]
        if isinstance(dataset.get("conditions_of_access"), str):
            out["schema:conditionsOfAccess"] = dataset["conditions_of_access"]
        if isinstance(dataset.get("in_language"), str):
            out["schema:inLanguage"] = dataset["in_language"]
        if dataset.get("created_at") is not None:
            out["schema:dateCreated"] = dataset["created_at"]
        if dataset.get("modified_at") is not None:
            out["schema:dateModified"] = dataset["modified_at"]
        if dataset.get("published_at") is not None:
            out["schema:datePublished"] = dataset["published_at"]
        if isinstance(dataset.get("temporal_coverage"), str):
            out["schema:temporalCoverage"] = dataset["temporal_coverage"]
        if isinstance(dataset.get("spatial_coverage"), str):
            out["schema:spatialCoverage"] = dataset["spatial_coverage"]
        if isinstance(dataset.get("is_based_on"), list):
            refs = [{"@id": item} for item in dataset["is_based_on"] if isinstance(item, str)]
            if refs:
                out["schema:isBasedOn"] = refs
        included_in_data_catalog = dataset.get("included_in_data_catalog")
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
        main_entity = dataset.get("main_entity")
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
    namespace, uid = _iri_tail(iri)
    logical_type = _logical_entity_type_from_doc(doc)
    out_dir = _as_path(target_root) / namespace / uid
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
        "entity_type": logical_type,
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


class MaterialSpecInput(BaseModel):
    """Typed input for saving a new canonical material-spec resource."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1.0"
    id: str | None = None
    uid: str | None = None
    name: str
    material_class: str | None = None
    electrode_polarity: str | None = None
    formula: str | None = None
    chemistry_family: str | None = None
    emmo_type: str | None = None
    cas_number: str | None = None
    manufacturer: str | dict[str, Any] | None = None
    supplier: str | dict[str, Any] | None = None
    product_id: str | None = None
    composition: dict[str, Any] | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None
    source_type: Literal["datasheet", "manufacturer", "measurement", "lab", "literature", "manual", "other"] = "datasheet"
    source_url: str | None = None
    citation: str | None = Field(default=None, validation_alias=AliasChoices("citation", "citation_doi"))
    retrieved_at: int | str | None = None
    notes: list[str] = Field(default_factory=list)


class MaterialInput(BaseModel):
    """Typed input for saving a new canonical material (instance) resource."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1.0"
    id: str | None = None
    uid: str | None = None
    material_spec_id: str
    name: str | None = None
    lot_id: str | None = None
    batch_id: str | None = None
    supplier: str | dict[str, Any] | None = None
    received_date: int | str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    property: dict[str, Any] = Field(default_factory=dict)
    source_type: Literal["datasheet", "manufacturer", "measurement", "lab", "literature", "manual", "other"] = "lab"
    source_url: str | None = None
    citation: str | None = Field(default=None, validation_alias=AliasChoices("citation", "citation_doi"))
    retrieved_at: int | str | None = None
    notes: list[str] = Field(default_factory=list)


def _org_value(value: str | dict[str, Any] | None) -> dict[str, Any] | None:
    """Coerce a manufacturer/supplier input to a structured Organization object."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return {"type": "Organization", "name": text} if text else None
    if isinstance(value, Mapping):
        org: dict[str, Any] = {"type": "Organization"}
        for key in ("name", "id", "url"):
            if value.get(key) is not None:
                org[key] = value[key]
        return org if org.get("name") else None
    return None


def _record_from_material_spec(draft: MaterialSpecInput) -> dict[str, Any]:
    if draft.id is not None:
        if not MATERIAL_SPEC_IRI_RE.fullmatch(draft.id):
            raise ValueError("material spec id must match https://w3id.org/battinfo/material-spec/{uid}.")
        if draft.uid is not None:
            _assert_id_matches_uid(draft.id, _normalized_dashed_uid(draft.uid))
        entity_id = draft.id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(draft.uid)
        entity_id = f"https://w3id.org/battinfo/material-spec/{dashed_uid}"

    spec: dict[str, Any] = {
        "id": entity_id,
        "short_id": dashed_uid.replace("-", "")[:6],
        "name": draft.name,
    }
    for field_name in (
        "material_class",
        "electrode_polarity",
        "formula",
        "chemistry_family",
        "emmo_type",
        "cas_number",
        "product_id",
        "description",
    ):
        value = getattr(draft, field_name)
        if value is not None:
            spec[field_name] = value
    for org_field in ("manufacturer", "supplier"):
        org = _org_value(getattr(draft, org_field))
        if org is not None:
            spec[org_field] = org
    if draft.composition:
        spec["composition"] = draft.composition
    if draft.property:
        spec["property"] = draft.property

    record: dict[str, Any] = {
        "schema_version": draft.schema_version,
        "material_spec": spec,
        "provenance": {
            "source_type": draft.source_type,
            "retrieved_at": _to_unix_time(draft.retrieved_at) or _now_unix(),
        },
    }
    if draft.source_url is not None:
        record["provenance"]["source_url"] = draft.source_url
    citation = _citation_url_value(draft.citation)
    if citation is not None:
        record["provenance"]["citation"] = citation
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record_to_snake_aliases(record)


def _record_from_material(draft: MaterialInput) -> dict[str, Any]:
    if not MATERIAL_SPEC_IRI_RE.fullmatch(draft.material_spec_id):
        raise ValueError("material_spec_id must match https://w3id.org/battinfo/material-spec/{uid}.")
    if draft.id is not None:
        if not MATERIAL_IRI_RE.fullmatch(draft.id):
            raise ValueError("material id must match https://w3id.org/battinfo/material/{uid}.")
        if draft.uid is not None:
            _assert_id_matches_uid(draft.id, _normalized_dashed_uid(draft.uid))
        entity_id = draft.id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(draft.uid)
        entity_id = f"https://w3id.org/battinfo/material/{dashed_uid}"

    material: dict[str, Any] = {
        "id": entity_id,
        "material_spec_id": draft.material_spec_id,
        "short_id": dashed_uid.replace("-", "")[:6],
    }
    for field_name in ("name", "lot_id", "batch_id"):
        value = getattr(draft, field_name)
        if value is not None:
            material[field_name] = value
    supplier = _org_value(draft.supplier)
    if supplier is not None:
        material["supplier"] = supplier
    if draft.received_date is not None:
        received = _to_unix_time(draft.received_date)
        material["received_date"] = received if received is not None else draft.received_date
    if draft.dataset_ids:
        for dataset_id in draft.dataset_ids:
            if not DATASET_IRI_RE.fullmatch(dataset_id):
                raise ValueError("dataset_ids entries must match https://w3id.org/battinfo/dataset/{uid}.")
        material["datasets"] = [{"id": dataset_id, "role": "raw"} for dataset_id in draft.dataset_ids]
    if draft.property:
        material["property"] = draft.property

    record: dict[str, Any] = {
        "schema_version": draft.schema_version,
        "material": material,
        "provenance": {
            "source_type": draft.source_type,
            "retrieved_at": _to_unix_time(draft.retrieved_at) or _now_unix(),
        },
    }
    if draft.source_url is not None:
        record["provenance"]["source_url"] = draft.source_url
    citation = _citation_url_value(draft.citation)
    if citation is not None:
        record["provenance"]["citation"] = citation
    if draft.notes:
        record["notes"] = list(draft.notes)
    return record_to_snake_aliases(record)


def template_material_spec(*, name: str = "Example Material", uid: str | None = TEMPLATE_UID) -> dict[str, Any]:
    """Build a starter canonical material-spec document for save workflows."""
    return _record_from_material_spec(
        MaterialSpecInput(
            uid=uid,
            name=name,
            notes=["Template-generated record. Set name/material_class/formula/property before saving."],
        )
    )


def template_material(
    *,
    material_spec_id: str = "https://w3id.org/battinfo/material-spec/0000-0000-0000-0000",
    uid: str | None = TEMPLATE_UID,
) -> dict[str, Any]:
    """Build a starter canonical material (instance) document for save workflows."""
    return _record_from_material(
        MaterialInput(
            uid=uid,
            material_spec_id=material_spec_id,
            notes=["Template-generated record. Set material_spec_id/lot_id/property before saving."],
        )
    )


def create_material_spec(*, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical material-spec document from typed fields."""
    record = _record_from_material_spec(MaterialSpecInput(**fields))
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def create_material(*, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical material (instance) document from typed fields."""
    record = _record_from_material(MaterialInput(**fields))
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def save_material_spec(
    draft: MaterialSpecInput | dict[str, Any] | PathLike,
    *,
    source_root: PathLike = DEFAULT_REGISTRATION_SOURCE_ROOT,
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    resolve_references: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Save a material-spec from either draft payload or canonical record."""
    if isinstance(draft, (str, Path)):
        return save_material_spec(
            _load_json(_as_path(draft)),
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
        )
    if isinstance(draft, MaterialSpecInput):
        record = _record_from_material_spec(draft)
    elif isinstance(draft, Mapping) and isinstance(draft.get("material_spec"), Mapping):
        record = dict(draft)
    else:
        record = _record_from_material_spec(MaterialSpecInput.model_validate(draft))
    return save_record(
        record,
        source_root=source_root,
        mode=mode,
        duplicate_policy=duplicate_policy,
        resolve_references=resolve_references,
        build_jsonld=False,
        build_html=False,
        validate=validate,
        validation_policy=validation_policy,
        dry_run=dry_run,
    )


def save_material(
    draft: MaterialInput | dict[str, Any] | PathLike,
    *,
    source_root: PathLike = DEFAULT_REGISTRATION_SOURCE_ROOT,
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    resolve_references: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Save a material (instance) from either draft payload or canonical record."""
    if isinstance(draft, (str, Path)):
        return save_material(
            _load_json(_as_path(draft)),
            source_root=source_root,
            mode=mode,
            duplicate_policy=duplicate_policy,
            resolve_references=resolve_references,
            validate=validate,
            validation_policy=validation_policy,
            dry_run=dry_run,
        )
    if isinstance(draft, MaterialInput):
        record = _record_from_material(draft)
    elif isinstance(draft, Mapping) and isinstance(draft.get("material"), Mapping):
        record = dict(draft)
    else:
        record = _record_from_material(MaterialInput.model_validate(draft))
    return save_record(
        record,
        source_root=source_root,
        mode=mode,
        duplicate_policy=duplicate_policy,
        resolve_references=resolve_references,
        build_jsonld=False,
        build_html=False,
        validate=validate,
        validation_policy=validation_policy,
        dry_run=dry_run,
    )


def query_material_specs(
    *,
    id: str | None = None,
    short_id_prefix: str | None = None,
    name: str | None = None,
    material_class: str | None = None,
    formula: str | None = None,
    manufacturer: str | None = None,
    source_type: str | None = None,
    directory: PathLike = DEFAULT_MATERIAL_SPECS_DIR,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query reusable material specifications."""
    records: list[dict[str, Any]] = []
    for path in _iter_json_files(_as_path(directory)):
        doc = _load_json(path)
        spec = doc.get("material_spec", {})
        prov = doc.get("provenance", {})
        if not isinstance(spec, Mapping):
            continue
        records.append(
            {
                "id": spec.get("id"),
                "short_id": spec.get("short_id"),
                "name": spec.get("name"),
                "material_class": spec.get("material_class"),
                "formula": spec.get("formula"),
                "manufacturer": spec.get("manufacturer"),
                "source_type": prov.get("source_type") if isinstance(prov, Mapping) else None,
                "path": str(path),
                "record": doc,
            }
        )

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if short_id_prefix and not str(rec.get("short_id", "")).lower().startswith(short_id_prefix.lower()):
            continue
        if not _str_eq(rec.get("name"), name):
            continue
        if not _str_eq(rec.get("material_class"), material_class):
            continue
        if not _str_eq(rec.get("formula"), formula):
            continue
        if not _str_eq(rec.get("manufacturer"), manufacturer):
            continue
        if not _str_eq(rec.get("source_type"), source_type):
            continue
        filtered.append(rec)

    return _paginate(filtered, limit=limit, offset=offset)


def query_materials(
    *,
    id: str | None = None,
    material_spec_id: str | None = None,
    short_id_prefix: str | None = None,
    lot_id: str | None = None,
    source_type: str | None = None,
    directory: PathLike = DEFAULT_MATERIALS_DIR,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query physical material lots/batches."""
    records: list[dict[str, Any]] = []
    for path in _iter_json_files(_as_path(directory)):
        doc = _load_json(path)
        material = doc.get("material", {})
        prov = doc.get("provenance", {})
        if not isinstance(material, Mapping):
            continue
        records.append(
            {
                "id": material.get("id"),
                "material_spec_id": material.get("material_spec_id"),
                "short_id": material.get("short_id"),
                "lot_id": material.get("lot_id"),
                "source_type": prov.get("source_type") if isinstance(prov, Mapping) else None,
                "path": str(path),
                "record": doc,
            }
        )

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if material_spec_id is not None and rec.get("material_spec_id") != material_spec_id:
            continue
        if short_id_prefix and not str(rec.get("short_id", "")).lower().startswith(short_id_prefix.lower()):
            continue
        if not _str_eq(rec.get("lot_id"), lot_id):
            continue
        if not _str_eq(rec.get("source_type"), source_type):
            continue
        filtered.append(rec)

    return _paginate(filtered, limit=limit, offset=offset)


# ── Generic component spec/instance factory ───────────────────────────────────
# Component families (electrode/electrolyte/separator/current-collector/housing) all
# follow one spec+instance shape that reuses an existing embedded holder. These generic
# functions are parameterized by family; thin per-family wrappers are generated below.

_UID_TAIL = r"[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}"


def _component_iri_re(namespace: str) -> re.Pattern[str]:
    return re.compile(rf"^https://w3id\.org/battinfo/{re.escape(namespace)}/{_UID_TAIL}$")


def _record_from_component_spec(
    family: str,
    *,
    name: str,
    body: dict[str, Any] | None = None,
    manufacturer: str | dict[str, Any] | None = None,
    supplier: str | dict[str, Any] | None = None,
    product_id: str | None = None,
    uid: str | None = None,
    id: str | None = None,
    source_type: str = "datasheet",
    source_url: str | None = None,
    citation: str | None = None,
    retrieved_at: int | str | None = None,
    notes: list[str] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    namespace = f"{family.replace('_', '-')}-spec"
    if id is not None:
        if not _component_iri_re(namespace).fullmatch(id):
            raise ValueError(f"{namespace} id must match https://w3id.org/battinfo/{namespace}/{{uid}}.")
        if uid is not None:
            _assert_id_matches_uid(id, _normalized_dashed_uid(uid))
        entity_id = id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(uid)
        entity_id = f"https://w3id.org/battinfo/{namespace}/{dashed_uid}"

    spec: dict[str, Any] = {"id": entity_id, "short_id": dashed_uid.replace("-", "")[:6], "name": name}
    spec.update(body or {})
    spec.update({k: v for k, v in extra.items() if v is not None})
    for org_field, org_input in (("manufacturer", manufacturer), ("supplier", supplier)):
        org = _org_value(org_input)
        if org is not None:
            spec[org_field] = org
    if product_id is not None:
        spec["product_id"] = product_id

    record: dict[str, Any] = {
        "schema_version": "0.1.0",
        f"{family}_spec": spec,
        "provenance": {"source_type": source_type, "retrieved_at": _to_unix_time(retrieved_at) or _now_unix()},
    }
    if source_url is not None:
        record["provenance"]["source_url"] = source_url
    citation_value = _citation_url_value(citation)
    if citation_value is not None:
        record["provenance"]["citation"] = citation_value
    if notes:
        record["notes"] = list(notes)
    return record_to_snake_aliases(record)


def _record_from_component_instance(
    family: str,
    *,
    spec_id: str,
    body: dict[str, Any] | None = None,
    name: str | None = None,
    lot_id: str | None = None,
    supplier: str | dict[str, Any] | None = None,
    dataset_ids: list[str] | None = None,
    uid: str | None = None,
    id: str | None = None,
    source_type: str = "lab",
    source_url: str | None = None,
    citation: str | None = None,
    retrieved_at: int | str | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    base_namespace = family.replace("_", "-")
    spec_namespace = f"{base_namespace}-spec"
    if not _component_iri_re(spec_namespace).fullmatch(spec_id):
        raise ValueError(f"{family}_spec_id must match https://w3id.org/battinfo/{spec_namespace}/{{uid}}.")
    if id is not None:
        if not _component_iri_re(base_namespace).fullmatch(id):
            raise ValueError(f"{family} id must match https://w3id.org/battinfo/{base_namespace}/{{uid}}.")
        if uid is not None:
            _assert_id_matches_uid(id, _normalized_dashed_uid(uid))
        entity_id = id
        _, dashed_uid = _iri_tail(entity_id)
    else:
        dashed_uid = _normalized_dashed_uid(uid)
        entity_id = f"https://w3id.org/battinfo/{base_namespace}/{dashed_uid}"

    instance: dict[str, Any] = {
        "id": entity_id,
        f"{family}_spec_id": spec_id,
        "short_id": dashed_uid.replace("-", "")[:6],
    }
    instance.update(body or {})
    if name is not None:
        instance["name"] = name
    if lot_id is not None:
        instance["lot_id"] = lot_id
    org = _org_value(supplier)
    if org is not None:
        instance["supplier"] = org
    if dataset_ids:
        for dataset_id in dataset_ids:
            if not DATASET_IRI_RE.fullmatch(dataset_id):
                raise ValueError("dataset_ids entries must match https://w3id.org/battinfo/dataset/{uid}.")
        instance["datasets"] = [{"id": dataset_id, "role": "raw"} for dataset_id in dataset_ids]

    record: dict[str, Any] = {
        "schema_version": "0.1.0",
        family: instance,
        "provenance": {"source_type": source_type, "retrieved_at": _to_unix_time(retrieved_at) or _now_unix()},
    }
    if source_url is not None:
        record["provenance"]["source_url"] = source_url
    citation_value = _citation_url_value(citation)
    if citation_value is not None:
        record["provenance"]["citation"] = citation_value
    if notes:
        record["notes"] = list(notes)
    return record_to_snake_aliases(record)


def create_component_spec(family: str, *, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical component-spec document for a family (electrode, separator, …)."""
    record = _record_from_component_spec(family, **fields)
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def create_component_instance(family: str, *, validate: bool = True, **fields: Any) -> dict[str, Any]:
    """Create a canonical component (instance) document for a family."""
    record = _record_from_component_instance(family, **fields)
    if validate:
        _validate_canonical_record(record, policy=DEFAULT_POLICY)
    return record


def _save_component(
    record: dict[str, Any] | PathLike,
    *,
    source_root: PathLike = DEFAULT_REGISTRATION_SOURCE_ROOT,
    mode: str = REGISTER_MODE_CREATE_ONLY,
    duplicate_policy: str = DUPLICATE_POLICY_ERROR,
    resolve_references: bool = True,
    validate: bool = True,
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, Any]:
    doc = _load_json(_as_path(record)) if isinstance(record, (str, Path)) else dict(record)
    return save_record(
        doc,
        source_root=source_root,
        mode=mode,
        duplicate_policy=duplicate_policy,
        resolve_references=resolve_references,
        build_jsonld=False,
        build_html=False,
        validate=validate,
        validation_policy=validation_policy,
        dry_run=dry_run,
    )


def save_component_spec(family: str, record: dict[str, Any] | PathLike, **kwargs: Any) -> dict[str, Any]:
    """Save a component-spec record (or path) for a family."""
    return _save_component(record, **kwargs)


def save_component_instance(family: str, record: dict[str, Any] | PathLike, **kwargs: Any) -> dict[str, Any]:
    """Save a component (instance) record (or path) for a family."""
    return _save_component(record, **kwargs)


def _query_component(
    record_key: str,
    directory: Path,
    *,
    id: str | None,
    name: str | None,
    short_id_prefix: str | None,
    spec_ref_field: str | None,
    spec_id: str | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in _iter_json_files(directory):
        doc = _load_json(path)
        body = doc.get(record_key)
        if not isinstance(body, Mapping):
            continue
        rec = {
            "id": body.get("id"),
            "name": body.get("name"),
            "short_id": body.get("short_id"),
            "path": str(path),
            "record": doc,
        }
        if spec_ref_field:
            rec[spec_ref_field] = body.get(spec_ref_field)
        records.append(rec)

    filtered: list[dict[str, Any]] = []
    for rec in records:
        if id is not None and rec.get("id") != id:
            continue
        if not _str_eq(rec.get("name"), name):
            continue
        if short_id_prefix and not str(rec.get("short_id", "")).lower().startswith(short_id_prefix.lower()):
            continue
        if spec_id is not None and spec_ref_field and rec.get(spec_ref_field) != spec_id:
            continue
        filtered.append(rec)
    return _paginate(filtered, limit=limit, offset=offset)


def query_component_specs(
    family: str,
    *,
    directory: PathLike | None = None,
    id: str | None = None,
    name: str | None = None,
    short_id_prefix: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query reusable component specifications for a family."""
    d = _as_path(directory) if directory is not None else EXAMPLES_ROOT / f"{family.replace('_', '-')}-spec"
    return _query_component(
        f"{family}_spec", d, id=id, name=name, short_id_prefix=short_id_prefix,
        spec_ref_field=None, spec_id=None, limit=limit, offset=offset,
    )


def query_component_instances(
    family: str,
    *,
    directory: PathLike | None = None,
    id: str | None = None,
    name: str | None = None,
    short_id_prefix: str | None = None,
    spec_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query physical component instances for a family."""
    d = _as_path(directory) if directory is not None else EXAMPLES_ROOT / family.replace("_", "-")
    return _query_component(
        family, d, id=id, name=name, short_id_prefix=short_id_prefix,
        spec_ref_field=f"{family}_spec_id", spec_id=spec_id, limit=limit, offset=offset,
    )


def template_component_spec(family: str, *, name: str | None = None, uid: str | None = TEMPLATE_UID) -> dict[str, Any]:
    """Build a starter component-spec document for a family."""
    return _record_from_component_spec(
        family, name=name or f"Example {family}", uid=uid,
        notes=[f"Template-generated {family}-spec. Fill in the holder body before saving."],
    )


def template_component_instance(
    family: str,
    *,
    spec_id: str | None = None,
    uid: str | None = TEMPLATE_UID,
) -> dict[str, Any]:
    """Build a starter component (instance) document for a family."""
    return _record_from_component_instance(
        family, spec_id=spec_id or f"https://w3id.org/battinfo/{family}-spec/0000-0000-0000-0000", uid=uid,
        notes=[f"Template-generated {family} instance. Set {family}_spec_id before saving."],
    )


# Per-family convenience wrappers (create_electrode_spec, save_electrode_spec, …).
_COMPONENT_WRAPPER_NAMES: list[str] = []
for _family in COMPONENT_FAMILIES:
    for _verb, _generic, _suffix in (
        ("create", create_component_spec, "spec"),
        ("save", save_component_spec, "spec"),
        ("template", template_component_spec, "spec"),
        ("create", create_component_instance, "instance"),
        ("save", save_component_instance, "instance"),
        ("template", template_component_instance, "instance"),
    ):
        _wname = f"{_verb}_{_family}_spec" if _suffix == "spec" else f"{_verb}_{_family}"
        globals()[_wname] = functools.partial(_generic, _family)
        _COMPONENT_WRAPPER_NAMES.append(_wname)
    _qspec = f"query_{_family}_specs"
    _qinst = f"query_{_family}s" if not _family.endswith("s") else f"query_{_family}"
    globals()[_qspec] = functools.partial(query_component_specs, _family)
    globals()[_qinst] = functools.partial(query_component_instances, _family)
    _COMPONENT_WRAPPER_NAMES.extend([_qspec, _qinst])


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

    cell_specs: list[dict[str, Any]] = []
    cell_instances: list[dict[str, Any]] = []
    test_specs: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    datasets: list[dict[str, Any]] = []
    material_specs: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    cell_specs_dir = src_root / "cell-spec"
    cell_instances_dir = src_root / "cell-instance"
    test_protocols_dir = src_root / "test-protocol"
    tests_dir = src_root / "test"
    datasets_dir = src_root / "dataset"
    material_specs_dir = src_root / "material-spec"
    materials_dir = src_root / "material"

    for path in sorted(cell_specs_dir.glob(glob)) if cell_specs_dir.exists() else []:
        try:
            doc = _load_json(path)
            if validate:
                _validate_canonical_record(doc, source_root=src_root, policy=validation_policy)
            product = doc.get("cell_spec")
            if isinstance(product, Mapping):
                entity = product
            else:
                legacy = doc.get("cell_spec")
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
            cell_specs.append(
                {
                    "id": entity["id"],
                    "short_id": entity.get("short_id") or _short_id_from_iri(entity["id"]),
                    "manufacturer": manufacturer_name,
                    "model_name": entity.get("model") or entity.get("model_name"),
                    "chemistry": entity.get("chemistry"),
                    "format": entity.get("cell_format") or entity.get("format"),
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
                    "cell_spec_id": inst.get("cell_spec_id"),
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
            protocol = doc.get("test_spec", {})
            prov = doc.get("provenance", {})
            if not isinstance(protocol, Mapping) or not isinstance(protocol.get("id"), str):
                raise ValueError("missing test_protocol.id")
            test_specs.append(
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

    for path in sorted(material_specs_dir.glob(glob)) if material_specs_dir.exists() else []:
        try:
            doc = _load_json(path)
            if validate:
                _validate_canonical_record(doc, source_root=src_root, policy=validation_policy)
            spec = doc.get("material_spec", {})
            prov = doc.get("provenance", {})
            if not isinstance(spec, Mapping) or not isinstance(spec.get("id"), str):
                raise ValueError("missing material_spec.id")
            material_specs.append(
                {
                    "id": spec["id"],
                    "short_id": spec.get("short_id") or _short_id_from_iri(spec["id"]),
                    "name": spec.get("name"),
                    "material_class": spec.get("material_class"),
                    "formula": spec.get("formula"),
                    "manufacturer": spec.get("manufacturer"),
                    "source_type": prov.get("source_type") if isinstance(prov, Mapping) else None,
                    "path": _relative_or_absolute(path, src_root),
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({"file": _relative_or_absolute(path, src_root), "error": str(exc)})

    for path in sorted(materials_dir.glob(glob)) if materials_dir.exists() else []:
        try:
            doc = _load_json(path)
            if validate:
                _validate_canonical_record(doc, source_root=src_root, policy=validation_policy)
            material = doc.get("material", {})
            prov = doc.get("provenance", {})
            if not isinstance(material, Mapping) or not isinstance(material.get("id"), str):
                raise ValueError("missing material.id")
            materials.append(
                {
                    "id": material["id"],
                    "material_spec_id": material.get("material_spec_id"),
                    "short_id": material.get("short_id") or _short_id_from_iri(material["id"]),
                    "name": material.get("name"),
                    "lot_id": material.get("lot_id"),
                    "source_type": prov.get("source_type") if isinstance(prov, Mapping) else None,
                    "path": _relative_or_absolute(path, src_root),
                }
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({"file": _relative_or_absolute(path, src_root), "error": str(exc)})

    # Component families (electrode/separator/…): one generic indexer per family.
    component_index: dict[str, list[dict[str, Any]]] = {}
    component_count = 0
    for family in COMPONENT_FAMILIES:
        _base = family.replace("_", "-")
        for record_key, subdir in ((f"{family}_spec", f"{_base}-spec"), (family, _base)):
            directory = src_root / subdir
            rows: list[dict[str, Any]] = []
            for path in sorted(directory.glob(glob)) if directory.exists() else []:
                try:
                    doc = _load_json(path)
                    if validate:
                        _validate_canonical_record(doc, source_root=src_root, policy=validation_policy)
                    body = doc.get(record_key, {})
                    if not isinstance(body, Mapping) or not isinstance(body.get("id"), str):
                        raise ValueError(f"missing {record_key}.id")
                    row = {
                        "id": body["id"],
                        "short_id": body.get("short_id") or _short_id_from_iri(body["id"]),
                        "name": body.get("name"),
                        "path": _relative_or_absolute(path, src_root),
                    }
                    if record_key.endswith("_spec"):
                        row["polarity"] = body.get("polarity")
                    else:
                        row[f"{family}_spec_id"] = body.get(f"{family}_spec_id")
                    rows.append(row)
                except Exception as exc:  # noqa: BLE001
                    failures.append({"file": _relative_or_absolute(path, src_root), "error": str(exc)})
            component_index[subdir] = rows
            component_count += len(rows)

    out: dict[str, Any] = {
        "build_timestamp": _now_iso(),
        "source_root": str(src_root),
        "cell_spec_count": len(cell_specs),
        "cell_instance_count": len(cell_instances),
        "test_spec_count": len(test_specs),
        "test_count": len(tests),
        "dataset_count": len(datasets),
        "material_spec_count": len(material_specs),
        "material_count": len(materials),
        "component_count": component_count,
        "total_count": (
            len(cell_specs)
            + len(cell_instances)
            + len(test_specs)
            + len(tests)
            + len(datasets)
            + len(material_specs)
            + len(materials)
            + component_count
        ),
        "failed": len(failures),
        "failures": failures,
        "cell_specs": cell_specs,
        "cell_instances": cell_instances,
        "test_specs": test_specs,
        "tests": tests,
        "datasets": datasets,
        "material_specs": material_specs,
        "materials": materials,
        "components": component_index,
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

    cell_spec_count = (
        int(doc["cell_spec_count"])
        if isinstance(doc.get("cell_spec_count"), int)
        else len(doc.get("cell_specs", [])) if isinstance(doc.get("cell_specs"), list) else 0
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
    test_spec_count = (
        int(doc["test_spec_count"])
        if isinstance(doc.get("test_spec_count"), int)
        else len(doc.get("test_specs", [])) if isinstance(doc.get("test_specs"), list) else 0
    )
    dataset_count = (
        int(doc["dataset_count"])
        if isinstance(doc.get("dataset_count"), int)
        else len(doc.get("datasets", [])) if isinstance(doc.get("datasets"), list) else 0
    )
    material_spec_count = (
        int(doc["material_spec_count"])
        if isinstance(doc.get("material_spec_count"), int)
        else len(doc.get("material_specs", [])) if isinstance(doc.get("material_specs"), list) else 0
    )
    material_count = (
        int(doc["material_count"])
        if isinstance(doc.get("material_count"), int)
        else len(doc.get("materials", [])) if isinstance(doc.get("materials"), list) else 0
    )
    total_count = (
        int(doc["total_count"])
        if isinstance(doc.get("total_count"), int)
        else cell_spec_count
        + cell_instance_count
        + test_spec_count
        + test_count
        + dataset_count
        + material_spec_count
        + material_count
    )
    failed = int(doc["failed"]) if isinstance(doc.get("failed"), int) else 0

    out = {
        "build_timestamp": doc.get("build_timestamp"),
        "cell_spec_count": cell_spec_count,
        "cell_instance_count": cell_instance_count,
        "test_spec_count": test_spec_count,
        "test_count": test_count,
        "dataset_count": dataset_count,
        "material_spec_count": material_spec_count,
        "material_count": material_count,
        "total_count": total_count,
        "failed": failed,
    }
    if index_path is not None:
        out["index_path"] = index_path
    return out


__all__ = [
    "RegistryError",
    "RegistryClientError",
    "RegistryTransientError",
    "CellSpecificationInput",
    "CellInstanceInput",
    "MaterialSpecInput",
    "MaterialInput",
    "create_material_spec",
    "create_material",
    "save_material_spec",
    "save_material",
    "query_material_specs",
    "query_materials",
    "template_material_spec",
    "template_material",
    "create_component_spec",
    "create_component_instance",
    "save_component_spec",
    "save_component_instance",
    "query_component_specs",
    "query_component_instances",
    "template_component_spec",
    "template_component_instance",
    "DatasetInput",
    "TestSpecInput",
    "TestInput",
    "build_cell_spec_library_rdf",
    "build_index",
    "build_curated_cell_spec_submission",
    "create_cell_instance",
    "index_stats",
    "publish_curated_cell_spec",
    "publish_batch",
    "publish_record",
    "promote_staging_cell_spec",
    "promote_staging_cell_specs",
    "promote_staging_dataset",
    "promote_staging_datasets",
    "query",
    "query_cell_instances",
    "query_library_cell_specs",
    "query_cell_specs",
    "query_datasets",
    "query_test_specs",
    "query_tests",
    "save_batch",
    "save_cell_instance",
    "save_cell_spec",
    "save_dataset",
    "save_library_cell_spec",
    "save_test_spec",
    "resolve_cell_spec_id",
    "save_record",
    "save_test",
    "template_library_cell_spec",
    "template_cell_instance",
    "template_cell_spec_draft",
    "template_cell_spec",
    "template_dataset",
    "template_test_spec_draft",
    "template_test_spec",
    "template_test",
    "submit_publication_package",
    "validate_staging_cell_spec",
    "validate_staging_cell_specs",
    "validate_staging_dataset",
    "validate_staging_datasets",
    "TestProtocolInput",
    "save_test_protocol",
    "template_test_protocol",
    "template_test_protocol_draft",
    "query_test_protocols",
]

# Per-family component wrappers (create_electrode_spec, query_electrode_specs, …).
__all__ += _COMPONENT_WRAPPER_NAMES

TestProtocolInput = TestSpecInput  # backward compat alias
save_test_protocol = save_test_spec  # backward compat alias
template_test_protocol = template_test_spec  # backward compat alias
template_test_protocol_draft = template_test_spec_draft  # backward compat alias
query_test_protocols = query_test_specs  # backward compat alias

