"""Dataset IRIs do not depend on where the workspace folder sits (evaluation finding C-15).

A dataset's identity seed used to include its access_url, which defaults to the
absolute file:// URI of the data file, so the same workspace built in another
folder minted new dataset IRIs. The seed now takes a location-independent
locator: an explicit remote URL as before, otherwise the data file's path
relative to the workspace root, otherwise its file name.
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


def test_locator_takes_the_relative_path_or_the_file_name(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    inside = root / "bdf" / "run 1" / "C1.bdf.csv"
    outside = tmp_path / "elsewhere" / "C1.bdf.csv"

    assert dataset_locator_seed(dataset_path=inside, workspace_root=root) == "bdf/run 1/C1.bdf.csv"
    assert dataset_locator_seed(access_url=inside.resolve().as_uri(), workspace_root=root) == "bdf/run 1/C1.bdf.csv"
    assert dataset_locator_seed(dataset_path=outside, workspace_root=root) == "C1.bdf.csv"
    assert dataset_locator_seed(access_url=outside.resolve().as_uri()) == "C1.bdf.csv"
    # An explicit remote URL wins over a local path, access_url before download_url.
    assert dataset_locator_seed(access_url=URL, dataset_path=inside, workspace_root=root) == URL
    assert dataset_locator_seed(
        access_url=inside.resolve().as_uri(), download_url="https://example.org/C1.csv",
        dataset_path=inside, workspace_root=root,
    ) == "https://example.org/C1.csv"
    assert dataset_locator_seed() == ""
