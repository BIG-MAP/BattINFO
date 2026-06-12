"""Bridge between the BDF (Battery Data Format) library and BattINFO records.

Converts a BDF-normalised DataFrame or CSV file into a pair of BattINFO
staging records (test + optional dataset) ready for workspace ingest or
direct use in the legacy data handoff pipeline.

No IRI minting happens here.  Test/dataset ``id`` fields are omitted so
that downstream tooling (the ingest engine or a curator) mints canonical
``w3id.org`` identifiers at publish time.

Install the BDF library with::

    pip install batterydf
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCHEMA_VERSION = "0.1.0"
PathLike = str | Path

# BDF canonical column name → (variable_measured name, unit_text)
_BDF_VARIABLE_MAP: dict[str, tuple[str, str]] = {
    "test_time_second":              ("test_time",              "s"),
    "unix_time_second":              ("time",                   "s"),
    "voltage_volt":                  ("voltage",                "V"),
    "current_ampere":                ("current",                "A"),
    "cycle_count":                   ("cycle_index",            ""),
    "step_count":                    ("step_index",             ""),
    "step_index":                    ("step_index",             ""),
    "ambient_temperature_celsius":   ("temperature",            "°C"),
    "charging_capacity_ah":          ("charging_capacity",      "Ah"),
    "discharging_capacity_ah":       ("discharging_capacity",   "Ah"),
    "step_capacity_ah":              ("step_capacity",          "Ah"),
    "net_capacity_ah":               ("net_capacity",           "Ah"),
    "cumulative_capacity_ah":        ("cumulative_capacity",    "Ah"),
    "charging_energy_wh":            ("charging_energy",        "Wh"),
    "discharging_energy_wh":         ("discharging_energy",     "Wh"),
    "step_energy_wh":                ("step_energy",            "Wh"),
    "net_energy_wh":                 ("net_energy",             "Wh"),
    "cumulative_energy_wh":          ("cumulative_energy",      "Wh"),
    "power_watt":                    ("power",                  "W"),
    "internal_resistance_ohm":       ("internal_resistance",    "Ω"),
    "temperature_t1_celsius":        ("temperature_t1",         "°C"),
    "temperature_t2_celsius":        ("temperature_t2",         "°C"),
    "temperature_t3_celsius":        ("temperature_t3",         "°C"),
    "temperature_t4_celsius":        ("temperature_t4",         "°C"),
    "temperature_t5_celsius":        ("temperature_t5",         "°C"),
}

# bdf.read() returns human-readable "Name / unit" column headers.
# This maps the lowercased, space→underscore name part to battinfo variable names.
_BDF_HUMAN_NAME_MAP: dict[str, str] = {
    "voltage":                  "voltage",
    "current":                  "current",
    "test_time":                "test_time",
    "unix_time":                "time",
    "cycle_count":              "cycle_index",
    "cycle_index":              "cycle_index",
    "step_count":               "step_index",
    "step_index":               "step_index",
    "ambient_temperature":      "temperature",
    "charging_capacity":        "charging_capacity",
    "discharging_capacity":     "discharging_capacity",
    "step_capacity":            "step_capacity",
    "net_capacity":             "net_capacity",
    "cumulative_capacity":      "cumulative_capacity",
    "charging_energy":          "charging_energy",
    "discharging_energy":       "discharging_energy",
    "step_energy":              "step_energy",
    "net_energy":               "net_energy",
    "cumulative_energy":        "cumulative_energy",
    "power":                    "power",
    "internal_resistance":      "internal_resistance",
    "temperature_t1":           "temperature_t1",
    "temperature_t2":           "temperature_t2",
    "temperature_t3":           "temperature_t3",
    "temperature_t4":           "temperature_t4",
    "temperature_t5":           "temperature_t5",
}


@dataclass
class BattdatImportResult:
    """Result of :func:`from_battdat`.

    Attributes
    ----------
    test_record:
        BattINFO test record dict.  No ``id`` field — IRI minted downstream.
    dataset_record:
        BattINFO dataset record dict, or ``None`` if *source* was a DataFrame
        with no associated file path.
    inferred_kind:
        Test kind inferred from BDF column names, or ``None`` if inference
        was not possible and no explicit *kind* was given.
    warnings:
        Non-fatal notes about what could not be determined.
    """

    test_record: dict[str, Any]
    dataset_record: dict[str, Any] | None
    inferred_kind: str | None
    warnings: list[str] = field(default_factory=list)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _read_df(source: Any, warnings: list[str]) -> tuple[Any, Path | None]:
    """Return (DataFrame, source_path_or_None).  Tries bdf.read then pandas fallback."""
    try:
        import pandas as pd  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "from_battdat() requires pandas: pip install pandas"
        ) from exc

    if isinstance(source, pd.DataFrame):
        return source, None

    path = Path(source)
    # Try BDF-aware reader first
    try:
        import bdf as _bdf  # noqa: PLC0415
        df = _bdf.read(path, validate=False)
        return df, path
    except ImportError:
        warnings.append(
            "batterydf is not installed; reading CSV with pandas.read_csv() without "
            "BDF normalisation.  Install with: pip install batterydf"
        )
    except Exception as exc:
        warnings.append(
            f"bdf.read() failed ({exc}); falling back to pandas.read_csv()."
        )

    df = pd.read_csv(path)
    return df, path


def _infer_kind(df: Any) -> str | None:
    """Infer BattINFO test kind from BDF DataFrame column names."""
    from battinfo.processing import _infer_test_type_from_df  # noqa: PLC0415
    return _infer_test_type_from_df(df)


def _extract_timestamps(df: Any) -> tuple[int | None, int | None]:
    """Return (started_at, ended_at) Unix timestamps from unix_time_second column.

    Handles both canonical BDF column names (``unix_time_second``) and the
    human-readable form produced by ``bdf.read()`` (``Unix Time / s``).
    """
    # Canonical form (DataFrame passed directly or pandas fallback)
    for candidate in ("unix_time_second", "Unix Time / s"):
        if candidate in df.columns:
            col = df[candidate].dropna()
            if not col.empty:
                return int(col.iloc[0]), int(col.iloc[-1])
    return None, None


def _to_variable_measured(df: Any) -> list[dict[str, Any]]:
    """Return a variable_measured list for the known BDF columns present in *df*.

    Handles both canonical BDF column names (``voltage_volt``) and the
    human-readable ``"Name / unit"`` form produced by ``bdf.read()``.
    """
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for col in df.columns:
        # Canonical BDF names (direct DataFrame input or pandas fallback)
        entry = _BDF_VARIABLE_MAP.get(col)
        if entry is not None:
            name, unit_text = entry
            if name not in seen:
                seen.add(name)
                item: dict[str, Any] = {"name": name}
                if unit_text:
                    item["unit_text"] = unit_text
                result.append(item)
            continue

        # Human-readable "Name / unit" form from bdf.read()
        if " / " in col:
            name_raw, unit_raw = col.rsplit(" / ", 1)
            name_norm = name_raw.strip().lower().replace(" ", "_")
            unit_text = unit_raw.strip() if unit_raw.strip() not in ("1", "") else ""
            canonical = _BDF_HUMAN_NAME_MAP.get(name_norm, name_norm)
            if canonical not in seen:
                seen.add(canonical)
                item = {"name": canonical}
                if unit_text:
                    item["unit_text"] = unit_text
                result.append(item)

    return result


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _infer_technique(kind: str | None) -> list[str]:
    """Map test kind to measurement_techniques strings."""
    if kind is None:
        return []
    _MAP = {
        "cycling":          "galvanostatic cycling",
        "capacity_check":   "galvanostatic capacity check",
        "rate_capability":  "rate capability",
        "eis":              "electrochemical impedance spectroscopy",
        "hppc":             "HPPC",
        "ici":              "incremental capacity analysis",
        "gitt":             "GITT",
        "dcir":             "DCIR",
        "quasi_ocv":        "quasi-OCV",
        "formation":        "formation cycling",
        "calendar_ageing":  "calendar ageing",
    }
    label = _MAP.get(kind)
    return [label] if label is not None else [kind]


# ── Public API ────────────────────────────────────────────────────────────────


def from_battdat(
    source: Any,
    *,
    cell_id: str,
    kind: str | None = None,
    name: str | None = None,
    instrument: str | None = None,
    license: str | None = None,
    access_url: str | None = None,
    download_url: str | None = None,
    started_at: int | str | None = None,
    ended_at: int | str | None = None,
    source_type: str = "measurement",
    source_file: str | None = None,
    source_url: str | None = None,
) -> BattdatImportResult:
    """Convert a BDF-normalised DataFrame or CSV file to BattINFO staging records.

    Parameters
    ----------
    source:
        A ``pandas.DataFrame`` already in BDF canonical form, or a path to a
        BDF-normalised CSV file.  When a path is given, ``batterydf`` is used
        to read and normalise the file; ``pandas.read_csv`` is the fallback.
    cell_id:
        The BattINFO cell-instance identifier (``https://w3id.org/battinfo/cell/…``
        or a staging placeholder such as ``urn:staging:a123--cell-07``).
    kind:
        Test kind (e.g. ``"cycling"``, ``"eis"``).  Inferred from BDF column
        names when omitted.
    name:
        Human-readable test name.  Defaults to ``"<cell_id> <kind> test"``.
    instrument:
        Cycler instrument name.
    license:
        Dataset license URI (e.g. ``"https://creativecommons.org/licenses/by/4.0/"``).
    access_url:
        URL where the dataset is accessible.  Defaults to the local file URI
        when *source* is a path.
    download_url:
        Direct download URL.
    started_at, ended_at:
        Unix timestamps.  Extracted from the ``unix_time_second`` BDF column
        when omitted.
    source_type:
        Provenance source type (default ``"measurement"``).
    source_file, source_url:
        Provenance file name and URL.

    Returns
    -------
    BattdatImportResult
        Contains ``test_record``, ``dataset_record`` (when *source* is a path),
        ``inferred_kind``, and ``warnings``.
    """
    warnings: list[str] = []

    df, source_path = _read_df(source, warnings)

    inferred_kind = _infer_kind(df)
    resolved_kind = kind or inferred_kind
    if resolved_kind is None:
        warnings.append(
            "Test kind could not be inferred from BDF column names; "
            "set kind= explicitly if you know the test type."
        )

    auto_started, auto_ended = _extract_timestamps(df)
    resolved_started_at = started_at if started_at is not None else auto_started
    resolved_ended_at = ended_at if ended_at is not None else auto_ended

    resolved_source_file = source_file or (source_path.name if source_path is not None else None)
    resolved_name = name or (
        f"{cell_id.rsplit('/', 1)[-1]} {resolved_kind or 'test'} test"
    )

    # ── Test record ───────────────────────────────────────────────────────────
    test_inner: dict[str, Any] = {
        "cell_id": cell_id,
        "kind": resolved_kind or "other",
        "name": resolved_name,
        "status": "completed",
    }
    if resolved_started_at is not None:
        test_inner["started_at"] = int(resolved_started_at)
    if resolved_ended_at is not None:
        test_inner["ended_at"] = int(resolved_ended_at)
    if instrument is not None:
        test_inner["instrument_name"] = instrument

    provenance: dict[str, Any] = {"source_type": source_type}
    if resolved_source_file is not None:
        provenance["source_file"] = resolved_source_file
    if source_url is not None:
        provenance["source_url"] = source_url

    test_record: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "test": test_inner,
        "provenance": provenance,
    }

    # ── Dataset record (only when source is a file) ───────────────────────────
    dataset_record: dict[str, Any] | None = None
    if source_path is not None:
        resolved_access_url = access_url or source_path.resolve().as_uri()
        variable_measured = _to_variable_measured(df)
        techniques = _infer_technique(resolved_kind)

        checksum_value = _sha256(source_path) if source_path.exists() else None

        distribution: dict[str, Any] = {
            "type": "DataDownload",
            "content_url": download_url or resolved_access_url,
            "encoding_format": "text/csv",
        }
        if checksum_value is not None:
            distribution["checksum"] = {"algorithm": "sha256", "value": checksum_value}

        dataset_inner: dict[str, Any] = {
            "name": f"{resolved_name} data",
            "about": [cell_id],
            "access_url": resolved_access_url,
            "distributions": [distribution],
        }
        if techniques:
            dataset_inner["measurement_techniques"] = techniques
        if variable_measured:
            dataset_inner["variable_measured"] = variable_measured
        if license is not None:
            dataset_inner["license"] = license
        if download_url is not None:
            dataset_inner["download_url"] = download_url

        dataset_record = {
            "schema_version": _SCHEMA_VERSION,
            "dataset": dataset_inner,
            "provenance": dict(provenance),
        }

    return BattdatImportResult(
        test_record=test_record,
        dataset_record=dataset_record,
        inferred_kind=inferred_kind,
        warnings=warnings,
    )
