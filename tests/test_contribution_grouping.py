"""D-7: _group_files_by_cell must not silently collapse ungroupable multi-file folders into one
synthetic cell (which mis-attributes every file); it raises unless the caller confirms n_cells=1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.contribution import _group_files_by_cell


def _touch(folder: Path, *names: str) -> None:
    for name in names:
        (folder / name).write_text("x", encoding="utf-8")


def test_group_single_file_is_one_cell(tmp_path: Path) -> None:
    _touch(tmp_path, "run.csv")
    assert list(_group_files_by_cell(tmp_path)) == ["1"]


def test_group_detects_distinct_cells(tmp_path: Path) -> None:
    _touch(tmp_path, "cell_1.csv", "cell_2.csv")
    assert set(_group_files_by_cell(tmp_path)) == {"1", "2"}


def test_group_ungroupable_multi_file_raises(tmp_path: Path) -> None:
    _touch(tmp_path, "alpha.csv", "beta.csv")  # no distinguishing numeric token
    with pytest.raises(ValueError, match="Could not detect a cell grouping"):
        _group_files_by_cell(tmp_path)


def test_group_ungroupable_collapses_only_when_n_cells_is_one(tmp_path: Path) -> None:
    _touch(tmp_path, "alpha.csv", "beta.csv")
    groups = _group_files_by_cell(tmp_path, n_cells=1)
    assert list(groups) == ["1"] and len(groups["1"]) == 2
