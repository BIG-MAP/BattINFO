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

A record a deposit has pointed at its copy of a file no longer names the
local file. The deposit index (``.battinfo/deposit-files.json``, see
:mod:`battinfo._deposit_index`) does, and :class:`DepositContext` reads it:
a URL under a record of this workspace's Zenodo record, or one
``ws.upload()`` made, is a file of the deposit (a :class:`RemoteSource`).
Its local file is planned as any other when it is there. When it is gone, a
deposit that continues the record keeps the copy it already holds (a kept
file, never sent again), and any other deposit lists it as missing. The
plan lists the copies ``ws.upload()`` made in R2 storage
(:attr:`DepositFilePlan.hosted`), which ``ws.zenodo()`` archives only when
it is called with ``archive_hosted_files=True``. A copy
of the workspace's own data whose local file the index does not know, such
as an R2 copy an earlier build made, refuses the deposit instead of being
linked to (:meth:`DepositContext.refusal_for`). Any other Zenodo file URL
on the deposit's Zenodo is put to Zenodo before anything is created
(:meth:`DepositContext.unplaced_record`), since an earlier build may have
pointed records at a draft or a version it never recorded.

A location in a record is screened from its text before the file system is
asked about it (:func:`location_path`). A network path outside the workspace
folder is not read unless the workspace registered the file
(``.battinfo/deposit-files.json``, see :mod:`battinfo._deposit_index`), and
a path that goes up a folder with ``..`` is never read. Asking Windows about
a file on another computer sends that computer the user's network
credentials, so a record must not make a deposit ask about one the workspace
did not take in itself. Imported records carry no local location at all:
``ws.import_()`` keeps only http(s) URLs.
"""

from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from battinfo._deposit_index import (
    ZENODO_HOSTS,
    IndexedFile,
    concept_of_record,
    deposited_files,
    hosted_file,
    parse_zenodo_file_url,
)
from battinfo._util import (
    file_uri_to_path,
    has_parent_reference,
    is_local_location,
    lexical_key,
    lexically_within,
    location_text,
    network_host,
    path_tail,
    url_segment,
)

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


class UnsafeLocation(ValueError):
    """A record location the screen refuses: nothing may read the file it names.

    ``reason`` completes a sentence that starts with the location. ``host`` is
    the computer a refused network path names; it is empty for a path that
    goes up a folder.
    """

    def __init__(self, location: str, reason: str, *, host: str = "") -> None:
        super().__init__(f"{location} {reason}")
        self.location = location
        self.reason = reason
        self.host = host

    def refusal(self) -> str:
        """What was not done with the data file at this location, and why, for a record's report line."""
        if self.host:
            return (
                f"its data file {self.location} {self.reason} and was not added to this workspace "
                "with ws.add(..., data=...), so it was not read"
            )
        return f"its data file {self.location} {self.reason}, so it was not read"


def location_path(location: str, root: Path, *, registered: Collection[str] = frozenset()) -> Path | None:
    """The local path a record location names, screened from its text alone.

    *location* is a ``file:`` URI or a plain path, and a relative path is read
    against *root*, the resolved workspace folder. A URL with any other scheme
    gives ``None``. Nothing here touches the file system: this runs before
    anything asks it about the file.

    A path that goes up a folder with ``..`` is refused with
    :class:`UnsafeLocation`: the workspace never writes one, and the text of
    such a path does not say where it leads. A network path
    (``file://server/share/...``, ``file:////server/share/...``,
    ``\\\\server\\share\\...``) is refused too, unless it lies in *root* or
    the workspace registered the file (its :func:`~battinfo._util.lexical_key`
    is in *registered*). A workspace kept on a network share, or on a drive
    mapped to one, resolves to a network path itself, so its own files pass.
    """
    text = location.strip()
    if not text or not is_local_location(text):
        return None
    written = file_uri_to_path(text)
    # Read from the text, before pathlib parses it: on Linux and macOS a
    # \\server\share path is a relative name, and Python 3.11's pathlib on
    # Windows folds a run of three separators into one, but either names
    # another computer all the same.
    host = network_host(location_text(text))
    path = written if written.is_absolute() else root / written
    if has_parent_reference(path):
        raise UnsafeLocation(text, "goes up a folder with '..'")
    if (
        host is not None
        and not (written.is_absolute() and lexically_within(path, root))
        and lexical_key(path) not in registered
    ):
        raise UnsafeLocation(text, f"is on another computer ({host!r})", host=host)
    return path


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        return path


def path_key(path: Path) -> str:
    """The key that identifies a local file: its resolved path, in the case the OS compares."""
    return os.path.normcase(str(_resolved(path)))


def location_key(location: str, root: Path, *, registered: Collection[str] = frozenset()) -> str | None:
    """The :func:`path_key` of the file *location* names.

    ``None`` when it names no local file, and when :func:`location_path`
    refuses it, in which case nothing asks the file system about it.
    """
    try:
        path = location_path(location, root, registered=registered)
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
    #: True for a file the deposit already holds and keeps as it is, because
    #: there is no local file to send: a copy a new version took over from
    #: the version before, or one an earlier run uploaded to the draft.
    #: ``path`` is the local file it was made from, which is gone (``Path()``
    #: when no record of it was kept), and the size and digests are the ones
    #: recorded when it was deposited (empty when none were).
    kept: bool = False

    def url(self, files_base: str) -> str:
        """The download URL of the deposit file that holds this file: the file itself, or its archive."""
        return f"{files_base}/{url_segment(self.archive) if self.archive else self.segment}"

    def stated_by(self, checksum: object) -> bool:
        """True when a record's ``checksum`` block states this file's sha256 or md5.

        A file that was not read (no digests) states nothing, and so matches
        nothing.
        """
        if not isinstance(checksum, Mapping):
            return False
        algorithm, value = checksum.get("algorithm"), checksum.get("value")
        if not isinstance(algorithm, str) or not isinstance(value, str):
            return False
        digest = {"sha256": self.sha256, "md5": self.md5}.get(algorithm.strip().lower(), "")
        return bool(digest) and value.strip().lower() == digest


def measured_file(path: Path, name: str, *, kind: str = "other") -> DepositFile:
    """A file deposited as *name*, measured now (an archive staged for a zipped deposit)."""
    size, md5, sha256 = _measure(path)
    return DepositFile(
        path=path,
        name=name,
        segment=url_segment(name),
        size=size,
        md5=md5,
        sha256=sha256,
        kind=kind,
    )


@dataclass(frozen=True)
class RemoteSource:
    """A URL a record gives for its data, which names a file of this workspace's deposits.

    The URL is a copy a deposit or ``ws.upload()`` made of a local file:
    ``path`` is that file, when the deposit index knows it, with the size and
    digests recorded then. ``name`` is the name the file has in the Zenodo
    record the deposit continues (or, for a Zenodo URL, in its own record);
    empty when it has none yet. ``continued`` says that the record the deposit
    continues already holds the file under ``name``, so the deposit can keep
    that copy when the local file is gone. ``hosted`` marks a copy hosted
    elsewhere (R2): a deposit that archives it carries the file too, but the
    records keep pointing at the hosted copy. ``private`` marks a hosted copy
    in the private bucket (``ws.upload(public=False)``).
    """

    url: str
    name: str = ""
    path: Path | None = None
    size: int = 0
    md5: str = ""
    sha256: str = ""
    continued: bool = False
    hosted: bool = False
    private: bool = False


@dataclass(frozen=True)
class DepositContext:
    """What a deposit knows, before it asks Zenodo, about the Zenodo record it makes or continues.

    ``environment`` is ``production`` or ``sandbox``. ``concept`` is the
    concept record id of the record the deposit continues (``None`` for a new
    record, or when no concept id was recorded), and ``records`` the record
    ids of that record's versions this workspace knows: a URL under one of
    them names a file the record already holds, whether or not the index
    knows the local file behind it. ``starts_from`` is the record whose files
    the deposit starts from: the draft it updates, or the published record a
    new version is made from (``None`` for a new record). ``index`` is the
    loaded deposit index. ``hosted_bases`` are the URLs ``ws.upload()`` puts
    its R2 copies under (``R2_PUBLIC_BASE_URL``), when one is configured.
    """

    environment: str = "production"
    concept: str | None = None
    records: frozenset[str] = frozenset()
    index: Mapping[str, Any] = field(default_factory=dict)
    hosted_bases: tuple[str, ...] = ()
    starts_from: str | None = None

    def held_files(self) -> dict[str, IndexedFile]:
        """The files the index lists for the record the deposit starts from, by deposit file name.

        A copy the deposit keeps, with no local file to send, is the one
        that record holds, so its size and digests are the ones the index
        noted for that record. A draft that was never published does not
        count, unless the deposit updates that very draft.
        """
        return deposited_files(self.index, self.environment, self.concept, self.starts_from)

    def recorded_names(self) -> dict[str, str]:
        """The name each local file has in the record the deposit continues, keyed by :func:`path_key`."""
        return {item.path_key(): name for name, item in self.held_files().items() if item.path}

    def source_for(self, url: str) -> RemoteSource | None:
        """The deposit file *url* names, or ``None`` for a URL elsewhere on the web.

        A Zenodo file URL (``https://zenodo.org/records/<id>/files/<name>``)
        names a deposit file when the index knows the local file behind it,
        under any record of this workspace, or when ``<id>`` is a record the
        deposit continues. Any other URL does when ``ws.upload()`` made it.
        The local file is the one the index noted for the URL's own record;
        the size and digests of a copy the deposit keeps are those the index
        noted for the record the deposit starts from (:meth:`held_files`).
        """
        zenodo_url = parse_zenodo_file_url(url)
        if zenodo_url is not None:
            environment, record, name = zenodo_url.environment, zenodo_url.record_id, zenodo_url.name
            concept = concept_of_record(self.index, environment, record)
            continued = environment == self.environment and (
                record in self.records or (concept is not None and concept == self.concept)
            )
            known = deposited_files(self.index, environment, concept, record).get(name)
            if known is None and not continued:
                return None
            held = self.held_files().get(name) if continued else None
            return _remote(url, name, known or held, held if continued else known, continued=continued)
        hosted = hosted_file(self.index, url)
        if hosted is None or not hosted.path:
            return None
        # The name and digests the file has in the record the deposit
        # continues, when an earlier version of it deposited the file.
        for name, item in self.held_files().items():
            if item.path and item.path_key() == hosted.path_key():
                return _remote(url, name, item, item, continued=True, hosted=True, private=hosted.private)
        return _remote(url, "", hosted, hosted, hosted=True, private=hosted.private)

    def refusal_for(self, url: str, *, short_id: str = "") -> str | None:
        """Why a deposit refuses a dataset whose data *url* names, or ``None``.

        Called for a URL :meth:`source_for` does not place, so the index
        knows no local file behind it. A deposit does not link to such a URL
        when it is a copy of the workspace's own data that the deposit should
        carry instead, or one a reader could not follow:

        - a file in a sandbox record, from a deposit on zenodo.org: the
          sandbox is a test service, and its records do not last;
        - a copy ``ws.upload()`` made in R2 storage: a URL under one of
          ``hosted_bases``, or one whose path ends in
          ``datasets/<short_id>/<name>`` with the dataset's own *short_id*,
          the key ``ws.upload()`` gives a copy. An earlier build kept no
          record of the local file behind such a copy;
        - an ``s3:`` URL, which no reader can open.
        """
        zenodo_url = parse_zenodo_file_url(url)
        if zenodo_url is not None:
            if self.environment != "production" or zenodo_url.environment != "sandbox":
                return None
            return (
                f"its data file is at {url}, in a record on the Zenodo sandbox ({ZENODO_HOSTS['sandbox']}), "
                "a test service whose records do not last, and this workspace has no record of the local "
                "file behind it. Point the dataset at its local file again (ws.add(..., data=...), then "
                "ws.save())"
            )
        try:
            parts = urlsplit(url.strip())
        except ValueError:
            return None
        if parts.scheme.lower() == "s3":
            return (
                f"its data file is at {url}, in object storage that a reader of the deposit cannot open, "
                "and this workspace has no record of the local file behind it. Point the dataset at its "
                "local file again (ws.add(..., data=...), then ws.save())"
            )
        own_key = bool(short_id) and f"/datasets/{short_id}/" in parts.path
        if own_key or any(url.startswith(f"{base}/") for base in self.hosted_bases):
            return (
                f"its data file is at {url}, a copy ws.upload() made in R2 storage, and this workspace "
                "has no record of the local file behind it, so the deposit cannot carry the file (an "
                "upload made by an earlier build). Point the dataset at its local file again "
                "(ws.add(..., data=...), then ws.save()) and run ws.upload() again"
            )
        return None

    def unplaced_record(self, url: str) -> str | None:
        """The record id of a Zenodo file *url* the deposit cannot tell a link from a copy of its own, or ``None``.

        Called for a URL :meth:`source_for` does not place: a URL on this
        context's Zenodo under a record the deposit does not continue, whose
        file the index does not know. An earlier build pointed the records at
        the drafts and versions it made without recording them, so such a
        URL may be a copy of the workspace's own data, in a draft no reader
        can download or in a version of the deposit's own record. Only Zenodo
        can tell, and ``ws.zenodo()`` asks it before it creates or changes
        anything. A URL on the other Zenodo gives ``None``: the deposit's
        token cannot ask there.
        """
        zenodo_url = parse_zenodo_file_url(url)
        if zenodo_url is None or zenodo_url.environment != self.environment:
            return None
        if zenodo_url.record_id in self.records:
            return None
        return zenodo_url.record_id


def _remote(
    url: str,
    name: str,
    local: IndexedFile | None,
    digests: IndexedFile | None,
    *,
    continued: bool = False,
    hosted: bool = False,
    private: bool = False,
) -> RemoteSource:
    """A :class:`RemoteSource` whose local file is *local*'s and whose size and digests are *digests*'s."""
    return RemoteSource(
        url=url,
        name=name,
        path=Path(local.path) if local is not None and local.path else None,
        size=digests.size if digests is not None else 0,
        md5=digests.md5 if digests is not None else "",
        sha256=digests.sha256 if digests is not None else "",
        continued=continued,
        hosted=hosted,
        private=private,
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
        elif isinstance(entry, Mapping):  # always so once distribution_problem passes it
            usable.append(entry)
    return usable, problems


@dataclass
class DepositFilePlan:
    """The files one deposit carries, each named once and found by its resolved path.

    ``files`` holds the local files first, then the kept files (see
    :attr:`DepositFile.kept`).
    """

    root: Path
    files: list[DepositFile] = field(default_factory=list)
    #: Distribution locations whose file does not exist or is not a file, and
    #: copies a record points at whose local file is gone and which the
    #: deposit does not already hold.
    missing: list[str] = field(default_factory=list)
    #: Artifacts left out of the deposit, one warning each.
    artifact_warnings: list[str] = field(default_factory=list)
    #: Record files and distribution entries that could not be read, so no
    #: file could be planned for them, and data file locations the screen
    #: refused (see :func:`location_path`).
    omissions: list[Omission] = field(default_factory=list)
    #: True when the files travel in one zip archive per test kind.
    zipped: bool = False
    #: False when the files were located and named but not read (no sizes or digests).
    measured: bool = True
    #: The :func:`~battinfo._util.lexical_key` of each file the workspace registered.
    registered: frozenset[str] = frozenset()
    #: URLs of the copies ``ws.upload()`` made in R2 storage that the records
    #: point at. ``ws.zenodo()`` refuses a deposit with any of them unless it
    #: is called with ``archive_hosted_files=True``; the deposit then carries
    #: their files too, and the records keep pointing at these URLs.
    hosted: frozenset[str] = frozenset()
    #: The URLs in ``hosted`` of copies in the private bucket (``ws.upload(public=False)``).
    private_hosted: frozenset[str] = frozenset()
    #: Zenodo file URLs on the deposit's Zenodo that the workspace cannot
    #: tell a link from a copy of its own data, by record id, each as
    #: ``(dataset, URL)`` (see :meth:`DepositContext.unplaced_record`). The
    #: deposit links to them unless Zenodo says the record is a draft of this
    #: account or a version of the deposit's own record.
    unplaced: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    _by_key: dict[str, DepositFile] = field(default_factory=dict, repr=False)
    _by_location: dict[str, DepositFile | None] = field(default_factory=dict, repr=False)
    #: The :func:`path_key` of each file a dataset record names by a ``file:`` location.
    _located: frozenset[str] = field(default_factory=frozenset, repr=False)

    def entry_for(self, location: object) -> DepositFile | None:
        """The planned file a record location names, by resolved path.

        *location* is a ``file:`` URI or a path, or a URL of a copy one of
        this workspace's deposits or uploads made (see :class:`RemoteSource`).
        ``None`` for any other URL, for a file the deposit does not carry, for
        a location the screen refuses (nothing asks the file system about
        it), and for anything that is not a string.
        """
        if not isinstance(location, str):
            return None
        if location not in self._by_location:
            key = location_key(location, self.root, registered=self.registered)
            self._by_location[location] = self._by_key.get(key) if key is not None else None
        return self._by_location[location]

    def local_files(self) -> list[DepositFile]:
        """The files the deposit sends from this computer (or packs into archives, when zipped)."""
        return [entry for entry in self.files if not entry.kept]

    def kept_files(self) -> list[DepositFile]:
        """The files the deposit already holds and keeps, with no local file to send."""
        return [entry for entry in self.files if entry.kept]

    def located_files(self) -> list[DepositFile]:
        """The data files a dataset record names by their local ``file:`` location: those ``ws.upload()`` would put in R2."""
        return [entry for key, entry in self._by_key.items() if key in self._located]

    def archives(self) -> dict[str, list[DepositFile]]:
        """The files of a zipped deposit, by the archive that carries them."""
        grouped: dict[str, list[DepositFile]] = {}
        for entry in self.files:
            if entry.archive:
                grouped.setdefault(entry.archive, []).append(entry)
        return dict(sorted(grouped.items()))

    def deposited_names(self) -> list[str]:
        """The names of the data files the deposit holds: the files, or their archives when zipped."""
        if self.zipped:
            return list(self.archives()) + [entry.name for entry in self.kept_files()]
        return [entry.name for entry in self.files]


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
    registered: Collection[str] = frozenset(),
    owners: Mapping[str, str] | None = None,
    remote: Iterable[tuple[RemoteSource, str]] = (),
    unplaced: Mapping[str, Iterable[tuple[str, str]]] | None = None,
    held: Mapping[str, IndexedFile] | None = None,
) -> DepositFilePlan:
    """Plan the files of one deposit.

    *locations* are ``(location, test kind)`` pairs in record order, one for
    each distribution that names a local file. *artifacts* are the artifact
    files already chosen for the deposit. A file named twice, by two
    distributions or two datasets, is one entry, under the first kind that
    names it. A location whose file is missing, or is not a file, is listed
    in ``missing``, unless the record the deposit continues holds a copy of
    it: *held* maps each file that record holds, by deposit name, to the
    local file the index noted behind it (:meth:`DepositContext.held_files`),
    and a location whose file is gone but which names one of those local
    files is a kept file, as a copy a record points at would be. A sandbox
    deposit leaves the records on their local files, so a new version made
    there after a file was deleted finds the copy this way. *omissions* are
    the records the caller could not read, kept in the plan for the caller
    to refuse.

    Each location is screened first, from its text alone (:func:`location_path`,
    with *registered* the keys of the files the workspace registered). A
    location the screen refuses is never looked up: it becomes an omission of
    the dataset *owners* maps it to (the location itself when it maps it to
    none), for the caller to refuse the deposit over.

    *remote* are ``(source, test kind)`` pairs for the distributions whose
    URL names a copy one of this workspace's deposits or uploads made (see
    :meth:`DepositContext.source_for`). The local file behind a copy is
    planned as any other file when it is there. When it is gone, a copy the
    deposit already holds (``source.continued``) is a kept file, never sent
    again; any other is listed in ``missing``. The URL of a copy
    ``ws.upload()`` made goes into ``hosted`` (and into ``private_hosted``
    for one in the private bucket), for the caller to refuse or archive.
    *unplaced* goes into the plan as it is (see
    :attr:`DepositFilePlan.unplaced`).

    A kept file has the name it has on the deposit. Each other file keeps
    the name in the URL of the copy a record points at, or else the name
    *recorded_names* gives its :func:`path_key` (the name an earlier deposit
    gave it), or else takes its own name in NFC form. A name whose
    :func:`name_key` another file, or one of *reserved_names*, already holds
    gets the first eight hex digits of the sha256 of the file's path inside
    *root* (its folder and name when it lies outside) in front:
    ``C01/data.csv`` stays ``data.csv`` and ``C02/Data.csv`` becomes
    ``3f2a9c1d-Data.csv``. The first file keeps its name, so a deposit without
    such clashes has the URLs it always had.

    With more than *zip_threshold* local files, each is assigned to the
    archive ``<kind>.zip``; a kept file stays as it is. Without *measure* the
    files are located and named but not read, which is enough to count them
    or to build the graph.
    """
    found: list[tuple[str, Path, str]] = []  # (path key, resolved path, kind)
    seen: set[str] = set()
    key_of_location: dict[str, str] = {}
    missing: list[str] = []
    left_out = list(omissions)
    refused: set[str] = set()
    kept: dict[str, DepositFile] = {}  # name key -> the kept file
    kept_location: dict[str, DepositFile] = {}  # URL -> the kept file it names
    url_names: dict[str, str] = {}  # path key -> the name in a record's URL
    hosted: set[str] = set()
    private_hosted: set[str] = set()
    located: set[str] = set()  # path keys of the files named by a file: location

    def _add(key: str, path: Path, kind: str) -> None:
        if key not in seen:
            seen.add(key)
            found.append((key, path, kind))

    def _keep(name: str, path: Path | None, digests: IndexedFile | RemoteSource, kind: str) -> DepositFile:
        """The kept file the deposit holds as *name*, made on first use."""
        entry = kept.get(name_key(name))
        if entry is None:
            entry = DepositFile(
                path=path or Path(),
                name=name,
                segment=url_segment(name),
                size=digests.size,
                md5=digests.md5,
                sha256=digests.sha256,
                kind=kind,
                kept=True,
            )
            kept[name_key(name)] = entry
        return entry

    held_by_path = {item.path_key(): (name, item) for name, item in (held or {}).items() if item.path}
    for location, kind in locations:
        try:
            path = location_path(location, root, registered=registered)
        except UnsafeLocation as exc:
            if location not in refused:
                refused.add(location)
                owner = (owners or {}).get(location) or location
                left_out.append(Omission("dataset", owner, exc.refusal()))
            continue
        except (OSError, ValueError):
            missing.append(location)
            continue
        if path is None:
            continue
        # Up to here only the location's text was read; this is the first
        # question put to the file system about the file.
        if not path.is_file():
            copy = held_by_path.get(path_key(path))
            if copy is not None:
                held_name, held_file = copy
                kept_location[location] = _keep(held_name, path, held_file, kind)
                continue
            missing.append(str(path))
            continue
        resolved = _resolved(path)
        key = os.path.normcase(str(resolved))
        key_of_location[location] = key
        located.add(key)
        _add(key, resolved, kind)
    for source, kind in remote:
        if source.hosted:
            hosted.add(source.url)
            if source.private:
                private_hosted.add(source.url)
        # The index wrote this path when the file went into a deposit or an
        # upload, after the screen had passed it.
        if source.path is not None and source.path.is_file():
            resolved = _resolved(source.path)
            key = os.path.normcase(str(resolved))
            key_of_location[source.url] = key
            _add(key, resolved, kind)
            if source.name:
                url_names.setdefault(key, source.name)
            continue
        if source.continued and source.name:
            kept_location[source.url] = _keep(source.name, source.path, source, kind)
            continue
        missing.append(f"{source.path} (the local file of {source.url})" if source.path is not None else source.url)
    for artifact in artifacts:
        resolved = _resolved(artifact)
        _add(os.path.normcase(str(resolved)), resolved, "protocol")

    # Names already settled come first: those of the deposit's own files and
    # of the files it keeps, then each name a record's URL gives a file, then
    # each name an earlier deposit gave one.
    taken = {name_key(name) for name in reserved_names} | set(kept)
    names: dict[str, str] = {}
    for preferred in (url_names, recorded_names or {}):
        for key, _path, _kind in found:
            name = preferred.get(key)
            if key not in names and name and name_key(name) not in taken:
                names[key] = name
                taken.add(name_key(name))
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
    by_location.update(kept_location)
    for location in refused:
        by_location[location] = None
    return DepositFilePlan(
        root=root,
        files=[*by_key.values(), *kept.values()],
        missing=missing,
        artifact_warnings=list(artifact_warnings),
        omissions=left_out,
        zipped=zipped,
        measured=measure,
        registered=frozenset(registered),
        hosted=frozenset(hosted),
        private_hosted=frozenset(private_hosted),
        unplaced={record: list(uses) for record, uses in (unplaced or {}).items()},
        _by_key=by_key,
        _by_location=by_location,
        _located=frozenset(located),
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


def kept_copy_problems(listing: object, keep: Mapping[str, str]) -> dict[str, str]:
    """Which of the files in *keep* a deposit, by its file *listing*, does not hold as given.

    *keep* maps ``{name: md5}``; an empty md5 accepts any copy. Returns
    ``{name: problem}`` for each file that is not listed, or is listed with
    another md5, where the problem completes a sentence that starts with the
    name (``"is not on it"``).
    """
    on_deposit = listed_files(listing)
    problems: dict[str, str] = {}
    for name, md5 in sorted(keep.items()):
        if name not in on_deposit:
            problems[name] = "is not on it"
        elif md5 and on_deposit[name] != md5.lower():
            problems[name] = f"is on it with md5 {on_deposit[name] or '(none listed)'}, not {md5}"
    return problems


def _graph_nodes(graph: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    nodes = graph.get("@graph")
    return [node for node in nodes if isinstance(node, Mapping)] if isinstance(nodes, list) else []


def _url_of(value: object) -> str:
    """The URL a ``dcat:downloadURL`` holds, written as text or as ``{"@id": ...}``."""
    if isinstance(value, Mapping):
        value = value.get("@id")
    return value.strip() if isinstance(value, str) else ""


def _stated_checksum(dist: Mapping[str, Any], algorithm: str) -> str:
    """The *algorithm* digest (``md5``, ``sha256``) a distribution node states for its file (``spdx:checksum``), or ``""``."""
    checksum = dist.get("spdx:checksum")
    if not isinstance(checksum, Mapping):
        return ""
    stated = checksum.get("spdx:checksumAlgorithm")
    if isinstance(stated, Mapping):
        stated = stated.get("@id")
    value = checksum.get("spdx:checksumValue")
    if not isinstance(stated, str) or not isinstance(value, str):
        return ""
    # An SPDX algorithm IRI (spdx:checksumAlgorithm_sha256), or the bare name.
    if stated.rpartition("_")[2].lower() != algorithm and stated.lower() != algorithm:
        return ""
    return value.strip().lower()


def deposit_file_problems(
    graph: Mapping[str, Any],
    *,
    files_base: str,
    listing: object,
    sent: Mapping[str, str],
    kept: Mapping[str, str] | None = None,
    planned: Mapping[str, DepositFile] | None = None,
) -> list[str]:
    """What is wrong with a deposit's files, one line each; empty when nothing is.

    *graph* is the deposit graph, *files_base* the URL the deposit serves its
    files under (``{record_url}/files``), *listing* the deposit's file
    listing, *sent* the ``{name: md5}`` of the files this run uploaded, or
    found on the deposit unchanged, *kept* the ``{name: md5}`` of the files
    it kept with no local file to send (an empty md5 when none was
    recorded), and *planned* the planned data files by deposit name, with
    the size and sha256 the plan measured. The deposit must hold:

    - every file in *sent*, with that md5;
    - every file in *kept*, with that md5 when it is not empty;
    - every file a ``dcat:downloadURL`` in the graph names under
      *files_base* (the name percent-encoded), with the md5 its distribution
      states when it states one and is the file itself, not an archive that
      holds it;
    - a download URL for every distribution of every member dataset
      (``dcat:Dataset``), either a file of the deposit or an http(s) URL
      elsewhere, which counts as external.

    A distribution of a planned file, the file itself, must also state the
    sha256 and byte size the plan measured, when it states them: Zenodo
    lists md5 only, and the bytes it holds are the bytes the plan read.
    """
    on_deposit = listed_files(listing)
    problems: list[str] = []
    for name, md5 in sorted(sent.items()):
        if name not in on_deposit:
            problems.append(f"{name} was uploaded but is not on the deposit")
        elif on_deposit[name] != md5:
            held = f"with md5 {on_deposit[name]}" if on_deposit[name] else "without an md5"
            problems.append(f"{name} is on the deposit {held}, but the file uploaded has md5 {md5}")
    for name, md5 in sorted((kept or {}).items()):
        if name not in on_deposit:
            problems.append(f"{name} has no local file to upload and is not on the deposit")
        elif md5 and on_deposit[name] != md5:
            held = f"with md5 {on_deposit[name]}" if on_deposit[name] else "without an md5"
            problems.append(
                f"{name} has no local file to upload and is on the deposit {held}, "
                f"not with the md5 {md5} it had when it was deposited"
            )
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
                name = unquote(url[len(prefix) :])
                if name not in on_deposit:
                    if name not in sent and name not in (kept or {}):  # reported above
                        problems.append(f"{owner}: links to {name}, which is not on the deposit")
                    continue
                if name != label:
                    continue  # an archive that holds the file: its digests are the archive's
                stated = _stated_checksum(dist, "md5")
                if stated and on_deposit[name] and stated != on_deposit[name]:
                    problems.append(
                        f"{owner}: {name} is on the deposit with md5 {on_deposit[name]}, "
                        f"but the record states md5 {stated}"
                    )
                entry = (planned or {}).get(name)
                if entry is None or not entry.sha256:
                    continue
                stated = _stated_checksum(dist, "sha256")
                if stated and stated != entry.sha256:
                    problems.append(f"{owner}: {name} has sha256 {entry.sha256}, but the record states sha256 {stated}")
                size = dist.get("dcat:byteSize")
                if isinstance(size, int) and not isinstance(size, bool) and size != entry.size:
                    problems.append(f"{owner}: {name} is {entry.size} bytes, but the record states {size}")
            elif member and not url:
                problems.append(f"{owner}: {label} has no download URL")
            elif member and not url.startswith(("http://", "https://")):
                problems.append(
                    f"{owner}: {label} has the download URL {url}, which is neither on the deposit nor on the web"
                )
    return list(dict.fromkeys(problems))
