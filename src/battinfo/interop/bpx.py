"""BPX files in and out of BattINFO.

BPX (Battery Parameter eXchange) is a JSON format developed by the PyBaMM
project for sharing battery physics parameters. One BPX file becomes one
parameter-set record (:func:`from_bpx_parameters`, then
:meth:`BpxParameterImportResult.to_parameter_set`): every value in the file is
a claim in a part (cell, each electrode's material and build, separator,
electrolyte, state), the ``User-defined`` block rides the record verbatim, and
anything else is named in a warning and listed in the record's
``not_imported``. The record's IRI derives from the file's parameters, it
links the cell the file describes (or says it is a virtual cell), and it
carries the file itself. :func:`to_bpx` rebuilds the BPX document from such a
record. Files are parsed strictly (:func:`battinfo._jcs.loads`), and the
v0.x-to-v1 layout conversion is :mod:`battinfo._bpx_layout`, which the
registry vendors to check a runnable copy against its source.

:func:`from_bpx` reads the cell-level fields a cell spec can hold (capacity,
voltage limits, dimensions) for other uses; a BPX import does not create a
cell spec, and a new cell spec gets its identity only, since the file's cell
values live on the parameter set. :func:`to_bpx` also exports a cell spec as
a ``"Partial"`` BPX document.

References
----------
- BPX spec: https://github.com/pybamm-team/BPX
- BPX Python library (optional): ``pip install bpx``
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
import warnings as _warnings
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from battinfo._bpx_layout import (
    DEFAULT_TARGET_VERSION,
    THERMAL_CONDUCTIVITY,
    V1_STATE_MOVES,
    is_v0_layout,
    to_v1_layout,
    uses_v1_layout,
    v0_layout_fields,
    version_tuple,
)
from battinfo._jcs import _from_numpy, canonical_json_bytes
from battinfo._jcs import loads as _loads_json

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
    # As-designed geometry (the BPX-required electrode area included): these
    # are engineering facts of the cell design, so they live as spec
    # properties and round-trip through to_bpx.
    "Electrode area [m2]":                ("electrode_area",         "cm2",  1e4),
    "External surface area [m2]":         ("external_surface_area",  "cm2",  1e4),
    "Volume [m3]":                        ("volume",                 "cm3",  1e6),
    "Cell volume [m3]":                   ("volume",                 "cm3",  1e6),
    "Specific heat capacity [J.K-1.kg-1]": None,   # no battinfo spec equivalent
    "Thermal conductivity [W.m-1.K-1]":   None,
    "Initial temperature [K]":            None,
    "Ambient temperature [K]":            None,
    # The temperature parameters are stated conditions of the parameterisation
    # (model conventions), not properties of the cell design.
    "Reference temperature [K]":          None,
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
        Dict of BattINFO spec-property key -> ``{"value": ..., "unit": ...}``
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
    extras:
        The Cell fields with no cell-spec property (electrode-pair count,
        temperatures, unknown keys), verbatim; ``to_bpx(spec,
        cell_extras=...)`` writes them back.
    warnings:
        Non-fatal notes about unmapped BPX fields or missing data.
    """

    specs: dict[str, Any]
    title: str | None
    bpx_version: str | None
    model_type: str | None
    description: str | None
    source_file: str | None
    extras: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_cell_spec_kwargs(self) -> dict[str, Any]:
        """Return ``properties`` (and ``name``, the BPX title) for :class:`battinfo.CellSpec`.

        The caller provides ``manufacturer``, ``model``, ``format`` and
        ``chemistry``: BPX does not carry those fields.
        """
        kwargs: dict[str, Any] = {"properties": dict(self.specs)}
        if self.title is not None:
            kwargs["name"] = self.title
        return kwargs


# ── Internal helpers ──────────────────────────────────────────────────────────


def _parse_bpx_bytes(raw: bytes, label: str) -> dict[str, Any]:
    """A BPX file's bytes as a document, parsed strictly (see :func:`battinfo._jcs.loads`).

    A byte order mark is skipped; a repeated key, a number too large for a
    double, NaN or Infinity, and text that is not a JSON object are refused
    with ``ValueError`` naming ``label`` and where.
    """
    try:
        data = _loads_json(raw)
    except ValueError as exc:
        raise ValueError(f"{label}: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{label} is not a JSON object.")
    return data


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc


def _load_bpx(source: Mapping[str, Any] | str | Path | bytes) -> tuple[dict[str, Any], str]:
    """Load a BPX source (dict, file bytes, or path) and return (data, filename)."""
    if isinstance(source, Mapping):
        return dict(source), "bpx-parameter.json"
    if isinstance(source, (bytes, bytearray)):
        return _parse_bpx_bytes(bytes(source), "the BPX bytes"), "bpx-parameter.json"
    path = Path(source)
    return _parse_bpx_bytes(_read_bytes(path), str(path)), path.name


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


def _extract_references(data: dict[str, Any]) -> str | None:
    """The BPX ``Header.References`` provenance string, if present."""
    header = data.get("Header") or data.get("header") or {}
    if not isinstance(header, Mapping):
        return None
    references = header.get("References") or header.get("references")
    if isinstance(references, list):
        parts = [str(item).strip() for item in references if str(item).strip()]
        return "; ".join(parts) or None
    if references is not None and str(references).strip():
        return str(references).strip()
    return None


def _extract_specs(
    cell_params: dict[str, Any],
    warnings: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map BPX Cell parameters to BattINFO spec-property dicts.

    Returns ``(specs, extras)``: mapped spec properties, plus every Cell key
    with no spec home carried VERBATIM — the same nothing-silently-lost rule
    the parameter annex follows, so :func:`to_bpx` can re-emit them.
    """
    specs: dict[str, Any] = {}
    extras: dict[str, Any] = {}
    known_no_spec: list[str] = []  # in our table, deliberately no BattINFO equivalent
    unknown: list[str] = []        # not in our table at all

    for bpx_key, raw_value in cell_params.items():
        if bpx_key not in _BPX_CELL_MAP:
            unknown.append(bpx_key)
            extras[bpx_key] = raw_value
            continue
        mapping = _BPX_CELL_MAP[bpx_key]
        if mapping is None:
            # Explicitly mapped to None — a recognised parameter with no
            # cell-level spec equivalent (model conventions, pair count, ...).
            known_no_spec.append(bpx_key)
            extras[bpx_key] = raw_value
            continue
        battinfo_key, unit, scale = mapping
        if not isinstance(raw_value, (int, float)) or isinstance(raw_value, bool):
            warnings.append(
                f"BPX field '{bpx_key}' has non-numeric value {raw_value!r}; skipped."
            )
            continue
        if not math.isfinite(raw_value):
            warnings.append(
                f"BPX field '{bpx_key}' has non-finite value {raw_value!r}; skipped."
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

    # EVERY key is named — a truncated list is a silent drop for the rest.
    if known_no_spec:
        warnings.append(
            f"BPX Cell parameters with no BattINFO spec equivalent, carried "
            f"verbatim in extras: {', '.join(known_no_spec)}"
        )
    if unknown:
        warnings.append(
            f"Unknown BPX Cell parameters, carried verbatim in extras: "
            f"{', '.join(unknown)}"
        )
    return specs, extras


def _fold_state_block(
    data: Mapping[str, Any], warnings: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fold a BPX >= 1.0 top-level ``State`` block back into its v0.x homes.

    The inverse of the State moves of :func:`upgrade_bpx`:
    initial/ambient temperatures return to the Cell block (where the importer
    carries them as verbatim extras) and the initial electrolyte concentration
    returns to the Electrolyte block (where it becomes an
    ``initial_concentration`` claim).
    Returns ``(cell_fields, electrolyte_fields)``; anything unrecognized is
    named in a warning — never dropped silently.
    """
    state = data.get("State")
    if not isinstance(state, Mapping) or not state:
        return {}, {}
    cell_fields: dict[str, Any] = {}
    electrolyte_fields: dict[str, Any] = {}
    unknown: list[str] = []
    initial = state.get("Initial conditions")
    if isinstance(initial, Mapping):
        for key, value in initial.items():
            if key == "Initial temperature [K]":
                cell_fields[key] = value
            elif key == "Initial electrolyte concentration [mol.m-3]":
                electrolyte_fields["Initial concentration [mol.m-3]"] = value
            else:
                unknown.append(f"Initial conditions.{key}")
    thermal = state.get("Thermal environment")
    if isinstance(thermal, Mapping):
        for key, value in thermal.items():
            if key == "Ambient temperature [K]":
                cell_fields[key] = value
            else:
                unknown.append(f"Thermal environment.{key}")
    for section in state:
        if section not in ("Initial conditions", "Thermal environment"):
            unknown.append(str(section))
    if unknown:
        # EVERY key is named — a truncated list is a silent drop for the rest.
        warnings.append(
            "BPX State entries with no BattINFO home were skipped: "
            + ", ".join(sorted(unknown))
        )
    return cell_fields, electrolyte_fields


# ── Public API ────────────────────────────────────────────────────────────────


def from_bpx(
    source: Mapping[str, Any] | str | Path,
    *,
    extra_warnings: bool = True,
) -> BpxImportResult:
    """Read the cell-spec properties a BPX file's Cell block can fill.

    Reads the ``Parameterisation.Cell`` block (and the temperatures a BPX
    1.x file keeps in ``State``) and maps the fields that have a cell-spec
    property: capacity, voltage limits, mass, dimensions, areas, volume.
    The Cell fields with no such property (electrode-pair count,
    temperatures, unknown keys) are kept verbatim in
    :attr:`BpxImportResult.extras`. The electrode, separator and
    electrolyte blocks are not read.

    A BPX import does not go through here: :func:`from_bpx_parameters` keeps
    every value of the file, the Cell block included, on the file's
    parameter-set record, and a cell spec created for the file's cell gets
    its identity only (name, maker, model, format, chemistry). Use this for
    other purposes, such as comparing a file's Cell block with a datasheet.

    Parameters
    ----------
    source:
        Path to a BPX JSON file, or an already-parsed dict.
    extra_warnings:
        When ``True`` (default), the warnings include the Cell fields kept
        in ``extras`` and the Cell values skipped as non-numeric or
        non-finite. ``False`` leaves those out; warnings about the file
        itself (no Parameterisation block, State entries with no home, a
        mass recovered from density and volume) are always given.

    Returns
    -------
    BpxImportResult
        ``specs`` (cell-spec properties), ``extras``, the header fields and
        the warnings.

    Examples
    --------
    >>> import battinfo
    >>> result = from_bpx("mohtat2021.json")                    # doctest: +SKIP
    >>> spec = battinfo.CellSpec(
    ...     manufacturer="Custom",
    ...     model="BPX cell",
    ...     format="cylindrical",
    ...     chemistry="li-ion",
    ...     **result.to_cell_spec_kwargs(),                     # properties and name
    ... )                                                       # doctest: +SKIP
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

    # BPX >= 1.0 moves the temperatures into a top-level State block; fold
    # them back so they ride the extras path like their v0.x counterparts
    # (and re-emit into State on a >= 1.0 export). Explicit Cell values win.
    state_cell_fields, _state_electrolyte = _fold_state_block(data, warnings)
    for state_key, state_value in state_cell_fields.items():
        cell_params.setdefault(state_key, state_value)

    specs, extras = _extract_specs(cell_params, warnings if extra_warnings else [])

    # Recover cell mass from Density x Volume when it wasn't carried as a cell-level
    # mass field: to_bpx emits mass only as Density [kg.m-3] (with Volume [m3]), so
    # without this a BattINFO -> BPX -> BattINFO round-trip silently loses the mass.
    if "mass" not in specs:
        density = cell_params.get("Density [kg.m-3]")
        volume = cell_params.get("Volume [m3]")
        if (
            isinstance(density, (int, float)) and not isinstance(density, bool) and math.isfinite(density)
            and isinstance(volume, (int, float)) and not isinstance(volume, bool) and math.isfinite(volume)
        ):
            specs["mass"] = {"value": _sig6(density * volume * 1000.0), "unit": "g"}  # kg -> g
            warnings.append(
                "Recovered cell mass from Density x Volume. Exact diameter/height are not "
                "reconstructed from the BPX physics fields (Volume/surface area)."
            )

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
        extras=extras,
        warnings=warnings,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Export:  parameter-file record, or cell spec / instance  ──►  BPX file
# ══════════════════════════════════════════════════════════════════════════════
#
# A parameter-file record holds every value of its file, so ``to_bpx`` rebuilds
# the document from it. A cell specification does not: a BPX file
# parameterises a *physics* model (DFN/SPMe), which needs electrode
# microstructure, transport coefficients and OCP functions a datasheet does not
# contain. For a spec ``to_bpx`` emits a BPX ``"Partial"`` document (a valid
# Header plus the cell-level ``Parameterisation.Cell`` block populated with
# everything derivable from the spec) and reports the required physics
# parameters it could not fill, instead of inventing them.

# Default BPX schema version to stamp into Header.BPX (override via to_bpx).
_BPX_VERSION = "0.4.0"

# Conventional reference temperature when the spec carries none (25 °C).
_DEFAULT_REFERENCE_TEMPERATURE_K = 298.15

# Unit → SI scale factors for the quantity kinds we export.
_CAP_TO_AH: dict[str, float] = {"Ah": 1.0, "mAh": 1e-3, "A.h": 1.0}
_VOLT_TO_V: dict[str, float] = {"V": 1.0, "mV": 1e-3, "kV": 1e3}
_LEN_TO_M: dict[str, float] = {"m": 1.0, "cm": 1e-2, "mm": 1e-3, "µm": 1e-6, "um": 1e-6}
_MASS_TO_KG: dict[str, float] = {"kg": 1.0, "g": 1e-3, "mg": 1e-6}

# BattINFO property key → (BPX Cell key, unit table, required-in-BPX?)
# Scalars that map straight through to the BPX ``Parameterisation.Cell`` block.
_AREA_TO_M2: dict[str, float] = {"m2": 1.0, "cm2": 1e-4, "mm2": 1e-6}
_VOL_TO_M3: dict[str, float] = {"m3": 1.0, "cm3": 1e-6, "mm3": 1e-9, "L": 1e-3, "mL": 1e-6}

_BPX_EXPORT_DIRECT: dict[str, tuple[str, dict[str, float], bool]] = {
    "nominal_capacity":            ("Nominal cell capacity [A.h]", _CAP_TO_AH, True),
    "charging_cutoff_voltage":     ("Upper voltage cut-off [V]",   _VOLT_TO_V, True),
    "discharging_cutoff_voltage":  ("Lower voltage cut-off [V]",   _VOLT_TO_V, True),
    "electrode_area":              ("Electrode area [m2]",         _AREA_TO_M2, True),
    "external_surface_area":       ("External surface area [m2]",  _AREA_TO_M2, False),
    "volume":                      ("Volume [m3]",                 _VOL_TO_M3, False),
}

# Required BPX Cell keys that a cell spec can never supply on its own.
_BPX_REQUIRED_UNFILLABLE: tuple[str, ...] = (
    "Number of electrode pairs connected in parallel to make a cell",
)

# Cell formats whose volume/surface area follow from diameter + height.
_CYLINDRICAL_FORMATS = {"cylindrical", "coin", "button"}


def _sig6(value: float) -> float:
    """Round to 6 significant figures to suppress float/scaling noise."""
    if value == 0:
        return 0.0
    return float(f"{value:.6g}")


def _scalar(props: Mapping[str, Any], key: str) -> tuple[float, str | None] | None:
    """Return ``(value, unit)`` for a numeric quantity property, else ``None``."""
    q = props.get(key)
    if not isinstance(q, Mapping):
        return None
    value = q.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if not math.isfinite(value):
        # NaN / +-inf would serialise to the bare tokens NaN/Infinity, which are
        # not valid JSON per RFC 8259 and crash strict (e.g. the bpx library's)
        # parsers. Drop the value rather than emit an invalid .bpx.json.
        return None
    unit = q.get("unit")
    return float(value), (str(unit) if unit is not None else None)


def _convert(value: float, unit: str | None, table: dict[str, float], warnings: list[str], key: str) -> float | None:
    """Scale ``value`` to SI using ``table``; warn on an unrecognised unit."""
    if unit is None:
        return value  # assume already in the target unit
    scale = table.get(unit)
    if scale is None:
        warnings.append(f"property '{key}' has unit '{unit}' with no BPX conversion; skipped.")
        return None
    return value * scale


def _length_m(props: Mapping[str, Any], key: str, warnings: list[str]) -> float | None:
    got = _scalar(props, key)
    if got is None:
        return None
    value, unit = got
    return _convert(value, unit, _LEN_TO_M, warnings, key)


def _geometry(
    props: Mapping[str, Any], cell_format: str | None, warnings: list[str]
) -> tuple[float | None, float | None]:
    """Best-effort (volume_m3, external_surface_area_m2) from spec dimensions."""
    fmt = (cell_format or "").lower()
    diameter = _length_m(props, "diameter", warnings)
    height = _length_m(props, "height", warnings)
    width = _length_m(props, "width", warnings)
    thickness = _length_m(props, "thickness", warnings)

    if fmt in _CYLINDRICAL_FORMATS and diameter and height:
        r = diameter / 2.0
        volume = math.pi * r * r * height
        area = 2.0 * math.pi * r * height + 2.0 * math.pi * r * r
        return _sig6(volume), _sig6(area)

    if width and height and thickness:  # pouch / prismatic
        volume = width * height * thickness
        area = 2.0 * (width * height + width * thickness + height * thickness)
        return _sig6(volume), _sig6(area)

    return None, None


@dataclass
class BpxExportResult:
    """Result of :func:`to_bpx`.

    Attributes
    ----------
    bpx:
        The BPX document: for a parameter-file record the file it
        describes, for a cell spec a ``"Partial"`` document with every
        cell-level parameter the spec gives.
    filled:
        The BPX fields written from the record (``"Cell.Electrode area
        [m2]"``, ``"State.Initial conditions.Initial temperature [K]"``).
    missing_required:
        Required BPX fields the document lacks: the user must supply
        these (or run a physics-parameterisation workflow) before the file
        can drive a full model. Cell keys are named by themselves
        (``"Electrode area [m2]"``). For a parameter-file record, when the
        official ``bpx`` package is installed and rejects the document,
        every other field it reports missing follows as
        ``"<block>.<field>"`` (``"Negative electrode.OCP [V]"``).
    warnings:
        What the caller should know: values the document lacks, unit
        conversions, values added by the v0-to-v1 layout conversion, and
        the official parser's verdict when it rejects the document.
    complete:
        ``False`` when the document lacks a value its source held: for a
        parameter-file record, a value the import did not read
        (``not_imported``) or a claim this export could not write; for a
        cell spec, a property in a unit with no BPX conversion. The source
        file under the record's ``distributions`` is then the complete copy.
    """

    bpx: dict[str, Any]
    filled: list[str]
    missing_required: list[str]
    warnings: list[str] = field(default_factory=list)
    complete: bool = True

    def to_json(self, *, indent: int = 2) -> str:
        """Serialise the BPX document to a JSON string.

        ``allow_nan=False`` so any non-finite value that slipped through fails
        loudly here rather than emitting the bare tokens ``NaN``/``Infinity``
        (invalid JSON per RFC 8259, rejected by strict parsers).
        """
        return json.dumps(self.bpx, indent=indent, ensure_ascii=False, allow_nan=False)

    def save(self, path: PathLike) -> Path:
        """Write the BPX document to ``path`` and return it."""
        out = Path(path)
        out.write_text(self.to_json() + "\n", encoding="utf-8")
        return out


def to_bpx(
    source: Any,
    *,
    cell_instance: Mapping[str, Any] | Any | None = None,
    cell_extras: Mapping[str, Any] | None = None,
    model: str | None = None,
    bpx_version: str | None = None,
    reference_temperature_k: float | None | str = "auto",
    title: str | None = None,
    strict: bool = False,
) -> BpxExportResult:
    """Export a BattINFO record to a BPX document.

    Two sources are accepted.

    A **parameter-file record** (a parameter set built by
    :meth:`BpxParameterImportResult.to_parameter_set`) is rebuilt into the
    full BPX document it describes: every part's claims go back to their BPX
    block (cell, electrodes, separator, electrolyte, State) at full precision,
    the annex becomes ``User-defined``, and the header comes from the
    record's model context. The document follows the layout of the version
    it declares: the source's own version by default, or ``bpx_version``. A
    record read from a v0.x-layout file (``model_context.layout`` is
    ``"v0"``) and exported at a 1.x version goes through the same layout
    conversion as :func:`upgrade_bpx`, so the State
    values the bpx package's own v0-to-v1 migration adds (initial state of
    charge 1, and the temperatures it resolves) are added here too, and
    named in the warnings. A claim in another unit than BPX states is
    converted (a curve's x axis included), or the export raises
    ``ValueError`` naming it, as it does for a curve tabulated against
    another quantity than the BPX field. What the record never held (the
    paths in its ``not_imported``: blended-electrode ``Particle`` blocks, a
    ``Validation`` section, ...) is named in the warnings and makes
    :attr:`BpxExportResult.complete` false: the stored source file is the
    complete copy.

    A **cell spec** (a cell-spec record dict ``{"cell_spec": ...,
    "properties": ...}``, a :class:`~battinfo.bundle.CellSpec`, or a bare
    properties mapping) gives a ``"Partial"`` document: the
    ``Parameterisation.Cell`` block with everything derivable from the
    specification (nominal capacity, voltage cut-offs, electrode area, and,
    from the dimensions, volume, external surface area and density), plus
    the required physics parameters a spec cannot provide, reported rather
    than invented.

    A registry resource JSON holding one such record (under
    ``semantic_payload.battinfo_records``) is unwrapped. Anything else
    raises ``TypeError``. When the official ``bpx`` package is installed,
    the document is parsed with it and a rejection is added to the warnings.

    Parameters
    ----------
    source:
        A parameter-file record, or a cell spec as above.
    cell_instance:
        Cell-spec export only: a cell-instance record or object whose serial
        number / id is recorded in ``Header.References``.
    cell_extras:
        Cell-spec export only: BPX Cell fields carried verbatim (for example
        :attr:`BpxImportResult.extras`); spec-derived values win.
    model:
        ``Header.Model``. A parameter file defaults to the model it was
        fitted under (its ``model_context``); a cell spec to ``"Partial"``.
    bpx_version:
        Value stamped into ``Header.BPX`` (always a string). The document
        follows that version's layout: from 1.0 on, the temperatures and the
        initial electrolyte concentration go in the ``State`` block and a
        Cell thermal conductivity goes in ``User-defined``; a 0.x version
        keeps them in Cell and Electrolyte.
    reference_temperature_k:
        Cell-spec export only. The default ``"auto"`` keeps a value carried
        by ``cell_extras`` and falls back to the 298.15 K convention only
        when nothing provides the field. Pass a float to force that value,
        or ``None`` to emit none of our own.
    title:
        Override ``Header.Title``.
    strict:
        Raise ``ValueError`` instead of returning a document that is not
        :attr:`~BpxExportResult.complete`.

    Returns
    -------
    BpxExportResult
        The BPX document plus ``filled`` / ``missing_required`` /
        ``warnings`` / ``complete``.

    Examples
    --------
    >>> record = from_bpx_parameters("nmc_pouch_cell_BPX.json").to_parameter_set(
    ...     virtual_cell=True)                          # doctest: +SKIP
    >>> to_bpx(record, bpx_version="1.1.0").save("nmc.bpx.json")  # doctest: +SKIP
    """
    record = _export_source(source)
    if isinstance(record.get("parameter_set"), Mapping):
        if cell_instance is not None or cell_extras is not None:
            raise ValueError(
                "cell_instance and cell_extras apply to a cell-spec export; a parameter-file "
                "record already holds every value of its file."
            )
        result, lacking = _parameter_file_to_bpx(record, model=model, bpx_version=bpx_version, title=title)
    else:
        result, lacking = _cell_spec_to_bpx(
            record,
            cell_instance=cell_instance,
            cell_extras=cell_extras,
            model=model,
            bpx_version=bpx_version,
            reference_temperature_k=reference_temperature_k,
            title=title,
        )
    result.complete = not lacking
    if strict and lacking:
        raise ValueError(
            "to_bpx(strict=True): the document would lack values its source holds: "
            + "; ".join(lacking)
        )
    rejection, parser_missing = _official_parser_rejection(result.bpx)
    if rejection is not None:
        result.warnings.append(f"The official bpx parser rejects this document: {rejection}")
    if isinstance(record.get("parameter_set"), Mapping):
        # The parser knows every block's required fields; the Cell check above
        # knows only the Cell's.
        for path in parser_missing:
            block, _, name = path.partition(".")
            if not (block == "Cell" and name in result.missing_required) and path not in result.missing_required:
                result.missing_required.append(path)
    return result


def _export_source(source: Any) -> dict[str, Any]:
    """``source`` as the record to_bpx exports, or ``TypeError`` saying what it accepts."""
    from battinfo.entities import kind_for_doc  # noqa: PLC0415

    if hasattr(source, "to_record") and callable(source.to_record):
        source = source.to_record()
    if not isinstance(source, Mapping):
        raise TypeError(
            "to_bpx exports a parameter-file record or a cell spec (a cell-spec record dict, a "
            f"CellSpec-like object with to_record(), or a properties mapping); got {type(source).__name__}."
        )
    resource = source.get("resource") if isinstance(source.get("resource"), Mapping) else source
    payload = resource.get("semantic_payload")
    if isinstance(payload, Mapping):
        held = payload.get("battinfo_records")
        candidates = [
            item
            for item in (held.values() if isinstance(held, Mapping) else [])
            if isinstance(item, Mapping)
            and (isinstance(item.get("parameter_set"), Mapping) or isinstance(item.get("cell_spec"), Mapping))
        ]
        if len(candidates) != 1:
            raise TypeError(
                "this registry resource does not hold exactly one parameter-set or cell-spec record "
                "under semantic_payload.battinfo_records, so to_bpx has nothing to export."
            )
        return dict(candidates[0])
    kind = kind_for_doc(source)
    if kind is not None and kind.entity_type not in ("cell-spec", "parameter-set"):
        raise TypeError(
            f"to_bpx exports a parameter-file record or a cell spec; this is a {kind.entity_type} record."
        )
    if kind is None and "properties" not in source and "cell_spec" not in source:
        quantities = [value for value in source.values() if isinstance(value, Mapping)]
        if not source or len(quantities) != len(source) or not all(
            "value" in value or "unit" in value for value in quantities
        ):
            raise TypeError(
                "to_bpx exports a parameter-file record, a cell-spec record or a cell spec's "
                "properties mapping (key -> {value, unit}); this mapping is none of them."
            )
    return dict(source)


def _official_parser_rejection(document: Mapping[str, Any]) -> tuple[str | None, list[str]]:
    """The official parser's error for ``document`` and the fields it reports missing.

    ``(None, [])`` when the document parses or bpx is not installed. A
    missing field is ``"<block>.<field>"`` (``"Negative electrode.OCP [V]"``).
    """
    try:
        import bpx as bpx_lib  # noqa: PLC0415
    except ImportError:
        return None, []
    passed, detail, missing = _parse_with_official_parser(dict(document), bpx_lib)
    return (None, []) if passed else (detail, missing)


_NO_CONVERSION = "with no BPX conversion; skipped."


def _cell_spec_to_bpx(
    source: Any,
    *,
    cell_instance: Mapping[str, Any] | Any | None,
    cell_extras: Mapping[str, Any] | None,
    model: str | None,
    bpx_version: str | None,
    reference_temperature_k: float | None | str,
    title: str | None,
) -> tuple[BpxExportResult, list[str]]:
    """A cell spec's ``Partial`` BPX document (see :func:`to_bpx`), and what it lacks."""
    warnings: list[str] = []
    meta, props = _coerce_cell_spec(source)

    name = title or meta.get("name") or meta.get("model")
    cell: dict[str, Any] = {}
    filled: list[str] = []

    # 1. Direct scalar mappings (capacity, voltage cut-offs).
    for bi_key, (bpx_key, table, _required) in _BPX_EXPORT_DIRECT.items():
        got = _scalar(props, bi_key)
        if got is None:
            continue
        value, unit = got
        si = _convert(value, unit, table, warnings, bi_key)
        if si is None:
            continue
        cell[bpx_key] = _sig6(si)
        filled.append(bpx_key)

    # 2. Geometry-derived volume and surface area — fallback only: explicit
    # electrode_area/external_surface_area/volume properties (step 1) win.
    volume, area = _geometry(props, meta.get("cell_format"), warnings)
    if volume is not None and "Volume [m3]" not in cell:
        cell["Volume [m3]"] = volume
        filled.append("Volume [m3]")
    if area is not None and "External surface area [m2]" not in cell:
        cell["External surface area [m2]"] = area
        filled.append("External surface area [m2]")

    mass = _scalar(props, "mass")
    emitted_volume = cell.get("Volume [m3]")
    if mass is not None and emitted_volume:
        mass_kg = _convert(mass[0], mass[1], _MASS_TO_KG, warnings, "mass")
        if mass_kg is not None:
            cell["Density [kg.m-3]"] = _sig6(mass_kg / emitted_volume)
            filled.append("Density [kg.m-3]")

    # 3. Explicitly forced reference temperature (a caller-passed float
    # wins over everything, including imported extras).
    if isinstance(reference_temperature_k, (int, float)):
        cell["Reference temperature [K]"] = float(reference_temperature_k)
        filled.append("Reference temperature [K]")

    # 3b. Verbatim Cell extras (e.g. :attr:`BpxImportResult.extras` from a
    # round trip): temperatures, pair count — BPX Cell fields with no spec
    # home. Spec-derived values always win; extras only fill gaps.
    for extra_key, extra_value in (cell_extras or {}).items():
        if extra_key not in cell:
            cell[extra_key] = extra_value
            filled.append(extra_key)

    # 3c. Conventional reference temperature, LAST: under "auto" the
    # 298.15 K convention fills the field only when neither the caller nor
    # the imported extras carried one — a round-tripped file's own
    # temperature must never be silently replaced by the convention.
    if reference_temperature_k == "auto" and "Reference temperature [K]" not in cell:
        cell["Reference temperature [K]"] = _DEFAULT_REFERENCE_TEMPERATURE_K
        filled.append("Reference temperature [K]")

    missing_required = _missing_required_cell_fields(cell)
    if missing_required:
        warnings.append(
            "Required BPX Cell parameters not derivable from a cell spec "
            "(supply these before driving a full model): "
            + ", ".join(missing_required)
        )

    resolved_model = model or "Partial"
    warnings.append(
        "Electrode, electrolyte, and separator physics parameters "
        "(thickness, porosity, transport, OCP, particle data) are not part of a "
        f"cell specification and were not emitted. Header.Model is {resolved_model!r}."
    )

    resolved_version = str(bpx_version or _BPX_VERSION)
    header: dict[str, Any] = {"BPX": resolved_version, "Model": resolved_model}
    if name:
        header["Title"] = str(name)
    header["Description"] = (
        "Partial BPX exported from a BattINFO cell specification"
        + (f" ('{name}')" if name else "")
        + ". Cell-level parameters only; physics parameters are not derivable "
        "from a specification and must be added separately."
    )
    instance_reference = _instance_reference(meta, cell_instance)
    if instance_reference:
        header["References"] = instance_reference

    bpx_doc: dict[str, Any] = {
        "Header": header,
        "Parameterisation": {"Cell": cell},
    }
    if uses_v1_layout(resolved_version) and is_v0_layout(bpx_doc):
        # Temperatures from cell_extras sit in Cell, where a 0.x file keeps
        # them: the same conversion upgrade_bpx makes.
        bpx_doc, changes = to_v1_layout(bpx_doc, resolved_version)
        _report_layout_changes(changes, resolved_version, warnings)
    lacking = [w.split(" has unit ")[0] for w in warnings if w.endswith(_NO_CONVERSION)]
    return (
        BpxExportResult(bpx=bpx_doc, filled=filled, missing_required=missing_required, warnings=warnings),
        lacking,
    )


def _report_layout_changes(changes: list[str], version: str, warnings: list[str]) -> None:
    """Name what the v0-to-v1 layout conversion did beyond moving State fields."""
    for change in changes:
        if change.startswith(f"Cell.{THERMAL_CONDUCTIVITY}"):
            warnings.append(f"BPX {version} has no Cell thermal conductivity: {change}.")
    added = [change.removeprefix("added ") for change in changes if change.startswith("added ")]
    if added:
        warnings.append(
            "Added for the v1 layout, as the bpx package's own v0-to-v1 migration adds them "
            "for a file without them: " + "; ".join(added) + "."
        )


def _missing_required_cell_fields(cell: Mapping[str, Any]) -> list[str]:
    """The Cell fields every non-Partial BPX file needs and ``cell`` lacks."""
    missing = [
        bpx_key
        for _bi_key, (bpx_key, _table, required) in _BPX_EXPORT_DIRECT.items()
        if required and bpx_key not in cell
    ]
    missing.extend(k for k in _BPX_REQUIRED_UNFILLABLE if k not in cell)
    return missing


# Parameter-file part -> (BPX block, vocabulary block for the field lookup).
_PART_BPX_BLOCKS: dict[str, tuple[str, str]] = {
    "cell": ("Cell", "cell"),
    "negative_material": ("Negative electrode", "electrode"),
    "negative_electrode": ("Negative electrode", "electrode"),
    "positive_material": ("Positive electrode", "electrode"),
    "positive_electrode": ("Positive electrode", "electrode"),
    "separator": ("Separator", "separator"),
    "electrolyte": ("Electrolyte", "electrolyte"),
    "state": ("State", "state"),
}

_REFERENCES_NOTE_PREFIX = "BPX Header.References: "

# The OCP branches BPX 1.0 added for single-phase electrodes: branch -> field.
_OCP_BRANCH_FIELDS: dict[str, str] = {
    "lithiation": "OCP (lithiation) [V]",
    "delithiation": "OCP (delithiation) [V]",
}

# State field -> its v0.x home: the inverse of the moves BPX 1.0 made.
_V0_STATE_HOMES: dict[tuple[str, str], tuple[str, str]] = {
    (section, new_key): (block, key) for block, key, section, new_key in V1_STATE_MOVES
}

# The unit a BPX table's x axis is in, by what it tabulates against.
_CURVE_X_UNITS: dict[str, str] = {"stoichiometry": "1", "concentration": "mol/m3", "temperature": "K"}

# BPX unit -> {unit: factor into it}. Keys are the spellings
# normalize_unit_symbol gives; the BPX unit itself always converts with 1.
_UNIT_FACTORS: dict[str, dict[str, float]] = {
    "1": {"%": 1e-2},
    "Ah": {"A.h": 1.0, "mAh": 1e-3},
    "V": {"mV": 1e-3, "kV": 1e3},
    "V/K": {"mV/K": 1e-3},
    "m": {"cm": 1e-2, "mm": 1e-3, "µm": 1e-6, "nm": 1e-9},
    "kg": {"g": 1e-3, "mg": 1e-6},
    "m2": {"cm2": 1e-4, "mm2": 1e-6},
    "m3": {"cm3": 1e-6, "mm3": 1e-9, "dm3": 1e-3, "L": 1e-3, "mL": 1e-6},
    "kg/m3": {"g/cm3": 1e3, "g/mL": 1e3, "g/L": 1.0},
    "mol/m3": {"mol/L": 1e3, "mol/dm3": 1e3, "M": 1e3, "kmol/m3": 1e3, "mmol/L": 1.0, "mM": 1.0, "mol/cm3": 1e6},
    "m2/s": {"cm2/s": 1e-4, "mm2/s": 1e-6},
    "S/m": {"S/cm": 1e2, "mS/cm": 1e-1, "mS/m": 1e-3},
    "1/m": {"m-1": 1.0, "1/cm": 1e2, "cm-1": 1e2},
    "J/mol": {"kJ/mol": 1e3},
    "mol.m-2.s-1": {"mol/(m2.s)": 1.0},
    "J/(kg.K)": {"J/kg/K": 1.0, "J.kg-1.K-1": 1.0, "J.K-1.kg-1": 1.0, "J/(g.K)": 1e3, "kJ/(kg.K)": 1e3},
    "W/(m.K)": {"W/m/K": 1.0, "W.m-1.K-1": 1.0},
    "W/(m2.K)": {"W/m2/K": 1.0, "W.m-2.K-1": 1.0},
}
# Units that convert with an offset: unit -> (BPX unit, offset added).
_UNIT_OFFSETS: dict[str, tuple[str, float]] = {"°C": ("K", 273.15)}


def _unit_factor(unit: str | None, bpx_unit: str) -> tuple[float, float] | None:
    """``(factor, offset)`` taking ``unit`` to ``bpx_unit``, or ``None`` when no conversion is known."""
    from battinfo.transform.json_to_jsonld import normalize_unit_symbol  # noqa: PLC0415

    if unit is None or unit == bpx_unit:
        return 1.0, 0.0
    source = normalize_unit_symbol(unit) or unit
    target = normalize_unit_symbol(bpx_unit) or bpx_unit
    if source == target:
        return 1.0, 0.0
    offset = _UNIT_OFFSETS.get(source)
    if offset is not None and offset[0] == target:
        return 1.0, offset[1]
    factor = _UNIT_FACTORS.get(target, {}).get(source)
    return (factor, 0.0) if factor is not None else None


def _claim_to_bpx_value(
    claim: Mapping[str, Any], bpx_unit: str, entry: Mapping[str, Any], part: Any, field_name: str
) -> Any:
    """One claim's value as BPX writes it, or ``ValueError`` saying why it cannot be.

    Values are written back exactly as the claim holds them when they are in
    the unit BPX states; otherwise they are converted. A quantity without a
    unit is in the parameter's canonical unit. A curve's x axis must
    tabulate what the BPX field tabulates, in (or convertible to) the unit
    BPX uses for it.
    """
    key = claim.get("parameter")
    label = f"claim {key!r} ({part})"
    quantity = claim.get("quantity")
    if isinstance(quantity, Mapping):
        value = quantity.get("value")
        if not _finite_number(value):
            raise ValueError(f"{label} has no finite numeric value for BPX {field_name!r}.")
        unit = quantity.get("unit")
        unit = str(unit) if unit is not None else str(entry.get("unit") or bpx_unit)
        return _converted([value], unit, bpx_unit, label, field_name)[0]
    curve = claim.get("curve")
    if isinstance(curve, Mapping):
        xs, ys = curve.get("x"), curve.get("y")
        if not (
            isinstance(xs, list) and isinstance(ys, list) and len(xs) == len(ys) >= 2
            and all(_finite_number(v) for v in [*xs, *ys])
        ):
            raise ValueError(f"{label} has a malformed curve: x and y need equal lengths of finite numbers.")
        tabulated = str(entry.get("x_quantity") or "stoichiometry")
        x_quantity = curve.get("x_quantity")
        if x_quantity != tabulated:
            raise ValueError(
                f"{label} is a curve against {x_quantity!r}, and BPX {field_name!r} tabulates against "
                f"{tabulated!r}; it cannot be written as that field."
            )
        x_unit = _CURVE_X_UNITS.get(tabulated, "1")
        given_x_unit = curve.get("x_unit")
        if given_x_unit is None and x_unit != "1":
            raise ValueError(
                f"{label} is a curve against {tabulated} with no x_unit; BPX {field_name!r} "
                f"tabulates it in {x_unit}, so say which unit the x values are in."
            )
        y_unit = curve.get("y_unit")
        return {
            "x": _converted(xs, None if given_x_unit is None else str(given_x_unit), x_unit, f"{label} x axis", field_name),
            "y": _converted(ys, None if y_unit is None else str(y_unit), bpx_unit, label, field_name),
        }
    expression = claim.get("expression")
    if isinstance(expression, Mapping):
        text = expression.get("text")
        if isinstance(text, str) and text.strip():
            return text
    raise ValueError(f"{label} holds no quantity, curve or expression BPX can write as {field_name!r}.")


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _converted(values: list[Any], unit: str | None, bpx_unit: str, label: str, field_name: str) -> list[Any]:
    conversion = _unit_factor(unit, bpx_unit)
    if conversion is None:
        raise ValueError(
            f"{label} is in {unit!r}, and BPX states {field_name!r} in {bpx_unit!r}: no conversion "
            "between the two is known, so the value is not written. Give the claim in "
            f"{bpx_unit!r}."
        )
    factor, offset = conversion
    if factor == 1.0 and offset == 0.0:
        return list(values)
    return [value * factor + offset for value in values]


def _ocp_branch(claim: Mapping[str, Any]) -> str | None:
    """'lithiation' or 'delithiation' for an OCP curve of one hysteresis branch, else None."""
    from battinfo.parameters import resolve_parameter  # noqa: PLC0415

    curve = claim.get("curve")
    if resolve_parameter(claim.get("parameter")) != "ocp" or not isinstance(curve, Mapping):
        return None
    branch = curve.get("branch")
    return branch if branch in _OCP_BRANCH_FIELDS else None


def _record_uses_v0_layout(model_context: Mapping[str, Any], source_version: str | None) -> bool:
    """Whether the record was read from a v0.x-layout file.

    ``model_context.layout`` says so; a record without it (built by hand)
    goes by its version, so a 0.x version means the v0.x layout.
    """
    layout = model_context.get("layout")
    if layout in ("v0", "v1"):
        return layout == "v0"
    return source_version is not None and bool(version_tuple(source_version)) and not uses_v1_layout(source_version)


def _parameter_file_to_bpx(
    record: Mapping[str, Any],
    *,
    model: str | None,
    bpx_version: str | None,
    title: str | None,
) -> tuple[BpxExportResult, list[str]]:
    """Rebuild the BPX document a parameter-file record describes (see :func:`to_bpx`).

    The document is first laid out the way the source file was (the v0.x
    layout for a record read from a v0.x-layout file) and then, when the
    requested version needs the other layout, converted: v0.x to v1 with
    the one conversion :func:`upgrade_bpx` makes, v1 to v0.x by folding
    State back into Cell and Electrolyte.
    """
    from battinfo.parameters import bpx_field, parameter_entry  # noqa: PLC0415

    body = record["parameter_set"]
    if not isinstance(body.get("parts"), list):
        raise ValueError(
            "to_bpx rebuilds a BPX file from a parameter-file record (one with parts, built by "
            "BpxParameterImportResult.to_parameter_set); a claim batch states one target's "
            "claims, not a file."
        )
    model_context = body.get("model_context") if isinstance(body.get("model_context"), Mapping) else {}
    declared = model_context.get("version")
    source_version = declared if isinstance(declared, str) and declared else None
    target_version = str(bpx_version or source_version or _BPX_VERSION)
    target_v1 = uses_v1_layout(target_version)
    v0_source = _record_uses_v0_layout(model_context, source_version)
    warnings: list[str] = []
    lacking: list[str] = []
    blocks: dict[str, dict[str, Any]] = {"Cell": {}}
    state: dict[str, dict[str, Any]] = {}
    user_defined: dict[str, Any] = {}

    for part in body["parts"]:
        if not isinstance(part, Mapping):
            continue
        part_name = part.get("part")
        if part.get("phase") is not None:
            lacking.append(
                f"part {part_name!r} phase {part.get('phase')!r} (blended electrodes, BPX Particle "
                "blocks, are not exported yet)"
            )
            continue
        target = _PART_BPX_BLOCKS.get(part_name)
        if target is None:
            lacking.append(f"part {part_name!r} (no BPX block)")
            continue
        block_name, vocab_block = target
        for claim in part.get("claims") or []:
            if not isinstance(claim, Mapping):
                continue
            key = claim.get("parameter")
            mapping = bpx_field(key, vocab_block)
            if mapping is None:
                lacking.append(f"claim {key!r} ({part_name}), which has no BPX field")
                continue
            field_name = mapping["field"]
            branch = _ocp_branch(claim)
            if branch is not None:
                if not target_v1:
                    raise ValueError(
                        f"claim {key!r} ({part_name}) is the OCP's {branch} branch, and BPX "
                        f"{target_version} has no field for one branch ('{_OCP_BRANCH_FIELDS[branch]}' "
                        "arrived with BPX 1.0): export at a 1.x version."
                    )
                field_name = _OCP_BRANCH_FIELDS[branch]
            value = _claim_to_bpx_value(claim, mapping["unit"], parameter_entry(key) or {}, part_name, field_name)
            expression = claim.get("expression")
            if isinstance(expression, Mapping) and expression.get("language") not in (None, "bpx"):
                warnings.append(
                    f"claim {key!r} ({part_name}) carries a {expression.get('language')!r} expression; "
                    "BPX expects its own function syntax, so it is written verbatim."
                )
            # Where the source file kept the value.
            if vocab_block == "state":
                section = mapping["section"]
                home = _V0_STATE_HOMES.get((section, field_name)) if v0_source else None
                if home is not None:
                    destination, where, name = blocks.setdefault(home[0], {}), home[0], home[1]
                else:
                    destination, where, name = state.setdefault(section, {}), f"State.{section}", field_name
            elif block_name == "Cell" and field_name == THERMAL_CONDUCTIVITY and target_v1 and not v0_source:
                destination, where, name = user_defined, "User-defined", field_name
            else:
                destination, where, name = blocks.setdefault(block_name, {}), block_name, field_name
            if name in destination and destination[name] != value:
                lacking.append(f"claim {key!r} ({part_name}), since {where}.{name} is set by another claim")
                continue
            destination[name] = value

    header: dict[str, Any] = {
        "BPX": (source_version or target_version) if (target_v1 and v0_source) else target_version,
        "Model": model or model_context.get("model") or "Partial",
    }
    header_title = title or model_context.get("name") or body.get("name")
    if header_title:
        header["Title"] = str(header_title)
    if isinstance(body.get("description"), str) and body["description"]:
        header["Description"] = body["description"]
    references = [
        note[len(_REFERENCES_NOTE_PREFIX):]
        for note in record.get("notes") or []
        if isinstance(note, str) and note.startswith(_REFERENCES_NOTE_PREFIX)
    ]
    provenance = record.get("provenance") if isinstance(record.get("provenance"), Mapping) else {}
    for prov_key in ("citation", "citation_doi"):
        prov_value = provenance.get(prov_key)
        if isinstance(prov_value, str) and prov_value and not references:
            references.append(prov_value)
    if references:
        header["References"] = "; ".join(dict.fromkeys(references))

    parameterisation: dict[str, Any] = {}
    for block_name in ("Cell", "Electrolyte", "Negative electrode", "Positive electrode", "Separator"):
        if block_name in blocks:
            parameterisation[block_name] = blocks[block_name]
    annex = body.get("annex")
    annex_copy: dict[str, Any] = copy.deepcopy(dict(annex)) if isinstance(annex, Mapping) else {}
    for name, value in user_defined.items():
        if name in annex_copy and annex_copy[name] != value:
            raise ValueError(
                f"BPX Cell.{name} is {value!r} but the annex (User-defined) holds {annex_copy[name]!r} "
                "under the same key; refusing to choose between them."
            )
        annex_copy[name] = value
    if annex_copy:
        parameterisation["User-defined"] = annex_copy
    document: dict[str, Any] = {"Header": header, "Parameterisation": parameterisation}
    if state:
        document["State"] = state

    added: set[str] = set()
    if target_v1 and v0_source:
        document, changes = to_v1_layout(document, target_version)
        _report_layout_changes(changes, target_version, warnings)
        added = {change.removeprefix("added ").split(" = ")[0] for change in changes if change.startswith("added ")}
    elif not target_v1:
        unhomed = _fold_state_into_v0(document)
        if unhomed:
            lacking.append(
                f"State values BPX {target_version} has no field for ({', '.join(unhomed)}; export at "
                "a 1.x version to keep them)"
            )

    filled = [
        f"{block_name}.{name}"
        for block_name, fields in document["Parameterisation"].items()
        if block_name != "User-defined" and isinstance(fields, Mapping)
        for name in fields
    ] + [
        path
        for section, fields in (document.get("State") or {}).items()
        if isinstance(fields, Mapping)
        for name in fields
        if (path := f"State.{section}.{name}") not in added
    ]
    missing_required = _missing_required_cell_fields(document["Parameterisation"].get("Cell", {}))
    if missing_required and header["Model"] != "Partial":
        warnings.append(
            "Required BPX Cell parameters the record does not hold: " + ", ".join(missing_required)
        )
    not_imported = [str(path) for path in body.get("not_imported") or [] if isinstance(path, str)]
    if not_imported:
        warnings.append(
            "The record does not hold these values of its source file, so this document lacks them "
            "(the source file under distributions is the complete copy): " + ", ".join(not_imported)
        )
    if lacking:
        warnings.append("Values the record holds that this document does not: " + "; ".join(lacking))
    return (
        BpxExportResult(bpx=document, filled=filled, missing_required=missing_required, warnings=warnings),
        [*(f"not imported: {path}" for path in not_imported), *lacking],
    )


def _fold_state_into_v0(document: dict[str, Any]) -> list[str]:
    """Move State into its v0.x homes (Cell, Electrolyte), in place; return what has none.

    The values with no v0.x field are left out of the document and named.
    A value set both in State and in its v0.x home is refused unless equal.
    """
    state = document.pop("State", None)
    if state is None:
        return []
    if not isinstance(state, dict):
        return ["State"]
    parameterisation = document.setdefault("Parameterisation", {})
    unhomed: list[str] = []
    for section, fields in state.items():
        if not isinstance(fields, dict):
            unhomed.append(f"State.{section}")
            continue
        for key, value in fields.items():
            home = _V0_STATE_HOMES.get((section, key))
            if home is None:
                unhomed.append(f"State.{section}.{key}")
                continue
            block_name, v0_key = home
            block = parameterisation.setdefault(block_name, {})
            if v0_key in block and block[v0_key] != value:
                raise ValueError(
                    f"BPX {block_name}.{v0_key} is set both there and as State.{section}.{key}; "
                    "refusing to choose between them."
                )
            block[v0_key] = value
    return unhomed


def save_bpx(source: Any, path: PathLike, **kwargs: Any) -> Path:
    """Convenience: :func:`to_bpx` then write the document to ``path``."""
    return to_bpx(source, **kwargs).save(path)


def _coerce_cell_spec(source: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalise ``source`` to ``(cell_spec_meta, properties)``."""
    if hasattr(source, "to_record") and callable(source.to_record):
        source = source.to_record()
    if isinstance(source, Mapping):
        if "properties" in source or "cell_spec" in source:
            meta = source.get("cell_spec")
            props = source.get("properties")
            return (
                dict(meta) if isinstance(meta, Mapping) else {},
                dict(props) if isinstance(props, Mapping) else {},
            )
        # A bare properties mapping (key → {value, unit}).
        return {}, dict(source)
    raise TypeError(
        "to_bpx expects a cell-spec record dict, a CellSpec-like object with "
        f"to_record(), or a properties mapping; got {type(source).__name__}."
    )


def _json_kind(value: Any) -> str:
    """How a JSON value reads in an error message: null, an array, a string, ..."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, (list, tuple)):
        return "an array"
    return f"a {type(value).__name__}"


# ══════════════════════════════════════════════════════════════════════════════
# Import:  one BPX file  ──►  one parameter-set record
# ══════════════════════════════════════════════════════════════════════════════
#
# One BPX file is one source and one record. Every value lands in a part: each
# electrode block splits into its material part (intrinsic values: OCP,
# diffusivity, stoichiometry window) and its electrode part (the build:
# thickness, porosity), and the Cell and State blocks become the cell and state
# parts. BPX value forms map 1:1 onto claim forms: number -> quantity,
# {"x": [...], "y": [...]} -> curve, "expression string" ->
# expression(language="bpx").

_BPX_ELECTRODE_BLOCKS = {"negative": "Negative electrode", "positive": "Positive electrode"}


# ── Parameter files: identity, layout upgrade, checks ──────────────────────
#
# A published BPX file is served to solvers as its own bytes. The claims are
# the searchable index and rebuild the file (to_bpx), but a rebuild cannot
# restore what the importer does not model (Particle blends, initial
# hysteresis state, Validation curves). These helpers give the file an
# identity, a declared conversion when current parsers reject its layout, and
# recorded checks.

# Top-level sections the parameter importer reads (or folds, for State).
_BPX_PARAMETER_SECTIONS = frozenset(
    {"Header", "header", "Parameterisation", "parameterisation", "parameters", "State"}
)


def bpx_content_digest(source: Mapping[str, Any] | str | Path | bytes) -> str:
    """SHA-256 of a BPX document's canonical JSON: the identity of its parameters.

    Canonical is RFC 8785 (JSON Canonicalization Scheme): numbers written the
    way ECMAScript writes doubles, keys sorted by UTF-16 code units, minimal
    string escaping, no whitespace, UTF-8. The digest names the parameters,
    not the bytes: a re-indented, reordered or CRLF copy has the same digest,
    and so does one that spells a number differently (``1`` or ``1.0``,
    ``1e-05`` or ``0.00001``, ``-0.0`` or ``0``), as a file passed through
    another JSON library will. Any changed value changes it. The record imported
    from the file stores it as ``parameters_sha256`` and mints its uid from it
    (IDENTIFIER_POLICY 6.3).

    numpy scalars and arrays in a dict input count as the values they hold.
    NaN and infinities have no JSON form, so they raise ``ValueError`` naming
    where they are.
    """
    data, _ = _load_bpx(source)
    return hashlib.sha256(canonical_json_bytes(data)).hexdigest()


@dataclass
class BpxUpgradeResult:
    """Result of :func:`upgrade_bpx`: the rewritten document and what changed.

    ``source_version`` is ``Header.BPX`` as the file declared it;
    ``target_version`` is what the rewritten file declares (the same when
    nothing needed rewriting). ``changes`` names every move, every State
    value added (entries starting ``"added "``) and the header change.
    """

    document: dict[str, Any]
    source_version: str | None
    target_version: str
    changes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.changes)

    @property
    def added(self) -> list[str]:
        """The State values the conversion added, as ``"State.<section>.<field> = <value> (why)"``."""
        return [change.removeprefix("added ") for change in self.changes if change.startswith("added ")]

    def conversion_note(self, tool: str) -> str:
        """One line for a runnable distribution's ``conversion`` field."""
        if not self.changes:
            return (
                f"BPX {self.source_version} file already in the BPX v1 layout; "
                f"nothing rewritten by {tool}."
            )
        rewritten = [change for change in self.changes if not change.startswith("added ")]
        note = (
            f"BPX {self.source_version} file in the v0.x layout, rewritten in the BPX v1 layout as "
            f"BPX {self.target_version} by {tool}: {'; '.join(rewritten)}."
        )
        if self.added:
            return (
                f"{note} Values added, which the file does not state: {'; '.join(self.added)}. "
                "The bpx package's own v0-to-v1 migration (bpx.convert_v0_to_v1) adds the same."
            )
        return f"{note} No values changed."

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.document, indent=indent, ensure_ascii=False) + "\n"

    def save(self, path: PathLike) -> Path:
        out = Path(path)
        out.write_text(self.to_json(), encoding="utf-8", newline="\n")
        return out


def upgrade_bpx(
    source: Mapping[str, Any] | str | Path | bytes, *, target_version: str = DEFAULT_TARGET_VERSION
) -> BpxUpgradeResult:
    """Rewrite a BPX file in the v0.x layout in the v1 layout, every value of the file kept.

    BPX 1.0 moved the initial and ambient temperatures out of ``Cell`` and the
    initial electrolyte concentration out of ``Electrolyte`` into a top-level
    ``State`` block, and took Cell's lumped thermal conductivity out of the
    schema (the parser asks for it in ``User-defined``). Every parser since
    1.0 rejects a file that declares 1.0 or later but keeps those fields in
    the old places, and some exporters write exactly that (the BattMo export
    of Schmitt et al. 2026 declares ``"BPX": 1.0``). This moves those fields,
    sets ``Header.BPX`` to ``target_version``, and adds the State values the
    v0.x layout has no field for, as the bpx package's own migration
    (``bpx.convert_v0_to_v1``) adds them: initial state of charge 1, the
    ambient temperature from the reference temperature (else 298.15 K) and
    the initial temperature from the ambient one, each only when the file
    has none. Every move and every added value is named in
    :attr:`BpxUpgradeResult.changes`. One difference from the bpx package:
    the thermal conductivity moves to ``User-defined`` instead of being
    dropped.

    The old layout is recognised by its fields or by a 0.x version, so a file
    declaring 1.1 with its temperatures still in Cell is rewritten too, and a
    document already in the v1 layout comes back unchanged. The conversion
    itself is :func:`battinfo._bpx_layout.to_v1_layout`, the module the
    registry vendors to check a runnable copy against its source.
    """
    data, _ = _load_bpx(source)
    if not isinstance(data.get("Header"), Mapping):
        raise ValueError("BPX document has no Header block.")
    declared = data["Header"].get("BPX")
    document, changes = to_v1_layout(data, target_version)
    source_label = None if declared is None else str(declared)
    target = target_version if changes else (source_label or target_version)
    return BpxUpgradeResult(document, source_label, target, changes)


def check_bpx(source: Mapping[str, Any] | str | Path | bytes) -> dict[str, Any]:
    """Parse a document with the official ``bpx`` package and report a file check.

    Parses the way PyBaMM does (legacy 0.x conversion on). Every warning the
    parser itself raises goes into the detail: a legacy conversion or a
    version-format deprecation (a file that only parses after conversion is
    not current), and the consistency checks, such as OCPs at the
    stoichiometry limits that overshoot a voltage cut-off. A file that parses
    with warnings still passes, and the detail names every one of them,
    first and in full, before the verdict (or the parser's error). Returns a
    ``checks`` entry for a parameter-file distribution. Needs
    ``pip install bpx``. A passing check means the parser accepts the file,
    not that a solver runs it: that is what a ``simulation_smoke`` check
    records.
    """
    try:
        import bpx as bpx_lib  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - bpx is a dev dependency
        raise ImportError("check_bpx needs the official parser: pip install bpx") from exc
    from importlib.metadata import PackageNotFoundError, version  # noqa: PLC0415

    try:
        tool = f"bpx {version('bpx')}"
    except PackageNotFoundError:  # pragma: no cover
        tool = "bpx"
    data, _ = _load_bpx(source)
    passed, detail, _missing = _parse_with_official_parser(data, bpx_lib)
    return {
        "check": "bpx_parse",
        "tool": tool,
        "passed": passed,
        "detail": detail,
        "checked_at": date.today().isoformat(),
    }


def _parse_with_official_parser(data: dict[str, Any], bpx_lib: Any) -> tuple[bool, str, list[str]]:
    """``(passed, detail, missing fields)`` from the official parser (see :func:`check_bpx`)."""
    bpx_dir = Path(bpx_lib.__file__).resolve().parent
    notes: set[str] = set()
    missing: list[str] = []

    def _keep_parser_warnings(message: Any, category: Any, filename: str, *_: Any, **__: Any) -> None:
        # Kept by where the warning was raised, not by what it says: the
        # consistency warnings never mention "bpx". The filename a warning
        # reports is wherever its stacklevel points: pydantic or this module
        # for some of bpx's own warnings, and bpx's own code for pyparsing's
        # deprecation noise. So look up the frame that called warn() instead.
        if _is_within(_warning_origin() or filename, bpx_dir):
            notes.add(str(message).strip())

    with _warnings.catch_warnings():
        _warnings.simplefilter("always")
        _warnings.showwarning = _keep_parser_warnings
        try:
            bpx_lib.parse_bpx_obj(copy.deepcopy(data))
            passed, detail = True, "Parsed by the official bpx parser."
        except Exception as exc:  # noqa: BLE001 - any parse failure is the finding
            passed = False
            lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
            lines = [line for line in lines if not line.startswith("For further information")]
            detail = " ".join(lines)
            errors = getattr(exc, "errors", None)
            if callable(errors):  # pydantic: which required fields are absent
                missing = [
                    ".".join(str(part) for part in error.get("loc", ()))
                    for error in errors()
                    if isinstance(error, Mapping) and error.get("type") == "missing"
                ]
    if notes:
        # Every warning, in full: a truncated list hides the rest.
        detail = f"Parser warnings: {' | '.join(sorted(notes)).rstrip('.')}. {detail}"
    return passed, detail, missing


# Modules that make up the warnings machinery itself (Python 3.14 moved the
# pure-Python half into _py_warnings).
_WARNINGS_MODULES = frozenset({"warnings", "_py_warnings"})


def _warning_origin() -> str | None:
    """From inside a ``showwarning`` hook: the file of the code that called ``warn()``."""
    getframe = getattr(sys, "_getframe", None)
    if getframe is None:  # pragma: no cover - not CPython
        return None
    frame = getframe(2)  # skip this function and the hook calling it
    while frame is not None and frame.f_globals.get("__name__") in _WARNINGS_MODULES:
        frame = frame.f_back
    return frame.f_code.co_filename if frame is not None else None


def _is_within(path: str, directory: Path) -> bool:
    try:
        Path(path).resolve().relative_to(directory)
    except (OSError, ValueError):
        return False
    return True


class _BpxFileEntry(dict):  # type: ignore[type-arg]
    """A ``distributions`` entry: a plain dict to JSON and the schema.

    It also remembers the parameters digest of the bytes it was made from,
    outside the dict, so :meth:`BpxParameterImportResult.to_parameter_set`
    can tell a copy with other bytes but the same parameters from another
    file.
    """

    parameters_sha256: str | None = None


def bpx_file_distribution(
    file: str | Path | bytes,
    *,
    content_url: str,
    role: str = "source",
    name: str | None = None,
    conforms_to: str | None = None,
    derived_from: str | None = None,
    conversion: str | None = None,
    software_requirements: list[str] | None = None,
    checks: list[Mapping[str, Any]] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """A parameter-file ``distributions`` entry for one BPX file.

    Hashes the exact bytes (the checksum a downloader verifies) and reads
    ``Header.BPX`` for ``conforms_to`` unless given. ``content_url`` is the
    https URL where an immutable copy of those bytes is served. Roles:
    ``source`` is the file as its authors published it; ``mirror`` is the
    same bytes served elsewhere (pass the same file, so the checksums
    agree); ``runnable`` is a declared conversion, made with
    :func:`upgrade_bpx` only when the official parser rejects the source,
    and needs ``derived_from`` (the source file's sha256, bare hex or
    ``sha256:<hex>``) and ``conversion`` (what changed, by which tool:
    :meth:`BpxUpgradeResult.conversion_note`). ``software_requirements``
    names what a solver needs beyond BPX itself, such as
    ``["aepybamm>=0.2.3"]`` for a file whose User-defined block holds
    About:Energy's functions. The file is parsed as strictly as the import
    parses it (no repeated keys).
    """
    if role not in ("source", "runnable", "mirror"):
        raise ValueError(f"role must be 'source', 'runnable' or 'mirror'; got {role!r}.")
    if not isinstance(content_url, str) or not content_url.startswith("https://"):
        raise ValueError(f"content_url must be an https URL; got {content_url!r}.")
    if isinstance(file, (bytes, bytearray)):
        raw = bytes(file)
        file_name = name or "parameters.bpx.json"
    else:
        path = Path(file)
        raw = _read_bytes(path)
        file_name = name or path.name
    document = _parse_bpx_bytes(raw, file_name)
    if conforms_to is None:
        _title, header_version, _model, _desc = _extract_header(document)
        if header_version is None:
            raise ValueError(f"{file_name} has no Header.BPX version; pass conforms_to=.")
        conforms_to = f"BPX {header_version}"
    entry = _BpxFileEntry(
        {
            "type": "DataDownload",
            "name": file_name,
            "role": role,
            "content_url": content_url,
            "encoding_format": "application/json",
            "conforms_to": conforms_to,
            "byte_size": len(raw),
            "checksum": {"algorithm": "sha256", "value": hashlib.sha256(raw).hexdigest()},
        }
    )
    entry.parameters_sha256 = hashlib.sha256(canonical_json_bytes(document)).hexdigest()
    if description:
        entry["description"] = description
    if role == "runnable":
        if not derived_from or not conversion:
            raise ValueError("a runnable file needs derived_from= (source sha256) and conversion=.")
        digest = derived_from.removeprefix("sha256:").lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("derived_from must be a sha256 hex digest (optionally 'sha256:'-prefixed).")
        entry["derived_from"] = f"sha256:{digest}"
        entry["conversion"] = conversion
    elif derived_from or conversion:
        raise ValueError("derived_from/conversion only apply to role='runnable'.")
    if software_requirements:
        entry["software_requirements"] = [str(item) for item in software_requirements]
    if checks:
        entry["checks"] = [dict(check) for check in checks]
    return entry


@dataclass
class BpxParameterImportResult:
    """Result of :func:`from_bpx_parameters`: one BPX file, read as parts.

    Attributes
    ----------
    parts:
        The file's claims grouped by part, in canonical order (cell,
        negative_material, negative_electrode, positive_material,
        positive_electrode, separator, electrolyte, state), each
        ``{"part": ..., "claims": [...]}``. For inspection: the record
        :meth:`to_parameter_set` builds re-reads the file, so editing these
        lists cannot change what the record's IRI names.
    title / bpx_version / model_type / description / source_file:
        BPX header fields, as in :class:`BpxImportResult`.
    references:
        The ``Header.References`` provenance string.
    annex:
        The ``Parameterisation.User-defined`` block verbatim: BPX's extension
        point, with no standard semantics, carried on the record so a
        re-export reproduces it.
    warnings:
        Every value the file holds that is not a claim or the annex, named
        (blended-electrode Particle blocks, initial hysteresis state,
        Degradation, Validation series, unknown fields), plus skipped values.
    not_imported:
        The BPX paths of those values (``"Parameterisation/Negative
        electrode/Particle"``, ``"State/Degradation"``, ``"Validation"``):
        the record's ``not_imported``, so a reader of the record knows what
        only the source file holds.
    content_digest:
        SHA-256 of the file's RFC 8785 canonical JSON (:func:`bpx_content_digest`):
        the record's ``parameters_sha256``, from which its IRI derives.
    source_sha256:
        SHA-256 of the exact bytes read, for a path or bytes input (``None``
        for a dict): the checksum the source distribution must carry.
    """

    parts: list[dict[str, Any]]
    title: str | None
    bpx_version: str | None
    model_type: str | None
    description: str | None
    source_file: str | None
    references: str | None = None
    annex: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    not_imported: list[str] = field(default_factory=list)
    content_digest: str | None = None
    source_sha256: str | None = None
    _document: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def file_uid(self) -> str | None:
        """The uid of the record this file becomes (IDENTIFIER_POLICY 6.3).

        Known before the record is built, so the file can be uploaded under
        its record's uid first. ``None`` when the import has no digest.
        """
        if self.content_digest is None:
            return None
        from battinfo.api._parameters import parameter_file_uid  # noqa: PLC0415

        return parameter_file_uid(self.content_digest)

    def to_parameter_set(
        self,
        *,
        cell_spec_id: str | None = None,
        cell_instance_id: str | None = None,
        virtual_cell: bool = False,
        materials: Mapping[str, str] | None = None,
        distributions: list[Mapping[str, Any]] | None = None,
        source_file: str | Path | bytes | None = None,
        runnable_file: str | Path | bytes | None = None,
        supersedes: str | None = None,
        name: str | None = None,
        default_provenance_class: str | None = "fitted",
        provenance_classes: Mapping[str, str | None] | None = None,
        **record_kwargs: Any,
    ) -> dict[str, Any]:
        """Build the file's one parameter-set record.

        Say which cell the file describes, with exactly one of
        ``cell_spec_id`` (a cell spec already in the genome),
        ``cell_instance_id`` (the one physical cell a fit was made on) or
        ``virtual_cell=True`` (no real cell). BattINFO never guesses, and it
        creates no cell record: a cell that is not in the genome yet is
        described first (identity only: name, maker, model, format,
        chemistry), and its BPX numbers stay on this record as cell claims.

        ``materials`` names what each electrode's material part is about,
        ``{"negative": ..., "positive": ...}``, as a curated material-kind
        key/alias (:func:`battinfo.materials.material_kind_keys` lists them)
        or a material-spec IRI: BPX does not name its materials, and a named
        part is what lets its claims be found by material. Naming the
        material of a blended electrode raises: its per-particle values are
        not imported yet, so there is no material part to name.

        ``distributions`` attaches the file (entries from
        :func:`bpx_file_distribution`): exactly one ``source``, at most one
        ``runnable`` conversion naming the source's checksum, and mirrors of
        the source's bytes. A file is required to publish the record and
        optional for local work. The source must be the file these
        parameters were read from. For a path or bytes import its checksum
        must equal :attr:`source_sha256`. For a dict import, or to attach a
        copy with other bytes but the same parameters (a CRLF checkout, a
        re-indented file), pass ``source_file=`` (its bytes or path): its
        parameters must match, and the source entry must carry its checksum.
        A ``runnable`` entry needs ``runnable_file=`` (its bytes or path):
        its sha256 must be the entry's checksum, and its parameters must be
        those of :func:`upgrade_bpx` applied to this file, so a runnable
        copy can only be this file's layout conversion.

        ``supersedes`` names the record (a spec IRI) of an earlier file this
        one corrects: a corrected file has other parameters, so it is a new
        record with a new IRI that points back at the old one.

        ``record_kwargs`` (description, citation, citation_doi, source_url,
        notes, license, retrieved_at, ...) pass to
        :func:`battinfo.api.create_parameter_set`. The header's
        ``Description`` and ``References`` fill description and citation
        (or a note) unless given. The record validates against the
        parameter-set schema.

        Each claim may say how its value was obtained (``provenance_class``:
        measured, fitted, literature, assumed or derived). BPX does not say,
        so the claims of the cell and state parts get no class: the file's
        capacity, cut-offs, geometry, temperatures and initial state of
        charge may as well be datasheet values or conventions as fits. The
        electrode, material, separator and electrolyte parts get
        ``default_provenance_class`` (``"fitted"``; ``None`` for no class).
        ``provenance_classes`` sets the class of a whole part by its name,
        for example ``{"cell": "measured"}`` or ``{"separator": None}``.
        """
        from battinfo._util import _citation_url_value  # noqa: PLC0415
        from battinfo.api import create_parameter_set  # noqa: PLC0415

        links = [
            link
            for link, value in (
                ("cell_spec_id", cell_spec_id),
                ("cell_instance_id", cell_instance_id),
                ("virtual_cell", True if virtual_cell else None),
            )
            if value is not None
        ]
        if len(links) != 1:
            raise ValueError(
                "say which cell this file describes: pass exactly one of cell_spec_id= (a cell "
                "spec in the genome), cell_instance_id= (the physical cell it was fitted on) or "
                f"virtual_cell=True (no real cell); got {links or 'none'}."
            )
        part_classes = _part_provenance_classes(default_provenance_class, provenance_classes)
        _check_record_kwargs(record_kwargs)
        if self.content_digest is None or bpx_content_digest(self._document) != self.content_digest:
            raise ValueError(
                "this import no longer holds the document it was read from; import the file again."
            )
        # Re-read the file rather than trusting self.parts: the IRI names the
        # file's parameters, so the record must say exactly what the file says.
        parts, annex, _warnings, not_imported = _parse_bpx_parameters(self._document)

        if materials is not None and not isinstance(materials, Mapping):
            raise TypeError(
                f"materials is a mapping {{'negative': ..., 'positive': ...}}, not {type(materials).__name__}."
            )
        materials = dict(materials or {})
        unknown_sides = sorted(set(materials) - set(_BPX_ELECTRODE_BLOCKS))
        if unknown_sides:
            raise ValueError(
                f"materials keys are 'negative' and 'positive'; got {', '.join(unknown_sides)}."
            )
        for side, block_name in _BPX_ELECTRODE_BLOCKS.items():
            part = next((p for p in parts if p["part"] == f"{side}_material"), None)
            target = materials.get(side)
            if part is None:
                if target is not None:
                    raise ValueError(self._no_material_part(side, block_name))
                continue
            if target is None:
                self._warn(
                    f"The {side} electrode material part names no material: BPX does not name "
                    f"its materials, so pass materials={{'{side}': '<kind or material-spec IRI>'}} "
                    "to make its claims findable by material."
                )
                continue
            part.update(_material_target(target, side))
        for part in parts:
            part_class = part_classes.get(part["part"])
            if part_class is not None:
                for claim in part["claims"]:
                    claim.setdefault("provenance_class", part_class)

        if distributions is not None:
            if not isinstance(distributions, list):
                raise TypeError(
                    "distributions is a list of entries from bpx_file_distribution(), not "
                    f"{type(distributions).__name__}; wrap a single entry in a list."
                )
            for index, entry in enumerate(distributions):
                if not isinstance(entry, Mapping):
                    raise TypeError(
                        f"distributions[{index}] is a {type(entry).__name__}; each entry is a dict "
                        "from bpx_file_distribution()."
                    )
        if distributions:
            self._check_source_file(distributions, source_file)
            self._check_runnable_file(distributions, runnable_file)
        else:
            for given, what in ((source_file, "source_file"), (runnable_file, "runnable_file")):
                if given is not None:
                    raise ValueError(f"{what}= checks an attached file: pass distributions= too.")

        record_kwargs = dict(record_kwargs)
        if self.description is not None:
            record_kwargs.setdefault("description", self.description)
        if (
            self.references is not None
            and "citation" not in record_kwargs
            and "citation_doi" not in record_kwargs
        ):
            # provenance.citation is URI-typed: a URL/DOI goes there, free text
            # rides a note verbatim (to_bpx reads it back into the header).
            citation_value = _citation_url_value(self.references)
            if isinstance(citation_value, str) and citation_value.startswith(("http://", "https://")):
                record_kwargs["citation"] = self.references
            else:
                notes = list(record_kwargs.get("notes") or [])
                notes.append(f"{_REFERENCES_NOTE_PREFIX}{self.references}")
                record_kwargs["notes"] = notes
        model_context = {
            "tool": "BPX",
            **({"name": self.title} if self.title else {}),
            **({"model": self.model_type} if self.model_type else {}),
            **({"version": self.bpx_version} if self.bpx_version else {}),
            # The layout the file actually uses: a file declaring 1.0 may
            # still keep the v0.x one, and a v1 export must then convert it.
            "layout": "v0" if is_v0_layout(self._document) else "v1",
        }
        link_kwargs: dict[str, Any] = {
            "cell_spec_id": {"cell_spec_id": cell_spec_id},
            "cell_instance_id": {"cell_instance_id": cell_instance_id},
            "virtual_cell": {"virtual_cell": True},
        }[links[0]]
        record = create_parameter_set(
            name=name or self.title or self.source_file or "BPX import",
            parts=parts,
            parameters_sha256=self.content_digest,
            model_context=model_context,
            **({"annex": annex} if annex else {}),
            **({"not_imported": not_imported} if not_imported else {}),
            **({"distributions": [dict(d) for d in distributions]} if distributions else {}),
            **({"supersedes": supersedes} if supersedes is not None else {}),
            default_provenance_class=None,  # set per part above
            **link_kwargs,
            **record_kwargs,
        )
        if distributions:
            from battinfo.api._parameters import parameter_file_issues  # noqa: PLC0415

            for _code, severity, _path, message in parameter_file_issues(record["parameter_set"]):
                if severity == "warning":
                    self._warn(message)
        return record

    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def _no_material_part(self, side: str, block_name: str) -> str:
        block = (self._document.get("Parameterisation") or {}).get(block_name)
        if isinstance(block, Mapping) and block.get("Particle") is not None:
            phases = block["Particle"]
            named = ", ".join(map(str, phases)) if isinstance(phases, Mapping) else "its phases"
            return (
                f"materials[{side!r}] names a material, but the {side} electrode is blended ({named}): "
                "its particle values sit in a Particle block, which is not imported yet, so there is "
                f"no {side} material part to name. Leave {side!r} out of materials."
            )
        return (
            f"materials[{side!r}] names a material, but the file has no {side} electrode material "
            f"values, so there is no {side} material part to name. Leave {side!r} out of materials."
        )

    def _check_source_file(
        self, distributions: list[Mapping[str, Any]], source_file: str | Path | bytes | None
    ) -> None:
        """The attached source must be the file these parameters were read from."""
        sources = [d for d in distributions if isinstance(d, Mapping) and d.get("role") == "source"]
        if len(sources) != 1:
            raise ValueError(
                "distributions need exactly one role='source' entry: the file these parameters "
                f"were read from (got {len(sources)})."
            )
        checksum = sources[0].get("checksum")
        attached = checksum.get("value") if isinstance(checksum, Mapping) else None
        if source_file is not None:
            raw = _file_bytes(source_file)
            document = _parse_bpx_bytes(raw, "source_file")
            if bpx_content_digest(document) != self.content_digest:
                raise ValueError(
                    "source_file holds other parameters than the ones imported (its RFC 8785 "
                    "digest differs), so it cannot be this record's source."
                )
            expected = hashlib.sha256(raw).hexdigest()
        elif self.source_sha256 is not None:
            expected = self.source_sha256
        else:
            raise ValueError(
                "these parameters were imported from a dict, so the attached source cannot be "
                "checked against them: pass source_file= (the source file's bytes or path)."
            )
        if attached == expected:
            return
        same_parameters = getattr(sources[0], "parameters_sha256", None) == self.content_digest
        if same_parameters and source_file is None:
            raise ValueError(
                "the attached source file holds the same parameters as the file read, in other "
                f"bytes (a CRLF checkout or a re-indented copy, for example): its checksum is "
                f"{attached}, the bytes read have sha256 {expected}. To attach that copy, pass "
                "source_file= (its bytes or path) as well."
            )
        raise ValueError(
            "the attached source file is not the file these parameters were read from: its "
            f"checksum is {attached}, the file read has sha256 {expected}. If it is the same file "
            "in other bytes (a CRLF checkout, a re-indented copy), pass source_file= (its bytes or "
            "path) and build the source entry from those bytes."
        )

    def _check_runnable_file(
        self, distributions: list[Mapping[str, Any]], runnable_file: str | Path | bytes | None
    ) -> None:
        """An attached runnable copy must be the layout conversion of this file, byte-checked."""
        runnables = [d for d in distributions if d.get("role") == "runnable"]
        if not runnables:
            if runnable_file is not None:
                raise ValueError("runnable_file= checks an attached runnable copy, and distributions has none.")
            return
        if runnable_file is None:
            raise ValueError(
                "distributions holds a runnable copy, so pass runnable_file= (its bytes or path): "
                "its sha256 must be the entry's checksum, and it must be upgrade_bpx() of this file."
            )
        if len(runnables) > 1:
            return  # the record builder refuses a second runnable copy
        entry = runnables[0]
        raw = _file_bytes(runnable_file)
        checksum = entry.get("checksum")
        declared = checksum.get("value") if isinstance(checksum, Mapping) else None
        actual = hashlib.sha256(raw).hexdigest()
        if declared != actual:
            raise ValueError(
                f"runnable_file is not the attached runnable copy: the entry's checksum is {declared}, "
                f"runnable_file has sha256 {actual}."
            )
        runnable = _parse_bpx_bytes(raw, "runnable_file")
        expected = upgrade_bpx(self._document).document
        if bpx_content_digest(runnable) != bpx_content_digest(expected):
            differing = _differing_paths(expected, runnable)
            raise ValueError(
                "the runnable copy is not the layout conversion of this file: its parameters differ "
                "from upgrade_bpx() of the file read"
                + (f" at {', '.join(differing)}" if differing else "")
                + ". A runnable copy may only move fields to the BPX v1 layout; make it with "
                "upgrade_bpx(source).save(path)."
            )
        if bpx_content_digest(runnable) == self.content_digest:
            # The conversion changed nothing: the source is already in the v1
            # layout, whether or not its entry carries a bpx_parse check.
            self._warn(
                "the runnable copy holds the same parameters as the source (upgrade_bpx() changes "
                "nothing in a file already in the v1 layout), so it is not needed: a runnable copy "
                "is made only when the official parser rejects the source."
            )


def _file_bytes(file: str | Path | bytes) -> bytes:
    return bytes(file) if isinstance(file, (bytes, bytearray)) else _read_bytes(Path(file))


def _differing_paths(expected: Any, actual: Any, path: str = "", limit: int = 5) -> list[str]:
    """Up to ``limit`` paths where two parsed documents differ (``"Parameterisation.Cell.Volume [m3]"``)."""
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        found: list[str] = []
        for key in [*expected, *(k for k in actual if k not in expected)]:
            where = f"{path}.{key}" if path else str(key)
            if key not in expected or key not in actual:
                found.append(where)
            else:
                found.extend(_differing_paths(expected[key], actual[key], where, limit))
            if len(found) >= limit:
                return found[:limit]
        return found
    if canonical_json_bytes(expected) != canonical_json_bytes(actual):
        return [path or "(the document)"]
    return []


def _v0_layout_in_v1_file(document: Mapping[str, Any]) -> tuple[Any, list[str]] | None:
    """``(declared version, old fields)`` for a file that declares BPX 1.0 or later but keeps the v0.x layout."""
    header = document.get("Header")
    declared = header.get("BPX") if isinstance(header, Mapping) else None
    fields = v0_layout_fields(document)
    if not fields or not uses_v1_layout(declared):
        return None
    return declared, fields


def _material_target(value: Any, side: str) -> dict[str, str]:
    """A materials[...] value as a part's material target."""
    from battinfo.materials import resolve_material_kind  # noqa: PLC0415

    kind = resolve_material_kind(value) if isinstance(value, str) else None
    if kind is not None:
        return {"material_kind": kind}
    if isinstance(value, str) and value.startswith("https://w3id.org/battinfo/"):
        return {"material_spec_id": value}
    raise ValueError(
        f"materials[{side!r}] is {value!r}, which is neither a curated material kind nor a "
        "material-spec IRI (https://w3id.org/battinfo/spec/<uid>). "
        "battinfo.materials.material_kind_keys() lists the material kinds."
    )


# Parts whose BPX values carry no provenance class by default: BPX does not say
# how a cell's capacity, cut-offs, geometry or temperatures, or the initial
# state, were obtained, so calling them fitted would state something the file
# does not.
_PARTS_WITHOUT_DEFAULT_CLASS = ("cell", "state")


def _part_provenance_classes(
    default: Any, overrides: Mapping[str, Any] | None
) -> dict[str, str | None]:
    """The provenance class each part's claims get, by part name (``None``: no class)."""
    from battinfo.api._parameters import _PROVENANCE_CLASSES  # noqa: PLC0415
    from battinfo.parameters import PARAMETER_FILE_PARTS  # noqa: PLC0415

    def checked(value: Any, what: str) -> str | None:
        if value is None or value in _PROVENANCE_CLASSES:
            return value
        raise ValueError(
            f"{what} is {value!r}; a provenance class is one of {', '.join(_PROVENANCE_CLASSES)}, "
            "or None for no class."
        )

    default = checked(default, "default_provenance_class")
    classes: dict[str, str | None] = {
        part: None if part in _PARTS_WITHOUT_DEFAULT_CLASS else default for part in PARAMETER_FILE_PARTS
    }
    if overrides is None:
        return classes
    if not isinstance(overrides, Mapping):
        raise TypeError(
            "provenance_classes maps part names to provenance classes, for example "
            f"{{'cell': 'measured'}}; got {type(overrides).__name__}."
        )
    unknown = [str(part) for part in overrides if part not in PARAMETER_FILE_PARTS]
    if unknown:
        raise ValueError(
            f"provenance_classes keys are part names ({', '.join(PARAMETER_FILE_PARTS)}); "
            f"got {', '.join(repr(part) for part in unknown)}."
        )
    for part, value in overrides.items():
        classes[part] = checked(value, f"provenance_classes[{part!r}]")
    return classes


# Keywords of create_parameter_set that to_parameter_set sets from the file,
# or that belong to a claim batch; the others pass through as record fields.
_SET_FROM_THE_FILE = frozenset({
    "name", "claims", "parts", "material_kind", "material_spec_id", "cell_spec_id",
    "cell_instance_id", "virtual_cell", "parameters_sha256", "scope", "electrode_polarity",
    "model_context", "annex", "not_imported", "distributions", "supersedes",
    "default_provenance_class",
})


def _check_record_kwargs(record_kwargs: Mapping[str, Any]) -> None:
    """``TypeError`` naming a keyword ``to_parameter_set`` does not take, with a did-you-mean."""
    import difflib  # noqa: PLC0415
    import inspect  # noqa: PLC0415

    from battinfo.api._parameters import _record_from_parameter_set  # noqa: PLC0415

    passed_through = sorted(
        {*inspect.signature(_record_from_parameter_set).parameters, "validate"} - _SET_FROM_THE_FILE
    )
    unknown = [key for key in record_kwargs if key not in passed_through]
    if not unknown:
        return
    own = [
        name for name in inspect.signature(BpxParameterImportResult.to_parameter_set).parameters
        if name not in ("self", "record_kwargs")
    ]
    accepted = [*own, *passed_through]
    named = []
    for key in unknown:
        close = difflib.get_close_matches(key, accepted, n=1)
        named.append(f"{key}=" + (f" (did you mean {close[0]}=?)" if close else ""))
    raise TypeError(
        "to_parameter_set() got unknown keyword(s): " + ", ".join(named)
        + f". It takes {', '.join(own)}, and the record fields {', '.join(passed_through)}."
    )


def _short_repr(value: Any, limit: int = 80) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _bpx_value_to_claim(key: str, raw_value: Any, entry: Mapping[str, Any], unit: str) -> dict[str, Any] | None:
    """One BPX field value as a claim body (quantity/curve/expression), or None.

    The value is kept exactly as the file states it, in the unit BPX states
    it in, so the record says what the file says.
    """
    if isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, (int, float)):
        if not math.isfinite(raw_value):
            return None
        return {"parameter": key, "quantity": {"value": raw_value, "unit": unit}}
    if isinstance(raw_value, str) and raw_value.strip():
        return {
            "parameter": key,
            "expression": {"text": raw_value, "language": "bpx", "argument": "x"},
        }
    if isinstance(raw_value, Mapping) and set(raw_value) == {"x", "y"}:
        xs, ys = raw_value["x"], raw_value["y"]
        numeric = all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in [*(xs if isinstance(xs, list) else []), *(ys if isinstance(ys, list) else [])]
        )
        if isinstance(xs, list) and isinstance(ys, list) and len(xs) == len(ys) >= 2 and numeric:
            curve: dict[str, Any] = {
                "x_quantity": str(entry.get("x_quantity", "stoichiometry")),
                "x": list(xs),
                "y": list(ys),
                "y_unit": unit,
            }
            x_unit = {"concentration": "mol/m3", "temperature": "K"}.get(curve["x_quantity"])
            if x_unit:
                curve["x_unit"] = x_unit
            return {"parameter": key, "curve": curve}
    return None


# BPX field -> the OCP branch it tabulates (single-phase electrodes, BPX 1.0+).
_OCP_BRANCH_BY_FIELD: dict[str, str] = {field: branch for branch, field in _OCP_BRANCH_FIELDS.items()}

# Transport parameters that are strictly positive in a physics model: a scalar
# of zero or less in a BPX file is a placeholder, named in a warning. (A table
# may reach zero, for example a conductivity at zero concentration.)
_POSITIVE_TRANSPORT_KEYS = frozenset({
    "ionic_conductivity",
    "electrolyte_diffusivity",
    "transference_number",
    "solid_diffusivity",
    "electronic_conductivity",
    "transport_efficiency",
})


def _bpx_block_claims(
    block: Mapping[str, Any],
    vocab_block: str,
    label: str,
    warnings: list[str],
    not_imported: list[str],
    path: str,
) -> list[tuple[dict[str, Any], list[str]]]:
    """One BPX block's fields as ``(claim, scopes)`` pairs; every field read or named.

    ``path`` is the block's BPX path (``"Parameterisation/Cell"``); a field
    that is not read lands in ``not_imported`` under it.
    """
    from battinfo.parameters import bpx_field, parameter_entry, resolve_bpx_field  # noqa: PLC0415

    out: list[tuple[dict[str, Any], list[str]]] = []
    unknown: list[str] = []
    not_positive: list[str] = []
    for field_name, raw_value in block.items():
        branch = _OCP_BRANCH_BY_FIELD.get(str(field_name)) if vocab_block == "electrode" else None
        if branch is not None:
            # An OCP branch of a single-phase electrode: the ocp parameter,
            # as a curve that says which branch it is.
            entry = parameter_entry("ocp") or {}
            claim = _bpx_value_to_claim("ocp", raw_value, entry, "V")
            if claim is None or "curve" not in claim:
                warnings.append(
                    f"BPX {label} field '{field_name}' is {_short_repr(raw_value)}: an OCP branch is "
                    "read as a curve claim only, so this one is not read."
                )
                not_imported.append(f"{path}/{field_name}")
                continue
            claim["curve"]["branch"] = branch
            out.append((claim, list(entry.get("scopes", []))))
            continue
        key = resolve_bpx_field(vocab_block, field_name)
        mapping = bpx_field(key, vocab_block) if key is not None else None
        if key is None or mapping is None:
            unknown.append(str(field_name))
            not_imported.append(f"{path}/{field_name}")
            continue
        entry = parameter_entry(key) or {}
        claim = _bpx_value_to_claim(key, raw_value, entry, mapping["unit"])
        if claim is None:
            warnings.append(
                f"BPX {label} field '{field_name}' has unusable value {_short_repr(raw_value)}; "
                "not read as a claim."
            )
            not_imported.append(f"{path}/{field_name}")
            continue
        if key in _POSITIVE_TRANSPORT_KEYS and "quantity" in claim and claim["quantity"]["value"] <= 0:
            not_positive.append(f"{path}/{field_name} = {raw_value!r}")
        out.append((claim, list(entry.get("scopes", []))))
    if unknown:
        # EVERY field is named: a truncated list is a silent drop for the rest.
        warnings.append(
            f"BPX {label} fields with no parameter mapping, not read as claims: {', '.join(unknown)}"
        )
    if not_positive:
        warnings.append(
            "BPX transport values a physics model needs positive are zero or negative, which "
            "usually marks a placeholder (the file may model them elsewhere, for example in "
            "User-defined): " + "; ".join(not_positive) + ". They are read as claims as the file "
            "states them; check the source before using them."
        )
    return out


def _bpx_state_sections(
    data: Mapping[str, Any],
    blocks: dict[str, dict[str, Any]],
    warnings: list[str],
    not_imported: list[str],
    params_key: str,
) -> dict[str, Any]:
    """The file's State values by section, in the v1 layout.

    A v0.x-layout file keeps the fields BPX 1.0 moved into State in Cell and
    Electrolyte; they are taken out of ``blocks`` (copies) and read as the
    State values they are, so either layout gives the same state part.
    """
    raw_state = data.get("State")
    state: dict[str, Any] = {}
    if isinstance(raw_state, Mapping):
        state = {
            section: dict(fields) if isinstance(fields, Mapping) else fields
            for section, fields in raw_state.items()
        }
    elif raw_state is not None:
        warnings.append(f"BPX State is {_json_kind(raw_state)}, not an object; not read.")
        not_imported.append("State")
    for block_name, key, section, new_key in V1_STATE_MOVES:
        block = blocks.get(block_name)
        if not block or key not in block:
            continue
        value = block.pop(key)
        target = state.setdefault(section, {})
        if not isinstance(target, dict):
            warnings.append(
                f"BPX {block_name}.{key} not read: State.{section} is {_json_kind(target)}, "
                "not an object."
            )
            not_imported.append(f"{params_key}/{block_name}/{key}")
            continue
        if new_key in target and target[new_key] != value:
            warnings.append(
                f"BPX {block_name}.{key} ({_short_repr(value)}) and State.{section}.{new_key} "
                f"({_short_repr(target[new_key])}) disagree: the State value is read, the "
                f"{block_name} value is not."
            )
            not_imported.append(f"{params_key}/{block_name}/{key}")
            continue
        target[new_key] = value
    return state


# Header fields the import reads (model_context, description, references).
_BPX_HEADER_FIELDS = frozenset(
    {"BPX", "bpx", "Title", "title", "Model", "model", "Description", "description", "References", "references"}
)


def _parse_bpx_parameters(
    data: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    """One BPX document as ``(parts, annex, warnings, not_imported)``.

    Every value in the document becomes a claim in a part, rides the annex
    (User-defined, verbatim), or is named in a warning, and its BPX path is
    listed in ``not_imported``.
    """
    from battinfo.parameters import PARAMETER_FILE_PARTS  # noqa: PLC0415

    warnings: list[str] = []
    not_imported: list[str] = []
    params_key = next(
        (k for k in ("Parameterisation", "parameterisation", "parameters") if data.get(k)), "Parameterisation"
    )
    params_raw = data.get(params_key) or {}
    if not isinstance(params_raw, Mapping) or not params_raw:
        warnings.append("BPX file has no 'Parameterisation' block; no claims extracted.")
        if params_raw:
            not_imported.append(params_key)
        params_raw = {}
    old_layout = _v0_layout_in_v1_file(data)
    if old_layout is not None:
        warnings.append(
            f"The file declares BPX {old_layout[0]} but keeps the v0.x layout "
            f"({', '.join(old_layout[1])}), so the official parser rejects it: attach a runnable "
            "copy made with upgrade_bpx() for solvers."
        )
    blocks: dict[str, dict[str, Any]] = {
        name: dict(block) for name, block in params_raw.items() if isinstance(block, Mapping)
    }
    state = _bpx_state_sections(data, blocks, warnings, not_imported, params_key)
    claims: dict[str, list[dict[str, Any]]] = {}

    cell = blocks.get("Cell")
    if cell:
        claims["cell"] = [
            claim
            for claim, _ in _bpx_block_claims(cell, "cell", "Cell", warnings, not_imported, f"{params_key}/Cell")
        ]

    for side, block_name in _BPX_ELECTRODE_BLOCKS.items():
        block = blocks.get(block_name)
        if not block:
            continue
        particle = block.pop("Particle", None)
        if particle is not None:
            if isinstance(particle, Mapping):
                phases = "; ".join(
                    f"{phase}: {', '.join(map(str, fields)) if isinstance(fields, Mapping) else _short_repr(fields)}"
                    for phase, fields in particle.items()
                )
            else:
                phases = _short_repr(particle)
            warnings.append(
                f"BPX {block_name} Particle block (a blended electrode) not read as claims: "
                f"blended electrodes are not modelled yet, so the per-phase values stay in the "
                f"source file ({phases})."
            )
            not_imported.append(f"{params_key}/{block_name}/Particle")
        path = f"{params_key}/{block_name}"
        for claim, scopes in _bpx_block_claims(block, "electrode", block_name, warnings, not_imported, path):
            part = f"{side}_material" if "material" in scopes else f"{side}_electrode"
            claims.setdefault(part, []).append(claim)

    for block_name, vocab_block in (("Separator", "separator"), ("Electrolyte", "electrolyte")):
        block = blocks.get(block_name)
        if block:
            path = f"{params_key}/{block_name}"
            found = [
                claim
                for claim, _ in _bpx_block_claims(block, vocab_block, block_name, warnings, not_imported, path)
            ]
            if found:
                claims[vocab_block] = found

    state_claims, unread = _bpx_state_claims(state, warnings, not_imported)
    if state_claims:
        claims["state"] = state_claims
    if unread:
        # EVERY entry is named: a truncated list is a silent drop for the rest.
        warnings.append(
            "BPX State entries not read as claims (initial hysteresis state and Degradation have "
            "no BattINFO home yet; they stay in the source file): " + ", ".join(unread)
        )

    # The User-defined block is BPX's blessed extension point (tool- and
    # study-specific keys with no standard semantics): carried VERBATIM as the
    # record's annex so a re-export reproduces it, and named so the carry is
    # visible.
    user_defined_raw = params_raw.get("User-defined")
    annex: dict[str, Any] = (
        copy.deepcopy(dict(user_defined_raw)) if isinstance(user_defined_raw, Mapping) else {}
    )
    if annex:
        keys = [str(k) for k in annex]
        warnings.append(
            f"BPX User-defined block carried verbatim as the record's annex, not as claims "
            f"({len(keys)} keys: {', '.join(keys)}). These have no standard semantics; author "
            "them as explicit claims if they matter."
        )
    handled = {"Cell", *_BPX_ELECTRODE_BLOCKS.values(), "Separator", "Electrolyte", "User-defined"}
    for block_name, block in params_raw.items():
        if block_name not in handled:
            warnings.append(f"BPX Parameterisation block '{block_name}' is not recognised; not read.")
            not_imported.append(f"{params_key}/{block_name}")
        elif not isinstance(block, Mapping):
            warnings.append(
                f"BPX Parameterisation block '{block_name}' is {_json_kind(block)}, not an object; "
                "not read."
            )
            not_imported.append(f"{params_key}/{block_name}")
    # Header fields beyond the ones the record holds are named too: they are
    # part of the file's parameters (its digest covers them).
    header = data.get("Header") if isinstance(data.get("Header"), Mapping) else data.get("header")
    if isinstance(header, Mapping):
        extra = [str(key) for key in header if key not in _BPX_HEADER_FIELDS]
        if extra:
            warnings.append(f"BPX Header fields not read: {', '.join(extra)}")
            not_imported.extend(f"Header/{key}" for key in extra)
    # Top-level sections beyond Header/Parameterisation/State are named too.
    # Validation holds measured curves, not parameters: they stay in the
    # source file, and belong in a dataset record.
    for section, value in data.items():
        if section in _BPX_PARAMETER_SECTIONS:
            continue
        if section == "Validation" and isinstance(value, Mapping):
            series = [str(k) for k in value]
            warnings.append(
                f"BPX Validation block not read as claims ({len(series)} series: "
                f"{', '.join(series)}). The measured curves stay in the source "
                "file; describe them as a dataset record to make them findable."
            )
        else:
            warnings.append(f"BPX top-level section '{section}' is not recognised; not read.")
        not_imported.append(str(section))

    if not claims:
        warnings.append("No parameter claims found in the BPX file.")
    parts = [{"part": part, "claims": claims[part]} for part in PARAMETER_FILE_PARTS if claims.get(part)]
    return parts, annex, warnings, list(dict.fromkeys(not_imported))


def _bpx_state_claims(
    state: Mapping[str, Any], warnings: list[str], not_imported: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """The State values as state-part claims, plus the entries with no home (named by the caller).

    A section none of whose entries is read (Degradation) is one
    ``not_imported`` path; otherwise each unread entry is.
    """
    from battinfo.parameters import bpx_field, parameter_entry, resolve_bpx_field  # noqa: PLC0415

    claims: list[dict[str, Any]] = []
    unread: list[str] = []
    for section, fields in state.items():
        if not isinstance(fields, Mapping):
            unread.append(f"{section} ({_json_kind(fields)})")
            not_imported.append(f"State/{section}")
            continue
        section_unread: list[str] = []
        for field_name, raw_value in fields.items():
            key = resolve_bpx_field("state", field_name)
            mapping = bpx_field(key, "state") if key is not None else None
            if mapping is None or mapping.get("section") != section:
                unread.append(f"{section}.{field_name}")
                section_unread.append(str(field_name))
                continue
            claim = _bpx_value_to_claim(key, raw_value, parameter_entry(key) or {}, mapping["unit"])
            if claim is None:
                warnings.append(
                    f"BPX State.{section} field '{field_name}' has unusable value "
                    f"{_short_repr(raw_value)}; not read as a claim."
                )
                section_unread.append(str(field_name))
                continue
            claims.append(claim)
        if section_unread and len(section_unread) == len(fields):
            not_imported.append(f"State/{section}")
        else:
            not_imported.extend(f"State/{section}/{name}" for name in section_unread)
    return claims, unread


def _plain_json(value: Any) -> Any:
    """A parsed-JSON value with numpy scalars and arrays as the plain values they hold (a copy)."""
    value = _from_numpy(value)
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _read_bpx_source(
    source: Mapping[str, Any] | str | Path | bytes,
) -> tuple[dict[str, Any], str | None, str | None]:
    """``(document, file name, sha256 of the exact bytes)``; no bytes for a dict input.

    Bytes and files are parsed strictly: a byte order mark is skipped (the
    checksum still covers it), and a repeated key, a number too large for a
    double, NaN or Infinity are refused.
    """
    if isinstance(source, Mapping):
        return _plain_json(source), None, None
    if isinstance(source, (bytes, bytearray)):
        raw, file_name = bytes(source), None
    else:
        path = Path(source)
        raw = _read_bytes(path)
        file_name = path.name
    data = _parse_bpx_bytes(raw, file_name or "the BPX bytes")
    return data, file_name, hashlib.sha256(raw).hexdigest()


def from_bpx_parameters(source: Mapping[str, Any] | str | Path | bytes) -> BpxParameterImportResult:
    """Read a BPX file as the parts of one parameter-set record.

    Every value in the file becomes a claim in its part (cell, each
    electrode's material and build, separator, electrolyte, state), rides
    the annex (the ``User-defined`` block, verbatim), or is named in
    :attr:`BpxParameterImportResult.warnings` with its BPX path in
    :attr:`BpxParameterImportResult.not_imported`. The fields BPX 1.0 moved
    into ``State`` read the same from either layout. A single-phase
    electrode's OCP branches (``OCP (lithiation) [V]``, ``OCP
    (delithiation) [V]``) are ``ocp`` curves with their ``branch``. Call
    :meth:`BpxParameterImportResult.to_parameter_set` (or
    :func:`import_bpx_parameters`) to build the record.

    ``source`` is a path, the file's bytes, or a parsed dict. A path or bytes
    input also records the sha256 of the exact bytes, which the attached
    source file must match. A file that repeats a key in an object is
    refused, since JSON parsers disagree on which value counts.

    Examples
    --------
    >>> result = from_bpx_parameters("nmc_pouch_cell_BPX.json")       # doctest: +SKIP
    >>> record = result.to_parameter_set(
    ...     virtual_cell=True,
    ...     materials={"negative": "graphite", "positive": "nmc111"},
    ... )                                                              # doctest: +SKIP
    """
    data, source_file, source_sha256 = _read_bpx_source(source)
    content_digest = bpx_content_digest(data)
    title, bpx_version, model_type, description = _extract_header(data)
    parts, annex, warnings, not_imported = _parse_bpx_parameters(data)
    return BpxParameterImportResult(
        parts=parts,
        title=title,
        bpx_version=bpx_version,
        model_type=model_type,
        description=description,
        source_file=source_file,
        references=_extract_references(data),
        annex=annex,
        warnings=warnings,
        not_imported=not_imported,
        content_digest=content_digest,
        source_sha256=source_sha256,
        _document=data,
    )


def import_bpx_parameters(
    source: Mapping[str, Any] | str | Path | bytes, **kwargs: Any
) -> dict[str, Any]:
    """One-call form of ``from_bpx_parameters(source).to_parameter_set(**kwargs)``.

    Returns the record. Use the two-step form to read the warnings.
    """
    return from_bpx_parameters(source).to_parameter_set(**kwargs)


def _instance_reference(
    meta: Mapping[str, Any], cell_instance: Mapping[str, Any] | Any | None
) -> str | None:
    """Build a Header.References provenance string from spec/instance identity."""
    parts: list[str] = []
    spec_id = meta.get("id") or meta.get("identifier")
    if spec_id:
        parts.append(f"cell spec {spec_id}")
    if cell_instance is not None:
        if hasattr(cell_instance, "to_record") and callable(cell_instance.to_record):
            cell_instance = cell_instance.to_record()
        ci = cell_instance.get("cell_instance") if isinstance(cell_instance, Mapping) else None
        ci = ci if isinstance(ci, Mapping) else (cell_instance if isinstance(cell_instance, Mapping) else {})
        serial = ci.get("serial_number")
        inst_id = ci.get("id")
        if serial:
            parts.append(f"cell instance serial {serial}")
        elif inst_id:
            parts.append(f"cell instance {inst_id}")
    return "; ".join(parts) if parts else None
