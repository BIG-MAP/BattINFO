"""Running a notebook cell twice adds nothing and keeps every IRI.

A notebook re-runs cells: ``ws.load()`` of the same draft, ``ws.add("cell")``
and ``ws.add("test")`` with the same arguments. Each repeat reuses the record
the session already holds, so the next ``ws.save()`` writes what one run
writes, and a pinned IRI stays where it was pinned. Two different records
that claim one IRI are refused.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import battinfo
from battinfo.ws import AuthoringWorkspace

SPEC_PIN = "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5"
CELL_PIN = "https://w3id.org/battinfo/cell/7k2m-4q8r-9tvx-3hd5"
OTHER_CELL_PIN = "https://w3id.org/battinfo/cell/7k2m-4q8r-9tvx-3hd6"
TEST_PIN = "https://w3id.org/battinfo/test/7d9k-2m4p-8t3x-6nq6"
DATASET_PIN = "https://w3id.org/battinfo/dataset/7d9k-2m4p-8t3x-6nq7"

SPEC_DRAFT = {
    "id": SPEC_PIN,
    "manufacturer": "Example Lab",
    "model": "R2032 graphite half cell",
    "format": "coin",
    "chemistry": "li-ion",
    "properties": {"nominal_capacity": {"value": 0.005, "unit": "Ah"}},
}
TEST_SPEC_DRAFT = {"name": "Formation C/10", "type": "cycling", "steps": ["Charge at C/10 until 1.5 V"]}


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "lab"
    (root / "data").mkdir(parents=True)
    (root / "spec.cell-spec.json").write_text(json.dumps(SPEC_DRAFT), encoding="utf-8")
    (root / "formation.test-spec.json").write_text(json.dumps(TEST_SPEC_DRAFT), encoding="utf-8")
    (root / "data" / "C01.csv").write_text("test_time_second,voltage_volt\n0,3.0\n60,3.1\n", encoding="utf-8")
    (root / "data" / "C01-b.csv").write_text("test_time_second,voltage_volt\n0,3.0\n60,3.2\n", encoding="utf-8")
    return root


def _notebook(ws: AuthoringWorkspace) -> dict:
    """The cells of a small notebook, as a user runs them."""
    spec = ws.load("spec.cell-spec.json")
    protocol = ws.load("formation.test-spec.json")
    ws.add("cell", spec=spec, serial_numbers=["C01"], iris=[CELL_PIN])
    ws.add("cell", spec=spec, names=["spare"])
    (test,) = ws.add(
        "test", type="cycling", cell="C01", spec=protocol, data="data/C01.csv", iri=TEST_PIN, dataset_iris=[DATASET_PIN]
    )
    (unpinned,) = ws.add("test", type="capacity_check", cell="C01", data="data/C01-b.csv")
    return {"spec": spec, "protocol": protocol, "test": test, "unpinned": unpinned}


def _files(root: Path) -> dict[str, str]:
    records = root / ".battinfo" / "records"
    return {
        path.relative_to(records).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(records.rglob("*.json"))
    }


# A dataset saved without a publication time takes the save time as created_at
# and published_at, so saving it again in a new session changes those stamps.
SAVE_TIME = ("created_at", "modified_at", "published_at", "retrieved_at")


def _without_save_time(files: dict[str, str]) -> dict[str, dict]:
    records = {}
    for name, text in files.items():
        doc = json.loads(text)
        for part in doc.values():
            if isinstance(part, dict):
                for key in SAVE_TIME:
                    part.pop(key, None)
        records[name] = doc
    return records


def _saved_items(result: dict) -> list[dict]:
    keys = ("cell_specs", "cell_instances", "test_specs", "tests", "datasets")
    return [item for key in keys for item in result.get(key, [])]


def _session_size(ws: AuthoringWorkspace) -> tuple[int, ...]:
    engine = ws._ws
    return tuple(
        len(items) for items in (engine.cell_specs, engine.cells, engine.test_specs, engine.tests, engine.datasets)
    )


def test_running_the_notebook_again_after_a_save_changes_nothing(tmp_path: Path) -> None:
    root = _root(tmp_path)
    ws = AuthoringWorkspace(root=root, registry_url=None)
    first = _notebook(ws)
    ws.save()
    files, size = _files(root), _session_size(ws)

    again = _notebook(ws)
    result = ws.save()

    assert _session_size(ws) == size
    assert all(again[key] is first[key] for key in first), "a repeat must hand back the object the session holds"
    assert all(item["status"] == "updated" and item["content_changed"] is False for item in _saved_items(result))
    assert _files(root) == files
    assert (again["spec"].id, again["test"].id) == (SPEC_PIN, TEST_PIN)


def test_running_cells_twice_before_the_save_writes_what_one_run_writes(tmp_path: Path) -> None:
    once = _root(tmp_path / "once")
    ws = AuthoringWorkspace(root=once, registry_url=None)
    _notebook(ws)
    ws.save()

    twice = _root(tmp_path / "twice")
    ws = AuthoringWorkspace(root=twice, registry_url=None)
    _notebook(ws)
    _notebook(ws)
    ws.save()

    assert _files(twice).keys() == _files(once).keys()
    saved = {json.loads(text).get("cell_instance", {}).get("id") for text in _files(twice).values()}
    assert CELL_PIN in saved


def test_a_new_session_running_the_notebook_twice_leaves_the_records_as_they_are(tmp_path: Path) -> None:
    root = _root(tmp_path)
    ws = AuthoringWorkspace(root=root, registry_url=None)
    _notebook(ws)
    ws.save()
    files = _files(root)

    again = AuthoringWorkspace(root=root, registry_url=None)
    _notebook(again)
    _notebook(again)
    result = again.save()

    assert all(item["status"] == "updated" for item in _saved_items(result))
    assert _without_save_time(_files(root)) == _without_save_time(files)


def test_an_unpinned_test_added_twice_in_a_new_session_is_saved_once(tmp_path: Path) -> None:
    root = _root(tmp_path)
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.add("cell", spec=ws.load("spec.cell-spec.json"), serial_numbers=["C01"])
    ws.add("test", type="cycling", cell="C01", data="data/C01.csv")
    ws.save()
    files = _files(root)

    again = AuthoringWorkspace(root=root, registry_url=None)
    for _ in range(2):
        again.add("test", type="cycling", cell="C01", data="data/C01.csv")
    result = again.save()

    assert len(again._ws.tests) == len(again._ws.datasets) == 1
    assert all(item["status"] == "updated" for item in _saved_items(result))
    assert _without_save_time(_files(root)) == _without_save_time(files)


def test_the_same_cell_iri_map_added_twice_keeps_its_iris(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "cell_iris.json").write_text(
        json.dumps({"cell one": CELL_PIN, "cell two": OTHER_CELL_PIN}), encoding="utf-8"
    )
    ws = AuthoringWorkspace(root=root, registry_url=None)
    spec = ws.load("spec.cell-spec.json")
    first = ws.add("cell", spec=spec, from_file="cell_iris.json")
    assert ws.add("cell", spec=spec, from_file="cell_iris.json") == []
    ws.save()

    assert len(first) == len(ws._ws.cells) == 2
    saved = sorted(
        json.loads(text)["cell_instance"]["id"] for name, text in _files(root).items() if "cell-instance" in name
    )
    assert saved == sorted([CELL_PIN, OTHER_CELL_PIN])


def test_an_inline_test_spec_built_again_is_one_test_spec(tmp_path: Path) -> None:
    root = _root(tmp_path)
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.add("cell", spec=battinfo.CellSpec(**{k: v for k, v in SPEC_DRAFT.items() if k != "id"}), serial_numbers=["C01"])
    for _ in range(2):
        protocol = battinfo.TestSpec(name="GITT", kind="gitt", source_type="manual")
        ws.add("test", cell="C01", spec=protocol, data="data/C01.csv")
    assert len(ws._ws.test_specs) == len(ws._ws.tests) == len(ws._ws.datasets) == 1
    ws.save()
    assert ws._ws.tests[0].protocol_id == ws._ws.test_specs[0].id


def test_a_search_result_loaded_twice_still_resolves_its_serial(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=_root(tmp_path), registry_url=None)
    hit = {"type": "cell", "id": CELL_PIN, "serial_number": "R-007", "cell_spec_id": SPEC_PIN}
    first = ws.load(hit)
    assert ws.load(hit) is first
    assert ws._resolve_cell("R-007") is first


def test_a_different_test_or_different_data_is_still_a_new_record(tmp_path: Path) -> None:
    root = _root(tmp_path)
    ws = AuthoringWorkspace(root=root, registry_url=None)
    spec = ws.load("spec.cell-spec.json")
    ws.add("cell", spec=spec, serial_numbers=["C01"])
    a = ws.add("test", type="cycling", cell="C01", data="data/C01.csv")[0]
    b = ws.add("test", type="cycling", cell="C01", data="data/C01-b.csv")[0]
    c = ws.add("test", type="cycling", cell="C01", data="data/C01.csv", instrument="Cycler 2")[0]
    assert len({id(a), id(b), id(c)}) == 3
    assert len(ws._ws.tests) == len(ws._ws.datasets) == 3


def test_an_edited_draft_that_pins_a_held_iri_is_refused(tmp_path: Path) -> None:
    root = _root(tmp_path)
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.load("spec.cell-spec.json")
    (root / "spec.cell-spec.json").write_text(json.dumps({**SPEC_DRAFT, "model": "R2032 corrected"}), encoding="utf-8")
    with pytest.raises(ValueError, match="One IRI names one record"):
        ws.load("spec.cell-spec.json")
    assert len(ws._ws.cell_specs) == 1


def test_two_cells_cannot_pin_one_iri(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=_root(tmp_path), registry_url=None)
    spec = ws.load("spec.cell-spec.json")
    with pytest.raises(ValueError, match="more than one cell"):
        ws.add("cell", spec=spec, serial_numbers=["C01", "C02"], iris=[CELL_PIN, CELL_PIN])
    ws.add("cell", spec=spec, serial_numbers=["C01"], iris=[CELL_PIN])
    with pytest.raises(ValueError, match="already the IRI of cell 'C01'"):
        ws.add("cell", spec=spec, serial_numbers=["C02"], iris=[CELL_PIN])
    assert [cell.serial_number for cell in ws._ws.cells] == ["C01"]


def test_a_pinned_test_with_other_content_is_refused_and_leaves_nothing_behind(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=_root(tmp_path), registry_url=None)
    spec = ws.load("spec.cell-spec.json")
    ws.add("cell", spec=spec, serial_numbers=["C01"])
    ws.add("test", type="cycling", cell="C01", data="data/C01.csv", iri=TEST_PIN, dataset_iris=[DATASET_PIN])
    protocol = battinfo.TestSpec(name="Other", kind="cycling", source_type="manual")
    with pytest.raises(ValueError, match="already used by another test"):
        ws.add("test", type="cycling", cell="C01", spec=protocol, data="data/C01-b.csv", iri=TEST_PIN)
    with pytest.raises(ValueError, match="dataset_iris must name distinct datasets"):
        ws.add("test", type="eis", cell="C01", data="data/C01-b.csv", dataset_iris=[DATASET_PIN])
    assert (len(ws._ws.tests), len(ws._ws.datasets), len(ws._ws.test_specs)) == (1, 1, 0)
