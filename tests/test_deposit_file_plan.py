"""A Zenodo deposit plans its data files before it sends anything.

Each local file is one entry in the plan, named once, and every part of the
deposit takes that name: the upload, the zip archives of a large deposit, the
deposit graph, the RO-Crate and the rewrite of the dataset records. A record
finds its file by its resolved path, never by its name.

- Two files that share a name, or whose names differ only in case or Unicode
  normalisation, are two files in the deposit, in each dataset's own links.
- A file that two distributions name is uploaded once.
- A data file never takes the name of the deposit's own metadata files.
- A file name with a space, ``#``, ``?``, ``%`` or a non-ASCII character is
  percent-encoded in every URL, and an upload the HTTP layer refuses is a
  ZenodoError that names the file.

All offline: Zenodo and R2 are faked.
"""

from __future__ import annotations

import hashlib
import http.client
import io
import json
import re
import sys
import types
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import pytest

import battinfo
from battinfo import zenodo as zmod
from battinfo.ws import AuthoringWorkspace
from battinfo.zenodo import ZenodoClient, ZenodoError

pytestmark = pytest.mark.usefixtures("registry_holds_none")  # deposits ask the registry first (#483)

CREATORS = [{"name": "Doe, Jane"}]
CSV = "test_time_second,voltage_volt,current_ampere\n0,3.0,0\n60,3.5,0.001\n"
RECORD_URL = "https://zenodo.org/records/7"
METADATA_FILES = {"battinfo.json", "ro-crate-metadata.json"}
NFC_CAFE = unicodedata.normalize("NFC", "café.csv")
NFD_CAFE = unicodedata.normalize("NFD", "café.csv")
# One URL path segment as RFC 3986 allows it: unreserved and sub-delimiter
# characters, ':' and '@', and percent-escapes.
_SEGMENT = re.compile(r"(?:[A-Za-z0-9\-._~!$&'()*+,;=:@]|%[0-9A-F]{2})+")


class _FakeZenodo:
    """Stands in for ZenodoClient: keeps each uploaded file's bytes under its deposit name."""

    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}

    def client(self, *args: object, **kwargs: object) -> _FakeZenodo:
        return self

    def create_empty_deposit(self) -> dict:
        return {"id": 7, "record_id": 7, "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.7"}}}

    def sync_files(self, deposit_id: int, upload_map: dict, *, keep: dict | None = None) -> dict:
        self.uploaded = {name: Path(path).read_bytes() for path, name in upload_map.items()}
        return {"uploaded": sorted(self.uploaded), "kept": [], "removed": []}

    def list_files(self, deposit_id: int) -> list[dict]:
        return [
            {"filename": name, "checksum": hashlib.md5(data).hexdigest()}  # noqa: S324 - Zenodo's checksum
            for name, data in self.uploaded.items()
        ]

    def update_metadata(self, deposit_id: int, metadata: dict) -> dict:
        return {}

    def publish_deposit(self, deposit_id: int) -> dict:
        return {"doi": "10.5281/zenodo.7"}

    def graph(self) -> dict:
        return json.loads(self.uploaded["battinfo.json"])

    def crate_files(self) -> list[dict]:
        crate = json.loads(self.uploaded["ro-crate-metadata.json"])
        return [node for node in crate["@graph"] if node.get("@type") == "File"]

    def data_names(self) -> list[str]:
        return sorted(set(self.uploaded) - METADATA_FILES)


@pytest.fixture()
def zenodo(monkeypatch: pytest.MonkeyPatch) -> _FakeZenodo:
    fake = _FakeZenodo()
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", fake.client)
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    return fake


def _workspace(root: Path, files: dict[str, str]) -> AuthoringWorkspace:
    """A saved workspace with one cell and one cycling test per entry of *files*.

    *files* maps a serial number to the path of the test's data file inside
    *root*. Each file ends with its serial number, so no two hold the same bytes.
    """
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


def _dataset_records(ws: AuthoringWorkspace) -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted((ws._ws.source_root / "dataset").glob("*.json"))
    ]


def _local_files(ws: AuthoringWorkspace) -> dict[str, Path]:
    """Each dataset's data file, by dataset IRI, as the saved records name it."""
    files: dict[str, Path] = {}
    for record in _dataset_records(ws):
        url = record["dataset"]["distributions"][0]["content_url"]
        files[record["dataset"]["id"]] = Path(url2pathname(urlparse(url).path))
    return files


def _distributions(graph: dict) -> dict[str, list[dict]]:
    """The dcat:distribution nodes of each member dataset of a deposit graph, by dataset IRI."""
    return {
        node["@id"]: node["dcat:distribution"]
        for node in graph["@graph"]
        if "dcat:Dataset" in (node.get("@type") or []) and node.get("dcat:distribution")
    }


def _name_of(url: str, record_url: str = RECORD_URL) -> str:
    """The deposit file a deposit URL points at, checking that the URL is well formed."""
    parsed = urlparse(url)
    assert url.startswith(f"{record_url}/files/"), url
    assert not parsed.query and not parsed.fragment, url
    segment = url[len(f"{record_url}/files/") :]
    assert _SEGMENT.fullmatch(segment), url
    return unquote(segment)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Files that share a name ──────────────────────────────────────────────────


def test_two_files_with_one_name_are_two_files_in_the_deposit(tmp_path: Path, zenodo: _FakeZenodo) -> None:
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv", "C02": "C02/cycling.csv"})
    local = _local_files(ws)
    ws.zenodo(token="placeholder", creators=CREATORS)

    names = zenodo.data_names()
    assert len(names) == 2 and "cycling.csv" in names
    renamed = next(name for name in names if name != "cycling.csv")
    assert re.fullmatch(r"[0-9a-f]{8}-cycling\.csv", renamed)
    assert sorted(zenodo.uploaded[name] for name in names) == sorted(p.read_bytes() for p in local.values())

    # The graph links each dataset to its own file.
    distributions = _distributions(zenodo.graph())
    for iri, path in local.items():
        [dist] = distributions[iri]
        name = _name_of(dist["dcat:downloadURL"])
        assert zenodo.uploaded[name] == path.read_bytes()
        assert dist["@id"] == dist["dcat:downloadURL"]
        assert dist["schema:name"] == name

    # So do the rewritten records, with the file's own checksum and provenance.
    for record in _dataset_records(ws):
        dataset = record["dataset"]
        [dist] = dataset["distributions"]
        data = local[dataset["id"]].read_bytes()
        assert zenodo.uploaded[_name_of(dist["content_url"])] == data
        assert dist["checksum"] == {"algorithm": "sha256", "value": _sha256(data)}
        assert dataset["access_url"] == dist["content_url"] == record["provenance"]["source_url"]

    # And the RO-Crate lists both, each with its own digest.
    crate = {unquote(node["@id"]): node for node in zenodo.crate_files()}
    assert sorted(crate) == names
    for name in names:
        assert crate[name]["name"] == name
        assert crate[name]["sha256"] == _sha256(zenodo.uploaded[name])
        assert crate[name]["contentSize"] == str(len(zenodo.uploaded[name]))


def test_two_files_with_one_name_stay_apart_in_a_zipped_deposit(
    tmp_path: Path, zenodo: _FakeZenodo, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("battinfo.ws._ZENODO_ZIP_THRESHOLD", 1)  # two files are zipped
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv", "C02": "C02/cycling.csv"})
    local = _local_files(ws)
    ws.zenodo(token="placeholder", creators=CREATORS)

    assert zenodo.data_names() == ["cycling.zip"]
    with zipfile.ZipFile(io.BytesIO(zenodo.uploaded["cycling.zip"])) as archive:
        members = {info.filename: archive.read(info) for info in archive.infolist()}
    assert len(members) == 2 and "cycling.csv" in members
    assert sorted(members.values()) == sorted(p.read_bytes() for p in local.values())

    # Each dataset points at the archive and names its own member.
    distributions = _distributions(zenodo.graph())
    for iri, path in local.items():
        [dist] = distributions[iri]
        assert dist["dcat:downloadURL"] == f"{RECORD_URL}/files/cycling.zip"
        assert members[dist["schema:name"]] == path.read_bytes()
    [entity] = zenodo.crate_files()
    assert entity["@id"] == "cycling.zip"
    assert entity["sha256"] == _sha256(zenodo.uploaded["cycling.zip"])


@pytest.mark.parametrize(
    ("first", "second"),
    [("Data.csv", "data.csv"), (NFC_CAFE, NFD_CAFE)],
    ids=["case", "unicode-normalisation"],
)
def test_names_a_file_system_takes_for_one_are_told_apart(
    tmp_path: Path, zenodo: _FakeZenodo, first: str, second: str
) -> None:
    """Windows and macOS ignore case, and macOS Unicode normalisation, when they compare names."""
    ws = _workspace(tmp_path, {"C01": f"C01/{first}", "C02": f"C02/{second}"})
    local = _local_files(ws)
    ws.zenodo(token="placeholder", creators=CREATORS)

    names = zenodo.data_names()
    assert len({unicodedata.normalize("NFC", name).casefold() for name in names}) == 2
    assert sorted(zenodo.uploaded[name] for name in names) == sorted(p.read_bytes() for p in local.values())
    for iri, path in local.items():
        [dist] = _distributions(zenodo.graph())[iri]
        assert zenodo.uploaded[_name_of(dist["dcat:downloadURL"])] == path.read_bytes()


def test_a_file_two_distributions_name_is_deposited_once(tmp_path: Path, zenodo: _FakeZenodo) -> None:
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv"})
    # A second dataset names the same file twice, once as a raw file.
    dataset_dir = ws._ws.source_root / "dataset"
    [saved] = dataset_dir.glob("*.json")
    record = json.loads(saved.read_text(encoding="utf-8"))
    record["dataset"]["id"] = "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-dddd"
    [dist] = record["dataset"]["distributions"]
    record["dataset"]["distributions"] = [dist, {**dist, "role": "raw"}]
    (dataset_dir / "dataset-aaaa-bbbb-cccc-dddd.json").write_text(json.dumps(record), encoding="utf-8")
    ws.zenodo(token="placeholder", creators=CREATORS)

    assert zenodo.data_names() == ["cycling.csv"]
    assert len(zenodo.crate_files()) == 1
    url = f"{RECORD_URL}/files/cycling.csv"
    urls = [d["content_url"] for r in _dataset_records(ws) for d in r["dataset"]["distributions"]]
    assert urls == [url, url, url]


def test_a_data_file_never_takes_the_name_of_the_deposit_metadata(tmp_path: Path, zenodo: _FakeZenodo) -> None:
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv"})
    # Point the dataset at a data file that happens to be called battinfo.json.
    data = tmp_path / "C01" / "battinfo.json"
    (tmp_path / "C01" / "cycling.csv").rename(data)
    [saved] = (ws._ws.source_root / "dataset").glob("*.json")
    text = saved.read_text(encoding="utf-8").replace("cycling.csv", "battinfo.json")
    saved.write_text(text, encoding="utf-8")
    ws.zenodo(token="placeholder", creators=CREATORS)

    assert "@graph" in zenodo.graph()  # the deposit graph, not the data file
    [name] = zenodo.data_names()
    assert re.fullmatch(r"[0-9a-f]{8}-battinfo\.json", name)
    assert zenodo.uploaded[name] == data.read_bytes()


# ── File names in URLs ────────────────────────────────────────────────────────

_NAMES_TO_ESCAPE = [
    pytest.param("cell 01.csv", id="space"),
    pytest.param("cell#3.csv", id="hash"),
    pytest.param("100%.csv", id="percent"),
    pytest.param(
        "cell?.csv",
        id="question-mark",
        marks=pytest.mark.skipif(sys.platform == "win32", reason="a Windows file name cannot hold '?'"),
    ),
    pytest.param("Zelle_25°C.csv", id="non-ascii"),
    pytest.param(NFD_CAFE, id="nfd"),
]


@pytest.mark.parametrize("name", _NAMES_TO_ESCAPE)
def test_a_file_name_is_percent_encoded_in_every_url(tmp_path: Path, zenodo: _FakeZenodo, name: str) -> None:
    ws = _workspace(tmp_path, {"C01": f"C01/{name}"})
    [path] = _local_files(ws).values()
    ws.zenodo(token="placeholder", creators=CREATORS)

    # The deposit stores the name itself, in composed (NFC) form.
    deposit_name = unicodedata.normalize("NFC", name)
    assert zenodo.data_names() == [deposit_name]
    assert zenodo.uploaded[deposit_name] == path.read_bytes()

    [dists] = _distributions(zenodo.graph()).values()
    [dist] = dists
    url = dist["dcat:downloadURL"]
    assert _name_of(url) == deposit_name
    assert dist["@id"] == url and dist["schema:name"] == deposit_name

    [record] = _dataset_records(ws)
    assert record["dataset"]["distributions"][0]["content_url"] == url
    assert record["provenance"]["source_url"] == url

    [entity] = zenodo.crate_files()
    assert _SEGMENT.fullmatch(entity["@id"]) and ":" not in entity["@id"]
    assert unquote(entity["@id"]) == entity["name"] == deposit_name


def test_the_preview_names_the_files_as_the_deposit_does(tmp_path: Path, zenodo: _FakeZenodo) -> None:
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv", "C02": "C02/cycling.csv", "C03": "C03/cell 03.csv"})
    preview = json.loads(ws.preview_jsonld(creators=CREATORS).read_text(encoding="utf-8"))
    placeholder = "https://zenodo.org/records/RECORD_ID"
    previewed = sorted(
        _name_of(dist["dcat:downloadURL"], placeholder) for dists in _distributions(preview).values() for dist in dists
    )
    ws.zenodo(token="placeholder", creators=CREATORS)
    assert previewed == zenodo.data_names()


def test_an_artifact_in_the_workspace_is_linked_under_its_deposit_name(tmp_path: Path, zenodo: _FakeZenodo) -> None:
    ws = _workspace(tmp_path, {"C01": "C01/cycling.csv"})
    (tmp_path / "protocols").mkdir()
    (tmp_path / "protocols" / "cc protocol.json").write_text("{}", encoding="utf-8")
    protocol_dir = ws._ws.source_root / "test-protocol"
    protocol_dir.mkdir(exist_ok=True)
    (protocol_dir / "test-protocol-aaaa-bbbb-cccc-dddd.json").write_text(
        json.dumps(
            {
                "test_spec": {
                    "id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
                    "name": "CC",
                    "kind": "capacity_check",
                },
                "artifacts": [
                    {
                        "role": "source_protocol",
                        "format": "aurora-unicycler-json",
                        "locator": "protocols/cc protocol.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    ws.zenodo(token="placeholder", creators=CREATORS)

    assert zenodo.data_names() == ["cc protocol.json", "cycling.csv"]
    plan = next(node for node in zenodo.graph()["@graph"] if "prov:Plan" in (node.get("@type") or []))
    [dist] = plan["dcat:distribution"]
    assert _name_of(dist["dcat:downloadURL"]["@id"]) == "cc protocol.json"


def test_url_segment_escapes_what_one_path_segment_cannot_hold() -> None:
    from battinfo._util import url_segment

    assert url_segment("cycling.bdf.csv") == "cycling.bdf.csv"
    assert url_segment("Cell 01 #3?.csv") == "Cell%2001%20%233%3F.csv"
    assert url_segment("100%.csv") == "100%25.csv"
    assert url_segment("a/b:c.csv") == "a%2Fb%3Ac.csv"  # one segment, never a scheme
    assert url_segment("Zelle_25°C.csv") == "Zelle_25%C2%B0C.csv"
    assert url_segment(NFD_CAFE) == "cafe%CC%81.csv"
    assert url_segment("run (1)+x.csv") == "run%20(1)+x.csv"


# ── The Zenodo upload ─────────────────────────────────────────────────────────


class _Reply:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _client(monkeypatch: pytest.MonkeyPatch, urlopen) -> ZenodoClient:  # noqa: ANN001
    monkeypatch.setattr(zmod.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(zmod.time, "sleep", lambda *_: None)  # no real backoff waits
    client = ZenodoClient(token="fake-token", sandbox=True)
    bucket = {"links": {"bucket": "https://sandbox.zenodo.org/api/files/b1"}}
    monkeypatch.setattr(client, "get_deposit", lambda deposit_id: bucket)
    return client


def test_the_bucket_upload_carries_the_name_percent_encoded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    first.write_text(CSV, encoding="utf-8")
    second.write_text(CSV, encoding="utf-8")
    urls: list[str] = []

    def urlopen(req, timeout=None):  # noqa: ANN001
        urls.append(req.full_url)
        return _Reply(b'{"links": {}}')

    client = _client(monkeypatch, urlopen)
    client.upload_files(1, {first: "Cell 01 #3?.csv", second: "raw/run 1.csv"})
    assert urls == [
        "https://sandbox.zenodo.org/api/files/b1/Cell%2001%20%233%3F.csv",
        # A relative key keeps its folder.
        "https://sandbox.zenodo.org/api/files/b1/raw/run%201.csv",
    ]


@pytest.mark.parametrize(
    "error",
    [
        http.client.InvalidURL("URL can't contain control characters"),
        UnicodeEncodeError("ascii", "Zelle_25°C.csv", 8, 9, "ordinal not in range(128)"),
    ],
    ids=["invalid-url", "unicode"],
)
def test_an_upload_the_http_layer_refuses_is_a_zenodo_error_naming_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    data = tmp_path / "data.csv"
    data.write_text(CSV, encoding="utf-8")
    calls: list[str] = []

    def urlopen(req, timeout=None):  # noqa: ANN001
        calls.append(req.full_url)
        raise error

    client = _client(monkeypatch, urlopen)
    with pytest.raises(ZenodoError, match="Zelle_25°C.csv") as excinfo:
        client.upload_files(1, {data: "Zelle_25°C.csv"})
    assert excinfo.value.__cause__ is error
    assert len(calls) == 1  # the same on every attempt, so not retried


# ── The plan ──────────────────────────────────────────────────────────────────


def test_the_plan_measures_each_file_once_and_finds_records_by_path(tmp_path: Path) -> None:
    from battinfo._deposit_files import build_deposit_file_plan

    data = tmp_path / "C01" / "cycling.csv"
    data.parent.mkdir()
    data.write_text(CSV, encoding="utf-8")
    other = tmp_path / "C02" / "cycling.csv"
    other.parent.mkdir()
    other.write_text(CSV, encoding="utf-8")
    gone = tmp_path / "gone.csv"
    plan = build_deposit_file_plan(
        [(data.as_uri(), "cycling"), (data.as_uri(), "cycling"), (gone.as_uri(), "cycling")],
        root=tmp_path,
    )
    [entry] = plan.files
    content = data.read_bytes()
    assert (entry.name, entry.segment, entry.size) == ("cycling.csv", "cycling.csv", len(content))
    assert entry.md5 == hashlib.md5(content).hexdigest()
    assert entry.sha256 == _sha256(content)
    assert plan.missing == [str(gone)]
    # A record finds the file by its path, spelled either way; a file of the same
    # name elsewhere, and a remote URL, are not it.
    assert plan.entry_for(data.as_uri()) is entry
    assert plan.entry_for("C01/cycling.csv") is entry
    assert plan.entry_for(other.as_uri()) is None
    assert plan.entry_for("https://zenodo.org/records/1/files/cycling.csv") is None


def test_a_name_an_earlier_deposit_gave_a_file_stays_with_it(tmp_path: Path) -> None:
    from battinfo._deposit_files import build_deposit_file_plan, path_key

    first, second = tmp_path / "C01" / "cycling.csv", tmp_path / "C02" / "cycling.csv"
    for path in (first, second):
        path.parent.mkdir()
        path.write_text(CSV, encoding="utf-8")
    # The new file comes first, so it would take the name...
    locations = [(second.as_uri(), "cycling"), (first.as_uri(), "cycling")]
    plan = build_deposit_file_plan(locations, root=tmp_path, measure=False)
    assert plan.entry_for(second.as_uri()).name == "cycling.csv"
    # ...unless the name is recorded for the file that had it.
    plan = build_deposit_file_plan(
        locations, root=tmp_path, measure=False, recorded_names={path_key(first): "cycling.csv"}
    )
    assert plan.entry_for(first.as_uri()).name == "cycling.csv"
    assert re.fullmatch(r"[0-9a-f]{8}-cycling\.csv", plan.entry_for(second.as_uri()).name)


# ── R2 object storage ─────────────────────────────────────────────────────────


class _FakeS3:
    """Stands in for a boto3 S3 client: keeps each object's sha256 under its key."""

    class exceptions:  # noqa: N801 - mirrors boto3's client.exceptions
        class ClientError(Exception):
            pass

    def __init__(self) -> None:
        self.objects: dict[str, str] = {}

    def head_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803
        if Key not in self.objects:
            raise self.exceptions.ClientError(Key)
        return {"Metadata": {"sha256": self.objects[Key]}}

    def upload_file(self, filename: str, bucket: str, key: str, ExtraArgs: dict, Config: object) -> None:  # noqa: N803
        self.objects[key] = ExtraArgs["Metadata"]["sha256"]


def test_r2_urls_carry_the_name_percent_encoded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = _FakeS3()
    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *args, **kwargs: s3  # type: ignore[attr-defined]
    transfer = types.ModuleType("boto3.s3.transfer")
    transfer.TransferConfig = lambda **kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "boto3.s3", types.ModuleType("boto3.s3"))
    monkeypatch.setitem(sys.modules, "boto3.s3.transfer", transfer)
    for name, value in (
        ("R2_ENDPOINT", "https://r2.example"),
        ("R2_ACCESS_KEY_ID", "k"),
        ("R2_SECRET_ACCESS_KEY", "s"),
        ("R2_BUCKET", "b"),
        ("R2_PUBLIC_BASE_URL", "https://pub.example"),
    ):
        monkeypatch.setenv(name, value)
    ws = _workspace(tmp_path, {"C01": "C01/cell 01.csv", "C02": "C02/cell 01.csv"})
    ws.upload()

    for record in _dataset_records(ws):
        dataset = record["dataset"]
        url = f"https://pub.example/datasets/{dataset['short_id']}/cell%2001.csv"
        assert dataset["distributions"][0]["content_url"] == dataset["access_url"] == url
        assert record["provenance"]["source_url"] == url
    assert all(key.endswith("/cell 01.csv") for key in s3.objects) and len(s3.objects) == 2
