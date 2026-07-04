"""_to_unix_time must anchor timezone-naive inputs to UTC so a saved record's timestamps
(manufactured_at / started_at / ended_at / created_at) are reproducible across machines,
regardless of the authoring machine's local timezone."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import _to_unix_time


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
