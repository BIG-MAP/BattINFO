"""`battinfo map` writes JSON-LD that carries the record, or exits non-zero.

Before 0.8.0, eight of the 22 record kinds fell through to an emitter for the
old base-profile envelope, so `battinfo map` wrote a document with no @id and
no record content and exited 0. Its default target was a Battery Pass stub
that put a top-level @type beside @graph. Now domain-battery is the default,
the Battery Pass target is gone, and a kind that `to_jsonld` does not emit
exits 2 with a message that names `battinfo.record_to_jsonld`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import record_to_jsonld  # noqa: E402
from battinfo.cli import app  # noqa: E402
from battinfo.entities import ENTITY_KINDS, kind_for_doc  # noqa: E402
from battinfo.transform.json_to_jsonld import to_jsonld  # noqa: E402

runner = CliRunner()
EXAMPLES = ROOT / "examples"
FLAGSHIP = EXAMPLES / "cell-spec" / "A123__ANR26650M1-B.json"

# Record kinds (entity types) that to_jsonld, and so `battinfo map`, does not emit.
NOT_MAPPED = {"cell", "test-protocol", "test", "dataset", "equipment-spec", "equipment", "channel", "organization"}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _first_example_per_kind() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in sorted(EXAMPLES.rglob("*.json")):
        kind = kind_for_doc(_load(path))
        if kind is not None:
            found.setdefault(kind.entity_type, path)
    return found


EXAMPLE_BY_KIND = _first_example_per_kind()


def _record_type(entity_type: str) -> str:
    return "cell-instance" if entity_type == "cell" else entity_type


def _node_ids(document: dict[str, Any]) -> set[Any]:
    graph = document.get("@graph")
    nodes = graph if isinstance(graph, list) else [document]
    return {node.get("@id") for node in nodes if isinstance(node, dict)}


def _map(*args: str) -> Any:
    return runner.invoke(app, ["map", *args])


def test_there_is_an_example_of_every_kind() -> None:
    assert sorted(EXAMPLE_BY_KIND) == sorted(kind.entity_type for kind in ENTITY_KINDS)


@pytest.mark.parametrize("entity_type", [kind.entity_type for kind in ENTITY_KINDS])
def test_map_writes_the_record_or_exits_non_zero(entity_type: str, tmp_path: Path) -> None:
    path = EXAMPLE_BY_KIND[entity_type]
    record = _load(path)
    kind = kind_for_doc(record)
    assert kind is not None
    iri = record[kind.record_key]["id"]
    out = tmp_path / "mapped.jsonld"

    result = _map(str(path), "--out", str(out))

    if entity_type in NOT_MAPPED:
        assert result.exit_code == 2, result.output
        assert not out.exists(), "a refused record must not leave an output file"
        hint = f"battinfo.record_to_jsonld(record, {_record_type(entity_type)!r})"
        assert hint in result.output
        # The type the message names is one record_to_jsonld accepts.
        assert iri in _node_ids(record_to_jsonld(record, _record_type(entity_type)))
        return
    assert result.exit_code == 0, result.output
    mapped = _load(out)
    nodes = mapped.get("@graph")
    assert isinstance(nodes, list) and nodes, f"{path.name} mapped to a document with no graph"
    assert iri in _node_ids(mapped), f"the graph for {path.name} has no node for {iri}"
    assert "@type" not in mapped, "a top-level @type beside @graph moves every triple into a named graph"


def test_map_defaults_to_domain_battery(tmp_path: Path) -> None:
    out = tmp_path / "flagship.jsonld"
    result = _map(str(FLAGSHIP), "--out", str(out))
    assert result.exit_code == 0, result.output
    assert _load(out) == to_jsonld(_load(FLAGSHIP), target="domain-battery")
    assert "batterypass" not in out.read_text(encoding="utf-8")


def test_map_refuses_the_removed_batterypass_target(tmp_path: Path) -> None:
    out = tmp_path / "flagship.jsonld"
    result = _map(str(FLAGSHIP), "--target", "batterypass", "--out", str(out))
    assert result.exit_code == 2, result.output
    assert not out.exists()
    assert "removed in 0.8.0" in result.output
    assert "domain-battery" in result.output


def test_map_refuses_a_document_it_cannot_route(tmp_path: Path) -> None:
    source = tmp_path / "notes.json"
    source.write_text(json.dumps({"title": "Lab notes", "cells": 3}), encoding="utf-8")
    out = tmp_path / "notes.jsonld"
    result = _map(str(source), "--out", str(out))
    assert result.exit_code == 2, result.output
    assert "not a BattINFO record" in result.output
    assert not out.exists()


def test_map_refuses_a_file_that_is_not_a_json_object(tmp_path: Path) -> None:
    out = tmp_path / "out.jsonld"
    for name, text in (("list.json", "[1, 2]"), ("broken.json", '{"cell_spec": ')):
        source = tmp_path / name
        source.write_text(text, encoding="utf-8")
        result = _map(str(source), "--out", str(out))
        assert result.exit_code == 2, f"{name}: {result.output}"
        assert result.exception is None or isinstance(result.exception, SystemExit), f"{name} raised a traceback"
        assert not out.exists()


def test_map_still_maps_the_base_profile_envelope(tmp_path: Path) -> None:
    """`battinfo init --profile base` scaffolds the old envelope; it keeps its emitter."""
    workspace = tmp_path / "base"
    assert runner.invoke(app, ["init", str(workspace), "--profile", "base"]).exit_code == 0
    out = tmp_path / "base.jsonld"
    result = _map(str(workspace / "battinfo.json"), "--out", str(out))
    assert result.exit_code == 0, result.output
    mapped = _load(out)
    assert mapped["@id"] == "urn:uuid:example"
    assert mapped["hasBattery"]["@id"] == "battery-001"


def test_to_jsonld_names_schema_version_for_a_cell_spec_without_one() -> None:
    record = _load(FLAGSHIP)
    del record["schema_version"]
    with pytest.raises(ValueError, match="schema_version") as raised:
        to_jsonld(record, target="domain-battery")
    assert "battinfo.record_to_jsonld(record, 'cell-spec')" in str(raised.value)


def test_to_jsonld_names_schema_version_for_a_descriptor_without_one() -> None:
    descriptor = {"specification": {"manufacturer": "A123", "model": "ANR26650M1-B", "format": "cylindrical"}}
    with pytest.raises(ValueError, match="cell descriptor only when it has a schema_version"):
        to_jsonld(descriptor, target="domain-battery")


def test_to_jsonld_tells_an_electrode_without_schema_version_to_add_one() -> None:
    """record_to_jsonld hands an electrode to to_jsonld, so naming it would send the user round in a circle."""
    record = _load(EXAMPLE_BY_KIND["electrode"])
    del record["schema_version"]
    for emit in (lambda: to_jsonld(record, target="domain-battery"), lambda: record_to_jsonld(record, "electrode")):
        with pytest.raises(ValueError) as raised:
            emit()
        message = str(raised.value)
        assert "maps electrode records only when they have a schema_version; add one." in message
        assert "record_to_jsonld" not in message


@pytest.mark.filterwarnings("ignore:semantic.value_text_only")
@pytest.mark.parametrize("entity_type", [kind.entity_type for kind in ENTITY_KINDS])
def test_the_record_to_jsonld_call_an_error_names_works(entity_type: str) -> None:
    """Without schema_version a record is invalid, but the call its error suggests must still emit it."""
    record = _load(EXAMPLE_BY_KIND[entity_type])
    record.pop("schema_version", None)
    kind = kind_for_doc(record)
    assert kind is not None
    try:
        to_jsonld(record, target="domain-battery")
    except ValueError as exc:
        message = str(exc)
    else:
        return
    named = re.search(r"battinfo\.record_to_jsonld\(record, '([^']+)'\)", message)
    if named is None:
        assert "schema_version" in message, message
        return
    assert record[kind.record_key]["id"] in _node_ids(record_to_jsonld(record, named.group(1)))


def test_to_jsonld_lists_the_targets_it_has() -> None:
    with pytest.raises(ValueError) as raised:
        to_jsonld(_load(FLAGSHIP), target="nonsense")
    message = str(raised.value)
    assert "'domain-battery'" in message and "'converter-compatible'" in message
    assert "batterypass" not in message
