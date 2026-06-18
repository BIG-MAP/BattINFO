"""Guard: every canonical example emits valid domain-battery JSON-LD.

The per-family contract tests only emit the first example of each kind, so a bad
@type in a later example (e.g. an unmapped current-collector material) could slip
through. This emits JSON-LD for the whole corpus and fails on any invalid @type.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from battinfo.transform.json_to_jsonld import to_jsonld

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

# record top-level keys that have a domain-battery JSON-LD emitter
EMITTING_KEYS = {
    "cell_spec", "cell_instance", "test", "test_spec", "dataset",
    "material_spec", "material", "electrode_spec", "electrode",
    "electrolyte_spec", "electrolyte", "separator_spec", "separator",
    "current_collector_spec", "current_collector", "housing_spec", "housing",
}


def _emitting_examples() -> list[Path]:
    out = []
    for path in sorted(EXAMPLES.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if any(k in doc for k in EMITTING_KEYS):
            out.append(path)
    return out


@pytest.mark.parametrize("path", _emitting_examples(), ids=lambda p: p.name)
def test_example_emits_valid_jsonld(path: Path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    # raises ValueError("json-ld validation failed: ...") on an unmapped @type
    to_jsonld(doc, target="domain-battery")
