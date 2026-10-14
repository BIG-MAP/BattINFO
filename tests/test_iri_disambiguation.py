"""Phase 3 / review C-1 + C-2: distinct entities that share identity fields must get
distinct, order-independent IRIs — never silently overwrite each other on save.

Two cell-specs for one manufacturer+model with different capacities have the same
identity seed (manufacturer::model::format::chemistry::size_code), so before the fix
they minted the same IRI and one overwrote the other on save. The fix re-mints every
member of a collision group from its content, deterministically and order-independently.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import Workspace, quantity  # noqa: E402


def _ws(root: Path) -> Workspace:
    return Workspace(root, name="t", title="T", description="d", tenant="x", publisher="p", version="0.1.0")


def _spec(ws: Workspace, capacity: float) -> None:
    ws.cell_spec(
        manufacturer="Acme",
        model="X1",
        format="cylindrical",
        chemistry="Li-ion",
        size_code="R26650",
        positive_electrode_basis="LFP",
        negative_electrode_basis="graphite",
        specs={"nominal_capacity": quantity(capacity, "Ah")},
        source_file=f"x-{capacity}.json",
    )


def test_colliding_cell_specs_get_distinct_ids(tmp_path: Path) -> None:
    ws = _ws(tmp_path / "ws")
    _spec(ws, 2.5)
    _spec(ws, 3.5)
    ws._finalize()
    ids = [s.id for s in ws.cell_specs]
    assert ids[0] != ids[1], "two distinct cell-specs collided onto one IRI (C-1 data loss)"
    assert all(i and "/spec/" in i for i in ids)


def test_colliding_cell_specs_persist_as_two_distinct_records(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    ws = _ws(root)
    _spec(ws, 2.5)
    _spec(ws, 3.5)
    ws.save_workspace()
    ids: set[str] = set()
    for f in root.rglob("*.json"):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(doc, dict) and isinstance(doc.get("cell_spec"), dict) and doc["cell_spec"].get("id"):
            ids.add(doc["cell_spec"]["id"])
    assert len(ids) == 2, "a distinct cell-spec was overwritten on save (C-1)"


def test_spec_disambiguation_is_order_independent(tmp_path: Path) -> None:
    def author(order: list[float]) -> dict[float, str]:
        ws = _ws(tmp_path / ("ws-" + "-".join(str(c) for c in order)))
        for cap in order:
            _spec(ws, cap)
        ws._finalize()
        return {cap: ws.cell_specs[i].id for i, cap in enumerate(order)}

    a = author([2.5, 3.5])
    b = author([3.5, 2.5])
    assert a[2.5] == b[2.5] and a[3.5] == b[3.5], "the same spec got a different IRI when sibling order changed (C-2)"


def test_single_spec_keeps_idempotent_identity_iri(tmp_path: Path) -> None:
    # No collision -> the identity-seeded IRI is preserved, so re-authoring the same
    # content (in a fresh workspace) yields the same IRI (idempotent upsert).
    ws_a = _ws(tmp_path / "a")
    _spec(ws_a, 2.5)
    ws_a._finalize()

    ws_b = _ws(tmp_path / "b")
    _spec(ws_b, 2.5)
    ws_b._finalize()

    assert ws_a.cell_specs[0].id == ws_b.cell_specs[0].id


def test_cells_link_to_their_own_colliding_spec(tmp_path: Path) -> None:
    # The cascade fix: two cells, each built on a distinct (identity-colliding) spec,
    # must end up referencing their OWN spec, not whichever survived.
    ws = _ws(tmp_path / "ws")
    s1 = _ws_spec(ws, 2.5)
    s2 = _ws_spec(ws, 3.5)
    ws.cell(s1, serial_number="c1", source_type="lab")
    ws.cell(s2, serial_number="c2", source_type="lab")
    ws._finalize()
    spec_ids = {s.id for s in ws.cell_specs}
    cell_spec_links = {c.cell_spec_id for c in ws.cells}
    assert len(spec_ids) == 2
    assert cell_spec_links == spec_ids, "cells did not each link to their own distinct spec (C-1 cascade)"


def _ws_spec(ws: Workspace, capacity: float):
    return ws.cell_spec(
        manufacturer="Acme",
        model="X1",
        format="cylindrical",
        chemistry="Li-ion",
        size_code="R26650",
        positive_electrode_basis="LFP",
        negative_electrode_basis="graphite",
        specs={"nominal_capacity": quantity(capacity, "Ah")},
        source_file=f"x-{capacity}.json",
    )


def test_colliding_test_specs_get_distinct_ids_and_tests_link_own(tmp_path: Path) -> None:
    # The test-spec disambiguation path (the new _finalize call for finalized_test_specs)
    # plus the conformsTo/protocol_id cascade — a regression here silently conflates two
    # distinct protocols into one canonical record.
    ws = _ws(tmp_path / "ws")
    cell = ws.cell(_ws_spec(ws, 2.5), serial_number="c1", source_type="lab")
    ts1 = ws.test_spec(
        name="Cycling",
        type="cycling",
        version="1",
        experiment=["Charge at 1C until 4.2 V", "Discharge at 1C until 2.5 V"],
    )
    ts2 = ws.test_spec(
        name="Cycling",
        type="cycling",
        version="1",
        experiment=["Charge at C/2 until 4.2 V", "Discharge at C/2 until 2.5 V"],
    )
    ws.test(cell, type="cycling", protocol_ref=ts1, status="completed")
    ws.test(cell, type="cycling", protocol_ref=ts2, status="completed")
    ws._finalize()
    spec_ids = {p.id for p in ws.test_specs}
    assert len(spec_ids) == 2, "two distinct test-specs collided onto one IRI (C-1)"
    assert all(i and "/spec/" in i for i in spec_ids)
    assert {t.protocol_id for t in ws.tests} == spec_ids, "tests did not each link to their own test-spec"


def test_colliding_spec_iri_is_stable_across_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A colliding spec's content-seeded IRI must be stable across runs with different
    # finalize timestamps — i.e. every finalize-time-varying field is stripped from the
    # content seed. If retrieved_at (or any new auto-timestamp) leaked in, the IRI would
    # drift and break the idempotent upsert on the collision path.
    def author(clock: int) -> dict[float, str]:
        monkeypatch.setattr("battinfo._workspace._now_unix", lambda: clock)
        ws = _ws(tmp_path / f"ws-{clock}")
        _spec(ws, 2.5)
        _spec(ws, 3.5)
        ws._finalize()
        return {2.5: ws.cell_specs[0].id, 3.5: ws.cell_specs[1].id}

    assert author(1000) == author(9_999_999)


def test_full_content_duplicate_specs_both_persist(tmp_path: Path) -> None:
    # Two genuinely identical specs collide AND hash identically; the ordinal "::dupN"
    # fallback must keep both rather than overwrite one.
    ws = _ws(tmp_path / "ws")
    _spec(ws, 2.5)
    _spec(ws, 2.5)
    ws._finalize()
    ids = [s.id for s in ws.cell_specs]
    assert ids[0] != ids[1], "an identical-content duplicate overwrote its sibling"


def test_three_way_collision_gives_distinct_ids(tmp_path: Path) -> None:
    ws = _ws(tmp_path / "ws")
    for cap in (2.5, 3.0, 3.5):
        _spec(ws, cap)
    ws._finalize()
    assert len({s.id for s in ws.cell_specs}) == 3


# ── An IRI a record already has is never re-minted ────────────────────────────
#
# Pinned by the caller, imported, or minted by an earlier save in the session:
# a sibling whose identity fields collide later is the one that moves, and two
# records holding one IRI before a save are refused.

PINNED = "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5"


def _identity_mint(tmp_path: Path, capacity: float) -> str:
    """The IRI the spec _ws_spec builds mints when nothing collides with it."""
    alone = _ws(tmp_path / f"alone-{capacity}")
    spec = _ws_spec(alone, capacity)
    alone._finalize()
    return str(spec.id)


def test_a_colliding_sibling_never_moves_a_saved_iri(tmp_path: Path) -> None:
    ws = _ws(tmp_path / "ws")
    first = _ws_spec(ws, 2.5)
    cell = ws.cell(first, serial_number="c1", source_type="lab")
    ws._finalize()
    saved_spec, saved_cell = first.id, cell.id
    assert saved_spec == _identity_mint(tmp_path, 2.5)

    second = _ws_spec(ws, 3.5)
    ws._finalize()

    assert (first.id, cell.id, cell.cell_spec_id) == (saved_spec, saved_cell, saved_spec)
    assert second.id is not None and second.id != saved_spec


def test_a_colliding_sibling_never_moves_a_pinned_iri(tmp_path: Path) -> None:
    ws = _ws(tmp_path / "ws")
    pinned = _ws_spec(ws, 2.5)
    pinned.id = _identity_mint(tmp_path, 3.5)  # the IRI the sibling below mints
    sibling = _ws_spec(ws, 3.5)
    ws._finalize()
    assert pinned.id == _identity_mint(tmp_path, 3.5)
    assert sibling.id not in (None, pinned.id)


def test_the_sibling_gets_the_iri_it_would_get_beside_any_other_collision(tmp_path: Path) -> None:
    # The record minted in the pass is re-seeded from its content, as it would be
    # if both were new: a later save of the same content lands on the same IRI.
    ws = _ws(tmp_path / "ws")
    _ws_spec(ws, 2.5)
    ws._finalize()
    later = _ws_spec(ws, 3.5)
    ws._finalize()

    both_new = _ws(tmp_path / "both-new")
    _ws_spec(both_new, 2.5)
    together = _ws_spec(both_new, 3.5)
    both_new._finalize()
    assert later.id == together.id


def test_two_records_that_held_one_iri_before_the_pass_are_refused(tmp_path: Path) -> None:
    ws = _ws(tmp_path / "ws")
    first = _ws_spec(ws, 2.5)
    second = _ws_spec(ws, 3.5)
    first.id = second.id = PINNED
    with pytest.raises(ValueError, match=f"have the IRI {PINNED}") as excinfo:
        ws._finalize()
    assert "One IRI names one record" in str(excinfo.value)
    assert first.id == second.id == PINNED, "a refused pass changes nothing"


def test_a_test_saved_earlier_in_the_session_keeps_its_iri_when_a_sibling_joins(tmp_path: Path) -> None:
    import battinfo

    root = tmp_path / "lab"
    (root / "data").mkdir(parents=True)
    for name, voltage in (("a.csv", "3.1"), ("b.csv", "3.2")):
        (root / "data" / name).write_text(f"test_time_second,voltage_volt\n0,3.0\n60,{voltage}\n", encoding="utf-8")
    ws = battinfo.workspace(root, registry_url=None)
    spec = battinfo.CellSpec(manufacturer="Example Lab", model="R2032", format="coin", chemistry="li-ion")
    ws.add("cell", spec=spec, serial_numbers=["C01"])
    (first,) = ws.add("test", type="cycling", cell="C01", data="data/a.csv")
    ws.save()
    saved = first.id
    (first_dataset,) = [d for d in ws._ws.datasets if d.test_id == saved]

    (second,) = ws.add("test", type="cycling", cell="C01", data="data/b.csv")
    ws.save()

    assert first.id == saved
    assert second.id not in (None, saved)
    assert first_dataset.test_id == saved
    records = {
        doc["test"]["id"]: doc["test"]
        for doc in (json.loads(p.read_text(encoding="utf-8")) for p in (root / ".battinfo/records/test").glob("*.json"))
    }
    assert set(records) == {saved, second.id}
    assert records[saved]["dataset_ids"] == [first_dataset.id]


def test_a_content_seed_leaves_derived_dataset_links_out() -> None:
    from battinfo._workspace import _content_seed
    from battinfo.bundle import Test

    test = Test(test_kind="cycling", cell_instance_id="https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-dddd")
    linked = test.model_copy(update={"dataset_ids": ["https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-0001"]})
    assert _content_seed(linked) == _content_seed(test)


# ── Records saved by an earlier session ─────────────────────────────────────
#
# A notebook re-run in a new kernel mints every record again. A record saved in
# the folder by an earlier session keeps its IRI when a colliding record joins,
# whether or not the earlier session saved before adding that record.


def _records_in(root: Path, folder: str) -> dict[str, dict]:
    paths = sorted((root / ".battinfo" / "records" / folder).glob("*.json"))
    return {path.name: json.loads(path.read_text(encoding="utf-8")) for path in paths}


def _lab_spec(rated: float, name: str | None = None):
    import battinfo

    return battinfo.CellSpec(
        manufacturer="Example Lab",
        model="R2032",
        format="coin",
        chemistry="li-ion",
        name=name,
        properties={"rated_capacity": {"value": rated, "unit": "Ah"}},
    )


@pytest.mark.parametrize("sibling_first", [False, True], ids=["sibling added after", "sibling added before"])
def test_a_spec_saved_in_an_earlier_session_keeps_its_iri_when_a_sibling_joins(
    tmp_path: Path, sibling_first: bool
) -> None:
    """The specs differ only in a property beside the record body, so the whole saved document is compared."""
    import battinfo

    root = tmp_path / "lab"
    first = battinfo.workspace(root, registry_url=None)
    first.add("cell", spec=_lab_spec(2.0), serial_numbers=["C01"])
    first.save()
    (saved_spec,), (saved_cell,) = first._ws.cell_specs, first._ws.cells
    saved_record = _records_in(root, "cell-spec")

    rerun = battinfo.workspace(root, registry_url=None)
    adds = [(_lab_spec(2.0), "C01"), (_lab_spec(3.0), "C02")]
    for spec, serial in reversed(adds) if sibling_first else adds:
        rerun.add("cell", spec=spec, serial_numbers=[serial])
    rerun.save()

    by_serial = {cell.serial_number: cell for cell in rerun._ws.cells}
    assert (by_serial["C01"].cell_spec_id, by_serial["C01"].id) == (saved_spec.id, saved_cell.id)
    assert by_serial["C02"].cell_spec_id not in (None, saved_spec.id)
    specs = _records_in(root, "cell-spec")
    assert len(specs) == 2 and len(_records_in(root, "cell-instance")) == 2
    (saved_file,) = saved_record
    assert specs[saved_file]["properties"] == saved_record[saved_file]["properties"]


def test_a_rerun_keeps_the_iris_whether_or_not_a_save_ran_between_the_adds(tmp_path: Path) -> None:
    import battinfo

    root = tmp_path / "lab"
    first = battinfo.workspace(root, registry_url=None)
    first.add("cell", spec=_lab_spec(2.0, "R2032 A"), serial_numbers=["MYLAB-001"])
    first.save()
    first.add("cell", spec=_lab_spec(3.0, "R2032 B"), serial_numbers=["MYLAB-002"])
    first.save()
    saved = ([str(s.id) for s in first._ws.cell_specs], [str(c.id) for c in first._ws.cells])
    files = (_records_in(root, "cell-spec"), _records_in(root, "cell-instance"))

    rerun = battinfo.workspace(root, registry_url=None)
    rerun.add("cell", spec=_lab_spec(2.0, "R2032 A"), serial_numbers=["MYLAB-001"])
    rerun.add("cell", spec=_lab_spec(3.0, "R2032 B"), serial_numbers=["MYLAB-002"])
    rerun.save()

    assert ([str(s.id) for s in rerun._ws.cell_specs], [str(c.id) for c in rerun._ws.cells]) == saved
    assert (_records_in(root, "cell-spec"), _records_in(root, "cell-instance")) == files


def test_a_test_saved_in_an_earlier_session_keeps_its_iri_when_a_sibling_joins(tmp_path: Path) -> None:
    import battinfo

    root = tmp_path / "lab"
    first = battinfo.workspace(root, registry_url=None)
    first.add("cell", spec=_lab_spec(2.0), serial_numbers=["C01"])
    (saved,) = first.add("test", type="cycling", cell="C01")
    first.save()

    rerun = battinfo.workspace(root, registry_url=None)
    rerun.add("cell", spec=_lab_spec(2.0), serial_numbers=["C01"])
    (again,) = rerun.add("test", type="cycling", cell="C01")
    (other,) = rerun.add("test", type="cycling", cell="C01", instrument="Cycler-2")
    rerun.save()

    assert again.id == saved.id
    assert other.id not in (None, saved.id)
    assert len(_records_in(root, "test")) == 2


# What 057b66a0, before the 0.8.0 seed changes, minted for the calls in the test
# below: two cell specs whose chemistry is spelled Li-ion, not as its vocabulary
# key, with one natural key, so its finalize pass minted both from their content.
SPECS_SAVED_BEFORE_0_8_0 = [
    "https://w3id.org/battinfo/spec/asnk-vtg6-ghnp-q0t2",
    "https://w3id.org/battinfo/spec/392y-8nwq-jrhg-ywv5",
]
CELLS_SAVED_BEFORE_0_8_0 = [
    "https://w3id.org/battinfo/cell/y6ty-ba06-ade2-5r54",
    "https://w3id.org/battinfo/cell/t113-jw8t-695m-nbmk",
    "https://w3id.org/battinfo/cell/d10r-6gt9-6dtn-n2zc",
]


def test_colliding_cell_specs_saved_before_0_8_0_keep_their_iris(tmp_path: Path) -> None:
    """The first session pins the IRIs 057b66a0 minted, so its records are the ones that release saved."""
    import battinfo

    root = tmp_path / "lab"

    def session(pinned: bool) -> dict[str, list[str]]:
        ws = battinfo.workspace(root, registry_url=None)
        plain = battinfo.CellSpec(manufacturer="Example Lab", model="R2032", format="coin", chemistry="Li-ion")
        rated = battinfo.CellSpec(
            manufacturer="Example Lab",
            model="R2032",
            format="coin",
            chemistry="Li-ion",
            properties={"rated_capacity": {"value": 3.0, "unit": "mAh"}},
        )
        ws.add("cell", spec=plain, serial_numbers=["C01", "C02"])
        ws.add("cell", spec=rated, names=["half cell X"])
        if pinned:
            for spec, iri in zip(ws._ws.cell_specs, SPECS_SAVED_BEFORE_0_8_0, strict=True):
                spec.id = iri
        ws.save()
        return {
            "specs": [str(spec.id) for spec in ws._ws.cell_specs],
            "cells": [str(cell.id) for cell in ws._ws.cells],
        }

    saved = session(pinned=True)
    assert saved == {"specs": SPECS_SAVED_BEFORE_0_8_0, "cells": CELLS_SAVED_BEFORE_0_8_0}
    files = (_records_in(root, "cell-spec"), _records_in(root, "cell-instance"))

    assert session(pinned=False) == saved
    assert (_records_in(root, "cell-spec"), _records_in(root, "cell-instance")) == files
    # A fresh session finds one cell under each serial.
    fresh = battinfo.workspace(root, registry_url=None)
    assert fresh._resolve_cell("C01").id == CELLS_SAVED_BEFORE_0_8_0[0]


# What 057b66a0 minted for one cell spec saved on its own (chemistry spelled
# Li-ion, not as its vocabulary key) and its cell C01: the plain natural-key IRI
# of before 0.8.0, and the cell seeded from it.
SPEC_SAVED_ALONE_BEFORE_0_8_0 = "https://w3id.org/battinfo/spec/8tdq-hs3n-kqf4-bmhb"
CELL_SAVED_ALONE_BEFORE_0_8_0 = "https://w3id.org/battinfo/cell/a9qe-9ymx-n3sc-855k"


def _li_ion_spec(rated: float):
    import battinfo

    return battinfo.CellSpec(
        manufacturer="Example Lab",
        model="R2032",
        format="coin",
        chemistry="Li-ion",
        properties={"rated_capacity": {"value": rated, "unit": "mAh"}},
    )


def _save_spec_alone_before_0_8_0(root: Path) -> dict:
    """Save the spec and C01 as 057b66a0 did, by pinning the IRI it minted; return the saved spec record."""
    import battinfo

    first = battinfo.workspace(root, registry_url=None)
    first.add("cell", spec=_li_ion_spec(2.0), serial_numbers=["C01"])
    first._ws.cell_specs[0].id = SPEC_SAVED_ALONE_BEFORE_0_8_0
    first.save()
    assert [str(cell.id) for cell in first._ws.cells] == [CELL_SAVED_ALONE_BEFORE_0_8_0]
    return _records_in(root, "cell-spec")["cell-spec-8tdq-hs3n-kqf4-bmhb.json"]


@pytest.mark.parametrize("sibling_first", [False, True], ids=["sibling added after", "sibling added before"])
def test_a_spec_saved_alone_before_0_8_0_keeps_its_iri_when_a_sibling_joins(
    tmp_path: Path, sibling_first: bool
) -> None:
    """The sibling shares the natural key of before 0.8.0; only the spec the saved record describes takes its IRI."""
    import battinfo

    root = tmp_path / "lab"
    saved = _save_spec_alone_before_0_8_0(root)

    rerun = battinfo.workspace(root, registry_url=None)
    adds = [(_li_ion_spec(2.0), "C01"), (_li_ion_spec(3.0), "C02")]
    for spec, serial in reversed(adds) if sibling_first else adds:
        rerun.add("cell", spec=spec, serial_numbers=[serial])
    rerun.save()

    by_serial = {cell.serial_number: cell for cell in rerun._ws.cells}
    assert by_serial["C01"].id == CELL_SAVED_ALONE_BEFORE_0_8_0
    assert by_serial["C01"].cell_spec_id == SPEC_SAVED_ALONE_BEFORE_0_8_0
    assert by_serial["C02"].cell_spec_id not in (None, SPEC_SAVED_ALONE_BEFORE_0_8_0)
    specs = _records_in(root, "cell-spec")
    assert len(specs) == 2 and len(_records_in(root, "cell-instance")) == 2
    assert specs["cell-spec-8tdq-hs3n-kqf4-bmhb.json"]["properties"] == saved["properties"]
    fresh = battinfo.workspace(root, registry_url=None)
    assert fresh._resolve_cell("C01").id == CELL_SAVED_ALONE_BEFORE_0_8_0


def test_a_sibling_never_takes_the_iri_of_a_spec_saved_alone_before_0_8_0(tmp_path: Path) -> None:
    """When no spec of the session is the saved one (it was edited as the sibling joined), none takes its IRI."""
    import battinfo

    root = tmp_path / "lab"
    saved = _save_spec_alone_before_0_8_0(root)

    rerun = battinfo.workspace(root, registry_url=None)
    rerun.add("cell", spec=_li_ion_spec(2.5), serial_numbers=["C01"])
    rerun.add("cell", spec=_li_ion_spec(3.0), serial_numbers=["C02"])
    rerun.save()

    assert SPEC_SAVED_ALONE_BEFORE_0_8_0 not in {spec.id for spec in rerun._ws.cell_specs}
    assert _records_in(root, "cell-spec")["cell-spec-8tdq-hs3n-kqf4-bmhb.json"] == saved
