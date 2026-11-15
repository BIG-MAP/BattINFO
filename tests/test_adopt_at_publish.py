"""A record that already exists keeps the IRI it has, at publish too (BIG-MAP/BattINFO#483).

A new workspace mints under ``https://w3id.org/battinfo/id/1001/``. When it
describes a record the registry already holds in the old form,
``https://w3id.org/battinfo/{segment}/{uid}``, the uid is the same under
either form (``entities.seed_iri``), and before anything is submitted or
deposited the workspace asks the registry about each ``/id/1001/`` IRI and
adopts the old form: every record that names it is rewritten, no uid
changes, and nothing sent names the ``/id/1001/`` form. A registry that
cannot be asked stops the submission or deposit unless
``allow_unchecked_iris=True``. A record the registry holds as superseded or
withdrawn is never adopted: it stops the submission or deposit before anything
is rewritten or sent. A workspace refers to a record it holds by the IRI its
saved copy has, whichever form the reference was given in.

The registry and Zenodo are answered in memory; nothing goes on the network.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

import battinfo
import battinfo.api
from battinfo import api
from battinfo import registry as registry_module
from battinfo import zenodo as zenodo_module
from battinfo._adoption import RetiredRecord
from battinfo.entities import cell_spec_uid
from battinfo.namespace import OLD_FORM_BASE, parse_record_iri, record_iri
from battinfo.ws import AuthoringWorkspace, RetiredIrisError, SubmitError, UncheckedIrisError

REGISTRY = "https://registry.example"
ZENODO_API = "https://zenodo.org/api"
BUCKET = f"{ZENODO_API}/files/bucket-7"
SPEC_FIELDS = {"manufacturer": "Example Lab", "model": "R2032", "format": "coin", "chemistry": "li-ion"}
SPEC_UID = cell_spec_uid({**SPEC_FIELDS, "size_code": None})
SPEC_OLD = record_iri("spec", SPEC_UID)
SPEC_NEW = record_iri("spec", SPEC_UID, "1001")
CREDS = {"registry_url": REGISTRY, "api_key": "k", "workspace_id": "w", "publisher_id": "p"}
CREATORS = [{"name": "Doe, Jane", "affiliation": "Example Lab"}]
CSV = "test_time_second,voltage_volt,current_ampere\n0,3.0,0\n60,3.5,0.001\n"


class _Reply(io.BytesIO):
    def __init__(self, payload: object) -> None:
        super().__init__(b"" if payload is None else json.dumps(payload).encode("utf-8"))

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def getcode(self) -> int:
        return 200


class FakeServices:
    """The registry and Zenodo, answered in memory.

    The registry holds the records in ``held`` (``"segment/uid"`` -> IRI) and
    answers ``GET /resources/{segment}/{uid}`` with the entry's
    ``canonical_iri`` and the fields ``status`` adds for it (none unless a
    test sets them, as an older registry answers), else 404; with
    ``offline`` every GET fails as an unreachable host would. Packages POSTed to it are kept in ``posted``.
    Zenodo serves one deposit (id 7) and keeps the files put in its bucket.
    """

    def __init__(self) -> None:
        self.held: dict[str, str] = {f"spec/{SPEC_UID}": SPEC_OLD}
        self.status: dict[str, dict[str, Any]] = {}
        self.offline = False
        self.lookups: list[str] = []
        self.posted: list[dict] = []
        self.zenodo: list[str] = []
        self.files: dict[str, bytes] = {}

    def __call__(self, request: Any, timeout: float | None = None) -> _Reply:
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        method = request.get_method() if isinstance(request, urllib.request.Request) else "GET"
        if url.startswith(REGISTRY):
            return self._registry(method, url, request)
        if url.startswith(ZENODO_API):
            return self._zenodo(method, url, request)
        raise AssertionError(f"unexpected request: {method} {url}")

    def _registry(self, method: str, url: str, request: Any) -> _Reply:
        path = urllib.parse.urlparse(url).path
        if method == "POST" and path == "/publication-packages":
            self.posted.append(json.loads(request.data))
            return _Reply({"status": "validated", "resources": [{"canonical_iri": "iri"}]})
        self.lookups.append(path)
        if self.offline:
            raise urllib.error.URLError("registry unreachable")
        key = path.removeprefix("/resources/")
        if key in self.held:
            entry = {"canonical_iri": self.held[key], "canonical_id": key.rsplit("/", 1)[1]}
            return _Reply({**entry, **self.status.get(key, {})})
        raise urllib.error.HTTPError(url, 404, "Not Found", None, io.BytesIO(b'{"detail": "Resource not found."}'))  # type: ignore[arg-type]

    def _zenodo(self, method: str, url: str, request: Any) -> _Reply:
        path = url[len(ZENODO_API) :]
        self.zenodo.append(f"{method} {path}")
        deposit = {
            "id": 7,
            "record_id": 7,
            "state": "unsubmitted",
            "submitted": False,
            "links": {"bucket": BUCKET},
            "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.7"}},
        }
        if url.startswith(f"{BUCKET}/") and method == "PUT":
            name = urllib.parse.unquote(url[len(BUCKET) + 1 :])
            self.files[name] = request.data
            return _Reply({"key": name})
        if f"{method} {path}" in ("POST /deposit/depositions", "GET /deposit/depositions/7"):
            return _Reply(deposit)
        if f"{method} {path}" == "PUT /deposit/depositions/7":
            return _Reply({**deposit, "metadata": json.loads(request.data)["metadata"]})
        if f"{method} {path}" == "GET /deposit/depositions/7/files":
            return _Reply(
                [
                    {"id": name, "filename": name, "checksum": hashlib.md5(data).hexdigest()}  # noqa: S324
                    for name, data in self.files.items()
                ]
            )
        raise AssertionError(f"unexpected Zenodo request: {method} {url}")

    def sent_text(self) -> str:
        """Everything that left the workspace: the packages posted and the files deposited."""
        return json.dumps(self.posted) + "".join(data.decode("utf-8", "replace") for data in self.files.values())


@pytest.fixture()
def services(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeServices:
    fake = FakeServices()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.setattr(battinfo.api, "urlopen", fake)
    monkeypatch.setattr(registry_module.time, "sleep", lambda *_: None)
    monkeypatch.setattr(zenodo_module.time, "sleep", lambda *_: None)
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    monkeypatch.delenv("BATTINFO_REGISTRY_URL", raising=False)
    monkeypatch.setattr("battinfo.config.USER_CONFIG_PATH", tmp_path / "home" / ".battinfo" / "config.yaml")
    return fake


def _body(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return next(value for value in doc.values() if isinstance(value, dict) and "id" in value)


def _saved(ws: AuthoringWorkspace, folder: str) -> list[dict]:
    return [_body(path) for path in sorted((ws._ws.source_root / folder).glob("*.json"))]


def _uid(iri: str) -> str:
    parsed = parse_record_iri(iri)
    assert parsed is not None, iri
    return parsed.uid


def _new_workspace(root: Path, registry_url: str | None = REGISTRY, *, data: bool = False) -> AuthoringWorkspace:
    """A workspace created now, so it mints under /id/1001/: a cell of a spec the registry holds in the old form.

    With *data*, a cycling test of the cell with a data file, for a deposit.
    """
    ws = AuthoringWorkspace(root=root, registry_url=registry_url)
    ws.license("cc-by-4.0")
    ws.add("cell", spec=battinfo.CellSpec(**SPEC_FIELDS), serial_numbers=["C01"])
    if data:
        (root / "C01").mkdir(parents=True)
        (root / "C01" / "cycling.csv").write_text(CSV, encoding="utf-8")
        ws.add("test", type="cycling", cell="C01", data="C01/cycling.csv")
    ws.save()
    ((spec,),) = [_saved(ws, "cell-spec")]
    ((cell,),) = [_saved(ws, "cell-instance")]
    assert spec["id"] == SPEC_NEW
    assert cell["cell_spec_id"] == SPEC_NEW
    return ws


# ── ws.submit() ───────────────────────────────────────────────────────────────


def test_submit_adopts_the_old_form_the_registry_holds(
    tmp_path: Path, services: FakeServices, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _new_workspace(tmp_path)
    ((cell_before,),) = [_saved(ws, "cell-instance")]

    outcomes = ws.submit(**CREDS)

    assert all(outcome["ok"] for outcome in outcomes)
    ((spec,),) = [_saved(ws, "cell-spec")]
    ((cell,),) = [_saved(ws, "cell-instance")]
    assert spec["id"] == SPEC_OLD
    assert cell["cell_spec_id"] == SPEC_OLD
    assert cell["id"] == cell_before["id"]  # its uid, and its own IRI, do not move
    assert SPEC_NEW not in services.sent_text()
    assert SPEC_OLD in services.sent_text()
    assert f"{SPEC_NEW} -> {SPEC_OLD}" in capsys.readouterr().out
    # Each IRI was asked about once: the packages did not ask again.
    assert len(services.lookups) == len(set(services.lookups))

    # The session took the adopted IRI, so a second save keeps it.
    ws.save()
    assert _saved(ws, "cell-spec")[0]["id"] == SPEC_OLD
    assert _saved(ws, "cell-instance")[0]["cell_spec_id"] == SPEC_OLD


def test_submit_stops_when_the_registry_cannot_be_asked(tmp_path: Path, services: FakeServices) -> None:
    ws = _new_workspace(tmp_path)
    services.offline = True
    before = {path: path.read_bytes() for path in ws._ws.source_root.rglob("*.json")}

    with pytest.raises(SubmitError) as refused:
        ws.submit(**CREDS)
    assert SPEC_NEW in str(refused.value)
    assert "allow_unchecked_iris=True" in str(refused.value)
    assert services.posted == []
    assert {path: path.read_bytes() for path in ws._ws.source_root.rglob("*.json")} == before

    with pytest.warns(UserWarning, match="were not checked"):
        outcomes = ws.submit(allow_unchecked_iris=True, **CREDS)
    assert outcomes and all(outcome["ok"] for outcome in outcomes)
    assert SPEC_NEW in services.sent_text()


def test_a_uid_pin_of_a_published_test_adopts_its_old_form(tmp_path: Path, services: FakeServices) -> None:
    uid = "b6yn-0sxe-t2qk-9mjv"
    services.held[f"test/{uid}"] = record_iri("test", uid)
    ws = _new_workspace(tmp_path)
    ws.add("test", type="cycling", cell="C01", name="the published run", uid=uid)
    ws.save()
    assert record_iri("test", uid, "1001") in [test["id"] for test in _saved(ws, "test")]

    ws.submit(**CREDS)
    assert record_iri("test", uid) in [test["id"] for test in _saved(ws, "test")]
    assert record_iri("test", uid, "1001") not in services.sent_text()


def test_a_deposit_recorded_before_the_adoption_still_gives_its_doi(tmp_path: Path, services: FakeServices) -> None:
    """.battinfo/zenodo.json names the /id/1001/ form the deposit held; the adopted record is the same record."""
    ws = _new_workspace(tmp_path)
    ((cell,),) = [_saved(ws, "cell-instance")]
    ws._save_zenodo_state(
        {
            "environment": "production",
            "concept_record_id": "7",
            "record_id": "7",
            "deposit_id": "7",
            "doi": "10.5281/zenodo.7",
            "published": True,
            "records": [SPEC_NEW, cell["id"]],
        }
    )

    ws.submit(**CREDS)

    assert sorted(package["resource"]["resource_type"] for package in services.posted) == ["cell", "cell_spec"]
    for package in services.posted:
        assert SPEC_NEW not in json.dumps(package)
        resource = package["resource"]
        own = resource["semantic_payload"]["battinfo_records"][resource["resource_type"]]
        assert own["provenance"]["citation_doi"] == "10.5281/zenodo.7", resource["resource_type"]


# ── ws.zenodo() ───────────────────────────────────────────────────────────────


def test_a_zenodo_draft_adopts_the_old_form_the_registry_holds(tmp_path: Path, services: FakeServices) -> None:
    ws = _new_workspace(tmp_path, data=True)
    ((cell_before,),) = [_saved(ws, "cell-instance")]

    result = ws.zenodo(token="placeholder", creators=CREATORS)

    assert result.published is False
    assert result.adopted == {SPEC_NEW: SPEC_OLD}
    ((cell,),) = [_saved(ws, "cell-instance")]
    assert cell["cell_spec_id"] == SPEC_OLD and _uid(cell["id"]) == _uid(cell_before["id"])
    graph = services.files["battinfo.json"].decode("utf-8")
    assert SPEC_OLD in graph and SPEC_NEW not in graph
    assert SPEC_NEW not in services.sent_text()


def test_a_zenodo_draft_stops_without_a_registry_unless_allowed(tmp_path: Path, services: FakeServices) -> None:
    ws = _new_workspace(tmp_path, registry_url=None, data=True)

    with pytest.raises(UncheckedIrisError) as refused:
        ws.zenodo(token="placeholder", creators=CREATORS)
    assert SPEC_NEW in refused.value.iris
    assert services.zenodo == [] and services.lookups == []

    with pytest.warns(UserWarning, match="were not checked"):
        result = ws.zenodo(token="placeholder", creators=CREATORS, allow_unchecked_iris=True)
    assert result.adopted == {}
    assert SPEC_NEW in services.files["battinfo.json"].decode("utf-8")


def test_a_zenodo_draft_stops_when_the_registry_cannot_be_asked(tmp_path: Path, services: FakeServices) -> None:
    ws = _new_workspace(tmp_path, data=True)
    services.offline = True

    with pytest.raises(UncheckedIrisError, match="allow_unchecked_iris=True") as refused:
        ws.zenodo(token="placeholder", creators=CREATORS)
    assert SPEC_NEW in refused.value.iris and len(refused.value.iris) > 1
    assert services.zenodo == []
    # The first lookup is tried once, and a registry that does not answer it
    # is not asked about the others.
    assert len(services.lookups) == 1


def test_a_deposit_refused_by_its_own_checks_asks_no_registry_and_rewrites_nothing(
    tmp_path: Path, services: FakeServices
) -> None:
    ws = _new_workspace(tmp_path, data=True)
    (tmp_path / "C01" / "cycling.csv").unlink()  # a dataset whose file is gone: the deposit refuses it
    before = {path: path.read_bytes() for path in ws._ws.source_root.rglob("*.json")}

    with pytest.raises(RuntimeError, match="cycling.csv"):
        ws.zenodo(token="placeholder", creators=CREATORS)
    assert services.lookups == [] and services.zenodo == []
    assert {path: path.read_bytes() for path in ws._ws.source_root.rglob("*.json")} == before


# ── References by the IRI the saved copy has ─────────────────────────────────


def test_a_spec_given_by_its_other_form_is_referred_to_by_the_iri_saved_here(tmp_path: Path) -> None:
    """The mixed-forms case: an old-form workspace, and its spec given by the /id/1001/ form."""
    old = AuthoringWorkspace(root=tmp_path, registry_url=None, base=OLD_FORM_BASE)
    old.add("cell", spec=battinfo.CellSpec(**SPEC_FIELDS), serial_numbers=["C01"])
    old.save()
    (spec_path,) = (old._ws.source_root / "cell-spec").glob("*.json")
    spec_record = json.loads(spec_path.read_text(encoding="utf-8"))
    assert spec_record["cell_spec"]["id"] == SPEC_OLD

    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    hit = {"id": SPEC_NEW, "type": "cell-spec", "source": "local", "_record": spec_record, **SPEC_FIELDS}
    ws.add("cell", spec=hit, serial_numbers=["C01", "C02"])
    ws.save()

    assert _saved(ws, "cell-spec")[0]["id"] == SPEC_OLD
    assert {cell["serial_number"]: cell["cell_spec_id"] for cell in _saved(ws, "cell-instance")} == {
        "C01": SPEC_OLD,
        "C02": SPEC_OLD,
    }


def test_a_registry_record_under_the_other_form_is_kept_with_the_iri_it_carries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The registry matches on segment and uid; the copy keeps the registry's IRI, and so does the reference."""
    record = battinfo.CellSpec(id=SPEC_OLD, source_type="datasheet", retrieved_at=1750032000, **SPEC_FIELDS).to_record()

    def envelope(request: Any, timeout: float | None = None) -> _Reply:
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        assert url == f"{REGISTRY}/resources/cell_spec/{SPEC_UID}", url
        return _Reply(
            {"canonical_iri": SPEC_OLD, "semantic_payload": {"battinfo_records": {"cell_spec": copy.deepcopy(record)}}}
        )

    monkeypatch.setattr(urllib.request, "urlopen", envelope)
    ws = AuthoringWorkspace(root=tmp_path, registry_url=REGISTRY)
    ws.add("cell", spec={"id": SPEC_NEW, "type": "cell-spec", **SPEC_FIELDS}, serial_numbers=["C01"])
    summary = ws.save()

    assert summary["index"]["failures"] == []
    ((cell,),) = [_saved(ws, "cell-instance")]
    assert cell["cell_spec_id"] == SPEC_OLD
    copy_path = tmp_path / ".battinfo" / "references" / "cell-spec" / f"cell-spec-{SPEC_UID}.json"
    assert json.loads(copy_path.read_text(encoding="utf-8"))["cell_spec"]["id"] == SPEC_OLD


# ── Saving into a folder of the old form (offline, from the saved copy) ─────


def test_a_record_saved_by_its_other_form_into_an_old_folder_adopts_the_saved_iri(tmp_path: Path) -> None:
    """An importer run again into a folder of 0.8.0rc2: its /id/1001/ IRIs take the old form the folder holds."""
    records = tmp_path / "records"
    saved = api.save_cell_spec(dict(SPEC_FIELDS), source_root=records, base=OLD_FORM_BASE)
    assert saved["id"] == SPEC_OLD
    cell_uid = "c3ka-7qxe-n2pd-4vbm"
    api.save_cell_instance(
        {"id": record_iri("cell", cell_uid), "cell_spec_id": SPEC_OLD, "serial_number": "C01"},
        source_root=records,
    )

    again = api.save_cell_spec({"id": SPEC_NEW, **SPEC_FIELDS}, source_root=records, mode="upsert")
    assert again["id"] == SPEC_OLD
    cell = api.save_cell_instance(
        {"id": record_iri("cell", cell_uid, "1001"), "cell_spec_id": SPEC_NEW, "serial_number": "C01"},
        source_root=records,
        mode="upsert",
    )
    assert cell["id"] == record_iri("cell", cell_uid)
    body = json.loads(Path(cell["path"]).read_text(encoding="utf-8"))["cell_instance"]
    assert body["cell_spec_id"] == SPEC_OLD
    assert [path.name for path in (records / "cell-spec").glob("*.json")] == [f"cell-spec-{SPEC_UID}.json"]


# ── The other submit and deposit paths ───────────────────────────────────────


def test_submit_publication_package_sends_the_old_form(services: FakeServices) -> None:
    payload = {"resource": {"canonical_iri": SPEC_NEW, "related": [f"{SPEC_NEW}#described"]}}

    result = api.submit_publication_package(payload, registry_base_url=REGISTRY, api_key="k")

    assert result["adopted"] == {SPEC_NEW: SPEC_OLD}
    assert services.posted == [{"resource": {"canonical_iri": SPEC_OLD, "related": [f"{SPEC_OLD}#described"]}}]
    assert payload["resource"]["canonical_iri"] == SPEC_NEW  # the caller's package is left as it was

    services.lookups.clear()
    api.submit_publication_package(payload, registry_base_url=REGISTRY, api_key="k", checked_iris={SPEC_NEW: SPEC_NEW})
    assert services.lookups == []


def test_a_404_that_is_not_the_registrys_answer_leaves_the_iri_unchecked(monkeypatch: pytest.MonkeyPatch) -> None:
    """A wrong address or a proxy answers 404 for everything; only the registry's own body means "not held"."""

    def elsewhere(request: Any, timeout: float | None = None) -> _Reply:
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", None, io.BytesIO(b"<html>404</html>"))  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", elsewhere)
    with pytest.raises(UncheckedIrisError) as refused:
        api.submit_publication_package(
            {"resource": {"canonical_iri": SPEC_NEW}}, registry_base_url=REGISTRY, api_key="k"
        )
    assert refused.value.iris == [SPEC_NEW]


def test_an_iri_is_found_only_as_a_whole_token() -> None:
    from battinfo._adoption import minted_iris, rewrite_iris

    longer = f"{SPEC_NEW}-aaaa"
    assert minted_iris(longer) == set()
    assert rewrite_iris(longer, {SPEC_NEW: SPEC_OLD}) == longer
    assert minted_iris(f"{SPEC_NEW}#described") == {SPEC_NEW}
    assert rewrite_iris(f"{SPEC_NEW}/v2", {SPEC_NEW: SPEC_OLD}) == f"{SPEC_OLD}/v2"


def test_submit_publication_package_stops_when_the_registry_cannot_be_asked(services: FakeServices) -> None:
    services.offline = True
    with pytest.raises(UncheckedIrisError):
        api.submit_publication_package(
            {"resource": {"canonical_iri": SPEC_NEW}}, registry_base_url=REGISTRY, api_key="k"
        )
    assert services.posted == []


def test_a_publication_package_adopts_the_old_form_the_registry_holds(tmp_path: Path, services: FakeServices) -> None:
    from battinfo.bundle import Cell, Dataset, Test
    from battinfo.publication import publish

    run = tmp_path / "run1"
    run.mkdir()
    (run / "data.csv").write_text(CSV, encoding="utf-8")

    def build(**kwargs: Any) -> dict[str, Any]:
        return publish(
            cell_spec=battinfo.CellSpec(**SPEC_FIELDS),
            cell_instance=Cell(serial_number="P01"),
            test=Test(test_kind="cycling"),
            dataset=Dataset(dataset_path=str(run), name="P01 cycling", license="CC-BY-4.0"),
            validation_policy="default",
            registry_url=REGISTRY,
            **kwargs,
        )

    services.held.clear()
    first = build()
    (run / "battinfo.publish.jsonld").unlink()
    services.held[f"spec/{_uid(first['cell_spec_id'])}"] = record_iri("spec", _uid(first["cell_spec_id"]))

    again = build()
    assert again["cell_spec_id"] == record_iri("spec", _uid(first["cell_spec_id"]))
    assert again["adopted"] == {first["cell_spec_id"]: again["cell_spec_id"]}
    assert again["cell_instance_id"] == first["cell_instance_id"]
    graph = (run / "battinfo.publish.jsonld").read_text(encoding="utf-8")
    assert first["cell_spec_id"] not in graph and again["cell_spec_id"] in graph

    services.offline = True
    (run / "battinfo.publish.jsonld").unlink()
    with pytest.raises(UncheckedIrisError):
        build()


def test_a_publication_package_without_a_registry_is_built_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no registry_url and no BATTINFO_REGISTRY_URL, a local build asks nothing and refuses nothing."""
    from battinfo.bundle import Cell, Dataset, Test
    from battinfo.publication import publish

    def no_network(request: Any, timeout: float | None = None) -> _Reply:
        raise AssertionError(f"a local build made a request: {request}")

    monkeypatch.delenv("BATTINFO_REGISTRY_URL", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    run = tmp_path / "run1"
    run.mkdir()
    (run / "data.csv").write_text(CSV, encoding="utf-8")

    built = publish(
        cell_spec=battinfo.CellSpec(**SPEC_FIELDS),
        cell_instance=Cell(serial_number="P01"),
        test=Test(test_kind="cycling"),
        dataset=Dataset(dataset_path=str(run), name="P01 cycling", license="CC-BY-4.0"),
        validation_policy="default",
    )

    assert built["adopted"] == {}
    assert parse_record_iri(built["cell_spec_id"]).prefix == "1001"  # type: ignore[union-attr]


def test_a_contribution_adopts_the_old_form_in_its_files_before_the_deposit(
    tmp_path: Path, services: FakeServices
) -> None:
    from battinfo.contribution import CONTRIBUTION_MANIFEST, _adopt_contribution_iris

    root = tmp_path / "cell-01"
    dist = root / ".battinfo" / "ingest" / root.name / "workspace" / "dist"
    dist.mkdir(parents=True)
    (root / CONTRIBUTION_MANIFEST).write_text(f"cell_spec_iri: {SPEC_NEW}\n", encoding="utf-8")
    intake = dist / "registry-intake.json"
    intake.write_text(json.dumps({"resources": [{"canonical_iri": SPEC_NEW}]}), encoding="utf-8")
    (dist / "data.csv").write_text(f"{SPEC_NEW}\n", encoding="utf-8")  # data, never rewritten

    adopted = _adopt_contribution_iris(root, dist.parent, registry_url=REGISTRY, allow_unchecked_iris=False)

    assert adopted == {SPEC_NEW: SPEC_OLD}
    assert (root / CONTRIBUTION_MANIFEST).read_text(encoding="utf-8") == f"cell_spec_iri: {SPEC_OLD}\n"
    assert json.loads(intake.read_text(encoding="utf-8")) == {"resources": [{"canonical_iri": SPEC_OLD}]}
    assert (dist / "data.csv").read_text(encoding="utf-8") == f"{SPEC_NEW}\n"


# ── A record the registry no longer publishes ────────────────────────────────

REPLACEMENT = record_iri("spec", "d4mr-8vxe-k2pq-7tnb")
OTHER_REPLACEMENT = record_iri("spec", "f5ws-3hzk-9qrt-2vcy")
# Each retired case: the fields the registry's entry adds, and what the error says happened to the record.
RETIRED = {
    "superseded": (
        {"status": "superseded", "replaced_by_iri": REPLACEMENT, "replaced_by_iris": None},
        f"superseded by {REPLACEMENT}",
    ),
    "superseded by several": (
        {
            "status": "superseded",
            "replaced_by_iri": REPLACEMENT,
            "replaced_by_iris": [REPLACEMENT, OTHER_REPLACEMENT],
        },
        f"superseded by {REPLACEMENT}, {OTHER_REPLACEMENT}",
    ),
    "withdrawn": ({"status": "withdrawn", "replaced_by_iri": None, "replaced_by_iris": None}, "withdrawn"),
}


@pytest.fixture(params=sorted(RETIRED))
def retired(request: pytest.FixtureRequest, services: FakeServices) -> str:
    """The registry holds the spec in the old form as retired; returns what the error says of it."""
    entry, said = RETIRED[request.param]
    services.status[f"spec/{SPEC_UID}"] = entry
    return said


def _files(ws: AuthoringWorkspace) -> dict[Path, bytes]:
    paths = [*ws._ws.source_root.rglob("*.json"), ws._ws.index_path]
    return {path: path.read_bytes() for path in paths if path.is_file()}


def _assert_stopped(error: BaseException | None, said: str) -> None:
    assert isinstance(error, RetiredIrisError)
    assert error.iris == [SPEC_NEW]
    assert error.retired[SPEC_NEW].iri == SPEC_OLD
    message = str(error)
    assert f"{SPEC_NEW}: the registry holds it as {SPEC_OLD}, which was {said}." in message
    assert "If it means the record that replaced it" in message and "must differ" in message


def test_submit_stops_on_a_record_the_registry_retired(tmp_path: Path, services: FakeServices, retired: str) -> None:
    ws = _new_workspace(tmp_path)
    ((cell,),) = [_saved(ws, "cell-instance")]
    # Held as published, so it would be adopted, were it not for the spec.
    services.held[f"cell/{_uid(cell['id'])}"] = record_iri("cell", _uid(cell["id"]))
    before = _files(ws)

    with pytest.raises(SubmitError) as refused:
        ws.submit(**CREDS)
    _assert_stopped(refused.value.__cause__, retired)
    assert services.posted == [] and services.zenodo == []
    assert _files(ws) == before
    asked = list(services.lookups)

    # The session keeps the answer: a second call stops without asking again,
    # and allow_unchecked_iris does not lift the stop.
    with pytest.raises(SubmitError) as again:
        ws.submit(allow_unchecked_iris=True, **CREDS)
    _assert_stopped(again.value.__cause__, retired)
    assert services.lookups == asked
    assert services.posted == []
    assert _files(ws) == before


def test_a_zenodo_draft_stops_on_a_record_the_registry_retired(
    tmp_path: Path, services: FakeServices, retired: str
) -> None:
    ws = _new_workspace(tmp_path, data=True)
    before = _files(ws)

    with pytest.raises(RetiredIrisError) as refused:
        ws.zenodo(token="placeholder", creators=CREATORS, allow_unchecked_iris=True)
    _assert_stopped(refused.value, retired)
    assert services.zenodo == [] and services.files == {} and services.posted == []
    assert _files(ws) == before


def test_submit_publication_package_stops_on_a_record_the_registry_retired(
    services: FakeServices, retired: str
) -> None:
    payload = {"resource": {"canonical_iri": SPEC_NEW, "related": [f"{SPEC_NEW}#described"]}}
    original = copy.deepcopy(payload)

    with pytest.raises(RetiredIrisError) as refused:
        api.submit_publication_package(payload, registry_base_url=REGISTRY, api_key="k", allow_unchecked_iris=True)
    _assert_stopped(refused.value, retired)
    assert services.posted == []
    assert payload == original

    # An answer passed on in checked_iris stops the call without asking again.
    services.lookups.clear()
    with pytest.raises(RetiredIrisError):
        api.submit_publication_package(
            payload, registry_base_url=REGISTRY, api_key="k", checked_iris=dict(refused.value.retired)
        )
    assert services.lookups == [] and services.posted == []


def test_a_record_retired_under_its_new_form_stops_too(services: FakeServices) -> None:
    services.held[f"spec/{SPEC_UID}"] = SPEC_NEW
    services.status[f"spec/{SPEC_UID}"] = {"status": "withdrawn"}

    with pytest.raises(RetiredIrisError) as refused:
        api.submit_publication_package(
            {"resource": {"canonical_iri": SPEC_NEW}}, registry_base_url=REGISTRY, api_key="k"
        )
    assert refused.value.retired == {SPEC_NEW: RetiredRecord(SPEC_NEW, "withdrawn")}
    assert services.posted == []


@pytest.mark.parametrize(
    "entry",
    [{"status": "published", "replaced_by_iri": None, "replaced_by_iris": None}, {}],
    ids=["published", "no status"],
)
def test_a_published_record_or_one_without_a_status_is_adopted(
    tmp_path: Path, services: FakeServices, entry: dict[str, Any]
) -> None:
    services.status[f"spec/{SPEC_UID}"] = entry

    result = api.submit_publication_package(
        {"resource": {"canonical_iri": SPEC_NEW}}, registry_base_url=REGISTRY, api_key="k"
    )
    assert result["adopted"] == {SPEC_NEW: SPEC_OLD}
    assert services.posted == [{"resource": {"canonical_iri": SPEC_OLD}}]

    ws = _new_workspace(tmp_path)
    assert all(outcome["ok"] for outcome in ws.submit(**CREDS))
    assert _saved(ws, "cell-spec")[0]["id"] == SPEC_OLD
    assert SPEC_NEW not in services.sent_text()
