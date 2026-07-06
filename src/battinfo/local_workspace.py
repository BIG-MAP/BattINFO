from __future__ import annotations

import json
import mimetypes
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError, model_validator

from battinfo._jsonio import read_json as _read_json
from battinfo._jsonio import write_json as _write_json
from battinfo._util import _as_path, _now_iso, _sha256
from battinfo._workspace import Workspace
from battinfo.bundle import (
    BattinfoBundle,
    Cell,
    CellSpec,
    ChecksumInfo,
    Dataset,
    ProtocolInfo,
    ProvenanceInfo,
    Test,
)
from battinfo.publication import load_publication
from battinfo.validate.record import validate_record

PathLike = str | Path

WORKSPACE_SCHEMA_VERSION = "0.1.0"
WORKSPACE_FILENAME = "battinfo-workspace.json"
DEFAULT_NOTEBOOKS_ROOT = Path(".battinfo/notebooks")
DEFAULT_CELL_RESOURCE_PATH = "resources/cell.json"
DEFAULT_TEST_RESOURCE_PATH = "resources/test.json"
DEFAULT_DATASET_RESOURCE_PATH = "resources/dataset.json"
DEFAULT_ARTIFACTS_DIR = "artifacts"
DEFAULT_DIST_DIR = "dist"
DEFAULT_SUBMISSION_PACKAGE_FILENAME = "submission-package.json"
DEFAULT_LEGACY_REGISTRY_INTAKE_FILENAME = "registry-intake.json"
DEFAULT_SCAFFOLD_WORKSPACE_ID = "digibatt-cr2032-release"


def _guess_media_type(path: str | None) -> str | None:
    if not path:
        return None
    guessed, _ = mimetypes.guess_type(path)
    return guessed


def _citation_url_from_doi(doi: str | None) -> str | None:
    if not isinstance(doi, str):
        return None
    normalized = doi.strip()
    if not normalized:
        return None
    if normalized.startswith("https://doi.org/"):
        return normalized
    if normalized.startswith("http://doi.org/"):
        return "https://" + normalized[len("http://") :]
    if normalized.startswith("doi:"):
        normalized = normalized[4:].strip()
        if not normalized:
            return None
    return f"https://doi.org/{normalized}"


def _relative_to(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _humanize_slug(value: str) -> str:
    text = value.replace("-", " ").replace("_", " ").strip()
    return " ".join(part.capitalize() for part in text.split())


def _is_default_scaffold_manifest(manifest: WorkspaceManifest) -> bool:
    return manifest.workspace_id == DEFAULT_SCAFFOLD_WORKSPACE_ID and manifest.registry == DEFAULT_SCAFFOLD_REGISTRY


class WorkspaceResourcePaths(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cell: str = DEFAULT_CELL_RESOURCE_PATH
    test: str = DEFAULT_TEST_RESOURCE_PATH
    dataset: str = DEFAULT_DATASET_RESOURCE_PATH


class RegistryTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant: str
    workspace: str


DEFAULT_SCAFFOLD_REGISTRY = RegistryTarget(tenant="digibatt", workspace="cr2032-baseline")


class ReleaseInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str | None = None
    community: str | None = None
    doi: str | None = None
    record_url: str | None = None


class ZenodoCreator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    affiliation: str | None = None
    orcid: str | None = None


class ZenodoMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str
    creators: list[ZenodoCreator] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    upload_type: str = "dataset"
    publication_date: str | None = None
    access_right: str = "open"
    license: str | None = None


class WorkspaceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = WORKSPACE_SCHEMA_VERSION
    kind: str = "BattinfoWorkspace"
    workspace_id: str
    title: str
    description: str | None = None
    publisher_id: str | None = "demo-lab"
    resources: WorkspaceResourcePaths = Field(default_factory=WorkspaceResourcePaths)
    artifacts_dir: str = DEFAULT_ARTIFACTS_DIR
    dist_dir: str = DEFAULT_DIST_DIR
    registry: RegistryTarget
    release: ReleaseInfo = Field(default_factory=ReleaseInfo)
    comment: list[str] = Field(default_factory=list)


class SubmissionRelatedResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relationship: str
    resource_type: str
    source_local_id: str | None = None
    canonical_iri: str | None = None
    title: str | None = None

    @model_validator(mode="after")
    def _require_target_reference(self) -> "SubmissionRelatedResource":
        if self.source_local_id is None and self.canonical_iri is None:
            raise ValueError("related_resources entries must include source_local_id or canonical_iri")
        return self


class SubmissionDistribution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    access_url: str
    media_type: str | None = None
    package_path: str | None = None
    checksum_sha256: str | None = None
    immutable: bool = True


class SubmissionProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system: str | None = None
    workflow_name: str | None = None
    generated_at: str | None = None


class SubmissionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = "canonical-publication"


class SubmissionResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: str
    source_local_id: str
    title: str
    semantic_payload: dict[str, Any]
    related_resources: list[SubmissionRelatedResource] = Field(default_factory=list)
    distributions: list[SubmissionDistribution] = Field(default_factory=list)


class BattinfoSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = WORKSPACE_SCHEMA_VERSION
    kind: str = "BattinfoSubmission"
    submission_mode: str
    generated_at: str
    workspace_id: str
    publisher_id: str
    source_version: str | None = None
    title: str
    publication_intent: SubmissionIntent = Field(default_factory=SubmissionIntent)
    provenance: SubmissionProvenance = Field(default_factory=SubmissionProvenance)
    release: dict[str, Any] = Field(default_factory=dict)
    workspace: dict[str, Any] | None = None
    resource: SubmissionResource | None = None
    resources: list[SubmissionResource] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_shape(self) -> "BattinfoSubmission":
        if self.submission_mode == "resource":
            if self.resource is None:
                raise ValueError("resource submission must provide a resource")
            if self.resources:
                raise ValueError("resource submission must not provide resources")
        elif self.submission_mode == "bundle":
            if not self.resources:
                raise ValueError("bundle submission must provide resources")
            if self.resource is not None:
                raise ValueError("bundle submission must not provide resource")
        else:
            raise ValueError("submission_mode must be 'resource' or 'bundle'")
        return self


class CellSpecificationAuthoring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    manufacturer: str
    model: str
    format: str
    chemistry: str
    size_code: str | None = None
    positive_electrode_basis: str | None = None
    negative_electrode_basis: str | None = None
    datasheet_revision: str | None = None
    specs: dict[str, Any] = Field(default_factory=dict)
    provenance: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)


class CellAuthoring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str | None = None
    serial_number: str | None = None
    batch_id: str | None = None
    manufactured_at: int | str | None = None
    measured: dict[str, Any] = Field(default_factory=dict)
    provenance: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)


class WorkspaceCellDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = WORKSPACE_SCHEMA_VERSION
    kind: str = "BattinfoWorkspaceCell"
    resource_id: str = "cell"
    cell_spec: CellSpecificationAuthoring
    cell: CellAuthoring


class TestAuthoring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str | None = None
    kind: str
    description: str | None = None
    status: str | None = None
    protocol_name: str | None = None
    protocol_url: str | None = None
    instrument_name: str | None = None
    started_at: int | str | None = None
    ended_at: int | str | None = None
    provenance: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)


class WorkspaceTestDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = WORKSPACE_SCHEMA_VERSION
    kind: str = "BattinfoWorkspaceTest"
    resource_id: str = "test"
    cell_resource: str = "cell"
    test: TestAuthoring


class DistributionAuthoring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str | None = None
    media_type: str | None = None
    access_url: str | None = None
    download_url: str | None = None
    checksum_algorithm: str | None = None
    checksum_value: str | None = None

    @model_validator(mode="after")
    def _require_path_or_url(self) -> "DistributionAuthoring":
        if not self.path and not self.access_url and not self.download_url:
            raise ValueError("distribution must define at least one of: path, access_url, download_url")
        if bool(self.checksum_algorithm) != bool(self.checksum_value):
            raise ValueError("distribution checksum_algorithm and checksum_value must be provided together")
        return self


class DatasetAuthoring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    title: str = Field(validation_alias=AliasChoices("title", "name"))
    description: str | None = None
    license: str | None = None
    created_at: int | str | None = None
    distribution: DistributionAuthoring
    provenance: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    release: ReleaseInfo = Field(default_factory=ReleaseInfo)
    zenodo: ZenodoMetadata | None = None
    comment: list[str] = Field(default_factory=list)


class WorkspaceDatasetDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = WORKSPACE_SCHEMA_VERSION
    kind: str = "BattinfoWorkspaceDataset"
    resource_id: str = "dataset"
    cell_resource: str = "cell"
    test_resource: str = "test"
    dataset: DatasetAuthoring


def _coerce_registry_target(value: RegistryTarget | Mapping[str, Any]) -> RegistryTarget:
    if isinstance(value, str):
        tenant, sep, workspace = value.partition("/")
        if not sep or not tenant or not workspace:
            raise ValueError("registry must be 'tenant/workspace' when passed as a string.")
        return RegistryTarget(tenant=tenant, workspace=workspace)
    if isinstance(value, RegistryTarget):
        return value.model_copy(deep=True)
    return RegistryTarget.model_validate(dict(value))


def _coerce_release_info(value: ReleaseInfo | Mapping[str, Any] | None) -> ReleaseInfo:
    if value is None:
        return ReleaseInfo()
    if isinstance(value, ReleaseInfo):
        return value.model_copy(deep=True)
    return ReleaseInfo.model_validate(dict(value))


def _coerce_zenodo_metadata(value: ZenodoMetadata | Mapping[str, Any] | None) -> ZenodoMetadata | None:
    if value is None:
        return None
    if isinstance(value, ZenodoMetadata):
        return value.model_copy(deep=True)
    return ZenodoMetadata.model_validate(dict(value))


class LocalWorkspace:
    """Disk-first submission workspace for one linked cell/test/dataset bundle.

    `LocalWorkspace` is distinct from the Python `Workspace` authoring helper. It is
    designed for JSON resource files on disk plus `battinfo workspace` CLI commands,
    not for object-first authoring in notebooks or scripts.
    """

    def __init__(self, root: PathLike) -> None:
        self.root = _as_path(root)
        self.manifest_path = self.root / WORKSPACE_FILENAME

    @classmethod
    def init(cls, root: PathLike, *, force: bool = False) -> "LocalWorkspace":
        workspace = cls(root)
        workspace._init_scaffold(force=force)
        return workspace

    @classmethod
    def sandbox(cls, name: str, *, force: bool = True, root: PathLike = DEFAULT_NOTEBOOKS_ROOT) -> "LocalWorkspace":
        return cls.init(_as_path(root) / name, force=force)

    def _init_scaffold(self, *, force: bool) -> None:
        if self.root.exists() and any(self.root.iterdir()) and not force:
            raise ValueError(f"workspace directory is not empty: {self.root}")

        self.root.mkdir(parents=True, exist_ok=True)
        manifest = WorkspaceManifest(
            workspace_id="digibatt-cr2032-release",
            title="DigiBatt CR2032 baseline release",
            description="Minimal BattINFO workspace for one DigiBatt-style dataset publication happy path.",
            registry=RegistryTarget(tenant="digibatt", workspace="cr2032-baseline"),
            release=ReleaseInfo(
                version="1.0.0",
                community="digibatt",
                doi="10.5281/zenodo.1234567",
                record_url="https://zenodo.org/records/1234567",
            ),
            comment=[
                "Edit the resource JSON files directly, then run `battinfo workspace validate` and `battinfo workspace bundle` to build the submission package.",
            ],
        )
        cell_doc = WorkspaceCellDocument(
            cell_spec=CellSpecificationAuthoring(
                manufacturer="Energizer",
                model="CR2032",
                format="coin",
                chemistry="Li-primary",
                size_code="R2032",
                positive_electrode_basis="MnO2",
                negative_electrode_basis="Li-metal",
                specs={
                    "nominal_voltage": {"value": 3.0, "unit": "V"},
                    "diameter": {"value": 20.0, "unit": "mm"},
                    "height": {"value": 3.2, "unit": "mm"},
                },
                provenance=ProvenanceInfo(
                    type="datasheet",
                    file="energizer-cr2032-datasheet.pdf",
                    retrieved_at=1773201600,
                ),
                comment=["Commercial reference cell type for the DigiBatt MVP workspace example."],
            ),
            cell=CellAuthoring(
                serial_number="digibatt-cr2032-lot-a-001",
                batch_id="CR2032-2026-A",
                provenance=ProvenanceInfo(type="lab", retrieved_at=1773288000),
                comment=["Physical cell instance measured for the release bundle."],
            ),
        )
        test_doc = WorkspaceTestDocument(
            test=TestAuthoring(
                name="CR2032 baseline capacity check",
                kind="capacity_check",
                description="Single-cell constant-current discharge summary used for the DigiBatt MVP happy path.",
                status="completed",
                protocol_name="0.2 mA constant-current discharge",
                instrument_name="Biologic VSP-300",
                started_at=1773374400,
                ended_at=1773378000,
                provenance=ProvenanceInfo(
                    type="measurement",
                    file="cycling.csv",
                    workflow_version="digibatt-mvp",
                    retrieved_at=1773378000,
                ),
            )
        )
        dataset_doc = WorkspaceDatasetDocument(
            dataset=DatasetAuthoring(
                title="DigiBatt CR2032 baseline dataset",
                description="Cycling export and linked metadata for one CR2032 cell release authored in a BattINFO workspace.",
                license="CC-BY-4.0",
                created_at=1773378000,
                distribution=DistributionAuthoring(
                    path="artifacts/cycling.csv",
                    media_type="text/csv",
                ),
                provenance=ProvenanceInfo(
                    type="measurement",
                    url="https://zenodo.org/records/1234567",
                    citation=_citation_url_from_doi(manifest.release.doi),
                    retrieved_at=1773378000,
                    curated_by="DigiBatt",
                    workflow_version="digibatt-mvp",
                ),
                release=manifest.release.model_copy(deep=True),
                zenodo=ZenodoMetadata(
                    title="DigiBatt CR2032 baseline dataset",
                    description="Cycling export and linked metadata for one CR2032 cell release authored in BattINFO.",
                    creators=[ZenodoCreator(name="DigiBatt Consortium")],
                    keywords=["battery", "digibatt", "cr2032", "cycling"],
                    publication_date="2026-03-12",
                    license="CC-BY-4.0",
                ),
                comment=["Primary distribution is kept local until the submission package is submitted."],
            )
        )

        artifact_dir = self.root / manifest.artifacts_dir
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "cycling.csv").write_text("time_s,voltage_v\n0,3.00\n60,2.95\n120,2.91\n", encoding="utf-8")

        _write_json(self.manifest_path, manifest.model_dump(mode="json", exclude_none=True))
        _write_json(self.root / manifest.resources.cell, cell_doc.model_dump(mode="json", exclude_none=True))
        _write_json(self.root / manifest.resources.test, test_doc.model_dump(mode="json", exclude_none=True))
        _write_json(self.root / manifest.resources.dataset, dataset_doc.model_dump(mode="json", exclude_none=True))

    def load(self) -> tuple[WorkspaceManifest, WorkspaceCellDocument, WorkspaceTestDocument, WorkspaceDatasetDocument]:
        if not self.manifest_path.exists():
            raise ValueError(f"workspace manifest not found: {self.manifest_path}")
        manifest = WorkspaceManifest.model_validate(_read_json(self.manifest_path))
        cell_doc = WorkspaceCellDocument.model_validate(_read_json(self.root / manifest.resources.cell))
        test_doc = WorkspaceTestDocument.model_validate(_read_json(self.root / manifest.resources.test))
        dataset_doc = WorkspaceDatasetDocument.model_validate(_read_json(self.root / manifest.resources.dataset))
        self._validate_workspace_links(cell_doc, test_doc, dataset_doc)
        return manifest, cell_doc, test_doc, dataset_doc

    def read_json(self, path: PathLike) -> dict[str, Any]:
        candidate = _as_path(path)
        resolved = candidate if candidate.is_absolute() else self.root / candidate
        return _read_json(resolved)

    def path(self, relative_path: PathLike) -> Path:
        candidate = _as_path(relative_path)
        return candidate if candidate.is_absolute() else self.root / candidate

    def write_text(self, relative_path: PathLike, text: str, *, encoding: str = "utf-8") -> Path:
        target = self.path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding=encoding)
        return target

    def clone(self, root: PathLike, *, force: bool = False, include_dist: bool = False) -> "LocalWorkspace":
        target = _as_path(root)
        if target.exists():
            if any(target.iterdir()) and not force:
                raise ValueError(f"workspace directory is not empty: {target}")
            if force:
                shutil.rmtree(target)
        shutil.copytree(self.root, target)
        cloned = LocalWorkspace(target)
        if not include_dist and cloned.dist_dir.exists():
            shutil.rmtree(cloned.dist_dir)
        return cloned

    def capture(
        self,
        cell_design: CellSpec,
        cell: Cell,
        test: Test,
        dataset: Dataset,
        *,
        workspace_id: str | None = None,
        registry: RegistryTarget | Mapping[str, Any] | str | None = None,
        publisher_id: str | None = None,
        version: str | None = None,
        community: str | None = None,
        title: str | None = None,
        description: str | None = None,
        zenodo: ZenodoMetadata | Mapping[str, Any] | None = None,
        comment: list[str] | None = None,
        capture_artifact: bool = True,
    ) -> dict[str, str]:
        existing_manifest = None
        existing_dataset_doc = None
        if self.manifest_path.exists():
            existing_manifest, _, _, existing_dataset_doc = self.load()
            if _is_default_scaffold_manifest(existing_manifest):
                existing_manifest = None
                existing_dataset_doc = None

        resolved_registry = registry or (existing_manifest.registry if existing_manifest is not None else None)
        parsed_registry = _coerce_registry_target(resolved_registry) if resolved_registry is not None else None
        resolved_workspace_id = (
            workspace_id
            or (existing_manifest.workspace_id if existing_manifest is not None else None)
            or (parsed_registry.workspace if parsed_registry is not None else None)
        )
        resolved_publisher_id = publisher_id or (existing_manifest.publisher_id if existing_manifest is not None else None) or "demo-lab"
        if resolved_workspace_id is None:
            raise ValueError("workspace_id is required when capturing a new workspace.")
        if parsed_registry is None:
            raise ValueError("registry is required when capturing a new workspace.")
        resolved_title = (
            title
            or (existing_manifest.title if existing_manifest is not None else None)
            or dataset.name
            or _humanize_slug(resolved_workspace_id)
        )
        resolved_description = description if description is not None else (existing_manifest.description if existing_manifest is not None else None)
        resolved_comment = comment if comment is not None else (list(existing_manifest.comment) if existing_manifest is not None else None)
        resolved_version = version if version is not None else (existing_manifest.release.version if existing_manifest is not None else None)
        resolved_community = (
            community
            if community is not None
            else (existing_manifest.release.community if existing_manifest is not None else None)
            or parsed_registry.tenant
        )
        resolved_zenodo = self._resolved_zenodo_metadata(
            dataset=dataset,
            zenodo=zenodo,
            existing=existing_dataset_doc.dataset.zenodo if existing_dataset_doc is not None else None,
            version=resolved_version,
            community=resolved_community,
        )
        return self.write_release(
            workspace_id=resolved_workspace_id,
            title=resolved_title,
            registry=parsed_registry,
            publisher_id=resolved_publisher_id,
            cell_design=cell_design,
            cell=cell,
            test=test,
            dataset=dataset,
            description=resolved_description,
            release=ReleaseInfo(version=resolved_version, community=resolved_community),
            zenodo=resolved_zenodo,
            comment=resolved_comment,
            capture_artifact=capture_artifact,
        )

    def write_release(
        self,
        *,
        workspace_id: str,
        title: str,
        registry: RegistryTarget | Mapping[str, Any],
        publisher_id: str | None = None,
        cell_design: CellSpec,
        cell: Cell,
        test: Test,
        dataset: Dataset,
        description: str | None = None,
        release: ReleaseInfo | Mapping[str, Any] | None = None,
        zenodo: ZenodoMetadata | Mapping[str, Any] | None = None,
        comment: list[str] | None = None,
        capture_artifact: bool = True,
    ) -> dict[str, str]:
        resolved_registry = _coerce_registry_target(registry)
        resolved_release = _coerce_release_info(release)
        resolved_zenodo = _coerce_zenodo_metadata(zenodo)
        resolved_comment = list(comment or [])
        artifact_relpath, access_url, download_url = self._resolve_distribution(
            dataset,
            capture_artifact=capture_artifact,
        )

        manifest = WorkspaceManifest(
            workspace_id=workspace_id,
            title=title,
            description=description,
            publisher_id=publisher_id or "demo-lab",
            registry=resolved_registry,
            release=resolved_release,
            comment=resolved_comment,
        )
        cell_doc = WorkspaceCellDocument(
            cell_spec=CellSpecificationAuthoring(
                id=cell_design.id,
                manufacturer=cell_design.manufacturer,
                model=cell_design.model,
                format=cell_design.format,
                chemistry=cell_design.chemistry,
                size_code=cell_design.size_code,
                positive_electrode_basis=cell_design.positive_electrode_basis,
                negative_electrode_basis=cell_design.negative_electrode_basis,
                datasheet_revision=cell_design.datasheet_revision,
                specs=dict(cell_design.properties),
                provenance=cell_design.source.model_copy(deep=True),
                comment=list(cell_design.comment),
            ),
            cell=CellAuthoring(
                id=cell.id,
                name=cell.name,
                serial_number=cell.serial_number,
                batch_id=cell.batch_id,
                manufactured_at=cell.manufactured_at,
                measured=dict(cell.measured),
                provenance=cell.source.model_copy(deep=True),
                comment=list(cell.comment),
            ),
        )
        test_doc = WorkspaceTestDocument(
            test=TestAuthoring(
                id=test.id,
                name=test.name,
                kind=str(test.test_type),
                description=test.description,
                status=test.status,
                protocol_name=test.protocol.name,
                protocol_url=test.protocol.url,
                instrument_name=test.instrument,
                started_at=test.started_at,
                ended_at=test.ended_at,
                provenance=test.source.model_copy(deep=True),
                comment=list(test.comment),
            )
        )
        dataset_doc = WorkspaceDatasetDocument(
            dataset=DatasetAuthoring(
                id=dataset.id,
                title=dataset.name or "dataset",
                description=dataset.description,
                license=dataset.license,
                created_at=dataset.created_at,
                distribution=DistributionAuthoring(
                    path=artifact_relpath,
                    media_type=dataset.data_format or _guess_media_type(artifact_relpath) or _guess_media_type(download_url),
                    access_url=access_url,
                    download_url=download_url,
                    checksum_algorithm=dataset.checksum.algorithm,
                    checksum_value=dataset.checksum.value,
                ),
                provenance=dataset.source.model_copy(deep=True),
                release=resolved_release.model_copy(deep=True),
                zenodo=resolved_zenodo,
                comment=list(dataset.comment),
            )
        )
        self.root.mkdir(parents=True, exist_ok=True)
        _write_json(self.manifest_path, manifest.model_dump(mode="json", exclude_none=True))
        _write_json(self.root / manifest.resources.cell, cell_doc.model_dump(mode="json", exclude_none=True))
        _write_json(self.root / manifest.resources.test, test_doc.model_dump(mode="json", exclude_none=True))
        _write_json(self.root / manifest.resources.dataset, dataset_doc.model_dump(mode="json", exclude_none=True))
        return {
            "workspace_root": str(self.root),
            "manifest_path": str(self.manifest_path),
            "cell_path": str(self.root / manifest.resources.cell),
            "test_path": str(self.root / manifest.resources.test),
            "dataset_path": str(self.root / manifest.resources.dataset),
        }

    def update_release(
        self,
        *,
        version: str | None = None,
        community: str | None = None,
        doi: str | None = None,
        record_url: str | None = None,
        download_url: str | None = None,
    ) -> dict[str, Any]:
        manifest, cell_doc, test_doc, dataset_doc = self.load()
        if version is not None:
            manifest.release.version = version
            dataset_doc.dataset.release.version = version
        if community is not None:
            manifest.release.community = community
            dataset_doc.dataset.release.community = community
        if doi is not None:
            manifest.release.doi = doi
            dataset_doc.dataset.release.doi = doi
        if record_url is not None:
            manifest.release.record_url = record_url
            dataset_doc.dataset.release.record_url = record_url
            dataset_doc.dataset.provenance.url = record_url
            dataset_doc.dataset.distribution.access_url = record_url
        citation = _citation_url_from_doi(dataset_doc.dataset.release.doi)
        if citation is not None and dataset_doc.dataset.provenance.url is not None:
            dataset_doc.dataset.provenance.citation = citation
        if download_url is not None:
            dataset_doc.dataset.distribution.download_url = download_url

        _write_json(self.manifest_path, manifest.model_dump(mode="json", exclude_none=True))
        _write_json(self.root / manifest.resources.cell, cell_doc.model_dump(mode="json", exclude_none=True))
        _write_json(self.root / manifest.resources.test, test_doc.model_dump(mode="json", exclude_none=True))
        _write_json(self.root / manifest.resources.dataset, dataset_doc.model_dump(mode="json", exclude_none=True))
        return {
            "workspace_root": str(self.root),
            "release": dataset_doc.dataset.release.model_dump(mode="json", exclude_none=True),
            "distribution": dataset_doc.dataset.distribution.model_dump(mode="json", exclude_none=True),
        }

    def record_zenodo_release(
        self,
        *,
        doi: str,
        record_url: str,
        download_url: str | None = None,
        version: str | None = None,
        community: str | None = None,
    ) -> dict[str, Any]:
        return self.update_release(
            version=version,
            community=community,
            doi=doi,
            record_url=record_url,
            download_url=download_url,
        )

    def new_version(
        self,
        root: PathLike,
        *,
        version: str,
        force: bool = False,
        include_dist: bool = False,
        keep_record_url: bool = False,
    ) -> "LocalWorkspace":
        cloned = self.clone(root, force=force, include_dist=include_dist)
        manifest, cell_doc, test_doc, dataset_doc = cloned.load()
        manifest.release.version = version
        dataset_doc.dataset.release.version = version
        dataset_doc.dataset.release.doi = None
        dataset_doc.dataset.release.record_url = None
        dataset_doc.dataset.provenance.citation = None
        if not keep_record_url:
            dataset_doc.dataset.provenance.url = None
            dataset_doc.dataset.distribution.access_url = None
            dataset_doc.dataset.distribution.download_url = None
        _write_json(cloned.manifest_path, manifest.model_dump(mode="json", exclude_none=True))
        _write_json(cloned.root / manifest.resources.cell, cell_doc.model_dump(mode="json", exclude_none=True))
        _write_json(cloned.root / manifest.resources.test, test_doc.model_dump(mode="json", exclude_none=True))
        _write_json(cloned.root / manifest.resources.dataset, dataset_doc.model_dump(mode="json", exclude_none=True))
        return cloned

    def load_objects(self) -> dict[str, Any]:
        manifest, cell_doc, test_doc, dataset_doc = self.load()
        distribution = dataset_doc.dataset.distribution
        dataset_path = None
        if distribution.path is not None:
            dataset_path = str((self.root / distribution.path).resolve())
        cell_design = CellSpec(
            id=cell_doc.cell_spec.id,
            manufacturer=cell_doc.cell_spec.manufacturer,
            model=cell_doc.cell_spec.model,
            format=cell_doc.cell_spec.format,
            chemistry=cell_doc.cell_spec.chemistry,
            size_code=cell_doc.cell_spec.size_code,
            positive_electrode_basis=cell_doc.cell_spec.positive_electrode_basis,
            negative_electrode_basis=cell_doc.cell_spec.negative_electrode_basis,
            datasheet_revision=cell_doc.cell_spec.datasheet_revision,
            properties=dict(cell_doc.cell_spec.specs),
            source=cell_doc.cell_spec.provenance.model_copy(deep=True),
            comment=list(cell_doc.cell_spec.comment),
        )
        cell = Cell(
            id=cell_doc.cell.id,
            name=cell_doc.cell.name,
            cell_spec=cell_design,
            serial_number=cell_doc.cell.serial_number,
            batch_id=cell_doc.cell.batch_id,
            manufactured_at=cell_doc.cell.manufactured_at,
            measured=dict(cell_doc.cell.measured),
            source=cell_doc.cell.provenance.model_copy(deep=True),
            comment=list(cell_doc.cell.comment),
        )
        test = Test(
            id=test_doc.test.id,
            name=test_doc.test.name,
            test_type=test_doc.test.kind,
            cell=cell,
            description=test_doc.test.description,
            status=test_doc.test.status,
            protocol=ProtocolInfo(name=test_doc.test.protocol_name, url=test_doc.test.protocol_url),
            instrument=test_doc.test.instrument_name,
            started_at=test_doc.test.started_at,
            ended_at=test_doc.test.ended_at,
            source=test_doc.test.provenance.model_copy(deep=True),
            comment=list(test_doc.test.comment),
        )
        dataset = Dataset(
            id=dataset_doc.dataset.id,
            name=dataset_doc.dataset.title,
            description=dataset_doc.dataset.description,
            license=dataset_doc.dataset.license,
            data_format=distribution.media_type,
            dataset_path=dataset_path,
            access_url=distribution.access_url,
            download_url=distribution.download_url,
            created_at=dataset_doc.dataset.created_at,
            checksum=ChecksumInfo(
                algorithm=distribution.checksum_algorithm,
                value=distribution.checksum_value,
            ),
            cell=cell,
            test=test,
            source=dataset_doc.dataset.provenance.model_copy(deep=True),
            comment=list(dataset_doc.dataset.comment),
        )
        return {
            "manifest": manifest,
            "release": dataset_doc.dataset.release.model_copy(deep=True),
            "zenodo": dataset_doc.dataset.zenodo.model_copy(deep=True) if dataset_doc.dataset.zenodo is not None else None,
            "cell_design": cell_design,
            "cell": cell,
            "test": test,
            "dataset": dataset,
        }

    def load_bundle(self) -> BattinfoBundle:
        return self.to_bundle()

    def to_bundle(self) -> BattinfoBundle:
        objects = self.load_objects()
        return BattinfoBundle(
            bundle_name=objects["dataset"].name,
            cell_spec=objects["cell_design"],
            cell_instance=objects["cell"],
            test=objects["test"],
            dataset=objects["dataset"],
        )

    @classmethod
    def from_bundle(
        cls,
        root: PathLike,
        bundle: BattinfoBundle,
        *,
        workspace_id: str,
        title: str,
        registry: RegistryTarget | Mapping[str, Any],
        publisher_id: str | None = None,
        description: str | None = None,
        release: ReleaseInfo | Mapping[str, Any] | None = None,
        zenodo: ZenodoMetadata | Mapping[str, Any] | None = None,
        comment: list[str] | None = None,
        force: bool = False,
        capture_artifact: bool = True,
    ) -> "LocalWorkspace":
        workspace = cls.init(root, force=force)
        workspace.write_release(
            workspace_id=workspace_id,
            title=title,
            registry=registry,
            publisher_id=publisher_id,
            cell_design=bundle.cell_spec,
            cell=bundle.cell_instance,
            test=bundle.test,
            dataset=bundle.dataset,
            description=description,
            release=release,
            zenodo=zenodo,
            comment=comment,
            capture_artifact=capture_artifact,
        )
        return workspace

    @staticmethod
    def _resource_semantic_payload(resource: Any) -> Mapping[str, Any]:
        if isinstance(resource, SubmissionResource):
            return resource.semantic_payload
        if isinstance(resource, Mapping):
            payload = resource.get("semantic_payload")
            if isinstance(payload, Mapping):
                return payload
        return {}

    @classmethod
    def _bundle_from_resource_payloads(
        cls,
        resource_payloads: Mapping[str, Any],
        *,
        bundle_name: str | None,
    ) -> BattinfoBundle:
        cell_payload = cls._resource_semantic_payload(resource_payloads["cell"]).get("battinfo_records", {})
        test_payload = cls._resource_semantic_payload(resource_payloads["test"]).get("battinfo_records", {})
        dataset_payload = cls._resource_semantic_payload(resource_payloads["dataset"]).get("battinfo_records", {})
        cell_spec_resource = resource_payloads.get("cell_spec")
        cell_spec_payload = cls._resource_semantic_payload(cell_spec_resource).get("battinfo_records", {})
        cell_spec_record = cell_spec_payload.get("cell_spec") or cell_payload.get("cell_spec")
        if not isinstance(cell_spec_record, Mapping):
            raise ValueError("Submission bundle must include a cell_spec record, either as a resource or nested in the cell resource.")
        return BattinfoBundle(
            bundle_name=bundle_name,
            cell_spec=CellSpec.from_record(dict(cell_spec_record)),
            cell_instance=Cell.from_record(cell_payload["cell"]),
            test=Test.from_record(test_payload["test"]),
            dataset=Dataset.from_record(dataset_payload["dataset"]),
        )

    @classmethod
    def from_registry_intake(
        cls,
        root: PathLike,
        intake: Mapping[str, Any] | PathLike,
        *,
        force: bool = False,
        workspace_id: str | None = None,
        title: str | None = None,
        description: str | None = None,
        capture_artifact: bool = True,
    ) -> "LocalWorkspace":
        payload = _read_json(_as_path(intake)) if isinstance(intake, (str, Path)) else dict(intake)
        raw_submission = payload.get("raw_submission")
        if isinstance(raw_submission, Mapping):
            payload = dict(raw_submission)
        else:
            normalized_export = payload.get("normalized_export")
            if isinstance(normalized_export, Mapping):
                payload = dict(normalized_export)
        if payload.get("kind") == "BattinfoSubmission":
            submission = BattinfoSubmission.model_validate(payload)
            if submission.submission_mode != "bundle":
                raise ValueError("LocalWorkspace.import_registry_intake currently supports bundle submissions only.")
            workspace_payload = submission.workspace or {}
            registry = workspace_payload.get("registry", {"tenant": "imported", "workspace": submission.workspace_id})
            release = submission.release
            resource_payloads = {resource.resource_type: resource for resource in submission.resources}
            bundle = cls._bundle_from_resource_payloads(
                resource_payloads,
                bundle_name=workspace_payload.get("title") or submission.title,
            )
            resolved_publisher_id = submission.publisher_id
        else:
            workspace_payload = payload.get("workspace", {})
            registry = workspace_payload.get("registry", {"tenant": "imported", "workspace": "registry-intake"})
            release = payload.get("release", {})
            resources = payload.get("resources", {})
            resource_payloads = (
                {str(item.get("resource_type")): item for item in resources if isinstance(item, Mapping) and isinstance(item.get("resource_type"), str)}
                if isinstance(resources, list)
                else resources
            )
            bundle = cls._bundle_from_resource_payloads(
                resource_payloads,
                bundle_name=workspace_payload.get("title"),
            )
            resolved_publisher_id = payload.get("publisher_id")
        return cls.from_bundle(
            root,
            bundle,
            workspace_id=workspace_id or workspace_payload.get("workspace_id") or "imported-workspace",
            title=title or workspace_payload.get("title") or bundle.dataset.name or "Imported workspace",
            registry=registry,
            publisher_id=resolved_publisher_id,
            description=description or workspace_payload.get("description"),
            release=release,
            force=force,
            capture_artifact=capture_artifact,
        )

    @classmethod
    def from_submission_package(
        cls,
        root: PathLike,
        intake: Mapping[str, Any] | PathLike,
        *,
        force: bool = False,
        workspace_id: str | None = None,
        title: str | None = None,
        description: str | None = None,
        capture_artifact: bool = True,
    ) -> "LocalWorkspace":
        """Preferred name for rehydrating from a submission package."""

        return cls.from_registry_intake(
            root,
            intake,
            force=force,
            workspace_id=workspace_id,
            title=title,
            description=description,
            capture_artifact=capture_artifact,
        )

    @classmethod
    def import_registry_intake(
        cls,
        root: PathLike,
        intake: Mapping[str, Any] | PathLike,
        *,
        force: bool = False,
        workspace_id: str | None = None,
        title: str | None = None,
        description: str | None = None,
        capture_artifact: bool = True,
    ) -> "LocalWorkspace":
        return cls.from_registry_intake(
            root,
            intake,
            force=force,
            workspace_id=workspace_id,
            title=title,
            description=description,
            capture_artifact=capture_artifact,
        )

    @classmethod
    def from_publication(
        cls,
        root: PathLike,
        publication: PathLike,
        *,
        registry: RegistryTarget | Mapping[str, Any],
        workspace_id: str,
        title: str,
        publisher_id: str | None = None,
        description: str | None = None,
        release: ReleaseInfo | Mapping[str, Any] | None = None,
        zenodo: ZenodoMetadata | Mapping[str, Any] | None = None,
        comment: list[str] | None = None,
        force: bool = False,
        capture_artifact: bool = True,
    ) -> "LocalWorkspace":
        bundle = load_publication(publication)
        return cls.from_bundle(
            root,
            bundle,
            workspace_id=workspace_id,
            title=title,
            registry=registry,
            description=description,
            release=release,
            zenodo=zenodo,
            comment=comment,
            publisher_id=publisher_id,
            force=force,
            capture_artifact=capture_artifact,
        )

    @classmethod
    def import_publication(
        cls,
        root: PathLike,
        publication: PathLike,
        *,
        registry: RegistryTarget | Mapping[str, Any] | str,
        workspace_id: str,
        title: str,
        publisher_id: str | None = None,
        description: str | None = None,
        release: ReleaseInfo | Mapping[str, Any] | None = None,
        zenodo: ZenodoMetadata | Mapping[str, Any] | None = None,
        comment: list[str] | None = None,
        force: bool = False,
        capture_artifact: bool = True,
    ) -> "LocalWorkspace":
        return cls.from_publication(
            root,
            publication,
            registry=registry,
            workspace_id=workspace_id,
            title=title,
            publisher_id=publisher_id,
            description=description,
            release=release,
            zenodo=zenodo,
            comment=comment,
            force=force,
            capture_artifact=capture_artifact,
        )

    def _resolve_distribution(
        self,
        dataset: Dataset,
        *,
        capture_artifact: bool,
    ) -> tuple[str | None, str | None, str | None]:
        artifact_relpath = None
        access_url = dataset.access_url
        download_url = dataset.download_url
        if dataset.dataset_path is None:
            return artifact_relpath, access_url, download_url

        source_path = _as_path(dataset.dataset_path)
        if source_path.exists() and capture_artifact:
            artifact_root = self.root / DEFAULT_ARTIFACTS_DIR
            artifact_root.mkdir(parents=True, exist_ok=True)
            target_path = artifact_root / source_path.name
            if source_path.resolve() != target_path.resolve():
                if source_path.is_dir():
                    if target_path.exists():
                        shutil.rmtree(target_path)
                    shutil.copytree(source_path, target_path)
                else:
                    shutil.copy2(source_path, target_path)
            artifact_relpath = _relative_to(self.root, target_path)
            access_url = None
            if download_url == dataset.access_url:
                download_url = None
        else:
            artifact_relpath = _relative_to(self.root, source_path) if capture_artifact else None
        return artifact_relpath, access_url, download_url

    def _resolved_zenodo_metadata(
        self,
        *,
        dataset: Dataset,
        zenodo: ZenodoMetadata | Mapping[str, Any] | None,
        existing: ZenodoMetadata | None,
        version: str | None,
        community: str | None,
    ) -> ZenodoMetadata | None:
        base = existing.model_dump(mode="json", exclude_none=True) if existing is not None else {}
        if zenodo is not None:
            if isinstance(zenodo, ZenodoMetadata):
                base.update(zenodo.model_dump(mode="json", exclude_none=True))
            else:
                base.update(dict(zenodo))
        if not base:
            return None
        base.setdefault("title", dataset.name or "dataset")
        base.setdefault("description", dataset.description or f"BattINFO release for {dataset.name or 'dataset'}.")
        base.setdefault("license", dataset.license)
        if "publication_date" not in base and version is not None:
            base["publication_date"] = date.today().isoformat()
        if "keywords" not in base:
            base["keywords"] = []
        if "creators" not in base:
            base["creators"] = []
        return ZenodoMetadata.model_validate(base)

    def _validate_workspace_links(
        self,
        cell_doc: WorkspaceCellDocument,
        test_doc: WorkspaceTestDocument,
        dataset_doc: WorkspaceDatasetDocument,
    ) -> None:
        if test_doc.cell_resource != cell_doc.resource_id:
            raise ValueError(
                f"test cell_resource '{test_doc.cell_resource}' does not match cell resource_id '{cell_doc.resource_id}'"
            )
        if dataset_doc.cell_resource != cell_doc.resource_id:
            raise ValueError(
                f"dataset cell_resource '{dataset_doc.cell_resource}' does not match cell resource_id '{cell_doc.resource_id}'"
            )
        if dataset_doc.test_resource != test_doc.resource_id:
            raise ValueError(
                f"dataset test_resource '{dataset_doc.test_resource}' does not match test resource_id '{test_doc.resource_id}'"
            )

    def _normalize(self) -> dict[str, Any]:
        manifest, cell_doc, test_doc, dataset_doc = self.load()
        distribution_path = None
        if dataset_doc.dataset.distribution.path is not None:
            distribution_path = self.root / dataset_doc.dataset.distribution.path
            if not distribution_path.exists():
                raise ValueError(f"distribution path does not exist: {distribution_path}")

        checksum_algorithm = dataset_doc.dataset.distribution.checksum_algorithm
        checksum_value = dataset_doc.dataset.distribution.checksum_value
        if distribution_path is not None and checksum_value is None:
            checksum_algorithm = checksum_algorithm or "sha256"
            if checksum_algorithm == "sha256":
                checksum_value = _sha256(distribution_path)

        cell_spec = CellSpec(
            id=cell_doc.cell_spec.id,
            manufacturer=cell_doc.cell_spec.manufacturer,
            model=cell_doc.cell_spec.model,
            format=cell_doc.cell_spec.format,
            chemistry=cell_doc.cell_spec.chemistry,
            size_code=cell_doc.cell_spec.size_code,
            positive_electrode_basis=cell_doc.cell_spec.positive_electrode_basis,
            negative_electrode_basis=cell_doc.cell_spec.negative_electrode_basis,
            datasheet_revision=cell_doc.cell_spec.datasheet_revision,
            properties=dict(cell_doc.cell_spec.specs),
            source=cell_doc.cell_spec.provenance.model_copy(deep=True),
            comment=list(cell_doc.cell_spec.comment),
        )
        cell = Cell(
            id=cell_doc.cell.id,
            name=cell_doc.cell.name,
            cell_spec=cell_spec,
            serial_number=cell_doc.cell.serial_number,
            batch_id=cell_doc.cell.batch_id,
            manufactured_at=cell_doc.cell.manufactured_at,
            measured=dict(cell_doc.cell.measured),
            source=cell_doc.cell.provenance.model_copy(deep=True),
            comment=list(cell_doc.cell.comment),
        )
        test = Test(
            id=test_doc.test.id,
            name=test_doc.test.name,
            kind=test_doc.test.kind,
            cell=cell,
            description=test_doc.test.description,
            status=test_doc.test.status,
            protocol=ProtocolInfo(name=test_doc.test.protocol_name, url=test_doc.test.protocol_url),
            instrument=test_doc.test.instrument_name,
            started_at=test_doc.test.started_at,
            ended_at=test_doc.test.ended_at,
            source=test_doc.test.provenance.model_copy(deep=True),
            comment=list(test_doc.test.comment),
        )
        dataset = Dataset(
            id=dataset_doc.dataset.id,
            name=dataset_doc.dataset.title,
            description=dataset_doc.dataset.description,
            license=dataset_doc.dataset.license,
            data_format=dataset_doc.dataset.distribution.media_type
            or _guess_media_type(dataset_doc.dataset.distribution.path)
            or _guess_media_type(dataset_doc.dataset.distribution.download_url),
            dataset_path=str(distribution_path) if distribution_path is not None else None,
            access_url=dataset_doc.dataset.distribution.access_url,
            download_url=dataset_doc.dataset.distribution.download_url,
            created_at=dataset_doc.dataset.created_at,
            checksum=ChecksumInfo(algorithm=checksum_algorithm, value=checksum_value),
            cell=cell,
            test=test,
            source=dataset_doc.dataset.provenance.model_copy(deep=True),
            comment=list(dataset_doc.dataset.comment),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            scratch = Workspace(root=Path(tmpdir))
            scratch.cell_specs.append(cell_spec)
            scratch.cells.append(cell)
            scratch.tests.append(test)
            scratch.datasets.append(dataset)
            records = scratch.render()

        return {
            "manifest": manifest,
            "cell_doc": cell_doc,
            "test_doc": test_doc,
            "dataset_doc": dataset_doc,
            "records": {
                "cell_spec": records["cell_specs"][0],
                "cell": records["cell_instances"][0],
                "test": records["tests"][0],
                "dataset": records["datasets"][0],
            },
        }

    def _validation_payload(self, name: str, result: Any) -> dict[str, Any]:
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
            "resource": name,
            "ok": result.ok,
            "policy": result.policy,
            "issue_count": len(issues),
            "error_count": sum(1 for issue in issues if issue["severity"] == "error"),
            "warning_count": sum(1 for issue in issues if issue["severity"] == "warning"),
            "issues": issues,
        }

    def validate(self, *, policy: str = "strict", write_report: bool = True) -> dict[str, Any]:
        try:
            normalized = self._normalize()
        except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            report = {
                "schema_version": WORKSPACE_SCHEMA_VERSION,
                "kind": "BattinfoWorkspaceValidationReport",
                "generated_at": _now_iso(),
                "workspace_root": str(self.root),
                "policy": policy,
                "ok": False,
                "issue_count": 1,
                "error_count": 1,
                "warning_count": 0,
                "records": {},
                "issues": [
                    {
                        "code": "workspace.invalid",
                        "severity": "error",
                        "path": "",
                        "message": str(exc),
                        "validator": "workspace",
                    }
                ],
            }
            if write_report:
                _write_json(self.root / DEFAULT_DIST_DIR / "validation-report.json", report)
            return report

        records = normalized["records"]
        with tempfile.TemporaryDirectory() as tmpdir:
            source_root = Path(tmpdir) / "normalized"
            self._write_normalized_records(records, target_root=source_root)
            validation_records = {
                name: self._validation_payload(name, validate_record(payload, source_root=source_root, policy=policy))
                for name, payload in records.items()
            }

        issue_count = sum(item["issue_count"] for item in validation_records.values())
        error_count = sum(item["error_count"] for item in validation_records.values())
        warning_count = sum(item["warning_count"] for item in validation_records.values())
        report = {
            "schema_version": WORKSPACE_SCHEMA_VERSION,
            "kind": "BattinfoWorkspaceValidationReport",
            "generated_at": _now_iso(),
            "workspace_root": str(self.root),
            "policy": policy,
            "ok": error_count == 0,
            "issue_count": issue_count,
            "error_count": error_count,
            "warning_count": warning_count,
            "records": validation_records,
            "resource_ids": {
                "cell_spec_id": records["cell_spec"]["cell_spec"]["id"],
                "cell_id": records["cell"]["cell_instance"]["id"],
                "test_id": records["test"]["test"]["id"],
                "dataset_id": records["dataset"]["dataset"]["id"],
            },
            "issues": [issue for item in validation_records.values() for issue in item["issues"]],
        }
        if write_report:
            _write_json(self.dist_dir / "validation-report.json", report)
        return report

    @property
    def dist_dir(self) -> Path:
        manifest = WorkspaceManifest.model_validate(_read_json(self.manifest_path))
        return self.root / manifest.dist_dir

    def _write_normalized_records(self, records: dict[str, dict[str, Any]], *, target_root: Path) -> None:
        mapping = {
            "cell_spec": target_root / "cell-spec" / "cell-spec.json",
            "cell": target_root / "cell-instance" / "cell.json",
            "test": target_root / "test" / "test.json",
            "dataset": target_root / "dataset" / "dataset.json",
        }
        for name, payload in records.items():
            _write_json(mapping[name], payload)

    def _artifact_payload(self, distribution: DistributionAuthoring) -> list[dict[str, Any]]:
        if distribution.path is None:
            return []
        artifact_path = self.root / distribution.path
        if not artifact_path.exists():
            raise ValueError(f"distribution path does not exist: {artifact_path}")
        checksum_value = distribution.checksum_value
        checksum_algorithm = distribution.checksum_algorithm
        if checksum_value is None:
            checksum_algorithm = checksum_algorithm or "sha256"
            if checksum_algorithm == "sha256":
                checksum_value = _sha256(artifact_path)
        return [
            {
                "path": distribution.path,
                "size_bytes": artifact_path.stat().st_size,
                "media_type": distribution.media_type or _guess_media_type(distribution.path),
                "checksum": {
                    "algorithm": checksum_algorithm,
                    "value": checksum_value,
                }
                if checksum_value is not None
                else None,
            }
        ]

    def _submission_source_local_id(self, manifest: WorkspaceManifest, resource_type: str) -> str:
        return f"{manifest.workspace_id}:{resource_type}"

    def _cell_submission_payload(self, manifest: WorkspaceManifest, records: dict[str, dict[str, Any]]) -> SubmissionResource:
        cell_record = records["cell"]["cell_instance"]
        cell_spec_record = records["cell_spec"]["cell_spec"]
        return SubmissionResource(
            resource_type="cell",
            source_local_id=self._submission_source_local_id(manifest, "cell"),
            title=cell_record.get("name") or f"{cell_spec_record.get('manufacturer', 'Battery')} {cell_spec_record.get('model', 'Cell')}",
            semantic_payload={
                "@type": "Cell",
                "battinfo_records": {
                    "cell_spec": records["cell_spec"],
                    "cell": records["cell"],
                },
            },
        )

    def _test_submission_payload(self, manifest: WorkspaceManifest, records: dict[str, dict[str, Any]]) -> SubmissionResource:
        test_record = records["test"]["test"]
        return SubmissionResource(
            resource_type="test",
            source_local_id=self._submission_source_local_id(manifest, "test"),
            title=test_record.get("name") or f"{manifest.title} test",
            semantic_payload={
                "@type": "Test",
                "battinfo_records": {"test": records["test"]},
            },
            related_resources=[
                SubmissionRelatedResource(
                    relationship="testsCell",
                    resource_type="cell",
                    source_local_id=self._submission_source_local_id(manifest, "cell"),
                    title=self._cell_submission_payload(manifest, records).title,
                )
            ],
        )

    def _dataset_submission_payload(
        self,
        manifest: WorkspaceManifest,
        dataset_doc: WorkspaceDatasetDocument,
        records: dict[str, dict[str, Any]],
    ) -> SubmissionResource:
        distribution = dataset_doc.dataset.distribution
        distributions: list[SubmissionDistribution] = []
        access_url = distribution.download_url or distribution.access_url
        if access_url is not None:
            distributions.append(
                SubmissionDistribution(
                    title=dataset_doc.dataset.title,
                    access_url=access_url,
                    media_type=distribution.media_type,
                    package_path=distribution.path,
                    checksum_sha256=distribution.checksum_value if distribution.checksum_algorithm == "sha256" else None,
                    immutable=dataset_doc.dataset.release.record_url is not None,
                )
            )
        return SubmissionResource(
            resource_type="dataset",
            source_local_id=self._submission_source_local_id(manifest, "dataset"),
            title=dataset_doc.dataset.title,
            semantic_payload={
                "@type": "Dataset",
                "battinfo_records": {"dataset": records["dataset"]},
            },
            related_resources=[
                SubmissionRelatedResource(
                    relationship="aboutCell",
                    resource_type="cell",
                    source_local_id=self._submission_source_local_id(manifest, "cell"),
                    title=self._cell_submission_payload(manifest, records).title,
                ),
                SubmissionRelatedResource(
                    relationship="generatedByTest",
                    resource_type="test",
                    source_local_id=self._submission_source_local_id(manifest, "test"),
                    title=self._test_submission_payload(manifest, records).title,
                ),
            ],
            distributions=distributions,
        )

    def _registry_intake_payload(
        self,
        *,
        normalized: dict[str, Any],
        validation_report: dict[str, Any],
    ) -> dict[str, Any]:
        manifest: WorkspaceManifest = normalized["manifest"]
        dataset_doc: WorkspaceDatasetDocument = normalized["dataset_doc"]
        records = normalized["records"]
        artifacts = self._artifact_payload(dataset_doc.dataset.distribution)
        submission = BattinfoSubmission(
            submission_mode="bundle",
            generated_at=_now_iso(),
            workspace_id=manifest.registry.workspace,
            publisher_id=manifest.publisher_id or "demo-lab",
            source_version=dataset_doc.dataset.release.version,
            title=manifest.title,
            publication_intent=SubmissionIntent(mode="canonical-publication"),
            provenance=SubmissionProvenance(
                source_system="battinfo",
                workflow_name="local-workspace",
                generated_at=_now_iso(),
            ),
            release=dataset_doc.dataset.release.model_dump(mode="json", exclude_none=True),
            workspace={
                "workspace_id": manifest.workspace_id,
                "title": manifest.title,
                "description": manifest.description,
                "root": str(self.root),
                "registry": manifest.registry.model_dump(mode="json"),
            },
            resources=[
                self._cell_submission_payload(manifest, records),
                self._test_submission_payload(manifest, records),
                self._dataset_submission_payload(manifest, dataset_doc, records),
            ],
            artifacts=[artifact for artifact in artifacts if artifact is not None],
            validation={
                "ok": validation_report["ok"],
                "policy": validation_report["policy"],
                "issue_count": validation_report["issue_count"],
                "error_count": validation_report["error_count"],
                "warning_count": validation_report["warning_count"],
            },
        )
        return submission.model_dump(mode="json", exclude_none=True)

    def _zenodo_metadata_payload(
        self,
        *,
        manifest: WorkspaceManifest,
        dataset_doc: WorkspaceDatasetDocument,
    ) -> dict[str, Any] | None:
        metadata = dataset_doc.dataset.zenodo
        if metadata is None:
            return None
        publication_date = metadata.publication_date or date.today().isoformat()
        payload: dict[str, Any] = {
            "metadata": {
                "title": metadata.title,
                "upload_type": metadata.upload_type,
                "publication_date": publication_date,
                "description": metadata.description,
                "creators": [creator.model_dump(mode="json", exclude_none=True) for creator in metadata.creators],
                "keywords": list(metadata.keywords),
                "access_right": metadata.access_right,
            },
            "release": dataset_doc.dataset.release.model_dump(mode="json", exclude_none=True),
            "registry": manifest.registry.model_dump(mode="json"),
        }
        if metadata.license is not None:
            payload["metadata"]["license"] = metadata.license
        if dataset_doc.dataset.release.version is not None:
            payload["metadata"]["version"] = dataset_doc.dataset.release.version
        if dataset_doc.dataset.release.community is not None:
            payload["metadata"]["communities"] = [{"identifier": dataset_doc.dataset.release.community}]
        return payload

    def bundle(self, *, policy: str = "strict") -> dict[str, Any]:
        """Compatibility alias for build_submission_package(...)."""

        return self.build_submission_package(policy=policy)

    def build_submission_package(self, *, policy: str = "strict") -> dict[str, Any]:
        validation_report = self.validate(policy=policy, write_report=True)
        if not validation_report["ok"]:
            raise ValueError("workspace validation failed; see dist/validation-report.json")

        normalized = self._normalize()
        manifest: WorkspaceManifest = normalized["manifest"]
        dataset_doc: WorkspaceDatasetDocument = normalized["dataset_doc"]
        records = normalized["records"]

        normalized_dir = self.dist_dir / "normalized"
        self._write_normalized_records(records, target_root=normalized_dir)

        submission_package = self._registry_intake_payload(normalized=normalized, validation_report=validation_report)
        submission_package_path = self.dist_dir / DEFAULT_SUBMISSION_PACKAGE_FILENAME
        legacy_registry_intake_path = self.dist_dir / DEFAULT_LEGACY_REGISTRY_INTAKE_FILENAME
        _write_json(submission_package_path, submission_package)
        _write_json(legacy_registry_intake_path, submission_package)

        zenodo_metadata = self._zenodo_metadata_payload(manifest=manifest, dataset_doc=dataset_doc)
        zenodo_metadata_path = None
        if zenodo_metadata is not None:
            zenodo_metadata_path = self.dist_dir / "zenodo-metadata.json"
            _write_json(zenodo_metadata_path, zenodo_metadata)

        return {
            "status": "ok",
            "generated_at": _now_iso(),
            "workspace_root": str(self.root),
            "validation_report_path": str(self.dist_dir / "validation-report.json"),
            "normalized_dir": str(normalized_dir),
            "submission_package_path": str(submission_package_path),
            "registry_intake_path": str(legacy_registry_intake_path),
            "zenodo_metadata_path": str(zenodo_metadata_path) if zenodo_metadata_path is not None else None,
            "resource_count": len(submission_package.get("resources", [])),
            "artifact_count": len(submission_package.get("artifacts", [])),
            "cell_spec_id": records["cell_spec"]["cell_spec"]["id"],
            "cell_id": records["cell"]["cell_instance"]["id"],
            "test_id": records["test"]["test"]["id"],
            "dataset_id": records["dataset"]["dataset"]["id"],
        }


__all__ = [
    "DEFAULT_ARTIFACTS_DIR",
    "DEFAULT_CELL_RESOURCE_PATH",
    "DEFAULT_DATASET_RESOURCE_PATH",
    "DEFAULT_DIST_DIR",
    "DEFAULT_LEGACY_REGISTRY_INTAKE_FILENAME",
    "DEFAULT_SUBMISSION_PACKAGE_FILENAME",
    "DEFAULT_TEST_RESOURCE_PATH",
    "LocalWorkspace",
    "ReleaseInfo",
    "RegistryTarget",
    "WorkspaceManifest",
    "WORKSPACE_FILENAME",
]

