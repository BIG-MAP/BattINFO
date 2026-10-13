"""Records referenced from the registry count as resolved (evaluation finding E-01).

A test added to a cell that lives only in the registry, by IRI or through
ws.load(<search hit>), failed the strict save-time reference check: the
workspace never asked the registry, although help(ws.add) says it does. With a
registry configured the workspace now looks the record up, keeps a read-only
copy of the published canonical record under .battinfo/references/<kind>/,
resolves references against that folder at save time, and never submits the
copies. Offline, an unresolved reference stays an error that says so.

The registry is mocked (sockets are disabled in the test suite).
"""
from __future__ import annotations

import copy
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

import battinfo
from battinfo.ws import AuthoringWorkspace

REGISTRY = "https://registry.example"
CELL_IRI = "https://w3id.org/battinfo/cell/epb7-1s8v-p342-469z"
SPEC_IRI = "https://w3id.org/battinfo/spec/avzy-5vjx-5nkj-jgsj"
PROTOCOL_IRI = "https://w3id.org/battinfo/spec/v4sk-j357-5jda-jreq"
SERIAL = "empa__ccid000149"
_CREDS = dict(registry_url=REGISTRY, api_key="k", workspace_id="w", publisher_id="p")

CELL_RECORD = battinfo.Cell(id=CELL_IRI, cell_spec_id=SPEC_IRI, serial_number=SERIAL,
                            source_type="measurement", retrieved_at=1750032000).to_record()
SPEC_RECORD = battinfo.CellSpec(id=SPEC_IRI, manufacturer="Duracell", model="MN2400", format="cylindrical",
                                chemistry="zn-mno2", source_type="datasheet",
                                retrieved_at=1750032000).to_record()
PROTOCOL_RECORD = battinfo.TestSpec(id=PROTOCOL_IRI, name="Svaluto-Ferro 2025 formation", kind="cycling",
                                    source_type="manual", retrieved_at=1750032000).to_record()


def _uid(iri: str) -> str:
    return iri.rsplit("/", 1)[1]


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class FakeRegistry:
    """Serves /resources listings and /resources/<type>/<uid> envelopes; 404 for anything else."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.envelopes = {
            f"cell/{_uid(CELL_IRI)}": ("cell", CELL_IRI, CELL_RECORD),
            f"cell_spec/{_uid(SPEC_IRI)}": ("cell_spec", SPEC_IRI, SPEC_RECORD),
            f"test_spec/{_uid(PROTOCOL_IRI)}": ("test_spec", PROTOCOL_IRI, PROTOCOL_RECORD),
        }
        self.listings = {
            "cell": [{"canonical_iri": CELL_IRI, "canonical_id": _uid(CELL_IRI), "resource_type": "cell",
                      "title": SERIAL, "metadata": {"name": SERIAL, "serial_number": SERIAL,
                                                    "cell_spec_id": SPEC_IRI}}],
            "cell_spec": [{"canonical_iri": SPEC_IRI, "canonical_id": _uid(SPEC_IRI), "resource_type": "cell_spec",
                           "title": "Duracell MN2400", "metadata": {"manufacturer": "Duracell", "model": "MN2400"}}],
        }

    def __call__(self, request, timeout=None):  # noqa: ANN001
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        self.calls.append(url)
        parsed = urllib.parse.urlparse(url)
        if parsed.path == "/resources":
            query = urllib.parse.parse_qs(parsed.query)
            rows = self.listings.get(query["resource_type"][0], [])
            return _Response(json.dumps(rows).encode("utf-8"))
        key = parsed.path.removeprefix("/resources/")
        if key in self.envelopes:
            resource_type, iri, record = self.envelopes[key]
            envelope = {"canonical_iri": iri, "canonical_id": _uid(iri), "resource_type": resource_type,
                        "semantic_payload": {"battinfo_records": {resource_type: copy.deepcopy(record)}}}
            return _Response(json.dumps(envelope).encode("utf-8"))
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)  # type: ignore[arg-type]


@pytest.fixture()
def registry(monkeypatch: pytest.MonkeyPatch) -> FakeRegistry:
    fake = FakeRegistry()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


def _references(root: Path) -> Path:
    return root / ".battinfo" / "references"


def test_cell_iri_is_looked_up_and_counts_as_resolved(tmp_path: Path, registry: FakeRegistry) -> None:
    """The reproduction (e01_registry_cell.py), by IRI: the strict save now passes."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url=REGISTRY)
    ws.add("test", type="cycling", cell=CELL_IRI, name="repro E-01 cycling test")
    assert f"{REGISTRY}/resources/cell/{_uid(CELL_IRI)}" in registry.calls

    summary = ws.save()
    assert summary["index"]["failures"] == []
    assert not any(item.get("failed") for item in summary["tests"])
    copy_path = _references(tmp_path) / "cell-instance" / f"cell-{_uid(CELL_IRI)}.json"
    assert json.loads(copy_path.read_text(encoding="utf-8")) == CELL_RECORD
    # The copy is not one of the workspace's own records.
    assert not (tmp_path / ".battinfo" / "records" / "cell-instance").exists()


def test_search_hit_is_looked_up_and_counts_as_resolved(tmp_path: Path, registry: FakeRegistry) -> None:
    """The reproduction, through ws.load(<search hit>)."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url=REGISTRY)
    cell = ws.load(ws.search(type="cell", serial=SERIAL)[0])
    test = ws.add("test", type="cycling", cell=cell, name="repro E-01 cycling test")[0]
    summary = ws.save()
    assert summary["index"]["failures"] == []

    # The relinked dataset of the reproduction saves under the strict policy too.
    saved = battinfo.save_dataset(
        battinfo.Dataset(name="Cycling data of Empa coin cell 000149", cell_instance_id=CELL_IRI,
                         test_id=test.id, access_url="https://doi.org/10.5281/zenodo.15481956",
                         published_at=1750032000, source={"type": "measurement"}),
        source_root=tmp_path / ".battinfo" / "records", mode="upsert", validation_policy="strict",
        build_jsonld=False, build_html=False,
    )
    assert saved["status"] == "created"


def test_cell_spec_hit_and_protocol_iri_resolve_the_same_way(tmp_path: Path, registry: FakeRegistry) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=REGISTRY)
    ws.add("cell", spec=ws.search("duracell mn2400")[0], serial_numbers=["S1"])
    ws.add("test", type="cycling", cell="S1", spec=PROTOCOL_IRI)
    summary = ws.save()
    assert summary["index"]["failures"] == []
    assert (_references(tmp_path) / "cell-spec" / f"cell-spec-{_uid(SPEC_IRI)}.json").exists()
    assert (_references(tmp_path) / "test-protocol" / f"test-protocol-{_uid(PROTOCOL_IRI)}.json").exists()


def test_reference_copies_are_never_submitted(
    tmp_path: Path, registry: FakeRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict] = []

    def fake_submit(payload, *, registry_base_url, api_key, **kw):  # noqa: ANN001
        sent.append(payload)
        return {"response": {"status": "validated", "resources": [{"canonical_iri": "iri"}]}}

    monkeypatch.setattr("battinfo.api.submit_publication_package", fake_submit)
    ws = AuthoringWorkspace(root=tmp_path, registry_url=REGISTRY)
    ws.add("test", type="cycling", cell=CELL_IRI, name="repro E-01 cycling test")
    ws.save()
    ws.submit(**_CREDS)
    ws.submit(submit_all=True, resume=False, **_CREDS)
    assert sent and {p["resource"]["resource_type"] for p in sent} == {"test"}
    assert all(set(p["resource"]["semantic_payload"]["battinfo_records"]) == {"test"} for p in sent)


def test_a_copy_made_earlier_resolves_offline(tmp_path: Path, registry: FakeRegistry) -> None:
    online = AuthoringWorkspace(root=tmp_path, registry_url=REGISTRY)
    online.add("test", type="cycling", cell=CELL_IRI, name="first test")
    online.save()

    calls_before = len(registry.calls)
    offline = AuthoringWorkspace(root=tmp_path, registry_url=None)
    offline.add("test", type="cycling", cell=CELL_IRI, name="second test")
    summary = offline.save()
    assert summary["index"]["failures"] == []
    assert len(registry.calls) == calls_before


def test_offline_an_unresolved_reference_stays_an_error(
    tmp_path: Path, registry: FakeRegistry, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.add("test", type="cycling", cell=CELL_IRI, name="repro E-01 cycling test")
    summary = ws.save()
    out = capsys.readouterr().out
    assert registry.calls == []
    assert summary["tests"][0]["failed"] is True
    assert "could not be checked offline" in summary["tests"][0]["error"]
    assert "could not be checked offline" in out
    assert not _references(tmp_path).exists()


def test_a_reference_the_registry_does_not_hold_stays_an_error(
    tmp_path: Path, registry: FakeRegistry, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = "https://w3id.org/battinfo/cell/zzzz-zzzz-zzzz-zzzz"
    ws = AuthoringWorkspace(root=tmp_path, registry_url=REGISTRY)
    ws.add("test", type="cycling", cell=missing, name="orphan test")
    out = capsys.readouterr().out
    assert "not found in the registry" in out
    summary = ws.save()
    assert summary["tests"][0]["failed"] is True
    assert "Referenced cell not found" in summary["tests"][0]["error"]


# ── A copy is named after a uid, never after what else an IRI ends in ────────
#
# The copy's file name ends in the uid that ends the record's IRI. A registry
# that returned an IRI ending in "..\..\victim\planted" made Windows write the
# copy outside the workspace.

HOSTILE_TAIL = "\\".join([".."] * 6 + ["victim", "planted"])


def _files_outside(root: Path, top: Path) -> list[Path]:
    return [path for path in top.rglob("*") if path.is_file() and not path.is_relative_to(root)]


def test_a_search_hit_whose_iri_does_not_end_in_a_uid_is_not_copied(tmp_path: Path, registry: FakeRegistry) -> None:
    hostile_iri = f"https://w3id.org/battinfo/spec/{HOSTILE_TAIL}"
    record = copy.deepcopy(SPEC_RECORD)
    record["cell_spec"]["id"] = hostile_iri
    registry.envelopes[f"cell_spec/{_uid(SPEC_IRI)}"] = ("cell_spec", hostile_iri, record)
    registry.listings["cell_spec"][0]["canonical_iri"] = hostile_iri
    root = tmp_path / "a" / "b" / "c" / "ws"  # the six '..' stay inside tmp_path
    ws = AuthoringWorkspace(root=root, registry_url=REGISTRY)

    with pytest.raises(ValueError, match="does not end in a record uid"):
        ws.load(ws.search("duracell mn2400")[0])

    assert _files_outside(root, tmp_path) == []
    assert not list(tmp_path.rglob("*planted*"))


def test_a_cell_iri_that_does_not_end_in_a_uid_is_not_copied(tmp_path: Path, registry: FakeRegistry) -> None:
    hostile_iri = f"https://w3id.org/battinfo/cell/{HOSTILE_TAIL}"
    record = copy.deepcopy(CELL_RECORD)
    record["cell_instance"]["id"] = hostile_iri
    registry.envelopes[f"cell/{HOSTILE_TAIL}"] = ("cell", hostile_iri, record)
    root = tmp_path / "a" / "b" / "c" / "ws"
    ws = AuthoringWorkspace(root=root, registry_url=REGISTRY)

    with pytest.raises(ValueError, match="does not end in a record uid"):
        ws.add("test", type="cycling", cell=hostile_iri, name="hostile cell")

    assert _files_outside(root, tmp_path) == []
    assert not list(tmp_path.rglob("*planted*"))


# ── A lookup is asked once per session, and gives up quickly ─────────────────


class DownRegistry:
    """A registry that does not answer: every request fails; each is counted with its timeout."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def __call__(self, request, timeout=None):  # noqa: ANN001
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        self.calls.append((url, timeout))
        raise urllib.error.URLError("registry down")


def test_a_failed_lookup_is_asked_once_and_with_a_short_timeout(tmp_path: Path, monkeypatch) -> None:
    down = DownRegistry()
    monkeypatch.setattr(urllib.request, "urlopen", down)
    ws = AuthoringWorkspace(root=tmp_path, registry_url=REGISTRY)
    for name in ("first", "second", "third"):
        ws.add("test", type="cycling", cell=CELL_IRI, name=name)
    lookups = [(url, timeout) for url, timeout in down.calls if url.endswith(f"/resources/cell/{_uid(CELL_IRI)}")]
    assert lookups == [(f"{REGISTRY}/resources/cell/{_uid(CELL_IRI)}", 10)]


def test_a_cell_found_by_serial_is_not_looked_up_again_by_iri(tmp_path: Path, registry: FakeRegistry) -> None:
    """The listing finds the cell by serial; its record lookup fails; the IRI reuses the cell."""
    del registry.envelopes[f"cell/{_uid(CELL_IRI)}"]  # the record lookup fails (404)
    ws = AuthoringWorkspace(root=tmp_path, registry_url=REGISTRY)
    ws.add("test", type="cycling", cell=SERIAL, name="by serial")
    calls = len(registry.calls)
    assert any(url.endswith(f"/resources/cell/{_uid(CELL_IRI)}") for url in registry.calls)
    ws.add("test", type="cycling", cell=CELL_IRI, name="by IRI")
    ws.add("test", type="cycling", cell=SERIAL, name="by serial again")
    assert len(registry.calls) == calls


# ── The deposit describes a registry-only record it points at ────────────────
#
# A test and dataset on a cell only the registry holds saved, but the deposit
# graph built by ws.preview_jsonld() and ws.zenodo() read the workspace's own
# records only: it had no node for the cell, failed the publication check with
# publication.reference_missing_node, and lost the cell part of the test's
# name. The copy the workspace keeps now gives the cell, and a referenced test
# spec, a "defined elsewhere" stub in the deposit.

DATA = "test_time_second,voltage_volt,current_ampere\n0,3.0,0\n60,3.5,0.001\n"
CREATORS = [{"name": "Doe, Jane"}]


def _workspace_on_registry_cell(root: Path, registry_url: str | None) -> AuthoringWorkspace:
    """The reproduction (n1_reference_not_in_deposit.py): a test with data on a registry-only cell."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "run.bdf.csv").write_text(DATA, encoding="utf-8")
    ws = AuthoringWorkspace(root=root, registry_url=registry_url)
    ws.license("cc-by-4.0")
    ws.add("test", type="cycling", cell=CELL_IRI, spec=PROTOCOL_IRI, data="run.bdf.csv")
    ws.save()
    return ws


def _preview(ws: AuthoringWorkspace) -> dict:
    return json.loads(ws.preview_jsonld(title="NEW-1", creators=CREATORS).read_text(encoding="utf-8"))


def _issues(graph: dict, policy: str, severity: str = "error") -> list[str]:
    from battinfo.validate import validate_publication_report

    report = validate_publication_report(graph, policy=policy)
    return sorted(issue.code for issue in report.issues if issue.severity == severity)


def test_a_registry_only_cell_is_a_defined_elsewhere_node_of_the_deposit(
    tmp_path: Path, registry: FakeRegistry
) -> None:
    ws = _workspace_on_registry_cell(tmp_path, REGISTRY)
    graph = _preview(ws)
    nodes = {node["@id"]: node for node in graph["@graph"]}

    assert nodes[CELL_IRI] == {
        "@id": CELL_IRI, "@type": "BatteryCell", "schema:name": SERIAL,
        "rdfs:isDefinedBy": {"@id": CELL_IRI},
    }
    assert nodes[PROTOCOL_IRI] == {
        "@id": PROTOCOL_IRI, "@type": ["prov:Plan", "schema:HowTo"],
        "schema:name": "Svaluto-Ferro 2025 formation", "rdfs:isDefinedBy": {"@id": PROTOCOL_IRI},
    }
    test = next(node for node in graph["@graph"] if "BatteryTest" in node["@type"])
    assert test["schema:name"] == f"cycling — {SERIAL}"  # was "cycling": the cell part was lost
    assert _issues(graph, "publisher") == [] and _issues(graph, "strict") == []

    # The published records are pointed at, not carried: no member, no file, no
    # spec link or other field read from the copies.
    catalog = next(node for node in graph["@graph"] if "dcat:Catalog" in node["@type"])
    assert {ref["@id"] for ref in catalog["dcat:dataset"]} == {
        node["@id"] for node in graph["@graph"] if "dcat:Dataset" in node["@type"]
    }
    assert SPEC_IRI not in json.dumps(graph)


def test_importing_tests_on_a_stub_cell_reports_them_as_skipped(
    tmp_path: Path, registry: FakeRegistry, capsys: pytest.CaptureFixture[str]
) -> None:
    """ws.import_() does not attach tests to a cell the deposit only points at, and says so."""
    ws = _workspace_on_registry_cell(tmp_path / "source", REGISTRY)
    deposit = tmp_path / "battinfo.json"
    deposit.write_text(json.dumps(_preview(ws)), encoding="utf-8")
    test_iri = ws._ws.tests[0].id
    dataset_iri = ws._ws.datasets[0].id
    capsys.readouterr()

    fresh = AuthoringWorkspace(root=tmp_path / "imported", registry_url=None)
    counts = fresh.import_(str(deposit))
    out = capsys.readouterr().out

    reason = "cell defined elsewhere"
    assert counts == {
        "properties": 0, "instances": 0, "tests": 0, "datasets": 0,
        "skipped": {
            "tests": [{"test": test_iri, "cell": CELL_IRI, "reason": reason}],
            "datasets": [{"dataset": dataset_iri, "test": test_iri, "cell": CELL_IRI, "reason": reason}],
        },
    }
    assert fresh._ws.tests == [] and fresh._ws.datasets == []
    assert f"Skipped 1 test(s) and 1 dataset(s) on 1 cell(s) defined in the registry, not in this deposit: {CELL_IRI}" in out
    assert "ws.load(ws.search(type=\"cell\", serial=...)[0])" in out


def test_without_a_copy_the_reference_stays_an_error_that_says_how_to_fetch_it(
    tmp_path: Path, registry: FakeRegistry, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace_on_registry_cell(tmp_path, None)  # offline: nothing was looked up
    capsys.readouterr()
    graph = _preview(ws)
    out = capsys.readouterr().out

    assert CELL_IRI not in {node["@id"] for node in graph["@graph"]}
    test = next(node for node in graph["@graph"] if "BatteryTest" in node["@type"])
    assert test["schema:name"] == "cycling"
    assert _issues(graph, "publisher") == ["publication.reference_missing_node"]
    assert _issues(graph, "strict") == ["publication.reference_missing_node"]
    assert "Not found locally: 1 record(s)" in out and CELL_IRI in out
    assert "Open the workspace with a registry_url" in out


class _FakeZenodo:
    """Stands in for ZenodoClient: records each call and the files each upload carries."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.uploaded: dict[str, str] = {}

    def client(self, *args: object, **kwargs: object) -> _FakeZenodo:
        self.calls.append("client")
        return self

    def create_empty_deposit(self) -> dict:
        self.calls.append("create")
        return {"id": 7, "record_id": 7, "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.7"}}}

    def sync_files(self, deposit_id: int, upload_map: dict) -> dict:
        self.calls.append("upload")
        self.uploaded = {name: Path(path).read_text(encoding="utf-8") for path, name in upload_map.items()}
        return {"uploaded": sorted(self.uploaded), "kept": [], "removed": []}

    def update_metadata(self, deposit_id: int, metadata: dict) -> dict:
        self.calls.append("metadata")
        return {}

    def publish_deposit(self, deposit_id: int) -> dict:
        self.calls.append("publish")
        return {"doi": "10.5281/zenodo.7"}


@pytest.fixture()
def zenodo(monkeypatch: pytest.MonkeyPatch) -> _FakeZenodo:
    fake = _FakeZenodo()
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", fake.client)
    return fake


def test_a_refused_publish_leaves_nothing_on_zenodo(
    tmp_path: Path, registry: FakeRegistry, zenodo: _FakeZenodo
) -> None:
    ws = _workspace_on_registry_cell(tmp_path, None)
    with pytest.raises(RuntimeError) as excinfo:
        ws.zenodo(publish=True, token="placeholder", title="NEW-1", creators=CREATORS)
    message = str(excinfo.value)
    assert message.startswith("Refusing to publish: 1 validation error(s)")
    assert "Not found locally" in message and message.endswith("Nothing was sent to Zenodo.")
    assert zenodo.calls == []  # no client, so no draft with a dangling cell IRI
    assert not (tmp_path / ".battinfo" / "zenodo.json").exists()


def test_a_publish_missing_a_data_file_leaves_nothing_on_zenodo(
    tmp_path: Path, registry: FakeRegistry, zenodo: _FakeZenodo
) -> None:
    ws = _workspace_on_registry_cell(tmp_path, REGISTRY)
    (tmp_path / "run.bdf.csv").unlink()
    with pytest.raises(RuntimeError, match="data file\\(s\\) are missing") as excinfo:
        ws.zenodo(publish=True, token="placeholder", title="NEW-1", creators=CREATORS)
    assert str(excinfo.value).endswith("Nothing was sent to Zenodo.")
    assert zenodo.calls == []


def test_a_publish_on_a_registry_only_cell_deposits_its_stub(
    tmp_path: Path, registry: FakeRegistry, zenodo: _FakeZenodo
) -> None:
    ws = _workspace_on_registry_cell(tmp_path, REGISTRY)
    result = ws.zenodo(publish=True, token="placeholder", title="NEW-1", creators=CREATORS)
    assert result.published
    assert zenodo.calls == ["client", "create", "upload", "metadata", "publish"]
    # The data file and the two metadata files; the reference copies stay local.
    assert sorted(zenodo.uploaded) == ["battinfo.json", "ro-crate-metadata.json", "run.bdf.csv"]
    deposited = json.loads(zenodo.uploaded["battinfo.json"])
    stub = next(node for node in deposited["@graph"] if node["@id"] == CELL_IRI)
    assert stub["rdfs:isDefinedBy"] == {"@id": CELL_IRI}


@pytest.mark.parametrize("registry_url", [REGISTRY, None], ids=["copy-kept", "no-copy"])
def test_the_check_before_the_deposit_gives_the_deposited_graph_verdict(
    tmp_path: Path, registry: FakeRegistry, registry_url: str | None
) -> None:
    """ws.zenodo(publish=True) checks a placeholder graph before the deposit exists.

    The graph it deposits has the real record id and DOI, and a graph rebuilt
    after the upload reads records that point at the deposited file; neither
    changes what the publication check reports.
    """
    ws = _workspace_on_registry_cell(tmp_path, registry_url)
    common = {"data_filenames": ["run.bdf.csv"], "title": "NEW-1", "creators": CREATORS,
              "license": "cc-by-4.0"}
    before = ws._build_zenodo_jsonld(
        zenodo_record_id=0, prereserved_doi="10.5281/zenodo.RECORD_ID",
        record_url="https://zenodo.org/records/RECORD_ID", **common,
    )
    record_url = "https://zenodo.org/records/4242"
    deposited = ws._build_zenodo_jsonld(
        zenodo_record_id=4242, prereserved_doi="10.5281/zenodo.4242", record_url=record_url,
        is_version_of="https://zenodo.org/records/4241", **common,
    )
    assert ws._apply_zenodo_file_urls(record_url, {"run.bdf.csv"}) == 1
    rebuilt = ws._build_zenodo_jsonld(
        zenodo_record_id=4242, prereserved_doi="10.5281/zenodo.4242", record_url=record_url,
        is_version_of="https://zenodo.org/records/4241", **common,
    )
    for policy in ("publisher", "strict"):
        for severity in ("error", "warning"):
            verdict = _issues(before, policy, severity)
            assert _issues(deposited, policy, severity) == verdict
            assert _issues(rebuilt, policy, severity) == verdict
