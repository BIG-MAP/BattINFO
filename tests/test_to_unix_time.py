"""_to_unix_time must anchor timezone-naive inputs to UTC so a saved record's timestamps
(manufactured_at / started_at / ended_at / created_at) are reproducible across machines,
regardless of the authoring machine's local timezone; it must never raise, and it must
reject values (bool, NaN, short digit strings) that only look like timestamps."""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import _resolved_time, _to_unix_time


def test_bare_date_parses_as_utc_midnight() -> None:
    # 2022-01-15 00:00:00 UTC. Pinned to an absolute value (not recomputed) so a
    # local-time regression fails here instead of silently drifting per machine.
    assert _to_unix_time("2022-01-15") == 1642204800
    assert _to_unix_time("2022-02-01") == 1643673600


def test_naive_datetime_parses_as_utc() -> None:
    assert _to_unix_time("2022-01-15T00:00:00") == 1642204800


def test_explicit_offset_is_respected() -> None:
    # An explicit offset must not be overridden by the UTC anchor.
    assert _to_unix_time("2022-01-15T00:00:00+01:00") == 1642204800 - 3600
    assert _to_unix_time("2022-01-15T00:00:00Z") == 1642204800


def test_passthrough_and_empty() -> None:
    assert _to_unix_time(1642204800) == 1642204800
    assert _to_unix_time("1642204800") == 1642204800
    assert _to_unix_time("") is None
    assert _to_unix_time("not-a-date") is None


def test_datetime_objects_convert() -> None:
    aware = datetime(2022, 1, 15, tzinfo=timezone.utc)
    assert _to_unix_time(aware) == 1642204800
    # Naive datetimes anchor to UTC, same as naive ISO strings.
    assert _to_unix_time(datetime(2022, 1, 15)) == 1642204800


def test_date_objects_convert_to_utc_midnight() -> None:
    assert _to_unix_time(date(2022, 1, 15)) == 1642204800


def test_epoch_zero_survives() -> None:
    assert _to_unix_time(0) == 0
    assert _to_unix_time(0.0) == 0
    # A present epoch-0 must not be replaced by the default at the call site.
    assert _resolved_time("created_at", 0, 999) == 0


def test_bool_is_not_a_timestamp() -> None:
    assert _to_unix_time(True) is None
    assert _to_unix_time(False) is None


def test_never_raises_on_garbage_floats_and_digits() -> None:
    assert _to_unix_time(float("nan")) is None
    assert _to_unix_time(float("inf")) is None
    assert _to_unix_time(float("-inf")) is None
    # str.isdigit() accepts non-ASCII digits that int() rejects.
    assert _to_unix_time("²" * 9) is None


def test_short_digit_strings_are_ambiguous() -> None:
    # "20240101" reads as a calendar date, not epoch second 20,240,101.
    assert _to_unix_time("20240101") is None
    assert _to_unix_time("0") is None
    # 9+ digit strings are unambiguous Unix seconds.
    assert _to_unix_time("164220480") == 164220480


def test_resolved_time_distinguishes_absent_from_unparseable() -> None:
    assert _resolved_time("created_at", None, 123) == 123
    converted = _resolved_time("created_at", "2022-01-15", 123)
    assert converted == 1642204800
    with pytest.raises(ValueError, match="created_at"):
        _resolved_time("created_at", "not-a-date", 123)
    with pytest.raises(ValueError, match="modified_at"):
        _resolved_time("modified_at", "20240101", 123)
