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
from typing import Any, NamedTuple


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
            df = bdf.read(csv_path, validate=False)
        else:
            df = bdf.read(csv_path, validate=True)
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
        import bdf
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
        if out_path.exists():
            import pandas as pd
            df = pd.read_parquet(out_path)
        else:
            # Suppress any diagnostic prints from batterydf plugins
            with _cl.redirect_stdout(_io.StringIO()), _cl.redirect_stderr(_io.StringIO()):
                df = bdf.read(raw_path, validate=False)
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
    if out_path.exists():
        return out_path

    df = _read_bdf_csv(source)
    if df is None:
        return None
    df = _downsample(df, max_points)

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
    if out_path.exists():
        return out_path

    df = _read_bdf_csv(source)
    if df is None:
        return None
    df = _downsample(df, max_points)

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
        out_path.write_text(fig.to_json(), encoding="utf-8")
        return out_path if out_path.exists() else None
    except Exception:
        return None
