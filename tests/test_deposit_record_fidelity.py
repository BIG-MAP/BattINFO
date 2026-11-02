"""The deposit graph carries what the test, cell and dataset records hold.

The graph ``ws.zenodo()`` writes into a deposit builds these nodes field by
field. It used to drop a test's name, description, status and conditions, a
cell's measured values, and a dataset's columns and derivation, while the
publication check passed. These tests pin the fields on each node kind, the
record fidelity check that now reports such a loss, the condition names that
fell back to plain PropertyValues, and the preview's summary.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.bundle import CellSpec, ProvenanceInfo  # noqa: E402
from battinfo.jsonld import as_run_condition_terms, record_to_jsonld  # noqa: E402
from battinfo.validate import record_fidelity_report, validate_publication_report  # noqa: E402
from battinfo.validate.core import ValidationPolicy, get_validation_policy  # noqa: E402
from battinfo.validate.publication import (  # noqa: E402
    RECORD_FIELD_TERMS,
    RECORD_FIELDS_NOT_EMITTED,
    _test_condition_issues,
)
from battinfo.ws import AuthoringWorkspace  # noqa: E402

SPEC = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-0000"
PROTOCOL = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-0001"
CELL = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-1000"
TEST_RUN = "https://w3id.org/battinfo/test/aaaa-bbbb-cccc-2000"
TEST_OK = "https://w3id.org/battinfo/test/aaaa-bbbb-cccc-2001"
STEP_DATA = "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-3000"
FULL_DATA = "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-3001"
CREATORS = [{"name": "Doe, Jane", "orcid": "0000-0002-1825-0097"}]


def _q(value: float, unit: str, **extra: object) -> dict:
    return {"value": value, "unit": unit, **extra}


def _dataset(iri: str, n: int, **fields: object) -> dict:
    return {
        "schema_version": "0.2.0",
        "dataset": {
            "id": iri,
            "name": f"Demo cell 25 degC run, file {n}",
            "description": f"Time series of file {n}.",
            "about": [CELL, TEST_RUN],
            "access_url": f"file:///data/demo-{n}.bdf.csv",
            "published_at": 1767225600,
            "distributions": [
                {
                    "content_url": f"https://example.org/data/demo-{n}.bdf.csv",
                    "encoding_format": "text/csv",
                    "checksum": {"algorithm": "sha256", "value": f"{n}" * 64},
                }
            ],
            "license": "cc-by-4.0",
            **fields,
        },
        "provenance": {"source_type": "measurement"},
    }


def _record_sets() -> dict[str, list[dict]]:
    return {
        "cell-spec": [
            CellSpec(
                id=SPEC,
                name="Demo prismatic cell",
                manufacturer="Demo Co",
                model="DEMO-1",
                format="prismatic",
                chemistry="lithium_ion",
                source=ProvenanceInfo(type="datasheet"),
            ).to_record()
        ],
        "cell-instance": [
            {
                "schema_version": "0.2.0",
                "cell_instance": {"id": CELL, "cell_spec_id": SPEC, "name": "Demo cell 7", "serial_number": "SN-7"},
                "measured": {
                    "discharging_capacity": _q(
                        103.7,
                        "Ah",
                        value_basis="Measured",
                        conditions={
                            "discharging_c_rate": _q(0.5, "A/Ah"),
                            "ambient_temperature": _q(25, "degC"),
                        },
                    ),
                    # No value_basis: a value of the measured block is still measured.
                    "specific_energy": _q(167.3, "Wh/kg"),
                },
                "notes": ["Baseline from the first full discharge."],
                "provenance": {"source_type": "measurement"},
            }
        ],
        "test": [
            {
                "schema_version": "0.2.0",
                "test": {
                    "id": TEST_RUN,
                    "name": "Demo cell 7 cycling 25 degC test",
                    "description": "Cycling at 25 degC without compression.",
                    "kind": "cycling",
                    "status": "completed",
                    "cell_id": CELL,
                    "protocol_id": PROTOCOL,
                    "protocol_name": "Demo cycling protocol",
                    "dataset_ids": [STEP_DATA],
                    "conditions": {
                        "ambient_temperature": _q(25, "degC"),
                        "applied_pressure": _q(0, "kPa"),
                        "state_of_charge": _q(50, "%"),
                    },
                    "conformance": {
                        "status": "non-conformant",
                        "deviations": [{"category": "other", "description": "Run without compression."}],
                    },
                },
                "provenance": {"source_type": "measurement"},
            },
            {
                "schema_version": "0.2.0",
                "test": {
                    "id": TEST_OK,
                    "kind": "cycling",
                    "cell_id": CELL,
                    "protocol_id": PROTOCOL,
                    "protocol_name": "Demo cycling protocol",
                    "conformance": {"status": "conformant"},
                },
                "provenance": {"source_type": "measurement"},
            },
        ],
        "test-protocol": [
            {
                "test_spec": {"id": PROTOCOL, "name": "Demo cycling protocol", "kind": "cycling"},
                "conditions": {
                    "applied_pressure": _q(90, "kPa"),
                    "state_of_charge": _q(100, "%"),
                    "initial_state_of_charge": _q(1, "1"),
                },
            }
        ],
        "dataset": [
            _dataset(
                STEP_DATA,
                1,
                variable_measured=[
                    {"name": "test_time", "unit_text": "s"},
                    {"name": "voltage", "unit_text": "V"},
                ],
                is_based_on=[FULL_DATA],
            ),
            _dataset(FULL_DATA, 2),
        ],
    }


def _graph(record_sets: dict[str, list[dict]]) -> dict:
    return AuthoringWorkspace._assemble_zenodo_jsonld(
        record_sets,
        zenodo_record_id=1,
        prereserved_doi="10.5281/zenodo.1",
        record_url="https://zenodo.org/records/1",
        data_filenames=[],
        title="fidelity deposit",
        creators=CREATORS,
        license="cc-by-4.0",
    )


@pytest.fixture(scope="module")
def graph() -> dict:
    return _graph(_record_sets())


def _nodes(doc: dict) -> dict[str, dict]:
    return {n["@id"]: n for n in doc["@graph"] if isinstance(n, dict) and "@id" in n}


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else [value]


def _parameters(node: dict) -> dict[str, dict]:
    return {p["skos:prefLabel"]: p for p in _as_list(node["hasMeasurementParameter"])}


# ── Fix 1: each node kind carries its record ──────────────────────────────────


def test_test_node_carries_name_description_status_and_conditions(graph: dict) -> None:
    node = _nodes(graph)[TEST_RUN]
    assert node["schema:name"] == node["rdfs:label"] == "Demo cell 7 cycling 25 degC test"
    assert node["schema:description"] == "Cycling at 25 degC without compression."
    assert node["schema:actionStatus"] == "completed"
    params = _parameters(node)
    assert params["ambient_temperature"]["@type"][0] == "AmbientCelsiusTemperature"
    assert params["ambient_temperature"]["hasNumericalPart"]["hasNumberValue"] == 25
    assert params["applied_pressure"]["@type"][0] == "Pressure"
    assert params["applied_pressure"]["hasMeasurementUnit"] == "https://w3id.org/emmo#KiloPascal"
    assert params["state_of_charge"]["@type"][0] == "StateOfCharge"
    names = {p["schema:name"] for p in node["schema:additionalProperty"]}
    assert names == {"ambient_temperature", "applied_pressure", "state_of_charge"}


def test_test_node_matches_the_record_emitter_for_conditions(graph: dict) -> None:
    record = _record_sets()["test"][0]
    standalone = record_to_jsonld(record, "test")
    node = _nodes(graph)[TEST_RUN]
    for term in ("hasMeasurementParameter", "schema:additionalProperty"):
        assert node[term] == standalone[term]


def test_test_without_a_name_keeps_the_protocol_and_cell_label(graph: dict) -> None:
    assert _nodes(graph)[TEST_OK]["schema:name"] == "Demo cycling protocol — Demo cell 7"


def test_a_generated_test_title_keeps_the_protocol_and_cell_label() -> None:
    # BattINFO titles an unnamed test after its cell and protocol; such a title
    # is not a name the record was given, so the label stays as it was.
    records = _record_sets()
    records["test"][1]["test"]["name"] = "Demo cell 7 Demo cycling protocol"
    doc = _graph(records)
    assert _nodes(doc)[TEST_OK]["schema:name"] == "Demo cycling protocol — Demo cell 7"
    assert _fidelity(doc, records) == []


def test_a_given_name_is_kept_as_the_record_writes_it() -> None:
    records = _record_sets()
    records["test"][0]["test"]["name"] = "Demo cell 7  cycling 25 degC run"
    doc = _graph(records)
    assert _nodes(doc)[TEST_RUN]["schema:name"] == "Demo cell 7  cycling 25 degC run"
    assert _fidelity(doc, records) == []


def test_conformance_is_unchanged(graph: dict) -> None:
    nodes = _nodes(graph)
    run, ok = nodes[TEST_RUN], nodes[TEST_OK]
    # A non-conformant test never claims dcterms:conformsTo; it carries the verdict.
    assert "dcterms:conformsTo" not in run
    assert run["dqv:hasQualityAnnotation"]["dqv:value"] == "non-conformant"
    assert run["prov:wasInfluencedBy"]
    assert ok["dcterms:conformsTo"] == {"@id": PROTOCOL}
    # The outputs keep the deposit's terms (both datasets name this test in about).
    assert run["hasOutput"] == run["prov:generated"]
    assert {"@id": STEP_DATA} in run["hasOutput"]
    assert "schema:result" not in run


def test_cell_node_carries_measured_values_with_their_conditions(graph: dict) -> None:
    node = _nodes(graph)[CELL]
    props = {p["@type"][0]: p for p in node["hasProperty"]}
    capacity = props["DischargingCapacity"]
    assert capacity["@type"] == ["DischargingCapacity", "MeasuredProperty"]
    assert capacity["hasNumericalPart"]["hasNumberValue"] == 103.7
    assert capacity["hasMeasurementUnit"] == "https://w3id.org/emmo#AmpereHour"
    measurement = capacity["isOutputOf"]
    assert measurement["@type"] == "BatteryMeasurement"
    assert set(_parameters(measurement)) == {"ambient_temperature", "discharging_c_rate"}
    # A value without value_basis is measured too, not the key's declared basis.
    assert "MeasuredProperty" in props["SpecificEnergy"]["@type"]
    assert node["schema:comment"] == "Baseline from the first full discharge."


def test_cell_record_emitter_carries_the_measured_block(graph: dict) -> None:
    standalone = record_to_jsonld(_record_sets()["cell-instance"][0], "cell-instance")
    assert standalone["hasProperty"] == _nodes(graph)[CELL]["hasProperty"]


def test_dataset_node_carries_columns_and_derivation(graph: dict) -> None:
    nodes = _nodes(graph)
    step = nodes[STEP_DATA]
    assert [v["schema:name"] for v in step["schema:variableMeasured"]] == ["test_time", "voltage"]
    assert step["schema:variableMeasured"][1]["schema:unitText"] == "V"
    assert step["schema:isBasedOn"] == [{"@id": FULL_DATA}]
    assert "schema:isBasedOn" not in nodes[FULL_DATA]
    # A member is not published on its own: the record's published_at stays off it.
    for iri in (STEP_DATA, FULL_DATA):
        assert "schema:datePublished" not in nodes[iri]
        assert "dcterms:issued" not in nodes[iri]


def test_dataset_record_emitter_carries_the_derivation() -> None:
    standalone = record_to_jsonld(_record_sets()["dataset"][0], "dataset")
    assert standalone["schema:isBasedOn"] == [{"@id": FULL_DATA}]


def test_the_graph_passes_the_publication_check(graph: dict) -> None:
    report = validate_publication_report(copy.deepcopy(graph), policy="publisher")
    assert report.ok, [(i.code, i.message) for i in report.errors]
    # The condition classes resolve in the deposit's own context.
    for term in ("AmbientCelsiusTemperature", "Pressure", "StateOfCharge", "MeasuredProperty", "Pascal"):
        assert term in graph["@context"], term


# ── Fix 3: condition names the schemas recommend are mapped ───────────────────


def test_protocol_conditions_emit_typed_quantities(graph: dict) -> None:
    howto = _nodes(graph)[PROTOCOL]
    by_label = {}
    for prop in _as_list(howto["hasProperty"]):
        by_label.setdefault(prop["@type"], []).append(prop)
    assert len(by_label["StateOfCharge"]) == 2
    (pressure,) = by_label["Pressure"]
    assert pressure["hasNumericalPart"]["hasNumberValue"] == 90
    assert "@id" in pressure["hasMeasurementUnit"]
    assert "schema:additionalProperty" not in howto
    report = _test_condition_issues(graph, get_validation_policy("publisher"))
    assert not [i for i in report.issues if i.code == "publication.test_condition_unmapped"]


@pytest.mark.parametrize(
    ("name", "unit", "cls"),
    [
        ("ambient_temperature", "degC", "AmbientCelsiusTemperature"),
        ("state_of_charge", "%", "StateOfCharge"),
        ("state_of_charge", "1", "StateOfCharge"),
        ("initial_state_of_charge", "1", "StateOfCharge"),
        ("applied_pressure", "kPa", "Pressure"),
        ("applied_pressure", "Pa", "Pressure"),
    ],
)
def test_as_run_conditions_emit_typed_quantities(name: str, unit: str, cls: str) -> None:
    terms = as_run_condition_terms({name: _q(1, unit)})
    param = terms["hasMeasurementParameter"]
    assert param["@type"][0] == cls
    assert "schema:unitText" not in param, f"{unit} did not resolve to a unit IRI"


@pytest.mark.parametrize(("unit", "unit_iri"), [("kPa", "KiloPascal"), ("Pa", "Pascal")])
def test_protocol_pressure_units_resolve(unit: str, unit_iri: str) -> None:
    from battinfo.jsonld import condition_quantity_node

    node = condition_quantity_node("applied_pressure", 90, unit)
    assert node is not None
    assert node["@type"] == "Pressure"
    assert node["hasMeasurementUnit"]["@id"].endswith(unit_iri)


# ── Fix 2: the fidelity check ─────────────────────────────────────────────────


def _fidelity(doc: dict, record_sets: dict) -> list[tuple[str, str]]:
    report = record_fidelity_report(doc, record_sets, policy="publisher")
    assert all(i.severity == "warning" for i in report.issues)
    return sorted((i.path.split(":", 1)[0], i.path.rsplit(".", 1)[1]) for i in report.issues)


def test_fidelity_check_finds_nothing_in_a_complete_graph(graph: dict) -> None:
    assert _fidelity(graph, _record_sets()) == []


def test_fidelity_check_reports_dropped_fields(graph: dict) -> None:
    lossy = copy.deepcopy(graph)
    nodes = _nodes(lossy)
    for term in ("hasMeasurementParameter", "schema:additionalProperty", "schema:actionStatus", "schema:description"):
        del nodes[TEST_RUN][term]
    nodes[TEST_RUN]["schema:name"] = "Demo cycling protocol — Demo cell 7"
    del nodes[CELL]["hasProperty"]
    del nodes[STEP_DATA]["schema:variableMeasured"]
    del nodes[STEP_DATA]["schema:isBasedOn"]
    assert _fidelity(lossy, _record_sets()) == [
        ("cell-instance", "measured"),
        ("dataset", "is_based_on"),
        ("dataset", "variable_measured"),
        ("test", "conditions"),
        ("test", "description"),
        ("test", "name"),
        ("test", "status"),
    ]
    report = record_fidelity_report(lossy, _record_sets())
    by_field = {i.path.rsplit(".", 1)[1]: i.message for i in report.issues}
    assert by_field["name"].endswith("carries another value for it.")
    assert by_field["status"].endswith("carries nothing for it.")
    assert TEST_RUN in by_field["status"]


def test_fidelity_check_reports_a_reference_missing_from_a_shared_term(graph: dict) -> None:
    # prov:used holds the cell as well, so the protocol must be one of its entries.
    lossy = copy.deepcopy(graph)
    run = _nodes(lossy)[TEST_RUN]
    run["prov:used"] = [ref for ref in run["prov:used"] if ref["@id"] != PROTOCOL]
    assert _fidelity(lossy, _record_sets()) == [("test", "protocol_id")]


def test_fidelity_check_reports_fields_the_graph_has_no_term_for(graph: dict) -> None:
    records = _record_sets()
    records["test"][0]["test"]["protocol_url"] = "https://example.org/protocol.pdf"
    records["dataset"][1]["dataset"]["funders"] = [{"name": "Demo Fund"}]
    assert _fidelity(graph, records) == [("dataset", "funders"), ("test", "protocol_url")]


def test_fidelity_check_ignores_local_file_addresses_and_off_policy(graph: dict) -> None:
    # Both datasets have a file: access_url, which the deposit never publishes.
    assert ("dataset", "access_url") not in _fidelity(graph, _record_sets())
    lossy = copy.deepcopy(graph)
    del _nodes(lossy)[CELL]["hasProperty"]
    off = ValidationPolicy(name="quiet", publication="off")
    assert record_fidelity_report(lossy, _record_sets(), policy=off).issues == ()


def _schema_fields(kind: str, body_key: str) -> set[str]:
    schema = json.loads((ROOT / "assets" / "schemas" / f"{kind}.schema.json").read_text(encoding="utf-8"))
    top = set(schema["properties"]) - {body_key}
    body = {f"{body_key}.{key}" for key in schema["properties"][body_key]["properties"]}
    return top | body


@pytest.mark.parametrize(
    ("kind", "body_key"), [("test", "test"), ("cell-instance", "cell_instance"), ("dataset", "dataset")]
)
def test_every_schema_field_has_a_fidelity_rule(kind: str, body_key: str) -> None:
    """A field added to the schema needs a graph term, or a reason it has none."""
    fields = _schema_fields(kind, body_key)
    terms, excluded = set(RECORD_FIELD_TERMS[kind]), set(RECORD_FIELDS_NOT_EMITTED[kind])
    assert not terms & excluded
    assert fields - terms - excluded == set(), "add each to RECORD_FIELD_TERMS or RECORD_FIELDS_NOT_EMITTED"
    assert (terms | excluded) - fields == set(), "these are not fields of the schema"


# ── Fix 8: the preview summary ────────────────────────────────────────────────


def _workspace(root: Path) -> AuthoringWorkspace:
    ws = AuthoringWorkspace(root=root, registry_url=None)
    (root / "d.cell-spec.json").write_text(
        '{"manufacturer":"X","model":"Y","format":"pouch","chemistry":"nmc"}', encoding="utf-8"
    )
    ws.add("cell", spec=ws.load(root / "d.cell-spec.json"), names=["c1"])
    (root / "c1.bdf.csv").write_text("a,b\n0,1\n", encoding="utf-8")
    ws.add("test", type="capacity_check", cell="c1", data="c1.bdf.csv")
    ws.save()
    return ws


_METADATA = {
    "title": "t",
    "description": "d",
    "creators": [{"name": "A", "affiliation": "Org"}],
    "license": "CC-BY-4.0",
}


def test_preview_counts_record_fields_the_graph_does_not_carry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ws = _workspace(tmp_path)
    ws.preview_jsonld(**_METADATA)
    out = capsys.readouterr().out
    assert "Gold-standard: PASS" in out
    assert "(0 record field(s) not carried)" in out

    (test_file,) = (tmp_path / ".battinfo" / "records" / "test").glob("*.json")
    record = json.loads(test_file.read_text(encoding="utf-8"))
    record["test"]["protocol_url"] = "https://example.org/protocol.pdf"
    test_file.write_text(json.dumps(record), encoding="utf-8")

    ws.preview_jsonld(**_METADATA)
    out = capsys.readouterr().out
    assert "ws.zenodo() refuses a deposit with errors; warnings do not stop it." in out
    assert "1 test record(s) have 'protocol_url', but their nodes in the deposit carry nothing for it" in out
    assert "(1 record field(s) not carried)" in out
