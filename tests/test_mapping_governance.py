from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.transform.json_to_jsonld import to_jsonld


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _collect_battinfo_terms(node: Any) -> set[str]:
    terms: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and key.startswith("battinfo:"):
                terms.add(key)
            if isinstance(value, str) and value.startswith("battinfo:"):
                terms.add(value)
            terms.update(_collect_battinfo_terms(value))
    elif isinstance(node, list):
        for item in node:
            terms.update(_collect_battinfo_terms(item))
    return terms


def test_entity_type_map_and_extension_policy_packaged_copies_match_assets() -> None:
    tracked = [
        ROOT / "assets" / "mappings" / "domain-battery" / "entity_type_map.json",
        ROOT / "assets" / "mappings" / "domain-battery" / "extension_policy.json",
        ROOT / "assets" / "mappings" / "domain-battery" / "property_map.curated.json",
        ROOT / "assets" / "mappings" / "domain-battery" / "unit_map.curated.json",
    ]
    assets_root = ROOT / "assets"
    packaged_root = ROOT / "src" / "battinfo" / "data"

    for asset_path in tracked:
        packaged_path = packaged_root / asset_path.relative_to(assets_root)
        assert packaged_path.exists(), f"Missing packaged copy for {asset_path}"
        assert asset_path.read_bytes() == packaged_path.read_bytes(), f"Packaged copy drifted for {asset_path}"


def test_descriptor_domain_battery_output_uses_only_approved_battinfo_extensions() -> None:
    policy_path = ROOT / "assets" / "mappings" / "domain-battery" / "extension_policy.json"
    policy = _load_json(policy_path)
    allowed = {item["term"] for item in policy["allowed_extensions"]}

    examples_dir = ROOT / "examples" / "cell-descriptors"
    for example_path in sorted(examples_dir.glob("*.example.json")):
        mapped = to_jsonld(_load_json(example_path), target="domain-battery")
        used = _collect_battinfo_terms(mapped)
        assert used <= allowed, f"Unapproved BattINFO terms in {example_path.name}: {sorted(used - allowed)}"


def test_entity_type_map_covers_current_descriptor_core_values() -> None:
    mapping = _load_json(ROOT / "assets" / "mappings" / "domain-battery" / "entity_type_map.json")["mappings"]
    examples_dir = ROOT / "examples" / "cell-descriptors"

    for example_path in sorted(examples_dir.glob("*.example.json")):
        document = _load_json(example_path)
        specification = document["specification"]
        for field in ("format", "chemistry", "positive_electrode_basis", "negative_electrode_basis"):
            normalized = specification[field].strip().lower()
            assert normalized in mapping[field], f"Missing entity mapping for {field}={specification[field]!r}"


def _type_stack(specification: dict[str, Any]) -> list[str]:
    """Return the physical EMMO @type list from the isDescriptionFor node in descriptor pipeline output."""
    from battinfo.transform.json_to_jsonld import _descriptor_specification_to_jsonld
    node = _descriptor_specification_to_jsonld(specification)
    types = node.get("isDescriptionFor", {}).get("@type", [])
    return types if isinstance(types, list) else [types]


def test_entity_type_map_na_ion_chemistry_stacks_sodium_ion_battery() -> None:
    spec = {"format": "prismatic", "chemistry": "na-ion",
            "positive_electrode_basis": "unknown", "negative_electrode_basis": "hard-carbon"}
    types = _type_stack(spec)
    assert "SodiumIonBattery" in types, f"SodiumIonBattery not in @type: {types}"


def test_entity_type_map_lco_uses_specific_battery_class() -> None:
    spec = {"format": "cylindrical", "chemistry": "li-ion",
            "positive_electrode_basis": "lco", "negative_electrode_basis": "graphite"}
    types = _type_stack(spec)
    assert "LithiumIonCobaltOxideBattery" in types, f"LithiumIonCobaltOxideBattery not in @type: {types}"
    assert "LithiumIonBattery" not in types or "LithiumIonCobaltOxideBattery" in types


def test_entity_type_map_nca_uses_specific_battery_class_without_electrode_node() -> None:
    spec = {"format": "cylindrical", "chemistry": "li-ion",
            "positive_electrode_basis": "nca", "negative_electrode_basis": "graphite"}
    from battinfo.transform.json_to_jsonld import _descriptor_specification_to_jsonld
    full_node = _descriptor_specification_to_jsonld(spec)
    types = full_node.get("isDescriptionFor", {}).get("@type", [])
    if isinstance(types, str):
        types = [types]
    assert "LithiumIonNickelCobaltAluminiumOxideBattery" in types
    # NCA has no node_type — hasPositiveElectrode must not be present on the specification node
    assert "hasPositiveElectrode" not in full_node


def test_entity_type_map_silicon_graphite_anode_emits_electrode_node() -> None:
    from battinfo.transform.json_to_jsonld import _descriptor_specification_to_jsonld
    spec = {"format": "cylindrical", "chemistry": "li-ion",
            "positive_electrode_basis": "nmc", "negative_electrode_basis": "silicon-graphite"}
    node = _descriptor_specification_to_jsonld(spec)
    neg = node.get("hasNegativeElectrode", {})
    assert neg.get("@type") == "SiliconGraphiteElectrode", f"Expected SiliconGraphiteElectrode, got: {neg}"


def test_entity_type_map_hard_carbon_anode_emits_electrode_node() -> None:
    from battinfo.transform.json_to_jsonld import _descriptor_specification_to_jsonld
    spec = {"format": "prismatic", "chemistry": "na-ion",
            "positive_electrode_basis": "unknown", "negative_electrode_basis": "hard-carbon"}
    node = _descriptor_specification_to_jsonld(spec)
    neg = node.get("hasNegativeElectrode", {})
    assert neg.get("@type") == "HardCarbonElectrode", f"Expected HardCarbonElectrode, got: {neg}"


def test_battinfo_application_ontology_imports_are_pinned() -> None:
    """battinfo.ttl must import domain-battery at a pinned version IRI, not a floating latest."""
    ontology_path = ROOT / "ontology" / "battinfo.ttl"
    content = ontology_path.read_text(encoding="utf-8")
    # Versioned IRI must be present; floating (unversioned) import is not acceptable.
    assert "owl:imports <https://w3id.org/emmo/domain/battery/0.19.0/battery>" in content, (
        "battinfo.ttl must import domain-battery at a pinned version IRI. "
        "Update the import and this assertion together when upgrading."
    )
    # domain-electrochemistry must also be declared explicitly.
    assert "owl:imports <https://w3id.org/emmo/domain/electrochemistry/0.34.0/electrochemistry>" in content, (
        "battinfo.ttl must explicitly import domain-electrochemistry at a pinned version IRI."
    )
    # The ontology must carry a versionIRI.
    assert "owl:versionIRI" in content, "battinfo.ttl must declare owl:versionIRI."
    # No local hasInstance property should be defined (it belongs to domain-battery).
    assert "battinfo:hasInstance a owl:ObjectProperty" not in content


