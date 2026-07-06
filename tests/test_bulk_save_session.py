"""bulk_save_session: one id->path scan per batch instead of one per record (3.4).

Correctness first: everything saved inside a session must be exactly as valid,
referenced, and findable as records saved without one. The session only changes
where lookups read from (an in-memory map kept current by each save) and skips
the per-file fsync (the batch is re-runnable, so power-loss repair is a re-run).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import api  # noqa: E402
from battinfo._record_index import active_record_cache, bulk_save_session  # noqa: E402

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def _uid(i: int) -> str:
    digits = []
    value = i + 1
    while value:
        value, rem = divmod(value, 32)
        digits.append(_ALPHABET[rem])
    return ("".join(digits) + "2m4p8t3x6nq57d9k")[:16]


def _spec_draft() -> dict:
    return {
        "uid": "7d9k2m4p8t3x6nq5",
        "manufacturer": "TestCo",
        "model": "TC-1",
        "chemistry": "Li-ion",
        "format": "cylindrical",
    }


def _instance_draft(spec_id: str, i: int) -> dict:
    return {"cell_spec_id": spec_id, "serial_number": f"SN-{i:04d}", "uid": _uid(i)}


def test_session_saves_match_unsessioned_saves(tmp_path: Path) -> None:
    plain_root = tmp_path / "plain" / "examples"
    session_root = tmp_path / "session" / "examples"

    spec_plain = api.save_cell_spec(_spec_draft(), source_root=plain_root)
    plain = [
        api.save_cell_instance(_instance_draft(spec_plain["id"], i), source_root=plain_root)
        for i in range(10)
    ]

    with bulk_save_session(session_root):
        spec_sessioned = api.save_cell_spec(_spec_draft(), source_root=session_root)
        sessioned = [
            api.save_cell_instance(_instance_draft(spec_sessioned["id"], i), source_root=session_root)
            for i in range(10)
        ]

    assert [p["status"] for p in plain] == [s["status"] for s in sessioned] == ["created"] * 10
    for p, s in zip(plain, sessioned):
        assert p["id"] == s["id"]
        assert Path(p["path"]).exists() and Path(s["path"]).exists()


def test_records_saved_inside_session_are_visible_to_reference_validation(tmp_path: Path) -> None:
    root = tmp_path / "examples"
    with bulk_save_session(root):
        spec = api.save_cell_spec(_spec_draft(), source_root=root)
        # The instance references a spec that did not exist when the session
        # started — resolvable only if each save updates the live map.
        result = api.save_cell_instance(_instance_draft(spec["id"], 1), source_root=root)
    assert result["status"] == "created"


def test_duplicate_detection_works_inside_session(tmp_path: Path) -> None:
    root = tmp_path / "examples"
    with bulk_save_session(root):
        api.save_cell_spec(_spec_draft(), source_root=root)
        with pytest.raises(ValueError, match="already exists"):
            api.save_cell_spec({**_spec_draft(), "model": "TC-1-changed"}, source_root=root)


def test_cache_is_scoped_to_its_source_root_and_lifetime(tmp_path: Path) -> None:
    root = tmp_path / "examples"
    other = tmp_path / "other"
    with bulk_save_session(root) as cache:
        assert active_record_cache(root) is cache
        assert active_record_cache(other) is None
        with bulk_save_session(root) as nested:
            assert nested is cache  # nested same-root sessions reuse the outer map
    assert active_record_cache(root) is None

    # Saves after the session ends take the uncached path and still work.
    spec = api.save_cell_spec(_spec_draft(), source_root=root)
    assert api.save_cell_instance(_instance_draft(spec["id"], 2), source_root=root)["status"] == "created"


def test_preexisting_records_are_found_by_the_session_scan(tmp_path: Path) -> None:
    root = tmp_path / "examples"
    spec = api.save_cell_spec(_spec_draft(), source_root=root)  # before the session
    with bulk_save_session(root):
        result = api.save_cell_instance(_instance_draft(spec["id"], 3), source_root=root)
        duplicate = api.save_cell_spec(
            _spec_draft(), source_root=root, duplicate_policy="return_existing"
        )
    assert result["status"] == "created"
    assert duplicate["status"] == "exists"


def test_save_batch_round_trips_through_the_session(tmp_path: Path) -> None:
    root = tmp_path / "examples"
    spec = api.save_cell_spec(_spec_draft(), source_root=root)
    staging = tmp_path / "staging"
    staging.mkdir()
    import json

    for i in range(5):
        record = api.create_cell_instance(cell_spec_id=spec["id"], uid=_uid(i), serial_number=f"B-{i}")
        (staging / f"instance-{i}.json").write_text(json.dumps(record), encoding="utf-8")

    payload = api.save_batch(source_dirs=[staging], source_root=root)
    assert payload["status"] == "ok"
    assert payload["created"] == 5
