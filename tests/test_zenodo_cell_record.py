from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest

from battinfo import (
    BattinfoBundle,
    CellInstance,
    CellSpecification,
    Dataset,
    Test,
    ZenodoCellRecord,
    ZenodoDatasetEntry,
)
from battinfo.bundle import (
    ZENODO_CELL_RECORD_FILENAME,
    ProtocolInfo,
    ProvenanceInfo,
)

# ── shared fixtures ────────────────────────────────────────────────────────────

CELL_TYPE_ID = "https://w3id.org/battinfo/spec/7r2m-4q8v-k6nt-c3pj"
CELL_SPEC_ID = "https://w3id.org/battinfo/spec/7r2m-4q8v-k6nt-c3pj"
CELL_INSTANCE_ID = "https://w3id.org/battinfo/cell/69ca-scxq-6w58-e9tc"
CELL_INSTANCE_ID_2 = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-dddd"
TEST_ID = "https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r"
TEST_ID_2 = "https://w3id.org/battinfo/test/1111-2222-3333-4444"
DATASET_ID = "https://w3id.org/battinfo/dataset/gj1y-pn2n-t5pm-gs9c"
DATASET_ID_2 = "https://w3id.org/battinfo/dataset/eeee-ffff-gggg-hhhh"


def _make_cell_spec() -> CellSpecification:
    return CellSpecification(
        id=CELL_SPEC_ID,
        manufacturer="Energizer",
        model="CR2032",
        format="coin",
        chemistry="Li-primary",
        positive_electrode_basis="MnO2",
        negative_electrode_basis="Li-metal",
        properties={"nominal_voltage": {"value": 3.0, "unit": "V"}},
        source=ProvenanceInfo(type="datasheet"),
    )


def _make_cell_spec() -> CellSpecification:
    return CellSpecification(
        id=CELL_TYPE_ID,
        name="Energizer CR2032",
        manufacturer="Energizer",
        model="CR2032",
        format="coin",
        chemistry="Li-primary",
        properties={"nominal_voltage": {"value": 3.0, "unit": "V"}},
        source=ProvenanceInfo(type="datasheet"),
    )


def _make_cell_instance(
    instance_id: str = CELL_INSTANCE_ID,
    serial: str = "sn-001",
) -> CellInstance:
    return CellInstance(
        id=instance_id,
        name=serial,
        cell_spec_id=CELL_TYPE_ID,
        serial_number=serial,
        source=ProvenanceInfo(type="measurement"),
    )


def _make_dataset_entry(
    test_id: str = TEST_ID,
    dataset_id: str = DATASET_ID,
    cell_instances: list[CellInstance] | None = None,
) -> ZenodoDatasetEntry:
    test = Test(
        id=test_id,
        name="capacity check",
        test_kind="capacity_check",
        cell_instance_id=CELL_INSTANCE_ID,
        protocol=ProtocolInfo(name="constant current"),
        source=ProvenanceInfo(type="measurement"),
    )
    dataset = Dataset(
        id=dataset_id,
        name=f"Energizer CR2032 dataset {test_id[-4:]}",
        cell_instance_id=CELL_INSTANCE_ID,
        test_id=test_id,
        source=ProvenanceInfo(type="measurement"),
    )
    return ZenodoDatasetEntry(
        cell_instances=cell_instances or [],
        test=test,
        dataset=dataset,
    )


# ── single-dataset round-trips ─────────────────────────────────────────────────

def test_round_trip_no_cell_instances() -> None:
    """Aggregate record: no individual cell tracking."""
    record = ZenodoCellRecord(
        cell_spec=_make_cell_spec(),
        datasets=[_make_dataset_entry()],
    )

    flat = record.to_flat_json()
    assert flat["kind"] == "BattinfoCellRecord"
    assert flat["datasets"][0]["cell_instances"] == []

    loaded = ZenodoCellRecord.from_flat_json(flat)
    assert loaded.cell_spec.id == CELL_TYPE_ID
    assert loaded.datasets[0].cell_instances == []
    assert loaded.datasets[0].test.id == TEST_ID


def test_round_trip_one_cell_instance() -> None:
    """Entry with a single tracked cell."""
    ci = _make_cell_instance()
    record = ZenodoCellRecord(
        cell_spec=_make_cell_spec(),
        datasets=[_make_dataset_entry(cell_instances=[ci])],
    )

    flat = record.to_flat_json()
    assert len(flat["datasets"][0]["cell_instances"]) == 1

    loaded = ZenodoCellRecord.from_flat_json(flat)
    assert len(loaded.datasets[0].cell_instances) == 1
    assert loaded.datasets[0].cell_instances[0].serial_number == "sn-001"


def test_round_trip_multiple_cell_instances_per_entry() -> None:
    """Entry where several cells were tested together."""
    ci1 = _make_cell_instance(CELL_INSTANCE_ID, "sn-001")
    ci2 = _make_cell_instance(CELL_INSTANCE_ID_2, "sn-002")
    record = ZenodoCellRecord(
        cell_spec=_make_cell_spec(),
        datasets=[_make_dataset_entry(cell_instances=[ci1, ci2])],
    )

    flat = record.to_flat_json()
    assert len(flat["datasets"][0]["cell_instances"]) == 2

    loaded = ZenodoCellRecord.from_flat_json(flat)
    serials = [ci.serial_number for ci in loaded.datasets[0].cell_instances]
    assert serials == ["sn-001", "sn-002"]


def test_round_trip_with_cell_specification() -> None:
    record = ZenodoCellRecord(
        cell_spec=_make_cell_spec(),
        cell_specification=_make_cell_spec(),
        datasets=[_make_dataset_entry()],
    )

    flat = record.to_flat_json()
    assert flat["cell_specification"]["specification"]["manufacturer"] == "Energizer"

    loaded = ZenodoCellRecord.from_flat_json(flat)
    assert loaded.cell_specification is not None
    assert loaded.cell_specification.model == "CR2032"
    assert loaded.cell_spec.cell_specification_id == CELL_SPEC_ID


def test_round_trip_multi_dataset_mixed_instances() -> None:
    """Some entries have instance data, others don't."""
    entry_with = _make_dataset_entry(cell_instances=[_make_cell_instance()])
    entry_without = _make_dataset_entry(test_id=TEST_ID_2, dataset_id=DATASET_ID_2)

    record = ZenodoCellRecord(
        cell_spec=_make_cell_spec(),
        datasets=[entry_with, entry_without],
    )

    flat = record.to_flat_json()
    assert len(flat["datasets"]) == 2
    assert len(flat["datasets"][0]["cell_instances"]) == 1
    assert flat["datasets"][1]["cell_instances"] == []

    loaded = ZenodoCellRecord.from_flat_json(flat)
    assert len(loaded.datasets[0].cell_instances) == 1
    assert len(loaded.datasets[1].cell_instances) == 0


# ── file I/O ──────────────────────────────────────────────────────────────────

def test_to_path_and_from_path(tmp_path: Path) -> None:
    record = ZenodoCellRecord(
        cell_spec=_make_cell_spec(),
        datasets=[_make_dataset_entry(cell_instances=[_make_cell_instance()])],
    )
    out = tmp_path / ZENODO_CELL_RECORD_FILENAME
    record.to_path(out)

    assert out.exists()
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["kind"] == "BattinfoCellRecord"
    assert len(raw["datasets"][0]["cell_instances"]) == 1

    loaded = ZenodoCellRecord.from_path(out)
    assert loaded.cell_spec.id == CELL_TYPE_ID
    assert loaded.datasets[0].cell_instances[0].serial_number == "sn-001"


# ── from_battinfo_bundles ──────────────────────────────────────────────────────

def test_from_battinfo_bundles_single() -> None:
    cell_spec = _make_cell_spec()
    entry = _make_dataset_entry(cell_instances=[_make_cell_instance()])
    bundle = BattinfoBundle(
        cell_spec=cell_spec,
        cell_instance=entry.cell_instances[0],
        test=entry.test,
        dataset=entry.dataset,
    )

    record = ZenodoCellRecord.from_battinfo_bundles([bundle])
    assert record.cell_spec.id == CELL_TYPE_ID
    assert len(record.datasets) == 1
    assert len(record.datasets[0].cell_instances) == 1
    assert record.datasets[0].cell_instances[0].serial_number == "sn-001"


def test_from_battinfo_bundles_multi() -> None:
    cell_spec = _make_cell_spec()
    spec = _make_cell_spec()
    ci1 = _make_cell_instance(CELL_INSTANCE_ID, "sn-001")
    ci2 = _make_cell_instance(CELL_INSTANCE_ID_2, "sn-002")
    e1 = _make_dataset_entry(cell_instances=[ci1])
    e2 = _make_dataset_entry(test_id=TEST_ID_2, dataset_id=DATASET_ID_2, cell_instances=[ci2])

    bundles = [
        BattinfoBundle(cell_spec=cell_spec, cell_instance=ci1, test=e1.test, dataset=e1.dataset),
        BattinfoBundle(cell_spec=cell_spec, cell_instance=ci2, test=e2.test, dataset=e2.dataset),
    ]

    record = ZenodoCellRecord.from_battinfo_bundles(bundles, cell_specification=spec)
    assert len(record.datasets) == 2
    assert record.datasets[0].cell_instances[0].serial_number == "sn-001"
    assert record.datasets[1].cell_instances[0].serial_number == "sn-002"
    assert record.cell_specification is not None


def test_from_battinfo_bundles_rejects_mixed_cell_specs() -> None:
    cell_spec_a = _make_cell_spec()
    cell_spec_b = _make_cell_spec()
    cell_spec_b = cell_spec_b.model_copy(update={"id": "https://w3id.org/battinfo/cell/different"})
    ci = _make_cell_instance()
    entry = _make_dataset_entry(cell_instances=[ci])
    bundles = [
        BattinfoBundle(cell_spec=cell_spec_a, cell_instance=ci, test=entry.test, dataset=entry.dataset),
        BattinfoBundle(cell_spec=cell_spec_b, cell_instance=ci, test=entry.test, dataset=entry.dataset),
    ]
    with pytest.raises(ValueError, match="same cell_spec.id"):
        ZenodoCellRecord.from_battinfo_bundles(bundles)


# ── JSON structure ─────────────────────────────────────────────────────────────

def test_flat_json_cell_spec_structure() -> None:
    flat = ZenodoCellRecord(
        cell_spec=_make_cell_spec(),
        datasets=[_make_dataset_entry()],
    ).to_flat_json()
    ct = flat["cell_spec"]
    assert "cell_spec" in ct
    assert ct["cell_spec"]["id"] == CELL_TYPE_ID
    assert ct["cell_spec"]["manufacturer"]["name"] == "Energizer"


def test_flat_json_dataset_entry_keys() -> None:
    flat = ZenodoCellRecord(
        cell_spec=_make_cell_spec(),
        datasets=[_make_dataset_entry(cell_instances=[_make_cell_instance()])],
    ).to_flat_json()
    entry = flat["datasets"][0]
    assert set(entry.keys()) == {"cell_instances", "test", "dataset"}
    assert entry["cell_instances"][0]["cell_instance"]["id"] == CELL_INSTANCE_ID
    assert entry["test"]["test"]["id"] == TEST_ID
    assert entry["dataset"]["dataset"]["id"] == DATASET_ID


# ── error cases ────────────────────────────────────────────────────────────────

def test_from_flat_json_missing_cell_spec_raises() -> None:
    with pytest.raises(ValueError, match="cell_spec"):
        ZenodoCellRecord.from_flat_json({"kind": "BattinfoCellRecord", "datasets": []})


def test_from_flat_json_missing_datasets_raises() -> None:
    flat = ZenodoCellRecord(
        cell_spec=_make_cell_spec(),
        datasets=[_make_dataset_entry()],
    ).to_flat_json()
    del flat["datasets"]
    with pytest.raises(ValueError, match="datasets"):
        ZenodoCellRecord.from_flat_json(flat)


def test_from_flat_json_malformed_cell_instances_raises() -> None:
    flat = ZenodoCellRecord(
        cell_spec=_make_cell_spec(),
        datasets=[_make_dataset_entry()],
    ).to_flat_json()
    flat["datasets"][0]["cell_instances"] = "not-a-list"
    with pytest.raises(ValueError, match="cell_instances"):
        ZenodoCellRecord.from_flat_json(flat)


def test_empty_bundles_rejected() -> None:
    with pytest.raises(ValueError):
        ZenodoCellRecord.from_battinfo_bundles([])
