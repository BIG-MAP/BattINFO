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
