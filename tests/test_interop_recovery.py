"""Interop recovery scorecard: the capability, asserted.

Confirms that every real non-canonical JSON-LD source normalizes into canonical
BattINFO records + JSON-LD, and that the generated scorecard page stays in sync
with the live scores. The scoring lives in scripts/gen_interop_recovery.py so the
docs page and these assertions cannot diverge.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_gen():
    spec = importlib.util.spec_from_file_location(
        "gen_interop_recovery", ROOT / "scripts" / "gen_interop_recovery.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses needs the module registered
    spec.loader.exec_module(module)
    return module


gen = _load_gen()

# The dimensions that must always be green: a non-canonical document that ingests,
# is shape-normalized, keeps its identity, and comes out as valid canonical
# BattINFO JSON-LD IS the capability this whole exercise is about.
CORE = ["ingest", "normalize", "identity", "canonical"]


@pytest.fixture(scope="module")
def scores():
    return gen.score_all()


def test_every_source_reaches_canonical_jsonld(scores):
    for s in scores:
        assert s.error is None, f"{s.label} failed to score: {s.error}"
        for dim in CORE:
            rating, detail = s.dims[dim]
            assert rating == gen.PASS, f"{s.label}: {dim} regressed to {rating!r} ({detail})"


def test_no_red_cells(scores):
    for s in scores:
        for dim, _ in gen.DIMENSIONS:
            rating, detail = s.dims[dim]
            assert rating != gen.FAIL, f"{s.label}: {dim} went red ({detail})"


def test_converter_family_recovers_quantities(scores):
    converter = [s for s in scores if s.family == "converter"]
    assert converter, "expected converter sources"
    for s in converter:
        assert s.dims["quantities"][0] == gen.PASS, f"{s.label}: {s.dims['quantities']}"


def test_discovery_family_recovers_component_specs(scores):
    discovery = [s for s in scores if s.family == "discovery"]
    assert discovery, "expected a discovery source"
    for s in discovery:
        assert s.dims["components"][0] == gen.PASS, f"{s.label}: {s.dims['components']}"


def test_scorecard_page_is_in_sync():
    committed = gen.OUT.read_text(encoding="utf-8")
    assert committed == gen.build(), (
        "docs/pages/interop-recovery.md is stale — regenerate with "
        "`uv run python scripts/gen_interop_recovery.py`"
    )
