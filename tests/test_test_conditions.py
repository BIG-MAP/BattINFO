"""C4: structured test conditions → EMMO control/termination/property quantities.

The publication builder turns a protocol's authored conditions into the EMMO
domain-battery model (hasControlParameter / hasTerminationParameter / hasProperty,
each a typed quantity), with a schema:PropertyValue fallback + a non-blocking
warning for names outside the controlled vocabulary.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.validate.core import get_validation_policy
from battinfo.validate.publication import _test_condition_issues
from battinfo.ws import AuthoringWorkspace

SPEC_ID = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"


def _assemble(test_protocol_record: dict) -> dict:
    return AuthoringWorkspace._assemble_zenodo_jsonld(
        {
            "cell-spec": [], "cell-instance": [], "test": [],
            "test-protocol": [test_protocol_record], "dataset": [],
        },
        zenodo_record_id=0,
        prereserved_doi="",
        record_url="https://example.org/records/0",
        data_filenames=[],
        title="t",
        description="d",
    )


def _howto(doc: dict) -> dict:
    return next(n for n in doc["@graph"] if "schema:HowTo" in (n.get("@type") or []))


def test_method_emits_emmo_process_graph() -> None:
    doc = _assemble({
        "test_spec": {"id": SPEC_ID, "name": "CC discharge", "kind": "capacity_check"},
        "method": [
            {
                "mode": "cc", "direction": "discharge",
                "setpoints": {"c_rate": {"value": 0.05, "unit": "A/Ah"}},
                "termination": [{"quantity": "voltage", "direction": "below", "value": 0.9, "unit": "V"}],
            }
        ],
        "conditions": {"temperature": {"value": 20, "unit": "degC"}},
    })
    node = _howto(doc)

    # The method is an ordered EMMO task chain; the single step is a CC discharge.
    step = node["hasTask"][0]
    assert step["@type"] == "ConstantCurrentDischarging"

    control = step["hasControlParameter"]
    assert control[0]["@type"] == "CRate"
    assert control[0]["hasNumericalPart"]["hasNumberValue"] == 0.05
    assert control[0]["hasMeasurementUnit"] == {"@id": "electrochemistry:AmperePerAmpereHour"}

    term = step["hasTerminationParameter"]
    assert term[0]["@type"] == "LowerVoltageLimit"
    assert term[0]["hasNumericalPart"]["hasNumberValue"] == 0.9
    assert term[0]["hasMeasurementUnit"] == {"@id": "emmo:Volt"}

    # Protocol-level ambient condition attaches as hasProperty on the procedure.
    prop = node["hasProperty"]
    assert prop[0]["@type"] == "ConventionalProperty"
    assert prop[0]["hasNumericalPart"]["hasNumberValue"] == 20
    assert prop[0]["rdfs:label"] == "temperature"          # generic class → human label
    assert "@id" in prop[0]["hasMeasurementUnit"]          # degC resolves

    # The method vocabulary must resolve in the document's own (inlined) context.
    ctx = doc["@context"]
    for term_name in ("hasTask", "hasControlParameter", "hasTerminationParameter",
                      "CRate", "LowerVoltageLimit", "ConstantCurrentDischarging", "ConventionalProperty"):
        assert term_name in ctx
    # Mapped conditions are NOT duplicated as schema:PropertyValue.
    assert "schema:additionalProperty" not in node


def test_group_emits_iterative_workflow() -> None:
    doc = _assemble({
        "test_spec": {"id": SPEC_ID, "name": "Cycling", "kind": "cycling"},
        "method": [
            {
                "mode": "group", "count": 3,
                "steps": [
                    {"mode": "cc", "direction": "charge",
                     "setpoints": {"c_rate": {"value": 1.0, "unit": "A/Ah"}},
                     "termination": [{"quantity": "voltage", "direction": "above", "value": 4.2, "unit": "V"}]},
                    {"mode": "cc", "direction": "discharge",
                     "setpoints": {"c_rate": {"value": 1.0, "unit": "A/Ah"}},
                     "termination": [{"quantity": "voltage", "direction": "below", "value": 2.5, "unit": "V"}]},
                ],
            }
        ],
    })
    group = _howto(doc)["hasTask"][0]
    assert group["@type"] == "IterativeWorkflow"
    assert group["NumberOfIterations"]["hasNumericalPart"]["hasNumberValue"] == 3
    assert [s["@type"] for s in group["hasTask"]] == ["ConstantCurrentCharging", "ConstantCurrentDischarging"]
    assert group["hasTask"][0]["hasTerminationParameter"][0]["@type"] == "UpperVoltageLimit"


def test_unmapped_condition_falls_back_and_warns() -> None:
    doc = _assemble({
        "test_spec": {"id": SPEC_ID, "name": "CC discharge", "kind": "capacity_check"},
        "conditions": {"relative_humidity": {"value": 50, "unit": "%"}},
    })
    node = _howto(doc)
    # Unmapped name → schema:PropertyValue fallback, not an EMMO quantity.
    extra = node["schema:additionalProperty"]
    assert extra[0]["schema:name"] == "relative_humidity"
    assert "hasProperty" not in node

    # …and the condition check flags it as a WARNING (never an error) even under
    # the strict publisher policy, so it nudges without blocking publication.
    report = _test_condition_issues(doc, get_validation_policy("publisher"))
    unmapped = [i for i in report.issues if i.code == "publication.test_condition_unmapped"]
    assert unmapped, "expected an unmapped-condition warning"
    assert all(i.severity == "warning" for i in unmapped)
    assert report.ok  # warnings never fail the report


def test_load_test_spec_forwards_method_and_conditions(tmp_path: Path) -> None:
    """The authoring hop must parse the PyBaMM-style experiment into the structured
    method and carry ambient conditions into the saved record."""
    ws = AuthoringWorkspace(root=tmp_path)
    spec_file = tmp_path / "p.test-spec.json"
    spec_file.write_text(
        '{"name": "CC discharge", "type": "capacity_check", '
        '"experiment": ["Discharge at C/20 until 0.9 V"], '
        '"conditions": {"temperature": {"value": 20, "unit": "degC"}}}',
        encoding="utf-8",
    )
    proto = ws.load(spec_file)
    # The PyBaMM string was parsed into a structured cc-discharge step.
    assert proto.method[0].mode == "cc"
    assert proto.method[0].direction == "discharge"
    term = proto.method[0].termination[0]
    assert (term.quantity, term.direction, term.value) == ("voltage", "below", 0.9)
    assert proto.conditions["temperature"].unit == "degC"
    # And they survive serialization once an id is assigned (the save path mints one).
    proto.id = SPEC_ID
    record = proto.to_record()
    assert record["method"][0]["termination"][0]["value"] == 0.9
    assert record["conditions"]["temperature"]["unit"] == "degC"
    assert record["facets"]["voltage_window_V"] == [0.9, 0.9]
