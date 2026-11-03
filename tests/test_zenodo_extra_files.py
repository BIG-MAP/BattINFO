"""A Zenodo deposit carries files that document it and belong to no dataset (``extra_files=``).

- ``ws.zenodo(extra_files=...)`` uploads each file as itself, never zipped,
  under its own name or the name a mapping gives it, and records the names in
  the state file. The RO-Crate lists each as a ``File`` and the deposit
  graph's catalog as a ``schema:DigitalDocument`` under ``schema:hasPart``,
  while ``dcat:dataset`` keeps the datasets alone.
- A re-run keeps an extra file that has not changed, replaces one that has,
  and removes none it names. A re-run that names none removes them, with a
  warning that names the files the state file recorded.
- A path that is no file, a name that is no plain file name, and a name the
  deposit already gives a data file, an archive, ``battinfo.json``,
  ``ro-crate-metadata.json``, ``battinfo.jsonld`` or another extra file are
  refused before anything is sent, by the previews too.
- Extra files count toward the 100 files Zenodo takes in one record.
- ``ws.preview_jsonld()`` and ``ws.preview_rocrate()`` take ``extra_files``;
  the graph still passes the gold-standard check, and the crate the RO-Crate
  validation.

All offline: Zenodo is answered in memory, under the real
``ZenodoClient.sync_files``.
"""

from __future__ import annotations

import hashlib
import json
import re
import warnings
import zipfile
from pathlib import Path

import pytest

import battinfo
from battinfo._deposit_index import DepositIndexError, load_deposit_state
from battinfo.validate import validate_publication_report
from battinfo.ws import AuthoringWorkspace, _extra_file_media_type
from battinfo.zenodo import ZenodoClient

pytestmark = pytest.mark.usefixtures("registry_holds_none")  # deposits ask the registry first (#483)

CREATORS = [{"name": "Doe, Jane", "affiliation": "Example University"}]
CSV = "test_time_second,voltage_volt,current_ampere\n0,3.0,0\n60,3.5,0.001\n"
PLACEHOLDER_FILES = "https://zenodo.org/records/RECORD_ID/files"
OWN_FILES = {"battinfo.json", "ro-crate-metadata.json"}


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()  # noqa: S324 - Zenodo's file checksum


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Zenodo:
    """One Zenodo account, answered in memory.

    Each deposit keeps its files by name. ``uploaded`` and ``deleted`` list
    the names each upload and each deletion touched, in order.
    """

    def __init__(self) -> None:
        self.deposits: dict[int, dict[str, bytes]] = {}
        self.published: set[int] = set()
        self.uploaded: list[str] = []
        self.deleted: list[str] = []

    def client(self, *, token: str, sandbox: bool = False) -> _Client:
        return _Client(self, token=token, sandbox=sandbox)

    def files(self, deposit_id: int = 7000) -> dict[str, bytes]:
        return self.deposits[deposit_id]

    def graph(self, deposit_id: int = 7000) -> dict:
        return json.loads(self.files(deposit_id)["battinfo.json"])

    def crate(self, deposit_id: int = 7000) -> dict:
        return json.loads(self.files(deposit_id)["ro-crate-metadata.json"])


class _Client(ZenodoClient):
    """The real ZenodoClient, sync_files included, on the in-memory account instead of HTTP."""

    def __init__(self, zenodo: _Zenodo, *, token: str, sandbox: bool = False) -> None:
        super().__init__(token=token, sandbox=sandbox)
        self._zenodo = zenodo

    def _reply(self, deposit_id: int | str) -> dict:
        deposit_id = int(deposit_id)
        published = deposit_id in self._zenodo.published
        doi = f"10.5281/zenodo.{deposit_id}"
        return {
            "id": deposit_id,
            "record_id": deposit_id,
            "conceptrecid": "6999",
            "state": "done" if published else "unsubmitted",
            "submitted": published,
            **({"doi": doi} if published else {}),
            "metadata": {"prereserve_doi": {"doi": doi}},
        }

    def create_empty_deposit(self) -> dict:
        deposit_id = 7000 + len(self._zenodo.deposits)
        self._zenodo.deposits[deposit_id] = {}
        return self._reply(deposit_id)

    def get_deposit(self, deposit_id: int | str) -> dict:
        return self._reply(deposit_id)

    def update_metadata(self, deposit_id: int | str, metadata: dict) -> dict:
        return {}

    def list_files(self, deposit_id: int | str) -> list[dict]:
        held = self._zenodo.deposits[int(deposit_id)]
        return [{"id": name, "filename": name, "checksum": f"md5:{_md5(data)}"} for name, data in held.items()]

    def delete_file(self, deposit_id: int | str, file_id: str) -> None:
        self._zenodo.deleted.append(file_id)
        del self._zenodo.deposits[int(deposit_id)][file_id]

    def upload_files(self, deposit_id: int | str, files: dict[Path, str], **kwargs: object) -> dict[Path, str]:
        for path, name in files.items():
            self._zenodo.deposits[int(deposit_id)][name] = Path(path).read_bytes()
            self._zenodo.uploaded.append(name)
        return {path: f"https://zenodo.org/api/files/{deposit_id}/{name}" for path, name in files.items()}

    def publish_deposit(self, deposit_id: int | str) -> dict:
        self._zenodo.published.add(int(deposit_id))
        return self._reply(deposit_id)


@pytest.fixture()
def zenodo(monkeypatch: pytest.MonkeyPatch) -> _Zenodo:
    fake = _Zenodo()
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", fake.client)
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    return fake


@pytest.fixture()
def no_zenodo(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Zenodo that fails the test when it is contacted."""

    def contacted(*args: object, **kwargs: object) -> None:
        raise AssertionError("Zenodo was contacted")

    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", contacted)


def _workspace(root: Path) -> AuthoringWorkspace:
    """One cell and one cycling test on run.bdf.csv, saved, with README.md, notes.txt and docs/README.md beside it."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "run.bdf.csv").write_text(CSV, encoding="utf-8")
    (root / "README.md").write_text("# Example deposit\n\nOne cycling test of one coin cell.\n", encoding="utf-8")
    (root / "notes.txt").write_text("Measured at 25 degC.\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "README.md").write_text("# The other README\n", encoding="utf-8")
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.license("cc-by-4.0")
    spec = battinfo.CellSpec(manufacturer="Example Lab", model="R2032", format="coin", chemistry="li-ion")
    ws.add("cell", spec=spec, serial_numbers=["C01"])
    ws.add("test", type="cycling", cell="C01", data="run.bdf.csv")
    ws.save()
    return ws


def _deposit(ws: AuthoringWorkspace, **kwargs: object) -> object:
    return ws.zenodo(token="placeholder", creators=CREATORS, **kwargs)


def _catalog(graph: dict) -> dict:
    return next(node for node in graph["@graph"] if "dcat:Catalog" in node["@type"])


def _documents(graph: dict) -> list[dict]:
    """The catalog's schema:hasPart entries that are files documenting the deposit."""
    return [part for part in _catalog(graph)["schema:hasPart"] if part.get("@type") == "schema:DigitalDocument"]


def _crate_files(crate: dict) -> dict[str, dict]:
    return {node["name"]: node for node in crate["@graph"] if node.get("@type") == "File"}


def _crate_root(crate: dict) -> dict:
    return next(node for node in crate["@graph"] if node.get("@id") == "./")


def _state(root: Path) -> dict | None:
    path = root / ".battinfo" / "zenodo.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _document(name: str, path: Path, files: str) -> dict:
    """The schema:DigitalDocument the catalog lists for the extra file *path*, deposited as *name*."""
    url = f"{files}/{name}"
    return {
        "@type": "schema:DigitalDocument",
        "@id": url,
        "schema:name": name,
        "schema:encodingFormat": _extra_file_media_type(name),
        "schema:contentUrl": url,
        "spdx:checksum": {
            "@type": "spdx:Checksum",
            "spdx:checksumAlgorithm": {"@id": "spdx:checksumAlgorithm_sha256"},
            "spdx:checksumValue": _sha256(path),
        },
        "dcat:byteSize": path.stat().st_size,
    }


# ── The deposit ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bundle", ["by_kind", "single"])
def test_extra_files_go_up_as_themselves_and_every_part_of_the_deposit_lists_them(
    tmp_path: Path, zenodo: _Zenodo, bundle: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(tmp_path)
    readme, notes = tmp_path / "README.md", tmp_path / "notes.txt"
    checked: list[dict] = []  # the crates the RO-Crate check before the upload reads
    monkeypatch.setattr("battinfo.ws._warn_rocrate_problems", checked.append)

    result = _deposit(
        ws, publish=True, bundle=bundle, extra_files={readme: "README.md", "notes.txt": "corrections.txt"}
    )

    assert result.published  # the check of the deposit's files before the publish passed
    [planned] = checked
    assert {"README.md", "corrections.txt"} <= set(_crate_files(planned))
    files = zenodo.files()
    assert files["README.md"] == readme.read_bytes()
    assert files["corrections.txt"] == notes.read_bytes()
    data = {"data.zip"} if bundle == "single" else {"run.bdf.csv"}
    assert set(files) == OWN_FILES | data | {"README.md", "corrections.txt"}
    if bundle == "single":  # never zipped with the data files
        downloaded = tmp_path / "downloaded.zip"
        downloaded.write_bytes(files["data.zip"])
        with zipfile.ZipFile(downloaded) as archive:
            assert archive.namelist() == ["run.bdf.csv"]

    # The state file records the names, after the publish too.
    state = _state(tmp_path)
    assert state is not None and state["published"] is True
    assert state["extra_files"] == ["README.md", "corrections.txt"]

    # The catalog lists them after the datasets, and dcat:dataset holds the datasets alone.
    graph = zenodo.graph()
    catalog = _catalog(graph)
    record_files = "https://zenodo.org/records/7000/files"
    assert _documents(graph) == [
        _document("README.md", readme, record_files),
        _document("corrections.txt", notes, record_files),
    ]
    datasets = [node["@id"] for node in graph["@graph"] if "dcat:Dataset" in node["@type"]]
    assert catalog["dcat:dataset"] == [{"@id": iri} for iri in datasets]
    assert catalog["schema:hasPart"][: len(datasets)] == catalog["dcat:dataset"]
    assert "README.md" not in json.dumps(catalog.get("schema:distribution", []))

    # The RO-Crate lists each as a File of the root dataset.
    crate = zenodo.crate()
    entities = _crate_files(crate)
    assert entities["README.md"] == {
        "@type": "File",
        "@id": "README.md",
        "name": "README.md",
        "encodingFormat": "text/markdown",
        "contentSize": str(readme.stat().st_size),
        "sha256": _sha256(readme),
    }
    assert entities["corrections.txt"]["encodingFormat"] == "text/plain"
    assert entities["corrections.txt"]["sha256"] == _sha256(notes)
    parts = [part["@id"] for part in _crate_root(crate)["hasPart"]]
    assert parts[-2:] == ["README.md", "corrections.txt"]


def test_a_rerun_keeps_an_unchanged_extra_file_and_replaces_a_changed_one(
    tmp_path: Path, zenodo: _Zenodo, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(tmp_path)
    _deposit(ws, extra_files=["README.md", "notes.txt"])  # a draft
    (tmp_path / "notes.txt").write_text("Measured at 25 degC, corrected.\n", encoding="utf-8")
    zenodo.uploaded.clear()
    zenodo.deleted.clear()
    capsys.readouterr()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _deposit(ws, extra_files=["README.md", "notes.txt"])

    assert not [w for w in caught if "extra files" in str(w.message)]  # nothing is left out
    assert len(zenodo.deposits) == 1  # the draft was updated, not a second one made
    assert "notes.txt" in zenodo.uploaded and "README.md" not in zenodo.uploaded
    assert "run.bdf.csv" not in zenodo.uploaded
    # The changed file is replaced (deleted, then uploaded); nothing is removed.
    assert "notes.txt" in zenodo.deleted and set(zenodo.deleted) <= {"notes.txt", *OWN_FILES}
    assert ", 0 removed" in capsys.readouterr().out
    files = zenodo.files()
    assert files["notes.txt"] == (tmp_path / "notes.txt").read_bytes()
    assert files["README.md"] == (tmp_path / "README.md").read_bytes()
    [notes] = [part for part in _documents(zenodo.graph()) if part["schema:name"] == "notes.txt"]
    assert notes["spdx:checksum"]["spdx:checksumValue"] == _sha256(tmp_path / "notes.txt")
    assert _crate_files(zenodo.crate())["notes.txt"]["sha256"] == _sha256(tmp_path / "notes.txt")


def test_a_rerun_without_extra_files_removes_them_and_names_them_in_a_warning(
    tmp_path: Path, zenodo: _Zenodo, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(tmp_path)
    _deposit(ws, extra_files=["README.md", "notes.txt"])
    assert _state(tmp_path)["extra_files"] == ["README.md", "notes.txt"]  # type: ignore[index]

    def left_out(caught: list[warnings.WarningMessage]) -> str:
        [warning] = [str(w.message) for w in caught if "leaves out the extra files" in str(w.message)]
        return warning

    # A run that names one of them leaves out the other, and says so. (It
    # also warns that it updates the draft.)
    with pytest.warns(UserWarning) as caught:
        _deposit(ws, extra_files=["README.md"])
    assert left_out(caught.list).startswith(
        "This deposit leaves out the extra files .battinfo/zenodo.json records from the last "
        "ws.zenodo() run: notes.txt."
    )
    assert set(zenodo.files()) == OWN_FILES | {"run.bdf.csv", "README.md"}
    assert _state(tmp_path)["extra_files"] == ["README.md"]  # type: ignore[index]

    # A run that names none removes the rest, with the warning.
    capsys.readouterr()
    with pytest.warns(UserWarning) as caught:
        _deposit(ws)
    assert "from the last ws.zenodo() run: README.md. " in left_out(caught.list)
    assert "WARNING: This deposit leaves out the extra files" in capsys.readouterr().out
    assert set(zenodo.files()) == OWN_FILES | {"run.bdf.csv"}
    assert "README.md" in zenodo.deleted
    assert "extra_files" not in _state(tmp_path)  # type: ignore[operator]
    assert _documents(zenodo.graph()) == []
    assert "README.md" not in _crate_files(zenodo.crate())

    # Once nothing is recorded, a run without extra files does not warn about them.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _deposit(ws)
    assert not [w for w in caught if "extra files" in str(w.message)]


# ── Refused before anything is sent ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("extra_files", "options", "error", "message"),
    [
        ({"notes.txt": "run.bdf.csv"}, {}, ValueError, "run.bdf.csv is the name of run.bdf.csv, a data file"),
        ({"notes.txt": "RUN.BDF.CSV"}, {}, ValueError, "RUN.BDF.CSV is the name of run.bdf.csv, a data file"),
        (
            {"notes.txt": "data.zip"},
            {"bundle": "single"},
            ValueError,
            "data.zip is the name of data.zip, an archive of the data files",
        ),
        (
            {"notes.txt": "battinfo.json"},
            {},
            ValueError,
            "battinfo.json is the name of battinfo.json, the deposit graph",
        ),
        (
            {"notes.txt": "RO-Crate-Metadata.json"},
            {},
            ValueError,
            "RO-Crate-Metadata.json is the name of ro-crate-metadata.json, the RO-Crate metadata",
        ),
        ({"notes.txt": "battinfo.jsonld"}, {}, ValueError, "the deposit graph's former name"),
        (["README.md", "docs/README.md"], {}, ValueError, "docs/README.md and README.md would both be deposited as"),
        ({"README.md": "notes.md", "notes.txt": "Notes.md"}, {}, ValueError, "would both be deposited as Notes.md"),
        ({"run.bdf.csv": "copy.csv"}, {}, ValueError, "is the data file run.bdf.csv of the deposit already"),
        ({"README.md": "a.md", "./README.md": "b.md"}, {}, ValueError, "./README.md is the file README.md already"),
        (["missing.md"], {}, ValueError, "missing.md is not a file"),
        (["docs"], {}, ValueError, "docs is not a file"),
        ({"README.md": "docs/README.md"}, {}, ValueError, "'docs/README.md', the name given for README.md, is not"),
        ({"README.md": "  "}, {}, ValueError, "'', the name given for README.md, is not a plain file name"),
        ("README.md", {}, TypeError, "not one path: pass ['README.md']"),
        (Path("README.md"), {}, TypeError, "not one path"),
        ({"README.md": 3}, {}, TypeError, "README.md maps to 3"),
        ([3], {}, TypeError, "takes each path as text or a Path, not 3"),
    ],
    ids=[
        "data-file",
        "data-file-case",
        "archive",
        "graph",
        "rocrate",
        "legacy-graph",
        "two-extras-own-names",
        "two-extras-given-names",
        "a-data-file-itself",
        "one-file-twice",
        "missing",
        "folder",
        "folder-in-name",
        "empty-name",
        "one-path-text",
        "one-path",
        "name-not-text",
        "path-not-text",
    ],
)
def test_extra_files_the_deposit_cannot_carry_are_refused_before_anything_is_sent(
    tmp_path: Path, no_zenodo: None, extra_files: object, options: dict, error: type, message: str
) -> None:
    ws = _workspace(tmp_path)
    calls = (
        lambda: _deposit(ws, extra_files=extra_files, **options),
        lambda: ws.preview_jsonld(creators=CREATORS, extra_files=extra_files, **options),
        lambda: ws.preview_rocrate(creators=CREATORS, extra_files=extra_files, **options),
    )
    for call in calls:
        with pytest.raises(error, match=re.escape(message)):
            call()
    assert _state(tmp_path) is None
    assert not (tmp_path / "battinfo.preview.jsonld").exists()
    assert not (tmp_path / "ro-crate-metadata.preview.json").exists()


# ── Zenodo's file limit ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("bundle", "held", "advice"),
    [
        ("by_kind", "1 data file", "Pass bundle='single' to zip the data files in one archive, or deposit fewer"),
        ("none", "1 data file", "Pass bundle='by_kind' to zip"),
        ("single", "1 archive of data files", "Deposit fewer extra files."),
    ],
)
def test_extra_files_count_toward_zenodos_file_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bundle: str, held: str, advice: str
) -> None:
    ws = _workspace(tmp_path)
    # One data file or archive, two extra files and the deposit's own two make five.
    monkeypatch.setattr("battinfo.ws._ZENODO_FILE_LIMIT", 4)
    counted = f"holds 5 files ({held}, 2 extra files (README.md; notes.txt), battinfo.json and ro-crate-metadata.json)"
    with pytest.warns(UserWarning, match=re.escape(counted)) as caught:
        ws.preview_jsonld(creators=CREATORS, bundle=bundle, extra_files=["README.md", "notes.txt"])
    assert advice in str(next(w.message for w in caught if "holds 5 files" in str(w.message)))

    # Within the limit, nothing warns about it.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ws.preview_jsonld(creators=CREATORS, bundle=bundle, extra_files=["README.md"])
    assert not [w for w in caught if "files in one record" in str(w.message)]


def test_the_file_limit_warning_comes_before_anything_is_sent(
    tmp_path: Path, no_zenodo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(tmp_path)
    monkeypatch.setattr("battinfo.ws._ZENODO_FILE_LIMIT", 4)
    with (
        pytest.warns(UserWarning, match=r"holds 5 files \(1 data file, 2 extra files"),
        pytest.raises(AssertionError, match="Zenodo was contacted"),
    ):
        _deposit(ws, extra_files=["README.md", "notes.txt"])


# ── The previews ──────────────────────────────────────────────────────────────


def test_the_graph_preview_lists_the_extra_files_and_passes_the_gold_standard_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(tmp_path)
    (tmp_path / "read me.md").write_text("# Spaces in the name\n", encoding="utf-8")
    without = json.loads(ws.preview_jsonld(creators=CREATORS).read_text(encoding="utf-8"))
    capsys.readouterr()

    graph = json.loads(
        ws.preview_jsonld(creators=CREATORS, extra_files=["read me.md", "notes.txt"]).read_text(encoding="utf-8")
    )

    out = capsys.readouterr().out
    assert "Gold-standard: PASS" in out and "Extra files: 2" in out
    errors = [i.message for i in validate_publication_report(graph, policy="publisher").issues if i.severity == "error"]
    assert errors == []
    readme = _document("read me.md", tmp_path / "read me.md", PLACEHOLDER_FILES)
    readme["@id"] = readme["schema:contentUrl"] = f"{PLACEHOLDER_FILES}/read%20me.md"
    assert _documents(graph) == [readme, _document("notes.txt", tmp_path / "notes.txt", PLACEHOLDER_FILES)]
    catalog, before = _catalog(graph), _catalog(without)
    assert catalog["dcat:dataset"] == before["dcat:dataset"] == before["schema:hasPart"]
    assert catalog["schema:hasPart"] == before["schema:hasPart"] + _documents(graph)
    assert catalog.get("schema:distribution") == before.get("schema:distribution")
    # Nothing else in the graph changes.
    assert [node for node in graph["@graph"] if node is not catalog] == [
        node for node in without["@graph"] if node is not before
    ]


def test_the_rocrate_preview_lists_the_extra_files_and_validates(tmp_path: Path) -> None:
    pytest.importorskip("rocrate")
    ws = _workspace(tmp_path)
    (tmp_path / "read me.md").write_text("# Spaces in the name\n", encoding="utf-8")

    out = ws.preview_rocrate(creators=CREATORS, bundle="single", extra_files={"read me.md": "read me.md"})

    crate = json.loads(out.read_text(encoding="utf-8"))
    entities = _crate_files(crate)
    assert set(entities) == {"data.zip", "read me.md"}
    assert entities["read me.md"] == {
        "@type": "File",
        "@id": "read%20me.md",
        "name": "read me.md",
        "encodingFormat": "text/markdown",
        "contentSize": str((tmp_path / "read me.md").stat().st_size),
        "sha256": _sha256(tmp_path / "read me.md"),
    }
    assert [part["@id"] for part in _crate_root(crate)["hasPart"]] == ["battinfo.json", "data.zip", "read%20me.md"]
    assert ws.validate_rocrate(out) is True


def test_a_deposit_graph_with_extra_files_imports_as_one_without_them(tmp_path: Path) -> None:
    ws = _workspace(tmp_path / "source")
    plain = ws.preview_jsonld(tmp_path / "plain.jsonld", creators=CREATORS)
    documented = ws.preview_jsonld(tmp_path / "documented.jsonld", creators=CREATORS, extra_files=["README.md"])

    imported = [
        AuthoringWorkspace(root=tmp_path / name, registry_url=None).import_(str(path))
        for name, path in (("a", plain), ("b", documented))
    ]
    assert imported[0] == imported[1]
    assert imported[1]["datasets"] == 1


# ── Pieces ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "media_type"),
    [
        ("README.md", "text/markdown"),
        ("sha256sums.txt", "text/plain"),
        ("NOTES.TXT", "text/plain"),
        ("summary.csv", "text/csv"),  # not what the Windows registry says
        ("datasets.json", "application/json"),
        ("paper.pdf", "application/pdf"),
        ("table.parquet", "application/vnd.apache.parquet"),
        ("blob.unknown-extension", "application/octet-stream"),
    ],
)
def test_an_extra_files_media_type_comes_from_its_extension(name: str, media_type: str) -> None:
    assert _extra_file_media_type(name) == media_type


def test_a_state_file_whose_extra_files_is_not_a_list_of_names_cannot_be_read(tmp_path: Path) -> None:
    path = tmp_path / ".battinfo" / "zenodo.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"record_id": "7000", "extra_files": "README.md"}), encoding="utf-8")
    with pytest.raises(DepositIndexError, match="its 'extra_files' is not a list of file names"):
        load_deposit_state(tmp_path)
