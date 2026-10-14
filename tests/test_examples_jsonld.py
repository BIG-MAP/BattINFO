"""Guard: every canonical example emits JSON-LD that carries the record.

The per-family contract tests only emit the first example of each kind, so a bad
@type in a later example (e.g. an unmapped current-collector material) could slip
through. This emits JSON-LD for the whole corpus and fails on any invalid @type,
and on any document that does not carry the record's own IRI as a node.

``to_jsonld`` emits cell specs, materials, electrodes, the four component
families and parameter sets. For the other record kinds it raises a
``ValueError`` that names ``battinfo.record_to_jsonld``, which emits every kind;
before 0.8.0 it returned an empty document for them, and this test counted that
as a pass.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from battinfo import record_to_jsonld
from battinfo.entities import kind_for_doc
from battinfo.transform.json_to_jsonld import to_jsonld

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

# Record kinds (entity types) that to_jsonld does not emit.
NOT_EMITTED_BY_TO_JSONLD = {
    "cell",
    "test-protocol",
    "test",
    "dataset",
    "equipment-spec",
    "equipment",
    "channel",
    "organization",
}


def _examples() -> list[Path]:
    return sorted(EXAMPLES.rglob("*.json"))


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _record_type(entity_type: str) -> str:
    """The record_type record_to_jsonld takes; it names the physical cell 'cell-instance'."""
    return "cell-instance" if entity_type == "cell" else entity_type


def _node_ids(document: dict[str, Any]) -> set[Any]:
    graph = document.get("@graph")
    nodes = graph if isinstance(graph, list) else [document]
    return {node.get("@id") for node in nodes if isinstance(node, dict)}


def test_every_example_is_a_record() -> None:
    strays = [path.relative_to(EXAMPLES).as_posix() for path in _examples() if kind_for_doc(_load(path)) is None]
    assert not strays, f"files under examples/ that are not records of a registered kind: {strays}"


@pytest.mark.parametrize("path", _examples(), ids=lambda p: p.relative_to(EXAMPLES).as_posix())
def test_example_emits_jsonld_that_carries_the_record(path: Path) -> None:
    doc = _load(path)
    kind = kind_for_doc(doc)
    assert kind is not None
    iri = doc[kind.record_key]["id"]
    if kind.entity_type in NOT_EMITTED_BY_TO_JSONLD:
        record_type = _record_type(kind.entity_type)
        hint = f"battinfo.record_to_jsonld(record, {record_type!r})"
        with pytest.raises(ValueError, match=re.escape(hint)):
            to_jsonld(doc, target="domain-battery")
        emitted = record_to_jsonld(doc, record_type)
    else:
        # raises ValueError("json-ld validation failed: ...") on an unmapped @type
        emitted = to_jsonld(doc, target="domain-battery")
    assert iri in _node_ids(emitted), f"the JSON-LD for {path.name} has no node for {iri}"


def test_example_iris_are_unique() -> None:
    """No two example records may claim the same canonical IRI."""
    seen: dict[str, str] = {}
    dups: list[str] = []
    for path in _examples():
        doc = _load(path)
        kind = kind_for_doc(doc)
        if kind is None:
            continue
        iri = doc[kind.record_key].get("id")
        if not isinstance(iri, str):
            continue
        if iri in seen:
            dups.append(f"{iri}: {path.name} and {seen[iri]}")
        seen[iri] = path.name
    assert not dups, "duplicate IRIs:\n  " + "\n  ".join(dups)
