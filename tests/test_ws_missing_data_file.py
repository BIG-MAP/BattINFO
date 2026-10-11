"""ws.add("test", data=...) refuses a data file that does not exist (evaluation finding C-02).

The getting-started workspace snippet saved a dataset record for bdf/S1.bdf.csv
in a folder that had no such file, with no error or warning; only the deposit
preview complained later, about something else. A missing data file now raises
FileNotFoundError naming the path it resolved to, before any record is created.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import battinfo

SPEC = dict(manufacturer="Molicel", model="INR21700-P45B", format="cylindrical", chemistry="li-ion")
CSV = "test_time_second,voltage_volt\n0,3.6\n3600,2.5\n"


def test_getting_started_snippet_refuses_the_missing_file(tmp_path: Path) -> None:
    ws = battinfo.workspace(tmp_path, registry_url=None)
    ws.add("cell", spec=battinfo.CellSpec(**SPEC), serial_numbers=["S1"])
    with pytest.raises(FileNotFoundError) as excinfo:
        ws.add("test", type="cycling", cell="S1", data="bdf/S1.bdf.csv")
    message = str(excinfo.value)
    assert str(tmp_path.resolve() / "bdf" / "S1.bdf.csv") in message
    assert "workspace root" in message
    # Nothing was created: the save writes the spec and the cell only.
    assert ws._ws.tests == [] and ws._ws.datasets == []
    saved = ws.save()
    assert saved["tests"] == [] and saved["datasets"] == []


def test_relative_data_paths_resolve_against_the_workspace_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    (root / "bdf").mkdir(parents=True)
    (root / "bdf" / "S1.bdf.csv").write_text(CSV, encoding="utf-8")
    monkeypatch.chdir(tmp_path)  # the current directory is not the workspace root
    ws = battinfo.workspace("project", registry_url=None)
    ws.add("cell", spec=battinfo.CellSpec(**SPEC), serial_numbers=["S1"])
    tests = ws.add("test", type="cycling", cell="S1", data="bdf/S1.bdf.csv")
    assert len(tests) == 1 and len(ws._ws.datasets) == 1


def test_missing_raw_file_and_dataset_list_entries_are_refused(tmp_path: Path) -> None:
    (tmp_path / "bdf").mkdir()
    (tmp_path / "bdf" / "S1.bdf.csv").write_text(CSV, encoding="utf-8")
    ws = battinfo.workspace(tmp_path, registry_url=None)
    ws.add("cell", spec=battinfo.CellSpec(**SPEC), serial_numbers=["S1"])
    with pytest.raises(FileNotFoundError, match="raw= file not found"):
        ws.add("test", type="cycling", cell="S1", data="bdf/S1.bdf.csv", raw="raw/S1.ndax")
    with pytest.raises(FileNotFoundError, match="datasets= file not found"):
        ws.add("test", type="cycling", datasets=["bdf/S1.bdf.csv", "bdf/S2.bdf.csv"])
    assert ws._ws.tests == []


def test_add_docstring_states_the_path_rule() -> None:
    doc = battinfo.ws.AuthoringWorkspace.add.__doc__ or ""
    assert "relative path resolves against the workspace root" in doc
    assert "FileNotFoundError" in doc
    assert "resolves against the workspace root" in (battinfo.ws.AuthoringWorkspace.load.__doc__ or "")
