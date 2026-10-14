"""A Zenodo deposit keeps its data files across drafts, versions, retries and environments.

- ``.battinfo/deposit-files.json`` records the local file behind each copy a
  deposit or ``ws.upload()`` made, so a record that points at its copy still
  has its data in the next deposit: a publish after a draft, a new version
  (also after the local file was deleted), a retry after a failed run, and a
  new record after ``.battinfo/zenodo.json`` was deleted.
- ``ZenodoClient.sync_files`` never removes a file a record still points at,
  keeps a copy whose md5 is the one recorded when there is no local file, and
  refuses before it changes anything when there is neither. ``ws.zenodo()``
  asks for the files of the record it starts from first, so such a refusal
  comes before a draft is made, and names each dataset and how to go on. A
  draft's files count in the index only once it is published, so a draft
  deleted on the website leaves the published copy its checksums.
- The dataset records, and the datasets in memory, point at the deposited
  files: a record that names a local file after a draft as after a publish,
  so ``ws.submit()`` sends https URLs and a later ``ws.save()`` does not undo
  it, and a record on a published copy only once the new version is
  published. A file that changed is described as the deposit holds it, with
  its own sha256 and size, in the graph, the RO-Crate and the record.
- A recorded draft is checked with Zenodo, so one published on the website
  gets a new version, and ``ws.submit()`` records its DOI. One deleted there
  stops the run, which names the way on that keeps the record's lineage.
- Each Zenodo has its own state file: ``.battinfo/zenodo.json`` and
  ``.battinfo/zenodo-sandbox.json``. A sandbox deposit never touches the
  records or the production record, and ``ws.submit()`` never records a
  sandbox DOI or a draft's.
- A record that points at a copy of the workspace's own data whose local file
  the workspace does not know (an R2 copy an earlier build made, a file in an
  unpublished draft of this account or in an unrecorded version of its own
  Zenodo record) refuses the deposit instead of being linked to, in a new
  session and in a first deposit too.
- A deposit of files ``ws.upload()`` put in R2, or that ``ws.publish(zenodo=True)``
  would put there, is refused before any request unless
  ``archive_hosted_files=True``, which archives them from their local files and
  names each one from the private bucket in a warning.

All offline: Zenodo's HTTP API (production and sandbox) and the registry are
answered in memory, so the real ZenodoClient runs.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import types
import urllib.error
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

import pytest

import battinfo
from battinfo import zenodo as zmod
from battinfo._deposit_index import DepositIndexError
from battinfo.ws import AuthoringWorkspace, SubmitError
from battinfo.zenodo import KeptFilesError, ZenodoClient, ZenodoError

CREATORS = [{"name": "Doe, Jane", "affiliation": "Example Lab"}]
CSV = "test_time_second,voltage_volt,current_ampere\n0,3.0,0\n60,3.5,0.001\n"
REGISTRY = dict(registry_url="https://registry.example", api_key="k", workspace_id="w", publisher_id="p")
APIS = {"production": "https://zenodo.org/api", "sandbox": "https://sandbox.zenodo.org/api"}
HOSTS = {"production": "https://zenodo.org", "sandbox": "https://sandbox.zenodo.org"}


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()  # noqa: S324 - Zenodo's file checksum


class _Reply:
    def __init__(self, payload: object) -> None:
        self._body = b"" if payload is None else json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *args: object) -> None:
        return None


@dataclass
class _Deposit:
    id: int
    concept: int
    files: dict[str, bytes] = field(default_factory=dict)
    published: bool = False


class _Zenodo:
    """Zenodo's deposit API, production and sandbox, answered in memory.

    Each environment numbers its records from its own counter: a new record
    takes a concept id and a record id, a new version the next record id. A
    new version starts as a draft holding a copy of every file of the version
    it was made from, as Zenodo's does. A published deposit refuses edits.
    ``requests`` logs ``"<environment> METHOD path"``; a request line in
    ``fail`` is answered with HTTP 500 as many times as it says.
    """

    def __init__(self) -> None:
        self.deposits: dict[str, dict[int, _Deposit]] = {"production": {}, "sandbox": {}}
        self._next = {"production": 7000, "sandbox": 500}
        self.requests: list[str] = []
        self.fail: dict[str, int] = {}

    # ── the service ──────────────────────────────────────────────────────────

    def create(
        self,
        environment: str = "production",
        *,
        files: dict[str, bytes] | None = None,
        concept: int | None = None,
        published: bool = False,
    ) -> _Deposit:
        if concept is None:
            concept = self._next[environment]
            self._next[environment] += 1
        deposit = _Deposit(id=self._next[environment], concept=concept, files=dict(files or {}), published=published)
        self._next[environment] += 1
        self.deposits[environment][deposit.id] = deposit
        return deposit

    def website_publish(self, deposit_id: int, environment: str = "production") -> None:
        """Publish a draft, as a click on the Zenodo website does."""
        self.deposits[environment][deposit_id].published = True

    def _json(self, environment: str, deposit: _Deposit) -> dict:
        api = APIS[environment]
        doi = f"10.5281/zenodo.{deposit.id}"
        reply: dict = {
            "id": deposit.id,
            "record_id": deposit.id,
            "conceptrecid": str(deposit.concept),
            "state": "done" if deposit.published else "unsubmitted",
            "submitted": deposit.published,
            "links": {"bucket": f"{api}/files/bucket-{deposit.id}"},
            "metadata": {"prereserve_doi": {"doi": doi}},
        }
        if deposit.published:
            reply["doi"] = doi
            reply["metadata"]["doi"] = doi
        return reply

    def urlopen(self, request, timeout: float | None = None) -> _Reply:  # noqa: ANN001
        method, url = request.get_method(), request.full_url
        environment = next(env for env, api in APIS.items() if url.startswith(f"{api}/"))
        path = url[len(APIS[environment]) :]
        line = f"{method} {path}"
        self.requests.append(f"{environment} {line}")
        if self.fail.get(line):
            self.fail[line] -= 1
            raise urllib.error.HTTPError(url, 500, "error", None, io.BytesIO(b"server error"))  # type: ignore[arg-type]
        deposits = self.deposits[environment]
        parts = path.strip("/").split("/")
        if parts[0] == "files" and method == "PUT":  # the bucket: /files/bucket-<id>/<name>
            deposit = deposits[int(parts[1].removeprefix("bucket-"))]
            if deposit.published:
                return self._refuse(url, 403)
            name = unquote("/".join(parts[2:]))
            deposit.files[name] = request.data
            return _Reply({"key": name, "checksum": f"md5:{_md5(request.data)}"})
        if line == "POST /deposit/depositions":
            return _Reply(self._json(environment, self.create(environment)))
        if parts[:2] != ["deposit", "depositions"] or len(parts) < 3:
            raise AssertionError(f"unexpected request: {method} {url}")
        deposit = deposits.get(int(parts[2]))
        if deposit is None:
            return self._refuse(url, 404)
        rest = parts[3:]
        if method == "GET" and not rest:
            return _Reply(self._json(environment, deposit))
        if method == "PUT" and not rest:
            if deposit.published:
                return self._refuse(url, 400)
            return _Reply({**self._json(environment, deposit), "metadata": json.loads(request.data)["metadata"]})
        if method == "GET" and rest == ["files"]:
            return _Reply(
                [{"id": name, "filename": name, "checksum": _md5(data)} for name, data in deposit.files.items()]
            )
        if method == "DELETE" and rest[:1] == ["files"]:
            if deposit.published:
                return self._refuse(url, 400)
            deposit.files.pop(unquote(rest[1]), None)
            return _Reply(None)
        if method == "POST" and rest == ["actions", "publish"]:
            if deposit.published:
                return self._refuse(url, 400)
            deposit.published = True
            return _Reply(self._json(environment, deposit))
        if method == "POST" and rest == ["actions", "newversion"]:
            drafts = [d for d in deposits.values() if d.concept == deposit.concept and not d.published]
            if not deposit.published or drafts:
                return self._refuse(url, 400)
            draft = self.create(environment, files=deposit.files, concept=deposit.concept)
            reply = self._json(environment, deposit)
            reply["links"]["latest_draft"] = f"{APIS[environment]}/deposit/depositions/{draft.id}"
            return _Reply(reply)
        raise AssertionError(f"unexpected request: {method} {url}")

    @staticmethod
    def _refuse(url: str, code: int) -> _Reply:
        raise urllib.error.HTTPError(url, code, "refused", None, io.BytesIO(b"refused"))  # type: ignore[arg-type]

    # ── what a test reads ────────────────────────────────────────────────────

    def deposit(self, deposit_id: int, environment: str = "production") -> _Deposit:
        return self.deposits[environment][deposit_id]

    def graph(self, deposit_id: int, environment: str = "production") -> dict:
        return json.loads(self.deposit(deposit_id, environment).files["battinfo.json"])

    def sent(self, environment: str = "production") -> list[str]:
        """The requests made to *environment*, without the environment."""
        prefix = f"{environment} "
        return [line[len(prefix) :] for line in self.requests if line.startswith(prefix)]


class _Registry:
    """Stands in for the registry's submission endpoint: keeps each payload."""

    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def __call__(self, payload, *, registry_base_url, api_key, **kwargs):  # noqa: ANN001
        self.payloads.append(copy.deepcopy(payload))
        return {
            "status": "ok",
            "status_code": 200,
            "response": {"status": "validated", "resources": [{"canonical_iri": "iri"}]},
        }

    def dois(self) -> dict[str, list[str]]:
        """The citation DOIs each submitted payload carries, by resource type."""
        found: dict[str, list[str]] = {}
        for payload in self.payloads:
            resource_type = payload["resource"]["resource_type"]
            found.setdefault(resource_type, []).extend(_values(payload, "citation_doi"))
        return found


def _values(node: object, key: str) -> list[str]:
    if isinstance(node, dict):
        return [v for k, v in node.items() if k == key] + [x for v in node.values() for x in _values(v, key)]
    if isinstance(node, list):
        return [x for item in node for x in _values(item, key)]
    return []


@pytest.fixture()
def zenodo(monkeypatch: pytest.MonkeyPatch) -> _Zenodo:
    fake = _Zenodo()
    monkeypatch.setattr(zmod.urllib.request, "urlopen", fake.urlopen)
    monkeypatch.setattr(zmod.time, "sleep", lambda *_: None)
    for name in ("R2_ENDPOINT", "ZENODO_API_TOKEN", "ZENODO_SANDBOX_TOKEN", "ZENODO_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    return fake


@pytest.fixture()
def registry(monkeypatch: pytest.MonkeyPatch) -> _Registry:
    fake = _Registry()
    monkeypatch.setattr("battinfo.api.submit_publication_package", fake)
    return fake


@pytest.fixture(autouse=True)
def user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI's ~/.battinfo/config.yaml, moved into the test's folder, so no real one is read."""
    monkeypatch.setattr("battinfo.config.USER_CONFIG_PATH", tmp_path / "home" / ".battinfo" / "config.yaml")


def _workspace(root: Path, serials: tuple[str, ...] = ("C01",)) -> AuthoringWorkspace:
    """One cycling test per serial number, on <serial>/cycling.csv, saved."""
    root.mkdir(parents=True, exist_ok=True)
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.license("cc-by-4.0")
    spec = battinfo.CellSpec(manufacturer="Example Lab", model="R2032", format="coin", chemistry="li-ion")
    ws.add("cell", spec=spec, serial_numbers=list(serials))
    for serial in serials:
        _data_file(root, serial)
        ws.add("test", type="cycling", cell=serial, data=f"{serial}/cycling.csv")
    ws.save()
    return ws


def _data_file(root: Path, serial: str) -> Path:
    path = root / serial / "cycling.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{CSV}# {serial}\n", encoding="utf-8")
    return path


def _datasets(ws: AuthoringWorkspace) -> list[tuple[Path, dict]]:
    folder = ws._ws.source_root / "dataset"
    return [(path, json.loads(path.read_text(encoding="utf-8"))) for path in sorted(folder.glob("*.json"))]


def _locations(ws: AuthoringWorkspace) -> list[str]:
    """Every location the saved dataset records give: access_url, content_url and source_url."""
    found: list[str] = []
    for _path, record in _datasets(ws):
        found.append(record["dataset"]["access_url"])
        found += [dist["content_url"] for dist in record["dataset"]["distributions"]]
        found.append(record["provenance"].get("source_url", ""))
    return found


STATE_FILES = {"production": "zenodo.json", "sandbox": "zenodo-sandbox.json"}


def _state(root: Path, environment: str = "production") -> dict | None:
    path = root / ".battinfo" / STATE_FILES[environment]
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _download_urls(graph: dict) -> list[str]:
    return sorted(dist["dcat:downloadURL"] for dist in _member_distributions(graph))


def _member_distributions(graph: dict) -> list[dict]:
    return [
        dist
        for node in graph["@graph"]
        if "dcat:Dataset" in (node.get("@type") or [])
        for dist in node.get("dcat:distribution") or []
    ]


def _crate_file(deposit: _Deposit, name: str) -> dict:
    crate = json.loads(deposit.files["ro-crate-metadata.json"])
    return next(node for node in crate["@graph"] if node.get("@type") == "File" and node.get("name") == name)


def _edit_datasets(ws: AuthoringWorkspace, edit: Callable[[dict], object]) -> None:
    """Apply *edit* to each saved dataset record's body, as a hand edit would."""
    for path, record in _datasets(ws):
        edit(record["dataset"])
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def _point_datasets_at(ws: AuthoringWorkspace, url: str) -> None:
    """Point every location of each saved dataset at *url*, as an earlier build's rewrite left it."""
    for path, record in _datasets(ws):
        record["dataset"]["access_url"] = url
        record["dataset"]["distributions"][0]["content_url"] = url
        record["provenance"]["source_url"] = url
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def _deposit(ws: AuthoringWorkspace, **kwargs: object):  # noqa: ANN202
    return ws.zenodo(token="placeholder", creators=CREATORS, **kwargs)


# ── Draft, then submit ────────────────────────────────────────────────────────


def test_a_draft_then_submit_sends_https_urls(
    tmp_path: Path, zenodo: _Zenodo, registry: _Registry, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(tmp_path)
    result = _deposit(ws)  # a draft
    assert not result.published
    url = f"{HOSTS['production']}/records/{result.record_id}/files/cycling.csv"
    assert set(_locations(ws)) == {url}

    capsys.readouterr()
    outcomes = ws.submit(**REGISTRY)

    assert outcomes and all(outcome["ok"] for outcome in outcomes)
    sent = json.dumps(registry.payloads)
    assert "file:" not in sent and url in sent
    # A draft's DOI is only reserved; without a token it cannot be checked, so none is recorded.
    assert all(dois == [] for dois in registry.dois().values())
    out = capsys.readouterr().out
    assert f"The Zenodo record {result.record_id} in .battinfo/zenodo.json is a draft" in out


def test_a_draft_published_on_the_website_gets_its_doi_on_submit_and_a_new_version_next(
    tmp_path: Path, zenodo: _Zenodo, registry: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(tmp_path)
    draft = _deposit(ws)
    zenodo.website_publish(int(draft.record_id))
    monkeypatch.setenv("ZENODO_API_TOKEN", "placeholder")

    ws.submit(**REGISTRY)

    doi = f"10.5281/zenodo.{draft.record_id}"
    assert registry.dois() == {"cell_spec": [doi], "cell": [doi], "test": [doi], "dataset": [doi]}
    state = _state(tmp_path)
    assert state is not None and state["published"] is True and state["doi"] == doi

    # The next deposit makes a new version of the published record; it does
    # not try to edit it.
    zenodo.requests.clear()
    with pytest.warns(UserWarning, match="NEW VERSION"):
        second = _deposit(ws, publish=True)
    assert f"POST /deposit/depositions/{draft.record_id}/actions/newversion" in zenodo.sent()
    assert f"PUT /deposit/depositions/{draft.record_id}" not in zenodo.sent()
    assert second.published and zenodo.deposit(int(second.record_id)).files["cycling.csv"]


def test_submit_names_the_doi_of_a_published_record_that_lists_no_records(
    tmp_path: Path, zenodo: _Zenodo, registry: _Registry, capsys: pytest.CaptureFixture[str]
) -> None:
    """A state an earlier build wrote does not list the records its deposit holds."""
    ws = _workspace(tmp_path)
    (tmp_path / ".battinfo" / "zenodo.json").write_text(
        json.dumps({"record_id": "7001", "doi": "10.5281/zenodo.7001", "published": True, "sandbox": False}),
        encoding="utf-8",
    )
    capsys.readouterr()

    ws.submit(allow_local_files=True, **REGISTRY)

    out = capsys.readouterr().out
    assert "does not list the records its deposit holds" in out
    assert "Pass doi='10.5281/zenodo.7001' to record it on every record." in out
    assert "run ws.zenodo() again" not in out  # that would make a new version, with a new DOI
    assert all(dois == [] for dois in registry.dois().values())


def test_a_publish_then_save_then_submit_keeps_the_deposited_urls(
    tmp_path: Path, zenodo: _Zenodo, registry: _Registry
) -> None:
    ws = _workspace(tmp_path)
    result = _deposit(ws, publish=True)
    url = f"{HOSTS['production']}/records/{result.record_id}/files/cycling.csv"

    ws.save()  # writes the datasets in memory, which point at the deposit too

    assert set(_locations(ws)) == {url}
    ws.submit(**REGISTRY)
    assert "file:" not in json.dumps(registry.payloads)
    assert registry.dois()["dataset"] == [result.doi]


def test_a_draft_leaves_records_on_a_published_copy_until_it_is_published(
    tmp_path: Path, zenodo: _Zenodo, registry: _Registry
) -> None:
    ws = _workspace(tmp_path)
    first = _deposit(ws, publish=True)
    published_url = f"{HOSTS['production']}/records/{first.record_id}/files/cycling.csv"

    with pytest.warns(UserWarning, match="NEW VERSION"):
        draft = _deposit(ws)  # a new version, left as a draft

    # The published copy works; the draft's serves nothing until it is published.
    assert set(_locations(ws)) == {published_url}
    ws.submit(**REGISTRY)
    sent = json.dumps(registry.payloads)
    assert published_url in sent and f"/records/{draft.record_id}/" not in sent

    with pytest.warns(UserWarning, match="unpublished draft"):
        second = _deposit(ws, publish=True)

    assert second.record_id == draft.record_id and second.published
    assert set(_locations(ws)) == {f"{HOSTS['production']}/records/{second.record_id}/files/cycling.csv"}
    assert zenodo.deposit(int(second.record_id)).files["cycling.csv"] == (tmp_path / "C01" / "cycling.csv").read_bytes()


# ── Versions, retries and a new record ────────────────────────────────────────


def test_a_new_version_after_the_local_file_is_deleted_keeps_the_data_file(tmp_path: Path, zenodo: _Zenodo) -> None:
    ws = _workspace(tmp_path)
    data = (tmp_path / "C01" / "cycling.csv").read_bytes()
    first = _deposit(ws, publish=True)
    (tmp_path / "C01" / "cycling.csv").unlink()
    zenodo.requests.clear()

    with pytest.warns(UserWarning, match="NEW VERSION"):
        second = _deposit(ws, publish=True)

    assert second.published and second.record_id != first.record_id
    files = zenodo.deposit(int(second.record_id)).files
    assert files["cycling.csv"] == data
    # The copy the new version took over is kept, not sent again.
    assert not any(line.endswith("/cycling.csv") and line.startswith("PUT /files/") for line in zenodo.sent())
    url = f"{HOSTS['production']}/records/{second.record_id}/files/cycling.csv"
    assert set(_locations(ws)) == {url}
    assert _download_urls(zenodo.graph(int(second.record_id))) == [url]


def test_a_new_version_from_a_state_without_an_index_keeps_the_data_file(tmp_path: Path, zenodo: _Zenodo) -> None:
    """A workspace whose records were pointed at Zenodo before the deposit index existed."""
    ws = _workspace(tmp_path)
    data = (tmp_path / "C01" / "cycling.csv").read_bytes()
    published = zenodo.create(
        files={"cycling.csv": data, "battinfo.json": b"{}", "ro-crate-metadata.json": b"{}"},
        published=True,
    )
    url = f"{HOSTS['production']}/records/{published.id}/files/cycling.csv"
    for path, record in _datasets(ws):
        sha256 = hashlib.sha256(data).hexdigest()
        record["dataset"]["access_url"] = url
        record["dataset"]["distributions"] = [
            {
                **record["dataset"]["distributions"][0],
                "content_url": url,
                "checksum": {"algorithm": "sha256", "value": sha256},
            },
        ]
        record["provenance"]["source_url"] = url
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    (tmp_path / ".battinfo" / "zenodo.json").write_text(
        json.dumps(
            {
                "record_id": str(published.id),
                "doi": f"10.5281/zenodo.{published.id}",
                "published": True,
                "sandbox": False,
            }
        ),
        encoding="utf-8",
    )
    index = json.loads((tmp_path / ".battinfo" / "deposit-files.json").read_text(encoding="utf-8"))
    assert "deposits" not in index
    fresh = AuthoringWorkspace(root=tmp_path, registry_url=None)  # a new session

    with pytest.warns(UserWarning, match="NEW VERSION"):
        result = _deposit(fresh, publish=True)

    assert result.published
    assert zenodo.deposit(int(result.record_id)).files["cycling.csv"] == data
    new_url = f"{HOSTS['production']}/records/{result.record_id}/files/cycling.csv"
    assert set(_locations(fresh)) == {new_url}
    state = _state(tmp_path)
    assert state is not None
    assert state["concept_record_id"] == str(published.concept) and state["environment"] == "production"


def test_a_new_version_sends_a_local_file_that_changed(tmp_path: Path, zenodo: _Zenodo) -> None:
    ws = _workspace(tmp_path)
    data_file = tmp_path / "C01" / "cycling.csv"
    _deposit(ws, publish=True)
    data_file.write_text(f"{CSV}120,3.6,0.001\n", encoding="utf-8")
    zenodo.requests.clear()

    with pytest.warns(UserWarning, match="NEW VERSION"):
        second = _deposit(ws, publish=True)

    assert zenodo.deposit(int(second.record_id)).files["cycling.csv"] == data_file.read_bytes()
    assert f"PUT /files/bucket-{second.record_id}/cycling.csv" in zenodo.sent()
    index = json.loads((tmp_path / ".battinfo" / "deposit-files.json").read_text(encoding="utf-8"))
    [entry] = index["deposits"]["production"].values()
    assert entry["files"]["cycling.csv"]["md5"] == _md5(data_file.read_bytes())


@pytest.mark.parametrize(
    ("first", "second"),
    [(None, True), (True, True), (False, True), (False, False)],
    ids=["first-deposit", "new-version", "draft-then-publish", "draft-then-draft"],
)
def test_a_local_file_that_changed_is_described_as_the_deposit_holds_it(
    tmp_path: Path, zenodo: _Zenodo, first: bool | None, second: bool
) -> None:
    ws = _workspace(tmp_path)
    data_file = tmp_path / "C01" / "cycling.csv"
    # The record states the size the file had when it was added, as ws.add() writes it for a raw file.
    _edit_datasets(ws, lambda ds: ds["distributions"][0].update(content_size=str(data_file.stat().st_size)))
    if first is not None:
        _deposit(ws, publish=first)
    data_file.write_text(f"{CSV}120,3.6,0.001\n", encoding="utf-8")
    data = data_file.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # a new version or a reused draft says so; not what is tested here
        result = _deposit(ws, publish=second)

    deposit = zenodo.deposit(int(result.record_id))
    assert result.published == second and deposit.files["cycling.csv"] == data
    # The graph, the RO-Crate and the record all state the file the deposit holds.
    [dist] = _member_distributions(zenodo.graph(int(result.record_id)))
    assert dist["spdx:checksum"]["spdx:checksumValue"] == sha256
    assert dist["dcat:byteSize"] == len(data)
    crate = _crate_file(deposit, "cycling.csv")
    assert (crate["sha256"], crate["contentSize"]) == (sha256, str(len(data)))
    [(_path, record)] = _datasets(ws)
    [saved] = record["dataset"]["distributions"]
    assert saved["checksum"] == {"algorithm": "sha256", "value": sha256}
    assert saved["content_size"] == str(len(data))
    ws.save()  # the datasets in memory carry the new checksum too
    [(_path, record)] = _datasets(ws)
    assert record["dataset"]["distributions"][0]["checksum"]["value"] == sha256


@pytest.mark.parametrize("owner", ["someone-else", "this-account"])
def test_a_url_in_another_zenodo_record_stays_a_link(tmp_path: Path, zenodo: _Zenodo, owner: str) -> None:
    ws = _workspace(tmp_path)
    _deposit(ws, publish=True)
    # Zenodo shows no one else's deposit to this account; another record of
    # this account is a deposit of another concept.
    record = zenodo.create(files={"raw run.ndax": b"raw"}, published=True).id if owner == "this-account" else 1234567
    elsewhere = f"{HOSTS['production']}/records/{record}/files/raw%20run.ndax"
    _edit_datasets(
        ws,
        lambda ds: ds["distributions"].append(
            {"content_url": elsewhere, "encoding_format": "application/octet-stream", "role": "raw"}
        ),
    )
    zenodo.requests.clear()

    with pytest.warns(UserWarning, match="NEW VERSION"):
        second = _deposit(ws, publish=True)

    assert f"GET /deposit/depositions/{record}" in zenodo.sent()  # asked before anything was created
    assert second.published
    assert set(zenodo.deposit(int(second.record_id)).files) == {
        "cycling.csv",
        "battinfo.json",
        "ro-crate-metadata.json",
    }
    assert elsewhere in _download_urls(zenodo.graph(int(second.record_id)))
    assert elsewhere in _locations(ws)


def test_a_failed_new_version_then_a_retry_keeps_the_data_file(tmp_path: Path, zenodo: _Zenodo) -> None:
    ws = _workspace(tmp_path)
    data = (tmp_path / "C01" / "cycling.csv").read_bytes()
    first = _deposit(ws, publish=True)
    draft_id = zenodo._next["production"]  # the id the new version gets
    zenodo.fail[f"PUT /files/bucket-{draft_id}/battinfo.json"] = 1

    with pytest.warns(UserWarning, match="NEW VERSION"), pytest.raises(ZenodoError, match="battinfo.json"):
        _deposit(ws, publish=True)

    state = _state(tmp_path)
    assert state is not None and state["record_id"] == str(draft_id) and state["published"] is False
    assert zenodo.deposit(draft_id).files["cycling.csv"] == data  # nothing removed it
    zenodo.requests.clear()

    with pytest.warns(UserWarning, match="unpublished draft"):
        retry = _deposit(ws, publish=True)

    assert retry.published and retry.record_id == str(draft_id)
    assert not any("newversion" in line for line in zenodo.sent())
    assert zenodo.deposit(draft_id).files["cycling.csv"] == data
    assert set(_locations(ws)) == {f"{HOSTS['production']}/records/{draft_id}/files/cycling.csv"}
    assert first.record_id != retry.record_id


def test_deleting_the_state_then_depositing_again_uploads_the_data_file(tmp_path: Path, zenodo: _Zenodo) -> None:
    ws = _workspace(tmp_path)
    data = (tmp_path / "C01" / "cycling.csv").read_bytes()
    first = _deposit(ws, publish=True)
    (tmp_path / ".battinfo" / "zenodo.json").unlink()
    zenodo.requests.clear()

    second = _deposit(ws, publish=True)

    assert "POST /deposit/depositions" in zenodo.sent()  # a new record, not a version
    assert second.published and second.record_id != first.record_id
    assert zenodo.deposit(int(second.record_id)).files["cycling.csv"] == data
    url = f"{HOSTS['production']}/records/{second.record_id}/files/cycling.csv"
    assert set(_locations(ws)) == {url}
    assert _download_urls(zenodo.graph(int(second.record_id))) == [url]


def test_a_new_record_without_the_local_file_is_refused_before_anything_is_sent(
    tmp_path: Path, zenodo: _Zenodo
) -> None:
    ws = _workspace(tmp_path)
    _deposit(ws, publish=True)
    (tmp_path / ".battinfo" / "zenodo.json").unlink()
    (tmp_path / "C01" / "cycling.csv").unlink()
    zenodo.requests.clear()

    with pytest.raises(RuntimeError, match=r"^Refusing to deposit: 1 distribution data file\(s\) are missing"):
        _deposit(ws)
    assert zenodo.requests == []


def test_a_draft_of_a_new_version_deleted_on_the_website_points_at_its_published_record(
    tmp_path: Path, zenodo: _Zenodo
) -> None:
    ws = _workspace(tmp_path)
    data = (tmp_path / "C01" / "cycling.csv").read_bytes()
    first = _deposit(ws, publish=True)
    with pytest.warns(UserWarning, match="NEW VERSION"):
        draft = _deposit(ws)
    state = _state(tmp_path)
    assert state is not None and state["version_of"] == first.record_id
    del zenodo.deposits["production"][int(draft.record_id)]  # discarded on the website
    zenodo.requests.clear()

    with pytest.raises(ZenodoError) as excinfo:
        _deposit(ws, publish=True)

    message = str(excinfo.value)
    assert message.startswith(f"The draft {draft.record_id} recorded in .battinfo/zenodo.json could not be read")
    assert f"run ws.zenodo(record_id='{first.record_id}') to make a new version of the published record" in message
    assert "delete .battinfo" not in message and message.endswith("Nothing was created on Zenodo.")
    assert excinfo.value.status == 404
    assert zenodo.sent() == [f"GET /deposit/depositions/{draft.record_id}"]

    result = _deposit(ws, record_id=first.record_id, publish=True)

    # A new version of the published record, in its concept: no second record.
    assert result.published and "POST /deposit/depositions" not in zenodo.sent()
    assert zenodo.deposit(int(result.record_id)).concept == zenodo.deposit(int(first.record_id)).concept
    assert zenodo.deposit(int(result.record_id)).files["cycling.csv"] == data
    assert set(_locations(ws)) == {f"{HOSTS['production']}/records/{result.record_id}/files/cycling.csv"}
    state = _state(tmp_path)
    assert state is not None and state["record_id"] == result.record_id and "version_of" not in state


def test_a_draft_of_a_new_record_deleted_on_the_website_names_its_state_file(tmp_path: Path, zenodo: _Zenodo) -> None:
    ws = _workspace(tmp_path)
    data = (tmp_path / "C01" / "cycling.csv").read_bytes()
    draft = _deposit(ws)
    del zenodo.deposits["production"][int(draft.record_id)]

    with pytest.raises(ZenodoError) as excinfo:
        _deposit(ws)

    message = str(excinfo.value)
    assert (
        "nothing of its record was published: delete .battinfo/zenodo.json to start a new record on zenodo.org"
        in message
    )
    assert "record_id=" not in message

    (tmp_path / ".battinfo" / "zenodo.json").unlink()
    result = _deposit(ws, publish=True)
    assert result.published and zenodo.deposit(int(result.record_id)).files["cycling.csv"] == data


def test_a_later_version_keeps_the_name_an_earlier_one_gave_a_file(tmp_path: Path, zenodo: _Zenodo) -> None:
    ws = _workspace(tmp_path, ("C01",))
    first = _deposit(ws, publish=True)
    first_url = f"{HOSTS['production']}/records/{first.record_id}/files/cycling.csv"
    assert set(_locations(ws)) == {first_url}
    # Another cell, whose data file has the same name. Its dataset record
    # comes first, so on order alone its file would take the plain name.
    _data_file(tmp_path, "C10")
    ws.add("cell", spec=ws._ws.cell_specs[0], serial_numbers=["C10"])
    ws.add("test", type="cycling", cell="C10", data="C10/cycling.csv")
    ws.save()
    assert _datasets(ws)[0][1]["dataset"]["distributions"][0]["content_url"].endswith("/C10/cycling.csv")

    with pytest.warns(UserWarning, match="NEW VERSION"):
        second = _deposit(ws, publish=True)

    files = zenodo.deposit(int(second.record_id)).files
    names = sorted(set(files) - {"battinfo.json", "ro-crate-metadata.json"})
    assert len(names) == 2 and "cycling.csv" in names
    [other] = [name for name in names if name != "cycling.csv"]
    assert other.endswith("-cycling.csv")
    assert files["cycling.csv"] == (tmp_path / "C01" / "cycling.csv").read_bytes()
    assert files[other] == (tmp_path / "C10" / "cycling.csv").read_bytes()


# ── Sandbox and production ────────────────────────────────────────────────────


def test_a_sandbox_deposit_never_reaches_the_records_or_the_production_record(
    tmp_path: Path, zenodo: _Zenodo, registry: _Registry, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(tmp_path)
    local = _locations(ws)
    assert all(location.startswith("file:") for location in local)

    draft = _deposit(ws, sandbox=True)
    assert _locations(ws) == local
    with pytest.warns(UserWarning, match="unpublished draft"):
        published = _deposit(ws, sandbox=True, publish=True)
    assert published.published and published.record_id == draft.record_id
    assert zenodo.deposit(int(draft.record_id), "sandbox").files["cycling.csv"]
    assert _locations(ws) == local
    state = _state(tmp_path, "sandbox")
    assert state is not None and state["environment"] == "sandbox" and state["published"] is True
    assert _state(tmp_path) is None  # the record on zenodo.org has a file of its own

    # The registry gets neither a sandbox URL nor a sandbox DOI.
    with pytest.raises(SubmitError, match="files on this computer"):
        ws.submit(**REGISTRY)
    capsys.readouterr()
    ws.submit(allow_local_files=True, resume=False, **REGISTRY)
    assert all(dois == [] for dois in registry.dois().values())
    assert "sandbox.zenodo.org" not in json.dumps(registry.payloads)
    assert "this workspace's Zenodo record is on the sandbox" in capsys.readouterr().out

    # The real deposit goes to production with nothing deleted, as a new record there.
    result = _deposit(ws, publish=True)
    assert "POST /deposit/depositions" in zenodo.sent("production")
    assert set(_locations(ws)) == {f"{HOSTS['production']}/records/{result.record_id}/files/cycling.csv"}
    registry.payloads.clear()
    ws.submit(resume=False, **REGISTRY)
    assert registry.dois()["dataset"] == [result.doi]
    assert _state(tmp_path, "sandbox") == state


def test_a_sandbox_rehearsal_leaves_the_published_record_its_next_version(tmp_path: Path, zenodo: _Zenodo) -> None:
    ws = _workspace(tmp_path)
    data = (tmp_path / "C01" / "cycling.csv").read_bytes()
    first = _deposit(ws, publish=True)
    production_state = _state(tmp_path)
    url = f"{HOSTS['production']}/records/{first.record_id}/files/cycling.csv"

    # A rehearsal on the sandbox, from records that point at the published copies.
    rehearsal = _deposit(ws, sandbox=True)
    with pytest.warns(UserWarning, match="unpublished draft"):
        _deposit(ws, sandbox=True, publish=True)
    assert zenodo.deposit(int(rehearsal.record_id), "sandbox").files["cycling.csv"] == data
    assert set(_locations(ws)) == {url}
    assert _state(tmp_path) == production_state
    zenodo.requests.clear()

    with pytest.warns(UserWarning, match="NEW VERSION"):
        second = _deposit(ws, publish=True)

    # A new version of the published record, not a second record for the same data.
    assert f"POST /deposit/depositions/{first.record_id}/actions/newversion" in zenodo.sent()
    assert "POST /deposit/depositions" not in zenodo.sent()
    assert zenodo.deposit(int(second.record_id)).concept == zenodo.deposit(int(first.record_id)).concept
    assert zenodo.deposit(int(second.record_id)).files["cycling.csv"] == data


def test_a_sandbox_record_an_earlier_build_kept_in_the_production_file_moves_to_its_own(
    tmp_path: Path, zenodo: _Zenodo
) -> None:
    ws = _workspace(tmp_path)
    sandbox_record = zenodo.create("sandbox", files={"cycling.csv": b"old"}, published=True)
    legacy = {
        "record_id": str(sandbox_record.id),
        "doi": f"10.5072/zenodo.{sandbox_record.id}",
        "published": True,
        "sandbox": True,
    }
    (tmp_path / ".battinfo" / "zenodo.json").write_text(json.dumps(legacy), encoding="utf-8")

    # On zenodo.org the workspace has no record yet.
    result = _deposit(ws, publish=True)
    assert "POST /deposit/depositions" in zenodo.sent("production")
    state = _state(tmp_path)
    assert state is not None and state["environment"] == "production" and state["record_id"] == result.record_id
    assert _state(tmp_path, "sandbox") == {
        "record_id": str(sandbox_record.id),
        "doi": legacy["doi"],
        "published": True,
        "environment": "sandbox",
    }

    # On the sandbox the next deposit continues the record the earlier build made.
    with pytest.warns(UserWarning, match="NEW VERSION"):
        _deposit(ws, sandbox=True)
    assert f"POST /deposit/depositions/{sandbox_record.id}/actions/newversion" in zenodo.sent("sandbox")


def test_publish_to_zenodo_reads_the_state_before_it_saves(
    tmp_path: Path, zenodo: _Zenodo, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(tmp_path)
    path = tmp_path / ".battinfo" / "zenodo.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("ZENODO_API_TOKEN", "placeholder")
    saves: list[str] = []
    monkeypatch.setattr(ws, "save", lambda *args, **kwargs: saves.append("save"))

    with pytest.raises(DepositIndexError, match="zenodo.json cannot be read"):
        ws.publish(zenodo=True, creators=CREATORS)
    assert saves == [] and zenodo.requests == []
    assert path.read_text(encoding="utf-8") == "{not json"


def test_a_sandbox_publish_without_r2_is_refused_before_anything_is_saved(
    tmp_path: Path, zenodo: _Zenodo, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(tmp_path)
    monkeypatch.setenv("ZENODO_SANDBOX_TOKEN", "placeholder")
    saves: list[str] = []
    monkeypatch.setattr(ws, "save", lambda *args, **kwargs: saves.append("save"))

    with pytest.raises(ValueError, match="a sandbox deposit is a dry run") as excinfo:
        ws.publish(zenodo=True, sandbox=True, creators=CREATORS)
    assert "ws.zenodo(sandbox=True)" in str(excinfo.value)
    assert saves == [] and zenodo.requests == []


def test_a_sandbox_url_in_a_production_deposit_is_refused(tmp_path: Path, zenodo: _Zenodo) -> None:
    ws = _workspace(tmp_path)
    url = f"{HOSTS['sandbox']}/records/501/files/cycling.csv"
    for path, record in _datasets(ws):
        record["dataset"]["distributions"][0]["content_url"] = url
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    with pytest.raises(RuntimeError) as excinfo:
        _deposit(ws)
    message = str(excinfo.value)
    assert message.startswith("Refusing to deposit: 1 record(s) would go into the deposit incomplete: ")
    assert f"its data file is at {url}, in a record on the Zenodo sandbox (sandbox.zenodo.org)" in message
    assert zenodo.requests == []


# ── R2 storage ────────────────────────────────────────────────────────────────


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


def _fake_r2(monkeypatch: pytest.MonkeyPatch) -> _FakeS3:
    """R2 storage configured, with a _FakeS3 standing in for the boto3 client."""
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
        ("R2_BUCKET_PRIVATE", "pb"),
        ("R2_PUBLIC_BASE_URL", "https://pub.example"),
    ):
        monkeypatch.setenv(name, value)
    return s3


R2_REFUSAL = "the deposit would archive data files hosted in R2 storage."


@pytest.mark.parametrize("public", [True, False], ids=["public-bucket", "private-bucket"])
def test_a_deposit_of_files_on_r2_is_refused_before_any_request(
    tmp_path: Path, zenodo: _Zenodo, monkeypatch: pytest.MonkeyPatch, public: bool
) -> None:
    _fake_r2(monkeypatch)
    ws = _workspace(tmp_path)
    [r2_url] = ws.upload(public=public)
    assert r2_url.startswith("https://pub.example/datasets/" if public else "s3://pb/datasets/")

    with pytest.raises(ValueError) as excinfo:
        _deposit(ws, publish=True)

    message = str(excinfo.value)
    assert message.startswith(f"Refusing to publish: {R2_REFUSAL}")
    assert f"The dataset records point at these copies ws.upload() made: {r2_url}." in message
    assert "pass archive_hosted_files=True" in message
    assert message.endswith("Nothing was sent to Zenodo.")
    assert zenodo.requests == [] and _state(tmp_path) is None
    assert set(_locations(ws)) == {r2_url}


def test_publish_with_r2_storage_is_refused_before_the_upload(
    tmp_path: Path, zenodo: _Zenodo, registry: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With R2 configured, ws.publish(zenodo=True) would put the files in R2 and then archive them."""
    s3 = _fake_r2(monkeypatch)
    monkeypatch.setenv("ZENODO_API_TOKEN", "placeholder")
    ws = _workspace(tmp_path)

    with pytest.raises(ValueError) as excinfo:
        ws.publish(zenodo=True, creators=CREATORS)

    message = str(excinfo.value)
    assert message.startswith(f"Refusing to publish: {R2_REFUSAL}")
    assert f"ws.upload() before the deposit: {Path('C01') / 'cycling.csv'}." in message
    assert "pass archive_hosted_files=True" in message
    assert "To let Zenodo host the files instead, run ws.zenodo(publish=True), then ws.submit()." in message
    assert message.endswith("Nothing was uploaded, deposited or sent.")
    assert s3.objects == {} and zenodo.requests == [] and registry.payloads == []
    assert all(location.startswith("file:") for location in _locations(ws))


def test_publish_with_the_flag_puts_the_files_in_r2_and_archives_them(
    tmp_path: Path, zenodo: _Zenodo, registry: _Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    s3 = _fake_r2(monkeypatch)
    for name, value in (
        ("ZENODO_API_TOKEN", "placeholder"),
        ("BATTINFO_REGISTRY_URL", REGISTRY["registry_url"]),
        ("BATTINFO_API_KEY", "k"),
        ("BATTINFO_WORKSPACE_ID", "w"),
        ("BATTINFO_PUBLISHER_ID", "p"),
    ):
        monkeypatch.setenv(name, value)
    ws = _workspace(tmp_path)
    data = (tmp_path / "C01" / "cycling.csv").read_bytes()

    outcomes = ws.publish(zenodo=True, creators=CREATORS, archive_hosted_files=True)

    assert outcomes and all(outcome["ok"] for outcome in outcomes)
    [r2_url] = set(_locations(ws))
    assert r2_url.startswith("https://pub.example/datasets/") and len(s3.objects) == 1
    state = _state(tmp_path)
    assert state is not None and state["published"] is True
    assert zenodo.deposit(int(state["record_id"])).files["cycling.csv"] == data
    sent = json.dumps(registry.payloads)
    assert r2_url in sent and "file:" not in sent


def test_the_flag_archives_files_on_r2_and_warns_for_the_private_ones(
    tmp_path: Path, zenodo: _Zenodo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_r2(monkeypatch)
    ws = _workspace(tmp_path, ("C01", "C02"))
    c02 = tmp_path / "C02" / "cycling.csv"
    data = sorted(path.read_bytes() for path in (tmp_path / "C01" / "cycling.csv", c02))
    # C02's file is away during the private upload, so only C01 goes to the private bucket.
    away = c02.rename(tmp_path / "away.csv")
    ws.upload(public=False)
    away.rename(c02)
    ws.upload()
    locations = set(_locations(ws))
    [private_url] = [url for url in locations if url.startswith("s3://pb/")]
    [public_url] = [url for url in locations if url.startswith("https://pub.example/")]
    assert locations == {private_url, public_url}
    capsys.readouterr()

    with pytest.warns(UserWarning, match="private R2 bucket") as caught:
        result = _deposit(ws, publish=True, archive_hosted_files=True)

    assert result.published
    [warning] = [str(item.message) for item in caught if "private R2 bucket" in str(item.message)]
    assert warning.startswith("The deposit archives 1 data file(s) that ws.upload(public=False) put in the")
    assert warning.endswith(f"and it makes them public: {private_url}")
    out = capsys.readouterr().out
    assert f"WARNING: the deposit makes 1 data file(s) from the private R2 bucket public:\n    {private_url}\n" in out
    assert public_url not in out
    # Both files are archived from their local files; the records keep the R2 URLs.
    deposit = zenodo.deposit(int(result.record_id))
    assert sorted(content for name, content in deposit.files.items() if name.endswith("cycling.csv")) == data
    graph_urls = _download_urls(zenodo.graph(int(result.record_id)))
    assert len(graph_urls) == 2 and all(url.startswith(f"{HOSTS['production']}/records/") for url in graph_urls)
    assert set(_locations(ws)) == locations
    ws.save()
    assert set(_locations(ws)) == locations


def test_the_index_marks_a_copy_in_the_private_bucket(
    tmp_path: Path, zenodo: _Zenodo, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_r2(monkeypatch)
    ws = _workspace(tmp_path)
    [r2_url] = ws.upload(public=False)
    path = tmp_path / ".battinfo" / "deposit-files.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    assert index["hosted"][r2_url]["private"] is True

    index["hosted"][r2_url]["private"] = "yes"
    content = json.dumps(index)
    path.write_text(content, encoding="utf-8")
    with pytest.raises(DepositIndexError, match="has a 'private' that is not true or false"):
        _deposit(ws, archive_hosted_files=True)
    assert zenodo.requests == [] and path.read_text(encoding="utf-8") == content


# ── Copies whose local file the workspace does not know ───────────────────────


def test_records_an_earlier_build_pointed_at_r2_are_refused_not_linked(
    tmp_path: Path, zenodo: _Zenodo, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_r2(monkeypatch)
    ws = _workspace(tmp_path)
    [r2_url] = ws.upload()
    # An earlier build kept no record of the local file behind its R2 copies.
    path = tmp_path / ".battinfo" / "deposit-files.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    del index["hosted"]
    path.write_text(json.dumps(index), encoding="utf-8")
    assert ws.upload() == [r2_url]  # as ws.publish(zenodo=True) runs it: nothing to record

    with pytest.raises(RuntimeError) as excinfo:
        _deposit(ws, publish=True)

    message = str(excinfo.value)
    assert f"its data file is at {r2_url}, a copy ws.upload() made in R2 storage" in message
    assert message.endswith("Nothing was sent to Zenodo.") and zenodo.requests == []


@pytest.mark.parametrize(
    ("url", "public_base", "why"),
    [
        ("https://cdn.example/datasets/{short_id}/cycling.csv", "", "a copy ws.upload() made in R2 storage"),
        ("https://cdn.example/archive/cycling.csv", "https://cdn.example", "a copy ws.upload() made in R2 storage"),
        (
            "s3://battinfo-public/datasets/{short_id}/cycling.csv",
            "",
            "in object storage that a reader of the deposit cannot open",
        ),
    ],
    ids=["upload-key", "configured-base", "s3"],
)
def test_a_copy_an_earlier_build_uploaded_without_its_local_file_is_refused(
    tmp_path: Path, zenodo: _Zenodo, monkeypatch: pytest.MonkeyPatch, url: str, public_base: str, why: str
) -> None:
    """Records an earlier build pointed at R2, before ws.upload() recorded the local file behind each copy."""
    if public_base:
        monkeypatch.setenv("R2_PUBLIC_BASE_URL", public_base)
    else:
        monkeypatch.delenv("R2_PUBLIC_BASE_URL", raising=False)
    ws = _workspace(tmp_path)
    [(_path, record)] = _datasets(ws)
    url = url.format(short_id=record["dataset"]["short_id"])
    _point_datasets_at(ws, url)

    with pytest.raises(RuntimeError) as excinfo:
        _deposit(ws, publish=True)

    message = str(excinfo.value)
    assert message.startswith("Refusing to publish: 1 record(s) would go into the deposit incomplete: ")
    assert f"dataset {record['dataset']['id']}: its data file is at {url}, {why}" in message
    assert "Point the dataset at its local file again" in message
    assert message.endswith("Nothing was sent to Zenodo.")
    assert zenodo.requests == []


@pytest.mark.parametrize("continued", ["state", "record-id"])
def test_a_file_in_an_unrecorded_version_of_the_workspace_record_is_refused(
    tmp_path: Path, zenodo: _Zenodo, continued: str
) -> None:
    """An earlier build made v1 and v2 without recording them; v2 lost the data, and the records still name v1."""
    ws = _workspace(tmp_path)
    data = (tmp_path / "C01" / "cycling.csv").read_bytes()
    v1 = zenodo.create(files={"cycling.csv": data, "battinfo.json": b"{}"}, published=True)
    v2 = zenodo.create(files={"battinfo.json": b"{}"}, concept=v1.concept, published=True)
    url = f"{HOSTS['production']}/records/{v1.id}/files/cycling.csv"
    _point_datasets_at(ws, url)
    if continued == "state":  # as the earlier build wrote it
        (tmp_path / ".battinfo" / "zenodo.json").write_text(
            json.dumps(
                {"record_id": str(v2.id), "doi": f"10.5281/zenodo.{v2.id}", "published": True, "sandbox": False}
            ),
            encoding="utf-8",
        )
    fresh = AuthoringWorkspace(root=tmp_path, registry_url=None)  # a new session

    [(_path, record)] = _datasets(fresh)

    with pytest.raises(RuntimeError) as excinfo:
        if continued == "state":
            _deposit(fresh, publish=True)
        else:
            _deposit(fresh, publish=True, record_id=str(v2.id))

    message = str(excinfo.value)
    assert message.startswith(
        "Refusing to deposit: 1 distribution(s) point at a copy on Zenodo whose local "
        "file this workspace has no record of, and the deposit cannot link to it: "
    )
    assert (
        f"dataset {record['dataset']['id']}: {url} is in the record {v1.id}, a version of this "
        f"workspace's own Zenodo record (concept {v1.concept} on zenodo.org) that the workspace never "
        "recorded"
    ) in message
    assert "Point each dataset at its local file again (ws.add(..., data=...), then ws.save())" in message
    assert message.endswith("Nothing was created on Zenodo.")
    # Zenodo was asked about the record, then about the record the deposit
    # continues, to compare their concepts; nothing was created or changed.
    assert zenodo.sent() == [f"GET /deposit/depositions/{v1.id}", f"GET /deposit/depositions/{v2.id}"]


@pytest.mark.parametrize("entry", ["zenodo", "publish"])
def test_records_on_a_draft_no_run_recorded_are_refused_in_a_new_session(
    tmp_path: Path, zenodo: _Zenodo, registry: _Registry, monkeypatch: pytest.MonkeyPatch, entry: str
) -> None:
    """An earlier build's publish run failed after it had pointed the records at its draft, and recorded nothing."""
    ws = _workspace(tmp_path)
    data = (tmp_path / "C01" / "cycling.csv").read_bytes()
    orphan = zenodo.create(files={"cycling.csv": data})  # a draft of this account, never published
    url = f"{HOSTS['production']}/records/{orphan.id}/files/cycling.csv"
    _point_datasets_at(ws, url)
    assert _state(tmp_path) is None
    for name, value in (
        ("ZENODO_API_TOKEN", "placeholder"),
        ("BATTINFO_API_KEY", "k"),
        ("BATTINFO_WORKSPACE_ID", "w"),
        ("BATTINFO_PUBLISHER_ID", "p"),
    ):
        monkeypatch.setenv(name, value)
    fresh = AuthoringWorkspace(root=tmp_path, registry_url=REGISTRY["registry_url"])  # a new session
    [(_path, record)] = _datasets(fresh)

    def run() -> object:
        if entry == "zenodo":
            return _deposit(fresh, publish=True)
        return fresh.publish(zenodo=True, creators=CREATORS)

    with pytest.raises(RuntimeError) as excinfo:
        run()

    message = str(excinfo.value)
    assert message.startswith("Refusing to deposit: 1 distribution(s) point at a copy on Zenodo")
    assert (
        f"dataset {record['dataset']['id']}: {url} is in the draft {orphan.id} on zenodo.org, which this "
        "Zenodo account has not published, so no reader can download it"
    ) in message
    assert "Point each dataset at its local file again (ws.add(..., data=...), then ws.save())" in message
    assert message.endswith("Nothing was created on Zenodo.")
    assert zenodo.sent() == [f"GET /deposit/depositions/{orphan.id}"]
    assert registry.payloads == [] and _state(tmp_path) is None

    # The way on the refusal names: the dataset takes its local file again.
    fresh.add("test", type="cycling", cell="C01", data="C01/cycling.csv")
    fresh.save()
    run()

    state = _state(tmp_path)
    assert state is not None and state["published"] is True and state["record_id"] != str(orphan.id)
    assert zenodo.deposit(int(state["record_id"])).files["cycling.csv"] == data
    new_url = f"{HOSTS['production']}/records/{state['record_id']}/files/cycling.csv"
    assert set(_locations(fresh)) == {new_url}
    assert _download_urls(zenodo.graph(int(state["record_id"]))) == [new_url]
    if entry == "publish":
        assert new_url in json.dumps(registry.payloads) and str(orphan.id) not in json.dumps(registry.payloads)


def test_a_file_in_an_unpublished_draft_of_this_account_is_refused_not_linked(tmp_path: Path, zenodo: _Zenodo) -> None:
    """The deposit continues its own record; a distribution points at a draft of this account in another concept."""
    ws = _workspace(tmp_path)
    first = _deposit(ws, publish=True)
    other = zenodo.create(files={"raw run.ndax": b"raw"})
    elsewhere = f"{HOSTS['production']}/records/{other.id}/files/raw%20run.ndax"
    _edit_datasets(
        ws,
        lambda ds: ds["distributions"].append(
            {"content_url": elsewhere, "encoding_format": "application/octet-stream", "role": "raw"}
        ),
    )
    zenodo.requests.clear()

    with pytest.raises(RuntimeError) as excinfo:
        _deposit(ws, publish=True)

    message = str(excinfo.value)
    assert (
        f"{elsewhere} is in the draft {other.id} on zenodo.org, which this Zenodo account has not published"
    ) in message
    assert message.endswith("Nothing was created on Zenodo.")
    # Asked about that record only: a draft needs no comparison of concepts.
    assert zenodo.sent() == [f"GET /deposit/depositions/{other.id}"]
    assert _state(tmp_path)["record_id"] == first.record_id  # type: ignore[index]


def test_a_first_deposit_asks_zenodo_about_a_record_it_cannot_place(tmp_path: Path, zenodo: _Zenodo) -> None:
    """With no record of its own yet, a link to anyone else's Zenodo record stays a link."""
    ws = _workspace(tmp_path)
    elsewhere = f"{HOSTS['production']}/records/1234567/files/raw%20run.ndax"
    _edit_datasets(
        ws,
        lambda ds: ds["distributions"].append(
            {"content_url": elsewhere, "encoding_format": "application/octet-stream", "role": "raw"}
        ),
    )

    result = _deposit(ws, publish=True)

    assert zenodo.sent()[0] == "GET /deposit/depositions/1234567"  # before anything was created
    assert result.published and elsewhere in _download_urls(zenodo.graph(int(result.record_id)))


# ── Copies the deposit keeps, with no local file to send ──────────────────────


def test_a_record_on_a_published_copy_its_version_lacks_is_refused_before_a_draft_exists(
    tmp_path: Path, zenodo: _Zenodo
) -> None:
    """An earlier build published v1 without its data file, and pointed the records at v1's copy."""
    ws = _workspace(tmp_path)
    data = (tmp_path / "C01" / "cycling.csv").read_bytes()
    v1 = zenodo.create(files={"battinfo.json": b"{}", "ro-crate-metadata.json": b"{}"}, published=True)
    url = f"{HOSTS['production']}/records/{v1.id}/files/cycling.csv"
    _point_datasets_at(ws, url)
    (tmp_path / ".battinfo" / "zenodo.json").write_text(
        json.dumps({"record_id": str(v1.id), "doi": f"10.5281/zenodo.{v1.id}", "published": True, "sandbox": False}),
        encoding="utf-8",
    )
    fresh = AuthoringWorkspace(root=tmp_path, registry_url=None)  # a new session
    [(_path, record)] = _datasets(fresh)

    for _attempt in range(2):  # a re-run is refused the same way, and leaves nothing behind
        zenodo.requests.clear()
        with pytest.raises(RuntimeError) as excinfo:
            _deposit(fresh, publish=True)
        message = str(excinfo.value)
        assert message.startswith(
            f"Refusing to deposit: the published record {v1.id} that this deposit makes a "
            "new version of does not hold 1 data file(s)"
        )
        assert f"dataset {record['dataset']['id']}: {url} (cycling.csv is not on it)" in message
        assert (
            "Point each dataset at its local file again (ws.add(..., data=...), then ws.save()), then re-run."
        ) in message
        assert "updates it" not in message and message.endswith("Nothing was created or changed on Zenodo.")
        assert zenodo.sent() == [f"GET /deposit/depositions/{v1.id}/files"]
    assert set(zenodo.deposits["production"]) == {v1.id}  # no draft was made

    fresh.add("test", type="cycling", cell="C01", data="C01/cycling.csv")
    fresh.save()
    with pytest.warns(UserWarning, match="NEW VERSION"):
        result = _deposit(fresh, publish=True)

    assert result.published and zenodo.deposit(int(result.record_id)).files["cycling.csv"] == data
    assert zenodo.deposit(int(result.record_id)).concept == v1.concept


def test_a_draft_deleted_on_the_website_leaves_the_published_copy_its_checksums(
    tmp_path: Path, zenodo: _Zenodo
) -> None:
    """A draft of a new version took a changed file; the draft was discarded, then the local file deleted."""
    ws = _workspace(tmp_path)
    data_file = tmp_path / "C01" / "cycling.csv"
    published = data_file.read_bytes()
    first = _deposit(ws, publish=True)
    data_file.write_text(f"{CSV}120,3.6,0.001\n", encoding="utf-8")
    changed = data_file.read_bytes()
    with pytest.warns(UserWarning, match="NEW VERSION"):
        draft = _deposit(ws)
    index = json.loads((tmp_path / ".battinfo" / "deposit-files.json").read_text(encoding="utf-8"))
    [entry] = index["deposits"]["production"].values()
    # The draft's file is kept apart from the published version's until the draft is published.
    assert entry["files"]["cycling.csv"]["md5"] == _md5(published)
    assert entry["drafts"][draft.record_id]["cycling.csv"]["md5"] == _md5(changed)
    del zenodo.deposits["production"][int(draft.record_id)]  # discarded on the website
    data_file.unlink()

    # The way on the deleted draft's message names: a new version of the published record.
    result = _deposit(ws, record_id=first.record_id, publish=True)

    assert result.published and zenodo.deposit(int(result.record_id)).files["cycling.csv"] == published
    [dist] = _member_distributions(zenodo.graph(int(result.record_id)))
    assert dist["spdx:checksum"]["spdx:checksumValue"] == hashlib.sha256(published).hexdigest()
    assert dist["dcat:byteSize"] == len(published)
    [(_path, record)] = _datasets(ws)
    [saved] = record["dataset"]["distributions"]
    assert saved["content_url"] == f"{HOSTS['production']}/records/{result.record_id}/files/cycling.csv"
    assert saved["checksum"] == {"algorithm": "sha256", "value": hashlib.sha256(published).hexdigest()}


def test_publishing_a_draft_after_its_local_file_is_deleted_keeps_the_copy_the_draft_holds(
    tmp_path: Path, zenodo: _Zenodo
) -> None:
    """A draft of a new version took a changed file, and the records stayed on the published copy."""
    ws = _workspace(tmp_path)
    data_file = tmp_path / "C01" / "cycling.csv"
    _deposit(ws, publish=True)
    data_file.write_text(f"{CSV}120,3.6,0.001\n", encoding="utf-8")
    changed = data_file.read_bytes()
    with pytest.warns(UserWarning, match="NEW VERSION"):
        draft = _deposit(ws)
    data_file.unlink()

    with pytest.warns(UserWarning, match="unpublished draft"):
        result = _deposit(ws, publish=True)

    sha256 = hashlib.sha256(changed).hexdigest()
    assert result.record_id == draft.record_id and result.published
    assert zenodo.deposit(int(result.record_id)).files["cycling.csv"] == changed
    [dist] = _member_distributions(zenodo.graph(int(result.record_id)))
    assert dist["spdx:checksum"]["spdx:checksumValue"] == sha256
    [(_path, record)] = _datasets(ws)
    [saved] = record["dataset"]["distributions"]
    assert saved["content_url"] == f"{HOSTS['production']}/records/{result.record_id}/files/cycling.csv"
    assert saved["checksum"] == {"algorithm": "sha256", "value": sha256}
    # Published, the draft's files are those of the published versions.
    index = json.loads((tmp_path / ".battinfo" / "deposit-files.json").read_text(encoding="utf-8"))
    [entry] = index["deposits"]["production"].values()
    assert entry["files"]["cycling.csv"]["md5"] == _md5(changed) and "drafts" not in entry


def test_a_new_version_whose_draft_lacks_a_kept_copy_names_the_dataset(
    tmp_path: Path, zenodo: _Zenodo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Should Zenodo make a new version without the files of the one before, the run says how to go on."""
    ws = _workspace(tmp_path)
    first = _deposit(ws, publish=True)
    url = f"{HOSTS['production']}/records/{first.record_id}/files/cycling.csv"
    (tmp_path / "C01" / "cycling.csv").unlink()
    create = zenodo.create

    def create_without_copies(
        environment: str = "production",
        *,
        files: dict[str, bytes] | None = None,
        concept: int | None = None,
        published: bool = False,
    ) -> _Deposit:
        return create(environment, files=None if concept is not None else files, concept=concept, published=published)

    monkeypatch.setattr(zenodo, "create", create_without_copies)
    [(_path, record)] = _datasets(ws)

    with pytest.warns(UserWarning, match="NEW VERSION"), pytest.raises(ZenodoError) as excinfo:
        _deposit(ws, publish=True)

    state = _state(tmp_path)
    assert state is not None and state["published"] is False
    message = str(excinfo.value)
    assert message.startswith(
        f"Refusing to deposit: the draft https://zenodo.org/deposit/{state['deposit_id']} does not hold 1 data file(s)"
    )
    assert f"dataset {record['dataset']['id']}: {url} (cycling.csv is not on it)" in message
    assert "updates it" not in message
    assert message.endswith("No file on the draft was changed, and the draft is recorded in .battinfo/zenodo.json.")
    assert zenodo.deposit(int(first.record_id)).files["cycling.csv"]  # the published copy is untouched


def test_a_pending_draft_of_a_new_version_publishes_after_the_index_is_deleted(tmp_path: Path, zenodo: _Zenodo) -> None:
    """The records stay on the published copy while the draft is pending; the draft holds the file too."""
    ws = _workspace(tmp_path)
    data = (tmp_path / "C01" / "cycling.csv").read_bytes()
    first = _deposit(ws, publish=True)
    with pytest.warns(UserWarning, match="NEW VERSION"):
        draft = _deposit(ws)
    assert _state(tmp_path)["version_of"] == first.record_id  # type: ignore[index]
    (tmp_path / ".battinfo" / "deposit-files.json").unlink()  # as its unreadable-file message offers
    zenodo.requests.clear()

    with pytest.warns(UserWarning, match="unpublished draft"):
        result = _deposit(ws, publish=True)

    assert result.record_id == draft.record_id and result.published
    assert zenodo.deposit(int(result.record_id)).files["cycling.csv"] == data
    # The published record the draft was made from is known from the state: no question about it.
    assert f"GET /deposit/depositions/{first.record_id}" not in zenodo.sent()
    assert set(_locations(ws)) == {f"{HOSTS['production']}/records/{draft.record_id}/files/cycling.csv"}


# ── The client ────────────────────────────────────────────────────────────────


def test_sync_files_keeps_a_copy_it_has_no_local_file_for(tmp_path: Path, zenodo: _Zenodo) -> None:
    deposit = zenodo.create(files={"kept.csv": b"kept", "old.txt": b"old", "battinfo.json": b"{}"})
    graph = tmp_path / "battinfo.json"
    graph.write_text('{"new": true}', encoding="utf-8")
    client = ZenodoClient(token="placeholder")

    result = client.sync_files(deposit.id, {graph: "battinfo.json"}, keep={"kept.csv": _md5(b"kept")})

    assert result == {"uploaded": ["battinfo.json"], "kept": ["kept.csv"], "removed": ["old.txt"]}
    assert deposit.files == {"kept.csv": b"kept", "battinfo.json": b'{"new": true}'}


@pytest.mark.parametrize("keep", [{"kept.csv": "0" * 32}, {"absent.csv": ""}], ids=["other-md5", "absent"])
def test_sync_files_refuses_before_changing_anything_when_a_kept_copy_is_wrong(
    tmp_path: Path, zenodo: _Zenodo, keep: dict[str, str]
) -> None:
    deposit = zenodo.create(files={"kept.csv": b"kept", "old.txt": b"old"})
    new = tmp_path / "new.csv"
    new.write_text("new", encoding="utf-8")
    client = ZenodoClient(token="placeholder")

    with pytest.raises(KeptFilesError, match="does not hold the files that have no local copy") as excinfo:
        client.sync_files(deposit.id, {new: "new.csv"}, keep=keep)

    assert isinstance(excinfo.value, ZenodoError) and set(excinfo.value.files) == set(keep)
    assert "Nothing on the deposit was changed." in str(excinfo.value)
    assert deposit.files == {"kept.csv": b"kept", "old.txt": b"old"}
    assert [line for line in zenodo.sent() if not line.startswith("GET ")] == []


def test_sync_files_and_upload_files_refuse_a_missing_local_file_before_sending(
    tmp_path: Path, zenodo: _Zenodo
) -> None:
    deposit = zenodo.create(files={"old.txt": b"old"})
    client = ZenodoClient(token="placeholder")
    missing = tmp_path / "gone.csv"

    with pytest.raises(FileNotFoundError, match="gone.csv"):
        client.sync_files(deposit.id, {missing: "gone.csv"})
    with pytest.raises(FileNotFoundError, match="no local file for gone.csv"):
        client.upload_files(deposit.id, {missing: "gone.csv"})
    assert zenodo.requests == [] and deposit.files == {"old.txt": b"old"}


# ── The files that record the deposits ────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://zenodo.org/records/7001/files/cycling.csv", ("production", "7001", "cycling.csv")),
        ("https://zenodo.org/record/7001/files/cell%2001.csv?download=1", ("production", "7001", "cell 01.csv")),
        ("https://sandbox.zenodo.org/records/501/files/raw/run%231.csv", ("sandbox", "501", "raw/run#1.csv")),
        ("https://ZENODO.org:443/records/7001/files/a.csv", ("production", "7001", "a.csv")),
        ("https://zenodo.org/records/7001", None),
        ("https://zenodo.org/records/abc/files/a.csv", None),
        ("https://zenodo.org:8443/records/7001/files/a.csv", None),
        ("https://zenodo.org.example/records/7001/files/a.csv", None),
        ("file:///C:/data/a.csv", None),
        (None, None),
    ],
)
def test_a_zenodo_file_url_is_read_for_its_environment_record_and_name(
    url: object, expected: tuple[str, str, str] | None
) -> None:
    from battinfo._deposit_index import parse_zenodo_file_url

    parsed = parse_zenodo_file_url(url)
    assert (None if parsed is None else (parsed.environment, parsed.record_id, parsed.name)) == expected


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        '{"doi": "10.5281/zenodo.1"}',
        '{"record_id": "7", "environment": "staging"}',
        '{"record_id": "7", "published": "yes"}',
    ],
    ids=["not-json", "list", "no-record", "environment", "published"],
)
def test_a_state_that_cannot_be_read_stops_the_deposit_and_is_left_as_it_is(
    tmp_path: Path, zenodo: _Zenodo, content: str
) -> None:
    ws = _workspace(tmp_path)
    path = tmp_path / ".battinfo" / "zenodo.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(DepositIndexError, match="zenodo.json cannot be read") as excinfo:
        _deposit(ws)
    assert "delete it to start a new record on zenodo.org" in str(excinfo.value)
    assert zenodo.requests == [] and path.read_text(encoding="utf-8") == content


def test_a_sandbox_state_file_that_names_a_production_record_is_refused(tmp_path: Path, zenodo: _Zenodo) -> None:
    ws = _workspace(tmp_path)
    path = tmp_path / ".battinfo" / "zenodo-sandbox.json"
    content = json.dumps({"record_id": "7001", "environment": "production"})
    path.write_text(content, encoding="utf-8")

    with pytest.raises(DepositIndexError, match="zenodo-sandbox.json cannot be read") as excinfo:
        _deposit(ws, sandbox=True)
    assert "it is the file of the sandbox record" in str(excinfo.value)
    assert "start a new record on sandbox.zenodo.org" in str(excinfo.value)
    assert zenodo.requests == [] and path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize(
    "deposits",
    [
        [],
        {"staging": {}},
        {"production": {"7000": {"records": [7001]}}},
        {"production": {"7000": {"files": {"a.csv": {"path": 3}}}}},
        {"production": {"7000": {"drafts": {"7001": {"a.csv": {"md5": 5}}}}}},
    ],
    ids=["list", "environment", "record-ids", "path", "draft-md5"],
)
def test_an_index_whose_deposits_cannot_be_read_stops_the_deposit(
    tmp_path: Path, zenodo: _Zenodo, deposits: object
) -> None:
    ws = _workspace(tmp_path)
    path = tmp_path / ".battinfo" / "deposit-files.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    index["deposits"] = deposits
    content = json.dumps(index)
    path.write_text(content, encoding="utf-8")

    with pytest.raises(DepositIndexError, match="deposit-files.json cannot be read"):
        _deposit(ws)
    assert zenodo.requests == [] and path.read_text(encoding="utf-8") == content


def test_the_index_records_each_deposited_file_by_environment_and_concept(tmp_path: Path, zenodo: _Zenodo) -> None:
    ws = _workspace(tmp_path)
    data_file = tmp_path / "C01" / "cycling.csv"
    data = data_file.read_bytes()
    first = _deposit(ws, publish=True)
    with pytest.warns(UserWarning, match="NEW VERSION"):
        second = _deposit(ws, publish=True)

    index = json.loads((tmp_path / ".battinfo" / "deposit-files.json").read_text(encoding="utf-8"))
    concept = str(zenodo.deposit(int(first.record_id)).concept)
    entry = index["deposits"]["production"][concept]
    assert entry["records"] == [first.record_id, second.record_id]
    assert entry["files"] == {
        "cycling.csv": {
            "path": str(data_file.resolve()),
            "size": len(data),
            "md5": _md5(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    }
    state = _state(tmp_path)
    assert state is not None
    assert {key: state[key] for key in ("environment", "concept_record_id", "record_id", "published")} == {
        "environment": "production",
        "concept_record_id": concept,
        "record_id": second.record_id,
        "published": True,
    }
