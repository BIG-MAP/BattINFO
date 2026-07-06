"""save_*/query_* record-store operations, record minting, and bulk-save integration.

Split from the former monolithic ``battinfo/api.py`` (beta-hardening 4.2);
import the public surface from ``battinfo.api``, not from this module.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from battinfo._jsonio import read_record_json as _load_json
from battinfo._jsonio import write_json as _write_json
from battinfo._record_index import active_record_cache, bulk_save_session
from battinfo._util import _as_path, _citation_url_value, _now_unix
from battinfo.api._index import build_index
from battinfo.api._resolver import publish_record
from battinfo.api._shared import (
    CELL_IRI_RE,
    CELL_SPEC_IRI_RE,
    DATASET_IRI_RE,
    DEFAULT_CELL_INSTANCES_DIR,
    DEFAULT_CELL_TYPES_DIR,
    DEFAULT_DATASETS_DIR,
    DEFAULT_LIBRARY_AGGREGATE_JSONLD,
    DEFAULT_LIBRARY_CELL_TYPES_DIR,
    DEFAULT_LIBRARY_MANIFEST_JSON,
    DEFAULT_LIBRARY_RDF_CELL_TYPES_DIR,
    DEFAULT_PACKAGED_LIBRARY_CELL_TYPES_DIR,
    DEFAULT_PUBLISH_SOURCES,
    DEFAULT_REGISTRATION_SOURCE_ROOT,
    DEFAULT_TEST_PROTOCOLS_DIR,
    DEFAULT_TESTS_DIR,
    DUPLICATE_POLICIES,
    DUPLICATE_POLICY_ERROR,
    DUPLICATE_POLICY_RETURN_EXISTING,
    REGISTER_MODE_CREATE_ONLY,
    REGISTER_MODE_UPSERT,
    REGISTER_MODES,
    TEST_IRI_RE,
    TEST_PROTOCOL_IRI_RE,
    PathLike,
    _component_iri_re,
    _entity_id,
    _in_range,
    _iri_tail,
    _iter_json_files,
    _logical_entity_type_from_doc,
    _normalized_dashed_uid,
    _paginate,
    _quantity_numeric_value,
    _resolved_retrieved_at,
    _resolved_time,
    _short_id_from_iri,
    _spec_numeric_value,
    _str_contains,
    _str_eq,
    _str_fuzzy_match,
    _validate_canonical_record,
    _validate_schema,
)
from battinfo.bundle import (
    SCHEMA_VERSION,
    Cell,
    CellSpec,
    Dataset,
    Test,
    TestSpec,
    stamp_provenance,
)
from battinfo.entities import (
    entity_types_for_namespace,
    iter_entity_files,
    save_entity_path,
)
from battinfo.validate.core import DEFAULT_POLICY, ValidationPolicy
from battinfo.validate.friendly import format_report_errors
from battinfo.validate.pydantic import validate_json
from battinfo.validate.references import validate_references_report
from battinfo.workflows.map import run_mapping


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
    # cell-spec schema — their structure is enforced by the cell-spec model upstream.
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
    are normally authored via ``cell_description()`` and saved as a ``CellSpec``
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

    # source_file/source_type are recorded only when provided — no fabricated placeholders.
    provenance: dict[str, Any] = {
        "retrieved_at": _resolved_retrieved_at(draft.get("retrieved_at")),
    }
    if draft.get("source_file") is not None:
        provenance["source_file"] = draft["source_file"]
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
        "schema_version": SCHEMA_VERSION,
        "cell_instance": {
            "id": instance_id,
            "cell_spec_id": resolved_cell_spec_id,
            "short_id": dashed_uid.replace("-", "")[:6],
        },
        "provenance": stamp_provenance({
            "source_type": source_type,
            "retrieved_at": _now_unix(),
        }),
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


def _candidate_types_for_namespace(namespace: str) -> list[str]:
    """Map an IRI namespace to the candidate internal entity types to search."""
    return entity_types_for_namespace(namespace)


def _find_record_path_by_id(entity_id: str, source_root: Path) -> Path | None:
    namespace, uid = _iri_tail(entity_id)
    cache = active_record_cache(source_root)
    if cache is not None:
        found = cache.lookup(entity_id, _candidate_types_for_namespace(namespace))
        return found[0] if found is not None else None
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


_COMPONENT_SPEC_REF_NAMESPACES = {
    "positive_electrode_spec_id": "electrode-spec",
    "negative_electrode_spec_id": "electrode-spec",
    "electrolyte_spec_id": "electrolyte-spec",
    "separator_spec_id": "separator-spec",
    "housing_spec_id": "housing-spec",
}


def _record_from_cell_spec(spec: CellSpec) -> dict[str, Any]:
    # Validate component-spec reference IRIs at the input boundary.
    for field_name, namespace in _COMPONENT_SPEC_REF_NAMESPACES.items():
        value = getattr(spec, field_name)
        if value is not None and not _component_iri_re(namespace).fullmatch(value):
            raise ValueError(f"{field_name} must match https://w3id.org/battinfo/{namespace}/{{uid}}.")
    # Mint / validate the canonical IRI — the one piece of canonicalization the model does not do.
    return _mint_cell_spec_record(spec)


def _seed_part(value: str | None, fallback: str = "") -> str:
    text = (value or "").strip()
    return text or fallback


def _identity_minted_uid(entity_kind: str, entity: Any) -> str:
    """Mint a deterministic uid from the record's natural identity (3.3).

    Seeds mirror the ``Workspace._finalize_*`` minting exactly, so a record
    authored through the workspace and the same record saved through ``save_*``
    land on the same IRI — and re-running an identical ingest is a no-op
    (``status: exists`` / ``updated`` with ``content_changed: False``) instead
    of a duplicate corpus.

    Natural keys per record type:
    - cell-spec:      manufacturer :: model :: format :: chemistry :: size_code
    - cell:           cell_spec_id :: serial_number :: batch_id :: name
    - test-protocol:  test_kind :: name :: version
    - test:           cell_instance_id :: test_kind :: protocol name :: name
    - dataset:        cell_instance_id :: test_id :: access/download/path :: name

    A record with NO distinguishing identity at all (e.g. a cell instance with
    no serial, batch, or name) falls back to a random uid — two anonymous but
    physically distinct records must never silently dedup into one.
    """
    from battinfo.entities import stable_uid  # noqa: PLC0415 — keep entities import-light at module load

    if entity_kind == "cell-spec":
        if not (_seed_part(entity.manufacturer) or _seed_part(entity.model)):
            return _normalized_dashed_uid(None)
        seed = "::".join(
            [
                _seed_part(entity.manufacturer, "unknown-manufacturer"),
                _seed_part(entity.model, "unknown-model"),
                _seed_part(entity.format, "unknown-format"),
                _seed_part(entity.chemistry, "unknown-chemistry"),
                entity.size_code or "",
            ]
        )
    elif entity_kind == "cell":
        name = entity.name or entity.serial_number or entity.batch_id
        if not _seed_part(name):
            return _normalized_dashed_uid(None)
        seed = "::".join(
            [
                _seed_part(entity.cell_spec_id, "unknown-cell-spec"),
                entity.serial_number or "",
                entity.batch_id or "",
                _seed_part(name, "cell"),
            ]
        )
    elif entity_kind == "test-protocol":
        if not (_seed_part(entity.name) or _seed_part(entity.version)):
            return _normalized_dashed_uid(None)
        seed = "::".join(
            [
                _seed_part(getattr(entity, "test_kind", None), "other"),
                _seed_part(entity.name, "test-protocol"),
                entity.version or "",
            ]
        )
    elif entity_kind == "test":
        protocol = getattr(entity, "protocol", None)
        protocol_name = (getattr(protocol, "name", None) if protocol is not None else None) or "test"
        name = entity.name or protocol_name
        if not (_seed_part(entity.name) or _seed_part(getattr(protocol, "name", None) if protocol else None)):
            return _normalized_dashed_uid(None)
        seed = "::".join(
            [
                _seed_part(entity.cell_instance_id, "unknown-cell"),
                _seed_part(getattr(entity, "test_kind", None), "other"),
                protocol_name,
                _seed_part(name, "test"),
            ]
        )
    elif entity_kind == "dataset":
        locator = entity.access_url or entity.download_url or entity.dataset_path or ""
        if not (_seed_part(entity.name) or _seed_part(locator) or _seed_part(entity.test_id)):
            return _normalized_dashed_uid(None)
        seed = "::".join(
            [
                _seed_part(entity.cell_instance_id, "unknown-cell"),
                entity.test_id or "",
                locator,
                _seed_part(entity.name or entity.dataset_path or entity.access_url, "dataset"),
            ]
        )
    else:  # pragma: no cover — programming error, not user input
        raise ValueError(f"No identity-minting policy for entity kind {entity_kind!r}.")
    return stable_uid(seed)


def _mint_cell_spec_record(spec: CellSpec) -> dict[str, Any]:
    if spec.id is not None:
        if not CELL_SPEC_IRI_RE.fullmatch(spec.id):
            raise ValueError("cell spec id must match https://w3id.org/battinfo/spec/{uid}.")
        if spec.uid is not None:
            _assert_id_matches_uid(spec.id, _normalized_dashed_uid(spec.uid))
        entity_id = spec.id
    else:
        dashed = _normalized_dashed_uid(spec.uid) if spec.uid is not None else _identity_minted_uid("cell-spec", spec)
        entity_id = f"https://w3id.org/battinfo/spec/{dashed}"
    # Finalize a copy (mint the id, apply save-time provenance defaults) without mutating the
    # caller. source_type is schema-required, so an unprovided one takes the documented
    # category default; source_file is optional and is recorded only when the author provided
    # it — a fabricated placeholder ("manual.json") would masquerade as real provenance.
    finalized = spec.model_copy(deep=True)
    finalized.id = entity_id
    if finalized.source.type is None:
        finalized.source.type = "datasheet"
    finalized.source.retrieved_at = _resolved_retrieved_at(finalized.source.retrieved_at)
    return finalized.to_record()


def _record_from_cell_instance(instance: Cell) -> dict[str, Any]:
    if instance.cell_spec_id is None or not CELL_SPEC_IRI_RE.fullmatch(instance.cell_spec_id):
        raise ValueError("cell_spec_id must match https://w3id.org/battinfo/spec/{uid}.")
    for dataset_id in instance.dataset_ids:
        if not DATASET_IRI_RE.fullmatch(dataset_id):
            raise ValueError("dataset_ids entries must match https://w3id.org/battinfo/dataset/{uid}.")
    if instance.id is not None:
        if not CELL_IRI_RE.fullmatch(instance.id):
            raise ValueError("cell-instance id must match https://w3id.org/battinfo/cell/{uid}.")
        if instance.uid is not None:
            _assert_id_matches_uid(instance.id, _normalized_dashed_uid(instance.uid))
        entity_id = instance.id
    else:
        dashed = (
            _normalized_dashed_uid(instance.uid)
            if instance.uid is not None
            else _identity_minted_uid("cell", instance)
        )
        entity_id = f"https://w3id.org/battinfo/cell/{dashed}"
    # Finalize a copy (mint the id, convert timestamps, apply save-time provenance defaults).
    finalized = instance.model_copy(deep=True)
    finalized.id = entity_id
    for _time_field in ("manufactured_at", "expires_at"):
        value = getattr(finalized, _time_field)
        if value is not None:
            setattr(finalized, _time_field, _resolved_time(_time_field, value, 0))
    if finalized.source.type is None:
        finalized.source.type = "measurement"  # schema-required; documented category default
    finalized.source.retrieved_at = _resolved_retrieved_at(finalized.source.retrieved_at)
    return finalized.to_record()


def _record_from_dataset(dataset: Dataset) -> dict[str, Any]:
    if dataset.id is not None:
        if not DATASET_IRI_RE.fullmatch(dataset.id):
            raise ValueError("dataset id must match https://w3id.org/battinfo/dataset/{uid}.")
        entity_id = dataset.id
    else:
        dashed = (
            _normalized_dashed_uid(dataset.uid)
            if dataset.uid is not None
            else _identity_minted_uid("dataset", dataset)
        )
        entity_id = f"https://w3id.org/battinfo/dataset/{dashed}"

    related_cells = [*dataset.related_cell_ids, *([dataset.cell_instance_id] if dataset.cell_instance_id else [])]
    for cell_id in related_cells:
        if not CELL_IRI_RE.fullmatch(cell_id):
            raise ValueError("related_cell_ids entries must match https://w3id.org/battinfo/cell/{uid}.")
    related_tests = [*dataset.related_test_ids, *([dataset.test_id] if dataset.test_id else [])]
    for test_id in related_tests:
        if not TEST_IRI_RE.fullmatch(test_id):
            raise ValueError("related_test_ids entries must match https://w3id.org/battinfo/test/{uid}.")

    finalized = dataset.model_copy(deep=True)
    finalized.id = entity_id
    # Save-time canonicalization: dates default to now and convert to Unix; provenance
    # gets the schema-required source_type category default and a retrieval timestamp. The
    # model's to_record() handles the schema.org field mapping and distribution assembly.
    created = _resolved_time("created_at", finalized.created_at, _now_unix())
    finalized.created_at = created
    finalized.modified_at = _resolved_time("modified_at", finalized.modified_at, created)
    finalized.published_at = _resolved_time("published_at", finalized.published_at, created)
    if finalized.source.type is None:
        finalized.source.type = "other"
    finalized.source.retrieved_at = _resolved_retrieved_at(finalized.source.retrieved_at)
    return finalized.to_record()


def _record_from_test(test: Test) -> dict[str, Any]:
    if test.cell_instance_id is None or not CELL_IRI_RE.fullmatch(test.cell_instance_id):
        raise ValueError("cell_id must match https://w3id.org/battinfo/cell/{uid}.")
    if test.protocol_id is not None and not TEST_PROTOCOL_IRI_RE.fullmatch(test.protocol_id):
        raise ValueError("protocol_id must match https://w3id.org/battinfo/spec/{uid}.")
    for dataset_id in test.dataset_ids:
        if not DATASET_IRI_RE.fullmatch(dataset_id):
            raise ValueError("dataset_ids entries must match https://w3id.org/battinfo/dataset/{uid}.")
    if test.id is not None:
        if not TEST_IRI_RE.fullmatch(test.id):
            raise ValueError("test id must match https://w3id.org/battinfo/test/{uid}.")
        if test.uid is not None:
            _assert_id_matches_uid(test.id, _normalized_dashed_uid(test.uid))
        entity_id = test.id
    else:
        dashed = _normalized_dashed_uid(test.uid) if test.uid is not None else _identity_minted_uid("test", test)
        entity_id = f"https://w3id.org/battinfo/test/{dashed}"
    # Finalize a copy (mint the id, convert timestamps, apply save-time provenance defaults).
    finalized = test.model_copy(deep=True)
    finalized.id = entity_id
    for _time_field in ("started_at", "ended_at"):
        value = getattr(finalized, _time_field)
        if value is not None:
            setattr(finalized, _time_field, _resolved_time(_time_field, value, 0))
    if finalized.source.type is None:
        finalized.source.type = "measurement"  # schema-required; documented category default
    finalized.source.retrieved_at = _resolved_retrieved_at(finalized.source.retrieved_at)
    return finalized.to_record()


def _record_from_test_protocol(spec: TestSpec) -> dict[str, Any]:
    if spec.id is not None:
        if not TEST_PROTOCOL_IRI_RE.fullmatch(spec.id):
            raise ValueError("test protocol id must match https://w3id.org/battinfo/spec/{uid}.")
        entity_id = spec.id
    else:
        dashed = (
            _normalized_dashed_uid(spec.uid)
            if spec.uid is not None
            else _identity_minted_uid("test-protocol", spec)
        )
        entity_id = f"https://w3id.org/battinfo/spec/{dashed}"

    # The model already parses the PyBaMM-style experiment/steps authoring input into the
    # canonical `method` and computes `facets` in to_record(); the builder only mints the id
    # and applies save-time provenance defaults.
    finalized = spec.model_copy(deep=True)
    finalized.id = entity_id
    if finalized.source.type is None:
        finalized.source.type = "manual"  # schema-required; documented category default
    finalized.source.retrieved_at = _resolved_retrieved_at(finalized.source.retrieved_at)
    return finalized.to_record()


def _resolve_references_for_save(doc: dict[str, Any], source_root: Path) -> None:
    report = validate_references_report(doc, source_root, allow_missing=True)
    if report.ok:
        return
    raise ValueError(format_report_errors(report, prefix="Reference validation failed"))


def _record_content_differs(existing_path: PathLike, new_doc: Mapping[str, Any]) -> bool:
    """True if the record already on disk differs from *new_doc* in a meaningful way.

    Volatile timestamps and identity scaffolding (see ``_strip_volatile``) are ignored, so an
    idempotent re-save of unchanged content reports False and a real edit reports True. A
    missing or unreadable existing file is treated as "differs" (the write is not a no-op)."""
    from battinfo._workspace import _strip_volatile

    try:
        existing = _load_json(_as_path(existing_path))
    except (OSError, ValueError):
        return True
    return _strip_volatile(existing) != _strip_volatile(dict(new_doc))


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
    """Save one canonical BattINFO resource into local source storage and optional resolver artifacts.

    Minting policy: records that arrive without an ``id``/``uid`` are minted
    deterministically from their natural identity key (see
    ``_identity_minted_uid``), so re-running an identical ingest lands on the
    existing records — use ``mode="upsert"`` (no-op re-save reports
    ``content_changed: False``) or ``duplicate_policy="return_existing"``
    for idempotent pipelines. Records with no distinguishing identity fall
    back to a random uid and never silently dedup.
    """
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
    # An upsert that replaces an existing record with genuinely different content (ignoring
    # volatile timestamps) is reported explicitly, so a same-IRI overwrite is never silent —
    # the caller can surface it or choose mode='create_only' to refuse it. (A-4)
    content_changed = False
    if existing_path is not None and mode_normalized == REGISTER_MODE_UPSERT:
        content_changed = _record_content_differs(existing_path, doc)
    payload: dict[str, Any] = {
        "status": "dry-run" if dry_run else operation,
        "id": entity_id,
        "entity_type": entity_type,
        "path": str(target_path),
        "mode": mode_normalized,
        "content_changed": content_changed,
        "published": False,
    }

    if dry_run:
        return payload

    cache = active_record_cache(source_root_path)
    # Inside a bulk session the per-file fsync is skipped: the batch is
    # re-runnable (identical re-saves are no-ops), so a power loss is repaired
    # by re-running the ingest, not by 6 ms of fsync per record.
    _write_json(target_path, doc, durable=cache is None)
    if cache is not None:
        cache.record_saved(entity_id, target_path, entity_type)

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
    draft: CellSpec | dict[str, Any] | PathLike,
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
    """Save a cell-spec from either draft payload or canonical record.

    Drafts without ``id``/``uid`` mint deterministically from the natural key
    (manufacturer :: model :: format :: chemistry :: size_code) — an identical
    re-save is a no-op; a revised datasheet updates the record in place under
    ``mode="upsert"``. See ``save_record`` for the full minting policy.
    """
    from battinfo.bundle import CellSpec as CellSpecificationBundle

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
    if isinstance(draft, Mapping) and isinstance(draft.get("cell_spec"), Mapping):
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
    spec = draft if isinstance(draft, CellSpecificationBundle) else CellSpecificationBundle(**dict(draft))
    record = _record_from_cell_spec(spec)
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
    draft: Cell | dict[str, Any] | PathLike,
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
    """Save a cell-instance from either draft payload or canonical record.

    Drafts without ``id``/``uid`` mint deterministically from the natural key
    (cell_spec_id :: serial_number :: batch_id :: name); instances with no
    serial, batch, or name mint randomly so distinct anonymous cells never
    dedup. See ``save_record`` for the full minting policy.
    """
    from battinfo.bundle import Cell as CellInstanceBundle

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
    instance = draft if isinstance(draft, CellInstanceBundle) else CellInstanceBundle(**dict(draft))
    record = _record_from_cell_instance(instance)
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
    draft: Dataset | dict[str, Any] | PathLike,
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
    dataset = draft if isinstance(draft, DatasetBundle) else DatasetBundle(**dict(draft))
    record = _record_from_dataset(dataset)
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
    draft: Test | dict[str, Any] | PathLike,
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
    test = draft if isinstance(draft, TestBundle) else TestBundle(**dict(draft))
    record = _record_from_test(test)
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
    draft: TestSpec | dict[str, Any] | PathLike,
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
    spec = draft if isinstance(draft, TestSpec) else TestSpec(**dict(draft))
    record = _record_from_test_protocol(spec)
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
    draft: "CellSpec | dict[str, Any] | PathLike",
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
    from battinfo.bundle import CellSpec as CellSpecificationBundle

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

    # One id->path scan for the whole batch instead of one per record (3.4).
    with bulk_save_session(_as_path(source_root)):
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
