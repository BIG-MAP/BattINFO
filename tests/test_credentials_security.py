"""A-6: the credentials file must be owner-only, and a registry response body embedded in an
error message must not leak the api_key (defence in depth against a registry that echoes it).

The same holds for every file that keeps a secret: the .battinfo/credentials file that
ws.setup() creates or ws.login() updates, ~/.battinfo/config.yaml, which can hold a
Zenodo token, and the publisher API key that `battinfo registry bootstrap --api-key-file`
writes."""
from __future__ import annotations

import json
import os
import stat
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import config
from battinfo.api import _scrub_secret
from battinfo.ws import AuthoringWorkspace

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are a no-op on Windows")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_scrub_secret_redacts_key_tokens() -> None:
    key = "bk_live_ABC123def456"
    scrubbed = _scrub_secret(f"401 Unauthorized: key {key} rejected; also bk_test_zzz999")
    assert key not in scrubbed
    assert "bk_test_zzz999" not in scrubbed  # any BattINFO key token redacted
    assert "Unauthorized" in scrubbed  # non-secret context preserved
    assert _scrub_secret("no secrets here") == "no secrets here"


@posix_only
def test_credentials_file_is_owner_only(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    path = ws._set_credentials({"api_key": "bk_live_secret"})
    assert path.exists()
    mode = _mode(path)
    assert mode == 0o600, oct(mode)  # no group/other read of API keys / R2 secrets / tokens


@posix_only
def test_login_makes_a_readable_credentials_file_owner_only(tmp_path: Path) -> None:
    path = tmp_path / ".battinfo" / "credentials"
    path.parent.mkdir()
    path.write_text("BATTINFO_API_KEY = bk_live_old\n", encoding="utf-8")
    os.chmod(path, 0o644)
    AuthoringWorkspace(root=tmp_path, registry_url=None)._set_credentials({"BATTINFO_API_KEY": "bk_live_new"})
    assert _mode(path) == 0o600, oct(_mode(path))


@posix_only
def test_setup_creates_an_owner_only_credentials_file(tmp_path: Path) -> None:
    path = AuthoringWorkspace(root=tmp_path, registry_url=None).setup()
    assert _mode(path) == 0o600, oct(_mode(path))


@posix_only
def test_setup_makes_an_existing_credentials_file_owner_only(tmp_path: Path) -> None:
    path = tmp_path / ".battinfo" / "credentials"
    path.parent.mkdir()
    path.write_text("ZENODO_API_TOKEN = zt_written_by_hand\n", encoding="utf-8")
    os.chmod(path, 0o644)
    assert AuthoringWorkspace(root=tmp_path, registry_url=None).setup() == path.resolve()
    assert _mode(path) == 0o600, oct(_mode(path))
    assert path.read_text(encoding="utf-8") == "ZENODO_API_TOKEN = zt_written_by_hand\n"


@posix_only
@pytest.mark.parametrize("existing", [False, True], ids=["new-file", "readable-file"])
def test_user_config_file_is_owner_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool) -> None:
    path = tmp_path / ".battinfo" / "config.yaml"
    monkeypatch.setattr(config, "USER_CONFIG_PATH", path)
    if existing:
        path.parent.mkdir()
        path.write_text("license: CC0-1.0\n", encoding="utf-8")
        os.chmod(path, 0o644)
    config.set_user_config_value("zenodo_token", "zt_live_8f3a91c2d4e5b6a7")
    assert _mode(path) == 0o600, oct(_mode(path))


def test_every_secret_file_write_asks_for_owner_only_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows ignores the mode, so this checks the request on every platform."""
    requested: list[tuple[Path, int]] = []
    real_chmod = os.chmod

    def recording_chmod(path: str | os.PathLike[str], mode: int, *args: object, **kwargs: object) -> None:
        requested.append((Path(path).resolve(), mode))
        real_chmod(path, mode, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "chmod", recording_chmod)
    config_path = tmp_path / "home" / ".battinfo" / "config.yaml"
    monkeypatch.setattr(config, "USER_CONFIG_PATH", config_path)
    ws = AuthoringWorkspace(root=tmp_path / "lab", registry_url=None)
    credentials = (tmp_path / "lab" / ".battinfo" / "credentials").resolve()

    ws.setup()
    assert requested == [(credentials, 0o600)]
    requested.clear()
    ws.setup()  # the file exists: setup() still restricts it
    assert requested == [(credentials, 0o600)]
    requested.clear()
    ws._set_credentials({"BATTINFO_API_KEY": "bk_live_secret"})
    assert requested == [(credentials, 0o600)]
    requested.clear()
    config.set_user_config_value("zenodo_token", "zt_live_8f3a91c2d4e5b6a7")
    assert requested == [(config_path.resolve(), 0o600)]


class _Created:
    """A registry answer of HTTP 201 with a JSON body."""

    status = 201

    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> _Created:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def test_registry_bootstrap_writes_the_new_api_key_owner_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from battinfo.cli import app

    requested: list[tuple[Path, int]] = []
    real_chmod = os.chmod

    def recording_chmod(path: str | os.PathLike[str], mode: int, *args: object, **kwargs: object) -> None:
        requested.append((Path(path).resolve(), mode))
        real_chmod(path, mode, *args, **kwargs)  # type: ignore[arg-type]

    def fake_registry(request: urllib.request.Request, timeout: float = 0) -> _Created:
        # The publisher is new, so the registry mints its API key.
        minted = request.full_url.endswith("/publishers")
        return _Created({"api_key": "bk_live_minted_9f8e7d6c"} if minted else {})

    monkeypatch.setattr(os, "chmod", recording_chmod)
    monkeypatch.setattr(urllib.request, "urlopen", fake_registry)
    key_file = tmp_path / "publisher.key"

    # The default --format, text, used to be refused once the publisher existed.
    result = CliRunner().invoke(app, [
        "registry", "bootstrap", "--workspace-id", "lab", "--publisher-id", "lab",
        "--registry-url", "https://registry.example", "--admin-token", "admin-token",
        "--api-key-file", str(key_file),
    ])

    assert result.exit_code == 0, result.output
    assert "Saved to:" in result.output
    assert key_file.read_text(encoding="utf-8") == "bk_live_minted_9f8e7d6c"
    assert (key_file.resolve(), 0o600) in requested
    if os.name != "nt":
        assert _mode(key_file) == 0o600, oct(_mode(key_file))


@pytest.mark.parametrize(("output_format", "exit_code", "asked"), [("xml", 2, False), ("table", 0, True)])
def test_registry_bootstrap_checks_the_format_before_asking_the_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output_format: str, exit_code: int, asked: bool
) -> None:
    from typer.testing import CliRunner

    from battinfo.cli import app

    urls: list[str] = []

    def fake_registry(request: urllib.request.Request, timeout: float = 0) -> _Created:
        urls.append(request.full_url)
        return _Created({})

    monkeypatch.setattr(urllib.request, "urlopen", fake_registry)
    result = CliRunner().invoke(app, [
        "registry", "bootstrap", "--workspace-id", "lab", "--publisher-id", "lab",
        "--registry-url", "https://registry.example", "--admin-token", "admin-token",
        "--format", output_format,
    ])

    assert result.exit_code == exit_code, result.output
    assert bool(urls) == asked
