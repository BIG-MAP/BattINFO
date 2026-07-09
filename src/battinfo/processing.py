"""Timeseries processing pipeline for BattINFO ingest.

Converts a raw CSV to BDF format, generates a static PNG plot, and
generates a self-contained interactive HTML plot.  All outputs are
written to a caller-supplied scratch directory so the caller controls
where they land on disk before uploading.

Install dependencies with::

    pip install "battinfo[processing]"

which pulls in: batterydf, matplotlib, plotly.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NamedTuple

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _is_valid_png(path: Path) -> bool:
    """A non-empty file starting with the PNG signature — cheap content sanity so a stale or
    partially-written .png is regenerated rather than reused and published (C-4)."""
    try:
        with path.open("rb") as handle:
            return handle.read(len(_PNG_MAGIC)) == _PNG_MAGIC
    except OSError:
        return False


def _is_valid_plot_json(path: Path) -> bool:
    """Parseable JSON carrying a Plotly figure's ``data`` key — so a stale/garbage .plot.json is
    regenerated rather than reused and published (C-4)."""
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(obj, dict) and "data" in obj


class ProcessedTimeseries(NamedTuple):
    """Paths produced by :func:`process_timeseries_csv`.

    All paths are inside *work_dir* and exist on disk after the call.
    Fields that could not be produced are ``None``.
    """

    bdf_path: Path | None
    """BDF-normalised CSV (``*.bdf.csv``).  ``None`` if bdf is not installed
    or the file format is not recognised."""

    plot_png_path: Path | None
    """Static PNG plot (voltage + current vs time).  ``None`` if matplotlib
    is not installed or reading the BDF CSV failed."""

    plot_json_path: Path | None
    """Plotly figure JSON (``*.plot.json``).  Suitable for client-side rendering
    via ``Plotly.react(el, data, layout)``.  ``None`` if plotly is not installed
    or reading the BDF CSV failed."""


def process_timeseries_csv(
    csv_path: Path,
    work_dir: Path,
    *,
    title: str | None = None,
    xunit: str = "h",
    yunit: str = "V",
    yyunit: str = "mA",
) -> ProcessedTimeseries:
    """Convert *csv_path* and generate plots, writing outputs to *work_dir*.

    The source file is assumed to be a raw timeseries CSV that either:
    - is already in BDF format (recognised by ``bdf.detect``), or
    - contains BDF-compatible columns that ``bdf.read`` can normalise.

    Parameters
    ----------
    csv_path:
        Path to the raw CSV file.
    work_dir:
        Directory in which to write the output files.  Created if absent.
    title:
        Plot title.  Defaults to the CSV stem.
    xunit:
        X-axis unit for plots (default ``"h"`` — hours).
    yunit:
        Primary Y-axis unit (default ``"V"``).
    yyunit:
        Secondary Y-axis unit for current (default ``"mA"``).
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    stem = csv_path.stem.replace(".bdf", "")  # avoid double suffix
    plot_title = title or stem

    bdf_path = _convert_to_bdf(csv_path, work_dir, stem)
    source_for_plots = bdf_path if bdf_path is not None else csv_path

    plot_png_path = _make_static_plot(source_for_plots, work_dir, stem, plot_title, xunit, yunit, yyunit)
    plot_json_path = _make_interactive_plot(source_for_plots, work_dir, stem, plot_title, xunit, yunit, yyunit)

    return ProcessedTimeseries(
        bdf_path=bdf_path,
        plot_png_path=plot_png_path,
        plot_json_path=plot_json_path,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _read_bdf_pandas(source: Path, *, validate: bool = False):
    """Read a cycler file with ``bdf.read`` and return ``(pandas_df, metadata)``.

    batterydf >= 0.2 returns a ``(polars_frame, metadata)`` tuple; this helper
    collects to a pandas DataFrame because the downstream helpers we chain
    (``bdf.repair.fix_time``, ``bdf.io.save``, ``bdf.validate``) operate on
    pandas.  ``metadata`` carries at least a ``"source"`` key naming the
    resolved reader plugin — useful provenance for callers.

    ``tz="UTC"`` is passed explicitly: UTC timestamps are the ratified project
    policy.  Upstream cannot distinguish a deliberate UTC from its default and
    still emits a "tz defaulted to UTC" UserWarning for naive-datetime formats,
    so that specific warning is suppressed here.
    """
    import warnings as _warnings  # noqa: PLC0415

    import bdf  # noqa: PLC0415

    with _warnings.catch_warnings():
        _warnings.filterwarnings(
            "ignore", message="tz defaulted to UTC", category=UserWarning
        )
        frame, metadata = bdf.read(source, validate=validate, lazy=False, tz="UTC")
    return frame.to_pandas(), metadata


def _read_bdf_csv(path: Path):
    """Read a BDF CSV or Parquet file into a DataFrame, returning None on failure."""
    try:
        import pandas as pd
        if str(path).lower().endswith(".parquet"):
            return pd.read_parquet(path)
        return pd.read_csv(path)
    except Exception:
        return None


def _downsample(df: "Any", max_points: int | None):
    """Thin a DataFrame to at most *max_points* rows (evenly), for a light preview."""
    if max_points and len(df) > max_points:
        step = len(df) // max_points + 1
        return df.iloc[::step]
    return df


def generate_dataset_plots(
    data_path: Path,
    out_dir: Path,
    *,
    title: str | None = None,
    max_points: int = 4000,
    xunit: str = "h",
    yunit: str = "V",
    yyunit: str = "mA",
) -> tuple[Path | None, Path | None]:
    """Generate a downsampled interactive Plotly JSON + static PNG from a BDF file.

    Reads CSV or Parquet, thins to ``max_points`` for a lightweight web preview, and
    writes ``<stem>.plot.json`` (for ``role=plot_data``) and ``<stem>.png`` (for
    ``role=plot_static``) into *out_dir*. Returns ``(plot_json_path, plot_png_path)``;
    either may be ``None`` if the optional plotting deps are absent or the columns are
    not recognised.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = data_path.stem.replace(".bdf", "")
    plot_title = title or stem
    json_path = _make_interactive_plot(data_path, out_dir, stem, plot_title, xunit, yunit, yyunit, max_points=max_points)
    png_path = _make_static_plot(data_path, out_dir, stem, plot_title, xunit, yunit, yyunit, max_points=max_points)
    return json_path, png_path


def _convert_to_bdf(csv_path: Path, work_dir: Path, stem: str) -> Path | None:
    """Convert *csv_path* to BDF CSV; return output path or None."""
    try:
        from bdf.io import save as bdf_save
    except ImportError:
        return None

    out_path = work_dir / f"{stem}.bdf.csv"
    if out_path.exists():
        return out_path

    try:
        # Tolerant conversion: bdf.read auto-detects the format (raising if no
        # reader matches) and validate=False keeps partially-conformant files
        # convertible — the interop policy is "express what you can".
        df, _meta = _read_bdf_pandas(csv_path, validate=False)
        bdf_save(df, out_path, index=False)
        return out_path
    except Exception:
        return None


def _infer_test_type_from_df(df: "Any") -> str | None:
    """Infer BatteryTestType string from a BDF DataFrame's column names.

    Returns one of the standard test type strings, or ``None`` if no confident
    inference can be made.
    """
    cols = {c.lower() for c in df.columns}

    def _has(*keywords: str) -> bool:
        return any(any(kw in c for c in cols) for kw in keywords)

    # EIS: frequency axis + impedance (real/imaginary)
    if _has("freq") and (_has("re_z", "rez", "z_re", "real") or _has("im_z", "imz", "z_im", "imag")):
        return "eis"
    # Capacity check: short run with energy/capacity, no cycle index
    if _has("capacity", "charge_capacity", "discharge_capacity") and not _has("cycle_index", "cycle_number"):
        return "capacity_check"
    # Cycle life: cycle index column present
    if _has("cycle_index", "cycle_number", "cycle"):
        return "cycling"
    # HPPC: rest periods + pulses — heuristic via column names
    if _has("hppc", "pulse"):
        return "hppc"
    # ICI: internal resistance measurements
    if _has("ici", "internal_resistance", "dcir"):
        return "ici"
    # Rate capability: c_rate or multiple rates
    if _has("c_rate", "crate", "rate"):
        return "rate_capability"
    # Formation: first few cycles, often distinguished by file name elsewhere
    if _has("formation"):
        return "formation"

    return None


def convert_raw_to_bdf(raw_path: Path) -> tuple[Path | None, str | None]:
    """Convert any raw cycler file to a ``.bdf.parquet`` file next to the source.

    Uses ``bdf.read`` which handles CSV, NDA, NDAX, MPT, XLSX, and other formats
    supported by installed batterydf plugins.  Returns ``(parquet_path,
    inferred_test_type)`` on success, or ``(None, None)`` if batterydf is not
    installed or the file cannot be parsed.  Skips conversion if the
    ``.bdf.parquet`` already exists (test type re-inferred from the parquet).
    """
    try:
        from bdf.io import save as bdf_save
    except ImportError:
        return None, None

    stem = raw_path.stem
    if stem.endswith(".bdf"):
        stem = stem[:-4]
    out_path = raw_path.parent / f"{stem}.bdf.parquet"

    try:
        import contextlib as _cl
        import io as _io
        df = None
        if out_path.exists():
            import pandas as pd
            try:
                df = pd.read_parquet(out_path)
            except Exception:
                # A corrupt cached .bdf.parquet must not be swallowed into a "no deps" result
                # (which would leave the poison in place to fail every future run): drop it and
                # regenerate from the raw source (R-8).
                out_path.unlink(missing_ok=True)
                df = None
        if df is None:
            # Suppress any diagnostic prints from batterydf plugins
            with _cl.redirect_stdout(_io.StringIO()), _cl.redirect_stderr(_io.StringIO()):
                df, _meta = _read_bdf_pandas(raw_path, validate=False)
            bdf_save(df, out_path, index=False)
        return out_path, _infer_test_type_from_df(df)
    except Exception:
        return None, None


def _make_static_plot(
    source: Path,
    work_dir: Path,
    stem: str,
    title: str,
    xunit: str,
    yunit: str,
    yyunit: str,
    max_points: int | None = None,
) -> Path | None:
    """Generate a static PNG via bdf.plot; return output path or None."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend
        import bdf
    except ImportError:
        return None

    out_path = work_dir / f"{stem}.png"
    if out_path.exists() and _is_valid_png(out_path):
        return out_path  # reuse only a content-valid artifact; else fall through to regenerate

    df = _read_bdf_csv(source)
    if df is None:
        return None
    df = _downsample(df, max_points)

    voltage_col = next((c for c in df.columns if "voltage" in c.lower()), None)
    current_col = next((c for c in df.columns if "current" in c.lower()), None)
    time_col = next((c for c in df.columns if "time" in c.lower() and "unix" not in c.lower()), None)

    if voltage_col is None or time_col is None:
        return None
    if len(df) < 2 or df[voltage_col].dropna().empty:
        return None  # degenerate input (empty / single-row / all-NaN voltage) -> no real preview (C-5)

    try:
        bdf.plot(
            df,
            xdata=time_col,
            ydata=voltage_col,
            yydata=current_col,
            xunit=xunit,
            yunit=yunit,
            yyunit=yyunit if current_col else None,
            title=title,
            save=str(out_path),
            show=False,
        )
        import matplotlib.pyplot as plt
        plt.close("all")
        return out_path if out_path.exists() else None
    except Exception:
        import matplotlib.pyplot as plt
        plt.close("all")
        return None


def _make_interactive_plot(
    source: Path,
    work_dir: Path,
    stem: str,
    title: str,
    xunit: str,
    yunit: str,
    yyunit: str,
    max_points: int | None = None,
) -> Path | None:
    """Generate a Plotly figure JSON file for client-side rendering.

    The JSON file contains the serialised Plotly figure (data + layout) and can
    be rendered in a browser via ``Plotly.react(el, fig.data, fig.layout)``.
    Storing JSON rather than a self-contained HTML file avoids the content-type
    and download-forcing behaviour of R2 public CDN URLs for HTML.
    """
    try:
        import bdf
        import plotly  # noqa: F401
    except ImportError:
        return None

    out_path = work_dir / f"{stem}.plot.json"
    if out_path.exists() and _is_valid_plot_json(out_path):
        return out_path  # reuse only a content-valid artifact; else fall through to regenerate

    df = _read_bdf_csv(source)
    if df is None:
        return None
    df = _downsample(df, max_points)

    voltage_col = next((c for c in df.columns if "voltage" in c.lower()), None)
    current_col = next((c for c in df.columns if "current" in c.lower()), None)
    time_col = next((c for c in df.columns if "time" in c.lower() and "unix" not in c.lower()), None)

    if voltage_col is None or time_col is None:
        return None
    if len(df) < 2 or df[voltage_col].dropna().empty:
        return None  # degenerate input (empty / single-row / all-NaN voltage) -> no real preview (C-5)

    try:
        fig = bdf.explore(
            df,
            xdata=time_col,
            ydata=voltage_col,
            yydata=current_col,
            xunit=xunit,
            yunit=yunit,
            yyunit=yyunit if current_col else None,
            backend="plotly",
            title=title,
        )
        out_path.write_text(fig.to_json(), encoding="utf-8")
        return out_path if out_path.exists() else None
    except Exception:
        return None
