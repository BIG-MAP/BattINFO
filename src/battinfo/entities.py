"""Single source of truth for BattINFO record types.

Every BattINFO record is one of a small set of **entity kinds**, and the model
follows a uniform *spec + instance* pattern: a *spec* is the reusable, datasheet
-like type description; an *instance* is a physical realization of that spec
(a batch of material, a built electrode, a tested cell). ``cell-spec``/``cell``
and ``test-spec``/``test`` already follow this; new families extend it.

This module centralizes the per-type metadata (top-level JSON key, schema file,
on-disk subdirectory, IRI namespace, instance->spec link) that used to be
copy-pasted across ``api.py``, ``validate/record.py``, ``validate/references.py``,
``ws.py`` and ``_workspace.py``. Those call sites now derive their dispatch from
:data:`ENTITY_KINDS` so adding a family is a single registry entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional


@dataclass(frozen=True)
class EntityKind:
    """Metadata describing one BattINFO record type.

    Attributes:
        entity_type: Canonical hyphenated identifier, e.g. ``"cell-spec"``,
            ``"material"``. Used as the logical type and the saved-file prefix.
        record_key: Top-level JSON key carrying the record body, e.g.
            ``"cell_spec"``, ``"material"``.
        schema_file: Path (relative to ``data/schemas``) of the JSON Schema.
        subdir: Directory name under a ``source_root`` where records live.
        iri_namespace: Path segment in the canonical IRI
            ``https://w3id.org/battinfo/<iri_namespace>/<uid>``.
        spec_ref_field: For an instance kind, the body field that links to its
            spec (e.g. ``"cell_spec_id"``); ``None`` for spec kinds.
        spec_entity_type: The ``entity_type`` that ``spec_ref_field`` points to.
    """

    entity_type: str
    record_key: str
    schema_file: str
    subdir: str
    iri_namespace: str
    spec_ref_field: Optional[str] = None
    spec_entity_type: Optional[str] = None


# Registered in a deterministic order. Dispatch keys on ``record_key`` (unique),
# so ordering only affects iteration (e.g. record-set directory order).
ENTITY_KINDS: tuple[EntityKind, ...] = (
    EntityKind("cell-spec", "cell_spec", "cell-spec.schema.json", "cell-spec", "spec"),
    EntityKind(
        "cell",
        "cell_instance",
        "cell-instance.schema.json",
        "cell-instance",
        "cell",
        spec_ref_field="cell_spec_id",
        spec_entity_type="cell-spec",
    ),
    EntityKind("test-protocol", "test_spec", "test-protocol.schema.json", "test-protocol", "spec"),
    EntityKind("test", "test", "test.schema.json", "test", "test"),
    EntityKind("dataset", "dataset", "dataset.schema.json", "dataset", "dataset"),
    EntityKind("material-spec", "material_spec", "material-spec.schema.json", "material-spec", "material-spec"),
    EntityKind(
        "material",
        "material",
        "material.schema.json",
        "material",
        "material",
        spec_ref_field="material_spec_id",
        spec_entity_type="material-spec",
    ),
)

ENTITY_BY_TYPE: dict[str, EntityKind] = {kind.entity_type: kind for kind in ENTITY_KINDS}
ENTITY_BY_RECORD_KEY: dict[str, EntityKind] = {kind.record_key: kind for kind in ENTITY_KINDS}


def kind_for_doc(doc: Mapping[str, object]) -> Optional[EntityKind]:
    """Return the :class:`EntityKind` whose ``record_key`` is present in *doc*."""
    for kind in ENTITY_KINDS:
        if isinstance(doc.get(kind.record_key), Mapping):
            return kind
    return None


def kind_for_type(entity_type: str) -> Optional[EntityKind]:
    """Return the :class:`EntityKind` for a logical ``entity_type``."""
    return ENTITY_BY_TYPE.get(entity_type)


def record_set_dirs() -> tuple[str, ...]:
    """On-disk subdirectory names for every registered record type."""
    return tuple(kind.subdir for kind in ENTITY_KINDS)


def iri_namespace_map() -> dict[str, str]:
    """Map ``entity_type`` -> IRI namespace segment for registered kinds."""
    return {kind.entity_type: kind.iri_namespace for kind in ENTITY_KINDS}


def entity_types_for_namespace(namespace: str) -> list[str]:
    """Logical entity types that mint IRIs under *namespace*.

    Multiple kinds can share a namespace (``cell-spec`` and ``test-protocol``
    both use ``spec/``). Falls back to ``[namespace]`` when nothing matches, to
    preserve the previous best-effort lookup behavior.
    """
    matches = [kind.entity_type for kind in ENTITY_KINDS if kind.iri_namespace == namespace]
    return matches or [namespace]


def entity_id_from_doc(doc: Mapping[str, object]) -> Optional[str]:
    """Return the canonical ``id`` from a record body, or ``None``."""
    kind = kind_for_doc(doc)
    if kind is None:
        return None
    body = doc.get(kind.record_key)
    if isinstance(body, Mapping) and isinstance(body.get("id"), str):
        return body["id"]
    return None


def save_entity_path(entity_type: str, uid: str, source_root: Path) -> Path:
    """Canonical on-disk path for a record of *entity_type* with *uid*."""
    kind = ENTITY_BY_TYPE.get(entity_type)
    if kind is None:
        raise ValueError(f"Unsupported entity type for save path: {entity_type}")
    return source_root / kind.subdir / f"{entity_type}-{uid}.json"


def iter_entity_files(entity_type: str, source_root: Path) -> list[Path]:
    """Sorted ``*.json`` files for *entity_type* under *source_root* (or empty)."""
    kind = ENTITY_BY_TYPE.get(entity_type)
    if kind is None:
        return []
    directory = source_root / kind.subdir
    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))
