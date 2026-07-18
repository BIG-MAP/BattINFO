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

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

UID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def stable_uid(seed: str) -> str:
    """Deterministic dashed 16-char uid derived from an identity seed.

    The single minting primitive shared by the workspace finalizers and the
    ``save_*`` builders: the same identity seed always mints the same uid, so a
    re-run of an identical ingest lands on the existing record instead of
    creating a duplicate corpus. The registry's dedup logic mirrors the same
    volatile-key policy (see ``_workspace._VOLATILE_SEED_KEYS``).
    """
    value = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:16], "big")
    chars: list[str] = []
    for _ in range(16):
        value, remainder = divmod(value, 32)
        chars.append(UID_ALPHABET[remainder])
    token = "".join(reversed(chars))
    return "-".join((token[:4], token[4:8], token[8:12], token[12:16]))


def cell_instance_identity_seed(
    *,
    cell_spec_id: str | None,
    serial_number: str | None = None,
    batch_id: str | None = None,
    name: str | None = None,
) -> Optional[str]:
    """Identity seed for a physical cell instance — shared by every minting surface.

    The instance IRI is deterministic from (spec IRI, serial/batch/name), so the
    same physical cell authored through the workspace (``ws.add('cell', ...)``),
    ``save_cell_instance`` or ``create_cell_instance`` lands on the same IRI
    instead of minting parallel identities per surface.

    Returns ``None`` when the instance carries no distinguishing identity at all
    (no name, serial, or batch) — callers must then fall back to their own
    anonymous policy (e.g. a random uid), because two anonymous but physically
    distinct cells must never silently dedup into one.
    """
    label = (name or serial_number or batch_id or "").strip()
    if not label:
        return None
    return "::".join(
        [
            (cell_spec_id or "").strip() or "unknown-cell-spec",
            serial_number or "",
            batch_id or "",
            label,
        ]
    )


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
    EntityKind("material-spec", "material_spec", "material-spec.schema.json", "material-spec", "spec"),
    EntityKind(
        "material",
        "material",
        "material.schema.json",
        "material",
        "material",
        spec_ref_field="material_spec_id",
        spec_entity_type="material-spec",
    ),
    EntityKind("electrode-spec", "electrode_spec", "electrode-spec.schema.json", "electrode-spec", "spec"),
    EntityKind(
        "electrode",
        "electrode",
        "electrode.schema.json",
        "electrode",
        "electrode",
        spec_ref_field="electrode_spec_id",
        spec_entity_type="electrode-spec",
    ),
    EntityKind("separator-spec", "separator_spec", "separator-spec.schema.json", "separator-spec", "spec"),
    EntityKind(
        "separator", "separator", "separator.schema.json", "separator", "separator",
        spec_ref_field="separator_spec_id", spec_entity_type="separator-spec",
    ),
    EntityKind(
        "current-collector-spec", "current_collector_spec", "current-collector-spec.schema.json",
        "current-collector-spec", "spec",
    ),
    EntityKind(
        "current-collector", "current_collector", "current-collector.schema.json",
        "current-collector", "current-collector",
        spec_ref_field="current_collector_spec_id", spec_entity_type="current-collector-spec",
    ),
    EntityKind("electrolyte-spec", "electrolyte_spec", "electrolyte-spec.schema.json", "electrolyte-spec", "spec"),
    EntityKind(
        "electrolyte", "electrolyte", "electrolyte.schema.json", "electrolyte", "electrolyte",
        spec_ref_field="electrolyte_spec_id", spec_entity_type="electrolyte-spec",
    ),
    EntityKind("housing-spec", "housing_spec", "housing-spec.schema.json", "housing-spec", "spec"),
    EntityKind(
        "housing", "housing", "housing.schema.json", "housing", "housing",
        spec_ref_field="housing_spec_id", spec_entity_type="housing-spec",
    ),
    EntityKind("equipment-spec", "equipment_spec", "equipment-spec.schema.json", "equipment-spec", "spec"),
    EntityKind(
        "equipment", "equipment", "equipment.schema.json", "equipment", "equipment",
        spec_ref_field="equipment_spec_id", spec_entity_type="equipment-spec",
    ),
    # Channels are instance-only (no channel-spec kind): flat IRIs, parent link
    # ``equipment_id`` lives in the record body, uid minted deterministically
    # from (equipment uid, index) — IDENTIFIER_POLICY 6.1.
    EntityKind("channel", "channel", "channel.schema.json", "channel", "channel"),
)


# Entity families that follow the generic component spec/instance pattern (reuse an
# existing embedded holder schema). Underscore identifiers; the generic API derives the
# hyphen IRI namespace via ``family.replace("_", "-")``.
COMPONENT_FAMILIES: tuple[str, ...] = (
    "electrode",
    "separator",
    "current_collector",
    "electrolyte",
    "housing",
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


RESERVED_NAMESPACE_SEGMENTS = frozenset(
    {"id", "ontology", "vocab", "doc", "context", "resolver", "twin", "w3id",
     # Claimed by the ontology block in the upstream w3id.org .htaccess —
     # requests to these paths can never reach the record resolver.
     "raw", "inferred", "turtle", "latest", "source"}
)
_reserved_clash = RESERVED_NAMESPACE_SEGMENTS & {k.iri_namespace for k in ENTITY_KINDS}
if _reserved_clash:  # fail at import: a reserved segment can never become an entity namespace
    raise RuntimeError(f"reserved namespace segment(s) used by ENTITY_KINDS: {sorted(_reserved_clash)}")


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
