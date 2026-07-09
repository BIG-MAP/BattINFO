"""Reserved namespace segments can never become entity IRI namespaces.

The reserved set mirrors IDENTIFIER_POLICY.md section 6.1: core resolver
infrastructure paths plus the segments claimed by the ontology block in the
upstream w3id.org .htaccess (raw/inferred/turtle/latest/source), which can
never reach the record resolver.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.entities import ENTITY_KINDS, RESERVED_NAMESPACE_SEGMENTS


def test_reserved_segments_include_policy_set() -> None:
    expected = {
        # resolver / vocabulary infrastructure
        "id", "ontology", "vocab", "doc", "context", "resolver", "twin", "w3id",
        # claimed by the ontology block in the upstream w3id .htaccess
        "raw", "inferred", "turtle", "latest", "source",
    }
    assert expected <= RESERVED_NAMESPACE_SEGMENTS


def test_no_entity_kind_uses_a_reserved_segment() -> None:
    used = {kind.iri_namespace for kind in ENTITY_KINDS}
    assert not (used & RESERVED_NAMESPACE_SEGMENTS)


def test_reserved_segments_documented_in_identifier_policy() -> None:
    """IDENTIFIER_POLICY.md must list every reserved segment (keep code and
    policy from drifting)."""
    policy = (ROOT / "IDENTIFIER_POLICY.md").read_text(encoding="utf-8")
    for segment in RESERVED_NAMESPACE_SEGMENTS:
        assert f"`{segment}`" in policy, f"IDENTIFIER_POLICY.md missing reserved segment {segment!r}"
