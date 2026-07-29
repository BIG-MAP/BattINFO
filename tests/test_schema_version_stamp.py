"""Guard: every stamped fixture agrees with battinfo.bundle.SCHEMA_VERSION.

The example corpus and the generated web fixtures each embed record
``schema_version`` stamps. They drifted once (issue #301): 85 example records
and the docs/web gallery were left at "0.1.0" after the package moved to
"0.2.0". This test walks both trees and fails on any stamp that does not match
the single source of truth, so a stamped artifact can never fall out of step
with the package again.

Scope note: this covers the canonical corpus (``examples/``) and the
*generated* web fixtures (``web/lib/*.generated.ts``). Hand-written web source
(e.g. ``web/lib/create-model.ts``) is out of scope here — it is not a committed
fixture and is regenerated/authored elsewhere.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.bundle import SCHEMA_VERSION  # noqa: E402

_STAMP = re.compile(r'"schema_version"\s*:\s*"([^"]+)"')


def _stamped_files() -> list[Path]:
    files = sorted((ROOT / "examples").rglob("*.json"))
    files += sorted((ROOT / "web" / "lib").glob("*.generated.ts"))
    return files


@pytest.mark.parametrize("path", _stamped_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_schema_version_matches_source_of_truth(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    stamps = _STAMP.findall(text)
    bad = [s for s in stamps if s != SCHEMA_VERSION]
    assert not bad, (
        f"{path.relative_to(ROOT)} carries schema_version {sorted(set(bad))} "
        f"but battinfo.bundle.SCHEMA_VERSION is {SCHEMA_VERSION!r}. "
        "Re-stamp the fixture (regenerate generated files) so every stamped "
        "artifact agrees with the package."
    )


def test_at_least_one_stamped_fixture_scanned() -> None:
    # Cheap guard against the glob silently matching nothing (e.g. a moved tree),
    # which would make the parametrized test vacuously pass.
    assert _stamped_files(), "no stamped fixtures found under examples/ or web/lib"
