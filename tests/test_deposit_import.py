"""ws.import_() reads back the deposit graph the assembler writes today.

The deposit emitter writes a distribution's media type as an IANA media-type
IRI (``{"@id": "https://www.iana.org/assignments/media-types/text/csv"}``)
and a cell's dates as typed literals, gives each dataset its own files under
a catalog, and states a test's kind as ``schema:additionalType``. The
importer expected the older plain strings and one dataset holding every
file, so importing any deposit with a data file raised a pydantic error.
Both shapes now import.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import battinfo
from battinfo.ws import AuthoringWorkspace

RECORD_URL = "https://zenodo.org/records/1"
DATA = "test_time_second,voltage_volt,current_ampere\n0,3.0,0\n60,3.5,0.001\n"


def _saved(root: Path, folder: str) -> list[dict]:
    directory = root / ".battinfo" / "records" / folder
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]


@pytest.fixture()
def source(tmp_path: Path) -> tuple[Path, dict]:
    """A local workspace (cell spec, cell, test spec, test with two data files) and its deposit graph."""
    root = tmp_path / "source"
    root.mkdir()
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.license("cc-by-4.0")
    spec = battinfo.CellSpec(
        manufacturer="Example Lab",
        model="R2032",
        format="coin",
        chemistry="li-ion",
        properties={"nominal_capacity": {"value": 0.005, "unit": "Ah"}},
    )
    ws.add("cell", spec=spec, serial_numbers=["C01", "C02"], production_date="2026-01-15")
    protocol = battinfo.TestSpec(name="Formation cycling", kind="cycling", source_type="manual")
    for serial in ("C01", "C02"):
        (root / f"{serial}.bdf.csv").write_text(DATA, encoding="utf-8")
        ws.add("test", type="cycling", cell=serial, spec=protocol, data=f"{serial}.bdf.csv")
    ws.save()
    graph = ws._build_zenodo_jsonld(
        zenodo_record_id=1,
        prereserved_doi="10.5281/zenodo.1",
        record_url=RECORD_URL,
        data_filenames=["C01.bdf.csv", "C02.bdf.csv"],
        title="Round trip",
        creators=[{"name": "Doe, Jane"}],
    )
    return root, graph


def _import(tmp_path: Path, graph: dict) -> tuple[Path, dict]:
    path = tmp_path / "battinfo.json"
    path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    root = tmp_path / "imported"
    ws = AuthoringWorkspace(root=root, registry_url=None)
    counts = ws.import_(str(path))
    assert ws.save()["index"]["failures"] == []
    return root, counts


def _by_id(records: list[dict], key: str) -> dict[str, dict]:
    return {record[key]["id"]: record[key] for record in records}


def test_a_deposit_written_today_imports_back(tmp_path: Path, source: tuple[Path, dict]) -> None:
    src, graph = source
    dst, counts = _import(tmp_path, graph)

    assert counts == {
        "properties": 1,
        "instances": 2,
        "tests": 2,
        "datasets": 2,
        "skipped": {"tests": [], "datasets": []},
    }

    [src_spec], [dst_spec] = _saved(src, "cell-spec"), _saved(dst, "cell-spec")
    for field in ("id", "model", "cell_format", "chemistry", "manufacturer"):
        assert dst_spec["cell_spec"][field] == src_spec["cell_spec"][field], field
    assert dst_spec["properties"]["nominal_capacity"] == src_spec["properties"]["nominal_capacity"]

    src_cells, dst_cells = (
        _by_id(_saved(src, "cell-instance"), "cell_instance"),
        _by_id(_saved(dst, "cell-instance"), "cell_instance"),
    )
    assert dst_cells.keys() == src_cells.keys()
    for iri, cell in src_cells.items():
        for field in ("cell_spec_id", "serial_number", "manufactured_at"):
            assert dst_cells[iri][field] == cell[field], field

    src_tests, dst_tests = _by_id(_saved(src, "test"), "test"), _by_id(_saved(dst, "test"), "test")
    assert dst_tests.keys() == src_tests.keys()
    for iri, test in src_tests.items():
        for field in ("kind", "protocol_name", "cell_id", "name"):
            assert dst_tests[iri][field] == test[field], field

    src_ds, dst_ds = _by_id(_saved(src, "dataset"), "dataset"), _by_id(_saved(dst, "dataset"), "dataset")
    assert dst_ds.keys() == src_ds.keys()
    for iri, dataset in src_ds.items():
        [source_file] = dataset["distributions"]
        [imported_file] = dst_ds[iri]["distributions"]
        name = source_file["content_url"].rsplit("/", 1)[1]
        # Each dataset gets its own file back, at the deposited URL.
        assert imported_file["content_url"] == f"{RECORD_URL}/files/{name}"
        assert imported_file["encoding_format"] == source_file["encoding_format"] == "text/csv"
        assert imported_file["checksum"] == source_file["checksum"]


def test_a_deposit_in_the_older_string_form_still_imports(tmp_path: Path, source: tuple[Path, dict]) -> None:
    src, graph = source
    older = copy.deepcopy(graph)
    for node in older["@graph"]:
        for dist in node.get("dcat:distribution") or []:
            media = dist.get("dcat:mediaType")
            if isinstance(media, dict):
                dist["dcat:mediaType"] = media["@id"].rsplit("media-types/", 1)[1]
        if isinstance(node.get("schema:productionDate"), dict):
            node["schema:productionDate"] = node["schema:productionDate"]["@value"]
        node.pop("schema:additionalType", None)  # the kind is read from the technique instead
    assert "media-types" not in json.dumps([n.get("dcat:distribution") for n in older["@graph"]])

    dst, counts = _import(tmp_path, older)
    assert (counts["tests"], counts["datasets"]) == (2, 2)
    # Both tests come back, each with its own file, not only the last dataset's.
    assert len(_saved(dst, "test")) == len(_saved(dst, "dataset")) == 2
    assert {d["dataset"]["distributions"][0]["encoding_format"] for d in _saved(dst, "dataset")} == {"text/csv"}
    assert {c["cell_instance"]["manufactured_at"] for c in _saved(dst, "cell-instance")} == {
        c["cell_instance"]["manufactured_at"] for c in _saved(src, "cell-instance")
    }
    assert {t["test"]["kind"] for t in _saved(dst, "test")} == {"cycling"}


@pytest.mark.parametrize(
    "value,expected",
    [
        ({"@id": "https://www.iana.org/assignments/media-types/text/csv"}, "text/csv"),
        (
            "https://www.iana.org/assignments/media-types/application/vnd.apache.parquet",
            "application/vnd.apache.parquet",
        ),
        ("text/csv", "text/csv"),
        ("application/x-parquet", "application/x-parquet"),
        ({"@id": "https://example.org/formats/csv"}, ""),  # not an IANA media type: not guessed
        (None, ""),
    ],
)
def test_media_type_reads_both_shapes(value: object, expected: str) -> None:
    from battinfo.ws import _media_type_from_jsonld

    assert _media_type_from_jsonld(value) == expected
