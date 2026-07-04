"""Import a tabular solid-state-battery literature database into BattINFO records.

The reference source is the "DB Master Sheet" — a wide CSV (one row per cell
reported in a paper) with hierarchical, prefix-coded columns: ``AAM_*`` (anode
active material), ``A_SE_*``/``A_ISE_*`` (anode-side solid electrolyte),
``S_*`` (the solid-electrolyte separator layer), ``CAM_*``/``C_*`` (cathode),
``FC_*``/``MC_*`` (cell fabrication / measurement conditions) and ``CLC_*``/
``R*_*`` (constant-current cycle-life and rate tests).

This module is the generic *tabular metadata* importer the package previously
lacked: it maps each row into the canonical spec + instance model —

    material_spec (cathode / anode / solid electrolyte)
    cell_spec  →  cell_instance  →  test (cycling)

It complements the converter (JSON-LD) and battdat (timeseries CSV) bridges,
and it is the first importer to exercise solid-state chemistries (garnet,
argyrodite, perovskite electrolytes; Li-metal / LTO anodes; sulfur cathodes)
that the canonical example corpus does not cover.

Records are *staging* records: identifiers are minted deterministically from the
row's publication identity (DOI + row id) so re-running the import is stable, but
they carry no claim to a published ``w3id.org`` registry entry. A curator re-mints
canonical IRIs at publish time.

No external dependencies — the standard-library ``csv`` reader is used. The
real master sheet is cp1252-encoded (degree signs in comment columns); the
reader auto-detects utf-8 / utf-8-sig / cp1252.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from battinfo.api import (
    UID_ALPHABET,
    CellInstanceInput,
    MaterialSpecInput,
    TestInput,
    _normalized_dashed_uid,
    _record_from_cell_instance,
    _record_from_cell_spec,
    _record_from_material_spec,
    _record_from_test,
    _validate_canonical_record,
)
from battinfo.bundle import BatteryTestType, CellSpecification

PathLike = str | Path

# Sentinels the sheet uses for "not reported" / "not applicable" / "none".
_MISSING_TOKENS = {
    "", "nr", "na", "n/a", "none", "none_s", "unknown", "unk", "-", "--", "?", "tbd",
}

# Casing column (FC_Casing) → canonical cell_format enum value.
_FORMAT_MAP = {
    "coin": "coin",
    "pouch": "pouch",
    "cylindrical": "cylindrical",
    "prismatic": "prismatic",
    "other": "other",
}

# Family / type codes → human-readable chemistry-family labels.
_FAMILY_LABELS = {
    "li_anode": "lithium anode",
    "li_cathode": "lithium cathode",
    "li_se": "lithium solid electrolyte",
    "li_transition_metal_oxide_c": "lithium transition-metal oxide",
    "li_phosphate_c": "lithium phosphate",
    "li_sulfur_c": "lithium sulfur",
    "li_metal_metalalloy_a": "lithium metal / alloy",
    "li_metal_oxide_a": "lithium metal oxide",
    "li_garnet": "garnet",
    "li_argyrodite": "argyrodite",
    "li_perovskite": "perovskite",
    "li_nasicon": "NASICON",
    "li_sulfide": "sulfide",
    "li_oxide": "oxide",
    "li_none": "none",
}


@dataclass(slots=True)
class SolidStateImportResult:
    """Records minted from one solid-state-database row.

    Attributes
    ----------
    row_id:
        The sheet's ``ID`` column for the source row (provenance, not an IRI).
    cell_spec, cell_instance, test:
        The canonical spec → instance → test chain for the cell. ``test`` is
        ``None`` when the row reported no cycle-life measurement.
    material_specs:
        Material-spec records for the distinct cathode / anode / solid-electrolyte
        materials named in the row.
    warnings:
        Non-fatal notes about fields that could not be mapped.
    """

    row_id: str
    cell_spec: dict[str, Any]
    cell_instance: dict[str, Any]
    test: dict[str, Any] | None
    material_specs: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def records(self) -> list[dict[str, Any]]:
        """All produced records, materials first (specs before instances)."""
        out: list[dict[str, Any]] = [*self.material_specs, self.cell_spec, self.cell_instance]
        if self.test is not None:
            out.append(self.test)
        return out


# ── helpers ───────────────────────────────────────────────────────────────────


def _clean(value: Any) -> str | None:
    """Return a trimmed cell value, or ``None`` for blank / sentinel tokens."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in _MISSING_TOKENS else text


def _number(value: Any) -> float | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    # 'nan'/'inf'/'-inf' parse fine but are not real measurements; reject them so
    # they neither crash int() downstream (e.g. cycle-life) nor land as nonsense
    # text in cell-spec notes.
    if not math.isfinite(number):
        return None
    return number


def _label(code: str | None) -> str | None:
    if code is None:
        return None
    return _FAMILY_LABELS.get(code.strip().lower(), code.strip())


def _uid_from_seed(*parts: str) -> str:
    """Deterministic 16-char Crockford-Base32 UID from a stable seed.

    The same row + role always yields the same identifier, so re-importing the
    sheet is idempotent. (No randomness — distinct from the registry minter.)
    """
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    token = "".join(UID_ALPHABET[b % 32] for b in digest[:16])
    return _normalized_dashed_uid(token)


def _row_seed(row: Mapping[str, str]) -> str:
    """Publication-stable identity for a row: DOI (preferred) + sheet ID."""
    doi = _clean(row.get("DOI"))
    rid = _clean(row.get("ID")) or _clean(row.get("MZ Database_ID")) or "?"
    return f"{doi or 'no-doi'}#{rid}"


def _se_material(row: Mapping[str, str], prefix: str) -> tuple[str | None, str | None]:
    """(material, type-label) for a solid-electrolyte layer (prefix ``A_``/``S_``/``C_``)."""
    material = _clean(row.get(f"{prefix}ISE_Material")) or _clean(row.get(f"{prefix}OSE_Material"))
    se_type = _label(_clean(row.get(f"{prefix}ISE_Type")) or _clean(row.get(f"{prefix}OSE_Type")))
    return material, se_type


# ── core mapping ────────────────────────────────────────────────────────────


def from_solid_state_db_row(
    row: Mapping[str, str],
    *,
    source_file: str = "DB Master Sheet.csv",
    validate: bool = True,
) -> SolidStateImportResult:
    """Map a single solid-state-database row into a BattINFO record chain.

    Parameters
    ----------
    row:
        A mapping of column name → cell value (e.g. one ``csv.DictReader`` row).
    source_file:
        Provenance file name recorded on every produced record.
    validate:
        When true, each record is checked against its JSON Schema (structure
        only; cross-references between the staging records are not resolved).

    Returns
    -------
    SolidStateImportResult
    """
    warnings: list[str] = []
    seed = _row_seed(row)
    row_id = _clean(row.get("ID")) or "?"
    doi = _clean(row.get("DOI"))
    citation = f"https://doi.org/{doi}" if doi else None
    author = _clean(row.get("Lead_Author"))
    journal = _clean(row.get("Journal_Name"))

    cathode = _clean(row.get("CAM_Material"))
    anode = _clean(row.get("AAM_Material"))
    se_material, se_type = _se_material(row, "S_")

    if cathode is None:
        warnings.append(f"row {row_id}: no cathode active material (CAM_Material)")
    if anode is None:
        warnings.append(f"row {row_id}: no anode active material (AAM_Material)")
    if se_material is None:
        warnings.append(f"row {row_id}: no solid electrolyte material (S_ISE/OSE_Material)")

    # ── material specs (deduped cathode / anode / electrolyte) ──────────────
    material_specs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_material(name: str | None, role: str, material_class: str,
                     polarity: str | None, family: str | None) -> None:
        if name is None or (role, name) in seen:
            return
        seen.add((role, name))
        draft = MaterialSpecInput(
            uid=_uid_from_seed(seed, "material", role, name),
            name=name,
            material_class=material_class,
            electrode_polarity=polarity,
            chemistry_family=family,
            source_type="literature",
            citation=citation,
        )
        material_specs.append(_record_from_material_spec(draft))

    # material_class is a coarse enum; "metal_electrode" fits Li-metal anodes,
    # "separator_material" the solid-electrolyte separator layer (electrolyte == separator).
    anode_class = "metal_electrode" if anode and "metal" in anode.lower() else "active_material"
    add_material(cathode, "cathode", "active_material", "positive",
                 _label(_clean(row.get("CAM_Type"))) or _label(_clean(row.get("CAM_Family"))))
    add_material(anode, "anode", anode_class, "negative",
                 _label(_clean(row.get("AAM_Type"))) or _label(_clean(row.get("AAM_Family"))))
    add_material(se_material, "electrolyte", "separator_material", None, se_type)

    # ── chemistry / format ───────────────────────────────────────────────────
    chemistry = " | ".join(p for p in (anode, se_material, cathode) if p) or "solid-state"
    casing = _clean(row.get("FC_Casing"))
    cell_format = _FORMAT_MAP.get((casing or "").lower(), "unknown")
    if casing and cell_format == "unknown":
        warnings.append(f"row {row_id}: unmapped casing '{casing}' → format 'unknown'")

    model_name = " / ".join(p for p in (cathode, se_material, anode) if p) or f"ssb-cell-{row_id}"
    manufacturer = author or "Unknown laboratory"

    # ── descriptive notes (numbers the spec model has no field for) ──────────
    notes: list[str] = ["Imported from solid-state-battery literature database."]
    for label, value, unit in (
        ("solid electrolyte type", se_type, ""),
        ("separator thickness", _number(row.get("S_Thickness")), " um"),
        ("ionic conductivity (25C)", _number(row.get("S_Conductivity25")), " S/cm"),
        ("cathode coating", _clean(row.get("CAM_Coating")), ""),
        ("measurement temperature", _number(row.get("MC_Temp")), " C"),
        ("stack pressure", _clean(row.get("MC_Pressure")), ""),
    ):
        if value is not None:
            notes.append(f"{label}: {value}{unit}")
    if journal:
        notes.append(f"reported in {journal} ({_clean(row.get('Publication_date')) or 'n.d.'})")

    cell_uid = _uid_from_seed(seed, "cell-spec")
    cell_spec = _record_from_cell_spec(CellSpecification(
        uid=cell_uid,
        model_name=model_name,
        manufacturer={"type": "Organization", "name": manufacturer},
        format=cell_format,  # type: ignore[arg-type]
        chemistry=chemistry,
        positive_electrode_basis=cathode,
        negative_electrode_basis=anode,
        source_type="other",
        source_file=source_file,
        citation=citation,
        notes=notes,
    ))
    cell_spec_id = cell_spec["cell_spec"]["id"]

    cell_instance = _record_from_cell_instance(CellInstanceInput(
        uid=_uid_from_seed(seed, "cell-instance"),
        cell_spec_id=cell_spec_id,
        source_type="lab",
        citation=citation,
        notes=[f"Cell reported as {model_name}." + (f" Lead author: {author}." if author else "")],
    ))
    cell_id = cell_instance["cell_instance"]["id"]

    # ── cycling test (constant-current cycle life) ───────────────────────────
    test: dict[str, Any] | None = None
    cycle_life = _number(row.get("CLC_CycleLife"))
    charge_v = _number(row.get("CLC_ChargeV"))
    discharge_v = _number(row.get("CLC_DischargeV"))
    current = _number(row.get("CLC_i"))
    areal_cap = _number(row.get("CLC_ArealCapacity"))
    if any(v is not None for v in (cycle_life, charge_v, discharge_v, current, areal_cap)):
        desc_parts = []
        if charge_v is not None and discharge_v is not None:
            desc_parts.append(f"{discharge_v}-{charge_v} V")
        if current is not None:
            desc_parts.append(f"{current} mA/cm2")
        if areal_cap is not None:
            desc_parts.append(f"areal capacity {areal_cap} mAh/cm2")
        if cycle_life is not None:
            desc_parts.append(f"{int(cycle_life)} cycles")
        test = _record_from_test(TestInput(
            uid=_uid_from_seed(seed, "test", "clc"),
            cell_id=cell_id,
            name="Constant-current cycle-life test",
            # mypy targets py3.10 where enum.StrEnum is unknown, so it sees the
            # member as plain `str`; it is a BatteryTestType at runtime (py>=3.11).
            kind=BatteryTestType.CYCLING,  # type: ignore[arg-type]
            description="Galvanostatic cycling; " + ", ".join(desc_parts) + "." if desc_parts else None,
            status="completed",
            source_type="lab",
            citation=citation,
        ))

    result = SolidStateImportResult(
        row_id=row_id,
        cell_spec=cell_spec,
        cell_instance=cell_instance,
        test=test,
        material_specs=material_specs,
        warnings=warnings,
    )

    if validate:
        for record in result.records():
            _validate_canonical_record(record)

    return result


# ── batch ─────────────────────────────────────────────────────────────────


def _read_rows(path: Path) -> Iterator[dict[str, str]]:
    """Yield rows from the CSV, auto-detecting utf-8 / utf-8-sig / cp1252.

    The whole file is decoded up front *before* any row is yielded. Decoding
    lazily (catching ``UnicodeDecodeError`` around ``yield from``) is unsafe: on
    a cp1252 file larger than the IO read buffer — the documented master-sheet
    encoding — the utf-8 attempt streams every row preceding the first
    undecodable byte to the consumer before raising, and the cp1252 fallback
    then re-yields the file from the start, silently duplicating those rows.
    """
    raw = path.read_bytes()
    text: str | None = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        # Last resort: replace undecodable bytes rather than fail the whole import.
        text = raw.decode("utf-8", errors="replace")
    yield from csv.DictReader(io.StringIO(text, newline=""))


def batch_import_solid_state_db(
    source: PathLike,
    *,
    limit: int | None = None,
    validate: bool = True,
    skip_errors: bool = False,
) -> list[SolidStateImportResult]:
    """Import every row of a solid-state-database CSV into record chains.

    Parameters
    ----------
    source:
        Path to the master-sheet CSV.
    limit:
        Import at most this many rows (useful for smoke tests).
    validate:
        Validate each produced record against its schema.
    skip_errors:
        When true, a row that fails to map is skipped (its error recorded in the
        next result's warnings is *not* attempted); when false, the error
        propagates. Rows with no cathode and no anode are always skipped as
        non-cells.

    Returns
    -------
    list[SolidStateImportResult]
    """
    path = Path(source)
    results: list[SolidStateImportResult] = []
    for row in _read_rows(path):
        if limit is not None and len(results) >= limit:
            break
        # Skip rows that name neither electrode — header-spacer / blank lines.
        if _clean(row.get("CAM_Material")) is None and _clean(row.get("AAM_Material")) is None:
            continue
        try:
            results.append(
                from_solid_state_db_row(row, source_file=path.name, validate=validate)
            )
        except Exception:
            if skip_errors:
                continue
            raise
    return results


def iter_solid_state_records(results: Iterable[SolidStateImportResult]) -> Iterator[dict[str, Any]]:
    """Flatten import results into a single stream of records."""
    for result in results:
        yield from result.records()
