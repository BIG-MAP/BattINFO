"""Shared cross-module utility helpers.

Single home for the tiny helpers that were previously copy-pasted across
modules (``api``, ``bundle``, ``publication``, ``local_workspace``,
``workspace_state``, ``_workspace``, ``ingest``, ``runtime``, ``ws``,
``interop.battdat``, ``transform.json_to_jsonld``): path coercion, UTC
timestamps, file hashing, and citation/DOI normalization.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

PathLike = str | Path


def require_extra(module_name: str, extra: str, feature: str):
    """Import and return *module_name*, or raise a teaching ImportError naming the fix.

    Single home for the optional-dependency error message so the wording cannot
    drift between call sites::

        pd = require_extra("pandas", "tabular", "convert_csv() reads tabular data files")

    On failure raises::

        ImportError: convert_csv() reads tabular data files and needs the
        [tabular] extra: pip install battinfo[tabular]
    """
    import importlib

    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise ImportError(
            f"{feature} and needs the [{extra}] extra: pip install battinfo[{extra}]"
        ) from exc


_DOI_URL_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/(10\.\S+)$", re.IGNORECASE)
_DOI_LITERAL_RE = re.compile(r"^(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)$")


def _as_path(path: PathLike) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _citation_doi_from_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    match = _DOI_URL_RE.match(value.strip())
    if match is None:
        return None
    return match.group(1)


def _citation_url_value(citation: object = None, citation_doi: object = None) -> str | None:
    if isinstance(citation, str):
        normalized = citation.strip()
        if not normalized:
            return None
        extracted = _citation_doi_from_url(normalized)
        if extracted is not None:
            return f"https://doi.org/{extracted}"
        if _DOI_LITERAL_RE.fullmatch(normalized):
            return f"https://doi.org/{normalized}"
        return normalized
    if isinstance(citation_doi, str):
        normalized = citation_doi.strip()
        if not normalized:
            return None
        extracted = _citation_doi_from_url(normalized)
        if extracted is not None:
            return f"https://doi.org/{extracted}"
        return f"https://doi.org/{normalized}"
    return None
