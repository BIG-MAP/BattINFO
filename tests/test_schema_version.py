"""Every record emitter stamps the single battinfo.bundle.SCHEMA_VERSION constant.

Records originally said "0.1.0"; the 2026-07 input-model consolidation accidentally
forked dataset records to "1.0.0". "0.2.0" deliberately supersedes both — this test
pins the constant and checks the model layer, the dict-builder layer, and an interop
emitter all agree, so a future fork cannot happen silently again.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import template_material_spec
from battinfo.bundle import SCHEMA_VERSION, CellSpecification, Dataset, ProvenanceInfo


def test_schema_version_value() -> None:
    assert SCHEMA_VERSION == "0.2.0"


def test_bundle_models_default_to_the_constant() -> None:
    spec = CellSpecification(manufacturer="Acme", model_name="X1", chemistry="LFP", format="cylindrical")
    assert spec.schema_version == SCHEMA_VERSION


def test_dataset_record_carries_the_constant() -> None:
    dataset = Dataset(
        id="https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x",
        name="Version-stamp dataset",
        access_url="https://example.org/datasets/version-stamp",
        created_at=1771804803,
        source=ProvenanceInfo(type="measurement", retrieved_at=1771805001),
    )
    assert dataset.to_record()["schema_version"] == SCHEMA_VERSION


def test_dict_builders_carry_the_constant() -> None:
    assert template_material_spec()["schema_version"] == SCHEMA_VERSION


def test_read_records_keep_their_stored_version() -> None:
    # An existing record's declared version is provenance — loading must not rewrite it.
    dataset = Dataset(
        id="https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x",
        name="Version-stamp dataset",
        access_url="https://example.org/datasets/version-stamp",
        created_at=1771804803,
        source=ProvenanceInfo(type="measurement", retrieved_at=1771805001),
    )
    record = dataset.to_record()
    record["schema_version"] = "0.1.0"
    assert Dataset.from_record(record).schema_version == "0.1.0"
