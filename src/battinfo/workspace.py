from __future__ import annotations

import hashlib
import mimetypes
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from battinfo.api import (
    build_cell_type_library_rdf,
    build_index as build_index_api,
    query as query_api,
    query_cell_instances,
    query_library_cell_types,
    query_cell_types,
    query_datasets,
    query_tests,
    save_cell_instance,
    save_cell_type,
    save_dataset,
    save_library_cell_type,
    save_test,
)
from battinfo.authoring import cell_description as build_cell_description
from battinfo.bundle import CellInstance, CellSpecification, CellType, ChecksumInfo, Dataset, ProtocolInfo, ProvenanceInfo, Test
from battinfo.publication import DEFAULT_PUBLISH_FILENAME, publish as publish_bundle

PathLike = str | Path
UID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
EXTENSION_MEDIA_TYPE_MAP = {
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".jsonld": "application/ld+json",
    ".h5": "application/x-hdf5",
    ".hdf5": "application/x-hdf5",
    ".parquet": "application/vnd.apache.parquet",
}


def quantity(
    value: int | float | None = None,
    unit: str | None = None,
    *,
    typical: int | float | None = None,
    min_value: int | float | None = None,
    max_value: int | float | None = None,
    text: str | None = None,
) -> dict[str, Any]:
    """Build a BattINFO quantity dict without hand-writing nested value/unit payloads."""
    payload: dict[str, Any] = {}
    if value is not None:
        payload["value"] = value
    if typical is not None:
        payload["value_typical"] = typical
    if min_value is not None:
        payload["value_min"] = min_value
    if max_value is not None:
        payload["value_max"] = max_value
    if text is not None:
        payload["value_text"] = text
    if unit is not None:
        payload["unit"] = unit
    return payload


def q(
    value: int | float | None = None,
    unit: str | None = None,
    *,
    typical: int | float | None = None,
    min_value: int | float | None = None,
    max_value: int | float | None = None,
    text: str | None = None,
) -> dict[str, Any]:
    """Compatibility alias for quantity(...)."""
    return quantity(
        value,
        unit,
        typical=typical,
        min_value=min_value,
        max_value=max_value,
        text=text,
    )


def _now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _stable_uid(seed: str) -> str:
    value = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:16], "big")
    chars: list[str] = []
    for _ in range(16):
        value, remainder = divmod(value, 32)
        chars.append(UID_ALPHABET[remainder])
    token = "".join(reversed(chars))
    return "-".join((token[:4], token[4:8], token[8:12], token[12:16]))


def _entity_iri(entity_type: str, seed: str) -> str:
    return f"https://w3id.org/battinfo/{entity_type}/{_stable_uid(seed)}"


def _with_default(value: str | None, fallback: str) -> str:
    text = (value or "").strip()
    return text or fallback


def _as_path(path: PathLike) -> Path:
    return path if isinstance(path, Path) else Path(path)


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _guess_media_type(value: str | None) -> str | None:
    if value is None:
        return None
    suffix = Path(value).suffix.lower()
    if suffix in EXTENSION_MEDIA_TYPE_MAP:
        return EXTENSION_MEDIA_TYPE_MAP[suffix]
    guessed, _ = mimetypes.guess_type(value)
    return guessed


def _sync_model_state(target: Any, source: Any) -> None:
    for field_name in target.__class__.model_fields:
        setattr(target, field_name, getattr(source, field_name))


def _mapping_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_mapping"):
        return dict(value.to_mapping())
    return dict(value)


def _append_unique(items: list[Any], candidate: Any) -> None:
    if not any(existing is candidate for existing in items):
        items.append(candidate)


class Workspace:
    """Human-facing BattINFO workspace for constructing and saving linked records."""

    def __init__(
        self,
        root: PathLike = ".battinfo/workspace",
        *,
        source_dir_name: str = "examples",
        index_name: str = "index.json",
        clean: bool = False,
    ) -> None:
        self.root = _as_path(root)
        if clean and self.root.exists():
            shutil.rmtree(self.root)
        self.source_root = self.root / source_dir_name
        self.index_path = self.root / index_name
        self.library_root = self.root / "library" / "cell-types"
        self.package_root = self.root / "package" / "cell-types"
        self.library_rdf_root = self.root / "library-rdf" / "cell-types"
        self.library_aggregate_jsonld = self.root / "ontology" / "library" / "cell-types.jsonld"
        self.library_manifest_json = self.root / "library-rdf" / "cell-types.index.json"
        self.root.mkdir(parents=True, exist_ok=True)

        self.descriptions: list[CellSpecification] = []
        self.cell_types: list[CellType] = []
        self.cells: list[CellInstance] = []
        self.tests: list[Test] = []
        self.datasets: list[Dataset] = []

    def add(self, *objects: Any) -> "Workspace":
        """Add one or more authoring objects to the workspace by type."""
        def _add(obj: Any) -> None:
            if isinstance(obj, CellSpecification):
                _append_unique(self.descriptions, obj)
            elif isinstance(obj, CellType):
                _append_unique(self.cell_types, obj)
            elif isinstance(obj, CellInstance):
                if obj.cell_type is not None:
                    _add(obj.cell_type)
                _append_unique(self.cells, obj)
            elif isinstance(obj, Test):
                if obj.cell is not None:
                    _add(obj.cell)
                _append_unique(self.tests, obj)
            elif isinstance(obj, Dataset):
                if obj.cell is not None:
                    _add(obj.cell)
                if obj.test is not None:
                    _add(obj.test)
                _append_unique(self.datasets, obj)
            else:
                raise TypeError(
                    "Workspace.add() supports CellSpecification, CellType, Cell/CellInstance, Test, and Dataset objects."
                )
        for obj in objects:
            _add(obj)
        return self

    def describe_cell(
        self,
        *,
        manufacturer: str,
        model: str,
        format: str,
        chemistry: str,
        positive_electrode_basis: str | None = None,
        negative_electrode_basis: str | None = None,
        size_code: str | None = None,
        construction: Any = None,
        properties: Any = None,
        positive_electrode: Any = None,
        negative_electrode: Any = None,
        electrolyte: Any = None,
        separator: Any = None,
        source: ProvenanceInfo | None = None,
        specification_comment: str | list[str] | None = None,
        comment: str | list[str] | None = None,
    ) -> CellSpecification:
        specification = build_cell_description(
            id=_entity_iri(
                "cell-type",
                "::".join(
                    [
                        _with_default(manufacturer, "unknown-manufacturer"),
                        _with_default(model, "unknown-model"),
                        _with_default(format, "unknown-format"),
                        _with_default(chemistry, "unknown-chemistry"),
                        size_code or "",
                    ]
                ),
            ),
            manufacturer=manufacturer,
            model=model,
            format=format,
            chemistry=chemistry,
            positive_electrode_basis=positive_electrode_basis,
            negative_electrode_basis=negative_electrode_basis,
            size_code=size_code,
            construction=construction,
            properties=properties,
            positive_electrode=positive_electrode,
            negative_electrode=negative_electrode,
            electrolyte=electrolyte,
            separator=separator,
            source=source,
            specification_comment=specification_comment,
            comment=comment,
        )
        if specification.source.type is None:
            specification.source.type = "manual"
        if specification.source.retrieved_at is None:
            specification.source.retrieved_at = _now_unix()
        self.descriptions.append(specification)
        return specification

    def cell_type(
        self,
        *,
        manufacturer: str,
        model: str,
        format: str,
        chemistry: str,
        specs: Any = None,
        size_code: str | None = None,
        positive_electrode_basis: str | None = None,
        negative_electrode_basis: str | None = None,
        datasheet_revision: str | None = None,
        source_type: str = "datasheet",
        source_file: str | None = None,
        source_url: str | None = None,
        citation: str | None = None,
        retrieved_at: int | str | None = None,
        comment: list[str] | None = None,
    ) -> CellType:
        cell_type = CellType(
            manufacturer=manufacturer,
            model=model,
            format=format,
            chemistry=chemistry,
            size_code=size_code,
            positive_electrode_basis=positive_electrode_basis,
            negative_electrode_basis=negative_electrode_basis,
            datasheet_revision=datasheet_revision,
            nominal_properties=_mapping_value(specs),
            source=ProvenanceInfo(
                type=source_type,
                file=source_file,
                url=source_url,
                citation=citation,
                retrieved_at=retrieved_at,
            ),
            comment=list(comment or []),
        )
        self.cell_types.append(cell_type)
        return cell_type

    def cell(
        self,
        cell_type: CellType,
        *,
        serial_number: str | None = None,
        batch_id: str | None = None,
        manufactured_at: int | str | None = None,
        measured: Any = None,
        source_type: str = "measurement",
        source_url: str | None = None,
        citation: str | None = None,
        retrieved_at: int | str | None = None,
        comment: list[str] | None = None,
    ) -> CellInstance:
        cell = CellInstance(
            cell_type=cell_type,
            serial_number=serial_number,
            batch_id=batch_id,
            manufactured_at=manufactured_at,
            measured=_mapping_value(measured),
            source=ProvenanceInfo(
                type=source_type,
                url=source_url,
                citation=citation,
                retrieved_at=retrieved_at,
            ),
            comment=list(comment or []),
        )
        self.cells.append(cell)
        return cell

    def test(
        self,
        cell: CellInstance,
        *,
        kind: str,
        name: str | None = None,
        description: str | None = None,
        protocol: str | None = None,
        protocol_url: str | None = None,
        instrument: str | None = None,
        status: str | None = None,
        started_at: int | str | None = None,
        ended_at: int | str | None = None,
        source_type: str = "measurement",
        source_url: str | None = None,
        source_file: str | None = None,
        citation: str | None = None,
        retrieved_at: int | str | None = None,
        workflow_version: str | None = None,
        comment: list[str] | None = None,
    ) -> Test:
        test = Test(
            name=name,
            test_kind=kind,
            cell=cell,
            description=description,
            status=status,
            protocol=ProtocolInfo(name=protocol, url=protocol_url),
            instrument=instrument,
            started_at=started_at,
            ended_at=ended_at,
            source=ProvenanceInfo(
                type=source_type,
                file=source_file,
                url=source_url,
                citation=citation,
                retrieved_at=retrieved_at,
                workflow_version=workflow_version,
            ),
            comment=list(comment or []),
        )
        self.tests.append(test)
        return test

    def record_test(
        self,
        cell: CellInstance,
        *,
        kind: str,
        path: PathLike | None = None,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        dataset_description: str | None = None,
        protocol: str | None = None,
        protocol_url: str | None = None,
        instrument: str | None = None,
        status: str | None = "completed",
        format: str | None = None,
        license: str | None = None,
        access_url: str | None = None,
        download_url: str | None = None,
        checksum_algorithm: str | None = None,
        checksum_value: str | None = None,
        created_at: int | str | None = None,
        source_type: str = "measurement",
        source_url: str | None = None,
        source_file: str | None = None,
        citation: str | None = None,
        retrieved_at: int | str | None = None,
        workflow_version: str | None = None,
        curated_by: str | None = None,
        comment: list[str] | None = None,
    ) -> Test:
        protocol_name = protocol or kind.replace("_", " ")
        test_name = name or f"{cell.name or cell.serial_number or 'cell'} {protocol_name}"
        test = self.test(
            cell,
            kind=kind,
            name=test_name,
            description=description,
            protocol=protocol_name,
            protocol_url=protocol_url,
            instrument=instrument,
            status=status,
            source_type=source_type,
            source_url=source_url,
            source_file=source_file,
            citation=citation,
            retrieved_at=retrieved_at,
            workflow_version=workflow_version,
            comment=comment,
        )
        if path is not None or access_url is not None or download_url is not None or title is not None:
            dataset_title = title or f"{cell.name or cell.serial_number or 'cell'} {kind} dataset"
            self.dataset(
                cell,
                title=dataset_title,
                description=dataset_description,
                test=test,
                path=path,
                access_url=access_url,
                download_url=download_url,
                format=format,
                license=license,
                checksum_algorithm=checksum_algorithm,
                checksum_value=checksum_value,
                created_at=created_at,
                source_type=source_type,
                source_url=source_url,
                citation=citation,
                retrieved_at=retrieved_at,
                curated_by=curated_by,
                comment=comment,
            )
        return test

    def dataset(
        self,
        cell: CellInstance,
        *,
        title: str,
        description: str | None = None,
        test: Test | None = None,
        path: PathLike | None = None,
        access_url: str | None = None,
        download_url: str | None = None,
        format: str | None = None,
        license: str | None = None,
        checksum_algorithm: str | None = None,
        checksum_value: str | None = None,
        created_at: int | str | None = None,
        source_type: str = "measurement",
        source_url: str | None = None,
        citation: str | None = None,
        retrieved_at: int | str | None = None,
        curated_by: str | None = None,
        comment: list[str] | None = None,
    ) -> Dataset:
        dataset_path_obj = _as_path(path) if path is not None else None
        dataset_path = str(dataset_path_obj) if dataset_path_obj is not None else None
        resolved_access_url = access_url
        if resolved_access_url is None and dataset_path_obj is not None:
            resolved_access_url = dataset_path_obj.resolve().as_uri()
        resolved_format = format or _guess_media_type(download_url) or _guess_media_type(resolved_access_url) or _guess_media_type(dataset_path)
        resolved_checksum_algorithm = checksum_algorithm
        resolved_checksum_value = checksum_value
        if dataset_path_obj is not None and dataset_path_obj.exists() and dataset_path_obj.is_file() and resolved_checksum_value is None:
            resolved_checksum_algorithm = resolved_checksum_algorithm or "sha256"
            if resolved_checksum_algorithm == "sha256":
                resolved_checksum_value = _sha256(dataset_path_obj)

        dataset = Dataset(
            name=title,
            description=description,
            license=license,
            data_format=resolved_format,
            dataset_path=dataset_path,
            access_url=resolved_access_url,
            download_url=download_url,
            created_at=created_at,
            checksum=ChecksumInfo(algorithm=resolved_checksum_algorithm, value=resolved_checksum_value),
            cell=cell,
            test=test,
            source=ProvenanceInfo(
                type=source_type,
                url=source_url or resolved_access_url,
                citation=citation,
                retrieved_at=retrieved_at,
                curated_by=curated_by,
            ),
            comment=list(comment or []),
        )
        self.datasets.append(dataset)
        return dataset

    def publish(
        self,
        dataset: Dataset,
        *,
        test: Test | None = None,
        cell: CellInstance | None = None,
        cell_type: CellType | None = None,
        cell_specification: CellSpecification | dict[str, Any] | PathLike | None = None,
        datasheet_path: PathLike | None = None,
        publication_root: PathLike | None = None,
        publish_filename: str = DEFAULT_PUBLISH_FILENAME,
        html_filename: str = "index.html",
        dataset_glob: str = "**/*",
        emit_bundle_dir: bool = False,
        emit_html_page: bool = False,
        validation_policy: str = "strict",
    ) -> dict[str, Any]:
        resolved_test = test or dataset.test or self._resolve_dataset_test(dataset)
        if resolved_test is None:
            raise ValueError("Workspace.publish() requires a Test or a Dataset linked to a Test.")

        resolved_cell = cell or dataset.cell or resolved_test.cell or self._resolve_dataset_cell(dataset)
        if resolved_cell is None:
            raise ValueError("Workspace.publish() requires a Cell or a Dataset/Test linked to a Cell.")

        resolved_cell_type = cell_type or resolved_cell.cell_type or self._resolve_dataset_cell_type(dataset, resolved_cell)
        if resolved_cell_type is None:
            raise ValueError("Workspace.publish() requires a CellType or a linked Cell with cell_type set.")

        staged_dataset = self._stage_publication_dataset(
            dataset,
            publication_root=_as_path(publication_root) if publication_root is not None else self.root / "publication",
        )
        return publish_bundle(
            cell_type=resolved_cell_type,
            cell_instance=resolved_cell,
            test=resolved_test,
            dataset=staged_dataset,
            cell_specification=cell_specification,
            datasheet_path=datasheet_path,
            publish_filename=publish_filename,
            html_filename=html_filename,
            dataset_glob=dataset_glob,
            emit_bundle_dir=emit_bundle_dir,
            emit_html_page=emit_html_page,
            validation_policy=validation_policy,
        )

    def render(self) -> dict[str, list[dict[str, Any]]]:
        finalized = self._finalize()
        return {
            "cell_types": [item.to_record() for item in finalized["cell_types"]],
            "cell_instances": [item.to_record() for item in finalized["cells"]],
            "tests": [item.to_record() for item in finalized["tests"]],
            "datasets": [item.to_record() for item in finalized["datasets"]],
        }

    def save(
        self,
        *,
        source_root: PathLike | None = None,
        mode: str = "upsert",
        resolve_references: bool = False,
        validation_policy: str = "strict",
        build_index: bool = True,
    ) -> dict[str, Any]:
        target_root = _as_path(source_root) if source_root is not None else self.source_root
        finalized = self._finalize()

        results = {
            "cell_types": [
                save_cell_type(
                    item,
                    source_root=target_root,
                    mode=mode,
                    resolve_references=resolve_references,
                    validation_policy=validation_policy,
                )
                for item in finalized["cell_types"]
            ],
            "cell_instances": [
                save_cell_instance(
                    item,
                    source_root=target_root,
                    mode=mode,
                    resolve_references=resolve_references,
                    validation_policy=validation_policy,
                )
                for item in finalized["cells"]
            ],
            "tests": [
                save_test(
                    item,
                    source_root=target_root,
                    mode=mode,
                    resolve_references=resolve_references,
                    validation_policy=validation_policy,
                )
                for item in finalized["tests"]
            ],
            "datasets": [
                save_dataset(
                    item,
                    source_root=target_root,
                    mode=mode,
                    resolve_references=resolve_references,
                    validation_policy=validation_policy,
                )
                for item in finalized["datasets"]
            ],
        }

        if build_index:
            results["index"] = build_index_api(
                source_root=target_root,
                out_path=self.index_path,
                validate=True,
                validation_policy=validation_policy,
            )
        return results

    def save_descriptions(
        self,
        *,
        library_root: PathLike | None = None,
        package_root: PathLike | None = None,
        mode: str = "upsert",
        validate: bool = True,
        sync_packaged_copy: bool = True,
        build_rdf: bool = True,
        output_jsonld_dir: PathLike | None = None,
        aggregate_jsonld: PathLike | None = None,
        manifest_json: PathLike | None = None,
        clean_output: bool = False,
    ) -> dict[str, Any]:
        target_library_root = _as_path(library_root) if library_root is not None else self.library_root
        target_package_root = _as_path(package_root) if package_root is not None else self.package_root
        target_output_jsonld_dir = _as_path(output_jsonld_dir) if output_jsonld_dir is not None else self.library_rdf_root
        target_aggregate_jsonld = (
            _as_path(aggregate_jsonld) if aggregate_jsonld is not None else self.library_aggregate_jsonld
        )
        target_manifest_json = _as_path(manifest_json) if manifest_json is not None else self.library_manifest_json

        finalized_descriptions = [self._finalize_description(item) for item in self.descriptions]
        for original, finalized in zip(self.descriptions, finalized_descriptions, strict=True):
            _sync_model_state(original, finalized)

        results: dict[str, Any] = {
            "descriptions": [
                save_library_cell_type(
                    item,
                    library_root=target_library_root,
                    package_root=target_package_root,
                    mode=mode,
                    validate=validate,
                    sync_packaged_copy=sync_packaged_copy,
                    build_rdf=False,
                )
                for item in self.descriptions
            ]
        }
        if build_rdf:
            results["rdf"] = build_cell_type_library_rdf(
                input_dir=target_library_root,
                output_jsonld_dir=target_output_jsonld_dir,
                aggregate_jsonld=target_aggregate_jsonld,
                manifest_json=target_manifest_json,
                clean_output=clean_output,
            )
        return results

    def build_index(
        self,
        *,
        source_root: PathLike | None = None,
        out_path: PathLike | None = None,
        validate: bool = True,
        validation_policy: str = "strict",
    ) -> dict[str, Any]:
        target_root = _as_path(source_root) if source_root is not None else self.source_root
        target_index = _as_path(out_path) if out_path is not None else self.index_path
        return build_index_api(
            source_root=target_root,
            out_path=target_index,
            validate=validate,
            validation_policy=validation_policy,
        )

    def query_cell_types(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("cell_types_dir", self.source_root / "cell-types")
        return query_cell_types(**filters)

    def query(self, kind: str, /, **filters: Any) -> list[dict[str, Any]]:
        normalized = kind.strip().lower().replace("-", "_")
        if normalized in {"cell_type", "cell_types"}:
            filters.setdefault("cell_types_dir", self.source_root / "cell-types")
            return query_api(kind, **filters)
        if normalized in {"cell", "cells", "cell_instance", "cell_instances"}:
            filters.setdefault("directory", self.source_root / "cell-instances")
            return query_api(kind, **filters)
        if normalized in {"test", "tests"}:
            filters.setdefault("directory", self.source_root / "tests")
            return query_api(kind, **filters)
        if normalized in {"dataset", "datasets"}:
            filters.setdefault("directory", self.source_root / "datasets")
            return query_api(kind, **filters)
        if normalized in {"description", "descriptions", "library_cell_type", "library_cell_types"}:
            filters.setdefault("directory", self.library_root)
            return query_api(kind, **filters)
        return query_api(kind, **filters)

    def query_cells(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.source_root / "cell-instances")
        return query_cell_instances(**filters)

    def query_tests(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.source_root / "tests")
        return query_tests(**filters)

    def query_datasets(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.source_root / "datasets")
        return query_datasets(**filters)

    def query_descriptions(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.library_root)
        return query_library_cell_types(**filters)

    def _finalize(self) -> dict[str, list[Any]]:
        finalized_cell_types = [self._finalize_cell_type(item) for item in self.cell_types]
        cell_type_map = {id(original): finalized for original, finalized in zip(self.cell_types, finalized_cell_types, strict=True)}

        finalized_cells = [self._finalize_cell(item, cell_type_map) for item in self.cells]
        cell_map = {id(original): finalized for original, finalized in zip(self.cells, finalized_cells, strict=True)}

        finalized_tests = [self._finalize_test(item, cell_map) for item in self.tests]
        test_map = {id(original): finalized for original, finalized in zip(self.tests, finalized_tests, strict=True)}

        finalized_datasets = [self._finalize_dataset(item, cell_map, test_map) for item in self.datasets]

        dataset_ids_by_cell: dict[str, list[str]] = {}
        for dataset in finalized_datasets:
            if dataset.cell_instance_id is None or dataset.id is None:
                continue
            dataset_ids_by_cell.setdefault(dataset.cell_instance_id, []).append(dataset.id)

        dataset_ids_by_test: dict[str, list[str]] = {}
        for dataset in finalized_datasets:
            if dataset.test_id is None or dataset.id is None:
                continue
            dataset_ids_by_test.setdefault(dataset.test_id, []).append(dataset.id)

        for cell in finalized_cells:
            if cell.id is not None:
                cell.dataset_ids = list(dict.fromkeys(dataset_ids_by_cell.get(cell.id, [])))

        for test in finalized_tests:
            if test.id is not None:
                test.dataset_ids = list(dict.fromkeys(dataset_ids_by_test.get(test.id, [])))

        for original, finalized in zip(self.cell_types, finalized_cell_types, strict=True):
            _sync_model_state(original, finalized)
        for original, finalized in zip(self.cells, finalized_cells, strict=True):
            _sync_model_state(original, finalized)
        for original, finalized in zip(self.tests, finalized_tests, strict=True):
            _sync_model_state(original, finalized)
        for original, finalized in zip(self.datasets, finalized_datasets, strict=True):
            _sync_model_state(original, finalized)

        return {
            "cell_types": self.cell_types,
            "cells": self.cells,
            "tests": self.tests,
            "datasets": self.datasets,
        }

    def _stage_publication_dataset(self, dataset: Dataset, *, publication_root: Path) -> Dataset:
        local_path = self._dataset_local_path(dataset)
        if local_path is None:
            raise ValueError("Workspace.publish() requires dataset.path to point to a local file or directory.")
        if not local_path.exists():
            raise FileNotFoundError(f"Dataset path does not exist: {local_path}")

        source_path = local_path.resolve()
        if source_path.is_file():
            target_dir = publication_root / source_path.stem
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_dir / source_path.name)
        elif source_path.is_dir():
            target_dir = publication_root / source_path.name
            if target_dir != source_path:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source_path, target_dir, dirs_exist_ok=True)
            else:
                target_dir.mkdir(parents=True, exist_ok=True)
        else:
            raise ValueError(f"Dataset path is neither a file nor a directory: {source_path}")

        staged = dataset.model_copy(deep=True)
        staged.path = target_dir
        staged.access_url = target_dir.resolve().as_uri()
        staged.download_url = None
        staged.data_format = "application/vnd.battinfo.dataset-directory"
        staged.checksum = ChecksumInfo()
        return staged

    def _dataset_local_path(self, dataset: Dataset) -> Path | None:
        if dataset.dataset_path:
            return _as_path(dataset.dataset_path)
        if dataset.access_url:
            return _path_from_file_uri(dataset.access_url)
        return None

    def _resolve_dataset_test(self, dataset: Dataset) -> Test | None:
        if dataset.test_id is not None:
            for candidate in self.tests:
                if candidate.id == dataset.test_id:
                    return candidate
        if dataset.cell is not None:
            matches = [candidate for candidate in self.tests if candidate.cell is dataset.cell]
            if len(matches) == 1:
                return matches[0]
        if len(self.tests) == 1:
            return self.tests[0]
        return None

    def _resolve_dataset_cell(self, dataset: Dataset) -> CellInstance | None:
        if dataset.cell_instance_id is not None:
            for candidate in self.cells:
                if candidate.id == dataset.cell_instance_id:
                    return candidate
        if dataset.test_id is not None:
            for candidate in self.tests:
                if candidate.id == dataset.test_id and candidate.cell is not None:
                    return candidate.cell
        if len(self.cells) == 1:
            return self.cells[0]
        return None

    def _resolve_dataset_cell_type(self, dataset: Dataset, cell: CellInstance) -> CellType | None:
        if cell.cell_type is not None:
            return cell.cell_type
        if dataset.cell_instance_id is not None:
            for candidate in self.cells:
                if candidate.id == dataset.cell_instance_id and candidate.cell_type is not None:
                    return candidate.cell_type
        if len(self.cell_types) == 1:
            return self.cell_types[0]
        return None

    def _finalize_description(self, specification: CellSpecification) -> CellSpecification:
        finalized = specification.model_copy(deep=True)
        if finalized.source.type is None:
            finalized.source.type = "manual"
        if finalized.source.retrieved_at is None:
            finalized.source.retrieved_at = _now_unix()
        return finalized

    def _finalize_cell_type(self, cell_type: CellType) -> CellType:
        finalized = cell_type.model_copy(deep=True)
        if finalized.id is None:
            finalized.id = _entity_iri(
                "cell-type",
                "::".join(
                    [
                        _with_default(finalized.manufacturer, "unknown-manufacturer"),
                        _with_default(finalized.model, "unknown-model"),
                        _with_default(finalized.format, "unknown-format"),
                        _with_default(finalized.chemistry, "unknown-chemistry"),
                        finalized.size_code or "",
                    ]
                ),
            )
        if finalized.name is None:
            finalized.name = f"{finalized.manufacturer} {finalized.model}"
        if finalized.source.type is None:
            finalized.source.type = "datasheet"
        if finalized.source.file is None:
            finalized.source.file = "manual.json"
        if finalized.source.retrieved_at is None:
            finalized.source.retrieved_at = _now_unix()
        return finalized

    def _finalize_cell(self, cell: CellInstance, cell_type_map: dict[int, CellType]) -> CellInstance:
        finalized = cell.model_copy(deep=True, update={"cell_type": None})
        linked_type = cell_type_map.get(id(cell.cell_type)) if cell.cell_type is not None else None
        if finalized.cell_type_id is None and linked_type is not None:
            finalized.cell_type_id = linked_type.id
        if finalized.name is None:
            finalized.name = finalized.serial_number or finalized.batch_id or "cell"
        if finalized.id is None:
            finalized.id = _entity_iri(
                "cell",
                "::".join(
                    [
                        _with_default(finalized.cell_type_id, "unknown-cell-type"),
                        finalized.serial_number or "",
                        finalized.batch_id or "",
                        _with_default(finalized.name, "cell"),
                    ]
                ),
            )
        if finalized.source.type is None:
            finalized.source.type = "measurement"
        if finalized.source.retrieved_at is None:
            finalized.source.retrieved_at = _now_unix()
        return finalized

    def _finalize_test(self, test: Test, cell_map: dict[int, CellInstance]) -> Test:
        finalized = test.model_copy(deep=True, update={"cell": None})
        linked_cell = cell_map.get(id(test.cell)) if test.cell is not None else None
        if finalized.cell_instance_id is None and linked_cell is not None:
            finalized.cell_instance_id = linked_cell.id
        protocol_name = finalized.protocol.name or "test"
        if finalized.name is None:
            finalized.name = f"{linked_cell.name} {protocol_name}" if linked_cell is not None else protocol_name
        if finalized.id is None:
            finalized.id = _entity_iri(
                "test",
                "::".join(
                    [
                        _with_default(finalized.cell_instance_id, "unknown-cell"),
                        _with_default(finalized.test_kind, "other"),
                        protocol_name,
                        _with_default(finalized.name, "test"),
                    ]
                ),
            )
        if finalized.source.type is None:
            finalized.source.type = "measurement"
        if finalized.source.retrieved_at is None:
            finalized.source.retrieved_at = _now_unix()
        return finalized

    def _finalize_dataset(
        self,
        dataset: Dataset,
        cell_map: dict[int, CellInstance],
        test_map: dict[int, Test],
    ) -> Dataset:
        finalized = dataset.model_copy(deep=True, update={"cell": None, "test": None})
        linked_cell = cell_map.get(id(dataset.cell)) if dataset.cell is not None else None
        linked_test = test_map.get(id(dataset.test)) if dataset.test is not None else None
        if finalized.cell_instance_id is None and linked_cell is not None:
            finalized.cell_instance_id = linked_cell.id
        if finalized.cell_instance_id is None and linked_test is not None:
            finalized.cell_instance_id = linked_test.cell_instance_id
        if finalized.test_id is None and linked_test is not None:
            finalized.test_id = linked_test.id
        if finalized.name is None:
            finalized.name = finalized.dataset_path or finalized.access_url or "dataset"
        if finalized.created_at is None:
            finalized.created_at = _now_unix()
        if finalized.access_url is None and finalized.dataset_path is not None:
            finalized.access_url = _as_path(finalized.dataset_path).resolve().as_uri()
        if finalized.id is None:
            finalized.id = _entity_iri(
                "dataset",
                "::".join(
                    [
                        _with_default(finalized.cell_instance_id, "unknown-cell"),
                        finalized.test_id or "",
                        finalized.access_url or finalized.download_url or finalized.dataset_path or "",
                        _with_default(finalized.name, "dataset"),
                    ]
                ),
            )
        if finalized.source.type is None:
            finalized.source.type = "measurement"
        if finalized.source.retrieved_at is None:
            finalized.source.retrieved_at = finalized.created_at
        if finalized.source.url is None:
            finalized.source.url = finalized.access_url
        return finalized


__all__ = ["Workspace", "quantity", "q"]
