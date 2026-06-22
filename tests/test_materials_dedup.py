"""Regression tests: material extraction must not silently lose materials
(audit theme D).
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.materials import _intrinsic_property, extract_material_specs  # noqa: E402


def test_single_dict_material_group_is_not_dropped() -> None:
    # A one-material group authored as a bare dict (not a list) must still extract.
    record = {"positive_electrode": {"coating": {"component": {"active_material": {"name": "LFP"}}}}}
    specs = extract_material_specs(record)
    assert len(specs) == 1


def test_property_wrapped_in_single_element_list_is_preserved() -> None:
    out = _intrinsic_property([{"density": {"value": 2.2, "unit": "g/cm3"}}])
    assert out == {"density": {"value": 2.2, "unit": "g/cm3"}}


def test_same_name_distinct_materials_warn_not_silent() -> None:
    record = {
        "positive_electrode": {"coating": {"component": {"active_material": [
            {"name": "NMC", "molecular_formula": "LiNi0.8Mn0.1Co0.1O2"}]}}},
        "negative_electrode": {"coating": {"component": {"active_material": [
            {"name": "NMC", "molecular_formula": "LiNi0.5Mn0.3Co0.2O2"}]}}},
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        extract_material_specs(record)
    assert any("differ" in str(w.message) for w in caught)


def test_same_name_same_data_dedups_silently() -> None:
    # The intentional case ("Graphite"/"graphite" -> one spec) must stay silent.
    record = {
        "positive_electrode": {"coating": {"component": {"active_material": [{"name": "Graphite"}]}}},
        "negative_electrode": {"coating": {"component": {"active_material": [{"name": "graphite"}]}}},
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        specs = extract_material_specs(record)
    assert len(specs) == 1
    assert not any("differ" in str(w.message) for w in caught)
