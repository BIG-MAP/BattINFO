"""Current densities in test-spec methods (Empa evaluation, findings E-04 to E-06).

Coin-cell protocols state their currents per electrode area: constant-current
steps at 0.1 mA/cm2 and constant-voltage holds that end when the current falls
to 0.05 mA/cm2. Both JSON-LD emitters dropped the current-density setpoint and
emitted the cutoff as a unitless TerminationQuantity, so no consumer of the
semantic layer could tell what current a protocol used.
"""
from __future__ import annotations

import json

import pytest
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF

import battinfo
from battinfo.jsonld import record_to_jsonld, resolve_unit_iri
from battinfo.ws import AuthoringWorkspace

EMMO = Namespace("https://w3id.org/emmo#")
ECHEM = Namespace("https://w3id.org/emmo/domain/electrochemistry#")
ELECTRIC_CURRENT_DENSITY = EMMO["EMMO_7c8007b0_58a7_4486_bf1c_4772852caca0"]
LOWER_CURRENT_DENSITY_LIMIT = ECHEM["electrochemistry_abdd3bbb_403a_4cb3_b522_50d027492a68"]
UPPER_CURRENT_DENSITY_LIMIT = ECHEM["electrochemistry_2a16f139_ab9c_4034_bd21_eabd2e1202e8"]
HAS_MEASUREMENT_UNIT = EMMO["EMMO_bed1d005_b04e_4a90_94cf_02bc678a8569"]

SPEC_ID = "https://w3id.org/battinfo/spec/0000-0000-0000-0001"


def _empa_spec() -> battinfo.TestSpec:
    """The reproduction from the evaluation (scripts/repro/e04_e05_testspec.py)."""
    return battinfo.TestSpec(
        id=SPEC_ID, name="CCCV at 0.1 mA/cm2", kind="cycling",
        source_type="import", retrieved_at=1750032000,
        method=[
            {"mode": "cc", "direction": "charge",
             "setpoints": {"current_density": {"value": 0.1, "unit": "mA/cm2"}},
             "termination": [{"quantity": "voltage", "value": 4.2, "unit": "V", "direction": "above"}]},
            {"mode": "cv", "direction": "hold", "setpoints": {"voltage": {"value": 4.2, "unit": "V"}},
             "termination": [{"quantity": "current", "value": 0.05, "unit": "mA/cm2", "direction": "below"}]},
            {"mode": "rest", "direction": "rest", "duration": {"value": 6, "unit": "h"}},
            {"mode": "group", "count": 3,
             "steps": [{"mode": "rest", "direction": "rest", "duration": {"value": 60, "unit": "s"}}]},
        ],
    )


def _step(setpoints: dict | None = None, termination: list | None = None, **extra) -> dict:
    """A one-step protocol record."""
    step = {"mode": "cc", "direction": "discharge", **extra}
    if setpoints is not None:
        step["setpoints"] = setpoints
    if termination is not None:
        step["termination"] = termination
    return {"test_spec": {"id": SPEC_ID, "name": "probe", "kind": "cycling"}, "method": [step]}


def _deposit_node(record: dict) -> tuple[dict, dict]:
    """The protocol node of the deposit graph (``ws.preview_jsonld()``) and the graph."""
    doc = AuthoringWorkspace._assemble_zenodo_jsonld(
        {"cell-spec": [], "cell-instance": [], "test": [], "test-protocol": [record], "dataset": []},
        zenodo_record_id=0, prereserved_doi="", record_url="https://example.org/records/0",
        data_filenames=[], title="t", description="d",
    )
    node = next(n for n in doc["@graph"] if n.get("@id") == record["test_spec"]["id"])
    return node, doc


# -- E-04: both emitters keep current densities ------------------------------


def test_current_density_setpoint_is_a_typed_control_parameter() -> None:
    doc = record_to_jsonld(_empa_spec().to_record(), "test-protocol")
    assert doc["hasTask"][0]["hasControlParameter"] == [{
        "@type": "ElectricCurrentDensity",
        "hasNumericalPart": {"hasNumberValue": 0.1},
        "hasMeasurementUnit": {"@id": "emmo:MilliAmperePerSquareCentiMetre"},
    }]


def test_current_cutoff_per_area_is_a_current_density_limit_with_its_unit() -> None:
    doc = record_to_jsonld(_empa_spec().to_record(), "test-protocol")
    assert doc["hasTask"][1]["hasTerminationParameter"] == [{
        "@type": "LowerCurrentDensityLimit",
        "hasNumericalPart": {"hasNumberValue": 0.05},
        "hasMeasurementUnit": {"@id": "emmo:MilliAmperePerSquareCentiMetre"},
    }]


def test_rising_current_density_cutoff_is_an_upper_limit() -> None:
    record = _step(termination=[{"quantity": "current", "value": 2, "unit": "A/m2", "direction": "above"}])
    term = record_to_jsonld(record, "test-protocol")["hasTask"][0]["hasTerminationParameter"][0]
    assert term["@type"] == "UpperCurrentDensityLimit"
    assert term["hasMeasurementUnit"] == {"@id": "emmo:AmperePerSquareMetre"}


def test_current_setpoint_stated_per_area_is_typed_as_a_current_density() -> None:
    record = _step(setpoints={"current": {"value": 0.1, "unit": "mA cm-2"}})
    control = record_to_jsonld(record, "test-protocol")["hasTask"][0]["hasControlParameter"][0]
    assert control["@type"] == "ElectricCurrentDensity"
    assert control["hasMeasurementUnit"] == {"@id": "emmo:MilliAmperePerSquareCentiMetre"}


def test_plain_current_setpoint_and_cutoff_are_unchanged() -> None:
    record = _step(
        setpoints={"current": {"value": 0.2, "unit": "A"}},
        termination=[{"quantity": "current", "value": 50, "unit": "mA", "direction": "below"}],
    )
    task = record_to_jsonld(record, "test-protocol")["hasTask"][0]
    assert task["hasControlParameter"][0]["@type"] == "ElectricCurrent"
    assert task["hasControlParameter"][0]["hasMeasurementUnit"] == {"@id": "emmo:Ampere"}
    assert task["hasTerminationParameter"][0]["@type"] == "TerminationQuantity"
    assert task["hasTerminationParameter"][0]["hasMeasurementUnit"] == {"@id": "emmo:MilliAmpere"}


def test_a_cutoff_whose_unit_has_no_iri_keeps_the_unit_as_text() -> None:
    record = _step(termination=[
        {"quantity": "current", "value": 5, "unit": "µA/cm2", "direction": "below"},
        {"quantity": "capacity", "value": 300, "unit": "mAh/g", "direction": "above"},
    ])
    terms = record_to_jsonld(record, "test-protocol")["hasTask"][0]["hasTerminationParameter"]
    assert terms[0]["@type"] == "LowerCurrentDensityLimit"
    assert terms[0]["schema:unitText"] == "µA/cm2"
    assert terms[1]["schema:unitText"] == "mAh/g"
    for term in terms:
        assert "hasMeasurementUnit" not in term


def test_step_duration_keeps_its_unit() -> None:
    doc = record_to_jsonld(_empa_spec().to_record(), "test-protocol")
    assert doc["hasTask"][2]["hasTerminationParameter"] == [{
        "@type": "Duration",
        "hasNumericalPart": {"hasNumberValue": 6.0},
        "hasMeasurementUnit": {"@id": "emmo:Hour"},
    }]


def test_deposit_graph_carries_the_same_current_densities() -> None:
    record = _empa_spec().to_record()
    node, deposit = _deposit_node(record)
    standalone = record_to_jsonld(record, "test-protocol")
    assert node["hasTask"] == standalone["hasTask"]
    assert node["hasTask"][0]["hasControlParameter"][0]["@type"] == "ElectricCurrentDensity"
    assert node["hasTask"][1]["hasTerminationParameter"][0]["@type"] == "LowerCurrentDensityLimit"
    for term in ("ElectricCurrentDensity", "LowerCurrentDensityLimit", "UpperCurrentDensityLimit"):
        assert term in deposit["@context"], term


@pytest.mark.parametrize("context", ["inline", "url"])
def test_current_densities_expand_to_the_pinned_ontology_iris(context: str) -> None:
    """The typed nodes must survive JSON-LD expansion, in both context modes."""
    record = _step(
        setpoints={"current_density": {"value": 0.1, "unit": "mA/cm2"}},
        termination=[
            {"quantity": "current", "value": 0.05, "unit": "mA/cm2", "direction": "below"},
            {"quantity": "current", "value": 1.0, "unit": "mA/cm2", "direction": "above"},
        ],
    )
    from battinfo.validate.jsonld import _inline_local_contexts

    doc = record_to_jsonld(record, "test-protocol", context=context)
    # URL mode resolves against the bundled copy of the hosted context, offline.
    graph = Graph().parse(data=json.dumps(_inline_local_contexts(doc)), format="json-ld")
    unit = URIRef("https://w3id.org/emmo#MilliAmperePerSquareCentiMetre")
    for cls in (ELECTRIC_CURRENT_DENSITY, LOWER_CURRENT_DENSITY_LIMIT, UPPER_CURRENT_DENSITY_LIMIT):
        nodes = list(graph.subjects(RDF.type, cls))
        assert len(nodes) == 1, cls
        assert graph.value(nodes[0], HAS_MEASUREMENT_UNIT) == unit


@pytest.mark.parametrize(
    ("spelling", "iri"),
    [
        ("mA/cm2", "emmo:MilliAmperePerSquareCentiMetre"),
        ("mA/cm^2", "emmo:MilliAmperePerSquareCentiMetre"),
        ("mA/cm²", "emmo:MilliAmperePerSquareCentiMetre"),
        ("mA cm-2", "emmo:MilliAmperePerSquareCentiMetre"),
        ("A/cm2", "emmo:AmperePerSquareCentiMetre"),
        ("A/m2", "emmo:AmperePerSquareMetre"),
        ("A.m-2", "emmo:AmperePerSquareMetre"),
    ],
)
def test_current_density_unit_spellings_resolve(spelling: str, iri: str) -> None:
    assert resolve_unit_iri(spelling) == iri


def test_curated_current_density_units_are_published_unit_iris() -> None:
    """Every curated current-density unit is a unit the pinned ontologies publish
    (checked against the bundled domain-battery context, which carries the EMMO
    unit classes)."""
    from importlib import resources

    def _load(*parts: str) -> dict:
        path = resources.files("battinfo").joinpath("data")
        for part in parts:
            path = path.joinpath(part)
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    context = _load("context", "domain-battery.context.json")["@context"]
    published = {v if isinstance(v, str) else v.get("@id") for v in context.values()}
    units = {m["symbol"]: m for m in _load("mappings", "domain-battery", "unit_map.curated.json")["mappings"]}
    for symbol, name in (
        ("mA/cm2", "MilliAmperePerSquareCentiMetre"),
        ("A/cm2", "AmperePerSquareCentiMetre"),
        ("A/m2", "AmperePerSquareMetre"),
    ):
        entry = units[symbol]
        assert entry["unit_iri"] == f"https://w3id.org/emmo#{name}"
        assert entry["unit_iri"] in published
        assert context[name] == entry["unit_iri"]


def test_hosted_context_defines_the_current_density_terms() -> None:
    from importlib import resources

    with resources.files("battinfo").joinpath("data", "context", "records.context.v1.json").open(
        "r", encoding="utf-8"
    ) as handle:
        hosted = json.load(handle)["@context"]
    assert hosted["ElectricCurrentDensity"].endswith("#EMMO_7c8007b0_58a7_4486_bf1c_4772852caca0")
    assert hosted["LowerCurrentDensityLimit"].endswith("#electrochemistry_abdd3bbb_403a_4cb3_b522_50d027492a68")
    assert hosted["UpperCurrentDensityLimit"].endswith("#electrochemistry_2a16f139_ab9c_4034_bd21_eabd2e1202e8")
    assert hosted["MilliAmperePerSquareCentiMetre"] == "emmo:MilliAmperePerSquareCentiMetre"


def test_gold_standard_check_accepts_the_current_density_classes() -> None:
    from battinfo.validate.jsonld import _allowed_type_terms

    allowed = _allowed_type_terms()
    for term in ("ElectricCurrentDensity", "LowerCurrentDensityLimit", "UpperCurrentDensityLimit"):
        assert term in allowed, term


# -- E-06: current density in the step grammar, and a unit check on current cutoffs


def test_a_current_density_step_string_parses() -> None:
    from battinfo.testmethod import parse_step

    step = parse_step("Charge at 0.1 mA/cm2 until 2.5 V")
    assert (step.mode, step.direction) == ("cc", "charge")
    assert step.setpoints["current_density"].model_dump(exclude_none=True) == {"value": 0.1, "unit": "mA/cm2"}
    term = step.termination[0]
    assert (term.quantity, term.value, term.unit, term.direction) == ("voltage", 2.5, "V", "above")


def test_a_current_density_cutoff_parses_to_the_stored_form() -> None:
    """The form production's own Empa specs use: a current cutoff in mA/cm2."""
    from battinfo.testmethod import parse_step

    step = parse_step("Hold at 4.2 V until 0.05 mA/cm2")
    term = step.termination[0]
    assert (term.quantity, term.value, term.unit, term.direction) == ("current", 0.05, "mA/cm2", "below")


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("0.1 mA/cm2", 0.1),
        ("0.1 mA/cm^2", 0.1),
        ("0.1 mA/cm²", 0.1),
        ("0.1 mA cm-2", 0.1),
        ("1 A/m2", 0.1),
        ("3 A/m2", 0.3),
        ("2 µA/cm2", 0.002),
        ("2 uA/cm2", 0.002),
        ("0.5 A/cm2", 500.0),
    ],
)
def test_current_density_spellings_normalise_to_ma_per_cm2(text: str, value: float) -> None:
    from battinfo.testmethod import parse_step

    qty = parse_step(f"Discharge at {text} until 3 V").setpoints["current_density"]
    assert qty.unit == "mA/cm2"
    assert qty.value == value  # exact: no float noise from the unit factor


def test_a_current_density_protocol_round_trips_through_its_strings() -> None:
    spec = _empa_spec()
    again = battinfo.TestSpec(name="again", kind="cycling", experiment=spec.experiment)
    first, hold = again.method[0], again.method[1]
    assert first.setpoints["current_density"].model_dump(exclude_none=True) == {"value": 0.1, "unit": "mA/cm2"}
    assert hold.termination[0].model_dump() == {
        "quantity": "current", "value": 0.05, "unit": "mA/cm2", "direction": "below",
    }
    assert again.method[2].duration is not None and again.method[2].duration.value == 6 * 3600
    assert again.experiment == spec.experiment


def test_a_protocol_authored_as_strings_emits_current_densities() -> None:
    spec = battinfo.TestSpec(
        id=SPEC_ID, name="strings", kind="cycling",
        experiment=["Charge at 0.1 mA/cm2 until 4.2 V", "Hold at 4.2 V until 0.05 mA/cm2"],
    )
    tasks = record_to_jsonld(spec.to_record(), "test-protocol")["hasTask"]
    assert tasks[0]["hasControlParameter"][0]["@type"] == "ElectricCurrentDensity"
    assert tasks[1]["hasTerminationParameter"][0]["@type"] == "LowerCurrentDensityLimit"


def test_parsed_current_density_steps_pass_the_save_time_schema() -> None:
    from importlib import resources

    from jsonschema import Draft202012Validator

    from battinfo.testmethod import parse_step

    with resources.files("battinfo").joinpath("data", "schemas", "test-protocol.schema.json").open(
        "r", encoding="utf-8"
    ) as handle:
        schema = json.load(handle)
    validator = Draft202012Validator({**schema["$defs"]["Step"], "$defs": schema["$defs"]})
    for text in ("Charge at 0.1 mA/cm2 until 4.2 V", "Hold at 4.2 V until 0.05 mA/cm2"):
        validator.validate(parse_step(text).model_dump(exclude_none=True))


def test_comparison_shorthand_takes_a_current_density() -> None:
    from battinfo.testmethod import ExperimentSyntaxError, parse_termination

    for text in ("Current < 0.05 mA/cm2", "Current density < 0.05", "current_density < 0.5 A/m2"):
        term = parse_termination(text)
        assert (term.quantity, term.value, term.unit, term.direction) == ("current", 0.05, "mA/cm2", "below"), text
    with pytest.raises(ExperimentSyntaxError, match="names current density but its value parses as current"):
        parse_termination("Current density < 0.05 A")


@pytest.mark.parametrize("unit", ["A", "mA", "µA", "mA/cm2", "A/m2", "mA cm-2", "mA/g"])
def test_a_current_cutoff_accepts_current_and_areal_units(unit: str) -> None:
    from battinfo.testmethod import Termination

    assert Termination(quantity="current", value=1, unit=unit, direction="below").unit == unit


@pytest.mark.parametrize(
    ("unit", "message"),
    [
        ("V", "voltage unit. Use quantity 'voltage'"),
        ("mAh", "charge unit. Use quantity 'capacity'"),
        ("C", "C-rate unit. Use quantity 'c_rate'"),
        ("A/Ah", "C-rate unit. Use quantity 'c_rate'"),
        ("min", "time unit. Use quantity 'duration'"),
        ("%", "dimensionless unit. Use quantity 'soc'"),
        ("W", "power unit."),
    ],
)
def test_a_current_cutoff_in_another_quantitys_unit_is_rejected(unit: str, message: str) -> None:
    from pydantic import ValidationError

    from battinfo.testmethod import Step

    with pytest.raises(ValidationError, match=message):
        Step(mode="cv", direction="hold",
             termination=[{"quantity": "current", "value": 1, "unit": unit, "direction": "below"}])


def test_published_empa_specs_still_load() -> None:
    """The check must not break reading records production already holds."""
    record = _empa_spec().to_record()
    again = battinfo.TestSpec.from_record(record)
    assert again.method[1].termination[0].unit == "mA/cm2"


# -- SI prefixes are case-sensitive: M is mega, m is milli --------------------


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1 MA/m2", 100000.0),
        ("1 mA/m2", 0.0001),
        ("1 kA/m2", 100.0),
        ("1 uA/cm2", 0.001),
        ("1 µA/cm2", 0.001),
        ("1 μA/cm2", 0.001),  # Greek mu
        ("1 ma/cm2", 1.0),  # all lower case: the prefix is still milli
    ],
)
def test_current_density_prefixes_are_read_case_sensitively(text: str, value: float) -> None:
    from battinfo.testmethod import parse_step

    qty = parse_step(f"Charge at {text} until 4.2 V").setpoints["current_density"]
    assert (qty.value, qty.unit) == (value, "mA/cm2")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("1 mA/Mm2", "Unsupported area unit 'Mm2'"),
        ("1 KA/m2", "Unsupported prefix 'K'"),
        ("1 pA/cm2", "Unsupported prefix 'p'"),
        ("1 Ma/cm2", "Ambiguous unit 'Ma/cm2'"),
        ("1 mA/CM2", "Could not parse value"),
    ],
)
def test_a_prefix_the_grammar_does_not_read_raises(text: str, message: str) -> None:
    from battinfo.testmethod import ExperimentSyntaxError, parse_step

    with pytest.raises(ExperimentSyntaxError, match=message):
        parse_step(f"Charge at {text} until 4.2 V")


def test_plain_unit_prefixes_are_case_sensitive_too() -> None:
    """The plain units had the same fold: 1 MA was read as 1 mA, 1 MW as 1 mW."""
    from battinfo.testmethod import ExperimentSyntaxError, parse_step

    assert parse_step("Discharge at 1 MA until 3 V").setpoints["current"].value == 1e6
    assert parse_step("Discharge at 5 µA until 3 V").setpoints["current"].value == 5e-6
    assert parse_step("Discharge at 200 ma until 3 V").setpoints["current"].value == 0.2
    assert parse_step("Discharge at 9 mA until 3 V").setpoints["current"].value == 0.009
    for text in ("Discharge at 1 MW until 3 V", "Hold at 1 MV until 0.1 A", "Discharge at 1 Ma until 3 V",
                 "Discharge at 1 KA until 3 V"):
        with pytest.raises(ExperimentSyntaxError):
            parse_step(text)


@pytest.mark.parametrize("unit", ["pA/cm2", "Ma/cm2", "mA/Mm2"])
def test_the_emitters_leave_an_unreadable_stored_unit_as_written(unit: str) -> None:
    """A stored record with a unit the grammar refuses still emits; the value
    keeps its unit as text and is not typed as a current density."""
    record = _step(setpoints={"current": {"value": 1, "unit": unit}},
                   termination=[{"quantity": "current", "value": 1, "unit": unit, "direction": "below"}])
    task = record_to_jsonld(record, "test-protocol")["hasTask"][0]
    assert task["hasControlParameter"][0]["@type"] == "ElectricCurrent"
    assert task["hasControlParameter"][0]["schema:unitText"] == unit
    assert task["hasTerminationParameter"][0]["@type"] == "TerminationQuantity"
    assert task["hasTerminationParameter"][0]["schema:unitText"] == unit
