from __future__ import annotations

import json
import mimetypes
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from pydantic import BaseModel, ConfigDict, Field

from battinfo.bundle import CellInstance, CellSpecification, CellType, Dataset, Test
from battinfo.local_workspace import (
    BattinfoSubmission,
    SubmissionDistribution,
    SubmissionIntent,
    SubmissionProvenance,
    SubmissionRelatedResource,
    SubmissionResource,
)
from battinfo.validate.record import validate_record
from battinfo.workspace import Workspace

PathLike = str | Path
ProjectTarget = CellType | CellInstance | Test | Dataset
PROJECT_SCHEMA_VERSION = "0.1.0"
PROJECT_FILENAME = "battinfo-project.json"


def _as_path(path: PathLike) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _relative_to(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _guess_media_type(path: str | None) -> str | None:
    if not path:
        return None
    guessed, _ = mimetypes.guess_type(path)
    return guessed


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_from_file_uri(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    path_text = unquote(parsed.path)
    if parsed.netloc:
        path_text = f"//{parsed.netloc}{path_text}"
    if path_text.startswith("/") and len(path_text) > 2 and path_text[2] == ":":
        path_text = path_text[1:]
    return Path(path_text)


def _dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


class ProjectPaths(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cell_types: str = "records/cell-types"
    cells: str = "records/cell-instances"
    tests: str = "records/tests"
    datasets: str = "records/datasets"


class ProjectArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    path: str


class ProjectManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PROJECT_SCHEMA_VERSION
    kind: str = "BattinfoProject"
    name: str | None = None
    title: str | None = None
    description: str | None = None
    tenant: str | None = None
    publisher: str | None = None
    version: str | None = None
    comment: list[str] = Field(default_factory=list)
    paths: ProjectPaths = Field(default_factory=ProjectPaths)
    artifacts_dir: str = "artifacts"
    dist_dir: str = "dist"
    dataset_artifacts: list[ProjectArtifact] = Field(default_factory=list)


class Project:
    """Compatibility wrapper around `Workspace` for project-shaped workflows.

    Use `Project` when the same linked object graph needs a named local project,
    validation reports, copied dataset artifacts, or a registry-ready submission package.
    For pure Python authoring without the project layer, use `Workspace` directly.
    """

    def __init__(
        self,
        root: PathLike,
        *,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        tenant: str | None = None,
        publisher: str | None = None,
        version: str | None = None,
        comment: list[str] | None = None,
        clean: bool = False,
    ) -> None:
        self.workspace = Workspace(root=root, clean=clean)
        self.name = name
        self.title = title
        self.description = description
        self.tenant = tenant
        self.publisher = publisher
        self.version = version
        self.comment = list(comment or [])
        self.manifest_path = self.root / PROJECT_FILENAME

    @property
    def root(self) -> Path:
        return self.workspace.root

    @property
    def cell_types(self) -> list[CellType]:
        return self.workspace.cell_types

    @property
    def cells(self) -> list[CellInstance]:
        return self.workspace.cells

    @property
    def tests(self) -> list[Test]:
        return self.workspace.tests

    @property
    def datasets(self) -> list[Dataset]:
        return self.workspace.datasets

    @property
    def descriptions(self) -> list[CellSpecification]:
        return self.workspace.descriptions

    def add(self, *objects: Any) -> "Project":
        self.workspace.add(*objects)
        return self

    def describe_cell(self, **kwargs: Any) -> CellSpecification:
        return self.workspace.describe_cell(**kwargs)

    def cell_type(self, **kwargs: Any) -> CellType:
        return self.workspace.cell_type(**kwargs)

    def cell(self, *args: Any, **kwargs: Any) -> CellInstance:
        return self.workspace.cell(*args, **kwargs)

    def test(self, *args: Any, **kwargs: Any) -> Test:
        return self.workspace.test(*args, **kwargs)

    def record_test(self, *args: Any, **kwargs: Any) -> Test:
        return self.workspace.record_test(*args, **kwargs)

    def dataset(self, *args: Any, **kwargs: Any) -> Dataset:
        return self.workspace.dataset(*args, **kwargs)

    def publish(self, dataset: Dataset, **kwargs: Any) -> dict[str, Any]:
        return self.workspace.publish(dataset, **kwargs)

    def render(self) -> dict[str, list[dict[str, Any]]]:
        return self.workspace.render()

    def save(self) -> dict[str, Any]:
        manifest, records, artifact_map = self._persist()
        return {
            "status": "ok",
            "project_root": str(self.root),
            "manifest_path": str(self.manifest_path),
            "cell_type_count": len(records["cell_types"]),
            "cell_count": len(records["cell_instances"]),
            "test_count": len(records["tests"]),
            "dataset_count": len(records["datasets"]),
            "artifact_count": sum(1 for value in artifact_map.values() if value is not None),
            "title": manifest.title,
            "name": manifest.name,
        }

    def check(self, *, policy: str = "strict", write_report: bool = True) -> dict[str, Any]:
        self._ensure_supported_state()
        records = self.render()
        with tempfile.TemporaryDirectory() as tmpdir:
            source_root = Path(tmpdir) / "normalized"
            self._write_record_groups(records, target_root=source_root)
            validation_groups = {
                "cell_types": [self._validation_payload(validate_record(record, source_root=source_root, policy=policy)) for record in records["cell_types"]],
                "cells": [self._validation_payload(validate_record(record, source_root=source_root, policy=policy)) for record in records["cell_instances"]],
                "tests": [self._validation_payload(validate_record(record, source_root=source_root, policy=policy)) for record in records["tests"]],
                "datasets": [self._validation_payload(validate_record(record, source_root=source_root, policy=policy)) for record in records["datasets"]],
            }

        issue_count = sum(item["issue_count"] for group in validation_groups.values() for item in group)
        error_count = sum(item["error_count"] for group in validation_groups.values() for item in group)
        warning_count = sum(item["warning_count"] for group in validation_groups.values() for item in group)
        report = {
            "schema_version": PROJECT_SCHEMA_VERSION,
            "kind": "BattinfoProjectValidationReport",
            "generated_at": _now_iso(),
            "project_root": str(self.root),
            "policy": policy,
            "ok": error_count == 0,
            "issue_count": issue_count,
            "error_count": error_count,
            "warning_count": warning_count,
            "counts": {
                "cell_types": len(records["cell_types"]),
                "cells": len(records["cell_instances"]),
                "tests": len(records["tests"]),
                "datasets": len(records["datasets"]),
            },
            "records": validation_groups,
            "issues": [issue for group in validation_groups.values() for item in group for issue in item["issues"]],
        }
        if write_report:
            manifest = self._manifest()
            _write_json(self.root / manifest.dist_dir / "validation-report.json", report)
        return report

    def bundle(
        self,
        target: ProjectTarget | None = None,
        *,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        tenant: str | None = None,
        publisher: str | None = None,
        version: str | None = None,
        policy: str = "strict",
    ) -> dict[str, Any]:
        """Compatibility alias for build_submission_package(...)."""

        return self.build_submission_package(
            target,
            name=name,
            title=title,
            description=description,
            tenant=tenant,
            publisher=publisher,
            version=version,
            policy=policy,
        )

    def build_submission_package(
        self,
        target: ProjectTarget | None = None,
        *,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        tenant: str | None = None,
        publisher: str | None = None,
        version: str | None = None,
        policy: str = "strict",
    ) -> dict[str, Any]:
        if name is not None:
            self.name = name
        if title is not None:
            self.title = title
        if description is not None:
            self.description = description
        if tenant is not None:
            self.tenant = tenant
        if publisher is not None:
            self.publisher = publisher
        if version is not None:
            self.version = version

        manifest, records, artifact_map = self._persist()
        validation_report = self.check(policy=policy, write_report=True)
        if not validation_report["ok"]:
            raise ValueError("project validation failed; see dist/validation-report.json")

        if manifest.name is None:
            raise ValueError("Project.bundle() requires project.name.")
        if manifest.publisher is None:
            raise ValueError("Project.bundle() requires project.publisher.")

        normalized_dir = self.root / manifest.dist_dir / "normalized"
        self._write_record_groups(records, target_root=normalized_dir)

        cell_type_by_id = {
            str(record["product"]["id"]): record
            for record in records["cell_types"]
            if isinstance(record.get("product"), dict) and isinstance(record["product"].get("id"), str)
        }
        cell_records = list(records["cell_instances"])
        test_records = list(records["tests"])
        dataset_records = list(records["datasets"])

        cell_titles = {
            self._source_local_id("cell", record): self._cell_title(record, cell_type_by_id)
            for record in cell_records
        }
        cell_local_ids = {
            str(record["cell_instance"]["id"]): self._source_local_id("cell", record)
            for record in cell_records
            if isinstance(record.get("cell_instance"), dict) and isinstance(record["cell_instance"].get("id"), str)
        }
        test_titles = {
            self._source_local_id("test", record): self._test_title(record)
            for record in test_records
        }
        test_local_ids = {
            str(record["test"]["id"]): self._source_local_id("test", record)
            for record in test_records
            if isinstance(record.get("test"), dict) and isinstance(record["test"].get("id"), str)
        }

        if target is None:
            resources: list[SubmissionResource] = []
            for record in cell_records:
                resources.append(self._cell_resource(record, cell_type_by_id))
            for record in test_records:
                resources.append(self._test_resource(record, cell_titles, cell_local_ids))
            for record in dataset_records:
                resources.append(self._dataset_resource(record, artifact_map, cell_titles, test_titles, cell_local_ids, test_local_ids))
            resource = None
            artifacts = [artifact for dataset_id in artifact_map for artifact in [self._artifact_entry(artifact_map[dataset_id])] if artifact is not None]
            submission_mode = "bundle"
        else:
            resource = self._resource_submission(
                target,
                cell_type_by_id=cell_type_by_id,
                cell_records=cell_records,
                test_records=test_records,
                dataset_records=dataset_records,
                artifact_map=artifact_map,
                cell_titles=cell_titles,
                test_titles=test_titles,
                cell_local_ids=cell_local_ids,
                test_local_ids=test_local_ids,
            )
            resources = []
            artifacts = self._resource_artifacts(target=target, artifact_map=artifact_map)
            submission_mode = "resource"

        submission = BattinfoSubmission(
            submission_mode=submission_mode,
            generated_at=_now_iso(),
            project_id=manifest.name,
            publisher_id=manifest.publisher,
            source_version=manifest.version,
            title=manifest.title or manifest.name,
            publication_intent=SubmissionIntent(mode="canonical-publication"),
            provenance=SubmissionProvenance(
                source_system="battinfo",
                workflow_name="project",
                generated_at=_now_iso(),
            ),
            release={"version": manifest.version} if manifest.version is not None else {},
            workspace={
                "name": manifest.name,
                "title": manifest.title,
                "description": manifest.description,
                "root": str(self.root),
                "registry": {key: value for key, value in {"tenant": manifest.tenant, "project": manifest.name}.items() if value is not None},
            },
            resource=resource,
            resources=resources,
            artifacts=artifacts,
            validation={
                "ok": validation_report["ok"],
                "policy": validation_report["policy"],
                "issue_count": validation_report["issue_count"],
                "error_count": validation_report["error_count"],
                "warning_count": validation_report["warning_count"],
            },
        )
        payload = submission.model_dump(mode="json", exclude_none=True)
        submission_package_path = self._submission_package_path(manifest=manifest, target=target, resource=resource)
        registry_intake_path = self._registry_intake_path(manifest=manifest, target=target, resource=resource)
        _write_json(submission_package_path, payload)
        _write_json(registry_intake_path, payload)
        return {
            "status": "ok",
            "submission_mode": submission_mode,
            "generated_at": payload["generated_at"],
            "project_root": str(self.root),
            "manifest_path": str(self.manifest_path),
            "validation_report_path": str(self.root / manifest.dist_dir / "validation-report.json"),
            "normalized_dir": str(normalized_dir),
            "submission_package_path": str(submission_package_path),
            "registry_intake_path": str(registry_intake_path),
            "resource_count": 1 if resource is not None else len(resources),
            "artifact_count": len(artifacts),
            "resource_type": resource.resource_type if resource is not None else None,
        }

    @classmethod
    def open(cls, root: PathLike) -> "Project":
        root_path = _as_path(root)
        manifest = ProjectManifest.model_validate(_read_json(root_path / PROJECT_FILENAME))
        project = cls(
            root_path,
            name=manifest.name,
            title=manifest.title,
            description=manifest.description,
            tenant=manifest.tenant,
            publisher=manifest.publisher,
            version=manifest.version,
            comment=list(manifest.comment),
        )
        project.workspace.descriptions.clear()
        project.workspace.cell_types.clear()
        project.workspace.cells.clear()
        project.workspace.tests.clear()
        project.workspace.datasets.clear()

        paths = manifest.paths
        cell_type_records = cls._load_records(root_path / paths.cell_types)
        cell_records = cls._load_records(root_path / paths.cells)
        test_records = cls._load_records(root_path / paths.tests)
        dataset_records = cls._load_records(root_path / paths.datasets)
        artifact_map = {entry.dataset_id: root_path / entry.path for entry in manifest.dataset_artifacts}

        cell_types = [CellType.from_record(record) for record in cell_type_records]
        cell_type_by_id = {item.id: item for item in cell_types if item.id is not None}

        cells: list[CellInstance] = []
        cell_by_id: dict[str, CellInstance] = {}
        for record in cell_records:
            cell = CellInstance.from_record(record)
            if cell.cell_type_id is not None:
                cell.cell_type = cell_type_by_id.get(cell.cell_type_id)
            cells.append(cell)
            if cell.id is not None:
                cell_by_id[cell.id] = cell

        tests: list[Test] = []
        test_by_id: dict[str, Test] = {}
        for record in test_records:
            test = Test.from_record(record)
            if test.cell_instance_id is not None:
                test.cell = cell_by_id.get(test.cell_instance_id)
            tests.append(test)
            if test.id is not None:
                test_by_id[test.id] = test

        datasets: list[Dataset] = []
        for record in dataset_records:
            dataset_id = record.get("dataset", {}).get("id") if isinstance(record.get("dataset"), dict) else None
            artifact_path = artifact_map.get(dataset_id) if isinstance(dataset_id, str) else None
            dataset = Dataset.from_record(record, dataset_path=str(artifact_path) if artifact_path is not None else None)
            if dataset.cell_instance_id is not None:
                dataset.cell = cell_by_id.get(dataset.cell_instance_id)
            if dataset.test_id is not None:
                dataset.test = test_by_id.get(dataset.test_id)
            datasets.append(dataset)

        project.workspace.cell_types.extend(cell_types)
        project.workspace.cells.extend(cells)
        project.workspace.tests.extend(tests)
        project.workspace.datasets.extend(datasets)
        return project

    def _ensure_supported_state(self) -> None:
        if self.descriptions:
            raise ValueError("Project currently supports cell types, cells, tests, and datasets, but not saved cell descriptions.")

    def _manifest(self) -> ProjectManifest:
        return ProjectManifest(
            name=self.name,
            title=self.title or self.name,
            description=self.description,
            tenant=self.tenant,
            publisher=self.publisher,
            version=self.version,
            comment=list(self.comment),
        )

    def _persist(self) -> tuple[ProjectManifest, dict[str, list[dict[str, Any]]], dict[str, str | None]]:
        self._ensure_supported_state()
        records = self.render()
        manifest = self._manifest()
        artifact_map = self._write_project(manifest, records)
        return manifest, records, artifact_map

    def _write_project(self, manifest: ProjectManifest, records: dict[str, list[dict[str, Any]]]) -> dict[str, str | None]:
        record_groups = {
            "cell_types": records["cell_types"],
            "cells": records["cell_instances"],
            "tests": records["tests"],
            "datasets": records["datasets"],
        }
        roots = {
            "cell_types": self.root / manifest.paths.cell_types,
            "cells": self.root / manifest.paths.cells,
            "tests": self.root / manifest.paths.tests,
            "datasets": self.root / manifest.paths.datasets,
        }
        for path in roots.values():
            if path.exists():
                shutil.rmtree(path)
            path.mkdir(parents=True, exist_ok=True)

        for key, items in record_groups.items():
            for record in items:
                filename = f"{self._record_short_id(key, record)}.json"
                _write_json(roots[key] / filename, record)

        dataset_by_id = {dataset.id: dataset for dataset in self.datasets if dataset.id is not None}
        artifacts_root = self.root / manifest.artifacts_dir / "datasets"
        source_paths, staged_roots = self._stage_dataset_sources(dataset_by_id, artifacts_root)
        try:
            if artifacts_root.exists():
                shutil.rmtree(artifacts_root)
            artifacts_root.mkdir(parents=True, exist_ok=True)

            dataset_artifacts: list[ProjectArtifact] = []
            artifact_map: dict[str, str | None] = {}
            for record in records["datasets"]:
                dataset_payload = record.get("dataset", {})
                if not isinstance(dataset_payload, dict) or not isinstance(dataset_payload.get("id"), str):
                    continue
                dataset_id = dataset_payload["id"]
                source_path = source_paths.get(dataset_id)
                artifact_path = None
                if source_path is not None and source_path.exists():
                    target_root = artifacts_root / self._record_short_id("datasets", record)
                    if source_path.is_file():
                        target_root.mkdir(parents=True, exist_ok=True)
                        copied = target_root / source_path.name
                        shutil.copy2(source_path, copied)
                        artifact_path = copied
                    elif source_path.is_dir():
                        shutil.copytree(source_path, target_root, dirs_exist_ok=True)
                        artifact_path = target_root
                if artifact_path is not None:
                    relpath = _relative_to(self.root, artifact_path)
                    dataset_artifacts.append(ProjectArtifact(dataset_id=dataset_id, path=relpath))
                    artifact_map[dataset_id] = relpath
                else:
                    artifact_map[dataset_id] = None
        finally:
            for staged_root in staged_roots:
                shutil.rmtree(staged_root, ignore_errors=True)

        manifest.dataset_artifacts = dataset_artifacts
        _write_json(self.manifest_path, manifest.model_dump(mode="json", exclude_none=True))
        return artifact_map

    def _stage_dataset_sources(
        self,
        dataset_by_id: dict[str, Dataset],
        artifacts_root: Path,
    ) -> tuple[dict[str, Path | None], list[Path]]:
        staged: dict[str, Path | None] = {}
        staged_roots: list[Path] = []
        for dataset_id, dataset in dataset_by_id.items():
            source_path = self._dataset_local_path(dataset)
            if source_path is None or not source_path.exists():
                staged[dataset_id] = None
                continue
            try:
                source_path.relative_to(artifacts_root)
            except ValueError:
                staged[dataset_id] = source_path
                continue

            temp_root = Path(tempfile.mkdtemp(prefix="battinfo-project-artifact-"))
            staged_roots.append(temp_root)
            if source_path.is_file():
                staged_path = temp_root / source_path.name
                shutil.copy2(source_path, staged_path)
            else:
                staged_path = temp_root / source_path.name
                shutil.copytree(source_path, staged_path, dirs_exist_ok=True)
            staged[dataset_id] = staged_path
        return staged, staged_roots

    def _dataset_local_path(self, dataset: Dataset | None) -> Path | None:
        if dataset is None:
            return None
        if dataset.dataset_path:
            return _as_path(dataset.dataset_path)
        if dataset.access_url:
            return _path_from_file_uri(dataset.access_url)
        return None

    def _validation_payload(self, result: Any) -> dict[str, Any]:
        issues = [
            {
                "code": issue.code,
                "severity": issue.severity,
                "path": issue.path,
                "message": issue.message,
                "validator": issue.validator,
                "resource_type": issue.resource_type,
            }
            for issue in result.issues
        ]
        return {
            "ok": result.ok,
            "policy": result.policy,
            "issue_count": len(issues),
            "error_count": sum(1 for issue in issues if issue["severity"] == "error"),
            "warning_count": sum(1 for issue in issues if issue["severity"] == "warning"),
            "issues": issues,
        }

    def _write_record_groups(self, records: dict[str, list[dict[str, Any]]], *, target_root: Path) -> None:
        groups = {
            "cell_types": target_root / "cell-types",
            "cell_instances": target_root / "cell-instances",
            "tests": target_root / "tests",
            "datasets": target_root / "datasets",
        }
        for key, path in groups.items():
            if path.exists():
                shutil.rmtree(path)
            path.mkdir(parents=True, exist_ok=True)
            for record in records[key]:
                filename = f"{self._record_short_id(key, record)}.json"
                _write_json(path / filename, record)

    @staticmethod
    def _load_records(directory: Path) -> list[dict[str, Any]]:
        if not directory.exists():
            return []
        return [_read_json(path) for path in sorted(directory.glob("*.json")) if path.is_file()]

    def _record_short_id(self, kind: str, record: dict[str, Any]) -> str:
        if kind == "cell_types":
            payload = record.get("product", {})
        elif kind in {"cells", "cell_instances"}:
            payload = record.get("cell_instance", {})
        elif kind == "tests":
            payload = record.get("test", {})
        elif kind == "datasets":
            payload = record.get("dataset", {})
        else:
            raise ValueError(f"Unsupported record kind: {kind}")
        if isinstance(payload, dict) and isinstance(payload.get("short_id"), str):
            return payload["short_id"]
        if isinstance(payload, dict) and isinstance(payload.get("id"), str):
            return payload["id"].rstrip("/").split("/")[-1]
        raise ValueError(f"Could not determine short_id for {kind} record.")

    def _source_local_id(self, resource_type: str, record: dict[str, Any]) -> str:
        kind_map = {
            "cell_type": "cell_types",
            "cell": "cells",
            "test": "tests",
            "dataset": "datasets",
        }
        return f"{resource_type}:{self._record_short_id(kind_map[resource_type], record)}"

    def _cell_type_title(self, record: dict[str, Any]) -> str:
        product = record["product"]
        manufacturer_obj = product.get("manufacturer")
        manufacturer = manufacturer_obj.get("name") if isinstance(manufacturer_obj, dict) else manufacturer_obj
        return str(product.get("name") or f"{manufacturer or 'Battery'} {product.get('model') or 'Cell'}").strip()

    def _cell_type_resource(self, record: dict[str, Any]) -> SubmissionResource:
        product = record["product"]
        manufacturer_obj = product.get("manufacturer")
        manufacturer = manufacturer_obj.get("name") if isinstance(manufacturer_obj, dict) else manufacturer_obj
        metadata = {
            "manufacturer": manufacturer,
            "model": product.get("model"),
            "format": product.get("cellFormat"),
            "chemistry": product.get("chemistry"),
            "size_code": product.get("sizeCode"),
            "iec_code": product.get("iecCode"),
            "country_of_origin": product.get("countryOfOrigin"),
            "year": product.get("year"),
            "positive_electrode_basis": product.get("positiveElectrodeBasis"),
            "negative_electrode_basis": product.get("negativeElectrodeBasis"),
        }
        return SubmissionResource(
            resource_type="cell_type",
            source_local_id=self._source_local_id("cell_type", record),
            title=self._cell_type_title(record),
            semantic_payload={
                "@type": "CellType",
                "metadata": {key: value for key, value in metadata.items() if value is not None},
                "battinfo_records": {"cell_type": record},
            },
        )

    def _cell_title(self, record: dict[str, Any], cell_type_by_id: dict[str, dict[str, Any]]) -> str:
        cell_payload = record["cell_instance"]
        cell_type_id = cell_payload.get("type_id")
        cell_type = cell_type_by_id.get(cell_type_id) if isinstance(cell_type_id, str) else None
        manufacturer = None
        model = None
        if isinstance(cell_type, dict) and isinstance(cell_type.get("product"), dict):
            product = cell_type["product"]
            manufacturer_obj = product.get("manufacturer")
            manufacturer = manufacturer_obj.get("name") if isinstance(manufacturer_obj, dict) else manufacturer_obj
            model = product.get("model")
        return str(cell_payload.get("serial_number") or cell_payload.get("batch_id") or f"{manufacturer or 'Battery'} {model or 'Cell'}").strip()

    def _test_title(self, record: dict[str, Any]) -> str:
        return str(record["test"].get("name") or record["test"].get("kind") or "test")

    def _cell_resource(self, record: dict[str, Any], cell_type_by_id: dict[str, dict[str, Any]]) -> SubmissionResource:
        cell_payload = record["cell_instance"]
        cell_type_id = cell_payload.get("type_id")
        cell_type_record = cell_type_by_id.get(cell_type_id) if isinstance(cell_type_id, str) else None
        product = cell_type_record.get("product", {}) if isinstance(cell_type_record, dict) else {}
        manufacturer_obj = product.get("manufacturer") if isinstance(product, dict) else None
        manufacturer = manufacturer_obj.get("name") if isinstance(manufacturer_obj, dict) else manufacturer_obj
        metadata = {
            "manufacturer": manufacturer,
            "model": product.get("model") if isinstance(product, dict) else None,
            "format": product.get("cellFormat") if isinstance(product, dict) else None,
            "chemistry": product.get("chemistry") if isinstance(product, dict) else None,
            "size_code": product.get("sizeCode") if isinstance(product, dict) else None,
            "iec_code": product.get("iecCode") if isinstance(product, dict) else None,
            "country_of_origin": product.get("countryOfOrigin") if isinstance(product, dict) else None,
            "year": product.get("year") if isinstance(product, dict) else None,
            "serial_number": cell_payload.get("serial_number"),
            "batch_id": cell_payload.get("batch_id"),
        }
        battinfo_records = {"cell": record}
        if cell_type_record is not None:
            battinfo_records["cell_type"] = cell_type_record
        return SubmissionResource(
            resource_type="cell",
            source_local_id=self._source_local_id("cell", record),
            title=self._cell_title(record, cell_type_by_id),
            semantic_payload={
                "@type": "Cell",
                "metadata": {key: value for key, value in metadata.items() if value is not None},
                "battinfo_records": battinfo_records,
            },
        )

    def _test_resource(
        self,
        record: dict[str, Any],
        cell_titles: dict[str, str],
        cell_local_ids: dict[str, str],
    ) -> SubmissionResource:
        test_payload = record["test"]
        related = []
        if isinstance(test_payload.get("cell_id"), str):
            local_id = cell_local_ids.get(test_payload["cell_id"])
            if local_id is not None:
                related.append(
                    SubmissionRelatedResource(
                        relationship="testsCell",
                        resource_type="cell",
                        source_local_id=local_id,
                        title=cell_titles.get(local_id),
                    )
                )
        return SubmissionResource(
            resource_type="test",
            source_local_id=self._source_local_id("test", record),
            title=self._test_title(record),
            semantic_payload={
                "@type": "Test",
                "metadata": {
                    key: value
                    for key, value in {
                        "kind": test_payload.get("kind"),
                        "status": test_payload.get("status"),
                        "protocol": test_payload.get("protocol_name"),
                        "instrument": test_payload.get("instrument_name"),
                        "started_at": test_payload.get("started_at"),
                        "ended_at": test_payload.get("ended_at"),
                    }.items()
                    if value is not None
                },
                "battinfo_records": {"test": record},
            },
            related_resources=related,
        )

    def _dataset_resource(
        self,
        record: dict[str, Any],
        artifact_map: dict[str, str | None],
        cell_titles: dict[str, str],
        test_titles: dict[str, str],
        cell_local_ids: dict[str, str],
        test_local_ids: dict[str, str],
    ) -> SubmissionResource:
        dataset_payload = record["dataset"]
        dataset_id = str(dataset_payload["id"])
        artifact_relpath = artifact_map.get(dataset_id)
        artifact_path = self.root / artifact_relpath if artifact_relpath is not None else None

        distributions = []
        access_url = None
        media_type = None
        checksum_sha256 = None
        distribution = dataset_payload.get("distribution")
        if isinstance(distribution, list) and distribution and isinstance(distribution[0], dict):
            first = distribution[0]
            access_url = first.get("contentUrl")
            media_type = first.get("encodingFormat")
            checksum = first.get("checksum")
            if isinstance(checksum, dict) and checksum.get("algorithm") == "sha256":
                checksum_sha256 = checksum.get("value")
        if artifact_path is not None and artifact_path.exists():
            access_url = artifact_path.resolve().as_uri()
            media_type = media_type or _guess_media_type(str(artifact_path))
            if artifact_path.is_file():
                checksum_sha256 = checksum_sha256 or _sha256(artifact_path)
        if access_url is not None:
            distributions.append(
                SubmissionDistribution(
                    title=dataset_payload.get("name"),
                    access_url=access_url,
                    media_type=media_type,
                    package_path=artifact_relpath,
                    checksum_sha256=checksum_sha256 if isinstance(checksum_sha256, str) else None,
                    immutable=False,
                )
            )

        related = []
        about = dataset_payload.get("about")
        if isinstance(about, list):
            for value in about:
                if not isinstance(value, str):
                    continue
                if "/cell/" in value:
                    local_id = cell_local_ids.get(value)
                    if local_id is not None:
                        related.append(
                            SubmissionRelatedResource(
                                relationship="aboutCell",
                                resource_type="cell",
                                source_local_id=local_id,
                                title=cell_titles.get(local_id),
                            )
                        )
                elif "/test/" in value:
                    local_id = test_local_ids.get(value)
                    if local_id is not None:
                        related.append(
                            SubmissionRelatedResource(
                                relationship="generatedByTest",
                                resource_type="test",
                                source_local_id=local_id,
                                title=test_titles.get(local_id),
                            )
                        )

        return SubmissionResource(
            resource_type="dataset",
            source_local_id=self._source_local_id("dataset", record),
            title=str(dataset_payload.get("name") or dataset_payload["id"]),
            semantic_payload={
                "@type": "Dataset",
                "metadata": {
                    key: value
                    for key, value in {
                        "license": dataset_payload.get("license"),
                        "created_at": dataset_payload.get("dateCreated"),
                        "version": dataset_payload.get("version"),
                        "access_url": dataset_payload.get("url"),
                    }.items()
                    if value is not None
                },
                "battinfo_records": {"dataset": record},
            },
            related_resources=related,
            distributions=distributions,
        )

    def _artifact_entry(self, artifact_relpath: str | None) -> dict[str, Any] | None:
        if artifact_relpath is None:
            return None
        artifact_path = self.root / artifact_relpath
        if not artifact_path.exists():
            return None
        checksum = None
        if artifact_path.is_file():
            checksum = {"algorithm": "sha256", "value": _sha256(artifact_path)}
        return {
            "path": artifact_relpath,
            "size_bytes": _dir_size(artifact_path),
            "media_type": _guess_media_type(str(artifact_path)),
            "checksum": checksum,
        }

    def _resource_submission(
        self,
        target: ProjectTarget,
        *,
        cell_type_by_id: dict[str, dict[str, Any]],
        cell_records: list[dict[str, Any]],
        test_records: list[dict[str, Any]],
        dataset_records: list[dict[str, Any]],
        artifact_map: dict[str, str | None],
        cell_titles: dict[str, str],
        test_titles: dict[str, str],
        cell_local_ids: dict[str, str],
        test_local_ids: dict[str, str],
    ) -> SubmissionResource:
        if isinstance(target, CellType):
            record = self._find_record("cell_types", target.id, cell_type_by_id.values())
            return self._cell_type_resource(record)
        if isinstance(target, CellInstance):
            record = self._find_record("cells", target.id, cell_records)
            return self._cell_resource(record, cell_type_by_id)
        if isinstance(target, Test):
            record = self._find_record("tests", target.id, test_records)
            return self._test_resource(record, cell_titles, cell_local_ids)
        if isinstance(target, Dataset):
            record = self._find_record("datasets", target.id, dataset_records)
            return self._dataset_resource(record, artifact_map, cell_titles, test_titles, cell_local_ids, test_local_ids)
        raise TypeError("Project.bundle() target must be a CellType, CellInstance, Test, or Dataset.")

    def _resource_artifacts(
        self,
        *,
        target: ProjectTarget,
        artifact_map: dict[str, str | None],
    ) -> list[dict[str, Any]]:
        if not isinstance(target, Dataset) or target.id is None:
            return []
        artifact = self._artifact_entry(artifact_map.get(target.id))
        return [artifact] if artifact is not None else []

    def _submission_package_path(
        self,
        *,
        manifest: ProjectManifest,
        target: ProjectTarget | None,
        resource: SubmissionResource | None,
    ) -> Path:
        dist_dir = self.root / manifest.dist_dir
        if target is None or resource is None:
            return dist_dir / "submission-package.json"
        short_id = resource.source_local_id.split(":", 1)[-1]
        return dist_dir / f"submission-package.{resource.resource_type}.{short_id}.json"

    def _registry_intake_path(
        self,
        *,
        manifest: ProjectManifest,
        target: ProjectTarget | None,
        resource: SubmissionResource | None,
    ) -> Path:
        dist_dir = self.root / manifest.dist_dir
        if target is None or resource is None:
            return dist_dir / "registry-intake.json"
        short_id = resource.source_local_id.split(":", 1)[-1]
        return dist_dir / f"registry-intake.{resource.resource_type}.{short_id}.json"

    def _find_record(
        self,
        kind: str,
        entity_id: str | None,
        records: Any,
    ) -> dict[str, Any]:
        if entity_id is None:
            raise ValueError(f"Project.bundle() target must have an id before it can be bundled as a {kind}.")
        for record in records:
            payload = self._record_payload(kind, record)
            if isinstance(payload.get("id"), str) and payload["id"] == entity_id:
                return record
        raise ValueError(f"Project.bundle() target {entity_id!r} is not present in this project.")

    def _record_payload(self, kind: str, record: dict[str, Any]) -> dict[str, Any]:
        if kind == "cell_types":
            payload = record.get("product", {})
        elif kind == "cells":
            payload = record.get("cell_instance", {})
        elif kind == "tests":
            payload = record.get("test", {})
        elif kind == "datasets":
            payload = record.get("dataset", {})
        else:
            raise ValueError(f"Unsupported record kind: {kind}")
        if not isinstance(payload, dict):
            raise ValueError(f"Malformed {kind} record.")
        return payload


__all__ = ["PROJECT_FILENAME", "PROJECT_SCHEMA_VERSION", "Project", "ProjectManifest"]
