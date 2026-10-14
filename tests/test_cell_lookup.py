"""A cell label binds the cell it names, never a cell that merely shares its suffix.

``ws.add("test", cell=...)`` looks a cell up in the session, then in the records
saved in the workspace, then in the registry. A serial or name has to match a
cell's serial or name exactly; the six-character short ID is used only when the
label is itself one. When several cells answer to a label the lookup refuses to
pick one and lists them, and when the registry fallback binds a cell it says
whose cell it bound.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402
from battinfo.ws import AuthoringWorkspace  # noqa: E402

SPEC = battinfo.CellSpec(manufacturer="Example Lab", model="R2032", format="coin", chemistry="li-ion")
OTHER_SPEC = battinfo.CellSpec(manufacturer="Example Lab", model="R2025", format="coin", chemistry="li-ion")

CELL_A = "https://w3id.org/battinfo/cell/aaaa-aaaa-aaaa-aaaa"
CELL_B = "https://w3id.org/battinfo/cell/bbbb-bbbb-bbbb-bbbb"
SPEC_IRI = "https://w3id.org/battinfo/spec/avzy-5vjx-5nkj-jgsj"


def _row(iri: str, *, serial: str | None = None, name: str | None = None, batch: str | None = None, publisher="lab-a"):
    """One row of the registry's /resources listing for a cell."""
    metadata = {"cell_spec_id": SPEC_IRI}
    if serial is not None:
        metadata["serial_number"] = serial
    if name is not None:
        metadata["name"] = name
    if batch is not None:
        metadata["batch_id"] = batch
    return {
        "canonical_iri": iri,
        "title": name or serial or "",
        "publisher_id": publisher,
        "metadata": metadata,
    }


def _registry_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rows: list[dict]) -> AuthoringWorkspace:
    ws = AuthoringWorkspace(root=tmp_path, registry_url="https://registry.example")
    monkeypatch.setattr(ws, "_registry_resources", lambda resource_type, q=None: [dict(r) for r in rows])
    # The bound cell is kept as a reference copy; no registry is reachable here.
    monkeypatch.setattr(ws, "_resolve_published_reference", lambda iri, entity_type: "copied")
    return ws


# ── The registry fallback ─────────────────────────────────────────────────────


def test_two_registry_cells_with_one_serial_raise_naming_both(tmp_path, monkeypatch) -> None:
    rows = [_row(CELL_A, serial="C01", publisher="lab-a"), _row(CELL_B, serial="C01", publisher="lab-b")]
    ws = _registry_ws(tmp_path, monkeypatch, rows)
    (tmp_path / "c01.csv").write_text("a,b\n0,1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="matches 2 cells in the registry") as excinfo:
        ws.add("test", type="cycling", cell="C01", data="c01.csv")

    message = str(excinfo.value)
    for expected in (CELL_A, CELL_B, "lab-a", "lab-b", 'cell="https://w3id.org/battinfo/cell/'):
        assert expected in message
    assert ws._ws.tests == [] and ws._ws.datasets == []


def test_a_single_registry_match_prints_a_notice_naming_its_publisher(tmp_path, monkeypatch, capsys) -> None:
    ws = _registry_ws(tmp_path, monkeypatch, [_row(CELL_A, serial="C01", publisher="lab-a")])

    cell = ws._resolve_cell("C01")

    assert cell.id == CELL_A
    out = capsys.readouterr().out
    assert "'C01'" in out and CELL_A in out and "published by lab-a" in out


def test_a_full_serial_does_not_bind_a_registry_cell_sharing_its_suffix(tmp_path, monkeypatch) -> None:
    ws = _registry_ws(tmp_path, monkeypatch, [_row(CELL_A, serial="LAB-2024-000001")])

    with pytest.raises(ValueError, match="Could not resolve cell 'LAB-2025-000001'"):
        ws._resolve_cell("LAB-2025-000001")
    assert ws.search(type="cell", serial="LAB-2025-000001") == []


def test_a_name_does_not_bind_another_name_sharing_its_suffix(tmp_path, monkeypatch) -> None:
    ws = _registry_ws(tmp_path, monkeypatch, [_row(CELL_A, name="LFP-sample")])

    with pytest.raises(ValueError, match="Could not resolve cell 'NMC-sample'"):
        ws._resolve_cell("NMC-sample")
    assert ws.search(type="cell", serial="NMC-sample") == []


def test_a_bare_short_id_still_finds_its_registry_cell(tmp_path, monkeypatch) -> None:
    rows = [_row(CELL_A, serial="duracell-mn2400-2026-02-tpejqj"), _row(CELL_B, serial="X-9")]
    ws = _registry_ws(tmp_path, monkeypatch, rows)

    # A label ending in the short ID, and the short ID of the cell's own IRI.
    assert [hit["id"] for hit in ws.search(type="cell", serial="tpejqj")] == [CELL_A]
    assert ws._resolve_cell("tpejqj").id == CELL_A
    assert ws._resolve_cell("bbbbbb").id == CELL_B


def test_an_exact_registry_match_wins_over_a_short_id_match(tmp_path, monkeypatch) -> None:
    rows = [_row(CELL_A, serial="LAB-2024-000001"), _row(CELL_B, serial="000001")]
    ws = _registry_ws(tmp_path, monkeypatch, rows)

    assert [hit["id"] for hit in ws.search(type="cell", serial="000001")] == [CELL_B]
    assert ws._resolve_cell("000001").id == CELL_B


def test_serial_and_batch_narrow_a_registry_search_together(tmp_path, monkeypatch, capsys) -> None:
    rows = [
        _row(CELL_A, serial="S1", batch="b1", publisher="lab-a"),
        _row(CELL_B, serial="S1", batch="b2", publisher="lab-b"),
    ]
    ws = _registry_ws(tmp_path, monkeypatch, rows)

    found = ws.search(type="cell", serial="S1", batch="b1")

    assert [hit["id"] for hit in found] == [CELL_A]
    assert found[0]["publisher_id"] == "lab-a"
    assert "published by lab-a" in capsys.readouterr().out
    assert [hit["id"] for hit in ws.search(type="cell", batch="b2")] == [CELL_B]


# ── The session and the records saved in the workspace ────────────────────────


def test_a_full_serial_does_not_bind_a_session_cell_sharing_its_suffix(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.add("cell", spec=SPEC, serial_numbers=["LAB-2024-000001"])
    (tmp_path / "run.csv").write_text("a,b\n0,1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Could not resolve cell 'LAB-2025-000001'"):
        ws.add("test", type="cycling", cell="LAB-2025-000001", data="run.csv")
    assert ws._ws.tests == []


def test_a_short_id_shared_by_two_session_cells_raises_listing_both(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.add("cell", spec=SPEC, serial_numbers=["LAB-2024-000001", "LAB-2025-000001"])

    with pytest.raises(ValueError, match="more than one cell") as excinfo:
        ws._resolve_cell("000001")
    assert "LAB-2024-000001" in str(excinfo.value) and "LAB-2025-000001" in str(excinfo.value)
    # Each full serial still names its own cell.
    assert ws._resolve_cell("LAB-2025-000001").serial_number == "LAB-2025-000001"


def test_a_shared_name_raises_listing_every_cell_it_names(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.add("cell", spec=SPEC, names=["A", "A"], serial_numbers=["x1", "x2"])

    with pytest.raises(ValueError, match="more than one cell") as excinfo:
        ws._resolve_cell("A")
    assert "x1" in str(excinfo.value) and "x2" in str(excinfo.value)


def test_an_exact_session_match_wins_over_a_short_id_match(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.add("cell", spec=SPEC, serial_numbers=["LAB-2024-000001", "000001"])

    assert ws._resolve_cell("000001").serial_number == "000001"


def test_a_saved_cell_resolves_by_the_short_id_of_its_iri(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    (cell,) = ws.add("cell", spec=SPEC, serial_numbers=["INR-9F3K72"])
    ws.save()
    short_id = cell.id.rsplit("/", 1)[-1].replace("-", "")[:6]

    assert ws._resolve_cell(short_id) is cell
    fresh = AuthoringWorkspace(root=tmp_path, registry_url=None)
    assert fresh._resolve_cell(short_id).id == cell.id


def test_reading_the_saved_cells_back_does_not_make_a_serial_ambiguous(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    (cell,) = ws.add("cell", spec=SPEC, serial_numbers=["S1"])
    ws.save()

    # An unknown label reads the saved cells back before giving up ...
    with pytest.raises(ValueError, match="Could not resolve cell 'S2'"):
        ws._resolve_cell("S2")
    # ... and the session's own S1 is still the one cell S1 names.
    assert ws._resolve_cell("S1") is cell


def test_a_cell_whose_serial_is_another_cells_suffix_can_be_added(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.add("cell", spec=SPEC, serial_numbers=["LAB-2024-000001"])

    added = ws.add("cell", spec=SPEC, serial_numbers=["000001"])

    assert [cell.serial_number for cell in added] == ["000001"]
    assert sorted(cell.serial_number for cell in ws._ws.cells) == ["000001", "LAB-2024-000001"]


def test_a_data_file_named_after_a_serial_matches_that_cell_before_its_short_id(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.add("cell", spec=SPEC, serial_numbers=["LAB-2024-000001", "LAB-2025-000001"])
    (tmp_path / "LAB-2024-000001.csv").write_text("a,b\n0,1\n", encoding="utf-8")

    tests = ws.add("test", type="cycling", datasets="LAB-2024-*.csv")

    assert len(tests) == 1
    assert tests[0].cell.serial_number == "LAB-2024-000001"


def _data(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("a,b\n0,1\n", encoding="utf-8")


def test_a_data_file_named_after_its_cells_short_id_matches_that_cell(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    (cell,) = ws.add("cell", spec=OTHER_SPEC, serial_numbers=["duracell-mn2400-2026-02-tpejqj"])
    ws.save()
    short_id = cell.id.rsplit("/", 1)[-1].replace("-", "")[:6]
    _data(tmp_path / "data" / f"cycling-{short_id}.csv")
    _data(tmp_path / "data" / f"{short_id}.bdf.csv")

    tests = ws.add("test", type="cycling", datasets="data/*.csv")

    assert len(tests) == 2 and all(test.cell is cell for test in tests)


def test_a_short_id_a_label_ends_in_counts_only_for_a_file_named_by_it_alone(tmp_path: Path) -> None:
    """A file name that ends in six characters a serial ends in does not name that cell; the short ID alone does."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    (cell,) = ws.add("cell", spec=OTHER_SPEC, serial_numbers=["duracell-mn2400-2026-02-tpejqj"])
    _data(tmp_path / "data" / "tpejqj.csv")
    _data(tmp_path / "data" / "cycling-tpejqj.csv")

    tests = ws.add("test", type="cycling", datasets="data/*.csv")

    assert len(tests) == 1 and tests[0].cell is cell
    assert [Path(d.dataset_path).name for d in ws._ws.datasets] == ["tpejqj.csv"]


def test_a_converted_file_named_after_a_serial_binds_only_that_serial(tmp_path: Path, capsys) -> None:
    """``ws.convert()`` writes ``<serial>.bdf.csv``; the serial in it is matched whole, never by its last six characters."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.add("cell", spec=SPEC, serial_numbers=["LAB-2025-000001", "LAB-2025-000002"])
    _data(tmp_path / "bdf" / "LAB-2024-000001.bdf.csv")
    _data(tmp_path / "bdf" / "LAB-2025-000002.csv")

    tests = ws.add("test", type="cycling", datasets="bdf/*.csv")

    assert [test.cell.serial_number for test in tests] == ["LAB-2025-000002"]
    out = capsys.readouterr().out
    assert "NO MATCH  LAB-2024-000001.bdf.csv" in out
    # The hint searches for the serial the file is named after, not the name with .bdf.
    assert "serials=['LAB-2024-000001']" in out


def test_converted_files_of_cells_whose_serials_share_a_tail_each_bind_their_own_cell(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    serials = ["LAB-2024-000001", "LAB-2025-000001", "MYLAB-50E-001"]
    ws.add("cell", spec=SPEC, serial_numbers=serials)
    for serial in serials:
        _data(tmp_path / "bdf" / f"{serial}.bdf.csv")

    tests = ws.add("test", type="cycling", datasets="bdf/*.bdf.csv")

    assert sorted(test.cell.serial_number for test in tests) == sorted(serials)
    for test in tests:
        (dataset,) = [d for d in ws._ws.datasets if d.test is test]
        assert Path(dataset.dataset_path).name == f"{test.cell.serial_number}.bdf.csv"


@pytest.mark.parametrize(
    ("name", "stems"),
    [
        ("C01.csv", ["C01.csv", "C01"]),
        ("LAB-2024-000001.bdf.csv", ["LAB-2024-000001.bdf.csv", "LAB-2024-000001.bdf", "LAB-2024-000001"]),
        ("C01.cycler-export", ["C01.cycler-export", "C01"]),
        ("S1.6.csv", ["S1.6.csv", "S1.6"]),
        ("S1.5.bdf.csv", ["S1.5.bdf.csv", "S1.5.bdf", "S1.5"]),
        ("S1.6", ["S1.6"]),
        ("C01.cycle1.csv", ["C01.cycle1.csv", "C01.cycle1"]),
    ],
)
def test_a_data_file_name_loses_only_its_extension_and_data_format_suffixes(name: str, stems: list[str]) -> None:
    from battinfo.ws import _data_file_stems

    assert _data_file_stems(name) == stems


def test_a_data_file_for_a_dotted_serial_never_binds_the_serial_it_starts_with(tmp_path: Path, capsys) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.add("cell", spec=SPEC, serial_numbers=["S1.5", "S1"])
    for name in ("S1.5.bdf.csv", "S1.6.csv", "S1.bdf.csv"):
        _data(tmp_path / "bdf" / name)

    tests = ws.add("test", type="cycling", datasets="bdf/*.csv")

    bound = {Path(d.dataset_path).name: d.test.cell.serial_number for d in ws._ws.datasets}
    assert len(tests) == 2 and bound == {"S1.5.bdf.csv": "S1.5", "S1.bdf.csv": "S1"}
    out = capsys.readouterr().out
    assert "NO MATCH  S1.6.csv" in out
    assert "serials=['S1.6']" in out


def test_reading_the_saved_cells_back_leaves_an_unsaved_session_cell_unambiguous(tmp_path: Path) -> None:
    """A fresh session adds the cells a saved one holds; a failed lookup reads the saved cells back."""
    first = AuthoringWorkspace(root=tmp_path, registry_url=None)
    first.add("cell", spec=SPEC, serial_numbers=["C01", "C02"])
    first.save()

    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    (c01, _) = ws.add("cell", spec=SPEC, serial_numbers=["C01", "C02"])
    with pytest.raises(ValueError, match="Could not resolve cell 'C03'"):
        ws._resolve_cell("C03")

    assert ws._resolve_cell("C01") is c01


def _rated_spec(rated: float, chemistry: str = "li-ion") -> battinfo.CellSpec:
    return battinfo.CellSpec(
        manufacturer="Example Lab",
        model="R2032",
        format="coin",
        chemistry=chemistry,
        properties={"rated_capacity": {"value": rated, "unit": "mAh"}},
    )


def test_reading_saved_cells_back_leaves_cells_of_colliding_specs_unambiguous(tmp_path: Path) -> None:
    """Two specs share a natural key, so a save mints both from their content; their cells are predicted the same way."""
    first = AuthoringWorkspace(root=tmp_path, registry_url=None)
    first.add("cell", spec=_rated_spec(2.0), serial_numbers=["C01"])
    first.add("cell", spec=_rated_spec(3.0), serial_numbers=["C02"])
    first.save()
    saved = {cell.serial_number: cell.id for cell in first._ws.cells}

    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    (c01,) = ws.add("cell", spec=_rated_spec(2.0), serial_numbers=["C01"])
    ws.add("cell", spec=_rated_spec(3.0), serial_numbers=["C02"])
    with pytest.raises(ValueError, match="Could not resolve cell 'C99'"):
        ws.add("test", type="cycling", cell="C99")

    (test,) = ws.add("test", type="cycling", cell="C01")
    assert test.cell is c01
    ws.save()
    assert c01.id == saved["C01"]


def test_reading_saved_cells_back_leaves_a_cell_whose_spec_keeps_an_earlier_iri_unambiguous(tmp_path: Path) -> None:
    """The spec was saved on its own before 0.8.0; with a sibling of the same natural key it keeps that IRI."""
    spec_iri = "https://w3id.org/battinfo/spec/8tdq-hs3n-kqf4-bmhb"  # what 057b66a0 minted for it
    first = AuthoringWorkspace(root=tmp_path, registry_url=None)
    first.add("cell", spec=_rated_spec(2.0, "Li-ion"), serial_numbers=["C01"])
    first._ws.cell_specs[0].id = spec_iri
    first.save()
    (saved_cell,) = first._ws.cells

    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    (c01,) = ws.add("cell", spec=_rated_spec(2.0, "Li-ion"), serial_numbers=["C01"])
    ws.add("cell", spec=_rated_spec(3.0, "Li-ion"), serial_numbers=["C02"])
    with pytest.raises(ValueError, match="Could not resolve cell 'C99'"):
        ws._resolve_cell("C99")

    assert ws._resolve_cell("C01") is c01
    ws.save()
    assert c01.id == saved_cell.id
