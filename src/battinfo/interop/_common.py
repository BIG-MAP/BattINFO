"""Shared helpers for the interop importers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json_source(path: str | Path) -> Any:
    """Read and parse a JSON source file for an importer.

    Every failure carries the file path, so a batch import over many files reports
    WHICH file was unreadable or malformed instead of a bare JSONDecodeError.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read {p}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{p} is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}"
        ) from exc
