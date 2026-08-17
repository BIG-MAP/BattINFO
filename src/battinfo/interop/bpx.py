"""Import battery parameters from a BPX file into BattINFO cell-spec specs.

BPX (Battery Parameter eXchange) is a JSON format developed by the PyBaMM
project for sharing battery physics parameters.  This module extracts the
subset of BPX parameters that correspond to cell-spec specification properties
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
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from battinfo.interop._common import load_json_source

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

    def to_cell_spec_kwargs(self) -> dict[str, Any]:
        """Return kwargs suitable for ``Workspace.cell_spec(specs=..., name=...)``.

        The caller is responsible for providing ``manufacturer``, ``model``,
        ``format``, and ``chemistry`` — BPX does not carry those fields.
        """
        kwargs: dict[str, Any] = {"properties": dict(self.specs)}
        if self.title is not None:
            kwargs["name"] = self.title
        return kwargs


# ── Internal helpers ──────────────────────────────────────────────────────────


def _load_bpx(source: Mapping[str, Any] | str | Path) -> tuple[dict[str, Any], str]:
    """Load a BPX source (dict, JSON string, or path) and return (data, filename)."""
    if isinstance(source, Mapping):
        return dict(source), "bpx-parameter.json"
    path = Path(source)
    data = load_json_source(path)
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
    known_no_spec: list[str] = []  # in our table, deliberately no BattINFO equivalent
    unknown: list[str] = []        # not in our table at all

    for bpx_key, raw_value in cell_params.items():
        if bpx_key not in _BPX_CELL_MAP:
            unknown.append(bpx_key)
            continue
        mapping = _BPX_CELL_MAP[bpx_key]
        if mapping is None:
            # Explicitly mapped to None — a recognised physics/transport parameter
            # with no cell-level spec equivalent.
            known_no_spec.append(bpx_key)
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

    if known_no_spec:
        warnings.append(
            f"BPX Cell parameters with no BattINFO spec equivalent "
            f"(physics/transport parameters — not cell-level specs): "
            f"{', '.join(known_no_spec[:8])}"
            + (" …" if len(known_no_spec) > 8 else "")
        )
    if unknown:
        warnings.append(
            f"Unknown BPX Cell parameters (not recognised): "
            f"{', '.join(unknown[:8])}"
            + (" …" if len(unknown) > 8 else "")
        )
    return specs


# ── Public API ────────────────────────────────────────────────────────────────


def from_bpx(
    source: Mapping[str, Any] | str | Path,
    *,
    extra_warnings: bool = True,
) -> BpxImportResult:
    """Import cell-spec specs from a BPX battery parameter file.

    Extracts the subset of BPX ``Parameterisation.Cell`` parameters that map
    directly to BattINFO cell-spec spec properties (capacity, voltage limits,
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
        Contains ``specs`` ready for ``Workspace.cell_spec(specs=...)``,
        along with title, version, and any warnings.

    Examples
    --------
    >>> result = from_bpx("mohtat2021.json")
    >>> ws.cell_spec(
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
        warnings=warnings,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Export:  BattINFO cell spec / instance  ──►  BPX file
# ══════════════════════════════════════════════════════════════════════════════
#
# A BPX file parameterises a *physics* model (DFN/SPMe): it needs electrode
# microstructure, transport coefficients, and OCP functions that a cell
# specification or datasheet simply does not contain.  ``to_bpx`` therefore
# emits a BPX ``"Partial"`` document — a valid Header plus the cell-level
# ``Parameterisation.Cell`` block populated with everything derivable from the
# spec — and reports the required physics parameters it could not fill, instead
# of inventing them.  This is the "as much information as is available" contract.

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
_BPX_EXPORT_DIRECT: dict[str, tuple[str, dict[str, float], bool]] = {
    "nominal_capacity":            ("Nominal cell capacity [A.h]", _CAP_TO_AH, True),
    "charging_cutoff_voltage":     ("Upper voltage cut-off [V]",   _VOLT_TO_V, True),
    "discharging_cutoff_voltage":  ("Lower voltage cut-off [V]",   _VOLT_TO_V, True),
}

# Required BPX Cell keys that a cell spec can never supply on its own.
_BPX_REQUIRED_UNFILLABLE: tuple[str, ...] = (
    "Electrode area [m2]",
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
        A BPX document (``{"Header": ..., "Parameterisation": {"Cell": ...}}``)
        with the ``"Partial"`` model type and every cell-level parameter that
        could be derived from the spec.
    filled:
        BPX Cell keys that were populated from the spec.
    missing_required:
        Required BPX Cell keys that could not be filled — the user must supply
        these (or run a physics-parameterisation workflow) before the file can
        drive a full model.
    warnings:
        Non-fatal notes (unconvertible units, absent dimensions, etc.).
    """

    bpx: dict[str, Any]
    filled: list[str]
    missing_required: list[str]
    warnings: list[str] = field(default_factory=list)

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
    model: str = "Partial",
    bpx_version: str = _BPX_VERSION,
    reference_temperature_k: float | None = _DEFAULT_REFERENCE_TEMPERATURE_K,
    title: str | None = None,
) -> BpxExportResult:
    """Export a BattINFO cell spec (and optional instance) to a BPX document.

    Populates the BPX ``Parameterisation.Cell`` block with everything derivable
    from the specification — nominal capacity, voltage cut-offs, and (when cell
    dimensions are present) volume, external surface area, and density — and
    reports the required physics parameters that a spec cannot provide.

    Parameters
    ----------
    source:
        A BattINFO cell-spec record dict (``{"cell_spec": ..., "properties":
        ...}``), a :class:`~battinfo.bundle.CellSpec` (anything exposing
        ``to_record()``), or a bare properties mapping.
    cell_instance:
        Optional cell-instance record or object; its serial number / id is
        recorded in the BPX ``Header`` so an exported file traces back to a
        physical cell.
    model:
        BPX ``Header.Model`` value. Defaults to ``"Partial"`` — the correct type
        for a spec-only export. Use ``"SPMe"`` / ``"DFN"`` only once the physics
        sections have been completed downstream.
    bpx_version:
        Value stamped into ``Header.BPX``.
    reference_temperature_k:
        Conventional ``"Reference temperature [K]"`` to emit when the spec gives
        none. Pass ``None`` to omit it.
    title:
        Override ``Header.Title``; defaults to the spec name/model.

    Returns
    -------
    BpxExportResult
        The BPX document plus ``filled`` / ``missing_required`` / ``warnings``.

    Examples
    --------
    >>> import json
    >>> record = json.load(open("examples/cell-spec/A123__ANR26650M1-B.json"))
    >>> result = to_bpx(record)
    >>> result.save("a123.bpx.json")          # doctest: +SKIP
    >>> result.missing_required
    ['Electrode area [m2]', 'Number of electrode pairs connected in parallel to make a cell', ...]
    """
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

    # 2. Geometry-derived volume, surface area, and density.
    volume, area = _geometry(props, meta.get("cell_format"), warnings)
    if volume is not None:
        cell["Volume [m3]"] = volume
        filled.append("Volume [m3]")
    if area is not None:
        cell["External surface area [m2]"] = area
        filled.append("External surface area [m2]")

    mass = _scalar(props, "mass")
    if mass is not None and volume:
        mass_kg = _convert(mass[0], mass[1], _MASS_TO_KG, warnings, "mass")
        if mass_kg is not None:
            cell["Density [kg.m-3]"] = _sig6(mass_kg / volume)
            filled.append("Density [kg.m-3]")

    # 3. Conventional reference temperature.
    if reference_temperature_k is not None:
        cell["Reference temperature [K]"] = float(reference_temperature_k)
        filled.append("Reference temperature [K]")

    # 4. Required BPX Cell keys a spec can never supply.
    missing_required = [
        bpx_key
        for _bi_key, (bpx_key, _table, required) in _BPX_EXPORT_DIRECT.items()
        if required and bpx_key not in cell
    ]
    missing_required.extend(_BPX_REQUIRED_UNFILLABLE)

    if missing_required:
        warnings.append(
            "Required BPX Cell parameters not derivable from a cell spec "
            "(supply these before driving a full model): "
            + ", ".join(missing_required)
        )
    warnings.append(
        "Electrode, electrolyte, and separator physics parameters "
        "(thickness, porosity, transport, OCP, particle data) are not part of a "
        "cell specification and were not emitted. Header.Model is 'Partial'."
    )

    header: dict[str, Any] = {"BPX": bpx_version, "Model": model}
    if name:
        header["Title"] = str(name)
    header["Description"] = (
        "Partial BPX exported from a BattINFO cell specification"
        + (f" ('{name}')" if name else "")
        + ". Cell-level parameters only; physics parameters are not derivable "
        "from a specification and must be added separately."
    )
    references = _instance_reference(meta, cell_instance)
    if references:
        header["References"] = references

    bpx_doc: dict[str, Any] = {
        "Header": header,
        "Parameterisation": {"Cell": cell},
    }

    return BpxExportResult(
        bpx=bpx_doc,
        filled=filled,
        missing_required=missing_required,
        warnings=warnings,
    )


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


# ══════════════════════════════════════════════════════════════════════════════
# Import:  BPX physics parameters  ──►  parameter-set claim records
# ══════════════════════════════════════════════════════════════════════════════
#
# :func:`from_bpx` deliberately imports only the cell-level spec subset; the
# physics parameters (microstructure, transport, kinetics, OCPs) now have a
# home — ``parameter-set`` records. One BPX file = one source making claims
# about several targets: each electrode's *material* parameters (targeting a
# material kind or material spec the caller names), and the *build* parameters
# (electrode thickness/porosity, separator, electrolyte) targeting the cell
# spec the file parameterises. BPX value forms map 1:1 onto claim forms:
# number → quantity, {"x": [...], "y": [...]} → curve, "expression string" →
# expression(language="bpx").

_BPX_ELECTRODE_BLOCKS = {"negative": "Negative electrode", "positive": "Positive electrode"}

# claim-key groups per BPX block, split by the vocabulary's scope: an electrode
# block mixes intrinsic material parameters with manufactured-build parameters,
# and they must land in different parameter sets (different targets).
_BPX_BLOCK_SCOPES = {
    "separator": "separator",
    "electrolyte": "electrolyte",
}


@dataclass
class BpxParameterImportResult:
    """Result of :func:`from_bpx_parameters`.

    Attributes
    ----------
    claims:
        Claim lists keyed by block: ``negative_material`` / ``positive_material``
        (intrinsic material claims), ``negative_electrode`` /
        ``positive_electrode`` (manufactured-build claims), ``separator``,
        ``electrolyte``. Every claim is schema-shaped (``parameter`` + one of
        ``quantity``/``curve``/``expression``).
    title / bpx_version / model_type / description / source_file:
        BPX header fields, as in :class:`BpxImportResult`.
    warnings:
        Unmapped fields and skipped values.
    """

    claims: dict[str, list[dict[str, Any]]]
    title: str | None
    bpx_version: str | None
    model_type: str | None
    description: str | None
    source_file: str | None
    warnings: list[str] = field(default_factory=list)

    def to_records(
        self,
        *,
        materials: Mapping[str, str] | None = None,
        cell_spec_id: str | None = None,
        name: str | None = None,
        default_provenance_class: str = "fitted",
        **record_kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Build canonical parameter-set records from the imported claims.

        ``materials`` maps ``"negative"`` / ``"positive"`` (and optionally
        ``"electrolyte"``, ``"separator"``) to a target: a curated material-kind
        key/alias or a material-spec IRI. Electrode-material claims without a
        mapping are skipped with a warning — BPX does not name its materials, so
        the caller must. Build claims (electrode/separator/electrolyte scope)
        target ``cell_spec_id`` and are skipped with a warning when it is absent
        (unless a material target was given for that block).

        ``record_kwargs`` (citation_doi, source_url, notes, ...) pass through to
        every record. Records validate against the parameter-set schema.
        """
        from battinfo.api import create_parameter_set  # noqa: PLC0415

        materials = dict(materials or {})
        base = name or self.title or self.source_file or "BPX import"
        model_context = {
            "tool": "BPX",
            **({"name": self.title} if self.title else {}),
            **({"model": self.model_type} if self.model_type else {}),
            **({"version": self.bpx_version} if self.bpx_version else {}),
        }

        def _target_fields(value: str) -> dict[str, str]:
            from battinfo.materials import resolve_material_kind  # noqa: PLC0415

            kind = resolve_material_kind(value)
            if kind is not None:
                return {"material_kind": kind}
            if isinstance(value, str) and value.startswith("https://w3id.org/battinfo/"):
                return {"material_spec_id": value}
            raise ValueError(
                f"materials[...] value {value!r} is neither a curated material kind "
                "nor a material-spec IRI."
            )

        records: list[dict[str, Any]] = []

        def _emit(block: str, scope: str, label: str, **target: str) -> None:
            block_claims = self.claims.get(block) or []
            if not block_claims:
                return
            records.append(
                create_parameter_set(
                    name=f"{base} - {label}",
                    scope=scope,
                    claims=block_claims,
                    model_context=model_context,
                    default_provenance_class=default_provenance_class,
                    **target,
                    **record_kwargs,
                )
            )

        for side in ("negative", "positive"):
            material_target = materials.get(side)
            if material_target is not None:
                _emit(
                    f"{side}_material", "material", f"{side} electrode material",
                    **_target_fields(material_target),
                )
            elif self.claims.get(f"{side}_material"):
                self.warnings.append(
                    f"{side} electrode material claims skipped: BPX does not name the "
                    f"material — pass materials={{'{side}': '<kind or material-spec IRI>'}}."
                )
            if self.claims.get(f"{side}_electrode"):
                if cell_spec_id is not None:
                    _emit(
                        f"{side}_electrode", "electrode", f"{side} electrode build",
                        electrode_polarity=side, cell_spec_id=cell_spec_id,
                    )
                else:
                    self.warnings.append(
                        f"{side} electrode build claims (thickness/porosity/...) skipped: "
                        "pass cell_spec_id=... to target the cell design they describe."
                    )

        for block, scope in _BPX_BLOCK_SCOPES.items():
            if not self.claims.get(block):
                continue
            block_material = materials.get(block)
            if block_material is not None:
                _emit(block, scope, block, **_target_fields(block_material))
            elif cell_spec_id is not None:
                _emit(block, scope, block, cell_spec_id=cell_spec_id)
            else:
                self.warnings.append(
                    f"{block} claims skipped: pass cell_spec_id=... (or a "
                    f"materials={{'{block}': ...}} target)."
                )
        return records


def _bpx_value_to_claim(key: str, raw_value: Any, entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """Map one BPX field value to a claim body (quantity/curve/expression), or None."""
    unit = str(entry.get("unit", "1"))
    if isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, (int, float)):
        if not math.isfinite(raw_value):
            return None
        return {"parameter": key, "quantity": {"value": float(raw_value), "unit": unit}}
    if isinstance(raw_value, str) and raw_value.strip():
        return {
            "parameter": key,
            "expression": {"text": raw_value.strip(), "language": "bpx", "argument": "x"},
        }
    if isinstance(raw_value, Mapping):
        xs, ys = raw_value.get("x"), raw_value.get("y")
        if isinstance(xs, list) and isinstance(ys, list) and len(xs) == len(ys) and len(xs) >= 2:
            curve: dict[str, Any] = {
                "x_quantity": str(entry.get("x_quantity", "stoichiometry")),
                "x": [float(v) for v in xs],
                "y": [float(v) for v in ys],
                "y_unit": unit,
            }
            x_unit = {"concentration": "mol/m3", "temperature": "K"}.get(curve["x_quantity"])
            if x_unit:
                curve["x_unit"] = x_unit
            return {"parameter": key, "curve": curve}
    return None


def _extract_block_claims(
    block_params: Mapping[str, Any],
    bpx_block: str,
    warnings: list[str],
    block_label: str,
) -> dict[str, list[dict[str, Any]]]:
    """Split one BPX block's fields into material- and build-scope claim lists."""
    from battinfo.parameters import parameter_entry, resolve_bpx_field  # noqa: PLC0415

    material_claims: list[dict[str, Any]] = []
    build_claims: list[dict[str, Any]] = []
    unknown: list[str] = []
    for field_name, raw_value in block_params.items():
        key = resolve_bpx_field(bpx_block, field_name)
        if key is None:
            unknown.append(field_name)
            continue
        entry = parameter_entry(key) or {}
        claim = _bpx_value_to_claim(key, raw_value, entry)
        if claim is None:
            warnings.append(
                f"BPX {block_label} field '{field_name}' has unusable value "
                f"{raw_value!r}; skipped."
            )
            continue
        scopes = entry.get("scopes", [])
        (material_claims if "material" in scopes else build_claims).append(claim)
    if unknown:
        warnings.append(
            f"BPX {block_label} fields with no parameter mapping: "
            f"{', '.join(unknown[:8])}" + (" …" if len(unknown) > 8 else "")
        )
    return {"material": material_claims, "build": build_claims}


def from_bpx_parameters(source: Mapping[str, Any] | str | Path) -> BpxParameterImportResult:
    """Import BPX physics parameters as parameter-set claims.

    Extracts the electrode, separator, and electrolyte blocks that
    :func:`from_bpx` deliberately skips, as schema-shaped claims grouped by
    block. Cell-level fields stay with :func:`from_bpx` (they are spec
    properties, not claims). Call :meth:`BpxParameterImportResult.to_records`
    (or :func:`import_bpx_parameters`) to mint the canonical records.

    Examples
    --------
    >>> result = from_bpx_parameters("chen2020.json")
    >>> records = result.to_records(
    ...     materials={"negative": "graphite", "positive": "nmc811"},
    ...     citation_doi="10.1149/1945-7111/ab9050",
    ... )
    """
    warnings: list[str] = []
    data, source_file = _load_bpx(source)
    title, bpx_version, model_type, description = _extract_header(data)

    params_raw = (
        data.get("Parameterisation")
        or data.get("parameterisation")
        or data.get("parameters")
        or {}
    )
    claims: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(params_raw, Mapping) or not params_raw:
        warnings.append("BPX file has no 'Parameterisation' block; no claims extracted.")
        params_raw = {}

    for side, block_name in _BPX_ELECTRODE_BLOCKS.items():
        block = params_raw.get(block_name)
        if isinstance(block, Mapping) and block:
            split = _extract_block_claims(block, "electrode", warnings, block_name)
            if split["material"]:
                claims[f"{side}_material"] = split["material"]
            if split["build"]:
                claims[f"{side}_electrode"] = split["build"]

    for block_name, bpx_block in (("Separator", "separator"), ("Electrolyte", "electrolyte")):
        block = params_raw.get(block_name)
        if isinstance(block, Mapping) and block:
            split = _extract_block_claims(block, bpx_block, warnings, block_name)
            merged = split["material"] + split["build"]
            if merged:
                claims[bpx_block] = merged

    if not claims:
        warnings.append("No parameter claims found in BPX electrode/separator/electrolyte blocks.")

    return BpxParameterImportResult(
        claims=claims,
        title=title,
        bpx_version=bpx_version,
        model_type=model_type,
        description=description,
        source_file=source_file,
        warnings=warnings,
    )


def import_bpx_parameters(
    source: Mapping[str, Any] | str | Path,
    *,
    materials: Mapping[str, str] | None = None,
    cell_spec_id: str | None = None,
    **record_kwargs: Any,
) -> list[dict[str, Any]]:
    """One-call BPX physics import: claims extracted and minted as records.

    Convenience for ``from_bpx_parameters(source).to_records(...)``; use the
    two-step form when you need to inspect claims or warnings first.
    """
    return from_bpx_parameters(source).to_records(
        materials=materials, cell_spec_id=cell_spec_id, **record_kwargs
    )


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
