"""Shared JSON file-I/O helpers.

A single home for the tiny read/write helpers that were previously duplicated in
almost every module. ``read_json`` returns the parsed object as-is;
``read_record_json`` additionally normalises keys to their canonical snake_case
aliases (used by the record-loading modules); ``write_json`` writes
pretty-printed UTF-8 JSON, creating parent directories as needed.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from battinfo.canonical_aliases import record_to_snake_aliases


def read_json(path: Path) -> dict[str, Any]:
    """Parse a UTF-8 JSON file into a dict."""
    return json.loads(path.read_text(encoding="utf-8"))


def read_record_json(path: Path) -> dict[str, Any]:
    """Read a record JSON file, normalising keys to canonical snake_case aliases."""
    return record_to_snake_aliases(read_json(path))


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Atomically write ``text`` to ``path``, creating parent dirs as needed.

    Writes to a temporary file in the same directory, flushes + ``fsync``s it,
    then ``os.replace``s it into place (atomic on POSIX and Windows). An
    interrupted write — Ctrl-C, crash, disk-full, or a cloud-sync race — therefore
    leaves the *previous* file fully intact instead of a truncated or empty record.

    Newline handling matches :meth:`pathlib.Path.write_text` (text mode, default
    translation), so the on-disk bytes are identical to the previous non-atomic
    implementation and no line-ending churn is introduced.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        # Best-effort cleanup so an interrupted write never leaks a temp file or
        # fd, and never masks the original exception. If os.fdopen itself failed,
        # the raw fd is still open and must be closed before the temp can be
        # unlinked on Windows (else the unlink hits WinError 32).
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically write ``payload`` as pretty-printed UTF-8 JSON, creating parent dirs."""
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
