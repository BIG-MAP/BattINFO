"""Registry submission refuses local file paths (evaluation finding C-14).

Publishing a workspace to the registry used to send the submitter's absolute
paths (file:///C:/Users/<name>/...) as the access and download URLs of every
dataset. Every registry submit path now refuses records whose access_url,
content_url, download_url, provenance.source_url or record_url is a file: URI
or a local path, names each record and field, and says how to fix it.
allow_local_files=True lifts the check for a local test registry.

All offline: the registry is mocked.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import battinfo
from battinfo.api import submit_publication_package
from battinfo.ws import AuthoringWorkspace, SubmitError

_CREDS = dict(registry_url="https://registry.example", api_key="k", workspace_id="w", publisher_id="p")
CSV = "test_time_second,voltage_volt\n0,1.6\n3600,0.9\n"


class _FakeRegistry:
    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self.kwargs: list[dict] = []

    def __call__(self, payload, *, registry_base_url, api_key, **kw):  # noqa: ANN001
        self.payloads.append(copy.deepcopy(payload))
        self.kwargs.append(dict(kw))
        return {"status": "ok", "status_code": 200,
                "response": {"status": "validated", "resources": [{"canonical_iri": "iri"}]}}


def _workspace_with_local_data(
    root: Path, *, registry_url: str | None = None, save: bool = True
) -> AuthoringWorkspace:
    """The evaluation's shape: a test whose dataset is a local converted file."""
    (root / "bdf").mkdir(parents=True, exist_ok=True)
    (root / "bdf" / "C1.bdf.csv").write_text(CSV, encoding="utf-8")
    ws = AuthoringWorkspace(root=root, registry_url=registry_url)
    ws.add("cell", spec=battinfo.CellSpec(manufacturer="Example Lab", model="R03 test cell",
                                          format="cylindrical", chemistry="zn-mno2"), names=["C1"])
    ws.add("test", type="capacity_check", cell="C1", data="bdf/C1.bdf.csv")
    if save:
        ws.save()
    return ws


@pytest.fixture()
def fake(monkeypatch: pytest.MonkeyPatch) -> _FakeRegistry:
    registry = _FakeRegistry()
    monkeypatch.setattr("battinfo.api.submit_publication_package", registry)
    return registry


def test_submit_refuses_local_paths_and_sends_nothing(tmp_path: Path, fake: _FakeRegistry) -> None:
    ws = _workspace_with_local_data(tmp_path / "ws")
    with pytest.raises(SubmitError) as excinfo:
        ws.submit(**_CREDS)
    message = str(excinfo.value)
    assert fake.payloads == []  # nothing was sent, not even the records without files
    assert "Nothing was sent" in message
    assert "ws.zenodo()" in message and "allow_local_files=True" in message
    # Each record and field is named.
    assert "dataset-" in message and "https://w3id.org/battinfo/dataset/" in message
    for field in ("dataset.access_url", "dataset.distributions[0].content_url", "provenance.source_url"):
        assert field in message
    assert (tmp_path / "ws" / "bdf" / "C1.bdf.csv").resolve().as_uri() in message
    failed = excinfo.value.failed
    assert [f["status"] for f in failed] == ["local_files"]


def test_submit_override_sends_local_paths_to_a_test_registry(tmp_path: Path, fake: _FakeRegistry) -> None:
    ws = _workspace_with_local_data(tmp_path / "ws")
    outcomes = ws.submit(allow_local_files=True, **_CREDS)
    assert outcomes and all(o["ok"] for o in outcomes)
    assert all(kw.get("allow_local_files") is True for kw in fake.kwargs)
    dataset_payloads = [p for p in fake.payloads if p["resource"]["resource_type"] == "dataset"]
    assert dataset_payloads
    assert "file:" in json.dumps(dataset_payloads[0])


def test_submit_allow_partial_sends_the_records_without_local_files(tmp_path: Path, fake: _FakeRegistry) -> None:
    ws = _workspace_with_local_data(tmp_path / "ws")
    outcomes = ws.submit(allow_partial=True, **_CREDS)
    refused = [o for o in outcomes if o["status"] == "local_files"]
    assert len(refused) == 1 and refused[0]["iri"].startswith("https://w3id.org/battinfo/dataset/")
    sent_types = {p["resource"]["resource_type"] for p in fake.payloads}
    assert "dataset" not in sent_types and {"cell_spec", "cell", "test"} <= sent_types
    assert "file:" not in json.dumps(fake.payloads)


def test_publish_registry_half_refuses_local_paths(
    tmp_path: Path, fake: _FakeRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in (("BATTINFO_API_KEY", "k"), ("BATTINFO_WORKSPACE_ID", "w"),
                        ("BATTINFO_PUBLISHER_ID", "p")):
        monkeypatch.setenv(name, value)
    ws = _workspace_with_local_data(tmp_path / "ws", registry_url="https://registry.example", save=False)
    with pytest.raises(SubmitError, match="point at files on this computer"):
        ws.publish()  # saves, then the registry half refuses
    assert fake.payloads == []


def test_a_zenodo_deposit_points_every_location_at_https(tmp_path: Path, fake: _FakeRegistry) -> None:
    """After the deposit patches the records, the registry route accepts them."""
    ws = _workspace_with_local_data(tmp_path / "ws")
    patched = ws._apply_zenodo_file_urls("https://zenodo.org/records/123", {"C1.bdf.csv"})
    assert patched == 1
    record_path = next((tmp_path / "ws" / ".battinfo" / "records" / "dataset").glob("*.json"))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    public = "https://zenodo.org/records/123/files/C1.bdf.csv"
    assert record["dataset"]["access_url"] == public
    assert record["dataset"]["distributions"][0]["content_url"] == public
    assert record["provenance"]["source_url"] == public
    outcomes = ws.submit(**_CREDS)
    assert outcomes and all(o["ok"] for o in outcomes)
    assert "file:" not in json.dumps(fake.payloads)


# ── The low-level client every registry path goes through ────────────────────

def _envelope(url: str) -> dict:
    return {
        "kind": "BattinfoSubmission",
        "resource": {
            "resource_type": "dataset",
            "title": "C1 data",
            "source_local_id": "ds-1",
            "semantic_payload": {"battinfo_records": {"dataset": {
                "dataset": {"id": "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-dddd", "access_url": url},
                "provenance": {"source_type": "measurement", "source_url": url},
            }}},
            "distributions": [{"title": "C1.bdf.csv", "access_url": url, "role": "processed"}],
        },
    }


class _Resp:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def getcode(self) -> int:
        return 200

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.mark.parametrize("url", [
    "file:///C:/Users/someone/project/bdf/C1.bdf.csv",
    "file:///home/someone/project/bdf/C1.bdf.csv",
    "C:\\Users\\someone\\project\\bdf\\C1.bdf.csv",
    "bdf/C1.bdf.csv",
])
def test_submit_publication_package_refuses_local_paths(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr("battinfo.api.urlopen", lambda request, timeout=None: calls.append(request))
    with pytest.raises(ValueError) as excinfo:
        submit_publication_package(_envelope(url), registry_base_url="https://r.example", api_key="k")
    assert calls == []
    message = str(excinfo.value)
    assert "dataset C1 data" in message
    assert "semantic_payload.battinfo_records.dataset.dataset.access_url" in message
    assert "semantic_payload.battinfo_records.dataset.provenance.source_url" in message
    assert "distributions[0].access_url" in message


def test_submit_publication_package_override_and_https(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[object] = []

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        sent.append(request)
        return _Resp({"status": "validated"})

    monkeypatch.setattr("battinfo.api.urlopen", fake_urlopen)
    result = submit_publication_package(
        _envelope("file:///C:/data/C1.bdf.csv"), registry_base_url="https://r.example", api_key="k",
        allow_local_files=True,
    )
    assert result["status"] == "ok" and len(sent) == 1
    submit_publication_package(
        _envelope("https://zenodo.org/records/1/files/C1.bdf.csv"), registry_base_url="https://r.example",
        api_key="k",
    )
    assert len(sent) == 2


def test_submission_packages_do_not_name_the_local_workspace_folder(tmp_path: Path) -> None:
    """The envelope's workspace block used to carry the absolute path, user name included."""
    from battinfo._workspace import Workspace, quantity
    from battinfo.local_workspace import LocalWorkspace

    release = LocalWorkspace.init(tmp_path / "release")
    release.build_submission_package()
    package = json.loads((release.root / "dist" / "submission-package.json").read_text(encoding="utf-8"))
    assert "root" not in package["workspace"]

    (tmp_path / "a.csv").write_text("cycle,capacity_ah\n0,2.50\n", encoding="utf-8")
    authoring = Workspace(tmp_path / "authoring", name="w", title="W", tenant="t", publisher="p", version="1.0.0")
    cell_spec = authoring.cell_spec(manufacturer="A123", model="ANR26650M1-B", format="cylindrical",
                                    chemistry="Li-ion", specs={"nominal_voltage": quantity(3.3, "V")},
                                    source_file="a123.manual.json")
    cell = authoring.cell(cell_spec, serial_number="root-001", source_type="lab")
    test = authoring.test(cell, kind="cycling", protocol="1C / 1C", status="completed")
    authoring.dataset(cell, title="Root dataset", test=test, path=tmp_path / "a.csv", license="CC-BY-4.0")
    bundle = authoring.bundle_workspace()
    package = json.loads(Path(bundle["submission_package_path"]).read_text(encoding="utf-8"))
    assert "root" not in package["workspace"]


def test_submit_publication_package_leaves_out_a_workspace_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """A package built before the envelope dropped the field still reaches the registry without it."""
    sent: list[dict] = []

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        sent.append(json.loads(request.data.decode("utf-8")))
        return _Resp({"status": "validated"})

    monkeypatch.setattr("battinfo.api.urlopen", fake_urlopen)
    envelope = _envelope("https://zenodo.org/records/1/files/C1.bdf.csv")
    envelope["workspace"] = {"workspace_id": "w", "root": "C:\\Users\\someone\\release",
                             "registry": {"tenant": "t", "workspace": "w"}}

    submit_publication_package(envelope, registry_base_url="https://r.example", api_key="k")

    assert sent[0]["workspace"] == {"workspace_id": "w", "registry": {"tenant": "t", "workspace": "w"}}
    assert envelope["workspace"]["root"] == "C:\\Users\\someone\\release"  # the caller's package is unchanged


def test_demo_pipeline_refuses_its_local_file_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from battinfo.demo import run_demo_pipeline

    calls: list[object] = []
    monkeypatch.setattr("battinfo.api.urlopen", lambda request, timeout=None: calls.append(request))
    with pytest.raises(ValueError, match="allow_local_files=True"):
        run_demo_pipeline(tmp_path / "demo", registry_base_url="https://registry.example.org",
                          api_key="secret", force=True)
    assert calls == []


# ── Absolute paths in source_file and artifact locators ──────────────────────

AURORA = {
    "unicycler": {"version": "0.3.2"},
    "sample": {"name": "cell-1", "capacity_mAh": "123"},
    "method": [{"step": "constant_current", "rate_C": "-0.1", "until_voltage_V": "2.5"}],
}


def _protocol_record(value: str) -> dict:
    return {
        "test_spec": {"id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd", "name": "CC discharge"},
        "artifacts": [{"role": "source_protocol", "format": "aurora-unicycler-json", "locator": value}],
        "provenance": {"source_type": "import", "source_file": value},
    }


@pytest.mark.parametrize("value", [
    r"C:\Users\someone\protocols\cc.json",
    "/home/someone/protocols/cc.json",
    "file:///C:/Users/someone/protocols/cc.json",
])
def test_an_absolute_source_file_or_locator_is_a_local_reference(value: str) -> None:
    from battinfo._util import local_file_references

    assert dict(local_file_references(_protocol_record(value))) == {
        "artifacts[0].locator": value, "provenance.source_file": value,
    }


@pytest.mark.parametrize("value", ["cc.json", "protocols/cc.json", "https://example.org/protocols/cc.json"])
def test_a_file_name_or_relative_path_is_not(value: str) -> None:
    from battinfo._util import local_file_references

    assert local_file_references(_protocol_record(value)) == []


def test_submit_publication_package_refuses_an_absolute_artifact_locator(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr("battinfo.api.urlopen", lambda request, timeout=None: calls.append(request))
    envelope = {"kind": "BattinfoSubmission", "resource": {
        "resource_type": "test_spec", "title": "CC discharge", "source_local_id": "ts-1",
        "semantic_payload": {"battinfo_records": {"test_spec": _protocol_record("/home/someone/cc.json")}},
    }}
    with pytest.raises(ValueError) as excinfo:
        submit_publication_package(envelope, registry_base_url="https://r.example", api_key="k")
    assert calls == []
    message = str(excinfo.value)
    assert "artifacts[0].locator" in message and "provenance.source_file" in message
    assert "not by its absolute path" in message


def test_protocol_import_stores_no_absolute_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`battinfo import-protocol` passes the path as typed; the record keeps no absolute path."""
    from typer.testing import CliRunner

    from battinfo._util import local_file_references
    from battinfo.cli import app
    from battinfo.interop.protocols import import_aurora_unicycler

    source = tmp_path / "project" / "protocols" / "cc.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps(AURORA), encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    out = tmp_path / "record.json"
    result = CliRunner().invoke(app, ["import-protocol", str(source.resolve()), "--format", "aurora",
                                      "--out", str(out)])
    assert result.exit_code == 0, result.output
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["artifacts"][0]["locator"] == "cc.json"
    assert record["provenance"]["source_file"] == "cc.json"
    assert local_file_references(record) == []

    # Inside the current directory the path stays, relative to it.
    monkeypatch.chdir(tmp_path / "project")
    spec = import_aurora_unicycler(AURORA, source_locator=str(source.resolve()))
    assert spec.artifacts[0].locator == "protocols/cc.json"
    assert spec.source.file == "protocols/cc.json"


# ── A deposit zipped by test kind cannot back the registry route yet ─────────


def _workspace_with_two_files(root: Path) -> AuthoringWorkspace:
    ws = _workspace_with_local_data(root, registry_url="https://registry.example", save=False)
    (root / "bdf" / "C1b.bdf.csv").write_text(CSV, encoding="utf-8")
    ws.add("test", type="cycling", cell="C1", data="bdf/C1b.bdf.csv")
    return ws


@pytest.fixture()
def no_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in (("BATTINFO_API_KEY", "k"), ("BATTINFO_WORKSPACE_ID", "w"),
                        ("BATTINFO_PUBLISHER_ID", "p")):
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("R2_ENDPOINT", raising=False)
    monkeypatch.setattr("battinfo.ws._ZENODO_ZIP_THRESHOLD", 1)  # two files would be zipped


def _record_deposits(ws: AuthoringWorkspace, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from types import SimpleNamespace

    steps: list[str] = []
    monkeypatch.setattr(ws, "upload", lambda *a, **kw: steps.append("upload"))
    monkeypatch.setattr(ws, "zenodo", lambda *a, **kw: steps.append("zenodo") or SimpleNamespace(doi="10.5281/x"))
    return steps


def test_publish_to_zenodo_refuses_a_zipped_deposit_before_depositing(
    tmp_path: Path, fake: _FakeRegistry, no_r2: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace_with_two_files(tmp_path / "ws")
    steps = _record_deposits(ws, monkeypatch)
    with pytest.raises(ValueError) as excinfo:
        ws.publish(zenodo=True)
    message = str(excinfo.value)
    assert "cannot yet point a record at a file inside an archive" in message
    assert "ws.zenodo(publish=True)" in message and "split the workspace" in message
    assert steps == [] and fake.payloads == []


def test_a_zipped_deposit_is_fine_for_a_local_test_registry(
    tmp_path: Path, fake: _FakeRegistry, no_r2: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace_with_two_files(tmp_path / "ws")
    steps = _record_deposits(ws, monkeypatch)
    outcomes = ws.publish(zenodo=True, allow_local_files=True)
    assert steps == ["zenodo"] and outcomes and all(o["ok"] for o in outcomes)


def test_a_zipped_deposit_is_fine_with_r2_storage(
    tmp_path: Path, fake: _FakeRegistry, no_r2: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With R2 the records point at R2 copies of their files, not at the deposit."""
    monkeypatch.setenv("R2_ENDPOINT", "https://r2.example")
    ws = _workspace_with_two_files(tmp_path / "ws")
    steps = _record_deposits(ws, monkeypatch)
    with pytest.raises(SubmitError):  # the stub upload pointed nothing at R2
        ws.publish(zenodo=True)
    assert steps == ["upload", "zenodo"]
