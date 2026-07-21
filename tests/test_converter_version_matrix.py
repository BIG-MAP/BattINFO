"""Interop coverage: BattINFO Converter outputs across its version history.

The existing converter tests pin a couple of hand-built fixtures. This pins
*real* outputs of `convert_excel_to_jsonld` for a representative spread of the
tool's filled templates (v1.0.0 … v1.1.17) and asserts BattINFO imports each —
proving "works across converter versions over the years", not just one shape.

The key structural drift is the cell-component holder: templates ≤ v1.1.11 emit
`hasConstituent`, ≥ v1.1.15 emit `hasComponent`. Both must import.

Fixtures are committed JSON-LD (small, one coin cell each), so this test needs
no BattInfoConverter dependency — see PROVENANCE.md and
scripts/generate_converter_version_fixtures.py to regenerate them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import (  # noqa: E402
    import_converter_jsonld_record,
    import_converter_package,
)
from battinfo.transform import to_jsonld  # noqa: E402

FIXTURES = sorted((ROOT / "tests" / "fixtures" / "interop" / "converter-versions").glob("*.coincell.jsonld"))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _types(node: dict) -> list[str]:
    t = node.get("@type", [])
    return t if isinstance(t, list) else [t]


def test_fixture_set_spans_both_component_holders() -> None:
    """The pinned set must cover both the old and new converter output shapes."""
    assert len(FIXTURES) >= 6, "expected the full version spread to be committed"
    holders = {("hasComponent" if "hasComponent" in _load(p) else "hasConstituent") for p in FIXTURES}
    assert holders == {"hasConstituent", "hasComponent"}, f"only saw {holders}"


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name.replace(".coincell.jsonld", ""))
def test_converter_version_imports_to_valid_descriptor(fixture: Path) -> None:
    result = import_converter_jsonld_record(_load(fixture))
    spec = result.record["specification"]
    # core descriptor fields the importer must recover regardless of version
    assert spec["format"] == "coin"
    assert spec["chemistry"]
    assert spec["model"]
    assert spec["positive_electrode_basis"]
    assert spec["negative_electrode_basis"]
    assert result.record["instances"], "expected at least one imported instance"


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name.replace(".coincell.jsonld", ""))
def test_converter_version_round_trips_both_jsonld_targets(fixture: Path) -> None:
    record = import_converter_jsonld_record(_load(fixture)).record
    # domain-battery: canonical descriptor graph
    db = to_jsonld(record, target="domain-battery")
    assert "BatteryCellSpecification" in _types(db["@graph"][0])
    # converter-compatible: back out to a CoinCell
    cc = to_jsonld(record, target="converter-compatible")
    assert cc["@type"] == "CoinCell"


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name.replace(".coincell.jsonld", ""))
def test_converter_version_builds_linked_package(fixture: Path) -> None:
    package = import_converter_package(_load(fixture))
    assert package.specification.id == package.cell_spec.id
    assert package.cell_instance is not None
    assert package.cell_instance.cell_spec_id == package.cell_spec.id
    # Default import does not extract component specs.
    assert package.component_records() == []


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name.replace(".coincell.jsonld", ""))
def test_converter_components_extract_to_valid_specs(fixture: Path) -> None:
    """components=True recovers the component tree as standalone canonical specs."""
    from battinfo.validate import validate_record

    package = import_converter_package(_load(fixture), components=True)
    specs = package.component_records()
    assert specs, "expected recovered component specs"
    assert package.electrode_specs, "expected at least one electrode spec"
    assert package.material_specs, "expected active-material specs"
    for record in specs:
        assert validate_record(record).ok, record
        to_jsonld(record, target="domain-battery")  # raises on unmapped @type
    # The recovered specs are linked from the cell spec.
    linked = {
        package.cell_spec.positive_electrode_spec_id,
        package.cell_spec.negative_electrode_spec_id,
        package.cell_spec.electrolyte_spec_id,
    }
    assert any(linked), "expected the cell spec to reference a recovered component"
