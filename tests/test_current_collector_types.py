"""Current collectors type from their material and form fields, then their name.

The emitter used to read only the product name, word by word, and the first
material word won. 'Stainless steel mesh' therefore became Steel, a class that
neither the v1 records context nor the pinned EMMO context defines, so
``record_to_jsonld`` raised on an electrode spec that passed strict validation.
'Carbon coated aluminium foil' became Carbon, the coating, rather than the
aluminium it coats. A collector given only as ``{material: 'Al', form: 'foil'}``
emitted nothing, and a mesh was always a woven mesh.

One normaliser now reads the ``material`` and ``form`` fields first and the
name after them. The tests compare the expanded class IRIs.
"""

from __future__ import annotations

import copy
import json
import warnings
from pathlib import Path
from typing import Any

import pytest
from pyld import jsonld as _jsonld

from battinfo.jsonld import record_to_jsonld
from battinfo.transform.json_to_jsonld import _descriptor_current_collector_to_jsonld
from battinfo.validate.jsonld import _inline_local_contexts

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "src" / "battinfo" / "data" / "examples"

EMMO = "https://w3id.org/emmo#"
ECHEM = "https://w3id.org/emmo/domain/electrochemistry#electrochemistry_"
CHEMSUB = "https://w3id.org/emmo/domain/chemical-substance#substance_"
SCHEMA_NAME = "https://schema.org/name"
SCHEMA_MATERIAL = "https://schema.org/material"

HAS_CURRENT_COLLECTOR = ECHEM + "cc8c2c5d_cf3d_444d_a7e8_44ec4c06a88e"
HAS_COATING = ECHEM + "4df9926d_d4f2_4955_93f3_a03c5edc5383"

CURRENT_COLLECTOR = ECHEM + "212af058_3bbb_419f_a9c6_90ba9ebb3706"
ALUMINIUM = CHEMSUB + "8f7dd877_5ad0_48f1_bbec_84153d8215f4"
COPPER = CHEMSUB + "0993cbab_ff7f_4ec3_8a6c_cd67497d54d9"
NICKEL = CHEMSUB + "f92b3948_72a5_4662_acf7_5d8dd64e85de"
STAINLESS_STEEL = CHEMSUB + "2cd874c8_f8f0_4794_bba9_d520603ab6bb"
CARBON = CHEMSUB + "4e5582a6_caec_4917_acad_6f472cd7d831"
FOIL = ECHEM + "1d5377a7_9f2b_4fdf_958a_7eeadce158d6"
PERFORATED_FOIL = ECHEM + "c84a1d8f_e405_42ba_8c80_bbe3b9c6c66a"
MESH = ECHEM + "18f2199b_c50c_49ec_bd17_a37626ca5e63"
WOVEN_MESH = ECHEM + "3a69a00e_235a_4948_b369_8ac20116c85e"
FOAM = EMMO + "EMMO_1f5e3e7e_72c9_40d4_91dd_ae432d7b7018"

# (current_collector body, expected class IRIs, coating text or None)
CASES: list[tuple[dict[str, Any], set[str], str | None]] = [
    ({"name": "Stainless steel mesh"}, {CURRENT_COLLECTOR, STAINLESS_STEEL, MESH}, None),
    ({"name": "Carbon coated aluminium foil"}, {CURRENT_COLLECTOR, ALUMINIUM, FOIL}, "Carbon"),
    ({"material": "Al", "form": "foil"}, {CURRENT_COLLECTOR, ALUMINIUM, FOIL}, None),
    ({"material": "Ni", "form": "mesh"}, {CURRENT_COLLECTOR, NICKEL, MESH}, None),
    ({"material": "Ni", "form": "foam"}, {CURRENT_COLLECTOR, NICKEL, FOAM}, None),
    ({"material": "Cu", "form": "perforated"}, {CURRENT_COLLECTOR, COPPER, PERFORATED_FOIL}, None),
    ({"material": "carbon-coated Al", "form": "foil"}, {CURRENT_COLLECTOR, ALUMINIUM, FOIL}, "carbon"),
    ({"material": "stainless steel", "form": "mesh"}, {CURRENT_COLLECTOR, STAINLESS_STEEL, MESH}, None),
    ({"name": "SUS316L mesh"}, {CURRENT_COLLECTOR, STAINLESS_STEEL, MESH}, None),
    ({"name": "Al foil 15 um"}, {CURRENT_COLLECTOR, ALUMINIUM, FOIL}, None),
    ({"name": "Cu foil"}, {CURRENT_COLLECTOR, COPPER, FOIL}, None),
    ({"name": "Nickel foam"}, {CURRENT_COLLECTOR, NICKEL, FOAM}, None),
    ({"name": "Nickel woven mesh"}, {CURRENT_COLLECTOR, NICKEL, WOVEN_MESH}, None),
    ({"name": "Nickel-plated copper foil"}, {CURRENT_COLLECTOR, COPPER, FOIL}, "Nickel"),
    ({"name": "Al foil coated with carbon"}, {CURRENT_COLLECTOR, ALUMINIUM, FOIL}, "carbon"),
    ({"name": "Al2O3 coated Cu foil"}, {CURRENT_COLLECTOR, COPPER, FOIL}, "Al2O3"),
    # A word that says how or where a foil is coated is not its coating.
    ({"name": "Double-side carbon coated Al foil"}, {CURRENT_COLLECTOR, ALUMINIUM, FOIL}, "carbon"),
    ({"name": "Double side coated Al foil"}, {CURRENT_COLLECTOR, ALUMINIUM, FOIL}, None),
    ({"name": "Double-sided coated Cu foil"}, {CURRENT_COLLECTOR, COPPER, FOIL}, None),
    ({"name": "Pre-coated Al foil"}, {CURRENT_COLLECTOR, ALUMINIUM, FOIL}, None),
    ({"name": "Non-coated Al foil"}, {CURRENT_COLLECTOR, ALUMINIUM, FOIL}, None),
    ({"name": "Carbon paper"}, {CURRENT_COLLECTOR, CARBON}, None),
    # Plain steel has no class in the pinned closure, so only the form types.
    ({"name": "Steel mesh"}, {CURRENT_COLLECTOR, MESH}, None),
    # The explicit fields win over the name.
    ({"name": "Copper foil", "material": "Al", "form": "mesh"}, {CURRENT_COLLECTOR, ALUMINIUM, MESH}, None),
    # "other" says the form is none of the listed ones, so the name is not read for it.
    ({"name": "Aluminium mesh", "form": "other"}, {CURRENT_COLLECTOR, ALUMINIUM}, None),
    # An unrecognised material field leaves the substrate to the name.
    ({"name": "Aluminium foil", "material": "AA1235"}, {CURRENT_COLLECTOR, ALUMINIUM, FOIL}, None),
]


def _quiet(fn, *args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fn(*args, **kwargs)


def _collectors(doc: dict) -> list[dict]:
    """Every hasCurrentCollector node of an emitted document, expanded offline."""
    found: list[dict] = []

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            found.extend(value.get(HAS_CURRENT_COLLECTOR, []))
            for item in value.values():
                walk(item)

    walk(_jsonld.expand(_inline_local_contexts(doc)))
    return found


def _electrode_spec(collector: dict) -> dict:
    record = json.loads((EXAMPLES / "electrode-spec" / "277n-cp9k-3g4m-w40y.json").read_text(encoding="utf-8"))
    record["electrode_spec"]["current_collector"] = collector
    return record


def _current_collector_spec(collector: dict) -> dict:
    record = json.loads((EXAMPLES / "current-collector-spec" / "vkaf-f5bv-fwt2-e6yz.json").read_text(encoding="utf-8"))
    body = record["current_collector_spec"]
    for key in ("name", "material", "form"):
        body.pop(key, None)
    body.update(collector)
    body.setdefault("name", "Collector")
    return record


def _cell_spec(collector: dict) -> dict:
    record = json.loads((EXAMPLES / "cell-spec" / "A123__ANR26650M1-B.json").read_text(encoding="utf-8"))
    record = copy.deepcopy(record)
    record["cell_spec"]["positive_electrode"] = {"current_collector": collector}
    return record


def _emitted_electrode_spec(collector: dict) -> dict:
    (node,) = _collectors(_quiet(record_to_jsonld, _electrode_spec(collector), "electrode-spec"))
    return node


def _emitted_cell_spec(collector: dict) -> dict:
    (node,) = _collectors(_quiet(record_to_jsonld, _cell_spec(collector), "cell-spec"))
    return node


def _coating_text(node: dict) -> str | None:
    coatings = node.get(HAS_COATING, [])
    if not coatings:
        return None
    (coating,) = coatings
    assert "@type" not in coating, "a coating is kept as text, never typed by its material"
    (material,) = coating[SCHEMA_MATERIAL]
    return material["@value"]


@pytest.mark.parametrize("emit", [_emitted_electrode_spec, _emitted_cell_spec], ids=["electrode-spec", "cell-spec"])
@pytest.mark.parametrize(("collector", "types", "coating"), CASES)
def test_a_collector_types_as_its_substrate_and_form(emit, collector: dict, types: set[str], coating: str | None):
    node = emit(collector)
    assert set(node["@type"]) == types
    assert _coating_text(node) == coating


@pytest.mark.parametrize(("collector", "types", "coating"), CASES)
def test_a_standalone_collector_spec_types_the_same_way(collector: dict, types: set[str], coating: str | None):
    doc = _quiet(record_to_jsonld, _current_collector_spec(collector), "current-collector-spec")
    expanded = _jsonld.expand(_inline_local_contexts(doc))
    described = [
        node
        for top in expanded
        for node in top.get(EMMO + "EMMO_f702bad4_fc77_41f0_a26d_79f6444fd4f3", [])  # isDescriptionFor
    ]
    (node,) = described
    assert set(node["@type"]) == types
    assert _coating_text(node) == coating


def test_the_material_and_name_strings_are_kept() -> None:
    node = _emitted_electrode_spec({"name": "Battery-grade foil", "material": "carbon-coated Al", "form": "foil"})
    assert node[SCHEMA_NAME] == [{"@value": "Battery-grade foil"}]
    assert node[SCHEMA_MATERIAL] == [{"@value": "carbon-coated Al"}]


def test_a_collector_with_no_name_is_emitted() -> None:
    node = _descriptor_current_collector_to_jsonld({"material": "Al", "form": "foil"})
    assert node == {"@type": ["CurrentCollector", "Aluminium", "Foil"], "schema:material": "Al"}


def test_a_stainless_steel_mesh_electrode_spec_validates_and_emits() -> None:
    """record_to_jsonld raised 'Steel is not in the allowed term set' here."""
    record = _electrode_spec({"name": "Stainless steel mesh"})
    doc = _quiet(record_to_jsonld, record, "electrode-spec")
    (node,) = _collectors(doc)
    assert STAINLESS_STEEL in node["@type"]


@pytest.mark.parametrize(
    ("example", "types"),
    [
        ("277n-cp9k-3g4m-w40y", {CURRENT_COLLECTOR, NICKEL, MESH}),  # "Nickel mesh"
        ("3abg-gxzh-6487-9eex", {CURRENT_COLLECTOR, MESH}),  # "Brass mesh": no class for brass
    ],
)
def test_the_packaged_mesh_collectors_type_as_mesh(example: str, types: set[str]) -> None:
    record = json.loads((EXAMPLES / "electrode-spec" / f"{example}.json").read_text(encoding="utf-8"))
    (node,) = _collectors(_quiet(record_to_jsonld, record, "electrode-spec"))
    assert set(node["@type"]) == types
