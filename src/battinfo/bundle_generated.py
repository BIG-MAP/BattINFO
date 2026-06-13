from __future__ import annotations

import re
import sys
from datetime import (
    date,
    datetime,
    time
)
from decimal import Decimal
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Literal,
    Optional,
    Union
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer
)


metamodel_version = "1.11.0"
version = "0.1.0"


class ConfiguredBaseModel(BaseModel):
    model_config = ConfigDict(
        serialize_by_alias = True,
        validate_by_name = True,
        validate_assignment = True,
        validate_default = True,
        extra = "allow",
        arbitrary_types_allowed = True,
        use_enum_values = True,
        strict = False,
    )





class LinkMLMeta(RootModel):
    root: dict[str, Any] = {}
    model_config = ConfigDict(frozen=True)

    def __getattr__(self, key:str):
        return getattr(self.root, key)

    def __getitem__(self, key:str):
        return self.root[key]

    def __setitem__(self, key:str, value):
        self.root[key] = value

    def __contains__(self, key:str) -> bool:
        return key in self.root


linkml_meta = LinkMLMeta({'default_prefix': 'battinfo',
     'default_range': 'string',
     'description': 'LinkML schema for the BattINFO battery data ecosystem.  This '
                    'file is the single source of truth for record types, '
                    'property-to-IRI mappings, and the JSON-LD context published '
                    'at https://w3id.org/battinfo/context/records/v1.json. '
                    'Generated artefacts (JSON Schema, JSON-LD context, Pydantic '
                    'models) are produced by running `make gen-all` from the repo '
                    'root.',
     'id': 'https://w3id.org/battinfo/schema/battinfo',
     'imports': ['linkml:types',
                 'types',
                 'cell-type',
                 'cell-instance',
                 'test-spec',
                 'test',
                 'dataset'],
     'license': 'https://creativecommons.org/licenses/by/4.0/',
     'name': 'battinfo',
     'prefixes': {'battery': {'prefix_prefix': 'battery',
                              'prefix_reference': 'https://w3id.org/emmo/domain/battery#'},
                  'battinfo': {'prefix_prefix': 'battinfo',
                               'prefix_reference': 'https://w3id.org/battinfo/'},
                  'dcat': {'prefix_prefix': 'dcat',
                           'prefix_reference': 'http://www.w3.org/ns/dcat#'},
                  'dcterms': {'prefix_prefix': 'dcterms',
                              'prefix_reference': 'http://purl.org/dc/terms/'},
                  'dqv': {'prefix_prefix': 'dqv',
                          'prefix_reference': 'http://www.w3.org/ns/dqv#'},
                  'electrochemistry': {'prefix_prefix': 'electrochemistry',
                                       'prefix_reference': 'https://w3id.org/emmo/domain/electrochemistry#'},
                  'emmo': {'prefix_prefix': 'emmo',
                           'prefix_reference': 'https://w3id.org/emmo#'},
                  'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'oa': {'prefix_prefix': 'oa',
                         'prefix_reference': 'http://www.w3.org/ns/oa#'},
                  'prov': {'prefix_prefix': 'prov',
                           'prefix_reference': 'http://www.w3.org/ns/prov#'},
                  'qudt': {'prefix_prefix': 'qudt',
                           'prefix_reference': 'http://qudt.org/schema/qudt/'},
                  'qudt-unit': {'prefix_prefix': 'qudt-unit',
                                'prefix_reference': 'http://qudt.org/vocab/unit/'},
                  'rdfs': {'prefix_prefix': 'rdfs',
                           'prefix_reference': 'http://www.w3.org/2000/01/rdf-schema#'},
                  'schema': {'prefix_prefix': 'schema',
                             'prefix_reference': 'http://schema.org/'},
                  'spdx': {'prefix_prefix': 'spdx',
                           'prefix_reference': 'http://spdx.org/rdf/terms#'},
                  'xsd': {'prefix_prefix': 'xsd',
                          'prefix_reference': 'http://www.w3.org/2001/XMLSchema#'}},
     'source_file': 'schema/battinfo.yaml',
     'title': 'BattINFO Battery Data Schema'} )

class BatteryTestType(str, Enum):
    """
    Controlled vocabulary for battery test types.
    """
    cycling = "cycling"
    """
    Repeated charge/discharge cycling.
    """
    capacity_check = "capacity_check"
    """
    Capacity measurement at defined C-rate.
    """
    rate_capability = "rate_capability"
    """
    Discharge at multiple C-rates.
    """
    hppc = "hppc"
    """
    Hybrid pulse power characterisation.
    """
    ici = "ici"
    """
    Intermittent current interruption.
    """
    gitt = "gitt"
    """
    Galvanostatic intermittent titration technique.
    """
    dcir = "dcir"
    """
    DC internal resistance measurement.
    """
    eis = "eis"
    """
    Electrochemical impedance spectroscopy.
    """
    impedance = "impedance"
    """
    Generic impedance measurement.
    """
    calendar_ageing = "calendar_ageing"
    """
    Storage / calendar ageing test.
    """
    formation = "formation"
    """
    Formation / conditioning cycling.
    """
    rpt = "rpt"
    """
    Reference performance test.
    """
    quasi_ocv = "quasi_ocv"
    """
    Quasi-OCV / low-rate discharge.
    """
    field = "field"
    """
    Field / in-vehicle / application test.
    """
    duty_cycle = "duty_cycle"
    """
    Application duty-cycle test.
    """
    wltp = "wltp"
    """
    Worldwide harmonised light-duty test procedure.
    """
    nedc = "nedc"
    """
    New European Driving Cycle.
    """
    sem = "sem"
    """
    Scanning electron microscopy.
    """
    characterization = "characterization"
    """
    General characterisation (unspecified type).
    """
    other = "other"
    """
    Test type not covered by enumerated values.
    """


class CellFormat(str, Enum):
    """
    Physical format (geometry) of the battery cell.
    """
    cylindrical = "cylindrical"
    prismatic = "prismatic"
    pouch = "pouch"
    coin = "coin"
    other = "other"
    unknown = "unknown"


class CellProductType(str, Enum):
    """
    Product maturity level of the cell.
    """
    commercial = "commercial"
    """
    Mass-produced commercial product.
    """
    research = "research"
    """
    Research / experimental cell.
    """
    prototype = "prototype"
    """
    Pre-production prototype.
    """


class CellGrade(str, Enum):
    """
    Battery grade / reuse status per EU Battery Regulation 2023/1542.
    """
    original = "original"
    repurposed = "repurposed"
    re_used = "re-used"
    remanufactured = "remanufactured"
    waste = "waste"


class BatteryStatus(str, Enum):
    """
    Battery status per EU Battery Regulation 2023/1542, Article 14.
    """
    original = "original"
    repurposed = "repurposed"
    reused = "reused"
    remanufactured = "remanufactured"
    waste = "waste"


class BatteryCategoryEU(str, Enum):
    """
    Battery category per EU Battery Regulation 2023/1542.
    """
    LMT = "LMT"
    """
    Light means of transport.
    """
    EV = "EV"
    """
    Electric vehicle (traction).
    """
    Industrial = "Industrial"
    """
    Industrial battery.
    """
    Stationary = "Stationary"
    """
    Stationary energy storage.
    """
    Portable = "Portable"
    """
    Portable (general purpose).
    """
    SLI = "SLI"
    """
    Starting, lighting, ignition.
    """


class ConformanceStatus(str, Enum):
    """
    How closely a test execution conformed to its specification.
    """
    conformant = "conformant"
    """
    Fully conformed to the test specification.
    """
    partial = "partial"
    """
    Deviated in minor steps but produced usable data.
    """
    non_conformant = "non-conformant"
    """
    Deviated to such degree that results are unreliable.
    """
    unknown = "unknown"
    """
    Conformance status not known.
    """


class ProvenanceSourceType(str, Enum):
    """
    Origin type for provenance tracking.
    """
    measurement = "measurement"
    lab = "lab"
    simulation = "simulation"
    catalog = "catalog"
    external = "external"
    manual = "manual"
    inferred = "inferred"
    other = "other"



class SpecValue(ConfiguredBaseModel):
    """
    A scalar quantity with an optional measurement unit.  Used for all quantitative battery properties in SpecSet.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/battinfo/schema/types'})

    sv_value: Optional[float] = Field(default=None, description="""Nominal/measured value of the quantity.""", json_schema_extra = { "linkml_meta": {'aliases': ['value'],
         'domain': 'SpecValue',
         'domain_of': ['SpecValue'],
         'slot_uri': 'qudt:value'} })
    sv_unit: Optional[str] = Field(default=None, description="""Unit symbol (e.g. \"Ah\", \"V\", \"g\").""", json_schema_extra = { "linkml_meta": {'aliases': ['unit'],
         'domain': 'SpecValue',
         'domain_of': ['SpecValue'],
         'slot_uri': 'qudt:unit'} })
    sv_min_value: Optional[float] = Field(default=None, description="""Minimum acceptable value.""", json_schema_extra = { "linkml_meta": {'aliases': ['min_value'], 'domain': 'SpecValue', 'domain_of': ['SpecValue']} })
    sv_max_value: Optional[float] = Field(default=None, description="""Maximum acceptable value.""", json_schema_extra = { "linkml_meta": {'aliases': ['max_value'], 'domain': 'SpecValue', 'domain_of': ['SpecValue']} })
    sv_typical_value: Optional[float] = Field(default=None, description="""Typical/representative value.""", json_schema_extra = { "linkml_meta": {'aliases': ['typical_value'],
         'domain': 'SpecValue',
         'domain_of': ['SpecValue']} })
    sv_value_text: Optional[str] = Field(default=None, description="""Free-text value representation when numeric is unavailable.""", json_schema_extra = { "linkml_meta": {'aliases': ['value_text'], 'domain': 'SpecValue', 'domain_of': ['SpecValue']} })


class Provenance(ConfiguredBaseModel):
    """
    Tracks the origin and curation history of a record.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/battinfo/schema/types'})

    source_type: Optional[ProvenanceSourceType] = Field(default=None, description="""Origin category of the record.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Provenance'], 'slot_uri': 'battinfo:sourceType'} })
    source_url: Optional[str] = Field(default=None, description="""URL of the original source document.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Provenance'], 'slot_uri': 'battinfo:sourceURL'} })
    source_file: Optional[str] = Field(default=None, description="""Filename of the source document.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Provenance'], 'slot_uri': 'battinfo:sourceFile'} })
    citation: Optional[str] = Field(default=None, description="""Citable reference URL.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Provenance'], 'slot_uri': 'dcterms:bibliographicCitation'} })
    citation_doi: Optional[str] = Field(default=None, description="""DOI of the citable reference.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Provenance'], 'slot_uri': 'battinfo:citationDOI'} })
    retrieved_at: Optional[int] = Field(default=None, description="""Epoch timestamp when the record was retrieved/ingested.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Provenance'], 'slot_uri': 'battinfo:retrievedAt'} })
    workflow_version: Optional[str] = Field(default=None, description="""Version of the ingestion workflow that created this record.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Provenance'], 'slot_uri': 'battinfo:workflowVersion'} })
    curated_by: Optional[str] = Field(default=None, description="""ORCID or name of the person who curated this record.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Provenance'], 'slot_uri': 'dcterms:contributor'} })


class ProtocolInfo(ConfiguredBaseModel):
    """
    Human-readable name and optional URL of a test protocol standard.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/battinfo/schema/types'})

    protocol_name: Optional[str] = Field(default=None, description="""Human-readable name of the protocol standard.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProtocolInfo'], 'slot_uri': 'schema:name'} })
    protocol_url: Optional[str] = Field(default=None, description="""URL pointing to the protocol specification document.""", json_schema_extra = { "linkml_meta": {'domain_of': ['ProtocolInfo'], 'slot_uri': 'schema:url'} })


class CellType(ConfiguredBaseModel):
    """
    A battery cell product specification: manufacturer, model, format, chemistry, and quantitative performance properties.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'class_uri': 'battery:battery_68ed592a_7924_45d0_a108_94d6275d57f0',
         'from_schema': 'https://w3id.org/battinfo/schema/cell-type'})

    id: str = Field(default=..., description="""Canonical IRI for this cell-type record.""", json_schema_extra = { "linkml_meta": {'domain_of': ['CellType'], 'slot_uri': 'schema:productID'} })
    ct_name: Optional[str] = Field(default=None, description="""Full display name of the product (manufacturer + model).""", json_schema_extra = { "linkml_meta": {'aliases': ['name'], 'domain_of': ['CellType'], 'slot_uri': 'schema:name'} })
    ct_model: str = Field(default=..., description="""Manufacturer's product model number or name.""", json_schema_extra = { "linkml_meta": {'aliases': ['model'], 'domain_of': ['CellType'], 'slot_uri': 'schema:model'} })
    ct_manufacturer: Organization = Field(default=..., description="""The company that manufactured this cell.""", json_schema_extra = { "linkml_meta": {'aliases': ['manufacturer'],
         'domain_of': ['CellType'],
         'slot_uri': 'schema:manufacturer'} })
    ct_cell_format: CellFormat = Field(default=..., description="""Physical format (geometry) of the cell housing.""", json_schema_extra = { "linkml_meta": {'aliases': ['cell_format', 'format'],
         'domain_of': ['CellType'],
         'slot_uri': 'battinfo:cellFormat'} })
    ct_chemistry: str = Field(default=..., description="""Cell chemistry identifier (e.g. \"li-ion\", \"li-primary\", \"na-ion\", \"alkaline\", \"zinc-carbon\", \"li-mno2\").""", json_schema_extra = { "linkml_meta": {'aliases': ['chemistry'],
         'domain_of': ['CellType'],
         'slot_uri': 'battinfo:chemistry'} })
    ct_positive_electrode_basis: Optional[str] = Field(default=None, description="""Cathode active material basis (e.g. \"nmc\", \"lfp\", \"nca\", \"lco\", \"mno2\").""", json_schema_extra = { "linkml_meta": {'aliases': ['positive_electrode_basis'],
         'domain_of': ['CellType'],
         'slot_uri': 'battinfo:positiveElectrodeBasis'} })
    ct_negative_electrode_basis: Optional[str] = Field(default=None, description="""Anode active material basis (e.g. \"graphite\", \"silicon-graphite\", \"hard-carbon\", \"lithium\").""", json_schema_extra = { "linkml_meta": {'aliases': ['negative_electrode_basis'],
         'domain_of': ['CellType'],
         'slot_uri': 'battinfo:negativeElectrodeBasis'} })
    ct_size_code: Optional[str] = Field(default=None, description="""Standardised size code (e.g. \"18650\", \"21700\", \"AA\", \"AAA\").""", json_schema_extra = { "linkml_meta": {'aliases': ['size_code'],
         'domain_of': ['CellType'],
         'slot_uri': 'battinfo:sizeCode'} })
    ct_iec_code: Optional[str] = Field(default=None, description="""IEC 60086 or IEC 61960 code string (e.g. \"LR6\", \"ICR18650\").""", json_schema_extra = { "linkml_meta": {'aliases': ['iec_code'],
         'domain_of': ['CellType'],
         'slot_uri': 'schema:productID'} })
    ct_product_type: Optional[CellProductType] = Field(default=None, description="""Product maturity level.""", json_schema_extra = { "linkml_meta": {'aliases': ['product_type'],
         'domain_of': ['CellType'],
         'slot_uri': 'battinfo:productType'} })
    ct_rechargeable: Optional[bool] = Field(default=None, description="""True for secondary (rechargeable) cells; false for primary.""", json_schema_extra = { "linkml_meta": {'aliases': ['rechargeable'],
         'domain_of': ['CellType'],
         'slot_uri': 'battinfo:rechargeable'} })
    ct_year: Optional[int] = Field(default=None, description="""Model release or market introduction year.""", json_schema_extra = { "linkml_meta": {'aliases': ['year'],
         'domain_of': ['CellType'],
         'slot_uri': 'schema:datePublished'} })
    ct_country_of_origin: Optional[str] = Field(default=None, description="""ISO 3166-1 alpha-2 country code of manufacturing origin.""", json_schema_extra = { "linkml_meta": {'aliases': ['country_of_origin'],
         'domain_of': ['CellType'],
         'slot_uri': 'battinfo:countryOfOrigin'} })
    ct_battery_category: Optional[BatteryCategoryEU] = Field(default=None, description="""EU Battery Regulation 2023/1542 battery category (LMT, EV, Industrial, Stationary, Portable, SLI).""", json_schema_extra = { "linkml_meta": {'aliases': ['battery_category'],
         'domain_of': ['CellType'],
         'slot_uri': 'battinfo:batteryCategory'} })
    ct_specs: Optional[SpecSet] = Field(default=None, description="""Quantitative performance specification for this cell type.""", json_schema_extra = { "linkml_meta": {'aliases': ['specs'], 'domain_of': ['CellType'], 'slot_uri': 'battinfo:specs'} })


class Organization(ConfiguredBaseModel):
    """
    A manufacturer, brand, or research organisation.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/battinfo/schema/cell-type'})

    org_id: Optional[str] = Field(default=None, description="""IRI / URL identifying the organisation.""", json_schema_extra = { "linkml_meta": {'aliases': ['id'], 'domain_of': ['Organization'], 'slot_uri': 'schema:url'} })
    org_name: str = Field(default=..., description="""Display name of the organisation.""", json_schema_extra = { "linkml_meta": {'aliases': ['name'], 'domain_of': ['Organization'], 'slot_uri': 'schema:name'} })


class SpecSet(ConfiguredBaseModel):
    """
    Harmonised set of quantitative battery cell properties. Each field is a SpecValue (value + unit), identified by its EMMO IRI.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/battinfo/schema/cell-type'})

    nominal_capacity: Optional[SpecValue] = Field(default=None, description="""Nominal (rated) discharge capacity at standard conditions.""", json_schema_extra = { "linkml_meta": {'aliases': ['Nominal capacity [Ah]', 'Rated capacity [Ah]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_8abde9d0_84f6_4b4f_a87e_86028a397100'} })
    minimum_capacity: Optional[SpecValue] = Field(default=None, description="""Minimum guaranteed capacity.""", json_schema_extra = { "linkml_meta": {'aliases': ['Minimum capacity [Ah]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_8abde9d0_84f6_4b4f_a87e_86028a397100'} })
    rated_capacity: Optional[SpecValue] = Field(default=None, description="""Capacity rated by the manufacturer (may differ from typical).""", json_schema_extra = { "linkml_meta": {'aliases': ['Rated capacity [Ah]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_8abde9d0_84f6_4b4f_a87e_86028a397100'} })
    typical_capacity: Optional[SpecValue] = Field(default=None, description="""Typical capacity as manufactured.""", json_schema_extra = { "linkml_meta": {'aliases': ['Typical capacity [Ah]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_8abde9d0_84f6_4b4f_a87e_86028a397100'} })
    nominal_voltage: Optional[SpecValue] = Field(default=None, description="""Nominal operating voltage.""", json_schema_extra = { "linkml_meta": {'aliases': ['Nominal voltage [V]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_639b844a_e801_436b_985d_28926129ead6'} })
    charging_voltage: Optional[SpecValue] = Field(default=None, description="""Maximum (end-of-charge) voltage.""", json_schema_extra = { "linkml_meta": {'aliases': ['Charging voltage [V]', 'Upper voltage limit [V]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_79a9e1be_35b0_4c3c_8087_b5f967ca0e87'} })
    discharging_cutoff_voltage: Optional[SpecValue] = Field(default=None, description="""Minimum (discharge cutoff) voltage.""", json_schema_extra = { "linkml_meta": {'aliases': ['Discharging cutoff voltage [V]', 'Lower voltage limit [V]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_534dd59c_904c_45d9_8550_ae9d2eb6bbc9'} })
    charging_cutoff_voltage: Optional[SpecValue] = Field(default=None, description="""Charge cutoff voltage (alias: upper voltage limit).""", json_schema_extra = { "linkml_meta": {'aliases': ['Charging cutoff voltage [V]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_6dcd5baf_58cd_43f5_a692_51508e036c88'} })
    upper_voltage_limit: Optional[SpecValue] = Field(default=None, description="""Upper voltage safety limit (synonym for charging cutoff voltage).""", json_schema_extra = { "linkml_meta": {'aliases': ['Upper voltage limit [V]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_6dcd5baf_58cd_43f5_a692_51508e036c88'} })
    maximum_continuous_charging_current: Optional[SpecValue] = Field(default=None, description="""Maximum continuous charge current allowed.""", json_schema_extra = { "linkml_meta": {'aliases': ['Maximum continuous charging current [A]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_39d8a6ee_cd55_4855_8b5b_d42bef95ac78'} })
    nominal_continuous_charging_current: Optional[SpecValue] = Field(default=None, description="""Nominal continuous charge current (standard rate).""", json_schema_extra = { "linkml_meta": {'aliases': ['Nominal continuous charging current [A]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_39d8a6ee_cd55_4855_8b5b_d42bef95ac78'} })
    maximum_pulse_charging_current: Optional[SpecValue] = Field(default=None, description="""Peak pulse charge current.""", json_schema_extra = { "linkml_meta": {'aliases': ['Maximum pulse charging current [A]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_39d8a6ee_cd55_4855_8b5b_d42bef95ac78'} })
    maximum_continuous_discharging_current: Optional[SpecValue] = Field(default=None, description="""Maximum continuous discharge current allowed.""", json_schema_extra = { "linkml_meta": {'aliases': ['Maximum continuous discharging current [A]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_ba7ac581_0e13_4815_b888_013c378932f5'} })
    nominal_continuous_discharging_current: Optional[SpecValue] = Field(default=None, description="""Nominal continuous discharge current.""", json_schema_extra = { "linkml_meta": {'aliases': ['Nominal continuous discharging current [A]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_ba7ac581_0e13_4815_b888_013c378932f5'} })
    maximum_pulse_discharging_current: Optional[SpecValue] = Field(default=None, description="""Peak pulse discharge current.""", json_schema_extra = { "linkml_meta": {'aliases': ['Maximum pulse discharging current [A]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_ba7ac581_0e13_4815_b888_013c378932f5'} })
    nominal_energy: Optional[SpecValue] = Field(default=None, description="""Nominal stored energy.""", json_schema_extra = { "linkml_meta": {'aliases': ['Nominal energy [Wh]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_19e27aa3_0970_43a6_86d3_e3cdd956134d'} })
    typical_energy: Optional[SpecValue] = Field(default=None, description="""Typical stored energy as manufactured.""", json_schema_extra = { "linkml_meta": {'aliases': ['Typical energy [Wh]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_19e27aa3_0970_43a6_86d3_e3cdd956134d'} })
    rated_energy: Optional[SpecValue] = Field(default=None, description="""Manufacturer-rated energy content.""", json_schema_extra = { "linkml_meta": {'aliases': ['Rated energy [Wh]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_19e27aa3_0970_43a6_86d3_e3cdd956134d'} })
    certified_usable_energy: Optional[SpecValue] = Field(default=None, description="""Certified usable energy per EU Battery Regulation 2023/1542.""", json_schema_extra = { "linkml_meta": {'aliases': ['Certified usable energy [Wh]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_19e27aa3_0970_43a6_86d3_e3cdd956134d'} })
    power_capability: Optional[SpecValue] = Field(default=None, description="""Continuous power output capability.""", json_schema_extra = { "linkml_meta": {'aliases': ['Power capability [W]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:powerCapability'} })
    maximum_power: Optional[SpecValue] = Field(default=None, description="""Peak (pulse) power output.""", json_schema_extra = { "linkml_meta": {'aliases': ['Maximum power [W]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:maximumPower'} })
    specific_energy: Optional[SpecValue] = Field(default=None, description="""Gravimetric energy density (energy per unit mass).""", json_schema_extra = { "linkml_meta": {'aliases': ['Specific energy [Wh/kg]', 'Gravimetric energy density [Wh/kg]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'emmo:EMMO_e218c625_6a39_47a9_8d08_a2ef41c152a9'} })
    energy_density: Optional[SpecValue] = Field(default=None, description="""Volumetric energy density (energy per unit volume).""", json_schema_extra = { "linkml_meta": {'aliases': ['Energy density [Wh/L]', 'Volumetric energy density [Wh/L]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_4aa1b96e_44a0_4b1a_a0ac_723d0223d80b'} })
    specific_power: Optional[SpecValue] = Field(default=None, description="""Gravimetric power density.""", json_schema_extra = { "linkml_meta": {'aliases': ['Specific power [W/kg]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:specificPower'} })
    power_density: Optional[SpecValue] = Field(default=None, description="""Volumetric power density.""", json_schema_extra = { "linkml_meta": {'aliases': ['Power density [W/L]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:powerDensity'} })
    power_energy_ratio: Optional[SpecValue] = Field(default=None, description="""Ratio of rated power to rated energy.""", json_schema_extra = { "linkml_meta": {'aliases': ['Power-to-energy ratio [W/Wh]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:powerEnergyRatio'} })
    internal_resistance: Optional[SpecValue] = Field(default=None, description="""General internal resistance.""", json_schema_extra = { "linkml_meta": {'aliases': ['Internal resistance [mOhm]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_9bf40017_3f58_4030_ada7_cb37a3dfda2d'} })
    dc_internal_resistance: Optional[SpecValue] = Field(default=None, description="""DC internal resistance measured by current-interrupt method.""", json_schema_extra = { "linkml_meta": {'aliases': ['DC internal resistance [mOhm]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_9bf40017_3f58_4030_ada7_cb37a3dfda2d'} })
    ac_internal_resistance: Optional[SpecValue] = Field(default=None, description="""AC impedance magnitude at 1 kHz.""", json_schema_extra = { "linkml_meta": {'aliases': ['AC internal resistance [mOhm]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_9bf40017_3f58_4030_ada7_cb37a3dfda2d'} })
    impedance: Optional[SpecValue] = Field(default=None, description="""Complex impedance magnitude (general).""", json_schema_extra = { "linkml_meta": {'aliases': ['Impedance [mOhm]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_9bf40017_3f58_4030_ada7_cb37a3dfda2d'} })
    round_trip_energy_efficiency: Optional[SpecValue] = Field(default=None, description="""Ratio of discharge energy to charge energy (full charge-discharge cycle).""", json_schema_extra = { "linkml_meta": {'aliases': ['Round-trip energy efficiency [1]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:roundTripEnergyEfficiency'} })
    round_trip_energy_efficiency_50pct: Optional[SpecValue] = Field(default=None, description="""Round-trip efficiency measured at 50% state of charge.""", json_schema_extra = { "linkml_meta": {'aliases': ['Round-trip energy efficiency at 50% SOC [1]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:roundTripEnergyEfficiency50Pct'} })
    initial_coulombic_efficiency: Optional[SpecValue] = Field(default=None, description="""Coulombic efficiency on the first formation cycle.""", json_schema_extra = { "linkml_meta": {'aliases': ['Initial coulombic efficiency [1]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:initialCoulombicEfficiency'} })
    mass: Optional[SpecValue] = Field(default=None, description="""Mass of the cell (including packaging).""", json_schema_extra = { "linkml_meta": {'aliases': ['Mass [g]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'emmo:EMMO_ed4af7ae_63a2_497e_bb88_2309619ea405'} })
    diameter: Optional[SpecValue] = Field(default=None, description="""Outer diameter (cylindrical or coin cells).""", json_schema_extra = { "linkml_meta": {'aliases': ['Diameter [mm]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'emmo:EMMO_c1c8ac3c_8a1c_4777_8e0b_14c1f9f9b0c6'} })
    height: Optional[SpecValue] = Field(default=None, description="""Height of the cell (cylindrical: total length; prismatic: z-dimension).""", json_schema_extra = { "linkml_meta": {'aliases': ['Height [mm]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'emmo:EMMO_08bcf1d6_e719_46c8_bb21_24bc9bf34dba'} })
    width: Optional[SpecValue] = Field(default=None, description="""Width of the cell (prismatic / pouch cells).""", json_schema_extra = { "linkml_meta": {'aliases': ['Width [mm]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'emmo:EMMO_e4de48b1_dabb_4490_ac2b_040f926c64f0'} })
    length: Optional[SpecValue] = Field(default=None, description="""Length of the cell (prismatic / pouch cells).""", json_schema_extra = { "linkml_meta": {'aliases': ['Length [mm]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'emmo:EMMO_cd2cd0de_e0cc_4ef1_b27e_2e88db027bac'} })
    thickness: Optional[SpecValue] = Field(default=None, description="""Thickness (pouch / coin cells).""", json_schema_extra = { "linkml_meta": {'aliases': ['Thickness [mm]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'emmo:EMMO_43003c86_9d15_433b_9789_ee2940920656'} })
    volume: Optional[SpecValue] = Field(default=None, description="""External volume of the cell.""", json_schema_extra = { "linkml_meta": {'aliases': ['Volume [mL]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:volume'} })
    maximum_charging_temperature: Optional[SpecValue] = Field(default=None, description="""Maximum allowed cell temperature during charging.""", json_schema_extra = { "linkml_meta": {'aliases': ['Maximum charging temperature [degC]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_4a354510_4dc2_4803_8845_f4024a1a7260'} })
    minimum_charging_temperature: Optional[SpecValue] = Field(default=None, description="""Minimum allowed cell temperature during charging.""", json_schema_extra = { "linkml_meta": {'aliases': ['Minimum charging temperature [degC]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_b90b1ad7_b9a8_44df_ad45_bfd25aac2e49'} })
    maximum_discharging_temperature: Optional[SpecValue] = Field(default=None, description="""Maximum allowed cell temperature during discharging.""", json_schema_extra = { "linkml_meta": {'aliases': ['Maximum discharging temperature [degC]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_de612af2_a029_4a02_8090_4a75ab13271d'} })
    minimum_discharging_temperature: Optional[SpecValue] = Field(default=None, description="""Minimum allowed cell temperature during discharging.""", json_schema_extra = { "linkml_meta": {'aliases': ['Minimum discharging temperature [degC]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_2a1de79f_e927_45a2_9619_3799a0d61e9b'} })
    maximum_storage_temperature: Optional[SpecValue] = Field(default=None, description="""Maximum recommended storage temperature.""", json_schema_extra = { "linkml_meta": {'aliases': ['Maximum storage temperature [degC]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_0ea4d188_9701_4699_a5ca_812a98a9afa7'} })
    minimum_storage_temperature: Optional[SpecValue] = Field(default=None, description="""Minimum recommended storage temperature.""", json_schema_extra = { "linkml_meta": {'aliases': ['Minimum storage temperature [degC]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_0ddfd57a_d338_4690_be45_b26884ed6302'} })
    operating_temperature_min: Optional[SpecValue] = Field(default=None, description="""Overall minimum operating temperature (discharge + charge).""", json_schema_extra = { "linkml_meta": {'aliases': ['Minimum operating temperature [degC]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:operatingTemperatureMin'} })
    operating_temperature_max: Optional[SpecValue] = Field(default=None, description="""Overall maximum operating temperature (discharge + charge).""", json_schema_extra = { "linkml_meta": {'aliases': ['Maximum operating temperature [degC]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:operatingTemperatureMax'} })
    cycle_life: Optional[SpecValue] = Field(default=None, description="""Number of cycles to rated end-of-life criterion.""", json_schema_extra = { "linkml_meta": {'aliases': ['Cycle life [1]', 'Cycle count'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_ae782b14_88ce_4cdd_9418_12aca00be937'} })
    cycle_life_c_rate: Optional[SpecValue] = Field(default=None, description="""C-rate used in the cycle life test.""", json_schema_extra = { "linkml_meta": {'aliases': ['Cycle life C-rate [1/h]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:cycleLifeCRate'} })
    calendar_life: Optional[SpecValue] = Field(default=None, description="""Calendar storage lifetime to end-of-life criterion.""", json_schema_extra = { "linkml_meta": {'aliases': ['Calendar life [years]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'electrochemistry:electrochemistry_743c71a3_b80c_42e3_92fa_13a67b8167df'} })
    capacity_fade: Optional[SpecValue] = Field(default=None, description="""Capacity fade rate per cycle or per year.""", json_schema_extra = { "linkml_meta": {'aliases': ['Capacity fade [1/cycle]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:capacityFade'} })
    capacity_threshold_exhaustion: Optional[SpecValue] = Field(default=None, description="""Capacity threshold defining battery exhaustion per EU Battery Regulation.""", json_schema_extra = { "linkml_meta": {'aliases': ['Capacity threshold for exhaustion [1]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:capacityThresholdExhaustion'} })
    charging_time: Optional[SpecValue] = Field(default=None, description="""Time to charge from 0% to 100% SOC at standard rate.""", json_schema_extra = { "linkml_meta": {'aliases': ['Charging time [min]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:chargingTime'} })
    self_discharge_rate: Optional[SpecValue] = Field(default=None, description="""Self-discharge rate (capacity loss per unit time in storage).""", json_schema_extra = { "linkml_meta": {'aliases': ['Self-discharge rate [%/month]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:selfDischargeRate'} })
    state_of_health: Optional[SpecValue] = Field(default=None, description="""State of health (ratio of current to original capacity).""", json_schema_extra = { "linkml_meta": {'aliases': ['State of health [1]'],
         'domain_of': ['SpecSet'],
         'slot_uri': 'battinfo:stateOfHealth'} })


class CellInstance(ConfiguredBaseModel):
    """
    A specific physical battery cell — one individual unit that can be tested. Links to a CellType specification and carries its own serial/batch identity.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'class_uri': 'battinfo:CellInstance',
         'from_schema': 'https://w3id.org/battinfo/schema/cell-instance'})

    ci_id: str = Field(default=..., description="""Canonical IRI for this cell instance.""", json_schema_extra = { "linkml_meta": {'aliases': ['id'],
         'domain_of': ['CellInstance'],
         'slot_uri': 'schema:productID'} })
    ci_type_id: str = Field(default=..., description="""IRI of the CellType specification this instance conforms to.""", json_schema_extra = { "linkml_meta": {'aliases': ['type_id'],
         'domain_of': ['CellInstance'],
         'slot_uri': 'battinfo:cellSpecification'} })
    ci_serial_number: Optional[str] = Field(default=None, description="""Manufacturer serial number (unique within the product model).""", json_schema_extra = { "linkml_meta": {'aliases': ['serial_number'],
         'domain_of': ['CellInstance'],
         'slot_uri': 'schema:serialNumber'} })
    ci_batch_id: Optional[str] = Field(default=None, description="""Batch or lot identifier assigned during manufacturing.""", json_schema_extra = { "linkml_meta": {'aliases': ['batch_id'],
         'domain_of': ['CellInstance'],
         'slot_uri': 'battinfo:batchId'} })
    ci_grade: Optional[CellGrade] = Field(default=None, description="""Cell grade / reuse status per EU Battery Regulation 2023/1542.""", json_schema_extra = { "linkml_meta": {'aliases': ['grade'],
         'domain_of': ['CellInstance'],
         'slot_uri': 'battinfo:cellGrade'} })
    ci_manufactured_at: Optional[int] = Field(default=None, description="""Manufacturing date (UNIX epoch or ISO 8601).""", json_schema_extra = { "linkml_meta": {'aliases': ['manufactured_at'],
         'domain_of': ['CellInstance'],
         'slot_uri': 'schema:productionDate'} })
    ci_expires_at: Optional[int] = Field(default=None, description="""Shelf life expiry date (UNIX epoch or ISO 8601).""", json_schema_extra = { "linkml_meta": {'aliases': ['expires_at'],
         'domain_of': ['CellInstance'],
         'slot_uri': 'battinfo:expiresAt'} })
    ci_service_start_date: Optional[str] = Field(default=None, description="""ISO 8601 date when the cell was first placed in service.""", json_schema_extra = { "linkml_meta": {'aliases': ['service_start_date'],
         'domain_of': ['CellInstance'],
         'slot_uri': 'battinfo:serviceStartDate'} })
    ci_battery_status: Optional[BatteryStatus] = Field(default=None, description="""Battery status per EU Battery Regulation 2023/1542.""", json_schema_extra = { "linkml_meta": {'aliases': ['battery_status'],
         'domain_of': ['CellInstance'],
         'slot_uri': 'battinfo:batteryStatus'} })
    ci_dataset_ids: Optional[list[str]] = Field(default=None, description="""IRIs of dataset records linked to this cell instance.""", json_schema_extra = { "linkml_meta": {'aliases': ['dataset_ids'],
         'domain_of': ['CellInstance'],
         'slot_uri': 'battinfo:hasDataset'} })
    ci_measured: Optional[SpecSet] = Field(default=None, description="""Measured properties for this individual cell (overrides CellType spec values where more precise measurements are available).""", json_schema_extra = { "linkml_meta": {'aliases': ['measured'],
         'domain_of': ['CellInstance'],
         'slot_uri': 'battinfo:measuredSpecs'} })


class TestSpec(ConfiguredBaseModel):
    """
    A test protocol specification (plan) that defines the procedure for a battery test.  Referenced by Test instances via prov:used.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'class_uri': 'battinfo:TestSpec',
         'from_schema': 'https://w3id.org/battinfo/schema/test-spec'})

    ts_id: str = Field(default=..., description="""Canonical IRI for this test specification.""", json_schema_extra = { "linkml_meta": {'aliases': ['id'], 'domain_of': ['TestSpec'], 'slot_uri': 'schema:productID'} })
    ts_name: str = Field(default=..., description="""Human-readable name of the test protocol.""", json_schema_extra = { "linkml_meta": {'aliases': ['name'], 'domain_of': ['TestSpec'], 'slot_uri': 'schema:name'} })
    ts_kind: BatteryTestType = Field(default=..., description="""Test type from the BatteryTestType controlled vocabulary.""", json_schema_extra = { "linkml_meta": {'aliases': ['kind', 'test_type'],
         'domain_of': ['TestSpec'],
         'slot_uri': 'battinfo:testKind'} })
    ts_description: Optional[str] = Field(default=None, description="""Free-text description of the protocol.""", json_schema_extra = { "linkml_meta": {'aliases': ['description'],
         'domain_of': ['TestSpec'],
         'slot_uri': 'schema:description'} })
    ts_version: Optional[str] = Field(default=None, description="""Version string of this protocol specification.""", json_schema_extra = { "linkml_meta": {'aliases': ['version'],
         'domain_of': ['TestSpec'],
         'slot_uri': 'schema:version'} })
    ts_protocol: Optional[ProtocolInfo] = Field(default=None, description="""Reference to the formal protocol standard document.""", json_schema_extra = { "linkml_meta": {'aliases': ['protocol'],
         'domain_of': ['TestSpec'],
         'slot_uri': 'battinfo:protocolReference'} })
    ts_steps: Optional[list[str]] = Field(default=None, description="""Ordered list of PyBaMM-compatible experiment step strings (e.g. \"Discharge at 1C until 2.5 V\").""", json_schema_extra = { "linkml_meta": {'aliases': ['steps'], 'domain_of': ['TestSpec'], 'slot_uri': 'battinfo:steps'} })
    ts_cycles: Optional[int] = Field(default=None, description="""Number of times the step sequence is repeated.""", ge=1, json_schema_extra = { "linkml_meta": {'aliases': ['cycles'],
         'domain_of': ['TestSpec'],
         'slot_uri': 'battinfo:cycles'} })
    ts_conditions: Optional[str] = Field(default=None, description="""Free-form JSON object of environmental conditions (e.g. {\"temperature_degC\": 25}).""", json_schema_extra = { "linkml_meta": {'aliases': ['conditions'],
         'domain_of': ['TestSpec'],
         'slot_uri': 'battinfo:conditions'} })
    ts_setpoints: Optional[str] = Field(default=None, description="""Free-form JSON object of instrument setpoints (e.g. {\"current_A\": 1.5}).""", json_schema_extra = { "linkml_meta": {'aliases': ['setpoints'],
         'domain_of': ['TestSpec'],
         'slot_uri': 'battinfo:setpoints'} })
    ts_termination_criteria: Optional[str] = Field(default=None, description="""Free-form JSON object of termination criteria (e.g. {\"voltage_V\": 2.5, \"time_h\": 10}).""", json_schema_extra = { "linkml_meta": {'aliases': ['termination_criteria'],
         'domain_of': ['TestSpec'],
         'slot_uri': 'battinfo:terminationCriteria'} })
    ts_measurement_outputs: Optional[list[str]] = Field(default=None, description="""List of measurement output descriptors specifying which quantities the cycler should record during this protocol.""", json_schema_extra = { "linkml_meta": {'aliases': ['measurement_outputs'],
         'domain_of': ['TestSpec'],
         'slot_uri': 'battinfo:measurementOutputs'} })


class Test(ConfiguredBaseModel):
    """
    A battery test execution (prov:Activity).  Links to the cell instance tested (hasTestObject) and to the test specification used (prov:used).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'class_uri': 'battery:battery_dca7729a_421a_4921_90cf_9692bb9eb081',
         'from_schema': 'https://w3id.org/battinfo/schema/test'})

    t_id: str = Field(default=..., description="""Canonical IRI for this test execution.""", json_schema_extra = { "linkml_meta": {'aliases': ['id'], 'domain_of': ['Test'], 'slot_uri': 'schema:productID'} })
    t_name: str = Field(default=..., description="""Human-readable label for this test execution.""", json_schema_extra = { "linkml_meta": {'aliases': ['name'], 'domain_of': ['Test'], 'slot_uri': 'schema:name'} })
    t_kind: BatteryTestType = Field(default=..., description="""Test type from the BatteryTestType controlled vocabulary.""", json_schema_extra = { "linkml_meta": {'aliases': ['kind', 'test_type'],
         'domain_of': ['Test'],
         'slot_uri': 'battinfo:testKind'} })
    t_cell_id: str = Field(default=..., description="""IRI of the cell instance that was tested (hasTestObject).""", json_schema_extra = { "linkml_meta": {'aliases': ['cell_id'],
         'domain_of': ['Test'],
         'slot_uri': 'battery:battery_da3b3f28_aaad_4d67_b674_df47e109fb8b'} })
    t_protocol_id: Optional[str] = Field(default=None, description="""IRI of the TestSpec (plan) used for this execution.""", json_schema_extra = { "linkml_meta": {'aliases': ['protocol_id'], 'domain_of': ['Test'], 'slot_uri': 'prov:used'} })
    t_description: Optional[str] = Field(default=None, description="""Free-text description of this specific test run.""", json_schema_extra = { "linkml_meta": {'aliases': ['description'],
         'domain_of': ['Test'],
         'slot_uri': 'schema:description'} })
    t_status: Optional[str] = Field(default=None, description="""Execution status (planned, running, completed, aborted, other).""", json_schema_extra = { "linkml_meta": {'aliases': ['status'],
         'domain_of': ['Test'],
         'slot_uri': 'battinfo:testStatus'} })
    t_protocol: Optional[ProtocolInfo] = Field(default=None, description="""Reference protocol used (may differ from the linked TestSpec).""", json_schema_extra = { "linkml_meta": {'aliases': ['protocol'],
         'domain_of': ['Test'],
         'slot_uri': 'battinfo:protocolReference'} })
    t_instrument: Optional[str] = Field(default=None, description="""Name or model of the test instrument/cycler (hasTestEquipment).""", json_schema_extra = { "linkml_meta": {'aliases': ['instrument'],
         'domain_of': ['Test'],
         'slot_uri': 'battery:battery_df4ff8f1_2cf2_444a_9498_23f533bd295c'} })
    t_started_at: Optional[int] = Field(default=None, description="""Test start timestamp (UNIX epoch).""", json_schema_extra = { "linkml_meta": {'aliases': ['started_at'],
         'domain_of': ['Test'],
         'slot_uri': 'prov:startedAtTime'} })
    t_ended_at: Optional[int] = Field(default=None, description="""Test end timestamp (UNIX epoch).""", json_schema_extra = { "linkml_meta": {'aliases': ['ended_at'], 'domain_of': ['Test'], 'slot_uri': 'prov:endedAtTime'} })
    t_dataset_ids: Optional[list[str]] = Field(default=None, description="""IRIs of dataset records produced by this test.""", json_schema_extra = { "linkml_meta": {'aliases': ['dataset_ids'],
         'domain_of': ['Test'],
         'slot_uri': 'battinfo:hasDataset'} })
    t_conformance: Optional[TestConformance] = Field(default=None, description="""Conformance assessment for this test execution.""", json_schema_extra = { "linkml_meta": {'aliases': ['conformance'],
         'domain_of': ['Test'],
         'slot_uri': 'battinfo:testConformance'} })


class TestConformance(ConfiguredBaseModel):
    """
    Records how closely this test execution conformed to its specification.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'class_uri': 'battinfo:TestConformance',
         'from_schema': 'https://w3id.org/battinfo/schema/test'})

    tc_status: ConformanceStatus = Field(default=..., description="""Conformance status from the ConformanceStatus vocabulary.""", json_schema_extra = { "linkml_meta": {'aliases': ['status'],
         'domain_of': ['TestConformance'],
         'slot_uri': 'battinfo:conformanceStatus'} })
    tc_note: Optional[str] = Field(default=None, description="""Free-text note explaining the conformance assessment.""", json_schema_extra = { "linkml_meta": {'aliases': ['note'],
         'domain_of': ['TestConformance'],
         'slot_uri': 'schema:description'} })
    tc_deviations: Optional[list[Deviation]] = Field(default=None, description="""Individual deviations from the specification.""", json_schema_extra = { "linkml_meta": {'aliases': ['deviations'],
         'domain_of': ['TestConformance'],
         'slot_uri': 'battinfo:deviation'} })


class Deviation(ConfiguredBaseModel):
    """
    A single deviation from the test specification.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'class_uri': 'battinfo:Deviation',
         'from_schema': 'https://w3id.org/battinfo/schema/test'})

    dev_step: Optional[str] = Field(default=None, description="""The protocol step where the deviation occurred.""", json_schema_extra = { "linkml_meta": {'aliases': ['step'],
         'domain_of': ['Deviation'],
         'slot_uri': 'battinfo:deviationStep'} })
    dev_description: Optional[str] = Field(default=None, description="""Description of what deviated from the specification.""", json_schema_extra = { "linkml_meta": {'aliases': ['description'],
         'domain_of': ['Deviation'],
         'slot_uri': 'schema:description'} })
    dev_impact: Optional[str] = Field(default=None, description="""Assessed impact of this deviation on data quality.""", json_schema_extra = { "linkml_meta": {'aliases': ['impact'],
         'domain_of': ['Deviation'],
         'slot_uri': 'battinfo:deviationImpact'} })


class Dataset(ConfiguredBaseModel):
    """
    A battery test dataset: a collection of time-series data files and metadata describing their content, provenance, and access conditions.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'class_uri': 'dcat:Dataset',
         'from_schema': 'https://w3id.org/battinfo/schema/dataset'})

    ds_id: str = Field(default=..., description="""Canonical IRI for this dataset (typically a DOI URL or registry IRI).""", json_schema_extra = { "linkml_meta": {'aliases': ['id'], 'domain_of': ['Dataset'], 'slot_uri': 'schema:url'} })
    ds_name: str = Field(default=..., description="""Human-readable dataset title.""", json_schema_extra = { "linkml_meta": {'aliases': ['name'], 'domain_of': ['Dataset'], 'slot_uri': 'dcterms:title'} })
    ds_description: Optional[str] = Field(default=None, description="""Free-text description of the dataset contents.""", json_schema_extra = { "linkml_meta": {'aliases': ['description'],
         'domain_of': ['Dataset'],
         'slot_uri': 'dcterms:description'} })
    ds_access_url: str = Field(default=..., description="""Landing page or direct download URL for the dataset.""", json_schema_extra = { "linkml_meta": {'aliases': ['access_url'],
         'domain_of': ['Dataset'],
         'slot_uri': 'dcat:accessURL'} })
    ds_same_as: Optional[list[str]] = Field(default=None, description="""Equivalent persistent identifiers (DOI URL, Zenodo record URL, etc.).""", json_schema_extra = { "linkml_meta": {'aliases': ['same_as'], 'domain_of': ['Dataset'], 'slot_uri': 'schema:sameAs'} })
    ds_about: Optional[list[str]] = Field(default=None, description="""IRIs of the cell types, cells, or tests this dataset is about.""", json_schema_extra = { "linkml_meta": {'aliases': ['about'], 'domain_of': ['Dataset'], 'slot_uri': 'dcterms:subject'} })
    ds_license: Optional[str] = Field(default=None, description="""SPDX licence URI (e.g. https://spdx.org/licenses/CC-BY-4.0.html).""", json_schema_extra = { "linkml_meta": {'aliases': ['license'],
         'domain_of': ['Dataset'],
         'slot_uri': 'dcterms:license'} })
    ds_version: Optional[str] = Field(default=None, description="""Dataset version string.""", json_schema_extra = { "linkml_meta": {'aliases': ['version'], 'domain_of': ['Dataset'], 'slot_uri': 'schema:version'} })
    ds_keywords: Optional[list[str]] = Field(default=None, description="""Subject keywords.""", json_schema_extra = { "linkml_meta": {'aliases': ['keywords'],
         'domain_of': ['Dataset'],
         'slot_uri': 'schema:keywords'} })
    ds_creators: list[PersonOrOrganization] = Field(default=..., description="""People and organisations who created the dataset.""", json_schema_extra = { "linkml_meta": {'aliases': ['creators'],
         'domain_of': ['Dataset'],
         'slot_uri': 'dcterms:creator'} })
    ds_publisher: Optional[PersonOrOrganization] = Field(default=None, description="""Organisation responsible for publishing the dataset.""", json_schema_extra = { "linkml_meta": {'aliases': ['publisher'],
         'domain_of': ['Dataset'],
         'slot_uri': 'dcterms:publisher'} })
    ds_funders: Optional[list[PersonOrOrganization]] = Field(default=None, description="""Funding organisations.""", json_schema_extra = { "linkml_meta": {'aliases': ['funders'], 'domain_of': ['Dataset'], 'slot_uri': 'schema:funder'} })
    ds_created_at: Optional[int] = Field(default=None, description="""Dataset creation timestamp (UNIX epoch).""", json_schema_extra = { "linkml_meta": {'aliases': ['created_at'],
         'domain_of': ['Dataset'],
         'slot_uri': 'dcterms:created'} })
    ds_modified_at: Optional[int] = Field(default=None, description="""Last modification timestamp (UNIX epoch).""", json_schema_extra = { "linkml_meta": {'aliases': ['modified_at'],
         'domain_of': ['Dataset'],
         'slot_uri': 'dcterms:modified'} })
    ds_published_at: Optional[int] = Field(default=None, description="""Publication date timestamp (UNIX epoch).""", json_schema_extra = { "linkml_meta": {'aliases': ['published_at'],
         'domain_of': ['Dataset'],
         'slot_uri': 'schema:datePublished'} })
    ds_distributions: list[DataDistribution] = Field(default=..., description="""File distributions available for download.""", json_schema_extra = { "linkml_meta": {'aliases': ['distributions'],
         'domain_of': ['Dataset'],
         'slot_uri': 'dcat:distribution'} })
    ds_is_accessible_for_free: Optional[bool] = Field(default=None, description="""True if the dataset is publicly accessible at no cost.""", json_schema_extra = { "linkml_meta": {'aliases': ['is_accessible_for_free'],
         'domain_of': ['Dataset'],
         'slot_uri': 'schema:isAccessibleForFree'} })
    ds_conditions_of_access: Optional[str] = Field(default=None, description="""Human-readable description of access conditions.""", json_schema_extra = { "linkml_meta": {'aliases': ['conditions_of_access'],
         'domain_of': ['Dataset'],
         'slot_uri': 'dcterms:accessRights'} })
    ds_in_language: Optional[str] = Field(default=None, description="""BCP 47 language tag (e.g. \"en\").""", json_schema_extra = { "linkml_meta": {'aliases': ['in_language'],
         'domain_of': ['Dataset'],
         'slot_uri': 'dcterms:language'} })


class DataDistribution(ConfiguredBaseModel):
    """
    A specific downloadable file distribution of the dataset.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'class_uri': 'dcat:Distribution',
         'from_schema': 'https://w3id.org/battinfo/schema/dataset'})

    dd_content_url: Optional[str] = Field(default=None, description="""Direct download URL for this distribution file.""", json_schema_extra = { "linkml_meta": {'aliases': ['content_url'],
         'domain_of': ['DataDistribution'],
         'slot_uri': 'dcat:downloadURL'} })
    dd_encoding_format: Optional[str] = Field(default=None, description="""IANA media type (e.g. \"application/parquet\", \"text/csv\").""", json_schema_extra = { "linkml_meta": {'aliases': ['encoding_format'],
         'domain_of': ['DataDistribution'],
         'slot_uri': 'dcat:mediaType'} })
    dd_byte_size: Optional[int] = Field(default=None, description="""File size in bytes.""", json_schema_extra = { "linkml_meta": {'aliases': ['byte_size'],
         'domain_of': ['DataDistribution'],
         'slot_uri': 'dcat:byteSize'} })
    dd_checksum: Optional[Checksum] = Field(default=None, description="""File integrity checksum.""", json_schema_extra = { "linkml_meta": {'aliases': ['checksum'],
         'domain_of': ['DataDistribution'],
         'slot_uri': 'spdx:checksum'} })
    dd_name: Optional[str] = Field(default=None, description="""Filename within the distribution.""", json_schema_extra = { "linkml_meta": {'aliases': ['name'],
         'domain_of': ['DataDistribution'],
         'slot_uri': 'schema:name'} })
    dd_description: Optional[str] = Field(default=None, description="""Free-text description of this distribution.""", json_schema_extra = { "linkml_meta": {'aliases': ['description'],
         'domain_of': ['DataDistribution'],
         'slot_uri': 'schema:description'} })


class Checksum(ConfiguredBaseModel):
    """
    File integrity checksum.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'class_uri': 'spdx:Checksum',
         'from_schema': 'https://w3id.org/battinfo/schema/dataset'})

    cs_algorithm: Optional[str] = Field(default=None, description="""Hash algorithm identifier (e.g. \"sha256\", \"md5\").""", json_schema_extra = { "linkml_meta": {'aliases': ['algorithm'],
         'domain_of': ['Checksum'],
         'slot_uri': 'spdx:checksumAlgorithm'} })
    cs_value: Optional[str] = Field(default=None, description="""Hex-encoded hash value.""", json_schema_extra = { "linkml_meta": {'aliases': ['value'],
         'domain_of': ['Checksum'],
         'slot_uri': 'spdx:checksumValue'} })


class PersonOrOrganization(ConfiguredBaseModel):
    """
    A person or organisation acting as creator, publisher, or funder.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://w3id.org/battinfo/schema/dataset'})

    poo_name: str = Field(default=..., description="""Full name.""", json_schema_extra = { "linkml_meta": {'aliases': ['name'],
         'domain_of': ['PersonOrOrganization'],
         'slot_uri': 'schema:name'} })
    poo_orcid: Optional[str] = Field(default=None, description="""ORCID URI (https://orcid.org/...).""", json_schema_extra = { "linkml_meta": {'aliases': ['orcid'],
         'domain_of': ['PersonOrOrganization'],
         'slot_uri': 'schema:identifier'} })
    poo_ror: Optional[str] = Field(default=None, description="""ROR URI (https://ror.org/...).""", json_schema_extra = { "linkml_meta": {'aliases': ['ror'],
         'domain_of': ['PersonOrOrganization'],
         'slot_uri': 'schema:identifier'} })
    poo_type: Optional[str] = Field(default=None, description="""Type hint: \"Person\" or \"Organization\" (schema.org class name).""", json_schema_extra = { "linkml_meta": {'aliases': ['type'],
         'domain_of': ['PersonOrOrganization'],
         'slot_uri': 'schema:additionalType'} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
SpecValue.model_rebuild()
Provenance.model_rebuild()
ProtocolInfo.model_rebuild()
CellType.model_rebuild()
Organization.model_rebuild()
SpecSet.model_rebuild()
CellInstance.model_rebuild()
TestSpec.model_rebuild()
Test.model_rebuild()
TestConformance.model_rebuild()
Deviation.model_rebuild()
Dataset.model_rebuild()
DataDistribution.model_rebuild()
Checksum.model_rebuild()
PersonOrOrganization.model_rebuild()
