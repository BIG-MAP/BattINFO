"""Phase 5 regression guardrail for the canonical coin-cell model.

Locks in the BattINFO ↔ BattINFO Converter integration seam:

1. ``converter -> import -> export(converter-compatible)`` round-trips the converter's
   own reference output with no property-node loss (the green/red signal that BattINFO
   can serve as the converter's conversion engine).
2. The canonical ``domain-battery`` export uses dimensionally-correct capacity classes
   (AreicCapacity / DischargingSpecificCapacity) rather than the converter's legacy
   ``RatedCapacity`` overload, and validates.
3. A coin cell authored with the BattINFO authoring API exports to converter-shaped
   JSON-LD — the "BattINFO Converter imports battinfo" direction.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import import_converter_package  # noqa: E402
from battinfo.authoring import (  # noqa: E402
    bom,
    cell_description,
    electrode,
    electrolyte_recipe,
    material,
    separator_spec,
)
from battinfo.transform import to_jsonld  # noqa: E402

REFERENCE = ROOT / "tests" / "fixtures" / "converter" / "coincell_reference_v3.jsonld"


def _load_reference() -> dict:
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


def _property_signatures(doc: dict) -> set[tuple[str, str]]:
    """Collect (json(@type), unit) for every quantity / string-valued property node."""
    out: set[tuple[str, str]] = []

    def walk(node):
        if isinstance(node, dict):
            if "hasNumericalPart" in node or "hasStringValue" in node:
                unit = node.get("hasMeasurementUnit")
                out.append((json.dumps(node.get("@type")), str(unit)))
            for key, value in node.items():
                if not key.startswith("@"):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc)
    return set(out)


def _descriptor_input(specification: dict) -> dict:
    spec = dict(specification)
    if "properties" in spec and "property" not in spec:
        spec["property"] = spec["properties"]
    return {"schema_version": "1.0.0", "specification": spec, "provenance": {"source_type": "converter-jsonld"}}


def test_converter_compatible_roundtrip_loses_no_property_nodes() -> None:
    original = _load_reference()
    package = import_converter_package(REFERENCE)
    exported = to_jsonld(_descriptor_input(package.specification.to_json()), target="converter-compatible")

    lost = _property_signatures(original) - _property_signatures(exported)
    assert lost == set(), f"converter round-trip dropped property nodes: {sorted(lost)}"


def test_converter_compatible_roundtrip_preserves_key_terms() -> None:
    package = import_converter_package(REFERENCE)
    exported = to_jsonld(_descriptor_input(package.specification.to_json()), target="converter-compatible")
    sigs = _property_signatures(exported)

    # RatedCapacity areal + specific survive with their units (legacy converter typing).
    assert ('"RatedCapacity"', "emmo:MilliAmpereHourPerSquareCentiMetre") in sigs
    assert ('"RatedCapacity"', "unit:MilliA-HR-PER-GM") in sigs
    # MassLoading keeps its unit; tortuosity survives; molecular formula re-emitted.
    assert ('"MassLoading"', "unit:MilliGM-PER-CentiM2") in sigs
    assert ('"Tortuosity"', "emmo:UnitOne") in sigs
    assert ('"molecularFormula"', "None") in sigs


def test_domain_battery_export_uses_canonical_capacity_types() -> None:
    package = import_converter_package(REFERENCE)
    # to_jsonld validates internally for the domain-battery target; a failure raises.
    doc = to_jsonld(_descriptor_input(package.specification.to_json()), target="domain-battery")
    battery = doc["@graph"][0]

    electrode_types: set[str] = set()
    for relation in ("hasPositiveElectrode", "hasNegativeElectrode"):
        props = battery.get(relation, {}).get("hasProperty", [])
        props = props if isinstance(props, list) else [props]
        for node in props:
            if isinstance(node, dict):
                types = node.get("@type")
                electrode_types.update(types if isinstance(types, list) else [types])

    # Dimensionally-correct capacity classes, NOT the converter's RatedCapacity overload.
    assert "AreicCapacity" in electrode_types
    assert "DischargingSpecificCapacity" in electrode_types
    assert "RatedCapacity" not in electrode_types
    assert "Diameter" in electrode_types  # electrode-level property is now emitted


def test_author_in_battinfo_exports_converter_jsonld() -> None:
    """The 'converter imports battinfo' direction: author objects, get converter JSON-LD."""
    cathode = electrode(
        bom=bom(active_material=material("NMC811", mass_fraction={"value": 96, "unit": "%"},
                                         molecular_formula="LiNi0.8Mn0.1Co0.1O2")),
        current_collector="Aluminium foil",
        diameter={"value": 11, "unit": "mm"},
        rated_specific_discharge_capacity={"value": 160, "unit": "mAh/g"},
    )
    spec = cell_description(
        id="https://w3id.org/battinfo/spec/authored-1",
        manufacturer="Lab", model="NMC811-Graphite", format="coin", chemistry="li-ion",
        positive_electrode_basis="nmc", negative_electrode_basis="graphite", size_code="R2032",
        positive_electrode=cathode,
        electrolyte=electrolyte_recipe(family="organic", salt="LiPF6",
                                       salt_concentration={"value": 1.0, "unit": "mol/L"},
                                       solvents=[material("EC"), material("EMC")]),
        separator=separator_spec(material="polypropylene", thickness={"value": 25, "unit": "um"}),
    )
    doc = to_jsonld(_descriptor_input(spec.to_json()), target="converter-compatible")

    assert doc["@type"] == "CoinCell"
    assert "hasPositiveElectrode" in doc
    assert doc["hasPositiveElectrode"]["@type"] == "Electrode"
    assert "hasElectrolyte" in doc
    assert "hasSeparator" in doc
