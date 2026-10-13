"""ws.zenodo() knows who the creators are before it sends anything, and keeps its steps in order.

- The creators come from ``creators=``, else the workspace contributors
  (``ws.contributor()``), else the creator set with ``battinfo config set
  creator``. With none of these, ws.zenodo() and ws.publish(zenodo=True)
  refuse before any request, and ws.publish() before it saves or uploads.
- Every ORCID reaches Zenodo as a bare id, and the deposit graph and the
  RO-Crate with one ``https://orcid.org/`` in front, however it was given.
- A draft gets the check a publish gets, before the deposit exists.
- The metadata goes up as soon as the deposit exists, before any file, and an
  ``errors`` list in Zenodo's reply stops the run there, with the draft saved
  for the next run to update.
- The data files go up before the graph and the RO-Crate, the deposit is
  published last, and the records point at the deposited files only then.

All offline: Zenodo's HTTP API is answered in memory, so the real client runs.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote

import pytest

import battinfo
from battinfo import zenodo as zmod
from battinfo.ws import AuthoringWorkspace
from battinfo.zenodo import ZenodoClient, ZenodoError

API = "https://zenodo.org/api"
BUCKET = f"{API}/files/bucket-7"
CREATORS = [{"name": "Doe, Jane", "affiliation": "Example Lab"}]
CSV = "test_time_second,voltage_volt,current_ampere\n0,3.0,0\n60,3.5,0.001\n"
ORCID = "0000-0002-1825-0097"
ORCID_X = "0000-0002-1694-233X"   # an ORCID whose check digit is X


class _Reply:
    def __init__(self, payload: object) -> None:
        self._body = b"" if payload is None else json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _ZenodoAPI:
    """Zenodo's deposit API for one deposit (id 7), answered in memory.

    Logs each request as ``"METHOD path"``, the path relative to the API
    root, and keeps the files the bucket receives. A hook in ``on`` runs when
    its request arrives, before the reply.
    """

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.files: dict[str, bytes] = {}
        self.metadata: dict | None = None
        self.metadata_errors: list | None = None
        self.published = False
        self.on: dict[str, Callable[[], None]] = {}

    def _deposit(self) -> dict:
        return {
            "id": 7, "record_id": 7,
            "state": "done" if self.published else "unsubmitted",
            "submitted": self.published,
            "links": {"bucket": BUCKET},
            "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.7"}},
        }

    def urlopen(self, request, timeout: float | None = None) -> _Reply:  # noqa: ANN001
        method, url = request.get_method(), request.full_url
        assert url.startswith(f"{API}/"), url
        path = url[len(API):]
        line = f"{method} {path}"
        self.requests.append(line)
        if line in self.on:
            self.on[line]()
        if url.startswith(f"{BUCKET}/") and method == "PUT":
            name = unquote(url[len(BUCKET) + 1:])
            self.files[name] = request.data
            return _Reply({"key": name, "links": {"self": url}})
        if line == "POST /deposit/depositions":
            return _Reply(self._deposit())
        if line == "GET /deposit/depositions/7":
            return _Reply(self._deposit())
        if line == "PUT /deposit/depositions/7":
            self.metadata = json.loads(request.data)["metadata"]
            reply = {**self._deposit(), "metadata": self.metadata}
            if self.metadata_errors is not None:
                reply["errors"] = self.metadata_errors
            return _Reply(reply)
        if line == "GET /deposit/depositions/7/files":
            return _Reply([
                {"id": name, "filename": name, "checksum": hashlib.md5(data).hexdigest()}  # noqa: S324
                for name, data in self.files.items()
            ])
        if method == "DELETE" and path.startswith("/deposit/depositions/7/files/"):
            self.files.pop(unquote(path.rsplit("/", 1)[-1]), None)
            return _Reply(None)
        if line == "POST /deposit/depositions/7/actions/publish":
            self.published = True
            return _Reply({**self._deposit(), "doi": "10.5281/zenodo.7"})
        raise AssertionError(f"unexpected request: {method} {url}")

    def graph(self) -> dict:
        return json.loads(self.files["battinfo.json"])

    def crate_root(self) -> dict:
        crate = json.loads(self.files["ro-crate-metadata.json"])
        return next(node for node in crate["@graph"] if node["@id"] == "./")


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> _ZenodoAPI:
    fake = _ZenodoAPI()
    monkeypatch.setattr(zmod.urllib.request, "urlopen", fake.urlopen)
    monkeypatch.setattr(zmod.time, "sleep", lambda *_: None)
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    return fake


@pytest.fixture(autouse=True)
def user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The CLI's ~/.battinfo/config.yaml, moved into the test's folder (absent until written)."""
    path = tmp_path / "home" / ".battinfo" / "config.yaml"
    monkeypatch.setattr("battinfo.config.USER_CONFIG_PATH", path)
    return path


def _workspace(root: Path, *, save: bool = True) -> AuthoringWorkspace:
    """One cell with one cycling test, whose data file is C01/cycling.csv."""
    (root / "C01").mkdir(parents=True)
    (root / "C01" / "cycling.csv").write_text(CSV, encoding="utf-8")
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.license("cc-by-4.0")
    spec = battinfo.CellSpec(manufacturer="Example Lab", model="R2032", format="coin", chemistry="li-ion")
    ws.add("cell", spec=spec, serial_numbers=["C01"])
    ws.add("test", type="cycling", cell="C01", data="C01/cycling.csv")
    if save:
        ws.save()
    return ws


def _saved_records(ws: AuthoringWorkspace) -> list[Path]:
    root = ws._ws.source_root
    return sorted(root.rglob("*.json")) if root.exists() else []


def _content_urls(ws: AuthoringWorkspace) -> list[str]:
    return [
        dist["content_url"]
        for path in sorted((ws._ws.source_root / "dataset").glob("*.json"))
        for dist in json.loads(path.read_text(encoding="utf-8"))["dataset"]["distributions"]
    ]


def _state(ws: AuthoringWorkspace) -> dict | None:
    path = ws._root / ".battinfo" / "zenodo.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _catalog(graph: dict) -> dict:
    return next(node for node in graph["@graph"] if "dcat:Catalog" in (node.get("@type") or []))


def _ids(nodes: object) -> list[str]:
    nodes = nodes if isinstance(nodes, list) else [nodes]
    return [node.get("@id", "") for node in nodes if isinstance(node, dict)]


# ── Creators ──────────────────────────────────────────────────────────────────


def test_a_deposit_without_creators_is_refused_before_any_request(tmp_path: Path, api: _ZenodoAPI) -> None:
    ws = _workspace(tmp_path)
    with pytest.raises(ValueError, match="No creators for the Zenodo deposit") as excinfo:
        ws.zenodo(token="placeholder", publish=True)
    message = str(excinfo.value)
    assert "Nothing was sent to Zenodo." in message
    assert "creators=" in message and "ws.contributor(" in message and "battinfo config set creator" in message
    assert api.requests == []
    assert _state(ws) is None


def test_publish_to_zenodo_without_creators_saves_and_uploads_nothing(
    tmp_path: Path, api: _ZenodoAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ZENODO_API_TOKEN", "placeholder")
    monkeypatch.setenv("R2_ENDPOINT", "https://r2.example")  # publish() uploads to R2 first
    ws = _workspace(tmp_path, save=False)
    steps: list[str] = []
    monkeypatch.setattr(ws, "upload", lambda *args, **kwargs: steps.append("upload"))
    monkeypatch.setattr(ws, "submit", lambda **kwargs: steps.append("submit") or [])

    with pytest.raises(ValueError, match="No creators for the Zenodo deposit"):
        ws.publish(zenodo=True, note="no creators")
    assert _saved_records(ws) == [] and steps == [] and api.requests == []

    # Given creators, the same call saves, uploads, deposits and submits.
    ws.publish(zenodo=True, note="with creators", creators=CREATORS)
    assert _saved_records(ws) and steps == ["upload", "submit"]
    assert api.published and api.metadata is not None and api.metadata["creators"] == CREATORS


def test_publish_to_zenodo_without_a_token_saves_nothing(
    tmp_path: Path, api: _ZenodoAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ZENODO_API_TOKEN", raising=False)
    ws = _workspace(tmp_path, save=False)
    with pytest.raises(RuntimeError, match="Zenodo token required"):
        ws.publish(zenodo=True, creators=CREATORS)
    assert _saved_records(ws) == [] and api.requests == []


@pytest.mark.parametrize("source", ["argument", "contributors", "config"])
def test_creators_come_from_the_argument_then_the_contributors_then_the_config(
    tmp_path: Path, api: _ZenodoAPI, user_config: Path, source: str
) -> None:
    user_config.parent.mkdir(parents=True)
    user_config.write_text('creator: "Roe, Rick; Config Lab"\n', encoding="utf-8")
    ws = _workspace(tmp_path, save=False)
    if source != "config":
        ws.contributor(ORCID, name="Lovelace, Ada", affiliation="SINTEF")
    ws.save()

    ws.zenodo(token="placeholder", creators=CREATORS if source == "argument" else None)

    expected = {
        "argument": CREATORS,
        "contributors": [{"orcid": ORCID, "name": "Lovelace, Ada", "affiliation": "SINTEF"}],
        "config": [{"name": "Roe, Rick", "affiliation": "Config Lab"}],
    }[source]
    assert api.metadata is not None and api.metadata["creators"] == expected
    creators = _catalog(api.graph())["schema:creator"]
    assert [node["schema:name"] for node in creators] == [c["name"] for c in expected]
    root_creators = api.crate_root()["creator"]
    root_creators = root_creators if isinstance(root_creators, list) else [root_creators]
    assert [node["name"] for node in root_creators] == [c["name"] for c in expected]


def test_a_creator_needs_a_name(tmp_path: Path, api: _ZenodoAPI) -> None:
    ws = _workspace(tmp_path)
    with pytest.raises(ValueError, match="creator 2 has no name"):
        ws.zenodo(token="placeholder", creators=[CREATORS[0], {"orcid": ORCID}])
    assert api.requests == []


def test_the_preview_credits_the_creators_the_deposit_would(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(tmp_path)
    capsys.readouterr()
    ws.preview_jsonld()
    assert "ERROR   no creators: ws.zenodo() refuses a deposit without them" in capsys.readouterr().out

    ws.contributor(ORCID, name="Lovelace, Ada")
    graph = json.loads(ws.preview_jsonld().read_text(encoding="utf-8"))
    assert "no creators" not in capsys.readouterr().out
    [creator] = _catalog(graph)["schema:creator"]
    assert creator["@id"] == f"https://orcid.org/{ORCID}" and creator["schema:name"] == "Lovelace, Ada"


# ── ORCIDs ────────────────────────────────────────────────────────────────────


_ORCID_FORMS = [
    pytest.param(ORCID, ORCID_X, id="bare"),
    pytest.param(f"https://orcid.org/{ORCID}", f"https://orcid.org/{ORCID_X.lower()}", id="https"),
    pytest.param(f"http://orcid.org/{ORCID}/", f"HTTP://ORCID.ORG/{ORCID_X}", id="http"),
    pytest.param(f" {ORCID} ", f"{ORCID_X}\n", id="padded"),
]


@pytest.mark.parametrize(("creator_orcid", "contributor_orcid"), _ORCID_FORMS)
def test_an_orcid_is_sent_as_a_bare_id_however_it_is_given(
    tmp_path: Path, api: _ZenodoAPI, creator_orcid: str, contributor_orcid: str
) -> None:
    ws = _workspace(tmp_path)
    creators = [{"name": "Lovelace, Ada", "orcid": creator_orcid}]
    contributors = [{"name": "Turing, Alan", "orcid": contributor_orcid, "type": "DataCurator"}]
    ws.zenodo(token="placeholder", creators=creators, contributors=contributors)

    assert api.metadata is not None
    assert [c["orcid"] for c in api.metadata["creators"]] == [ORCID]
    assert [c["orcid"] for c in api.metadata["contributors"]] == [ORCID_X]
    catalog = _catalog(api.graph())
    assert _ids(catalog["schema:creator"]) == [f"https://orcid.org/{ORCID}"]
    assert _ids(catalog["schema:contributor"]) == [f"https://orcid.org/{ORCID_X}"]
    root = api.crate_root()
    assert _ids(root["creator"]) == [f"https://orcid.org/{ORCID}"]
    assert _ids(root["contributor"]) == [f"https://orcid.org/{ORCID_X}"]

    # The previews show the same identifiers.
    preview = json.loads(
        ws.preview_jsonld(creators=creators, contributors=contributors).read_text(encoding="utf-8")
    )
    assert _ids(_catalog(preview)["schema:creator"]) == [f"https://orcid.org/{ORCID}"]
    assert _ids(_catalog(preview)["schema:contributor"]) == [f"https://orcid.org/{ORCID_X}"]
    crate = json.loads(ws.preview_rocrate(creators=creators, contributors=contributors).read_text(encoding="utf-8"))
    preview_root = next(node for node in crate["@graph"] if node["@id"] == "./")
    assert _ids(preview_root["creator"]) == [f"https://orcid.org/{ORCID}"]
    assert _ids(preview_root["contributor"]) == [f"https://orcid.org/{ORCID_X}"]


def test_a_contributor_given_by_orcid_url_is_credited_once(tmp_path: Path, api: _ZenodoAPI) -> None:
    """The workspace contributor and the same person given by URL are one node in the graph."""
    ws = _workspace(tmp_path, save=False)
    ws.contributor(ORCID_X, name="Turing, Alan")
    ws.save()
    contributors = [{"name": "Turing, Alan", "orcid": f"https://orcid.org/{ORCID_X}"}]
    ws.zenodo(token="placeholder", creators=CREATORS, contributors=contributors)
    assert _ids(_catalog(api.graph())["schema:contributor"]) == [f"https://orcid.org/{ORCID_X}"]


@pytest.mark.parametrize("call", ["zenodo", "preview_jsonld", "preview_rocrate"])
def test_an_invalid_orcid_is_refused_naming_its_creator(tmp_path: Path, api: _ZenodoAPI, call: str) -> None:
    ws = _workspace(tmp_path)
    creators = [{"name": "Lovelace, Ada", "orcid": "https://orcid.org/1234"}]
    kwargs = {"token": "placeholder"} if call == "zenodo" else {}
    with pytest.raises(ValueError, match=r"creator 'Lovelace, Ada': invalid ORCID iD"):
        getattr(ws, call)(creators=creators, **kwargs)
    assert api.requests == []


# ── The order of the steps ────────────────────────────────────────────────────


def test_a_publish_sends_the_metadata_first_and_points_the_records_last(tmp_path: Path, api: _ZenodoAPI) -> None:
    ws = _workspace(tmp_path)
    local_urls = _content_urls(ws)
    seen: dict[str, object] = {}
    api.on["PUT /deposit/depositions/7"] = lambda: seen.update(state_at_metadata=_state(ws))
    api.on["POST /deposit/depositions/7/actions/publish"] = lambda: seen.update(urls_at_publish=_content_urls(ws))

    result = ws.zenodo(token="placeholder", creators=CREATORS, publish=True)

    assert api.requests == [
        "POST /deposit/depositions",
        "PUT /deposit/depositions/7",                  # the metadata, before any file
        "GET /deposit/depositions/7/files",
        "GET /deposit/depositions/7",
        "PUT /files/bucket-7/cycling.csv",             # the data first,
        "PUT /files/bucket-7/battinfo.json",           # then the graph that links to it
        "PUT /files/bucket-7/ro-crate-metadata.json",
        "POST /deposit/depositions/7/actions/publish",
    ]
    # The draft was saved before its metadata went up, as unpublished.
    assert seen["state_at_metadata"] == {
        "record_id": "7", "doi": "10.5281/zenodo.7", "published": False, "sandbox": False,
    }
    # The records kept their local files until the DOI existed.
    assert seen["urls_at_publish"] == local_urls and local_urls[0].startswith("file:")
    assert _content_urls(ws) == ["https://zenodo.org/records/7/files/cycling.csv"]
    assert _state(ws) == {"record_id": "7", "doi": "10.5281/zenodo.7", "published": True, "sandbox": False}
    assert result.published and result.doi == "10.5281/zenodo.7"


def test_metadata_zenodo_does_not_accept_stops_the_deposit_before_any_file(
    tmp_path: Path, api: _ZenodoAPI
) -> None:
    ws = _workspace(tmp_path)
    local_urls = _content_urls(ws)
    api.metadata_errors = [
        {"field": "metadata.creators", "messages": ["Missing data for required field."]},
        {"field": "metadata.publication_date", "message": "Not a valid date."},
    ]
    with pytest.raises(ZenodoError) as excinfo:
        ws.zenodo(token="placeholder", creators=CREATORS, publish=True)
    message = str(excinfo.value)
    assert "metadata.creators (Missing data for required field.)" in message
    assert "metadata.publication_date (Not a valid date.)" in message
    assert "This run uploaded no file." in message
    assert "https://zenodo.org/deposit/7" in message and "the next ws.zenodo() updates it" in message
    assert api.requests == ["POST /deposit/depositions", "PUT /deposit/depositions/7"]
    assert api.files == {} and not api.published
    assert _content_urls(ws) == local_urls
    # The draft is saved, unpublished, so the next run updates it rather than open another.
    assert _state(ws) == {"record_id": "7", "doi": "10.5281/zenodo.7", "published": False, "sandbox": False}

    api.metadata_errors = None
    api.requests.clear()
    with pytest.warns(UserWarning, match="unpublished draft"):
        ws.zenodo(token="placeholder", creators=CREATORS, publish=True)
    assert api.requests[:2] == ["GET /deposit/depositions/7", "PUT /deposit/depositions/7"]
    assert "POST /deposit/depositions" not in api.requests
    assert api.published and set(api.files) == {"cycling.csv", "battinfo.json", "ro-crate-metadata.json"}


def test_a_draft_with_a_graph_error_is_refused_before_the_deposit_exists(tmp_path: Path, api: _ZenodoAPI) -> None:
    ws = _workspace(tmp_path)
    # The test now points at a cell the deposit has no node for.
    for path in (ws._ws.source_root / "cell-instance").glob("*.json"):
        path.unlink()
    with pytest.raises(RuntimeError) as excinfo:
        ws.zenodo(token="placeholder", creators=CREATORS)   # a draft
    message = str(excinfo.value)
    assert message.startswith("Refusing to deposit: ")
    assert "validation error(s)" in message and "Not found locally" in message
    assert "leave the deposit as a draft" not in message
    assert message.endswith("Nothing was sent to Zenodo.")
    assert api.requests == [] and _state(ws) is None


def test_a_draft_missing_a_data_file_is_refused_before_the_deposit_exists(tmp_path: Path, api: _ZenodoAPI) -> None:
    ws = _workspace(tmp_path)
    (tmp_path / "C01" / "cycling.csv").unlink()
    with pytest.raises(RuntimeError, match=r"^Refusing to deposit: 1 distribution data file\(s\) are missing"):
        ws.zenodo(token="placeholder", creators=CREATORS)
    assert api.requests == [] and _state(ws) is None


# ── The client ────────────────────────────────────────────────────────────────


def test_update_metadata_raises_on_an_errors_list_naming_the_fields(api: _ZenodoAPI) -> None:
    api.metadata_errors = [
        {"field": "metadata.creators", "messages": ["Missing data for required field.", "Too short."]},
        {"field": "metadata.title"},
        "the record has problems",
    ]
    client = ZenodoClient(token="placeholder")
    with pytest.raises(ZenodoError) as excinfo:
        client.update_metadata(7, {"title": ""})
    assert str(excinfo.value) == (
        "Zenodo did not accept the metadata of deposit 7: "
        "metadata.creators (Missing data for required field.; Too short.); "
        "metadata.title; the record has problems"
    )
    assert api.requests == ["PUT /deposit/depositions/7"]  # a write is sent once


def test_update_metadata_returns_a_reply_without_errors(api: _ZenodoAPI) -> None:
    client = ZenodoClient(token="placeholder")
    assert client.update_metadata(7, {"title": "Coin cells"})["metadata"] == {"title": "Coin cells"}
    api.metadata_errors = []  # an empty list is no objection
    assert client.update_metadata(7, {"title": "Coin cells"})["errors"] == []
