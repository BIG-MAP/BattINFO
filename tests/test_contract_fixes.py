"""Contract fixes made before the 0.8.0 schemas are published.

Each test pins one place where the code, a schema description or an example
disagreed with the record contract: the range keys ``q()`` writes, a licence
given to one record, the superseded ``*-spec/`` IRIs, the size_code form, the
units the publication-package reader reads back and the units the BPX export
of a cell spec reads.
"""

from __future__ import annotations

import copy
import json
import math
import re
import warnings
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

import battinfo
from battinfo.interop import to_bpx
from battinfo.validate.record import validate_record_report

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
SCHEMAS = ROOT / "src" / "battinfo" / "data" / "schemas"
LIBRARY_A123 = ROOT / "src" / "battinfo" / "data" / "library" / "cell-spec" / "A123__ANR26650M1-B.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _quantity_errors(quantity: dict) -> list[str]:
    """Errors of *quantity* against the shared quantity module, as the registry serves it."""
    schema = _load(SCHEMAS / "modules" / "common" / "quantity.schema.json")
    registry = Registry().with_resource(schema["$id"], Resource.from_contents(schema))
    validator = Draft202012Validator(schema, registry=registry)
    return [error.message for error in validator.iter_errors(quantity)]


# ── q() and quantity(): the range keys the schema names ──────────────────────


def test_q_writes_min_value_max_value_and_typical_value() -> None:
    assert battinfo.q(min_value=2.5, max_value=4.2, unit="V") == {"min_value": 2.5, "max_value": 4.2, "unit": "V"}
    assert battinfo.quantity(3.6, "V", typical=3.7) == {"value": 3.6, "typical_value": 3.7, "unit": "V"}


def test_a_q_range_validates_as_a_quantity() -> None:
    assert _quantity_errors(battinfo.q(min_value=2.5, max_value=4.2, unit="V")) == []
    assert _quantity_errors(battinfo.q(typical=3.7, unit="V")) == []


def test_a_cell_spec_built_with_q_ranges_passes_strict_validation() -> None:
    spec = battinfo.CellSpec(
        id="https://w3id.org/battinfo/spec/9qfb-4wrn-ynwc-ayjw",
        manufacturer="Example Lab",
        model="EX-1",
        format="cylindrical",
        chemistry="li-ion",
        size_code="R18650",
        properties={
            "nominal_voltage": battinfo.q(min_value=2.5, max_value=4.2, unit="V"),
            "nominal_capacity": battinfo.q(typical=2.5, unit="Ah"),
        },
    )
    record = spec.to_record()
    record["provenance"]["source_type"] = "manual"
    report = validate_record_report(record, policy="strict")
    assert report.ok, [(issue.code, issue.path) for issue in report.errors]


def test_query_cell_specs_reads_a_typical_value(tmp_path: Path) -> None:
    from battinfo.api import query_cell_specs

    record = _load(EXAMPLES / "cell-spec" / "A123__ANR26650M1-B.json")
    record["properties"]["nominal_capacity"] = {"typical_value": 2.5, "unit": "Ah"}
    folder = tmp_path / "cell-spec"
    folder.mkdir()
    (folder / "a123.json").write_text(json.dumps(record), encoding="utf-8")

    hits = query_cell_specs(source_root=tmp_path, nominal_capacity_min=2.0)
    assert [hit["nominal_capacity"] for hit in hits] == [2.5]
    assert query_cell_specs(source_root=tmp_path, spec_filters={"nominal_capacity": (2.4, 2.6)})


def test_derive_cell_spec_keeps_the_range_keys_and_validates() -> None:
    from battinfo.publication import derive_cell_spec

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cell_spec = derive_cell_spec(_load(LIBRARY_A123))
    assert cell_spec.properties["nominal_capacity"] == {"typical_value": 2.5, "unit": "Ah"}
    assert cell_spec.properties["pulse_charging_current"] == {"max_value": 5.0, "unit": "A"}
    report = validate_record_report(cell_spec.to_record(), policy="strict")
    assert report.ok, [(issue.code, issue.path) for issue in report.errors]


def test_the_publication_property_node_reads_a_typical_value() -> None:
    from battinfo.publication import _cell_spec_property_node

    node = _cell_spec_property_node("nominal_capacity", {"typical_value": 2.5, "unit": "Ah"})
    assert node is not None
    assert node["hasNumericalPart"]["hasNumberValue"] == 2.5


# ── The workspace licence back-fills; it never replaces a record's own ───────


def _saved(root: Path, pattern: str) -> dict:
    return _load(next(root.rglob(pattern)))


def test_a_parameter_set_keeps_its_own_licence_through_save(tmp_path: Path) -> None:
    ws = battinfo.workspace(str(tmp_path / "ws"), registry_url=None)
    ws.license("cc0-1.0")
    ws.add(
        "parameter_set",
        name="Chen 2020 - graphite",
        material="graphite",
        license="cc-by-4.0",
        claims=[{"parameter": "particle_radius", "quantity": {"value": 5.86e-6, "unit": "m"}}],
    )
    ws.add(
        "parameter_set",
        name="Ecker 2015 - graphite",
        material="graphite",
        claims=[{"parameter": "particle_radius", "quantity": {"value": 1.37e-5, "unit": "m"}}],
    )
    ws.save()
    licences = sorted(_load(path)["license"] for path in (tmp_path / "ws").rglob("parameter-set-*.json"))
    assert licences == ["cc-by-4.0", "cc0-1.0"]


# ── Superseded *-spec/ IRIs stay accepted in component references ───────────

_OLD_MATERIAL_SPEC = "https://w3id.org/battinfo/material-spec/"
_OLD_ELECTRODE_SPEC = "https://w3id.org/battinfo/electrode-spec/"


def _with_superseded_material_spec_ids(record: dict) -> dict:
    text = json.dumps(record).replace(
        '"material_spec_id": "https://w3id.org/battinfo/spec/', f'"material_spec_id": "{_OLD_MATERIAL_SPEC}'
    )
    return json.loads(text)


def _strict_errors(record: dict) -> list[tuple[str, str]]:
    report = validate_record_report(record, policy="strict")
    return [(issue.code, issue.path) for issue in report.errors]


def test_an_electrode_spec_with_superseded_material_spec_iris_validates() -> None:
    record = _with_superseded_material_spec_ids(_load(EXAMPLES / "electrode-spec" / "277n-cp9k-3g4m-w40y.json"))
    record["electrode_spec"]["current_collector"]["material_spec_id"] = _OLD_MATERIAL_SPEC + "fwnh-2wkq-n9wm-fdab"
    assert _OLD_MATERIAL_SPEC in json.dumps(record["electrode_spec"]["coating"])
    assert _strict_errors(record) == []


@pytest.mark.parametrize("name", ["gpkh-74nj-6sdb-vcsc.json", "gzt2-hrqq-gsfn-sp94.json"])
def test_an_electrolyte_spec_with_a_superseded_salt_iri_validates(name: str) -> None:
    record = _with_superseded_material_spec_ids(_load(EXAMPLES / "electrolyte-spec" / name))
    assert _OLD_MATERIAL_SPEC in json.dumps(record["electrolyte_spec"]["salt"])
    assert _strict_errors(record) == []


def test_an_inline_electrode_with_a_superseded_electrode_spec_iri_validates() -> None:
    record = _load(EXAMPLES / "cell-spec" / "A123__ANR26650M1-B.json")
    record["positive_electrode"] = {"electrode_spec_id": _OLD_ELECTRODE_SPEC + "m5qz-ry48-xpgh-p9s3"}
    assert _strict_errors(record) == []


@pytest.mark.parametrize(
    ("field", "iri"),
    [
        ("material_spec_id", "https://w3id.org/battinfo/electrode-spec/fwnh-2wkq-n9wm-fdab"),
        ("material_spec_id", "https://w3id.org/battinfo/material/fwnh-2wkq-n9wm-fdab"),
        ("electrode_spec_id", "https://w3id.org/battinfo/material-spec/m5qz-ry48-xpgh-p9s3"),
    ],
)
def test_a_reference_to_another_family_is_still_refused(field: str, iri: str) -> None:
    record = _load(EXAMPLES / "electrode-spec" / "277n-cp9k-3g4m-w40y.json")
    if field == "material_spec_id":
        record["electrode_spec"]["coating"]["component"]["active_material"][0][field] = iri
    else:
        record = _load(EXAMPLES / "cell-spec" / "A123__ANR26650M1-B.json")
        record["positive_electrode"] = {field: iri}
    assert (
        "schema.pattern",
        f"{'electrode_spec.coating.component.active_material.0' if field == 'material_spec_id' else 'positive_electrode'}.{field}",
    ) in _strict_errors(record)


# ── size_code: the R/P form strict validation enforces ───────────────────────


@pytest.mark.parametrize("name", ["coin-detailed.example.json", "cylindrical-detailed.example.json"])
def test_the_research_examples_use_the_r_form(name: str) -> None:
    from battinfo.validate.semantic import SIZE_CODE_PATTERN

    for root in (EXAMPLES, ROOT / "src" / "battinfo" / "data" / "examples"):
        record = _load(root / "cell-spec" / "research" / name)
        assert re.fullmatch(SIZE_CODE_PATTERN, record["cell_spec"]["size_code"])
        assert _strict_errors(record) == []


_BARE_SIZE = re.compile(r"'\d+'")


def _size_code_nodes(node: object) -> list[dict]:
    """Every schema node under a ``size_code`` key, wherever it sits."""
    found: list[dict] = []
    if isinstance(node, dict):
        for key, child in node.items():
            if key == "size_code" and isinstance(child, dict):
                found.append(child)
            found.extend(_size_code_nodes(child))
    elif isinstance(node, list):
        for child in node:
            found.extend(_size_code_nodes(child))
    return found


def _size_code_descriptions() -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in ("cell-spec.schema.json", "cell-canonical.schema.json", "modules/components/specification.schema.json"):
        found = [node.get("description", "") for node in _size_code_nodes(_load(ROOT / "assets" / "schemas" / rel))]
        assert found, rel
        for index, description in enumerate(found):
            out[f"{rel}#{index}"] = description
    fragment = _load(
        ROOT
        / "src"
        / "battinfo"
        / "data"
        / "profiles"
        / "cell-spec"
        / "generated"
        / "specification-core.schema.fragment.json"
    )
    out["specification-core fragment"] = fragment["properties"]["size_code"]["description"]
    out["CellSpec.size_code"] = battinfo.CellSpec.model_fields["size_code"].description or ""
    return out


def test_size_code_descriptions_give_the_r_p_form() -> None:
    for where, description in _size_code_descriptions().items():
        assert "'R18650'" in description, where
        assert "'P" in description, where
        assert not _BARE_SIZE.search(description), (where, description)


# ── Publication-package reader: units read back as written ───────────────────


def _publication_package(tmp_path: Path, specs: dict) -> Path:
    from battinfo._workspace import Workspace

    data = tmp_path / "C01.csv"
    data.write_text("time_s,voltage_v,current_a\n0,3.0,0\n60,2.9,-0.001\n", encoding="utf-8")
    engine = Workspace(root=tmp_path / "workspace")
    spec = engine.cell_spec(
        manufacturer="Energizer",
        model="CR2032",
        format="coin",
        chemistry="li-mno2",
        size_code="R2032",
        specs=specs,
    )
    cell = engine.cell(spec, serial_number="C01")
    test = engine.test(cell, type="capacity_check", instrument="Maccor 4200")
    dataset = engine.dataset(cell, title="C01 capacity check", test=test, path=data, format="text/csv")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        engine.save()
        built = engine.build_publication_package(dataset, publication_root=str(tmp_path / "publication"))
    return Path(built.get("publish_path") or built.get("jsonld_path"))


def test_the_publication_package_reads_prefixed_units_back(tmp_path: Path) -> None:
    specs = {
        "nominal_capacity": {"value": 235, "unit": "mAh"},
        "nominal_voltage": {"value": 3000, "unit": "mV"},
        "mass": {"value": 2900, "unit": "mg"},
        "diameter": {"value": 2.0, "unit": "cm"},
        "height": {"value": 3.2, "unit": "mm"},
    }
    package = _publication_package(tmp_path, specs)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        properties = battinfo.load_publication_package(package).cell_spec.properties
    assert properties == specs


def test_unit_symbol_for_iri_reads_full_compact_and_reference_forms() -> None:
    from battinfo.jsonld import unit_symbol_for_iri

    assert unit_symbol_for_iri("https://w3id.org/emmo#MilliAmpereHour") == "mAh"
    assert unit_symbol_for_iri("emmo:MilliVolt") == "mV"
    assert unit_symbol_for_iri({"@id": "https://w3id.org/emmo#MilliGram"}) == "mg"
    assert unit_symbol_for_iri("emmo:KiloVolt") == "kV"
    assert unit_symbol_for_iri("electrochemistry:AmperePerAmpereHour") == "A/Ah"
    assert unit_symbol_for_iri("https://w3id.org/emmo#DegreeCelsius") == "°C"
    assert unit_symbol_for_iri("https://w3id.org/emmo#EMMO_5ebd5e01_0ed3_49a2_a30d_cd05cbe72978") == "1"
    # The IRI BattINFO wrote for degree Celsius by mistake before 0.8.0.
    assert unit_symbol_for_iri("https://w3id.org/emmo#EMMO_36a9bf69_483b_42fd_8a0c_7ac9206320bc") == "°C"
    assert unit_symbol_for_iri("https://example.org/units/Furlong") is None
    assert unit_symbol_for_iri("") is None
    assert unit_symbol_for_iri(None) is None


def test_every_curated_unit_reads_back_to_a_symbol_with_the_same_iri() -> None:
    from battinfo.jsonld import unit_symbol_for_iri
    from battinfo.transform.json_to_jsonld import _unit_iri

    curated = _load(ROOT / "src" / "battinfo" / "data" / "mappings" / "domain-battery" / "unit_map.curated.json")
    for entry in curated["mappings"]:
        symbol = unit_symbol_for_iri(entry["unit_iri"])
        assert symbol is not None, entry["symbol"]
        assert _unit_iri(symbol) == entry["unit_iri"], (entry["symbol"], symbol)


def _reader_node(**extra) -> dict:
    return {"@type": ["NominalVoltage", "ConventionalProperty"], **extra}


def test_the_reader_keeps_an_unknown_unit_iri_whole_and_warns() -> None:
    from battinfo.bundle import _extract_property_item

    node = _reader_node(
        hasNumericalPart={"@type": "RealData", "hasNumberValue": 1.5},
        hasMeasurementUnit="https://example.org/units/KiloVoltish",
    )
    with pytest.warns(UserWarning, match="KiloVoltish"):
        assert _extract_property_item(node) == (
            "nominal_voltage",
            {"value": 1.5, "unit": "https://example.org/units/KiloVoltish"},
        )


def test_the_reader_takes_unit_text_and_string_values() -> None:
    from battinfo.bundle import _extract_property_item

    with_text_unit = _reader_node(hasNumericalPart={"hasNumberValue": {"@value": 3.7}}, **{"schema:unitText": "V"})
    assert _extract_property_item(with_text_unit) == ("nominal_voltage", {"value": 3.7, "unit": "V"})
    with_reference = _reader_node(
        hasNumericalPart={"hasNumberValue": 3700}, hasMeasurementUnit={"@id": "emmo:MilliVolt"}
    )
    assert _extract_property_item(with_reference) == ("nominal_voltage", {"value": 3700, "unit": "mV"})
    with_text = _reader_node(
        hasNumericalPart={"hasNumberValue": 3.7},
        hasStringValue="3.7 (typical)",
        hasMeasurementUnit="https://w3id.org/emmo#Volt",
    )
    assert _extract_property_item(with_text) == (
        "nominal_voltage",
        {"value": 3.7, "value_text": "3.7 (typical)", "unit": "V"},
    )
    numeric_string = _reader_node(hasNumericalPart={"hasNumberValue": "3.7"}, hasMeasurementUnit="emmo:Volt")
    assert _extract_property_item(numeric_string) == ("nominal_voltage", {"value": 3.7, "unit": "V"})
    with pytest.warns(UserWarning, match="moved the text 'about 3.7' to value_text"):
        text_value = _reader_node(hasNumericalPart={"hasNumberValue": "about 3.7"}, hasMeasurementUnit="emmo:Volt")
        assert _extract_property_item(text_value) == ("nominal_voltage", {"value_text": "about 3.7", "unit": "V"})


def _units_deposit(tmp_path: Path) -> tuple[dict, dict[str, dict]]:
    """A deposit graph with three cell-spec properties, and its property nodes by label."""
    from battinfo.ws import AuthoringWorkspace

    source = AuthoringWorkspace(root=tmp_path / "source", registry_url=None)
    source.license("cc-by-4.0")
    spec = battinfo.CellSpec(
        manufacturer="Example Lab",
        model="EX-2",
        format="coin",
        chemistry="li-ion",
        properties={
            "nominal_capacity": {"value": 0.005, "unit": "Ah"},
            "maximum_power": {"value": 1.2, "unit": "kW"},
            "maximum_discharging_temperature": {"value": 60, "unit": "°C"},
        },
    )
    source.add("cell", spec=spec, serial_numbers=["C01"])
    source.save()
    graph = source._build_zenodo_jsonld(
        zenodo_record_id=1,
        prereserved_doi="10.5281/zenodo.1",
        record_url="https://zenodo.org/records/1",
        data_filenames=[],
        title="Units",
        creators=[{"name": "Doe, Jane"}],
    )
    [spec_node] = [n for n in graph["@graph"] if "BatteryCellSpecification" in (n.get("@type") or [])]
    return graph, {node["skos:prefLabel"]: node for node in spec_node["isDescriptionFor"]["hasProperty"]}


def test_ws_import_reads_units_through_the_same_table(tmp_path: Path) -> None:
    from battinfo.ws import AuthoringWorkspace

    graph, nodes = _units_deposit(tmp_path)
    # kW as resolve_unit_iri wrote it before the unit map named it: a records-context unit term.
    power = nodes["MaximumPower"]
    power.pop("schema:unitText", None)
    power["hasMeasurementUnit"] = "emmo:KiloWatt"
    path = tmp_path / "battinfo.json"
    path.write_text(json.dumps(graph), encoding="utf-8")

    imported = AuthoringWorkspace(root=tmp_path / "imported", registry_url=None)
    imported.import_(str(path))
    result = imported.save()  # strict by default
    assert result["index"]["failures"] == []
    [saved] = [_load(p) for p in (tmp_path / "imported" / ".battinfo" / "records" / "cell-spec").glob("*.json")]
    units = {key: quantity["unit"] for key, quantity in saved["properties"].items()}
    assert units["maximum_power"] == "kW"
    assert "°C" in units.values()


def test_ws_import_keeps_an_unknown_unit_iri_whole_and_warns(tmp_path: Path) -> None:
    from battinfo.ws import AuthoringWorkspace

    graph, nodes = _units_deposit(tmp_path)
    power = nodes["MaximumPower"]
    power.pop("schema:unitText", None)
    power["hasMeasurementUnit"] = {"@id": "https://example.org/units/KiloWattish"}
    path = tmp_path / "battinfo.json"
    path.write_text(json.dumps(graph), encoding="utf-8")

    imported = AuthoringWorkspace(root=tmp_path / "imported", registry_url=None)
    # As the publication-package reader does: the IRI is kept whole, never cut at its first colon.
    with pytest.warns(UserWarning, match="'https://example.org/units/KiloWattish' has no symbol"):
        imported.import_(str(path))
    [spec] = imported._ws.cell_specs
    assert spec.properties["maximum_power"]["unit"] == "https://example.org/units/KiloWattish"
    assert spec.properties["nominal_capacity"]["unit"] == "Ah"


# ── BPX export of a cell spec: unit_text is read, no unit is never SI ────────


@pytest.fixture
def a123_record() -> dict:
    return _load(EXAMPLES / "cell-spec" / "A123__ANR26650M1-B.json")


def test_the_bpx_export_reads_unit_text(a123_record: dict) -> None:
    record = copy.deepcopy(a123_record)
    props = record["properties"]
    props["electrode_area"] = {"value": 168.0, "unit_text": "cm2"}
    props["mass"] = {"value": 76.0, "unit_text": "g"}
    for key in ("diameter", "height"):
        quantity = props[key]
        quantity["unit_text"] = quantity.pop("unit")
    result = to_bpx(record)
    cell = result.bpx["Parameterisation"]["Cell"]
    assert cell["Electrode area [m2]"] == pytest.approx(0.0168)
    r, h = 0.013, 0.065  # the example is 26 mm across and 65 mm high
    assert cell["Volume [m3]"] == pytest.approx(math.pi * r * r * h, rel=1e-4)
    assert cell["Density [kg.m-3]"] == pytest.approx(0.076 / cell["Volume [m3]"], rel=1e-4)
    assert result.complete


@pytest.mark.parametrize(
    "quantity",
    [{"value": 2.5}, {"value": 2.5, "unit_code": "AMH"}],
    ids=["no-unit", "unit-code-with-no-conversion"],
)
def test_the_bpx_export_never_takes_a_value_without_a_usable_unit_as_si(quantity: dict) -> None:
    result = to_bpx({"nominal_capacity": quantity, "nominal_voltage": {"value": 3.6, "unit": "V"}})
    assert "Nominal cell capacity [A.h]" not in result.bpx["Parameterisation"]["Cell"]
    assert any("nominal_capacity" in warning for warning in result.warnings)
    assert result.complete is False
    with pytest.raises(ValueError, match="nominal_capacity"):
        to_bpx({"nominal_capacity": quantity}, strict=True)


def test_a_bpx_dimension_without_a_unit_is_not_taken_as_metres() -> None:
    result = to_bpx(
        {
            "cell_spec": {"cell_format": "cylindrical"},
            "properties": {"diameter": {"value": 18}, "height": {"value": 65, "unit": "mm"}},
        }
    )
    assert "Volume [m3]" not in result.bpx["Parameterisation"]["Cell"]
    assert any("diameter" in warning and "no unit" in warning for warning in result.warnings)
    assert result.complete is False


@pytest.mark.parametrize(
    "quantity",
    [
        {"typical_value": 2.5, "unit": "Ah"},
        {"min_value": 2.4, "max_value": 2.6, "unit": "Ah"},
        {"value_text": "about 2.5", "unit": "Ah"},
    ],
    ids=["typical", "range", "text"],
)
def test_a_bpx_field_with_no_single_value_is_reported_not_skipped(quantity: dict) -> None:
    result = to_bpx({"nominal_capacity": quantity})
    assert "Nominal cell capacity [A.h]" not in result.bpx["Parameterisation"]["Cell"]
    assert any("nominal_capacity" in warning and "single value" in warning for warning in result.warnings)
    assert result.complete is False


def test_a_claim_in_unit_text_is_converted() -> None:
    from battinfo.interop.bpx import _claim_to_bpx_value

    claim = {"parameter": "reference_temperature", "quantity": {"value": 25.0, "unit_text": "°C"}}
    assert _claim_to_bpx_value(claim, "K", {"unit": "K"}, "cell", "Reference temperature [K]") == pytest.approx(298.15)
