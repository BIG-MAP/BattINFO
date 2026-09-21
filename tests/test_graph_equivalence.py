"""M2 semantic contracts: emission modes agree as RDF GRAPHS, and exported
graphs answer domain questions through an independent consumer.

The 0.8.0 review showed that comparing JSON spelling is insufficient — the
generated files and their expectations can share a defect. These tests parse
the emitted JSON-LD with rdflib (an independent processor, not battinfo's own
loader), canonicalize, and compare/query the actual graphs:

- inline and URL emission modes must be graph-isomorphic for every packaged
  record (the promise stated on ``record_to_jsonld``);
- every hosted-context URL a document names must be resolvable from the
  vendored files (the offline promise);
- SPARQL questions with independently stated expected answers must hold on
  the merged corpus graph — class IRIs are resolved THROUGH the published
  context, the way a third-party consumer would, and expected values are read
  from the plain records, not from the emitter.
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import pytest
import rdflib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.jsonld import record_to_jsonld  # noqa: E402

EXAMPLES = ROOT / "src" / "battinfo" / "data" / "examples"
BASE = "https://battinfo.invalid/base/"

_V1 = json.loads(
    (ROOT / "src" / "battinfo" / "data" / "context" / "records.context.v1.json")
    .read_text(encoding="utf-8")
)["@context"]
_DOMAIN_BATTERY = json.loads(
    (ROOT / "src" / "battinfo" / "data" / "context" / "domain-battery.context.json")
    .read_text(encoding="utf-8")
)["@context"]

# Every context URL an emitted document may name, mapped to the vendored copy.
# A URL outside this map means the offline promise is broken — the test fails
# rather than fetching.
LOCAL_CONTEXTS = {
    "https://w3id.org/battinfo/context/records/v1.json": _V1,
    "https://w3id.org/emmo/domain/battery/context": _DOMAIN_BATTERY,
}


def _substituted(doc: dict) -> dict:
    doc = dict(doc)
    ctx = doc.get("@context")
    if isinstance(ctx, str):
        assert ctx in LOCAL_CONTEXTS, f"unmapped remote context: {ctx}"
        doc["@context"] = LOCAL_CONTEXTS[ctx]
    elif isinstance(ctx, list):
        out = []
        for entry in ctx:
            if isinstance(entry, str):
                assert entry in LOCAL_CONTEXTS, f"unmapped remote context: {entry}"
                out.append(LOCAL_CONTEXTS[entry])
            else:
                out.append(entry)
        doc["@context"] = out
    return doc


def _graph(doc: dict) -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=json.dumps(_substituted(doc)), format="json-ld", base=BASE)
    return g


def _iter_records():
    for kind_dir in sorted(p for p in EXAMPLES.iterdir() if p.is_dir()):
        if kind_dir.name == "profiles":
            continue  # profile documents, not records — no emitter
        for path in sorted(kind_dir.glob("*.json")):
            yield kind_dir.name, path, json.loads(path.read_text(encoding="utf-8"))


def _graph_signature(g: rdflib.Graph) -> Counter:
    """A canonical multiset of triples with blank nodes replaced by structural
    hashes, computed bottom-up.

    rdflib's ``to_isomorphic`` blank-node coloring is exponential on the highly
    symmetric property lists these documents contain; our emitted documents are
    TREES over blank nodes (cycles only through named IRIs), so a fixpoint of
    bottom-up hashing converges in tree-depth iterations and is linear in
    practice. Two identical sibling nodes hash equal — the multiset keeps them
    both.
    """
    def atom(term) -> str:
        return term.n3()

    bnodes = {t for t in set(g.subjects()) | set(g.objects()) if isinstance(t, rdflib.BNode)}
    labels: dict[rdflib.BNode, str] = {b: "" for b in bnodes}
    for _ in range(len(bnodes) + 1):
        new_labels = {}
        for b in bnodes:
            outgoing = sorted(
                (atom(p), labels[o] if isinstance(o, rdflib.BNode) else atom(o))
                for p, o in g.predicate_objects(b)
            )
            new_labels[b] = hashlib.sha256(repr(outgoing).encode()).hexdigest()
        if new_labels == labels:
            break
        labels = new_labels

    def rep(term) -> str:
        return labels[term] if isinstance(term, rdflib.BNode) else atom(term)

    return Counter((rep(s), atom(p), rep(o)) for s, p, o in g)


def test_inline_and_url_modes_are_graph_isomorphic() -> None:
    """The documented promise: 'Both expand to the same graph' — checked as
    canonicalized RDF over the whole packaged corpus (0.8.0 review F4)."""
    checked = 0
    mismatches: list[str] = []
    for kind, path, record in _iter_records():
        inline = _graph_signature(_graph(record_to_jsonld(record, kind, context="inline")))
        url = _graph_signature(_graph(record_to_jsonld(record, kind, context="url")))
        checked += 1
        if inline != url:
            in_only = sum((inline - url).values())
            url_only = sum((url - inline).values())
            mismatches.append(f"{kind}/{path.name}: inline-only={in_only} url-only={url_only}")
    assert checked > 140, f"corpus sweep looks broken (only {checked} records)"
    assert not mismatches, "emission modes diverge as graphs:\n" + "\n".join(mismatches)


# ── Independent-consumer SPARQL questions ────────────────────────────────────


@pytest.fixture(scope="module")
def corpus_graph() -> rdflib.Graph:
    """Every packaged record's URL-mode JSON-LD, merged into one graph by an
    independent processor."""
    g = rdflib.Graph()
    for kind, _path, record in _iter_records():
        doc = record_to_jsonld(record, kind, context="url")
        g.parse(data=json.dumps(_substituted(doc)), format="json-ld", base=BASE)
    return g


def _term_iri(term: str) -> str:
    """Resolve a context term to its absolute IRI the way a consumer would:
    through the published records context (compact IRIs via its prefixes)."""
    value = _V1[term]
    compact = value if isinstance(value, str) else value["@id"]
    if "://" in compact:
        return compact
    prefix, _, local = compact.partition(":")
    return _V1[prefix] + local


def test_cell_instances_state_their_spec_conformance(corpus_graph) -> None:
    """Q1: 'which spec does this physical cell conform to?' — every cell
    instance carries dcterms:conformsTo, and every target is a spec IRI that
    the corpus actually describes."""
    rows = list(corpus_graph.query(
        """
        SELECT ?cell ?spec WHERE {
            ?cell <http://purl.org/dc/terms/conformsTo> ?spec .
        }
        """
    ))
    cell_instances = len(list((EXAMPLES / "cell-instance").glob("*.json")))
    assert cell_instances > 0
    assert len(rows) >= cell_instances, (
        f"{cell_instances} cell instances but only {len(rows)} conformsTo edges"
    )
    subjects = {str(s) for s in corpus_graph.subjects()}
    for _cell, spec in rows:
        assert str(spec).startswith("https://w3id.org/battinfo/spec/"), str(spec)
        assert str(spec) in subjects, f"conformsTo target not described in corpus: {spec}"


def test_nominal_capacity_is_a_conventional_property_with_the_records_value(
    corpus_graph,
) -> None:
    """Q2 (the review's rated-vs-measured spirit): the A123 spec's nominal
    capacity is retrievable by CLASS (NominalCapacity), is explicitly typed as
    a ConventionalProperty (a declared datasheet value, not a measurement),
    and carries the number the plain record states."""
    record = json.loads(
        (EXAMPLES / "cell-spec" / "A123__ANR26650M1-B.json").read_text(encoding="utf-8")
    )
    expected = record["properties"]["nominal_capacity"]["value"]  # independent source
    spec_iri = record["cell_spec"]["id"]

    rows = list(corpus_graph.query(
        f"""
        SELECT ?value WHERE {{
            <{spec_iri}> <{_term_iri("isDescriptionFor")}> ?described .
            ?described <{_term_iri("hasProperty")}> ?prop .
            ?prop a <{_term_iri("NominalCapacity")}> , <{_term_iri("ConventionalProperty")}> .
            ?prop <{_term_iri("hasNumericalPart")}> ?num .
            ?num <{_term_iri("hasNumberValue")}> ?value .
        }}
        """
    ))
    assert len(rows) == 1, f"expected exactly one nominal-capacity node, got {len(rows)}"
    assert float(rows[0][0]) == pytest.approx(expected)


def test_parameter_claims_expose_their_provenance_class(corpus_graph) -> None:
    """Q3 (claims epistemics): a consumer can ask 'on what basis is this
    parameter claimed?' — provenance_class annotations are retrievable per
    claim, and the corpus distinguishes more than one epistemic basis."""
    rows = list(corpus_graph.query(
        """
        SELECT ?claim ?basis WHERE {
            ?claim <https://schema.org/additionalProperty> ?ann .
            ?ann <https://schema.org/name> "provenance_class" .
            ?ann <https://schema.org/value> ?basis .
        }
        """
    ))
    assert len(rows) > 50, f"expected a claims corpus, found {len(rows)} annotated claims"
    bases = {str(b) for _c, b in rows}
    assert len(bases) >= 2, f"corpus should distinguish epistemic bases, found only {bases}"
    assert bases <= {"measured", "fitted", "literature", "derived", "assumed"}, bases
