"""Registry listing pagination (#340/#341).

A single GET of /resources is capped by the server at one page (default 100
rows, newest first), so the client-side caches that treated one response as
the full catalog silently lost every record older than the first page — and
the workspace then re-minted IRIs for records that were already registered.
These tests pin the exhaustive-pagination behavior of _fetch_resource_pages
and its two consumers (_registry_resources, _build_api_cache).
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.ws import AuthoringWorkspace  # noqa: E402

PAGE_LIMIT = AuthoringWorkspace._RESOURCES_PAGE_LIMIT


class _Resp:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *a: object) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _paginating_server(corpus: list[dict], seen_urls: list[str], *, ignore_offset: bool = False):
    """Fake urlopen serving slices of ``corpus``, honoring limit/offset."""

    def _open(req, timeout=0):  # noqa: ARG001
        url = req.full_url
        seen_urls.append(url)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        limit = int(params.get("limit", ["100"])[0])
        offset = 0 if ignore_offset else int(params.get("offset", ["0"])[0])
        return _Resp(corpus[offset : offset + limit])

    return _open


def _ws(tmp_path: Path) -> AuthoringWorkspace:
    return AuthoringWorkspace(root=tmp_path, registry_url="https://registry.example")


def _cell_row(i: int, serial: str | None = None) -> dict:
    return {
        "canonical_iri": f"https://w3id.org/battinfo/cell/{i:04d}",
        "canonical_id": f"{i:04d}",
        "title": f"Cell {i}",
        "metadata": {"serial_number": serial or f"SN{i:05d}", "batch_id": "b1"},
    }


def test_registry_resources_paginates_past_first_page(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.request

    corpus = [_cell_row(i) for i in range(2 * PAGE_LIMIT + 500)]
    urls: list[str] = []
    monkeypatch.setattr(urllib.request, "urlopen", _paginating_server(corpus, urls))

    rows = _ws(tmp_path)._registry_resources("cell")
    assert len(rows) == len(corpus)
    offsets = [urllib.parse.parse_qs(urllib.parse.urlparse(u).query)["offset"][0] for u in urls]
    assert offsets == ["0", str(PAGE_LIMIT), str(2 * PAGE_LIMIT)]


def test_offset_ignoring_server_does_not_loop_forever(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A pre-pagination registry ignores offset and serves the same first page
    again; the client must stop after the repeat, not spin."""
    import urllib.request

    corpus = [_cell_row(i) for i in range(PAGE_LIMIT)]  # exactly one full page
    urls: list[str] = []
    monkeypatch.setattr(urllib.request, "urlopen", _paginating_server(corpus, urls, ignore_offset=True))

    rows = _ws(tmp_path)._registry_resources("cell")
    assert len(rows) == PAGE_LIMIT  # first page kept once, repeat discarded
    assert len(urls) == 2


def test_q_parameter_is_passed_through(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.request

    urls: list[str] = []
    monkeypatch.setattr(urllib.request, "urlopen", _paginating_server([_cell_row(1)], urls))

    _ws(tmp_path)._registry_resources("cell", q="TRFFC")
    params = urllib.parse.parse_qs(urllib.parse.urlparse(urls[0]).query)
    assert params["q"] == ["TRFFC"]
    assert params["resource_type"] == ["cell"]


def test_query_registry_cells_finds_serial_beyond_first_page(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The #341 repro: a cell registered early sorts past the first page once
    newer cells accumulate; serial lookup must still resolve it."""
    import urllib.request

    corpus = [_cell_row(i) for i in range(PAGE_LIMIT + 100)]
    corpus[PAGE_LIMIT + 50] = _cell_row(PAGE_LIMIT + 50, serial="TRFFC00197")
    monkeypatch.setattr(urllib.request, "urlopen", _paginating_server(corpus, []))

    hits = _ws(tmp_path)._query_registry_cells(serials=["TRFFC00197"])
    assert [h["serial_number"] for h in hits] == ["TRFFC00197"]
    assert hits[0]["id"] == corpus[PAGE_LIMIT + 50]["canonical_iri"]


def test_build_api_cache_paginates(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The #340 repro: a spec older than the first page must enter the search cache."""
    import urllib.request

    corpus = [
        {
            "canonical_iri": f"https://w3id.org/battinfo/spec/{i:04d}",
            "canonical_id": f"{i:04d}",
            "title": f"Maker Model{i}",
            "metadata": {"manufacturer": "Maker", "model": f"Model{i}"},
        }
        for i in range(PAGE_LIMIT + 200)
    ]
    monkeypatch.setattr(urllib.request, "urlopen", _paginating_server(corpus, []))

    entries = _ws(tmp_path)._build_api_cache()
    assert len(entries) == len(corpus)
    ids = {e["id"] for e in entries}
    assert corpus[-1]["canonical_iri"] in ids  # oldest row survived pagination
