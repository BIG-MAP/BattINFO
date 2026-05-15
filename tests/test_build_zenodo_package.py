from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest

from battinfo import (
    CellInstance,
    CellSpecification,
    CellType,
    Dataset,
    Test,
    ZenodoCellRecord,
    ZenodoDatasetEntry,
    build_zenodo_package,
)
from battinfo.bundle import (
    ZENODO_CELL_RECORD_FILENAME,
    ProtocolInfo,
    ProvenanceInfo,
)
from battinfo.publication import DEFAULT_PUBLISH_FILENAME, DEFAULT_RO_CRATE_METADATA_FILENAME

# ── fixtures ───────────────────────────────────────────────────────────────────

CELL_TYPE_ID = "https://w3id.org/battinfo/cell-type/7r2m-4q8v-k6nt-c3pj"
CELL_INSTANCE_ID = "https://w3id.org/battinfo/cell/69ca-scxq-6w58-e9tc"
TEST_ID = "https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r"
DATASET_ID = "https://w3id.org/battinfo/dataset/gj1y-pn2n-t5pm-gs9c"


def _make_record(n_datasets: int = 1, *, with_spec: bool = False) -> ZenodoCellRecord:
    cell_type = CellType(
        id=CELL_TYPE_ID,
        name="Energizer CR2032",
        manufacturer="Energizer",
        model="CR2032",
        format="coin",
        chemistry="Li-primary",
        source=ProvenanceInfo(type="datasheet"),
    )
    spec = None
    if with_spec:
        spec = CellSpecification(
            id=CELL_TYPE_ID,
            manufacturer="Energizer",
            model="CR2032",
            format="coin",
            chemistry="Li-primary",
            source=ProvenanceInfo(type="datasheet"),
        )
    datasets = []
    for i in range(n_datasets):
        idx = f"{i + 1:03d}"
        ci_id = f"https://w3id.org/battinfo/cell/ci-{idx}"
        test_id = f"https://w3id.org/battinfo/test/t-{idx}"
        ds_id = f"https://w3id.org/battinfo/dataset/d-{idx}"
        ci = CellInstance(
            id=ci_id,
            name=f"sn-{idx}",
            cell_type_id=CELL_TYPE_ID,
            serial_number=f"sn-{idx}",
            source=ProvenanceInfo(type="measurement"),
        )
        test = Test(
            id=test_id,
            name=f"capacity check {idx}",
            test_kind="capacity_check",
            cell_instance_id=ci_id,
            protocol=ProtocolInfo(name="constant current"),
            source=ProvenanceInfo(type="measurement"),
        )
        dataset = Dataset(
            id=ds_id,
            name=f"Energizer CR2032 {idx}",
            cell_instance_id=ci_id,
            test_id=test_id,
            source=ProvenanceInfo(type="measurement"),
        )
        datasets.append(ZenodoDatasetEntry(cell_instances=[ci], test=test, dataset=dataset))

    return ZenodoCellRecord(cell_type=cell_type, cell_specification=spec, datasets=datasets)


def _make_file_sets(
    tmp_path: Path,
    n: int,
    *,
    include_bdf: bool = True,
) -> list[tuple[Path | None, Path | None]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    file_sets = []
    for i in range(1, n + 1):
        raw = tmp_path / f"raw_{i:03d}.csv"
        raw.write_text("time,voltage\n0,3.0\n1,2.9\n", encoding="utf-8")
        bdf = None
        if include_bdf:
            bdf = tmp_path / f"bdf_{i:03d}.parquet"
            bdf.write_bytes(b"PAR1fake")
        file_sets.append((raw, bdf))
    return file_sets


# ── basic output presence ──────────────────────────────────────────────────────

def test_single_dataset_files_created(tmp_path: Path) -> None:
    record = _make_record(1)
    staging = tmp_path / "staging"
    result = build_zenodo_package(record, staging, _make_file_sets(tmp_path / "src", 1))

    assert result["status"] == "ok"
    assert result["dataset_count"] == 1
    assert Path(result["bundle_path"]).exists()
    assert Path(result["publish_path"]).exists()
    assert Path(result["ro_crate_path"]).exists()
    # canonical data file names
    assert (staging / "dataset-001.csv").exists()
    assert (staging / "dataset-001.bdf.parquet").exists()


def test_multi_dataset_file_naming(tmp_path: Path) -> None:
    record = _make_record(3)
    staging = tmp_path / "staging"
    build_zenodo_package(record, staging, _make_file_sets(tmp_path / "src", 3))

    for i in range(1, 4):
        assert (staging / f"dataset-{i:03d}.csv").exists()
        assert (staging / f"dataset-{i:03d}.bdf.parquet").exists()
    assert not (staging / "dataset-004.csv").exists()


def test_no_bdf_files(tmp_path: Path) -> None:
    record = _make_record(2)
    staging = tmp_path / "staging"
    file_sets = _make_file_sets(tmp_path / "src", 2, include_bdf=False)
    result = build_zenodo_package(record, staging, file_sets)

    assert len(result["staged_data_files"]) == 2
    assert not (staging / "dataset-001.bdf.parquet").exists()


def test_none_raw_file_skipped(tmp_path: Path) -> None:
    record = _make_record(2)
    src = tmp_path / "src"
    src.mkdir()
    bdf1 = src / "bdf_001.parquet"
    bdf1.write_bytes(b"PAR1")
    file_sets: list[tuple[Path | None, Path | None]] = [(None, bdf1), (None, None)]
    staging = tmp_path / "staging"
    result = build_zenodo_package(record, staging, file_sets)

    assert len(result["staged_data_files"]) == 1
    assert (staging / "dataset-001.bdf.parquet").exists()
    assert not (staging / "dataset-001.csv").exists()


# ── battinfo.bundle.json ───────────────────────────────────────────────────────

def test_bundle_json_is_valid_cell_record(tmp_path: Path) -> None:
    record = _make_record(2)
    staging = tmp_path / "staging"
    result = build_zenodo_package(record, staging, _make_file_sets(tmp_path / "src", 2))

    raw = json.loads(Path(result["bundle_path"]).read_text(encoding="utf-8"))
    assert raw["kind"] == "BattinfoCellRecord"
    assert len(raw["datasets"]) == 2

    # Round-trip
    loaded = ZenodoCellRecord.from_flat_json(raw)
    assert loaded.cell_type.id == CELL_TYPE_ID


# ── battinfo.publish.jsonld ────────────────────────────────────────────────────

def test_publish_jsonld_has_graph(tmp_path: Path) -> None:
    record = _make_record(2)
    staging = tmp_path / "staging"
    result = build_zenodo_package(record, staging, _make_file_sets(tmp_path / "src", 2))

    payload = json.loads(Path(result["publish_path"]).read_text(encoding="utf-8"))
    assert "@context" in payload
    assert "@graph" in payload
    graph = payload["@graph"]
    assert isinstance(graph, list)
    # cell type node
    ids_in_graph = {node.get("@id") for node in graph}
    assert CELL_TYPE_ID in ids_in_graph


def test_publish_jsonld_placeholder_urls(tmp_path: Path) -> None:
    record = _make_record(1)
    staging = tmp_path / "staging"
    result = build_zenodo_package(record, staging, _make_file_sets(tmp_path / "src", 1))

    text = Path(result["publish_path"]).read_text(encoding="utf-8")
    assert "ZENODO_RECORD_ID" in text
    assert "file://" not in text


def test_publish_jsonld_custom_placeholder(tmp_path: Path) -> None:
    record = _make_record(1)
    staging = tmp_path / "staging"
    build_zenodo_package(
        record,
        staging,
        _make_file_sets(tmp_path / "src", 1),
        zenodo_record_id_placeholder="12345678",
    )
    text = (staging / DEFAULT_PUBLISH_FILENAME).read_text(encoding="utf-8")
    assert "12345678" in text


def test_publish_jsonld_contains_dataset_distribution(tmp_path: Path) -> None:
    record = _make_record(1)
    staging = tmp_path / "staging"
    build_zenodo_package(record, staging, _make_file_sets(tmp_path / "src", 1))

    payload = json.loads((staging / DEFAULT_PUBLISH_FILENAME).read_text(encoding="utf-8"))
    graph = payload["@graph"]
    dataset_nodes = [n for n in graph if "BatteryTestResult" in (n.get("@type") or [])]
    assert len(dataset_nodes) == 1
    dist = dataset_nodes[0].get("schema:distribution", [])
    assert len(dist) >= 1
    assert all("ZENODO_RECORD_ID" in d.get("schema:contentUrl", "") for d in dist)


def test_publish_jsonld_multi_dataset_cell_instance_nodes(tmp_path: Path) -> None:
    record = _make_record(3)
    staging = tmp_path / "staging"
    build_zenodo_package(record, staging, _make_file_sets(tmp_path / "src", 3))

    payload = json.loads((staging / DEFAULT_PUBLISH_FILENAME).read_text(encoding="utf-8"))
    graph = payload["@graph"]
    cell_nodes = [n for n in graph if "BatteryCell" in (n.get("@type") or [])]
    assert len(cell_nodes) == 3  # one per dataset entry


def test_publish_jsonld_with_cell_specification(tmp_path: Path) -> None:
    record = _make_record(1, with_spec=True)
    staging = tmp_path / "staging"
    build_zenodo_package(record, staging, _make_file_sets(tmp_path / "src", 1))

    payload = json.loads((staging / DEFAULT_PUBLISH_FILENAME).read_text(encoding="utf-8"))
    graph = payload["@graph"]
    spec_nodes = [n for n in graph if "BatteryCellSpecification" in (n.get("@type") or [])]
    assert len(spec_nodes) >= 1


# ── ro-crate-metadata.json ─────────────────────────────────────────────────────

def test_ro_crate_structure(tmp_path: Path) -> None:
    record = _make_record(2)
    staging = tmp_path / "staging"
    result = build_zenodo_package(record, staging, _make_file_sets(tmp_path / "src", 2))

    crate = json.loads(Path(result["ro_crate_path"]).read_text(encoding="utf-8"))
    assert crate["@context"] == "https://w3id.org/ro/crate/1.2/context"
    graph = crate["@graph"]
    ids = {n["@id"] for n in graph}
    assert "./" in ids
    assert DEFAULT_RO_CRATE_METADATA_FILENAME in ids


def test_ro_crate_has_file_entries_with_placeholder_urls(tmp_path: Path) -> None:
    record = _make_record(2)
    staging = tmp_path / "staging"
    build_zenodo_package(record, staging, _make_file_sets(tmp_path / "src", 2))

    crate = json.loads((staging / DEFAULT_RO_CRATE_METADATA_FILENAME).read_text(encoding="utf-8"))
    file_nodes = [n for n in crate["@graph"] if n.get("@type") == "File"]
    assert len(file_nodes) >= 4  # 2 csv + 2 bdf
    urls = [n.get("url", "") for n in file_nodes]
    assert all("ZENODO_RECORD_ID" in u for u in urls if u)


def test_ro_crate_checksums_present(tmp_path: Path) -> None:
    record = _make_record(1)
    staging = tmp_path / "staging"
    build_zenodo_package(record, staging, _make_file_sets(tmp_path / "src", 1))

    crate = json.loads((staging / DEFAULT_RO_CRATE_METADATA_FILENAME).read_text(encoding="utf-8"))
    data_files = [n for n in crate["@graph"] if n.get("@type") == "File" and n["@id"].startswith("dataset-")]
    assert all("sha256" in n for n in data_files)
    assert all("contentSize" in n for n in data_files)


# ── file_url_map ───────────────────────────────────────────────────────────────

def test_file_url_map_covers_all_files(tmp_path: Path) -> None:
    record = _make_record(2)
    staging = tmp_path / "staging"
    result = build_zenodo_package(record, staging, _make_file_sets(tmp_path / "src", 2))

    url_map = result["file_url_map"]
    # data files
    assert "dataset-001.csv" in url_map
    assert "dataset-001.bdf.parquet" in url_map
    assert "dataset-002.csv" in url_map
    # meta files
    assert ZENODO_CELL_RECORD_FILENAME in url_map
    assert DEFAULT_PUBLISH_FILENAME in url_map
    assert DEFAULT_RO_CRATE_METADATA_FILENAME in url_map
    for url in url_map.values():
        assert "ZENODO_RECORD_ID" in url


# ── error cases ────────────────────────────────────────────────────────────────

def test_mismatched_file_sets_length_raises(tmp_path: Path) -> None:
    record = _make_record(2)
    file_sets = _make_file_sets(tmp_path / "src", 3)  # 3 vs 2 entries
    with pytest.raises(ValueError, match="file_sets length"):
        build_zenodo_package(record, tmp_path / "staging", file_sets)


def test_staging_dir_created_if_absent(tmp_path: Path) -> None:
    record = _make_record(1)
    staging = tmp_path / "deep" / "nested" / "staging"
    assert not staging.exists()
    build_zenodo_package(record, staging, _make_file_sets(tmp_path / "src", 1))
    assert staging.exists()
