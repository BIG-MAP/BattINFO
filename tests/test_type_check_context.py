"""The @type check judges a document against its own @context.

A bare @type token expands through the document's effective context. One the
context does not define expands relative to wherever the document is read
(file:///.../coin), so the check flags it as jsonld.type_term_unknown, an
error under every policy. The allowed set used to be a union of every mapping
table (entity-map slugs and notes, candidate-map labels, material classes),
whether or not any context defined them, and record_to_jsonld ran the check
only for the record kinds that pass through to_jsonld.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from battinfo import jsonld as jsonld_module
from battinfo.jsonld import record_to_jsonld
from battinfo.validate.jsonld import (
    _allowed_type_terms,
    _context_class_terms,
    _context_unit_terms,
    type_term_issues,
    validate_jsonld_report,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "src" / "battinfo" / "data" / "examples"
CONTEXT_DIR = ROOT / "src" / "battinfo" / "data" / "context"

V1_URL = "https://w3id.org/battinfo/context/records/v1.json"
EMMO_URL = "https://w3id.org/emmo/domain/battery/context"


def _v1_terms() -> dict[str, Any]:
    return json.loads((CONTEXT_DIR / "records.context.v1.json").read_text(encoding="utf-8"))["@context"]


def _emmo_terms() -> dict[str, Any]:
    return json.loads((CONTEXT_DIR / "domain-battery.context.json").read_text(encoding="utf-8"))["@context"]


def _doc(context: Any, type_term: str) -> dict[str, Any]:
    return {"@context": context, "@graph": [{"@id": "https://example.org/x", "@type": type_term}]}


def _unknown_terms(doc: dict[str, Any]) -> list[str]:
    return [issue.message for issue in type_term_issues(doc)]


# -- what the v1 context (URL mode) allows -------------------------------------


def test_allowed_type_terms_are_the_class_terms_of_bundled_v1() -> None:
    v1 = _v1_terms()
    assert _allowed_type_terms() == _context_class_terms(v1) - _context_unit_terms(v1)


@pytest.mark.parametrize(
    "token",
    [
        # format and chemistry slugs, and electrode-basis labels, from entity_type_map.json
        "coin",
        "cylindrical",
        "li-metal",
        "zn-mno2",
        "lithium",
        # labels the mapping tables name but v1 does not define
        "Capacity",
        "LithiumTitanate",
        "JellyRoll",
        "PowerCapability",
    ],
)
def test_a_token_v1_does_not_define_is_rejected_in_a_v1_document(token: str) -> None:
    messages = _unknown_terms(_doc(V1_URL, token))
    assert messages == [f"relative @type reference '{token}' is not a class the document's @context defines"]


def test_an_entity_map_note_is_not_a_type() -> None:
    note = "Spelling variant. Write zn-mno2."
    assert _unknown_terms(_doc(V1_URL, note))


@pytest.mark.parametrize("token", ["BatteryCell", "Case", "Charging", "Mesh", "Dataset"])
def test_a_v1_class_is_accepted_in_a_v1_document(token: str) -> None:
    assert not _unknown_terms(_doc(V1_URL, token))


# -- the document's own context decides --------------------------------------------


@pytest.mark.parametrize("token", ["Capacity", "LithiumTitanate", "Additive"])
def test_a_class_only_the_emmo_context_defines_is_accepted_in_an_emmo_document(token: str) -> None:
    assert token in _emmo_terms() and token not in _v1_terms()
    assert not _unknown_terms(_doc([EMMO_URL, {"schema": "https://schema.org/"}], token))
    assert _unknown_terms(_doc(V1_URL, token))


def test_a_class_only_v1_defines_is_rejected_in_an_emmo_document() -> None:
    assert "Grant" in _v1_terms() and "Grant" not in _emmo_terms()
    assert not _unknown_terms(_doc(V1_URL, "Grant"))
    assert _unknown_terms(_doc(EMMO_URL, "Grant"))


def test_an_inline_context_defines_its_own_classes() -> None:
    inline = {"Widget": "https://example.org/Widget"}
    assert not _unknown_terms(_doc(inline, "Widget"))
    assert _unknown_terms(_doc(inline, "BatteryCell"))
    # The URL plus a local patch: both define terms.
    assert not _unknown_terms(_doc([V1_URL, inline], "Widget"))
    assert not _unknown_terms(_doc([V1_URL, inline], "BatteryCell"))


def test_the_inline_v1_context_and_the_url_allow_the_same_classes() -> None:
    v1 = _v1_terms()
    for token in ("BatteryCell", "Grant", "Capacity", "coin"):
        assert bool(_unknown_terms(_doc(v1, token))) == bool(_unknown_terms(_doc(V1_URL, token)))


def test_a_term_a_local_context_unbinds_is_no_longer_defined() -> None:
    assert _unknown_terms(_doc([V1_URL, {"BatteryCell": None}], "BatteryCell"))


def test_a_nested_context_applies_to_its_own_subtree_only() -> None:
    doc = {
        "@context": V1_URL,
        "@id": "https://example.org/a",
        "@type": "BatteryCell",
        "hasPart": {
            "@context": {"Widget": "https://example.org/Widget"},
            "@id": "https://example.org/b",
            "@type": "Widget",
        },
        "isPartOf": {"@id": "https://example.org/c", "@type": "Widget"},
    }
    assert [issue.path for issue in type_term_issues(doc)] == ["isPartOf.@type"]


def test_a_null_context_drops_the_inherited_terms() -> None:
    doc = {
        "@context": V1_URL,
        "@id": "https://example.org/a",
        "@type": "BatteryCell",
        "hasPart": {"@context": None, "@id": "https://example.org/b", "@type": "BatteryCell"},
    }
    assert [issue.path for issue in type_term_issues(doc)] == ["hasPart.@type"]


def test_a_property_scoped_context_applies_below_that_property() -> None:
    context = {
        "part": {"@id": "https://example.org/part", "@context": {"Widget": "https://example.org/Widget"}},
        "other": "https://example.org/other",
    }
    doc = {
        "@context": context,
        "@id": "https://example.org/a",
        "part": {"@id": "https://example.org/b", "@type": "Widget"},
        "other": {"@id": "https://example.org/c", "@type": "Widget"},
    }
    assert [issue.path for issue in type_term_issues(doc)] == ["other.@type"]


def test_a_vocabulary_mapping_makes_a_bare_type_absolute() -> None:
    assert not _unknown_terms(_doc({"@vocab": "https://schema.org/"}, "Dataset"))


def test_the_v1_type_alias_is_checked_like_at_type() -> None:
    doc = {"@context": V1_URL, "@id": "https://example.org/x", "type": "coin"}
    issues = type_term_issues(doc)
    assert [(issue.path, issue.code) for issue in issues] == [("type", "jsonld.type_term_unknown")]


@pytest.mark.parametrize(("context", "unit"), [(V1_URL, "V"), (V1_URL, "Volt"), (EMMO_URL, "Volt")])
def test_a_unit_term_is_never_a_type(context: str, unit: str) -> None:
    assert _unknown_terms(_doc(context, unit))


def test_an_unloadable_remote_context_is_left_to_the_normaliser() -> None:
    """The check cannot know what a context it cannot load defines. It flags
    nothing under it; the URDNA2015 step reports the context as an error."""
    doc = _doc("https://example.invalid/no-such-context.jsonld", "Widget")
    assert not type_term_issues(doc)
    report = validate_jsonld_report(doc)
    assert not report.ok
    assert "jsonld.type_term_unknown" not in [issue.code for issue in report.errors]


@pytest.mark.parametrize("policy", ["default", "strict", "publisher", "ingest"])
def test_an_unknown_type_is_an_error_under_every_policy(policy: str) -> None:
    report = validate_jsonld_report(_doc(V1_URL, "coin"), policy=policy)
    assert [issue.code for issue in report.errors] == ["jsonld.type_term_unknown"]


# -- record_to_jsonld runs the check for every record kind -------------------------


def _example_kinds() -> list[tuple[str, Path]]:
    kinds = []
    for kind_dir in sorted(p for p in EXAMPLES.iterdir() if p.is_dir()):
        if kind_dir.name not in jsonld_module._TRANSFORMERS:
            continue
        example = next(iter(sorted(kind_dir.glob("*.json"))), None)
        if example is not None:
            kinds.append((kind_dir.name, example))
    return kinds


_KINDS = _example_kinds()


def test_every_kind_with_an_emitter_has_an_example_here() -> None:
    names = {kind for kind, _ in _KINDS}
    assert {"cell-spec", "cell-instance", "test-protocol", "dataset", "material-spec", "electrode-spec"} <= names
    assert len(names) >= 18


@pytest.mark.parametrize("mode", ["url", "inline"])
@pytest.mark.parametrize(("kind", "example"), _KINDS, ids=[kind for kind, _ in _KINDS])
def test_record_to_jsonld_refuses_an_undefined_type_for_every_kind(
    kind: str, example: Path, mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = jsonld_module._TRANSFORMERS[kind]

    def emit_with_a_slug(record: dict) -> dict:
        node = original(record)
        types = node.get("@type")
        node["@type"] = [*(types if isinstance(types, list) else [types] if types else []), "coin"]
        return node

    monkeypatch.setitem(jsonld_module._TRANSFORMERS, kind, emit_with_a_slug)
    record = json.loads(example.read_text(encoding="utf-8"))
    with pytest.raises(ValueError, match=r"relative @type reference 'coin'"):
        record_to_jsonld(record, kind, context=mode)


def test_record_to_jsonld_checks_a_material_against_its_emmo_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """A material document carries the EMMO context, so a class only v1
    defines is undefined there, while a cell spec (v1) may use it."""

    def add_type(kind: str, token: str) -> None:
        original = jsonld_module._TRANSFORMERS[kind]

        def emit(record: dict) -> dict:
            node = original(record)
            node["hasPart"] = {"@type": token}
            return node

        monkeypatch.setitem(jsonld_module._TRANSFORMERS, kind, emit)

    material = json.loads(next(iter(sorted((EXAMPLES / "material-spec").glob("*.json")))).read_text(encoding="utf-8"))
    cell = json.loads(next(iter(sorted((EXAMPLES / "cell-spec").glob("*.json")))).read_text(encoding="utf-8"))
    add_type("material-spec", "Grant")
    add_type("cell-spec", "Grant")
    with pytest.raises(ValueError, match=r"'Grant'"):
        record_to_jsonld(material, "material-spec")
    for mode in ("url", "inline"):
        assert record_to_jsonld(cell, "cell-spec", context=mode)["hasPart"] == {"@type": "Grant"}


# -- the packaged corpus emits only defined terms ----------------------------------


def _bare_types(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, list):
        for item in node:
            found |= _bare_types(item)
    elif isinstance(node, dict):
        for key, value in node.items():
            if key == "@context":
                continue
            if key == "@type":
                for token in value if isinstance(value, list) else [value]:
                    if isinstance(token, str) and ":" not in token:
                        found.add(token)
            else:
                found |= _bare_types(value)
    return found


@pytest.mark.parametrize("mode", ["url", "inline"])
def test_every_packaged_example_emits_only_terms_its_context_defines(mode: str) -> None:
    checked = 0
    problems: list[str] = []
    for kind_dir in sorted(p for p in EXAMPLES.iterdir() if p.is_dir()):
        if kind_dir.name not in jsonld_module._TRANSFORMERS:
            continue
        for path in sorted(kind_dir.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            out = record_to_jsonld(record, kind_dir.name, context=mode)
            checked += 1
            problems += [
                f"{kind_dir.name}/{path.name}: {issue.path}: {issue.message}" for issue in type_term_issues(out)
            ]
            if mode == "inline" and isinstance(out["@context"], dict):
                undefined = _bare_types(out) - set(out["@context"])
                problems += [
                    f"{kind_dir.name}/{path.name}: '{token}' is not in the inline context" for token in undefined
                ]
    assert checked > 100, checked
    assert not problems, problems
