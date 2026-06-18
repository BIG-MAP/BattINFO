"""Tests for workspace contributor (ORCID) tagging — battinfo.ws.contributor().

Covers the ContributorRef model, ORCID normalization, the set/get/clear flow,
and stamping the contributor onto dataset creators at save() so platform
contributions can be attributed to a person. All tests run offline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.ws import (  # noqa: E402
    AuthoringWorkspace,
    ContributorRef,
    _normalize_orcid,
)

ORCID = "0000-0002-1825-0097"
ORCID_URL = f"https://orcid.org/{ORCID}"


# ── ORCID normalization ───────────────────────────────────────────────────────

def test_normalize_orcid_accepts_bare_and_url() -> None:
    assert _normalize_orcid(ORCID) == ORCID
    assert _normalize_orcid(ORCID_URL) == ORCID
    assert _normalize_orcid("https://orcid.org/0000-0002-1825-009X") == "0000-0002-1825-009X"


def test_normalize_orcid_rejects_invalid() -> None:
    for bad in ("not-an-orcid", "0000-0002-1825", "1234"):
        with pytest.raises(ValueError):
            _normalize_orcid(bad)


# ── ContributorRef model ──────────────────────────────────────────────────────

def test_creator_block_shape() -> None:
    block = ContributorRef(ORCID, name="Jane Researcher", affiliation="SINTEF").creator_block()
    assert block == {
        "type": "Person",
        "name": "Jane Researcher",
        "same_as": ORCID_URL,
        "affiliation": {"type": "Organization", "name": "SINTEF"},
    }


def test_creator_block_minimal() -> None:
    block = ContributorRef(ORCID, name="Jane Researcher").creator_block()
    assert block == {"type": "Person", "name": "Jane Researcher", "same_as": ORCID_URL}


def test_to_from_dict_roundtrip() -> None:
    ref = ContributorRef(ORCID, name="Jane Researcher", affiliation="SINTEF")
    assert ContributorRef.from_dict(ref.to_dict()) == ref


# ── ws.contributor() set / get / persist ──────────────────────────────────────

def test_set_contributor_persists(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    block = ws.contributor(ORCID, name="Jane Researcher")
    assert block["same_as"] == ORCID_URL
    state = json.loads((tmp_path / ".battinfo" / "workspace.json").read_text())
    assert state["contributor"]["orcid"] == ORCID
    assert state["contributor"]["name"] == "Jane Researcher"


def test_contributor_reloads_from_disk(tmp_path: Path) -> None:
    AuthoringWorkspace(root=tmp_path, registry_url=None).contributor(ORCID, name="Jane Researcher")
    fresh = AuthoringWorkspace(root=tmp_path, registry_url=None)
    assert fresh._get_contributor().orcid == ORCID


def test_getter_with_no_contributor_returns_none(tmp_path: Path) -> None:
    assert AuthoringWorkspace(root=tmp_path, registry_url=None).contributor() is None


def test_name_required(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with pytest.raises(ValueError, match="name is required"):
        ws.contributor(ORCID)


def test_patch_fields_preserve_orcid(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.contributor(ORCID, name="Jane Researcher")
    ws.contributor(affiliation="SINTEF")  # patch without re-passing orcid
    ref = ws._get_contributor()
    assert ref.orcid == ORCID and ref.name == "Jane Researcher" and ref.affiliation == "SINTEF"


def test_clear_removes_contributor(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.contributor(ORCID, name="Jane Researcher")
    assert ws.contributor(clear=True) is None
    state = json.loads((tmp_path / ".battinfo" / "workspace.json").read_text())
    assert "contributor" not in state


# ── stamping onto dataset creators at save() ──────────────────────────────────

def _populate(ws: AuthoringWorkspace, tmp_path: Path) -> None:
    """Author a full cell-spec → cell → test → dataset chain on the workspace."""
    from battinfo import quantity

    data_file = tmp_path / "inputs" / "cap.csv"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text("time_s,voltage_v\n0,3.0\n60,2.95\n", encoding="utf-8")

    cell_spec = ws._ws.cell_spec(
        manufacturer="Energizer", model="CR2032", format="coin", chemistry="Li-primary",
        specs={"nominal_voltage": quantity(3.0, "V"), "diameter": quantity(20.0, "mm"),
               "height": quantity(3.2, "mm")},
        source_file="energizer-cr2032.manual.json",
    )
    cell = ws._ws.cell(cell_spec, serial_number="cr2032-001", source_type="lab")
    test = ws._ws.test(cell, kind="capacity_check", protocol="0.2 mA CC discharge",
                       instrument="Biologic VSP-300", status="completed")
    ws._ws.dataset(cell, title="CR2032 capacity", description="discharge summary",
                   test=test, path=data_file, license="CC-BY-4.0")


def _dataset_records(records_root: Path) -> list[dict]:
    out = []
    for p in records_root.rglob("*.json"):
        if "index" in p.name:
            continue
        rec = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(rec.get("dataset"), dict):
            out.append(rec)
    return out


def _creator_orcids(record: dict) -> list[str]:
    return [c.get("same_as") for c in record["dataset"].get("creators", []) if isinstance(c, dict)]


def test_save_stamps_contributor_on_datasets(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _populate(ws, tmp_path)
    ws.contributor(ORCID, name="Jane Researcher")
    ws.save(validation_policy="strict")

    datasets = _dataset_records(ws._records_root)
    assert datasets, "expected a dataset record"
    for rec in datasets:
        assert ORCID_URL in _creator_orcids(rec)


def test_resave_does_not_duplicate_contributor(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _populate(ws, tmp_path)
    ws.contributor(ORCID, name="Jane Researcher")
    ws.save(validation_policy="strict")
    result = ws.save(validation_policy="strict")  # re-runs strict validation over stamped files
    assert result["index"]["failed"] == 0
    for rec in _dataset_records(ws._records_root):
        assert _creator_orcids(rec).count(ORCID_URL) == 1


def test_contributor_backfills_datasets_saved_before_set(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _populate(ws, tmp_path)
    ws.save(validation_policy="strict")  # no contributor yet
    for rec in _dataset_records(ws._records_root):
        assert ORCID_URL not in _creator_orcids(rec)

    ws.contributor(ORCID, name="Jane Researcher")
    ws.save(validation_policy="strict")  # re-save back-fills
    for rec in _dataset_records(ws._records_root):
        assert ORCID_URL in _creator_orcids(rec)


def test_no_contributor_leaves_datasets_unstamped(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    _populate(ws, tmp_path)
    ws.save(validation_policy="strict")
    for rec in _dataset_records(ws._records_root):
        assert ORCID_URL not in _creator_orcids(rec)
