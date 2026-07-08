"""Shared constants, IRI regexes, and cross-cutting validation/ID helpers for the api package.

Split from the former monolithic ``battinfo/api.py`` (beta-hardening 4.2);
import the public surface from ``battinfo.api``, not from this module.
"""
from __future__ import annotations

import difflib
import json
import math
import re
import secrets
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from battinfo._util import _now_unix
from battinfo.bundle import (
    BatteryTestType,
)
from battinfo.entities import (
    ENTITY_KINDS,
    entity_id_from_doc,
    kind_for_doc,
)
from battinfo.validate.core import DEFAULT_POLICY, ValidationPolicy
from battinfo.validate.friendly import format_report_errors
from battinfo.validate.publication import validate_publication_report
from battinfo.validate.record import validate_record_report
from battinfo.validate.schema import validate_schema_data

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
# spec/ is canonical; the superseded material-spec/ form stays accepted as
# input so pre-consolidation records keep loading (IDENTIFIER_POLICY 6.1).
MATERIAL_SPEC_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/(?:spec|material-spec)/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)
MATERIAL_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/material/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)

# The battinfo package root (this file lives in the api/ subpackage, one level down).
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
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


def _to_unix_time(value: object) -> int | None:
    """Best-effort conversion to Unix seconds; ``None`` for anything unconvertible.

    Never raises — call sites decide whether an unconvertible *present* value is an
    error (see ``_resolved_time``).
    """
    if isinstance(value, bool):
        # bool is an int subclass; True/False are never meaningful timestamps.
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return int(value)
    if isinstance(value, datetime):
        # Anchor naive datetimes to UTC (same rationale as for strings below).
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp())
    if isinstance(value, str):
        txt = value.strip()
        if not txt:
            return None
        if txt.isdigit():
            # Digit runs shorter than 9 chars are ambiguous: "20240101" reads as a
            # calendar date, not epoch second 20,240,101. Require 9+ digits (i.e.
            # timestamps from 1973 onward) for a bare digit string to count as Unix
            # seconds; use an int, an ISO string, or a datetime for anything else.
            # str.isdigit() also accepts non-ASCII digits ("²") that int() rejects,
            # hence the try/except.
            if len(txt) < 9:
                return None
            try:
                return int(txt)
            except ValueError:
                return None
        try:
            parsed = datetime.fromisoformat(txt.replace("Z", "+00:00"))
        except ValueError:
            return None
        # A bare date ("2022-01-15") or a time without an offset parses to a naive
        # datetime; .timestamp() would then read it in the machine's local zone, making
        # the resulting Unix time timezone-dependent (non-reproducible across machines).
        # Anchor naive values to UTC so the same input always yields the same timestamp.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    return None


def _resolved_time(field_name: str, value: object, default: int) -> int:
    """Save-time canonicalization of an optional timestamp field: an absent value takes
    *default*; a present one converts to Unix seconds, raising (never silently substituting
    the default) when it cannot be parsed. Epoch zero is a valid timestamp."""
    if value is None:
        return default
    converted = _to_unix_time(value)
    if converted is None:
        raise ValueError(
            f"{field_name} must be a Unix timestamp (int), ISO 8601 datetime string, "
            f"or datetime/date object; got {value!r}."
        )
    return converted


def _resolved_retrieved_at(value: object) -> int:
    """Save-time canonicalization of provenance ``retrieved_at``: default a missing value to
    now; convert a provided one to Unix seconds, raising (never silently substituting the
    current time) when it cannot be parsed."""
    return _resolved_time("retrieved_at", value, _now_unix())


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


def _validate_schema(doc: dict[str, Any], schema_rel_path: str) -> None:
    schema = json.loads((SCHEMAS_ROOT / schema_rel_path).read_text(encoding="utf-8"))
    report = validate_schema_data(doc, schema)
    if report.ok:
        return
    raise ValueError(format_report_errors(report, prefix="Schema validation failed"))


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
    raise ValueError(format_report_errors(report, prefix=prefix))


def _validate_publication_artifact(
    doc: dict[str, Any],
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> None:
    report = validate_publication_report(doc, policy=policy)
    if report.ok:
        return
    raise ValueError(format_report_errors(report, prefix="Publication validation failed"))


def _logical_entity_type_from_doc(doc: Mapping[str, Any]) -> str:
    """Return the logical entity type from document structure, independent of IRI namespace."""
    kind = kind_for_doc(doc)
    if kind is None:
        raise ValueError(
            "Cannot determine entity type: expected cell_spec, cell_instance, test_spec, "
            "test, dataset, material_spec, or material key."
        )
    return kind.entity_type


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


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


# ── Generic component spec/instance factory ───────────────────────────────────
# Component families (electrode/electrolyte/separator/current-collector/housing) all
# follow one spec+instance shape that reuses an existing embedded holder. These generic
# functions are parameterized by family; thin per-family wrappers are generated below.

_UID_TAIL = r"[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}"


def _component_iri_re(namespace: str) -> re.Pattern[str]:
    return re.compile(rf"^https://w3id\.org/battinfo/{re.escape(namespace)}/{_UID_TAIL}$")


def _spec_iri_re(family_namespace: str) -> re.Pattern[str]:
    """Spec IRIs mint under the shared spec/ namespace (IDENTIFIER_POLICY 6.1);
    the superseded per-family '{family}-spec/' form stays accepted as input so
    records minted before the consolidation keep loading (never break an IRI)."""
    return re.compile(
        rf"^https://w3id\.org/battinfo/(?:spec|{re.escape(family_namespace)})/{_UID_TAIL}$"
    )
