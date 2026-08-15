from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.validate import ValidationPolicy, validate_semantic_report

STRICT_SEMANTIC = ValidationPolicy(name="strict-semantic", semantic="error")


def _load_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_semantic_validation_accepts_canonical_cell_spec_example() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert report.ok
    assert not report.errors


def test_semantic_validation_rejects_short_id_mismatch() -> None:
    doc = _load_json("src/battinfo/data/examples/test/test-5p7v-2n8k-4m3t-6q9r.json")
    doc["test"]["short_id"] = "xxxxxx"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert report.errors[0].code == "semantic.short_id_mismatch"


def test_semantic_validation_rejects_unit_mismatch_for_specs() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["properties"]["nominal_capacity"]["unit"] = "V"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.unit_mismatch" for issue in report.errors)


def test_semantic_validation_rejects_unit_mismatch_for_continuous_current_specs() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["properties"]["maximum_continuous_charging_current"]["unit"] = "V"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.unit_mismatch" for issue in report.errors)


# D-1: these unit-bearing SpecSet props previously had NO unit-compatibility entry, so any unit
# (e.g. state_of_health in 'furlongs') passed strict/publisher and flowed to submit.
@pytest.mark.parametrize(
    "spec_key, bad_unit",
    [
        ("state_of_health", "furlongs"),
        ("initial_coulombic_efficiency", "kg"),
        ("ac_internal_resistance", "%"),
        ("self_discharge_rate", "volts"),
    ],
)
def test_semantic_validation_rejects_bad_unit_for_health_specs(spec_key: str, bad_unit: str) -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["properties"][spec_key] = {"value": 50, "unit": bad_unit}
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.unit_mismatch" for issue in report.errors)


@pytest.mark.parametrize(
    "spec_key, good_unit",
    [("state_of_health", "%"), ("initial_coulombic_efficiency", "%"), ("ac_internal_resistance", "mOhm")],
)
def test_semantic_validation_accepts_valid_unit_for_health_specs(spec_key: str, good_unit: str) -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["properties"][spec_key] = {"value": 50, "unit": good_unit}
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not any(issue.code == "semantic.unit_mismatch" for issue in report.errors)


def test_semantic_validation_rejects_invalid_spec_range_ordering() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["properties"]["minimum_storage_temperature"]["value"] = 70
    doc["properties"]["maximum_storage_temperature"]["value"] = 60
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.range_invalid" for issue in report.errors)


def test_semantic_validation_rejects_invalid_dataset_temporal_order_and_checksum() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    doc["dataset"]["modified_at"] = doc["dataset"]["created_at"] - 1
    doc["dataset"]["distributions"][0]["checksum"]["value"] = "xyz"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    codes = {issue.code for issue in report.errors}
    assert "semantic.temporal_order_invalid" in codes
    assert "semantic.checksum_invalid" in codes


def test_semantic_validation_rejects_dataset_without_cell_link() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    doc["dataset"]["about"] = ["https://w3id.org/battinfo/test/5p7v-2n8k-4m3t-6q9r"]
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.dataset_missing_cell_link" for issue in report.errors)


def test_semantic_validation_allows_dataset_with_cell_spec_link_only() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    doc["dataset"]["about"] = ["https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5"]
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert report.ok


def test_semantic_validation_allows_dataset_without_test_link_when_cell_is_present() -> None:
    doc = _load_json("src/battinfo/data/examples/dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    doc["dataset"]["about"] = ["https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8"]
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert report.ok


def test_semantic_validation_warns_for_unmapped_controlled_value() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["cell_spec"]["chemistry"] = "VeryNewChem"
    report = validate_semantic_report(doc)
    assert report.ok
    assert report.warnings
    assert report.warnings[0].code == "semantic.controlled_value_unmapped"


def test_semantic_validation_defaults_to_warning_mode_for_hard_rules() -> None:
    doc = _load_json("src/battinfo/data/examples/test/test-5p7v-2n8k-4m3t-6q9r.json")
    doc["test"]["short_id"] = "xxxxxx"
    report = validate_semantic_report(doc)
    assert report.ok
    assert report.warnings
    assert report.warnings[0].code == "semantic.short_id_mismatch"


def test_semantic_validation_rejects_size_code_without_round_or_pouch_prefix() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["cell_spec"]["size_code"] = "26650"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.size_code_invalid" for issue in report.errors)


def test_semantic_validation_rejects_size_code_prefix_mismatch_for_format() -> None:
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["cell_spec"]["size_code"] = "P20/50/50"
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    assert not report.ok
    assert any(issue.code == "semantic.size_code_prefix_mismatch" for issue in report.errors)

# ── #299: unmapped property keys surface on COMPONENT records too ─────────────


def test_component_property_unmapped_key_warns() -> None:
    rec = {
        "schema_version": "0.2.0",
        "material_spec": {
            "id": "https://w3id.org/battinfo/material-spec/aaaa-bbbb-cccc-dddd",
            "name": "X",
            "property": {
                "made_up_prop": {"value": 1.0, "unit": "g"},
                "density": {"value": 1.2, "unit": "g/cm3"},
                "porosity": {"value": 40, "unit": "%"},
            },
        },
        "provenance": {"source_type": "datasheet"},
    }
    report = validate_semantic_report(rec, policy=STRICT_SEMANTIC)
    hits = [(i.severity, i.path) for i in report.issues if i.code == "semantic.property_unmapped"]
    # density/porosity resolve through the transform's descriptor/fraction
    # tables and must NOT warn; the invented key must.
    assert hits == [("warning", "material_spec.property.made_up_prop")]


def test_coating_property_unmapped_key_warns_with_coating_path() -> None:
    rec = {
        "schema_version": "0.2.0",
        "electrode_spec": {
            "id": "https://w3id.org/battinfo/electrode-spec/aaaa-bbbb-cccc-dddd",
            "name": "E",
            "coating": {
                "property": {
                    "loading": {"value": 6.6, "unit": "mg/cm2"},
                    "thickness": {"value": 16, "unit": "um"},
                    "junk_key": {"value": 1, "unit": "g"},
                }
            },
        },
        "provenance": {"source_type": "datasheet"},
    }
    report = validate_semantic_report(rec, policy=STRICT_SEMANTIC)
    hits = [i.path for i in report.issues if i.code == "semantic.property_unmapped"]
    assert hits == ["electrode_spec.coating.property.junk_key"]


def test_property_unmapped_message_matches_transform_reality() -> None:
    # The transform emits unmapped keys under a battinfo: fallback term — it
    # does not omit them. The warning must say what actually happens.
    doc = _load_json("src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json")
    doc["properties"]["frobnication_index"] = {"value": 1.0, "unit": "%"}
    report = validate_semantic_report(doc, policy=STRICT_SEMANTIC)
    issue = next(i for i in report.issues if i.code == "semantic.property_unmapped")
    assert "fallback" in issue.message
    assert "OMITTED" not in issue.message


# ── The validator must accept exactly what the emitters map ───────────────────
# _component_property_terms() used to name the transform's term tables one by
# one. #342 added _ELECTRODE_PROPERTY_TERMS to the emitter and nothing added it
# here, so a correct electrode design value warned that it had no mapping — while
# the helper's own docstring claimed the set "can never drift". Three warnings
# for zero defects in the Flores corpus (E5), and _MATERIAL_PROPERTY_TERMS had
# drifted the same way for eight more keys.


@pytest.mark.parametrize(
    "key", ["areal_capacity", "nominal_areal_capacity", "reversible_areal_capacity"]
)
def test_electrode_design_values_do_not_warn(key: str) -> None:
    """E5: the electrode emitter maps these to AreicCapacity; nothing may warn."""
    rec = {
        "schema_version": "0.2.0",
        "electrode_spec": {
            "id": "https://w3id.org/battinfo/electrode-spec/aaaa-bbbb-cccc-dddd",
            "name": "Purchased graphite electrode",
            "kind": "graphite",
            "property": {key: {"value": 3.4, "unit": "mA.h/cm2"}},
        },
        "provenance": {"source_type": "datasheet"},
    }
    report = validate_semantic_report(rec, policy=STRICT_SEMANTIC)
    assert [i.code for i in report.issues] == []


@pytest.mark.parametrize("key", ["bet_surface_area", "specific_capacity", "particle_size_d50"])
def test_material_datasheet_values_do_not_warn(key: str) -> None:
    """Same drift on _MATERIAL_PROPERTY_TERMS: ordinary powder datasheet keys."""
    rec = {
        "schema_version": "0.2.0",
        "material_spec": {
            "id": "https://w3id.org/battinfo/material-spec/aaaa-bbbb-cccc-dddd",
            "name": "Graphite powder",
            "property": {key: {"value": 2.5, "unit": "m2/g"}},
        },
        "provenance": {"source_type": "datasheet"},
    }
    hits = [
        i.path
        for i in validate_semantic_report(rec, policy=STRICT_SEMANTIC).issues
        if i.code == "semantic.property_unmapped"
    ]
    assert hits == []


def test_every_emitter_property_table_is_registered() -> None:
    """A new holder term table must join the registry the validator reads.

    Naming the tables in two places is what allowed the drift. The emitter now
    exports one registry; this pins that no ``_<holder>_PROPERTY_TERMS`` can be
    added to the transform without appearing in it.
    """
    from battinfo.transform import json_to_jsonld as emitter

    registered = {id(table) for table in emitter.COMPONENT_PROPERTY_TERM_TABLES}
    unregistered = sorted(
        name
        for name in dir(emitter)
        if name.endswith("_PROPERTY_TERMS") and id(getattr(emitter, name)) not in registered
    )
    assert not unregistered, (
        "property term tables the emitter uses but COMPONENT_PROPERTY_TERM_TABLES "
        "does not list, so the semantic validator will warn about keys the emitter "
        f"maps: {unregistered}"
    )


def test_validator_known_keys_equal_the_emitter_registry() -> None:
    """The invariant the docstring claims, asserted rather than assumed."""
    from battinfo.transform.json_to_jsonld import COMPONENT_PROPERTY_TERM_TABLES
    from battinfo.validate.semantic import _component_property_terms

    expected = {key for table in COMPONENT_PROPERTY_TERM_TABLES for key in table}
    assert set(_component_property_terms()) == expected

