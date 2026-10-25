"""Committed generated reference pages must match what the code produces today."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load(script: str):
    spec = importlib.util.spec_from_file_location(script, ROOT / "scripts" / f"{script}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The standalone schema-reference page retired into docs/records/ (each family
# page carries its schemas' field tables, drift-gated by
# tests/test_reference_records.py); its generator went with it.


def test_cli_reference_matches_the_typer_app() -> None:
    # gen_cli_reference normalises path separators, so the committed page is
    # byte-identical no matter which platform generated or checks it.
    gen = _load("gen_cli_reference")
    expected = gen.build()
    actual = gen.OUT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert actual == expected, (
        "docs/pages/cli-reference.md drifts from the CLI — regenerate with `uv run python scripts/gen_cli_reference.py`"
    )


def test_battinfo_vocab_covers_every_emitted_term() -> None:
    gen = _load("gen_battinfo_vocab")

    committed = (ROOT / "assets" / "vocab" / "battinfo-records.ttl").read_text(encoding="utf-8")
    assert committed == gen.build(), (
        "assets/vocab/battinfo-records.ttl is stale - a battinfo: term was "
        "added/removed; regenerate with `uv run python scripts/gen_battinfo_vocab.py`"
    )


def test_the_vocabulary_is_its_own_ontology_and_keeps_its_retired_terms() -> None:
    """One owl:Ontology, https://w3id.org/battinfo/vocab/records, defining every term (BIG-MAP/BattINFO#481).

    The root, https://w3id.org/battinfo/, is the BattINFO ontology's address,
    so the vocabulary does not claim it. Its terms stay at the root; the
    retired ones are owl:deprecated, with dcterms:isReplacedBy where known.
    """
    import rdflib
    from rdflib.namespace import DCTERMS, OWL, RDF, RDFS

    gen = _load("gen_battinfo_vocab")
    graph = rdflib.Graph().parse(ROOT / "assets" / "vocab" / "battinfo-records.ttl", format="turtle")
    ontology = rdflib.URIRef("https://w3id.org/battinfo/vocab/records")
    assert set(graph.subjects(RDF.type, OWL.Ontology)) == {ontology}

    terms = {s for s in graph.subjects(RDFS.isDefinedBy, None)}
    assert {str(o) for o in graph.objects(None, RDFS.isDefinedBy)} == {str(ontology)}
    assert all(str(term).startswith("https://w3id.org/battinfo/") and "/" not in str(term)[26:] for term in terms)
    deprecated = {s for s in graph.subjects(OWL.deprecated, rdflib.Literal(True))}
    current = terms - deprecated
    assert {str(t)[26:] for t in current} == set(gen.placeholder_terms()) | set(gen.RESIDUE)
    assert len(current) == 57
    assert {str(t)[26:] for t in deprecated} == set(gen.RETIRED)
    assert len(deprecated) == 39
    replaced = {str(s)[26:]: str(o) for s, o in graph.subject_objects(DCTERMS.isReplacedBy)}
    assert replaced == {term: iri for term, iri in gen.RETIRED.items() if iri}
    assert len(replaced) == 9


def test_emmo_labels_cover_every_mapped_term() -> None:
    gen = _load("gen_emmo_labels")

    committed = (ROOT / "assets" / "vocab" / "emmo-labels.ttl").read_text(encoding="utf-8")
    assert committed == gen.build(), (
        "assets/vocab/emmo-labels.ttl is stale - the curated property/unit/"
        "entity mappings changed; regenerate with "
        "`uv run python scripts/gen_emmo_labels.py`"
    )


def test_property_reference_matches_the_mapping_tables() -> None:
    gen = _load("gen_property_reference")

    committed = (ROOT / "docs" / "pages" / "property-reference.md").read_text(encoding="utf-8")
    assert committed == gen.build(), (
        "docs/pages/property-reference.md is stale - regenerate with `uv run python scripts/gen_property_reference.py`"
    )
