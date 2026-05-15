from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _schema_registry(schema_root: Path) -> Registry:
    registry = Registry()
    for path in sorted(schema_root.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        schema_id = doc.get("$id")
        if isinstance(schema_id, str) and schema_id:
            registry = registry.with_resource(schema_id, Resource.from_contents(doc))
    return registry


def test_battery_descriptor_schema_validates_example() -> None:
    schema_root = ROOT / "src" / "battinfo" / "data" / "schemas"
    schema_path = schema_root / "cell-descriptor.schema.json"
    schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))

    registry = _schema_registry(schema_root)
    validator = Draft202012Validator(schema_doc, registry=registry)

    sample = {
        "schema_version": "1.0.0",
        "specification": {
            "id": "https://w3id.org/battinfo/cell-type/9qfb-4wrn-ynwc-ayjw",
            "manufacturer": "A123",
            "model": "ANR26650M1-B",
            "format": "cylindrical",
            "chemistry": "Li-ion",
            "positive_electrode_basis": "LFP",
            "negative_electrode_basis": "graphite",
            "property": {
                "nominal_capacity": {"value": 2.5, "unit": "Ah"},
                "nominal_voltage": {"value": 3.3, "unit": "V"}
            },
            "electrolyte": {
                "family": "organic",
                "solvent_mixture": {
                    "component": [
                        {"name": "EC", "property": {"volume_fraction": {"value": 0.3, "unit": "1"}}},
                        {"name": "EMC", "property": {"volume_fraction": {"value": 0.7, "unit": "1"}}}
                    ]
                }
            }
        },
        "instances": [
            {
                "name": "lfp_k1",
                "id": "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8"
            }
        ],
        "provenance": {
            "source_file": "battery.json",
            "citation": "https://doi.org/10.17632/kxsbr4x3j2.2",
            "retrieved_at": 1772556000
        }
    }

    errors = list(validator.iter_errors(sample))
    assert errors == []


def test_battery_descriptor_schema_rejects_missing_required_fields() -> None:
    schema_root = ROOT / "src" / "battinfo" / "data" / "schemas"
    schema_path = schema_root / "cell-descriptor.schema.json"
    schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
    registry = _schema_registry(schema_root)
    validator = Draft202012Validator(schema_doc, registry=registry)

    invalid = {
        "schema_version": "1.0.0",
        "specification": {
            "id": "https://w3id.org/battinfo/cell-type/9qfb-4wrn-ynwc-ayjw",
            "model": "ANR26650M1-B",
            "format": "cylindrical",
            "chemistry": "Li-ion"
        }
    }

    with pytest.raises(ValidationError):
        validator.validate(invalid)


def test_battery_descriptor_schema_validates_minimal_core() -> None:
    schema_root = ROOT / "src" / "battinfo" / "data" / "schemas"
    schema_path = schema_root / "cell-descriptor.schema.json"
    schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
    registry = _schema_registry(schema_root)
    validator = Draft202012Validator(schema_doc, registry=registry)

    minimal = {
        "schema_version": "1.0.0",
        "specification": {
            "id": "https://w3id.org/battinfo/cell-type/pvn1-43h7-rm3e-mjqq",
            "manufacturer": "A123",
            "model": "ANR26650M1-B",
            "format": "cylindrical",
            "chemistry": "Li-ion",
            "positive_electrode_basis": "LFP",
            "negative_electrode_basis": "graphite",
        },
    }

    errors = list(validator.iter_errors(minimal))
    assert errors == []


def test_battery_descriptor_schema_accepts_construction_metadata() -> None:
    schema_root = ROOT / "src" / "battinfo" / "data" / "schemas"
    schema_path = schema_root / "cell-descriptor.schema.json"
    schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
    registry = _schema_registry(schema_root)
    validator = Draft202012Validator(schema_doc, registry=registry)

    sample = {
        "schema_version": "1.0.0",
        "specification": {
            "id": "https://w3id.org/battinfo/cell-type/4p7m-2q8v-6n3t-9k5r",
            "manufacturer": "ExampleCells",
            "model": "SLP-001",
            "format": "pouch",
            "chemistry": "Li-ion",
            "positive_electrode_basis": "NMC",
            "negative_electrode_basis": "graphite",
            "construction": {
                "assembly_type": "stacked",
                "layering": "single_layer",
                "layer_count": 1,
                "assembly_sequence": ["CellCan", "NegativeElectrode", "Separator", "Electrolyte", "Spring", "CellLid"],
                "comment": "Single-layer alpha fixture."
            }
        }
    }

    errors = list(validator.iter_errors(sample))
    assert errors == []


def test_battery_descriptor_schema_accepts_coin_hardware_metadata() -> None:
    schema_root = ROOT / "src" / "battinfo" / "data" / "schemas"
    schema_path = schema_root / "cell-descriptor.schema.json"
    schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
    registry = _schema_registry(schema_root)
    validator = Draft202012Validator(schema_doc, registry=registry)

    sample = {
        "schema_version": "1.0.0",
        "specification": {
            "id": "https://w3id.org/battinfo/cell-type/4p7m-2q8v-6n3t-9k5r",
            "manufacturer": "ExampleCells",
            "model": "CR2032-ALPHA",
            "format": "coin",
            "chemistry": "Li-ion",
            "positive_electrode_basis": "NMC",
            "negative_electrode_basis": "graphite",
            "coin_hardware": {
                "case": {
                    "size_code": "R2032",
                    "material": "Stainless steel",
                    "supplier": "CaseVendor GmbH",
                    "product_id": "2032, SUS316L"
                },
                "lid": {
                    "material": "Stainless steel",
                    "coating": "Au",
                    "manufacturer": "LidCo"
                },
                "can": {
                    "material": "Stainless steel",
                    "coating": "Ni",
                    "supplier": "CanParts"
                },
                "spring": {
                    "supplier": "SpringParts",
                    "property": {
                        "diameter": {"value": 15.0, "unit": "mm"},
                        "thickness": {"value": 1.4, "unit": "mm"}
                    }
                },
                "spacer": {
                    "property": {
                        "diameter": {"value": 16.0, "unit": "mm"},
                        "thickness": {"value": 1.0, "unit": "mm"}
                    }
                }
            }
        }
    }

    errors = list(validator.iter_errors(sample))
    assert errors == []


def test_battery_descriptor_schema_accepts_component_provenance_fields() -> None:
    schema_root = ROOT / "src" / "battinfo" / "data" / "schemas"
    schema_path = schema_root / "cell-descriptor.schema.json"
    schema_doc = json.loads(schema_path.read_text(encoding="utf-8"))
    registry = _schema_registry(schema_root)
    validator = Draft202012Validator(schema_doc, registry=registry)

    sample = {
        "schema_version": "1.0.0",
        "specification": {
            "id": "https://w3id.org/battinfo/cell-type/7p8m-2q4v-6n3t-9k5r",
            "manufacturer": "ExampleCells",
            "model": "COIN-PROV-01",
            "format": "coin",
            "chemistry": "Li-ion",
            "positive_electrode_basis": "NMC",
            "negative_electrode_basis": "graphite",
            "positive_electrode": {
                "manufacturer": "ElectrodeCo",
                "product_id": "PE-001",
                "current_collector": {
                    "name": "Aluminium",
                    "supplier": "FoilSource",
                    "product_id": "AL-15"
                },
                "coating": {
                    "supplier": "CathodeMix BV",
                    "component": {
                        "active_material": [
                            {
                                "name": "NMC",
                                "manufacturer": "CAM Inc.",
                                "product_id": "NMC-622"
                            }
                        ]
                    }
                }
            },
            "electrolyte": {
                "family": "organic",
                "manufacturer": "ElectrolyteLab",
                "solvent_mixture": {
                    "supplier": "BlendSupplier",
                    "component": [
                        {"name": "EC", "manufacturer": "SolventCo"},
                        {"name": "EMC", "product_id": "EMC-70"}
                    ]
                },
                "salt": {
                    "name": "LiPF6",
                    "supplier": "SaltVendor",
                    "product_id": "LPF6-1M"
                }
            },
            "separator": {
                "material": "PP",
                "manufacturer": "SeparatorCo",
                "supplier": "SeparatorDistributor",
                "product_id": "PP-25"
            }
        }
    }

    errors = list(validator.iter_errors(sample))
    assert errors == []

