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
        ROOT / "assets" / "mappings" / "domain-battery" / "material_map.json",
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

    examples_dir = ROOT / "examples" / "cell-spec" / "research"
    for example_path in sorted(examples_dir.glob("*.example.json")):
        mapped = to_jsonld(_load_json(example_path), target="domain-battery")
        used = _collect_battinfo_terms(mapped)
        assert used <= allowed, f"Unapproved BattINFO terms in {example_path.name}: {sorted(used - allowed)}"


def test_entity_type_map_covers_current_descriptor_core_values() -> None:
    mapping = _load_json(ROOT / "assets" / "mappings" / "domain-battery" / "entity_type_map.json")["mappings"]
    examples_dir = ROOT / "examples" / "cell-spec" / "research"

    for example_path in sorted(examples_dir.glob("*.example.json")):
        document = _load_json(example_path)
        product = document.get("cell_spec", {})
        field_map = {
            "format": product.get("cell_format", ""),
            "chemistry": product.get("chemistry", ""),
            "positive_electrode_basis": product.get("positive_electrode_basis", ""),
            "negative_electrode_basis": product.get("negative_electrode_basis", ""),
        }
        for field, value in field_map.items():
            if not value:
                continue
            normalized = value.strip().lower()
            assert normalized in mapping[field], f"Missing entity mapping for {field}={value!r}"


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
    node = _descriptor_specification_to_jsonld(spec)["isDescriptionFor"]
    neg = node.get("hasNegativeElectrode", {})
    assert neg.get("@type") == "SiliconGraphiteElectrode", f"Expected SiliconGraphiteElectrode, got: {neg}"


def test_entity_type_map_hard_carbon_anode_emits_electrode_node() -> None:
    from battinfo.transform.json_to_jsonld import _descriptor_specification_to_jsonld
    spec = {"format": "prismatic", "chemistry": "na-ion",
            "positive_electrode_basis": "unknown", "negative_electrode_basis": "hard-carbon"}
    node = _descriptor_specification_to_jsonld(spec)["isDescriptionFor"]
    neg = node.get("hasNegativeElectrode", {})
    assert neg.get("@type") == "HardCarbonElectrode", f"Expected HardCarbonElectrode, got: {neg}"


def test_reference_electrode_stacks_the_half_cell_device_classes() -> None:
    """A half-cell types as the DEVICE classes, never as ElectrochemicalHalfCell."""
    from battinfo.transform.cell_spec_node import physical_type_stack

    spec = {"cell_format": "coin", "chemistry": "li-metal",
            "positive_electrode_basis": "lfp", "reference_electrode": "lithium"}
    types = physical_type_stack(spec)
    assert "BatteryHalfCell" in types and "HalfCellDevice" in types, types
    assert "ElectrochemicalHalfCell" not in types

    full_cell = {"cell_format": "coin", "chemistry": "li-ion",
                 "positive_electrode_basis": "lfp", "negative_electrode_basis": "graphite"}
    assert "BatteryHalfCell" not in physical_type_stack(full_cell)


def test_descriptor_path_agrees_on_the_half_cell_type_stack() -> None:
    from battinfo.transform.json_to_jsonld import _descriptor_specification_to_jsonld

    node = _descriptor_specification_to_jsonld(
        {"format": "coin", "chemistry": "li-metal", "positive_electrode_basis": "lfp",
         "reference_electrode": "lithium"}
    )
    types = node["isDescriptionFor"]["@type"]
    assert "BatteryHalfCell" in types and "HalfCellDevice" in types, types


def test_material_map_resolves_stoichiometric_nmc_and_keeps_the_generic() -> None:
    from battinfo.transform.json_to_jsonld import _material_emmo_class

    assert _material_emmo_class("NMC811") == "LithiumNickelManganeseCobaltOxide811"
    assert _material_emmo_class("nmc 622") == "LithiumNickelManganeseCobaltOxide622"
    assert _material_emmo_class("NMC") == "LithiumNickelManganeseCobaltOxide"
    assert _material_emmo_class("silicon-graphite") == "SiliconGraphite"
    assert _material_emmo_class("LiTFSI") == "LithiumBistrifluoromethanesulfonylimide"


def test_every_mapped_term_resolves_in_the_bundled_emmo_context() -> None:
    """Emitted class prefLabels must expand through the pinned domain-battery context."""
    context = _load_json(
        ROOT / "src" / "battinfo" / "data" / "context" / "domain-battery.context.json"
    )["@context"]
    material_map = _load_json(ROOT / "assets" / "mappings" / "domain-battery" / "material_map.json")
    unresolved = [m["emmo_class"] for m in material_map["mappings"] if m["emmo_class"] not in context]
    assert not unresolved, f"material_map classes missing from the EMMO context: {unresolved}"

    entity_map = _load_json(ROOT / "assets" / "mappings" / "domain-battery" / "entity_type_map.json")
    missing = [
        battery_type
        for section in entity_map["mappings"].values()
        for entry in section.values()
        for battery_type in entry.get("battery_types", [])
        if battery_type not in context
    ]
    assert not missing, f"entity_type_map classes missing from the EMMO context: {missing}"


def test_battinfo_application_ontology_imports_are_pinned() -> None:
    """battinfo.ttl must import domain-battery at a pinned version IRI, not a floating latest."""
    ontology_path = ROOT / "battinfo.ttl"
    content = ontology_path.read_text(encoding="utf-8")
    # Versioned IRI must be present; floating (unversioned) import is not acceptable.
    assert "owl:imports <https://w3id.org/emmo/domain/battery/0.20.2/battery>" in content, (
        "battinfo.ttl must import domain-battery at a pinned version IRI. "
        "Update the import and this assertion together when upgrading."
    )
    # domain-electrochemistry must also be declared explicitly.
    assert "owl:imports <https://w3id.org/emmo/domain/electrochemistry/0.37.2/electrochemistry>" in content, (
        "battinfo.ttl must explicitly import domain-electrochemistry at a pinned version IRI."
    )
    # domain-chemical-substance carries the material vocabulary material_map.json uses.
    assert (
        "owl:imports <https://w3id.org/emmo/domain/chemical-substance/0.15.0/chemical-substance>" in content
    ), "battinfo.ttl must explicitly import domain-chemical-substance at a pinned version IRI."
    # The ontology must carry a versionIRI.
    assert "owl:versionIRI" in content, "battinfo.ttl must declare owl:versionIRI."
    # No local hasInstance property should be defined (it belongs to domain-battery).
    assert "battinfo:hasInstance a owl:ObjectProperty" not in content




# ── chemistry vocabulary (entity_type_map 0.6.0) ──────────────────────────────

def _chemistry_map() -> dict[str, dict[str, Any]]:
    path = ROOT / "src" / "battinfo" / "data" / "mappings" / "domain-battery" / "entity_type_map.json"
    return _load_json(path)["mappings"]["chemistry"]


def test_chemistry_aliases_point_at_a_recommended_label() -> None:
    chemistry = _chemistry_map()
    for key, entry in chemistry.items():
        if "alias_of" not in entry:
            continue
        target = chemistry.get(entry["alias_of"])
        assert target is not None, f"{key}: alias_of names an unknown label {entry['alias_of']!r}"
        assert "alias_of" not in target, f"{key}: alias_of must name a recommended label, not another alias"
        assert entry.get("note"), f"{key}: an alias states why it was superseded"


def test_chemistry_broader_links_form_a_tree_of_recommended_labels() -> None:
    chemistry = _chemistry_map()
    for key, entry in chemistry.items():
        seen = {key}
        current = entry
        while current.get("broader"):
            parent_key = current["broader"]
            assert parent_key in chemistry, f"{key}: broader names an unknown label {parent_key!r}"
            assert "alias_of" not in chemistry[parent_key], f"{key}: broader must not be an alias"
            assert parent_key not in seen, f"{key}: broader links loop back to {parent_key!r}"
            seen.add(parent_key)
            current = chemistry[parent_key]


def test_recommended_chemistry_labels_each_own_their_battery_class() -> None:
    # Importing JSON-LD turns a battery class back into a chemistry label. Two
    # recommended labels on one class would make that a coin toss.
    owner: dict[str, str] = {}
    for key, entry in _chemistry_map().items():
        if "alias_of" in entry:
            continue
        for battery_class in entry["battery_types"]:
            assert battery_class not in owner, (
                f"{battery_class} is claimed by both {owner[battery_class]!r} and {key!r}"
            )
            owner[battery_class] = key


def test_specific_lithium_metal_system_emits_its_own_class() -> None:
    types = _type_stack({"format": "coin", "chemistry": "Li-MnO2",
                         "positive_electrode_basis": "unknown", "negative_electrode_basis": "unknown"})
    assert "LithiumManganeseDioxideBattery" in types, types


def test_li_primary_alias_keeps_resolving_and_says_primary() -> None:
    types = _type_stack({"format": "coin", "chemistry": "Li-primary",
                         "positive_electrode_basis": "unknown", "negative_electrode_basis": "unknown"})
    assert "LithiumMetalBattery" in types, types
    assert "PrimaryBattery" in types, types


def test_zinc_manganese_dioxide_variants_are_told_apart() -> None:
    chemistry = _chemistry_map()
    # The bare couple does not claim an electrolyte.
    assert chemistry["zn-mno2"]["battery_types"] == ["ZincBattery"]
    assert chemistry["alkaline-zn-mno2"]["battery_types"] == ["AlkalineZincManganeseDioxideBattery"]
    # zinc-carbon is the non-alkaline branch; it used to resolve to AlkalineCell.
    assert chemistry["zinc-carbon"]["battery_types"] == ["ZincCarbonBattery"]
    assert chemistry["leclanche"]["broader"] == chemistry["zinc-chloride"]["broader"] == "zinc-carbon"
    assert chemistry["zinc-carbon"]["broader"] == chemistry["alkaline-zn-mno2"]["broader"] == "zn-mno2"
    # "alkaline" alone still resolves, to the alkaline zinc cell it has always meant.
    assert chemistry["alkaline"]["alias_of"] == "alkaline-zn-mno2"


def test_every_property_mapping_names_a_class_the_ontology_publishes() -> None:
    # Two candidate entries once carried class IRIs that were never minted
    # (battery#nominalContinuousChargingCurrent). The emitter used their labels
    # as bare @type values, no context defined them, and a JSON-LD processor
    # silently turned them into addresses under the document base.
    mapping_dir = ROOT / "src" / "battinfo" / "data" / "mappings" / "domain-battery"
    context = _load_json(ROOT / "src" / "battinfo" / "data" / "context" / "domain-battery.context.json")["@context"]
    published = {value.get("@id") if isinstance(value, dict) else value for value in context.values()}
    unknown = []
    for name in ("property_map.curated.json", "property_map.candidates.json"):
        for entry in _load_json(mapping_dir / name)["mappings"]:
            iri = entry.get("class_iri")
            if iri and iri not in published:
                unknown.append(f"{name}: {entry['key']} -> {iri}")
    assert unknown == []
