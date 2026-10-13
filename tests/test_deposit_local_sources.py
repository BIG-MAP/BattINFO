"""A deposit reads only the local files it may, and ws.import_() lets in no local path.

- One parser reads every ``file:`` URI: it keeps a network host
  (``file://server/share/x`` and ``file:////server/share/x``), drops
  ``localhost``, and drops the ``/`` in front of a drive letter.
- A deposit screens each data file location from its text before anything
  asks the file system about it. A network path outside the workspace folder
  that the workspace did not register, and a path that goes up a folder with
  ``..``, are never looked up, and the record that names one stops the
  deposit. A workspace kept on a network share deposits its own files.
- ``ws.add(..., data=...)`` and ``ws.convert()`` register their files in
  ``.battinfo/deposit-files.json``, so a file outside the workspace folder is
  deposited.
- ``ws.import_()`` reads a document that may come from anyone: it keeps only
  http(s) download URLs, reads only http(s) URLs, and sends a Zenodo token
  only over https to the Zenodo API host, never to another host and never on
  a redirect.

All offline: Zenodo, R2 and the web are faked, and no network share is needed.
"""
from __future__ import annotations

import copy
import email.message
import hashlib
import io
import json
import sys
import types
import urllib.request
import urllib.response
import warnings
from collections.abc import Callable
from pathlib import Path, PureWindowsPath

import pytest

import battinfo
from battinfo._deposit_files import UnsafeLocation, build_deposit_file_plan, location_path
from battinfo._deposit_index import DepositIndexError
from battinfo._util import file_uri_to_path, lexical_key, local_file_references, local_path
from battinfo.publication import check_artifact_conformance, plan_artifact_inclusion
from battinfo.ws import AuthoringWorkspace, _import_resolve_source

CREATORS = [{"name": "Doe, Jane"}]
CSV = "test_time_second,voltage_volt,current_ampere\n0,3.0,0\n60,3.5,0.001\n"
RECORD_URL = "https://zenodo.org/records/1"
HOST = "attacker.invalid"
TOKEN = "SECRET-TOKEN"


class _FakeZenodo:
    """Stands in for ZenodoClient: logs each call and keeps each uploaded file's bytes by name."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.uploaded: dict[str, bytes] = {}

    def client(self, *args: object, **kwargs: object) -> _FakeZenodo:
        return self

    def create_empty_deposit(self) -> dict:
        self.calls.append("create")
        return {"id": 7, "record_id": 7, "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.7"}}}

    def update_metadata(self, deposit_id: int, metadata: dict) -> dict:
        self.calls.append("metadata")
        return {}

    def sync_files(self, deposit_id: int, upload_map: dict) -> dict:
        self.calls.append("sync")
        self.uploaded = {name: Path(path).read_bytes() for path, name in upload_map.items()}
        return {"uploaded": sorted(self.uploaded), "kept": [], "removed": []}

    def list_files(self, deposit_id: int) -> list[dict]:
        return [
            {"filename": name, "checksum": hashlib.md5(data).hexdigest()}  # noqa: S324 - Zenodo's checksum
            for name, data in self.uploaded.items()
        ]

    def publish_deposit(self, deposit_id: int) -> dict:
        self.calls.append("publish")
        return {"doi": "10.5281/zenodo.7"}

    def data_names(self) -> list[str]:
        return sorted(set(self.uploaded) - {"battinfo.json", "ro-crate-metadata.json"})


@pytest.fixture()
def zenodo(monkeypatch: pytest.MonkeyPatch) -> _FakeZenodo:
    fake = _FakeZenodo()
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", fake.client)
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    return fake


def _watch(monkeypatch: pytest.MonkeyPatch, marker: str = HOST) -> list[str]:
    """Every question pathlib is asked about a path that holds *marker*.

    Each such question is logged and refused, so a test can check that no
    code asked the file system about the path, even code that swallows the
    error.
    """
    asked: list[str] = []
    for name in ("stat", "lstat", "exists", "is_file", "is_dir", "resolve", "open", "read_bytes", "read_text"):
        original = getattr(Path, name)

        def guard(self: Path, *args: object, _original: Callable = original, _name: str = name, **kwargs: object):
            if marker in str(self).replace("\\", "/").lower():
                asked.append(f"{_name}({self})")
                raise AssertionError(f"the file system was asked about {self}")
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(Path, name, guard)
    return asked


def _workspace(root: Path, files: dict[str, Path | str]) -> AuthoringWorkspace:
    """A saved workspace with one cell and one cycling test for each entry of *files*.

    *files* maps a serial number to the test's data file, a path inside
    *root* or an absolute path anywhere. Each file ends with its serial
    number, so no two hold the same bytes.
    """
    root.mkdir(parents=True, exist_ok=True)
    for serial, relative in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{CSV}# {serial}\n", encoding="utf-8")
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.license("cc-by-4.0")
    spec = battinfo.CellSpec(manufacturer="Example Lab", model="R2032", format="coin", chemistry="li-ion")
    ws.add("cell", spec=spec, serial_numbers=list(files))
    for serial, relative in files.items():
        ws.add("test", type="cycling", cell=serial, data=relative)
    ws.save()
    return ws


def _saved(ws: AuthoringWorkspace, folder: str) -> list[tuple[Path, dict]]:
    directory = ws._ws.source_root / folder
    return [(path, json.loads(path.read_text(encoding="utf-8"))) for path in sorted(directory.glob("*.json"))]


def _point_dataset_at(ws: AuthoringWorkspace, location: str) -> str:
    """Point the first saved dataset's data file at *location*, as a hand edit would; return its IRI."""
    path, record = _saved(ws, "dataset")[0]
    record["dataset"]["distributions"][0]["content_url"] = location
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record["dataset"]["id"]


def _index(root: Path) -> dict:
    return json.loads((root / ".battinfo" / "deposit-files.json").read_text(encoding="utf-8"))


# ── One parser for file: URIs ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("uri", "text"),
    [
        ("file://server/share/run1.csv", "//server/share/run1.csv"),
        ("file:////server/share/run1.csv", "//server/share/run1.csv"),
        ("file://///server/share/run1.csv", "//server/share/run1.csv"),
        ("file://localhost/C:/data/run1.csv", "C:/data/run1.csv"),
        ("file://LOCALHOST/C:/data/run1.csv", "C:/data/run1.csv"),
        ("file:///C:/data/run%201.csv", "C:/data/run 1.csv"),
        ("file://C:/data/run1.csv", "C:/data/run1.csv"),
        ("file:///C|/data/run1.csv", "C:/data/run1.csv"),
        ("file:///srv/data/run1.csv", "/srv/data/run1.csv"),
        ("file://localhost/srv/data/run1.csv", "/srv/data/run1.csv"),
    ],
)
def test_one_parser_reads_every_file_uri(uri: str, text: str) -> None:
    from battinfo import _workspace, publication, workspace_state
    from battinfo._util import _file_uri_path_text

    assert _file_uri_path_text(uri) == text
    # Every reader of file: URIs agrees: the workspace's, the one record
    # locations and identity seeds use, and the three local copies it replaced.
    assert file_uri_to_path(uri) == Path(text)
    assert local_path(uri) == Path(text)
    for module in (publication, _workspace, workspace_state):
        assert module._path_from_file_uri(uri) == Path(text)


def test_a_network_host_stays_a_network_path() -> None:
    from battinfo._util import _file_uri_path_text

    for uri in ("file://server/share/run1.csv", "file:////server/share/run1.csv"):
        path = PureWindowsPath(_file_uri_path_text(uri))
        assert (path.drive, path.name) == ("\\\\server\\share", "run1.csv")
    assert PureWindowsPath(_file_uri_path_text("file://localhost/C:/data/run1.csv")).drive == "C:"


# ── The screen ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "location",
    [
        f"file://{HOST}/share/data.csv",
        f"file:////{HOST}/share/data.csv",
        f"file://localhost//{HOST}/share/data.csv",
        f"//{HOST}/share/data.csv",
        f"\\\\{HOST}\\share\\data.csv",
        f"file:///%5C%5C{HOST}%5Cshare%5Cdata.csv",
    ],
)
def test_the_screen_refuses_a_file_on_another_computer(tmp_path: Path, location: str) -> None:
    with pytest.raises(UnsafeLocation) as excinfo:
        location_path(location, tmp_path)
    assert excinfo.value.host == HOST
    assert excinfo.value.refusal() == (
        f"its data file {location} is on another computer ({HOST!r}) and was not added to this "
        "workspace with ws.add(..., data=...), so it was not read"
    )


@pytest.mark.parametrize("location", ["../outside.csv", "data/../../outside.csv", "file:///srv/lab/../etc/data.csv"])
def test_the_screen_refuses_a_path_that_goes_up_a_folder(tmp_path: Path, location: str) -> None:
    with pytest.raises(UnsafeLocation, match="goes up a folder with '..'") as excinfo:
        location_path(location, tmp_path)
    assert excinfo.value.host == ""


def test_the_screen_lets_through_what_the_workspace_may_read(tmp_path: Path) -> None:
    outside = tmp_path.parent / "cycler-exports" / "C01.csv"
    assert location_path(outside.as_uri(), tmp_path) == outside          # this computer, outside the folder
    assert location_path("bdf/C01.bdf.csv", tmp_path) == tmp_path / "bdf" / "C01.bdf.csv"
    assert location_path("https://zenodo.org/records/1/files/C01.csv", tmp_path) is None
    # A file on a lab share that ws.add() registered.
    share = Path("//lab/exports/C01.csv")
    assert location_path("file://lab/exports/C01.csv", tmp_path, registered={lexical_key(share)}) == share


def test_the_plan_never_asks_about_a_location_the_screen_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inside = tmp_path / "C01.csv"
    inside.write_text(CSV, encoding="utf-8")
    refused = {
        f"file://{HOST}/share/data.csv": "https://w3id.org/battinfo/dataset/aaaa-aaaa-aaaa-aaaa",
        f"file:////{HOST}/share/more.csv": "https://w3id.org/battinfo/dataset/bbbb-bbbb-bbbb-bbbb",
        "../outside.csv": "https://w3id.org/battinfo/dataset/cccc-cccc-cccc-cccc",
    }
    asked = _watch(monkeypatch)
    plan = build_deposit_file_plan(
        [(inside.as_uri(), "cycling"), *((location, "cycling") for location in refused)],
        root=tmp_path,
        owners=refused,
    )

    assert [entry.path for entry in plan.files] == [inside.resolve()]
    assert plan.missing == []
    assert [(o.kind, o.record) for o in plan.omissions] == [("dataset", iri) for iri in refused.values()]
    assert plan.omissions[0].reason.startswith(f"its data file file://{HOST}/share/data.csv is on another computer")
    assert plan.omissions[2].reason == "its data file ../outside.csv goes up a folder with '..', so it was not read"
    for location in refused:
        assert plan.entry_for(location) is None
    assert plan.entry_for(f"\\\\{HOST}\\share\\other.csv") is None
    assert asked == []


def test_a_workspace_on_a_network_share_deposits_its_own_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """A workspace opened on a mapped drive resolves to a network path, and so do its records."""
    import battinfo._deposit_files as deposit_files

    root = Path("//server/share/lab")
    present = {lexical_key(root / "C01.csv"), lexical_key(root / "bdf" / "C02.bdf.csv"),
               lexical_key(Path("//lab/exports/C03.csv"))}
    is_file = Path.is_file

    def fake_is_file(self: Path) -> bool:
        # The share exists only in this test: answer for it without the network.
        if str(self).replace("\\", "/").startswith("//"):
            return lexical_key(self) in present
        return is_file(self)

    monkeypatch.setattr(Path, "is_file", fake_is_file)
    monkeypatch.setattr(deposit_files, "_resolved", lambda path: path)
    plan = build_deposit_file_plan(
        [
            ("file://server/share/lab/C01.csv", "cycling"),
            ("file://server/share/lab/bdf/C02.bdf.csv", "cycling"),
            ("file://lab/exports/C03.csv", "cycling"),        # on another share, registered
            ("file://server/share/elsewhere/C04.csv", "cycling"),   # on the same server, outside the folder
        ],
        root=root,
        measure=False,
        registered={lexical_key(Path("//lab/exports/C03.csv"))},
        owners={"file://server/share/elsewhere/C04.csv": "https://w3id.org/battinfo/dataset/dddd-dddd-dddd-dddd"},
    )

    assert [entry.name for entry in plan.files] == ["C01.csv", "C02.bdf.csv", "C03.csv"]
    assert plan.entry_for("file://server/share/lab/C01.csv") is plan.files[0]
    [omission] = plan.omissions
    assert omission.record == "https://w3id.org/battinfo/dataset/dddd-dddd-dddd-dddd"
    assert "is on another computer ('server')" in omission.reason


# ── Files the workspace registers ─────────────────────────────────────────────


def test_a_data_file_outside_the_workspace_is_registered_and_deposited(tmp_path: Path, zenodo: _FakeZenodo) -> None:
    outside = tmp_path / "cycler-exports" / "C01.csv"
    raw = tmp_path / "cycler-exports" / "C01.ndax"
    outside.parent.mkdir()
    outside.write_text(CSV, encoding="utf-8")
    raw.write_bytes(b"raw cycler file")
    root = tmp_path / "lab"
    root.mkdir()
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.license("cc-by-4.0")
    spec = battinfo.CellSpec(manufacturer="Example Lab", model="R2032", format="coin", chemistry="li-ion")
    ws.add("cell", spec=spec, serial_numbers=["C01"])
    ws.add("test", type="cycling", cell="C01", data=outside, raw=raw)
    ws.save()

    assert _index(root)["sources"] == {
        str(outside.resolve()): {"registered_by": "ws.add"},
        str(raw.resolve()): {"registered_by": "ws.add"},
    }
    ws.zenodo(token="placeholder", creators=CREATORS)
    assert zenodo.data_names() == ["C01.csv", "C01.ndax"]
    assert zenodo.uploaded["C01.csv"] == outside.read_bytes()
    assert zenodo.uploaded["C01.ndax"] == raw.read_bytes()


def test_a_conversion_registers_its_source_and_its_output(tmp_path: Path) -> None:
    source, output = tmp_path / "exports" / "C01.ndax", tmp_path / "lab" / "bdf" / "C01.bdf.csv"
    for path in (source, output):
        path.parent.mkdir(parents=True)
        path.write_text("x", encoding="utf-8")
    ws = AuthoringWorkspace(root=tmp_path / "lab", registry_url=None)
    ws._record_conversion(source, output)
    assert _index(tmp_path / "lab")["sources"] == {
        str(source.resolve()): {"registered_by": "ws.convert"},
        str(output.resolve()): {"registered_by": "ws.convert"},
    }
    assert lexical_key(source.resolve()) in ws._registered_sources()


def test_the_index_keeps_what_it_does_not_know(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, {"C01": "C01.csv"})
    path = tmp_path / ".battinfo" / "deposit-files.json"
    index = _index(tmp_path)
    index["deposits"] = [{"name": "C01.csv"}]
    path.write_text(json.dumps(index), encoding="utf-8")
    (tmp_path / "C02.csv").write_text(CSV, encoding="utf-8")
    ws.add("test", type="cycling", cell="C01", data="C02.csv")
    assert _index(tmp_path)["deposits"] == [{"name": "C01.csv"}]
    assert str((tmp_path / "C02.csv").resolve()) in _index(tmp_path)["sources"]


@pytest.mark.parametrize("content", ["{not json", "[]", '{"sources": []}'], ids=["not-json", "list", "sources-list"])
def test_an_index_that_cannot_be_read_is_never_written_over(
    tmp_path: Path, zenodo: _FakeZenodo, content: str
) -> None:
    ws = _workspace(tmp_path, {"C01": "C01.csv"})
    path = tmp_path / ".battinfo" / "deposit-files.json"
    path.write_text(content, encoding="utf-8")
    tests_before = len(ws._ws.tests)

    with pytest.raises(DepositIndexError, match="deposit-files.json cannot be read") as excinfo:
        ws.add("test", type="cycling", cell="C01", data="C01.csv")
    assert "it was left as it is" in str(excinfo.value)
    assert len(ws._ws.tests) == tests_before   # refused before anything was made
    with pytest.raises(DepositIndexError):
        ws.zenodo(token="placeholder", creators=CREATORS)
    assert zenodo.calls == []
    assert path.read_text(encoding="utf-8") == content


# ── A deposit and a record that names a file it may not read ──────────────────


@pytest.mark.parametrize("publish", [False, True], ids=["draft", "publish"])
def test_a_record_that_names_a_file_on_another_computer_stops_the_deposit(
    tmp_path: Path, zenodo: _FakeZenodo, monkeypatch: pytest.MonkeyPatch, publish: bool
) -> None:
    ws = _workspace(tmp_path, {"C01": "C01.csv", "C02": "C02.csv"})
    location = f"file://{HOST}/share/data.csv"
    dataset_iri = _point_dataset_at(ws, location)
    asked = _watch(monkeypatch)

    with pytest.raises(RuntimeError) as excinfo:
        ws.zenodo(token="placeholder", creators=CREATORS, publish=publish)

    message = str(excinfo.value)
    assert message.startswith(f"Refusing to {'publish' if publish else 'deposit'}: 1 record(s) would go into the deposit incomplete: ")
    assert f"dataset {dataset_iri}: its data file {location} is on another computer ({HOST!r})" in message
    assert message.endswith("Nothing was sent to Zenodo.")
    assert zenodo.calls == [] and asked == []


def test_the_preview_lists_a_file_the_deposit_may_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(tmp_path, {"C01": "C01.csv", "C02": "C02.csv"})
    dataset_iri = _point_dataset_at(ws, f"file:////{HOST}/share/data.csv")
    asked = _watch(monkeypatch)
    capsys.readouterr()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ws.preview_jsonld(creators=CREATORS)

    out = capsys.readouterr().out
    assert f"ERROR   left out of the deposit: dataset {dataset_iri}: its data file file:////{HOST}/share" in out
    assert asked == []


def test_r2_upload_reads_no_file_the_screen_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    uploaded: dict[str, str] = {}

    class _S3:
        class exceptions:  # noqa: N801 - mirrors boto3's client.exceptions
            class ClientError(Exception):
                pass

        def head_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803
            if Key not in uploaded:
                raise self.exceptions.ClientError(Key)
            return {"Metadata": {"sha256": uploaded[Key]}}

        def upload_file(self, filename: str, bucket: str, key: str, ExtraArgs: dict, Config: object) -> None:  # noqa: N803
            uploaded[key] = ExtraArgs["Metadata"]["sha256"]

    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *args, **kwargs: _S3()  # type: ignore[attr-defined]
    transfer = types.ModuleType("boto3.s3.transfer")
    transfer.TransferConfig = lambda **kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "boto3.s3", types.ModuleType("boto3.s3"))
    monkeypatch.setitem(sys.modules, "boto3.s3.transfer", transfer)
    for name, value in (("R2_ENDPOINT", "https://r2.example"), ("R2_ACCESS_KEY_ID", "k"),
                        ("R2_SECRET_ACCESS_KEY", "s"), ("R2_BUCKET", "b"),
                        ("R2_PUBLIC_BASE_URL", "https://pub.example")):
        monkeypatch.setenv(name, value)
    ws = _workspace(tmp_path, {"C01": "C01.csv", "C02": "C02.csv"})
    location = f"file://{HOST}/share/C01.csv"
    dataset_iri = _point_dataset_at(ws, location)
    asked = _watch(monkeypatch)

    ws.upload()

    assert asked == []
    assert len(uploaded) == 1   # the other dataset's own file
    out = capsys.readouterr().out
    assert f"WARNING: dataset {dataset_iri}: its data file {location} is on another computer" in out


# ── Artifacts ─────────────────────────────────────────────────────────────────


def test_artifact_locators_are_read_by_the_same_parser_and_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    protocol = tmp_path / "protocols" / "cycling.json"
    protocol.parent.mkdir()
    protocol.write_text("{}", encoding="utf-8")
    records = [{"artifacts": [
        # A file: URI of a file in the workspace (on Windows its /C: used to be misread).
        {"locator": protocol.as_uri(), "format": "aurora-unicycler-json"},
        {"locator": f"file://{HOST}/share/protocol.json", "format": "aurora-unicycler-json"},
        {"locator": "../protocol.json", "format": "aurora-unicycler-json"},
    ]}]
    asked = _watch(monkeypatch)

    included, notes = plan_artifact_inclusion(records, tmp_path)

    assert included == [protocol]
    assert len(notes) == 2
    assert f"is on another computer ({HOST!r}), so it was not read" in notes[0]
    assert "goes up a folder with '..', so it was not read" in notes[1]
    assert check_artifact_conformance({"artifacts": records[0]["artifacts"][1:]}, tmp_path) == []
    assert asked == []


# ── ws.import_(): the document may come from anyone ─────────────────────────


@pytest.fixture()
def deposit(tmp_path: Path) -> dict:
    """The deposit graph of a workspace with two cycling tests, each with one data file."""
    ws = _workspace(tmp_path / "source", {"C01": "C01.csv", "C02": "C02.csv"})
    return ws._build_zenodo_jsonld(
        zenodo_record_id=1, prereserved_doi="10.5281/zenodo.1", record_url=RECORD_URL,
        data_filenames=["C01.csv", "C02.csv"], title="Round trip", creators=CREATORS,
    )


def _members(graph: dict) -> list[dict]:
    return sorted(
        (node for node in graph["@graph"] if "dcat:Dataset" in (node.get("@type") or [])),
        key=lambda node: node["dcat:distribution"][0]["schema:name"],
    )


def _import(tmp_path: Path, graph: dict) -> tuple[AuthoringWorkspace, dict]:
    path = tmp_path / "battinfo.json"
    path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    ws = AuthoringWorkspace(root=tmp_path / "imported", registry_url=None)
    counts = ws.import_(str(path))
    assert ws.save()["index"]["failures"] == []
    return ws, counts


def test_an_imported_deposit_brings_no_local_path_into_the_workspace(
    tmp_path: Path, deposit: dict, zenodo: _FakeZenodo, monkeypatch: pytest.MonkeyPatch
) -> None:
    private = tmp_path / "private" / "unpublished.csv"
    private.parent.mkdir()
    private.write_text("secret", encoding="utf-8")
    graph = copy.deepcopy(deposit)
    c01, c02 = _members(graph)
    c01["dcat:distribution"][0]["dcat:downloadURL"] = private.as_uri()
    c02["dcat:distribution"][0]["dcat:downloadURL"] = f"file:////{HOST}/share/data.csv"

    with pytest.warns(UserWarning, match="Left out the download URL") as record:
        ws, counts = _import(tmp_path, graph)

    assert len([w for w in record if "Left out the download URL" in str(w.message)]) == 2
    assert (counts["tests"], counts["datasets"], counts["skipped"]["datasets"]) == (2, 2, [])
    datasets = {record["dataset"]["id"]: record for _path, record in _saved(ws, "dataset")}
    for node, left_out in ((c01, private.as_uri()), (c02, f"file:////{HOST}/share/data.csv")):
        saved = datasets[node["@id"]]
        # Kept, at the deposit's page, without a file, and its notes say why.
        assert local_file_references(saved) == []
        assert saved["dataset"]["access_url"] == RECORD_URL
        assert "distributions" not in saved["dataset"]
        assert any(left_out in note for note in saved["notes"])
    # A deposit of the imported workspace reads neither file.
    asked = _watch(monkeypatch, HOST)
    asked_private = _watch(monkeypatch, "unpublished")
    plan = ws._deposit_file_plan(ws._ws.source_root, report=False)
    assert plan.files == [] and plan.missing == [] and plan.omissions == []
    try:
        ws.zenodo(token="placeholder", creators=CREATORS)
    except RuntimeError:
        pass   # a dataset without a file may fail the publication check; nothing is read either way
    assert zenodo.data_names() == []
    assert asked == [] and asked_private == []


def test_an_imported_dataset_keeps_its_http_file_and_drops_a_local_one(tmp_path: Path, deposit: dict) -> None:
    graph = copy.deepcopy(deposit)
    c01, _c02 = _members(graph)
    [dist] = c01["dcat:distribution"]
    c01["dcat:distribution"] = [
        {**dist, "dcat:downloadURL": "file:///C:/Users/someone/raw.ndax", "schema:name": "raw.ndax"},
        dist,
    ]

    with pytest.warns(UserWarning, match="raw.ndax"):
        ws, counts = _import(tmp_path, graph)

    assert counts["datasets"] == 2
    saved = {record["dataset"]["id"]: record for _path, record in _saved(ws, "dataset")}[c01["@id"]]
    [kept] = saved["dataset"]["distributions"]
    assert kept["content_url"] == f"{RECORD_URL}/files/C01.csv"
    assert local_file_references(saved) == []


def test_an_imported_dataset_notes_every_url_it_left_out(tmp_path: Path, deposit: dict) -> None:
    graph = copy.deepcopy(deposit)
    c01, _c02 = _members(graph)
    [dist] = c01["dcat:distribution"]
    c01["dcat:distribution"] = [
        {**dist, "dcat:downloadURL": "file:///C:/data/C01.csv"},
        {**dist, "dcat:downloadURL": {"@id": f"file://{HOST}/share/C01.ndax"}},
    ]

    with pytest.warns(UserWarning, match="Left out the download URL"):
        ws, _counts = _import(tmp_path, graph)

    saved = {record["dataset"]["id"]: record for _path, record in _saved(ws, "dataset")}[c01["@id"]]
    assert saved["dataset"]["access_url"] == RECORD_URL
    assert saved["notes"] == [
        "Imported without a file: the deposit gave the download URLs 'file:///C:/data/C01.csv', "
        f"'file://{HOST}/share/C01.ndax', which ws.import_() does not keep, as they are not http(s) URLs."
    ]


def test_an_imported_dataset_with_no_http_page_is_skipped(tmp_path: Path, deposit: dict) -> None:
    graph = copy.deepcopy(deposit)
    c01, _c02 = _members(graph)
    c01["dcat:distribution"][0]["dcat:downloadURL"] = f"\\\\{HOST}\\share\\data.csv"
    c01["dcterms:isPartOf"] = {"@id": "file:///C:/deposits/1"}
    c01.pop("schema:url", None)

    with pytest.warns(UserWarning, match="Left out the download URL"):
        ws, counts = _import(tmp_path, graph)

    assert counts["datasets"] == 1
    [skipped] = counts["skipped"]["datasets"]
    assert (skipped["dataset"], skipped["reason"]) == (c01["@id"], "no http(s) download URL")
    for _path, record in _saved(ws, "dataset"):
        assert local_file_references(record) == []


# ── ws.import_(): URLs and the Zenodo token ───────────────────────────────────


class _FakeWeb(urllib.request.BaseHandler):
    """Answers http and https requests from a table, and logs each with its Authorization header.

    It runs before urllib's own handlers, which are never reached, so no
    socket is opened; redirects are followed by urllib's redirect handler.
    """

    handler_order = 50

    def __init__(self, routes: dict[str, tuple[int, object]]) -> None:
        self.routes = routes
        self.sent: list[tuple[str, str | None]] = []

    def _answer(self, request: urllib.request.Request) -> urllib.response.addinfourl:
        url = request.full_url
        self.sent.append((url, dict(request.header_items()).get("Authorization")))
        status, payload = self.routes[url]
        headers = email.message.Message()
        if 300 <= status < 400:
            headers["Location"] = str(payload)
            body = b""
        else:
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        response = urllib.response.addinfourl(io.BytesIO(body), headers, url, status)
        response.msg = "Found" if 300 <= status < 400 else "OK"  # type: ignore[attr-defined]
        return response

    https_open = _answer
    http_open = _answer


@pytest.fixture()
def web(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, tuple[int, object]]], _FakeWeb]:
    def install(routes: dict[str, tuple[int, object]]) -> _FakeWeb:
        fake = _FakeWeb(routes)
        # No proxy from the environment: every request reaches the fake.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), fake)
        monkeypatch.setattr(urllib.request, "_opener", opener)
        return fake

    return install


GRAPH = {"@context": {}, "@graph": []}
LISTING = "https://zenodo.org/api/records/7/files"
CONTENT = "https://zenodo.org/api/records/7/files/battinfo.json/content"


def _listing(link: str) -> dict:
    return {"entries": [{"key": "battinfo.json", "links": {"content": link}}]}


def test_the_token_goes_to_the_zenodo_api_host(tmp_path: Path, web: Callable) -> None:
    fake = web({LISTING: (200, _listing(CONTENT)), CONTENT: (200, GRAPH)})
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ws.import_("7", token=TOKEN)
    # The file list, and the file on the same host (a private record's file needs it).
    assert fake.sent == [(LISTING, f"Bearer {TOKEN}"), (CONTENT, f"Bearer {TOKEN}")]


def test_the_sandbox_token_goes_to_the_sandbox_host(web: Callable) -> None:
    listing = "https://sandbox.zenodo.org/api/records/7/files"
    content = "https://sandbox.zenodo.org/api/records/7/files/battinfo.json/content"
    fake = web({listing: (200, _listing(content)), content: (200, GRAPH)})
    _import_resolve_source("7", sandbox=True, token=TOKEN)
    assert fake.sent == [(listing, f"Bearer {TOKEN}"), (content, f"Bearer {TOKEN}")]


def test_the_token_is_not_sent_to_a_file_link_on_another_host(web: Callable) -> None:
    elsewhere = "https://files.example.org/7/battinfo.json"
    fake = web({LISTING: (200, _listing(elsewhere)), elsewhere: (200, GRAPH)})
    with pytest.warns(UserWarning, match="token was not sent to https://files.example.org"):
        _import_resolve_source("7", token=TOKEN)
    assert fake.sent == [(LISTING, f"Bearer {TOKEN}"), (elsewhere, None)]


@pytest.mark.parametrize(
    "target",
    ["https://elsewhere.example.org/api/records/7/files", "https://zenodo.org/api/records/7/files/"],
    ids=["another-host", "same-host"],
)
def test_the_token_is_not_sent_on_a_redirect(web: Callable, target: str) -> None:
    fake = web({LISTING: (302, target), target: (200, _listing(CONTENT)), CONTENT: (200, GRAPH)})
    _import_resolve_source("7", token=TOKEN)
    # urllib copies the other headers onto the redirected request, never the token.
    assert fake.sent[:2] == [(LISTING, f"Bearer {TOKEN}"), (target, None)]


@pytest.mark.parametrize(
    ("url", "sandbox"),
    [
        ("http://zenodo.org/records/7/files/battinfo.json", False),
        ("https://example.org/battinfo.json", False),
        ("https://zenodo.org.example.org/battinfo.json", False),
        ("https://zenodo.org:8443/records/7/files/battinfo.json", False),
        ("https://sandbox.zenodo.org/records/7/files/battinfo.json", False),
        ("https://zenodo.org/records/7/files/battinfo.json", True),
    ],
    ids=["plain-http", "another-host", "lookalike-host", "another-port", "sandbox-for-production", "production-for-sandbox"],
)
def test_a_url_gets_the_token_only_on_the_chosen_api_host(web: Callable, url: str, sandbox: bool) -> None:
    fake = web({url: (200, GRAPH)})
    with pytest.warns(UserWarning, match="token was not sent"):
        _import_resolve_source(url, sandbox=sandbox, token=TOKEN)
    assert fake.sent == [(url, None)]


def test_a_url_on_the_api_host_gets_the_token(web: Callable) -> None:
    url = "https://zenodo.org/records/7/files/battinfo.json?download=1"
    fake = web({url: (200, GRAPH)})
    _import_resolve_source(url, token=TOKEN)
    assert fake.sent == [(url, f"Bearer {TOKEN}")]


@pytest.mark.parametrize(
    "source",
    ["ftp://example.org/battinfo.json", "file:///srv/deposits/battinfo.json", f"smb://{HOST}/share/battinfo.json"],
)
def test_an_import_url_that_is_not_http_is_refused(tmp_path: Path, web: Callable, source: str) -> None:
    fake = web({})
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with pytest.raises(ValueError, match="reads only http and https URLs"):
        ws.import_(source)
    assert fake.sent == []


def test_a_zenodo_file_link_that_is_not_http_is_never_read(tmp_path: Path, web: Callable) -> None:
    private = tmp_path / "private.json"
    private.write_text(json.dumps({**GRAPH, "secret": True}), encoding="utf-8")
    for link in (str(private), private.as_uri(), f"file:////{HOST}/share/battinfo.json"):
        web({LISTING: (200, _listing(link))})
        with pytest.raises(RuntimeError, match=r"which is not an http\(s\) URL, so nothing was read from it"):
            _import_resolve_source("7", token=TOKEN)
