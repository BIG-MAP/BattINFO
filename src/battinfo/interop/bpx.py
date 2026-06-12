"""Import battery parameters from a BPX file into BattINFO cell-type specs.

BPX (Battery Parameter eXchange) is a JSON format developed by the PyBaMM
project for sharing battery physics parameters.  This module extracts the
subset of BPX parameters that correspond to cell-type specification properties
in BattINFO (capacity, voltage limits, mass, dimensions) and converts them to
BattINFO's ``{value, unit}`` quantity format.

The remaining BPX parameters (electrode microstructure, transport coefficients,
OCP functions, etc.) have no direct BattINFO spec equivalent and are silently
skipped with a note in ``warnings``.

References
----------
- BPX spec: https://github.com/pybamm-team/BPX
- BPX Python library (optional): ``pip install bpx``
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

PathLike = str | Path

# BPX "Parameterisation.Cell" key → (battinfo_spec_key, unit, scale_to_unit)
# scale_to_unit: multiply the BPX value by this factor to get the battinfo unit
_BPX_CELL_MAP: dict[str, tuple[str, str, float]] = {
    "Nominal cell capacity [A.h]":        ("nominal_capacity",           "Ah",   1.0),
    "Nominal cell energy [W.h]":          ("nominal_energy",             "Wh",   1.0),
    "Nominal cell voltage [V]":           ("nominal_voltage",            "V",    1.0),
    "Upper voltage cut-off [V]":          ("charging_cutoff_voltage",    "V",    1.0),
    "Lower voltage cut-off [V]":          ("discharging_cutoff_voltage", "V",    1.0),
    "Cell mass [kg]":                     ("mass",                       "g",    1000.0),
    "Cell diameter [m]":                  ("diameter",                   "mm",   1000.0),
    "Cell height [m]":                    ("height",                     "mm",   1000.0),
    "Electrode height [m]":               ("height",                     "mm",   1000.0),
    "Electrode width [m]":                ("width",                      "mm",   1000.0),
    "Cell thickness [m]":                 ("thickness",                  "mm",   1000.0),
    "Nominal cell resistance [Ohm]":      ("internal_resistance",        "Ω",    1.0),
    "Specific heat capacity [J.K-1.kg-1]": None,   # no battinfo spec equivalent
    "Thermal conductivity [W.m-1.K-1]":   None,
    "Cell volume [m3]":                   None,
    "Initial temperature [K]":            None,
    "Ambient temperature [K]":            None,
    "Number of electrode pairs connected in parallel to make a cell": None,
    "External temperature [K]":           None,
}

# Fields in Positive/Negative electrode blocks that hint at the electrode basis
_ELECTRODE_MATERIAL_KEYS = (
    "Positive electrode active material volume fraction",
    "Positive electrode OCP [V]",
    "Negative electrode active material volume fraction",
    "Negative electrode OCP [V]",
)


@dataclass
class BpxImportResult:
    """Result of :func:`from_bpx`.

    Attributes
    ----------
    specs:
        Dict of BattINFO spec-property key → ``{"value": ..., "unit": ...}``
        objects for all BPX parameters that have a direct BattINFO equivalent.
    title:
        ``Header.Title`` from the BPX file, or ``None``.
    bpx_version:
        ``Header.BPX`` version string, or ``None``.
    model_type:
        ``Header.Model`` string (e.g. ``"SPMe"``, ``"DFN"``), or ``None``.
    description:
        ``Header.Description``, or ``None``.
    source_file:
        Filename of the BPX source (when loaded from a path).
    warnings:
        Non-fatal notes about unmapped BPX fields or missing data.
    """

    specs: dict[str, Any]
    title: str | None
    bpx_version: str | None
    model_type: str | None
    description: str | None
    source_file: str | None
    warnings: list[str] = field(default_factory=list)

    def to_cell_type_kwargs(self) -> dict[str, Any]:
        """Return kwargs suitable for ``Workspace.cell_type(specs=..., name=...)``.

        The caller is responsible for providing ``manufacturer``, ``model``,
        ``format``, and ``chemistry`` — BPX does not carry those fields.
        """
        kwargs: dict[str, Any] = {"specs": dict(self.specs)}
        if self.title is not None:
            kwargs["name"] = self.title
        return kwargs


# ── Internal helpers ──────────────────────────────────────────────────────────


def _load_bpx(source: Mapping[str, Any] | str | Path) -> tuple[dict[str, Any], str]:
    """Load a BPX source (dict, JSON string, or path) and return (data, filename)."""
    if isinstance(source, Mapping):
        return dict(source), "bpx-parameter.json"
    path = Path(source)
    data = json.loads(path.read_text(encoding="utf-8"))
    return data, path.name


def _extract_header(data: dict[str, Any]) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (title, bpx_version, model_type, description) from the BPX Header."""
    header = data.get("Header") or data.get("header") or {}
    if not isinstance(header, Mapping):
        return None, None, None, None
    title = header.get("Title") or header.get("title")
    version = header.get("BPX") or header.get("bpx")
    model = header.get("Model") or header.get("model")
    desc = header.get("Description") or header.get("description")
    return (
        str(title) if title is not None else None,
        str(version) if version is not None else None,
        str(model) if model is not None else None,
        str(desc) if desc is not None else None,
    )


def _extract_specs(
    cell_params: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    """Map BPX Cell parameters to BattINFO spec-property dicts."""
    specs: dict[str, Any] = {}
    unmapped: list[str] = []

    for bpx_key, raw_value in cell_params.items():
        mapping = _BPX_CELL_MAP.get(bpx_key)
        if mapping is None:
            # Key not in our table at all — unknown parameter
            unmapped.append(bpx_key)
            continue
        if mapping is None:
            # Explicitly mapped to None — known but no battinfo equivalent
            continue
        battinfo_key, unit, scale = mapping
        if not isinstance(raw_value, (int, float)):
            warnings.append(
                f"BPX field '{bpx_key}' has non-numeric value {raw_value!r}; skipped."
            )
            continue
        value = float(raw_value) * scale
        # Round to 6 significant figures to avoid float noise from scaling
        if scale != 1.0:
            value = float(f"{value:.6g}")
        # Don't overwrite an already-extracted entry with a less-specific alias
        # (e.g. "Electrode height [m]" vs "Cell height [m]")
        if battinfo_key not in specs:
            specs[battinfo_key] = {"value": value, "unit": unit}

    if unmapped:
        warnings.append(
            f"BPX Cell parameters with no BattINFO spec equivalent "
            f"(physics/transport parameters — not cell-level specs): "
            f"{', '.join(unmapped[:8])}"
            + (" …" if len(unmapped) > 8 else "")
        )
    return specs


# ── Public API ────────────────────────────────────────────────────────────────


def from_bpx(
    source: Mapping[str, Any] | str | Path,
    *,
    extra_warnings: bool = True,
) -> BpxImportResult:
    """Import cell-type specs from a BPX battery parameter file.

    Extracts the subset of BPX ``Parameterisation.Cell`` parameters that map
    directly to BattINFO cell-type spec properties (capacity, voltage limits,
    mass, dimensions).  Physics parameters (microstructure, transport,
    electrochemical kinetics) are logged as warnings and skipped.

    Parameters
    ----------
    source:
        Path to a BPX JSON file, a JSON-string, or an already-parsed dict.
    extra_warnings:
        When ``True`` (default), append a warning listing BPX physics
        parameters that were skipped.  Set ``False`` to suppress.

    Returns
    -------
    BpxImportResult
        Contains ``specs`` ready for ``Workspace.cell_type(specs=...)``,
        along with title, version, and any warnings.

    Examples
    --------
    >>> result = from_bpx("mohtat2021.json")
    >>> ws.cell_type(
    ...     manufacturer="Custom",
    ...     model=result.title or "BPX cell",
    ...     format="cylindrical",
    ...     chemistry="Li-ion",
    ...     specs=result.specs,
    ... )
    """
    warnings: list[str] = []
    data, source_file = _load_bpx(source)

    title, bpx_version, model_type, description = _extract_header(data)

    # Navigate to Parameterisation block (case-insensitive key search)
    params_raw = (
        data.get("Parameterisation")
        or data.get("parameterisation")
        or data.get("parameters")
        or {}
    )
    if not isinstance(params_raw, Mapping) or not params_raw:
        warnings.append("BPX file has no 'Parameterisation' block; no specs extracted.")
        return BpxImportResult(
            specs={},
            title=title,
            bpx_version=bpx_version,
            model_type=model_type,
            description=description,
            source_file=source_file,
            warnings=warnings,
        )

    cell_params_raw = (
        params_raw.get("Cell")
        or params_raw.get("cell")
        or {}
    )
    if not isinstance(cell_params_raw, Mapping):
        warnings.append(
            "BPX 'Parameterisation.Cell' block is missing or not a mapping; "
            "no cell-level specs extracted."
        )
        cell_params: dict[str, Any] = {}
    else:
        cell_params = dict(cell_params_raw)

    specs = _extract_specs(cell_params, warnings if extra_warnings else [])

    if not specs:
        warnings.append(
            "No BattINFO-mappable specs found in BPX Cell parameters.  "
            "The file may use non-standard field names — check _BPX_CELL_MAP."
        )

    return BpxImportResult(
        specs=specs,
        title=title,
        bpx_version=bpx_version,
        model_type=model_type,
        description=description,
        source_file=source_file,
        warnings=warnings,
    )
