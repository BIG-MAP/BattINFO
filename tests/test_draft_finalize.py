"""PR D: draft vs. publish-ready.

The CellSpec model is tolerant to construct (a half-filled spec is a valid draft — this is
what lets importers build it from arbitrary data and a GUI hold work-in-progress). Publish-readiness
is a POLICY applied at finalize()/is_publishable(), not baked into the field types. These tests pin
that separation, which is the foundation for folding the strict input DTOs onto the one model."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.bundle import CellSpec


def test_draft_constructs_and_is_not_publishable() -> None:
    draft = CellSpec(manufacturer="Acme")  # half-filled, no id
    assert draft.is_publishable() is False
    problems = draft.publish_readiness_problems()
    # every unset required field is reported at once (manufacturer IS set, so it is not listed)
    assert any(p.startswith("id") for p in problems)
    assert "model" in problems and "format" in problems and "chemistry" in problems
    assert "manufacturer" not in problems


def test_finalize_raises_listing_all_missing_fields() -> None:
    draft = CellSpec(manufacturer="Acme")
    with pytest.raises(ValueError, match="not publish-ready") as exc:
        draft.finalize()
    msg = str(exc.value)
    assert "model" in msg and "chemistry" in msg  # aggregated, not one-at-a-time


def test_complete_spec_is_publishable_and_finalize_returns_self() -> None:
    spec = CellSpec(
        id="https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd", name="Acme X",
        manufacturer="Acme", model="X", format="coin", chemistry="Li-ion",
    )
    assert spec.is_publishable() is True
    assert spec.finalize() is spec  # chainable: spec.finalize().to_record()
    assert "cell_spec" in spec.finalize().to_record()


def test_tolerant_import_is_serializable_but_flagged_unpublishable() -> None:
    # A record imported with an unknown chemistry (tolerant construction) must still serialize — so
    # import->save round-trips — while is_publishable() flags it for the author to complete.
    imported = CellSpec(
        id="https://w3id.org/battinfo/spec/bbbb-cccc-dddd-eeee", name="Imported",
        manufacturer="X", model="Y", format="coin",  # chemistry defaults to "unknown"
    )
    assert "cell_spec" in imported.to_record()  # serialization does not require a known chemistry
    assert imported.is_publishable() is False
    assert imported.publish_readiness_problems() == ["chemistry"]


def test_to_record_on_a_draft_raises_a_clear_draft_error() -> None:
    draft = CellSpec(manufacturer="Acme", model="X", format="coin", chemistry="Li-ion")
    with pytest.raises(ValueError, match="draft"):
        draft.to_record()  # no id yet
