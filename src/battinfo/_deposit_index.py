"""The local-source index of a workspace: ``.battinfo/deposit-files.json``.

A Zenodo deposit reads a data file that a record names only when it may (see
:func:`battinfo._deposit_files.location_path`). A file on another computer,
such as a cycler export on a lab share, may be read when this workspace
registered it: ``ws.add("test", ..., data=...)`` registers each data file and
raw file it makes a dataset from, and ``ws.convert()`` each file it converts
and each file it writes. The registered files are kept here, so that the
registration outlives the session.

The file is a JSON object. ``sources`` maps the resolved path of each
registered file to how it was registered::

    {"sources": {"//lab/share/run1.csv": {"registered_by": "ws.add"}}}

Keys other than ``sources`` are kept as they are when the file is written,
so that records of deposits can live in the same file. The file is written
atomically, and one that cannot be read is never written over, since it may
hold what no run can rebuild.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from battinfo._jsonio import write_json
from battinfo._util import lexical_key

#: Where a workspace keeps the index, relative to its root folder.
INDEX_PATH = Path(".battinfo") / "deposit-files.json"


class DepositIndexError(ValueError):
    """The index file exists and cannot be read."""


def index_path(root: Path) -> Path:
    """The index file of the workspace in *root*."""
    return root / INDEX_PATH


def load_deposit_index(root: Path) -> dict[str, Any]:
    """The index of the workspace in *root*, or ``{"sources": {}}`` when it has none yet.

    Raises :class:`DepositIndexError`, naming the file, when the file cannot
    be read, is not JSON, or is not an object whose ``sources`` is an object.
    """
    path = index_path(root)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {"sources": {}}
    except (OSError, UnicodeError) as exc:
        raise DepositIndexError(_unreadable(path, exc)) from exc
    try:
        index = json.loads(text)
    except ValueError as exc:
        raise DepositIndexError(_unreadable(path, exc)) from exc
    if not isinstance(index, dict) or not isinstance(index.setdefault("sources", {}), dict):
        raise DepositIndexError(_unreadable(path, "it is not a JSON object with a 'sources' object"))
    return index


def save_deposit_index(root: Path, index: Mapping[str, Any]) -> None:
    """Write *index* as the index of the workspace in *root*, atomically."""
    write_json(index_path(root), index)


def register_sources(root: Path, paths: Iterable[Path], *, by: str) -> None:
    """Record each of *paths* as a file the workspace in *root* registered; *by* says how.

    Each path is stored resolved, as the dataset records name it. The index
    is written only when a path is new to it.
    """
    resolved = [str(_resolved(path)) for path in paths]
    if not resolved:
        return
    index = load_deposit_index(root)
    sources = index["sources"]
    new = [text for text in dict.fromkeys(resolved) if text not in sources]
    for text in new:
        sources[text] = {"registered_by": by}
    if new:
        save_deposit_index(root, index)


def registered_keys(index: Mapping[str, Any]) -> frozenset[str]:
    """The :func:`~battinfo._util.lexical_key` of each file *index* registers."""
    sources = index.get("sources")
    if not isinstance(sources, Mapping):
        return frozenset()
    return frozenset(lexical_key(Path(text)) for text in sources if isinstance(text, str) and text)


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        return path.absolute()


def _unreadable(path: Path, problem: object) -> str:
    return (
        f"{path} cannot be read ({problem}). It lists the data files this workspace registered "
        "for its Zenodo deposits, and it was left as it is. Repair it, or delete it and run "
        "ws.add(..., data=...) again for the data files outside the workspace folder."
    )
