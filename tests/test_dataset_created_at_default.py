"""A new version of a published dataset saves under the strict policy (evaluation finding E-03).

A published record read back with Dataset.from_record() has published_at but no
created_at. Saving defaulted created_at to the save time, which is after the
publication date, so strict validation refused the record with an error about
published_at, a field the user never touched. created_at now defaults to
published_at when only that is known, and modified_at then to the save time:
the save is the modification, and the old publication time is not.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import pytest

import battinfo
from battinfo._workspace import Workspace

PUBLISHED = 1750032000  # 2025-06-16, the Empa deposit
CELL = "https://w3id.org/battinfo/cell/epb7-1s8v-p342-469z"
TEST = "https://w3id.org/battinfo/test/68hd-09k3-ew5p-p551"
FILE_URL = "https://pub-5d124607e4b748eea681efca486508ab.r2.dev/datasets/zbwt81/zbwt-812f-t4p4-ea49.bdf.parquet"

# The production record the evaluation relinked (trimmed to the fields that matter here).
PUBLISHED_RECORD = {
    "schema_version": "1.0.0",
    "dataset": {
        "id": "https://w3id.org/battinfo/dataset/zbwt-812f-t4p4-ea49",
        "name": "Cycling data of Empa coin cell 000149",
        "access_url": FILE_URL,
        "distributions": [
            {
                "role": "processed",
                "content_url": FILE_URL,
                "name": "zbwt-812f-t4p4-ea49.bdf.parquet",
                "encoding_format": "application/vnd.apache.parquet",
                "content_size": "9059665",
                "checksum": {
                    "algorithm": "sha256",
                    "value": "0165c2f6f93980902aeb3de54dbdbcf751211f99f18737f679654c11a44a90c3",
                },
            }
        ],
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "published_at": PUBLISHED,
        "about": [CELL, TEST],
    },
    "provenance": {
        "source_type": "measurement",
        "retrieved_at": PUBLISHED,
        "source_url": "https://doi.org/10.5281/zenodo.15481956",
    },
}


def _save(dataset: battinfo.Dataset, root: Path) -> dict:
    saved = battinfo.save_dataset(
        dataset,
        source_root=root,
        mode="upsert",
        validation_policy="strict",
        resolve_references=False,
        build_jsonld=False,
        build_html=False,
    )
    return json.loads(Path(saved["path"]).read_text(encoding="utf-8"))


def test_published_dataset_resaves_under_the_strict_policy(tmp_path: Path) -> None:
    """The reproduction from the evaluation (e03_created_at.py)."""
    dataset = battinfo.Dataset.from_record(copy.deepcopy(PUBLISHED_RECORD))
    assert dataset.created_at is None
    before = int(time.time())
    record = _save(dataset, tmp_path)
    assert record["dataset"]["created_at"] == PUBLISHED
    assert record["dataset"]["published_at"] == PUBLISHED
    # The new version was modified now, not when the first one was published.
    assert before <= record["dataset"]["modified_at"] <= int(time.time()) + 1


def test_a_relinked_new_version_saves(tmp_path: Path) -> None:
    new_test = "https://w3id.org/battinfo/test/mcnf-7ph4-stth-ppaj"
    dataset = battinfo.Dataset.from_record(copy.deepcopy(PUBLISHED_RECORD)).model_copy(update={"test_id": new_test})
    record = _save(dataset, tmp_path)
    assert new_test in record["dataset"]["about"]
    assert record["dataset"]["created_at"] == PUBLISHED


def test_the_workspace_engine_defaults_created_at_the_same_way(tmp_path: Path) -> None:
    engine = Workspace(root=tmp_path / "engine")
    dataset = battinfo.Dataset(
        name="Cell 1 data", access_url=FILE_URL, published_at=PUBLISHED, cell_instance_id=CELL, test_id=TEST
    )
    before = int(time.time())
    finalized = engine._finalize_dataset(dataset, {}, {})
    assert finalized.created_at == PUBLISHED
    assert before <= finalized.modified_at <= int(time.time()) + 1


def test_without_either_date_created_at_is_the_save_time(tmp_path: Path) -> None:
    before = int(time.time())
    record = _save(
        battinfo.Dataset(name="Fresh data", access_url=FILE_URL, cell_instance_id=CELL, source={"type": "measurement"}),
        tmp_path,
    )
    assert before <= record["dataset"]["created_at"] <= int(time.time()) + 1
    assert record["dataset"]["published_at"] == record["dataset"]["created_at"]


def test_the_ordering_rule_still_holds(tmp_path: Path) -> None:
    dataset = battinfo.Dataset.from_record(copy.deepcopy(PUBLISHED_RECORD)).model_copy(
        update={"created_at": PUBLISHED + 3600}
    )
    with pytest.raises(ValueError, match=r"published_at .* must be >= created_at"):
        _save(dataset, tmp_path)


def test_a_stated_modified_at_is_kept(tmp_path: Path) -> None:
    stated = PUBLISHED + 86400
    dataset = battinfo.Dataset.from_record(copy.deepcopy(PUBLISHED_RECORD)).model_copy(update={"modified_at": stated})
    assert _save(dataset, tmp_path)["dataset"]["modified_at"] == stated
    engine = Workspace(root=tmp_path / "engine")
    finalized = engine._finalize_dataset(
        battinfo.Dataset(
            name="Cell 1 data",
            access_url=FILE_URL,
            published_at=PUBLISHED,
            modified_at=stated,
            cell_instance_id=CELL,
            test_id=TEST,
        ),
        {},
        {},
    )
    assert finalized.modified_at == stated
