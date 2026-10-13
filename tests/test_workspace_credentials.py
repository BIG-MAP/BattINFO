"""Each workspace reads its own .battinfo/credentials and leaves os.environ alone.

Opening a workspace used to copy its credentials file into the process
environment, and the first workspace opened won: every workspace opened after
it in the same session submitted, deposited and logged in with the first one's
API key, workspace id and Zenodo token. These tests pin the lookup order (an
argument passed to the call, ws.login() in this session, an environment
variable, this workspace's credentials file, then the default) and the checks
that replace reading os.environ: ws.credentials_status(), ws.has_credential()
and ws.whoami(). They also pin BATTINFO_REGISTRY_URL, which battinfo.workspace()
used to ignore. Everything runs offline: the registry and Zenodo are fakes.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402
from battinfo import CellSpec  # noqa: E402
from battinfo.ws import _DEFAULT_REGISTRY_URL, AuthoringWorkspace  # noqa: E402

CREATORS = [{"name": "Lovelace, Ada"}]
REGISTRY = "https://registry.example"
# Every name the workspace reads, in the order ws.credentials_status() lists them.
NAMES = (
    "BATTINFO_API_KEY", "BATTINFO_WORKSPACE_ID", "BATTINFO_PUBLISHER_ID", "BATTINFO_ADMIN_TOKEN",
    "BATTINFO_REGISTRY_URL",
    "R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_BUCKET_PUBLIC",
    "R2_BUCKET_PRIVATE", "R2_PUBLIC_BASE_URL",
    "ZENODO_API_TOKEN", "ZENODO_SANDBOX_TOKEN",
)


@pytest.fixture(autouse=True)
def _clean_environment() -> Iterator[None]:
    """Run each test with none of the names exported, and put os.environ back afterwards."""
    with mock.patch.dict(os.environ):
        for name in NAMES:
            os.environ.pop(name, None)
        yield


def _write_credentials(root: Path, **values: str) -> Path:
    path = root / ".battinfo" / "credentials"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{name:22} = {value}\n" for name, value in values.items()), encoding="utf-8")
    return path


def _saved_workspace(root: Path) -> AuthoringWorkspace:
    ws = battinfo.workspace(root, registry_url=None)
    ws.add("cell", spec=CellSpec(manufacturer="Example Lab", model="R2032", format="coin",
                                 chemistry="li-ion"), serial_numbers=["C01"])
    ws.save()
    return ws


class _FakeZenodo:
    """Stands in for battinfo.zenodo.ZenodoClient and remembers the token it was given."""

    def __init__(self) -> None:
        self.clients: list[tuple[str, bool]] = []

    def client(self, token: str, sandbox: bool = False) -> _FakeZenodo:
        self.clients.append((token, sandbox))
        return self

    def create_empty_deposit(self) -> dict:
        return {"id": 7, "record_id": 7, "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.7"}}}

    def sync_files(self, deposit_id: int, upload_map: dict) -> dict:
        return {"uploaded": sorted(upload_map.values()), "kept": [], "removed": []}

    def update_metadata(self, deposit_id: int, metadata: dict) -> dict:
        return {}


@pytest.fixture()
def fake_zenodo(monkeypatch: pytest.MonkeyPatch) -> _FakeZenodo:
    fake = _FakeZenodo()
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", fake.client)
    return fake


class _Response:
    def __init__(self, body: object) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class _FakeRegistryHttp:
    """Stands in for urllib.request.urlopen: records each request and gives one canned answer."""

    def __init__(self, answer: object = None) -> None:
        self.requests: list[urllib.request.Request] = []
        self.answer = answer

    def __call__(self, request: urllib.request.Request | str, timeout: float = 0) -> _Response:
        if isinstance(request, str):
            request = urllib.request.Request(request)
        self.requests.append(request)
        if isinstance(self.answer, Exception):
            raise self.answer
        return _Response(self.answer)

    @property
    def urls(self) -> list[str]:
        return [request.full_url for request in self.requests]


def _registry_http(monkeypatch: pytest.MonkeyPatch, answer: object = None) -> _FakeRegistryHttp:
    fake = _FakeRegistryHttp(answer)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return fake


# ── one workspace, one credentials file ──────────────────────────────────────


def test_each_workspace_reads_only_its_own_credentials_file(tmp_path: Path) -> None:
    _write_credentials(tmp_path / "lab-a", BATTINFO_API_KEY="KEY-OF-LAB-A",
                       BATTINFO_WORKSPACE_ID="ws-lab-a", ZENODO_API_TOKEN="ZTOK-A")
    _write_credentials(tmp_path / "lab-b", BATTINFO_API_KEY="KEY-OF-LAB-B",
                       BATTINFO_WORKSPACE_ID="ws-lab-b", ZENODO_API_TOKEN="ZTOK-B")
    (tmp_path / "lab-c").mkdir()
    environment = dict(os.environ)

    lab_a = battinfo.workspace(tmp_path / "lab-a", registry_url=None)
    lab_b = battinfo.workspace(tmp_path / "lab-b", registry_url=None)
    lab_c = battinfo.workspace(tmp_path / "lab-c", registry_url=None)

    assert dict(os.environ) == environment, "opening a workspace must not change os.environ"
    assert lab_a._credential("BATTINFO_API_KEY") == "KEY-OF-LAB-A"
    assert lab_a._credential("BATTINFO_WORKSPACE_ID") == "ws-lab-a"
    assert lab_a._credential("ZENODO_API_TOKEN") == "ZTOK-A"
    assert lab_b._credential("BATTINFO_API_KEY") == "KEY-OF-LAB-B"
    assert lab_b._credential("BATTINFO_WORKSPACE_ID") == "ws-lab-b"
    assert lab_b._credential("ZENODO_API_TOKEN") == "ZTOK-B"
    for name in ("BATTINFO_API_KEY", "BATTINFO_WORKSPACE_ID", "ZENODO_API_TOKEN"):
        assert lab_c._credential(name) is None
        assert lab_c.has_credential(name) is False
        assert lab_a.has_credential(name) and lab_b.has_credential(name)
    assert lab_a.credentials_status()["BATTINFO_API_KEY"] == {"set": True, "source": "credentials_file"}
    assert lab_c.credentials_status()["BATTINFO_API_KEY"] == {"set": False, "source": None}


def test_opening_a_workspace_with_the_default_registry_leaves_the_environment_alone(tmp_path: Path) -> None:
    _write_credentials(tmp_path, BATTINFO_API_KEY="bk_test_key", BATTINFO_REGISTRY_URL="https://file.example",
                       R2_ENDPOINT="https://r2.example", ZENODO_SANDBOX_TOKEN="sandbox-token")
    environment = dict(os.environ)
    ws = battinfo.workspace(tmp_path)
    assert dict(os.environ) == environment
    assert ws._registry_url == "https://file.example"


def test_a_credentials_file_written_after_opening_is_read(tmp_path: Path) -> None:
    ws = battinfo.workspace(tmp_path, registry_url=None)
    assert not ws.has_credential("ZENODO_SANDBOX_TOKEN")
    _write_credentials(tmp_path, ZENODO_SANDBOX_TOKEN="sandbox-token")
    assert ws.has_credential("ZENODO_SANDBOX_TOKEN")
    assert "ZENODO_SANDBOX_TOKEN" not in os.environ


# ── the lookup order, through the calls that use it ──────────────────────────


@pytest.mark.parametrize(("sandbox", "name"), [(False, "ZENODO_API_TOKEN"), (True, "ZENODO_SANDBOX_TOKEN")])
def test_zenodo_finds_a_token_that_is_only_in_the_credentials_file(
    tmp_path: Path, fake_zenodo: _FakeZenodo, sandbox: bool, name: str
) -> None:
    _write_credentials(tmp_path, **{name: "token-from-the-file"})
    ws = _saved_workspace(tmp_path)

    result = ws.zenodo(sandbox=sandbox, creators=CREATORS)

    assert fake_zenodo.clients == [("token-from-the-file", sandbox)]
    assert result.record_id == "7" and not result.published
    assert name not in os.environ


def test_an_exported_variable_overrides_the_credentials_file(
    tmp_path: Path, fake_zenodo: _FakeZenodo, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_credentials(tmp_path, ZENODO_API_TOKEN="token-from-the-file")
    monkeypatch.setenv("ZENODO_API_TOKEN", "token-from-the-environment")
    ws = _saved_workspace(tmp_path)

    ws.zenodo(creators=CREATORS)

    assert fake_zenodo.clients == [("token-from-the-environment", False)]
    assert ws.credentials_status()["ZENODO_API_TOKEN"] == {"set": True, "source": "environment"}


def test_an_explicit_argument_overrides_the_environment_and_the_file(
    tmp_path: Path, fake_zenodo: _FakeZenodo, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_credentials(tmp_path, ZENODO_API_TOKEN="token-from-the-file")
    monkeypatch.setenv("ZENODO_API_TOKEN", "token-from-the-environment")
    ws = _saved_workspace(tmp_path)

    ws.zenodo(token="token-passed-in", creators=CREATORS)

    assert fake_zenodo.clients == [("token-passed-in", False)]


def test_zenodo_without_a_token_names_both_places_to_put_one(tmp_path: Path) -> None:
    ws = _saved_workspace(tmp_path)
    with pytest.raises(RuntimeError, match=r"ZENODO_SANDBOX_TOKEN.*\.battinfo/credentials"):
        ws.zenodo(sandbox=True, creators=CREATORS)


def test_submit_resolves_each_credential_in_the_documented_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_credentials(
        tmp_path, BATTINFO_REGISTRY_URL="https://file.example", BATTINFO_API_KEY="key-from-the-file",
        BATTINFO_WORKSPACE_ID="ws-from-the-file", BATTINFO_PUBLISHER_ID="pub-from-the-file",
    )
    monkeypatch.setenv("BATTINFO_API_KEY", "key-from-the-environment")
    ws = battinfo.workspace(tmp_path)  # the registry comes from the file
    ws.add("cell", spec=CellSpec(manufacturer="Example Lab", model="R2032", format="coin",
                                 chemistry="li-ion"), serial_numbers=["C01"])
    ws.save()
    sent: list[dict] = []

    def fake_submit(payload: dict, *, registry_base_url: str, api_key: str, **kw: object) -> dict:
        sent.append({"url": registry_base_url, "key": api_key,
                     "workspace": payload["workspace_id"], "publisher": payload["publisher_id"]})
        return {"status": "ok", "response": {"status": "validated", "resources": [{"canonical_iri": "x"}]}}

    monkeypatch.setattr("battinfo.api.submit_publication_package", fake_submit)

    ws.submit()
    assert {(s["url"], s["key"], s["workspace"], s["publisher"]) for s in sent} == {
        ("https://file.example", "key-from-the-environment", "ws-from-the-file", "pub-from-the-file")
    }

    sent.clear()
    ws.submit(registry_url="https://passed.example", api_key="key-passed-in", workspace_id="ws-passed-in",
              resume=False)
    assert {(s["url"], s["key"], s["workspace"], s["publisher"]) for s in sent} == {
        ("https://passed.example", "key-passed-in", "ws-passed-in", "pub-from-the-file")
    }


def test_a_login_in_this_session_beats_the_environment_and_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_credentials(tmp_path, BATTINFO_API_KEY="key-from-the-file", BATTINFO_WORKSPACE_ID="ws-from-the-file")
    monkeypatch.setenv("BATTINFO_WORKSPACE_ID", "ws-from-the-environment")
    ws = battinfo.workspace(tmp_path, registry_url=REGISTRY)
    assert ws._credential("BATTINFO_WORKSPACE_ID") == "ws-from-the-environment"

    _registry_http(monkeypatch, {"workspace_id": "ws-from-the-registry", "publisher_id": "pub-from-the-registry"})
    ws.login(api_key="key-passed-in")

    status = ws.credentials_status()
    assert status["BATTINFO_API_KEY"] == {"set": True, "source": "login"}
    assert status["BATTINFO_WORKSPACE_ID"] == {"set": True, "source": "login"}
    assert ws._credential("BATTINFO_WORKSPACE_ID") == "ws-from-the-registry"
    assert ws._credential("BATTINFO_WORKSPACE_ID", explicit="ws-passed-in") == "ws-passed-in"


def test_approve_and_the_registry_reads_use_this_workspaces_admin_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_credentials(tmp_path / "reviewer", BATTINFO_ADMIN_TOKEN="admin-from-the-file")
    # Opening the reviewer's workspace first used to hand its admin token to every later one.
    battinfo.workspace(tmp_path / "reviewer", registry_url=REGISTRY)
    author = battinfo.workspace(tmp_path / "author", registry_url=REGISTRY)
    assert "X-Battinfo-Admin-Token" not in author._registry_read_headers()
    with pytest.raises(RuntimeError, match="admin_token"):
        author.approve("sub-1")

    reviewer = battinfo.workspace(tmp_path / "reviewer", registry_url=REGISTRY)
    http = _registry_http(monkeypatch, {"title": "t", "status": "published"})
    reviewer.approve("sub-1")
    assert http.requests[0].get_header("X-battinfo-admin-token") == "admin-from-the-file"
    assert reviewer._registry_read_headers()["X-Battinfo-Admin-Token"] == "admin-from-the-file"


def test_upload_reads_r2_settings_from_this_workspaces_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    boto3 = pytest.importorskip("boto3")
    _write_credentials(tmp_path / "with-r2", R2_ENDPOINT="https://r2.example", R2_ACCESS_KEY_ID="r2-id",
                       R2_SECRET_ACCESS_KEY="r2-secret", R2_BUCKET="lab-bucket")
    with_r2 = battinfo.workspace(tmp_path / "with-r2", registry_url=None)
    without_r2 = battinfo.workspace(tmp_path / "without-r2", registry_url=None)
    assert with_r2._r2_configured() and not without_r2._r2_configured()

    class _Stop(Exception):
        pass

    seen: dict = {}

    def fake_client(service: str, **kwargs: object) -> None:
        seen.update(kwargs)
        raise _Stop

    monkeypatch.setattr(boto3, "client", fake_client)
    with pytest.raises(_Stop):
        with_r2.upload(dry_run=True)
    assert seen == {"endpoint_url": "https://r2.example", "aws_access_key_id": "r2-id",
                    "aws_secret_access_key": "r2-secret"}
    with pytest.raises(RuntimeError, match="R2_ENDPOINT"):
        without_r2.upload(dry_run=True)


# ── login() keeps what it saves to what the registry or the caller gave ───────


def test_login_does_not_save_another_workspaces_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_credentials(tmp_path / "lab-a", BATTINFO_API_KEY="KEY-OF-LAB-A",
                       BATTINFO_WORKSPACE_ID="ws-lab-a", BATTINFO_PUBLISHER_ID="pub-lab-a")
    # Opening lab A first used to put its ids where lab B's login() picked them up and saved them.
    battinfo.workspace(tmp_path / "lab-a", registry_url=REGISTRY)
    lab_b = battinfo.workspace(tmp_path / "lab-b", registry_url=REGISTRY)
    _registry_http(monkeypatch, OSError("registry down"))

    result = lab_b.login(api_key="KEY-OF-LAB-B")

    saved = (tmp_path / "lab-b" / ".battinfo" / "credentials").read_text(encoding="utf-8")
    assert "KEY-OF-LAB-B" in saved
    assert "ws-lab-a" not in saved and "pub-lab-a" not in saved and "KEY-OF-LAB-A" not in saved
    assert (result["workspace_id"], result["publisher_id"]) == ("battinfo-records", "battinfo-authoring")


def test_login_uses_but_does_not_save_ids_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BATTINFO_WORKSPACE_ID", "ws-from-the-environment")
    ws = battinfo.workspace(tmp_path, registry_url=REGISTRY)
    _registry_http(monkeypatch, urllib.error.URLError("registry down"))

    result = ws.login(api_key="bk_test_key")

    assert result["workspace_id"] == "ws-from-the-environment"
    assert "ws-from-the-environment" not in ws._credentials_path().read_text(encoding="utf-8")
    assert "environment" in capsys.readouterr().out


def test_login_saves_the_identity_the_registry_returns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BATTINFO_WORKSPACE_ID", "ws-from-the-environment")
    ws = battinfo.workspace(tmp_path, registry_url=REGISTRY)
    _registry_http(monkeypatch, {"workspace_id": "ws-from-the-registry", "publisher_id": "pub-from-the-registry"})

    result = ws.login(api_key="bk_test_key")

    saved = ws._credentials_path().read_text(encoding="utf-8")
    assert "ws-from-the-registry" in saved and "pub-from-the-registry" in saved
    assert result["workspace_id"] == "ws-from-the-registry"
    assert os.environ["BATTINFO_WORKSPACE_ID"] == "ws-from-the-environment"


# ── BATTINFO_REGISTRY_URL ────────────────────────────────────────────────────


def test_workspace_honours_the_registry_url_variable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from battinfo.registry import Registry

    monkeypatch.setenv("BATTINFO_REGISTRY_URL", "https://staging.example/")
    ws = battinfo.workspace(tmp_path)
    assert ws._registry_url == Registry().url == "https://staging.example"
    assert ws.credentials_status()["BATTINFO_REGISTRY_URL"] == {"set": True, "source": "environment"}

    explicit = battinfo.workspace(tmp_path, registry_url="https://explicit.example")
    assert explicit._registry_url == "https://explicit.example"
    assert explicit.credentials_status()["BATTINFO_REGISTRY_URL"] == {"set": True, "source": "argument"}

    assert battinfo.workspace(tmp_path, registry_url=None)._registry_url is None  # None: no lookups


def test_workspace_reads_the_registry_url_from_its_credentials_file(tmp_path: Path) -> None:
    _write_credentials(tmp_path / "staging-lab", BATTINFO_REGISTRY_URL="https://staging.example")
    staging = battinfo.workspace(tmp_path / "staging-lab")
    production = battinfo.workspace(tmp_path / "production-lab")
    assert staging._registry_url == "https://staging.example"
    assert staging.credentials_status()["BATTINFO_REGISTRY_URL"]["source"] == "credentials_file"
    assert production._registry_url == _DEFAULT_REGISTRY_URL
    assert production.credentials_status()["BATTINFO_REGISTRY_URL"] == {"set": True, "source": "default"}


def test_status_and_whoami_ask_the_registry_the_workspace_was_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_credentials(tmp_path, BATTINFO_API_KEY="bk_test_key", BATTINFO_WORKSPACE_ID="ws-1")
    monkeypatch.setenv("BATTINFO_REGISTRY_URL", "https://staging.example")
    ws = battinfo.workspace(tmp_path)
    http = _registry_http(monkeypatch, [])

    ws.status()
    ws.whoami()

    assert http.urls == ["https://staging.example/workspaces/ws-1/submissions", "https://staging.example/me"]


def test_a_workspace_without_a_registry_never_falls_back_to_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_credentials(tmp_path, BATTINFO_API_KEY="bk_test_key", BATTINFO_WORKSPACE_ID="ws-1")
    ws = battinfo.workspace(tmp_path, registry_url=None)
    http = _registry_http(monkeypatch, [])

    with pytest.raises(RuntimeError, match="registry_url"):
        ws.login(api_key="bk_test_key")
    with pytest.raises(RuntimeError, match="registry_url"):
        ws.status()
    with pytest.raises(RuntimeError, match="registry_url"):
        ws.pending()
    result = ws.whoami()

    assert http.requests == []
    assert result["workspace_id"] == "ws-1"
    assert "registry_url=None" in capsys.readouterr().out

    # BATTINFO_REGISTRY_URL still names a registry for the calls that need one.
    monkeypatch.setenv("BATTINFO_REGISTRY_URL", "https://staging.example")
    ws.status()
    assert http.urls == ["https://staging.example/workspaces/ws-1/submissions"]
    assert ws._registry_url is None  # lookups stay off


# ── the public checks ────────────────────────────────────────────────────────


def test_credentials_status_reports_sources_and_never_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = {
        "BATTINFO_API_KEY": "bk_live_file_secret_1",
        "R2_SECRET_ACCESS_KEY": "r2-file-secret-2",
        "ZENODO_SANDBOX_TOKEN": "zenodo-file-secret-3",
        "BATTINFO_ADMIN_TOKEN": "admin-file-secret-4",
    }
    _write_credentials(tmp_path, **secrets)
    monkeypatch.setenv("ZENODO_API_TOKEN", "zenodo-env-secret-5")
    ws = battinfo.workspace(tmp_path, registry_url=REGISTRY)
    _registry_http(monkeypatch, {"workspace_id": "ws-session-6", "publisher_id": "pub-session-7"})
    ws.login(api_key="bk_live_login_secret_8")

    status = ws.credentials_status()

    shown = json.dumps(status) + repr(status) + str(status)
    for value in [*secrets.values(), "zenodo-env-secret-5", "ws-session-6", "pub-session-7",
                  "bk_live_login_secret_8", REGISTRY]:
        assert value not in shown
    assert tuple(status) == NAMES
    assert all(set(entry) == {"set", "source"} for entry in status.values())
    assert status["BATTINFO_API_KEY"] == {"set": True, "source": "login"}
    assert status["R2_SECRET_ACCESS_KEY"] == {"set": True, "source": "credentials_file"}
    assert status["ZENODO_API_TOKEN"] == {"set": True, "source": "environment"}
    assert status["R2_ENDPOINT"] == {"set": False, "source": None}


def test_has_credential_rejects_a_name_the_workspace_never_reads(tmp_path: Path) -> None:
    ws = battinfo.workspace(tmp_path, registry_url=None)
    with pytest.raises(ValueError, match="ZENODO_API_TOKEN"):
        ws.has_credential("ZENODO_TOKEN")


def test_whoami_says_where_each_credential_came_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_credentials(tmp_path, BATTINFO_API_KEY="bk_live_file_key")
    ws = battinfo.workspace(tmp_path, registry_url=REGISTRY)
    _registry_http(monkeypatch, {"display_name": "Ada", "workspace_id": "ws-1", "publisher_id": "pub-1"})

    profile = ws.whoami()

    out = capsys.readouterr().out
    assert profile["credential_sources"] == {"BATTINFO_API_KEY": "credentials_file",
                                             "BATTINFO_REGISTRY_URL": "argument"}
    assert ".battinfo/credentials" in out and "bk_live_file_key" not in out

    monkeypatch.setenv("BATTINFO_API_KEY", "bk_live_env_key")
    assert ws.whoami()["credential_sources"]["BATTINFO_API_KEY"] == "environment"
    assert "environment" in capsys.readouterr().out


def test_whoami_without_the_registry_names_the_source_of_each_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_credentials(tmp_path, BATTINFO_API_KEY="bk_live_file_key", BATTINFO_WORKSPACE_ID="ws-from-the-file")
    ws = battinfo.workspace(tmp_path, registry_url=REGISTRY)
    _registry_http(monkeypatch, OSError("registry down"))

    result = ws.whoami()

    assert result["workspace_id"] == "ws-from-the-file"
    assert result["publisher_id"] == "battinfo-authoring"
    assert result["credential_sources"] == {
        "BATTINFO_API_KEY": "credentials_file", "BATTINFO_REGISTRY_URL": "argument",
        "BATTINFO_WORKSPACE_ID": "credentials_file", "BATTINFO_PUBLISHER_ID": "default",
    }
    out = capsys.readouterr().out
    assert "registry profile unavailable" in out and "bk_live_file_key" not in out


def test_setup_template_documents_the_lookup_order(tmp_path: Path) -> None:
    ws = battinfo.workspace(tmp_path, registry_url=None)
    text = ws.setup().read_text(encoding="utf-8")
    order = ["1. an argument", "2. a value ws.login() set", "3. an environment variable", "4. this file",
             "5. the default"]
    positions = [text.find(step) for step in order]
    assert -1 not in positions and positions == sorted(positions), positions
    assert "ws.credentials_status()" in text
    assert ws.credentials_status()["BATTINFO_WORKSPACE_ID"] == {"set": True, "source": "credentials_file"}
