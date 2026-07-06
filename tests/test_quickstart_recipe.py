"""The ws.quickstart() recipe executes offline, end to end.

Phase 1 put the guide notebooks under execution CI; this does the same for the
recipe `ws.quickstart()` prints — the first thing a newcomer types. The
search→add seam broke once without any test noticing (a search hit fed into
the model tripped the unknown-kwarg check); this file keeps every step of the
taught sequence runnable: convert → search → add cell → add test → save.
Registry-dependent steps (login/publish/status) are exercised elsewhere with a
mocked registry.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402
from battinfo.ws import AuthoringWorkspace  # noqa: E402


@pytest.fixture()
def ws(tmp_path: Path) -> AuthoringWorkspace:
    import json

    (tmp_path / "cycler-export.csv").write_text(
        "Cycle,Step,Time(s),Voltage(V),Current(mA),Capacity(mAh)\n"
        "1,CC_Chg,0,3.02,4500,0\n"
        "1,CC_Chg,60,3.45,4500,75\n"
        "1,CC_DChg,3600,4.19,-4500,4430\n",
        encoding="utf-8",
    )
    # Offline search falls back to a local battinfo-records clone; fabricate a
    # one-record clone so the search->add seam runs with zero network.
    record = battinfo.CellSpecification(
        id="https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
        manufacturer="Molicel",
        model="INR21700-P45B",
        format="cylindrical",
        chemistry="Li-ion",
        nominal_capacity={"value": 4.5, "unit": "Ah"},
        source={"type": "datasheet", "retrieved_at": 1781589239},
    ).to_record()
    record_dir = tmp_path / "records-clone" / "records" / "cell-spec" / "molicel-p45b"
    record_dir.mkdir(parents=True)
    (record_dir / "record.json").write_text(json.dumps(record), encoding="utf-8")
    return AuthoringWorkspace(root=tmp_path, records_repo=tmp_path / "records-clone")


def test_quickstart_recipe_runs_offline(ws: AuthoringWorkspace, tmp_path: Path) -> None:
    # Step 3: convert raw cycler files (generic CSV needs the explicit pattern).
    ws.convert("*.csv")
    bdf_files = sorted((tmp_path / "bdf").glob("*.csv"))
    assert bdf_files, "convert must write a BDF file next to the workspace"

    # Step 4: find the cell in the (offline, packaged) index.
    hits = ws.search("molicel p45b")
    assert hits, "offline search must fall back to the packaged index"

    # Step 5: register the physical cells — a raw search hit must be accepted.
    cells = ws.add("cell", spec=hits[0], serial_numbers=["S1", "S2"])
    assert len(cells) == 2
    assert cells[0].cell_spec is not None

    # Step 6: attach a test + data to a cell.
    ws.add("test", type="cycling", cell="S1", data=str(bdf_files[0]))

    # Step 7 (local half): save the linked records.
    ws.save()
    examples = tmp_path / ".battinfo" / "records" / "examples"
    kinds = {p.parent.name for p in examples.rglob("*.json")}
    assert "cell-instance" in kinds and "test" in kinds


def test_add_accepts_search_hit_metadata_keys(ws: AuthoringWorkspace) -> None:
    # A hit carries index metadata the authoring model must never see.
    hit = ws.search("molicel p45b")[0]
    assert "_canonical_id" in hit or "type" in hit, "precondition: hit carries metadata keys"
    cells = ws.add("cell", spec=hit, serial_numbers=["META-1"])
    assert cells and cells[0].cell_spec_id == hit["id"], (
        "the referenced spec must reuse the existing IRI, not mint a new one"
    )


def test_add_accepts_a_registry_shaped_hit_even_offline(ws: AuthoringWorkspace) -> None:
    # A hit from the live registry index carries _canonical_id and source="api".
    # Offline, the full-record fetch fails; the reference must still build from
    # the hit's own fields instead of crashing.
    hit = {
        "id": "https://w3id.org/battinfo/spec/ycek-4qa3-d4v3-rm6r",
        "_canonical_id": "cs-abc123",
        "manufacturer": "molicel",
        "model": "inr21700-p45b",
        "source": "api",
        "type": "cell_spec",
    }
    cells = ws.add("cell", spec=hit, serial_numbers=["API-1"])
    assert cells and cells[0].cell_spec_id == hit["id"]


def test_add_with_string_spec_teaches_the_fix(ws: AuthoringWorkspace) -> None:
    with pytest.raises(TypeError, match=r"ws\.search"):
        ws.add("cell", spec="Molicel INR21700-P45B", serial_numbers=["S1"])


def test_add_still_accepts_a_cell_specification(ws: AuthoringWorkspace) -> None:
    spec = battinfo.CellSpecification(
        manufacturer="Acme", model="QS-1", format="coin", chemistry="Li-ion"
    )
    cells = ws.add("cell", spec=spec, serial_numbers=["ACME-1"])
    assert cells and cells[0].cell_spec is spec


def test_user_facing_prints_are_console_safe() -> None:
    """No print() in ws.py may carry characters outside cp437/cp1252 — a plain
    Windows console must never crash mid-flow with UnicodeEncodeError."""
    import re

    source = (ROOT / "src" / "battinfo" / "ws.py").read_text(encoding="utf-8").splitlines()
    offenders: list[str] = []
    printing = False
    depth = 0
    for number, line in enumerate(source, 1):
        if "print(" in line:
            printing = True
            depth = 0
        if printing:
            if re.search(r"[^\x00-\x7f]", line) and ('"' in line or "'" in line):
                offenders.append(f"ws.py:{number}: {line.strip()[:80]}")
            depth += line.count("(") - line.count(")")
            if depth <= 0:
                printing = False
    assert not offenders, "non-ASCII in printed strings crashes legacy Windows consoles:\n" + "\n".join(
        offenders
    )


def test_new_spec_passed_to_add_joins_the_save_set(ws: AuthoringWorkspace, tmp_path: Path) -> None:
    # A CellSpecification without an id handed to add() must be saved and
    # minted with the instances — not left as an orphan that fails at save.
    spec = battinfo.CellSpecification(
        manufacturer="Molicel", model="INR21700-P45B", format="cylindrical", chemistry="Li-ion"
    )
    cells = ws.add("cell", spec=spec, serial_numbers=["NEW-1"])
    ws.save()
    examples = tmp_path / ".battinfo" / "records" / "examples"
    spec_files = list((examples / "cell-spec").glob("*.json"))
    assert spec_files, "the new spec must be saved alongside its instances"
    assert cells[0].cell_spec_id == spec.id and spec.id is not None
