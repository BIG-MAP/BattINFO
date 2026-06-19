"""The publish/validation JSON-LD path must run fully offline.

Bundled contexts (EMMO domain-battery, battinfo records) are resolved locally for
both rdflib (RDF materialization) and PyLD (URDNA2015 normalization), so no live
network is required to validate or normalize a record. The suite-wide
``--disable-socket`` gate enforces offline-ness for every test; these tests pin
the JSON-LD machinery that makes the publish path offline in the first place.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.validate.jsonld import (
    _BATTINFO_RECORDS_CONTEXT_URL,
    _EMMO_BATTERY_CONTEXT_URL,
    _inline_local_contexts,
    _resolve_local_context,
    validate_jsonld_report,
)


def test_bundled_contexts_resolve_locally() -> None:
    assert _resolve_local_context(_EMMO_BATTERY_CONTEXT_URL) is not None
    assert _resolve_local_context(_BATTINFO_RECORDS_CONTEXT_URL) is not None
    # trailing slash / stray dot are tolerated
    assert _resolve_local_context(_EMMO_BATTERY_CONTEXT_URL + "/") is not None
    # unknown URLs are NOT resolved locally (they would otherwise need the network)
    assert _resolve_local_context("https://example.org/unknown/context") is None


def test_remote_context_url_is_inlined_for_rdflib() -> None:
    doc = {
        "@context": _EMMO_BATTERY_CONTEXT_URL,
        "@id": "https://w3id.org/battinfo/spec/x",
        "@type": "BatteryCellSpecification",
    }
    inlined = _inline_local_contexts(doc)
    # the remote URL string is replaced by the bundled term-map object
    assert isinstance(inlined["@context"], dict)
    assert len(inlined["@context"]) > 0
    # the original document is not mutated (deep copy)
    assert doc["@context"] == _EMMO_BATTERY_CONTEXT_URL


def test_validate_jsonld_runs_offline_against_bundled_contexts() -> None:
    # Runs under the suite-wide --disable-socket gate: a record referencing the
    # remote EMMO context validates purely from the bundled copy, no network.
    doc = {
        "@context": [
            _EMMO_BATTERY_CONTEXT_URL,
            {"schema": "https://schema.org/"},
        ],
        "@id": "https://w3id.org/battinfo/spec/offline-test-0000",
        "@type": ["BatteryCellSpecification", "schema:CreativeWork"],
        "schema:name": "Offline test cell spec",
    }
    report = validate_jsonld_report(doc)
    errors = [issue for issue in report.issues if issue.severity == "error"]
    assert not errors, [issue.message for issue in errors]
