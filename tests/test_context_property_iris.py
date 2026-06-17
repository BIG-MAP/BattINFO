"""Guard: the generated JSON-LD context must agree with the curated property map.

The records.context.json snake_case property terms are derived from the LinkML
schema's ``slot_uri:`` declarations, while the quantity *classes* the emitted data
uses are typed from ``property_map.curated.json`` (the curated source of truth for
property -> EMMO IRI). These two must agree, or a snake_case-keyed consumer and a
class-keyed consumer would resolve the same property to different IRIs (the
"collapsed capacity/current" class of bug). This test fails loudly if they diverge.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / "src" / "battinfo" / "data" / "context" / "records.context.json"
CURATED = ROOT / "assets" / "mappings" / "domain-battery" / "property_map.curated.json"


def _expand(compact: str, prefixes: dict[str, str]) -> str:
    if isinstance(compact, str) and ":" in compact:
        prefix, local = compact.split(":", 1)
        if prefix in prefixes:
            return prefixes[prefix] + local
    return compact


def test_context_property_iris_match_curated_map() -> None:
    ctx = json.loads(CONTEXT.read_text(encoding="utf-8"))["@context"]
    curated = json.loads(CURATED.read_text(encoding="utf-8"))["mappings"]
    prefixes = {k: v for k, v in ctx.items() if isinstance(v, str) and v.endswith(("#", "/"))}

    mismatches = []
    for mapping in curated:
        key = mapping["key"]
        want = mapping["class_iri"]
        term = ctx.get(key)
        if isinstance(term, str):  # only snake_case property terms (string values)
            got = _expand(term, prefixes)
            if got != want:
                mismatches.append((key, got, want))

    assert not mismatches, (
        "records.context.json disagrees with the curated property map "
        f"(regenerate via scripts/assemble_context.py after fixing schema slot_uris): {mismatches}"
    )


def test_context_uses_single_emmo_quantity_serialization() -> None:
    """Quantities use ONE EMMO serialization everywhere (publish + validation), so the
    QUDT value/unit schema is fully retired: no value/unit aliases and no qudt prefixes."""
    ctx = json.loads(CONTEXT.read_text(encoding="utf-8"))["@context"]
    assert "value" not in ctx and "unit" not in ctx
    assert "qudt" not in ctx and "qudt-unit" not in ctx
    # The EMMO quantity terms the single serialization relies on must be present.
    assert "hasNumberValue" in ctx and "hasMeasurementUnit" in ctx
