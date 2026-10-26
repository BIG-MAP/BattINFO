from __future__ import annotations

import json
import mimetypes
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from battinfo.local_workspace import LocalWorkspace

from battinfo._fs_guard import is_empty_or_missing, remove_tree, write_marker
from battinfo._jsonio import read_record_json as _load_json
from battinfo._util import (
    LOCATION_FIELDS,
    _as_path,
    _now_unix,
    _sha256,
    file_uri_to_path,
    is_file_uri,
    is_local_location,
    workspace_layout_root,
)
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
from battinfo.api._records import (
    _record_from_cell_instance,
    _record_from_cell_spec,
    _record_from_dataset,
    _record_from_test,
    _record_from_test_protocol,
)
from battinfo.api._shared import _to_unix_time
from battinfo.authoring import cell_description as build_cell_description
from battinfo.bundle import (
    Cell,
    CellSpec,
    ChecksumInfo,
    Dataset,
    ProtocolInfo,
    ProvenanceInfo,
    Test,
    TestConformance,
    TestSpec,
)
from battinfo.entities import (
    ENTITY_BY_TYPE,
    cell_instance_identity_seed,
    cell_spec_identity_seed,
    cell_spec_seed_fields,
    cell_spec_uid,
    dataset_locator_seed,
    given_test_name,
    iri_namespace_map,
    kind_for_doc,
    legacy_cell_spec_identity_seed,
    legacy_stable_uid,
    legacy_test_identity_seed,
    save_entity_path,
    saved_record_body,
    saved_record_document,
    seed_iri,
    seed_text,
    stable_uid,
    test_identity_seed,
)
from battinfo.namespace import DEFAULT_RECORD_BASE, base_prefix, record_iri, same_record
from battinfo.publication import DEFAULT_PUBLISH_FILENAME
from battinfo.publication import publish as publish_bundle
from battinfo.validate.record import validate_record_report

PathLike = str | Path
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
    """Build a BattINFO quantity dict without hand-writing nested value/unit payloads.

    The keys are the quantity schema's: ``value``, ``typical_value``,
    ``min_value``, ``max_value``, ``value_text`` and ``unit``. Only the
    arguments given are written.

    Examples
    --------
    ::

        quantity(3.6, "V")                          # {"value": 3.6, "unit": "V"}
        quantity(min_value=2.5, max_value=4.2, unit="V")
        # {"min_value": 2.5, "max_value": 4.2, "unit": "V"}
        quantity(typical=2.5, unit="Ah")            # {"typical_value": 2.5, "unit": "Ah"}
        quantity(text="5-8 at 1 kHz", unit="mΩ")    # {"value_text": "5-8 at 1 kHz", "unit": "mΩ"}
    """
    payload: dict[str, Any] = {}
    if value is not None:
        payload["value"] = value
    if typical is not None:
        payload["typical_value"] = typical
    if min_value is not None:
        payload["min_value"] = min_value
    if max_value is not None:
        payload["max_value"] = max_value
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


def _stable_uid(seed: str) -> str:
    return stable_uid(seed)


# Derived from the entity registry (registered record types), plus extra
# namespaces for things that are not yet first-class record types.
_IRI_NAMESPACE: dict[str, str] = {
    **iri_namespace_map(),
    "organization": "organization",
    "electrode": "electrode",
}


def _entity_iri(entity_type: str, seed: str, *, prefix: str | None = None) -> str:
    """The IRI *seed* mints, in the old form unless a publisher *prefix* is given (``namespace.record_iri``)."""
    namespace = _IRI_NAMESPACE.get(entity_type, entity_type)
    return record_iri(namespace, _stable_uid(seed), prefix)


def _legacy_entity_iri(entity_type: str, seed: str) -> str:
    """The IRI the minting of before 0.8.0 gave *seed*, which had no NFC step (``entities.legacy_stable_uid``).

    Only for finding a record saved under it; nothing new is minted with it.
    Every record of before 0.8.0 has the old form, and a lookup finds a saved
    record in either form, so this one gives the old form.
    """
    namespace = _IRI_NAMESPACE.get(entity_type, entity_type)
    return record_iri(namespace, legacy_stable_uid(seed))


def _iri_uid(iri: str) -> str:
    """The uid that ends *iri*."""
    return iri.rstrip("/").rsplit("/", 1)[-1]


def _with_default(value: str | None, fallback: str) -> str:
    text = (value or "").strip()
    return text or fallback


def _seed_text_or(value: Any, fallback: str) -> str:
    """A free-text identity field as it enters a seed (``entities.seed_text``), else *fallback*."""
    return seed_text(value) or fallback


def _cell_spec_fields(manufacturer: Any, model: Any, format: Any, chemistry: Any, size_code: Any) -> dict[str, Any]:
    return {
        "manufacturer": manufacturer,
        "model": model,
        "format": format,
        "chemistry": chemistry,
        "size_code": size_code,
    }


def _cell_spec_iri(uid: str, *, prefix: str | None = None) -> str:
    return record_iri(_IRI_NAMESPACE["cell-spec"], uid, prefix)


# Fields that vary across runs and must NOT influence a content-derived
# disambiguation seed or an upsert's change check, wherever they sit: otherwise a
# re-minted IRI would be unstable across re-runs (e.g. a finalize-time
# ``retrieved_at`` timestamp). The record's own ``id`` is left out as well, but
# only at the record's top level (_RECORD_ID_KEY): a nested ``id``, such as a
# dataset link or a manufacturer's organisation IRI, is content, so an edit to it
# is a change and two records that differ only there are two records.
_VOLATILE_SEED_KEYS = frozenset({"uid", "retrieved_at", "created_at", "modified_at", "generated_at", "imported_at"})
_RECORD_ID_KEY = "id"


def _without_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _without_volatile(v) for k, v in value.items() if k not in _VOLATILE_SEED_KEYS}
    if isinstance(value, list):
        return [_without_volatile(v) for v in value]
    return value


def _strip_volatile(value: Any) -> Any:
    """*value*, a record document, without what never marks a change.

    That is the volatile fields (:data:`_VOLATILE_SEED_KEYS`) wherever they sit,
    and the record's own ``id``: the one in its body (the object under its
    kind's record key, such as ``cell_instance``), or at the top of *value*
    when it has no record key. Every other ``id`` stays and is compared.
    """
    stripped = _without_volatile(value)
    if isinstance(stripped, dict):
        kind = kind_for_doc(stripped)
        body = stripped.get(kind.record_key) if kind is not None else stripped
        if isinstance(body, dict):
            body.pop(_RECORD_ID_KEY, None)
    return stripped


# Fields that can name a local file. In a content seed a local value enters as its
# location-independent locator (dataset_locator_seed), never as the absolute path,
# so a re-minted IRI does not change when the workspace folder moves.
_LOCATION_SEED_KEYS = frozenset({*LOCATION_FIELDS, "dataset_path", "path", "url", "file"})


def _seed_view(value: Any, workspace_root: Path | None, *, top: bool = True, every_id: bool = False) -> Any:
    """*value*, a record, without its own ``id`` and the volatile fields, each local file location as its locator.

    The record's own ``id`` is the one at its top level; a nested ``id`` stays
    (see :data:`_VOLATILE_SEED_KEYS`). With *every_id*, every ``id`` is left
    out, as the content seed of before 0.8.0 did (:func:`_legacy_content_seed`).
    Every record IRI that stays enters in the old form (``entities.seed_iri``),
    so the seed does not depend on the base the records it names were minted under.
    """
    if isinstance(value, dict):
        view: dict[str, Any] = {}
        for key, item in value.items():
            if key in _VOLATILE_SEED_KEYS or (key == _RECORD_ID_KEY and (top or every_id)):
                continue
            if key in _LOCATION_SEED_KEYS and isinstance(item, str) and is_local_location(item):
                item = dataset_locator_seed(dataset_path=item, workspace_root=workspace_root)
            view[key] = _seed_view(item, workspace_root, top=False, every_id=every_id)
        return view
    if isinstance(value, list):
        return [_seed_view(item, workspace_root, top=False, every_id=every_id) for item in value]
    if isinstance(value, str):
        return seed_iri(value)
    return value


# Links a finalize pass derives from other records (the datasets that name a cell
# or a test), not content of the record itself.
_DERIVED_BACK_LINKS = ("dataset_ids",)
# The same back-links where a record document carries them beside its body (a
# cell's ``datasets`` list, written from its dataset_ids).
_DERIVED_DOCUMENT_LINKS = ("datasets",)


def _content_seed(entity: Any, *, workspace_root: Path | None = None) -> str:
    """A stable, order-independent seed from an entity's distinguishing content
    (its canonical record minus its own IRI and the volatile timestamps, with
    local file locations as their workspace-relative locators).

    A derived back-link (``dataset_ids``, which each finalize pass sets from the
    datasets that name the record) enters empty, as it is before any pass, so a
    content seed never depends on an earlier pass.
    """
    data = entity.model_dump(mode="json", exclude_none=True)
    for key in _DERIVED_BACK_LINKS:
        if key in data:
            data[key] = []
    return json.dumps(_seed_view(data, workspace_root), sort_keys=True, ensure_ascii=False)


def _link_key(linked: Any, iri: str | None) -> str | None:
    """How a session view names the record a link leads to.

    By the linked object's IRI, or by the object itself while it has none
    (two objects without an IRI are two records until a save tells them
    apart), else by the IRI the link already holds.
    """
    if linked is not None:
        return getattr(linked, "id", None) or f"session-object:{id(linked)}"
    return iri


def _repeat_key(entity: Any) -> tuple[Any, ...]:
    """A few fields two objects share whenever their session views are equal (a cheap first check)."""
    if isinstance(entity, CellSpec):
        return (entity.manufacturer, entity.model)
    if isinstance(entity, TestSpec):
        return (entity.name, str(entity.test_type))
    if isinstance(entity, Test):
        return (
            str(entity.test_type),
            _link_key(entity.cell, entity.cell_instance_id),
            entity.instrument,
            entity.started_at,
        )
    if isinstance(entity, Cell):
        return (entity.serial_number, entity.batch_id)
    return ()


def _given_test_name(test: Any, linked_cell: Any = None) -> str | None:
    """The name the caller gave *test*, or ``None`` when it has none or the workspace generated it.

    A generated title restates the test's cell and protocol (``C01 cycling``);
    see ``entities.given_test_name``. *linked_cell* is the finalized cell the
    test links to, whose name the workspace defaults to its serial number.
    """
    labels = [
        getattr(cell, field, None)
        for cell in (linked_cell, getattr(test, "cell", None))
        if cell is not None
        for field in ("name", "serial_number", "batch_id")
    ]
    protocol = getattr(test, "protocol", None)
    return given_test_name(
        test.name,
        kind=getattr(test, "test_kind", None),
        protocol_name=getattr(protocol, "name", None) if protocol is not None else None,
        cell_labels=labels,
    )


def _same_cell_spec_identity(body: Mapping[str, Any], spec: Any) -> bool:
    """Whether *body*, a saved cell-spec record, has the natural key of *spec* (``entities.cell_spec_identity_seed``)."""
    fields = _cell_spec_fields(spec.manufacturer, spec.model, spec.format, spec.chemistry, spec.size_code)
    return cell_spec_identity_seed(**cell_spec_seed_fields(body)) == cell_spec_identity_seed(**fields)


def _run_differences(saved: Mapping[str, Any], test: Any) -> list[str]:
    """How *saved*, a test record body, and *test* describe two runs: another instrument, start or end time.

    A field only one of them gives is not a difference; filling it in is an update.
    """
    pairs = (
        ("instrument", saved.get("instrument_name"), getattr(test, "instrument", None)),
        ("started at", _to_unix_time(saved.get("started_at")), _to_unix_time(getattr(test, "started_at", None))),
        ("ended at", _to_unix_time(saved.get("ended_at")), _to_unix_time(getattr(test, "ended_at", None))),
    )
    return [
        f"{label} {old!r} saved, {new!r} now"
        for label, old, new in pairs
        if old not in (None, "") and new not in (None, "") and old != new
    ]


def _entity_label(entity: Any) -> str:
    """A short name for *entity* in a message: its name, serial number or model, quoted."""
    for field in ("name", "serial_number", "model"):
        value = getattr(entity, field, None)
        if isinstance(value, str) and value.strip():
            return repr(value.strip())
    return "an unnamed record"


def _disambiguate_entity_ids(
    entities: Sequence[Any],
    entity_type: str,
    *,
    workspace_root: Path | None = None,
    assigned: Sequence[bool] | None = None,
    prefix: str | None = None,
) -> None:
    """Make the IRIs of *entities* unique without moving one that was assigned before this pass.

    Deterministic IRIs are seeded from a record's identity fields, so two
    distinct records whose identity fields match (two cell specs for one
    manufacturer and model with different capacities, two unnamed cycling
    tests on one cell) mint the *same* IRI, and on save the second would
    overwrite the first. *assigned* says, for each entity, whether its IRI is
    fixed: it had it before this finalize pass (pinned by the caller, imported,
    or minted by an earlier pass, a save earlier in the session), or it is the
    record a previous session saved under it (``Workspace._hold_saved_iris``).
    Within a group of entities that share an IRI:

    - an assigned IRI is never re-minted: published identities and the links
      other records already hold to them stay where they are;
    - two or more assigned members raise ``ValueError``, since one IRI names
      one record;
    - every member minted in this pass is re-minted from a hash of its content
      (``{iri}::{content}``), which does not depend on sibling order; a member
      whose content is identical to another's falls back to a stable ordinal
      suffix (``::dupN``) so it still persists.

    An entity whose IRI no other entity shares keeps it, so the common case
    keeps its identity-seeded, idempotent IRI. *assigned* defaults to "none
    assigned before this pass". The content seed names a local data file by its
    locator relative to *workspace_root* (see ``entities.dataset_locator_seed``),
    not its absolute path, and leaves derived back-links out (``_content_seed``).
    A re-minted IRI takes the publisher *prefix* of the pass (``None`` for the
    old form), and its seed takes the shared IRI in the old form
    (``entities.seed_iri``), so the uid is the same under every base.
    """
    flags = list(assigned) if assigned is not None else [False] * len(entities)
    if len(flags) != len(entities):
        raise ValueError("assigned must say, for each entity, whether it had its IRI before the pass.")
    # Records are grouped by their IRI in the old form (entities.seed_iri): the
    # two forms of one segment and uid name one record, and one record file.
    by_key: dict[str, list[int]] = {}
    for index, entity in enumerate(entities):
        current = getattr(entity, "id", None)
        if current is not None:
            by_key.setdefault(seed_iri(current), []).append(index)

    for members in by_key.values():
        held = [entities[index] for index in members if flags[index]]
        if len(held) > 1:
            labels = ", ".join(_entity_label(entity) for entity in held)
            kind = entity_type.replace("-", " ")
            raise ValueError(
                f"{len(held)} {kind} records in this session have the IRI {held[0].id}: {labels}. One IRI names "
                "one record, and an IRI a record already has (pinned, imported or saved earlier) is never "
                "re-minted. Give each record its own IRI, or remove the duplicate."
            )

    # Assigned IRIs are fixed first, so a member minted in this pass never takes one.
    seen: set[str] = {
        seed_iri(entity.id) for index, entity in enumerate(entities) if flags[index] and entity.id is not None
    }
    for index, entity in enumerate(entities):
        current = getattr(entity, "id", None)
        if current is None or flags[index]:
            continue
        if len(by_key[seed_iri(current)]) > 1:
            # Shares its IRI with another record: re-seed from content (order-independent).
            content = _content_seed(entity, workspace_root=workspace_root)
            current = _entity_iri(entity_type, f"{seed_iri(current)}::{content}", prefix=prefix)
        if seed_iri(current) in seen:
            # Genuine full-content duplicate: keep both with a stable ordinal suffix.
            ordinal = 1
            candidate = _entity_iri(entity_type, f"{seed_iri(current)}::dup{ordinal}", prefix=prefix)
            while seed_iri(candidate) in seen:
                ordinal += 1
                candidate = _entity_iri(entity_type, f"{seed_iri(current)}::dup{ordinal}", prefix=prefix)
            current = candidate
        entity.id = current
        seen.add(seed_iri(current))


def _legacy_content_seed(entity: Any, *, workspace_root: Path | None = None) -> str:
    """The content seed of before 0.8.0, which left out every ``id``, nested ones too.

    Only for finding a record saved under an IRI minted from it
    (:func:`_legacy_disambiguated_ids`).
    """
    data = entity.model_dump(mode="json", exclude_none=True)
    return json.dumps(_seed_view(data, workspace_root, every_id=True), sort_keys=True, ensure_ascii=False)


def _legacy_disambiguated_ids(
    ids: Sequence[str | None],
    entities: Sequence[Any],
    entity_type: str,
    *,
    workspace_root: Path | None = None,
) -> list[str | None]:
    """The IRIs the finalize pass of before 0.8.0 ended with, given the *ids* it started from.

    That pass re-minted every member of a group of *entities* sharing an IRI
    from its content (:func:`_legacy_content_seed`), and gave a member whose
    content repeated another's an ordinal suffix, hashing without the NFC
    step. Only for finding records saved under those IRIs; nothing new is
    minted with them.
    """
    counts: dict[str, int] = {}
    for current in ids:
        if current is not None:
            counts[current] = counts.get(current, 0) + 1
    seen: set[str] = set()
    result: list[str | None] = []
    for current, entity in zip(ids, entities, strict=True):
        if current is None:
            result.append(None)
            continue
        if counts[current] > 1:
            content = _legacy_content_seed(entity, workspace_root=workspace_root)
            current = _legacy_entity_iri(entity_type, f"{seed_iri(current)}::{content}")
        if current in seen:
            ordinal = 1
            candidate = _legacy_entity_iri(entity_type, f"{seed_iri(current)}::dup{ordinal}")
            while candidate in seen:
                ordinal += 1
                candidate = _legacy_entity_iri(entity_type, f"{seed_iri(current)}::dup{ordinal}")
            current = candidate
        seen.add(current)
        result.append(current)
    return result


def _legacy_candidates(started: Sequence[str | None], ended: Sequence[str | None]) -> list[tuple[str, ...]]:
    """For each record, the IRIs a finalize pass of before 0.8.0 can have given it, most specific first.

    *started* holds the IRIs that pass started from and *ended* the ones it
    ended with (:func:`_legacy_disambiguated_ids`). A record that shared its
    seed with a sibling in this session gets the re-minted IRI first, then the
    plain one, which it had if it was saved before the sibling was added. A
    record that shares its seed with no other gets its one IRI.
    """
    return [tuple(dict.fromkeys(iri for iri in (end, start) if iri)) for start, end in zip(started, ended, strict=True)]


def _path_from_file_uri(uri: str) -> Path | None:
    """The path a ``file:`` URI names (see :func:`battinfo._util.file_uri_to_path`), or ``None``."""
    return file_uri_to_path(uri) if is_file_uri(uri) else None


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
        inputs: Sequence[PathLike | None] = (),
        generated: bool = False,
        base: str = DEFAULT_RECORD_BASE,
    ) -> None:
        """Open or create the workspace at ``root``.

        ``clean=True`` deletes ``root`` first and builds it again. The delete is
        refused (``UnsafeDeleteError``) for a folder BattINFO did not create,
        for the home or working folder, and for a folder that is, holds or lies
        inside one of ``inputs``: the files and folders the caller's operation
        reads. ``generated=True`` says ``root`` is BattINFO output, so a root
        this call creates gets the marker that lets a later ``clean=True``
        delete it.

        ``base`` is the base the records this session mints take
        (``namespace.base_prefix``), given by the caller: ``battinfo.workspace()``
        passes the one its folder recorded when it was created. A record
        already saved under the records folder keeps the IRI it has, in
        either form (:meth:`_hold_saved_iris`).
        """
        self.record_base = base
        self._record_prefix = base_prefix(base)
        self.root = _as_path(root)
        creates_root = is_empty_or_missing(self.root)
        if clean:
            remove_tree(self.root, inputs=inputs)
            creates_root = True
        self.source_root = self.root / source_dir_name
        # The folder a data file's path is taken relative to when it seeds a
        # dataset IRI: the project folder of a battinfo.workspace(), else this root.
        self.data_root = workspace_layout_root(self.source_root) or self.root
        self.index_path = self.root / index_name
        self.library_root = self.root / "library" / "cell-spec"
        self.package_root = self.root / "package" / "cell-spec"
        self.library_rdf_root = self.root / "library-rdf" / "cell-spec"
        self.library_aggregate_jsonld = self.root / "ontology" / "library" / "cell-spec.jsonld"
        self.library_manifest_json = self.root / "library-rdf" / "cell-spec.index.json"
        self.root.mkdir(parents=True, exist_ok=True)
        if generated and creates_root:
            write_marker(self.root)
        self.name = name
        self.title = title
        self.description = description
        self.tenant = tenant
        self.publisher = publisher
        self.version = version
        self.comment = list(comment or [])

        self.descriptions: list[CellSpec] = []
        self.cell_specs: list[CellSpec] = []
        self.cells: list[Cell] = []
        self.test_specs: list[TestSpec] = []
        self.tests: list[Test] = []
        self.datasets: list[Dataset] = []
        # dataset_locator_seed resolves paths on disk; a dataset's locator depends only
        # on its location fields and data_root, so it is computed once per location.
        self._locators: dict[tuple[Any, ...], str] = {}

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
        target: CellSpec | Cell | Test | Dataset | None = None,
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
            # The authoring model and the datasheet model are now one CellSpec
            # (a BatteryCellSpecification); add() routes it to the canonical cell-spec
            # collection. The datasheet-library workflow uses the dedicated
            # add_description/save_descriptions methods.
            if isinstance(obj, CellSpec):
                _append_unique(self.cell_specs, obj)
            elif isinstance(obj, TestSpec):
                _append_unique(self.test_specs, obj)
            elif isinstance(obj, Cell):
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
                    "Workspace.add() supports CellSpec, CellSpec, TestSpec, Cell/Cell, Test, and Dataset objects."
                )

        for obj in objects:
            _add(obj)
        return self

    def load_cell_spec(
        self,
        source: CellSpec | dict[str, Any] | PathLike,
        *,
        validate: bool = True,
        validation_policy: str = "strict",
    ) -> CellSpec:
        """Load one cell-spec JSON source into the workspace.

        The source can be either a canonical BattINFO `cell-spec` record with a
        top-level `product` object or a simpler authoring draft with fields like
        `manufacturer`, `model`, `format`, `chemistry`, and optional `specs`.
        Draft inputs are canonized later when the workspace renders or saves.
        """

        if isinstance(source, CellSpec):
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
                cell_spec = CellSpec.from_record(payload)
            else:
                cell_spec = self._cell_spec_from_authoring_payload(payload)

        _append_unique(self.cell_specs, cell_spec)
        return cell_spec

    def load_cell_specs(
        self,
        *sources: CellSpec | dict[str, Any] | PathLike,
        directory: PathLike | None = None,
        glob: str = "*.json",
        validate: bool = True,
        validation_policy: str = "strict",
    ) -> list[CellSpec]:
        """Load multiple cell-spec JSON sources into the workspace."""

        inputs: list[CellSpec | dict[str, Any] | PathLike] = list(sources)
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
            if (
                isinstance(payload.get("TestSpec"), dict)
                and "test_spec" not in payload
                and "test_protocol" not in payload
            ):
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

    def _cell_spec_from_authoring_payload(self, payload: dict[str, Any]) -> CellSpec:
        model = payload.get("model")
        if model is None:
            model = payload.get("model_name")
        manufacturer = payload.get("manufacturer")
        format_value = payload.get("format")
        chemistry = payload.get("chemistry")
        if not all(
            isinstance(value, str) and value.strip() for value in (manufacturer, model, format_value, chemistry)
        ):
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

        return CellSpec(
            name=name if isinstance(name, str) and name.strip() else None,
            manufacturer=manufacturer,
            model=model,
            format=format_value,
            chemistry=chemistry,
            size_code=payload.get("size_code"),
            iec_code=iec_code if isinstance(iec_code, str) else None,
            country_of_origin=country_of_origin if isinstance(country_of_origin, str) else None,
            year=year
            if isinstance(year, int)
            else int(year)
            if isinstance(year, str) and year.strip().isdigit()
            else None,
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
        working_electrode: Any = None,
        counter_electrode: Any = None,
        cell_configuration: str | None = None,
        electrolyte: Any = None,
        separator: Any = None,
        coin_hardware: Any = None,  # DEPRECATED: pass ``housing`` instead (auto-migrated).
        housing: Any = None,
        source: ProvenanceInfo | None = None,
        specification_comment: str | list[str] | None = None,
        comment: str | list[str] | None = None,
    ) -> CellSpec:
        from battinfo.api._records import _library_cell_spec_iri  # noqa: PLC0415

        fields = _cell_spec_fields(manufacturer, model, format, chemistry, size_code)
        # The library holds one file per manufacturer and model; a spec it holds
        # under the IRI the seeds of before 0.8.0 gave it, or under the other
        # form of its IRI, keeps that IRI.
        specification_id = _library_cell_spec_iri(fields, self.library_root, base=self.record_base) or _cell_spec_iri(
            cell_spec_uid(fields), prefix=self._record_prefix
        )
        specification = build_cell_description(
            id=specification_id,
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
            working_electrode=working_electrode,
            counter_electrode=counter_electrode,
            cell_configuration=cell_configuration,
            electrolyte=electrolyte,
            separator=separator,
            coin_hardware=coin_hardware,
            housing=housing,
            source=source,
            specification_comment=specification_comment,
            comment=comment,
        )
        if specification.source.type is None:
            specification.source.type = "manual"  # schema-required; documented category default
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
        properties: Any = None,
        specs: Any = None,  # quiet alias for properties=
        size_code: str | None = None,
        iec_code: str | None = None,
        country_of_origin: str | None = None,
        cell_configuration: str | None = None,
        reference_electrode: str | None = None,
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
    ) -> CellSpec:
        from battinfo.bundle import CellConfiguration, CellProductType

        resolved_pt = CellProductType(product_type) if product_type is not None else None
        resolved_cfg = CellConfiguration(cell_configuration) if cell_configuration is not None else None
        cell_spec = CellSpec(
            manufacturer=manufacturer,
            model=model,
            format=format,
            chemistry=chemistry,
            product_type=resolved_pt,
            size_code=size_code,
            iec_code=iec_code,
            country_of_origin=country_of_origin,
            cell_configuration=resolved_cfg,
            reference_electrode=reference_electrode,
            rechargeable=rechargeable,
            year=year,
            positive_electrode_basis=positive_electrode_basis,
            negative_electrode_basis=negative_electrode_basis,
            datasheet_revision=datasheet_revision,
            properties=_mapping_value(properties if properties is not None else specs),
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
        cell_spec: CellSpec,
        *,
        name: str | None = None,
        serial_number: str | None = None,
        batch_id: str | None = None,
        working_electrode_id: str | None = None,
        counter_electrode_id: str | None = None,
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
    ) -> Cell:
        from battinfo.bundle import Conformance as _Conformance

        if isinstance(conformance, dict):
            conformance = _Conformance.from_record(conformance)
        cell = Cell(
            cell_spec=cell_spec,
            name=name,
            serial_number=serial_number,
            batch_id=batch_id,
            working_electrode_id=working_electrode_id,
            counter_electrode_id=counter_electrode_id,
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
        kind: str | None = None,  # backward-compat alias for type
        description: str | None = None,
        experiment: list[str] | None = None,
        steps: list[str] | None = None,  # alias for experiment (PyBaMM strings)
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
        cell: Cell,
        *,
        type: str | None = None,
        kind: str | None = None,  # backward-compat alias for type
        protocol_ref: TestSpec | None = None,
        name: str | None = None,
        description: str | None = None,
        protocol: str | None = None,
        protocol_url: str | None = None,
        instrument: str | None = None,
        status: str | None = None,
        conditions: dict[str, Any] | None = None,
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
            conditions=dict(conditions or {}),
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
        cell: Cell,
        *,
        type: str | None = None,
        kind: str | None = None,  # backward-compat alias for type
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
        cell: Cell,
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
        resolved_format = (
            format
            or _guess_media_type(download_url)
            or _guess_media_type(resolved_access_url)
            or _guess_media_type(dataset_path)
        )
        resolved_checksum_algorithm = checksum_algorithm
        resolved_checksum_value = checksum_value
        if (
            dataset_path_obj is not None
            and dataset_path_obj.exists()
            and dataset_path_obj.is_file()
            and resolved_checksum_value is None
        ):
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
        cell: Cell,
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
    ) -> CellSpec:
        """Create a CellSpec from a BPX battery parameter file.

        Reads *path* and maps the BPX ``Parameterisation.Cell`` parameters
        that have direct BattINFO spec equivalents (capacity, voltage limits,
        mass, dimensions) to a BattINFO CellSpec.  Physics parameters are
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
        cell: Cell | None = None,
        cell_spec: CellSpec | None = None,
        cell_specification: CellSpec | dict[str, Any] | PathLike | None = None,
        datasheet_path: PathLike | None = None,
        publication_root: PathLike | None = None,
        publish_filename: str = DEFAULT_PUBLISH_FILENAME,
        html_filename: str = "index.html",
        dataset_glob: str = "**/*",
        emit_bundle_dir: bool = False,
        emit_html_page: bool = False,
        validation_policy: str = "strict",
        registry_url: str | None = None,
        allow_unchecked_iris: bool = False,
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
            registry_url=registry_url,
            allow_unchecked_iris=allow_unchecked_iris,
        )

    def build_publication_package(
        self,
        dataset: Dataset,
        *,
        test: Test | None = None,
        cell: Cell | None = None,
        cell_spec: CellSpec | None = None,
        cell_specification: CellSpec | dict[str, Any] | PathLike | None = None,
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
        registry_url: str | None = None,
        allow_unchecked_iris: bool = False,
    ) -> dict[str, Any]:
        """Preferred name for locally building a publication package from `Workspace`.

        Given a registry (*registry_url*, else ``BATTINFO_REGISTRY_URL``), a
        record it already holds in the old form keeps that IRI in the package
        (see :func:`battinfo.publication.publish`).
        """

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
            base=self.record_base,
            registry_url=registry_url,
            allow_unchecked_iris=allow_unchecked_iris,
        )

    def export_release(
        self,
        dataset: Dataset,
        *,
        registry: Any,
        root: PathLike | None = None,
        test: Test | None = None,
        cell: Cell | None = None,
        cell_spec: CellSpec | None = None,
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
        cell: Cell | None = None,
        cell_spec: CellSpec | None = None,
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
        """Export one linked dataset chain to a disk-backed submission workspace.

        ``root`` defaults to ``<workspace>/release``. A ``root`` that is not
        empty is refused unless ``force=True``, which deletes it first. That
        delete is refused for a folder BattINFO did not create, and for one
        that holds the dataset's file or this workspace's records.
        """

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
                # The release is built from the dataset's file and this workspace's records.
                remove_tree(release_root, inputs=(self._dataset_local_path(dataset), self.source_root))
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
        cell: Cell | None = None,
        cell_spec: CellSpec | None = None,
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
        cell: Cell | None = None,
        cell_spec: CellSpec | None = None,
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
        stamp: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        target_root = _as_path(source_root) if source_root is not None else self.source_root
        finalized = self._finalize(record_roots=[target_root], refuse_replaced_runs=True)

        from battinfo._record_index import bulk_save_session  # noqa: PLC0415 — avoid import cycle

        with bulk_save_session(target_root):
            results = self._save_finalized(
                finalized,
                target_root=target_root,
                mode=mode,
                resolve_references=resolve_references,
                validation_policy=validation_policy,
                stamp=stamp,
            )

        if build_index:
            results["index"] = build_index_api(
                source_root=target_root,
                out_path=self.index_path,
                validate=True,
                validation_policy=validation_policy,
            )
        return results

    def _save_finalized(
        self,
        finalized: dict[str, Any],
        *,
        target_root: Path,
        mode: str,
        resolve_references: bool,
        validation_policy: str,
        stamp: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return {
            "cell_specs": [
                save_cell_spec(
                    item,
                    source_root=target_root,
                    mode=mode,
                    resolve_references=resolve_references,
                    validation_policy=validation_policy,
                    stamp=stamp,
                    base=self.record_base,
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
                    stamp=stamp,
                    base=self.record_base,
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
                    stamp=stamp,
                    base=self.record_base,
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
                    stamp=stamp,
                    base=self.record_base,
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
                    stamp=stamp,
                    base=self.record_base,
                )
                for item in finalized["datasets"]
            ],
        }

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
        target_output_jsonld_dir = (
            _as_path(output_jsonld_dir) if output_jsonld_dir is not None else self.library_rdf_root
        )
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

    def _query_location(self, filters: dict[str, Any], *, dir_param: str = "directory") -> dict[str, Any]:
        """Default a query to this workspace's records root unless the caller
        already targeted a location (source_root= or a deprecated dir alias)."""
        if dir_param not in filters and "source_root" not in filters:
            filters["source_root"] = self.source_root
        return filters

    def query_cell_specs(self, **filters: Any) -> list[dict[str, Any]]:
        return query_cell_specs(**self._query_location(filters, dir_param="cell_specs_dir"))

    def query(self, type: str, /, **filters: Any) -> list[dict[str, Any]]:
        normalized = type.strip().lower().replace("-", "_")
        if normalized in {"cell_spec", "cell_specs"}:
            return query_api(type, **self._query_location(filters, dir_param="cell_specs_dir"))
        if normalized in {
            "cell",
            "cells",
            "cell_instance",
            "cell_instances",
            "test_spec",
            "test_specs",
            "test_protocol",
            "test_protocols",
            "test",
            "tests",
            "dataset",
            "datasets",
        }:
            return query_api(type, **self._query_location(filters))
        if normalized in {"description", "descriptions", "library_cell_spec", "library_cell_specs"}:
            filters.setdefault("directory", self.library_root)
            return query_api(type, **filters)
        return query_api(type, **filters)

    def query_cells(self, **filters: Any) -> list[dict[str, Any]]:
        return query_cell_instances(**self._query_location(filters))

    def query_tests(self, **filters: Any) -> list[dict[str, Any]]:
        return query_tests(**self._query_location(filters))

    def query_test_specs(self, **filters: Any) -> list[dict[str, Any]]:
        return query_test_specs(**self._query_location(filters))

    def query_datasets(self, **filters: Any) -> list[dict[str, Any]]:
        return query_datasets(**self._query_location(filters))

    def query_descriptions(self, **filters: Any) -> list[dict[str, Any]]:
        filters.setdefault("directory", self.library_root)
        return query_library_cell_specs(**filters)

    # backward compat aliases
    test_protocol = test_spec
    load_test_protocol = load_test_spec
    load_test_protocols = load_test_specs
    query_test_protocols = query_test_specs

    def _session_view(self, entity: Any, *, without: Sequence[str] = ()) -> str:
        """*entity* as the next save would write it, to tell a repeated record from a new one.

        The record a finalize pass makes of *entity*, without its own IRI, its
        timestamps, its derived back-links (``dataset_ids``) and the fields in
        *without*. A link to another record names that record by its IRI or,
        while it has none, by the object (:func:`_link_key`), so two links are
        equal only when they lead to one record. Two objects with one view would
        save as one record. Nothing in the session changes.
        """
        cells = {id(cell): cell for cell in self.cells}
        links: dict[str, str | None] = {}
        finalized: Any
        if isinstance(entity, CellSpec):
            finalized = self._finalize_cell_spec(entity)
        elif isinstance(entity, Cell):
            finalized = self._finalize_cell(entity, {id(spec): spec for spec in self.cell_specs})
            links["cell_spec_id"] = _link_key(entity.cell_spec, entity.cell_spec_id)
        elif isinstance(entity, TestSpec):
            finalized = self._finalize_test_spec(entity)
        elif isinstance(entity, Test):
            finalized = self._finalize_test(entity, cells, {id(spec): spec for spec in self.test_specs})
            links["cell_instance_id"] = _link_key(entity.cell, entity.cell_instance_id)
            links["protocol_id"] = _link_key(entity.protocol_entity, entity.protocol_id)
        elif isinstance(entity, Dataset):
            finalized = self._finalize_dataset(entity, cells, {id(test): test for test in self.tests})
            links["cell_instance_id"] = _link_key(entity.cell, entity.cell_instance_id)
            links["test_id"] = _link_key(entity.test, entity.test_id)
        else:
            raise TypeError(f"No session view for {type(entity).__name__}.")
        data = finalized.model_dump(mode="json", exclude_none=True)
        data.update({key: value for key, value in links.items() if value is not None})
        for key in ("id", "dataset_ids", *without):
            data.pop(key, None)
        return json.dumps(_seed_view(data, self.data_root), sort_keys=True, ensure_ascii=False)

    def _repeats_in(self, entity: Any, pool: Sequence[Any]) -> list[Any]:
        """The objects of *pool* that *entity* repeats, in order: the same view, and its IRI if it has one.

        *entity* is never a repeat of itself. Used when a load or add runs a
        second time, so the session keeps the object it already holds.
        """
        pinned = getattr(entity, "id", None)
        candidates = [
            other
            for other in pool
            if other is not entity
            and type(other) is type(entity)
            and (pinned is None or getattr(other, "id", None) == pinned)
            and _repeat_key(other) == _repeat_key(entity)
        ]
        if not candidates:
            return []
        view = self._session_view(entity)
        return [other for other in candidates if self._session_view(other) == view]

    def _finalize(
        self, *, record_roots: Sequence[Path] | None = None, refuse_replaced_runs: bool = False
    ) -> dict[str, list[Any]]:
        """Mint and link every record of the session, in place.

        *record_roots* are the records folders a save writes to (by default
        :attr:`source_root`). With *refuse_replaced_runs* (a save), a test that
        nothing tells apart from a saved test that records another run raises
        ``ValueError`` instead (:meth:`_refuse_replacing_saved_runs`); the
        session is left as it was.

        A record keeps an IRI it had before the pass, whether the caller pinned
        it, an import set it or an earlier pass minted it. So does a record
        saved under *record_roots* by an earlier session: one whose seeded IRI
        names the saved record a save of it would write, and a cell spec or
        test saved under the IRI the seeds of before 0.8.0 gave it
        (:meth:`_hold_saved_iris`). A record minted in this pass whose IRI
        collides with another's is re-minted from its content, and two records
        that both had one IRI before the pass raise ``ValueError`` (see
        :func:`_disambiguate_entity_ids`). Whether a record keeps its IRI does
        not depend on whether a save ran between adding it and adding the
        record that collides with it.
        """
        finalized = self._finalized_records(record_roots=record_roots, refuse_replaced_runs=refuse_replaced_runs)
        for key in ("cell_specs", "cells", "test_specs", "tests", "datasets"):
            for original, item in zip(getattr(self, key), finalized[key], strict=True):
                _sync_model_state(original, item)
        return {
            "cell_specs": self.cell_specs,
            "cells": self.cells,
            "test_specs": self.test_specs,
            "tests": self.tests,
            "datasets": self.datasets,
        }

    def _finalized_records(
        self, *, record_roots: Sequence[Path] | None = None, refuse_replaced_runs: bool = False
    ) -> dict[str, list[Any]]:
        """The records :meth:`_finalize` makes of the session, as copies: the session is not changed.

        Each list holds the finalized copy of the session's record at the same
        position (``cell_specs``, ``cells``, ``test_specs``, ``tests`` and
        ``datasets``), with the IRI a save under *record_roots* would write it
        under.
        """
        roots = [self.source_root] if record_roots is None else list(record_roots)
        # IRIs held before this pass (pinned, imported, or minted by an earlier
        # pass) are never re-minted when a sibling collides with them.
        assigned_cell_specs = [item.id is not None for item in self.cell_specs]
        assigned_cells = [item.id is not None for item in self.cells]
        assigned_test_specs = [item.id is not None for item in self.test_specs]
        assigned_tests = [item.id is not None for item in self.tests]
        assigned_datasets = [item.id is not None for item in self.datasets]
        finalized_cell_specs = [self._finalize_cell_spec(item) for item in self.cell_specs]
        cell_spec_map = {
            id(original): finalized for original, finalized in zip(self.cell_specs, finalized_cell_specs, strict=True)
        }
        # Break cell-spec IRI collisions before cells link to them: distinct specs that
        # share identity fields must not overwrite each other on save, and each cell must
        # link to its own spec (cell_spec_map holds the same objects, so in-place
        # re-minting propagates into _finalize_cell's cell_spec_id lookup below). A spec
        # saved earlier keeps its IRI, one saved before 0.8.0 changed the seed included.
        held_cell_specs = self._hold_saved_iris(
            finalized_cell_specs,
            "cell-spec",
            assigned=assigned_cell_specs,
            record_roots=roots,
            legacy_ids=self._legacy_cell_spec_ids(finalized_cell_specs, assigned_cell_specs),
            is_legacy_record=lambda index, body: _same_cell_spec_identity(body, finalized_cell_specs[index]),
        )
        _disambiguate_entity_ids(
            finalized_cell_specs,
            "cell-spec",
            workspace_root=self.data_root,
            assigned=held_cell_specs,
            prefix=self._record_prefix,
        )

        finalized_cells = [self._finalize_cell(item, cell_spec_map) for item in self.cells]
        cell_map = {id(original): finalized for original, finalized in zip(self.cells, finalized_cells, strict=True)}
        # Break IRI collisions before datasets link to these ids (cell_map holds
        # the same objects, so in-place re-minting propagates to dataset linking).
        held_cells = self._hold_saved_iris(finalized_cells, "cell", assigned=assigned_cells, record_roots=roots)
        _disambiguate_entity_ids(
            finalized_cells, "cell", workspace_root=self.data_root, assigned=held_cells, prefix=self._record_prefix
        )

        finalized_test_specs = [self._finalize_test_spec(item) for item in self.test_specs]
        test_spec_map = {
            id(original): finalized for original, finalized in zip(self.test_specs, finalized_test_specs, strict=True)
        }
        # Break test-spec IRI collisions before tests link to them via conformsTo.
        held_test_specs = self._hold_saved_iris(
            finalized_test_specs, "test-protocol", assigned=assigned_test_specs, record_roots=roots
        )
        _disambiguate_entity_ids(
            finalized_test_specs,
            "test-protocol",
            workspace_root=self.data_root,
            assigned=held_test_specs,
            prefix=self._record_prefix,
        )

        finalized_tests = [self._finalize_test(item, cell_map, test_spec_map) for item in self.tests]
        test_map = {id(original): finalized for original, finalized in zip(self.tests, finalized_tests, strict=True)}
        # The test seed changed in 0.8.0; a test saved under its earlier IRI keeps it.
        held_tests = self._hold_saved_iris(
            finalized_tests,
            "test",
            assigned=assigned_tests,
            record_roots=roots,
            legacy_ids=self._legacy_test_ids(finalized_tests, assigned_tests),
            is_legacy_record=lambda index, body: self._is_saved_run(
                body, self.tests[index], finalized_tests[index], cell_map
            ),
        )
        _disambiguate_entity_ids(
            finalized_tests, "test", workspace_root=self.data_root, assigned=held_tests, prefix=self._record_prefix
        )
        if refuse_replaced_runs:
            self._refuse_replacing_saved_runs(
                finalized_tests, assigned=assigned_tests, record_roots=roots, cell_map=cell_map
            )

        finalized_datasets = [self._finalize_dataset(item, cell_map, test_map) for item in self.datasets]
        held_datasets = self._hold_saved_iris(
            finalized_datasets, "dataset", assigned=assigned_datasets, record_roots=roots
        )
        _disambiguate_entity_ids(
            finalized_datasets,
            "dataset",
            workspace_root=self.data_root,
            assigned=held_datasets,
            prefix=self._record_prefix,
        )

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

        return {
            "cell_specs": finalized_cell_specs,
            "cells": finalized_cells,
            "test_specs": finalized_test_specs,
            "tests": finalized_tests,
            "datasets": finalized_datasets,
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

    def _resolve_dataset_cell(self, dataset: Dataset) -> Cell | None:
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

    def _resolve_dataset_cell_spec(self, dataset: Dataset, cell: Cell) -> CellSpec | None:
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
        cell: Cell | None = None,
        cell_spec: CellSpec | None = None,
        action: str,
    ) -> tuple[Test, Cell, CellSpec]:
        resolved_test = test or dataset.test or self._resolve_dataset_test(dataset)
        if resolved_test is None:
            raise ValueError(f"Workspace.{action}() requires a Test or a Dataset linked to a Test.")

        resolved_cell = cell or dataset.cell or resolved_test.cell or self._resolve_dataset_cell(dataset)
        if resolved_cell is None:
            raise ValueError(f"Workspace.{action}() requires a Cell or a Dataset/Test linked to a Cell.")

        resolved_cell_spec = (
            cell_spec or resolved_cell.cell_spec or self._resolve_dataset_cell_spec(dataset, resolved_cell)
        )
        if resolved_cell_spec is None:
            raise ValueError(f"Workspace.{action}() requires a CellSpec or a linked Cell with cell_spec set.")

        return resolved_test, resolved_cell, resolved_cell_spec

    def _finalize_description(self, specification: CellSpec) -> CellSpec:
        # source_type is schema-required, so an unprovided one takes the documented category
        # default; source_file is optional and stays absent unless the author provided it — a
        # fabricated placeholder ("manual.json") would masquerade as real provenance (applies
        # to all _finalize_* below; retrieved_at genuinely IS "now" at ingest time).
        finalized = specification.model_copy(deep=True)
        if finalized.source.type is None:
            finalized.source.type = "manual"
        if finalized.source.retrieved_at is None:
            finalized.source.retrieved_at = _now_unix()
        return finalized

    def _finalize_cell_spec(self, cell_spec: CellSpec, *, record_roots: Sequence[Path] = ()) -> CellSpec:
        """A finalized copy of *cell_spec*, its IRI minted from its natural key when it has none.

        A spec saved under *record_roots* (the records folder the save writes
        to) with the IRI the seeds of before 0.8.0 gave it keeps that IRI.
        """
        finalized = cell_spec.model_copy(deep=True)
        if finalized.id is None:
            fields = _cell_spec_fields(
                finalized.manufacturer, finalized.model, finalized.format, finalized.chemistry, finalized.size_code
            )
            finalized.id = _cell_spec_iri(cell_spec_uid(fields, roots=record_roots), prefix=self._record_prefix)
        if finalized.name is None:
            finalized.name = f"{finalized.manufacturer} {finalized.model}"
        if finalized.source.type is None:
            finalized.source.type = "datasheet"
        if finalized.source.retrieved_at is None:
            finalized.source.retrieved_at = _now_unix()
        return finalized

    def _finalize_cell(self, cell: Cell, cell_spec_map: dict[int, CellSpec]) -> Cell:
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
            # Shared cell-instance identity policy (entities.py): the same
            # (spec IRI, serial/name) mints the same IRI here and on the
            # low-level save_cell_instance/create_cell_instance surfaces.
            seed = cell_instance_identity_seed(
                cell_spec_id=finalized.cell_spec_id,
                serial_number=finalized.serial_number,
                batch_id=finalized.batch_id,
                name=finalized.name,
            )
            # name is defaulted above, so the seed is essentially always
            # available; the fallback keeps the pre-refactor anonymous seed
            # (colliding siblings are re-minted by _disambiguate_entity_ids).
            if seed is None:
                seed = "::".join([seed_iri(_with_default(finalized.cell_spec_id, "unknown-cell-spec")), "", "", "cell"])
            finalized.id = _entity_iri("cell", seed, prefix=self._record_prefix)
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
                        _seed_text_or(finalized.name, "test-protocol"),
                        seed_text(finalized.version),
                    ]
                ),
                prefix=self._record_prefix,
            )
        if finalized.source.type is None:
            finalized.source.type = "manual"
        if finalized.source.retrieved_at is None:
            finalized.source.retrieved_at = _now_unix()
        return finalized

    def _finalize_test(
        self,
        test: Test,
        cell_map: dict[int, Cell],
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
        given_name = _given_test_name(test, linked_cell)
        if finalized.name is None:
            finalized.name = f"{linked_cell.name} {protocol_name}" if linked_cell is not None else protocol_name
        if finalized.id is None:
            # One run on one cell (entities.test_identity_seed): the cell, the kind, the
            # protocol's IRI (else its name) and the run: the first data file's location,
            # else the start time given, else the name given. A title the workspace
            # generated (C01 cycling) never enters.
            finalized.id = _entity_iri(
                "test",
                test_identity_seed(
                    cell_id=finalized.cell_instance_id,
                    kind=finalized.test_kind,
                    protocol_id=finalized.protocol_id,
                    protocol_name=finalized.protocol.name,
                    data_locator=self._test_data_locator(test),
                    started_at=finalized.started_at,
                    name=given_name,
                ),
                prefix=self._record_prefix,
            )
        if finalized.source.type is None:
            finalized.source.type = "measurement"
        if finalized.source.retrieved_at is None:
            finalized.source.retrieved_at = _now_unix()
        return finalized

    def _test_data_locator(self, test: Test) -> str:
        """The locator of *test*'s first data file (``entities.dataset_locator_seed``), or ``""``.

        The first dataset of the session made from *test* that names a data
        file, in the order the datasets were added.
        """
        for dataset in self.datasets:
            if dataset.test is not test:
                continue
            locator = self._dataset_locator(dataset)
            if locator:
                return locator
        return ""

    def _dataset_locator(self, dataset: Dataset) -> str:
        """The locator of *dataset*'s data (``entities.dataset_locator_seed``), ``""`` when it names none.

        Computed once for each location: it depends only on the dataset's
        location fields and the data root.
        """
        cache: dict[tuple[Any, ...], str] = self.__dict__.setdefault("_locators", {})
        key = (dataset.access_url, dataset.download_url, dataset.dataset_path, self.data_root)
        locator = cache.get(key)
        if locator is None:
            locator = dataset_locator_seed(
                access_url=dataset.access_url,
                download_url=dataset.download_url,
                dataset_path=dataset.dataset_path,
                workspace_root=self.data_root,
            )
            cache[key] = locator
        return locator

    def _hold_saved_iris(
        self,
        finalized: Sequence[Any],
        entity_type: str,
        *,
        assigned: Sequence[bool],
        record_roots: Sequence[Path],
        legacy_ids: Sequence[Sequence[str]] | None = None,
        is_legacy_record: Callable[[int, Mapping[str, Any]], bool] | None = None,
    ) -> list[bool]:
        """Which of *finalized* keep their IRI when the pass breaks collisions: *assigned*, and the records already saved.

        *finalized* are the records of one kind as this pass minted them, in
        session order, and *assigned* says which had their IRI before it. A
        records folder a save writes to (*record_roots*) can hold a record a
        previous session saved, which this session mints again. When two
        records minted in this pass share an IRI and a record is saved under
        it, the one whose save would write that record again (:meth:`_is_saved_record`)
        keeps it, and only the others are re-minted from their content; so a
        record keeps its IRI whether or not a save ran before the record that
        collides with it was added. A record alone on an IRI that is saved
        already has its own record and keeps it. A record is saved under its
        IRI in either form, the old form or ``/id/1001/`` (``namespace.same_record``),
        and keeps the form it is saved in whichever form this pass minted.

        A record saved under a seed of before 0.8.0 keeps that IRI too.
        *legacy_ids* holds, for each record, the IRIs the rule of before 0.8.0
        can have given it, most specific first: the IRI that rule re-minted it
        to when a sibling of the session shared its seed, then its plain seeded
        IRI. A record takes the first of them that is saved, that no record of
        the session has, and whose saved record *is_legacy_record* says is this
        one. Several records can claim one saved IRI: the plain IRI of a record
        saved on its own before a sibling with the same seed was added. Then
        only the record whose save would write the saved record again takes it
        (the first, when several would); when none would, none takes it.
        """
        held = list(assigned)
        roots = [Path(root) for root in record_roots]
        if not roots:
            return held
        record_key = ENTITY_BY_TYPE[entity_type].record_key
        # Records are grouped by their IRI in the old form (entities.seed_iri):
        # the two forms of one segment and uid are one record, saved in one file.
        groups: dict[str, list[int]] = {}
        for index, item in enumerate(finalized):
            if item.id is not None:
                groups.setdefault(seed_iri(item.id), []).append(index)
        own_record: set[int] = set()  # alone on an IRI saved under the roots: the record is its own
        for members in groups.values():
            if any(held[index] for index in members):
                continue
            iri = finalized[members[0]].id  # every member was minted in this pass, in one form
            uid = _iri_uid(iri)
            if not any(save_entity_path(entity_type, uid, root).is_file() for root in roots):
                continue
            doc = saved_record_document(entity_type, uid, roots)
            saved_iri = doc[record_key].get("id") if doc is not None else None
            if not same_record(saved_iri, iri):
                doc = None
            elif saved_iri != iri:
                # Saved under the other form of this IRI: the record keeps the IRI it is saved under.
                for index in members:
                    finalized[index].id = saved_iri
            if len(members) == 1:
                own_record.add(members[0])
                continue
            match = next(
                (index for index in members if doc is not None and self._is_saved_record(finalized[index], doc)),
                None,
            )
            if match is not None:
                held[match] = True
        if legacy_ids is None or is_legacy_record is None:
            return held
        # Compared in the old form, as the legacy IRIs are, so a record that has
        # the other form of one is seen to take it.
        taken = {seed_iri(item.id) for item in finalized if item.id is not None}
        pending = [
            index
            for index, item in enumerate(finalized)
            if not held[index] and index not in own_record and item.id is not None
        ]
        depth = max((len(legacy_ids[index]) for index in pending), default=0)
        for position in range(depth):
            claims: dict[str, list[int]] = {}
            for index in pending:
                candidates = legacy_ids[index]
                if held[index] or position >= len(candidates) or seed_iri(candidates[position]) in taken:
                    continue
                claims.setdefault(candidates[position], []).append(index)
            for legacy, claimants in claims.items():
                doc = saved_record_document(entity_type, _iri_uid(legacy), roots)
                if doc is None:
                    continue
                matches = [index for index in claimants if is_legacy_record(index, doc[record_key])]
                if len(matches) > 1:
                    matches = [
                        index
                        for index in matches
                        if self._is_saved_record(finalized[index].model_copy(update={"id": legacy}), doc)
                    ][:1]
                if len(matches) != 1:
                    continue
                saved_iri = doc[record_key]["id"]  # the legacy IRI, in the form it is saved under
                finalized[matches[0]].id = saved_iri
                held[matches[0]] = True
                taken.add(seed_iri(saved_iri))
        return held

    def _is_saved_record(self, item: Any, saved: Mapping[str, Any]) -> bool:
        """Whether *saved*, a record document saved under *item*'s IRI, is the record a save of *item* writes.

        The whole documents are compared, the sections beside the body (such
        as a cell spec's ``properties``) included. Left out are the record's
        own IRI, the volatile timestamps, the schema and BattINFO versions that
        wrote it, the derived back-links (``dataset_ids``, a cell's
        ``datasets``) and, for a dataset that has none of its own, the
        publication time and licence a save fills in.
        """
        builders: dict[type, Callable[[Any], dict[str, Any]]] = {
            CellSpec: _record_from_cell_spec,
            Cell: _record_from_cell_instance,
            TestSpec: _record_from_test_protocol,
            Test: _record_from_test,
            Dataset: _record_from_dataset,
        }
        builder = builders.get(type(item))
        if builder is None:
            return False
        try:
            doc = builder(item)
        except (ValueError, TypeError):
            return False
        kind = kind_for_doc(doc)
        if kind is None:
            return False
        skip = {_RECORD_ID_KEY, *_DERIVED_BACK_LINKS}
        if isinstance(item, Dataset):
            if item.published_at is None:
                skip.add("published_at")
            if not item.license:
                skip.add("license")

        def view(document: Mapping[str, Any]) -> dict[str, Any] | None:
            data = _without_volatile(dict(document))
            body = data.get(kind.record_key)
            if not isinstance(body, dict):
                return None
            data[kind.record_key] = {key: entry for key, entry in body.items() if key not in skip}
            for key in ("schema_version", *_DERIVED_DOCUMENT_LINKS):
                data.pop(key, None)
            provenance = data.get("provenance")
            if isinstance(provenance, dict):
                provenance.pop("battinfo_version", None)
            return data

        mine = view(doc)
        return mine is not None and mine == view(saved)

    def _legacy_cell_spec_ids(self, finalized: Sequence[CellSpec], assigned: Sequence[bool]) -> list[tuple[str, ...]]:
        """The IRIs the finalize pass of before 0.8.0 can have given each cell spec of *finalized*.

        The re-mint from content that kept specs sharing a seed apart then
        (:func:`_legacy_disambiguated_ids`), then the plain natural-key IRI of
        before 0.8.0 (``entities.legacy_cell_spec_identity_seed``, hashed
        without NFC), which a spec saved on its own has. A spec in *assigned*
        starts from the IRI it has, in the old form as every IRI of before
        0.8.0 is. Only for finding specs saved under those
        IRIs (:meth:`_hold_saved_iris`).
        """
        started = [
            seed_iri(spec.id)
            if held and spec.id is not None
            else _legacy_entity_iri(
                "cell-spec",
                legacy_cell_spec_identity_seed(
                    **_cell_spec_fields(spec.manufacturer, spec.model, spec.format, spec.chemistry, spec.size_code)
                ),
            )
            for spec, held in zip(finalized, assigned, strict=True)
        ]
        ended = _legacy_disambiguated_ids(started, finalized, "cell-spec", workspace_root=self.data_root)
        return _legacy_candidates(started, ended)

    def _legacy_test_ids(self, finalized: Sequence[Test], assigned: Sequence[bool]) -> list[tuple[str, ...]]:
        """The IRIs the finalize pass of before 0.8.0 can have given each test of *finalized*.

        The re-mint from content that kept tests sharing a seed apart then
        (:func:`_legacy_disambiguated_ids`), then the plain IRI of its seed of
        before 0.8.0 (``entities.legacy_test_identity_seed``), which a test
        saved without such a sibling has. A test in *assigned* starts from the
        IRI it has, in the old form as every IRI of before 0.8.0 is. Only for
        finding tests saved under those IRIs
        (:meth:`_hold_saved_iris`).
        """
        started = [
            seed_iri(test.id)
            if held and test.id is not None
            else _legacy_entity_iri(
                "test",
                legacy_test_identity_seed(
                    cell_id=test.cell_instance_id,
                    kind=test.test_kind,
                    protocol_name=test.protocol.name,
                    name=test.name,
                ),
            )
            for test, held in zip(finalized, assigned, strict=True)
        ]
        ended = _legacy_disambiguated_ids(started, finalized, "test", workspace_root=self.data_root)
        return _legacy_candidates(started, ended)

    def _refuse_replacing_saved_runs(
        self,
        finalized_tests: Sequence[Test],
        *,
        assigned: Sequence[bool],
        record_roots: Sequence[Path],
        cell_map: dict[int, Cell],
    ) -> None:
        """Raise ``ValueError`` when a save would let a test replace a saved test that records another run.

        A test with no data file, no start time and no name of its own has
        nothing that tells its run apart (``entities.test_identity_seed``), so
        it is one run per cell, kind and protocol. When a records folder the
        save writes to (*record_roots*) holds a test under its IRI with another
        instrument, start or end time, the save would overwrite that run's
        record. Only tests minted in this pass are checked: one whose IRI was
        pinned, imported or saved earlier in the session updates its record.
        Nothing in the session has changed when this raises.
        """
        roots = [Path(root) for root in record_roots]
        if not roots:
            return
        clashes: list[str] = []
        for original, test, held in zip(self.tests, finalized_tests, assigned, strict=True):
            if held or test.id is None or test.started_at is not None:
                continue
            body = saved_record_body("test", _iri_uid(test.id), roots)
            if body is None or self._test_data_locator(original):
                continue
            linked_cell = cell_map.get(id(original.cell)) if original.cell is not None else None
            if _given_test_name(original, linked_cell) is not None:
                continue
            differences = _run_differences(body, test)
            if differences:
                clashes.append(f"  {test.id} ({test.name}): {'; '.join(differences)}")
        if clashes:
            listing = "\n".join(clashes)
            raise ValueError(
                "This save would replace a saved test with another run of the same kind on the same cell:\n"
                f"{listing}\n"
                "Nothing tells the two runs apart: the new one has no data file, no start time and no name. "
                "To add it as a run of its own, give it a name (name=...), its start time (started_at=...) "
                "or its data file (data=...). To update the saved test instead, pin its IRI (iri=...). "
                "No cell, test or dataset record was written."
            )

    def _is_saved_run(
        self,
        body: Mapping[str, Any],
        original: Test,
        finalized: Test,
        cell_map: dict[int, Cell],
    ) -> bool:
        """Whether *body*, a saved test, records the run *finalized* (made from *original*) describes.

        It has the same cell, kind and protocol, and the same data files: the
        datasets the session made from this run, minted with the saved test's
        IRI as their test, are the ones the saved test lists. A test without
        data files must have the same start time as the saved one.
        """
        if body.get("cell_id") != finalized.cell_instance_id or str(body.get("kind") or "") != str(finalized.test_kind):
            return False
        if (body.get("protocol_id") or None) != (finalized.protocol_id or None):
            return False
        listed = sorted(str(item) for item in body.get("dataset_ids") or [])
        datasets = [dataset for dataset in self.datasets if dataset.test is original]
        if not datasets:
            return not listed and _to_unix_time(body.get("started_at")) == _to_unix_time(finalized.started_at)
        probe = finalized.model_copy(update={"id": body.get("id")})
        made = sorted(str(self._finalize_dataset(dataset, cell_map, {id(original): probe}).id) for dataset in datasets)
        return made == listed

    def _finalize_dataset(
        self,
        dataset: Dataset,
        cell_map: dict[int, Cell],
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
            if finalized.published_at is not None:
                # A dataset already published was created by then, not at this save,
                # and this save modifies it: without its own modified_at it takes the
                # save time, not the old publication time.
                finalized.created_at = finalized.published_at
                if finalized.modified_at is None:
                    finalized.modified_at = _now_unix()
            else:
                finalized.created_at = _now_unix()
        if finalized.access_url is None and finalized.dataset_path is not None:
            finalized.access_url = _as_path(finalized.dataset_path).resolve().as_uri()
        if finalized.id is None:
            # The local access_url stays on the record (the deposit preview reads it),
            # but the seed takes a location-independent locator (dataset_locator_seed).
            finalized.id = _entity_iri(
                "dataset",
                "::".join(
                    [
                        seed_iri(_with_default(finalized.cell_instance_id, "unknown-cell")),
                        seed_iri(finalized.test_id or ""),
                        dataset_locator_seed(
                            access_url=finalized.access_url,
                            download_url=finalized.download_url,
                            dataset_path=finalized.dataset_path,
                            workspace_root=self.data_root,
                        ),
                        _seed_text_or(finalized.name, "dataset"),
                    ]
                ),
                prefix=self._record_prefix,
            )
        if finalized.source.type is None:
            finalized.source.type = "measurement"
        if finalized.source.retrieved_at is None:
            finalized.source.retrieved_at = finalized.created_at
        if finalized.source.url is None:
            finalized.source.url = finalized.access_url
        return finalized


__all__ = ["Workspace", "quantity", "q"]
