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

from pathlib import Path
from typing import NamedTuple


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

    plot_html_path: Path | None
    """Self-contained interactive HTML (Plotly).  ``None`` if plotly is not
    installed or reading the BDF CSV failed."""


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
    plot_html_path = _make_interactive_plot(source_for_plots, work_dir, stem, plot_title, xunit, yunit, yyunit)

    return ProcessedTimeseries(
        bdf_path=bdf_path,
        plot_png_path=plot_png_path,
        plot_html_path=plot_html_path,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _read_bdf_csv(path: Path):
    """Read a BDF CSV into a DataFrame, returning None on failure."""
    try:
        import pandas as pd
        df = pd.read_csv(path)
        return df
    except Exception:
        return None


def _convert_to_bdf(csv_path: Path, work_dir: Path, stem: str) -> Path | None:
    """Convert *csv_path* to BDF CSV; return output path or None."""
    try:
        import bdf
        from bdf.io import save as bdf_save
    except ImportError:
        return None

    out_path = work_dir / f"{stem}.bdf.csv"
    if out_path.exists():
        return out_path

    try:
        sniff = bdf.detect(csv_path)
        if sniff.id == "abstract" or sniff.confidence <= 0:
            # Already-BDF or unrecognised — try reading directly
            df = bdf.read(csv_path, validate=False)
        else:
            df = bdf.read(csv_path, validate=True)
        bdf_save(df, out_path, index=False)
        return out_path
    except Exception:
        return None


def _make_static_plot(
    source: Path,
    work_dir: Path,
    stem: str,
    title: str,
    xunit: str,
    yunit: str,
    yyunit: str,
) -> Path | None:
    """Generate a static PNG via bdf.plot; return output path or None."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend
        import bdf
    except ImportError:
        return None

    out_path = work_dir / f"{stem}.png"
    if out_path.exists():
        return out_path

    df = _read_bdf_csv(source)
    if df is None:
        return None

    voltage_col = next((c for c in df.columns if "voltage" in c.lower()), None)
    current_col = next((c for c in df.columns if "current" in c.lower()), None)
    time_col = next((c for c in df.columns if "time" in c.lower() and "unix" not in c.lower()), None)

    if voltage_col is None or time_col is None:
        return None

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
) -> Path | None:
    """Generate a self-contained interactive HTML via bdf.explore (plotly)."""
    try:
        import plotly  # noqa: F401
        import bdf
    except ImportError:
        return None

    out_path = work_dir / f"{stem}.html"
    if out_path.exists():
        return out_path

    df = _read_bdf_csv(source)
    if df is None:
        return None

    voltage_col = next((c for c in df.columns if "voltage" in c.lower()), None)
    current_col = next((c for c in df.columns if "current" in c.lower()), None)
    time_col = next((c for c in df.columns if "time" in c.lower() and "unix" not in c.lower()), None)

    if voltage_col is None or time_col is None:
        return None

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
        fig.write_html(str(out_path), include_plotlyjs="cdn", full_html=True)
        return out_path if out_path.exists() else None
    except Exception:
        return None
