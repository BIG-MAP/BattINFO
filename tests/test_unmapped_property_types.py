"""A property key without an EMMO class gets no invented class.

IDENTIFIER_POLICY.md section 14: BattINFO never mints a class for a scientific
quantity. A quantity node for an unmapped key carries only its value-basis
class (ConventionalProperty, MeasuredProperty, ...) and the record key as its
label, and validation warns ``semantic.property_unmapped``.
"""
from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.jsonld import record_to_jsonld  # noqa: E402
from battinfo.transform.json_to_jsonld import _descriptor_quantity_node  # noqa: E402
from battinfo.validate.semantic import validate_semantic_report  # noqa: E402

# A generated name: battinfo: prefix (or the slash namespace) followed by a
# lower-case letter, the shape the old fallback produced (battinfo:solidDiffusivity).
# Record-layer classes such as battinfo:MaterialSpec are capitalised and allowed.
GENERATED_NAME = re.compile(r"^(battinfo:|https://w3id\.org/battinfo/)[a-z]")


def _collect_types(value: Any, out: set[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_types(item, out)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key == "@type":
                out.update(t for t in (item if isinstance(item, list) else [item]) if isinstance(t, str))
            else:
                _collect_types(item, out)


def test_unmapped_key_is_typed_by_its_value_basis_only() -> None:
    node = _descriptor_quantity_node("frobnication_index", {"value": 1.0, "unit": "1"})
    assert node is not None
    assert node["@type"] == ["ConventionalProperty"]
    assert node["skos:prefLabel"] == "frobnication_index"

    measured = _descriptor_quantity_node(
        "frobnication_index", {"value": 1.0, "unit": "1", "value_basis": "Measured"}
    )
    assert measured is not None
    assert measured["@type"] == ["MeasuredProperty"]


@pytest.mark.parametrize(
    ("key", "term"),
    [
        ("solid_diffusivity", "Diffusivity"),
        ("entropic_coefficient", "TemperatureCoefficientOfTheOpenCircuitVoltage"),
        ("initial_concentration", "InitialChargeCarrierConcentrationInElectrolyte"),
        ("particle_d50", "D50ParticleSize"),
        ("compaction_density", "CalenderedDensity"),
    ],
)
def test_former_fallback_keys_type_as_published_classes(key: str, term: str) -> None:
    node = _descriptor_quantity_node(key, {"value": 1.0, "unit": "1"})
    assert node is not None
    assert node["@type"][0] == term
    assert node["skos:prefLabel"] == term


def test_no_packaged_example_emits_a_generated_battinfo_class() -> None:
    examples = ROOT / "src" / "battinfo" / "data" / "examples"
    generated: set[str] = set()
    checked = 0
    for path in sorted(examples.rglob("*.json")):
        kind = path.relative_to(examples).parts[0]
        record = json.loads(path.read_text(encoding="utf-8"))
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                out = record_to_jsonld(record, kind)
        except (KeyError, ValueError):
            continue  # folders without a standalone emitter
        checked += 1
        types: set[str] = set()
        _collect_types(out, types)
        generated.update(
            f"{path.relative_to(examples).as_posix()}: {t}" for t in types if GENERATED_NAME.match(t)
        )
    assert checked > 100, f"corpus sweep looks broken (only {checked} records emitted)"
    assert not generated, sorted(generated)


def test_unmapped_parameter_claim_warns_like_an_unmapped_property() -> None:
    doc = {
        "schema_version": "0.2.0",
        "parameter_set": {
            "id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
            "name": "Separator transport",
            "scope": "separator",
            "claims": [
                {"parameter": "porosity", "quantity": {"value": 0.4, "unit": "1"}},
                {"parameter": "transport_efficiency", "quantity": {"value": 0.25, "unit": "1"}},
            ],
        },
    }
    report = validate_semantic_report(doc)
    hits = [i for i in report.issues if i.code == "semantic.property_unmapped"]
    assert [i.path for i in hits] == ["parameter_set.claims[1].transport_efficiency"]
    assert hits[0].severity == "warning"
    assert "no quantity class" in hits[0].message
