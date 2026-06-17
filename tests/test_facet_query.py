"""Tests for facet-based test-spec querying (Phase 4): finding protocols by what
their method does (step modes, C-rates, CV holds, tags), not just identity."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import query_test_specs  # noqa: E402
from battinfo.bundle import TestSpec  # noqa: E402

UID = "aaaa-bbbb-cccc"


def _write_spec(directory: Path, tail: str, name: str, kind: str,
                experiment: list[str], cycles=None) -> None:
    spec = TestSpec(
        id=f"https://w3id.org/battinfo/spec/{UID}-{tail}", name=name, test_kind=kind,
        experiment=experiment, cycles=cycles,
        source={"type": "manual", "retrieved_at": 1781589239},
    )
    (directory / f"test-protocol-{UID}-{tail}.json").write_text(
        json.dumps(spec.to_record()), encoding="utf-8")


def _make_dir(tmp_path: Path) -> Path:
    d = tmp_path / "test-protocol"
    d.mkdir()
    _write_spec(d, "1n5v", "Formation CCCV", "formation",
                ["Charge at 1 C until 4.2 V", "Hold at 4.2 V until C/50",
                 "Discharge at 1 C until 2.5 V"], cycles=3)
    _write_spec(d, "2n5v", "Simple CC discharge", "capacity_check",
                ["Discharge at 0.5 C until 2.5 V"])
    return d


def test_query_by_cv_hold(tmp_path: Path) -> None:
    d = _make_dir(tmp_path)
    cv = query_test_specs(directory=d, has_cv_hold=True)
    assert [r["name"] for r in cv] == ["Formation CCCV"]
    no_cv = query_test_specs(directory=d, has_cv_hold=False)
    assert [r["name"] for r in no_cv] == ["Simple CC discharge"]


def test_query_by_c_rate_and_mode(tmp_path: Path) -> None:
    d = _make_dir(tmp_path)
    assert len(query_test_specs(directory=d, c_rate=0.5)) == 1
    assert len(query_test_specs(directory=d, c_rate=1.0)) == 1
    # A group (cycled) method only appears in the formation spec.
    assert [r["name"] for r in query_test_specs(directory=d, mode="group")] == ["Formation CCCV"]


def test_query_combines_facet_and_identity_filters(tmp_path: Path) -> None:
    d = _make_dir(tmp_path)
    hits = query_test_specs(directory=d, kind="formation", has_cv_hold=True, direction="charge")
    assert [r["name"] for r in hits] == ["Formation CCCV"]
    assert query_test_specs(directory=d, kind="capacity_check", has_cv_hold=True) == []
