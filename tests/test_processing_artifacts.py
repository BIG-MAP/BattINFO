"""C-4/C-5/R-8: processing must not reuse stale/garbage plot artifacts, must not produce a
"successful" preview from degenerate input, and must not swallow (and leave) a corrupt parquet
cache. The plotting/bdf extras are assumed installed (they are in CI)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.processing import (
    _is_valid_plot_json,
    _is_valid_png,
    _make_interactive_plot,
    _make_static_plot,
    convert_raw_to_bdf,
    process_timeseries_csv,
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


# A cycler export batterydf recognises: BDF machine column names, with a cycle
# counter so the test type can be inferred from the columns.
_BDF_CSV = (
    "test_time_second,voltage_volt,current_ampere,cycle_count\n"
    "0,3.0,0.1,1\n1,3.1,0.1,1\n2,3.2,0.1,1\n3,3.3,-0.1,2\n4,3.2,-0.1,2\n"
)


def test_convert_raw_to_bdf_writes_the_parquet_and_infers_the_test_type(tmp_path: Path) -> None:
    # This goes through batterydf's own save, with no stand-in: batterydf 0.2
    # hands extra keywords to the polars writer, which rejected the pandas-style
    # index=False, and the error was swallowed, so nothing was ever written.
    pytest.importorskip("bdf")
    raw = tmp_path / "run.csv"
    raw.write_text(_BDF_CSV, encoding="utf-8")

    out_path, test_type = convert_raw_to_bdf(raw)

    assert out_path == tmp_path / "run.bdf.parquet"
    assert out_path.read_bytes()[:4] == b"PAR1"
    assert test_type == "cycling"
    import pandas as pd

    frame = pd.read_parquet(out_path)
    assert list(frame.columns) == ["test_time_second", "voltage_volt", "current_ampere", "cycle_count"]
    assert len(frame) == 5
    # A second run reads the cached parquet and infers the same type.
    assert convert_raw_to_bdf(raw) == (out_path, "cycling")


def test_process_timeseries_csv_writes_the_bdf_csv(tmp_path: Path) -> None:
    pytest.importorskip("bdf")
    raw = tmp_path / "run.csv"
    raw.write_text(_BDF_CSV, encoding="utf-8")

    result = process_timeseries_csv(raw, tmp_path / "work")

    assert result.bdf_path == tmp_path / "work" / "run.bdf.csv"
    lines = result.bdf_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "test_time_second,voltage_volt,current_ampere,cycle_count"
    assert len(lines) == 6


def test_dataset_process_converts_the_data_and_infers_the_test_type(tmp_path: Path, monkeypatch) -> None:
    # The same path end to end, as `battinfo dataset process` runs it. The file
    # name carries no test type, so the type has to come from the BDF columns.
    pytest.importorskip("bdf")
    from battinfo.contribution import init_batch, process_contribution

    monkeypatch.chdir(tmp_path)
    batch = init_batch(tmp_path / "batch", "Energizer CR2032", 1, lab="SINTEF")
    cell = tmp_path / "batch" / batch["cells"][0]["folder"]
    (cell / "run.csv").write_text(_BDF_CSV, encoding="utf-8")

    result = process_contribution(cell, bundle=False)

    assert result["errors"] == []
    assert result["conversions"] == {"run.csv": str(cell / "run.bdf.parquet")}
    assert result["bdf_test_types"] == {"run.csv": "cycling"}
    assert (cell / "run.bdf.parquet").read_bytes()[:4] == b"PAR1"
