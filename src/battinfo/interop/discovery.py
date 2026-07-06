"""Import the DIGIBAT Discovery-Benchmark coin-cell dataset into BattINFO records.

The Discovery-Benchmark ships in two shapes that describe the *same* ~259 coin
cells (NMC811 / NMC622 / LFP / LCO / LMFP vs graphite):

- a BattINFO-annotated **RO-Crate** (`.eln` export) — a rich linked graph where
  259 cells share 13 characterized electrodes and 9 electrolytes, with EMMO
  quantity properties and per-cell cycling files;
- a flat **Excel** workbook (`Discovery-benchmark.xlsx`, "Automated cells"
  sheet) — one row per cell with masses, capacities, N/P ratio, separator and
  electrolyte columns.

This module offers an entry point for each:

    import_discovery_eln(path)    # RO-Crate → full spec graph
    import_discovery_xlsx(path)   # workbook  → flat per-row chains

Both return a :class:`DiscoveryImportPackage`. The `.eln` path produces the
linked graph cell-spec → electrode-spec → material-spec (+ electrolyte-spec) plus
a cycling test and a dataset per cell; the `.xlsx` path produces the lighter
material-spec + electrolyte-spec + cell-spec → instance → test chain (no
electrode-specs — the flat sheet has no separable electrode entities).

Identifiers are minted deterministically from each entity's Discovery refcode /
item id, so shared electrodes/electrolytes dedupe to one spec and re-import is
idempotent. These are staging identifiers, not published registry entries.

The `.eln` reader needs only the crate's `ro-crate-metadata.json`; the `.xlsx`
reader needs openpyxl (installed with the ``battinfo[tabular]`` extra).
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections.abc import Mapping, Sequence
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
    create_component_spec,
    create_material_spec,
)
from battinfo.bundle import BatteryTestType, Cell, CellSpec, Dataset, Test
from battinfo.interop._common import load_json_source
from battinfo.interop.protocols import _num

PathLike = str | Path

# EMMO active-material class (RO-Crate #active-material @type) → friendly family.
_EMMO_MATERIAL_FAMILY = {
    "LithiumNickelManganeseCobaltOxide": "lithium nickel manganese cobalt oxide",
    "LithiumIronPhosphate": "lithium iron phosphate",
    "LithiumCobaltOxide": "lithium cobalt oxide",
    "LithiumManganeseIronPhosphate": "lithium manganese iron phosphate",
    "Graphite": "graphite",
}

# Cathode grade (from the cell/electrode name) → its EMMO active-material class.
_GRADE_EMMO = {
    "NMC811": "LithiumNickelManganeseCobaltOxide",
    "NMC622": "LithiumNickelManganeseCobaltOxide",
    "NMC": "LithiumNickelManganeseCobaltOxide",
    "LFP": "LithiumIronPhosphate",
    "LCO": "LithiumCobaltOxide",
    "LMFP": "LithiumManganeseIronPhosphate",
    "Graphite": "Graphite",
}

# EMMO units seen on Discovery electrode/cell properties → BattINFO unit text.
_EMMO_UNIT = {
    "MilliGramPerSquareCentiMetre": "mg/cm2",
    "MilliGram": "mg",
    "Litre": "L",
    "GramPerCubicCentiMetre": "g/cm3",
}


@dataclass(slots=True)
class DiscoveryCell:
    """The per-cell record chain (specs are shared on the package)."""

    cell_id: str
    refcode: str | None
    cell_spec: dict[str, Any]
    cell_instance: dict[str, Any]
    test: dict[str, Any] | None
    dataset: dict[str, Any] | None


@dataclass(slots=True)
class DiscoveryImportPackage:
    """Everything minted from a Discovery source.

    ``material_specs`` / ``electrode_specs`` / ``electrolyte_specs`` are
    deduplicated shared specs; ``cells`` holds the per-cell chains that reference
    them. ``source`` is ``"eln"`` or ``"xlsx"``.
    """

    source: str
    material_specs: list[dict[str, Any]] = field(default_factory=list)
    electrode_specs: list[dict[str, Any]] = field(default_factory=list)
    electrolyte_specs: list[dict[str, Any]] = field(default_factory=list)
    cells: list[DiscoveryCell] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def records(self) -> list[dict[str, Any]]:
        """All records, specs first (so references resolve in file order)."""
        out: list[dict[str, Any]] = [
            *self.material_specs, *self.electrode_specs, *self.electrolyte_specs,
        ]
        for cell in self.cells:
            out.append(cell.cell_spec)
            out.append(cell.cell_instance)
            if cell.test is not None:
                out.append(cell.test)
            if cell.dataset is not None:
                out.append(cell.dataset)
        return out


# ── helpers ───────────────────────────────────────────────────────────────────


def _uid(*parts: str) -> str:
    """Deterministic Crockford-Base32 UID from a stable seed (idempotent import)."""
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return _normalized_dashed_uid("".join(UID_ALPHABET[b % 32] for b in digest[:16]))


def _grade(name: str | None) -> str | None:
    """The chemistry grade from a Discovery name, e.g. 'NMC811 (Canrud)' → 'NMC811'."""
    if not name:
        return None
    return re.sub(r"\s*\(.*?\)\s*", "", str(name)).strip() or None


def _qty(value: float, unit: str | None) -> dict[str, Any]:
    q: dict[str, Any] = {"value": value}
    if unit:
        q["unit"] = unit
    return q


def _dedupe_solvents(solvents: list[tuple[str, float | None]]) -> list[tuple[str, float | None]]:
    """Merge repeated solvent names into one component, summing known volume fractions.

    A malformed token like ``EC:EC=1:1`` (or a stray colon code) would otherwise emit two
    components for the same solvent; collapse them so the importer never invents a phantom
    duplicate.
    """
    merged: dict[str, float | None] = {}
    for name, frac in solvents:
        if name not in merged:
            merged[name] = frac
            continue
        prev = merged[name]
        if prev is None:
            merged[name] = frac
        elif frac is not None:
            merged[name] = round(prev + frac, 4)
        # else both None — keep the single None entry
    return list(merged.items())


def _parse_electrolyte(name: str) -> dict[str, Any]:
    """Parse '1M LiPF6 EC:EMC=3:7wt%' → salt, concentration, solvent fractions."""
    out: dict[str, Any] = {"family": "organic", "name": name}
    conc = re.search(r"([\d.]+)\s*M\b", name)
    if conc:
        out["concentration"] = float(conc.group(1))
    salt = re.search(r"\b(LiPF6|LiTFSI|LiFSI|LiBF4|LiClO4|LiBOB)\b", name, re.I)
    if salt:
        out["salt"] = salt.group(1)
    solv = re.search(r"\b([A-Z]{2,4}(?::[A-Z]{2,4})+)\s*=?\s*([\d:]+)?", name)
    if solv and ":" in solv.group(1):
        names = solv.group(1).split(":")
        ratios = [float(x) for x in solv.group(2).split(":")] if solv.group(2) and ":" in solv.group(2) else []
        total = sum(ratios) if ratios else 0.0
        solvents: list[tuple[str, float | None]]
        if ratios and len(ratios) == len(names) and total > 0:
            solvents = [(n, round(r / total, 4)) for n, r in zip(names, ratios)]
        else:
            solvents = [(n, None) for n in names]
        out["solvents"] = _dedupe_solvents(solvents)
    return out


class _Builder:
    """Accumulates deduplicated specs and per-cell chains for one import."""

    def __init__(self, source: str, source_file: str, validate: bool) -> None:
        self.source = source
        self.source_file = source_file
        self.validate = validate
        self._materials: dict[str, dict[str, Any]] = {}     # name → record
        self._electrodes: dict[str, dict[str, Any]] = {}    # key → record
        self._electrolytes: dict[str, dict[str, Any]] = {}  # name → record
        self.cells: list[DiscoveryCell] = []
        self.warnings: list[str] = []

    def _check(self, record: dict[str, Any]) -> dict[str, Any]:
        if self.validate:
            _validate_canonical_record(record)
        return record

    # -- specs (deduped) --
    def material_spec(self, name: str, *, polarity: str, emmo_type: str | None,
                      citation: str | None) -> str:
        if name not in self._materials:
            family = _EMMO_MATERIAL_FAMILY.get(emmo_type or "", None)
            rec = create_material_spec(
                validate=self.validate,
                uid=_uid("discovery", "material", name),
                name=name,
                material_class="active_material",
                electrode_polarity=polarity,
                chemistry_family=family,
                emmo_type=emmo_type,
                source_type="literature",
                citation=citation,
            )
            self._materials[name] = rec
        return self._materials[name]["material_spec"]["id"]

    def electrode_spec(self, key: str, *, name: str, polarity: str, active_name: str,
                       active_id: str, loading: dict[str, Any] | None,
                       mass_fraction: float | None, citation: str | None,
                       notes: list[str]) -> str:
        if key not in self._electrodes:
            active: dict[str, Any] = {"name": active_name, "material_spec_id": active_id}
            if mass_fraction is not None:
                active["property"] = {"mass_fraction": _qty(mass_fraction, "1")}
            coating: dict[str, Any] = {"component": {"active_material": [active]}}
            if loading is not None:
                coating["property"] = {"loading": loading}
            cc = "Aluminium foil" if polarity == "positive" else "Copper foil"
            body = {"coating": coating, "current_collector": {"name": cc}}
            rec = create_component_spec(
                "electrode", validate=self.validate,
                uid=_uid("discovery", "electrode", key),
                name=name, body=body, source_type="lab", citation=citation,
                notes=notes or None,
            )
            self._electrodes[key] = rec
        return self._electrodes[key]["electrode_spec"]["id"]

    def electrolyte_spec(self, name: str, *, supplier: str | None, citation: str | None) -> str:
        if name not in self._electrolytes:
            parsed = _parse_electrolyte(name)
            body: dict[str, Any] = {"family": parsed["family"]}
            if parsed.get("salt"):
                salt: dict[str, Any] = {"name": parsed["salt"]}
                if parsed.get("concentration") is not None:
                    salt["property"] = {"concentration": _qty(parsed["concentration"], "mol/L")}
                body["salt"] = salt
            if parsed.get("solvents"):
                comps = []
                for sname, frac in parsed["solvents"]:
                    comp: dict[str, Any] = {"name": sname}
                    if frac is not None:
                        comp["property"] = {"volume_fraction": _qty(frac, "1")}
                    comps.append(comp)
                body["solvent_mixture"] = {"component": comps}
            rec = create_component_spec(
                "electrolyte", validate=self.validate,
                uid=_uid("discovery", "electrolyte", name),
                name=name, body=body, supplier=supplier, source_type="datasheet",
                citation=citation,
            )
            self._electrolytes[name] = rec
        return self._electrolytes[name]["electrolyte_spec"]["id"]

    # -- per-cell chain --
    def add_cell(self, *, cell_id: str, refcode: str | None, model_name: str,
                 chemistry: str, positive_basis: str, negative_basis: str,
                 manufacturer: str, citation: str | None, notes: list[str],
                 positive_electrode_spec_id: str | None = None,
                 negative_electrode_spec_id: str | None = None,
                 electrolyte_spec_id: str | None = None,
                 test_name: str | None = None, test_description: str | None = None,
                 dataset_file: str | None = None) -> DiscoveryCell:
        seed = refcode or cell_id
        cell_spec = self._check(_record_from_cell_spec(CellSpec(
            uid=_uid("discovery", "cell-spec", seed),
            model_name=model_name,
            manufacturer={"type": "Organization", "name": manufacturer},
            format="coin",
            chemistry=chemistry,
            positive_electrode_basis=positive_basis,
            negative_electrode_basis=negative_basis,
            positive_electrode_spec_id=positive_electrode_spec_id,
            negative_electrode_spec_id=negative_electrode_spec_id,
            electrolyte_spec_id=electrolyte_spec_id,
            source_type="other",
            source_file=self.source_file,
            citation=citation,
            notes=notes,
        )))
        cell_spec_id = cell_spec["cell_spec"]["id"]

        cell_instance = self._check(_record_from_cell_instance(Cell(
            uid=_uid("discovery", "cell-instance", seed),
            cell_spec_id=cell_spec_id,
            serial_number=cell_id,
            source_type="lab",
            citation=citation,
        )))
        cell_uid = cell_instance["cell_instance"]["id"]

        test: dict[str, Any] | None = None
        dataset: dict[str, Any] | None = None
        if test_name is not None:
            test = self._check(_record_from_test(Test(
                uid=_uid("discovery", "test", seed),
                cell_id=cell_uid,
                name=test_name,
                kind=BatteryTestType.CYCLING,  # type: ignore[arg-type]
                description=test_description,
                status="completed",
                source_type="lab",
                citation=citation,
            )))
            test_id = test["test"]["id"]
            if dataset_file is not None:
                dataset = self._check(_record_from_dataset(Dataset(
                    uid=_uid("discovery", "dataset", seed),
                    title=f"{model_name} cycling data",
                    source_type="measurement",
                    access_url=dataset_file,
                    related_cell_ids=[cell_uid],
                    related_test_ids=[test_id],
                    distribution=[{
                        "type": "DataDownload",
                        "content_url": dataset_file,
                        "encoding_format": (
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        ),
                    }],
                    citation=citation,
                )))

        cell = DiscoveryCell(cell_id, refcode, cell_spec, cell_instance, test, dataset)
        self.cells.append(cell)
        return cell

    def package(self) -> DiscoveryImportPackage:
        if not self.cells:
            # An empty result from a real source is worth a word: silence reads as
            # "imported everything" when nothing matched.
            self.warnings.append(
                f"{self.source_file}: no cells found — 0 records imported."
            )
        return DiscoveryImportPackage(
            source=self.source,
            material_specs=list(self._materials.values()),
            electrode_specs=list(self._electrodes.values()),
            electrolyte_specs=list(self._electrolytes.values()),
            cells=self.cells,
            warnings=self.warnings,
        )


# ── RO-Crate (.eln) ───────────────────────────────────────────────────────────


def _node_types(node: Mapping[str, Any]) -> list[str]:
    t = node.get("@type", [])
    if isinstance(t, str):
        return [t]
    return [x for x in t if isinstance(x, str)] if isinstance(t, Sequence) else []


def _first_ref(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return value.get("@id")
    if isinstance(value, list) and value:
        return _first_ref(value[0])
    return None


def _find_property(node: Mapping[str, Any], emmo_type: str, name: str | None = None) -> dict[str, Any] | None:
    for prop in node.get("hasProperty", []) or []:
        if not isinstance(prop, Mapping):
            continue
        if emmo_type in _node_types(prop) and (name is None or prop.get("name") == name):
            num = prop.get("hasNumericalPart")
            raw = num.get("hasNumericalValue") if isinstance(num, Mapping) else None
            if raw is not None:
                # JSON-LD / RO-Crate numbers are commonly serialized as strings
                # (e.g. "6e-05"); coerce leniently like the sibling readers do
                # (protocols/converter/ws via _num) so downstream arithmetic and
                # quantity values are numeric, not a string that crashes or corrupts.
                value = _num(raw)
                if value is None:
                    continue
                unit = _EMMO_UNIT.get(prop.get("hasMeasurementUnit", ""), None)
                return {"value": value, "unit": unit}
    return None


def import_discovery_eln(
    source: PathLike,
    *,
    limit: int | None = None,
    validate: bool = True,
) -> DiscoveryImportPackage:
    """Import a Discovery-Benchmark RO-Crate (`.eln`) into a linked spec graph.

    Parameters
    ----------
    source:
        Path to the crate directory, or directly to its ``ro-crate-metadata.json``.
    limit:
        Import at most this many cells.
    validate:
        Validate each produced record against its schema.
    """
    path = Path(source)
    if path.is_file() and zipfile.is_zipfile(path):
        # A real `.eln` export is a ZIP archive wrapping the crate directory.
        with zipfile.ZipFile(path) as archive:
            candidates = [n for n in archive.namelist() if n.endswith("ro-crate-metadata.json")]
            if not candidates:
                raise ValueError(
                    f"{path} contains no ro-crate-metadata.json — not an RO-Crate .eln archive."
                )
            candidates.sort(key=lambda n: n.count("/"))  # shallowest crate wins
            try:
                graph = json.loads(archive.read(candidates[0]).decode("utf-8")).get("@graph", [])
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path} ({candidates[0]}) is not valid JSON "
                    f"(line {exc.lineno}, column {exc.colno}): {exc.msg}"
                ) from exc
        source_name = path.name
    else:
        crate = path / "ro-crate-metadata.json" if path.is_dir() else path
        loaded = load_json_source(crate)
        graph = loaded.get("@graph", []) if isinstance(loaded, Mapping) else []
        source_name = crate.name
    index: dict[str, Mapping[str, Any]] = {
        n["@id"]: n for n in graph if isinstance(n, Mapping) and "@id" in n
    }
    builder = _Builder("eln", source_name, validate)

    cells = [n for n in graph if isinstance(n, Mapping) and "CoinCell" in _node_types(n)]
    cells.sort(key=lambda n: n.get("@id", ""))
    for node in cells:
        if limit is not None and len(builder.cells) >= limit:
            break
        cell_id = (node.get("@id", "")).strip("./") or node.get("name", "?")
        refcode = node.get("identifier") or node.get("@id")
        url = node.get("url")

        eld_pos = index.get(_first_ref(node.get("hasPositiveElectrode")) or "")
        eld_neg = index.get(_first_ref(node.get("hasNegativeElectrode")) or "")
        ely = index.get(_first_ref(node.get("hasElectrolyte")) or "")

        def _electrode_spec_id(eld: Mapping[str, Any] | None, polarity: str) -> tuple[str | None, str | None]:
            if eld is None:
                return None, None
            ename = eld.get("name", "")
            grade = _grade(ename) or ename
            active_node = index.get(_first_ref(eld.get("hasActiveMaterial")) or "")
            emmo_type = None
            if active_node is not None:
                emmo_type = next((t for t in _node_types(active_node) if t != "ActiveMaterial"), None)
            emmo_type = emmo_type or _GRADE_EMMO.get(grade)
            mat_id = builder.material_spec(grade, polarity=polarity, emmo_type=emmo_type, citation=url)
            loading = _find_property(eld, "MassLoading")
            mass_fraction = _find_property(eld, "MassFraction")
            spec_id = builder.electrode_spec(
                eld.get("@id", grade), name=ename, polarity=polarity,
                active_name=grade, active_id=mat_id, loading=loading,
                mass_fraction=(mass_fraction or {}).get("value"), citation=url,
                notes=[f"Discovery electrode {eld.get('@id','').strip('./')}"],
            )
            return spec_id, grade

        pos_spec_id, cathode = _electrode_spec_id(eld_pos, "positive")
        neg_spec_id, anode = _electrode_spec_id(eld_neg, "negative")
        ely_spec_id = None
        if ely is not None:
            ely_spec_id = builder.electrolyte_spec(
                ely.get("name", "electrolyte"), supplier=ely.get("supplier"), citation=url
            )

        notes = ["Imported from DIGIBAT Discovery-Benchmark RO-Crate."]
        vol = _find_property(node, "Volume", "Electrolyte volume")
        if vol is not None:
            notes.append(f"electrolyte volume: {round(vol['value'] * 1e6, 1)} uL")
        if not cathode:
            builder.warnings.append(f"{cell_id}: no positive electrode resolved")
        if not anode:
            builder.warnings.append(f"{cell_id}: no negative electrode resolved")

        # cycling data file (the .xlsx in hasPart)
        dataset_file = None
        for part in node.get("hasPart", []) or []:
            pid = part.get("@id", "") if isinstance(part, Mapping) else ""
            if pid.endswith(".xlsx"):
                dataset_file = url or pid
                break

        builder.add_cell(
            cell_id=cell_id, refcode=refcode,
            model_name=node.get("name", cell_id),
            chemistry=" | ".join(p for p in (cathode, anode) if p) or "unknown",
            positive_basis=cathode or "unknown", negative_basis=anode or "unknown",
            manufacturer="DIGIBAT Discovery-Benchmark",
            citation=url, notes=notes,
            positive_electrode_spec_id=pos_spec_id,
            negative_electrode_spec_id=neg_spec_id,
            electrolyte_spec_id=ely_spec_id,
            test_name="Galvanostatic cycling", test_description="Rate-performance galvanostatic cycling.",
            dataset_file=dataset_file,
        )

    return builder.package()


# ── Excel workbook (.xlsx) ──────────────────────────────────────────────────


def import_discovery_xlsx(
    source: PathLike,
    *,
    sheet: str = "Automated cells",
    limit: int | None = None,
    validate: bool = True,
) -> DiscoveryImportPackage:
    """Import the flat Discovery-Benchmark workbook (one cell per row).

    Produces material-spec + electrolyte-spec + cell-spec → instance → test per
    row. Unlike the RO-Crate path this emits no electrode-specs (the flat sheet
    has no separable electrode entities); electrodes are carried as cell-spec
    basis names.
    """
    from battinfo._util import require_extra  # noqa: PLC0415

    openpyxl = require_extra("openpyxl", "tabular", "import_discovery_xlsx() reads Excel workbooks")

    path = Path(source)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet]
    rows = list(ws.iter_rows(min_row=1, values_only=True))
    wb.close()
    # An empty target sheet (blank/template export or truncated save) has no header
    # row; treat it as a header with no columns so the rest yields an empty package
    # instead of an IndexError on rows[0].
    header = [str(h).strip() if h is not None else "" for h in rows[0]] if rows else []

    def col(name: str, occurrence: int = 0) -> int | None:
        seen = -1
        for i, h in enumerate(header):
            if h == name:
                seen += 1
                if seen == occurrence:
                    return i
        return None

    ix = {
        "id": col("ID"), "name": col("Cell name"), "cathode": col("Cathode"),
        "cathode_supplier": col("Cathode supplier"), "anode": col("Anode"),
        "anode_supplier": col("Anode supplier"), "np": col("N/P Ratio"),
        "separator": col("Separator_Type"), "electrolyte": col("Electrolyte"),
        "electrolyte_supplier": col("Electrolyte supplier"),
        "electrolyte_volume": col("Electrolyte_Volume_uL"), "spacer": col("Spacer_mm"),
        "procedure": col("Testing procedure"), "assembler": col("Assembler"),
        "cathode_active": col("Active material", 0), "cathode_capacity": col("Capacity mAh"),
        "anode_active": col("Active material", 1), "anode_capacity": col("Capacity"),
    }
    builder = _Builder("xlsx", path.name, validate)

    def cell_val(row: Sequence[Any], key: str) -> Any:
        i = ix.get(key)
        return row[i] if i is not None and i < len(row) else None

    for row in rows[1:]:
        if limit is not None and len(builder.cells) >= limit:
            break
        cell_id = cell_val(row, "id")
        cathode = _grade(cell_val(row, "cathode"))
        anode = _grade(cell_val(row, "anode"))
        if not cell_id or (cathode is None and anode is None):
            continue
        cell_id = str(cell_id)

        if cathode:
            builder.material_spec(cathode, polarity="positive",
                                  emmo_type=_GRADE_EMMO.get(cathode), citation=None)
        if anode:
            builder.material_spec(anode, polarity="negative",
                                  emmo_type=_GRADE_EMMO.get(anode), citation=None)
        ely_name = cell_val(row, "electrolyte")
        ely_spec_id = None
        if ely_name:
            ely_spec_id = builder.electrolyte_spec(
                str(ely_name), supplier=cell_val(row, "electrolyte_supplier"), citation=None
            )

        notes = ["Imported from Discovery-Benchmark workbook (Automated cells)."]
        for label, key, unit in (
            ("N/P ratio", "np", ""), ("separator", "separator", ""),
            ("electrolyte volume", "electrolyte_volume", " uL"), ("spacer", "spacer", " mm"),
            ("cathode active mass", "cathode_active", " mg"), ("cathode capacity", "cathode_capacity", " mAh"),
            ("anode active mass", "anode_active", " mg"), ("anode capacity", "anode_capacity", " mAh"),
            ("assembler", "assembler", ""),
        ):
            v = cell_val(row, key)
            if v not in (None, ""):
                notes.append(f"{label}: {round(v, 4) if isinstance(v, float) else v}{unit}")

        procedure = cell_val(row, "procedure")
        builder.add_cell(
            cell_id=cell_id, refcode=cell_id,
            model_name=str(cell_val(row, "name") or cell_id),
            chemistry=" | ".join(p for p in (cathode, anode) if p) or "unknown",
            positive_basis=cathode or "unknown", negative_basis=anode or "unknown",
            manufacturer=str(cell_val(row, "assembler") or "DIGIBAT Discovery-Benchmark"),
            citation=None, notes=notes,
            electrolyte_spec_id=ely_spec_id,
            test_name=f"Galvanostatic cycling ({procedure})" if procedure else "Galvanostatic cycling",
            test_description=f"{procedure} test." if procedure else None,
        )

    return builder.package()
