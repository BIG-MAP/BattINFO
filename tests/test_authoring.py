"""Tests for battinfo.authoring helper functions.

Covers every exported function in authoring.py:
  properties, construction, source, material, bom,
  electrode, electrolyte_recipe, separator_spec, cell_description
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest

from battinfo.authoring import (
    bom,
    cell_description,
    construction,
    electrode,
    electrolyte_recipe,
    material,
    properties,
    separator_spec,
    source,
)
from battinfo.bundle import (
    BillOfMaterials,
    CellConstruction,
    CellSpecification,
    Electrode,
    Electrolyte,
    MaterialComponent,
    PropertySet,
    ProvenanceInfo,
    Salt,
    Separator,
)

# ---------------------------------------------------------------------------
# properties()
# ---------------------------------------------------------------------------

class TestProperties:
    def test_returns_property_set(self):
        ps = properties(nominal_capacity={"value": 2.5, "unit": "Ah"})
        assert isinstance(ps, PropertySet)

    def test_empty_call_returns_empty_property_set(self):
        ps = properties()
        assert isinstance(ps, PropertySet)

    def test_multiple_properties(self):
        ps = properties(
            nominal_capacity={"value": 2.5, "unit": "Ah"},
            nominal_voltage={"value": 3.2, "unit": "V"},
        )
        assert isinstance(ps, PropertySet)
        assert ps.nominal_capacity == {"value": 2.5, "unit": "Ah"}
        assert ps.nominal_voltage == {"value": 3.2, "unit": "V"}


# ---------------------------------------------------------------------------
# construction()
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_returns_cell_construction(self):
        c = construction()
        assert isinstance(c, CellConstruction)

    def test_all_none_by_default(self):
        c = construction()
        assert c.assembly_type is None
        assert c.layering is None
        assert c.layer_count is None
        assert c.comment is None

    def test_wound_construction(self):
        c = construction(assembly_type="wound", layering="jelly-roll", layer_count=32)
        assert c.assembly_type == "wound"
        assert c.layering == "jelly-roll"
        assert c.layer_count == 32

    def test_stacked_construction_with_comment(self):
        c = construction(assembly_type="stacked", comment="Single-layer pouch")
        assert c.assembly_type == "stacked"
        assert c.comment == "Single-layer pouch"


# ---------------------------------------------------------------------------
# source()
# ---------------------------------------------------------------------------

class TestSource:
    def test_returns_provenance_info(self):
        s = source()
        assert isinstance(s, ProvenanceInfo)

    def test_all_none_by_default(self):
        s = source()
        assert s.type is None
        assert s.url is None
        assert s.citation is None

    def test_datasheet_source(self):
        s = source(
            type="datasheet",
            name="A123 ANR26650M1-B datasheet",
            url="https://example.com/datasheet.pdf",
            retrieved_at=1746230400,
        )
        assert s.type == "datasheet"
        assert s.name == "A123 ANR26650M1-B datasheet"
        assert s.retrieved_at == 1746230400

    def test_citation_doi(self):
        s = source(citation="https://doi.org/10.1234/test")
        assert s.citation == "https://doi.org/10.1234/test"

    def test_with_file_hash(self):
        s = source(file="battery.json", file_hash="abc123")
        assert s.file == "battery.json"
        assert s.file_hash == "abc123"

    def test_with_curated_by(self):
        s = source(curated_by="Simon Clark")
        assert s.curated_by == "Simon Clark"


# ---------------------------------------------------------------------------
# material()
# ---------------------------------------------------------------------------

class TestMaterial:
    def test_returns_material_component(self):
        m = material("LFP")
        assert isinstance(m, MaterialComponent)

    def test_name_is_set(self):
        m = material("Graphite")
        assert m.name == "Graphite"

    def test_named_properties_become_property_set(self):
        m = material("LFP", mass_fraction={"value": 90, "unit": "%"})
        # PropertySet fields are serialised to dict by Pydantic on model construction
        assert m.property["mass_fraction"] == {"value": 90, "unit": "%"}

    def test_explicit_property_set(self):
        ps = properties(density={"value": 3.6, "unit": "g/cm3"})
        m = material("LFP", property=ps)
        assert m.property["density"] == {"value": 3.6, "unit": "g/cm3"}

    def test_comment_is_preserved(self):
        m = material("Carbon black", comment="Conductive additive")
        assert m.comment == "Conductive additive"

    def test_name_is_required(self):
        with pytest.raises(TypeError):
            material()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# bom()
# ---------------------------------------------------------------------------

class TestBom:
    def test_returns_bill_of_materials(self):
        b = bom(active_material="LFP")
        assert isinstance(b, BillOfMaterials)

    def test_string_active_material_becomes_component(self):
        b = bom(active_material="LFP")
        assert len(b.active_material) == 1
        assert b.active_material[0].name == "LFP"

    def test_list_of_strings(self):
        b = bom(active_material=["NMC", "LFP"])
        assert len(b.active_material) == 2

    def test_material_component_passthrough(self):
        m = material("PVDF")
        b = bom(binder=m)
        assert b.binder[0] is m

    def test_all_components_empty_by_default(self):
        b = bom()
        assert b.active_material == []
        assert b.binder == []
        assert b.additive == []

    def test_full_composition(self):
        b = bom(
            active_material=material("LFP", mass_fraction={"value": 90, "unit": "%"}),
            binder="PVDF",
            additive="Carbon black",
        )
        assert b.active_material[0].name == "LFP"
        assert b.binder[0].name == "PVDF"
        assert b.additive[0].name == "Carbon black"


# ---------------------------------------------------------------------------
# electrode()
# ---------------------------------------------------------------------------

class TestElectrode:
    def _lfp_bom(self) -> BillOfMaterials:
        return bom(active_material="LFP", binder="PVDF", additive="Carbon black")

    def test_returns_electrode(self):
        e = electrode(bom=self._lfp_bom())
        assert isinstance(e, Electrode)

    def test_bom_is_required(self):
        with pytest.raises(TypeError):
            electrode()  # type: ignore[call-arg]

    def test_loading_merges_into_coating_properties(self):
        loading = {"value": 12.5, "unit": "mg/cm2"}
        e = electrode(bom=self._lfp_bom(), loading=loading)
        assert e.coating.property["loading"] == loading

    def test_current_collector_created_from_name(self):
        e = electrode(bom=self._lfp_bom(), current_collector="Aluminium foil")
        assert e.current_collector is not None
        assert e.current_collector.name == "Aluminium foil"

    def test_no_current_collector_when_not_provided(self):
        e = electrode(bom=self._lfp_bom())
        assert e.current_collector is None

    def test_current_collector_thickness(self):
        thickness = {"value": 16.0, "unit": "mm"}
        e = electrode(
            bom=self._lfp_bom(),
            current_collector="Aluminium foil",
            current_collector_thickness=thickness,
        )
        assert e.current_collector.property["thickness"] == thickness

    def test_coating_comment(self):
        e = electrode(bom=self._lfp_bom(), coating_comment="NMP-cast")
        assert e.coating.comment == "NMP-cast"

    def test_electrode_level_comment(self):
        e = electrode(bom=self._lfp_bom(), comment="Positive electrode")
        assert e.comment == "Positive electrode"

    def test_calendered_density_merges_into_coating(self):
        density = {"value": 2.4, "unit": "g/cm3"}
        e = electrode(bom=self._lfp_bom(), calendered_density=density)
        assert e.coating.property["calendered_density"] == density


# ---------------------------------------------------------------------------
# electrolyte_recipe()
# ---------------------------------------------------------------------------

class TestElectrolyteRecipe:
    def test_returns_electrolyte(self):
        e = electrolyte_recipe(family="organic")
        assert isinstance(e, Electrolyte)

    def test_family_is_required(self):
        with pytest.raises(TypeError):
            electrolyte_recipe()  # type: ignore[call-arg]

    def test_family_is_set(self):
        e = electrolyte_recipe(family="solid")
        assert e.family == "solid"

    def test_string_salt_creates_salt_object(self):
        e = electrolyte_recipe(
            family="organic",
            salt="LiPF6",
            salt_concentration={"value": 1.0, "unit": "mol/L"},
        )
        assert isinstance(e.salt, Salt)
        assert e.salt.name == "LiPF6"
        assert e.salt.property["concentration"] == {"value": 1.0, "unit": "mol/L"}

    def test_salt_object_passthrough(self):
        s = Salt(name="LiFSI")
        e = electrolyte_recipe(family="organic", salt=s)
        assert e.salt is s

    def test_no_salt(self):
        e = electrolyte_recipe(family="aqueous")
        assert e.salt is None

    def test_solvents_become_mixture(self):
        e = electrolyte_recipe(family="organic", solvents=["EC", "DMC"])
        assert e.solvent_mixture is not None
        assert len(e.solvent_mixture.component) == 2

    def test_no_solvents_gives_no_mixture(self):
        e = electrolyte_recipe(family="solid")
        assert e.solvent_mixture is None

    def test_additives(self):
        e = electrolyte_recipe(family="organic", additives="VC")
        assert len(e.additive) == 1
        assert e.additive[0].name == "VC"

    def test_full_lp30_recipe(self):
        e = electrolyte_recipe(
            family="organic",
            solvents=[
                material("EC", volume_fraction={"value": 50, "unit": "%"}),
                material("DMC", volume_fraction={"value": 50, "unit": "%"}),
            ],
            salt="LiPF6",
            salt_concentration={"value": 1.0, "unit": "mol/L"},
            comment="LP30",
        )
        assert e.family == "organic"
        assert e.salt.name == "LiPF6"
        assert len(e.solvent_mixture.component) == 2
        assert e.comment == "LP30"


# ---------------------------------------------------------------------------
# separator_spec()
# ---------------------------------------------------------------------------

class TestSeparatorSpec:
    def test_returns_separator(self):
        s = separator_spec(material="polypropylene")
        assert isinstance(s, Separator)

    def test_material_is_required(self):
        with pytest.raises(TypeError):
            separator_spec()  # type: ignore[call-arg]

    def test_material_is_set(self):
        s = separator_spec(material="polyethylene")
        assert s.material == "polyethylene"

    def test_thickness_merges_into_properties(self):
        thickness = {"value": 25.0, "unit": "mm"}
        s = separator_spec(material="polypropylene", thickness=thickness)
        assert s.property["thickness"] == thickness

    def test_explicit_properties(self):
        ps = properties(porosity={"value": 41, "unit": "%"})
        s = separator_spec(material="polypropylene", properties=ps)
        assert s.property["porosity"] == {"value": 41, "unit": "%"}

    def test_thickness_and_properties_merged(self):
        ps = properties(porosity={"value": 41, "unit": "%"})
        thickness = {"value": 25.0, "unit": "mm"}
        s = separator_spec(material="polypropylene", thickness=thickness, properties=ps)
        assert s.property["thickness"] == thickness
        assert s.property["porosity"] == {"value": 41, "unit": "%"}

    def test_comment(self):
        s = separator_spec(material="glass fibre", comment="Whatman GF/A")
        assert s.comment == "Whatman GF/A"


# ---------------------------------------------------------------------------
# cell_description()
# ---------------------------------------------------------------------------

_CELL_ID = "https://w3id.org/battinfo/cell/1234-5678-abcd-efgh"


class TestCellDescription:
    def _minimal(self) -> CellSpecification:
        return cell_description(
            id=_CELL_ID,
            manufacturer="Acme",
            model="XR-2032",
            format="coin",
            chemistry="li-primary",
        )

    def test_returns_cell_specification(self):
        spec = self._minimal()
        assert isinstance(spec, CellSpecification)

    def test_required_fields_set(self):
        spec = self._minimal()
        assert spec.id == _CELL_ID
        assert spec.manufacturer == "Acme"
        assert spec.model == "XR-2032"
        assert spec.format == "coin"
        assert spec.chemistry == "li-primary"

    def test_optional_fields_have_defaults(self):
        spec = self._minimal()
        assert spec.positive_electrode is None
        assert spec.negative_electrode is None
        assert spec.electrolyte is None
        assert spec.separator is None

    def test_electrode_basis_fields(self):
        spec = cell_description(
            id=_CELL_ID,
            manufacturer="Acme",
            model="XR-18650",
            format="cylindrical",
            chemistry="li-ion",
            positive_electrode_basis="lfp",
            negative_electrode_basis="graphite",
        )
        assert spec.positive_electrode_basis == "lfp"
        assert spec.negative_electrode_basis == "graphite"

    def test_size_code(self):
        spec = cell_description(
            id=_CELL_ID, manufacturer="A", model="B", format="cylindrical",
            chemistry="li-ion", size_code="R18650",
        )
        assert spec.size_code == "R18650"

    def test_string_comment_becomes_list(self):
        spec = cell_description(
            id=_CELL_ID, manufacturer="A", model="B",
            format="coin", chemistry="li-primary",
            comment="Research cell",
        )
        assert spec.comment == ["Research cell"]

    def test_list_comment_preserved(self):
        spec = cell_description(
            id=_CELL_ID, manufacturer="A", model="B",
            format="coin", chemistry="li-primary",
            comment=["Note 1", "Note 2"],
        )
        assert spec.comment == ["Note 1", "Note 2"]

    def test_string_specification_comment_becomes_list(self):
        spec = cell_description(
            id=_CELL_ID, manufacturer="A", model="B",
            format="coin", chemistry="li-primary",
            specification_comment="Spec note",
        )
        assert spec.specification_comment == ["Spec note"]

    def test_with_all_components(self):
        pos = electrode(bom=bom(active_material="LFP"))
        neg = electrode(bom=bom(active_material="Graphite"))
        elyte = electrolyte_recipe(family="organic", salt="LiPF6")
        sep = separator_spec(material="polypropylene")
        src = source(type="datasheet")

        spec = cell_description(
            id=_CELL_ID,
            manufacturer="Acme",
            model="LFP-18650",
            format="cylindrical",
            chemistry="li-ion",
            positive_electrode_basis="lfp",
            negative_electrode_basis="graphite",
            positive_electrode=pos,
            negative_electrode=neg,
            electrolyte=elyte,
            separator=sep,
            source=src,
        )
        assert spec.positive_electrode is pos
        assert spec.negative_electrode is neg
        assert spec.electrolyte is elyte
        assert spec.separator is sep
        assert spec.source is src

    def test_missing_required_id_raises(self):
        with pytest.raises(TypeError):
            cell_description(
                manufacturer="A", model="B", format="coin", chemistry="li-primary"
            )  # type: ignore[call-arg]
