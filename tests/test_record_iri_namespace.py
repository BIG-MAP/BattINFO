"""Record IRIs in both shapes (battinfo.namespace, IRI ruling of 22 October 2026).

The old form ``https://w3id.org/battinfo/{segment}/{uid}`` and the prefixed
form ``https://w3id.org/battinfo/id/{prefix}/{segment}/{uid}`` are built and
recognised in one module. Every recogniser accepts both shapes
(BIG-MAP/BattINFO#478), and the ones that read a reference to a product model
or a material also accept a shared thing, ``https://w3id.org/battinfo/id/{uid}``.
New records mint under ``/id/1001/`` (BIG-MAP/BattINFO#482); a record saved in
either form keeps the IRI it has.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import namespace  # noqa: E402
from battinfo.entities import ENTITY_KINDS, UID_ALPHABET, saved_record_body, saved_record_document  # noqa: E402
from battinfo.namespace import (  # noqa: E402
    BATTINFO_ROOT,
    DEFAULT_RECORD_BASE,
    OLD_FORM_BASE,
    RecordIri,
    parse_record_iri,
    parse_thing_iri,
    record_base,
    record_iri,
    record_iri_forms,
    record_iri_pattern,
    record_iri_regex,
    same_record,
)

UID = "b6yn-0sxe-t2qk-9mjv"
OTHER_UID = "nm6t-ceph-frax-1mk1"
OLD = f"https://w3id.org/battinfo/cell/{UID}"
GENOME = f"https://w3id.org/battinfo/id/1001/cell/{UID}"
SECOND_HUB = f"https://w3id.org/battinfo/id/1002/cell/{UID}"
THING = f"https://w3id.org/battinfo/id/{UID}"
SEGMENTS = sorted({kind.iri_namespace for kind in ENTITY_KINDS})


# ── Building ────────────────────────────────────────────────────────────────


def test_record_iri_builds_the_old_form_without_a_prefix_and_the_prefixed_form_with_one() -> None:
    assert record_iri("cell", UID) == OLD
    assert record_iri("cell", UID, prefix="1001") == GENOME
    assert record_iri("current-collector", UID, "1002") == f"https://w3id.org/battinfo/id/1002/current-collector/{UID}"
    assert record_base() == BATTINFO_ROOT
    assert record_base("1001") == "https://w3id.org/battinfo/id/1001/"


@pytest.mark.parametrize("segment", ["", "Cell", "cell/x", "1cell", "cell_type", "id", "def", None])
def test_record_iri_refuses_a_malformed_segment(segment: object) -> None:
    with pytest.raises(ValueError, match="not a record segment"):
        record_iri(segment, UID)


@pytest.mark.parametrize(
    "uid",
    [
        "",
        "b6yn0sxet2qk9mjv",
        "B6YN-0SXE-T2QK-9MJV",
        "b6yn-0sxe-t2qk",
        "b6yn-0sxe-t2qk-9mjvx",
        "i6yn-0sxe-t2qk-9mjv",
        None,
    ],
)
def test_record_iri_refuses_a_malformed_uid(uid: object) -> None:
    with pytest.raises(ValueError, match="not a record uid"):
        record_iri("cell", uid)


@pytest.mark.parametrize("prefix", ["100", "1", "abcd", "10a1", "", 1001, "1001/"])
def test_record_iri_refuses_a_malformed_prefix(prefix: object) -> None:
    with pytest.raises(ValueError, match="not a publisher prefix"):
        record_iri("cell", UID, prefix=prefix)


def test_no_record_is_minted_under_the_definitions_only_prefix() -> None:
    with pytest.raises(ValueError, match="definitions only"):
        record_iri("cell", UID, prefix=namespace.BATTINFO_PREFIX)


def test_the_standard_namespaces_stay_where_they_are() -> None:
    assert namespace.VOCABULARY_NAMESPACE == "https://w3id.org/battinfo/"
    assert namespace.CONTEXT_BASE + "records/v1.json" == "https://w3id.org/battinfo/context/records/v1.json"
    assert namespace.SCHEMA_BASE == "https://w3id.org/battinfo/schema/"
    assert (namespace.BATTINFO_PREFIX, namespace.BATTERY_GENOME_PREFIX) == ("1000", "1001")


# ── Parsing ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("prefix", [None, "1001", "1002", "12345"])
@pytest.mark.parametrize("segment", SEGMENTS)
def test_every_segment_round_trips_in_both_shapes(segment: str, prefix: str | None) -> None:
    iri = record_iri(segment, UID, prefix)
    parsed = parse_record_iri(iri)
    assert parsed == RecordIri(prefix, segment, UID)
    assert parsed is not None and record_iri(parsed.segment, parsed.uid, parsed.prefix) == iri


def test_an_iri_under_the_definitions_only_prefix_parses_but_is_never_built() -> None:
    """Whether a publisher holds a prefix is the registry's question, not the parser's."""
    iri = f"https://w3id.org/battinfo/id/1000/cell/{UID}"
    assert parse_record_iri(iri) == RecordIri("1000", "cell", UID)
    with pytest.raises(ValueError):
        record_iri("cell", UID, prefix="1000")


@pytest.mark.parametrize(
    "value",
    [
        None,
        42,
        "",
        BATTINFO_ROOT,
        f"{OLD}/",
        f"{OLD}#described",
        f"{OLD}?format=json",
        f"{GENOME}/v3",
        OLD.replace("https://", "http://"),
        OLD.replace("w3id.org", "w3id.org.example"),
        f"https://w3id.org/battinfo/Cell/{UID}",
        f"https://w3id.org/battinfo/cell_type/{UID}",
        f"https://w3id.org/battinfo/cell/{UID.upper()}",
        f"https://w3id.org/battinfo/cell/{UID.replace('-', '')}",
        "https://w3id.org/battinfo/cell/b6yn-0sxe-t2qk",
        f"https://w3id.org/battinfo/cell/x/{UID}",
        f"https://w3id.org/battinfo/id/100/cell/{UID}",
        f"https://w3id.org/battinfo/id/abcd/cell/{UID}",
        f"https://w3id.org/battinfo/id/1001/{UID}",
        f"https://w3id.org/battinfo/id/1001/id/{UID}",
        "https://w3id.org/battinfo/id/1001/harmonisedCycleIndex",
        f"https://w3id.org/battinfo/def/{UID}",
        THING,
        "https://w3id.org/battinfo/context/records/v1.json",
        "https://w3id.org/battinfo/batchId",
    ],
)
def test_parse_record_iri_refuses_anything_but_a_whole_record_iri(value: object) -> None:
    assert parse_record_iri(value) is None


@pytest.mark.parametrize("letter", "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.")
def test_the_uid_alphabet_is_the_minting_alphabet(letter: str) -> None:
    """A uid takes the 32 characters stable_uid mints from: digits and lower-case letters but i, l, o and u."""
    uid = f"{letter}6yn-0sxe-t2qk-9mjv"
    expected = letter in UID_ALPHABET
    assert (parse_record_iri(f"https://w3id.org/battinfo/cell/{uid}") is not None) is expected
    assert (parse_thing_iri(f"https://w3id.org/battinfo/id/{uid}") is not None) is expected
    assert (record_iri_pattern("cell").fullmatch(f"https://w3id.org/battinfo/cell/{uid}") is not None) is expected


def test_parse_thing_iri_reads_a_shared_thing_and_nothing_else() -> None:
    assert parse_thing_iri(THING) == UID
    for value in (OLD, GENOME, f"{THING}/", f"{THING}/v2", "https://w3id.org/battinfo/id/1001", None, UID):
        assert parse_thing_iri(value) is None


# ── One record, two shapes ──────────────────────────────────────────────────


def test_the_old_form_and_the_battery_genome_form_are_one_record() -> None:
    assert same_record(OLD, GENOME) and same_record(GENOME, OLD)
    assert same_record(OLD, OLD) and same_record(GENOME, GENOME) and same_record(SECOND_HUB, SECOND_HUB)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (OLD, SECOND_HUB),
        (GENOME, SECOND_HUB),
        (OLD, f"https://w3id.org/battinfo/spec/{UID}"),
        (OLD, f"https://w3id.org/battinfo/cell/{OTHER_UID}"),
        (GENOME, f"https://w3id.org/battinfo/id/1001/cell/{OTHER_UID}"),
        (OLD, THING),
        (OLD, f"{OLD}/"),
        (OLD, None),
        (None, None),
        ("not an IRI", "not an IRI"),
    ],
)
def test_iris_of_two_records_are_not_the_same_record(left: object, right: object) -> None:
    assert not same_record(left, right)


# ── Recognisers ─────────────────────────────────────────────────────────────


def test_a_pattern_accepts_the_old_form_only_unless_both_shapes_are_asked_for() -> None:
    old_only = record_iri_pattern("cell")
    both = record_iri_pattern("cell", both_shapes=True)
    assert old_only.fullmatch(OLD) and not old_only.fullmatch(GENOME) and not old_only.fullmatch(SECOND_HUB)
    for iri in (OLD, GENOME, SECOND_HUB):
        assert both.fullmatch(iri)
    for iri in (
        f"https://w3id.org/battinfo/id/1/cell/{UID}",
        f"https://w3id.org/battinfo/id/abc/cell/{UID}",
        f"https://w3id.org/battinfo/id/1001/spec/{UID}",
        "https://w3id.org/battinfo/id/1001/cell/b6yn-0sxe-t2qk-9mjI",
        THING,
    ):
        assert not both.fullmatch(iri)


def test_a_pattern_takes_several_segments_and_needs_one() -> None:
    pattern = record_iri_pattern("spec", "material-spec")
    assert pattern.fullmatch(f"https://w3id.org/battinfo/spec/{UID}")
    assert pattern.fullmatch(f"https://w3id.org/battinfo/material-spec/{UID}")
    assert not pattern.fullmatch(f"https://w3id.org/battinfo/material/{UID}")
    with pytest.raises(ValueError):
        record_iri_regex()
    with pytest.raises(ValueError):
        record_iri_regex("id")


def test_a_regex_has_no_groups_so_a_json_schema_pattern_can_take_it() -> None:
    assert re.compile(record_iri_regex("spec", "cell", both_shapes=True)).groups == 0
    assert re.compile(record_iri_regex("spec", "cell", both_shapes=True, things=True)).groups == 0


def test_a_pattern_with_things_also_takes_a_shared_thing() -> None:
    pattern = record_iri_pattern("organization", both_shapes=True, things=True)
    organization = f"https://w3id.org/battinfo/organization/{UID}"
    for iri in (organization, f"https://w3id.org/battinfo/id/1001/organization/{UID}", THING):
        assert pattern.fullmatch(iri), iri
    for iri in (
        f"https://w3id.org/battinfo/id/1001/{UID}",
        f"https://w3id.org/battinfo/id/id/{UID}",
        f"https://w3id.org/battinfo/{UID}",
        f"{THING}/",
        f"https://w3id.org/battinfo/id/{UID.upper()}",
        OLD,
    ):
        assert not pattern.fullmatch(iri), iri
    old_form_and_thing = record_iri_pattern("organization", things=True)
    assert old_form_and_thing.fullmatch(organization) and old_form_and_thing.fullmatch(THING)
    assert not old_form_and_thing.fullmatch(f"https://w3id.org/battinfo/id/1001/organization/{UID}")


_UID_TAIL = r"[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}"


_RECOGNISERS = [
    ("battinfo.api._shared", "SPEC_IRI_RE", ("spec",)),
    ("battinfo.api._shared", "CELL_IRI_RE", ("cell",)),
    ("battinfo.api._shared", "DATASET_IRI_RE", ("dataset",)),
    ("battinfo.api._shared", "TEST_IRI_RE", ("test",)),
    ("battinfo.api._shared", "MATERIAL_SPEC_IRI_RE", ("spec", "material-spec")),
    ("battinfo.api._shared", "MATERIAL_IRI_RE", ("material",)),
    ("battinfo.validate.references", "SPEC_IRI_RE", ("spec",)),
    ("battinfo.validate.references", "CELL_IRI_RE", ("cell",)),
    ("battinfo.validate.references", "DATASET_IRI_RE", ("dataset",)),
    ("battinfo.validate.references", "TEST_IRI_RE", ("test",)),
]
# Recognisers of a reference to a product model or a material, which also take a shared thing.
_REFERENCE_RECOGNISERS = [
    ("battinfo.api._shared", "CELL_SPEC_REF_IRI_RE", ("spec",)),
    ("battinfo.api._shared", "MATERIAL_SPEC_REF_IRI_RE", ("spec", "material-spec")),
]


def _accepted_and_refused(segment: str) -> tuple[list[str], list[str]]:
    """IRIs under *segment* that a recogniser of both shapes accepts, and IRIs it refuses."""
    other = "dataset" if segment != "dataset" else "cell"
    accepted = [
        f"https://w3id.org/battinfo/{segment}/{UID}",
        f"https://w3id.org/battinfo/id/1001/{segment}/{UID}",
        f"https://w3id.org/battinfo/id/1002/{segment}/{UID}",
        f"https://w3id.org/battinfo/id/12345/{segment}/{UID}",
    ]
    refused = [
        f"https://w3id.org/battinfo/id/1/{segment}/{UID}",
        f"https://w3id.org/battinfo/id/abc/{segment}/{UID}",
        f"https://w3id.org/battinfo/{other}/{UID}",
        f"https://w3id.org/battinfo/id/1001/{other}/{UID}",
        f"https://w3id.org/battinfo/{segment}/{UID[:-1]}I",
        f"https://w3id.org/battinfo/{segment}/{UID}/",
        f"https://w3id.org/battinfo/id/1001/{segment}/{UID}#described",
    ]
    return accepted, refused


@pytest.mark.parametrize(("module", "name", "segments"), _RECOGNISERS)
def test_every_recogniser_accepts_both_shapes_and_nothing_else(
    module: str, name: str, segments: tuple[str, ...]
) -> None:
    import importlib

    recogniser = getattr(importlib.import_module(module), name)
    assert recogniser.pattern == record_iri_regex(*segments, both_shapes=True)
    for segment in segments:
        accepted, refused = _accepted_and_refused(segment)
        assert all(recogniser.fullmatch(iri) for iri in accepted), accepted
        assert not any(recogniser.fullmatch(iri) for iri in refused), refused
    assert not recogniser.fullmatch(THING), "a record's own id is never a shared thing"


@pytest.mark.parametrize(("module", "name", "segments"), _REFERENCE_RECOGNISERS)
def test_a_reference_recogniser_also_takes_a_shared_thing(module: str, name: str, segments: tuple[str, ...]) -> None:
    import importlib

    recogniser = getattr(importlib.import_module(module), name)
    assert recogniser.pattern == record_iri_regex(*segments, both_shapes=True, things=True)
    for segment in segments:
        accepted, refused = _accepted_and_refused(segment)
        assert all(recogniser.fullmatch(iri) for iri in [*accepted, THING]), accepted
        assert not any(recogniser.fullmatch(iri) for iri in refused), refused


def test_the_api_uid_tail_is_the_module_uid_grammar_unchanged() -> None:
    from battinfo import api

    assert api._UID_TAIL == namespace.UID_PATTERN == _UID_TAIL


@pytest.mark.parametrize("family", ["electrode", "separator", "current-collector", "equipment", "organization"])
def test_the_component_recognisers_accept_both_shapes(family: str) -> None:
    from battinfo.api._shared import _component_iri_re, _spec_iri_re

    for prefix in (None, "1001", "1002"):
        assert _component_iri_re(family).fullmatch(record_iri(family, UID, prefix))
        assert _spec_iri_re(f"{family}-spec").fullmatch(record_iri("spec", UID, prefix))
        assert _spec_iri_re(f"{family}-spec").fullmatch(record_iri(f"{family}-spec", UID, prefix))
        assert not _component_iri_re(family).fullmatch(record_iri("cell", UID, prefix))
        assert not _spec_iri_re(f"{family}-spec").fullmatch(record_iri(family, UID, prefix))
    for iri in (
        f"https://w3id.org/battinfo/{family}/{UID}/",
        f"https://w3id.org/battinfo/{family}/{UID.upper()}",
        THING,
    ):
        assert not _component_iri_re(family).fullmatch(iri)
        assert not _spec_iri_re(f"{family}-spec").fullmatch(iri)


# ── No other module builds or matches a record IRI ──────────────────────────

_RECORD_BASE_LITERALS = ("https://w3id.org/battinfo/", r"https://w3id\.org/battinfo/")
# Callables whose string arguments are messages, help or descriptions.
_MESSAGE_CALLS = frozenset({"warn", "echo", "secho", "print", "Field", "Option", "Argument", "_append_issue"})
_MESSAGE_KEYWORDS = frozenset({"help", "description", "message", "hint"})
# Variables a message is built in before it is raised or reported.
_MESSAGE_VARIABLES = frozenset({"msg", "message", "replacement"})


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def _call_name(call: ast.Call) -> str:
    func = call.func
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def _is_message(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Whether *node* is part of a raised exception, a message call or a help or description argument."""
    current = node
    while current in parents:
        parent = parents[current]
        if isinstance(parent, ast.Assign):
            return all(isinstance(target, ast.Name) and target.id in _MESSAGE_VARIABLES for target in parent.targets)
        if isinstance(parent, ast.stmt):
            return isinstance(parent, ast.Raise)
        if isinstance(parent, ast.keyword) and parent.arg in _MESSAGE_KEYWORDS:
            return True
        if isinstance(parent, ast.Dict) and current in parent.values:
            key = parent.keys[parent.values.index(current)]
            if isinstance(key, ast.Constant) and key.value in _MESSAGE_KEYWORDS:
                return True
        if isinstance(parent, ast.Call) and current is not parent.func:
            name = _call_name(parent)
            if name in _MESSAGE_CALLS or name.endswith(("Error", "Exception", "Warning")):
                return True
        current = parent
    return False


def _names_the_standard(node: ast.Constant, parents: dict[ast.AST, ast.AST]) -> bool:
    """Whether *node* names the vocabulary, context or schema namespace, which never change with the record shapes."""
    value = node.value
    if any(value.startswith((literal + "context/", literal + "schema/")) for literal in _RECORD_BASE_LITERALS):
        return True
    parent = parents.get(node)
    # The vocabulary namespace as a JSON-LD prefix or a conformsTo target.
    return value == BATTINFO_ROOT and (
        isinstance(parent, ast.Dict)
        or (isinstance(parent, ast.Assign) and all(isinstance(target, ast.Subscript) for target in parent.targets))
    )


def _record_base_offenders(path: Path, root: Path = ROOT) -> list[str]:
    """The lines of *path* outside a docstring, a message or a standard namespace that hold the record base."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    parents = _parents(tree)
    docstrings = {
        id(owner.body[0].value)
        for owner in ast.walk(tree)
        if isinstance(owner, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and owner.body
        and isinstance(owner.body[0], ast.Expr)
    }
    where = path.relative_to(root).as_posix()
    lines = source.splitlines()
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docstrings or not any(literal in node.value for literal in _RECORD_BASE_LITERALS):
            continue
        if _is_message(node, parents) or _names_the_standard(node, parents):
            continue
        offenders.append(f"{where}:{node.lineno}: {lines[node.lineno - 1].strip()}")
    return offenders


def test_no_module_but_the_namespace_module_builds_or_matches_a_record_iri() -> None:
    """Every record IRI is built with record_iri and recognised with a pattern or parser of battinfo.namespace.

    A string with the record base is allowed elsewhere only in a docstring, a
    message (an exception, a warning, a validation issue, CLI help, a field
    description) and where it names the vocabulary, context or schema namespace.
    """
    package = ROOT / "src" / "battinfo"
    offenders = [
        offender
        for path in sorted(package.rglob("*.py"))
        if path != package / "namespace.py"
        for offender in _record_base_offenders(path)
    ]
    assert not offenders, "Build and recognise record IRIs through battinfo.namespace:\n" + "\n".join(offenders)


def test_the_source_scan_catches_a_builder_and_a_recogniser(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        '"""A docstring naming https://w3id.org/battinfo/cell/{uid}."""\n'
        "def build(uid):\n"
        "    return f'https://w3id.org/battinfo/cell/{uid}'\n"
        "def check(value):\n"
        "    return value.startswith('https://w3id.org/battinfo/')\n"
        "def fail(value):\n"
        "    raise ValueError(f'{value} must match https://w3id.org/battinfo/cell/{{uid}}.')\n"
        "PREFIXES = {'battinfo': 'https://w3id.org/battinfo/'}\n"
        "CONTEXT = 'https://w3id.org/battinfo/context/records/v1.json'\n"
        "msg = 'an id must match https://w3id.org/battinfo/cell/{uid}'\n"
        "iri = 'https://w3id.org/battinfo/cell/' + UID\n",
        encoding="utf-8",
    )
    offenders = _record_base_offenders(sample, root=tmp_path)
    assert sorted(int(offender.split(":")[1]) for offender in offenders) == [3, 5, 11]


# ── A message names both shapes ─────────────────────────────────────────────


@pytest.mark.parametrize("things", [False, True])
def test_record_iri_forms_names_the_shapes_the_recogniser_accepts(things: bool) -> None:
    wording = record_iri_forms("cell", things=things)
    assert wording.startswith(
        "https://w3id.org/battinfo/cell/{uid} or https://w3id.org/battinfo/id/{prefix}/cell/{uid}"
    )
    named = [shape.format(uid=UID, prefix="1001") for shape in re.findall(r"https://\S+?\{uid\}", wording)]
    assert named == [OLD, GENOME, *([THING] if things else [])]
    recogniser = record_iri_pattern("cell", both_shapes=True, things=things)
    assert all(recogniser.fullmatch(iri) for iri in named)
    assert ("shared thing" in wording) is things
    with pytest.raises(ValueError, match="not a record segment"):
        record_iri_forms("id")


# The shape of a record IRI written out by hand: the record base, a segment and a stand-in for the uid.
_HAND_WRITTEN_SHAPE = re.compile(r"https://w3id\.org/battinfo/(?!id/)[^\s/]+/(?:\{uid\}|<uid>|xxxx-|\.\.\.)")
# _adoption names the old form as the form a registry may hold a record in, beside the base it was minted under.
_NAMES_THE_OLD_FORM_ON_PURPOSE = frozenset({"src/battinfo/_adoption.py"})


def _hand_written_shapes(path: Path, root: Path = ROOT) -> list[str]:
    """The messages of *path* that write out the shape of a record IRI, with ``{}`` for each value an f-string fills in."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    parents = _parents(tree)
    where = path.relative_to(root).as_posix()
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(part.value if isinstance(part, ast.Constant) else "{}" for part in node.values)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = "" if isinstance(parents.get(node), ast.JoinedStr) else node.value
        else:
            continue
        shape = _HAND_WRITTEN_SHAPE.search(text)
        if shape is not None and _is_message(node, parents):
            offenders.append(f"{where}:{node.lineno}: {shape[0]}")
    return offenders


def test_no_message_writes_out_the_shape_of_a_record_iri() -> None:
    """A message that says what a record IRI looks like takes the wording from record_iri_forms.

    A shape written out by hand names one form and leaves the other out, as the messages did before the wording was shared. An exception, a warning, a validation issue, CLI help and a field description all count; a docstring cannot call the function, so it writes both shapes out.
    """
    package = ROOT / "src" / "battinfo"
    offenders = [
        offender
        for path in sorted(package.rglob("*.py"))
        if path != package / "namespace.py" and path.relative_to(ROOT).as_posix() not in _NAMES_THE_OLD_FORM_ON_PURPOSE
        for offender in _hand_written_shapes(path)
    ]
    assert not offenders, "Name the shapes of a record IRI with namespace.record_iri_forms():\n" + "\n".join(offenders)


def test_the_message_scan_catches_a_shape_written_out_by_hand(tmp_path: Path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        '"""A docstring naming https://w3id.org/battinfo/cell/{uid}."""\n'
        "def fail(value, segment):\n"
        "    if value is None:\n"
        "        raise ValueError(f'id must match {record_iri_forms(\"cell\")}.')\n"
        "    if segment:\n"
        "        raise ValueError(f'{value} must match https://w3id.org/battinfo/{segment}/{{uid}}.')\n"
        "    if value:\n"
        "        raise ValueError(f'{value} is not a test IRI; expected '\n"
        "                         'https://w3id.org/battinfo/test/xxxx-xxxx-xxxx-xxxx.')\n"
        "    raise ValueError('minted under https://w3id.org/battinfo/id/1001/, not https://w3id.org/battinfo/')\n"
        "OPTION = Option(None, help='Its IRI (https://w3id.org/battinfo/spec/...) or its name.')\n"
        "FIELD = Field(default=None, description='A material-spec IRI (https://w3id.org/battinfo/spec/<uid>).')\n"
        "replacement = f'its replacement is https://w3id.org/battinfo/dataset/{value}'\n"
        "example = 'https://w3id.org/battinfo/cell/{uid}'\n",
        encoding="utf-8",
    )
    offenders = _hand_written_shapes(sample, root=tmp_path)
    assert sorted(int(offender.split(":")[1]) for offender in offenders) == [6, 8, 11, 12]


def _message(call: Any) -> str:
    with pytest.raises((ValueError, TypeError)) as raised:
        call()
    return str(raised.value)


def test_a_message_about_a_record_iri_names_both_shapes(tmp_path: Path) -> None:
    import battinfo
    from battinfo import ws
    from battinfo.api import create_channel, create_material
    from battinfo.interop import bpx

    spec, dataset, cell = record_iri_forms("spec"), record_iri_forms("dataset"), record_iri_forms("cell")
    spec_or_thing = record_iri_forms("spec", things=True)

    assert f"material_spec_id must match {spec_or_thing}." == _message(lambda: create_material(material_spec_id="x"))
    assert f"equipment_id must match {record_iri_forms('equipment')}." == _message(
        lambda: create_channel(equipment_id="x", index=1)
    )
    assert f"cell_id must match {cell}." == _message(
        lambda: battinfo.save_test(battinfo.Test(cell_id="x", test_type="cycling"), source_root=tmp_path)
    )
    assert f"expected {spec}." in _message(lambda: ws._draft_spec_iri("https://example.org/x", None, "draft.json"))
    assert f"({record_iri_forms('organization', things=True)})" in _message(
        lambda: ws._deposit_publisher({"name": "Example Lab", "id": "https://example.org/lab"})
    )
    assert f"material-spec IRI ({spec_or_thing})" in _message(lambda: bpx._material_target("no such kind", "positive"))
    claim = {"parameter": "particle_radius", "quantity": {"value": 5.86e-06, "unit": "m"}, "provenance_class": "fitted"}
    assert f"supersedes must be a parameter-set IRI ({dataset})" in _message(
        lambda: battinfo.api.create_parameter_set(
            name="Example - graphite", material_kind="graphite", claims=[claim], supersedes="x"
        )
    )


# ── A saved record keeps the IRI it has, in either shape ────────────────────


def _lab_spec(rated: float = 2.0):
    import battinfo

    return battinfo.CellSpec(
        manufacturer="Example Lab",
        model="R2032",
        format="coin",
        chemistry="li-ion",
        properties={"rated_capacity": {"value": rated, "unit": "Ah"}},
    )


def _record_files(root: Path) -> dict[Path, tuple[bytes, int]]:
    folder = root / ".battinfo" / "records"
    return {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in sorted(folder.rglob("*.json"))}


def _old_workspace(root: Path) -> Any:
    """A workspace that mints the old form, as one created before the switch does."""
    import battinfo

    return battinfo.workspace(root, registry_url=None, base=OLD_FORM_BASE)


def _minting_under(root: Path, base: str) -> Any:
    """The workspace at *root* opened again, its records minted under *base*.

    A workspace keeps the base it was created with, so this stands for a
    session of the other base over the same records folder, such as a new
    workspace that the records of an old one were copied into.
    """
    import battinfo

    ws = battinfo.workspace(root, registry_url=None)
    ws._record_base = base
    ws._ws = ws._make_engine()
    return ws


def _as_prefixed(iri: str, prefix: str = "1001") -> str:
    parsed = parse_record_iri(iri)
    assert parsed is not None and parsed.prefix is None
    return record_iri(parsed.segment, parsed.uid, prefix)


def test_a_record_saved_in_the_old_form_keeps_its_iri_when_minted_with_a_prefix(tmp_path: Path) -> None:
    root = tmp_path / "lab"
    first = _old_workspace(root)
    first.add("cell", spec=_lab_spec(), serial_numbers=["C01", "C02"])
    first.save()
    saved_ids = sorted(item.id for item in [*first._ws.cell_specs, *first._ws.cells])
    assert all(parse_record_iri(iri).prefix is None for iri in saved_ids)
    before = _record_files(root)

    rerun = _minting_under(root, DEFAULT_RECORD_BASE)
    rerun.add("cell", spec=_lab_spec(), serial_numbers=["C01", "C02"])
    rerun.save()

    assert sorted(item.id for item in [*rerun._ws.cell_specs, *rerun._ws.cells]) == saved_ids
    assert {cell.cell_spec_id for cell in rerun._ws.cells} == {first._ws.cell_specs[0].id}
    assert _record_files(root) == before


def test_a_new_record_beside_a_saved_one_takes_the_prefix(tmp_path: Path) -> None:
    """Only the record that is already saved keeps the old form."""
    root = tmp_path / "lab"
    first = _old_workspace(root)
    first.add("cell", spec=_lab_spec(), serial_numbers=["C01"])
    first.save()

    rerun = _minting_under(root, DEFAULT_RECORD_BASE)
    rerun.add("cell", spec=_lab_spec(), serial_numbers=["C01", "C02"])
    finalized = rerun._ws._finalized_records()

    by_serial = {cell.serial_number: cell.id for cell in finalized["cells"]}
    assert by_serial["C01"] == first._ws.cells[0].id
    assert parse_record_iri(by_serial["C02"]).prefix == "1001"


def _rerun_beside_a_prefixed_spec(tmp_path: Path) -> tuple[Any, dict[str, list[Any]]]:
    """A cell and its spec saved, the spec's file rewritten under /id/1001/, and a new session minting them again.

    The second session is only finalized: its records carry the IRIs a save
    would write them under (``_finalized_records``). Both sessions mint the old form.
    """
    import battinfo

    root = tmp_path / "lab"
    first = _old_workspace(root)
    first.add("cell", spec=_lab_spec(), serial_numbers=["C01"])
    first.save()
    (path,) = (root / ".battinfo" / "records" / "cell-spec").glob("*.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["cell_spec"]["id"] = _as_prefixed(first._ws.cell_specs[0].id)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    rerun = battinfo.workspace(root, registry_url=None)
    rerun.add("cell", spec=_lab_spec(), serial_numbers=["C01"])
    return first, rerun._ws._finalized_records()


def test_a_record_saved_in_the_prefixed_form_keeps_its_iri_when_minted_in_the_old_form(tmp_path: Path) -> None:
    """The reverse: a spec saved under /id/1001/ keeps that IRI when a session mints the old form."""
    first, finalized = _rerun_beside_a_prefixed_spec(tmp_path)
    prefixed = _as_prefixed(first._ws.cell_specs[0].id)

    assert [spec.id for spec in finalized["cell_specs"]] == [prefixed]
    assert [cell.cell_spec_id for cell in finalized["cells"]] == [prefixed]


def test_a_cell_under_a_spec_saved_in_the_prefixed_form_keeps_its_iri(tmp_path: Path) -> None:
    """The /id/1001/ spec IRI enters the cell's seed in the old form, so the cell keeps its uid (BIG-MAP/BattINFO#482)."""
    first, finalized = _rerun_beside_a_prefixed_spec(tmp_path)

    assert [cell.id for cell in finalized["cells"]] == [first._ws.cells[0].id]


def test_the_saved_record_lookup_finds_either_form_of_one_record_and_no_other(tmp_path: Path) -> None:
    root = tmp_path / "lab"
    first = _old_workspace(root)
    first.add("cell", spec=_lab_spec(), serial_numbers=["C01"])
    first.save()
    records = first._ws.source_root
    old_iri = first._ws.cell_specs[0].id
    uid = parse_record_iri(old_iri).uid
    (path,) = (records / "cell-spec").glob("*.json")
    doc = json.loads(path.read_text(encoding="utf-8"))

    assert saved_record_body("cell-spec", uid, [records])["id"] == old_iri
    for prefix, found in (("1001", True), ("1002", False)):
        doc["cell_spec"]["id"] = _as_prefixed(old_iri, prefix)
        path.write_text(json.dumps(doc), encoding="utf-8")
        saved = saved_record_document("cell-spec", uid, [records])
        assert (saved is not None) is found
        if found:
            assert saved["cell_spec"]["id"] == _as_prefixed(old_iri, prefix)


# ── A reference and a query find a record under either form of its IRI ──────

LOOSE_SPEC = {"manufacturer": "Example Lab", "model": "R2032", "format": "coin", "chemistry": "li-ion"}
BASES = pytest.mark.parametrize("base", [OLD_FORM_BASE, DEFAULT_RECORD_BASE], ids=["old-form", "id-1001"])
SESSIONS = pytest.mark.parametrize("in_session", [False, True], ids=["plain", "bulk-session"])


def _other_form(iri: str, prefix: str = "1001") -> str:
    """The old form of an ``/id/1001/`` IRI, and the *prefix* form of an old-form one."""
    parsed = parse_record_iri(iri)
    assert parsed is not None and parsed.prefix in (None, "1001")
    return record_iri(parsed.segment, parsed.uid, prefix if parsed.prefix is None else None)


def _under(iri: str, prefix: str) -> str:
    parsed = parse_record_iri(iri)
    assert parsed is not None
    return record_iri(parsed.segment, parsed.uid, prefix)


def _saved_chain(records: Path, base: str) -> dict[str, str]:
    """A cell spec, a cell of it, a test of the cell and a test protocol, saved under *records* with *base*."""
    from battinfo import api
    from battinfo.bundle import Test, TestSpec

    spec = api.save_cell_spec(dict(LOOSE_SPEC), source_root=records, base=base)["id"]
    cell = api.save_cell_instance({"cell_spec_id": spec, "serial_number": "C01"}, source_root=records, base=base)["id"]
    test = api.save_test(
        Test(cell_instance_id=cell, test_kind="cycling", name="run 1"), source_root=records, base=base
    )["id"]
    protocol = api.save_test_spec(TestSpec(name="CCCV 1C", test_kind="cycling"), source_root=records, base=base)["id"]
    return {"spec": spec, "cell": cell, "test": test, "protocol": protocol}


def _session(records: Path, in_session: bool) -> Any:
    """A bulk save session over *records*, whose lookups read its cache, or nothing."""
    import contextlib

    from battinfo._record_index import bulk_save_session

    return bulk_save_session(records) if in_session else contextlib.nullcontext()


def _saved_body(result: dict[str, Any], key: str) -> dict[str, Any]:
    return json.loads(Path(result["path"]).read_text(encoding="utf-8"))[key]


@BASES
@SESSIONS
def test_a_save_resolves_a_reference_written_in_the_other_form(tmp_path: Path, base: str, in_session: bool) -> None:
    """A cell, a test and a dataset saved beside their parents, each parent named by the form the folder lacks."""
    from battinfo import api
    from battinfo.bundle import Dataset, Test

    records = tmp_path / "records"
    saved = _saved_chain(records, base)
    spec_ref, cell_ref, test_ref = (_other_form(saved[name]) for name in ("spec", "cell", "test"))

    with _session(records, in_session):
        cell = api.save_cell_instance(
            {"cell_spec_id": spec_ref, "serial_number": "C02"}, source_root=records, base=base
        )
        test = api.save_test(
            Test(cell_instance_id=cell_ref, test_kind="eis", name="run 2"), source_root=records, base=base
        )
        dataset = api.save_dataset(
            Dataset(
                name="run 1 data", cell_instance_id=cell_ref, test_id=test_ref, access_url="https://example.org/a.csv"
            ),
            source_root=records,
            base=base,
        )

    stored = {
        "spec": _saved_body(cell, "cell_instance")["cell_spec_id"],
        "cell": _saved_body(test, "test")["cell_id"],
        "about": _saved_body(dataset, "dataset")["about"],
    }
    if base == DEFAULT_RECORD_BASE:
        # The reference is stored as it was written; only the lookup reads both forms.
        assert stored == {"spec": spec_ref, "cell": cell_ref, "about": [cell_ref, test_ref]}
    else:
        # A folder that holds the old form adopts it in what a save names (#483), as before.
        assert stored == {"spec": saved["spec"], "cell": saved["cell"], "about": [saved["cell"], saved["test"]]}
    assert {parse_record_iri(result["id"]).prefix for result in (cell, test, dataset)} == {
        parse_record_iri(saved["spec"]).prefix
    }


@BASES
@SESSIONS
def test_reference_validation_reads_either_form_and_no_other_prefix(
    tmp_path: Path, base: str, in_session: bool
) -> None:
    from battinfo.validate.references import validate_references_report

    records = tmp_path / "records"
    saved = _saved_chain(records, base)

    def codes(spec_ref: str) -> list[str]:
        doc = {"schema_version": "0.2.0", "cell_instance": {"id": saved["cell"], "cell_spec_id": spec_ref}}
        return [issue.code for issue in validate_references_report(doc, records).issues]

    with _session(records, in_session):
        assert codes(saved["spec"]) == []
        assert codes(_other_form(saved["spec"])) == []
        # Under another prefix the same uid is another record, which this folder does not hold.
        assert codes(_under(saved["spec"], "1002")) == ["reference.missing"]
        # A record found under its other form is still checked for its kind.
        assert codes(saved["protocol"]) == ["reference.type_mismatch"]
        assert codes(_other_form(saved["protocol"])) == ["reference.type_mismatch"]


@SESSIONS
def test_a_reference_takes_the_record_saved_under_the_iri_as_written_first(tmp_path: Path, in_session: bool) -> None:
    """Two files hold the two forms of one IRI, as a copy made by hand can leave, and each form finds its own file."""
    from battinfo import api
    from battinfo.validate.references import _find_record

    records = tmp_path / "records"
    saved = api.save_cell_spec(dict(LOOSE_SPEC), source_root=records)
    path = Path(saved["path"])
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["cell_spec"]["id"] = _other_form(saved["id"])
    copy = path.with_name("copied-by-hand.json")
    copy.write_text(json.dumps(doc), encoding="utf-8")

    with _session(records, in_session):
        assert _find_record(saved["id"], records) == (path, "cell-spec")
        assert _find_record(_other_form(saved["id"]), records) == (copy, "cell-spec")
        assert _find_record(_under(saved["id"], "1002"), records) is None


def test_the_cache_pairs_an_iri_with_the_form_same_record_pairs_it_with() -> None:
    from battinfo._record_index import _other_form as cached_other_form

    assert cached_other_form(OLD) == GENOME
    assert cached_other_form(GENOME) == OLD
    assert same_record(OLD, cached_other_form(OLD))
    for alone in (SECOND_HUB, THING, f"https://example.org/cell/{UID}", "C01", ""):
        assert cached_other_form(alone) is None


@BASES
@pytest.mark.parametrize("kind, name", [("cell_specs", "spec"), ("cells", "cell"), ("tests", "test")])
def test_a_query_by_id_finds_the_record_under_either_form(tmp_path: Path, base: str, kind: str, name: str) -> None:
    from battinfo import api

    records = tmp_path / "records"
    saved = _saved_chain(records, base)

    def found(iri: str) -> list[str]:
        return [row["id"] for row in api.query(kind, id=iri, source_root=records)]

    assert found(saved[name]) == [saved[name]]
    assert found(_other_form(saved[name])) == [saved[name]]
    assert found(_under(saved[name], "1002")) == []


# ── A deposit graph holds one node for a spec that cells name in both forms ──

SPEC_LINKS = ("dcterms:conformsTo", "hasDescription", "schema:isVariantOf")


def _lab_with_cells(root: Path, base: str, serial_numbers: list[str]) -> tuple[Any, str, dict[str, str]]:
    """A saved workspace with one spec and its cells, with the spec's IRI and each cell's IRI by serial number."""
    import battinfo

    ws = battinfo.workspace(root, registry_url=None, base=base)
    ws.add("cell", spec=_lab_spec(), serial_numbers=serial_numbers)
    ws.save()
    return ws, ws._ws.cell_specs[0].id, {cell.serial_number: cell.id for cell in ws._ws.cells}


def _name_the_spec_as(ws: Any, cell_iri: str, spec_ref: str) -> None:
    """Rewrite the saved cell *cell_iri* so that it names its spec as *spec_ref*, as a record written elsewhere may."""
    for path in (ws._ws.source_root / "cell-instance").glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc["cell_instance"]["id"] == cell_iri:
            doc["cell_instance"]["cell_spec_id"] = spec_ref
            path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
            return
    raise AssertionError(f"no saved cell {cell_iri}")


def _preview_graph(ws: Any) -> list[dict[str, Any]]:
    """The graph ``ws.preview_jsonld()`` writes, which is the one a Zenodo deposit would carry."""
    path = ws.preview_jsonld(title="Example cells", creators=[{"name": "Doe, Jane"}], license="cc-by-4.0")
    return json.loads(Path(path).read_text(encoding="utf-8"))["@graph"]


@BASES
def test_a_cell_that_names_its_spec_in_the_other_form_links_to_the_spec_node(tmp_path: Path, base: str) -> None:
    ws, spec_iri, cells = _lab_with_cells(tmp_path / "lab", base, ["C01", "C02", "C03"])
    _name_the_spec_as(ws, cells["C02"], _other_form(spec_iri))
    _name_the_spec_as(ws, cells["C03"], _under(spec_iri, "1002"))

    nodes = {node["@id"]: node for node in _preview_graph(ws) if "@id" in node}

    # One node for the spec, the one the deposit carries, and no stub under its other form.
    assert [iri for iri in nodes if same_record(iri, spec_iri)] == [spec_iri]
    assert "rdfs:isDefinedBy" not in nodes[spec_iri]
    for serial in ("C01", "C02"):
        assert {term: nodes[cells[serial]][term] for term in SPEC_LINKS} == dict.fromkeys(SPEC_LINKS, {"@id": spec_iri})
    # The cell takes the kind of battery its spec describes, as the cell that names the spec as saved does.
    assert nodes[cells["C02"]]["@type"] == nodes[cells["C01"]]["@type"] != "BatteryCell"
    # Under another prefix the same uid is another record, which this deposit points at and does not carry.
    elsewhere = _under(spec_iri, "1002")
    assert nodes[elsewhere] == {
        "@id": elsewhere,
        "@type": "BatteryCellSpecification",
        "rdfs:isDefinedBy": {"@id": elsewhere},
    }
    assert {term: nodes[cells["C03"]][term] for term in SPEC_LINKS} == dict.fromkeys(SPEC_LINKS, {"@id": elsewhere})


def test_cells_that_name_an_outside_spec_in_both_forms_share_one_stub(tmp_path: Path) -> None:
    """The deposit does not carry the spec, so its cells point at one stub, under the form the first cell wrote."""
    ws, spec_iri, cells = _lab_with_cells(tmp_path / "lab", DEFAULT_RECORD_BASE, ["C01", "C02"])
    for path in (ws._ws.source_root / "cell-spec").glob("*.json"):
        path.unlink()
    first, second = sorted(cells.values())
    _name_the_spec_as(ws, second, _other_form(spec_iri))

    nodes = {node["@id"]: node for node in _preview_graph(ws) if "@id" in node}

    assert [iri for iri in nodes if same_record(iri, spec_iri)] == [spec_iri]
    assert nodes[spec_iri] == {
        "@id": spec_iri,
        "@type": "BatteryCellSpecification",
        "rdfs:isDefinedBy": {"@id": spec_iri},
    }
    for cell_iri in (first, second):
        assert {term: nodes[cell_iri][term] for term in SPEC_LINKS} == dict.fromkeys(SPEC_LINKS, {"@id": spec_iri})
