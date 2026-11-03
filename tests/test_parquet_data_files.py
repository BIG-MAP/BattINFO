"""Parquet data files in a workspace and its deposit.

The measured period is read from a parquet file's footer, parquet files carry
the media type IANA registered (``application/vnd.apache.parquet``) wherever a
graph names one, a saved record that holds the deprecated alias is written out
with the registered type, and the deposit names the BDF table schema of the
version the caller gives (``bdf_version=``), else the unversioned one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

import battinfo  # noqa: E402
from battinfo import CellSpec  # noqa: E402
from battinfo._util import PARQUET_MEDIA_TYPE, file_media_type, registered_media_type  # noqa: E402
from battinfo.ws import (  # noqa: E402
    BDF_TABLE_SCHEMA_IRI,
    AuthoringWorkspace,
    _bdf_measurement_period,
    _guess_format,
)

SPEC = {"manufacturer": "Example Lab", "model": "R2032 half cell", "format": "coin", "chemistry": "li-ion"}
IANA = "https://www.iana.org/assignments/media-types/"
BDF_1_3_0 = "https://w3id.org/battery-data-alliance/ontology/battery-data-format/1.3.0/schema"
T0 = 1700000000


@pytest.fixture(autouse=True)
def _no_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("BATTINFO_API_KEY", "BATTINFO_REGISTRY_URL", "ZENODO_API_TOKEN", "ZENODO_SANDBOX_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def _parquet(
    path: Path,
    times: list[float] | None,
    *,
    row_group_size: int = 2,
    write_statistics: bool = True,
) -> Path:
    """A BDF-like parquet file; *times* is its ``unix_time_second`` column, or ``None`` for no such column."""
    rows = len(times) if times is not None else 4
    columns: dict[str, list[float]] = {
        "test_time_second": [float(10 * i) for i in range(rows)],
        "voltage_volt": [3.0 + 0.01 * i for i in range(rows)],
    }
    if times is not None:
        columns["unix_time_second"] = times
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(columns), path, row_group_size=row_group_size, write_statistics=write_statistics)
    return path


def _workspace(root: Path, files: dict[str, list[float] | None]) -> AuthoringWorkspace:
    """A workspace with one cell and one test per parquet file in *files* (name -> times)."""
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    for name, times in files.items():
        _parquet(root / "data" / name, times)
        ws.add("test", type="cycling", cell="C01", data=f"data/{name}")
    return ws


def _dataset_records(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    folder = root / ".battinfo" / "records" / "dataset"
    return [(path, json.loads(path.read_text(encoding="utf-8"))) for path in sorted(folder.glob("*.json"))]


# ── The measured period ──────────────────────────────────────────────────────


def test_period_is_the_span_the_footer_records(tmp_path: Path) -> None:
    # Two row groups, out of order within them: the span is the smallest and
    # the largest value over all of them, read from the footer.
    path = _parquet(tmp_path / "a.bdf.parquet", [T0 + 10, T0, T0 + 30, T0 + 20])
    assert pq.ParquetFile(path).metadata.num_row_groups == 2
    assert _bdf_measurement_period(path) == (T0, T0 + 30)


def test_period_without_statistics_reads_the_first_and_last_row_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _parquet(
        tmp_path / "a.bdf.parquet", [T0, T0 + 10, T0 + 20, T0 + 30, T0 + 40, T0 + 50], write_statistics=False
    )
    read: list[int] = []
    original = pq.ParquetFile.read_row_group

    def spy(self: Any, i: int, *args: Any, **kwargs: Any) -> Any:
        read.append(i)
        return original(self, i, *args, **kwargs)

    monkeypatch.setattr(pq.ParquetFile, "read_row_group", spy)
    assert _bdf_measurement_period(path) == (T0, T0 + 50)
    assert read == [0, 2]  # never the middle row group


def test_period_of_a_file_without_the_column_is_none(tmp_path: Path) -> None:
    assert _bdf_measurement_period(_parquet(tmp_path / "a.bdf.parquet", None)) is None


def test_period_with_an_implausible_end_is_withheld(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _parquet(tmp_path / "a.bdf.parquet", [T0, T0 + 10, T0 + 20, 9_000_000_000.0])
    assert _bdf_measurement_period(path) is None
    assert "implausible" in capsys.readouterr().out


def test_period_of_a_parquet_file_without_pyarrow_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _parquet(tmp_path / "a.bdf.parquet", [T0, T0 + 10])
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", None)
    with pytest.warns(UserWarning, match=r"battinfo\[tabular\]"):
        assert _bdf_measurement_period(path) is None


def test_a_parquet_test_takes_its_period_and_media_type(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, {"a.bdf.parquet": [T0, T0 + 10, T0 + 20, T0 + 30]})
    (test,) = ws._ws.tests
    (dataset,) = ws._ws.datasets
    assert (test.started_at, test.ended_at) == (T0, T0 + 30)
    assert dataset.temporal_coverage == "2023-11-14T22:13:20Z/2023-11-14T22:13:50Z"
    ws.save()
    ((_path, record),) = _dataset_records(tmp_path)
    assert record["dataset"]["distributions"][0]["encoding_format"] == PARQUET_MEDIA_TYPE


def test_parquet_tests_and_datasets_keep_the_iris_they_had(tmp_path: Path) -> None:
    # Two tests of one cell, a parquet file each. A period and the registered
    # media type now enter their records, and the seed a colliding pair is
    # re-minted from reads the whole record; these records do not collide, so
    # they keep the IRIs 21af1b8b minted, before either change.
    ws = battinfo.workspace(str(tmp_path), registry_url=None)
    ws.add("cell", spec=CellSpec(**SPEC), serial_numbers=["C01"])
    tests = {}
    for name, offset in (("a.bdf.parquet", 0.0), ("b.bdf.parquet", 0.1)):
        columns = {
            "test_time_second": [0.0, 10.0, 20.0, 30.0],
            "voltage_volt": [3.0 + offset, 3.1, 3.2, 3.3],
            "unix_time_second": [float(T0), T0 + 10.0, T0 + 20.0, T0 + 30.0],
        }
        (tmp_path / "data").mkdir(exist_ok=True)
        pq.write_table(pa.table(columns), tmp_path / "data" / name, row_group_size=2)
        tests[name] = ws.add("test", type="cycling", cell="C01", data=f"data/{name}")[0]
    ws.save()
    base = "https://w3id.org/battinfo/id/1001/"
    assert str(tests["a.bdf.parquet"].id) == f"{base}test/n74h-9vzj-0xty-27f0"
    assert str(tests["b.bdf.parquet"].id) == f"{base}test/head-sbpb-sx25-0eh4"
    assert sorted(str(d.id) for d in ws._ws.datasets) == [
        f"{base}dataset/h0zh-kk2e-852k-xvs2",
        f"{base}dataset/shea-49d0-jr9v-66jt",
    ]
    assert all(d.temporal_coverage for d in ws._ws.datasets)


# ── The media type ───────────────────────────────────────────────────────────


def test_media_types_by_file_name() -> None:
    assert _guess_format(Path("cell.bdf.parquet")) == PARQUET_MEDIA_TYPE
    assert file_media_type("cell.bdf.parquet") == PARQUET_MEDIA_TYPE
    # Before the platform's mimetypes table, which on Windows can say vnd.ms-excel.
    assert file_media_type("cell.bdf.csv") == "text/csv"
    assert file_media_type("CELL.PARQUET") == PARQUET_MEDIA_TYPE
    assert file_media_type("") is None


def test_the_deprecated_alias_is_written_as_the_registered_type() -> None:
    assert registered_media_type("application/x-parquet") == PARQUET_MEDIA_TYPE
    assert registered_media_type(" Application/X-Parquet ") == PARQUET_MEDIA_TYPE
    assert registered_media_type("text/csv") == "text/csv"


def test_a_saved_alias_is_written_out_as_the_registered_type(tmp_path: Path) -> None:
    from battinfo.jsonld import dataset_to_jsonld

    ws = _workspace(tmp_path, {"a.bdf.parquet": [T0, T0 + 10]})
    ws.save()
    # A record saved before battinfo used the registered type.
    ((path, record),) = _dataset_records(tmp_path)
    record["dataset"]["distributions"][0]["encoding_format"] = "application/x-parquet"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    saved = path.read_text(encoding="utf-8")

    graph_text = ws.preview_jsonld(tmp_path / "preview.jsonld").read_text(encoding="utf-8")
    assert "x-parquet" not in graph_text
    graph = json.loads(graph_text)["@graph"]
    media = [d["dcat:mediaType"] for n in graph for d in n.get("dcat:distribution", []) if "dcat:mediaType" in d]
    assert media and all(m == {"@id": f"{IANA}{PARQUET_MEDIA_TYPE}"} for m in media)
    formats = [d["schema:encodingFormat"] for n in graph for d in n.get("schema:distribution", [])]
    assert formats and set(formats) == {PARQUET_MEDIA_TYPE}

    dist = dataset_to_jsonld(record)["dcat:distribution"]
    assert [d["dcat:mediaType"] for d in dist] == [PARQUET_MEDIA_TYPE]
    # Reading the record for the graph does not rewrite it.
    assert path.read_text(encoding="utf-8") == saved


def test_the_ro_crate_names_parquet_by_the_registered_type(tmp_path: Path) -> None:
    pytest.importorskip("rocrate")
    ws = _workspace(tmp_path, {"a.bdf.parquet": [T0, T0 + 10]})
    ws.save()
    crate = json.loads(ws.preview_rocrate(tmp_path / "crate.json").read_text(encoding="utf-8"))
    files = [n for n in crate["@graph"] if n.get("@type") == "File" and str(n.get("name", "")).endswith(".parquet")]
    assert files and all(n["encodingFormat"] == PARQUET_MEDIA_TYPE for n in files)


def test_other_emitters_write_the_registered_type() -> None:
    from battinfo.publication import _schema_distribution_node
    from battinfo.transform.json_to_jsonld import _parameter_file_node

    item = {"content_url": "https://example.org/a.parquet", "encoding_format": "application/x-parquet"}
    assert _schema_distribution_node(item, part_of_id="#d")["schema:encodingFormat"] == PARQUET_MEDIA_TYPE
    node = _parameter_file_node(item)
    assert node is not None and node["schema:encodingFormat"] == PARQUET_MEDIA_TYPE


# ── The BDF table schema ─────────────────────────────────────────────────────


def _bdf_conformance(graph_path: Path) -> list[str]:
    graph = json.loads(graph_path.read_text(encoding="utf-8"))["@graph"]
    found = []
    for node in graph:
        for key in ("dcat:distribution", "schema:distribution"):
            for dist in node.get(key, []):
                if "dcterms:conformsTo" in dist:
                    found.append(dist["dcterms:conformsTo"]["@id"])
    return found


def test_the_deposit_names_the_bdf_version_given(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, {"a.bdf.parquet": [T0, T0 + 10]})
    ws.save()
    named = _bdf_conformance(ws.preview_jsonld(tmp_path / "preview.jsonld", bdf_version="1.3.0"))
    assert named and set(named) == {BDF_1_3_0}


def test_without_a_bdf_version_the_deposit_names_the_unversioned_schema(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, {"a.bdf.parquet": [T0, T0 + 10]})
    ws.save()
    named = _bdf_conformance(ws.preview_jsonld(tmp_path / "preview.jsonld"))
    assert named and set(named) == {BDF_TABLE_SCHEMA_IRI}
    assert BDF_TABLE_SCHEMA_IRI == "https://w3id.org/battery-data-alliance/ontology/battery-data-format/schema"


@pytest.mark.parametrize("value", ["1.3", "v1.3.0", "1.3.0-rc1", 130])
def test_a_malformed_bdf_version_is_refused_before_anything_is_made(tmp_path: Path, value: Any) -> None:
    ws = _workspace(tmp_path, {"a.bdf.parquet": [T0, T0 + 10]})
    ws.save()
    with pytest.raises(ValueError, match="bdf_version="):
        ws.preview_jsonld(tmp_path / "preview.jsonld", bdf_version=value)
    assert not (tmp_path / "preview.jsonld").exists()
    # ws.zenodo() refuses it with the form's other options, before it needs a token.
    with pytest.raises(ValueError, match="bdf_version="):
        ws.zenodo(bdf_version=value)
