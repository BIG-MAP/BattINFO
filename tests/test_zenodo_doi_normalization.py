"""Regression tests: Zenodo related_identifiers must carry a BARE DOI, and must
not drop citations whose DOI is only present as a doi.org URL (audit theme F).

Zenodo's API rejects a full URL under scheme="doi"; a citation's DOI may live in
either the 'doi' or 'url' field, bare or as a doi.org URL.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.zenodo import _normalized_citation_doi  # noqa: E402


def test_url_form_doi_is_normalized_to_bare() -> None:
    assert _normalized_citation_doi({"doi": "https://doi.org/10.1038/s41467-020-15235-7"}) == "10.1038/s41467-020-15235-7"


def test_bare_doi_passes_through() -> None:
    assert _normalized_citation_doi({"doi": "10.1038/x"}) == "10.1038/x"


def test_doi_recovered_from_url_field_when_no_doi_field() -> None:
    assert _normalized_citation_doi({"url": "https://doi.org/10.1016/j.ijepes.2018.12.016", "kind": "article"}) \
        == "10.1016/j.ijepes.2018.12.016"


def test_non_doi_url_and_empty_return_none() -> None:
    assert _normalized_citation_doi({"url": "https://example.org/foo"}) is None
    assert _normalized_citation_doi({}) is None
