from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

if TYPE_CHECKING:
    from battinfo.local_workspace import LocalWorkspace

from battinfo._jsonio import read_record_json as _load_json
from battinfo.api import (
    build_cell_spec_library_rdf,
    query_cell_instances,
    query_cell_specs,
    query_datasets,
    query_library_cell_specs,
    query_test_specs,
    query_tests,
    save_cell_instance,
    save_cell_spec,
    save_dataset,
    save_library_cell_spec,
    save_test,
    save_test_spec,
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
    ChecksumInfo,
    Dataset,
    ProtocolInfo,
    ProvenanceInfo,
    Test,
    TestConformance,
    TestSpec,
)
from battinfo.entities import iri_namespace_map
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


# Derived from the entity registry (registered record types), plus extra
# namespaces for things that are not yet first-class record types.
_IRI_NAMESPACE: dict[str, str] = {
    **iri_namespace_map(),
    "organization": "organization",
    "electrode": "electrode",
}


def _entity_iri(entity_type: str, seed: str) -> str:
    namespace = _IRI_NAMESPACE.get(entity_type, entity_type)
    return f"https://w3id.org/battinfo/{namespace}/{_stable_uid(seed)}"


def _with_default(value: str | None, fallback: str) -> str:
    text = (value or "").strip()
    return text or fallback


# Fields that vary across runs (or are the IRI itself) and must NOT influence a
# content-derived disambiguation seed — otherwise a re-minted IRI would be unstable
# across re-runs (e.g. a finalize-time ``retrieved_at`` timestamp).
_VOLATILE_SEED_KEYS = frozenset(
    {"id", "uid", "retrieved_at", "created_at", "modified_at", "generated_at", "imported_at"}
)


def _strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_volatile(v) for k, v in value.items() if k not in _VOLATILE_SEED_KEYS}
    if isinstance(value, list):
        return [_strip_volatile(v) for v in value]
    return value


def _content_seed(entity: Any) -> str:
    """A stable, order-independent seed from an entity's distinguishing content
    (its canonical record minus the IRI and volatile timestamps)."""
    data = entity.model_dump(mode="json", exclude_none=True)
    return json.dumps(_strip_volatile(data), sort_keys=True, ensure_ascii=False)


def _disambiguate_entity_ids(entities: Sequence[Any], entity_type: str) -> None:
    """Ensure auto-minted IRIs are unique across distinct authored entities.

    Deterministic IRIs are seeded from a record's identity fields, so two
    genuinely-distinct entities whose identity fields happen to match — e.g. two
    cell-specs for one manufacturer+model with different capacities, or two unnamed
    cycling tests on one cell — mint the *same* IRI. On save each record is written
    to a file named after its IRI, so the duplicate silently overwrote its sibling
    and one record was lost.

    When >=2 entities collide on one IRI, re-mint *every* member of that group from a
    hash of its distinguishing content (``{iri}::{content}``). This is
    order-independent — a given record keeps the same IRI regardless of sibling order
    or re-run — and guarantees distinct content can never overwrite. A genuine
    full-content duplicate (identical content) falls back to a stable ordinal suffix
    so it still persists. Entities whose IRI is already unique are untouched,
    preserving the idempotent identity-seeded IRI for the common single-record case.

    Note: adding an identity-colliding sibling later re-mints a previously-unique record
    to a content-seeded IRI — the deliberate cost of order-independence. This loses no
    data within a workspace, since save() stages-then-swaps the full finalized set.
    """
    by_id: dict[str, list[Any]] = {}
    for entity in entities:
        current = getattr(entity, "id", None)
        if current is not None:
            by_id.setdefault(current, []).append(entity)

    seen: set[str] = set()
    for entity in entities:
        current = getattr(entity, "id", None)
        if current is None:
            continue
        group = by_id.get(current)
        if group is not None and len(group) > 1:
            # Distinct entities sharing an IRI: re-seed from content (order-independent).
            current = _entity_iri(entity_type, f"{current}::{_content_seed(entity)}")
        if current in seen:
            # Genuine full-content duplicate — keep both with a stable ordinal suffix.
            ordinal = 1
            candidate = _entity_iri(entity_type, f"{current}::dup{ordinal}")
            while candidate in seen:
                ordinal += 1
                candidate = _entity_iri(entity_type, f"{current}::dup{ordinal}")
            current = candidate
        entity.id = current
        seen.add(current)


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
    cand_id = getattr(candidate, "id", None)
    for existing in items:
        if existing is candidate:
            return
        # Two distinct objects with the same canonical id are the same entity
        # (e.g. a cell-spec and its specification, now merged) — keep only one.
        if cand_id is not None and getattr(existing, "id", None) == cand_id:
            return
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
        self.library_root = self.root / "library" / "cell-spec"
        self.package_root = self.root / "package" / "cell-spec"
        self.library_rdf_root = self.root / "library-rdf" / "cell-spec"
        self.library_aggregate_jsonld = self.root / "ontology" / "library" / "cell-spec.jsonld"
        self.library_manifest_json = self.root / "library-rdf" / "cell-spec.index.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.name = name
        self.title = title
        self.description = description
        self.tenant = tenant
        self.publisher = publisher
        self.version = version
        self.comment = list(comment or [])

        self.descriptions: list[CellSpecification] = []
        self.cell_specs: list[CellSpecification] = []
        self.cells: list[CellInstance] = []
        self.test_specs: list[TestSpec] = []
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
        target: CellSpecification | CellInstance | Test | Dataset | None = None,
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
            # The authoring model and the datasheet model are now one CellSpecification
            # (a BatteryCellSpecification); add() routes it to the canonical cell-spec
            # collection. The datasheet-library workflow uses the dedicated
            # add_description/save_descriptions methods.
            if isinstance(obj, CellSpecification):
                _append_unique(self.cell_specs, obj)
            elif isinstance(obj, TestSpec):
                _append_unique(self.test_specs, obj)
            elif isinstance(obj, CellInstance):
                if obj.cell_spec is not None:
                    _add(obj.cell_spec)
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
                    "Workspace.add() supports CellSpecification, CellSpecification, TestSpec, Cell/CellInstance, Test, and Dataset objects."
                )
        for obj in objects:
            _add(obj)
        return self

    def load_cell_spec(
        self,
        source: CellSpecification | dict[str, Any] | PathLike,
        *,
        validate: bool = True,
        validation_policy: str = "strict",
    ) -> CellSpecification:
        """Load one cell-spec JSON source into the workspace.

        The source can be either a canonical BattINFO `cell-spec` record with a
        top-level `product` object or a simpler authoring draft with fields like
        `manufacturer`, `model`, `format`, `chemistry`, and optional `specs`.
        Draft inputs are canonized later when the workspace renders or saves.
        """

        if isinstance(source, CellSpecification):
            cell_spec = source.model_copy(deep=True)
        else:
            payload = _load_json(_as_path(source)) if isinstance(source, (str, Path)) else dict(source)
            if isinstance(payload.get("cell_spec"), dict) and "cell_spec" not in payload:
                payload = dict(payload)
                payload["cell_spec"] = dict(payload["cell_spec"])
            if isinstance(payload.get("specification"), dict) and "cell_spec" not in payload:
                # Library cell-spec format: promote specification fields for authoring path
                payload = dict(payload["specification"])
            if isinstance(payload.get("cell_spec"), dict):
                if validate:
                    report = validate_record_report(payload, policy=validation_policy)
                    if not report.ok:
                        raise ValueError(f"cell-spec validation failed: {'; '.join(report.render_errors())}")
                cell_spec = CellSpecification.from_record(payload)
            else:
                cell_spec = self._cell_spec_from_authoring_payload(payload)

        _append_unique(self.cell_specs, cell_spec)
        return cell_spec

    def load_cell_specs(
        self,
        *sources: CellSpecification | dict[str, Any] | PathLike,
        directory: PathLike | None = None,
        glob: str = "*.json",
        validate: bool = True,
        validation_policy: str = "strict",
    ) -> list[CellSpecification]:
        """Load multiple cell-spec JSON sources into the workspace."""

        inputs: list[CellSpecification | dict[str, Any] | PathLike] = list(sources)
        if directory is not None:
            directory_path = _as_path(directory)
            if not directory_path.exists() or not directory_path.is_dir():
                raise ValueError(f"cell type directory does not exist: {directory_path}")
            inputs.extend(sorted(directory_path.glob(glob)))
        if not inputs:
            raise ValueError("load_cell_specs requires one or more sources or a directory.")
        return [
            self.load_cell_spec(
                item,
                validate=validate,
                validation_policy=validation_policy,
            )
            for item in inputs
        ]

    def load_test_spec(
        self,
        source: TestSpec | dict[str, Any] | PathLike,
        *,
        validate: bool = True,
        validation_policy: str = "strict",
    ) -> TestSpec:
        """Load one test-protocol JSON source into the workspace."""

        if isinstance(source, TestSpec):
            protocol = source.model_copy(deep=True)
        else:
            payload = _load_json(_as_path(source)) if isinstance(source, (str, Path)) else dict(source)
            if isinstance(payload.get("TestSpec"), dict) and "test_spec" not in payload and "test_protocol" not in payload:
                payload = dict(payload)
                payload["test_spec"] = dict(payload["TestSpec"])
            # accept both "test_spec" (current) and "test_protocol" (legacy) record key
            if "test_protocol" in payload and "test_spec" not in payload:
                payload = dict(payload)
                payload["test_spec"] = payload["test_protocol"]
            if isinstance(payload.get("test_spec"), dict):
                if validate:
                    report = validate_record_report(payload, policy=validation_policy)
                    if not report.ok:
                        raise ValueError(f"test-protocol validation failed: {'; '.join(report.render_errors())}")
                protocol = TestSpec.from_record(payload)
            else:
                protocol = self._test_spec_from_authoring_payload(payload)

        _append_unique(self.test_specs, protocol)
        return protocol

    def load_test_specs(
        self,
        *sources: TestSpec | dict[str, Any] | PathLike,
        directory: PathLike | None = None,
        glob: str = "*.json",
        validate: bool = True,
        validation_policy: str = "strict",
    ) -> list[TestSpec]:
        """Load multiple test-protocol JSON sources into the workspace."""

        inputs: list[TestSpec | dict[str, Any] | PathLike] = list(sources)
        if directory is not None:
            directory_path = _as_path(directory)
            if not directory_path.exists() or not directory_path.is_dir():
                raise ValueError(f"test spec directory does not exist: {directory_path}")
            inputs.extend(sorted(directory_path.glob(glob)))
        if not inputs:
            raise ValueError("load_test_specs requires one or more sources or a directory.")
        return [
            self.load_test_spec(
                item,
                validate=validate,
                validation_policy=validation_policy,
            )
            for item in inputs
        ]

    def _cell_spec_from_authoring_payload(self, payload: dict[str, Any]) -> CellSpecification:
        model = payload.get("model")
        if model is None:
            model = payload.get("model_name")
        manufacturer = payload.get("manufacturer")
        format_value = payload.get("format")
        chemistry = payload.get("chemistry")
        if not all(isinstance(value, str) and value.strip() for value in (manufacturer, model, format_value, chemistry)):
            raise ValueError(
                "cell-spec authoring JSON requires non-empty string fields: manufacturer, model, format, chemistry."
            )

        specs = payload.get("properties")
        if specs is not None and not isinstance(specs, dict):
            raise ValueError("cell-spec authoring JSON field 'properties' must be an object when provided.")

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
            raise ValueError("cell-spec authoring JSON field 'comment' must be a string or list of strings.")

        provenance = payload.get("provenance")
        if provenance is None:
            provenance = {}
        elif not isinstance(provenance, dict):
            raise ValueError("cell-spec authoring JSON field 'provenance' must be an object when provided.")

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

        return CellSpecification(
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
            properties=dict(specs or {}),
            source=ProvenanceInfo(
                type=source_type if isinstance(source_type, str) else None,
                file=source_file if isinstance(source_file, str) else None,
                url=source_url if isinstance(source_url, str) else None,
                citation=citation if isinstance(citation, str) else None,
                retrieved_at=retrieved_at,
            ),
            comment=comment_list,
        )

    def _test_spec_from_authoring_payload(self, payload: dict[str, Any]) -> TestSpec:
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

        record_settings = payload.get("record")
        if record_settings is None:
            record_settings = {}
        elif not isinstance(record_settings, dict):
            raise ValueError("test-protocol authoring JSON field 'record' must be an object when provided.")

        safety = payload.get("safety")
        if safety is None:
            safety = {}
        elif not isinstance(safety, dict):
            raise ValueError("test-protocol authoring JSON field 'safety' must be an object when provided.")

        artifacts = payload.get("artifacts")
        if artifacts is None:
            artifacts = []
        elif not (isinstance(artifacts, list) and all(isinstance(item, dict) for item in artifacts)):
            raise ValueError("test-protocol authoring JSON field 'artifacts' must be a list of objects.")

        source_type = payload.get("source_type", provenance.get("source_type"))
        source_file = payload.get("source_file", provenance.get("source_file"))
        source_url = payload.get("source_url", provenance.get("source_url"))
        citation = payload.get("citation", provenance.get("citation"))
        retrieved_at = payload.get("retrieved_at", provenance.get("retrieved_at"))
        workflow_version = payload.get("workflow_version", provenance.get("workflow_version"))

        # Descriptive method: a pre-built structured `method` wins; otherwise parse
        # the PyBaMM-style `experiment`/`steps` strings (the default human interface).
        method_fields: dict[str, Any] = {}
        method = payload.get("method")
        if isinstance(method, list) and method:
            method_fields["method"] = method
        else:
            authored = payload.get("experiment")
            if authored is None:
                authored = payload.get("steps")
            if authored is not None:
                if not (isinstance(authored, list) and all(isinstance(s, str) for s in authored)):
                    raise ValueError(
                        "test-protocol authoring JSON 'experiment'/'steps' must be a list of PyBaMM-style strings."
                    )
                method_fields["experiment"] = list(authored)
                cycles = payload.get("cycles")
                if isinstance(cycles, int):
                    method_fields["cycles"] = cycles

        return TestSpec(
            name=name,
            test_kind=kind,
            description=payload.get("description"),
            version=payload.get("version"),
            protocol=ProtocolInfo(url=payload.get("protocol_url")),
            record=dict(record_settings),
            safety=dict(safety),
            conditions=dict(conditions),
            artifacts=[dict(item) for item in artifacts],
            source=ProvenanceInfo(
                type=source_type if isinstance(source_type, str) else None,
                file=source_file if isinstance(source_file, str) else None,
                url=source_url if isinstance(source_url, str) else None,
                citation=citation if isinstance(citation, str) else None,
                retrieved_at=retrieved_at,
                workflow_version=workflow_version if isinstance(workflow_version, str) else None,
            ),
            comment=comment_list,
            **method_fields,
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
        coin_hardware: Any = None,  # DEPRECATED: pass ``housing`` instead (auto-migrated).
        housing: Any = None,
        source: ProvenanceInfo | None = None,
        specification_comment: str | list[str] | None = None,
        comment: str | list[str] | None = None,
    ) -> CellSpecification:
        specification = build_cell_description(
            id=_entity_iri(
                "cell-spec",
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
            housing=housing,
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

    def cell_spec(
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
        rechargeable: bool | None = None,
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
    ) -> CellSpecification:
        from battinfo.bundle import CellProductType
        resolved_pt = CellProductType(product_type) if product_type is not None else None
        cell_spec = CellSpecification(
            manufacturer=manufacturer,
            model=model,
            format=format,
            chemistry=chemistry,
            product_type=resolved_pt,
            size_code=size_code,
            iec_code=iec_code,
            country_of_origin=country_of_origin,
            rechargeable=rechargeable,
            year=year,
            positive_electrode_basis=positive_electrode_basis,
            negative_electrode_basis=negative_electrode_basis,
            datasheet_revision=datasheet_revision,
            properties=_mapping_value(specs),
            source=ProvenanceInfo(
                type=source_type,
                file=source_file,
                url=source_url,
                citation=citation,
                retrieved_at=retrieved_at,
            ),
            comment=list(comment or []),
        )
        self.cell_specs.append(cell_spec)
        return cell_spec

    def cell(
        self,
        cell_spec: CellSpecification,
        *,
        name: str | None = None,
        serial_number: str | None = None,
        batch_id: str | None = None,
        grade: str | None = None,
        manufactured_at: int | str | None = None,
        expires_at: int | str | None = None,
        measured: Any = None,
        conformance: Any = None,
        source_type: str = "measurement",
        source_url: str | None = None,
        citation: str | None = None,
        retrieved_at: int | str | None = None,
        comment: list[str] | None = None,
    ) -> CellInstance:
        from battinfo.bundle import Conformance as _Conformance
        if isinstance(conformance, dict):
            conformance = _Conformance.from_record(conformance)
        cell = CellInstance(
            cell_spec=cell_spec,
            name=name,
            serial_number=serial_number,
            batch_id=batch_id,
            conformance=conformance,
            grade=grade,
            manufactured_at=manufactured_at,
            expires_at=expires_at,
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

    def test_spec(
        self,
        *,
        name: str,
        type: str | None = None,
        kind: str | None = None,   # backward-compat alias for type
        description: str | None = None,
        experiment: list[str] | None = None,
        steps: list[str] | None = None,   # alias for experiment (PyBaMM strings)
        cycles: int | None = None,
        method: list[Any] | None = None,
        version: str | None = None,
        protocol_url: str | None = None,
        record: dict[str, Any] | None = None,
        safety: dict[str, Any] | None = None,
        conditions: Any = None,
        artifacts: list[Any] | None = None,
        source_type: str = "manual",
        source_url: str | None = None,
        source_file: str | None = None,
        citation: str | None = None,
        retrieved_at: int | str | None = None,
        workflow_version: str | None = None,
        comment: list[str] | None = None,
    ) -> TestSpec:
        kind = type or kind
        if not kind:
            raise ValueError("Workspace.test_spec() requires type=... (the test type).")
        fields: dict[str, Any] = {
            "name": name,
            "test_kind": kind,
            "description": description,
            "version": version,
            "protocol": ProtocolInfo(url=protocol_url),
            "record": dict(record or {}),
            "safety": dict(safety or {}),
            "conditions": _mapping_value(conditions),
            "artifacts": list(artifacts or []),
            "source": ProvenanceInfo(
                type=source_type,
                file=source_file,
                url=source_url,
                citation=citation,
                retrieved_at=retrieved_at,
                workflow_version=workflow_version,
            ),
            "comment": list(comment or []),
        }
        # PyBaMM-string authoring (default human interface) -> parsed into method;
        # a pre-built structured method takes precedence when supplied.
        if method:
            fields["method"] = list(method)
        else:
            authored = experiment if experiment is not None else steps
            if authored:
                fields["experiment"] = list(authored)
                if cycles is not None:
                    fields["cycles"] = cycles
        protocol = TestSpec(**fields)
        self.test_specs.append(protocol)
        return protocol

    def test(
        self,
        cell: CellInstance,
        *,
        type: str | None = None,
        kind: str | None = None,   # backward-compat alias for type
        protocol_ref: TestSpec | None = None,
        name: str | None = None,
        description: str | None = None,
        protocol: str | None = None,
        protocol_url: str | None = None,
        instrument: str | None = None,
        status: str | None = None,
        conformance: "TestConformance | dict[str, Any] | None" = None,
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
        from battinfo.bundle import TestConformance as _TestConformance
        if isinstance(conformance, dict):
            conformance = _TestConformance.from_record(conformance)
        protocol_name = protocol or (protocol_ref.name if protocol_ref is not None else None)
        protocol_link = protocol_url or (protocol_ref.protocol_url if protocol_ref is not None else None)
        resolved_kind = (type or kind) or (str(protocol_ref.test_kind) if protocol_ref is not None else None)
        if resolved_kind is None:
            raise ValueError("Workspace.test() requires type or protocol_ref.")
        test = Test(
            name=name,
            test_kind=resolved_kind,
            protocol_id=protocol_ref.id if protocol_ref is not None else None,
            protocol_entity=protocol_ref,
            cell=cell,
            description=description,
            status=status,
            conformance=conformance,
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
        type: str | None = None,
        kind: str | None = None,   # backward-compat alias for type
        path: PathLike | None = None,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        dataset_description: str | None = None,
        protocol: str | None = None,
        protocol_url: str | None = None,
        protocol_ref: "TestSpec | None" = None,
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
        source_path: PathLike | None = None,
        source_format: str | None = None,
        citation: str | None = None,
        retrieved_at: int | str | None = None,
        workflow_version: str | None = None,
        curated_by: str | None = None,
        comment: list[str] | None = None,
    ) -> Test:
        kind = type or kind
        if not kind:
            raise ValueError("Workspace.record_test() requires type=... (the test type).")
        protocol_name = protocol or kind.replace("_", " ")
        test_name = name or f"{cell.name or cell.serial_number or 'cell'} {protocol_name}"
        test = self.test(
            cell,
            kind=kind,
            name=test_name,
            description=description,
            protocol=protocol_name,
            protocol_url=protocol_url,
            protocol_ref=protocol_ref,
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
                source_path=source_path,
                source_format=source_format,
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
        temporal_coverage: str | None = None,
        source_type: str = "measurement",
        source_url: str | None = None,
        source_path: PathLike | None = None,
        source_format: str | None = None,
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

        # When an original pre-conversion source file is supplied, the dataset holds
        # two distributions of the same measurement: the normalised file (role
        # "processed") and the original instrument file (role "raw"), kept for
        # provenance. Both are uploaded and listed as dcat:distribution at publish.
        explicit_distributions: list[dict] = []
        source_path_obj = _as_path(source_path) if source_path is not None else None
        if source_path_obj is not None:
            processed_dist: dict = {"role": "processed"}
            content_url = download_url or resolved_access_url
            if content_url is not None:
                processed_dist["content_url"] = content_url
            # encoding_format is required by the schema — fall back to a generic type.
            processed_dist["encoding_format"] = resolved_format or "application/octet-stream"
            if dataset_path_obj is not None:
                processed_dist["name"] = dataset_path_obj.name
            if dataset_path_obj is not None and dataset_path_obj.exists() and dataset_path_obj.is_file():
                processed_dist["content_size"] = str(dataset_path_obj.stat().st_size)
            if resolved_checksum_value is not None:
                processed_dist["checksum"] = {
                    "algorithm": resolved_checksum_algorithm or "sha256",
                    "value": resolved_checksum_value,
                }
            # The raw file is the source the PROCESSED file was converted FROM — name the
            # processed file here, not the raw file itself.
            _processed_name = dataset_path_obj.name if dataset_path_obj is not None else "the processed dataset"
            raw_dist: dict = {
                "role": "raw",
                "content_url": source_path_obj.resolve().as_uri(),
                "name": source_path_obj.name,
                "description": f"Original instrument data file (pre-conversion source for {_processed_name}).",
            }
            raw_dist["encoding_format"] = (
                source_format or _guess_media_type(str(source_path_obj)) or "application/octet-stream"
            )
            if source_path_obj.exists() and source_path_obj.is_file():
                raw_dist["checksum"] = {"algorithm": "sha256", "value": _sha256(source_path_obj)}
                raw_dist["content_size"] = str(source_path_obj.stat().st_size)
            explicit_distributions = [processed_dist, raw_dist]

        dataset = Dataset(
            name=title,
            description=description,
            license=license,
            data_format=resolved_format,
            dataset_path=dataset_path,
            access_url=resolved_access_url,
            download_url=download_url,
            created_at=created_at,
            temporal_coverage=temporal_coverage,
            checksum=ChecksumInfo(algorithm=resolved_checksum_algorithm, value=resolved_checksum_value),
            cell=cell,
            test=test,
            distributions=explicit_distributions,
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

    def from_battdat(
        self,
        cell: CellInstance,
        path: PathLike,
        *,
        kind: str | None = None,
        name: str | None = None,
        instrument: str | None = None,
        license: str | None = None,
        access_url: str | None = None,
        source_type: str = "measurement",
        source_file: str | None = None,
        source_url: str | None = None,
        comment: list[str] | None = None,
    ) -> Test:
        """Create a Test (+ linked Dataset) from a BDF-normalised CSV file.

        Reads *path* with the ``batterydf`` library, infers the test kind from
        BDF column names, extracts start/end timestamps from the
        ``unix_time_second`` column, and delegates to
        :meth:`record_test`.  The Test and Dataset are appended to this
        workspace automatically.

        Parameters
        ----------
        cell:
            The physical cell instance the test was run on.
        path:
            Path to a BDF-normalised CSV file.
        kind:
            Test kind.  Inferred from column names when omitted.
        name:
            Human-readable test name.  Defaults to ``"<cell_name> <kind> test"``.
        instrument:
            Cycler instrument make/model.
        license:
            Dataset license URI.
        access_url:
            URL where the dataset is accessible.  Defaults to ``file://...`` URI.
        source_type:
            Provenance source type (default ``"measurement"``).
        source_file:
            Provenance source filename.  Defaults to the CSV file name.
        source_url:
            Provenance source URL.
        comment:
            Free-text comments attached to the test record.
        """
        from battinfo.interop.battdat import from_battdat as _from_battdat  # noqa: PLC0415

        cell_id_str = cell.id or f"urn:staging:{getattr(cell, 'serial_number', 'cell')}"
        result = _from_battdat(
            path,
            cell_id=cell_id_str,
            kind=kind,
            name=name,
            instrument=instrument,
            license=license,
            access_url=access_url,
            source_type=source_type,
            source_file=source_file,
            source_url=source_url,
        )
        resolved_kind = result.inferred_kind or kind or "other"
        test_inner = result.test_record.get("test", {})
        resolved_name = test_inner.get("name", name)
        resolved_source_file = source_file or Path(path).name

        # Use ws.test() directly so we can pass started_at / ended_at
        test = self.test(
            cell,
            kind=resolved_kind,
            name=resolved_name,
            instrument=instrument or test_inner.get("instrument_name"),
            status="completed",
            started_at=test_inner.get("started_at"),
            ended_at=test_inner.get("ended_at"),
            source_type=source_type,
            source_file=resolved_source_file,
            source_url=source_url,
            comment=list(comment or result.warnings or []),
        )
        self.dataset(
            cell,
            title=f"{resolved_name} data",
            test=test,
            path=path,
            access_url=access_url,
            license=license,
            source_type=source_type,
            source_url=source_url,
        )
        return test

    def from_bpx(
        self,
        path: PathLike,
        *,
        manufacturer: str,
        model: str | None = None,
        format: str = "unknown",
        chemistry: str | None = None,
        source_type: str = "simulation",
        source_file: str | None = None,
        comment: list[str] | None = None,
    ) -> CellSpecification:
        """Create a CellSpecification from a BPX battery parameter file.

        Reads *path* and maps the BPX ``Parameterisation.Cell`` parameters
        that have direct BattINFO spec equivalents (capacity, voltage limits,
        mass, dimensions) to a BattINFO CellSpecification.  Physics parameters are
        silently skipped.

        Parameters
        ----------
        path:
            Path to a BPX JSON file.
        manufacturer:
            Manufacturer name (required — BPX does not carry manufacturer info).
        model:
            Model identifier.  Falls back to ``Header.Title`` from the BPX file.
        format:
            Cell format (``"cylindrical"``, ``"pouch"``, etc.).
        chemistry:
            Chemistry string (e.g. ``"Li-ion"``).
        source_type:
            Provenance source type (default ``"simulation"``).
        source_file:
            Provenance source filename.  Defaults to the BPX file name.
        comment:
            Free-text comments.  BPX import warnings are appended automatically.
        """
        from battinfo.interop.bpx import from_bpx as _from_bpx  # noqa: PLC0415

        result = _from_bpx(path)
        resolved_model = model or result.title or Path(path).stem
        resolved_source_file = source_file or Path(path).name
        bpx_comments = list(comment or [])
        if result.warnings:
            bpx_comments.extend(result.warnings)
        if result.bpx_version is not None:
            bpx_comments.append(f"BPX version: {result.bpx_version}")
        if result.model_type is not None:
            bpx_comments.append(f"Physics model: {result.model_type}")

        cell_spec = self.cell_spec(
            manufacturer=manufacturer,
            model=resolved_model,
            format=format,
            chemistry=chemistry or "unknown",
            source_type=source_type,
            source_file=resolved_source_file,
            comment=bpx_comments if bpx_comments else None,
            specs=result.specs,
        )
        return cell_spec

    def publish(
        self,
        dataset: Dataset,
        *,
        test: Test | None = None,
        cell: CellInstance | None = None,
        cell_spec: CellSpecification | None = None,
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
            cell_spec=cell_spec,
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
        cell_spec: CellSpecification | None = None,
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

        resolved_test, resolved_cell, resolved_cell_spec = self._resolve_dataset_chain(
            dataset,
            test=test,
            cell=cell,
            cell_spec=cell_spec,
            action="build_publication_package",
        )
        staged_dataset = self._stage_publication_dataset(
            dataset,
            publication_root=_as_path(publication_root) if publication_root is not None else self.root / "publication",
        )
        return publish_bundle(
            cell_spec=resolved_cell_spec,
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
        cell_spec: CellSpecification | None = None,
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
            cell_spec=cell_spec,
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
        cell_spec: CellSpecification | None = None,
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

        resolved_test, resolved_cell, resolved_cell_spec = self._resolve_dataset_chain(
            dataset,
            test=test,
            cell=cell,
            cell_spec=cell_spec,
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
            resolved_cell_spec,
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
        cell_spec: CellSpecification | None = None,
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
            cell_spec=cell_spec,
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
        cell_spec: CellSpecification | None = None,
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
            cell_spec=cell_spec,
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
            "cell_specs": [item.to_record() for item in finalized["cell_specs"]],
            "cell_instances": [item.to_record() for item in finalized["cells"]],
            "test_specs": [item.to_record() for item in finalized["test_specs"]],
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
            "cell_specs": [
                save_cell_spec(
                    item,
                    source_root=target_root,
                    mode=mode,
                    resolve_references=resolve_references,
                    validation_policy=validation_policy,
                )
                for item in finalized["cell_specs"]
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
            "test_specs": [
                save_test_spec(
                    item,
                    source_root=target_root,
                    mode=mode,
                    resolve_references=resolve_references,
                    validation_policy=validation_policy,
                )
                for item in finalized["test_specs"]
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
                save_library_cell_spec(
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
            results["rdf"] = build_cell_spec_library_rdf(
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

    def query_cell_specs(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("cell_specs_dir", self.source_root / "cell-spec")
        return query_cell_specs(**filters)

    def query(self, type: str, /, **filters: Any) -> list[dict[str, Any]]:
        normalized = type.strip().lower().replace("-", "_")
        if normalized in {"cell_spec", "cell_specs", "cell_spec", "cell_specs"}:
            filters.setdefault("cell_specs_dir", self.source_root / "cell-spec")
            return query_api(type, **filters)
        if normalized in {"cell", "cells", "cell_instance", "cell_instances"}:
            filters.setdefault("directory", self.source_root / "cell-instance")
            return query_api(type, **filters)
        if normalized in {"test_spec", "test_specs", "test_protocol", "test_protocols"}:
            filters.setdefault("directory", self.source_root / "test-protocol")
            return query_api(type, **filters)
        if normalized in {"test", "tests"}:
            filters.setdefault("directory", self.source_root / "test")
            return query_api(type, **filters)
        if normalized in {"dataset", "datasets"}:
            filters.setdefault("directory", self.source_root / "dataset")
            return query_api(type, **filters)
        if normalized in {"description", "descriptions", "library_cell_spec", "library_cell_specs"}:
            filters.setdefault("directory", self.library_root)
            return query_api(type, **filters)
        return query_api(type, **filters)

    def query_cells(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.source_root / "cell-instance")
        return query_cell_instances(**filters)

    def query_tests(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.source_root / "test")
        return query_tests(**filters)

    def query_test_specs(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.source_root / "test-protocol")
        return query_test_specs(**filters)

    def query_datasets(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.source_root / "dataset")
        return query_datasets(**filters)

    def query_descriptions(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.library_root)
        return query_library_cell_specs(**filters)

    # backward compat aliases
    test_protocol = test_spec
    load_test_protocol = load_test_spec
    load_test_protocols = load_test_specs
    query_test_protocols = query_test_specs

    def _finalize(self) -> dict[str, list[Any]]:
        finalized_cell_specs = [self._finalize_cell_spec(item) for item in self.cell_specs]
        cell_spec_map = {id(original): finalized for original, finalized in zip(self.cell_specs, finalized_cell_specs, strict=True)}
        # Break cell-spec IRI collisions before cells link to them: distinct specs that
        # share identity fields must not overwrite each other on save, and each cell must
        # link to its own spec (cell_spec_map holds the same objects, so in-place
        # re-minting propagates into _finalize_cell's cell_spec_id lookup below).
        _disambiguate_entity_ids(finalized_cell_specs, "cell-spec")

        finalized_cells = [self._finalize_cell(item, cell_spec_map) for item in self.cells]
        cell_map = {id(original): finalized for original, finalized in zip(self.cells, finalized_cells, strict=True)}
        # Break IRI collisions before datasets link to these ids (cell_map holds
        # the same objects, so in-place re-minting propagates to dataset linking).
        _disambiguate_entity_ids(finalized_cells, "cell")

        finalized_test_specs = [self._finalize_test_spec(item) for item in self.test_specs]
        test_spec_map = {
            id(original): finalized for original, finalized in zip(self.test_specs, finalized_test_specs, strict=True)
        }
        # Break test-spec IRI collisions before tests link to them via conformsTo.
        _disambiguate_entity_ids(finalized_test_specs, "test-protocol")

        finalized_tests = [self._finalize_test(item, cell_map, test_spec_map) for item in self.tests]
        test_map = {id(original): finalized for original, finalized in zip(self.tests, finalized_tests, strict=True)}
        _disambiguate_entity_ids(finalized_tests, "test")

        finalized_datasets = [self._finalize_dataset(item, cell_map, test_map) for item in self.datasets]
        _disambiguate_entity_ids(finalized_datasets, "dataset")

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

        for original, finalized in zip(self.cell_specs, finalized_cell_specs, strict=True):
            _sync_model_state(original, finalized)
        for original, finalized in zip(self.cells, finalized_cells, strict=True):
            _sync_model_state(original, finalized)
        for original, finalized in zip(self.test_specs, finalized_test_specs, strict=True):
            _sync_model_state(original, finalized)
        for original, finalized in zip(self.tests, finalized_tests, strict=True):
            _sync_model_state(original, finalized)
        for original, finalized in zip(self.datasets, finalized_datasets, strict=True):
            _sync_model_state(original, finalized)

        return {
            "cell_specs": self.cell_specs,
            "cells": self.cells,
            "test_specs": self.test_specs,
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

    def _resolve_dataset_cell_spec(self, dataset: Dataset, cell: CellInstance) -> CellSpecification | None:
        if cell.cell_spec is not None:
            return cell.cell_spec
        if dataset.cell_instance_id is not None:
            for candidate in self.cells:
                if candidate.id == dataset.cell_instance_id and candidate.cell_spec is not None:
                    return candidate.cell_spec
        if len(self.cell_specs) == 1:
            return self.cell_specs[0]
        return None

    def _resolve_dataset_chain(
        self,
        dataset: Dataset,
        *,
        test: Test | None = None,
        cell: CellInstance | None = None,
        cell_spec: CellSpecification | None = None,
        action: str,
    ) -> tuple[Test, CellInstance, CellSpecification]:
        resolved_test = test or dataset.test or self._resolve_dataset_test(dataset)
        if resolved_test is None:
            raise ValueError(f"Workspace.{action}() requires a Test or a Dataset linked to a Test.")

        resolved_cell = cell or dataset.cell or resolved_test.cell or self._resolve_dataset_cell(dataset)
        if resolved_cell is None:
            raise ValueError(f"Workspace.{action}() requires a Cell or a Dataset/Test linked to a Cell.")

        resolved_cell_spec = cell_spec or resolved_cell.cell_spec or self._resolve_dataset_cell_spec(dataset, resolved_cell)
        if resolved_cell_spec is None:
            raise ValueError(f"Workspace.{action}() requires a CellSpecification or a linked Cell with cell_spec set.")

        return resolved_test, resolved_cell, resolved_cell_spec

    def _finalize_description(self, specification: CellSpecification) -> CellSpecification:
        finalized = specification.model_copy(deep=True)
        if finalized.source.type is None:
            finalized.source.type = "manual"
        if finalized.source.retrieved_at is None:
            finalized.source.retrieved_at = _now_unix()
        return finalized

    def _finalize_cell_spec(self, cell_spec: CellSpecification) -> CellSpecification:
        finalized = cell_spec.model_copy(deep=True)
        if finalized.id is None:
            finalized.id = _entity_iri(
                "cell-spec",
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

    def _finalize_cell(self, cell: CellInstance, cell_spec_map: dict[int, CellSpecification]) -> CellInstance:
        finalized = cell.model_copy(deep=True, update={"cell_spec": None})
        linked_type = cell_spec_map.get(id(cell.cell_spec)) if cell.cell_spec is not None else None
        if finalized.cell_spec_id is None and linked_type is not None:
            finalized.cell_spec_id = linked_type.id
        # Fall back to a referenced spec's IRI (e.g. one loaded from the registry and
        # not part of this session's authored specs).
        if finalized.cell_spec_id is None and cell.cell_spec is not None and getattr(cell.cell_spec, "id", None):
            finalized.cell_spec_id = cell.cell_spec.id
        if finalized.name is None:
            finalized.name = finalized.serial_number or finalized.batch_id or "cell"
        if finalized.id is None:
            finalized.id = _entity_iri(
                "cell",
                "::".join(
                    [
                        _with_default(finalized.cell_spec_id, "unknown-cell-spec"),
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

    def _finalize_test_spec(self, protocol: TestSpec) -> TestSpec:
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
        test_spec_map: dict[int, TestSpec],
    ) -> Test:
        finalized = test.model_copy(deep=True, update={"cell": None, "protocol_entity": None})
        linked_cell = cell_map.get(id(test.cell)) if test.cell is not None else None
        linked_protocol = test_spec_map.get(id(test.protocol_entity)) if test.protocol_entity is not None else None
        if finalized.cell_instance_id is None and linked_cell is not None:
            finalized.cell_instance_id = linked_cell.id
        # Fall back to an externally-linked cell's IRI — e.g. an instance registered
        # earlier (at manufacture) and linked via ws.link_cells(), which is not part
        # of this session's saved cells.
        if finalized.cell_instance_id is None and test.cell is not None and getattr(test.cell, "id", None):
            finalized.cell_instance_id = test.cell.id
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
        # Fall back to an externally-linked cell's IRI (see _finalize_test).
        if finalized.cell_instance_id is None and dataset.cell is not None and getattr(dataset.cell, "id", None):
            finalized.cell_instance_id = dataset.cell.id
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
