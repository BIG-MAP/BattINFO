"""The ns# catch-all namespace stays retired.

Served artifacts once expanded unmapped keys against ``@vocab
https://w3id.org/battinfo/ns#`` and the vocabulary generator declared an ns#
subject for every one of them. That regime is gone: every predicate a served
record carries is a real vocabulary term, a ``battinfo:`` slash placeholder
from the closed inventory, or excluded from RDF by the registry's artifact
context (whose honesty check enforces the allowlist corpus-wide). This module
is the library-side tripwire — the generated vocabulary must never mint an
ns# subject again, and the record contexts must never route a key there.
"""

from __future__ import annotations

import json
from pathlib import Path

import rdflib

ROOT = Path(__file__).resolve().parents[1]
TTL = ROOT / "assets" / "vocab" / "battinfo-records.ttl"
CONTEXTS = ROOT / "src" / "battinfo" / "data" / "context"
NS = "https://w3id.org/battinfo/ns#"
SLASH = "https://w3id.org/battinfo/"


def test_vocabulary_defines_only_slash_subjects() -> None:
    graph = rdflib.Graph()
    graph.parse(TTL, format="turtle")
    subjects = {str(s) for s in graph.subjects() if isinstance(s, rdflib.URIRef)}
    assert subjects, "vocabulary parsed empty"
    ns_subjects = {s for s in subjects if s.startswith(NS)}
    assert not ns_subjects, f"retired ns# subjects reappeared: {sorted(ns_subjects)}"
    strays = {s for s in subjects if not s.startswith(SLASH)}
    assert not strays, f"non-battinfo subjects in the record vocabulary: {sorted(strays)}"


def test_record_contexts_never_route_to_ns() -> None:
    """No context term, prefix, or @vocab points at the retired namespace."""
    for path in sorted(CONTEXTS.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        assert NS not in text, f"{path.name} references the retired ns# namespace"
        context = json.loads(text).get("@context", {})
        assert "@vocab" not in context, f"{path.name} declares a catch-all @vocab"
