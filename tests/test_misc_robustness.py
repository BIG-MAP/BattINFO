"""Regression tests for assorted robustness defects from the adversarial audit
(misc mediums M9/M10/M11/M14 + low L9).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from battinfo.interop.battery_data_commons import import_bdc_record, to_bdc_record  # noqa: E402
from battinfo.interop.converter import import_converter_jsonld_record  # noqa: E402
from battinfo.testmethod import ExperimentSyntaxError, parse_step  # noqa: E402


def test_converter_graph_with_string_first_node_does_not_crash() -> None:
    # M9: a @graph whose first element is a bare string/IRI must not raise a cryptic
    # dict(<str>) ValueError.
    result = import_converter_jsonld_record({"@graph": ["https://example.org/iri", {"@type": "Dataset", "@id": "./"}]})
    assert result is not None


def test_bdc_roundtrip_does_not_fabricate_manufacturer_or_model() -> None:
    # M10: a record with no manufacturer/model must not gain 'Unknown' / id-fallback
    # values on a round-trip back to the commons.
    imported = import_bdc_record(
        {"id": "bdc_nomanu", "overview": {"case": "CoinCase"}, "electrodes": {"positive": "LFP"}},
        validate=False,
    )
    overview = to_bdc_record(imported.cell_spec)["overview"]
    assert "manufacturer" not in overview
    assert "battery_model" not in overview


def test_bdc_roundtrip_preserves_real_manufacturer_and_model() -> None:
    imported = import_bdc_record(
        {"id": "bdc_real", "overview": {"case": "CoinCase", "manufacturer": "Acme", "battery_model": "AC-18650"},
         "electrodes": {"positive": "LFP"}},
        validate=False,
    )
    overview = to_bdc_record(imported.cell_spec)["overview"]
    assert overview["manufacturer"] == "Acme"
    assert overview["battery_model"] == "AC-18650"


def test_bdc_null_categories_are_filtered_not_stringified() -> None:
    # M11: a JSON null category must not become the literal keyword 'None'.
    imported = import_bdc_record(
        {"id": "bdc_cat", "overview": {"case": "CoinCase"}, "electrodes": {"positive": "LFP"},
         "categories": [None, "performance", ""]},
        validate=True,
    )
    keywords = imported.dataset["dataset"].get("keywords")
    assert "None" not in keywords
    assert "performance" in keywords


@pytest.mark.parametrize("step", [
    "Charge at 4.2.1 V",
    "Rest for 1.2.3 hours",
    "Discharge at C/1.2.3 until 4.2 V",
    "Discharge at 1..2 C",
])
def test_parse_step_multidot_raises_experiment_syntax_error(step: str) -> None:
    # M14: malformed numbers must raise the documented ExperimentSyntaxError, not a
    # bare ValueError (which callers' `except ExperimentSyntaxError` would miss).
    with pytest.raises(ExperimentSyntaxError):
        parse_step(step)


def test_parse_step_unicode_ohm_symbol_parses() -> None:
    # L9: the unicode ohm symbol Ω must parse to a resistance step (it was unreachable).
    step = parse_step("Discharge at 5 Ω")
    setpoints = getattr(step, "setpoints", None) or {}
    assert "resistance" in setpoints
    assert setpoints["resistance"].value == 5.0


def test_import_discovery_xlsx_empty_sheet_returns_empty_package(tmp_path: Path) -> None:
    # L1: an empty target sheet must yield an empty package, not an IndexError.
    from openpyxl import Workbook

    from battinfo import import_discovery_xlsx
    wb = Workbook()
    wb.active.title = "Automated cells"
    path = tmp_path / "empty.xlsx"
    wb.save(path)
    pkg = import_discovery_xlsx(path)
    assert len(getattr(pkg, "cell_specs", []) or []) == 0


def test_bdc_bool_capacity_is_rejected() -> None:
    # L2: a boolean must not be accepted as a numeric capacity (bool is an int subclass).
    imp = import_bdc_record(
        {"id": "b", "overview": {"case": "CoinCase"}, "electrodes": {"positive": "LFP"},
         "reported_values": {"rated_capacity_Ah": True}},
        validate=False,
    )
    props = imp.cell_spec.get("cell_spec", {}).get("properties") or {}
    assert "nominal_capacity" not in props


def test_bdc_string_overview_does_not_crash() -> None:
    # L3: a scalar where a mapping is expected must not raise a bare AttributeError.
    import_bdc_record({"id": "b2", "overview": "CoinCase"}, validate=False)


def test_checksum_algorithm_lookup_is_case_insensitive() -> None:
    # L5: an uppercase 'SHA256' must not bypass the hex/length checksum check.
    from battinfo.validate import validate_semantic
    doc = {"dataset": {
        "id": "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-dddd",
        "about": ["https://w3id.org/battinfo/cell/1111-2222-3333-4444"],
        "distributions": [{"checksum": {"algorithm": "SHA256", "value": "nothex"}}],
    }}
    res = validate_semantic(doc, policy="strict")
    assert any(i.code == "semantic.checksum_invalid" for i in res.issues)


def test_snake_alias_collision_prefers_canonical_deterministically() -> None:
    # L8: when both camelCase and snake_case keys are present, the snake_case value
    # must win regardless of dict order (no silent, order-dependent data loss).
    from battinfo.canonical_aliases import record_to_snake_aliases
    a = record_to_snake_aliases({"cell_spec": {"countryOfOrigin": "JP", "country_of_origin": "CN"}})
    b = record_to_snake_aliases({"cell_spec": {"country_of_origin": "CN", "countryOfOrigin": "JP"}})
    assert a["cell_spec"]["country_of_origin"] == "CN"
    assert b["cell_spec"]["country_of_origin"] == "CN"


def test_find_records_repo_tolerates_shallow_path() -> None:
    # ws.py: a shallow workspace path (few ancestors) must not raise IndexError.
    from battinfo.ws import _find_records_repo
    assert _find_records_repo(Path("c:/tmp/x")) is None or True  # just must not raise
