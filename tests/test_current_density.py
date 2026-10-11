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
