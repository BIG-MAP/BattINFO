"""Dataset IRIs do not depend on where the workspace folder sits (evaluation finding C-15).

A dataset's identity seed used to include its access_url, which defaults to the
absolute file:// URI of the data file, so the same workspace built in another
folder minted new dataset IRIs. The seed now takes a location-independent
locator: an explicit remote URL as before, otherwise the data file's path
relative to the workspace root, otherwise its folder and file name. The older
publication-package path (publish_publication_package and
Workspace.build_publication_package) seeded on the dataset folder's absolute
URI the same way and now follows the same rule.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import battinfo
from battinfo._workspace import Workspace
from battinfo.entities import dataset_locator_seed, stable_uid

URL = "https://www.sintef.no/en/sintef-industry/"
SPEC = dict(manufacturer="Example Lab", model="R03 test cell", format="cylindrical", chemistry="zn-mno2")
CSV = "test_time_second,voltage_volt\n0,1.6\n3600,0.9\n"


def _build(root: Path) -> dict[str, list[str]]:
    """The reproduction from the evaluation (p2_08_identity.py): one cell, one test, one data file."""
    if (root / ".battinfo").exists():
        shutil.rmtree(root / ".battinfo")
    (root / "bdf").mkdir(parents=True, exist_ok=True)
    (root / "bdf" / "C1.bdf.csv").write_text(CSV, encoding="utf-8")
    ws = battinfo.workspace(root, registry_url=None)
    ws.add("cell", spec=battinfo.CellSpec(**SPEC), names=["C1"])
    ws.add("test", type="capacity_check", cell="C1", data="bdf/C1.bdf.csv")
    out = ws.save()
    return {
        "cell": [r["id"] for r in out.get("cell_instances", [])],
        "test": [r["id"] for r in out.get("tests", [])],
        "dataset": [r["id"] for r in out.get("datasets", [])],
    }


def test_same_workspace_in_two_folders_gives_identical_dataset_iris(tmp_path: Path) -> None:
    built_in_x = _build(tmp_path / "X")
    built_in_y = _build(tmp_path / "somewhere" / "else" / "Y")
    assert len(built_in_x["dataset"]) == 1
    assert built_in_x == built_in_y


def test_local_access_url_stays_on_the_record(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    ids = _build(root)
    uid = ids["dataset"][0].rsplit("/", 1)[1]
    path = root / ".battinfo" / "records" / "dataset" / f"dataset-{uid}.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    # The deposit preview reads the local file from access_url, so it is kept as it was.
    assert record["dataset"]["access_url"] == (root / "bdf" / "C1.bdf.csv").resolve().as_uri()


def test_https_access_url_seeds_as_before(tmp_path: Path) -> None:
    """An explicit https access URL is still the locator: the IRI equals the earlier seed."""
    cell = "https://w3id.org/battinfo/cell/2435-kc9w-g9q0-1xsm"
    test = "https://w3id.org/battinfo/test/y4gj-dvk5-e8x4-3y3t"
    name = "C1 data"
    expected = f"https://w3id.org/battinfo/dataset/{stable_uid('::'.join([cell, test, URL, name]))}"

    saved = battinfo.save_dataset(
        battinfo.Dataset(name=name, cell_instance_id=cell, test_id=test, access_url=URL,
                         license="cc-by-4.0", source={"type": "measurement"}),
        source_root=tmp_path / "ws" / ".battinfo" / "records", mode="upsert",
        resolve_references=False, build_jsonld=False, build_html=False,
    )
    assert saved["id"] == expected

    # The workspace engine mints the same IRI for the same fields.
    engine = Workspace(root=tmp_path / "engine")
    dataset = battinfo.Dataset(name=name, cell_instance_id=cell, test_id=test, access_url=URL)
    finalized = engine._finalize_dataset(dataset, {}, {})
    assert finalized.id == expected


def test_collection_iri_from_https_access_url_is_unchanged(tmp_path: Path) -> None:
    """A collection has no cell or test, so its IRI comes from the access URL and name alone."""
    name = "Graphite half-cell pOCV collection"
    expected = f"https://w3id.org/battinfo/dataset/{stable_uid('::'.join(['unknown-cell', '', URL, name]))}"
    saved = battinfo.save_dataset(
        battinfo.Dataset(name=name, additional_type=["DatasetSeries"], access_url=URL,
                         license="cc-by-4.0", source={"type": "measurement"}),
        source_root=tmp_path / "records", mode="upsert",
        validation_policy="strict", build_jsonld=False, build_html=False,
    )
    assert saved["id"] == expected


def test_save_dataset_into_a_workspace_agrees_with_the_workspace(tmp_path: Path) -> None:
    """save_dataset into a workspace's records folder seeds a local file the same way ws.add does."""
    root = tmp_path / "ws"
    ids = _build(root)
    data_uri = (root / "bdf" / "C1.bdf.csv").resolve().as_uri()
    saved = battinfo.save_dataset(
        battinfo.Dataset(name="C1 data", cell_instance_id=ids["cell"][0], test_id=ids["test"][0],
                         access_url=data_uri, source={"type": "measurement"}),
        source_root=root / ".battinfo" / "records", mode="upsert",
        resolve_references=False, build_jsonld=False, build_html=False,
    )
    assert saved["id"] == ids["dataset"][0]


def test_locator_takes_the_relative_path_or_the_folder_and_name(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    inside = root / "bdf" / "run 1" / "C1.bdf.csv"
    outside = tmp_path / "elsewhere" / "C1.bdf.csv"

    assert dataset_locator_seed(dataset_path=inside, workspace_root=root) == "bdf/run 1/C1.bdf.csv"
    assert dataset_locator_seed(access_url=inside.resolve().as_uri(), workspace_root=root) == "bdf/run 1/C1.bdf.csv"
    assert dataset_locator_seed(dataset_path=outside, workspace_root=root) == "elsewhere/C1.bdf.csv"
    assert dataset_locator_seed(access_url=outside.resolve().as_uri()) == "elsewhere/C1.bdf.csv"
    assert dataset_locator_seed(dataset_path="C1.bdf.csv") == "C1.bdf.csv"
    assert dataset_locator_seed(dataset_path=r"C:\ext\run1\data.csv") == "run1/data.csv"
    assert dataset_locator_seed(dataset_path="/ext/run1/data.csv") == "run1/data.csv"
    # An explicit remote URL wins over a local path, access_url before download_url.
    assert dataset_locator_seed(access_url=URL, dataset_path=inside, workspace_root=root) == URL
    assert dataset_locator_seed(
        access_url=inside.resolve().as_uri(), download_url="https://example.org/C1.csv",
        dataset_path=inside, workspace_root=root,
    ) == "https://example.org/C1.csv"
    assert dataset_locator_seed() == ""


# ── The publication-package path ──────────────────────────────────────────────


def _publish_package(parent: Path, **dataset_fields: str) -> dict:
    """publish_publication_package for one cell, one test and one dataset folder under *parent*."""
    folder = parent / "run-1"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "C1.bdf.csv").write_text(CSV, encoding="utf-8")
    cell_spec = battinfo.CellSpec(**SPEC)
    cell = battinfo.Cell(cell_spec=cell_spec, serial_number="C1")
    test = battinfo.Test(cell=cell, kind="capacity_check", protocol="C/5 discharge", status="completed")
    dataset = battinfo.Dataset(path=str(folder), cell=cell, test=test, **dataset_fields)
    return battinfo.publish_publication_package(cell_spec=cell_spec, cell_instance=cell, test=test, dataset=dataset)


def test_publication_package_dataset_iri_does_not_depend_on_the_folder(tmp_path: Path) -> None:
    """The same project folder, here and somewhere else: the dataset folder is named by
    its own name and its parent's (project/run-1), never by the absolute path."""
    here = _publish_package(tmp_path / "X" / "project")
    there = _publish_package(tmp_path / "somewhere" / "else" / "project")
    assert here["dataset_id"] == there["dataset_id"]
    assert (here["cell_instance_id"], here["test_id"]) == (there["cell_instance_id"], there["test_id"])


def test_publication_package_agrees_with_save_dataset_on_a_remote_url(tmp_path: Path) -> None:
    """With a remote access URL the package mints the IRI save_dataset mints for the same fields."""
    published = _publish_package(tmp_path / "package", name="C1 data", access_url=URL)
    saved = battinfo.save_dataset(
        battinfo.Dataset(name="C1 data", cell_instance_id=published["cell_instance_id"],
                         test_id=published["test_id"], access_url=URL, license="cc-by-4.0",
                         source={"type": "measurement"}),
        source_root=tmp_path / "records", mode="upsert",
        resolve_references=False, build_jsonld=False, build_html=False,
    )
    assert published["dataset_id"] == saved["id"]


def test_workspace_publication_package_dataset_iri_does_not_depend_on_the_folder(tmp_path: Path) -> None:
    def build(root: Path) -> str:
        engine = Workspace(root=root)
        data = root / "inputs" / "C1.bdf.csv"
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_text(CSV, encoding="utf-8")
        spec = engine.cell_spec(**SPEC)
        cell = engine.cell(spec, serial_number="C1")
        test = engine.test(cell, kind="capacity_check", protocol="C/5 discharge", status="completed")
        dataset = engine.dataset(cell, title="C1 data", test=test, path=data, license="CC-BY-4.0")
        return engine.build_publication_package(dataset)["dataset_id"]

    assert build(tmp_path / "X") == build(tmp_path / "somewhere" / "else" / "Y")


# ── Files outside the workspace, relative paths, and colliding records ────────


def _save_outside(tmp_path: Path, folder: str) -> dict:
    data = tmp_path / "ext" / folder / "data.csv"
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text(CSV, encoding="utf-8")
    return battinfo.save_dataset(
        battinfo.Dataset(name="data", path=str(data), access_url=data.resolve().as_uri(), cell_instance_id="https://w3id.org/battinfo/cell/2435-kc9w-g9q0-1xsm",
                         test_id="https://w3id.org/battinfo/test/y4gj-dvk5-e8x4-3y3t", license="cc-by-4.0",
                         source={"type": "measurement"}),
        source_root=tmp_path / "records", resolve_references=False, build_jsonld=False, build_html=False,
    )


def test_one_file_name_in_two_outside_folders_mints_two_iris(tmp_path: Path) -> None:
    """/ext/run1/data.csv and /ext/run2/data.csv with one title: two datasets, not one."""
    first = _save_outside(tmp_path, "run1")
    second = _save_outside(tmp_path, "run2")
    assert first["status"] == second["status"] == "created"
    assert first["id"] != second["id"]


def test_relative_paths_are_read_against_the_workspace_root(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "ws"
    (root / "notebooks").mkdir(parents=True)
    for cwd in (root, root / "notebooks", tmp_path):
        monkeypatch.chdir(cwd)
        assert dataset_locator_seed(dataset_path="data/C01.csv", workspace_root=root) == "data/C01.csv"
        assert dataset_locator_seed(dataset_path=Path("data") / "C01.csv", workspace_root=root) == "data/C01.csv"


def test_save_dataset_with_a_relative_path_mints_one_iri_from_any_directory(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "ws"
    (root / "notebooks").mkdir(parents=True)
    ids = []
    for cwd in (root, root / "notebooks"):
        monkeypatch.chdir(cwd)
        saved = battinfo.save_dataset(
            # access_url as a naive caller derives it, from the current directory; the
            # IRI must not follow it.
            battinfo.Dataset(name="C01 data", path="data/C01.csv", license="cc-by-4.0",
                             access_url=Path("data/C01.csv").resolve().as_uri(),
                             cell_instance_id="https://w3id.org/battinfo/cell/2435-kc9w-g9q0-1xsm",
                             source={"type": "measurement"}),
            source_root=root / ".battinfo" / "records", mode="upsert", validate=False,
            resolve_references=False, build_jsonld=False, build_html=False,
        )
        ids.append(saved["id"])
    assert ids[0] == ids[1]


def test_colliding_datasets_are_re_minted_the_same_in_any_folder(tmp_path: Path) -> None:
    """Two datasets on one file and title collide; the content-seeded re-mint that keeps
    them apart names the file by its locator, so it does not move with the folder."""
    def build(root: Path) -> list[str]:
        engine = Workspace(root=root)
        data = root / "bdf" / "C1.bdf.csv"
        data.parent.mkdir(parents=True, exist_ok=True)
        data.write_text(CSV, encoding="utf-8")
        spec = engine.cell_spec(**SPEC)
        cell = engine.cell(spec, serial_number="C1")
        test = engine.test(cell, kind="capacity_check", protocol="C/5 discharge", status="completed")
        for description in ("first pass", "second pass"):
            engine.dataset(cell, title="C1 data", test=test, path=data, description=description)
        return [dataset.id for dataset in engine._finalize()["datasets"]]

    here = build(tmp_path / "X")
    assert len(set(here)) == 2
    assert here == build(tmp_path / "somewhere" / "else" / "Y")
