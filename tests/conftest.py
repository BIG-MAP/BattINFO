"""Fixtures shared by the test modules."""

from __future__ import annotations

import io
import urllib.error

import pytest

from battinfo.registry import Registry


def _not_held(self: Registry, record: object, **kwargs: object) -> dict:
    raise urllib.error.HTTPError(str(record), 404, "Not Found", None, io.BytesIO(b'{"detail": "Resource not found."}'))  # type: ignore[arg-type]


@pytest.fixture()
def registry_holds_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A registry that holds none of the records a test submits or deposits.

    A submit or deposit first asks the registry about each IRI minted under
    ``/id/1001/`` (#483). This one is ``BATTINFO_REGISTRY_URL``, so a workspace
    opened with ``registry_url=None`` asks it too, and it answers 404 for
    every record. Modules that submit or deposit offline use it with
    ``pytestmark = pytest.mark.usefixtures("registry_holds_none")``.
    """
    monkeypatch.setenv("BATTINFO_REGISTRY_URL", "https://registry.example")
    monkeypatch.setattr(Registry, "get", _not_held)
