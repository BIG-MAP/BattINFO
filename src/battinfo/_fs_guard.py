"""Guarded recursive deletes.

This module holds the only ``shutil.rmtree`` calls in battinfo;
``tests/test_fs_guard.py`` fails if another module makes one. Code that
removes a folder calls one of two functions:

``remove_tree(path, inputs=..., within=...)``
    Removes a folder that a caller named or derived: a workspace root that
    ``force=True`` rebuilds, a ``dist/`` folder named in a manifest. It refuses
    a delete that could take files BattINFO did not write.

``remove_temp_tree(path)``
    Removes a temporary folder the code made itself (``tempfile.mkdtemp``, or
    a folder it renamed aside while swapping a new one in), ignoring errors.

``check_remove`` runs the checks of ``remove_tree`` without deleting, for a
caller that wants to refuse before doing any work. ``is_within(path, root)``
says whether a path lies inside a folder; it is the contained-path test shared
by the delete guard and the manifest path checks.

BattINFO writes :data:`MARKER_FILENAME` into each output root it creates
(:func:`write_marker`), so that a later ``force=True`` may delete that root.
Roots made by 0.7 and 0.8 carry no marker; they are recognised by their layout
instead, as long as they hold nothing BattINFO does not put there.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from pathlib import Path

PathLike = str | Path

MARKER_FILENAME = ".battinfo-generated"
_MARKER_TEXT = (
    "BattINFO created this folder for its output.\n"
    "A command run with --force (force=True in Python) may delete this folder\n"
    "and everything in it to build it again.\n"
)

# Roots made by 0.7 and 0.8 carry no marker. They are recognised by one of
# these files, or by index.json next to examples/ or records/.
_LAYOUT_FILES = ("battinfo-workspace.json", "battinfo-authoring-workspace.json")
_ENGINE_INDEX = "index.json"
_ENGINE_RECORD_DIRS = ("examples", "records")

# What those roots hold at their top level: LocalWorkspace roots (manifest,
# resources/, artifacts/, dist/), ingest and authoring roots (records/,
# artifacts/, dist/) and object-graph engine roots (index.json, records,
# library exports, publication/ and release/ output, the demo's inputs/). A
# marker-less root that holds anything else may be a user's folder that
# BattINFO wrote into, so it is not deleted.
_LAYOUT_ENTRIES = frozenset({
    *_LAYOUT_FILES,
    _ENGINE_INDEX,
    *_ENGINE_RECORD_DIRS,
    "artifacts",
    "dist",
    "inputs",
    "library",
    "library-rdf",
    "ontology",
    "package",
    "publication",
    "release",
    "resources",
})

# Files an operating system leaves in a folder someone has browsed.
_SYSTEM_FILES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})


class UnsafeDeleteError(ValueError):
    """A delete was refused because it could remove files BattINFO did not write."""


def _resolved(path: PathLike) -> Path:
    return Path(path).resolve()


def is_within(path: PathLike, root: PathLike) -> bool:
    """True when ``path`` is ``root`` or lies inside it.

    Both are resolved first, so ``..`` segments and symbolic links cannot step
    out: ``root/dist/../../x`` is not inside ``root``.
    """
    return _resolved(path).is_relative_to(_resolved(root))


def require_within(path: PathLike, root: PathLike) -> None:
    """Raise :class:`UnsafeDeleteError` unless ``path`` lies strictly inside ``root``.

    For a path read from a manifest or a record that names a folder BattINFO
    may delete: it must lie inside the root that owns it, and must not be
    that root.
    """
    target, owner = _resolved(path), _resolved(root)
    if target == owner or not target.is_relative_to(owner):
        raise UnsafeDeleteError(
            f"Refusing to delete {path}: it is not inside {root}. A folder named in a "
            "manifest or a record must lie inside the workspace that owns it."
        )


def is_empty_or_missing(path: PathLike) -> bool:
    """True when ``path`` does not exist, or is a folder that holds nothing of note.

    A folder holding only files the operating system leaves behind
    (``.DS_Store``, ``Thumbs.db``, ``desktop.ini``) counts as empty.
    """
    folder = Path(path)
    if not folder.exists():
        return True
    if not folder.is_dir():
        return False
    return all(entry.name in _SYSTEM_FILES for entry in folder.iterdir())


def write_marker(root: PathLike) -> Path:
    """Mark ``root`` as an output folder BattINFO created, so ``force=True`` may delete it later."""
    marker = Path(root) / MARKER_FILENAME
    marker.write_text(_MARKER_TEXT, encoding="utf-8")
    return marker


def _home() -> Path | None:
    try:
        return Path.home().resolve()
    except (KeyError, OSError, RuntimeError):
        return None


def _cwd() -> Path | None:
    try:
        return Path.cwd().resolve()
    except OSError:
        return None


def _protected(path: Path) -> str | None:
    """Why the resolved ``path`` may never be deleted, or None."""
    if path.parent == path:
        return "it is the root of a drive or file system."
    for label, place in (("your home folder", _home()), ("the current working folder", _cwd())):
        if place is not None and place.is_relative_to(path):
            return f"it is or holds {label} ({place})."
    return None


def _overlap(path: Path, inputs: Iterable[PathLike | None]) -> str | None:
    """Why deleting the resolved ``path`` would touch one of ``inputs``, or None."""
    for item in inputs:
        if item is None:
            continue
        source = _resolved(item)
        if source.is_relative_to(path):
            return f"it is or holds {item}, which this operation reads. Choose a folder outside it."
        if path.is_relative_to(source):
            return f"it lies inside {item}, which this operation reads. Choose a folder outside it."
    return None


def _has_old_layout(path: Path, names: set[str]) -> bool:
    if any(name in names and (path / name).is_file() for name in _LAYOUT_FILES):
        return True
    return (
        _ENGINE_INDEX in names
        and (path / _ENGINE_INDEX).is_file()
        and any(name in names and (path / name).is_dir() for name in _ENGINE_RECORD_DIRS)
    )


def _not_ours(path: Path) -> str | None:
    """Why the folder ``path`` does not look like one BattINFO created, or None."""
    names = {entry.name for entry in path.iterdir()} - _SYSTEM_FILES
    if not names or (path / MARKER_FILENAME).is_file():
        return None
    if _has_old_layout(path, names):
        extra = sorted(names - _LAYOUT_ENTRIES)
        if not extra:
            return None
        return (
            f"it holds {', '.join(extra)}, which BattINFO did not put there. Move "
            f"{'it' if len(extra) == 1 else 'them'} out, choose another folder, or delete this one yourself."
        )
    return (
        "it is not empty and BattINFO did not create it. Choose an empty or new "
        "folder, or delete this one yourself."
    )


def _is_link(path: Path) -> bool:
    isjunction = getattr(os.path, "isjunction", None)  # Python 3.12 and later
    return path.is_symlink() or bool(isjunction is not None and isjunction(path))


def check_remove(
    path: PathLike,
    *,
    inputs: Iterable[PathLike | None] = (),
    within: PathLike | None = None,
) -> None:
    """Raise :class:`UnsafeDeleteError` if :func:`remove_tree` would refuse ``path``.

    Lets a caller refuse before it does any work. Takes the same arguments as
    :func:`remove_tree` and deletes nothing.
    """
    target = Path(path)
    if within is not None:
        require_within(target, within)
    if _is_link(target):
        raise UnsafeDeleteError(f"Refusing to delete {target}: it is a link. Remove the link yourself.")
    if not target.exists():
        return
    if not target.is_dir():
        raise NotADirectoryError(f"Not a folder: {target}")
    resolved = _resolved(target)
    reason = _protected(resolved) or _overlap(resolved, inputs)
    if reason is None and within is None:
        reason = _not_ours(target)
    if reason is not None:
        raise UnsafeDeleteError(f"Refusing to delete {target}: {reason}")


def remove_tree(
    path: PathLike,
    *,
    inputs: Iterable[PathLike | None] = (),
    within: PathLike | None = None,
) -> None:
    """Delete the folder ``path`` and everything in it, unless that is unsafe.

    Refused with :class:`UnsafeDeleteError`, which names the folder:

    - a filesystem root, the home folder, the current working folder, or a
      folder that holds one of them;
    - a folder that is or holds one of ``inputs`` (the files and folders the
      operation reads; ``None`` entries are skipped), or that lies inside one;
    - with ``within`` (the root that owns a path read from a manifest or a
      record): a path that does not lie strictly inside it, even one that does
      not exist;
    - without ``within``: a folder that is not empty and carries neither the
      marker nor the layout of a root BattINFO 0.7 or 0.8 made, or one with
      such a layout that also holds entries BattINFO does not put there.

    A path that does not exist is left alone. A symbolic link or junction is
    refused rather than followed, and a file raises ``NotADirectoryError``.
    """
    check_remove(path, inputs=inputs, within=within)
    if Path(path).exists():
        shutil.rmtree(path)


def remove_temp_tree(path: PathLike) -> None:
    """Delete a temporary folder the code made itself, ignoring errors.

    For a folder from ``tempfile.mkdtemp`` and for one renamed aside while a
    new folder is swapped in. A missing folder is fine. The filesystem-root,
    home and working-folder rules of :func:`remove_tree` still apply, and
    raise :class:`UnsafeDeleteError`.
    """
    target = Path(path)
    reason = _protected(_resolved(target))
    if reason is not None:
        raise UnsafeDeleteError(f"Refusing to delete {target}: {reason}")
    shutil.rmtree(target, ignore_errors=True)


__all__ = [
    "MARKER_FILENAME",
    "UnsafeDeleteError",
    "check_remove",
    "is_empty_or_missing",
    "is_within",
    "remove_temp_tree",
    "remove_tree",
    "require_within",
    "write_marker",
]
