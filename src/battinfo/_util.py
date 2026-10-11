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
from pathlib import Path, PureWindowsPath
from urllib.parse import unquote, urlparse

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


# The processing extra brings the BDF converter (PyPI name ``batterydf``, import
# name ``bdf``), the readers behind the file formats ``ws.convert()``
# auto-detects, and the plotting libraries.
CONVERTER_INSTALL_HINT = 'Run: pip install "battinfo[processing]"'

_DOI_URL_RE = re.compile(r"^https?://(?:dx\.)?doi\.org/(10\.\S+)$", re.IGNORECASE)
_DOI_LITERAL_RE = re.compile(r"^(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)$")


def _as_path(path: PathLike) -> Path:
    return path if isinstance(path, Path) else Path(path)


_WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def is_local_location(value: object) -> bool:
    """True when *value* names a place on the local file system, not on the network.

    A ``file:`` URI, a Windows drive or UNC path, and a string with no URL
    scheme at all (an absolute or relative path) are local. ``https://...``
    and every other URL scheme are not.
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if _WINDOWS_PATH_RE.match(text) or text.startswith("\\\\"):
        return True
    return urlparse(text).scheme.lower() in ("", "file")


def local_path(value: object) -> Path | None:
    """The file-system path a local location names, or ``None`` for a remote URL.

    Accepts a :class:`~pathlib.Path`, a ``file:`` URI or a plain path string.
    """
    if isinstance(value, Path):
        return value
    if not is_local_location(value):
        return None
    text = str(value).strip()
    parsed = urlparse(text)
    if parsed.scheme.lower() == "file":
        path_text = unquote(parsed.path)
        if parsed.netloc:
            path_text = f"//{parsed.netloc}{path_text}"
        if path_text.startswith("/") and len(path_text) > 2 and path_text[2] == ":":
            path_text = path_text[1:]  # /C:/... -> C:/...
        return Path(path_text)
    return Path(text)


#: Record fields that say where a file or its source can be downloaded. A
#: registry must not receive a local path in any of them (see local_file_references).
LOCATION_FIELDS = frozenset({"access_url", "content_url", "download_url", "source_url", "record_url"})
#: Record fields that may name a file by its name or a relative path (a source
#: file, an artifact's locator inside a deposit), but never by an absolute path
#: on the submitter's computer.
PATH_FIELDS = frozenset({"source_file", "locator"})


def is_absolute_local_path(value: object) -> bool:
    """True for a ``file:`` URI or an absolute file-system path (drive, UNC or ``/`` root).

    A bare file name or a relative path is not absolute, and neither is a URL
    with any other scheme.
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if _WINDOWS_PATH_RE.match(text) or text.startswith(("\\", "/")):
        return True
    return urlparse(text).scheme.lower() == "file"


def local_file_references(node: object, path: str = "") -> list[tuple[str, str]]:
    """``(field path, value)`` for every field in *node* that names a file on this computer.

    Walks a record (or a whole submission envelope) and reports each
    ``access_url``, ``content_url``, ``download_url``, ``source_url`` and
    ``record_url`` holding a ``file:`` URI or a plain path, wherever it sits
    (``dataset.distributions[0].content_url``, ``provenance.source_url``, ...),
    and each ``source_file`` or artifact ``locator`` holding an absolute path or
    a ``file:`` URI (a file name or a relative path there is fine).
    """
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if key in LOCATION_FIELDS and isinstance(value, str):
                if is_local_location(value):
                    found.append((child, value))
            elif key in PATH_FIELDS and isinstance(value, str):
                if is_absolute_local_path(value):
                    found.append((child, value))
            else:
                found.extend(local_file_references(value, child))
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            found.extend(local_file_references(item, f"{path}[{index}]"))
    return found


def local_files_message(offenders: list[tuple[str, list[tuple[str, str]]]]) -> str:
    """The refusal message for records that would publish local file paths to a registry."""
    lines = [
        f"Refusing to send {len(offenders)} record(s) to the registry: they point at files "
        "on this computer, which nobody else can download."
    ]
    for label, fields in offenders:
        lines.append(f"  {label}")
        lines.extend(f"    {field}: {value}" for field, value in fields)
    lines.append(
        "Nothing was sent. Deposit the data files first, for example with ws.zenodo(), so the "
        "records carry https URLs, then submit again. Only for a local test registry, pass "
        "allow_local_files=True."
    )
    if any(field.rsplit(".", 1)[-1] in PATH_FIELDS for _, fields in offenders for field, _ in fields):
        lines.append(
            "A source_file or an artifact locator names the file by its name or by its path "
            "inside the workspace, not by its absolute path on this computer."
        )
    return "\n".join(lines)


def path_name(path: PathLike) -> str:
    """The last component of *path*, split on ``/`` and ``\\`` alike so it is the same on every OS."""
    return PureWindowsPath(str(path)).name


def path_tail(path: PathLike) -> str:
    """The folder and name of *path* (``run1/data.csv``), in POSIX form on every OS.

    Just the name when the path has no named parent (``data.csv``, ``C:\\data.csv``).
    """
    pure = PureWindowsPath(str(path))
    parent = pure.parent.name
    return f"{parent}/{pure.name}" if parent not in ("", ".", "..") else pure.name


def workspace_layout_root(records_root: PathLike) -> Path | None:
    """The workspace folder that owns *records_root*, when it is a workspace records folder.

    ``battinfo.workspace(root)`` keeps its records in ``<root>/.battinfo/records``
    (``<root>/.battinfo/records/examples`` in a pre-0.8 workspace); for either
    this returns ``<root>``. Any other folder returns ``None``.
    """
    path = _as_path(records_root)
    for parent in (path.parent, path.parent.parent):
        if parent.name == ".battinfo":
            return parent.parent
    return None


def workspace_references_root(records_root: PathLike) -> Path | None:
    """Where the workspace owning *records_root* keeps copies of published records it references.

    ``<root>/.battinfo/references/<kind>/`` holds read-only copies of records a
    workspace resolved in the registry (a cell referenced by IRI, a cell spec
    from a search hit). Reference validation against the workspace's records
    folder reads them too; they are never saved over or submitted.
    """
    root = workspace_layout_root(records_root)
    return root / ".battinfo" / "references" if root is not None else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def is_dataset_series(additional_type: object) -> bool:
    """True when a dataset's ``additional_type`` marks it as a dcat:DatasetSeries.

    The marker is the exact string ``"DatasetSeries"`` (DCAT 3 declares
    dcat:DatasetSeries a subclass of dcat:Dataset, so a series is an ordinary
    dataset record flavored by this value — not a separate record type).
    """
    if isinstance(additional_type, str):
        return additional_type == "DatasetSeries"
    if isinstance(additional_type, (list, tuple)):
        return any(item == "DatasetSeries" for item in additional_type)
    return False


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
