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
