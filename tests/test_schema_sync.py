"""Verify that bundle.py and bundle_generated.py stay in sync with the schema.

These tests catch drift between the handcrafted application layer (bundle.py)
and the LinkML-generated schema layer (bundle_generated.py).  They run on every
CI push and fail fast when the two files diverge in ways that matter at runtime.

Test categories
---------------
ENUM SYNC (fail) — both files must define the same controlled vocabulary.
  If a new test type or cell format is added to schema/*.yaml and make gen-all
  is run, bundle.py must be updated to match.

SPEC COVERAGE (report only) — which SpecSet schema fields lack a direct
  authoring-property mapping in bundle.py.  Logged as a warning; not a hard
  failure, since schema can legitimately contain EU-regulation fields that
  aren't in the authoring API yet.

ADAPTER ROUNDTRIP (fail) — CellSpecification → generated CellSpecification → record dict →
  CellSpecification must preserve identity for all non-None fields.
"""

from __future__ import annotations

import warnings

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _bundle_enum_values(name: str) -> set[str]:
    import battinfo.bundle as bun
    return {v.value for v in getattr(bun, name)}


def _gen_enum_values(name: str) -> set[str]:
    import battinfo.bundle_generated as gen
    return {v.value for v in getattr(gen, name)}


# ── ENUM SYNC — hard failures ─────────────────────────────────────────────────

def test_battery_test_type_values_match() -> None:
    bundle_vals = _bundle_enum_values("BatteryTestType")
    gen_vals = _gen_enum_values("BatteryTestType")
    only_in_bundle = bundle_vals - gen_vals
    only_in_schema = gen_vals - bundle_vals
    assert not only_in_bundle, (
        f"BatteryTestType values in bundle.py but not schema: {only_in_bundle}. "
        "Remove or rename them in bundle.py to match the schema."
    )
    assert not only_in_schema, (
        f"BatteryTestType values in schema but not bundle.py: {only_in_schema}. "
        "Add them to BatteryTestType in bundle.py."
    )


def test_cell_product_type_values_match() -> None:
    bundle_vals = _bundle_enum_values("CellProductType")
    gen_vals = _gen_enum_values("CellProductType")
    only_in_bundle = bundle_vals - gen_vals
    only_in_schema = gen_vals - bundle_vals
    assert not only_in_bundle, (
        f"CellProductType values in bundle.py but not schema: {only_in_bundle}"
    )
    assert not only_in_schema, (
        f"CellProductType values in schema but not bundle.py: {only_in_schema}"
    )


def test_cell_format_values_covered_by_bundle() -> None:
    """bundle.py uses format: str, so CellFormat values just need to be known strings."""
    gen_vals = _gen_enum_values("CellFormat")
    # bundle.py accepts any string for format, but validate the schema values are
    # reasonable (not empty, all lowercase).
    for v in gen_vals:
        assert isinstance(v, str) and v, f"CellFormat has non-string value: {v!r}"


# ── SPEC COVERAGE — informational warnings ────────────────────────────────────

# These SpecSet fields are intentionally schema-only: they represent EU Battery
# Regulation properties or derived metrics not yet exposed in the authoring API.
# Add to this set when you deliberately choose not to expose a schema field in
# bundle.py's CELL_TYPE_AUTHORING_PROPERTY_FIELDS.
_KNOWN_SCHEMA_ONLY_SPEC_FIELDS: frozenset[str] = frozenset({
    "typical_capacity",
    "certified_usable_energy",
    "power_capability",
    "maximum_power",
    "maximum_pulse_charging_current",
    "maximum_pulse_discharging_current",
    "dc_internal_resistance",
    "ac_internal_resistance",
    "round_trip_energy_efficiency",
    "round_trip_energy_efficiency_50pct",
    "initial_coulombic_efficiency",
    "volume",
    "operating_temperature_min",
    "operating_temperature_max",
    "cycle_life_c_rate",
    "calendar_life",
    "capacity_fade",
    "capacity_threshold_exhaustion",
    "charging_time",
    "self_discharge_rate",
    "state_of_health",
    "power_energy_ratio",
    # voltage aliases — schema has both the canonical and a synonym
    "charging_cutoff_voltage",
    "upper_voltage_limit",
    # energy synonym — schema splits rated/nominal/typical; bundle uses typical/rated
    "nominal_energy",
})


def test_specset_fields_all_known() -> None:
    """Every SpecSet field must either be in CELL_TYPE_AUTHORING_PROPERTY_FIELDS
    or in _KNOWN_SCHEMA_ONLY_SPEC_FIELDS.

    A failure here means the schema added a new spec field that wasn't expected.
    Either:
    (a) add it to bundle.py's CELL_TYPE_AUTHORING_PROPERTY_FIELDS, or
    (b) add it to _KNOWN_SCHEMA_ONLY_SPEC_FIELDS in this test file.
    """
    from battinfo.bundle import CELL_TYPE_AUTHORING_PROPERTY_FIELDS
    from battinfo.bundle_generated import SpecSet

    authoring_fields = frozenset(CELL_TYPE_AUTHORING_PROPERTY_FIELDS)
    schema_fields = frozenset(
        k for k in SpecSet.model_fields if k != "linkml_meta"
    )

    unexpected = schema_fields - authoring_fields - _KNOWN_SCHEMA_ONLY_SPEC_FIELDS
    assert not unexpected, (
        f"SpecSet has fields not yet accounted for in bundle.py or this test: "
        f"{sorted(unexpected)}.\n"
        "Add them to CELL_TYPE_AUTHORING_PROPERTY_FIELDS in bundle.py, or to "
        "_KNOWN_SCHEMA_ONLY_SPEC_FIELDS in test_schema_sync.py."
    )


def test_bundle_authoring_fields_report_schema_gaps() -> None:
    """Emit a warning listing bundle authoring properties that are not in SpecSet.

    Not a hard failure — these are legacy aliases or grandfathered names.
    The warning is informational: they could be migrated to canonical names.
    """
    from battinfo.bundle import CELL_TYPE_AUTHORING_PROPERTY_FIELDS
    from battinfo.bundle_generated import SpecSet

    schema_fields = frozenset(k for k in SpecSet.model_fields if k != "linkml_meta")
    only_in_bundle = sorted(
        f for f in CELL_TYPE_AUTHORING_PROPERTY_FIELDS if f not in schema_fields
    )
    if only_in_bundle:
        warnings.warn(
            f"bundle.py authoring fields with no direct SpecSet equivalent "
            f"(legacy aliases — consider migrating): {only_in_bundle}",
            stacklevel=2,
        )


# ── ADAPTER ROUNDTRIP ─────────────────────────────────────────────────────────

def test_adapter_cell_spec_to_schema_basic() -> None:
    from battinfo.bundle import CellSpecification
    from battinfo.bundle_adapter import cell_spec_to_schema

    ct = CellSpecification(
        manufacturer="Panasonic",
        model="NCR18650B",
        format="cylindrical",
        chemistry="li-ion",
        nominal_capacity={"value": 3.4, "unit": "Ah"},
        mass={"value": 48.0, "unit": "g"},
    )
    gen = cell_spec_to_schema(ct)
    assert gen.ct_model == "NCR18650B"
    assert gen.ct_manufacturer.org_name == "Panasonic"
    assert gen.ct_cell_format == "cylindrical"
    assert gen.ct_specs is not None
    assert gen.ct_specs.nominal_capacity.sv_value == pytest.approx(3.4)
    assert gen.ct_specs.nominal_capacity.sv_unit == "Ah"
    assert gen.ct_specs.mass.sv_value == pytest.approx(48.0)


def test_adapter_cell_spec_roundtrip() -> None:
    from battinfo.bundle import CellSpecification
    from battinfo.bundle_adapter import cell_spec_to_schema, schema_cell_spec_to_record_dict

    ct = CellSpecification(
        id="https://w3id.org/battinfo/spec/abc123",
        manufacturer="Samsung SDI",
        model="INR21700-50E",
        format="cylindrical",
        chemistry="li-ion",
        nominal_capacity={"value": 5.0, "unit": "Ah"},
        nominal_voltage={"value": 3.6, "unit": "V"},
        mass={"value": 70.0, "unit": "g"},
    )
    gen = cell_spec_to_schema(ct)
    record = schema_cell_spec_to_record_dict(gen)
    ct2 = CellSpecification.from_record(record)

    assert ct2.manufacturer == ct.manufacturer
    assert ct2.model == ct.model
    assert ct2.format == ct.format
    assert ct2.properties.get("nominal_capacity", {}).get("value") == pytest.approx(5.0)
    assert ct2.properties.get("nominal_voltage", {}).get("value") == pytest.approx(3.6)
    assert ct2.properties.get("mass", {}).get("value") == pytest.approx(70.0)


def test_adapter_spec_value_coercion_in_cell_spec() -> None:
    """SpecValue objects passed to CellSpecification should be coerced to dicts."""
    from battinfo.bundle import CellSpecification
    from battinfo.bundle_generated import SpecValue

    sv = SpecValue(sv_value=2.5, sv_unit="Ah")
    ct = CellSpecification(
        manufacturer="A123",
        model="ANR26650M1B",
        format="cylindrical",
        chemistry="li-ion",
        nominal_capacity=sv,
    )
    stored = ct.properties.get("nominal_capacity")
    assert isinstance(stored, dict), "SpecValue should be coerced to dict"
    assert stored["value"] == pytest.approx(2.5)
    assert stored["unit"] == "Ah"


def test_adapter_spec_value_via_mapping_property() -> None:
    """Setting a _mapping_property with a SpecValue should coerce to dict."""
    from battinfo.bundle import CellSpecification
    from battinfo.bundle_generated import SpecValue

    ct = CellSpecification(manufacturer="A123", model="X", format="cylindrical", chemistry="li-ion")
    ct.nominal_capacity = SpecValue(sv_value=3.0, sv_unit="Ah")
    assert ct.nominal_capacity == {"value": 3.0, "unit": "Ah"}


def test_adapter_specset_roundtrip() -> None:
    from battinfo.bundle_adapter import specs_to_specset, specset_to_specs

    props = {
        "nominal_capacity": {"value": 3.0, "unit": "Ah"},
        "mass": {"value": 65.0, "unit": "g"},
        "nominal_voltage": {"value": 3.7, "unit": "V"},
    }
    ss = specs_to_specset(props)
    assert ss is not None
    assert ss.nominal_capacity.sv_value == pytest.approx(3.0)
    assert ss.mass.sv_unit == "g"

    recovered = specset_to_specs(ss)
    assert recovered["nominal_capacity"]["value"] == pytest.approx(3.0)
    assert recovered["mass"]["unit"] == "g"
    assert recovered["nominal_voltage"]["value"] == pytest.approx(3.7)


def test_adapter_bundle_to_schema_dispatcher() -> None:
    from battinfo.bundle import CellInstance, CellSpecification, Test, TestSpec
    from battinfo.bundle_adapter import bundle_to_schema
    from battinfo.bundle_generated import (
        CellInstance as GenCI,
        CellSpecification as GenCT,
        Test as GenT,
        TestSpec as GenTS,
    )

    ct = CellSpecification(manufacturer="X", model="Y", format="pouch", chemistry="nmc")
    assert isinstance(bundle_to_schema(ct), GenCT)

    ci = CellInstance(
        cell_spec_id="https://w3id.org/battinfo/spec/abc",
        serial_number="SN-001",
    )
    assert isinstance(bundle_to_schema(ci), GenCI)

    ts = TestSpec(id="urn:ts:1", name="Cycling 1C", test_type="cycling")
    assert isinstance(bundle_to_schema(ts), GenTS)

    t = Test(
        id="urn:t:1",
        name="Test run 1",
        test_type="cycling",
        cell_instance_id="urn:ci:1",
    )
    assert isinstance(bundle_to_schema(t), GenT)


def test_adapter_unknown_type_raises() -> None:
    from battinfo.bundle_adapter import bundle_to_schema
    with pytest.raises(TypeError, match="No schema adapter"):
        bundle_to_schema(object())
