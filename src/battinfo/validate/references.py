from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from battinfo.validate.core import (
    DEFAULT_POLICY,
    ValidationIssue,
    ValidationPolicy,
    ValidationReport,
    ValidationResult,
    get_validation_policy,
)

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


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iri_tail(iri: str) -> tuple[str, str]:
    parts = iri.rstrip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"Invalid IRI: {iri}")
    return parts[-2], parts[-1]


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


def _entity_type_from_doc(doc: dict[str, Any]) -> str:
    if isinstance(doc.get("product"), Mapping) or isinstance(doc.get("cell_type"), Mapping):
        return "cell-type"
    if isinstance(doc.get("cell_instance"), Mapping):
        return "cell"
    if isinstance(doc.get("test"), Mapping):
        return "test"
    if isinstance(doc.get("dataset"), Mapping):
        return "dataset"
    raise ValueError("Unsupported record type: expected product/cell_type, cell_instance, test, or dataset.")


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


def _registration_entity_path(entity_type: str, uid: str, source_root: Path) -> Path:
    filename = f"{entity_type}-{uid}.json" if entity_type != "cell-type" else f"cell-type-{uid}.json"
    if entity_type == "cell-type":
        return source_root / "cell-types" / filename
    if entity_type == "cell":
        return source_root / "cell-instances" / filename
    if entity_type == "test":
        return source_root / "tests" / filename
    if entity_type == "dataset":
        return source_root / "datasets" / filename
    raise ValueError(f"Unsupported entity type: {entity_type}")


def _find_record(entity_id: str, source_root: Path) -> tuple[Path, str] | None:
    entity_type, uid = _iri_tail(entity_id)
    expected = _registration_entity_path(entity_type, uid, source_root)
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
) -> None:
    found = _find_record(ref_id, source_root)
    if found is None:
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
        type_id = doc["cell_instance"].get("type_id")
        if isinstance(type_id, str):
            _check_reference(
                issues=issues,
                ref_id=type_id,
                expected_type="cell-type",
                path="cell_instance.type_id",
                source_root=root,
                resource_type=resource_type,
                missing_message=(
                    "Referenced cell_type not found in source_root. Register the type first "
                    f"or disable resolve_references. Missing: {type_id}"
                ),
                mismatch_message=(
                    "Referenced cell_type must resolve to a cell-type record in source_root. "
                    f"Found a different record type for: {type_id}"
                ),
            )

        dataset_ids: list[tuple[str, str]] = []
        provenance = doc.get("provenance", {})
        if isinstance(provenance, Mapping):
            if isinstance(provenance.get("dataset_id"), str):
                dataset_ids.append(("provenance.dataset_id", provenance["dataset_id"]))
            if isinstance(provenance.get("dataset_ids"), list):
                dataset_ids.extend(
                    (f"provenance.dataset_ids[{idx}]", dataset_id)
                    for idx, dataset_id in enumerate(provenance["dataset_ids"])
                    if isinstance(dataset_id, str)
                )
        datasets = doc.get("datasets", [])
        if isinstance(datasets, list):
            dataset_ids.extend(
                (f"datasets[{idx}].id", dataset["id"])
                for idx, dataset in enumerate(datasets)
                if isinstance(dataset, Mapping) and isinstance(dataset.get("id"), str)
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
            )

    if isinstance(doc.get("test"), Mapping):
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
                )

    return ValidationReport(issues=tuple(issues), policy=resolved_policy)


def validate_references(
    doc: dict[str, Any],
    source_root: str | Path,
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationResult:
    return validate_references_report(doc, source_root, policy=policy).to_result()
