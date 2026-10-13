"""The data files of a Zenodo deposit, planned before anything is sent.

``AuthoringWorkspace.zenodo()`` and the deposit previews collect the local
files that the dataset records and the test artifacts name, and plan them
here: each file is resolved once, gets the name it has in the deposit, and is
measured (size, md5 and sha256 in one pass over its bytes). Staging, the
deposit graph, the RO-Crate and the rewrite of the dataset records all take
names, URLs and checksums from the plan, and find a record's file by its
resolved path, never by its name. Two files called ``cycling.csv`` in two
folders are two files in the deposit.

A record, or a distribution entry, that cannot be read is an
:class:`Omission`, never a silent skip, and :func:`deposit_file_problems`
checks the deposit's files against the deposit graph before it is published.
"""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from battinfo._util import file_uri_to_path, is_local_location, path_tail, url_segment

#: Bytes read at a time while a file is measured.
_CHUNK = 1 << 20


def name_key(name: str) -> str:
    """The form under which two deposit names count as one name.

    Windows and macOS file systems ignore case, and macOS also ignores the
    difference between composed and decomposed Unicode, so ``Data.csv`` and
    ``data.csv``, or ``café.csv`` written either way, would land on one file
    when they are staged or downloaded there. The key is the case-folded NFC
    form of the name.
    """
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", name).casefold())


def location_path(location: str, root: Path) -> Path | None:
    """The local path a record location names, read from its text alone.

    *location* is a ``file:`` URI or a plain path, and a relative path is read
    against *root*. A URL with any other scheme gives ``None``. Nothing here
    touches the file system.
    """
    text = location.strip()
    if not text or not is_local_location(text):
        return None
    path = file_uri_to_path(text)
    return path if path.is_absolute() else root / path


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        return path


def path_key(path: Path) -> str:
    """The key that identifies a local file: its resolved path, in the case the OS compares."""
    return os.path.normcase(str(_resolved(path)))


def location_key(location: str, root: Path) -> str | None:
    """The :func:`path_key` of the file *location* names, or ``None`` when it names no local file."""
    try:
        path = location_path(location, root)
    except (OSError, ValueError):
        return None
    return path_key(path) if path is not None else None


def _measure(path: Path) -> tuple[int, str, str]:
    """The size, md5 and sha256 of *path*, from one read of its bytes."""
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            size += len(chunk)
            md5.update(chunk)
            sha256.update(chunk)
    return size, md5.hexdigest(), sha256.hexdigest()


@dataclass(frozen=True)
class DepositFile:
    """One file of a deposit: where it is, what the deposit calls it, and its digests."""

    path: Path
    #: The name the deposit stores and shows, not percent-encoded.
    name: str
    #: ``name`` percent-encoded as one URL path segment.
    segment: str
    size: int = 0
    md5: str = ""
    sha256: str = ""
    #: The test kind of the dataset that first named the file (``protocol`` for an artifact).
    kind: str = "other"
    #: The archive that carries the file in a zipped deposit; empty when the file is deposited as itself.
    archive: str = ""

    def url(self, files_base: str) -> str:
        """The download URL of the deposit file that holds this file: the file itself, or its archive."""
        return f"{files_base}/{url_segment(self.archive) if self.archive else self.segment}"


def measured_file(path: Path, name: str, *, kind: str = "other") -> DepositFile:
    """A file deposited as *name*, measured now (an archive staged for a zipped deposit)."""
    size, md5, sha256 = _measure(path)
    return DepositFile(
        path=path, name=name, segment=url_segment(name), size=size, md5=md5, sha256=sha256, kind=kind,
    )


@dataclass(frozen=True)
class Omission:
    """A record, or a distribution of one, that a deposit would leave out, and why."""

    #: The kind of record, named as the folder it is saved in: ``test``,
    #: ``dataset``, ``cell-instance`` and so on.
    kind: str
    #: The record's IRI or, for a record without one, its file or its place
    #: among the records of its kind (``#2``).
    record: str
    reason: str

    def __str__(self) -> str:
        return f"{self.kind} {self.record}: {self.reason}"


def _brief(value: object) -> str:
    """*value* as ``repr`` shows it, cut to 80 characters."""
    text = repr(value)
    return text if len(text) <= 80 else f"{text[:77]}..."


def distribution_problem(dist: object, position: int) -> str | None:
    """Why the *position*-th distribution entry of a dataset cannot be deposited, or ``None``.

    An entry is an object whose ``content_url`` is text, as the dataset
    schema requires. Anything else names no file a deposit could carry or
    link to. The deposit file plan and the deposit graph both ask, so the two
    report one problem in the same words.
    """
    if not isinstance(dist, Mapping):
        return f"distribution {position} is not an object ({_brief(dist)})"
    url = dist.get("content_url")
    if url is None or (isinstance(url, str) and not url.strip()):
        return f"distribution {position} has no content_url"
    if not isinstance(url, str):
        return f"distribution {position} has a content_url that is not text ({_brief(url)})"
    return None


def dataset_distributions(dataset: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], list[str]]:
    """The distribution entries of a dataset body a deposit can use, and why it cannot use the rest.

    Returns ``(entries, problems)``: the entries :func:`distribution_problem`
    finds nothing wrong with, in order, and one line for each it does, or
    for a ``distributions`` value that is not a list.
    """
    entries = dataset.get("distributions")
    if not entries:
        return [], []
    if not isinstance(entries, list):
        return [], [f"its distributions are not a list ({_brief(entries)})"]
    usable: list[Mapping[str, Any]] = []
    problems: list[str] = []
    for position, entry in enumerate(entries, start=1):
        problem = distribution_problem(entry, position)
        if problem is not None:
            problems.append(problem)
        elif isinstance(entry, Mapping):   # always so once distribution_problem passes it
            usable.append(entry)
    return usable, problems


@dataclass
class DepositFilePlan:
    """The local files one deposit carries, each named once and found by its resolved path."""

    root: Path
    files: list[DepositFile] = field(default_factory=list)
    #: Distribution locations whose file does not exist or is not a file.
    missing: list[str] = field(default_factory=list)
    #: Artifacts left out of the deposit, one warning each.
    artifact_warnings: list[str] = field(default_factory=list)
    #: Record files and distribution entries that could not be read, so no
    #: file could be planned for them.
    omissions: list[Omission] = field(default_factory=list)
    #: True when the files travel in one zip archive per test kind.
    zipped: bool = False
    #: False when the files were located and named but not read (no sizes or digests).
    measured: bool = True
    _by_key: dict[str, DepositFile] = field(default_factory=dict, repr=False)
    _by_location: dict[str, DepositFile | None] = field(default_factory=dict, repr=False)

    def entry_for(self, location: object) -> DepositFile | None:
        """The planned file a record location names (a ``file:`` URI or a path), by resolved path.

        ``None`` for a remote URL, for a file the deposit does not carry, and
        for anything that is not a string.
        """
        if not isinstance(location, str):
            return None
        if location not in self._by_location:
            key = location_key(location, self.root)
            self._by_location[location] = self._by_key.get(key) if key is not None else None
        return self._by_location[location]

    def archives(self) -> dict[str, list[DepositFile]]:
        """The files of a zipped deposit, by the archive that carries them."""
        grouped: dict[str, list[DepositFile]] = {}
        for entry in self.files:
            if entry.archive:
                grouped.setdefault(entry.archive, []).append(entry)
        return dict(sorted(grouped.items()))

    def deposited_names(self) -> list[str]:
        """The names of the data files the deposit holds: the files, or their archives when zipped."""
        return list(self.archives()) if self.zipped else [entry.name for entry in self.files]


def _archive_name(kind: str) -> str:
    """``<kind>.zip``, with anything but letters, digits, ``_``, ``.`` and ``-`` replaced."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", kind).strip("._-")
    return f"{safe or 'other'}.zip"


def _path_label(path: Path, root: Path) -> str:
    """What a colliding name is told apart by: the file's path inside *root*, else its folder and name."""
    try:
        label = path.relative_to(_resolved(root)).as_posix()
    except ValueError:
        label = path_tail(path)
    return unicodedata.normalize("NFC", label)


def _disambiguated(name: str, label: str, taken: set[str]) -> str:
    """*name* with a short hash of *label* in front, salted again until no taken name has its key."""
    salt = label
    attempt = 0
    while True:
        digest = hashlib.sha256(salt.encode("utf-8", "surrogatepass")).hexdigest()[:8]
        candidate = f"{digest}-{name}"
        if name_key(candidate) not in taken:
            return candidate
        attempt += 1
        salt = f"{label}#{attempt}"


def build_deposit_file_plan(
    locations: Iterable[tuple[str, str]],
    *,
    root: Path,
    artifacts: Iterable[Path] = (),
    artifact_warnings: Iterable[str] = (),
    omissions: Iterable[Omission] = (),
    recorded_names: Mapping[str, str] | None = None,
    reserved_names: Iterable[str] = (),
    zip_threshold: int | None = None,
    measure: bool = True,
) -> DepositFilePlan:
    """Plan the files of one deposit.

    *locations* are ``(location, test kind)`` pairs in record order, one for
    each distribution that names a local file. *artifacts* are the artifact
    files already chosen for the deposit. A file named twice, by two
    distributions or two datasets, is one entry, under the first kind that
    names it. A location whose file is missing, or is not a file, is listed
    in ``missing``. *omissions* are the records the caller could not read,
    kept in the plan for the caller to refuse.

    Each file keeps the name *recorded_names* gives its :func:`path_key` (the
    name an earlier deposit gave it), or else takes its own name in NFC form.
    A name whose :func:`name_key` another file, or one of *reserved_names*,
    already holds gets the first eight hex digits of the sha256 of the file's
    path inside *root* (its folder and name when it lies outside) in front:
    ``C01/data.csv`` stays ``data.csv`` and ``C02/Data.csv`` becomes
    ``3f2a9c1d-Data.csv``. The first file keeps its name, so a deposit without
    such clashes has the URLs it always had.

    With more than *zip_threshold* files, each file is assigned to the
    archive ``<kind>.zip``. Without *measure* the files are located and named
    but not read, which is enough to count them or to build the graph.
    """
    found: list[tuple[str, Path, str]] = []   # (path key, resolved path, kind)
    seen: set[str] = set()
    key_of_location: dict[str, str] = {}
    missing: list[str] = []

    def _add(key: str, path: Path, kind: str) -> None:
        if key not in seen:
            seen.add(key)
            found.append((key, path, kind))

    for location, kind in locations:
        try:
            path = location_path(location, root)
        except (OSError, ValueError):
            missing.append(location)
            continue
        if path is None:
            continue
        # Up to here only the location's text was read; this is the first
        # question put to the file system about the file.
        if not path.is_file():
            missing.append(str(path))
            continue
        resolved = _resolved(path)
        key = os.path.normcase(str(resolved))
        key_of_location[location] = key
        _add(key, resolved, kind)
    for artifact in artifacts:
        resolved = _resolved(artifact)
        _add(os.path.normcase(str(resolved)), resolved, "protocol")

    taken = {name_key(name) for name in reserved_names}
    names: dict[str, str] = {}
    for key, _path, _kind in found:
        recorded = (recorded_names or {}).get(key)
        if recorded and name_key(recorded) not in taken:
            names[key] = recorded
            taken.add(name_key(recorded))
    for key, path, _kind in found:
        if key in names:
            continue
        name = unicodedata.normalize("NFC", path.name)
        if name_key(name) in taken:
            name = _disambiguated(name, _path_label(path, root), taken)
        names[key] = name
        taken.add(name_key(name))

    zipped = zip_threshold is not None and len(found) > zip_threshold
    by_key: dict[str, DepositFile] = {}
    by_location: dict[str, DepositFile | None] = {}
    for key, path, kind in found:
        size, md5, sha256 = _measure(path) if measure else (0, "", "")
        name = names[key]
        by_key[key] = DepositFile(
            path=path,
            name=name,
            segment=url_segment(name),
            size=size,
            md5=md5,
            sha256=sha256,
            kind=kind,
            archive=_archive_name(kind) if zipped else "",
        )
    for location, key in key_of_location.items():
        by_location[location] = by_key[key]
    return DepositFilePlan(
        root=root,
        files=list(by_key.values()),
        missing=missing,
        artifact_warnings=list(artifact_warnings),
        omissions=list(omissions),
        zipped=zipped,
        measured=measure,
        _by_key=by_key,
        _by_location=by_location,
    )


def listed_files(listing: object) -> dict[str, str]:
    """The files a deposit lists, as ``{name: md5}``.

    *listing* is Zenodo's reply to a listing of the deposit's files. A
    checksum may carry an ``md5:`` prefix; a file listed with no md5 (another
    algorithm, or none) maps to ``""``. A reply that is not a list lists
    nothing.
    """
    files: dict[str, str] = {}
    for entry in listing if isinstance(listing, list) else []:
        if not isinstance(entry, Mapping):
            continue
        name = entry.get("filename") or entry.get("key")
        if not isinstance(name, str) or not name:
            continue
        algorithm, _, digest = str(entry.get("checksum") or "").rpartition(":")
        files[name] = digest.strip().lower() if algorithm.lower() in ("", "md5") else ""
    return files


def _graph_nodes(graph: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    nodes = graph.get("@graph")
    return [node for node in nodes if isinstance(node, Mapping)] if isinstance(nodes, list) else []


def _url_of(value: object) -> str:
    """The URL a ``dcat:downloadURL`` holds, written as text or as ``{"@id": ...}``."""
    if isinstance(value, Mapping):
        value = value.get("@id")
    return value.strip() if isinstance(value, str) else ""


def _stated_md5(dist: Mapping[str, Any]) -> str:
    """The md5 a distribution node states for its file (``spdx:checksum``), or ``""``."""
    checksum = dist.get("spdx:checksum")
    if not isinstance(checksum, Mapping):
        return ""
    algorithm = checksum.get("spdx:checksumAlgorithm")
    if isinstance(algorithm, Mapping):
        algorithm = algorithm.get("@id")
    value = checksum.get("spdx:checksumValue")
    if not isinstance(algorithm, str) or not algorithm.lower().endswith("md5") or not isinstance(value, str):
        return ""
    return value.strip().lower()


def deposit_file_problems(
    graph: Mapping[str, Any],
    *,
    files_base: str,
    listing: object,
    sent: Mapping[str, str],
) -> list[str]:
    """What is wrong with a deposit's files, one line each; empty when nothing is.

    *graph* is the deposit graph, *files_base* the URL the deposit serves its
    files under (``{record_url}/files``), *listing* the deposit's file
    listing, and *sent* the ``{name: md5}`` of the files this run uploaded or
    kept. The deposit must hold:

    - every file in *sent*, with that md5;
    - every file a ``dcat:downloadURL`` in the graph names under
      *files_base* (the name percent-encoded), with the md5 its distribution
      states when it states one and is the file itself, not an archive that
      holds it;
    - a download URL for every distribution of every member dataset
      (``dcat:Dataset``), either a file of the deposit or an http(s) URL
      elsewhere, which counts as external.
    """
    on_deposit = listed_files(listing)
    problems: list[str] = []
    for name, md5 in sorted(sent.items()):
        if name not in on_deposit:
            problems.append(f"{name} was uploaded but is not on the deposit")
        elif on_deposit[name] != md5:
            held = f"with md5 {on_deposit[name]}" if on_deposit[name] else "without an md5"
            problems.append(f"{name} is on the deposit {held}, but the file uploaded has md5 {md5}")
    prefix = files_base.rstrip("/") + "/"
    for node in _graph_nodes(graph):
        types = node.get("@type")
        member = "dcat:Dataset" in (types if isinstance(types, list) else [types])
        owner = f"dataset {node.get('@id')}" if member else str(node.get("@id") or "a node")
        distributions = node.get("dcat:distribution")
        for dist in distributions if isinstance(distributions, list) else [distributions]:
            if not isinstance(dist, Mapping):
                continue
            url = _url_of(dist.get("dcat:downloadURL"))
            label = str(dist.get("schema:name") or "a distribution")
            if url.startswith(prefix):
                name = unquote(url[len(prefix):])
                if name not in on_deposit:
                    if name not in sent:   # an upload that did not arrive is reported above
                        problems.append(f"{owner}: links to {name}, which is not on the deposit")
                    continue
                stated = _stated_md5(dist)
                if stated and name == label and on_deposit[name] and stated != on_deposit[name]:
                    problems.append(
                        f"{owner}: {name} is on the deposit with md5 {on_deposit[name]}, "
                        f"but the record states md5 {stated}"
                    )
            elif member and not url:
                problems.append(f"{owner}: {label} has no download URL")
            elif member and not url.startswith(("http://", "https://")):
                problems.append(
                    f"{owner}: {label} has the download URL {url}, which is neither on the deposit nor on the web"
                )
    return list(dict.fromkeys(problems))
