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
