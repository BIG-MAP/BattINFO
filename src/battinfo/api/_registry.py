"""The registry HTTP client: submit_publication_package and the RegistryError family.

Split from the former monolithic ``battinfo/api.py`` (beta-hardening 4.2);
import the public surface from ``battinfo.api``, not from this module.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest

from battinfo.api._shared import PathLike
from battinfo.api._staging import build_curated_cell_spec_submission
from battinfo.validate.core import DEFAULT_POLICY, ValidationPolicy


def _urlopen(request: UrlRequest, *, timeout: float):  # noqa: ANN202
    """Open via ``battinfo.api.urlopen`` so tests that monkeypatch
    ``battinfo.api.urlopen`` keep intercepting registry HTTP calls now that this
    code lives in a submodule of the api package."""
    import battinfo.api as _facade  # noqa: PLC0415

    return _facade.urlopen(request, timeout=timeout)


class RegistryError(RuntimeError):
    """Base class for registry submission failures.

    Subclasses :class:`RuntimeError` so existing ``except RuntimeError`` handlers
    (e.g. ``ws._do_submit``) keep working unchanged.
    """

    def __init__(self, message: str, *, status_code: int | None = None, response_body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class RegistryClientError(RegistryError):
    """Terminal client-side failure (HTTP 4xx except 429, or a malformed response).

    The request will not succeed if retried as-is, so it is raised immediately.
    """


class RegistryTransientError(RegistryError):
    """Transient failure (connection error, timeout, HTTP 429/5xx).

    Safe to retry; raised only after the retry budget is exhausted.
    """


# HTTP statuses worth retrying: rate-limiting plus the standard transient 5xx set.
_REGISTRY_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
# Body-level statuses that mean "the registry rejected this record" even on a 2xx.
_REGISTRY_REJECTED_BODY_STATUS = frozenset({"failed", "rejected", "error"})
# Cap embedded response bodies so a misbehaving/echoing registry can't blow up
# (or leak large headers into) the raised error message.
_REGISTRY_ERROR_BODY_LIMIT = 500

_SECRET_TOKEN_RE = re.compile(r"bk_(?:live|test)_[A-Za-z0-9._-]+")


def _scrub_secret(text: str) -> str:
    """Redact BattINFO API-key tokens (``bk_live_``/``bk_test_``) from a registry response body
    before it is embedded in an exception message — defence in depth against a registry that
    echoes the key (A-6). Pattern-based, NOT value-based on purpose: the api_key never flows into
    logged/derived data, so it can't taint the (public) response we return and print."""
    return _SECRET_TOKEN_RE.sub("***", text)


def submit_publication_package(
    payload: Mapping[str, Any],
    *,
    registry_base_url: str,
    api_key: str,
    api_key_header: str = "X-Battinfo-API-Key",
    timeout_sec: float = 30.0,
    max_attempts: int = 3,
    backoff_sec: float = 0.5,
) -> dict[str, Any]:
    """POST a publication package to the registry, defending against a hostile/cold registry.

    Retries transient failures (connection/timeout, HTTP 429/5xx) with exponential
    backoff up to ``max_attempts``; never retries other 4xx (raised immediately as
    :class:`RegistryClientError`). A 2xx with a non-JSON body, or a body-level
    ``failed``/``rejected``/``error`` status, is surfaced rather than reported as a
    blanket success. Every failure raises a :class:`RegistryError` subclass — which
    is a :class:`RuntimeError`, so existing callers keep working.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    request_url = registry_base_url.rstrip("/") + "/publication-packages"
    request_payload = dict(payload)
    request_body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", api_key_header: api_key}

    last_transient: RegistryTransientError | None = None
    for attempt in range(max_attempts):
        request = UrlRequest(request_url, data=request_body, headers=headers, method="POST")
        try:
            with _urlopen(request, timeout=timeout_sec) as response:
                status_code = response.getcode()
                # errors="replace": a non-UTF-8 2xx body must not raise a bare
                # UnicodeDecodeError (a ValueError) that escapes the caller's
                # `except RuntimeError`; the body is only used for JSON/error text.
                response_text = _scrub_secret(response.read().decode("utf-8", errors="replace"))
            try:
                response_payload = json.loads(response_text) if response_text else None
            except json.JSONDecodeError as exc:
                # A 2xx carrying an HTML/proxy/cold-start body is NOT a success.
                raise RegistryClientError(
                    f"Registry returned a non-JSON response (HTTP {status_code}): "
                    f"{response_text[:_REGISTRY_ERROR_BODY_LIMIT]!r}",
                    status_code=status_code,
                    response_body=response_text[:_REGISTRY_ERROR_BODY_LIMIT],
                ) from exc
            if response_payload is not None and not isinstance(response_payload, dict):
                # A 2xx whose JSON body is a scalar/list rather than an object is not
                # a valid submission response; surface it as a typed RuntimeError
                # rather than passing a non-mapping through to callers that do
                # `(result["response"] or {}).get(...)` (which would raise AttributeError
                # and escape the caller's `except RuntimeError`, aborting the batch).
                raise RegistryClientError(
                    f"Registry returned a non-object JSON response (HTTP {status_code}): "
                    f"{response_text[:_REGISTRY_ERROR_BODY_LIMIT]!r}",
                    status_code=status_code,
                    response_body=response_text[:_REGISTRY_ERROR_BODY_LIMIT],
                )
            body_status = None
            if isinstance(response_payload, dict):
                raw_status = response_payload.get("status")
                if isinstance(raw_status, str):
                    body_status = raw_status.lower()
            outer_status = "failed" if body_status in _REGISTRY_REJECTED_BODY_STATUS else "ok"
            return {
                "status": outer_status,
                "url": request_url,
                "status_code": status_code,
                "response": response_payload,
            }
        except HTTPError as exc:
            body = _scrub_secret(exc.read().decode("utf-8", errors="replace")[:_REGISTRY_ERROR_BODY_LIMIT])
            try:
                detail: Any = json.loads(body) if body else None
            except json.JSONDecodeError:
                detail = body
            message = f"Registry submission failed with HTTP {exc.code}: {detail}"
            if exc.code in _REGISTRY_RETRYABLE_STATUS:
                last_transient = RegistryTransientError(message, status_code=exc.code, response_body=body)
            else:
                # Other 4xx (incl. 409 conflict, 422 validation) won't succeed on a
                # retry; raise now. The "HTTP <code>" text is preserved so the
                # caller's existing 409 handling still matches.
                raise RegistryClientError(message, status_code=exc.code, response_body=body) from exc
        except (URLError, TimeoutError, OSError) as exc:
            # Read-timeouts surface as a bare socket.timeout/TimeoutError (an OSError,
            # NOT a URLError), so the original URLError-only catch let them escape and
            # abort the whole batch. OSError is the safe superset.
            reason = getattr(exc, "reason", exc)
            last_transient = RegistryTransientError(f"Registry submission failed (network/timeout): {reason}")

        # Reached only on a transient failure: back off, then the loop retries
        # unless the attempt budget is exhausted.
        if attempt + 1 < max_attempts and backoff_sec > 0:
            time.sleep(backoff_sec * (2 ** attempt))
    # Only reachable via the transient path. Use an explicit raise (not assert,
    # which `python -O` strips) since this is load-bearing control flow.
    if last_transient is None:  # pragma: no cover - defensive; max_attempts >= 1
        raise RegistryClientError("Registry submission made no attempts")
    raise last_transient


def publish_curated_cell_spec(
    source: dict[str, Any] | PathLike,
    *,
    workspace_id: str,
    publisher_id: str,
    source_version: str,
    registry_base_url: str,
    api_key: str,
    api_key_header: str = "X-Battinfo-API-Key",
    source_local_id: str | None = None,
    title: str | None = None,
    publication_mode: str = "canonical-publication",
    source_system: str = "battinfo-records",
    workflow_name: str = "curated-cell-spec-publication",
    validation_policy: ValidationPolicy | str = DEFAULT_POLICY,
    timeout_sec: float = 30.0,
) -> dict[str, Any]:
    payload = build_curated_cell_spec_submission(
        source,
        workspace_id=workspace_id,
        publisher_id=publisher_id,
        source_version=source_version,
        source_local_id=source_local_id,
        title=title,
        publication_mode=publication_mode,
        source_system=source_system,
        workflow_name=workflow_name,
        validation_policy=validation_policy,
    )
    response = submit_publication_package(
        payload,
        registry_base_url=registry_base_url,
        api_key=api_key,
        api_key_header=api_key_header,
        timeout_sec=timeout_sec,
    )
    return {
        "status": response["status"],
        "request": payload,
        "response": response["response"],
        "status_code": response["status_code"],
        "url": response["url"],
    }
