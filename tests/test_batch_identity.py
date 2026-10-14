"""Cell identity on the folder-based batch path (``battinfo batch init`` / ``add``).

A cell with a serial number gets the IRI every other path gives it: the shared
cell seed (``entities.cell_instance_identity_seed``). A cell without one gets a
random IRI, recorded in its ``battinfo.yaml``; its place in the batch never
enters an IRI. A re-init with ``--force`` keeps every IRI a cell folder already
records.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402
import yaml  # noqa: E402

import battinfo  # noqa: E402
from battinfo import api  # noqa: E402
from battinfo.bundle import CellSpec  # noqa: E402
from battinfo.contribution import CONTRIBUTION_MANIFEST, add_to_batch, init_batch, package_batch  # noqa: E402
from battinfo.entities import stable_uid  # noqa: E402

CELL_SPEC_IRI = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"
OTHER_SPEC_IRI = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-eeee"
SPEC_FIELDS = {"manufacturer": "Energizer", "model": "CR2032", "format": "coin", "chemistry": "li-metal"}
CREATORS = [{"name": "Clark, Simon", "affiliation": "SINTEF"}]


@pytest.fixture(autouse=True)
def _specs_in_the_local_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The batch path reads its cell spec from a library, so both specs go in ``./.battinfo/library/cell-spec``."""
    library = tmp_path / ".battinfo" / "library" / "cell-spec"
    library.mkdir(parents=True)
    for n, iri in enumerate((CELL_SPEC_IRI, OTHER_SPEC_IRI)):
        record = {"specification": {"id": iri, **SPEC_FIELDS}}
        (library / f"spec-{n}.json").write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.chdir(tmp_path)


def _iris(result: dict) -> list[str]:
    cells = result.get("cells") or result.get("new_cells") or []
    return [cell["cell_iri"] for cell in cells]


def _recorded(batch_dir: Path) -> dict[str, str]:
    """Folder name -> the cell IRI its battinfo.yaml records."""
    out: dict[str, str] = {}
    for manifest in sorted(batch_dir.glob(f"*/{CONTRIBUTION_MANIFEST}")):
        out[manifest.parent.name] = yaml.safe_load(manifest.read_text(encoding="utf-8"))["cell_iri"]
    return out


@pytest.mark.parametrize("batch_id", [None, "B7"])
def test_a_cell_with_a_serial_gets_the_iri_every_other_path_gives_it(tmp_path: Path, batch_id: str | None) -> None:
    (batch_iri,) = _iris(init_batch(tmp_path / "batch", CELL_SPEC_IRI, 1, batch_id=batch_id, serial_numbers=["S1"]))
    fields = {"cell_spec_id": CELL_SPEC_IRI, "serial_number": "S1", **({"batch_id": batch_id} if batch_id else {})}
    saved = api.save_cell_instance(dict(fields), source_root=tmp_path / "save", resolve_references=False)["id"]
    assert batch_iri == saved
    if batch_id is None:  # ws.add("cell") takes serial numbers, not a batch
        ws = battinfo.workspace(tmp_path / "ws", registry_url=None)
        (cell,) = ws.add("cell", spec=CellSpec(id=CELL_SPEC_IRI, **SPEC_FIELDS), serial_numbers=["S1"])
        ws._ws.render()
        assert batch_iri == str(cell.id)


def test_a_serial_with_repeated_whitespace_is_the_same_cell(tmp_path: Path) -> None:
    first = _iris(init_batch(tmp_path / "a", CELL_SPEC_IRI, 1, serial_numbers=["MYLAB 001"]))
    second = _iris(init_batch(tmp_path / "b", CELL_SPEC_IRI, 1, serial_numbers=["MYLAB  001"]))
    assert first == second


def test_a_cell_without_a_serial_gets_a_random_iri_never_one_from_its_place(tmp_path: Path) -> None:
    first = _iris(init_batch(tmp_path / "a", CELL_SPEC_IRI, 2))
    second = _iris(init_batch(tmp_path / "b", CELL_SPEC_IRI, 2))
    assert len(set(first + second)) == 4
    # The seed the batch path used to give the first two cells of a batch.
    from_index = {f"https://w3id.org/battinfo/cell/{stable_uid(f'{CELL_SPEC_IRI}::batch::{i}')}" for i in (0, 1)}
    assert not from_index & set(first + second)


def test_a_cell_without_a_serial_records_its_iri_in_its_manifest(tmp_path: Path) -> None:
    result = init_batch(tmp_path / "batch", CELL_SPEC_IRI, 2, batch_id="B7")
    assert _recorded(tmp_path / "batch") == {cell["folder"]: cell["cell_iri"] for cell in result["cells"]}


def test_adding_cells_without_a_serial_never_derives_their_iri_from_the_count(tmp_path: Path) -> None:
    for name in ("a", "b"):
        init_batch(tmp_path / name, CELL_SPEC_IRI, 1)
    added = _iris(add_to_batch(tmp_path / "a", 1)) + _iris(add_to_batch(tmp_path / "b", 1))
    assert len(set(added)) == 2


def test_a_forced_re_init_keeps_the_iris_its_cells_record(tmp_path: Path) -> None:
    batch = tmp_path / "batch"
    first = init_batch(batch, CELL_SPEC_IRI, 2)
    recorded = _recorded(batch)

    again = init_batch(batch, CELL_SPEC_IRI, 2, overwrite=True)

    assert sorted(_iris(again)) == sorted(_iris(first))
    assert _recorded(batch) == recorded  # no new cell folders, no IRI rewritten


def test_a_forced_re_init_keeps_an_iri_recorded_before_0_8_0(tmp_path: Path) -> None:
    """A serial cell's folder may record the IRI the earlier batch seed gave it."""
    batch = tmp_path / "batch"
    init_batch(batch, CELL_SPEC_IRI, 1, serial_numbers=["S1"])
    manifest = batch / "s1" / CONTRIBUTION_MANIFEST
    old_iri = f"https://w3id.org/battinfo/cell/{stable_uid(f'{CELL_SPEC_IRI}::batch::S1')}"
    text = manifest.read_text(encoding="utf-8")
    recorded_now = yaml.safe_load(text)["cell_iri"]
    manifest.write_text(text.replace(recorded_now, old_iri), encoding="utf-8")

    again = init_batch(batch, CELL_SPEC_IRI, 1, serial_numbers=["S1"], overwrite=True)

    assert _iris(again) == [old_iri]
    assert _recorded(batch) == {"s1": old_iri}


def test_a_forced_re_init_with_another_spec_mints_its_own_iris(tmp_path: Path) -> None:
    batch = tmp_path / "batch"
    first = init_batch(batch, CELL_SPEC_IRI, 1, serial_numbers=["S1"])
    again = init_batch(batch, OTHER_SPEC_IRI, 1, serial_numbers=["S1"], overwrite=True)
    assert _iris(again) != _iris(first)


def test_the_batch_package_keeps_the_iri_a_cell_records(tmp_path: Path) -> None:
    batch = tmp_path / "batch"
    result = init_batch(batch, CELL_SPEC_IRI, 1)
    (cell,) = result["cells"]
    data = batch / cell["folder"] / "data" / "cycling.csv"
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text("time_s,voltage_V\n0,3.0\n", encoding="utf-8")
    package = package_batch(batch, creators=CREATORS)
    entry = json.loads(Path(package["bundle_path"]).read_text(encoding="utf-8"))["datasets"][0]
    assert entry["cell_instances"][0]["cell_instance"]["id"] == cell["cell_iri"]
