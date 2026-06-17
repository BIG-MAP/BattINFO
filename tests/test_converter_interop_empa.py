"""Tests covering BattINFO Converter import for both known document generations.

Generation A: v1.1.4 / CoinCellSchema v1.1.7
  - @graph wrapper at root
  - BatteryTest → hasTestObject → CoinCell
  - schema:productID is a list [lab_id, empa__ccidXXXXXX]
  - schema:dateCreated in DD/MM/YY format
  - hasConstituent dict for hardware (Spring/Spacer)
  - hasOutput with BatteryTestResult + dcat:Dataset types
  - dcat:accessURL for Zenodo landing page
  - NMC active material with rdfs:comment, no @type

Generation B: v3.2.0 / CoinCellSchema v1.1.17
  - BatteryTest at root (no @graph)
  - schema:productID is a single string
  - schema:dateCreated in ISO 8601
  - hasComponent list for hardware
  - hasOutput plain object with dcat:distribution list
  - NMC active material with rdfs:comment, no @type
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest

from battinfo import (  # noqa: E402
    batch_import_converter_directory,
    import_converter_jsonld_record,
    import_dataset_record,
)
from battinfo.validate import validate_json  # noqa: E402

# ---------------------------------------------------------------------------
# Minimal inline fixtures — representative of each generation
# ---------------------------------------------------------------------------

def _gen_a_fixture() -> dict:
    """Generation A: v1.1.4 / CoinCellSchema 1.1.7 (Dataset-rocrate format)."""
    return {
        "@context": [
            "https://w3id.org/emmo/domain/battery/context",
            {
                "schema": "https://schema.org",
                "emmo": "https://w3id.org/emmo#",
                "echem": "https://w3id.org/emmo/domain/electrochemistry#",
                "unit": "https://qudt.org/vocab/unit/",
                "rdfs": "https://www.w3.org/TR/rdf-schema/#ch_comment",
            },
        ],
        "@graph": [
            {
                "@type": "BatteryTest",
                "hasTestObject": {
                    "@type": "CoinCell",
                    "schema:version": "1.1.7",
                    "schema:productID": ["241211_svfe_gen19_01", "empa__ccid000037"],
                    "schema:dateCreated": "11/12/24",
                    "schema:creator": {
                        "@type": "schema:Person",
                        "@id": "https://orcid.org/0009-0004-4673-7806",
                        "schema:name": "Enea Svaluto-Ferro",
                    },
                    "schema:manufacturer": {
                        "@type": "schema:Organization",
                        "@id": "https://www.wikidata.org/wiki/Q683116",
                        "schema:name": "Empa",
                    },
                    "rdfs:comment": [
                        "BattINFO Converter version: 1.1.4",
                        "BattINFO CoinCellSchema version: 1.1.7",
                        "Project: Battery2030+/PREMISE",
                        "Assembled manually or by robot: robot",
                        "Cell assembly sequence: CellCan, NegativeElectrode, Separator, 100.0 uL Electrolyte, PositiveElectrode, 1.0 mm Spacer, Spring, CellLid",
                    ],
                    "hasPositiveElectrode": {
                        "@type": "Electrode",
                        "hasCurrentCollector": {
                            "@type": ["CurrentCollector", "Aluminium"],
                            "hasMeasuredProperty": {
                                "@type": "Thickness",
                                "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 15},
                                "hasMeasurementUnit": "emmo:MicroMetre",
                            },
                        },
                        "hasCoating": {
                            "@type": "ElectrodeCoating",
                            "hasActiveMaterial": {
                                "rdfs:comment": "LithiumNickelCobaltManganeseOxide",
                                "molecularFormula": {"rdfs:comment": "Ni0.83Mn0.06Co0.11O2"},
                                "hasMeasuredProperty": [
                                    {
                                        "@type": "MassFraction",
                                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 96},
                                        "hasMeasurementUnit": "unit:PERCENT",
                                    },
                                    {
                                        "@type": "MassLoading",
                                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 4.94},
                                        "hasMeasurementUnit": "unit:MilliGM-PER-CentiM2",
                                    },
                                ],
                            },
                            "hasBinder": {"@type": ["Binder", "PolyvinylideneFluoride"]},
                            "hasConductiveAdditive": {"@type": ["ConductiveAdditive", "CarbonBlack"]},
                            "hasMeasuredProperty": [
                                {
                                    "@type": "CalenderedCoatingThickness",
                                    "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 20},
                                    "hasMeasurementUnit": "emmo:MicroMetre",
                                },
                            ],
                        },
                        "hasMeasuredProperty": [
                            {
                                "@type": "RatedCapacity",
                                "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 1.0},
                                "hasMeasurementUnit": "emmo:MilliAmpereHourPerSquareCentiMetre",
                            },
                            {
                                "@type": "Diameter",
                                "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 14},
                                "hasMeasurementUnit": "unit:MilliM",
                            },
                        ],
                    },
                    "hasNegativeElectrode": {
                        "@type": "Electrode",
                        "hasCurrentCollector": {
                            "@type": ["CurrentCollector", "Copper"],
                            "hasMeasuredProperty": {
                                "@type": "Thickness",
                                "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 10},
                                "hasMeasurementUnit": "emmo:MicroMetre",
                            },
                        },
                        "hasCoating": {
                            "@type": "ElectrodeCoating",
                            "hasActiveMaterial": {
                                "@type": "Graphite",
                                "hasMeasuredProperty": [
                                    {
                                        "@type": "MassFraction",
                                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 95},
                                        "hasMeasurementUnit": "unit:PERCENT",
                                    },
                                    {
                                        "@type": "MassLoading",
                                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 3.58},
                                        "hasMeasurementUnit": "unit:MilliGM-PER-CentiM2",
                                    },
                                ],
                            },
                        },
                    },
                    "hasElectrolyte": {
                        "@type": "OrganicElectrolyte",
                        "hasSolvent": {
                            "@type": "Solvent",
                            "hasConstituent": [
                                {
                                    "@type": "EthyleneCarbonate",
                                    "hasMeasuredProperty": {
                                        "@type": "VolumeFraction",
                                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 30},
                                        "hasMeasurementUnit": "unit:PERCENT",
                                    },
                                },
                                {
                                    "@type": "EthylMethylCarbonate",
                                    "hasMeasuredProperty": {
                                        "@type": "VolumeFraction",
                                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 70},
                                        "hasMeasurementUnit": "unit:PERCENT",
                                    },
                                },
                            ],
                        },
                        "hasSolute": {
                            "@type": "Solute",
                            "hasConstituent": {
                                "@type": "LithiumHexafluorophosphate",
                                "hasMeasuredProperty": {
                                    "@type": "AmountConcentration",
                                    "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 1},
                                    "hasMeasurementUnit": "unit:MOL-PER-L",
                                },
                            },
                            "hasAdditive": {
                                "@type": "Additive",
                                "hasConstituent": {
                                    "@type": "FluoroethyleneCarbonate",
                                    "hasMeasuredProperty": {
                                        "@type": "AmountConcentration",
                                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 0.289},
                                        "hasMeasurementUnit": "unit:MOL-PER-L",
                                    },
                                },
                            },
                        },
                    },
                    "hasSeparator": {
                        "@type": ["Separator", "GlassFibreSeparator"],
                        "hasMeasuredProperty": [
                            {
                                "@type": "Thickness",
                                "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 675},
                                "hasMeasurementUnit": "emmo:MicroMetre",
                            },
                        ],
                        "schema:manufacturer": {"@type": "schema:Organization", "schema:name": "Whatman"},
                        "schema:productID": "GF/D 1823-110",
                    },
                    "hasCase": {
                        "@type": "R2032",
                        "schema:productID": "2032, SUS316L",
                        "schema:manufacturer": {"@type": "schema:Organization", "schema:name": "Hosen"},
                    },
                    "hasConstituent": {
                        "Spring": {
                            "@type": "Spring",
                            "hasMeasuredProperty": [
                                {
                                    "@type": "Diameter",
                                    "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 15},
                                    "hasMeasurementUnit": "unit:MilliM",
                                },
                                {
                                    "@type": "Thickness",
                                    "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 1.4},
                                    "hasMeasurementUnit": "unit:MilliM",
                                },
                            ],
                        },
                        "Spacer": {
                            "@type": "Spacer",
                            "hasMeasuredProperty": [
                                {
                                    "@type": "Thickness",
                                    "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 1},
                                    "hasMeasurementUnit": "unit:MilliM",
                                },
                            ],
                        },
                    },
                },
                "hasOutput": {
                    "@type": ["BatteryTestResult", "dcat:Dataset"],
                    "dc:title": "Cycling data of Empa coin cell 000037",
                    "dc:description": "Cycling data of Empa coin cell 000037",
                    "dc:license": "https://creativecommons.org/licenses/by/4.0/",
                    "dc:issued": "2025-06-16",
                    "dcat:accessURL": "https://doi.org/10.5281/zenodo.15481956",
                    "schema:citation": "Svaluto-Ferro et al., Batteries & Supercaps, 2025, https://doi.org/10.1002/batt.202500155",
                    "schema:associatedMedia": {
                        "@id": "https://doi.org/10.1002/batt.202500155",
                        "rdfs:label": ["Fig. 3b"],
                    },
                    "dc:creator": [
                        {
                            "@type": "schema:Person",
                            "@id": "https://orcid.org/0009-0004-4673-7806",
                            "schema:name": "Enea Svaluto-Ferro",
                            "schema:affiliation": {
                                "@id": "https://www.wikidata.org/wiki/Q683116",
                                "schema:name": "Empa",
                            },
                        },
                    ],
                    "dcat:distribution": [
                        {
                            "@id": "https://doi.org/10.5281/zenodo.15481956#empa__ccid000037/empa__ccid000037.bdf.csv",
                            "@type": "dcat:Distribution",
                            "dcat:mediaType": "text/csv",
                        },
                        {
                            "@id": "https://doi.org/10.5281/zenodo.15481956#empa__ccid000037/empa__ccid000037.bdf.parquet",
                            "@type": "dcat:Distribution",
                            "dcat:mediaType": "application/vnd.apache.parquet",
                        },
                    ],
                },
            }
        ],
    }


def _gen_b_fixture() -> dict:
    """Generation B: v3.2.0 / CoinCellSchema 1.1.17 (kiye format)."""
    return {
        "@context": [
            "https://w3id.org/emmo/domain/battery/context",
            {
                "schema": "https://schema.org/",
                "emmo": "https://w3id.org/emmo#",
                "echem": "https://w3id.org/emmo/domain/electrochemistry#",
                "unit": "https://qudt.org/vocab/unit/",
                "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            },
        ],
        "@type": "BatteryTest",
        "hasTestObject": {
            "@type": "CoinCell",
            "schema:version": "1.1.17",
            "schema:productID": "empa__ccid001583",
            "schema:dateCreated": "2024-03-27",
            "schema:creator": {
                "@type": "schema:Person",
                "@id": "https://orcid.org/0000-0003-3024-6370",
                "schema:name": "YeonJu Kim",
            },
            "schema:manufacturer": {
                "@type": "schema:Organization",
                "@id": "https://www.wikidata.org/wiki/Q683116",
                "schema:name": "Empa",
            },
            "rdfs:comment": [
                "BattINFO Converter version: 3.2.0",
                "BattINFO CoinCellSchema version: 1.1.17",
                "Project: PVD4LIB",
                "Assembled manually or by robot: manually",
                "Cell assembly sequence: CellLid, 0.5 mm Spacer, NegativeElectrode, 20 uL Electrolyte, Separator, 20 uL Electrolyte, PositiveElectrode, 1.0 mm Spacer, Spring, CellCan",
            ],
            "hasPositiveElectrode": {
                "@type": "Electrode",
                "hasCurrentCollector": {
                    "@type": ["CurrentCollector", "Aluminium"],
                    "hasMeasuredProperty": {
                        "@type": "Thickness",
                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 15},
                        "hasMeasurementUnit": "emmo:MicroMetre",
                    },
                    "schema:manufacturer": {"@type": "schema:Organization", "schema:name": "MTI"},
                },
                "hasCoating": {
                    "@type": "ElectrodeCoating",
                    "hasActiveMaterial": {
                        "rdfs:comment": "LithiumNickelCobaltManganeseOxide",
                        "molecularFormula": {"rdfs:comment": "LiNi0.8Co0.1Mn0.1O2"},
                        "hasMeasuredProperty": [
                            {
                                "@type": "MassFraction",
                                "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 94},
                                "hasMeasurementUnit": "unit:PERCENT",
                            },
                            {
                                "@type": "MassLoading",
                                "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 3.777},
                                "hasMeasurementUnit": "unit:MilliGM-PER-CentiM2",
                            },
                        ],
                        "schema:manufacturer": {"@type": "schema:Organization", "schema:name": "Gelon"},
                        "schema:productID": "S800",
                    },
                    "hasBinder": {
                        "@type": ["Binder", "PolyvinylideneFluoride"],
                        "hasMeasuredProperty": {
                            "@type": "MassFraction",
                            "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 3},
                            "hasMeasurementUnit": "unit:PERCENT",
                        },
                    },
                    "hasConductiveAdditive": {
                        "@type": ["ConductiveAdditive", "CarbonBlack"],
                        "hasMeasuredProperty": {
                            "@type": "MassFraction",
                            "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 3},
                            "hasMeasurementUnit": "unit:PERCENT",
                        },
                    },
                },
                "hasMeasuredProperty": [
                    {
                        "@type": "Diameter",
                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 14},
                        "hasMeasurementUnit": "unit:MilliM",
                    },
                ],
            },
            "hasNegativeElectrode": {
                "@type": "Electrode",
                "hasCurrentCollector": {
                    "@type": ["CurrentCollector", "Aluminium"],
                    "hasMeasuredProperty": {
                        "@type": "Thickness",
                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 20},
                        "hasMeasurementUnit": "emmo:MicroMetre",
                    },
                },
                "hasCoating": {
                    "@type": "ElectrodeCoating",
                    "hasActiveMaterial": {
                        "@type": "LithiumTitanate",
                        "hasMeasuredProperty": [
                            {
                                "@type": "MassFraction",
                                "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 90},
                                "hasMeasurementUnit": "unit:PERCENT",
                            },
                            {
                                "@type": "MassLoading",
                                "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 6.8},
                                "hasMeasurementUnit": "unit:MilliGM-PER-CentiM2",
                            },
                        ],
                    },
                },
            },
            "hasElectrolyte": {
                "@type": "OrganicElectrolyte",
                "hasSolvent": {
                    "@type": "Solvent",
                    "hasConstituent": [
                        {
                            "@type": "EthyleneCarbonate",
                            "hasMeasuredProperty": {
                                "@type": "VolumeFraction",
                                "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 30},
                                "hasMeasurementUnit": "unit:PERCENT",
                            },
                        },
                        {
                            "@type": "EthylMethylCarbonate",
                            "hasMeasuredProperty": {
                                "@type": "VolumeFraction",
                                "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 70},
                                "hasMeasurementUnit": "unit:PERCENT",
                            },
                        },
                    ],
                },
                "hasSolute": {
                    "@type": "Solute",
                    "hasConstituent": {
                        "@type": "LithiumBistrifluoromethanesulfonylimide",
                        "hasMeasuredProperty": {
                            "@type": "AmountConcentration",
                            "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 1},
                            "hasMeasurementUnit": "unit:MOL-PER-L",
                        },
                    },
                },
                "schema:manufacturer": {"@type": "schema:Organization", "schema:name": "Solvionic"},
            },
            "hasSeparator": {
                "@type": "Separator",
                "hasProperPart": [{"@type": "Polypropylene"}, {"@type": "Polyethylene"}],
                "rdfs:comment": "Celgard 2325 Trilayer Microporous Membrane (PP/PE/PP)",
                "hasMeasuredProperty": [
                    {
                        "@type": "Thickness",
                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 25},
                        "hasMeasurementUnit": "emmo:MicroMetre",
                    },
                    {
                        "@type": "Porosity",
                        "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 39},
                        "hasMeasurementUnit": "unit:PERCENT",
                    },
                ],
                "schema:manufacturer": {"@type": "schema:Organization", "schema:name": "Celgard"},
                "schema:productID": "2325",
            },
            "hasCase": {
                "@type": "R2032",
                "schema:productID": "2032, SUS316L",
                "schema:manufacturer": {"@type": "schema:Organization", "schema:name": "Hohsen"},
            },
            "hasComponent": [
                {
                    "@type": ["Spring", "StainlessSteel"],
                    "hasMeasuredProperty": [
                        {
                            "@type": "Diameter",
                            "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 15},
                            "hasMeasurementUnit": "unit:MilliM",
                        },
                        {
                            "@type": "Thickness",
                            "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 1.4},
                            "hasMeasurementUnit": "unit:MilliM",
                        },
                    ],
                },
                {
                    "@type": ["Spacer", "StainlessSteel"],
                    "hasMeasuredProperty": [
                        {
                            "@type": "Thickness",
                            "hasNumericalPart": {"@type": "emmo:RealData", "hasNumberValue": 1.0},
                            "hasMeasurementUnit": "unit:MilliM",
                        },
                    ],
                },
            ],
        },
        "hasOutput": {
            "dcat:distribution": [
                {
                    "@id": "https://doi.org/10.5281/zenodo.19107066#240327_kiye_NMC-LTO_Al_LiTFSI_022/full.csv",
                    "@type": "dcat:Distribution",
                    "dcat:mediaType": "text/csv",
                },
            ],
            "dc:title": "Cycling data coin cell empa__ccid001583",
            "dc:license": "https://creativecommons.org/licenses/by/4.0/",
            "dc:issued": "2026-04-13",
            "schema:citation": "Kim et al., Adv. Energy Sustainability Res., 2025, 6, 2500194",
            "schema:associatedMedia": {
                "@id": "https://doi.org/10.1002/aesr.202500194",
                "rdfs:label": ["Fig. 4d"],
            },
            "dc:creator": [
                {
                    "@type": "schema:Person",
                    "@id": "https://orcid.org/0000-0003-3024-6370",
                    "schema:name": "YeonJu Kim",
                    "schema:affiliation": {
                        "@id": "https://www.wikidata.org/wiki/Q683116",
                        "schema:name": "Empa",
                    },
                },
            ],
        },
    }


# ---------------------------------------------------------------------------
# Generation A tests
# ---------------------------------------------------------------------------

class TestGenerationA:
    def test_import_produces_valid_descriptor(self) -> None:
        result = import_converter_jsonld_record(_gen_a_fixture())
        assert isinstance(result.record.get("specification"), dict), "converter output should have specification key"

    def test_cell_id_prefers_empa_ccid_entry(self) -> None:
        result = import_converter_jsonld_record(_gen_a_fixture())
        instances = result.record.get("instances", [])
        assert instances, "expected at least one instance"
        assert instances[0]["serial_number"] == "empa__ccid000037"

    def test_date_parsed_from_dd_mm_yy(self) -> None:
        result = import_converter_jsonld_record(_gen_a_fixture())
        # 11/12/24 → 2024-12-11 in UTC → 1733875200
        prov = result.record.get("provenance") or {}
        retrieved = prov.get("retrieved_at", 0)
        assert retrieved > 0, "date was not parsed"

    def test_electrode_basis_inferred_from_comment(self) -> None:
        result = import_converter_jsonld_record(_gen_a_fixture())
        spec = result.record["specification"]
        assert spec["positive_electrode_basis"] == "NMC"
        assert spec["negative_electrode_basis"] == "graphite"

    def test_glass_fibre_separator_mapped(self) -> None:
        result = import_converter_jsonld_record(_gen_a_fixture())
        sep = result.record["specification"].get("separator", {})
        assert sep.get("material") == "Glass fibre"

    def test_hardware_extracted_from_hasConstituent_dict(self) -> None:
        result = import_converter_jsonld_record(_gen_a_fixture())
        housing = result.record["specification"].get("housing", {})
        parts = {part["type"]: part for part in housing.get("parts", [])}
        assert "spring" in parts
        assert parts["spring"]["property"]["diameter"]["value"] == 15

    def test_dataset_record_built(self) -> None:
        ds = import_dataset_record(_gen_a_fixture())
        assert ds is not None
        validation = validate_json(ds, profile="dataset")
        assert validation.ok, validation.errors

    def test_dataset_url_is_zenodo_landing_page(self) -> None:
        ds = import_dataset_record(_gen_a_fixture())
        assert ds is not None
        assert "zenodo.15481956" in ds["dataset"]["access_url"]

    def test_dataset_has_two_distributions(self) -> None:
        ds = import_dataset_record(_gen_a_fixture())
        assert ds is not None
        assert len(ds["dataset"]["distributions"]) == 2

    def test_dataset_parquet_format_mapped(self) -> None:
        ds = import_dataset_record(_gen_a_fixture())
        assert ds is not None
        formats = {d["encoding_format"] for d in ds["dataset"]["distributions"]}
        assert "application/vnd.apache.parquet" in formats


# ---------------------------------------------------------------------------
# Generation B tests
# ---------------------------------------------------------------------------

class TestGenerationB:
    def test_import_produces_valid_descriptor(self) -> None:
        result = import_converter_jsonld_record(_gen_b_fixture())
        assert isinstance(result.record.get("specification"), dict), "converter output should have specification key"

    def test_cell_id_from_single_string_product_id(self) -> None:
        result = import_converter_jsonld_record(_gen_b_fixture())
        instances = result.record.get("instances", [])
        assert instances
        assert instances[0]["serial_number"] == "empa__ccid001583"

    def test_nmc_basis_from_rdfs_comment(self) -> None:
        result = import_converter_jsonld_record(_gen_b_fixture())
        spec = result.record["specification"]
        assert spec["positive_electrode_basis"] == "NMC"

    def test_lto_anode_basis_mapped(self) -> None:
        result = import_converter_jsonld_record(_gen_b_fixture())
        spec = result.record["specification"]
        assert spec["negative_electrode_basis"] == "LTO"

    def test_litfsi_salt_name_mapped(self) -> None:
        result = import_converter_jsonld_record(_gen_b_fixture())
        electrolyte = result.record["specification"]["electrolyte"]
        assert electrolyte["salt"]["name"] == "LiTFSI"

    def test_hardware_extracted_from_hasComponent_list(self) -> None:
        result = import_converter_jsonld_record(_gen_b_fixture())
        housing = result.record["specification"].get("housing", {})
        parts = {part["type"]: part for part in housing.get("parts", [])}
        assert "spring" in parts
        assert parts["spring"]["property"]["diameter"]["value"] == 15
        assert "spacer" in parts

    def test_dataset_record_built(self) -> None:
        ds = import_dataset_record(_gen_b_fixture())
        assert ds is not None
        validation = validate_json(ds, profile="dataset")
        assert validation.ok, validation.errors

    def test_dataset_citation_doi_extracted(self) -> None:
        ds = import_dataset_record(_gen_b_fixture())
        assert ds is not None
        prov = ds["provenance"]
        assert "citation_doi" in prov
        assert prov["citation_doi"].startswith("10.")


# ---------------------------------------------------------------------------
# Cross-generation consistency
# ---------------------------------------------------------------------------

class TestCrossGeneration:
    def test_both_produce_coin_format(self) -> None:
        a = import_converter_jsonld_record(_gen_a_fixture()).record
        b = import_converter_jsonld_record(_gen_b_fixture()).record
        assert a["specification"]["format"] == "coin"
        assert b["specification"]["format"] == "coin"

    def test_both_produce_r2032_size_code(self) -> None:
        a = import_converter_jsonld_record(_gen_a_fixture()).record
        b = import_converter_jsonld_record(_gen_b_fixture()).record
        assert a["specification"]["size_code"] == "R2032"
        assert b["specification"]["size_code"] == "R2032"

    def test_both_have_organic_electrolyte(self) -> None:
        a = import_converter_jsonld_record(_gen_a_fixture()).record
        b = import_converter_jsonld_record(_gen_b_fixture()).record
        assert a["specification"]["electrolyte"]["family"] == "organic"
        assert b["specification"]["electrolyte"]["family"] == "organic"


# ---------------------------------------------------------------------------
# Batch importer (smoke test with real files if available)
# ---------------------------------------------------------------------------

KIYE_DIR = Path("D:/EMPA/kiye_dataset_csv")
ROCRATE_DIR = Path("D:/EMPA/Dataset-rocrate")


@pytest.mark.skipif(not KIYE_DIR.exists(), reason="kiye dataset not present on this machine")
def test_batch_import_kiye_all_succeed() -> None:
    results = batch_import_converter_directory(KIYE_DIR)
    assert results, "no metadata files found"
    failures = [r for r in results if not r.ok]
    assert not failures, "\n".join(f"{r.path.name}: {r.error}" for r in failures)
    for r in results:
        assert isinstance(r.descriptor.get("specification"), dict), f"{r.path.name}: converter output should have specification key"


@pytest.mark.skipif(not ROCRATE_DIR.exists(), reason="Dataset-rocrate not present on this machine")
def test_batch_import_rocrate_all_succeed() -> None:
    results = batch_import_converter_directory(ROCRATE_DIR)
    assert results, "no metadata files found"
    failures = [r for r in results if not r.ok]
    assert not failures, "\n".join(f"{r.path.name}: {r.error}" for r in failures)
    for r in results:
        assert isinstance(r.descriptor.get("specification"), dict), f"{r.path.name}: converter output should have specification key"
