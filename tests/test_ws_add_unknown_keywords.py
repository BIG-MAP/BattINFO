"""ws.add() refuses an unknown keyword the way the record models do.

The keywords go on to a private method, so a stray one used to fail with
Python's own TypeError ("AuthoringWorkspace._add_tests() got an unexpected
keyword argument 'test_spec'"), which named that private method and listed
nothing. The error now names ws.add, suggests the closest keyword and lists
the accepted ones, before anything is created.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import battinfo

SPEC = {"manufacturer": "Example Lab", "model": "HC-01", "format": "coin", "chemistry": "li-ion"}


def _workspace_with_cell(tmp_path: Path):
    ws = battinfo.workspace(tmp_path, registry_url=None)
    ws.add("cell", spec=battinfo.CellSpec(**SPEC), serial_numbers=["S1"])
    return ws


def test_unknown_test_keyword_gets_a_did_you_mean_and_the_accepted_list(tmp_path: Path) -> None:
    ws = _workspace_with_cell(tmp_path)
    with pytest.raises(TypeError) as excinfo:
        ws.add("test", type="cycling", cell="S1", test_spec="https://w3id.org/battinfo/spec/x")
    message = str(excinfo.value)
    assert "ws.add('test')" in message
    assert "test_spec= (did you mean spec=?)" in message
    for keyword in ("protocol=", "description=", "status=", "license=", "series_id="):
        assert keyword in message
    assert "_add_tests" not in message
    assert ws._ws.tests == []


def test_unknown_keyword_without_a_close_match_still_lists_the_accepted_ones(tmp_path: Path) -> None:
    ws = _workspace_with_cell(tmp_path)
    with pytest.raises(TypeError, match=r"conditions=\. ws\.add\('test', \.\.\.\) accepts: "):
        ws.add("test", type="cycling", cell="S1", conditions={"temperature": 25})


def test_unknown_cell_and_equipment_keywords_name_ws_add(tmp_path: Path) -> None:
    ws = battinfo.workspace(tmp_path, registry_url=None)
    with pytest.raises(TypeError, match=r"serial_number= \(did you mean serial_numbers=\?\)"):
        ws.add("cell", spec=battinfo.CellSpec(**SPEC), serial_number="S1")
    with pytest.raises(TypeError, match=r"ws\.add\('equipment'\): serial= \(did you mean serial_number=\?\)"):
        ws.add("equipment", spec="unit.json", serial="MC-1")


def test_accepted_test_keywords_still_work(tmp_path: Path) -> None:
    ws = _workspace_with_cell(tmp_path)
    tests = ws.add(
        "test", type="cycling", cell="S1", description="first run", status="completed",
        license="cc-by-4.0", instrument="Maccor 4200",
    )
    assert len(tests) == 1
    assert tests[0].description == "first run"


def test_add_docstring_lists_the_test_keywords() -> None:
    doc = battinfo.ws.AuthoringWorkspace.add.__doc__ or ""
    for keyword in ("``protocol``", "``description``", "``status``", "``license``", "``series_id``"):
        assert keyword in doc
