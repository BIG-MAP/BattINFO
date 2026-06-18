from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from battinfo.canonical_aliases import record_to_snake_aliases
from battinfo.entities import (
    entity_id_from_doc,
    entity_types_for_namespace,
    iter_entity_files,
    kind_for_doc,
    save_entity_path,
)
from battinfo.validate.core import (
    DEFAULT_POLICY,
    ValidationIssue,
    ValidationPolicy,
    ValidationReport,
    ValidationResult,
    get_validation_policy,
)

SPEC_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/spec/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)
# Aliases kept for clarity — cell specs and test protocols both use spec/ namespace
CELL_SPEC_IRI_RE = SPEC_IRI_RE
TEST_SPEC_IRI_RE = SPEC_IRI_RE
CELL_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/cell/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)
DATASET_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/dataset/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)
TEST_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/test/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)


def _load_json(path: Path) -> dict[str, Any]:
    return record_to_snake_aliases(json.loads(path.read_text(encoding="utf-8")))


def _iri_tail(iri: str) -> tuple[str, str]:
    parts = iri.rstrip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"Invalid IRI: {iri}")
    return parts[-2], parts[-1]


def _entity_id(doc: dict[str, Any]) -> str:
    entity_id = entity_id_from_doc(doc)
    if entity_id is None:
        raise ValueError("Could not locate canonical entity id in document.")
    return entity_id


def _entity_type_from_doc(doc: dict[str, Any]) -> str:
    kind = kind_for_doc(doc)
    if kind is None:
        raise ValueError(
            "Unsupported record type: expected cell_spec, cell_instance, test_spec, "
            "test, dataset, material_spec, or material."
        )
    return kind.entity_type


def _iter_entity_files(entity_type: str, source_root: Path) -> list[Path]:
    return iter_entity_files(entity_type, source_root)


def _save_entity_path(entity_type: str, uid: str, source_root: Path) -> Path:
    return save_entity_path(entity_type, uid, source_root)


def _candidate_types(namespace: str) -> list[str]:
    # A namespace can map to several types (spec/ covers both cell-spec specs and
    # test-protocol specs); the registry resolves this.
    return entity_types_for_namespace(namespace)


def _find_record(entity_id: str, source_root: Path) -> tuple[Path, str] | None:
    namespace, uid = _iri_tail(entity_id)
    for entity_type in _candidate_types(namespace):
        expected = _save_entity_path(entity_type, uid, source_root)
        if expected.exists():
            try:
                doc = _load_json(expected)
                if _entity_id(doc) == entity_id:
                    return expected, _entity_type_from_doc(doc)
            except Exception:  # noqa: BLE001
                pass
        for path in _iter_entity_files(entity_type, source_root):
            if path == expected:
                continue
            try:
                doc = _load_json(path)
                if _entity_id(doc) == entity_id:
                    return path, _entity_type_from_doc(doc)
            except Exception:  # noqa: BLE001
                continue
    return None


def _check_reference(
    *,
    issues: list[ValidationIssue],
    ref_id: str,
    expected_type: str,
    path: str,
    source_root: Path,
    resource_type: str | None,
    missing_message: str,
    mismatch_message: str,
    allow_missing: bool = False,
) -> None:
    found = _find_record(ref_id, source_root)
    if found is None:
        if allow_missing:
            return
        issues.append(
            ValidationIssue(
                code="reference.missing",
                severity="error",
                path=path,
                message=missing_message,
                validator="references",
                resource_type=resource_type,
            )
        )
        return
    _, actual_type = found
    if actual_type != expected_type:
        issues.append(
            ValidationIssue(
                code="reference.type_mismatch",
                severity="error",
                path=path,
                message=mismatch_message,
                validator="references",
                resource_type=resource_type,
            )
        )


def validate_references_report(
    doc: dict[str, Any],
    source_root: str | Path,
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
    allow_missing: bool = False,
) -> ValidationReport:
    resolved_policy = get_validation_policy(policy) if isinstance(policy, str) else policy
    if resolved_policy.references == "off":
        return ValidationReport(policy=resolved_policy)

    root = source_root if isinstance(source_root, Path) else Path(source_root)
    issues: list[ValidationIssue] = []
    resource_type = None
    try:
        resource_type = _entity_type_from_doc(doc)
    except ValueError:
        resource_type = None

    if isinstance(doc.get("cell_instance"), Mapping):
        cell_spec_id = doc["cell_instance"].get("cell_spec_id")
        if isinstance(cell_spec_id, str):
            _check_reference(
                issues=issues,
                ref_id=cell_spec_id,
                expected_type="cell-spec",
                path="cell_instance.cell_spec_id",
                source_root=root,
                resource_type=resource_type,
                missing_message=(
                    "Referenced cell_spec not found in source_root. Register the type first "
                    f"or disable resolve_references. Missing: {cell_spec_id}"
                ),
                mismatch_message=(
                    "Referenced cell_spec must resolve to a cell-spec record in source_root. "
                    f"Found a different record type for: {cell_spec_id}"
                ),
                allow_missing=allow_missing,
            )

        dataset_ids: list[tuple[str, str]] = []
        datasets = doc.get("datasets", [])
        if isinstance(datasets, list):
            dataset_ids.extend(
                (f"datasets[{idx}].id", dataset["id"])
                for idx, dataset in enumerate(datasets)
                if isinstance(dataset, Mapping) and isinstance(dataset.get("id"), str)
            )
        else:
            provenance = doc.get("provenance", {})
            # Backward compatibility for legacy records that stored dataset links under provenance.
            if isinstance(provenance, Mapping):
                if isinstance(provenance.get("dataset_id"), str):
                    dataset_ids.append(("provenance.dataset_id", provenance["dataset_id"]))
                if isinstance(provenance.get("dataset_ids"), list):
                    dataset_ids.extend(
                        (f"provenance.dataset_ids[{idx}]", dataset_id)
                        for idx, dataset_id in enumerate(provenance["dataset_ids"])
                        if isinstance(dataset_id, str)
                    )
        for path, dataset_id in dataset_ids:
            _check_reference(
                issues=issues,
                ref_id=dataset_id,
                expected_type="dataset",
                path=path,
                source_root=root,
                resource_type=resource_type,
                missing_message=(
                    "Referenced dataset not found in source_root. Register dataset first "
                    f"or disable resolve_references. Missing: {dataset_id}"
                ),
                mismatch_message=(
                    "Referenced dataset must resolve to a dataset record in source_root. "
                    f"Found a different record type for: {dataset_id}"
                ),
                allow_missing=allow_missing,
            )

    if isinstance(doc.get("test"), Mapping):
        protocol_id = doc["test"].get("protocol_id")
        if isinstance(protocol_id, str):
            _check_reference(
                issues=issues,
                ref_id=protocol_id,
                expected_type="test-protocol",
                path="test.protocol_id",
                source_root=root,
                resource_type=resource_type,
                missing_message=(
                    "Referenced test protocol not found in source_root. Register test protocol first "
                    f"or disable resolve_references. Missing: {protocol_id}"
                ),
                mismatch_message=(
                    "Referenced test protocol must resolve to a test-protocol record in source_root. "
                    f"Found a different record type for: {protocol_id}"
                ),
                allow_missing=allow_missing,
            )
        cell_id = doc["test"].get("cell_id")
        if isinstance(cell_id, str):
            _check_reference(
                issues=issues,
                ref_id=cell_id,
                expected_type="cell",
                path="test.cell_id",
                source_root=root,
                resource_type=resource_type,
                missing_message=(
                    "Referenced cell not found in source_root. Register cell instance first "
                    f"or disable resolve_references. Missing: {cell_id}"
                ),
                mismatch_message=(
                    "Referenced cell must resolve to a cell-instance record in source_root. "
                    f"Found a different record type for: {cell_id}"
                ),
                allow_missing=allow_missing,
            )
        dataset_ids = doc["test"].get("dataset_ids")
        if isinstance(dataset_ids, list):
            for idx, dataset_id in enumerate(dataset_ids):
                if not isinstance(dataset_id, str):
                    continue
                _check_reference(
                    issues=issues,
                    ref_id=dataset_id,
                    expected_type="dataset",
                    path=f"test.dataset_ids[{idx}]",
                    source_root=root,
                    resource_type=resource_type,
                    missing_message=(
                        "Referenced dataset not found in source_root. Register dataset first "
                        f"or disable resolve_references. Missing: {dataset_id}"
                    ),
                    mismatch_message=(
                        "Referenced dataset must resolve to a dataset record in source_root. "
                        f"Found a different record type for: {dataset_id}"
                    ),
                    allow_missing=allow_missing,
                )

    if isinstance(doc.get("dataset"), Mapping):
        about = doc["dataset"].get("about")
        if isinstance(about, list):
            for idx, ref_id in enumerate(about):
                if not isinstance(ref_id, str):
                    continue
                if CELL_IRI_RE.fullmatch(ref_id):
                    _check_reference(
                        issues=issues,
                        ref_id=ref_id,
                        expected_type="cell",
                        path=f"dataset.about[{idx}]",
                        source_root=root,
                        resource_type=resource_type,
                        missing_message=(
                            "Referenced cell not found in source_root. Register cell instance first "
                            f"or disable resolve_references. Missing: {ref_id}"
                        ),
                        mismatch_message=(
                            "Referenced cell must resolve to a cell-instance record in source_root. "
                            f"Found a different record type for: {ref_id}"
                        ),
                        allow_missing=allow_missing,
                    )
                elif TEST_IRI_RE.fullmatch(ref_id):
                    _check_reference(
                        issues=issues,
                        ref_id=ref_id,
                        expected_type="test",
                        path=f"dataset.about[{idx}]",
                        source_root=root,
                        resource_type=resource_type,
                        missing_message=(
                            "Referenced test not found in source_root. Register test first "
                            f"or disable resolve_references. Missing: {ref_id}"
                        ),
                        mismatch_message=(
                            "Referenced test must resolve to a test record in source_root. "
                            f"Found a different record type for: {ref_id}"
                        ),
                        allow_missing=allow_missing,
                    )

        legacy_related = doc["dataset"].get("related_entities", {})
        if isinstance(legacy_related, Mapping):
            for idx, ref_id in enumerate(legacy_related.get("cell_ids", [])):
                if not isinstance(ref_id, str):
                    continue
                _check_reference(
                    issues=issues,
                    ref_id=ref_id,
                    expected_type="cell",
                    path=f"dataset.related_entities.cell_ids[{idx}]",
                    source_root=root,
                    resource_type=resource_type,
                    missing_message=(
                        "Referenced cell not found in source_root. Register cell instance first "
                        f"or disable resolve_references. Missing: {ref_id}"
                    ),
                    mismatch_message=(
                        "Referenced cell must resolve to a cell-instance record in source_root. "
                        f"Found a different record type for: {ref_id}"
                    ),
                    allow_missing=allow_missing,
                )

    if isinstance(doc.get("material"), Mapping):
        material_spec_id = doc["material"].get("material_spec_id")
        if isinstance(material_spec_id, str):
            _check_reference(
                issues=issues,
                ref_id=material_spec_id,
                expected_type="material-spec",
                path="material.material_spec_id",
                source_root=root,
                resource_type=resource_type,
                missing_message=(
                    "Referenced material_spec not found in source_root. Register the material spec first "
                    f"or disable resolve_references. Missing: {material_spec_id}"
                ),
                mismatch_message=(
                    "Referenced material_spec must resolve to a material-spec record in source_root. "
                    f"Found a different record type for: {material_spec_id}"
                ),
                allow_missing=allow_missing,
            )
        datasets = doc["material"].get("datasets")
        if isinstance(datasets, list):
            for idx, link in enumerate(datasets):
                if not (isinstance(link, Mapping) and isinstance(link.get("id"), str)):
                    continue
                _check_reference(
                    issues=issues,
                    ref_id=link["id"],
                    expected_type="dataset",
                    path=f"material.datasets[{idx}].id",
                    source_root=root,
                    resource_type=resource_type,
                    missing_message=(
                        "Referenced dataset not found in source_root. Register the dataset first "
                        f"or disable resolve_references. Missing: {link['id']}"
                    ),
                    mismatch_message=(
                        "Referenced dataset must resolve to a dataset record in source_root. "
                        f"Found a different record type for: {link['id']}"
                    ),
                    allow_missing=allow_missing,
                )

    if isinstance(doc.get("material_spec"), Mapping):
        composition = doc["material_spec"].get("composition")
        if isinstance(composition, Mapping):
            comp_refs: list[tuple[str, str]] = []
            base = composition.get("base_material_id")
            if isinstance(base, str):
                comp_refs.append(("material_spec.composition.base_material_id", base))
            for group in ("coatings", "constituents"):
                items = composition.get(group)
                if isinstance(items, list):
                    comp_refs.extend(
                        (f"material_spec.composition.{group}[{idx}].material_spec_id", item["material_spec_id"])
                        for idx, item in enumerate(items)
                        if isinstance(item, Mapping) and isinstance(item.get("material_spec_id"), str)
                    )
            for path, ref_id in comp_refs:
                _check_reference(
                    issues=issues,
                    ref_id=ref_id,
                    expected_type="material-spec",
                    path=path,
                    source_root=root,
                    resource_type=resource_type,
                    missing_message=(
                        "Referenced material_spec not found in source_root. Register it first "
                        f"or disable resolve_references. Missing: {ref_id}"
                    ),
                    mismatch_message=(
                        "Referenced material in composition must resolve to a material-spec record. "
                        f"Found a different record type for: {ref_id}"
                    ),
                    allow_missing=allow_missing,
                )

    return ValidationReport(issues=tuple(issues), policy=resolved_policy)


def validate_references(
    doc: dict[str, Any],
    source_root: str | Path,
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationResult:
    return validate_references_report(doc, source_root, policy=policy).to_result()
