"""build_index / index_stats over the canonical record store.

Split from the former monolithic ``battinfo/api.py`` (beta-hardening 4.2);
import the public surface from ``battinfo.api``, not from this module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from battinfo._jsonio import read_record_json as _load_json
from battinfo._jsonio import write_json as _write_json
from battinfo._util import _as_path, _now_iso
from battinfo.api._shared import (
    CELL_IRI_RE,
    DEFAULT_INDEX_SOURCE_ROOT,
    PathLike,
    _relative_or_absolute,
    _short_id_from_iri,
    _validate_canonical_record,
)
from battinfo.entities import (
    COMPONENT_FAMILIES,
)
from battinfo.validate.core import DEFAULT_POLICY, ValidationPolicy


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
