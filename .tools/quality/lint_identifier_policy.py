from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]

UID = r"[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}"
CELL_TYPE_IRI_RE = re.compile(rf"^https://w3id\.org/battinfo/cell-type/{UID}$")
CELL_IRI_RE = re.compile(rf"^https://w3id\.org/battinfo/cell/{UID}$")
DATASET_IRI_RE = re.compile(rf"^https://w3id\.org/battinfo/dataset/{UID}$")
SHORT_ID_RE = re.compile(r"^[0-9a-hjkmnp-tv-z]{6,16}$")
SERIAL_FILENAME_RE = re.compile(r"sn\d+", re.IGNORECASE)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_short_id(short_id: object, path: Path, errors: list[str]) -> None:
    if short_id is None:
        return
    if not isinstance(short_id, str) or not SHORT_ID_RE.fullmatch(short_id):
        errors.append(f"{path}: invalid short_id '{short_id}'")


def _check_filename_policy(path: Path, errors: list[str]) -> None:
    if SERIAL_FILENAME_RE.search(path.name):
        errors.append(f"{path}: filename must not include serial-like tokens")


def _check_cell_types(dir_path: Path, errors: list[str]) -> None:
    for path in sorted(dir_path.glob("*.json")):
        _check_filename_policy(path, errors)
        doc = _load(path)
        cell_type = doc.get("cell_type")
        if not isinstance(cell_type, dict):
            errors.append(f"{path}: missing cell_type object")
            continue
        cell_id = cell_type.get("id")
        if not isinstance(cell_id, str) or not CELL_TYPE_IRI_RE.fullmatch(cell_id):
            errors.append(f"{path}: invalid cell_type.id '{cell_id}'")
        _check_short_id(cell_type.get("short_id"), path, errors)


def _check_cell_instances(dir_path: Path, errors: list[str]) -> None:
    for path in sorted(dir_path.glob("*.json")):
        _check_filename_policy(path, errors)
        doc = _load(path)
        inst = doc.get("cell_instance")
        if not isinstance(inst, dict):
            errors.append(f"{path}: missing cell_instance object")
            continue
        cell_id = inst.get("id")
        type_id = inst.get("type_id")
        if not isinstance(cell_id, str) or not CELL_IRI_RE.fullmatch(cell_id):
            errors.append(f"{path}: invalid cell_instance.id '{cell_id}'")
        if not isinstance(type_id, str) or not CELL_TYPE_IRI_RE.fullmatch(type_id):
            errors.append(f"{path}: invalid cell_instance.type_id '{type_id}'")
        _check_short_id(inst.get("short_id"), path, errors)

        provenance = doc.get("provenance", {})
        if isinstance(provenance, dict):
            dataset_id = provenance.get("dataset_id")
            if dataset_id is not None and (
                not isinstance(dataset_id, str) or not DATASET_IRI_RE.fullmatch(dataset_id)
            ):
                errors.append(f"{path}: invalid provenance.dataset_id '{dataset_id}'")
            dataset_ids = provenance.get("dataset_ids")
            if isinstance(dataset_ids, list):
                for dataset_id in dataset_ids:
                    if not isinstance(dataset_id, str) or not DATASET_IRI_RE.fullmatch(dataset_id):
                        errors.append(f"{path}: invalid provenance.dataset_ids item '{dataset_id}'")

        datasets = doc.get("datasets")
        if isinstance(datasets, list):
            for dataset in datasets:
                if not isinstance(dataset, dict):
                    errors.append(f"{path}: datasets entry must be object, got {type(dataset).__name__}")
                    continue
                dataset_id = dataset.get("id")
                if not isinstance(dataset_id, str) or not DATASET_IRI_RE.fullmatch(dataset_id):
                    errors.append(f"{path}: invalid datasets[].id '{dataset_id}'")


def _check_datasets(dir_path: Path, errors: list[str]) -> None:
    for path in sorted(dir_path.glob("*.json")):
        _check_filename_policy(path, errors)
        doc = _load(path)
        dataset = doc.get("dataset")
        if not isinstance(dataset, dict):
            errors.append(f"{path}: missing dataset object")
            continue
        dataset_id = dataset.get("id")
        if not isinstance(dataset_id, str) or not DATASET_IRI_RE.fullmatch(dataset_id):
            errors.append(f"{path}: invalid dataset.id '{dataset_id}'")
        _check_short_id(dataset.get("short_id"), path, errors)

        related = dataset.get("related_entities")
        if isinstance(related, dict):
            for cell_id in related.get("cell_ids", []) if isinstance(related.get("cell_ids"), list) else []:
                if not isinstance(cell_id, str) or not CELL_IRI_RE.fullmatch(cell_id):
                    errors.append(f"{path}: invalid related_entities.cell_ids item '{cell_id}'")


def _dirs() -> Iterable[tuple[str, Path]]:
    yield "assets cell-types", ROOT / "assets" / "examples" / "cell-types"
    yield "assets cell-instances", ROOT / "assets" / "examples" / "cell-instances"
    yield "assets datasets", ROOT / "assets" / "examples" / "datasets"
    yield "pkg cell-types", ROOT / "src" / "battinfo" / "data" / "examples" / "cell-types"
    yield "pkg cell-instances", ROOT / "src" / "battinfo" / "data" / "examples" / "cell-instances"
    yield "pkg datasets", ROOT / "src" / "battinfo" / "data" / "examples" / "datasets"

def main() -> None:
    errors: list[str] = []

    for _, path in _dirs():
        if not path.exists():
            errors.append(f"missing directory: {path}")

    _check_cell_types(ROOT / "assets" / "examples" / "cell-types", errors)
    _check_cell_instances(ROOT / "assets" / "examples" / "cell-instances", errors)
    _check_datasets(ROOT / "assets" / "examples" / "datasets", errors)

    _check_cell_types(ROOT / "src" / "battinfo" / "data" / "examples" / "cell-types", errors)
    _check_cell_instances(ROOT / "src" / "battinfo" / "data" / "examples" / "cell-instances", errors)
    _check_datasets(ROOT / "src" / "battinfo" / "data" / "examples" / "datasets", errors)

    if errors:
        print(f"identifier-policy-lint: FAIL ({len(errors)} issues)")
        for err in errors[:200]:
            print(f"- {err}")
        raise SystemExit(1)

    print("identifier-policy-lint: PASS")


if __name__ == "__main__":
    main()

