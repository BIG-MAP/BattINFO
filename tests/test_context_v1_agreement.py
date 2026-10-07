"""Guard: the published v1 records context must agree with the curated maps.

``records.context.v1.json`` is the context every emitter uses and the file
served at https://w3id.org/battinfo/context/records/v1.json. It is append-only,
so it does not follow later changes to the curated property map or the class
table on its own. Before 0.8.0 that let eight terms drift: six kept a private
``battinfo:`` mint after domain-electrochemistry 0.37.1 added the real classes,
``capacity_fade`` kept the superseded CapacityFade phenomenon, and
``PrismaticBattery`` kept an IRI the battery ontology deprecated. They were
corrected in place (``PRE_RELEASE_CORRECTIONS`` in scripts/gen_context.py).

These tests fail when the curated sources and v1 disagree again. After 0.8.0
the fix is a v2 context, not another edit to v1.
"""

from __future__ import annotations

import json
from pathlib import Path

from battinfo.transform.cell_spec_node import label_to_compact

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json"
CURATED = ROOT / "src" / "battinfo" / "data" / "mappings" / "domain-battery" / "property_map.curated.json"


def _v1() -> dict:
    return json.loads(V1.read_text(encoding="utf-8"))["@context"]


def _expander(ctx: dict):
    prefixes = {k: v for k, v in ctx.items() if isinstance(v, str) and v.endswith(("#", "/"))}

    def expand(value):
        if isinstance(value, dict):
            value = value.get("@id")
        if isinstance(value, str) and ":" in value and not value.startswith(("http://", "https://")):
            prefix, local = value.split(":", 1)
            if prefix in prefixes:
                return prefixes[prefix] + local
        return value

    return expand


def test_v1_property_terms_match_curated_map() -> None:
    ctx = _v1()
    expand = _expander(ctx)
    curated = json.loads(CURATED.read_text(encoding="utf-8"))["mappings"]
    mismatches = [
        (m["key"], expand(ctx[m["key"]]), m["class_iri"])
        for m in curated
        if m["key"] in ctx and expand(ctx[m["key"]]) != m["class_iri"]
    ]
    assert not mismatches, (
        "records.context.v1.json disagrees with property_map.curated.json. "
        f"After 0.8.0 this needs a v2 context: {mismatches}"
    )


def test_v1_class_terms_match_class_table() -> None:
    ctx = _v1()
    expand = _expander(ctx)
    table = label_to_compact()
    mismatches = [
        (term, expand(ctx[term]), expand(value))
        for term, value in table.items()
        if term in ctx and expand(ctx[term]) != expand(value)
    ]
    assert not mismatches, (
        "records.context.v1.json disagrees with the class table (label_to_compact). "
        f"After 0.8.0 this needs a v2 context: {mismatches}"
    )


def test_v1_has_no_private_mint_for_a_curated_property() -> None:
    ctx = _v1()
    curated = {m["key"] for m in json.loads(CURATED.read_text(encoding="utf-8"))["mappings"]}
    private = sorted(k for k in curated if isinstance(ctx.get(k), str) and ctx[k].startswith("battinfo:"))
    assert not private, f"curated properties still mapped to private battinfo: terms in v1: {private}"
