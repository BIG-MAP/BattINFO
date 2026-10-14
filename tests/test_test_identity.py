"""A test's IRI names one run on one cell, told apart by its data, never by its title.

A test is seeded from its cell, its kind, the protocol it followed (the
protocol's IRI whenever the test names one) and the run: the location of its
first data file, or, for a test without one, the start time the caller gives.
The name is display text. A test saved before 0.8.0 keeps its IRI: the rule of
before 0.8.0 is minted as well, and a saved test with the same cell, kind,
protocol and data files keeps the IRI it was saved under, and so do its
datasets.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402
from battinfo import api, entities  # noqa: E402
from battinfo._workspace import Workspace  # noqa: E402
from battinfo.bundle import CellSpec, Test, TestSpec  # noqa: E402

GOLDEN = json.loads((ROOT / "tests" / "fixtures" / "identity" / "golden-iris.json").read_text(encoding="utf-8"))["iris"]

# The cell spec and data of the golden table's workspace cases (tests/test_golden_iris.py).
SPEC = {"manufacturer": "Example Lab", "model": "R2032 half cell", "format": "coin", "chemistry": "li-ion"}
PROTOCOL_IRI = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"
OTHER_PROTOCOL_IRI = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-eeee"
CELL_IRI = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-dddd"


def _workspace(root: Path) -> battinfo.AuthoringWorkspace:
    root.mkdir(parents=True, exist_ok=True)
    return battinfo.workspace(root, registry_url=None)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _records(root: Path, folder: str) -> dict[str, dict]:
    """The records saved under ``.battinfo/records/<folder>``, by file name."""
    directory = root / ".battinfo" / "records" / folder
    return {path.name: json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))}


def _test_body(root: Path, iri: str) -> dict:
    uid = iri.rsplit("/", 1)[-1]
    return _records(root, "test")[f"test-{uid}.json"]["test"]


# ── The seed ──────────────────────────────────────────────────────────────────


def test_the_seed_is_the_cell_kind_protocol_and_run() -> None:
    seed = entities.test_identity_seed
    base = {"cell_id": CELL_IRI, "kind": "cycling"}
    assert seed(**base) == f"{CELL_IRI}::cycling::::"
    # The protocol enters as its IRI whenever the test names one, whatever its name.
    assert seed(**base, protocol_id=PROTOCOL_IRI, protocol_name="Formation C/10") == seed(
        **base, protocol_id=PROTOCOL_IRI, protocol_name="Ageing 1C"
    )
    assert seed(**base, protocol_id=PROTOCOL_IRI) != seed(**base, protocol_id=OTHER_PROTOCOL_IRI)
    # Without an IRI it enters as its name, and not at all when the name only restates the kind.
    assert seed(**base, protocol_name="CCCV 1C") == f"{CELL_IRI}::cycling::CCCV 1C::"
    assert seed(cell_id=CELL_IRI, kind="capacity_check", protocol_name="capacity check") == seed(
        cell_id=CELL_IRI, kind="capacity_check"
    )
    # The run: the first data file's locator, else the start time the caller gave.
    assert seed(**base, data_locator="data/C01.csv") == f"{CELL_IRI}::cycling::::data/C01.csv"
    assert seed(**base, data_locator="data/C01.csv", started_at=1790845200) == seed(**base, data_locator="data/C01.csv")
    assert seed(**base, started_at=1790845200) == f"{CELL_IRI}::cycling::::started_at=1790845200"
    assert seed(**base, started_at="2026-10-01T09:00:00Z") == seed(**base, started_at=1790845200)
    assert seed(**base, started_at="2026-10-01T09:00:00+00:00") == seed(**base, started_at=1790845200)


def test_the_seed_of_before_0_8_0_is_kept_to_find_saved_tests() -> None:
    seed = entities.legacy_test_identity_seed
    assert seed(cell_id=CELL_IRI, kind="cycling", protocol_name="cycling", name="C01 cycling") == (
        f"{CELL_IRI}::cycling::cycling::C01 cycling"
    )
    assert seed(cell_id=CELL_IRI, kind="cycling", protocol_name=None, name=None) == f"{CELL_IRI}::cycling::test::test"


# ── Runs, sessions and re-runs ───────────────────────────────────────────────


def _lab(tmp_path: Path) -> Path:
    root = tmp_path / "lab"
    _write(root / "data" / "a.csv", "test_time_second,voltage_volt\n0,3.0\n60,3.1\n")
    _write(root / "data" / "b.csv", "test_time_second,voltage_volt\n0,3.0\n60,3.2\n")
    return root


def _add_run(root: Path, data: str, *, instrument: str = "Cycler-1") -> tuple[str, list[str]]:
    """One session: the cell, one cycling run on it from *data*, saved. Returns the test and dataset IRIs."""
    ws = _workspace(root)
    ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    (test,) = ws.add("test", type="cycling", cell="C01", data=data, instrument=instrument)
    ws.save()
    return str(test.id), sorted(str(d.id) for d in ws._ws.datasets)


def test_a_second_run_in_a_new_session_gets_its_own_iri(tmp_path: Path) -> None:
    root = _lab(tmp_path)
    first, first_datasets = _add_run(root, "data/a.csv", instrument="Cycler-1")
    saved = _test_body(root, first)

    second, second_datasets = _add_run(root, "data/b.csv", instrument="Cycler-2")

    assert second != first
    assert set(second_datasets).isdisjoint(first_datasets)
    # The first run's record is still there, untouched by the second.
    assert _test_body(root, first) == saved
    assert saved["instrument_name"] == "Cycler-1" and saved["dataset_ids"] == first_datasets
    assert len(_records(root, "test")) == 2


def test_adding_the_same_run_again_changes_nothing(tmp_path: Path) -> None:
    root = _lab(tmp_path)
    first, first_datasets = _add_run(root, "data/a.csv")
    saved = _records(root, "test")

    ws = _workspace(root)
    ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    (test,) = ws.add("test", type="cycling", cell="C01", data="data/a.csv", instrument="Cycler-1")
    (again,) = ws.add("test", type="cycling", cell="C01", data="data/a.csv", instrument="Cycler-1")
    result = ws.save()

    assert again is test
    assert test.id == first
    assert sorted(str(d.id) for d in ws._ws.datasets) == first_datasets
    (saved_test,) = result["tests"]
    assert saved_test["status"] == "updated" and saved_test["content_changed"] is False
    assert _records(root, "test") == saved


def test_renaming_a_test_keeps_its_iri(tmp_path: Path) -> None:
    root = _lab(tmp_path)
    minted = []
    for name in ("C01 first cycling run", "Graphite AQ-1 cell C01, cycling at 25 degC"):
        ws = _workspace(tmp_path / name.replace(" ", "-").replace(",", ""))
        _write(ws._root / "data" / "a.csv", (root / "data" / "a.csv").read_text(encoding="utf-8"))
        ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
        (test,) = ws.add("test", type="cycling", cell="C01", data="data/a.csv", name=name)
        ws.save()
        minted.append(test.id)
    assert minted[0] == minted[1]


def test_the_cell_reference_does_not_change_the_test_iri(tmp_path: Path) -> None:
    """A generated title such as "C01 cycling" depends on how the cell was referenced; the IRI does not."""
    root = _lab(tmp_path)
    by_serial, _ = _add_run(root, "data/a.csv")
    cell_iri = _test_body(root, by_serial)["cell_id"]

    ws = _workspace(root)
    (test,) = ws.add("test", type="cycling", cell=cell_iri, data="data/a.csv", instrument="Cycler-1")
    ws._ws.render()

    assert test.id == by_serial


def test_two_runs_under_two_protocols_referenced_by_iri_get_two_iris(tmp_path: Path) -> None:
    """Neither protocol is saved in the workspace; each run is seeded from its protocol's IRI."""

    def alone(folder: str, protocol: str) -> str:
        ws = _workspace(tmp_path / folder)
        ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
        (test,) = ws.add("test", type="cycling", cell="C01", spec=protocol)
        ws._ws.render()
        return str(test.id)

    ws = _workspace(tmp_path / "both")
    ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    (formation,) = ws.add("test", type="cycling", cell="C01", spec=PROTOCOL_IRI)
    (ageing,) = ws.add("test", type="cycling", cell="C01", spec=OTHER_PROTOCOL_IRI)
    ws.save()

    assert formation.id != ageing.id
    # Each is the IRI the run gets on its own, not one minted from content to keep two apart.
    assert formation.id == alone("formation", PROTOCOL_IRI)
    assert ageing.id == alone("ageing", OTHER_PROTOCOL_IRI)


def test_a_run_has_one_iri_however_its_protocol_is_passed(tmp_path: Path) -> None:
    """A TestSpec object, its IRI once saved here, and that IRI in a folder that never saw it give one test IRI."""
    root = _lab(tmp_path)
    first = _workspace(root)
    first.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    (as_object,) = first.add(
        "test", type="cycling", cell="C01", data="data/a.csv", spec=TestSpec(name="CCCV 1C", test_kind="cycling")
    )
    first.save()
    protocol_iri = str(first._ws.test_specs[0].id)

    second = _workspace(root)
    (by_saved_iri,) = second.add("test", type="cycling", cell="C01", data="data/a.csv", spec=protocol_iri)
    second._ws.render()

    elsewhere = _workspace(tmp_path / "elsewhere")
    _write(elsewhere._root / "data" / "a.csv", (root / "data" / "a.csv").read_text(encoding="utf-8"))
    elsewhere.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    (by_iri,) = elsewhere.add("test", type="cycling", cell="C01", data="data/a.csv", spec=protocol_iri)
    elsewhere._ws.render()

    assert as_object.id == by_saved_iri.id == by_iri.id


def test_a_later_session_under_another_protocol_does_not_overwrite_the_first_run(tmp_path: Path) -> None:
    root = tmp_path / "lab"
    first = _workspace(root)
    first.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    (formation,) = first.add("test", type="cycling", cell="C01", spec=PROTOCOL_IRI)
    first.save()

    second = _workspace(root)
    (ageing,) = second.add("test", type="cycling", cell="C01", spec=OTHER_PROTOCOL_IRI)
    second.save()

    assert ageing.id != formation.id
    assert _test_body(root, str(formation.id))["protocol_id"] == PROTOCOL_IRI
    assert _test_body(root, str(ageing.id))["protocol_id"] == OTHER_PROTOCOL_IRI


def test_a_start_time_tells_two_runs_without_data_apart(tmp_path: Path) -> None:
    ws = _workspace(tmp_path / "lab")
    ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    (morning,) = ws.add("test", type="cycling", cell="C01", started_at="2026-10-01T09:00:00Z")
    (evening,) = ws.add("test", type="cycling", cell="C01", started_at=1790881200)
    ws.save()

    assert morning.id != evening.id
    assert _test_body(tmp_path / "lab", str(morning.id))["started_at"] == 1790845200
    # The same start time in another form is the same run.
    again = _workspace(tmp_path / "again")
    again.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    (same,) = again.add("test", type="cycling", cell="C01", started_at=1790845200)
    again._ws.render()
    assert same.id == morning.id


def test_a_start_time_given_with_data_is_recorded_and_the_data_decides_the_iri(tmp_path: Path) -> None:
    root = _lab(tmp_path)
    plain, _ = _add_run(root, "data/a.csv")

    ws = _workspace(tmp_path / "timed")
    _write(ws._root / "data" / "a.csv", (root / "data" / "a.csv").read_text(encoding="utf-8"))
    ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    (test,) = ws.add(
        "test",
        type="cycling",
        cell="C01",
        data="data/a.csv",
        instrument="Cycler-1",
        started_at="2026-10-01T09:00:00Z",
        ended_at="2026-10-01T21:00:00Z",
    )
    ws.save()

    assert test.id == plain
    body = _test_body(ws._root, str(test.id))
    assert body["started_at"] == 1790845200 and body["ended_at"] == 1790888400


def test_a_start_time_that_is_not_a_time_is_refused_before_anything_is_added(tmp_path: Path) -> None:
    ws = _workspace(tmp_path / "lab")
    ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    with pytest.raises(ValueError, match="started_at"):
        ws.add("test", type="cycling", cell="C01", started_at="last Tuesday")
    assert ws._ws.tests == []


def test_converting_again_after_a_converter_upgrade_keeps_the_test_iri(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An upgraded converter can add the measured start time to the converted file; the IRI stays."""
    pytest.importorskip("bdf")
    import battinfo.processing as processing

    root = tmp_path / "lab"
    _write(root / "C01.csv", "test_time_second,voltage_volt,current_ampere\n0,3.7,1.0\n60,3.71,1.0\n")

    def session() -> tuple[str, list[str], dict]:
        ws = _workspace(root)
        ws.convert("*.csv")
        ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
        (test,) = ws.add("test", type="cycling", cell="C01", data="bdf/C01.bdf.csv")
        ws.save()
        return str(test.id), sorted(str(d.id) for d in ws._ws.datasets), _test_body(root, str(test.id))

    before, datasets_before, body_before = session()
    assert "started_at" not in body_before

    read = processing._read_bdf_pandas

    def read_with_clock(*args, **kwargs):
        # A converter that reads the instrument's wall clock adds this column.
        frame, meta = read(*args, **kwargs)
        frame["Unix Time / s"] = 1790845200 + frame["Test Time / s"]
        return frame, meta

    monkeypatch.setattr(processing, "_read_bdf_pandas", read_with_clock)
    (root / "bdf" / "C01.bdf.csv").unlink()
    after, datasets_after, body_after = session()

    assert body_after["started_at"] == 1790845200
    assert after == before
    assert datasets_after == datasets_before


# ── Workspaces and records saved before 0.8.0 ────────────────────────────────


def test_a_workspace_saved_before_the_change_keeps_its_test_and_dataset_iris(tmp_path: Path) -> None:
    """The golden table holds what the workspace minted before 0.8.0 for these calls.

    The first session pins those test IRIs, so its records are the ones the
    earlier release saved; its datasets mint the earlier dataset IRIs from
    them. The second session runs the same calls with nothing pinned.
    """
    root = tmp_path / "ws"
    _write(root / "data" / "C01.csv", "time_s,voltage_V\n0,3.0\n")
    cases = {
        "unnamed": {"type": "cycling"},
        "named": {"type": "formation", "name": "C01 formation run"},
        "with data": {"type": "capacity_check", "data": "data/C01.csv"},
        "protocol object": {
            "type": "rate_capability",
            "spec": lambda: TestSpec(name="CCCV 1C", test_kind="rate_capability"),
        },
        "protocol by IRI, not saved here": {"type": "gitt", "spec": PROTOCOL_IRI},
    }

    def session(pinned: bool) -> dict[str, str]:
        ws = _workspace(root)
        ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
        tests = {}
        for case, fields in cases.items():
            kwargs = {key: value() if callable(value) else value for key, value in fields.items()}
            if pinned:
                kwargs["iri"] = GOLDEN[f"test | ws | {case}"]
            (tests[case],) = ws.add("test", cell="C01", **kwargs)
        ws.save()
        minted = {case: str(test.id) for case, test in tests.items()}
        minted["datasets"] = ", ".join(sorted(str(d.id) for d in ws._ws.datasets))
        return minted

    saved = session(pinned=True)
    assert saved["datasets"] == GOLDEN["dataset | ws | local file"]
    files = (_records(root, "test"), _records(root, "dataset"))

    rerun = session(pinned=False)

    assert rerun == saved
    assert (set(_records(root, "test")), set(_records(root, "dataset"))) == (set(files[0]), set(files[1]))


def test_two_runs_saved_before_the_change_keep_their_iris(tmp_path: Path) -> None:
    """Two unnamed runs of one kind on one cell were kept apart by minting from their content."""
    root = tmp_path / "ws"
    for name in ("a.csv", "b.csv"):
        _write(root / "data" / name, f"time_s,voltage_V\n0,{3.0 if name == 'a.csv' else 3.1}\n")

    def session(pinned: bool) -> dict[str, str]:
        ws = _workspace(root)
        ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
        tests = {}
        for name in ("a.csv", "b.csv"):
            pin = {"iri": GOLDEN[f"test | ws | colliding pair, {name}"]} if pinned else {}
            (tests[name],) = ws.add("test", type="cycling", cell="C01", data=f"data/{name}", **pin)
        ws.save()
        minted = {name: str(test.id) for name, test in tests.items()}
        minted["datasets"] = ", ".join(sorted(str(d.id) for d in ws._ws.datasets))
        return minted

    saved = session(pinned=True)
    assert saved["datasets"] == GOLDEN["dataset | ws | colliding pair"]

    assert session(pinned=False) == saved
    assert len(_records(root, "test")) == 2 and len(_records(root, "dataset")) == 2


def test_a_saved_test_is_kept_only_for_the_same_run(tmp_path: Path) -> None:
    """The IRI of before 0.8.0 is kept only when the saved test has this run's data files."""
    root = tmp_path / "ws"
    _write(root / "data" / "C01.csv", "time_s,voltage_V\n0,3.0\n")
    _write(root / "data" / "C01-other.csv", "time_s,voltage_V\n0,3.0\n")
    ws = _workspace(root)
    ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    ws.add("test", type="capacity_check", cell="C01", data="data/C01.csv", iri=GOLDEN["test | ws | with data"])
    ws.save()

    rerun = _workspace(root)
    rerun.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    (other,) = rerun.add("test", type="capacity_check", cell="C01", data="data/C01-other.csv")
    rerun.save()

    assert other.id != GOLDEN["test | ws | with data"]
    assert _test_body(root, GOLDEN["test | ws | with data"])["dataset_ids"] == [GOLDEN["dataset | ws | local file"]]


def _engine_cell_iri(root: Path) -> str:
    engine = Workspace(root)
    cell = engine.cell(engine.cell_spec(**SPEC), serial_number="C01")
    engine.render()
    return str(cell.id)


def test_a_test_saved_by_save_test_before_the_change_keeps_its_iri(tmp_path: Path) -> None:
    cell_iri = _engine_cell_iri(tmp_path / "engine")
    old = GOLDEN["test | save | named"]
    fields = {"cell_instance_id": cell_iri, "test_kind": "formation", "name": "C01 formation run"}
    root = tmp_path / "records"
    api.save_test(Test(id=old, **fields), source_root=root, resolve_references=False)

    again = api.save_test(Test(**fields), source_root=root, mode="upsert", resolve_references=False)

    assert again["id"] == old
    assert again["status"] == "updated" and again["content_changed"] is False
    doc = {"schema_version": "1.0", "test": {"cell_id": cell_iri, "kind": "formation", "name": "C01 formation run"}}
    without_id = api.save_record(
        doc, source_root=root, mode="upsert", validate=False, dry_run=True, resolve_references=False
    )
    assert without_id["id"] == old


def test_save_test_tells_runs_apart_by_their_start_time(tmp_path: Path) -> None:
    cell_iri = _engine_cell_iri(tmp_path / "engine")
    root = tmp_path / "records"
    first = api.save_test(
        Test(cell_instance_id=cell_iri, test_kind="cycling", started_at=1790845200),
        source_root=root,
        resolve_references=False,
    )
    second = api.save_test(
        Test(cell_instance_id=cell_iri, test_kind="cycling", started_at=1790881200),
        source_root=root,
        resolve_references=False,
    )
    assert first["id"] != second["id"]
    assert len(list((root / "test").glob("*.json"))) == 2
