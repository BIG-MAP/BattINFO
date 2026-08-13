"""Every term a served record uses must dereference to a defining subject.

Served records expand against ``@vocab https://w3id.org/battinfo/ns#``. The
vocabulary served at /battinfo/ns (assets/vocab/battinfo-records.ttl, generated
by scripts/gen_battinfo_vocab.py) must therefore define an ``ns#`` subject for
every predicate and type those records carry — otherwise the IRI is a
dereference dead-end.

The fixtures under tests/fixtures/served/ are the ACTUAL registry-served
representations of the flagship cell spec
(w3id.org/battinfo/spec/pge5-wer6-2q82-v9k0), captured verbatim: the JSON-LD
(@vocab, snake_case, ``@type: CellSpec``) and its Turtle projection (camelCase,
``a battinfo:CellSpecification``). Both are registry emitters; see the PR body
for the registry-side convergence note.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import rdflib
from pyld import jsonld

ROOT = Path(__file__).resolve().parents[1]
TTL = ROOT / "assets" / "vocab" / "battinfo-records.ttl"
FIX = ROOT / "tests" / "fixtures" / "served"
NS = "https://w3id.org/battinfo/ns#"

# rdf_type stamped by the BattINFO submission envelope for each record type
# (api/_staging.py, ws.py). These are the canonical served ``@type`` names.
BATTINFO_RDF_TYPES = {
    "CellSpec", "BatteryCell", "TestSpec", "BatteryTest", "Dataset",
    "MaterialSpec", "Material", "ElectrodeSpec", "Electrode",
}


def _defined_ns_subjects() -> set[str]:
    graph = rdflib.Graph()
    graph.parse(TTL, format="turtle")
    return {str(s)[len(NS):] for s in set(graph.subjects()) if str(s).startswith(NS)}


def _ns_iris_in_expanded(node) -> set[str]:
    """All ns# IRIs used as predicates or @type values in an expanded JSON-LD tree."""
    found: set[str] = set()

    def walk(obj) -> None:
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key == "@type":
                    for t in val if isinstance(val, list) else [val]:
                        if isinstance(t, str) and t.startswith(NS):
                            found.add(t[len(NS):])
                elif key.startswith("@"):
                    walk(val)
                else:
                    if key.startswith(NS):
                        found.add(key[len(NS):])
                    walk(val)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(node)
    return found


def test_generated_ttl_parses() -> None:
    graph = rdflib.Graph()
    graph.parse(TTL, format="turtle")
    assert len(graph) > 0


def test_flagship_jsonld_terms_all_dereference() -> None:
    doc = json.loads((FIX / "flagship-cell-spec.jsonld").read_text(encoding="utf-8"))
    expanded = jsonld.expand(doc)  # offline: @vocab + inline prefixes only
    used = _ns_iris_in_expanded(expanded)
    assert used, "fixture produced no ns# terms — expansion changed shape"
    missing = sorted(used - _defined_ns_subjects())
    assert not missing, (
        "served JSON-LD uses ns# IRIs with no defining subject in "
        f"battinfo-records.ttl: {missing}. Regenerate with "
        "`uv run python scripts/gen_battinfo_vocab.py`."
    )


def test_flagship_turtle_terms_all_dereference() -> None:
    ttl = (FIX / "flagship-cell-spec.ttl").read_text(encoding="utf-8")
    used = set(re.findall(r"battinfo:([A-Za-z_][A-Za-z0-9_]*)", ttl))
    assert used
    missing = sorted(used - _defined_ns_subjects())
    assert not missing, (
        "served Turtle uses ns# IRIs with no defining subject in "
        f"battinfo-records.ttl: {missing}."
    )


def test_every_battinfo_rdf_type_is_a_defined_class() -> None:
    graph = rdflib.Graph()
    graph.parse(TTL, format="turtle")
    owl_class = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
    classes = {
        str(s)[len(NS):]
        for s in graph.subjects(rdflib.RDF.type, owl_class)
        if str(s).startswith(NS)
    }
    missing = sorted(BATTINFO_RDF_TYPES - classes)
    assert not missing, f"rdf_type(s) emitted by the package but undefined as ns# classes: {missing}"


def test_jsonld_and_turtle_type_names_reconcile() -> None:
    """CellSpec (JSON-LD @type) and CellSpecification (Turtle) resolve to one class."""
    doc = json.loads((FIX / "flagship-cell-spec.jsonld").read_text(encoding="utf-8"))
    assert doc["@type"] == "CellSpec"
    ttl = (FIX / "flagship-cell-spec.ttl").read_text(encoding="utf-8")
    assert "battinfo:CellSpecification" in ttl

    graph = rdflib.Graph()
    graph.parse(TTL, format="turtle")
    equiv = rdflib.URIRef("http://www.w3.org/2002/07/owl#equivalentClass")
    # The registry Turtle spelling is declared equivalent to the canonical name,
    # so both dereference to the same class until the registry converges.
    assert (
        rdflib.URIRef(NS + "CellSpecification"),
        equiv,
        rdflib.URIRef(NS + "CellSpec"),
    ) in graph
