"""A cell label names a cell within its cell spec.

Two cell specs in one workspace can both have a ``C01``, and each is its own
cell, because a cell's IRI is seeded from its spec and its serial number (or
its name). ``ws.add("cell")`` used to look a label up across every cell the
workspace held, whatever its spec, so the second spec's cells were never made
and their tests were saved against the first spec's cells. The same call run
again still adds nothing, in this session and in a later one, and a bare label
that two cells answer to is refused, never bound to one of them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import battinfo
from battinfo.ws import AuthoringWorkspace

BY = pytest.mark.parametrize("by", ["names", "serial_numbers"])
FOUR = [("G1", "C01"), ("G1", "C02"), ("N8", "C01"), ("N8", "C02")]


def _specs() -> tuple[battinfo.CellSpec, battinfo.CellSpec]:
    """Two cell specs, built anew on each call as a script that runs again builds them."""
    graphite = battinfo.CellSpec(manufacturer="Acme", model="G1", format="coin", chemistry="li-ion")
    nmc = battinfo.CellSpec(manufacturer="Acme", model="N8", format="coin", chemistry="li-ion")
    return graphite, nmc


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "lab"
    (root / "raw").mkdir(parents=True)
    for name in ("nmc-C01.csv", "g-C01.csv", "C01.csv"):
        (root / "raw" / name).write_text("test_time_second,voltage_volt\n0,3.0\n60,3.1\n", encoding="utf-8")
    return root


def _script(ws: AuthoringWorkspace, by: str) -> tuple[list, list]:
    """The authoring script: the cells C01 and C02 of each spec, given as names or as serial numbers."""
    graphite, nmc = _specs()
    first = ws.add("cell", spec=graphite, **{by: ["C01", "C02"]})
    second = ws.add("cell", spec=nmc, **{by: ["C01", "C02"]})
    return first, second


def _records(root: Path, folder: str, key: str) -> list[dict]:
    paths = sorted((root / ".battinfo" / "records" / folder).glob("*.json"))
    return [json.loads(path.read_text(encoding="utf-8"))[key] for path in paths]


def _saved_cells(root: Path) -> dict[tuple[str, str], str]:
    """The IRI of each saved cell, by its spec's model and its label."""
    models = {spec["id"]: spec["model"] for spec in _records(root, "cell-spec", "cell_spec")}
    cells = _records(root, "cell-instance", "cell_instance")
    saved = {(models[cell["cell_spec_id"]], cell.get("serial_number") or cell["name"]): cell["id"] for cell in cells}
    assert len(saved) == len(cells), "two saved cells of one spec share a label"
    return saved


# ── Adding the cells ──────────────────────────────────────────────────────────


@BY
def test_a_second_spec_gets_its_own_cells_under_the_labels_the_first_uses(tmp_path: Path, capsys, by: str) -> None:
    root = _root(tmp_path)
    ws = AuthoringWorkspace(root=root, registry_url=None)

    first, second = _script(ws, by)

    assert "already in this workspace" not in capsys.readouterr().out
    assert len(ws._ws.cells) == 4 and all(new is not old for new, old in zip(second, first))
    assert [cell.cell_spec.model for cell in second] == ["N8", "N8"]

    ws.add("test", type="cycling", cell=second[0], data="raw/nmc-C01.csv")
    ws.save()

    cells = _saved_cells(root)
    assert sorted(cells) == FOUR and len(set(cells.values())) == 4
    (test,) = _records(root, "test", "test")
    (dataset,) = _records(root, "dataset", "dataset")
    assert test["cell_id"] == cells[("N8", "C01")]
    assert cells[("N8", "C01")] in dataset["about"] and cells[("G1", "C01")] not in dataset["about"]


@BY
def test_the_same_calls_run_again_add_nothing_and_return_the_same_cells(tmp_path: Path, capsys, by: str) -> None:
    root = _root(tmp_path)
    ws = AuthoringWorkspace(root=root, registry_url=None)
    first, second = _script(ws, by)
    capsys.readouterr()

    again = _script(ws, by)

    assert capsys.readouterr().out.count("2 already in this workspace, reusing them: ['C01', 'C02']") == 2
    assert all(held is made for held, made in zip([*again[0], *again[1]], [*first, *second]))
    assert len(ws._ws.cells) == 4 and len(ws._ws.cell_specs) == 2

    ws.save()
    cells = _saved_cells(root)
    after_save = _script(ws, by)  # the cells now hold their spec as its IRI

    assert all(held is made for held, made in zip([*after_save[0], *after_save[1]], [*first, *second]))
    assert len(ws._ws.cells) == 4 and len(ws._ws.cell_specs) == 2
    ws.save()
    assert _saved_cells(root) == cells and sorted(cells) == FOUR


@BY
@pytest.mark.parametrize("read_back_first", [False, True])
def test_a_new_session_running_the_script_again_leaves_the_four_cells_as_they_are(
    tmp_path: Path, by: str, read_back_first: bool
) -> None:
    root = _root(tmp_path)
    ws = AuthoringWorkspace(root=root, registry_url=None)
    _script(ws, by)
    ws.save()
    cells = _saved_cells(root)

    again = AuthoringWorkspace(root=root, registry_url=None)
    if read_back_first:
        again.reload_cells()  # the four saved cells are held before the script names them
    first, second = _script(again, by)
    # Read back, a saved cell is held under its spec's IRI and the script's spec has none yet.
    assert len(again._ws.cells) == (0 if read_back_first else 4)
    again.save()

    assert _saved_cells(root) == cells
    assert [cell.id for cell in [*first, *second]] == [cells[key] for key in FOUR]


def test_a_cell_saved_earlier_does_not_hold_back_a_spec_added_later(tmp_path: Path) -> None:
    root = _root(tmp_path)
    ws = AuthoringWorkspace(root=root, registry_url=None)
    graphite, nmc = _specs()
    (held,) = ws.add("cell", spec=graphite, names=["C01"])
    ws.save()

    (added,) = ws.add("cell", spec=nmc, names=["C01"])

    assert added is not held and added.cell_spec is nmc
    ws.save()
    assert sorted(_saved_cells(root)) == [("G1", "C01"), ("N8", "C01")]


def test_a_spec_named_in_either_form_of_its_iri_is_one_spec(tmp_path: Path) -> None:
    uid = "7d9k-2m4p-8t3x-6nq5"
    fields = {"manufacturer": "Acme", "model": "G1", "format": "coin", "chemistry": "li-ion"}
    ws = AuthoringWorkspace(root=_root(tmp_path), registry_url=None)
    hit = {
        "type": "cell",
        "id": "https://w3id.org/battinfo/cell/7k2m-4q8r-9tvx-3hd5",
        "serial_number": "R-007",
        "cell_spec_id": f"https://w3id.org/battinfo/spec/{uid}",
    }
    held = ws.load(hit)

    same = battinfo.CellSpec(id=f"https://w3id.org/battinfo/id/1001/spec/{uid}", **fields)
    assert ws.add("cell", spec=same, serial_numbers=["R-007"]) == [held]

    other = battinfo.CellSpec(id="https://w3id.org/battinfo/id/1001/spec/7d9k-2m4p-8t3x-6nq6", **fields)
    (added,) = ws.add("cell", spec=other, serial_numbers=["R-007"])
    assert added is not held and ws._ws.cells == [added]


def test_a_spec_with_no_iri_yet_is_compared_by_its_natural_key_when_the_session_cannot_be_finalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    ws = AuthoringWorkspace(root=root, registry_url=None)
    _script(ws, "names")
    ws.save()
    cells = _saved_cells(root)

    again = AuthoringWorkspace(root=root, registry_url=None)
    again.reload_cells()

    def refuse(*args: object, **kwargs: object) -> dict:
        raise ValueError("this session cannot be finalized as it stands")

    monkeypatch.setattr(again._ws, "_finalized_records", refuse)
    first, second = _script(again, "names")

    assert again._ws.cells == []
    assert [cell.id for cell in [*first, *second]] == [cells[key] for key in FOUR]


# ── Pinned IRIs ───────────────────────────────────────────────────────────────

G1_C01 = "https://w3id.org/battinfo/cell/7k2m-4q8r-9tvx-3hd5"
G1_C02 = "https://w3id.org/battinfo/cell/7k2m-4q8r-9tvx-3hd6"
N8_C01 = "https://w3id.org/battinfo/cell/7k2m-4q8r-9tvx-3hd7"
N8_C02 = "https://w3id.org/battinfo/cell/7k2m-4q8r-9tvx-3hd8"


def test_each_spec_takes_the_iris_its_own_map_pins_under_shared_labels(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "g1.json").write_text(json.dumps({"C01": G1_C01, "C02": G1_C02}), encoding="utf-8")
    (root / "n8.json").write_text(json.dumps({"C01": N8_C01, "C02": N8_C02}), encoding="utf-8")
    ws = AuthoringWorkspace(root=root, registry_url=None)
    graphite, nmc = _specs()

    first = ws.add("cell", spec=graphite, from_file="g1.json")
    second = ws.add("cell", spec=nmc, from_file="n8.json")

    assert [cell.id for cell in [*first, *second]] == [G1_C01, G1_C02, N8_C01, N8_C02]
    assert ws.add("cell", spec=nmc, from_file="n8.json") == second and len(ws._ws.cells) == 4
    ws.save()
    assert _saved_cells(root) == dict(zip(FOUR, [G1_C01, G1_C02, N8_C01, N8_C02]))


def test_an_iri_pinned_for_one_specs_cell_cannot_name_another_specs_cell(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "g1.json").write_text(json.dumps({"C01": G1_C01, "C02": G1_C02}), encoding="utf-8")
    ws = AuthoringWorkspace(root=root, registry_url=None)
    graphite, nmc = _specs()
    ws.add("cell", spec=graphite, from_file="g1.json")

    # Before, the map's labels were held, so the first spec's cells came back without a word.
    with pytest.raises(ValueError, match="one IRI names one cell"):
        ws.add("cell", spec=nmc, from_file="g1.json")
    with pytest.raises(ValueError, match="one IRI names one cell"):
        ws.add("cell", spec=nmc, names=["C01", "C02"], iris=[G1_C01, G1_C02])
    assert len(ws._ws.cells) == 2

    second = ws.add("cell", spec=nmc, names=["C01", "C02"], iris=[N8_C01, N8_C02])
    assert [cell.id for cell in second] == [N8_C01, N8_C02] and len(ws._ws.cells) == 4


# ── Naming one of the cells ───────────────────────────────────────────────────


@BY
def test_a_bare_label_two_cells_answer_to_is_refused_and_lists_both(tmp_path: Path, by: str) -> None:
    root = _root(tmp_path)
    ws = AuthoringWorkspace(root=root, registry_url=None)
    _script(ws, by)

    # In the session that added them, where neither spec has an IRI yet.
    with pytest.raises(ValueError, match="'C01' matches more than one cell in this workspace") as excinfo:
        ws.add("test", type="cycling", cell="C01", data="raw/C01.csv")
    message = str(excinfo.value)
    assert "spec Acme G1, no IRI until ws.save()" in message and "spec Acme N8, no IRI until ws.save()" in message
    assert "Pass the cell itself (the object ws.add('cell') returned), its IRI" in message

    # After a save.
    ws.save()
    cells = _saved_cells(root)
    with pytest.raises(ValueError, match="'C01' matches more than one cell in this workspace") as excinfo:
        ws.add("test", type="cycling", cell="C01", data="raw/C01.csv")
    assert cells[("G1", "C01")] in str(excinfo.value) and cells[("N8", "C01")] in str(excinfo.value)
    assert ws._ws.tests == [] and ws._ws.datasets == []

    # In a later session, which reads the saved cells back ...
    later = AuthoringWorkspace(root=root, registry_url=None)
    with pytest.raises(ValueError, match="'C01' matches more than one cell in this workspace") as excinfo:
        later.add("test", type="cycling", cell="C01", data="raw/C01.csv")
    assert cells[("G1", "C01")] in str(excinfo.value) and cells[("N8", "C01")] in str(excinfo.value)

    # ... and in one that runs the script again.
    rerun = AuthoringWorkspace(root=root, registry_url=None)
    _script(rerun, by)
    with pytest.raises(ValueError, match="'C01' matches more than one cell in this workspace"):
        rerun.add("test", type="cycling", cell="C01", data="raw/C01.csv")
    assert later._ws.tests == [] and rerun._ws.tests == []


@BY
def test_the_cell_object_and_the_cell_iri_each_bind_their_own_cell(tmp_path: Path, by: str) -> None:
    root = _root(tmp_path)
    ws = AuthoringWorkspace(root=root, registry_url=None)
    first, second = _script(ws, by)

    (by_object,) = ws.add("test", type="cycling", cell=second[0], data="raw/nmc-C01.csv")
    assert by_object.cell is second[0]
    ws.save()
    cells = _saved_cells(root)

    (by_iri,) = ws.add("test", type="eis", cell=cells[("N8", "C01")], data="raw/nmc-C01.csv")
    (other,) = ws.add("test", type="eis", cell=cells[("G1", "C01")], data="raw/g-C01.csv")
    assert by_iri.cell is second[0] and other.cell is first[0]
    ws.save()

    # A later session holds neither cell until it is named by its IRI.
    later = AuthoringWorkspace(root=root, registry_url=None)
    later.add("test", type="capacity_check", cell=cells[("G1", "C01")], data="raw/g-C01.csv")
    later.save()

    bound = {(test["kind"], test["cell_id"]) for test in _records(root, "test", "test")}
    assert bound == {
        ("cycling", cells[("N8", "C01")]),
        ("eis", cells[("N8", "C01")]),
        ("eis", cells[("G1", "C01")]),
        ("capacity_check", cells[("G1", "C01")]),
    }
    assert _saved_cells(root) == cells


def test_a_data_file_named_after_a_label_two_cells_share_is_matched_to_neither(tmp_path: Path, capsys) -> None:
    ws = AuthoringWorkspace(root=_root(tmp_path), registry_url=None)
    _script(ws, "serial_numbers")

    tests = ws.add("test", type="cycling", datasets="raw/C01.csv")

    assert tests == [] and ws._ws.tests == [] and ws._ws.datasets == []
    assert "AMBIGUOUS C01.csv -- 'C01' matches more than one cell" in capsys.readouterr().out
