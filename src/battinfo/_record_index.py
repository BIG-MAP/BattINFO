"""In-memory record-location cache for bulk saves (beta-hardening 3.4).

``save_record`` (and reference validation) must map a canonical IRI to the file
that holds it. Outside a session that is a per-call directory scan with a JSON
parse of every candidate file — O(n) per save, O(n²) for a bulk ingest, the
measured 15–20 records/s. Inside a :func:`bulk_save_session` each entity type
is scanned once, lookups are O(1), and every save updates the map in place.

The session assumes it is the only writer under ``source_root`` for its
lifetime (the normal shape of a bulk ingest). Files changed by OTHER processes
during the session are not re-read.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator

from battinfo._jsonio import read_record_json
from battinfo.entities import entity_id_from_doc, iter_entity_files, kind_for_doc


def _root_key(source_root: Path | str) -> str:
    """Normalise a source root for cache-identity comparison WITHOUT touching the
    filesystem (``Path.resolve`` costs two syscalls per call on Windows, and this
    runs several times per save). Symlink aliases of the same root therefore
    compare unequal — the caller just misses the cache and takes the slow path."""
    return os.path.normcase(os.path.abspath(str(source_root)))


class RecordLocationCache:
    """Lazy id → (path, entity_type) map over one source root."""

    def __init__(self, source_root: Path | str) -> None:
        self.source_root = Path(source_root)
        self.root_key = _root_key(source_root)
        self._by_id: dict[str, tuple[Path, str]] = {}
        self._scanned_types: set[str] = set()

    def _scan(self, entity_type: str) -> None:
        if entity_type in self._scanned_types:
            return
        self._scanned_types.add(entity_type)
        for path in iter_entity_files(entity_type, self.source_root):
            try:
                doc = read_record_json(path)
                entity_id = entity_id_from_doc(doc)
                kind = kind_for_doc(doc)
            except Exception:  # noqa: BLE001 — unreadable stray files never block a save
                continue
            if not entity_id or kind is None:
                continue
            # First hit wins, matching the scan order of the uncached lookup.
            self._by_id.setdefault(entity_id, (path, kind.entity_type))

    def lookup(self, entity_id: str, candidate_types: list[str]) -> tuple[Path, str] | None:
        """Return (path, entity_type) for *entity_id*, scanning candidate types once."""
        for entity_type in candidate_types:
            self._scan(entity_type)
        return self._by_id.get(entity_id)

    def record_saved(self, entity_id: str, path: Path | str, entity_type: str) -> None:
        """Keep the map current after a write, so later saves resolve references to it."""
        self._by_id[entity_id] = (Path(path), entity_type)


_ACTIVE: ContextVar[RecordLocationCache | None] = ContextVar("battinfo_record_cache", default=None)


def active_record_cache(source_root: Path | str) -> RecordLocationCache | None:
    """The enclosing bulk session's cache, if one is active for *source_root*."""
    cache = _ACTIVE.get()
    if cache is not None and cache.root_key == _root_key(source_root):
        return cache
    return None


@contextmanager
def bulk_save_session(source_root: Path | str) -> Iterator[RecordLocationCache]:
    """Speed up a batch of ``save_*`` calls against one source root.

    Loads the id→path map once (per entity type, lazily) instead of rescanning
    the source root on every save::

        with battinfo.bulk_save_session("examples"):
            for draft in drafts:
                battinfo.save_cell_instance(draft, source_root="examples")

    Nested sessions for the same root reuse the outer cache. The session
    assumes single-writer access to ``source_root`` for its duration.
    """
    outer = _ACTIVE.get()
    if outer is not None and outer.root_key == _root_key(source_root):
        yield outer
        return
    cache = RecordLocationCache(source_root)
    token = _ACTIVE.set(cache)
    try:
        yield cache
    finally:
        _ACTIVE.reset(token)
