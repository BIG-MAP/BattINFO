from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from battinfo.bundle import CellInstance, CellSpecification, CellType, ProvenanceInfo, Test, TestProtocol

if TYPE_CHECKING:
    from battinfo.workspace import Workspace

UID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"

GENERIC_TYPES = {
    "Additive",
    "BatteryTest",
    "Binder",
    "CellCan",
    "CellLid",
    "CoinCell",
    "ConductiveAdditive",
    "CurrentCollector",
    "Electrode",
    "ElectrodeCoating",
    "ElectrochemicalCell",
    "ElectrochemicalHalfCell",
    "Measurement",
    "OrganicElectrolyte",
    "Separator",
    "Solute",
    "Solvent",
    "Spacer",
    "Spring",
}

TYPE_LABEL_MAP = {
    "Aluminium": "Aluminium",
    "CarbonBlack": "Carbon black",
    "Copper": "Copper",
    "EthylMethylCarbonate": "EMC",
    "EthyleneCarbonate": "EC",
    "FluoroethyleneCarbonate": "FEC",
    "GlassFibreSeparator": "Glass fibre",
    "Graphite": "Graphite",
    "LithiumBisfluorosulfonylimide": "LiFSI",
    "LithiumBistrifluoromethanesulfonylimide": "LiTFSI",
    "LithiumElectrode": "Li-metal",
    "LithiumHexafluorophosphate": "LiPF6",
    "LithiumIronPhosphate": "LFP",
    "LithiumNickelManganeseCobaltOxide": "NMC",
    "LithiumTitanate": "LTO",
    "Polypropylene": "PP",
    "PolyvinylideneFluoride": "PVDF",
    "StainlessSteel": "Stainless steel",
    "Tantalum": "Tantalum",
    "TrisTrimethylsilyPhosphite": "TMSPi",
    "VinyleneCarbonate": "VC",
}

BASIS_TYPE_MAP = {
    "Graphite": "graphite",
    "LithiumCobaltOxide": "LCO",
    "LithiumElectrode": "Li-metal",
    "LithiumIronPhosphate": "LFP",
    "LithiumManganeseOxide": "LMO",
    "LithiumNickelCobaltAluminiumOxide": "NCA",
    "LithiumNickelManganeseCobaltOxide": "NMC",
    "LithiumTitanate": "LTO",
    "ManganeseDioxide": "MnO2",
    "Silicon": "silicon",
}

# Maps rdfs:comment strings (used when @type is absent) to basis labels.
# Keys are lowercased substrings for case-insensitive matching.
_COMMENT_BASIS_MAP: dict[str, str] = {
    "lithiumnickelcobaltmanganeseoxide": "NMC",
    "lithiumironphosphate": "LFP",
    "lithiumcobaltoxide": "LCO",
    "lithiumtitanate": "LTO",
    "graphite": "graphite",
    "lithiumnickelcobaltmanganeseo": "NMC",  # truncated variants
}

ELECTROLYTE_FAMILY_MAP = {
    "AqueousElectrolyte": "aqueous",
    "GelElectrolyte": "gel",
    "HybridElectrolyte": "hybrid",
    "IonicLiquidElectrolyte": "ionic_liquid",
    "OrganicElectrolyte": "organic",
    "SolidElectrolyte": "solid",
}

UNIT_MAP = {
    "emmo:CelsiusTemperature": "°C",
    "emmo:DegreeCelsius": "°C",
    "emmo:GramPerCubicCentiMetre": "g/cm3",
    "emmo:Hertz": "Hz",
    "emmo:Hour": "h",
    "emmo:MilliAmpere": "mA",
    "emmo:MilliAmpereHourPerSquareCentiMetre": "mAh/cm2",
    "emmo:MilliAmperePerSquareCentiMetre": "mA/cm2",
    "emmo:MicroMetre": "um",
    "emmo:Second": "s",
    "emmo:UnitOne": "1",
    "emmo:Volt": "V",
    "unit:MilliA-HR-PER-GM": "mAh/g",
    "unit:MOL-PER-L": "mol/L",
    "unit:MicroL": "uL",
    "unit:MilliGM-PER-CentiM2": "mg/cm2",
    "unit:MilliM": "mm",
    "unit:MilliPA-SEC": "mPa.s",
    "unit:MilliS-PER-CentiM": "mS/cm",
    "unit:PERCENT": "%",
}

PROPERTY_TYPE_MAP = {
    "AmountConcentration": "concentration",
    "CalenderedCoatingThickness": "thickness",
    "CelsiusTemperature": "temperature",
    "D50ParticleSize": "d50_particle_size",
    "Density": "density",
    "Diameter": "diameter",
    "DynamicViscosity": "viscosity",
    "ElectrolyticConductivity": "conductivity",
    "MassFraction": "mass_fraction",
    "MassLoading": "loading",
    "Porosity": "porosity",
    "Thickness": "thickness",
    "Tortuosity": "tortuosity",
    "Volume": "fill_volume",
    "VolumeFraction": "volume_fraction",
}


@dataclass(slots=True)
class ConverterImportResult:
    specification: CellSpecification
    record: dict[str, Any]
    warnings: list[str]
    test_protocols: list[dict[str, Any]] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ConverterImportPackage:
    specification: CellSpecification
    cell_type: CellType
    cell_instance: CellInstance | None
    test_protocols: list[TestProtocol] = field(default_factory=list)
    tests: list[Test] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    record: dict[str, Any] | None = None

    def objects(self) -> list[Any]:
        objects: list[Any] = [self.specification, self.cell_type]
        if self.cell_instance is not None:
            objects.append(self.cell_instance)
        objects.extend(self.test_protocols)
        objects.extend(self.tests)
        return objects

    def add_to_workspace(self, workspace: "Workspace") -> "Workspace":
        workspace.add(*self.objects())
        return workspace


def _normalize_to_coin_cell(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (coin_cell_node, battery_test_node) from any known converter document shape.

    Handles three shapes produced by different converter versions:
    - CoinCell at root (old fixture format)
    - BatteryTest at root with hasTestObject (v3.x kiye format)
    - @graph array wrapping a BatteryTest (v1.1.x Dataset-rocrate format)
    """
    # Shape 1: @graph wrapper (v1.1.x)
    if "@graph" in payload:
        graph = payload["@graph"]
        if isinstance(graph, list):
            for node in graph:
                if isinstance(node, Mapping) and "BatteryTest" in _node_types(node):
                    payload = dict(node)
                    break
            else:
                payload = dict(graph[0]) if graph else payload

    # Shape 2: BatteryTest wrapper with hasTestObject (v3.x and v1.1.x after above)
    if "BatteryTest" in _node_types(payload):
        test_object = _mapping_or_none(payload.get("hasTestObject"))
        if test_object is not None:
            return test_object, payload

    # Shape 3: CoinCell already at root (legacy fixtures)
    return payload, payload


def _extract_product_id(value: Any) -> str | None:
    """Extract a single product ID, preferring empa__ccid* when value is a list."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        # Prefer the empa__ccid* canonical identifier
        for item in value:
            if isinstance(item, str) and item.startswith("empa__"):
                return item
        # Fall back to first string entry
        for item in value:
            if isinstance(item, str):
                return item
    return _string_value(value)


def import_converter_jsonld(
    source: Mapping[str, Any] | str | Path,
    *,
    id: str | None = None,
    manufacturer: str | None = None,
    model: str | None = None,
    chemistry: str | None = None,
    schema_version: str = "1.0.0",
) -> ConverterImportResult:
    return import_converter_jsonld_record(
        source,
        id=id,
        manufacturer=manufacturer,
        model=model,
        chemistry=chemistry,
        schema_version=schema_version,
    )


def import_converter_jsonld_record(
    source: Mapping[str, Any] | str | Path,
    *,
    id: str | None = None,
    manufacturer: str | None = None,
    model: str | None = None,
    chemistry: str | None = None,
    schema_version: str = "1.0.0",
) -> ConverterImportResult:
    raw_payload, source_file = _load_source(source)
    warnings: list[str] = []

    payload, battery_test_node = _normalize_to_coin_cell(raw_payload)

    root_types = _node_types(payload)
    if "CoinCell" not in root_types:
        warnings.append("Expected a BattINFO Converter coin-cell export with root @type CoinCell.")

    root_comments = _comment_list(payload.get("rdfs:comment"))
    converter_version = _extract_prefixed_comment(root_comments, "BattINFO Converter version:")
    converter_schema_version = _string_value(payload.get("schema:version"))
    assembly_date = _string_value(payload.get("schema:dateCreated"))
    retrieved_at = _parse_converter_date(assembly_date)

    imported_manufacturer = manufacturer or _agent_name(payload.get("schema:manufacturer")) or "unknown"
    imported_model = model or _extract_product_id(payload.get("schema:productID"))
    if imported_model is None:
        imported_model = _infer_size_code(payload.get("hasCase")) or "converter-coin-cell"
        warnings.append(
            "Converter JSON-LD did not expose schema:productID; BattINFO imported a fallback model label."
        )
    elif model is None:
        warnings.append(
            "BattINFO imported schema:productID as specification.model because the converter export does not include a distinct reusable model field."
        )
    if manufacturer is None:
        warnings.append(
            "BattINFO imported schema:manufacturer as specification.manufacturer; this is likely the assembly organization rather than a reusable product manufacturer."
        )

    positive_electrode_node = _mapping_or_none(payload.get("hasPositiveElectrode"))
    negative_electrode_node = _mapping_or_none(payload.get("hasNegativeElectrode"))
    electrolyte_node = _mapping_or_none(payload.get("hasElectrolyte"))
    separator_node = _mapping_or_none(payload.get("hasSeparator"))

    positive_basis = _infer_electrode_basis(positive_electrode_node) or "unknown"
    negative_basis = _infer_electrode_basis(negative_electrode_node) or "unknown"

    imported_chemistry = chemistry or _infer_chemistry(positive_basis, negative_basis)
    if chemistry is None and imported_chemistry == "unknown":
        warnings.append(
            "Converter JSON-LD did not expose a clean chemistry label; BattINFO imported chemistry='unknown'."
        )

    size_code = _infer_size_code(payload.get("hasCase"))
    if size_code is None:
        warnings.append("Converter JSON-LD did not expose a recognizable coin-cell size code.")

    assembly_comment = _extract_prefixed_comment(root_comments, "Cell assembly sequence:")
    construction: dict[str, Any] = {
        "assembly_type": "stacked",
        "layering": "not_applicable",
    }
    if assembly_comment is not None:
        sequence = [item.strip() for item in assembly_comment.split(",") if item.strip()]
        if sequence:
            construction["assembly_sequence"] = sequence
        construction["comment"] = assembly_comment

    spec_id = id or _entity_iri(
        "cell-type",
        "::".join(
            [
                imported_manufacturer,
                imported_model,
                "coin",
                imported_chemistry,
                size_code or "",
            ]
        ),
    )

    instance_serial = _extract_product_id(payload.get("schema:productID"))
    instance_name = instance_serial or imported_model
    instances: list[dict[str, Any]] = []
    if instance_name is not None:
        instance_seed = "::".join([instance_name, assembly_date or "", imported_manufacturer])
        instance_entry: dict[str, Any] = {
            "id": _entity_iri("cell", instance_seed),
            "name": instance_name,
            "comment": "Imported from BattINFO Converter JSON-LD.",
        }
        if instance_serial is not None:
            instance_entry["serial_number"] = instance_serial
        instances.append(instance_entry)

    positive_electrode = _map_electrode(positive_electrode_node)
    negative_electrode = _map_electrode(negative_electrode_node)
    electrolyte = _map_electrolyte(electrolyte_node, warnings)
    separator = _map_separator(separator_node)
    coin_hardware = _map_coin_hardware(payload)

    specification_comments = ["Imported from BattINFO Converter JSON-LD."]
    if converter_schema_version is not None:
        specification_comments.append(f"Converter coin-cell schema version: {converter_schema_version}.")

    top_level_comments = list(root_comments)
    hardware_comment = _hardware_summary_comment(payload)
    if hardware_comment is not None and not coin_hardware:
        top_level_comments.append(hardware_comment)
        warnings.append(
            "Converter-specific coin-cell hardware metadata is still preserved only as comments because it could not be mapped into BattINFO coin_hardware."
        )

    source_comment = "Imported from BattINFO Converter JSON-LD."
    if converter_version is not None or converter_schema_version is not None:
        fragments = []
        if converter_version is not None:
            fragments.append(f"app={converter_version}")
        if converter_schema_version is not None:
            fragments.append(f"coin-schema={converter_schema_version}")
        source_comment = f"{source_comment} {'; '.join(fragments)}"

    specification = CellSpecification(
        schema_version=schema_version,
        id=spec_id,
        manufacturer=imported_manufacturer,
        model=imported_model,
        format="coin",
        chemistry=imported_chemistry,
        positive_electrode_basis=positive_basis,
        negative_electrode_basis=negative_basis,
        size_code=size_code,
        construction=construction,
        positive_electrode=positive_electrode,
        negative_electrode=negative_electrode,
        electrolyte=electrolyte,
        separator=separator,
        coin_hardware=coin_hardware,
        specification_comment=specification_comments,
        source=ProvenanceInfo(
            type="converter-jsonld",
            name="BattINFO Converter",
            file=source_file,
            retrieved_at=retrieved_at,
            workflow_version=_workflow_version(converter_version, converter_schema_version),
            comment=source_comment,
        ),
        comment=[],
    )

    record = specification.to_library_record()
    if instances:
        record["instances"] = instances
    if top_level_comments:
        record["comment"] = top_level_comments

    instance_id = instances[0]["id"] if instances else None
    instance_label = instances[0]["name"] if instances else imported_model
    test_protocols, tests = _extract_procedure_records(
        positive_electrode_node,
        negative_electrode_node,
        instance_id=instance_id,
        instance_label=instance_label,
        source_file=source_file,
        retrieved_at=retrieved_at,
        workflow_version=_workflow_version(converter_version, converter_schema_version),
        schema_version=schema_version,
        warnings=warnings,
    )

    return ConverterImportResult(
        specification=CellSpecification.from_library_record(record),
        record=record,
        warnings=warnings,
        test_protocols=test_protocols,
        tests=tests,
    )


def import_converter_package(
    source: Mapping[str, Any] | str | Path,
    *,
    id: str | None = None,
    manufacturer: str | None = None,
    model: str | None = None,
    chemistry: str | None = None,
    schema_version: str = "1.0.0",
) -> ConverterImportPackage:
    imported = import_converter_jsonld_record(
        source,
        id=id,
        manufacturer=manufacturer,
        model=model,
        chemistry=chemistry,
        schema_version=schema_version,
    )
    specification = imported.specification
    cell_type = CellType.from_cell_specification(specification)
    if cell_type.source.type not in {"datasheet", "label", "catalog", "manual", "other"}:
        cell_type.source.type = "other"
        existing = list(cell_type.comment)
        existing.append("Source type normalized from converter-jsonld during converter package import.")
        cell_type.comment = existing

    cell_instance: CellInstance | None = None
    instances = imported.record.get("instances")
    if isinstance(instances, list) and instances:
        first = instances[0]
        if isinstance(first, Mapping):
            cell_instance = CellInstance(
                schema_version=schema_version,
                id=first.get("id"),
                name=first.get("name"),
                cell_type=cell_type,
                serial_number=first.get("serial_number"),
                source=ProvenanceInfo(
                    type=specification.source.type if specification.source.type in {"manual", "lab", "simulation", "other"} else "other",
                    file=specification.source.file,
                    url=specification.source.url,
                    citation=specification.source.citation,
                    retrieved_at=specification.source.retrieved_at,
                    workflow_version=specification.source.workflow_version,
                ),
                comment=[str(first["comment"])] if isinstance(first.get("comment"), str) else [],
            )

    protocol_objects = [TestProtocol.from_record(item) for item in imported.test_protocols]
    protocols_by_id = {item.id: item for item in protocol_objects if item.id is not None}
    test_objects = [Test.from_record(item) for item in imported.tests]
    for test in test_objects:
        if cell_instance is not None:
            test.cell = cell_instance
            test.cell_instance_id = cell_instance.id
        if test.protocol_id is not None and test.protocol_id in protocols_by_id:
            test.protocol_entity = protocols_by_id[test.protocol_id]

    return ConverterImportPackage(
        specification=specification,
        cell_type=cell_type,
        cell_instance=cell_instance,
        test_protocols=protocol_objects,
        tests=test_objects,
        warnings=list(imported.warnings),
        record=imported.record,
    )


def _load_source(source: Mapping[str, Any] | str | Path) -> tuple[dict[str, Any], str]:
    if isinstance(source, Mapping):
        return copy.deepcopy(dict(source)), "converter-export.jsonld"
    path = Path(source)
    return json.loads(path.read_text(encoding="utf-8")), path.name


def _workflow_version(converter_version: str | None, schema_version: str | None) -> str | None:
    parts = []
    if converter_version is not None:
        parts.append(f"converter-{converter_version}")
    if schema_version is not None:
        parts.append(f"coin-schema-{schema_version}")
    if not parts:
        return None
    return "::".join(parts)


def _mapping_or_none(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _node_types(node: Any) -> list[str]:
    if not isinstance(node, Mapping):
        return []
    raw = node.get("@type")
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(item) for item in raw if isinstance(item, (str, int, float))]
    return []


def _preferred_type(node: Any, *, exclude: set[str] | None = None) -> str | None:
    excluded = GENERIC_TYPES if exclude is None else GENERIC_TYPES | exclude
    for item in _node_types(node):
        if item not in excluded:
            return item
    return None


def _label_for_type(type_name: str | None) -> str | None:
    if type_name is None:
        return None
    return TYPE_LABEL_MAP.get(type_name, type_name)


def _comment_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, (str, int, float))]
    return []


def _extract_prefixed_comment(comments: list[str], prefix: str) -> str | None:
    for comment in comments:
        if comment.startswith(prefix):
            return comment[len(prefix) :].strip()
    return None


def _string_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, Mapping):
        for key in ("schema:name", "rdfs:comment", "@id", "@type"):
            nested = value.get(key)
            if isinstance(nested, str):
                return nested
    return None


def _agent_name(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return _string_value(value)
    schema_name = value.get("schema:name")
    if isinstance(schema_name, str):
        return schema_name
    preferred = _preferred_type(value, exclude={"schema:Organization", "schema:Person"})
    if preferred is not None:
        return _label_for_type(preferred)
    comment = value.get("rdfs:comment")
    if isinstance(comment, str):
        return comment
    return None


def _apply_component_metadata(out: dict[str, Any], node: Mapping[str, Any]) -> None:
    manufacturer = _agent_name(node.get("schema:manufacturer"))
    if manufacturer is not None:
        out["manufacturer"] = manufacturer
    supplier = _agent_name(node.get("schema:supplier"))
    if supplier is not None:
        out["supplier"] = supplier
    product_id = _string_value(node.get("schema:productID"))
    if product_id is not None:
        out["product_id"] = product_id


def _property_name(type_name: str, unit: str | None) -> str | None:
    if type_name == "RatedCapacity":
        if unit == "mAh/cm2":
            return "rated_areal_discharge_capacity"
        if unit == "mAh/g":
            return "rated_specific_discharge_capacity"
    return PROPERTY_TYPE_MAP.get(type_name)


def _map_unit(value: Any) -> str | None:
    if isinstance(value, str):
        return UNIT_MAP.get(value, value)
    return None


def _quantity_value(node: Mapping[str, Any]) -> Any:
    numerical = node.get("hasNumericalPart")
    if isinstance(numerical, Mapping):
        if "hasNumberValue" in numerical:
            return numerical.get("hasNumberValue")
        if "hasNumericalValue" in numerical:
            return numerical.get("hasNumericalValue")
    if "hasStringValue" in node:
        return node.get("hasStringValue")
    return None


def _quantity_text(node: Mapping[str, Any]) -> dict[str, Any] | None:
    value = _quantity_value(node)
    if value is None:
        return None
    quantity: dict[str, Any] = {"value": value}
    unit = _map_unit(node.get("hasMeasurementUnit"))
    if unit is not None:
        quantity["unit"] = unit
    return quantity


def _mapped_properties(value: Any) -> dict[str, dict[str, Any]]:
    items: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        items = [value]
    elif isinstance(value, list):
        items = [item for item in value if isinstance(item, Mapping)]
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        type_name = _preferred_type(item, exclude=set())
        if type_name is None:
            continue
        unit = _map_unit(item.get("hasMeasurementUnit"))
        property_name = _property_name(type_name, unit)
        quantity_value = _quantity_value(item)
        if property_name is None or quantity_value is None:
            continue
        quantity: dict[str, Any] = {"value": quantity_value}
        if unit is not None:
            quantity["unit"] = unit
        out[property_name] = quantity
    return out


def _component_comment(node: Mapping[str, Any]) -> str | None:
    fragments: list[str] = []
    formula = None
    measured = node.get("hasMeasuredProperty")
    if isinstance(measured, list):
        for item in measured:
            if isinstance(item, Mapping) and _preferred_type(item, exclude=set()) == "molecularFormula":
                formula = _string_value(item)
                break
    elif isinstance(measured, Mapping) and _preferred_type(measured, exclude=set()) == "molecularFormula":
        formula = _string_value(measured)
    if formula is not None:
        fragments.append(f"formula: {formula}")
    if not fragments:
        return None
    return "; ".join(fragments)


def _map_material_component(node: Any, *, wrapper_types: set[str] | None = None) -> dict[str, Any] | None:
    if not isinstance(node, Mapping):
        return None
    preferred = _preferred_type(node, exclude=wrapper_types or set())
    if preferred is None:
        # Fallback: material described only via rdfs:comment (e.g. NMC without @type)
        comment_name = _string_value(node.get("rdfs:comment"))
        if comment_name is None:
            return None
        preferred = comment_name
    component: dict[str, Any] = {
        "name": _label_for_type(preferred) or preferred,
    }
    _apply_component_metadata(component, node)
    properties = _mapped_properties(node.get("hasMeasuredProperty"))
    if properties:
        component["property"] = properties
    comment = _component_comment(node)
    if comment is not None:
        component["comment"] = comment
    return component


def _map_component_group(value: Any, *, wrapper_types: set[str] | None = None) -> list[dict[str, Any]]:
    if isinstance(value, list):
        out = []
        for item in value:
            component = _map_material_component(item, wrapper_types=wrapper_types)
            if component is not None:
                out.append(component)
        return out
    component = _map_material_component(value, wrapper_types=wrapper_types)
    return [component] if component is not None else []


def _map_electrode(node: dict[str, Any] | None) -> dict[str, Any] | None:
    if node is None:
        return None
    out: dict[str, Any] = {}

    collector_node = _mapping_or_none(node.get("hasCurrentCollector"))
    if collector_node is not None:
        collector_name = _label_for_type(
            _preferred_type(collector_node, exclude={"CurrentCollector"})
        )
        collector: dict[str, Any] = {}
        if collector_name is not None:
            collector["name"] = collector_name
        _apply_component_metadata(collector, collector_node)
        collector_properties = _mapped_properties(collector_node.get("hasMeasuredProperty"))
        if collector_properties:
            collector["property"] = collector_properties
        collector_comment = _component_comment(collector_node)
        if collector_comment is not None:
            collector["comment"] = collector_comment
        if collector:
            out["current_collector"] = collector

    coating_node = _mapping_or_none(node.get("hasCoating"))
    if coating_node is not None:
        coating: dict[str, Any] = {}
        component_groups: dict[str, list[dict[str, Any]]] = {}

        active = _map_component_group(coating_node.get("hasActiveMaterial"))
        if active:
            component_groups["active_material"] = active
        binder = _map_component_group(coating_node.get("hasBinder"), wrapper_types={"Binder"})
        if binder:
            component_groups["binder"] = binder
        additive = _map_component_group(
            coating_node.get("hasConductiveAdditive"),
            wrapper_types={"ConductiveAdditive"},
        )
        if additive:
            component_groups["additive"] = additive
        if component_groups:
            coating["component"] = component_groups
        _apply_component_metadata(coating, coating_node)

        coating_properties = _mapped_properties(coating_node.get("hasMeasuredProperty"))
        if coating_properties:
            coating["property"] = coating_properties
        coating_comment = _component_comment(coating_node)
        if coating_comment is not None:
            coating["comment"] = coating_comment
        if coating:
            out["coating"] = coating

    electrode_properties = _mapped_properties(node.get("hasMeasuredProperty"))
    _apply_component_metadata(out, node)
    if electrode_properties:
        out["property"] = electrode_properties
    electrode_comment = _component_comment(node)
    if electrode_comment is not None:
        out["comment"] = electrode_comment

    return out or None


def _first_nonzero_component(value: Any) -> dict[str, Any] | None:
    items = value if isinstance(value, list) else [value]
    fallback = None
    for item in items:
        if not isinstance(item, Mapping):
            continue
        component = _map_material_component(item)
        if component is None:
            continue
        if fallback is None:
            fallback = component
        concentration = component.get("property", {}).get("concentration", {})
        numeric = concentration.get("value")
        if isinstance(numeric, (int, float)) and numeric > 0:
            return component
    return fallback


def _map_electrolyte(node: dict[str, Any] | None, warnings: list[str]) -> dict[str, Any] | None:
    if node is None:
        return None
    out: dict[str, Any] = {}
    family = "unknown"
    for type_name in _node_types(node):
        if type_name in ELECTROLYTE_FAMILY_MAP:
            family = ELECTROLYTE_FAMILY_MAP[type_name]
            break
    out["family"] = family
    _apply_component_metadata(out, node)

    solvent_node = _mapping_or_none(node.get("hasSolvent"))
    if solvent_node is not None:
        components = _map_component_group(solvent_node.get("hasConstituent"))
        if components:
            solvent_mixture: dict[str, Any] = {"component": components}
            _apply_component_metadata(solvent_mixture, solvent_node)
            out["solvent_mixture"] = solvent_mixture

    solute_node = _mapping_or_none(node.get("hasSolute"))
    if solute_node is not None:
        salt_component = _first_nonzero_component(solute_node.get("hasConstituent"))
        if salt_component is not None:
            salt: dict[str, Any] = {"name": salt_component["name"]}
            for key in ("manufacturer", "supplier", "product_id"):
                if key in salt_component:
                    salt[key] = salt_component[key]
            if "property" in salt_component:
                salt["property"] = salt_component["property"]
            if "comment" in salt_component:
                salt["comment"] = salt_component["comment"]
            out["salt"] = salt

        raw_solutes = solute_node.get("hasConstituent")
        raw_solute_count = len(raw_solutes) if isinstance(raw_solutes, list) else (1 if isinstance(raw_solutes, Mapping) else 0)
        if raw_solute_count > 1:
            warnings.append(
                "Converter electrolyte export included multiple solutes; BattINFO imported the first non-zero solute as electrolyte.salt."
            )

        additive_node = _mapping_or_none(solute_node.get("hasAdditive"))
        if additive_node is not None:
            additives = _map_component_group(additive_node.get("hasConstituent"), wrapper_types={"Additive"})
            if additives:
                out["additive"] = additives

    electrolyte_properties = _mapped_properties(node.get("hasMeasuredProperty"))
    if electrolyte_properties:
        out["property"] = electrolyte_properties
    electrolyte_comment = _component_comment(node)
    if electrolyte_comment is not None:
        out["comment"] = electrolyte_comment
    return out or None


def _map_separator(node: dict[str, Any] | None) -> dict[str, Any] | None:
    if node is None:
        return None
    out: dict[str, Any] = {}

    # Primary: non-Separator @type on the node itself (e.g. GlassFibreSeparator)
    material = _label_for_type(_preferred_type(node, exclude={"Separator"}))

    # Secondary: hasProperPart carries material layer types (e.g. PP/PE trilayer)
    if material is None:
        proper_parts = node.get("hasProperPart")
        if isinstance(proper_parts, list):
            part_labels = [
                _label_for_type(_preferred_type(p, exclude=set()))
                for p in proper_parts
                if isinstance(p, Mapping)
            ]
            part_labels = [lb for lb in part_labels if lb]
            if part_labels:
                # Deduplicate while preserving order
                seen: set[str] = set()
                unique = [lb for lb in part_labels if not (lb in seen or seen.add(lb))]  # type: ignore[func-returns-value]
                material = "/".join(unique)

    if material is not None:
        out["material"] = material

    _apply_component_metadata(out, node)
    separator_properties = _mapped_properties(node.get("hasMeasuredProperty"))
    if separator_properties:
        out["property"] = separator_properties
    separator_comment = _component_comment(node)
    if separator_comment is not None:
        out["comment"] = separator_comment
    return out or None


def _basis_from_comment(node: Mapping[str, Any]) -> str | None:
    """Extract electrode basis from rdfs:comment when @type is absent (e.g. NMC active material)."""
    comment = _string_value(node.get("rdfs:comment")) or ""
    normalized = comment.lower().replace(" ", "").replace("-", "")
    for key, basis in _COMMENT_BASIS_MAP.items():
        if key in normalized:
            return basis
    return None


def _infer_electrode_basis(node: dict[str, Any] | None) -> str | None:
    if node is None:
        return None
    coating = _mapping_or_none(node.get("hasCoating"))
    if coating is None:
        return None
    active = coating.get("hasActiveMaterial")
    candidates = active if isinstance(active, list) else [active]
    for item in candidates:
        if not isinstance(item, Mapping):
            continue
        preferred = _preferred_type(item, exclude=set())
        if preferred in BASIS_TYPE_MAP:
            return BASIS_TYPE_MAP[preferred]
        # Fallback: rdfs:comment carries the material name when @type is absent
        basis = _basis_from_comment(item)
        if basis is not None:
            return basis
    return None


def _infer_chemistry(positive_basis: str, negative_basis: str) -> str:
    positive = positive_basis.lower()
    negative = negative_basis.lower()
    if negative == "li-metal" and positive == "mno2":
        return "Li-primary"
    if negative in {"graphite", "graphite-silicon", "silicon"} and positive in {"nmc", "lfp", "lco", "lmo", "nca"}:
        return "Li-ion"
    if negative == "li-metal" and positive not in {"unknown", ""}:
        return "Li-metal"
    return "unknown"


def _infer_size_code(case_node: Any) -> str | None:
    if not isinstance(case_node, Mapping):
        return None
    for item in _node_types(case_node):
        if len(item) >= 2 and item[0] in {"R", "P"} and any(char.isdigit() for char in item[1:]):
            return item
    product_id = _string_value(case_node.get("schema:productID"))
    if product_id is None:
        return None
    for token in str(product_id).replace(",", " ").split():
        if len(token) >= 2 and token[0] in {"R", "P"} and any(char.isdigit() for char in token[1:]):
            return token
        if token.isdigit():
            return f"R{token}"
    return None


def _hardware_summary_comment(payload: Mapping[str, Any]) -> str | None:
    fragments: list[str] = []

    case_node = _mapping_or_none(payload.get("hasCase"))
    if case_node is not None:
        case_types = [item for item in _node_types(case_node) if item not in {"CoinCell"}]
        if case_types:
            fragments.append(f"case={', '.join(case_types)}")

    constituents = payload.get("hasConstituent")
    items = constituents if isinstance(constituents, list) else [constituents]
    hardware_types: list[str] = []
    for item in items:
        if isinstance(item, Mapping):
            preferred = _preferred_type(item, exclude=set())
            if preferred is not None:
                hardware_types.append(preferred)
    if hardware_types:
        fragments.append(f"extra_hardware={', '.join(hardware_types)}")

    if not fragments:
        return None
    return "Converter-specific hardware metadata not yet modeled in BattINFO descriptor core: " + "; ".join(fragments) + "."


def _case_material(case_node: Mapping[str, Any]) -> str | None:
    for item in _node_types(case_node):
        if len(item) >= 2 and item[0] in {"R", "P"} and any(char.isdigit() for char in item[1:]):
            continue
        return _label_for_type(item) or item
    return None


def _component_from_hardware_node(node: Any, *, expected_type: str) -> dict[str, Any] | None:
    if not isinstance(node, Mapping):
        return None
    if expected_type not in _node_types(node):
        return None
    out: dict[str, Any] = {}
    _apply_component_metadata(out, node)
    properties = _mapped_properties(node.get("hasMeasuredProperty"))
    if properties:
        out["property"] = properties
    comment = _component_comment(node)
    if comment is not None:
        out["comment"] = comment
    return out or None


def _map_case_part(node: Any, *, expected_types: set[str]) -> dict[str, Any] | None:
    if not isinstance(node, Mapping):
        return None
    if not expected_types.intersection(_node_types(node)):
        return None
    out: dict[str, Any] = {}
    material = _label_for_type(_preferred_type(node, exclude=expected_types))
    if material is not None:
        out["material"] = material
    _apply_component_metadata(out, node)
    properties = _mapped_properties(node.get("hasMeasuredProperty"))
    if properties:
        out["property"] = properties
    coating = node.get("hasCoating")
    if isinstance(coating, Mapping):
        coating_material = _string_value(coating.get("schema:material")) or _label_for_type(_preferred_type(coating))
        if coating_material is not None:
            out["coating"] = coating_material
    comment = _component_comment(node)
    if comment is not None:
        out["comment"] = comment
    return out or None


def _map_coin_hardware(payload: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}

    case_node = _mapping_or_none(payload.get("hasCase"))
    if case_node is not None:
        case: dict[str, Any] = {}
        size_code = _infer_size_code(case_node)
        if size_code is not None:
            case["size_code"] = size_code
        material = _case_material(case_node)
        if material is not None:
            case["material"] = material
        _apply_component_metadata(case, case_node)
        case_properties = _mapped_properties(case_node.get("hasMeasuredProperty"))
        if case_properties:
            case["property"] = case_properties
        case_constituents = case_node.get("hasConstituent")
        case_items = case_constituents if isinstance(case_constituents, list) else [case_constituents]
        for item in case_items:
            lid = _map_case_part(item, expected_types={"CellLid"})
            if lid is not None:
                out["lid"] = lid
            can = _map_case_part(item, expected_types={"CellCan"})
            if can is not None:
                out["can"] = can
        if case:
            out["case"] = case

    # hasConstituent: dict {"Spring": node, "Spacer": node} (v1.1.x style)
    # hasComponent: list [Spring node, Spacer node, ...] (v3.x kiye style)
    hardware_sources: list[Any] = []
    constituents = payload.get("hasConstituent")
    if isinstance(constituents, dict):
        hardware_sources.extend(constituents.values())
    elif isinstance(constituents, list):
        hardware_sources.extend(constituents)
    components = payload.get("hasComponent")
    if isinstance(components, list):
        hardware_sources.extend(components)

    for item in hardware_sources:
        if not isinstance(item, Mapping):
            continue
        spring = _component_from_hardware_node(item, expected_type="Spring")
        if spring is not None:
            out["spring"] = spring
        spacer = _component_from_hardware_node(item, expected_type="Spacer")
        if spacer is not None:
            out["spacer"] = spacer

    return out


def _parse_converter_date(value: str | None) -> int | None:
    if value is None:
        return None
    patterns = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d")
    for pattern in patterns:
        try:
            parsed = dt.datetime.strptime(value, pattern)
            return int(parsed.replace(tzinfo=dt.timezone.utc).timestamp())
        except ValueError:
            continue
    return None


def _safe_retrieved_at(value: int | None) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _task_chain_steps(task: Any) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    current = _mapping_or_none(task)
    while current is not None:
        step: dict[str, Any] = {}
        task_type = _preferred_type(current, exclude=set()) or _string_value(current.get("@type"))
        if task_type is not None:
            step["task"] = task_type
        inputs: list[dict[str, Any]] = []
        for item in _mapping_list(current.get("hasInput")):
            quantity = _quantity_text(item)
            input_types = _node_types(item)
            input_entry: dict[str, Any] = {
                "type": [value for value in input_types if value != "TerminationQuantity"] or input_types,
            }
            if quantity is not None:
                input_entry["quantity"] = quantity
            inputs.append(input_entry)
        if inputs:
            step["inputs"] = inputs
        steps.append(step)
        current = _mapping_or_none(current.get("hasNext"))
    return steps


def _test_object_context(node: Any) -> dict[str, Any]:
    test_object = _mapping_or_none(node)
    if test_object is None:
        return {}
    out: dict[str, Any] = {}

    half_cell = _mapping_or_none(test_object.get("ElectrochemicalHalfCell"))
    if half_cell is not None:
        out["test_object_type"] = "half_cell"
        reference = _mapping_or_none(half_cell.get("hasReferenceElectrode"))
        reference_type = _label_for_type(_preferred_type(reference, exclude=set()))
        if reference_type is not None:
            out["reference_electrode"] = reference_type

    full_cell = _mapping_or_none(test_object.get("ElectrochemicalCell"))
    if full_cell is not None:
        out["test_object_type"] = "electrochemical_cell"
        counter = _mapping_or_none(full_cell.get("hasNegativeElectrode"))
        counter_type = _label_for_type(_preferred_type(counter, exclude=set()))
        if counter_type is not None:
            out["counter_electrode"] = counter_type

    return out


def _rated_capacity_measurements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for item in items:
        if _preferred_type(item, exclude=set()) != "RatedCapacity":
            continue
        if _mapping_or_none(item.get("@reverse")) is not None:
            continue
        quantity = _quantity_text(item)
        if quantity is None:
            continue
        output: dict[str, Any] = {"property": "rated_capacity", "quantity": quantity}
        unit = quantity.get("unit")
        if unit == "mAh/cm2":
            output["basis"] = "areal"
        elif unit == "mAh/g":
            output["basis"] = "specific"
        outputs.append(output)
    return outputs


def _extract_procedure_records(
    positive_electrode_node: dict[str, Any] | None,
    negative_electrode_node: dict[str, Any] | None,
    *,
    instance_id: str | None,
    instance_label: str | None,
    source_file: str,
    retrieved_at: int | None,
    workflow_version: str | None,
    schema_version: str,
    warnings: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(instance_id, str) or not instance_id:
        return [], []

    protocol_records: list[dict[str, Any]] = []
    test_records: list[dict[str, Any]] = []
    retrieved_timestamp = _safe_retrieved_at(retrieved_at)

    for role, electrode_node in (("positive_electrode", positive_electrode_node), ("negative_electrode", negative_electrode_node)):
        if electrode_node is None:
            continue
        measured_properties = _mapping_list(electrode_node.get("hasMeasuredProperty"))
        measurement_outputs = _rated_capacity_measurements(measured_properties)
        procedure_index = 0
        for property_node in measured_properties:
            if _preferred_type(property_node, exclude=set()) != "RatedCapacity":
                continue
            reverse = _mapping_or_none(property_node.get("@reverse"))
            if reverse is None:
                continue
            battery_test = _mapping_or_none(reverse.get("hasOutput"))
            if battery_test is None or "BatteryTest" not in _node_types(battery_test):
                continue

            measurement_parameter = _mapping_or_none(battery_test.get("hasMeasurementParameter")) or {}
            role_label = role.replace("_", " ")
            protocol_name = _string_value(measurement_parameter.get("rdfs:label")) or f"{role_label} rated capacity procedure"
            protocol_description = _string_value(measurement_parameter.get("rdfs:comment"))
            steps = _task_chain_steps(measurement_parameter.get("hasTask"))
            conditions = _test_object_context(battery_test.get("hasTestObject"))
            conditions["subject"] = role
            if not steps:
                warnings.append(
                    f"Converter rated-capacity procedure for {role} was imported without parsed task steps."
                )

            protocol_id = _entity_iri("test-protocol", f"{instance_id}::{role}::capacity-check::{procedure_index}")
            protocol = TestProtocol(
                schema_version=schema_version,
                id=protocol_id,
                name=protocol_name,
                test_type="capacity_check",
                description=protocol_description,
                version=workflow_version,
                conditions=conditions,
                setpoints={"steps": steps} if steps else {},
                measurement_outputs=measurement_outputs,
                source=ProvenanceInfo(
                    type="manual",
                    file=source_file,
                    retrieved_at=retrieved_timestamp,
                    workflow_version=workflow_version,
                ),
                comment=[f"Imported from BattINFO Converter JSON-LD for {role_label}."],
            )

            test_id = _entity_iri("test", f"{instance_id}::{role}::capacity-check::{procedure_index}")
            test = Test(
                schema_version=schema_version,
                id=test_id,
                name=f"{instance_label or 'cell'} {role_label} rated capacity",
                test_type="capacity_check",
                protocol_id=protocol_id,
                cell_instance_id=instance_id,
                description=f"Imported converter rated-capacity test for {role_label}.",
                protocol=protocol_name,
                source=ProvenanceInfo(
                    type="manual",
                    file=source_file,
                    retrieved_at=retrieved_timestamp,
                    workflow_version=workflow_version,
                ),
                comment=[f"Imported from BattINFO Converter JSON-LD for {role_label}."],
            )

            protocol_records.append(protocol.to_record())
            test_records.append(test.to_record())
            procedure_index += 1

    return protocol_records, test_records


def _stable_uid(seed: str) -> str:
    digest = hashlib.sha1(seed.encode("utf-8")).digest()[:10]
    number = int.from_bytes(digest, "big")
    chars: list[str] = []
    for _ in range(16):
        number, remainder = divmod(number, 32)
        chars.append(UID_ALPHABET[remainder])
    token = "".join(reversed(chars))
    return "-".join(token[i : i + 4] for i in range(0, 16, 4))


_IRI_NAMESPACE: dict[str, str] = {
    "cell-type": "spec",
    "cell": "cell",
    "test-protocol": "spec",
    "test": "test",
    "dataset": "dataset",
    "organization": "organization",
    "electrode": "electrode",
    "material": "material",
}


def _entity_iri(entity_type: str, seed: str) -> str:
    namespace = _IRI_NAMESPACE.get(entity_type, entity_type)
    return f"https://w3id.org/battinfo/{namespace}/{_stable_uid(seed)}"


# ---------------------------------------------------------------------------
# Dataset record builder
# ---------------------------------------------------------------------------

_MEDIA_TYPE_FORMAT: dict[str, str] = {
    "text/csv": "text/csv",
    "application/vnd.apache.parquet": "application/vnd.apache.parquet",
    "application/json": "application/json",
}


def _map_person(node: Any) -> dict[str, Any] | None:
    if not isinstance(node, Mapping):
        return None
    name = _string_value(node.get("schema:name"))
    if name is None:
        return None
    person: dict[str, Any] = {"type": "Person", "name": name}
    orcid = _string_value(node.get("@id"))
    if orcid and orcid.startswith("https://orcid.org/"):
        person["same_as"] = orcid
    affiliation = _mapping_or_none(node.get("schema:affiliation"))
    if affiliation is not None:
        org_name = _string_value(affiliation.get("schema:name"))
        org_id = _string_value(affiliation.get("@id"))
        if org_name is not None:
            aff: dict[str, Any] = {"name": org_name}
            if org_id:
                aff["same_as"] = org_id
            person["affiliation"] = aff
    return person


def _map_distributions(dcat_distributions: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in dcat_distributions:
        if not isinstance(item, Mapping):
            continue
        url = _string_value(item.get("@id"))
        media_type = _string_value(item.get("dcat:mediaType"))
        if url is None or media_type is None:
            continue
        dist: dict[str, Any] = {
            "content_url": url,
            "encoding_format": _MEDIA_TYPE_FORMAT.get(media_type, media_type),
        }
        out.append(dist)
    return out


def _extract_doi_from_url(url: str) -> str | None:
    """Extract a bare DOI from a doi.org URL or return None."""
    import re
    match = re.search(r"10\.\d{4,9}/[^\s#]+", url)
    return match.group(0) if match else None


def import_dataset_record(
    source: Mapping[str, Any] | str | Path,
    *,
    schema_version: str = "1.0.0",
) -> dict[str, Any] | None:
    """Build a battinfo dataset record from the hasOutput block of a converter export.

    Returns None if the document contains no dataset distribution information.
    """
    raw_payload, source_file = _load_source(source)
    _, battery_test_node = _normalize_to_coin_cell(raw_payload)

    has_output = battery_test_node.get("hasOutput")
    if not isinstance(has_output, Mapping):
        return None

    dcat_distributions_raw = has_output.get("dcat:distribution")
    if not isinstance(dcat_distributions_raw, list) or not dcat_distributions_raw:
        return None

    distributions = _map_distributions(dcat_distributions_raw)
    if not distributions:
        return None

    # Resolve dataset URL: prefer dcat:accessURL (canonical DOI landing page)
    dataset_url = (
        _string_value(has_output.get("dcat:accessURL"))
        or _string_value(has_output.get("schema:url"))
        or distributions[0]["content_url"]
    )

    title = (
        _string_value(has_output.get("dc:title"))
        or _string_value(has_output.get("schema:name"))
        or f"Dataset from {source_file}"
    )

    dataset_id = _entity_iri("dataset", dataset_url + "::" + title)
    identifier = _string_value(has_output.get("schema:identifier")) or dataset_url

    dataset: dict[str, Any] = {
        "id": dataset_id,
        "identifier": identifier,
        "name": title,
        "access_url": dataset_url,
        "distributions": distributions,
    }

    description = _string_value(has_output.get("dc:description") or has_output.get("schema:description"))
    if description:
        dataset["description"] = description

    license_val = _string_value(has_output.get("dc:license") or has_output.get("schema:license"))
    if license_val:
        dataset["license"] = license_val
        dataset["is_accessible_for_free"] = True

    # Creators
    raw_creators = has_output.get("dc:creator") or has_output.get("schema:creator")
    if isinstance(raw_creators, list):
        persons = [p for p in (_map_person(c) for c in raw_creators) if p is not None]
        if persons:
            dataset["creators"] = persons
    elif isinstance(raw_creators, Mapping):
        person = _map_person(raw_creators)
        if person:
            dataset["creators"] = [person]

    # Publisher
    raw_publisher = has_output.get("dc:publisher")
    if isinstance(raw_publisher, Mapping):
        pub_name = _string_value(raw_publisher.get("schema:name"))
        if pub_name:
            dataset["publisher"] = {"name": pub_name}

    # Keywords
    keywords_raw = has_output.get("dcat:keyword")
    if isinstance(keywords_raw, list):
        dataset["keywords"] = [str(k) for k in keywords_raw if k]

    # Citation
    citation_text = _string_value(has_output.get("schema:citation"))
    assoc_media = _mapping_or_none(has_output.get("schema:associatedMedia"))
    citation_url: str | None = None
    if assoc_media is not None:
        citation_url = _string_value(assoc_media.get("@id"))
    if citation_url is None and citation_text:
        # Try to pull a DOI URL out of the citation string
        import re
        doi_match = re.search(r"https?://doi\.org/\S+", citation_text)
        citation_url = doi_match.group(0).rstrip(".,;)") if doi_match else None
    if citation_url or citation_text:
        citation_entry: dict[str, Any] = {"kind": "article"}
        if citation_text:
            citation_entry["name"] = citation_text
        if citation_url:
            citation_entry["url"] = citation_url
            doi = _extract_doi_from_url(citation_url)
            if doi:
                citation_entry["doi"] = doi
        dataset["citations"] = [citation_entry]

    # Published date → unix timestamp
    issued = _string_value(has_output.get("dc:issued") or has_output.get("schema:datePublished"))
    if issued:
        ts = _parse_converter_date(issued)
        if ts is not None:
            dataset["published_at"] = ts

    # Measurement technique (always cycling for these files)
    dataset["measurement_techniques"] = ["Galvanostatic cycling", "Electrochemical impedance spectroscopy"]

    retrieved_at = _parse_converter_date(
        _string_value(has_output.get("dc:issued") or has_output.get("schema:datePublished"))
    ) or 0

    provenance: dict[str, Any] = {
        "source_type": "measurement",
        "source_file": source_file,
        "retrieved_at": retrieved_at,
        "workflow_version": "battinfoconverter-import",
    }
    if citation_url:
        provenance["source_url"] = citation_url
        doi = _extract_doi_from_url(citation_url)
        if doi:
            provenance["citation_doi"] = doi

    return {
        "schema_version": schema_version,
        "dataset": dataset,
        "provenance": provenance,
    }


# ---------------------------------------------------------------------------
# Batch importer
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class BatchImportResult:
    path: Path
    cell_id: str | None
    descriptor: dict[str, Any] | None
    dataset: dict[str, Any] | None
    warnings: list[str]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def batch_import_converter_directory(
    directory: str | Path,
    *,
    glob: str = "**/*metadata*.json",
    schema_version: str = "1.0.0",
    manufacturer: str | None = None,
    chemistry: str | None = None,
) -> list[BatchImportResult]:
    """Import all BattINFO Converter metadata files found under *directory*.

    Each file produces one descriptor record and (if hasOutput is present)
    one dataset record.  Returns results in file-discovery order; failures are
    captured per-file so a single bad file does not abort the batch.
    """
    root = Path(directory)
    results: list[BatchImportResult] = []

    # File names that are known non-converter JSON files present in RO-Crate packages
    _SKIP_NAMES = {"ro-crate-metadata.json"}

    for path in sorted(root.glob(glob)):
        if path.name in _SKIP_NAMES:
            continue

        cell_id: str | None = None
        descriptor: dict[str, Any] | None = None
        dataset: dict[str, Any] | None = None
        warnings: list[str] = []
        error: str | None = None

        try:
            import_result = import_converter_jsonld_record(
                path,
                manufacturer=manufacturer,
                chemistry=chemistry,
                schema_version=schema_version,
            )
            descriptor = import_result.record
            warnings = list(import_result.warnings)

            # Extract the canonical cell ID from the instances block
            instances = descriptor.get("instances") or []
            if instances:
                cell_id = instances[0].get("id")

            try:
                dataset = import_dataset_record(path, schema_version=schema_version)
            except Exception as ds_err:
                warnings.append(f"Dataset record could not be built: {ds_err}")

        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        results.append(
            BatchImportResult(
                path=path,
                cell_id=cell_id,
                descriptor=descriptor,
                dataset=dataset,
                warnings=warnings,
                error=error,
            )
        )

    return results
