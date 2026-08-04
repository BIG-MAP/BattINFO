"""Test-protocol JSON-LD emission (readiness finding M5).

Protocols were the last record type ``record_to_jsonld`` could not emit: the only
implementation lived inside the publication graph builder. It now lives in
``battinfo.jsonld`` and both callers share it, so a protocol published in a deposit
and one exported standalone are the same graph.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from rdflib import Graph

import battinfo

# Imported as a module, not by name: the protocol helpers follow the existing
# ``test_to_jsonld`` naming, so importing them here would have pytest try to
# collect them as test functions.
from battinfo import jsonld as bi_jsonld
from battinfo.jsonld import record_to_jsonld

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
                for token in (value if isinstance(value, list) else [value]):
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
        zenodo_record_id=1, prereserved_doi="10.5281/zenodo.1",
        record_url="https://zenodo.org/records/1", data_filenames=[],
        title="t", description="d", license="CC-BY-4.0",
    )
    graph_node = next(n for n in graph_doc["@graph"] if n.get("@id") == record["test_spec"]["id"])
    standalone = {k: v for k, v in record_to_jsonld(record, "test-protocol").items()
                  if k not in ("@context", "dcterms:source")}
    for key, value in standalone.items():
        assert graph_node.get(key) == value, f"{key} differs between the two emitters"


def test_attribution_is_stamped_like_every_other_record_type() -> None:
    record = dict(_example("3p7k-2m9r-6t4n-1v8x"))
    record["license"] = "https://creativecommons.org/licenses/by/4.0/"
    record["contributor"] = [{"name": "Josiah Carberry",
                              "same_as": "https://orcid.org/0000-0002-1825-0097"}]
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
    (records / "test-protocol-3p7k-2m9r-6t4n-1v8x.json").write_text(
        json.dumps(record), encoding="utf-8"
    )
    written = ws.export()
    assert any(p.name.endswith(".jsonld") and "test-protocol" in p.parent.name for p in written)
