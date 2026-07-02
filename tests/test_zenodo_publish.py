"""A-5: the Zenodo HTTP layer must (1) retry idempotent reads on transient failures, (2) never
retry a write (a publish retry could mint a second DOI), (3) surface connection/timeout errors as
a clean ZenodoError instead of a raw urllib exception, and (4) confirm-on-transient for publish so
a timed-out-but-committed publish is reported as success rather than a phantom failure."""
from __future__ import annotations

import io
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import zenodo as zmod
from battinfo.zenodo import ZenodoClient, ZenodoError


class _FakeResp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *a: object) -> None:
        return None


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, handler) -> list[str]:
    """Route urlopen through *handler(req, calls)*; return the mutable call log."""
    calls: list[str] = []

    def fake_urlopen(req, timeout=None):  # noqa: ANN001
        calls.append(f"{req.get_method()} {req.full_url}")
        return handler(req, calls)

    monkeypatch.setattr(zmod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(zmod.time, "sleep", lambda *_: None)  # no real backoff waits
    return calls


def _client() -> ZenodoClient:
    return ZenodoClient(token="fake-token", sandbox=True)


def test_get_retries_transient_url_error_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req, calls):  # noqa: ANN001
        if len(calls) < 3:  # fail the first two attempts
            raise urllib.error.URLError("connection reset")
        return _FakeResp(b'{"id": 42, "state": "unsubmitted"}')

    calls = _patch_urlopen(monkeypatch, handler)
    dep = _client().get_deposit(42)
    assert dep["id"] == 42
    assert len(calls) == 3  # two retries, then success


def test_get_gives_up_after_max_attempts_as_zenodo_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req, calls):  # noqa: ANN001
        raise urllib.error.URLError("dns failure")

    calls = _patch_urlopen(monkeypatch, handler)
    with pytest.raises(ZenodoError):
        _client().get_deposit(42)
    assert len(calls) == 3  # bounded, not infinite


def test_write_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req, calls):  # noqa: ANN001
        raise urllib.error.URLError("timeout")

    calls = _patch_urlopen(monkeypatch, handler)
    with pytest.raises(ZenodoError):
        _client().update_metadata(42, {"title": "x"})  # PUT
    assert len(calls) == 1  # exactly once — no double-write


def test_transient_error_becomes_clean_zenodo_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req, calls):  # noqa: ANN001
        raise TimeoutError("read timed out")

    _patch_urlopen(monkeypatch, handler)
    with pytest.raises(ZenodoError, match="Zenodo request failed"):
        _client().get_deposit(42)


def test_publish_confirms_success_when_transiently_failed_but_committed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # POST publish times out (never retried), but the GET confirms the deposit is published.
    def handler(req, calls):  # noqa: ANN001
        if req.get_method() == "POST":
            raise urllib.error.URLError("timeout after publish accepted")
        return _FakeResp(b'{"id": 42, "state": "done", "submitted": true}')

    calls = _patch_urlopen(monkeypatch, handler)
    dep = _client().publish_deposit(42)
    assert dep["state"] == "done"
    assert calls[0].startswith("POST")  # publish attempted exactly once
    assert sum(c.startswith("POST") for c in calls) == 1


def test_publish_reraises_when_deposit_not_actually_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(req, calls):  # noqa: ANN001
        if req.get_method() == "POST":
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(b"nope"))
        return _FakeResp(b'{"id": 42, "state": "unsubmitted"}')

    _patch_urlopen(monkeypatch, handler)
    with pytest.raises(ZenodoError):
        _client().publish_deposit(42)
