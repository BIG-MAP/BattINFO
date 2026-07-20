"""Electrode basis is never lost in the JSON-LD projection.

A cell spec's positive/negative electrode basis must surface as a
hasPositiveElectrode / hasNegativeElectrode node: a specific EMMO electrode
class when the basis maps, and a labeled generic Electrode otherwise — so no
basis string is silently dropped. Separator variants (spaces, commas, slashes)
of the mapped terms are accepted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.transform import to_jsonld  # noqa: E402


def _negative_electrode(basis: str) -> dict | None:
    record = {
        "schema_version": "0.1.0",
        "cell_spec": {
            "id": "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
            "name": "X", "model": "X",
            "manufacturer": {"type": "Organization", "name": "A"},
            "cell_format": "cylindrical", "chemistry": "Li-ion",
            "positive_electrode_basis": "LFP",
            "negative_electrode_basis": basis,
        },
    }
    # to_jsonld validates its own output and raises on an unmapped @type, so a
    # returned graph already proves every emitted electrode class resolves.
    return to_jsonld(record, target="domain-battery")["@graph"][0].get("hasNegativeElectrode")


def _types(node: dict | None) -> list[str]:
    if not node:
        return []
    t = node.get("@type", [])
    return t if isinstance(t, list) else [t]


@pytest.mark.parametrize(
    "basis,expected",
    [
        ("graphite", "GraphiteElectrode"),
        ("hard carbon", "HardCarbonElectrode"),   # space accepted for hard-carbon
        ("hard-carbon", "HardCarbonElectrode"),
        ("silicon", "SiliconBasedElectrode"),      # bare silicon != silicon-graphite
        ("si", "SiliconBasedElectrode"),
        ("silicon-graphite", "SiliconGraphiteElectrode"),
        ("silicon, graphite", "SiliconGraphiteElectrode"),  # comma accepted
        ("silicon/graphite", "SiliconGraphiteElectrode"),   # slash accepted
        ("lithium metal", "LithiumElectrode"),
        ("LTO", "LithiumTitanateElectrode"),
    ],
)
def test_mapped_basis_gets_specific_electrode_class(basis: str, expected: str) -> None:
    assert expected in _types(_negative_electrode(basis))


def test_unmapped_basis_gets_labeled_generic_electrode() -> None:
    node = _negative_electrode("some custom anode")
    assert _types(node) == ["Electrode"]
    assert node is not None and node.get("skos:prefLabel") == "some custom anode"


@pytest.mark.parametrize("basis", ["unknown", "Unknown", "", "   "])
def test_unknown_or_empty_basis_emits_no_electrode(basis: str) -> None:
    assert _negative_electrode(basis) is None
