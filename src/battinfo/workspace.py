from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

if TYPE_CHECKING:
    from battinfo.local_workspace import LocalWorkspace

from battinfo.api import (
    build_cell_type_library_rdf,
    query_cell_instances,
    query_cell_types,
    query_datasets,
    query_library_cell_types,
    query_test_protocols,
    query_tests,
    save_cell_instance,
    save_cell_type,
    save_dataset,
    save_library_cell_type,
    save_test,
    save_test_protocol,
)
from battinfo.api import (
    build_index as build_index_api,
)
from battinfo.api import (
    query as query_api,
)
from battinfo.authoring import cell_description as build_cell_description
from battinfo.bundle import (
    CellInstance,
    CellSpecification,
    CellType,
    ChecksumInfo,
    Dataset,
    ProtocolInfo,
    ProvenanceInfo,
    Test,
    TestProtocol,
)
from battinfo.canonical_aliases import record_to_legacy_aliases, record_to_snake_aliases
from battinfo.publication import DEFAULT_PUBLISH_FILENAME
from battinfo.publication import publish as publish_bundle
from battinfo.validate.record import validate_record_report

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


_IRI_NAMESPACE: dict[str, str] = {
    "cell-type": "spec",
    "cell": "cell",
    "test-protocol": "spec",
    "test": "test",
    "dataset": "dataset",
    "organization": "organization",
    "electrode": "electrode",
    "material": "material",
}


def _entity_iri(entity_type: str, seed: str) -> str:
    namespace = _IRI_NAMESPACE.get(entity_type, entity_type)
    return f"https://w3id.org/battinfo/{namespace}/{_stable_uid(seed)}"


def _with_default(value: str | None, fallback: str) -> str:
    text = (value or "").strip()
    return text or fallback


def _as_path(path: PathLike) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _load_json(path: Path) -> dict[str, Any]:
    return record_to_snake_aliases(json.loads(path.read_text(encoding="utf-8")))


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
    """Human-facing BattINFO authoring surface for linked records.

    Use `Workspace` when you want to create, link, save, query, build publication
    packages, persist authoring state, and export BattINFO objects directly from
    Python. `LocalWorkspace` remains the separate disk-first scaffold used by the
    `battinfo workspace` CLI.
    """

    def __init__(
        self,
        root: PathLike = ".battinfo/workspace",
        *,
        source_dir_name: str = "examples",
        index_name: str = "index.json",
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        tenant: str | None = None,
        publisher: str | None = None,
        version: str | None = None,
        comment: list[str] | None = None,
        clean: bool = False,
    ) -> None:
        self.root = _as_path(root)
        if clean and self.root.exists():
            shutil.rmtree(self.root)
        self.source_root = self.root / source_dir_name
        self.index_path = self.root / index_name
        self.library_root = self.root / "library" / "cell-type"
        self.package_root = self.root / "package" / "cell-type"
        self.library_rdf_root = self.root / "library-rdf" / "cell-type"
        self.library_aggregate_jsonld = self.root / "ontology" / "library" / "cell-type.jsonld"
        self.library_manifest_json = self.root / "library-rdf" / "cell-type.index.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.name = name
        self.title = title
        self.description = description
        self.tenant = tenant
        self.publisher = publisher
        self.version = version
        self.comment = list(comment or [])

        self.descriptions: list[CellSpecification] = []
        self.cell_types: list[CellType] = []
        self.cells: list[CellInstance] = []
        self.test_protocols: list[TestProtocol] = []
        self.tests: list[Test] = []
        self.datasets: list[Dataset] = []

    @classmethod
    def open(cls, root: PathLike) -> "Workspace":
        from battinfo.workspace_state import workspace_open

        return workspace_open(root)

    def save_workspace(self) -> dict[str, Any]:
        from battinfo.workspace_state import workspace_save

        return workspace_save(self)

    def check_workspace(self, *, policy: str = "strict", write_report: bool = True) -> dict[str, Any]:
        from battinfo.workspace_state import workspace_check

        return workspace_check(self, policy=policy, write_report=write_report)

    def bundle_workspace(
        self,
        target: CellType | CellInstance | Test | Dataset | None = None,
        *,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        tenant: str | None = None,
        publisher: str | None = None,
        version: str | None = None,
        policy: str = "strict",
    ) -> dict[str, Any]:
        from battinfo.workspace_state import workspace_build_submission_package

        return workspace_build_submission_package(
            self,
            target=target,
            name=name,
            title=title,
            description=description,
            tenant=tenant,
            publisher=publisher,
            version=version,
            policy=policy,
        )

    def add(self, *objects: Any) -> "Workspace":
        """Add one or more authoring objects to the workspace by type."""
        def _add(obj: Any) -> None:
            if isinstance(obj, CellSpecification):
                _append_unique(self.descriptions, obj)
            elif isinstance(obj, CellType):
                _append_unique(self.cell_types, obj)
            elif isinstance(obj, TestProtocol):
                _append_unique(self.test_protocols, obj)
            elif isinstance(obj, CellInstance):
                if obj.cell_type is not None:
                    _add(obj.cell_type)
                _append_unique(self.cells, obj)
            elif isinstance(obj, Test):
                if obj.protocol_entity is not None:
                    _add(obj.protocol_entity)
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
                    "Workspace.add() supports CellSpecification, CellType, TestProtocol, Cell/CellInstance, Test, and Dataset objects."
                )
        for obj in objects:
            _add(obj)
        return self

    def load_cell_type(
        self,
        source: CellType | dict[str, Any] | PathLike,
        *,
        validate: bool = True,
        validation_policy: str = "strict",
    ) -> CellType:
        """Load one cell-type JSON source into the workspace.

        The source can be either a canonical BattINFO `cell-type` record with a
        top-level `product` object or a simpler authoring draft with fields like
        `manufacturer`, `model`, `format`, `chemistry`, and optional `specs`.
        Draft inputs are canonized later when the workspace renders or saves.
        """

        if isinstance(source, CellType):
            cell_type = source.model_copy(deep=True)
        else:
            payload = _load_json(_as_path(source)) if isinstance(source, (str, Path)) else dict(source)
            if isinstance(payload.get("cell_type"), dict) and "product" not in payload:
                payload = dict(payload)
                payload["product"] = dict(payload["cell_type"])
            if isinstance(payload.get("specification"), dict) and "product" not in payload:
                # Library cell-type format: promote specification fields for authoring path
                payload = dict(payload["specification"])
            if isinstance(payload.get("product"), dict):
                if validate:
                    report = validate_record_report(payload, policy=validation_policy)
                    if not report.ok:
                        raise ValueError(f"cell-type validation failed: {'; '.join(report.render_errors())}")
                cell_type = CellType.from_record(payload)
            else:
                cell_type = self._cell_type_from_authoring_payload(payload)

        _append_unique(self.cell_types, cell_type)
        return cell_type

    def load_cell_types(
        self,
        *sources: CellType | dict[str, Any] | PathLike,
        directory: PathLike | None = None,
        glob: str = "*.json",
        validate: bool = True,
        validation_policy: str = "strict",
    ) -> list[CellType]:
        """Load multiple cell-type JSON sources into the workspace."""

        inputs: list[CellType | dict[str, Any] | PathLike] = list(sources)
        if directory is not None:
            directory_path = _as_path(directory)
            if not directory_path.exists() or not directory_path.is_dir():
                raise ValueError(f"cell type directory does not exist: {directory_path}")
            inputs.extend(sorted(directory_path.glob(glob)))
        if not inputs:
            raise ValueError("load_cell_types requires one or more sources or a directory.")
        return [
            self.load_cell_type(
                item,
                validate=validate,
                validation_policy=validation_policy,
            )
            for item in inputs
        ]

    def load_test_protocol(
        self,
        source: TestProtocol | dict[str, Any] | PathLike,
        *,
        validate: bool = True,
        validation_policy: str = "strict",
    ) -> TestProtocol:
        """Load one test-protocol JSON source into the workspace."""

        if isinstance(source, TestProtocol):
            protocol = source.model_copy(deep=True)
        else:
            payload = _load_json(_as_path(source)) if isinstance(source, (str, Path)) else dict(source)
            if isinstance(payload.get("testProtocol"), dict) and "test_protocol" not in payload:
                payload = dict(payload)
                payload["test_protocol"] = dict(payload["testProtocol"])
            if isinstance(payload.get("test_protocol"), dict):
                if validate:
                    report = validate_record_report(payload, policy=validation_policy)
                    if not report.ok:
                        raise ValueError(f"test-protocol validation failed: {'; '.join(report.render_errors())}")
                protocol = TestProtocol.from_record(payload)
            else:
                protocol = self._test_protocol_from_authoring_payload(payload)

        _append_unique(self.test_protocols, protocol)
        return protocol

    def load_test_protocols(
        self,
        *sources: TestProtocol | dict[str, Any] | PathLike,
        directory: PathLike | None = None,
        glob: str = "*.json",
        validate: bool = True,
        validation_policy: str = "strict",
    ) -> list[TestProtocol]:
        """Load multiple test-protocol JSON sources into the workspace."""

        inputs: list[TestProtocol | dict[str, Any] | PathLike] = list(sources)
        if directory is not None:
            directory_path = _as_path(directory)
            if not directory_path.exists() or not directory_path.is_dir():
                raise ValueError(f"test protocol directory does not exist: {directory_path}")
            inputs.extend(sorted(directory_path.glob(glob)))
        if not inputs:
            raise ValueError("load_test_protocols requires one or more sources or a directory.")
        return [
            self.load_test_protocol(
                item,
                validate=validate,
                validation_policy=validation_policy,
            )
            for item in inputs
        ]

    def _cell_type_from_authoring_payload(self, payload: dict[str, Any]) -> CellType:
        model = payload.get("model")
        if model is None:
            model = payload.get("model_name")
        manufacturer = payload.get("manufacturer")
        format_value = payload.get("format")
        chemistry = payload.get("chemistry")
        if not all(isinstance(value, str) and value.strip() for value in (manufacturer, model, format_value, chemistry)):
            raise ValueError(
                "cell-type authoring JSON requires non-empty string fields: manufacturer, model, format, chemistry."
            )

        specs = payload.get("specs")
        if specs is None:
            specs = payload.get("nominal_properties")
        if specs is not None and not isinstance(specs, dict):
            raise ValueError("cell-type authoring JSON field 'specs' must be an object when provided.")

        comment = payload.get("comment")
        if comment is None:
            comment = payload.get("notes")
        if comment is None:
            comment_list: list[str] = []
        elif isinstance(comment, str):
            comment_list = [comment]
        elif isinstance(comment, list) and all(isinstance(item, str) for item in comment):
            comment_list = list(comment)
        else:
            raise ValueError("cell-type authoring JSON field 'comment' must be a string or list of strings.")

        provenance = payload.get("provenance")
        if provenance is None:
            provenance = {}
        elif not isinstance(provenance, dict):
            raise ValueError("cell-type authoring JSON field 'provenance' must be an object when provided.")

        source_type = payload.get("source_type", provenance.get("source_type"))
        source_file = payload.get("source_file", provenance.get("source_file"))
        source_url = payload.get("source_url", provenance.get("source_url"))
        citation = payload.get("citation", provenance.get("citation"))
        retrieved_at = payload.get("retrieved_at", provenance.get("retrieved_at"))
        datasheet_revision = payload.get("datasheet_revision")
        if datasheet_revision is None:
            datasheet_revision = provenance.get("datasheet_revision")
        iec_code = payload.get("iec_code")
        country_of_origin = payload.get("country_of_origin")
        year = payload.get("year")
        name = payload.get("name")

        return CellType(
            name=name if isinstance(name, str) and name.strip() else None,
            manufacturer=manufacturer,
            model=model,
            format=format_value,
            chemistry=chemistry,
            size_code=payload.get("size_code"),
            iec_code=iec_code if isinstance(iec_code, str) else None,
            country_of_origin=country_of_origin if isinstance(country_of_origin, str) else None,
            year=year if isinstance(year, int) else int(year) if isinstance(year, str) and year.strip().isdigit() else None,
            positive_electrode_basis=payload.get("positive_electrode_basis"),
            negative_electrode_basis=payload.get("negative_electrode_basis"),
            datasheet_revision=datasheet_revision,
            nominal_properties=dict(specs or {}),
            source=ProvenanceInfo(
                type=source_type if isinstance(source_type, str) else None,
                file=source_file if isinstance(source_file, str) else None,
                url=source_url if isinstance(source_url, str) else None,
                citation=citation if isinstance(citation, str) else None,
                retrieved_at=retrieved_at,
            ),
            comment=comment_list,
        )

    def _test_protocol_from_authoring_payload(self, payload: dict[str, Any]) -> TestProtocol:
        name = payload.get("name")
        kind = payload.get("kind")
        if not (isinstance(name, str) and name.strip() and isinstance(kind, str) and kind.strip()):
            raise ValueError("test-protocol authoring JSON requires non-empty string fields: name, kind.")

        comment = payload.get("comment")
        if comment is None:
            comment = payload.get("notes")
        if comment is None:
            comment_list: list[str] = []
        elif isinstance(comment, str):
            comment_list = [comment]
        elif isinstance(comment, list) and all(isinstance(item, str) for item in comment):
            comment_list = list(comment)
        else:
            raise ValueError("test-protocol authoring JSON field 'comment' must be a string or list of strings.")

        provenance = payload.get("provenance")
        if provenance is None:
            provenance = {}
        elif not isinstance(provenance, dict):
            raise ValueError("test-protocol authoring JSON field 'provenance' must be an object when provided.")

        conditions = payload.get("conditions")
        if conditions is None:
            conditions = {}
        elif not isinstance(conditions, dict):
            raise ValueError("test-protocol authoring JSON field 'conditions' must be an object when provided.")

        setpoints = payload.get("setpoints")
        if setpoints is None:
            setpoints = {}
        elif not isinstance(setpoints, dict):
            raise ValueError("test-protocol authoring JSON field 'setpoints' must be an object when provided.")

        termination_criteria = payload.get("termination_criteria")
        if termination_criteria is None:
            termination_criteria = {}
        elif not isinstance(termination_criteria, dict):
            raise ValueError("test-protocol authoring JSON field 'termination_criteria' must be an object when provided.")

        measurement_outputs = payload.get("measurement_outputs")
        if measurement_outputs is None:
            measurement_outputs = []
        elif not (
            isinstance(measurement_outputs, list)
            and all(isinstance(item, dict) for item in measurement_outputs)
        ):
            raise ValueError("test-protocol authoring JSON field 'measurement_outputs' must be a list of objects.")

        source_type = payload.get("source_type", provenance.get("source_type"))
        source_file = payload.get("source_file", provenance.get("source_file"))
        source_url = payload.get("source_url", provenance.get("source_url"))
        citation = payload.get("citation", provenance.get("citation"))
        retrieved_at = payload.get("retrieved_at", provenance.get("retrieved_at"))
        workflow_version = payload.get("workflow_version", provenance.get("workflow_version"))

        return TestProtocol(
            name=name,
            test_kind=kind,
            description=payload.get("description"),
            version=payload.get("version"),
            protocol=ProtocolInfo(url=payload.get("protocol_url")),
            conditions=dict(conditions),
            setpoints=dict(setpoints),
            termination_criteria=dict(termination_criteria),
            measurement_outputs=[dict(item) for item in measurement_outputs],
            source=ProvenanceInfo(
                type=source_type if isinstance(source_type, str) else None,
                file=source_file if isinstance(source_file, str) else None,
                url=source_url if isinstance(source_url, str) else None,
                citation=citation if isinstance(citation, str) else None,
                retrieved_at=retrieved_at,
                workflow_version=workflow_version if isinstance(workflow_version, str) else None,
            ),
            comment=comment_list,
        )

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
        coin_hardware: Any = None,
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
            coin_hardware=coin_hardware,
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
        product_type: str | None = None,
        specs: Any = None,
        size_code: str | None = None,
        iec_code: str | None = None,
        country_of_origin: str | None = None,
        year: int | None = None,
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
        from battinfo.bundle import CellProductType
        resolved_pt = CellProductType(product_type) if product_type is not None else None
        cell_type = CellType(
            manufacturer=manufacturer,
            model=model,
            format=format,
            chemistry=chemistry,
            product_type=resolved_pt,
            size_code=size_code,
            iec_code=iec_code,
            country_of_origin=country_of_origin,
            year=year,
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

    def test_protocol(
        self,
        *,
        name: str,
        kind: str,
        description: str | None = None,
        steps: list[str] | None = None,
        cycles: int | None = None,
        version: str | None = None,
        protocol_url: str | None = None,
        conditions: Any = None,
        setpoints: Any = None,
        termination_criteria: Any = None,
        measurement_outputs: list[dict[str, Any]] | None = None,
        source_type: str = "manual",
        source_url: str | None = None,
        source_file: str | None = None,
        citation: str | None = None,
        retrieved_at: int | str | None = None,
        workflow_version: str | None = None,
        comment: list[str] | None = None,
    ) -> TestProtocol:
        protocol = TestProtocol(
            name=name,
            test_kind=kind,
            description=description,
            steps=list(steps) if steps else [],
            cycles=cycles,
            version=version,
            protocol=ProtocolInfo(url=protocol_url),
            conditions=_mapping_value(conditions),
            setpoints=_mapping_value(setpoints),
            termination_criteria=_mapping_value(termination_criteria),
            measurement_outputs=[dict(item) for item in (measurement_outputs or [])],
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
        self.test_protocols.append(protocol)
        return protocol

    def test(
        self,
        cell: CellInstance,
        *,
        kind: str | None = None,
        protocol_ref: TestProtocol | None = None,
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
        protocol_name = protocol or (protocol_ref.name if protocol_ref is not None else None)
        protocol_link = protocol_url or (protocol_ref.protocol_url if protocol_ref is not None else None)
        resolved_kind = kind or (str(protocol_ref.test_kind) if protocol_ref is not None else None)
        if resolved_kind is None:
            raise ValueError("Workspace.test() requires kind or protocol_ref.")
        test = Test(
            name=name,
            test_kind=resolved_kind,
            protocol_id=protocol_ref.id if protocol_ref is not None else None,
            protocol_entity=protocol_ref,
            cell=cell,
            description=description,
            status=status,
            protocol=ProtocolInfo(name=protocol_name, url=protocol_link),
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
        return self.build_publication_package(
            dataset,
            test=test,
            cell=cell,
            cell_type=cell_type,
            cell_specification=cell_specification,
            datasheet_path=datasheet_path,
            publication_root=publication_root,
            publish_filename=publish_filename,
            html_filename=html_filename,
            dataset_glob=dataset_glob,
            emit_bundle_dir=emit_bundle_dir,
            emit_html_page=emit_html_page,
            validation_policy=validation_policy,
        )

    def build_publication_package(
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
        emit_ro_crate_metadata: bool = True,
        emit_datacite_metadata: bool = True,
        emit_dcat_export: bool = False,
        validation_policy: str = "strict",
    ) -> dict[str, Any]:
        """Preferred name for locally building a publication package from `Workspace`."""

        resolved_test, resolved_cell, resolved_cell_type = self._resolve_dataset_chain(
            dataset,
            test=test,
            cell=cell,
            cell_type=cell_type,
            action="build_publication_package",
        )
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
            emit_ro_crate_metadata=emit_ro_crate_metadata,
            emit_datacite_metadata=emit_datacite_metadata,
            emit_dcat_export=emit_dcat_export,
            validation_policy=validation_policy,
        )

    def export_release(
        self,
        dataset: Dataset,
        *,
        registry: Any,
        root: PathLike | None = None,
        test: Test | None = None,
        cell: CellInstance | None = None,
        cell_type: CellType | None = None,
        workspace_id: str | None = None,
        publisher_id: str | None = None,
        version: str | None = None,
        community: str | None = None,
        title: str | None = None,
        description: str | None = None,
        zenodo: Any = None,
        comment: list[str] | None = None,
        capture_artifact: bool = True,
        force: bool = False,
    ) -> "LocalWorkspace":
        """Compatibility alias for export_submission_workspace(...)."""

        return self.export_submission_workspace(
            dataset,
            registry=registry,
            root=root,
            test=test,
            cell=cell,
            cell_type=cell_type,
            workspace_id=workspace_id,
            publisher_id=publisher_id,
            version=version,
            community=community,
            title=title,
            description=description,
            zenodo=zenodo,
            comment=comment,
            capture_artifact=capture_artifact,
            force=force,
        )

    def export_submission_workspace(
        self,
        dataset: Dataset,
        *,
        registry: Any,
        root: PathLike | None = None,
        test: Test | None = None,
        cell: CellInstance | None = None,
        cell_type: CellType | None = None,
        workspace_id: str | None = None,
        publisher_id: str | None = None,
        version: str | None = None,
        community: str | None = None,
        title: str | None = None,
        description: str | None = None,
        zenodo: Any = None,
        comment: list[str] | None = None,
        capture_artifact: bool = True,
        force: bool = False,
    ) -> "LocalWorkspace":
        """Export one linked dataset chain to a disk-backed submission workspace."""

        from battinfo.local_workspace import LocalWorkspace

        resolved_test, resolved_cell, resolved_cell_type = self._resolve_dataset_chain(
            dataset,
            test=test,
            cell=cell,
            cell_type=cell_type,
            action="export_submission_workspace",
        )
        release_root = _as_path(root) if root is not None else self.root / "release"
        if release_root.exists():
            if not release_root.is_dir():
                raise ValueError(f"workspace path is not a directory: {release_root}")
            if any(release_root.iterdir()):
                if not force:
                    raise ValueError(f"workspace directory is not empty: {release_root}")
                shutil.rmtree(release_root)
        release_workspace = LocalWorkspace(release_root)
        release_workspace.capture(
            resolved_cell_type,
            resolved_cell,
            resolved_test,
            dataset,
            workspace_id=workspace_id,
            registry=registry,
            publisher_id=publisher_id,
            version=version,
            community=community,
            title=title,
            description=description,
            zenodo=zenodo,
            comment=comment,
            capture_artifact=capture_artifact,
        )
        return release_workspace

    def build_release(
        self,
        dataset: Dataset,
        *,
        registry: Any,
        root: PathLike | None = None,
        test: Test | None = None,
        cell: CellInstance | None = None,
        cell_type: CellType | None = None,
        workspace_id: str | None = None,
        publisher_id: str | None = None,
        version: str | None = None,
        community: str | None = None,
        title: str | None = None,
        description: str | None = None,
        zenodo: Any = None,
        comment: list[str] | None = None,
        capture_artifact: bool = True,
        force: bool = False,
        policy: str = "strict",
    ) -> dict[str, Any]:
        """Compatibility alias for build_submission_package(...)."""

        return self.build_submission_package(
            dataset,
            registry=registry,
            root=root,
            test=test,
            cell=cell,
            cell_type=cell_type,
            workspace_id=workspace_id,
            publisher_id=publisher_id,
            version=version,
            community=community,
            title=title,
            description=description,
            zenodo=zenodo,
            comment=comment,
            capture_artifact=capture_artifact,
            force=force,
            policy=policy,
        )

    def build_submission_package(
        self,
        dataset: Dataset,
        *,
        registry: Any,
        root: PathLike | None = None,
        test: Test | None = None,
        cell: CellInstance | None = None,
        cell_type: CellType | None = None,
        workspace_id: str | None = None,
        publisher_id: str | None = None,
        version: str | None = None,
        community: str | None = None,
        title: str | None = None,
        description: str | None = None,
        zenodo: Any = None,
        comment: list[str] | None = None,
        capture_artifact: bool = True,
        force: bool = False,
        policy: str = "strict",
    ) -> dict[str, Any]:
        """Create a disk-backed submission workspace and write a submission package."""

        release_workspace = self.export_submission_workspace(
            dataset,
            registry=registry,
            root=root,
            test=test,
            cell=cell,
            cell_type=cell_type,
            workspace_id=workspace_id,
            publisher_id=publisher_id,
            version=version,
            community=community,
            title=title,
            description=description,
            zenodo=zenodo,
            comment=comment,
            capture_artifact=capture_artifact,
            force=force,
        )
        return release_workspace.build_submission_package(policy=policy)

    def render(self) -> dict[str, list[dict[str, Any]]]:
        finalized = self._finalize()
        return {
            "cell_types": [item.to_record() for item in finalized["cell_types"]],
            "cell_instances": [item.to_record() for item in finalized["cells"]],
            "test_protocols": [item.to_record() for item in finalized["test_protocols"]],
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
            "test_protocols": [
                save_test_protocol(
                    item,
                    source_root=target_root,
                    mode=mode,
                    resolve_references=resolve_references,
                    validation_policy=validation_policy,
                )
                for item in finalized["test_protocols"]
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
        filters.setdefault("cell_types_dir", self.source_root / "cell-type")
        return query_cell_types(**filters)

    def query(self, kind: str, /, **filters: Any) -> list[dict[str, Any]]:
        normalized = kind.strip().lower().replace("-", "_")
        if normalized in {"cell_type", "cell_types"}:
            filters.setdefault("cell_types_dir", self.source_root / "cell-type")
            return query_api(kind, **filters)
        if normalized in {"cell", "cells", "cell_instance", "cell_instances"}:
            filters.setdefault("directory", self.source_root / "cell-instance")
            return query_api(kind, **filters)
        if normalized in {"test_protocol", "test_protocols"}:
            filters.setdefault("directory", self.source_root / "test-protocol")
            return query_api(kind, **filters)
        if normalized in {"test", "tests"}:
            filters.setdefault("directory", self.source_root / "test")
            return query_api(kind, **filters)
        if normalized in {"dataset", "datasets"}:
            filters.setdefault("directory", self.source_root / "dataset")
            return query_api(kind, **filters)
        if normalized in {"description", "descriptions", "library_cell_type", "library_cell_types"}:
            filters.setdefault("directory", self.library_root)
            return query_api(kind, **filters)
        return query_api(kind, **filters)

    def query_cells(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.source_root / "cell-instance")
        return query_cell_instances(**filters)

    def query_tests(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.source_root / "test")
        return query_tests(**filters)

    def query_test_protocols(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.source_root / "test-protocol")
        return query_test_protocols(**filters)

    def query_datasets(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.source_root / "dataset")
        return query_datasets(**filters)

    def query_descriptions(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.library_root)
        return query_library_cell_types(**filters)

    def _finalize(self) -> dict[str, list[Any]]:
        finalized_cell_types = [self._finalize_cell_type(item) for item in self.cell_types]
        cell_type_map = {id(original): finalized for original, finalized in zip(self.cell_types, finalized_cell_types, strict=True)}

        finalized_cells = [self._finalize_cell(item, cell_type_map) for item in self.cells]
        cell_map = {id(original): finalized for original, finalized in zip(self.cells, finalized_cells, strict=True)}

        finalized_test_protocols = [self._finalize_test_protocol(item) for item in self.test_protocols]
        test_protocol_map = {
            id(original): finalized for original, finalized in zip(self.test_protocols, finalized_test_protocols, strict=True)
        }

        finalized_tests = [self._finalize_test(item, cell_map, test_protocol_map) for item in self.tests]
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
        for original, finalized in zip(self.test_protocols, finalized_test_protocols, strict=True):
            _sync_model_state(original, finalized)
        for original, finalized in zip(self.tests, finalized_tests, strict=True):
            _sync_model_state(original, finalized)
        for original, finalized in zip(self.datasets, finalized_datasets, strict=True):
            _sync_model_state(original, finalized)

        return {
            "cell_types": self.cell_types,
            "cells": self.cells,
            "test_protocols": self.test_protocols,
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

    def _resolve_dataset_chain(
        self,
        dataset: Dataset,
        *,
        test: Test | None = None,
        cell: CellInstance | None = None,
        cell_type: CellType | None = None,
        action: str,
    ) -> tuple[Test, CellInstance, CellType]:
        resolved_test = test or dataset.test or self._resolve_dataset_test(dataset)
        if resolved_test is None:
            raise ValueError(f"Workspace.{action}() requires a Test or a Dataset linked to a Test.")

        resolved_cell = cell or dataset.cell or resolved_test.cell or self._resolve_dataset_cell(dataset)
        if resolved_cell is None:
            raise ValueError(f"Workspace.{action}() requires a Cell or a Dataset/Test linked to a Cell.")

        resolved_cell_type = cell_type or resolved_cell.cell_type or self._resolve_dataset_cell_type(dataset, resolved_cell)
        if resolved_cell_type is None:
            raise ValueError(f"Workspace.{action}() requires a CellType or a linked Cell with cell_type set.")

        return resolved_test, resolved_cell, resolved_cell_type

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

    def _finalize_test_protocol(self, protocol: TestProtocol) -> TestProtocol:
        finalized = protocol.model_copy(deep=True)
        if finalized.id is None:
            finalized.id = _entity_iri(
                "test-protocol",
                "::".join(
                    [
                        _with_default(finalized.test_kind, "other"),
                        _with_default(finalized.name, "test-protocol"),
                        finalized.version or "",
                    ]
                ),
            )
        if finalized.source.type is None:
            finalized.source.type = "manual"
        if finalized.source.file is None:
            finalized.source.file = "manual.json"
        if finalized.source.retrieved_at is None:
            finalized.source.retrieved_at = _now_unix()
        return finalized

    def _finalize_test(
        self,
        test: Test,
        cell_map: dict[int, CellInstance],
        test_protocol_map: dict[int, TestProtocol],
    ) -> Test:
        finalized = test.model_copy(deep=True, update={"cell": None, "protocol_entity": None})
        linked_cell = cell_map.get(id(test.cell)) if test.cell is not None else None
        linked_protocol = test_protocol_map.get(id(test.protocol_entity)) if test.protocol_entity is not None else None
        if finalized.cell_instance_id is None and linked_cell is not None:
            finalized.cell_instance_id = linked_cell.id
        if finalized.protocol_id is None and linked_protocol is not None:
            finalized.protocol_id = linked_protocol.id
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
