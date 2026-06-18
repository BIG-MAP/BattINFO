"""Shared JSON file-I/O helpers.

A single home for the tiny read/write helpers that were previously duplicated in
almost every module. ``read_json`` returns the parsed object as-is;
``read_record_json`` additionally normalises keys to their canonical snake_case
aliases (used by the record-loading modules); ``write_json`` writes
pretty-printed UTF-8 JSON, creating parent directories as needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from battinfo.canonical_aliases import record_to_snake_aliases


def read_json(path: Path) -> dict[str, Any]:
    """Parse a UTF-8 JSON file into a dict."""
    return json.loads(path.read_text(encoding="utf-8"))


def read_record_json(path: Path) -> dict[str, Any]:
    """Read a record JSON file, normalising keys to canonical snake_case aliases."""
    return record_to_snake_aliases(read_json(path))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write ``payload`` as pretty-printed UTF-8 JSON, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
