"""A dataset carries a publication time only once it is published.

Saving a dataset gave it ``published_at`` equal to its ``created_at``, so every
saved record, and its JSON-LD (``schema:datePublished``, ``dcterms:issued``),
said it was published when it was saved. A save now leaves ``published_at``
empty unless the dataset states one, and a stated one is kept. ``ws.zenodo()``
sets it when it publishes a deposit (tests/test_zenodo_deposit_versions.py).
A dataset described again without one, by a later session, keeps the time its
saved record holds, with a ``created_at`` that is not later, unless that time
is the save-time value 0.8.0 wrote (the saved ``created_at``).
"""

from __future__ import annotations

import calendar
import copy
import json
from collections.abc import Iterator
from pathlib import Path

import pytest

import battinfo
from battinfo.api._resolver import _resolver_jsonld
from battinfo.jsonld import dataset_to_jsonld
from battinfo.ws import AuthoringWorkspace, _zenodo_publication_time

CELL = "https://w3id.org/battinfo/cell/epb7-1s8v-p342-469z"
FILE_URL = "https://example.org/data/run-01.bdf.parquet"
PUBLISHED = 1750032000  # 2025-06-16T00:00:00Z
CSV = "test_time_second,voltage_volt,current_ampere\n0,3.0,0\n60,3.5,0.001\n"


def _dataset(**fields: object) -> battinfo.Dataset:
    return battinfo.Dataset(
        name="Run 01", access_url=FILE_URL, cell_instance_id=CELL, source={"type": "measurement"}, **fields
    )


def _save(draft: object, root: Path) -> dict:
    return battinfo.save_dataset(
        draft,
        source_root=root,
        mode="upsert",
        validation_policy="strict",
        resolve_references=False,
        build_jsonld=False,
        build_html=False,
    )


def _record(result: dict) -> dict:
    return json.loads(Path(result["path"]).read_text(encoding="utf-8"))


def _dates(node: dict) -> set[str]:
    return {key for key in ("schema:datePublished", "dcterms:issued") if key in node}


# ── A save does not publish ───────────────────────────────────────────────────


@pytest.mark.parametrize("created_at", [None, 1781772876], ids=["no created_at", "created_at stated"])
def test_a_saved_dataset_states_no_publication_time(tmp_path: Path, created_at: int | None) -> None:
    dataset = _dataset(created_at=created_at)
    assert dataset.published_at is None
    with_id = dataset.model_copy(update={"id": "https://w3id.org/battinfo/dataset/zbwt-812f-t4p4-ea49"})
    assert "published_at" not in with_id.to_record()["dataset"]

    record = _record(_save(dataset, tmp_path))

    assert "published_at" not in record["dataset"]
    if created_at is not None:
        assert record["dataset"]["created_at"] == created_at
    assert _dates(dataset_to_jsonld(record)) == set()
    assert "schema:datePublished" not in _resolver_jsonld(record)


def test_a_workspace_save_states_no_publication_time(tmp_path: Path) -> None:
    (tmp_path / "C01").mkdir()
    (tmp_path / "C01" / "cycling.csv").write_text(CSV, encoding="utf-8")
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = battinfo.CellSpec(manufacturer="Example Lab", model="R2032", format="coin", chemistry="li-ion")
    ws.add("cell", spec=spec, serial_numbers=["C01"])
    ws.add("test", type="cycling", cell="C01", data="C01/cycling.csv")
    ws.save()

    [path] = (tmp_path / ".battinfo" / "records" / "dataset").glob("*.json")
    assert "published_at" not in json.loads(path.read_text(encoding="utf-8"))["dataset"]
    assert all(dataset.published_at is None for dataset in ws._ws.datasets)


def test_a_resave_in_a_later_session_is_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The save-time default made the re-save compare as changed: a new save time, a new published_at."""
    clock: Iterator[int] = iter(range(1781772876, 1781772876 + 1000, 100))
    monkeypatch.setattr("battinfo.api._records._now_unix", lambda: next(clock))

    first = _save(_dataset(), tmp_path)
    again = _save(_dataset(), tmp_path)

    assert first["status"] == "created"
    assert again["status"] == "updated" and again["content_changed"] is False
    assert "published_at" not in _record(again)["dataset"]


# ── A stated publication time is kept ─────────────────────────────────────────


def test_a_stated_publication_time_survives_a_resave(tmp_path: Path) -> None:
    record = _record(_save(_dataset(published_at=PUBLISHED), tmp_path))
    assert record["dataset"]["published_at"] == PUBLISHED

    # Read back and saved again as a model, and as the record itself.
    again = _save(battinfo.Dataset.from_record(copy.deepcopy(record)), tmp_path)
    assert again["content_changed"] is False
    assert _record(again)["dataset"]["published_at"] == PUBLISHED
    assert _record(_save(copy.deepcopy(record), tmp_path))["dataset"]["published_at"] == PUBLISHED

    assert _dates(dataset_to_jsonld(record)) == {"schema:datePublished", "dcterms:issued"}
    assert _resolver_jsonld(record)["schema:datePublished"] == PUBLISHED


def test_a_stated_iso_publication_time_is_kept_as_unix_seconds(tmp_path: Path) -> None:
    record = _record(_save(_dataset(published_at="2025-06-16T00:00:00Z"), tmp_path))
    assert record["dataset"]["published_at"] == PUBLISHED


# ── A published dataset keeps the time it was first published ─────────────────

CREATED = PUBLISHED - 86400  # the day before


def _published(result: dict, **dates: object) -> None:
    """Date the saved record as ``ws.zenodo()`` does when it publishes the deposit that holds it."""
    record = _record(result)
    record["dataset"].update(published_at=PUBLISHED, **dates)
    for key in [key for key, value in dates.items() if value is None]:
        del record["dataset"][key]
    Path(result["path"]).write_text(json.dumps(record, indent=2), encoding="utf-8")


def test_a_dataset_described_again_keeps_the_publication_time_its_saved_record_holds(tmp_path: Path) -> None:
    _published(_save(_dataset(created_at=CREATED), tmp_path))

    # A later session describes the dataset again. It states no publication
    # time, and no creation time, which the save then takes to be now.
    unchanged = _save(_dataset(), tmp_path)
    assert unchanged["status"] == "updated" and unchanged["content_changed"] is False
    assert _record(unchanged)["dataset"]["published_at"] == PUBLISHED

    changed = _save(_dataset(description="Cycled at 25 degC."), tmp_path)
    assert changed["content_changed"] is True
    body = _record(changed)["dataset"]
    assert body["description"] == "Cycled at 25 degC."
    # Published then, the dataset was not created at this save, which modified it.
    assert (body["published_at"], body["created_at"]) == (PUBLISHED, CREATED)
    assert body["modified_at"] > PUBLISHED


def test_a_saved_record_with_no_earlier_creation_time_gives_the_publication_time(tmp_path: Path) -> None:
    _published(_save(_dataset(), tmp_path), created_at=None)

    body = _record(_save(_dataset(description="Cycled at 25 degC."), tmp_path))["dataset"]

    assert (body["published_at"], body["created_at"]) == (PUBLISHED, PUBLISHED)


def test_the_save_time_value_an_earlier_release_wrote_is_not_kept(tmp_path: Path) -> None:
    """0.8.0 gave a saved dataset its ``created_at`` as ``published_at``, which no publication set."""
    _published(_save(_dataset(), tmp_path), created_at=PUBLISHED)

    again = _save(_dataset(), tmp_path)

    assert again["content_changed"] is True and "published_at" not in _record(again)["dataset"]


def test_a_dataset_that_states_a_publication_time_replaces_the_saved_one(tmp_path: Path) -> None:
    _published(_save(_dataset(created_at=CREATED), tmp_path))

    body = _record(_save(_dataset(created_at=CREATED, published_at=PUBLISHED + 3600), tmp_path))["dataset"]

    assert body["published_at"] == PUBLISHED + 3600


def test_a_canonical_record_is_saved_as_it_is_given(tmp_path: Path) -> None:
    first = _save(_dataset(created_at=CREATED), tmp_path)
    undated = _record(first)
    _published(first)

    again = _save(copy.deepcopy(undated), tmp_path)

    assert again["content_changed"] is True and "published_at" not in _record(again)["dataset"]


# ── The time a Zenodo publish reports ─────────────────────────────────────────

CALLED_AT = calendar.timegm((2026, 11, 2, 14, 30, 5))  # 2026-11-02T14:30:05Z


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ({"doi": "10.5281/zenodo.7"}, CALLED_AT),
        ({"metadata": {"publication_date": "2026-11-02"}}, CALLED_AT),
        # Zenodo's calendar may already be on the next day.
        ({"metadata": {"publication_date": "2026-11-03"}}, CALLED_AT),
        ({"metadata": {"publication_date": "2025-06-16"}}, PUBLISHED),
        ({"metadata": {"publication_date": "2025"}}, CALLED_AT),
        ({"metadata": {"publication_date": None}}, CALLED_AT),
        (None, CALLED_AT),
    ],
    ids=["no date", "the day of the call", "a later day", "an earlier day", "not a date", "null", "no answer"],
)
def test_the_publication_time_of_a_zenodo_answer(answer: object, expected: int) -> None:
    assert _zenodo_publication_time(answer, CALLED_AT) == expected
