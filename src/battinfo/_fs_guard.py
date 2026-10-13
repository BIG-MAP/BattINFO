"""Guarded recursive deletes, and the check on paths a workspace manifest names.

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

The paths a workspace manifest names (``dist_dir``, ``artifacts_dir``,
``paths.*``, ``resources.*`` and the ``dataset_artifacts`` paths) are checked
twice. When the manifest is read, ``check_relative_path`` requires each to be
a relative path that stays inside the workspace, written the same way on every
system. When BattINFO deletes a folder a manifest names,
``remove_tree(..., within=root)`` checks the resolved path again, so a symbolic
link cannot lead it outside.

BattINFO writes :data:`MARKER_FILENAME` into each output root it creates
(:func:`write_marker`), so that a later ``force=True`` may delete that root.
Roots made by 0.7 and 0.8 carry no marker. They are recognised by their layout
instead, and only when everything in them is what BattINFO writes there: a
folder with a common name such as ``inputs/``, ``release/`` or ``dist/`` counts
only when its content matches. The ``.battinfo`` folder where
``battinfo.workspace()`` keeps a project's records is never deleted, marker or
not, and neither is a folder that holds one.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path, PureWindowsPath
from typing import NamedTuple

PathLike = str | Path

MARKER_FILENAME = ".battinfo-generated"
_MARKER_TEXT = (
    "BattINFO created this folder for its output.\n"
    "A command run with --force (force=True in Python) may delete this folder\n"
    "and everything in it to build it again.\n"
)

# Where battinfo.workspace() keeps a project's records, credentials and
# settings. 0.8 keeps the records in .battinfo/records/; 0.7 kept index.json
# and examples/ there, which looks like an output root.
_AUTHORING_STORE = ".battinfo"

# Files an operating system leaves in a folder someone has browsed.
_SYSTEM_FILES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
_JSON_SUFFIXES = (".json", ".jsonld")


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


def check_relative_path(value: str, *, field: str) -> str:
    """Return ``value`` if it is a relative path that stays inside the folder it is read against.

    For a path a manifest names: ``dist``, ``records/cell-spec`` or
    ``resources/cell.json`` pass. Refused with ``ValueError``, which names
    ``field``:

    - an absolute path, or one with a drive or a share (``/x``, ``C:\\x``,
      ``C:x``, ``//host/share/x``);
    - a ``..`` segment, and a segment of dots and spaces only, which Windows
      reads as the folder it is in;
    - an empty path or ``.``, which name the folder itself.

    ``/`` and ``\\`` both separate segments, so a manifest written on one
    system means the same on another.
    """
    pure = PureWindowsPath(value)  # its anchor holds a leading slash, a drive or a share
    if pure.anchor:
        problem = "starts at a drive, a share or a root folder"
    elif ".." in pure.parts:
        problem = "climbs out of the folder with '..'"
    elif any(not part.strip(". ") for part in pure.parts):
        problem = "has a segment of only dots and spaces, which Windows reads as the folder it is in"
    elif not pure.parts:
        problem = "names the folder itself"
    else:
        return value
    raise ValueError(
        f"{field} {value!r} {problem}. It must be a path relative to the workspace folder that "
        "stays inside it, such as 'dist' or 'records/cell-spec'."
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
    return not _visible(folder)


def _visible(folder: Path) -> list[Path]:
    """What ``folder`` holds, leaving out the files an operating system leaves behind."""
    return [entry for entry in folder.iterdir() if entry.name not in _SYSTEM_FILES]


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


def _authoring_store(path: Path) -> str | None:
    """Why ``path`` is, or holds, the folder where battinfo.workspace() keeps a project's records, or None."""
    folder = _resolved(path)
    name, parent = folder.name.lower(), folder.parent.name.lower()  # Windows and macOS ignore case
    if name == _AUTHORING_STORE or (name == "records" and parent == _AUTHORING_STORE):
        return "battinfo.workspace() keeps a project's records there. Delete it yourself if you mean to."
    if (folder / _AUTHORING_STORE).is_dir():
        return (
            f"it holds {_AUTHORING_STORE}, where battinfo.workspace() keeps a project's records. "
            "Choose another folder, or delete this one yourself."
        )
    return None


# The content checks for what a root made by 0.7 or 0.8 holds at its top level.


def _a_file(path: Path) -> bool:
    return path.is_file()


def _a_folder(path: Path) -> bool:
    return path.is_dir()


def _json_files(path: Path) -> bool:
    """A folder of records, indexes or reports: JSON and JSON-LD files only, at any depth."""
    return path.is_dir() and all(
        item.is_dir() or item.name.endswith(_JSON_SUFFIXES) or item.name in _SYSTEM_FILES
        for item in path.rglob("*")
    )


def _publications(path: Path) -> bool:
    """``publication/``: a folder for each dataset, holding the dataset's JSON-LD publication record."""
    return path.is_dir() and all(
        item.is_dir() and any(child.suffix == ".jsonld" for child in item.iterdir())
        for item in _visible(path)
    )


def _demo_inputs(path: Path) -> bool:
    """The demo's ``inputs/``, which holds its ``cycle-life.csv`` and nothing else."""
    return path.is_dir() and all(item.name == "cycle-life.csv" for item in _visible(path))


def _release(path: Path) -> bool:
    """The ``release/`` folder an export writes, which is a LocalWorkspace root."""
    return path.is_dir() and _not_ours(path, (_LOCAL_WORKSPACE,)) is None


class _Layout(NamedTuple):
    """A kind of root that 0.7 and 0.8 made: the entries that identify it, and what it may hold."""

    files: tuple[str, ...]
    folders: tuple[str, ...]
    entries: Mapping[str, Callable[[Path], bool]]


_LOCAL_WORKSPACE = _Layout(
    # LocalWorkspace.init(), clone(), new_version(), and the release/ an export writes.
    files=("battinfo-workspace.json",),
    folders=(),
    entries={
        "battinfo-workspace.json": _a_file,
        "resources": _json_files,
        "artifacts": _a_folder,  # copies of the dataset's files
        "dist": _json_files,
    },
)
_AUTHORING_WORKSPACE = _Layout(
    # Ingest builds, `battinfo dataset process` and Workspace.save_workspace().
    files=("battinfo-authoring-workspace.json",),
    folders=(),
    entries={
        "battinfo-authoring-workspace.json": _a_file,
        "records": _json_files,
        "artifacts": _a_folder,  # copies of the datasets' files
        "dist": _json_files,
    },
)
_ENGINE = _Layout(
    # publish() and the demo workspace: the object-graph engine's records and exports.
    files=("index.json",),
    folders=("examples",),
    entries={
        "index.json": _a_file,
        "examples": _json_files,
        "library": _json_files,
        "library-rdf": _json_files,
        "ontology": _json_files,
        "package": _json_files,
        "dist": _json_files,
        "publication": _publications,
        "release": _release,
        "inputs": _demo_inputs,
    },
)
_LAYOUTS = (_LOCAL_WORKSPACE, _AUTHORING_WORKSPACE, _ENGINE)


def _not_ours(path: Path, layouts: tuple[_Layout, ...] = _LAYOUTS) -> str | None:
    """Why the folder ``path`` does not look like one BattINFO created, or None.

    A marker-less root counts as BattINFO's when ``layouts`` recognise it and
    each entry in it passes the content check of a layout that does. A project
    folder that BattINFO once wrote ``index.json`` and ``examples/`` into keeps
    its own ``inputs/``, ``publication/`` or ``dist/``.
    """
    reason = _authoring_store(path)
    if reason is not None:
        return reason
    entries = _visible(path)
    if not entries or (path / MARKER_FILENAME).is_file():
        return None
    matched = [
        layout
        for layout in layouts
        if all((path / name).is_file() for name in layout.files)
        and all((path / name).is_dir() for name in layout.folders)
    ]
    if not matched:
        return (
            "it is not empty and BattINFO did not create it. Choose an empty or new "
            "folder, or delete this one yourself."
        )
    extra = sorted(
        entry.name
        for entry in entries
        if not any(entry.name in layout.entries and layout.entries[entry.name](entry) for layout in matched)
    )
    if not extra:
        return None
    one = len(extra) == 1
    return (
        f"it holds {', '.join(extra)}, which {'is' if one else 'are'} not BattINFO output. "
        f"Move {'it' if one else 'them'} out, choose another folder, or delete this one yourself."
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
      such a layout that also holds something BattINFO does not write there;
    - without ``within``, marker or not: the ``.battinfo`` folder where
      ``battinfo.workspace()`` keeps a project's records, its ``records``
      folder, and a folder that holds a ``.battinfo`` folder.

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
    "check_relative_path",
    "check_remove",
    "is_empty_or_missing",
    "is_within",
    "remove_temp_tree",
    "remove_tree",
    "require_within",
    "write_marker",
]
