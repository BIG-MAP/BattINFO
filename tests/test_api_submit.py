"""Regression tests for the registry submission contract (hardening plan Phase 2.4).

Pins ``submit_publication_package`` against a hostile / cold-starting registry:
- a 2xx with a non-JSON body is surfaced, not raised as ``JSONDecodeError`` (R-3);
- a read-timeout / network error is a typed transient error, not a bare
  ``TimeoutError`` that escapes the caller's ``except RuntimeError`` (R-4);
- a body-level ``rejected``/``failed`` status on a 2xx is not reported as ok (C-7);
- transient HTTP 5xx/429 are retried with backoff, other 4xx are not (A-1);
- a 409 still raises a ``RuntimeError`` whose message contains "409" and is not
  retried, so ``ws._do_submit``'s version-bump handling keeps working.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import (  # noqa: E402
    RegistryClientError,
    RegistryTransientError,
    submit_publication_package,
)

# backoff_sec=0 keeps the retry tests instant.
_KW = dict(registry_base_url="https://registry.example", api_key="k", backoff_sec=0)


class _FakeResp:
    """Minimal stand-in for the urlopen() context manager on the success path."""

    def __init__(self, code: int, body: str | bytes) -> None:
        self._code = code
        self._body = body

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def getcode(self) -> int:
        return self._code

    def read(self) -> bytes:
        return self._body if isinstance(self._body, bytes) else self._body.encode("utf-8")


def _http_error(code: int, body: str = "") -> HTTPError:
    return HTTPError(
        "https://registry.example/publication-packages",
        code,
        "error",
        {},  # type: ignore[arg-type]
        io.BytesIO(body.encode("utf-8")),
    )


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, actions: list[object]) -> dict[str, int]:
    """Replace battinfo.api.urlopen with a scripted sequence.

    Each element is either a ``_FakeResp`` (returned) or a ``BaseException``
    (raised). The last element repeats if there are more attempts than actions.
    """
    calls = {"n": 0}

    def fake_urlopen(_request: object, timeout: float | None = None) -> _FakeResp:
        idx = min(calls["n"], len(actions) - 1)
        calls["n"] += 1
        action = actions[idx]
        if isinstance(action, BaseException):
            raise action
        return action  # type: ignore[return-value]

    monkeypatch.setattr("battinfo.api.urlopen", fake_urlopen)
    return calls


def test_non_json_2xx_raises_client_error_not_jsondecodeerror(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, [_FakeResp(200, "<html>502 Bad Gateway</html>")])
    with pytest.raises(RegistryClientError):
        submit_publication_package({"kind": "x"}, **_KW)


def test_read_timeout_raises_transient_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_urlopen(monkeypatch, [TimeoutError("timed out")])
    with pytest.raises(RegistryTransientError):
        submit_publication_package({"kind": "x"}, max_attempts=3, **_KW)
    assert calls["n"] == 3  # the full retry budget was used


def test_timeout_error_is_a_runtimeerror(monkeypatch: pytest.MonkeyPatch) -> None:
    # ws._do_submit catches RuntimeError; the transient error must qualify.
    _patch_urlopen(monkeypatch, [TimeoutError("timed out")])
    with pytest.raises(RuntimeError):
        submit_publication_package({"kind": "x"}, max_attempts=1, **_KW)


def test_body_status_rejected_is_not_reported_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, [_FakeResp(200, json.dumps({"status": "rejected", "resources": []}))])
    result = submit_publication_package({"kind": "x"}, **_KW)
    assert result["status"] == "failed"


def test_body_status_published_is_ok_and_preserves_inner(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, [_FakeResp(200, json.dumps({"status": "published", "resources": []}))])
    result = submit_publication_package({"kind": "x"}, **_KW)
    assert result["status"] == "ok"
    assert result["response"]["status"] == "published"  # inner body status passes through untouched


def test_body_status_validated_is_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only failed/rejected/error flip the outer status; other non-2xx-reject bodies stay ok.
    _patch_urlopen(monkeypatch, [_FakeResp(200, json.dumps({"status": "validated"}))])
    result = submit_publication_package({"kind": "x"}, **_KW)
    assert result["status"] == "ok"


def test_retries_5xx_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_urlopen(
        monkeypatch,
        [_http_error(503, "down"), _FakeResp(200, json.dumps({"status": "published"}))],
    )
    result = submit_publication_package({"kind": "x"}, max_attempts=3, **_KW)
    assert result["status"] == "ok"
    assert calls["n"] == 2  # one retry, then success


def test_does_not_retry_4xx(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_urlopen(monkeypatch, [_http_error(422, json.dumps({"detail": "bad"}))])
    with pytest.raises(RegistryClientError):
        submit_publication_package({"kind": "x"}, max_attempts=3, **_KW)
    assert calls["n"] == 1  # a client error is terminal


def test_409_is_runtimeerror_with_code_and_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_urlopen(monkeypatch, [_http_error(409, "conflict")])
    with pytest.raises(RegistryClientError) as exc_info:
        submit_publication_package({"kind": "x"}, max_attempts=3, **_KW)
    assert isinstance(exc_info.value, RuntimeError)
    assert "409" in str(exc_info.value)  # ws._do_submit keys its version-bump retry on this
    assert calls["n"] == 1


def test_non_utf8_2xx_raises_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # A non-UTF-8 2xx body must surface as a RegistryClientError (a RuntimeError),
    # NOT a bare UnicodeDecodeError (a ValueError) that escapes except RuntimeError.
    _patch_urlopen(monkeypatch, [_FakeResp(200, b"\xff\xfe not utf-8 garbage")])
    with pytest.raises(RegistryClientError):
        submit_publication_package({"kind": "x"}, **_KW)


def test_connection_error_raises_transient_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _patch_urlopen(monkeypatch, [URLError("Connection refused")])
    with pytest.raises(RegistryTransientError):
        submit_publication_package({"kind": "x"}, max_attempts=3, **_KW)
    assert calls["n"] == 3


def test_max_attempts_below_one_raises_valueerror(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, [_FakeResp(200, json.dumps({"status": "published"}))])
    with pytest.raises(ValueError):
        submit_publication_package({"kind": "x"}, max_attempts=0, **_KW)


def test_do_submit_retries_on_409_with_version_bump(monkeypatch: pytest.MonkeyPatch) -> None:
    # End-to-end: a 409 RegistryClientError must still drive ws._do_submit's
    # version-bump retry (the load-bearing reason it subclasses RuntimeError and
    # keeps "409" in its message), then succeed on the second attempt.
    import battinfo.ws as ws_module

    calls = _patch_urlopen(
        monkeypatch,
        [
            _http_error(409, "conflict"),
            _FakeResp(200, json.dumps({"status": "published", "resources": [{"canonical_iri": "iri-1"}]})),
        ],
    )
    payload = {
        "source_version": "2026-06-27",
        "provenance": {},
        "resource": {"source_version": "2026-06-27"},
    }
    result = ws_module._do_submit(payload, "https://registry.example", "k", "Test Record")
    assert calls["n"] == 2  # 409, then a bumped-version retry that succeeds
    assert result["ok"] and result["status"] == "published"
    assert result["result"]["status_code"] == 200


@pytest.mark.parametrize("body", [b"42", b'"ok"', b"[1, 2]"])
def test_non_dict_json_2xx_raises_client_error(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    # A 2xx whose JSON body is a scalar/list (not an object) must surface as a
    # RegistryClientError, not pass a non-mapping through to callers.
    _patch_urlopen(monkeypatch, [_FakeResp(200, body)])
    with pytest.raises(RegistryClientError):
        submit_publication_package({"kind": "x"}, **_KW)


def test_do_submit_scalar_2xx_body_does_not_abort_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    # The scalar-body case must be recorded as one failed record (return []), not an
    # AttributeError that escapes _do_submit's except RuntimeError and aborts the batch.
    import battinfo.ws as ws_module

    _patch_urlopen(monkeypatch, [_FakeResp(200, b"42")])
    payload = {"source_version": "v1", "provenance": {}, "resource": {"source_version": "v1"}}
    result = ws_module._do_submit(payload, "https://registry.example", "k", "Test Record")
    assert result["ok"] is False and result["status"] == "error"  # one failed record, batch not aborted
