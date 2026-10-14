"""What a workspace records about its deposits: ``.battinfo/deposit-files.json`` and the Zenodo state files.

``deposit-files.json``, the deposit index, answers two questions a Zenodo
deposit asks about a data file before it reads it.

May it read the file at all? A data file on another computer, such as a
cycler export on a lab share, may be read when this workspace registered
it (see :func:`battinfo._deposit_files.location_path`): ``ws.add("test",
..., data=...)`` registers each data file and raw file it makes a dataset
from, ``ws.convert()`` each file it converts and each file it writes, and
``ws.process()`` each preview it writes.

Which local file is behind a URL a record points at? A deposit points the
dataset records at the copies it holds
(``https://zenodo.org/records/<id>/files/<name>``), and ``ws.upload()``
points them at copies in R2 object storage. Once a record names the copy,
nothing in it names the local file any more, so the index keeps it: the
next deposit (a new version, a retry after a failed run, or a new record
after ``zenodo.json`` was deleted) finds the file through the index, and
keeps the copy a new version takes over from the one before when the local
file is gone. A deposit carries a file hosted in R2 only when it is called
with ``archive_hosted_files=True``, and then reads it from the local file
the index names.

The index is a JSON object::

    {
      "sources": {"//lab/share/run1.csv": {"registered_by": "ws.add"}},
      "deposits": {
        "production": {
          "7000": {
            "records": ["7001", "7002"],
            "files": {
              "cycling.csv": {"path": "C:/lab/C01/cycling.csv", "size": 70,
                              "md5": "...", "sha256": "..."}
            },
            "drafts": {
              "7002": {"cycling.csv": {"path": "C:/lab/C01/cycling.csv", "size": 74,
                                       "md5": "...", "sha256": "..."}}
            }
          }
        }
      },
      "hosted": {
        "https://pub.example/datasets/abc/cycling.csv": {"path": "...", "size": 70,
                                                         "md5": "...", "sha256": "..."},
        "s3://lab-private/datasets/def/eis.csv": {"path": "...", "size": 52, "md5": "...",
                                                  "sha256": "...", "private": true}
      }
    }

``sources`` maps the resolved path of each registered file to how it was
registered. ``deposits`` is keyed by environment (``production`` or
``sandbox``), then by the concept record id that groups the versions of
one Zenodo record, and lists the record ids of those versions this
workspace made and each file its published versions deposited, by deposit
file name, with its local path, size, md5 and sha256. Entries are kept
across versions. ``drafts`` lists, by record id, the files of a draft that
is not published yet: a draft that is never published (one deleted on the
Zenodo website) leaves the entries of the published versions as they were,
and a published one joins them. ``hosted`` maps each URL ``ws.upload()``
gave a record to the local file behind it, marked ``"private": true`` when
the copy went to the private bucket (``ws.upload(public=False)``).

The deposit state names the Zenodo record the next ``ws.zenodo()``
continues, one file for each Zenodo: ``zenodo.json`` for zenodo.org and
``zenodo-sandbox.json`` for the sandbox, so a dry run on the sandbox never
touches the record on zenodo.org. A state holds the environment, concept
record id, record id, deposit id and DOI, whether the record is published,
the published record a draft of a new version was made from
(``version_of``), and the IRIs of the records the deposit holds
(``ws.submit()`` records the DOI on those only).

The files are written atomically. One that cannot be read raises
:class:`DepositIndexError`, naming the file, and is never written over,
since it may hold what no run can rebuild. Keys of the index other than
these are kept as they are when it is written.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from battinfo._jsonio import write_json
from battinfo._util import lexical_key

#: Where a workspace keeps the index, relative to its root folder.
INDEX_PATH = Path(".battinfo") / "deposit-files.json"

#: Where a workspace keeps the state of its record on each Zenodo, relative to its root folder.
STATE_PATHS: dict[str, Path] = {
    "production": Path(".battinfo") / "zenodo.json",
    "sandbox": Path(".battinfo") / "zenodo-sandbox.json",
}

#: The Zenodo environments, with the host that serves the record pages of each.
ZENODO_HOSTS: dict[str, str] = {"production": "zenodo.org", "sandbox": "sandbox.zenodo.org"}


class DepositIndexError(ValueError):
    """A file that records the workspace's deposits exists and cannot be read."""


def zenodo_environment(sandbox: bool) -> str:
    """``"sandbox"`` or ``"production"``."""
    return "sandbox" if sandbox else "production"


# ── The index ────────────────────────────────────────────────────────────────


def index_path(root: Path) -> Path:
    """The index file of the workspace in *root*."""
    return root / INDEX_PATH


def load_deposit_index(root: Path) -> dict[str, Any]:
    """The index of the workspace in *root*, or ``{"sources": {}}`` when it has none yet.

    Raises :class:`DepositIndexError`, naming the file, when the file cannot
    be read, is not JSON, or is not an object of the shape the module
    docstring shows.
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
    problem = _index_shape_problem(index)
    if problem:
        raise DepositIndexError(_unreadable(path, problem))
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


@dataclass(frozen=True)
class IndexedFile:
    """A file the index knows: the local file behind a deposited or hosted copy.

    ``private`` is written to the index only when it is true.
    """

    #: The resolved local path, as text; empty when the index does not know it.
    path: str
    size: int = 0
    md5: str = ""
    sha256: str = ""
    #: True for a copy ``ws.upload(public=False)`` put in the private bucket.
    private: bool = False

    @classmethod
    def from_entry(cls, entry: Mapping[str, Any]) -> IndexedFile:
        size = entry.get("size")
        return cls(
            path=str(entry.get("path") or ""),
            size=size if isinstance(size, int) and not isinstance(size, bool) else 0,
            md5=str(entry.get("md5") or ""),
            sha256=str(entry.get("sha256") or ""),
            private=entry.get("private") is True,
        )

    def to_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"path": self.path, "size": self.size, "md5": self.md5, "sha256": self.sha256}
        if self.private:
            entry["private"] = True
        return entry

    def path_key(self) -> str:
        """The file's path in the case the OS compares, as the deposit file plan keys files."""
        return os.path.normcase(self.path) if self.path else ""


def _concepts(index: Mapping[str, Any], environment: str) -> Mapping[str, Any]:
    deposits = index.get("deposits")
    concepts = deposits.get(environment) if isinstance(deposits, Mapping) else None
    return concepts if isinstance(concepts, Mapping) else {}


def _file_entries(files: object) -> dict[str, IndexedFile]:
    if not isinstance(files, Mapping):
        return {}
    return {name: IndexedFile.from_entry(item) for name, item in files.items() if isinstance(item, Mapping)}


def deposited_files(
    index: Mapping[str, Any], environment: str, concept: str | None, record: str | None = None
) -> dict[str, IndexedFile]:
    """The files the index lists for the Zenodo record *concept* in *environment*, by deposit file name.

    These are the files its published versions deposited, the latest entry
    for each name. With *record*, the files the index lists for that record
    as a draft are laid over them: a draft holds the files of the version it
    was made from and those its runs sent, and keeps them once published. A
    draft that is never published changes nothing for any other record.
    """
    entry = _concepts(index, environment).get(concept or "")
    if not isinstance(entry, Mapping):
        return {}
    found = _file_entries(entry.get("files"))
    drafts = entry.get("drafts")
    if record and isinstance(drafts, Mapping):
        found.update(_file_entries(drafts.get(record)))
    return found


def concept_records(index: Mapping[str, Any], environment: str, concept: str | None) -> frozenset[str]:
    """The record ids of the versions of *concept* in *environment* that this workspace made."""
    entry = _concepts(index, environment).get(concept or "")
    records = entry.get("records") if isinstance(entry, Mapping) else None
    return frozenset(str(item) for item in records) if isinstance(records, list) else frozenset()


def concept_of_record(index: Mapping[str, Any], environment: str, record_id: str) -> str | None:
    """The concept record id the index files *record_id* under in *environment*, or ``None``."""
    for concept, entry in _concepts(index, environment).items():
        records = entry.get("records") if isinstance(entry, Mapping) else None
        if isinstance(records, list) and record_id in (str(item) for item in records):
            return str(concept)
    return None


def note_deposit(
    index: dict[str, Any],
    environment: str,
    concept: str,
    *,
    record_ids: Iterable[str] = (),
    files: Mapping[str, IndexedFile] | None = None,
    draft: str | None = None,
) -> bool:
    """Add *record_ids* and *files* (by deposit file name) to the entry of *concept*; True when it changed.

    With *draft*, the record id of a draft, *files* are the files that draft
    holds. They are kept apart from those of the published versions until
    :func:`note_published` says the draft was published.
    """
    deposits = index.setdefault("deposits", {})
    entry = deposits.setdefault(environment, {}).setdefault(concept, {})
    records = entry.setdefault("records", [])
    files_entry = entry.setdefault("files", {})
    if draft:
        files_entry = entry.setdefault("drafts", {}).setdefault(draft, {})
    changed = False
    for record_id in record_ids:
        if record_id and record_id not in records:
            records.append(record_id)
            changed = True
    for name, item in (files or {}).items():
        value = item.to_entry()
        if files_entry.get(name) != value:
            files_entry[name] = value
            changed = True
    return changed


def note_published(index: dict[str, Any], environment: str, concept: str | None, record_id: str) -> bool:
    """Count the files the draft *record_id* holds among those of the published versions; True when the index changed."""
    entry = _concepts(index, environment).get(concept or "")
    if not isinstance(entry, dict):
        return False
    drafts = entry.get("drafts")
    if not isinstance(drafts, dict) or record_id not in drafts:
        return False
    held = drafts.pop(record_id)
    if not drafts:
        del entry["drafts"]
    if isinstance(held, Mapping):
        files = entry.setdefault("files", {})
        files.update({name: dict(item) for name, item in held.items() if isinstance(item, Mapping)})
    return True


def hosted_file(index: Mapping[str, Any], url: str) -> IndexedFile | None:
    """The local file behind *url*, a copy ``ws.upload()`` made, or ``None``."""
    hosted = index.get("hosted")
    entry = hosted.get(url) if isinstance(hosted, Mapping) else None
    return IndexedFile.from_entry(entry) if isinstance(entry, Mapping) else None


def note_hosted(index: dict[str, Any], files: Mapping[str, IndexedFile]) -> bool:
    """Record the local file behind each URL of *files*; True when the index changed."""
    hosted = index.setdefault("hosted", {})
    changed = False
    for url, item in files.items():
        value = item.to_entry()
        if hosted.get(url) != value:
            hosted[url] = value
            changed = True
    return changed


@dataclass(frozen=True)
class ZenodoFileURL:
    """The parts of the URL of a file in a Zenodo record."""

    environment: str
    record_id: str
    #: The file name, percent-decoded.
    name: str


def parse_zenodo_file_url(url: object) -> ZenodoFileURL | None:
    """The environment, record id and file name of a Zenodo file URL, or ``None``.

    The URL is ``https://zenodo.org/records/<id>/files/<name>`` (or
    ``sandbox.zenodo.org``, or the older ``/record/<id>``), the form a deposit
    gives the records it points at its files. A query such as
    ``?download=1`` is ignored.
    """
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    environment = next((env for env, name in ZENODO_HOSTS.items() if name == host), None)
    if environment is None or parts.scheme.lower() not in ("http", "https") or port not in (None, 443):
        return None
    segments = parts.path.split("/")
    if len(segments) < 5 or segments[0] or segments[1] not in ("records", "record") or segments[3] != "files":
        return None
    record_id, name = segments[2], unquote("/".join(segments[4:]))
    if not record_id.isdigit() or not name:
        return None
    return ZenodoFileURL(environment=environment, record_id=record_id, name=name)


# ── The state of the workspace's Zenodo record ───────────────────────────────


def state_path(root: Path, environment: str = "production") -> Path:
    """The file that holds the state of the record the workspace in *root* has on the Zenodo of *environment*."""
    return root / STATE_PATHS[environment]


def state_file(environment: str) -> str:
    """The state file of *environment* as messages name it, such as ``.battinfo/zenodo.json``."""
    return STATE_PATHS[environment].as_posix()


def _read_state(path: Path, environment: str) -> dict[str, Any] | None:
    """The state the file *path* of *environment* holds, or ``None`` when there is no such file.

    The state's own environment is filled in: a state written before it was
    stored names it with ``"sandbox": true`` or ``false``, or not at all (the
    environment of its file).
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as exc:
        raise DepositIndexError(_unreadable_state(path, environment, exc)) from exc
    try:
        state = json.loads(text)
    except ValueError as exc:
        raise DepositIndexError(_unreadable_state(path, environment, exc)) from exc
    problem = _state_shape_problem(state, environment)
    if problem:
        raise DepositIndexError(_unreadable_state(path, environment, problem))
    state.setdefault("environment", "sandbox" if state.get("sandbox") is True else environment)
    state.pop("sandbox", None)
    for key in ("record_id", "deposit_id", "concept_record_id", "version_of"):
        if state.get(key) is not None:
            state[key] = str(state[key])
    return state


def load_deposit_state(root: Path, environment: str = "production") -> dict[str, Any]:
    """The state of the record the workspace in *root* has on the Zenodo of *environment*, or ``{}``.

    Each Zenodo has its own file (:data:`STATE_PATHS`), so a dry run on the
    sandbox never touches the record on zenodo.org. An earlier build kept a
    sandbox record in ``zenodo.json`` too, marked ``"sandbox": true``. Such a
    state is read as the sandbox's, until the sandbox has a file of its own,
    and never as the record on zenodo.org. Raises :class:`DepositIndexError`,
    naming the file, when a file it reads cannot be read or does not hold a
    state.
    """
    state = _read_state(state_path(root, environment), environment)
    if state is not None:
        return state if state["environment"] == environment else {}
    if environment == "sandbox":
        legacy = _read_state(state_path(root, "production"), "production")
        if legacy is not None and legacy["environment"] == "sandbox":
            return legacy
    return {}


def save_deposit_state(root: Path, state: Mapping[str, Any]) -> None:
    """Write *state* to the state file of its environment in *root*, atomically.

    A sandbox record an earlier build kept in ``zenodo.json`` is moved to
    the sandbox's own file first, when that has none yet, so the record on
    zenodo.org does not write over it.
    """
    environment = str(state.get("environment") or "production")
    if environment == "production":
        current = _read_state(state_path(root, "production"), "production")
        sandbox_path = state_path(root, "sandbox")
        if current is not None and current["environment"] == "sandbox" and not sandbox_path.exists():
            write_json(sandbox_path, current)
    write_json(state_path(root, environment), {**state, "environment": environment})


# ── Shapes ────────────────────────────────────────────────────────────────────


def _file_entry_problem(entry: object) -> str | None:
    if not isinstance(entry, Mapping):
        return "is not an object"
    if not isinstance(entry.get("path", ""), str):
        return "has a path that is not text"
    for key in ("md5", "sha256"):
        if not isinstance(entry.get(key, ""), str):
            return f"has an {key} that is not text"
    size = entry.get("size", 0)
    if not isinstance(size, int) or isinstance(size, bool):
        return "has a size that is not a whole number"
    if not isinstance(entry.get("private", False), bool):
        return "has a 'private' that is not true or false"
    return None


def _index_shape_problem(index: Mapping[str, Any]) -> str | None:
    """What is wrong with the shape of the ``deposits`` and ``hosted`` parts of *index*, or ``None``."""
    deposits = index.get("deposits", {})
    if not isinstance(deposits, Mapping):
        return "its 'deposits' is not an object"
    for environment, concepts in deposits.items():
        if environment not in ZENODO_HOSTS:
            return f"its 'deposits' names the environment {environment!r}, not 'production' or 'sandbox'"
        if not isinstance(concepts, Mapping):
            return f"its 'deposits' entry {environment!r} is not an object"
        for concept, entry in concepts.items():
            where = f"'deposits' entry {environment!r} {concept!r}"
            if not isinstance(entry, Mapping):
                return f"its {where} is not an object"
            records = entry.get("records", [])
            if not isinstance(records, list) or not all(isinstance(item, str) for item in records):
                return f"its {where} 'records' is not a list of record ids"
            files = entry.get("files", {})
            if not isinstance(files, Mapping):
                return f"its {where} 'files' is not an object"
            for name, item in files.items():
                problem = _file_entry_problem(item)
                if problem:
                    return f"the file {name!r} of its {where} {problem}"
            drafts = entry.get("drafts", {})
            if not isinstance(drafts, Mapping):
                return f"its {where} 'drafts' is not an object"
            for draft, held in drafts.items():
                if not isinstance(held, Mapping):
                    return f"its {where} draft {draft!r} is not an object"
                for name, item in held.items():
                    problem = _file_entry_problem(item)
                    if problem:
                        return f"the file {name!r} of draft {draft!r} in its {where} {problem}"
    hosted = index.get("hosted", {})
    if not isinstance(hosted, Mapping):
        return "its 'hosted' is not an object"
    for url, item in hosted.items():
        problem = _file_entry_problem(item)
        if problem:
            return f"its 'hosted' entry {url!r} {problem}"
    return None


def _state_shape_problem(state: object, environment_of_file: str) -> str | None:
    """What keeps *state*, read from the state file of *environment_of_file*, from being a deposit state, or ``None``."""
    if not isinstance(state, dict):
        return "it is not a JSON object"
    for key in ("record_id", "deposit_id", "concept_record_id", "version_of"):
        value = state.get(key)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip()
        ):
            return f"its {key!r} is not a record id"
    if not state.get("record_id"):
        return "it names no 'record_id'"
    environment = state.get("environment")
    if environment is not None and environment not in ZENODO_HOSTS:
        return f"its 'environment' is {environment!r}, not 'production' or 'sandbox'"
    for key in ("published", "sandbox"):
        if key in state and not isinstance(state[key], bool):
            return f"its {key!r} is not true or false"
    if (
        environment is not None
        and isinstance(state.get("sandbox"), bool)
        and (environment == "sandbox") != state["sandbox"]
    ):
        return "its 'environment' and its 'sandbox' disagree"
    if environment_of_file == "sandbox" and (environment == "production" or state.get("sandbox") is False):
        return "it names a record on zenodo.org, but it is the file of the sandbox record"
    if "doi" in state and not isinstance(state["doi"], str):
        return "its 'doi' is not text"
    records = state.get("records", [])
    if not isinstance(records, list) or not all(isinstance(item, str) for item in records):
        return "its 'records' is not a list of record IRIs"
    return None


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError, ValueError):
        return path.absolute()


def _unreadable(path: Path, problem: object) -> str:
    return (
        f"{path} cannot be read ({problem}). It lists the data files this workspace registered "
        "and the local files behind the copies its deposits and uploads made, and it was left as "
        "it is. Repair it, or delete it and run ws.add(..., data=...) again for the data files "
        "outside the workspace folder."
    )


def _unreadable_state(path: Path, environment: str, problem: object) -> str:
    host = ZENODO_HOSTS[environment]
    return (
        f"{path} cannot be read ({problem}). It names the record this workspace continues on {host}, "
        f"and it was left as it is. Repair it, or delete it to start a new record on {host} "
        "(ws.zenodo(record_id=...) after that continues a published record instead)."
    )
