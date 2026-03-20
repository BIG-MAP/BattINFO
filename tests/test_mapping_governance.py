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


def test_battinfo_application_ontology_declares_has_instance_extension() -> None:
    ontology_path = ROOT / "ontology" / "battinfo.ttl"
    content = ontology_path.read_text(encoding="utf-8")
    assert "owl:imports <https://w3id.org/emmo/domain/battery>" in content
    assert "battinfo:hasInstance a owl:ObjectProperty" not in content


