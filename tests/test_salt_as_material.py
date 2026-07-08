"""Salts are materials: electrolyte_recipe accepts the same material() form as solvents."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.authoring import electrolyte_recipe, material  # noqa: E402
from battinfo.bundle import Salt  # noqa: E402


def test_salt_accepts_the_material_component_form() -> None:
    e = electrolyte_recipe(
        family="organic",
        solvents=[material("EC", volume_fraction={"value": 50, "unit": "%"})],
        salt=material("LiPF6", concentration={"value": 1.0, "unit": "mol/L"}),
    )
    assert isinstance(e.salt, Salt)
    assert e.salt.name == "LiPF6"
    assert e.salt.property["concentration"] == {"value": 1.0, "unit": "mol/L"}


def test_salt_material_keeps_its_materialspec_link() -> None:
    spec_iri = "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5"
    component = material("LiPF6", concentration={"value": 1.0, "unit": "mol/L"})
    component.material_spec_id = spec_iri
    e = electrolyte_recipe(family="organic", salt=component)
    assert e.salt is not None and e.salt.material_spec_id == spec_iri, (
        "the MaterialSpec -> Material link must survive — salts are materials too"
    )


def test_salt_with_molecular_formula_refuses_instead_of_dropping() -> None:
    component = material("LiPF6")
    component.molecular_formula = "LiPF6"
    with pytest.raises(ValueError, match="cation="):
        electrolyte_recipe(family="organic", salt=component)


def test_string_salt_with_concentration_still_works() -> None:
    e = electrolyte_recipe(
        family="organic", salt="LiPF6", salt_concentration={"value": 1.0, "unit": "mol/L"}
    )
    assert e.salt is not None and e.salt.name == "LiPF6"
