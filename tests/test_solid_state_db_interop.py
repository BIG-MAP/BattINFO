"""Interop coverage: the solid-state-battery literature database (tabular CSV).

Proves BattINFO ingests a wide, prefix-coded metadata sheet (one cell per row)
into the canonical spec → instance → test chain, exercising solid-state
chemistries (garnet/argyrodite/perovskite/polymer electrolytes, Li-metal/LTO
anodes, sulfur/NMC/LFP cathodes) absent from the example corpus.

The fixture is a trimmed, version-pinned sample of the master sheet — see
tests/fixtures/interop/solid-state-db/PROVENANCE.md.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import (  # noqa: E402
    batch_import_solid_state_db,
    from_solid_state_db_row,
    iter_solid_state_records,
)
from battinfo.transform import to_jsonld  # noqa: E402
from battinfo.validate import validate_record  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "interop" / "solid-state-db" / "db-master-sample.csv"


def _rows() -> list[dict[str, str]]:
    with open(FIXTURE, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def test_read_rows_does_not_duplicate_rows_of_large_cp1252_file(tmp_path: Path) -> None:
    """A cp1252 file larger than the IO buffer must not duplicate rows.

    Regression: ``_read_rows`` was a lazy generator wrapped in
    ``try/except UnicodeDecodeError`` around ``yield from``. On a cp1252 file
    (the documented master-sheet encoding) bigger than the read buffer, the
    utf-8 attempt streamed every row preceding the first non-ASCII byte to the
    consumer before raising, then the cp1252 fallback re-yielded the whole file
    from the start — silently importing those rows twice with no error.
    """
    from battinfo.interop.solid_state_db import _read_rows

    header = b"ID,CAM_Material,AAM_Material,Lead_Author\n"
    body = b"".join(("%d,LiCoO2,Li,Smith\n" % i).encode("ascii") for i in range(2000))
    body += b"9999,LFP,Li,M\xfcller\n"  # single cp1252 'ü' on the final row
    path = tmp_path / "ss_big.csv"
    path.write_bytes(header + body)

    parsed = list(_read_rows(path))
    ids = [row["ID"] for row in parsed]

    assert len(parsed) == 2001
    assert len(ids) == len(set(ids)), "rows were duplicated during encoding fallback"
    assert ids[-1] == "9999"


def test_fixture_present_and_wide() -> None:
    rows = _rows()
    assert len(rows) == 6
    # the prefix-coded schema is the point — make sure the trim kept it intact
    assert len(rows[0]) >= 180
    assert {"CAM_Material", "AAM_Material", "S_ISE_Material", "FC_Casing", "CLC_CycleLife"} <= set(rows[0])


def test_batch_imports_every_row() -> None:
    results = batch_import_solid_state_db(FIXTURE, validate=True)
    assert len(results) == 6
    for r in results:
        # every row yields a full chain
        assert r.cell_spec["cell_spec"]["id"].startswith("https://w3id.org/battinfo/spec/")
        assert r.cell_instance["cell_instance"]["cell_spec_id"] == r.cell_spec["cell_spec"]["id"]
        assert r.material_specs, f"row {r.row_id} produced no materials"
        assert r.test is not None and r.test["test"]["kind"] == "cycling"


def test_chain_is_internally_consistent() -> None:
    [r] = batch_import_solid_state_db(FIXTURE, validate=True, limit=1)
    spec_id = r.cell_spec["cell_spec"]["id"]
    inst_id = r.cell_instance["cell_instance"]["id"]
    assert r.cell_instance["cell_instance"]["cell_spec_id"] == spec_id
    assert r.test["test"]["cell_id"] == inst_id
    # solid-state framing carried through
    assert r.cell_spec["cell_spec"]["positive_electrode_basis"]
    assert r.cell_spec["cell_spec"]["negative_electrode_basis"]
    classes = {m["material_spec"]["material_class"] for m in r.material_specs}
    assert "separator_material" in classes  # the solid electrolyte


def test_every_record_validates_against_schema() -> None:
    for record in iter_solid_state_records(batch_import_solid_state_db(FIXTURE, validate=False)):
        result = validate_record(record)  # schema/semantic; refs are staging, so source_root=None
        assert result.ok, f"{record.get('schema_version')} record invalid: {result}"


def test_every_record_emits_domain_battery_jsonld() -> None:
    for record in iter_solid_state_records(batch_import_solid_state_db(FIXTURE, validate=False)):
        to_jsonld(record, target="domain-battery")  # raises on an unmapped @type


def test_all_iris_unique() -> None:
    records = list(iter_solid_state_records(batch_import_solid_state_db(FIXTURE, validate=False)))
    iris = [
        body["id"]
        for record in records
        for body in record.values()
        if isinstance(body, dict) and isinstance(body.get("id"), str)
    ]
    assert len(iris) == len(set(iris)) == 36


def _strip_import_stamps(records: list[dict]) -> list[dict]:
    import copy
    records = copy.deepcopy(records)
    for r in records:
        for holder in r.values():
            if isinstance(holder, dict):
                for key in ("retrieved_at", "created_at", "modified_at", "published_at"):
                    holder.pop(key, None)
    return records


def test_import_is_idempotent() -> None:
    """Deterministic IRIs: the same sheet re-imports to identical records.

    (Modulo the builder's wall-clock import-time stamps — the minted IRIs and all
    substantive content are deterministic.)
    """
    a = [_strip_import_stamps(r.records()) for r in batch_import_solid_state_db(FIXTURE, validate=False)]
    b = [_strip_import_stamps(r.records()) for r in batch_import_solid_state_db(FIXTURE, validate=False)]
    assert a == b


def test_missing_sentinels_become_none() -> None:
    """`NR` / `NA` / `None_S` are treated as missing, not literal values."""
    rows = _rows()
    # row 1 (index 0) reports S_ISE_Material=None_S but an organic (PEO) electrolyte
    r = from_solid_state_db_row(rows[0], validate=True)
    chem = r.cell_spec["cell_spec"]["chemistry"]
    assert "None_S" not in chem and "NR" not in chem
    assert "Sulfur" in chem and "Li Metal" in chem


def test_row_without_electrodes_is_skipped() -> None:
    blank = {"ID": "999", "CAM_Material": "NR", "AAM_Material": "NA"}
    assert batch_import_solid_state_db_from_rows([blank]) == []


def batch_import_solid_state_db_from_rows(rows: list[dict[str, str]]):
    # helper mirroring the batch skip-logic without writing a temp CSV
    out = []
    from battinfo.interop.solid_state_db import _clean
    for row in rows:
        if _clean(row.get("CAM_Material")) is None and _clean(row.get("AAM_Material")) is None:
            continue
        out.append(from_solid_state_db_row(row))
    return out


@pytest.mark.parametrize("fmt", ["coin", "pouch", "other"])
def test_fixture_covers_multiple_formats(fmt: str) -> None:
    formats = {
        r.cell_spec["cell_spec"]["cell_format"]
        for r in batch_import_solid_state_db(FIXTURE, validate=False)
    }
    assert fmt in formats
