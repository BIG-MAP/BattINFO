"""Every authoring-model field carries a Field(description=...) (beta-hardening plan 2.2).

The descriptions power help(), IDE hover, and .model_json_schema() — this gate keeps a
newly added field from shipping undocumented.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.bundle import (
    Cell,
    CellSpec,
    Dataset,
    ProvenanceInfo,
    Test,
    TestSpec,
)

MODELS = [CellSpec, Cell, Test, TestSpec, Dataset, ProvenanceInfo]

# Structural fields shared via BundleJsonModel — not part of the authoring vocabulary.
STRUCTURAL = {"kind", "schema_version"}


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_every_authoring_field_has_a_description(model) -> None:
    undocumented = sorted(
        name
        for name, info in model.model_fields.items()
        if name not in STRUCTURAL and not (info.description or "").strip()
    )
    assert not undocumented, f"{model.__name__} fields missing Field(description=...): {undocumented}"


def test_descriptions_reach_the_json_schema() -> None:
    schema = Dataset.model_json_schema()
    assert "landing page" in schema["properties"]["access_url"]["description"].lower()
