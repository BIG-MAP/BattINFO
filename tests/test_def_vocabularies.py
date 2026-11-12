"""The publishers' vocabularies under def/: scripts/check_def_vocabularies.py and scripts/build_def_site.py.

A release of a publisher's vocabulary is def/{prefix}/{X.Y.Z}/vocab.ttl. The
checks run on the real def/ folder, which may hold no vocabulary yet, and on
the fixture vocabulary in tests/fixtures/def-vocabularies/def/1000/ (releases
1.0.0, 1.1.0-beta.1 and 1.1.0), changed in one place for each rule. The
immutability check (--unchanged-since) runs against scratch git repositories.
The site build lays the fixture out as GitHub Pages serves it;
tests/test_docs_deploy.py covers how the deploy merges that into gh-pages.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "def-vocabularies" / "def"
sys.path.insert(0, str(ROOT / "src"))

from battinfo.entities import RESERVED_NAMESPACE_SEGMENTS  # noqa: E402
from battinfo.namespace import BATTINFO_ROOT, PREFIX_PATTERN  # noqa: E402


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check = _load("check_def_vocabularies")
site = _load("build_def_site")

ONTOLOGY = "https://w3id.org/battinfo/def/1000"
HAS_HOLDER = """
ex:hasHolder a owl:ObjectProperty ;
    rdfs:label "has holder"@en ;
    rdfs:comment "Links a sample to the thing that holds it."@en .
"""
DRY = """
ex:Dry a skos:Concept ;
    skos:prefLabel "dry"@en, "trocken"@de ;
    skos:definition "Held below 1 % relative humidity."@en .
"""
GLOVEBOX = """
ex:Glovebox a owl:NamedIndividual ;
    rdfs:label "glovebox"@en ;
    skos:definition "The enclosure the samples are kept in."@en .
"""
MASS_FRACTION = """
ex:massFraction a owl:DatatypeProperty ;
    rdfs:label "mass fraction"@en ;
    skos:definition "The mass of a component divided by the mass of the whole."@en .
"""


def _copy(tmp_path: Path, versions: tuple[str, ...] = ("1.0.0", "1.1.0-beta.1", "1.1.0")) -> Path:
    """A def/ folder in *tmp_path* holding the fixture releases *versions* of prefix 1000."""
    def_dir = tmp_path / "def"
    for version in versions:
        shutil.copytree(FIXTURE / "1000" / version, def_dir / "1000" / version)
    return def_dir


def _edit(def_dir: Path, version: str, old: str, new: str) -> None:
    path = def_dir / "1000" / version / "vocab.ttl"
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} is not in {version}"
    path.write_text(text.replace(old, new), encoding="utf-8")


def _add(def_dir: Path, version: str, turtle: str) -> None:
    path = def_dir / "1000" / version / "vocab.ttl"
    path.write_text(path.read_text(encoding="utf-8") + turtle, encoding="utf-8")


def _write(def_dir: Path, relative: str, text: str = "x\n") -> None:
    path = def_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_the_def_folder_passes_its_checks() -> None:
    assert (ROOT / "def" / "README.md").is_file()
    assert check.check(ROOT / "def") == []


def test_the_fixture_vocabulary_passes_its_checks() -> None:
    assert check.check(FIXTURE) == []
    assert [release.version for release in check.releases(FIXTURE)] == ["1.0.0", "1.1.0-beta.1", "1.1.0"]


def test_the_grammar_is_the_namespace_modules() -> None:
    assert check.DEF_BASE == BATTINFO_ROOT + "def/"
    assert check.BATTINFO_ROOT == BATTINFO_ROOT
    assert check.PREFIX_RE.pattern == PREFIX_PATTERN
    assert "def" in RESERVED_NAMESPACE_SEGMENTS
    # A term's local name never looks like a version, so w3id tells them apart.
    assert not any(check.TERM_RE.fullmatch(version) for version in ("1.0.0", "0.1.0-beta.1"))


@pytest.mark.parametrize(
    "name", ["1.0.0", "0.1.0", "10.20.30", "1.3.0-beta.1", "1.3.0-rc.1", "2.0.0-alpha", "1.0.0-0.3.7"]
)
def test_a_release_folder_is_named_by_a_version(name: str) -> None:
    assert check.VERSION_RE.fullmatch(name)


@pytest.mark.parametrize(
    "name", ["1.0", "v1.0.0", "01.0.0", "1.0.0+build.1", "1.0.0-", "1.0.0-beta..1", "1.0.0-01", "latest"]
)
def test_other_folder_names_are_not_versions(name: str) -> None:
    assert not check.VERSION_RE.fullmatch(name)


def test_versions_sort_by_precedence_with_pre_releases_before_their_final() -> None:
    ordered = [
        "0.9.0",
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-alpha.beta",
        "1.0.0-beta",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0-rc.1",
        "1.0.0",
        "1.2.0",
        "1.10.0",
    ]
    assert sorted(reversed(ordered), key=check.release_key) == ordered


def test_the_newest_release_is_the_newest_final_one_unless_none_is_final() -> None:
    assert check.newest_release(["1.0.0", "1.1.0-beta.1", "0.9.0"]) == "1.0.0"
    assert check.newest_release(["1.1.0-beta.1", "1.1.0-beta.2", "1.0.0-rc.1"]) == "1.1.0-beta.2"


def _backport(def_dir: Path, turtle: str = "") -> None:
    """Release 1.0.1, a backport of 1.0.0 published beside the later releases, with *turtle* added."""
    shutil.copytree(def_dir / "1000" / "1.0.0", def_dir / "1000" / "1.0.1")
    _edit(
        def_dir,
        "1.0.1",
        f'owl:versionIRI <{ONTOLOGY}/1.0.0> ;\n    owl:versionInfo "1.0.0" ;',
        f'owl:versionIRI <{ONTOLOGY}/1.0.1> ;\n    owl:versionInfo "1.0.1" ;\n    owl:priorVersion <{ONTOLOGY}/1.0.0> ;',
    )
    _add(def_dir, "1.0.1", turtle)


def _rename_prefix(def_dir: Path) -> None:
    (def_dir / "1000").rename(def_dir / "9999")


# Each case changes the fixture in one place and names a line the check must print.
CASES: list[tuple[str, Callable[[Path], None], str]] = [
    ("unallocated prefix", _rename_prefix, "def/9999: 9999 is not a prefix allocated in"),
    (
        "folder that is not a version",
        lambda d: shutil.copytree(d / "1000" / "1.0.0", d / "1000" / "latest"),
        "def/1000/latest: not a release folder",
    ),
    (
        "version with a leading zero",
        lambda d: shutil.copytree(d / "1000" / "1.0.0", d / "1000" / "01.0.0"),
        "def/1000/01.0.0: not a release folder",
    ),
    (
        "second file in a release",
        lambda d: _write(d, "1000/1.0.0/notes.md"),
        "def/1000/1.0.0/notes.md: a release folder holds vocab.ttl only",
    ),
    ("file beside the prefixes", lambda d: _write(d, "notes.txt"), "def/notes.txt: def/ holds README.md"),
    (
        "release folder without vocab.ttl",
        lambda d: (d / "1000" / "1.2.0").mkdir(),
        "def/1000/1.2.0: has no vocab.ttl",
    ),
    (
        "Turtle that does not parse",
        lambda d: _edit(d, "1.0.0", 'owl:versionInfo "1.0.0" ;', 'owl:versionInfo "1.0.0"'),
        "def/1000/1.0.0/vocab.ttl: does not parse as Turtle: line 13",
    ),
    (
        "no ontology",
        lambda d: _edit(d, "1.0.0", "a owl:Ontology", "a owl:Thing"),
        "def/1000/1.0.0/vocab.ttl: declares the owl:Ontology none; it must declare exactly one, "
        "<https://w3id.org/battinfo/def/1000>",
    ),
    (
        "ontology IRI with a trailing slash",
        lambda d: _edit(d, "1.0.0", f"<{ONTOLOGY}> a owl:Ontology", f"<{ONTOLOGY}/> a owl:Ontology"),
        "declares the owl:Ontology <https://w3id.org/battinfo/def/1000/>; it must declare exactly one",
    ),
    (
        "two ontologies",
        lambda d: _add(d, "1.1.0", f"\n<{ONTOLOGY}/Other> a owl:Ontology .\n"),
        "def/1000/1.1.0/vocab.ttl: declares the owl:Ontology <https://w3id.org/battinfo/def/1000>, "
        "<https://w3id.org/battinfo/def/1000/Other>",
    ),
    (
        "wrong version IRI",
        lambda d: _edit(d, "1.0.0", f"owl:versionIRI <{ONTOLOGY}/1.0.0>", f"owl:versionIRI <{ONTOLOGY}/1.0>"),
        "owl:versionIRI is <https://w3id.org/battinfo/def/1000/1.0>, not <https://w3id.org/battinfo/def/1000/1.0.0>",
    ),
    (
        "wrong version info",
        lambda d: _edit(d, "1.0.0", 'owl:versionInfo "1.0.0"', 'owl:versionInfo "1.0"'),
        'def/1000/1.0.0/vocab.ttl: owl:versionInfo is "1.0", not "1.0.0"',
    ),
    (
        "no title",
        lambda d: _edit(d, "1.0.0", '    dcterms:title "Example vocabulary"@en ;\n', ""),
        "def/1000/1.0.0/vocab.ttl: the ontology has no dcterms:title",
    ),
    (
        "licence as text",
        lambda d: _edit(
            d, "1.0.0", "dcterms:license <https://creativecommons.org/licenses/by/4.0/>", 'dcterms:license "CC BY 4.0"'
        ),
        "def/1000/1.0.0/vocab.ttl: the ontology has no dcterms:license that is an IRI",
    ),
    (
        "no licence",
        lambda d: _edit(
            d,
            "1.0.0",
            " ;\n    dcterms:license <https://creativecommons.org/licenses/by/4.0/> .",
            " .",
        ),
        "def/1000/1.0.0/vocab.ttl: the ontology has no dcterms:license that is an IRI",
    ),
    (
        "prior version that is no release",
        lambda d: _edit(
            d, "1.0.0", 'owl:versionInfo "1.0.0" ;', f'owl:versionInfo "1.0.0" ; owl:priorVersion <{ONTOLOGY}/0.9.0> ;'
        ),
        "def/1000/1.0.0/vocab.ttl: owl:priorVersion <https://w3id.org/battinfo/def/1000/0.9.0> is not the version "
        "IRI of a release under def/1000/ that sorts below 1.0.0",
    ),
    (
        "prior version that sorts above",
        lambda d: _edit(
            d, "1.1.0-beta.1", f"owl:priorVersion <{ONTOLOGY}/1.0.0>", f"owl:priorVersion <{ONTOLOGY}/1.1.0>"
        ),
        "def/1000/1.1.0-beta.1/vocab.ttl: owl:priorVersion <https://w3id.org/battinfo/def/1000/1.1.0> is not the "
        "version IRI of a release under def/1000/ that sorts below 1.1.0-beta.1",
    ),
    (
        "prior version of another vocabulary",
        lambda d: _edit(
            d,
            "1.1.0",
            f"owl:priorVersion <{ONTOLOGY}/1.1.0-beta.1>",
            "owl:priorVersion <https://w3id.org/battinfo/def/1001/1.0.0>",
        ),
        "owl:priorVersion <https://w3id.org/battinfo/def/1001/1.0.0> is not the version IRI of a release under def/1000/",
    ),
    (
        "term of another prefix",
        lambda d: _add(d, "1.1.0", '\n<https://w3id.org/battinfo/def/1001/Other> rdfs:label "other"@en .\n'),
        "def/1000/1.1.0/vocab.ttl: <https://w3id.org/battinfo/def/1001/Other> lies outside the vocabulary's own "
        "space, https://w3id.org/battinfo/def/1000/",
    ),
    (
        "term at the root of the name",
        lambda d: _add(d, "1.1.0", '\n<https://w3id.org/battinfo/batchId> rdfs:label "batch id"@en .\n'),
        "<https://w3id.org/battinfo/batchId> lies outside the vocabulary's own space",
    ),
    (
        "local name with a hyphen",
        lambda d: _add(
            d, "1.1.0", '\nex:has-part a owl:ObjectProperty ; rdfs:label "has part"@en ; rdfs:comment "x" .\n'
        ),
        "def/1000/1.1.0/vocab.ttl: <https://w3id.org/battinfo/def/1000/has-part>: a local name starts with a letter",
    ),
    (
        "local name that starts with a digit",
        lambda d: _add(
            d, "1.1.0", f'\n<{ONTOLOGY}/2ndPhase> a owl:Class ; rdfs:label "phase"@en ; rdfs:comment "x" .\n'
        ),
        "<https://w3id.org/battinfo/def/1000/2ndPhase>: a local name starts with a letter",
    ),
    (
        "local name with a slash",
        lambda d: _add(d, "1.1.0", f'\n<{ONTOLOGY}/a/b> a owl:Class ; rdfs:label "a b"@en ; rdfs:comment "x" .\n'),
        "<https://w3id.org/battinfo/def/1000/a/b>: a local name starts with a letter",
    ),
    (
        "label in German only",
        lambda d: _edit(d, "1.1.0", 'rdfs:label "mass fraction"@en', 'rdfs:label "Massenanteil"@de'),
        "def/1000/1.1.0/vocab.ttl: massFraction has no English label (rdfs:label or skos:prefLabel with @en)",
    ),
    (
        "label without a language",
        lambda d: _edit(d, "1.1.0", 'rdfs:label "mass fraction"@en', 'rdfs:label "mass fraction"'),
        "def/1000/1.1.0/vocab.ttl: massFraction has no English label",
    ),
    (
        "no definition",
        lambda d: _edit(
            d,
            "1.1.0",
            ' ;\n    skos:definition "The mass of a component divided by the mass of the whole."@en .',
            " .",
        ),
        "def/1000/1.1.0/vocab.ttl: massFraction has no definition (skos:definition or rdfs:comment)",
    ),
    (
        "term dropped from a later release",
        lambda d: _edit(d, "1.1.0", HAS_HOLDER, ""),
        "def/1000/1.1.0/vocab.ttl: drops hasHolder, which release 1.0.0 has; a term is never removed",
    ),
    (
        "term of a pre-release dropped from its final",
        lambda d: _edit(d, "1.1.0", DRY, ""),
        "def/1000/1.1.0/vocab.ttl: drops Dry, which release 1.1.0-beta.1 has",
    ),
    (
        "individual dropped",
        lambda d: _add(d, "1.1.0-beta.1", GLOVEBOX),
        "def/1000/1.1.0/vocab.ttl: drops Glovebox, which release 1.1.0-beta.1 has",
    ),
    (
        "subject without a type dropped",
        lambda d: _add(d, "1.0.0", '\nex:note rdfs:comment "A note."@en .\n'),
        "def/1000/1.1.0-beta.1/vocab.ttl: drops note, which release 1.0.0 has",
    ),
    (
        "individual without a label",
        lambda d: _add(d, "1.1.0", '\nex:Glovebox a owl:NamedIndividual ; rdfs:comment "An enclosure."@en .\n'),
        "def/1000/1.1.0/vocab.ttl: Glovebox has no English label",
    ),
    (
        "deprecation withdrawn",
        lambda d: _edit(d, "1.1.0", "    owl:deprecated true ;\n", ""),
        "def/1000/1.1.0/vocab.ttl: OldName is not owl:deprecated, but release 1.1.0-beta.1 deprecates it; a "
        "deprecated term stays deprecated",
    ),
    (
        "replacement the release does not define",
        lambda d: _edit(d, "1.1.0", "dcterms:isReplacedBy ex:NewName", "dcterms:isReplacedBy ex:Missing"),
        "def/1000/1.1.0/vocab.ttl: <https://w3id.org/battinfo/def/1000/OldName> dcterms:isReplacedBy "
        "<https://w3id.org/battinfo/def/1000/Missing>, which this release does not define",
    ),
    (
        "backport that adds a term the later releases lack",
        lambda d: _backport(d, '\nex:Extra a owl:Class ; rdfs:label "extra"@en ; rdfs:comment "Only in 1.0.1."@en .\n'),
        "def/1000/1.0.1/vocab.ttl: the backport 1.0.1 adds Extra, which the later release 1.1.0-beta.1 lacks",
    ),
]


@pytest.mark.parametrize(("change", "expected"), [(case[1], case[2]) for case in CASES], ids=[c[0] for c in CASES])
def test_each_rule_is_checked(tmp_path: Path, change: Callable[[Path], None], expected: str) -> None:
    def_dir = _copy(tmp_path)
    change(def_dir)
    problems = check.check(def_dir)
    assert any(expected in problem for problem in problems), problems
    assert all("\n" not in problem for problem in problems)


def test_a_deprecated_term_stays_and_a_new_release_may_add_terms(tmp_path: Path) -> None:
    def_dir = _copy(tmp_path, ("1.0.0", "1.1.0-beta.1"))
    shutil.copytree(def_dir / "1000" / "1.1.0-beta.1", def_dir / "1000" / "1.2.0")
    _edit(def_dir, "1.2.0", "1.1.0-beta.1>", "1.2.0>")
    _edit(def_dir, "1.2.0", '"1.1.0-beta.1"', '"1.2.0"')
    _edit(def_dir, "1.2.0", f"owl:priorVersion <{ONTOLOGY}/1.0.0>", f"owl:priorVersion <{ONTOLOGY}/1.1.0-beta.1>")
    _add(def_dir, "1.2.0", MASS_FRACTION)
    assert check.check(def_dir) == []


def test_a_backport_passes(tmp_path: Path) -> None:
    def_dir = _copy(tmp_path)
    _backport(def_dir)
    assert check.check(def_dir) == []
    assert [release.version for release in check.releases(def_dir)] == ["1.0.0", "1.0.1", "1.1.0-beta.1", "1.1.0"]


def test_prior_version_is_optional_and_may_name_any_earlier_release(tmp_path: Path) -> None:
    def_dir = _copy(tmp_path)
    _edit(def_dir, "1.1.0-beta.1", f"    owl:priorVersion <{ONTOLOGY}/1.0.0> ;\n", "")
    _edit(def_dir, "1.1.0", f"owl:priorVersion <{ONTOLOGY}/1.1.0-beta.1>", f"owl:priorVersion <{ONTOLOGY}/1.0.0>")
    assert check.check(def_dir) == []


def test_a_concept_scheme_may_take_its_label_and_definition_from_dcterms(tmp_path: Path) -> None:
    def_dir = _copy(tmp_path)
    _add(
        def_dir,
        "1.1.0",
        '\nex:Conditions a skos:ConceptScheme ;\n    dcterms:title "storage conditions"@en ;\n'
        '    dcterms:description "The conditions a sample is kept in."@en .\n',
    )
    assert check.check(def_dir) == []
    page = site.release_page("1000", "1.1.0", check.read_vocabulary(def_dir / "1000" / "1.1.0" / "vocab.ttl"))
    assert '<h3><a href="#Conditions">storage conditions</a> <span class="bi-badge">concept scheme</span></h3>' in page


def test_an_individual_is_a_term_on_the_page(tmp_path: Path) -> None:
    def_dir = _copy(tmp_path)
    _add(def_dir, "1.1.0", GLOVEBOX)
    assert check.check(def_dir) == []
    page = site.release_page("1000", "1.1.0", check.read_vocabulary(def_dir / "1000" / "1.1.0" / "vocab.ttl"))
    assert '<article class="bi-card term" id="Glovebox">' in page
    assert '<h3><a href="#Glovebox">glovebox</a> <span class="bi-badge">individual</span></h3>' in page


ABOUT = """
<https://w3id.org/battinfo/def/1000>
    dcterms:description "Terms for <storing> samples."@en ;
    dcterms:issued "2026-10-30" ;
    dcterms:publisher [ <http://xmlns.com/foaf/0.1/name> "Example & Co" ;
        <http://xmlns.com/foaf/0.1/homepage> <https://example.org/> ] ;
    <http://www.w3.org/2000/01/rdf-schema#seeAlso> <https://example.org/docs/> .
"""

# A scheme with a top concept given from each side, a narrower concept given
# by skos:broader alone, a cycle, and matches to an EMMO term the domain-battery
# context names (Simulation) and to an IRI it does not.
CONDITIONS = """
ex:Conditions a skos:ConceptScheme ;
    dcterms:title "storage conditions"@en ;
    dcterms:description "The conditions a sample is kept in."@en ;
    skos:hasTopConcept ex:Cold .

ex:Cold a skos:Concept ;
    skos:prefLabel "cold"@en ;
    skos:altLabel "chilled"@en, "kalt"@de ;
    skos:definition "Kept below 5 degrees Celsius."@en ;
    skos:scopeNote "Not <frozen>."@en ;
    skos:relatedMatch <https://w3id.org/emmo#EMMO_9335cf09_431f_4613_9dab_ce4ceaca965b> ;
    skos:closeMatch <https://example.org/cold> .

ex:Frozen a skos:Concept ;
    skos:prefLabel "frozen"@en ;
    skos:definition "Kept below 0 degrees Celsius."@en ;
    skos:broader ex:Cold .

ex:Warm a skos:Concept ;
    skos:prefLabel "warm"@en ;
    skos:definition "Kept above 25 degrees Celsius."@en ;
    skos:topConceptOf ex:Conditions ;
    skos:broader ex:Hot .

ex:Hot a skos:Concept ;
    skos:prefLabel "hot"@en ;
    skos:definition "Kept above 40 degrees Celsius."@en ;
    skos:broader ex:Warm .
"""


def test_a_page_names_the_publisher_and_links_further_documentation(tmp_path: Path) -> None:
    def_dir = _copy(tmp_path)
    _add(def_dir, "1.1.0", ABOUT)
    page = site.release_page("1000", "1.1.0", check.read_vocabulary(def_dir / "1000" / "1.1.0" / "vocab.ttl"))
    assert '<p class="lead">Terms for &lt;storing&gt; samples.</p>' in page
    assert '<meta name="description" content="Terms for &lt;storing&gt; samples.">' in page
    assert '<p class="byline">Published by <a href="https://example.org/">Example &amp; Co</a></p>' in page
    assert "<tr><th>Issued</th><td>2026-10-30</td></tr>" in page
    assert (
        '<tr><th>Documentation</th><td><a href="https://example.org/docs/">https://example.org/docs/</a></td></tr>'
        in page
    )


def test_a_publisher_without_a_name_or_homepage_is_shown_by_what_it_has(tmp_path: Path) -> None:
    def_dir = _copy(tmp_path)
    _add(def_dir, "1.1.0", "\n<https://w3id.org/battinfo/def/1000> dcterms:publisher <https://example.org/lab> .\n")
    page = site.release_page("1000", "1.1.0", check.read_vocabulary(def_dir / "1000" / "1.1.0" / "vocab.ttl"))
    assert 'Published by <a href="https://example.org/lab">https://example.org/lab</a>' in page

    def_dir = _copy(tmp_path / "named")
    _add(
        def_dir,
        "1.1.0",
        '\n<https://w3id.org/battinfo/def/1000> dcterms:publisher [ <http://xmlns.com/foaf/0.1/name> "A lab" ] .\n',
    )
    page = site.release_page("1000", "1.1.0", check.read_vocabulary(def_dir / "1000" / "1.1.0" / "vocab.ttl"))
    assert '<p class="byline">Published by A lab</p>' in page

    # A publisher given as plain text is shown as it is, and a homepage is linked whatever the case of its scheme.
    def_dir = _copy(tmp_path / "literal")
    _add(
        def_dir,
        "1.1.0",
        '\n<https://w3id.org/battinfo/def/1000> dcterms:publisher "Plain Lab"@en, '
        '[ <http://xmlns.com/foaf/0.1/name> "Loud Lab" ; <http://xmlns.com/foaf/0.1/homepage> <HTTPS://LOUD.EXAMPLE/> ] .\n',
    )
    page = site.release_page("1000", "1.1.0", check.read_vocabulary(def_dir / "1000" / "1.1.0" / "vocab.ttl"))
    assert "Published by" in page and "Plain Lab" in page
    assert '<a href="HTTPS://LOUD.EXAMPLE/">Loud Lab</a>' in page


CREATORS = """
<https://w3id.org/battinfo/def/1000> dcterms:creator
    [ <http://xmlns.com/foaf/0.1/name> "Ada <Lab>" ;
      <https://schema.org/affiliation> [ <http://xmlns.com/foaf/0.1/name> "Example University" ],
          <https://ror.org/000000000> ],
    <https://orcid.org/0000-0002-1825-0097> ,
    "Plain Name" .
<https://orcid.org/0000-0002-1825-0097> <http://schema.org/name> "Josiah Carberry" ;
    <http://schema.org/affiliation> <https://ror.org/05gq02987>, "Wesleyan University" .
<https://ror.org/05gq02987> <http://xmlns.com/foaf/0.1/name> "Brown University" .
"""


def test_a_page_lists_the_creators_with_their_affiliations(tmp_path: Path) -> None:
    def_dir = _copy(tmp_path)
    _add(def_dir, "1.1.0", CREATORS)
    vocabulary = check.read_vocabulary(def_dir / "1000" / "1.1.0" / "vocab.ttl")
    assert vocabulary.creators == (
        ("Ada <Lab>", (("Example University", ""), ("https://ror.org/000000000", "https://ror.org/000000000")), ""),
        (
            "Josiah Carberry",
            (("Brown University", "https://ror.org/05gq02987"), ("Wesleyan University", "")),
            "https://orcid.org/0000-0002-1825-0097",
        ),
        ("Plain Name", (), ""),
    )
    page = site.release_page("1000", "1.1.0", vocabulary)
    assert (
        "<tr><th>Creators</th><td><ul>\n<li>Ada &lt;Lab&gt;, Example University, "
        '<a href="https://ror.org/000000000">https://ror.org/000000000</a></li>\n'
        '<li><a href="https://orcid.org/0000-0002-1825-0097">Josiah Carberry</a>, '
        '<a href="https://ror.org/05gq02987">Brown University</a>, Wesleyan University</li>\n'
        "<li>Plain Name</li>\n</ul></td></tr>" in page
    )


def test_the_battery_data_commons_release_1_0_1_names_its_creators(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert site.build(out) == []
    page = (out / "def" / "1002" / "1.0.1" / "index.html").read_text(encoding="utf-8")
    for orcid, person, ror, affiliation in (
        ("0000-0003-4713-5220", "Marwan Hassini", "03x42jk29", "Université Gustave Eiffel"),
        ("0000-0003-3041-1436", "Philipp Dechent", "035vnjr65", "Toshiba Europe GmbH"),
        ("0000-0002-5900-1409", "Sara Luciani", "035vnjr65", "Toshiba Europe GmbH"),
        ("0000-0003-4447-9319", "Shiyun Liu", "024mrxd33", "University of Leeds"),
        ("0000-0002-8758-6109", "Simon Clark", "01f677e56", "SINTEF AS"),
        ("0000-0001-8834-9458", "Paul Gasper", "036266993", "National Lab of the Rockies"),
        ("0000-0002-4993-2672", "Gonçalo dos Reis", "01nrxwf90", "University of Edinburgh"),
    ):
        assert (
            f'<li><a href="https://orcid.org/{orcid}">{person}</a>, '
            f'<a href="https://ror.org/{ror}">{affiliation}</a></li>' in page
        )
    assert (
        '<tr><th>Previous release</th><td><a href="https://w3id.org/battinfo/def/1002/1.0.0">1.0.0</a></td></tr>'
        in page
    )
    # The ontology IRI serves the newest release.
    assert (out / "def" / "1002" / "index.html").read_bytes() == (
        out / "def" / "1002" / "1.0.1" / "index.html"
    ).read_bytes()


def test_a_page_outlines_each_concept_scheme_and_links_the_hierarchy_both_ways(tmp_path: Path) -> None:
    def_dir = _copy(tmp_path)
    _add(def_dir, "1.1.0", CONDITIONS)
    page = site.release_page("1000", "1.1.0", check.read_vocabulary(def_dir / "1000" / "1.1.0" / "vocab.ttl"))

    outline = page[page.index('<h2 id="schemes">') : page.index('<h2 id="terms">')]
    assert outline == (
        '<h2 id="schemes">Concept schemes</h2>\n'
        '<div class="bi-card tree">\n'
        '<p><strong><a href="#Conditions">storage conditions</a></strong></p>\n'
        "<ul>\n"
        '<li><a href="#Cold">cold</a><ul><li><a href="#Frozen">frozen</a></li></ul></li>\n'
        '<li><a href="#Warm">warm</a><ul><li><a href="#Hot">hot</a></li></ul></li>\n'
        "</ul>\n"
        "</div>\n"
    )
    # skos:broader on Frozen alone makes it narrower of Cold, and the reverse.
    assert '<tr><th>Narrower</th><td><a href="#Frozen">frozen</a></td></tr>' in page
    assert '<tr><th>Broader</th><td><a href="#Cold">cold</a></td></tr>' in page
    assert "<tr><th>Note</th><td>Not &lt;frozen&gt;.</td></tr>" in page
    assert "<tr><th>Also called</th><td>chilled</td></tr>" in page and "kalt" not in page
    assert (
        '<tr><th>Related match</th><td><a href="https://w3id.org/emmo#EMMO_9335cf09_431f_4613_9dab_ce4ceaca965b">'
        "Simulation</a></td></tr>" in page
    )
    assert (
        '<tr><th>Close match</th><td><a href="https://example.org/cold">https://example.org/cold</a></td></tr>' in page
    )


def test_a_page_without_a_concept_scheme_has_no_outline(tmp_path: Path) -> None:
    def_dir = _copy(tmp_path)
    page = site.release_page("1000", "1.1.0", check.read_vocabulary(def_dir / "1000" / "1.1.0" / "vocab.ttl"))
    assert "Concept schemes" not in page and "Published by" not in page and "Documentation" not in page


def test_the_battery_data_commons_page_documents_its_dataset_kinds(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert site.build(out) == []
    page = (out / "def" / "1002" / "1.0.0" / "index.html").read_text(encoding="utf-8")
    assert 'Published by <a href="https://batterydatacommons.org/">Battery Data Commons</a>' in page
    assert (
        '<li><a href="#ModelingData">Modelling data</a><ul><li><a href="#SyntheticData">Synthetic data</a></li></ul></li>'
        in page
    )
    assert ">ReferencePerformanceTest</a>" in page and ">CyclingTest</a>" in page and ">ThermalRunawayTest</a>" in page
    assert "<tr><th>Also called</th><td>performance</td></tr>" in page


def test_the_pages_carry_the_battinfo_style_and_stand_alone(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert site.build(out, FIXTURE) == []
    tokens = (ROOT / "brand" / "tokens.css").read_text(encoding="utf-8").strip()
    for path in ("def/1000/1.1.0/index.html", "def/index.html"):
        page = (out / path).read_text(encoding="utf-8")
        # The design tokens and both symbols are in the page, so it needs nothing else from the site.
        assert tokens in page
        assert '<span class="mark-light" aria-hidden="true"><svg' in page
        assert '<span class="mark-dark" aria-hidden="true"><svg' in page
        assert '<html lang="en" data-theme="light">' in page
        assert "localStorage.getItem('mode')" in page and "prefers-color-scheme: dark" in page
        assert "Hosted in the BattINFO namespace" in page
    release = (out / "def" / "1000" / "1.1.0" / "index.html").read_text(encoding="utf-8")
    assert (
        'Source: <a href="https://github.com/BIG-MAP/BattINFO/blob/main/def/1000/1.1.0/vocab.ttl">'
        "def/1000/1.1.0/vocab.ttl</a>" in release
    )
    assert '<a href="https://big-map.github.io/BattINFO/def/">Publisher vocabularies</a>' in release


def test_the_page_rules_use_the_semantic_tokens_only() -> None:
    # brand/AGENTS.md rule 1: no literal colours and no --raw-* primitives.
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgba?\(|--raw-", site._STYLE)
    assert "var(--bi-" in site._STYLE


def test_a_page_is_still_written_without_the_brand_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(site, "BRAND", tmp_path / "no-brand")
    monkeypatch.setattr(site, "_brand", None)
    page = site.release_page("1000", "1.1.0", check.read_vocabulary(FIXTURE / "1000" / "1.1.0" / "vocab.ttl"))
    assert "<svg" not in page and "<h1>Example vocabulary</h1>" in page


def test_a_licence_given_as_text_beside_an_iri_passes(tmp_path: Path) -> None:
    def_dir = _copy(tmp_path)
    _edit(
        def_dir,
        "1.1.0",
        "dcterms:license <https://creativecommons.org/licenses/by/4.0/>",
        'dcterms:license <https://creativecommons.org/licenses/by/4.0/>, "CC BY 4.0"',
    )
    assert check.check(def_dir) == []


def test_a_failing_check_prints_one_line_per_problem_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def_dir = _copy(tmp_path)
    _edit(def_dir, "1.1.0", HAS_HOLDER, "")
    _write(def_dir, "1000/1.0.0/notes.md")

    assert check.main([], root=tmp_path) == 1
    lines = capsys.readouterr().err.splitlines()
    assert lines == [
        "def/1000/1.0.0/notes.md: a release folder holds vocab.ttl only",
        "def/1000/1.1.0/vocab.ttl: drops hasHolder, which release 1.0.0 has; a term is never removed, it is "
        "marked owl:deprecated true",
    ]


def test_a_passing_check_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _copy(tmp_path)
    assert check.main([], root=tmp_path) == 0
    assert capsys.readouterr().out == "def/: 3 release(s) pass the checks.\n"


# --unchanged-since, against a scratch repository whose commit "base" holds two releases.


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", "-c", "init.defaultBranch=main", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository whose commit tagged base holds the releases 1.0.0 and 1.1.0-beta.1, without the user's git configuration."""
    if shutil.which("git") is None:
        pytest.skip("needs git")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    _copy(tmp_path, ("1.0.0", "1.1.0-beta.1"))
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "tag", "base")
    return tmp_path


def _commit(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change")


def test_new_releases_and_files_outside_releases_may_be_added(repo: Path) -> None:
    shutil.copytree(FIXTURE / "1000" / "1.1.0", repo / "def" / "1000" / "1.1.0")
    _write(repo / "def", "README.md", "# def\n")
    _commit(repo)
    assert check.changed_releases("base", repo) == []
    assert check.main(["--unchanged-since", "base"], root=repo) == 0


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            lambda d: _add(d, "1.0.0", "# a comment\n"),
            "def/1000/1.0.0/vocab.ttl: modified since base; a release never changes once merged, so make the "
            "change in a new release",
        ),
        (lambda d: (d / "1000" / "1.0.0" / "vocab.ttl").unlink(), "def/1000/1.0.0/vocab.ttl: deleted since base"),
        (
            lambda d: (d / "1000" / "1.0.0").rename(d / "1000" / "1.0.1"),
            "def/1000/1.0.0/vocab.ttl: renamed to def/1000/1.0.1/vocab.ttl since base",
        ),
        (
            lambda d: _write(d, "1000/1.1.0-beta.1/extra.ttl"),
            "def/1000/1.1.0-beta.1/extra.ttl: added to the release def/1000/1.1.0-beta.1/ since base",
        ),
    ],
    ids=["modified", "deleted", "renamed", "added to a release"],
)
def test_a_release_that_base_holds_never_changes(repo: Path, change: Callable[[Path], None], expected: str) -> None:
    change(repo / "def")
    _commit(repo)
    assert any(expected in problem for problem in check.changed_releases("base", repo)), check.changed_releases(
        "base", repo
    )
    assert check.main(["--unchanged-since", "base"], root=repo) == 1


def test_an_uncommitted_change_counts_too(repo: Path) -> None:
    _add(repo / "def", "1.0.0", "# a comment\n")
    assert check.changed_releases("base", repo) == [
        "def/1000/1.0.0/vocab.ttl: modified since base; a release never changes once merged, so make the change "
        "in a new release"
    ]


def test_a_missing_ref_is_an_error(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(ValueError, match="no-such-ref is not a commit of this repository"):
        check.changed_releases("no-such-ref", repo)
    assert check.main(["--unchanged-since", "no-such-ref"], root=repo) == 2
    err = capsys.readouterr().err
    assert err.startswith("check_def_vocabularies.py: --unchanged-since: no-such-ref is not a commit"), err


def test_ci_checks_each_pull_request_against_its_base() -> None:
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    jobs = [
        (job, step)
        for job in ci["jobs"].values()
        for step in job["steps"]
        if "check_def_vocabularies.py --unchanged-since" in step.get("run", "")
    ]
    assert len(jobs) == 1
    job, step = jobs[0]
    assert step["if"].startswith("github.event_name == 'pull_request'")
    assert step["env"]["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert '--unchanged-since "$BASE_SHA"' in step["run"]
    # The base commit is in the clone only with the full history.
    (checkout,) = [s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert checkout["with"]["fetch-depth"] == 0


# The site build.


def test_the_site_build_lays_out_each_release_and_serves_the_newest_final_one(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert site.build(out, FIXTURE) == []

    for version in ("1.0.0", "1.1.0-beta.1", "1.1.0"):
        folder = out / "def" / "1000" / version
        assert (folder / "vocab.ttl").read_bytes() == (FIXTURE / "1000" / version / "vocab.ttl").read_bytes()
        page = (folder / "index.html").read_text(encoding="utf-8")
        assert "<h1>Example vocabulary</h1>" in page
        assert f"<tr><th>Version IRI</th><td><code>{ONTOLOGY}/{version}</code></td></tr>" in page
        assert '<a href="https://creativecommons.org/licenses/by/4.0/">' in page
        assert '<a href="vocab.ttl">vocab.ttl</a>' in page
        assert 'href="https://big-map.github.io/BattINFO/def/#1000"' in page
        assert '<h3><a href="#Sample">sample</a> <span class="bi-badge">class</span></h3>' in page
    beta = (out / "def" / "1000" / "1.1.0-beta.1" / "index.html").read_text(encoding="utf-8")
    assert f'<tr><th>Previous release</th><td><a href="{ONTOLOGY}/1.0.0">1.0.0</a></td></tr>' in beta
    assert (
        '<h3><a href="#OldName">old name</a> <span class="bi-badge">class</span> '
        '<span class="bi-badge deprecated">deprecated</span></h3>' in beta
    )
    assert '<tr><th>Replaced by</th><td><a href="#NewName">new name</a></td></tr>' in beta
    assert '<h3><a href="#Dry">dry</a> <span class="bi-badge">concept</span></h3>' in beta
    assert "Previous release" not in (out / "def" / "1000" / "1.0.0" / "index.html").read_text(encoding="utf-8")

    # The vocabulary's own address serves the newest final release, not the pre-release.
    assert (out / "def" / "1000" / "vocab.ttl").read_bytes() == (FIXTURE / "1000" / "1.1.0" / "vocab.ttl").read_bytes()
    assert (out / "def" / "1000" / "index.html").read_bytes() == (
        out / "def" / "1000" / "1.1.0" / "index.html"
    ).read_bytes()
    index = (out / "def" / "index.html").read_text(encoding="utf-8")
    assert '<h2 id="1000">Example vocabulary</h2>' in index
    assert "<tr><th>Prefix</th><td>1000, BattINFO</td></tr>" in index
    assert re.findall(r'<li><a href="1000/([^/]+)/">', index) == ["1.1.0", "1.1.0-beta.1", "1.0.0"]
    assert '<a href="1000/1.1.0/">1.1.0</a>, served at the ontology IRI' in index


def test_a_pre_release_is_not_served_while_a_final_release_exists(tmp_path: Path) -> None:
    def_dir = _copy(tmp_path, ("1.0.0", "1.1.0-beta.1"))
    out = tmp_path / "out"
    assert site.build(out, def_dir) == []
    assert (out / "def" / "1000" / "vocab.ttl").read_bytes() == (def_dir / "1000" / "1.0.0" / "vocab.ttl").read_bytes()


def test_the_pages_escape_what_the_vocabulary_says(tmp_path: Path) -> None:
    def_dir = _copy(tmp_path)
    _edit(def_dir, "1.1.0", '"Example vocabulary"@en', '"Example <i>vocabulary</i> & co"@en')
    _edit(def_dir, "1.1.0", '"mass fraction"@en', '"mass \\"fraction\\" <b>"@en')
    _edit(def_dir, "1.1.0", '"The mass of a component', '"<script>alert(1)</script> The mass of a component')
    _edit(
        def_dir,
        "1.1.0",
        "dcterms:license <https://creativecommons.org/licenses/by/4.0/>",
        "dcterms:license <javascript:alert(1)>",
    )
    out = tmp_path / "out"
    assert site.build(out, def_dir) == []

    page = (out / "def" / "1000" / "1.1.0" / "index.html").read_text(encoding="utf-8")
    assert "<h1>Example &lt;i&gt;vocabulary&lt;/i&gt; &amp; co</h1>" in page
    assert "mass &quot;fraction&quot; &lt;b&gt;" in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    # The one script is the page's own theme switch; nothing the vocabulary says becomes markup.
    assert page.count("<script") == 1 and "<script>alert" not in page and "<b>" not in page
    assert 'href="javascript' not in page and "<code>javascript:alert(1)</code>" in page
    # def/index.html reads the title back from the page, and escapes it again.
    assert '<h2 id="1000">Example &lt;i&gt;vocabulary&lt;/i&gt; &amp; co</h2>' in (
        out / "def" / "index.html"
    ).read_text(encoding="utf-8")


def test_the_site_build_refuses_a_def_folder_that_fails_its_checks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def_dir = _copy(tmp_path)
    _edit(def_dir, "1.1.0", HAS_HOLDER, "")
    out = tmp_path / "out"

    assert site.main([str(out)], def_dir=def_dir) == 1
    assert "drops hasHolder" in capsys.readouterr().err
    assert not (out / "def").exists()


def test_the_site_build_of_an_empty_def_folder_writes_only_the_index(tmp_path: Path) -> None:
    def_dir = tmp_path / "def"
    _write(def_dir, "README.md", "# def\n")
    out = tmp_path / "out"
    assert site.main([str(out)], def_dir=def_dir) == 0
    assert [path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file()] == ["def/index.html"]
    assert "No vocabulary is published yet." in (out / "def" / "index.html").read_text(encoding="utf-8")
