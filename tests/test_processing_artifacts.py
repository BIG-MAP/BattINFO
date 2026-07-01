"""C-4/C-5/R-8: processing must not reuse stale/garbage plot artifacts, must not produce a
"successful" preview from degenerate input, and must not swallow (and leave) a corrupt parquet
cache. The plotting/bdf extras are assumed installed (they are in CI)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.processing import (
    _is_valid_plot_json,
    _is_valid_png,
    _make_interactive_plot,
    _make_static_plot,
    convert_raw_to_bdf,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def test_is_valid_png(tmp_path: Path) -> None:
    (tmp_path / "g.png").write_bytes(_PNG)
    (tmp_path / "b.png").write_bytes(b"not a png")
    assert _is_valid_png(tmp_path / "g.png") is True
    assert _is_valid_png(tmp_path / "b.png") is False
    assert _is_valid_png(tmp_path / "missing.png") is False


def test_is_valid_plot_json(tmp_path: Path) -> None:
    (tmp_path / "g.plot.json").write_text('{"data": [], "layout": {}}', encoding="utf-8")
    (tmp_path / "b.plot.json").write_text("{ not json", encoding="utf-8")
    (tmp_path / "n.plot.json").write_text('{"layout": {}}', encoding="utf-8")  # no "data"
    assert _is_valid_plot_json(tmp_path / "g.plot.json") is True
    assert _is_valid_plot_json(tmp_path / "b.plot.json") is False
    assert _is_valid_plot_json(tmp_path / "n.plot.json") is False


def test_static_plot_does_not_reuse_garbage_png(tmp_path: Path) -> None:
    # C-4: a stale/garbage .png must not be returned as "success" (it would be hashed + published).
    (tmp_path / "s.png").write_bytes(b"not a real png")
    result = _make_static_plot(tmp_path / "missing.csv", tmp_path, "s", "t", "s", "V", "A")
    assert result is None  # garbage NOT returned; regeneration impossible -> None


def test_interactive_plot_does_not_reuse_garbage_json(tmp_path: Path) -> None:
    (tmp_path / "s.plot.json").write_text("{ garbage", encoding="utf-8")
    result = _make_interactive_plot(tmp_path / "missing.csv", tmp_path, "s", "t", "s", "V", "A")
    assert result is None


def test_static_plot_rejects_degenerate_input(tmp_path: Path) -> None:
    # C-5: a single-row (no-curve) CSV must not yield a "successful" blank preview.
    (tmp_path / "one.csv").write_text("time,voltage\n0,3.7\n", encoding="utf-8")
    result = _make_static_plot(tmp_path / "one.csv", tmp_path, "one", "t", "s", "V", "A")
    assert result is None


def test_convert_drops_corrupt_parquet_cache(tmp_path: Path) -> None:
    # R-8: a corrupt cached .bdf.parquet must not be swallowed into a no-deps result and LEFT to
    # poison every future run — it is dropped (and regenerated if possible).
    (tmp_path / "data.csv").write_text("time,voltage\n0,3.7\n1,3.6\n", encoding="utf-8")
    cache = tmp_path / "data.bdf.parquet"
    cache.write_bytes(b"not a parquet file")
    convert_raw_to_bdf(tmp_path / "data.csv")
    assert (not cache.exists()) or cache.read_bytes()[:4] == b"PAR1"  # corrupt cache not left
