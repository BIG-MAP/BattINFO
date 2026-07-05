"""Interoperability seam with Battery Data Commons (BDC).

Battery Data Commons (https://github.com/BatteryCommons/BatteryDataCommons) is a
curated registry of public battery datasets. Each canonical record
(``canonical/datasets/bdc_NNNNNN.json``) catalogues a dataset and describes the
cell it measured with EMMO-flavoured terms (``CoinCase``, ``BatteryCell``,
``LithiumNickelManganeseCobaltOxide``, …).

This module is the first step toward the strategic goal of **native BattINFO
integration into BDC**: a documented, tested two-way mapping.

- ``import_bdc_record`` / ``batch_import_bdc`` — BDC canonical record →
  BattINFO records: a dataset (the catalogue entry) plus the cell it describes
  as cell-spec → instance, the electrode material-specs, and a test per reported
  measurement (``available_measurements`` → test kinds).
- ``to_bdc_record`` — the reverse: a BattINFO cell-spec (+ optional dataset) →
  a BDC-shaped canonical dict, so BattINFO-authored cells can be contributed
  back to the commons.

The field mapping is documented in ``docs/internal/battery-data-commons.md``.

Identifiers are minted deterministically from the BDC record id, so re-import is
idempotent (modulo the builder's wall-clock import stamps). These are staging
identifiers, not published registry entries.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from battinfo.api import (
    UID_ALPHABET,
    _normalized_dashed_uid,
    _record_from_cell_instance,
    _record_from_cell_spec,
    _record_from_dataset,
    _record_from_test,
    _validate_canonical_record,
    create_material_spec,
)
from battinfo.bundle import BatteryTestType, CellInstance, CellSpecification, Dataset, Test
from battinfo.interop._common import load_json_source

PathLike = str | Path

# BDC overview.case → (BattINFO cell_format, size_code-or-None)
_CASE_FORMAT = {
    "CoinCase": ("coin", None),
    "PouchCase": ("pouch", None),
    "PrismaticCase": ("prismatic", None),
    "Unknown": ("unknown", None),
    "Multiple": ("other", None),
    "Synthetic cycles": ("other", None),
}

# BattINFO cell_format → BDC overview.case (export direction)
_FORMAT_CASE = {"coin": "CoinCase", "pouch": "PouchCase", "prismatic": "PrismaticCase"}

# BDC available_measurements flag → (BattINFO test kind, human label)
_MEASUREMENT_KIND = {
    "discharge_capacity": ("capacity_check", "Discharge capacity"),
    "eis": ("eis", "Electrochemical impedance spectroscopy"),
    "internal_resistance": ("dcir", "Internal resistance (DCIR)"),
    "pseudo_ocv": ("quasi_ocv", "Pseudo-OCV"),
}

# Values BDC uses for "not a real single material".
_UNKNOWN_MATERIAL = {None, "", "Unknown", "Multiple", "N/A", "NA"}

# Capacity units → Ampere-hours, for the Ah-typed BDC ``rated_capacity_Ah`` field.
_CAPACITY_TO_AH = {"Ah": 1.0, "A.h": 1.0, "mAh": 1e-3}


def _capacity_to_ah(capacity: Mapping[str, Any]) -> float | None:
    """Convert a nominal-capacity quantity to Ampere-hours for BDC export.

    The BDC field is ``rated_capacity_Ah``, so a mAh-authored value (the
    idiomatic coin-cell unit, producible via ``battinfo.quantity``) must be
    scaled — writing it verbatim previously claimed e.g. 45 Ah for a 45 mAh
    cell (a 1000× error). Returns ``None`` (so the field is omitted) when the
    value is non-numeric or the unit is not a recognised capacity unit, rather
    than emitting an unconvertible value under an Ah-typed key.
    """
    value = capacity.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    scale = _CAPACITY_TO_AH.get(str(capacity.get("unit") or "Ah"))
    if scale is None:
        return None
    return value * scale


@dataclass(slots=True)
class BdcRecordImport:
    """The BattINFO record chain minted from one BDC canonical record."""

    bdc_id: str
    dataset: dict[str, Any]
    cell_spec: dict[str, Any]
    cell_instance: dict[str, Any]
    tests: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BdcImportPackage:
    material_specs: list[dict[str, Any]] = field(default_factory=list)
    imports: list[BdcRecordImport] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def records(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = list(self.material_specs)
        for imp in self.imports:
            out.extend([imp.cell_spec, imp.cell_instance, *imp.tests, imp.dataset])
        return out


# ── helpers ───────────────────────────────────────────────────────────────────


def _uid(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return _normalized_dashed_uid("".join(UID_ALPHABET[b % 32] for b in digest[:16]))


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _format_of(case: str | None) -> tuple[str, str | None]:
    if case in _CASE_FORMAT:
        return _CASE_FORMAT[case]
    if case and re.fullmatch(r"R\d{4,5}", case):  # R18650 / R21700 → cylindrical, case is the size code
        return "cylindrical", case
    return ("unknown" if not case else "other"), None


def _looks_emmo(name: str) -> bool:
    """A CamelCase EMMO-style class name, e.g. LithiumIronPhosphate."""
    return bool(re.fullmatch(r"[A-Z][A-Za-z]+", name)) and not name.isupper()


def _first(value: Any) -> str | None:
    if isinstance(value, list):
        return next((str(x) for x in value if x), None)
    return _clean(value)


def _encoding_format(url: str) -> str:
    """Best-effort MIME type for a download URL (BDC links are mostly archives)."""
    lower = url.lower()
    for suffix, mime in ((".zip", "application/zip"), (".csv", "text/csv"),
                         (".json", "application/json"), (".h5", "application/x-hdf5"),
                         (".parquet", "application/vnd.apache.parquet")):
        if lower.endswith(suffix):
            return mime
    return "application/octet-stream"


# ── BDC → BattINFO ──────────────────────────────────────────────────────────


def import_bdc_record(record: Mapping[str, Any], *, validate: bool = True,
                      _materials: dict[str, dict[str, Any]] | None = None) -> BdcRecordImport | None:
    """Map one BDC canonical record into a BattINFO record chain.

    Returns ``None`` for software-tool records (no cell). ``_materials`` is a
    shared accumulator used by :func:`batch_import_bdc` to deduplicate electrode
    material-specs across records; pass nothing for a standalone call.
    """
    materials = _materials if _materials is not None else {}
    warnings: list[str] = []
    # Drop null/blank category entries rather than coercing them to the literal
    # keyword 'None' (which would survive validation and land in dataset.keywords).
    categories = [str(c).strip() for c in (record.get("categories") or []) if c is not None and str(c).strip()]
    if "software" in categories or record.get("software"):
        return None

    bdc_id = str(record.get("id") or "bdc_unknown")
    # Tolerate type-drift in external records: a scalar/list where a mapping is
    # expected becomes {} rather than crashing later on `.get` with a bare AttributeError.
    _overview = record.get("overview")
    overview = _overview if isinstance(_overview, Mapping) else {}
    _electrodes = record.get("electrodes")
    electrodes = _electrodes if isinstance(_electrodes, Mapping) else {}
    _reported = record.get("reported_values")
    reported = _reported if isinstance(_reported, Mapping) else {}
    source_meta = record.get("source_metadata") or {}
    citation = _first([p.get("url") for p in (record.get("publications") or []) if isinstance(p, Mapping)]) \
        or _first(record.get("source_urls"))

    def _check(rec: dict[str, Any]) -> dict[str, Any]:
        if validate:
            _validate_canonical_record(rec)
        return rec

    def material_id(name: str | None, polarity: str) -> str | None:
        clean = _clean(name)
        if clean is None or clean in _UNKNOWN_MATERIAL:
            return None
        if clean not in materials:
            materials[clean] = create_material_spec(
                validate=validate, uid=_uid("bdc", "material", clean), name=clean,
                material_class="active_material", electrode_polarity=polarity,
                emmo_type=clean if _looks_emmo(clean) else None,
                source_type="literature", citation=citation,
            )
        return materials[clean]["material_spec"]["id"]

    pos = _clean(electrodes.get("positive"))
    neg = _clean(electrodes.get("negative"))
    material_id(pos, "positive")
    material_id(neg, "negative")

    cell_format, size_code = _format_of(_clean(overview.get("case")))
    chemistry = " | ".join(p for p in (pos, neg) if p and p not in _UNKNOWN_MATERIAL) or "unknown"

    specs: dict[str, Any] = {}
    cap = reported.get("rated_capacity_Ah")
    if isinstance(cap, (int, float)) and not isinstance(cap, bool) and cap > 0:
        specs["nominal_capacity"] = {"value": cap, "unit": "Ah"}
    elif cap is not None:
        warnings.append(
            f"BDC record {bdc_id}: dropped rated_capacity_Ah={cap!r} (not a usable positive "
            "number); nominal_capacity omitted."
        )

    notes = [f"Imported from Battery Data Commons record {bdc_id}."]
    if source_meta.get("data_modality"):
        notes.append(f"data modality: {source_meta['data_modality']}")
    if source_meta.get("owner"):
        notes.append(f"dataset owner: {source_meta['owner']}")

    cell_spec = _check(_record_from_cell_spec(CellSpecification(
        uid=_uid("bdc", "cell-spec", bdc_id),
        model_name=_clean(overview.get("battery_model")) or bdc_id,
        manufacturer={"type": "Organization", "name": _clean(overview.get("manufacturer")) or "Unknown"},
        format=cell_format,  # type: ignore[arg-type]
        chemistry=chemistry,
        positive_electrode_basis=(pos if pos not in _UNKNOWN_MATERIAL else None),
        negative_electrode_basis=(neg if neg not in _UNKNOWN_MATERIAL else None),
        size_code=size_code,
        iec_code=_clean(overview.get("iec_battery_code")),
        specs=specs,
        source_type="catalog",
        source_file=f"{bdc_id}.json",
        citation=citation,
        notes=notes,
    )))
    cell_spec_id = cell_spec["cell_spec"]["id"]

    cell_instance = _check(_record_from_cell_instance(CellInstance(
        uid=_uid("bdc", "cell-instance", bdc_id),
        cell_spec_id=cell_spec_id,
        serial_number=bdc_id,
        source_type="lab",
        citation=citation,
    )))
    cell_uid = cell_instance["cell_instance"]["id"]

    tests: list[dict[str, Any]] = []
    techniques: list[str] = []
    for flag, (kind, label) in _MEASUREMENT_KIND.items():
        if (record.get("available_measurements") or {}).get(flag):
            techniques.append(label)
            tests.append(_check(_record_from_test(Test(
                uid=_uid("bdc", "test", bdc_id, flag),
                cell_id=cell_uid,
                name=label,
                kind=BatteryTestType(kind),  # type: ignore[arg-type]
                description=f"{label} reported by Battery Data Commons record {bdc_id}.",
                status="completed",
                source_type="lab",
                citation=citation,
            ))))

    title = _clean(record.get("title")) or _clean(overview.get("feature")) \
        or _clean(record.get("comment")) or f"Battery dataset {bdc_id}"
    licence = record.get("license") or {}
    # access_url must reference something real: prefer the record's source URLs, then its
    # download URLs; a record carrying no URL at all keeps a truthful catalog URN (the
    # BDC record identity) rather than a fabricated placeholder URL.
    access_url = _first(record.get("source_urls")) or _first(record.get("download_urls"))
    if access_url is None:
        access_url = f"urn:battery-data-commons:record:{bdc_id}"
        warnings.append(
            f"record {bdc_id} has no source or download URL; dataset access_url set to "
            f"its catalog URN ({access_url})."
        )
    dataset = _check(_record_from_dataset(Dataset(
        uid=_uid("bdc", "dataset", bdc_id),
        title=title,
        description=_clean(source_meta.get("purpose")),
        license=_clean(licence.get("url")) or _clean(record.get("license_url")),
        keywords=categories,
        same_as=[str(u) for u in (record.get("source_urls") or []) if u],
        measurement_techniques=techniques,
        access_url=access_url,
        distribution=[{"type": "DataDownload", "content_url": str(u),
                       "encoding_format": _encoding_format(str(u))}
                      for u in (record.get("download_urls") or []) if u],
        related_cell_ids=[cell_uid],
        related_test_ids=[t["test"]["id"] for t in tests],
        source_type="catalog",
        citation=citation,
    )))

    return BdcRecordImport(bdc_id, dataset, cell_spec, cell_instance, tests, warnings=warnings)


def batch_import_bdc(source: PathLike, *, limit: int | None = None,
                     validate: bool = True) -> BdcImportPackage:
    """Import every canonical BDC dataset record under *source*.

    *source* may be the BDC repository root, its ``canonical/datasets``
    directory, or a single ``bdc_*.json`` file.
    """
    path = Path(source)
    if path.is_file():
        files = [path]
    else:
        datasets_dir = path / "canonical" / "datasets"
        root = datasets_dir if datasets_dir.is_dir() else path
        files = sorted(root.glob("bdc_*.json"))

    materials: dict[str, dict[str, Any]] = {}
    imports: list[BdcRecordImport] = []
    for file in files:
        if limit is not None and len(imports) >= limit:
            break
        record = load_json_source(file)
        if str(record.get("record_status", "active")) != "active":
            continue
        imp = import_bdc_record(record, validate=validate, _materials=materials)
        if imp is not None:
            imports.append(imp)

    batch_warnings = [w for imp in imports for w in imp.warnings]
    if not imports:
        detail = f"{len(files)} file(s) matched" if files else "no bdc_*.json files found"
        batch_warnings.append(f"{path}: 0 records imported ({detail}).")
    return BdcImportPackage(
        material_specs=list(materials.values()),
        imports=imports,
        warnings=batch_warnings,
    )


# ── BattINFO → BDC ──────────────────────────────────────────────────────────


def to_bdc_record(cell_spec: Mapping[str, Any], *, dataset: Mapping[str, Any] | None = None,
                  bdc_id: str | None = None) -> dict[str, Any]:
    """Render a BattINFO cell-spec (+ optional dataset) as a BDC canonical dict.

    The inverse of :func:`import_bdc_record` — enough to contribute a
    BattINFO-authored cell/dataset to the commons. ``cell_spec`` /
    ``dataset`` are canonical BattINFO record dicts.
    """
    cs = cell_spec.get("cell_spec", cell_spec)
    manufacturer = cs.get("manufacturer")
    manufacturer_name = manufacturer.get("name") if isinstance(manufacturer, Mapping) else manufacturer
    fmt = cs.get("cell_format")
    case = _FORMAT_CASE.get(fmt) or (cs.get("size_code") if fmt == "cylindrical" else None) or "Unknown"

    # Don't contribute placeholders injected on import back to the commons: a
    # sentinel 'Unknown' manufacturer and a 'bdc_'-prefixed model (the id-fallback
    # import uses when a record has no real model) are not catalogue facts.
    model = cs.get("model")
    model_is_id_fallback = isinstance(model, str) and model.startswith("bdc_")
    overview = {
        "feature": (dataset or {}).get("dataset", {}).get("name") if dataset else cs.get("name"),
        "case": case,
        "cell_module_pack": "BatteryCell",
        "manufacturer": manufacturer_name if manufacturer_name not in _UNKNOWN_MATERIAL else None,
        "battery_model": None if model_is_id_fallback else model,
        "iec_battery_code": cs.get("iec_code"),
    }
    record: dict[str, Any] = {
        "id": bdc_id,
        "record_status": "active",
        "categories": ["performance"],
        "overview": {k: v for k, v in overview.items() if v is not None},
        "electrodes": {
            k: v for k, v in (
                ("positive", cs.get("positive_electrode_basis")),
                ("negative", cs.get("negative_electrode_basis")),
            ) if v is not None
        },
        "reported_values": {},
        "source_metadata": {"data_modality": "TimeSeriesDataSet"},
        "provenance": [{"event": "exported", "source": "battinfo", "curator": "battinfo.interop.battery_data_commons"}],
    }
    capacity = (cell_spec.get("properties") or {}).get("nominal_capacity") if "properties" in cell_spec else None
    if isinstance(capacity, Mapping):
        capacity_ah = _capacity_to_ah(capacity)
        if capacity_ah is not None:
            record["reported_values"]["rated_capacity_Ah"] = capacity_ah

    if dataset is not None:
        ds = dataset.get("dataset", dataset)
        if ds.get("same_as") or ds.get("access_url"):
            record["source_urls"] = list(ds.get("same_as") or []) or [ds["access_url"]]
        dist = [d.get("content_url") for d in (ds.get("distributions") or ds.get("distribution") or []) if isinstance(d, Mapping)]
        if dist:
            record["download_urls"] = [u for u in dist if u]
        if ds.get("license"):
            record["license"] = {"url": ds["license"]}
    return {k: v for k, v in record.items() if v not in (None, {}, [])}
