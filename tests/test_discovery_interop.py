"""Interop coverage: the DIGIBAT Discovery-Benchmark coin-cell dataset.

Two entry points over the same ~259 cells:
- `import_discovery_eln`  — the BattINFO-annotated RO-Crate (rich linked graph:
  cell-spec → electrode-spec → material-spec, + electrolyte-spec, test, dataset);
- `import_discovery_xlsx` — the flat "Automated cells" workbook (material-spec +
  electrolyte-spec + cell-spec → instance → test).

Fixtures are trimmed samples (5 cells each, spanning NMC811/NMC622/LFP/LCO/LMFP)
— see tests/fixtures/interop/discovery/PROVENANCE.md.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import import_discovery_eln, import_discovery_xlsx  # noqa: E402
from battinfo.transform import to_jsonld  # noqa: E402
from battinfo.validate import validate_record  # noqa: E402

FX = ROOT / "tests" / "fixtures" / "interop" / "discovery"
ELN = FX / "ro-crate-metadata.sample.json"
XLSX = FX / "discovery-benchmark.sample.xlsx"


def _iris(records: list[dict]) -> list[str]:
    return [b["id"] for r in records for b in r.values() if isinstance(b, dict) and isinstance(b.get("id"), str)]


# Builder-stamped wall-clock fields (when the staging record was generated), not
# source content — excluded from the idempotency comparison.
_IMPORT_STAMPS = ("retrieved_at", "created_at", "modified_at", "published_at")


def _strip_import_stamps(records: list[dict]) -> list[dict]:
    records = copy.deepcopy(records)
    for r in records:
        for holder in r.values():
            if isinstance(holder, dict):
                for key in _IMPORT_STAMPS:
                    holder.pop(key, None)
    return records


# ── RO-Crate (.eln) ──────────────────────────────────────────────────────────


def test_electrolyte_parser_dedupes_solvents() -> None:
    from battinfo.interop.discovery import _parse_electrolyte

    merged = _parse_electrolyte("1M LiPF6 EC:EC=1:1")["solvents"]
    assert [n for n, _ in merged] == ["EC"], "a malformed EC:EC token minted a duplicate solvent"
    normal = _parse_electrolyte("1M LiPF6 EC:EMC=3:7")["solvents"]
    assert [n for n, _ in normal] == ["EC", "EMC"], "distinct solvents must be unaffected"


def test_find_property_drops_non_finite_value() -> None:
    from battinfo.interop.discovery import _find_property

    nan_node = {"hasProperty": [{"@type": "MassLoading",
                                 "hasNumericalPart": {"hasNumericalValue": "NaN"}}]}
    assert _find_property(nan_node, "MassLoading") is None, "a NaN value must be dropped, never coerced"
    ok_node = {"hasProperty": [{"@type": "MassLoading",
                                "hasNumericalPart": {"hasNumericalValue": "2.5"}}]}
    prop = _find_property(ok_node, "MassLoading")
    assert prop is not None and prop["value"] == 2.5


def test_eln_builds_linked_spec_graph() -> None:
    pkg = import_discovery_eln(ELN, validate=True)
    assert pkg.source == "eln"
    assert len(pkg.cells) == 5
    assert pkg.material_specs and pkg.electrode_specs and pkg.electrolyte_specs
    # every cell references electrode-specs + an electrolyte-spec that exist in the package
    spec_ids = {r["electrode_spec"]["id"] for r in pkg.electrode_specs}
    ely_ids = {r["electrolyte_spec"]["id"] for r in pkg.electrolyte_specs}
    for cell in pkg.cells:
        cs = cell.cell_spec
        assert cs["positive_electrode_spec_id"] in spec_ids
        assert cs["negative_electrode_spec_id"] in spec_ids
        assert cs["electrolyte_spec_id"] in ely_ids
        assert cell.test is not None and cell.test["test"]["kind"] == "cycling"
        assert cell.dataset is not None  # cycling .xlsx referenced


def test_eln_recovers_cell_mass_and_electrode_density() -> None:
    """Cell- and electrode-level quantities the crate carries are recovered."""
    pkg = import_discovery_eln(ELN, validate=True)
    # at least one cell carries a mass property with a unit
    masses = [
        c.cell_spec["properties"]["mass"]
        for c in pkg.cells
        if isinstance(c.cell_spec.get("properties"), dict) and "mass" in c.cell_spec["properties"]
    ]
    assert masses, "expected cell mass to be recovered from the crate"
    assert masses[0]["unit"] == "mg"
    # the compaction density lands on the electrode coating
    densities = [
        r["electrode_spec"]["coating"]["property"]["density"]
        for r in pkg.electrode_specs
        if "density" in r["electrode_spec"]["coating"].get("property", {})
    ]
    assert densities, "expected electrode compaction density to be recovered"
    assert densities[0]["unit"] == "g/cm3"


def test_eln_electrode_links_material_and_electrolyte_is_parsed() -> None:
    pkg = import_discovery_eln(ELN, validate=True)
    mat_ids = {r["material_spec"]["id"] for r in pkg.material_specs}
    nmc = next(r for r in pkg.electrode_specs if "NMC811" in r["electrode_spec"]["name"])
    active = nmc["electrode_spec"]["coating"]["component"]["active_material"][0]
    assert active["material_spec_id"] in mat_ids
    assert nmc["electrode_spec"]["coating"]["property"]["loading"]["unit"] == "mg/cm2"
    # electrolyte name parsed into salt + solvent fractions
    ely = next(r["electrolyte_spec"] for r in pkg.electrolyte_specs if "LiPF6" in r["electrolyte_spec"]["name"])
    assert ely["salt"]["name"] == "LiPF6"
    assert ely["salt"]["property"]["concentration"]["value"] == 1.0
    fracs = [c["property"]["volume_fraction"]["value"] for c in ely["solvent_mixture"]["component"]]
    assert fracs == [0.3, 0.7]


# ── Excel (.xlsx) ────────────────────────────────────────────────────────────


def test_xlsx_builds_flat_chains() -> None:
    pkg = import_discovery_xlsx(XLSX, validate=True)
    assert pkg.source == "xlsx"
    assert len(pkg.cells) == 5
    assert pkg.material_specs and pkg.electrolyte_specs
    assert not pkg.electrode_specs  # flat sheet → no separable electrode entities
    for cell in pkg.cells:
        assert cell.cell_spec["cell_spec"]["cell_format"] == "coin"
        assert cell.cell_spec["electrolyte_spec_id"] in {r["electrolyte_spec"]["id"] for r in pkg.electrolyte_specs}
        assert cell.cell_instance["cell_instance"]["serial_number"]
        assert cell.test is not None


def test_xlsx_carries_rich_notes() -> None:
    pkg = import_discovery_xlsx(XLSX, validate=False)
    notes = " ".join(pkg.cells[0].cell_spec.get("notes", []))
    assert "N/P ratio" in notes and "electrolyte volume" in notes


# ── shared guarantees (both sources) ─────────────────────────────────────────


@pytest.mark.parametrize("loader,src", [(import_discovery_eln, ELN), (import_discovery_xlsx, XLSX)], ids=["eln", "xlsx"])
def test_every_record_validates_and_emits_jsonld(loader, src) -> None:
    for record in loader(src, validate=False).records():
        assert validate_record(record).ok, record
        to_jsonld(record, target="domain-battery")  # raises on unmapped @type


@pytest.mark.parametrize("loader,src", [(import_discovery_eln, ELN), (import_discovery_xlsx, XLSX)], ids=["eln", "xlsx"])
def test_iris_unique(loader, src) -> None:
    iris = _iris(loader(src, validate=False).records())
    assert len(iris) == len(set(iris))


@pytest.mark.parametrize("loader,src", [(import_discovery_eln, ELN), (import_discovery_xlsx, XLSX)], ids=["eln", "xlsx"])
def test_import_is_idempotent(loader, src) -> None:
    """Re-import yields identical IRIs and identical records (modulo retrieval time)."""
    a, b = loader(src, validate=False).records(), loader(src, validate=False).records()
    assert _iris(a) == _iris(b)
    assert _strip_import_stamps(a) == _strip_import_stamps(b)


def test_eln_covers_all_five_chemistries() -> None:
    bases = {c.cell_spec["cell_spec"]["positive_electrode_basis"] for c in import_discovery_eln(ELN).cells}
    # eln electrode names carry full chemistry (LiCoO2, LiMn0.6Fe0.4PO4, NMC…)
    assert len(bases) == 5


def test_shared_electrolyte_iri_matches_across_sources() -> None:
    """Same electrolyte name → same minted IRI whether imported from .eln or .xlsx."""
    eln = {r["electrolyte_spec"]["name"]: r["electrolyte_spec"]["id"] for r in import_discovery_eln(ELN).electrolyte_specs}
    xlsx = {r["electrolyte_spec"]["name"]: r["electrolyte_spec"]["id"] for r in import_discovery_xlsx(XLSX).electrolyte_specs}
    shared = set(eln) & set(xlsx)
    assert shared and all(eln[k] == xlsx[k] for k in shared)
