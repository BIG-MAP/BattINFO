"""Unit checks on spec properties: canonical symbols, case, and one dimension per property.

Validation reads a unit the way the JSON-LD emitter does (normalize_unit_symbol), so
'µm', 'g/cm³' and '℃' pass where the emitter resolves them. Case is kept where it
changes magnitude: 'MV' is a megavolt, so it is a strict error that suggests 'mV',
while 'ah' passes with a warning that names 'Ah'. A unit with no EMMO unit IRI draws
the semantic.unit_unmapped warning. Every unit a property accepts has one dimension,
which rules out mAh/g for a specific energy, a C-rate for a current and a bare
percentage for a self-discharge rate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.cli import app
from battinfo.transform.json_to_jsonld import _unit_iri, normalize_unit_symbol
from battinfo.validate import ValidationPolicy, validate_record_report, validate_semantic_report
from battinfo.validate.semantic import SPEC_PLAUSIBILITY_BOUNDS, SPEC_UNIT_COMPATIBILITY

STRICT = ValidationPolicy(name="strict", semantic="error")
EXAMPLES = ROOT / "src" / "battinfo" / "data" / "examples"
A123 = EXAMPLES / "cell-spec" / "A123__ANR26650M1-B.json"
LFP = EXAMPLES / "material-spec" / "5ms1-9jv8-hr54-mn4e.json"

CURRENT_KEYS = (
    "pulse_charging_current",
    "continuous_charging_current",
    "nominal_continuous_charging_current",
    "maximum_continuous_charging_current",
    "maximum_pulse_charging_current",
    "pulse_discharging_current",
    "continuous_discharging_current",
    "nominal_continuous_discharging_current",
    "maximum_continuous_discharging_current",
    "maximum_pulse_discharging_current",
)


def _cell_spec(**properties: dict) -> dict:
    doc = json.loads(A123.read_text(encoding="utf-8"))
    doc["properties"].update(properties)
    return doc


def _material_spec(**properties: dict) -> dict:
    doc = json.loads(LFP.read_text(encoding="utf-8"))
    doc["material_spec"]["property"].update(properties)
    return doc


def _at(report, code: str, path: str) -> list:
    return [issue for issue in report.issues if issue.code == code and issue.path == path]


# ── Case: a variant that changes magnitude is an error, any other a warning ──────


@pytest.mark.parametrize(
    ("key", "unit", "meant"),
    [
        ("nominal_voltage", "MV", "mV"),
        ("power_capability", "MW", "mW"),
        ("typical_energy", "MWh", "mWh"),
        ("pulse_charging_current", "MA", "mA"),
        ("internal_resistance", "MΩ", "mΩ"),
        ("internal_resistance", "MOhm", "mΩ"),
        ("nominal_capacity", "MAh", "mAh"),
        ("mass", "Mg", "mg"),
        ("diameter", "MM", "mm"),
    ],
)
def test_a_case_variant_that_changes_magnitude_is_a_strict_error(key: str, unit: str, meant: str) -> None:
    report = validate_semantic_report(_cell_spec(**{key: {"value": 3300, "unit": unit}}), policy=STRICT)
    errors = _at(report, "semantic.unit_mismatch", f"properties.{key}")
    assert len(errors) == 1 and errors[0].severity == "error"
    assert f"Did you mean '{meant}'?" in errors[0].message
    assert "mega" in errors[0].message
    # One issue for one unit: the mismatch, not also an unmapped-unit warning.
    assert not _at(report, "semantic.unit_unmapped", f"properties.{key}")


def test_a_magnitude_variant_is_a_warning_under_the_default_policy() -> None:
    report = validate_semantic_report(_cell_spec(nominal_voltage={"value": 3300, "unit": "MV"}))
    issues = _at(report, "semantic.unit_mismatch", "properties.nominal_voltage")
    assert [issue.severity for issue in issues] == ["warning"]


@pytest.mark.parametrize(
    ("key", "unit", "canonical"),
    [
        ("nominal_capacity", "ah", "Ah"),
        ("nominal_voltage", "v", "V"),
        ("typical_energy", "kwh", "kWh"),
        ("mass", "KG", "kg"),
        ("maximum_continuous_discharging_current", "a", "A"),
        ("internal_resistance", "mω", "mΩ"),
        ("minimum_storage_temperature", "C", "°C"),
        ("minimum_storage_temperature", "degc", "°C"),
        ("cycle_life", "cycles", "count"),
        ("energy_density", "Wh/liter", "Wh/L"),
    ],
)
def test_an_unambiguous_variant_passes_with_a_warning_naming_the_symbol(key: str, unit: str, canonical: str) -> None:
    report = validate_semantic_report(_cell_spec(**{key: {"value": 2.5, "unit": unit}}), policy=STRICT)
    assert report.ok, [issue.message for issue in report.errors]
    warnings = _at(report, "semantic.unit_unmapped", f"properties.{key}")
    assert len(warnings) == 1 and warnings[0].severity == "warning"
    assert f"write '{canonical}'" in warnings[0].message
    assert _unit_iri(canonical) is not None


def test_a_canonical_symbol_with_an_iri_draws_no_warning() -> None:
    report = validate_semantic_report(_cell_spec(), policy=STRICT)
    assert report.ok
    assert not [issue for issue in report.issues if issue.code == "semantic.unit_unmapped"]


# ── Normalisation before comparing ───────────────────────────────────────────────


@pytest.mark.parametrize("unit", ["\u00b5m", "\u03bcm", "um"])  # micro sign, Greek mu, ASCII
def test_every_micrometre_spelling_passes(unit: str) -> None:
    doc = _material_spec(particle_size_d50={"value": 12.0, "unit": unit})
    report = validate_semantic_report(doc, policy=STRICT)
    assert report.ok, [issue.message for issue in report.errors]
    assert not _at(report, "semantic.unit_unmapped", "material_spec.property.particle_size_d50")


@pytest.mark.parametrize(
    ("key", "unit"),
    [("true_density", "g/cm³"), ("bet_surface_area", "m²/g"), ("density", "g/cc")],
)
def test_unicode_and_alias_spellings_pass_on_a_material_spec(key: str, unit: str) -> None:
    report = validate_semantic_report(_material_spec(**{key: {"value": 3.6, "unit": unit}}), policy=STRICT)
    assert report.ok, [issue.message for issue in report.errors]


def test_degree_celsius_sign_passes_on_a_temperature() -> None:
    doc = _cell_spec(minimum_storage_temperature={"value": -40, "unit": "℃"})
    report = validate_semantic_report(doc, policy=STRICT)
    assert report.ok, [issue.message for issue in report.errors]
    assert not _at(report, "semantic.unit_unmapped", "properties.minimum_storage_temperature")


def test_paired_specs_compare_normalised_symbols() -> None:
    doc = _cell_spec(
        minimum_storage_temperature={"value": -40, "unit": "°C"},
        maximum_storage_temperature={"value": 60, "unit": "degC"},
    )
    report = validate_semantic_report(doc, policy=STRICT)
    assert report.ok, [issue.message for issue in report.errors]


def test_cycle_life_accepts_unit_one_as_the_cell_spec_template_writes_it() -> None:
    report = validate_semantic_report(_cell_spec(cycle_life={"value": 1000, "unit": "1"}), policy=STRICT)
    assert report.ok, [issue.message for issue in report.errors]


# ── One dimension per property ───────────────────────────────────────────────────


def test_specific_energy_refuses_a_specific_capacity_unit() -> None:
    report = validate_semantic_report(_cell_spec(specific_energy={"value": 150, "unit": "mAh/g"}), policy=STRICT)
    errors = _at(report, "semantic.unit_mismatch", "properties.specific_energy")
    assert len(errors) == 1 and errors[0].severity == "error"
    assert "(valid: Wh/kg)" in errors[0].message
    ok = validate_semantic_report(_cell_spec(specific_energy={"value": 150, "unit": "Wh/kg"}), policy=STRICT)
    assert ok.ok


@pytest.mark.parametrize("key", CURRENT_KEYS)
@pytest.mark.parametrize("unit", ["C", "c"])
def test_a_c_rate_on_a_current_key_is_refused_with_the_matching_c_rate_key(key: str, unit: str) -> None:
    report = validate_semantic_report(_cell_spec(**{key: {"value": 1, "unit": unit}}), policy=STRICT)
    errors = _at(report, "semantic.unit_mismatch", f"properties.{key}")
    assert len(errors) == 1 and errors[0].severity == "error"
    rate_key = "discharging_c_rate" if "discharging" in key else "charging_c_rate"
    assert "C-rate" in errors[0].message and f"'{rate_key}'" in errors[0].message


@pytest.mark.parametrize("unit", ["%", "percent"])
def test_self_discharge_rate_refuses_a_percentage_without_a_time_base(unit: str) -> None:
    report = validate_semantic_report(_cell_spec(self_discharge_rate={"value": 3, "unit": unit}), policy=STRICT)
    errors = _at(report, "semantic.unit_mismatch", "properties.self_discharge_rate")
    assert len(errors) == 1 and "'%/month'" in errors[0].message


@pytest.mark.parametrize("unit", ["%/month", "%/day", "%/week", "%/year", "%/h", "%/hour"])
def test_self_discharge_rate_keeps_its_per_time_units(unit: str) -> None:
    report = validate_semantic_report(_cell_spec(self_discharge_rate={"value": 3, "unit": unit}), policy=STRICT)
    assert report.ok, [issue.message for issue in report.errors]


# The dimension of every unit symbol a spec property accepts. A new symbol has to be
# added here, which is the point: the table is the second opinion on each property.
UNIT_DIMENSIONS: dict[str, str] = {
    **dict.fromkeys(("Ah", "mAh"), "charge"),
    **dict.fromkeys(("Wh", "kWh", "mWh"), "energy"),
    **dict.fromkeys(("V", "mV"), "voltage"),
    **dict.fromkeys(("A", "mA"), "current"),
    **dict.fromkeys(("W", "kW", "mW"), "power"),
    **dict.fromkeys(("Ω", "mΩ"), "resistance"),
    **dict.fromkeys(("g", "kg", "mg"), "mass"),
    **dict.fromkeys(("m", "cm", "mm", "µm", "nm"), "length"),
    **dict.fromkeys(("m2", "cm2", "mm2"), "area"),
    **dict.fromkeys(("L", "mL", "cm3", "mm3"), "volume"),
    **dict.fromkeys(("s", "min", "h", "day", "days", "month", "months", "year", "years"), "time"),
    **dict.fromkeys(("°C", "K"), "temperature"),
    "%": "ratio",
    **dict.fromkeys(("count", "1"), "count"),
    **dict.fromkeys(("mAh/g", "Ah/kg"), "charge/mass"),
    "Wh/kg": "energy/mass",
    "Wh/L": "energy/volume",
    **dict.fromkeys(("W/kg", "mW/g"), "power/mass"),
    "W/L": "power/volume",
    **dict.fromkeys(("g/cm3", "kg/m3"), "mass/volume"),
    "m2/g": "area/mass",
    **dict.fromkeys(("g/mol", "kg/mol"), "mass/amount"),
    # A C-rate (A/Ah), a power-to-energy ratio and a self-discharge rate are all per time.
    **dict.fromkeys(("A/Ah", "W/Wh", "kW/kWh"), "1/time"),
    **dict.fromkeys(("%/h", "%/hour", "%/day", "%/week", "%/month", "%/year"), "1/time"),
}


def test_every_unit_of_a_property_has_the_same_dimension() -> None:
    unknown = sorted({unit for units in SPEC_UNIT_COMPATIBILITY.values() for unit in units} - set(UNIT_DIMENSIONS))
    assert not unknown, f"give these symbols a dimension in UNIT_DIMENSIONS: {unknown}"
    mixed = {
        key: sorted({UNIT_DIMENSIONS[unit] for unit in units})
        for key, units in SPEC_UNIT_COMPATIBILITY.items()
        if len({UNIT_DIMENSIONS[unit] for unit in units}) > 1
    }
    assert not mixed, f"properties whose units have more than one dimension: {mixed}"


def test_accepted_symbols_are_canonical_and_listed_once() -> None:
    for key, units in SPEC_UNIT_COMPATIBILITY.items():
        assert len(set(units)) == len(units), key
        for unit in units:
            assert normalize_unit_symbol(unit) == unit, f"{key}: {unit!r} is not the symbol the normaliser keeps"


def test_a_spelling_never_stands_for_two_units_of_one_property() -> None:
    from battinfo.validate.semantic import _UNIT_SPELLINGS

    for key, units in SPEC_UNIT_COMPATIBILITY.items():
        for spelling, targets in _UNIT_SPELLINGS.items():
            assert spelling not in units, f"{key}: {spelling!r} is a spelling, not a symbol"
            assert len(set(targets) & set(units)) <= 1, f"{key}: {spelling!r} is ambiguous"


def test_plausibility_bounds_use_accepted_units() -> None:
    for key, bounds in SPEC_PLAUSIBILITY_BOUNDS.items():
        assert key in SPEC_UNIT_COMPATIBILITY, f"bounds for {key}, which has no unit check"
        assert set(bounds) <= set(SPEC_UNIT_COMPATIBILITY[key]), key


def test_every_cell_spec_property_has_a_unit_check() -> None:
    schema = json.loads((ROOT / "assets" / "schemas" / "cell-canonical.schema.json").read_text(encoding="utf-8"))
    spec_keys = set(schema["$defs"]["SpecSet"]["properties"])
    assert not sorted(spec_keys - set(SPEC_UNIT_COMPATIBILITY))


# Example units the unit map gives no EMMO unit IRI: 'year' and '%/month', for which the
# pinned closure defines no unit, and 'W/Wh', which the closure defines as
# electrochemistry:WattPerWattHour but the map does not list.
EXAMPLE_UNITS_WITHOUT_IRI = {
    "calendar_life": "year",
    "power_energy_ratio": "W/Wh",
    "self_discharge_rate": "%/month",
}


def test_the_example_unit_resolves_to_a_unit_iri() -> None:
    missing = {key: units[0] for key, units in SPEC_UNIT_COMPATIBILITY.items() if _unit_iri(units[0]) is None}
    assert missing == EXAMPLE_UNITS_WITHOUT_IRI


def test_plausibility_bound_for_ah_per_kg_matches_mah_per_g() -> None:
    # 1 Ah/kg is 1 mAh/g, so graphite's 372 is plausible in either unit.
    for unit in ("mAh/g", "Ah/kg"):
        report = validate_semantic_report(_material_spec(specific_capacity={"value": 372, "unit": unit}))
        assert not [issue for issue in report.issues if issue.code == "semantic.value_out_of_plausible_range"]


# ── semantic.unit_unmapped ───────────────────────────────────────────────────────


def test_an_unmapped_unit_is_a_warning_under_strict() -> None:
    # molar_mass accepts kg/mol, for which the pinned closure has no unit.
    report = validate_semantic_report(_material_spec(molar_mass={"value": 0.158, "unit": "kg/mol"}), policy=STRICT)
    assert report.ok
    warnings = _at(report, "semantic.unit_unmapped", "material_spec.property.molar_mass")
    assert len(warnings) == 1 and warnings[0].severity == "warning"
    assert "'kg/mol'" in warnings[0].message and "unit_map.curated.json" in warnings[0].message


def test_an_unlisted_property_names_a_case_insensitive_match() -> None:
    doc = json.loads((EXAMPLES / "electrode-spec" / "qw3j-we77-zzj1-ya55.json").read_text(encoding="utf-8"))
    doc["electrode_spec"]["property"]["loading"] = {"value": 6.2, "unit": "MG/CM2"}
    report = validate_semantic_report(doc, policy=STRICT)
    warnings = _at(report, "semantic.unit_unmapped", "electrode_spec.property.loading")
    assert len(warnings) == 1 and "did you mean 'mg/cm2'?" in warnings[0].message


@pytest.mark.parametrize("unit", ["mPa", "mpa"])
def test_a_milli_unit_is_not_offered_its_mega_twin(unit: str) -> None:
    # The unit map knows 'MPa', a billion times a millipascal, and not 'mPa'. A viscosity
    # in 'mPa' that lacks its '.s' must not be told to write megapascals.
    report = validate_semantic_report(_material_spec(viscosity={"value": 2.5, "unit": unit}), policy=STRICT)
    (warning,) = _at(report, "semantic.unit_unmapped", "material_spec.property.viscosity")
    assert "did you mean" not in warning.message and "MPa" not in warning.message


def test_no_packaged_example_draws_unit_unmapped() -> None:
    # Every unit a packaged example states in its properties or property maps has an
    # EMMO unit IRI, including mAh/g (11 material specs) and mAh/cm2 (2 electrode specs).
    files: dict[tuple[str, str], set[str]] = {}
    for path in sorted(EXAMPLES.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or "schema_version" not in doc:
            continue
        for issue in validate_semantic_report(doc, policy=STRICT).issues:
            if issue.code == "semantic.unit_unmapped":
                quantity = doc
                for key in issue.path.split("."):
                    quantity = quantity[key]
                files.setdefault((path.parent.name, quantity["unit"]), set()).add(path.name)
    assert files == {}


def test_unit_issues_name_the_property_where_it_is() -> None:
    doc = _material_spec(specific_capacity={"value": 160, "unit": "Wh/kg"})
    report = validate_semantic_report(doc, policy=STRICT)
    assert _at(report, "semantic.unit_mismatch", "material_spec.property.specific_capacity")


def test_a_save_message_gives_the_unit_fix_without_the_shape_hint() -> None:
    from battinfo.validate.friendly import format_report_errors

    report = validate_record_report(_cell_spec(nominal_voltage={"value": 3300, "unit": "MV"}), policy="strict")
    message = format_report_errors(report)
    assert "properties.nominal_voltage: unit 'MV'" in message and "Did you mean 'mV'?" in message
    # The record did pass a quantity object; the shape example would be wrong advice here.
    assert "pass a quantity object" not in message


def test_a_full_record_check_reports_the_unit_warning() -> None:
    report = validate_record_report(_cell_spec(nominal_capacity={"value": 2.5, "unit": "ah"}), policy="strict")
    assert report.ok
    assert _at(report, "semantic.unit_unmapped", "properties.nominal_capacity")


# ── CLI and hints show canonical symbols ─────────────────────────────────────────


def test_properties_show_gives_canonical_units_and_an_example_that_resolves() -> None:
    result = CliRunner().invoke(app, ["properties", "show", "specific_energy", "--format", "json"])
    assert result.exit_code == 0, result.output
    detail = json.loads(result.output)
    assert detail["valid_units"] == "Wh/kg"
    assert detail["example"] == {"specific_energy": {"value": 0.0, "unit": "Wh/kg"}}

    result = CliRunner().invoke(app, ["properties", "show", "nominal_capacity"])
    assert "valid units: Ah, mAh" in result.output
    assert 'example:     {"nominal_capacity": {"value": 0.0, "unit": "Ah"}}' in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["properties", "list"],
        ["properties", "list", "--format", "json"],
        ["properties", "show", "internal_resistance"],
        ["properties", "show", "internal_resistance", "--format", "json"],
    ],
)
def test_properties_commands_survive_a_terminal_without_unicode(args: list[str]) -> None:
    # A Windows console redirected to a file encodes cp1252, which has no 'Ω'.
    result = CliRunner(charset="cp1252").invoke(app, args)
    assert result.exit_code == 0, repr(result.exception)


def test_properties_list_shows_symbols_not_lower_case_tokens() -> None:
    result = CliRunner().invoke(app, ["properties", "list", "--format", "json"])
    rows = {row["name"]: row["valid_units"] for row in json.loads(result.output)}
    assert rows["internal_resistance"] == "mΩ, Ω"
    assert rows["minimum_storage_temperature"] == "°C, K"
    assert rows["maximum_continuous_charging_current"] == "A, mA"
