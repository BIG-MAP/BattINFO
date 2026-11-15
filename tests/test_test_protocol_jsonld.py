"""Test-protocol JSON-LD emission (readiness finding M5).

Protocols were the last record type ``record_to_jsonld`` could not emit: the only
implementation lived inside the publication graph builder. It now lives in
``battinfo.jsonld`` and both callers share it, so a protocol published in a deposit
and one exported standalone are the same graph.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import pytest
from rdflib import Graph

import battinfo

# Imported as a module, not by name: the protocol helpers follow the existing
# ``test_to_jsonld`` naming, so importing them here would have pytest try to
# collect them as test functions.
from battinfo import jsonld as bi_jsonld
from battinfo.jsonld import record_to_jsonld
from battinfo.validate import validate_record_report

EXAMPLES = Path(__file__).resolve().parents[1] / "src" / "battinfo" / "data" / "examples" / "test-protocol"


def _example(uid: str) -> dict:
    return json.loads((EXAMPLES / f"test-protocol-{uid}.json").read_text(encoding="utf-8"))


def test_record_to_jsonld_accepts_test_protocol() -> None:
    doc = record_to_jsonld(_example("3p7k-2m9r-6t4n-1v8x"), "test-protocol", context="inline")
    assert doc["@id"] == "https://w3id.org/battinfo/spec/3p7k-2m9r-6t4n-1v8x"
    assert "prov:Plan" in doc["@type"] and "schema:HowTo" in doc["@type"]


@pytest.mark.parametrize("alias", ["test-protocol", "test_protocol", "test-spec", "test_spec"])
def test_every_record_type_alias_routes_to_the_protocol_emitter(alias: str) -> None:
    assert record_to_jsonld(_example("3p7k-2m9r-6t4n-1v8x"), alias)["@id"]


def test_protocol_types_itself_with_its_method_class() -> None:
    gitt = record_to_jsonld(_example("3p7k-2m9r-6t4n-1v8x"), "test-protocol")
    assert "GalvanostaticIntermittentTitrationTechnique" in gitt["@type"]
    pocv = record_to_jsonld(_example("t163-7ba5-r0kn-h9my"), "test-protocol")
    assert "PseudoOpenCircuitVoltageMethod" in pocv["@type"]


def test_unmapped_kind_keeps_the_plan_node_untyped() -> None:
    assert bi_jsonld.test_method_class("some-bespoke-procedure") is None
    node = bi_jsonld.test_protocol_node({"test_spec": {"id": "https://example.org/p", "kind": "other"}})
    assert node["@type"] == ["prov:Plan", "schema:HowTo"]


def test_method_kind_spellings_importers_produce_all_resolve() -> None:
    for spelling in ("GITT", "gitt", "quasi ocv", "quasi-ocv", "rate-capability"):
        assert bi_jsonld.test_method_class(spelling) is not None, spelling


def test_a_record_without_a_protocol_iri_yields_no_node() -> None:
    assert bi_jsonld.test_protocol_node({"test_spec": {"name": "draft"}}) is None


def test_every_shipped_protocol_example_parses_as_rdf() -> None:
    """A typed method node is worth nothing if the document does not expand."""
    seen_method_class = 0
    for path in sorted(EXAMPLES.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        doc = record_to_jsonld(record, "test-protocol", context="inline")
        graph = Graph()
        graph.parse(data=json.dumps(doc), format="json-ld")
        assert len(graph) > 0, f"{path.name} expanded to no triples"
        if len(doc["@type"]) > 2:
            seen_method_class += 1
    assert seen_method_class >= 5, "expected the shipped examples to exercise several method classes"


def test_method_steps_become_a_typed_task_chain() -> None:
    doc = record_to_jsonld(_example("j19t-9cm0-f219-zh4y"), "test-protocol", context="inline")
    tasks = doc["hasTask"]
    assert tasks, "a protocol with a descriptive method must emit hasTask"
    # Every step node carries a bare EMMO process class, never a raw literal.
    for task in tasks:
        assert isinstance(task["@type"], str) and ":" not in task["@type"]


def test_hosted_context_resolves_everything_the_protocol_emitter_uses() -> None:
    """``context="url"`` is only safe if the hosted document is a superset."""
    from importlib import resources

    ctx_file = resources.files("battinfo").joinpath("data", "context", "records.context.v1.json")
    with ctx_file.open("r", encoding="utf-8") as handle:
        hosted = json.load(handle)["@context"]
    for path in sorted(EXAMPLES.glob("*.json")):
        doc = record_to_jsonld(json.loads(path.read_text(encoding="utf-8")), "test-protocol", context="inline")
        for term in _bare_terms(doc):
            assert term in hosted, f"{path.name}: {term} missing from the hosted context"


def _bare_terms(node: object, out: set[str] | None = None) -> set[str]:
    """Every key and bare @type token a document uses (skipping the context)."""
    out = set() if out is None else out
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "@context":
                continue
            if not key.startswith("@") and ":" not in key:
                out.add(key)
            if key == "@type":
                for token in value if isinstance(value, list) else [value]:
                    if isinstance(token, str) and ":" not in token:
                        out.add(token)
            else:
                _bare_terms(value, out)
    elif isinstance(node, list):
        for item in node:
            _bare_terms(item, out)
    return out


def test_publication_graph_and_standalone_document_agree(tmp_path: Path) -> None:
    """The two consumers of the shared builder must produce the same node."""
    record = _example("j19t-9cm0-f219-zh4y")
    ws = battinfo.workspace(str(tmp_path))
    graph_doc = ws._assemble_zenodo_jsonld(
        {"test-protocol": [record]},
        zenodo_record_id=1,
        prereserved_doi="10.5281/zenodo.1",
        record_url="https://zenodo.org/records/1",
        data_filenames=[],
        title="t",
        description="d",
        license="CC-BY-4.0",
    )
    graph_node = next(n for n in graph_doc["@graph"] if n.get("@id") == record["test_spec"]["id"])
    standalone = {
        k: v for k, v in record_to_jsonld(record, "test-protocol").items() if k not in ("@context", "dcterms:source")
    }
    for key, value in standalone.items():
        assert graph_node.get(key) == value, f"{key} differs between the two emitters"


def test_attribution_is_stamped_like_every_other_record_type() -> None:
    record = dict(_example("3p7k-2m9r-6t4n-1v8x"))
    record["license"] = "https://creativecommons.org/licenses/by/4.0/"
    record["contributor"] = [{"name": "Josiah Carberry", "same_as": "https://orcid.org/0000-0002-1825-0097"}]
    record["funding"] = {"identifier": "101103997", "name": "A grant"}
    doc = record_to_jsonld(record, "test-protocol")
    assert doc["dcterms:license"]["@id"] == record["license"]
    assert doc["schema:contributor"][0]["@id"].endswith("0000-0002-1825-0097")
    assert doc["schema:funding"]["schema:identifier"] == "101103997"


def test_export_writes_a_protocol_document(tmp_path: Path) -> None:
    ws = battinfo.workspace(str(tmp_path))
    records = tmp_path / ".battinfo" / "records" / "test-protocol"
    records.mkdir(parents=True)
    record = _example("3p7k-2m9r-6t4n-1v8x")
    (records / "test-protocol-3p7k-2m9r-6t4n-1v8x.json").write_text(json.dumps(record), encoding="utf-8")
    written = ws.export()
    assert any(p.name.endswith(".jsonld") and "test-protocol" in p.parent.name for p in written)


# ── The unit "C" is the C-rate unit on a C-rate only ─────────────────────────

C_RATE_UNIT = {"@id": "electrochemistry:AmperePerAmpereHour"}
IN_C = {"value": 25, "unit": "C"}


def _with(path: str, quantity: dict) -> dict:
    """The Empa half-cell protocol with *quantity* written at *path*, a dotted path with ``[i]`` list steps."""
    record = _example("xj15-1cpp-amcv-kyxz")
    parts = path.replace("]", "").replace("[", ".").split(".")
    holder: Any = record
    for part, following in zip(parts, parts[1:]):
        key: Any = int(part) if part.isdigit() else part
        if isinstance(holder, list):
            while len(holder) <= key:
                holder.append({})
        elif key not in holder:
            holder[key] = [] if following.isdigit() else {}
        holder = holder[key]
    last: Any = int(parts[-1]) if parts[-1].isdigit() else parts[-1]
    if isinstance(holder, list):
        holder.insert(last, quantity)
    else:
        holder[last] = quantity
    return record


def _quantity_nodes(node: Any) -> list[dict]:
    """Every node of an emitted document that carries a unit, as an IRI or as text."""
    found = []
    if isinstance(node, dict):
        if "hasMeasurementUnit" in node or "schema:unitText" in node:
            found.append(node)
        for value in node.values():
            found += _quantity_nodes(value)
    elif isinstance(node, list):
        for item in node:
            found += _quantity_nodes(item)
    return found


def _emit(record: dict) -> tuple[list[dict], list[str]]:
    """The unit-carrying nodes of the protocol's JSON-LD, and the ``semantic.unit_unmapped`` warnings it gave."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        doc = record_to_jsonld(record, "test-protocol")
    said = [str(w.message) for w in caught if str(w.message).startswith("semantic.unit_unmapped")]
    return _quantity_nodes(doc), said


def _unit_issues(record: dict, policy: str) -> list[tuple[str, str]]:
    report = validate_record_report(record, policy=policy)
    assert report.ok
    return [(issue.severity, issue.path) for issue in report.issues if issue.code == "semantic.unit_unmapped"]


NOT_A_C_RATE = [
    ("conditions.temperature", IN_C, "CelsiusTemperature"),
    ("conditions.ambient_temperature", IN_C, "AmbientCelsiusTemperature"),
    ("conditions.duration", {"value": 2, "unit": "C"}, "Duration"),
    ("conditions.current", {"value": 0.5, "unit": "C"}, "ElectricCurrent"),
    ("method[0].temperature", IN_C, "CelsiusTemperature"),
    ("method[0].setpoints.temperature", IN_C, "CelsiusTemperature"),
    ("method[0].duration", {"value": 2, "unit": "C"}, "Duration"),
    (
        "method[0].termination[0]",
        {"quantity": "capacity", "value": 3600, "unit": "C", "direction": "above"},
        "TerminationQuantity",
    ),
    ("method[1].setpoints.voltage", {"value": 4.2, "unit": " C "}, "Voltage"),
]


@pytest.mark.parametrize(("path", "quantity", "cls"), NOT_A_C_RATE, ids=[case[0] for case in NOT_A_C_RATE])
def test_the_unit_c_on_a_quantity_that_is_not_a_c_rate_is_kept_as_text(path: str, quantity: dict, cls: str) -> None:
    """A temperature, a duration or a current in ``C`` no longer takes the C-rate unit, and both sides say so."""
    record = _with(path, quantity)

    nodes, said = _emit(record)
    (as_text,) = [node for node in nodes if "schema:unitText" in node]
    assert as_text["@type"] == cls
    assert as_text["schema:unitText"] == quantity["unit"]
    assert "hasMeasurementUnit" not in as_text
    assert [node for node in nodes if node.get("hasMeasurementUnit") == C_RATE_UNIT] == []
    assert len(said) == 1 and "'C' is a unit on a C-rate only" in said[0]

    for policy in ("default", "strict", "publisher"):
        assert _unit_issues(record, policy) == [("warning", path)]


def test_the_unit_c_inside_a_group_is_found_at_its_step() -> None:
    record = _example("xj15-1cpp-amcv-kyxz")
    record["method"] = [{"mode": "group", "count": 2, "steps": [{**record["method"][0], "temperature": IN_C}]}]

    nodes, said = _emit(record)
    assert [node["@type"] for node in nodes if node.get("schema:unitText") == "C"] == ["CelsiusTemperature"]
    assert len(said) == 1
    assert _unit_issues(record, "strict") == [("warning", "method[0].steps[0].temperature")]


A_C_RATE = [
    ("conditions.c_rate", {"value": 0.5, "unit": "C"}, "CRate"),
    ("method[0].setpoints.c_rate", {"value": 0.5, "unit": "C"}, "CRate"),
    (
        "method[0].termination[0]",
        {"quantity": "c_rate", "value": 0.05, "unit": "C", "direction": "below"},
        "TerminationQuantity",
    ),
    # A current cutoff written in C is a C-rate cutoff under the wrong name. The step
    # model says so when it loads one, and the emitter gives it the generic class.
    (
        "method[0].termination[0]",
        {"quantity": "current", "value": 0.05, "unit": "C", "direction": "below"},
        "TerminationQuantity",
    ),
]


@pytest.mark.parametrize(
    ("path", "quantity", "cls"), A_C_RATE, ids=[f"{case[0]}-{case[1].get('quantity', '')}" for case in A_C_RATE]
)
def test_the_unit_c_on_a_c_rate_is_the_c_rate_unit(path: str, quantity: dict, cls: str) -> None:
    record = _with(path, quantity)

    nodes, said = _emit(record)
    (c_rate,) = [node for node in nodes if node.get("hasMeasurementUnit") == C_RATE_UNIT]
    assert c_rate["@type"] == cls
    assert [node for node in nodes if "schema:unitText" in node] == []
    assert said == []
    for policy in ("default", "strict", "publisher"):
        assert _unit_issues(record, policy) == []


def test_resolve_unit_iri_reads_c_on_a_c_rate_only() -> None:
    assert bi_jsonld.resolve_unit_iri("C") is None
    assert bi_jsonld.resolve_unit_iri("C", c_rate=True) == C_RATE_UNIT["@id"]
    # The spelled-out C-rate units name one quantity, so they resolve wherever they stand.
    for symbol in ("A/Ah", "Ah/Ah"):
        assert (
            bi_jsonld.resolve_unit_iri(symbol) == bi_jsonld.resolve_unit_iri(symbol, c_rate=True) == C_RATE_UNIT["@id"]
        )
    # C is never read as another unit, and degC is the degree Celsius as before.
    assert bi_jsonld.resolve_unit_iri("degC") == "emmo:DegreeCelsius"
    assert bi_jsonld.c_rate_unit_reason("degC", c_rate=False) is None
    assert bi_jsonld.c_rate_unit_reason("C", c_rate=True) is None
    assert bi_jsonld.c_rate_unit_reason("banana", c_rate=False) is None
