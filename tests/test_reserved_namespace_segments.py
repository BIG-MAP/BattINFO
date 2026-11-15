"""Reserved namespace segments can never become entity IRI namespaces.

The reserved set is data, ``src/battinfo/data/namespace/reserved-segments.json``
(IDENTIFIER_POLICY.md section 6.1, BIG-MAP/BattINFO#479): the branches of the
ruled layout (id, def), the paths of the standard and the resolver, and the
segments claimed by the ontology block in the upstream w3id.org .htaccess
(raw/inferred/turtle/latest/source), which can never reach the record resolver.
"""

from __future__ import annotations

import json
import re
import sys
from importlib import resources
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import namespace  # noqa: E402
from battinfo.entities import ENTITY_KINDS, RESERVED_NAMESPACE_SEGMENTS  # noqa: E402

# The 19 segments of ruling decision 2 (BIG-MAP/BattINFO#476).
RULED = {
    # branches of the ruled layout
    "id",
    "def",
    # resolver / vocabulary infrastructure
    "ontology",
    "vocab",
    "doc",
    "context",
    "resolver",
    "schema",
    "shapes",
    "profile",
    "ns",
    "twin",
    "w3id",
    # claimed by the ontology block in the upstream w3id .htaccess
    "raw",
    "inferred",
    "turtle",
    "latest",
    "source",
    # the GitHub Pages folder of the ontology releases
    "versions",
}


def _entries() -> list[dict[str, str]]:
    path = resources.files("battinfo").joinpath("data", "namespace", "reserved-segments.json")
    return json.loads(path.read_text(encoding="utf-8"))["segments"]


def test_reserved_segments_include_policy_set() -> None:
    assert RULED <= RESERVED_NAMESPACE_SEGMENTS


def test_no_entity_kind_uses_a_reserved_segment() -> None:
    used = {kind.iri_namespace for kind in ENTITY_KINDS}
    legacy = {segment for kind in ENTITY_KINDS for segment in kind.legacy_iri_namespaces}
    assert not ((used | legacy) & RESERVED_NAMESPACE_SEGMENTS)


def test_reserved_segments_documented_in_identifier_policy() -> None:
    """IDENTIFIER_POLICY.md must list every reserved segment (keep code and
    policy from drifting)."""
    policy = (ROOT / "IDENTIFIER_POLICY.md").read_text(encoding="utf-8")
    for segment in RESERVED_NAMESPACE_SEGMENTS:
        assert f"`{segment}`" in policy, f"IDENTIFIER_POLICY.md missing reserved segment {segment!r}"


def test_the_file_is_the_ruled_set_with_a_reason_for_each_segment() -> None:
    entries = _entries()
    segments = [entry["segment"] for entry in entries]
    assert len(segments) == len(set(segments)), "a segment is listed twice"
    assert set(segments) == RULED == RESERVED_NAMESPACE_SEGMENTS
    for entry in entries:
        assert set(entry) == {"segment", "reason"}, entry
        assert re.fullmatch(namespace.SEGMENT_PATTERN, entry["segment"]), entry
        assert isinstance(entry["reason"], str) and entry["reason"].strip(), entry


@pytest.mark.parametrize(
    "lead",
    [
        "Reserved segments (never usable as entity namespaces):",  # section 6.1
        "Reserved namespace segments (never usable as entity types):",  # section 14
    ],
)
def test_each_policy_list_is_the_file(lead: str) -> None:
    """Both lists in IDENTIFIER_POLICY.md name exactly the segments of the data file."""
    policy = (ROOT / "IDENTIFIER_POLICY.md").read_text(encoding="utf-8")
    assert policy.count(lead) == 1, f"IDENTIFIER_POLICY.md has no single list starting {lead!r}"
    listed = policy.split(lead, 1)[1].split("\n\n", 1)[0]
    segments = re.findall(r"`([^`]+)`", listed)
    assert len(segments) == len(set(segments)), "the policy lists a segment twice"
    assert set(segments) == {entry["segment"] for entry in _entries()}


@pytest.mark.parametrize("segment", sorted(RULED))
def test_a_reserved_segment_is_never_a_record_segment(segment: str) -> None:
    uid = "b6yn-0sxe-t2qk-9mjv"
    with pytest.raises(ValueError, match="not a record segment"):
        namespace.record_iri(segment, uid)
    assert namespace.parse_record_iri(f"https://w3id.org/battinfo/{segment}/{uid}") is None
    assert namespace.parse_record_iri(f"https://w3id.org/battinfo/id/1001/{segment}/{uid}") is None
