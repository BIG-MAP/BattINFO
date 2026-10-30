"""Check the publishers' vocabularies under def/ against the rules in def/README.md.

A publisher defines terms under https://w3id.org/battinfo/def/{prefix}/, where
{prefix} is its number in ``src/battinfo/data/namespace/prefixes.json``. Each
release of its vocabulary is one Turtle file, ``def/{prefix}/{X.Y.Z}/vocab.ttl``,
which ``scripts/build_def_site.py`` lays out for GitHub Pages. For every release
this checks:

* that the prefix is allocated in the register, and that the release folder is
  named X.Y.Z or a pre-release such as 1.3.0-beta.1 and holds vocab.ttl only;
* that the file parses as Turtle and declares one owl:Ontology,
  https://w3id.org/battinfo/def/{prefix}, with the owl:versionIRI
  .../def/{prefix}/{X.Y.Z}, the owl:versionInfo "X.Y.Z", a dcterms:title and a
  dcterms:license that is an IRI;
* that each owl:priorVersion, which is optional, names the version IRI of a
  release under def/{prefix}/ that sorts lower. Releases sort by version, a
  pre-release before its final;
* that every subject under https://w3id.org/battinfo/ lies under
  def/{prefix}/, with a local name that starts with a letter and holds only
  letters, digits and underscores, and that a dcterms:isReplacedBy there
  names a subject of the same release;
* that every term (a subject there typed as an OWL class, property or
  individual, an RDF property, or a SKOS concept or concept scheme) has an
  English rdfs:label or skos:prefLabel, and a skos:definition or rdfs:comment.
  A concept scheme may use dcterms:title and dcterms:description instead;
* that every subject under def/{prefix}/ of a release is in each release that
  sorts above it, and stays owl:deprecated once it is: a term is deprecated,
  never removed. A term that only a backport (a patch release of an older
  line) adds is reported on the backport.

A release never changes once it is merged. With ``--unchanged-since REF`` the
script also fails when a file under def/{prefix}/{X.Y.Z}/ at REF is modified,
deleted or renamed in the working tree, or a file is added to such a folder.
``.github/workflows/ci.yml`` runs that on each pull request against its base,
and ``tests/test_def_vocabularies.py`` runs the other checks on def/ and on
fixtures.

Usage::

    python scripts/check_def_vocabularies.py [--unchanged-since REF]

The exit status is 0 when every check passes, 1 when one fails, with one line
per problem, and 2 when REF is not a commit of the repository.

``build_def_site.py --merge`` imports this module in the docs deploy job, which
has neither rdflib nor battinfo, so both are imported only where they are used.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEF_DIR = ROOT / "def"
#: The root of the battinfo w3id name (``battinfo.namespace.BATTINFO_ROOT``).
BATTINFO_ROOT = "https://w3id.org/battinfo/"
#: The branch of publishers' definitions: a vocabulary's IRI is DEF_BASE + prefix.
DEF_BASE = BATTINFO_ROOT + "def/"
#: A publisher prefix (``battinfo.namespace.PREFIX_PATTERN``).
PREFIX_RE = re.compile(r"[1-9][0-9]{3,}")
# A version, as in an ontology release's versionIRI that docs-deploy.sh reads:
# X.Y.Z, then an optional pre-release such as -beta.1. It is semantic
# versioning without build metadata or leading zeros, so no two folder names
# are one version and any two have an order.
_NUMBER = r"(?:0|[1-9][0-9]*)"
_PRE_RELEASE_PART = r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
VERSION_RE = re.compile(rf"{_NUMBER}\.{_NUMBER}\.{_NUMBER}(?:-{_PRE_RELEASE_PART}(?:\.{_PRE_RELEASE_PART})*)?")
#: The local name of a term: the part of its IRI after def/{prefix}/.
TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
#: The one file of a release folder.
VOCABULARY_FILE = "vocab.ttl"

_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_OWL = "http://www.w3.org/2002/07/owl#"
_SKOS = "http://www.w3.org/2004/02/skos/core#"
_DCTERMS = "http://purl.org/dc/terms/"
_FOAF = "http://xmlns.com/foaf/0.1/"
#: schema.org, under both of the namespace IRIs that vocabularies use for it.
_SCHEMA = ("https://schema.org/", "http://schema.org/")
#: The SKOS mapping properties, with the words a page uses for each.
MATCHES = {
    _SKOS + "exactMatch": "Exact match",
    _SKOS + "closeMatch": "Close match",
    _SKOS + "broadMatch": "Broad match",
    _SKOS + "narrowMatch": "Narrow match",
    _SKOS + "relatedMatch": "Related match",
}
#: The types that make a subject a term, with the word a page uses for each.
TERM_TYPES = {
    _OWL + "Class": "class",
    _OWL + "ObjectProperty": "object property",
    _OWL + "DatatypeProperty": "datatype property",
    _OWL + "AnnotationProperty": "annotation property",
    _OWL + "NamedIndividual": "individual",
    _RDF + "Property": "property",
    _SKOS + "Concept": "concept",
    _SKOS + "ConceptScheme": "concept scheme",
}
_FIX = "a release never changes once merged, so make the change in a new release"


@dataclass(frozen=True)
class Release:
    """The release *version* of the vocabulary of *prefix*, in the file *path*."""

    prefix: str
    version: str
    path: Path


@dataclass(frozen=True)
class Term:
    """A subject typed as a term.

    *labels* holds its English rdfs:label and skos:prefLabel values, and
    *definitions* its skos:definition and rdfs:comment values, the preferred
    first: skos before rdfs, English before other languages. A concept
    scheme's English dcterms:title counts as a label, and its
    dcterms:description as a definition.

    The site build alone reads the rest: *alt_labels* and *scope_notes*
    (skos:altLabel, skos:scopeNote); *broader*, *narrower*, *in_scheme* and
    *top_concepts*, each read from either side, so that skos:broader on one
    concept is skos:narrower on the other and skos:topConceptOf on a concept
    is skos:hasTopConcept on its scheme; *matches*, each (mapping property,
    IRI) pair of the SKOS mapping properties; and *see_also* (rdfs:seeAlso).
    """

    iri: str
    kinds: tuple[str, ...]
    labels: tuple[str, ...]
    definitions: tuple[str, ...]
    deprecated: bool
    replaced_by: tuple[str, ...]
    alt_labels: tuple[str, ...] = ()
    scope_notes: tuple[str, ...] = ()
    broader: tuple[str, ...] = ()
    narrower: tuple[str, ...] = ()
    in_scheme: tuple[str, ...] = ()
    top_concepts: tuple[str, ...] = ()
    matches: tuple[tuple[str, str], ...] = ()
    see_also: tuple[str, ...] = ()


@dataclass(frozen=True)
class Vocabulary:
    """What the checks and the site build read from one vocab.ttl.

    *ontologies* holds every subject typed owl:Ontology (``_:`` and an id for
    a blank node). The other ontology fields are read from that subject when
    there is exactly one, and are empty otherwise. *subjects* holds every
    subject that is an IRI, *deprecated* those marked owl:deprecated true,
    *replacements* each (subject, dcterms:isReplacedBy IRI) pair, and *terms*
    the subjects typed as terms.

    The site build alone reads *descriptions* (the ontology's
    dcterms:description), *issued* (its dcterms:issued), *publishers* (each
    dcterms:publisher as a (name, homepage) pair, from foaf:name or
    rdfs:label and foaf:homepage, the homepage empty when there is none) and
    *pages* (its rdfs:seeAlso and foaf:page), and *creators* (each
    dcterms:creator as a (name, affiliation, IRI) triple, the name from
    foaf:name, schema:name or rdfs:label, the affiliation from the name of
    each schema:affiliation, the IRI empty for a blank node or a name given
    as text).
    """

    ontologies: tuple[str, ...]
    version_iris: tuple[str, ...]
    version_infos: tuple[str, ...]
    titles: tuple[str, ...]
    licences: tuple[str, ...]
    licence_literals: tuple[str, ...]
    prior_versions: tuple[str, ...]
    subjects: frozenset[str]
    deprecated: frozenset[str]
    replacements: tuple[tuple[str, str], ...]
    terms: tuple[Term, ...]
    descriptions: tuple[str, ...] = ()
    issued: tuple[str, ...] = ()
    publishers: tuple[tuple[str, str], ...] = ()
    pages: tuple[str, ...] = ()
    creators: tuple[tuple[str, str, str], ...] = ()


def release_key(version: str) -> tuple[tuple[int, ...], int, tuple[tuple[int, int, str], ...]]:
    """Sort key of a version: semantic-versioning precedence, a pre-release before its final release."""
    core, _, pre_release = version.partition("-")
    numbers = tuple(int(part) for part in core.split("."))
    if not pre_release:
        return numbers, 1, ()
    parts = tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in pre_release.split("."))
    return numbers, 0, parts


def newest_release(versions: Iterable[str]) -> str:
    """The release a vocabulary's own IRI serves: the newest final one, or the newest pre-release if none is final."""
    versions = list(versions)
    finals = [version for version in versions if "-" not in version]
    return max(finals or versions, key=release_key)


def _shown(path: Path, def_dir: Path) -> str:
    return path.relative_to(def_dir.parent).as_posix()


def _walk(def_dir: Path) -> tuple[list[Release], list[str]]:
    """The releases under *def_dir*, by prefix and in version order, and every way its layout is wrong."""
    found: list[Release] = []
    problems: list[str] = []
    if not def_dir.is_dir():
        return found, problems
    for prefix_dir in sorted(def_dir.iterdir()):
        if prefix_dir.name == "README.md" and prefix_dir.is_file():
            continue
        if not prefix_dir.is_dir():
            problems.append(f"{_shown(prefix_dir, def_dir)}: def/ holds README.md and one folder per prefix only")
            continue
        in_prefix = []
        for release_dir in sorted(prefix_dir.iterdir()):
            where = _shown(release_dir, def_dir)
            if not release_dir.is_dir() or not VERSION_RE.fullmatch(release_dir.name):
                problems.append(
                    f"{where}: not a release folder, which is named X.Y.Z or a pre-release such as 1.3.0-beta.1"
                )
                continue
            for entry in sorted(release_dir.iterdir()):
                if entry.name != VOCABULARY_FILE:
                    problems.append(f"{_shown(entry, def_dir)}: a release folder holds {VOCABULARY_FILE} only")
            if (release_dir / VOCABULARY_FILE).is_file():
                in_prefix.append(Release(prefix_dir.name, release_dir.name, release_dir / VOCABULARY_FILE))
            else:
                problems.append(f"{where}: has no {VOCABULARY_FILE}")
        found += sorted(in_prefix, key=lambda release: release_key(release.version))
    return found, problems


def releases(def_dir: Path = DEF_DIR) -> list[Release]:
    """The releases under *def_dir*, by prefix and in version order."""
    return _walk(def_dir)[0]


def _parse_error(exc: Exception) -> str:
    """rdflib's parser error on one line: where, and why."""
    text = str(exc)
    line = re.search(r"at line (\d+)", text)
    why = re.search(r"Bad syntax \((.*?)\) at \^", text, re.S)
    if why:
        return f"line {line[1]}: {why[1]}" if line else why[1]
    return " ".join(text.split())[:200] or type(exc).__name__


def read_vocabulary(path: Path) -> Vocabulary:
    """The parts of the Turtle file *path* that the checks and the site build read.

    Raises ``ValueError`` when the file does not parse.
    """
    from rdflib import BNode, Graph, Literal, URIRef

    graph = Graph()
    try:
        graph.parse(path, format="turtle")
    except Exception as exc:  # the parser raises several kinds of error
        raise ValueError(_parse_error(exc)) from exc

    def english(value: Any) -> bool:
        language = (value.language or "").lower()
        return language == "en" or language.startswith("en-")

    def texts(subject: Any, *predicates: str, english_only: bool = False) -> tuple[str, ...]:
        """The non-empty literal values of *predicates*, in that order, English before other languages."""
        found: list[str] = []
        for predicate in predicates:
            values = [v for v in graph.objects(subject, URIRef(predicate)) if isinstance(v, Literal) and str(v).strip()]
            found += sorted(str(v) for v in values if english(v))
            if not english_only:
                found += sorted(str(v) for v in values if not english(v))
        return tuple(dict.fromkeys(found))

    def iris(subject: Any, predicate: str) -> tuple[str, ...]:
        return tuple(sorted(str(v) for v in graph.objects(subject, URIRef(predicate)) if isinstance(v, URIRef)))

    def related(subject: Any, predicate: str, inverse: str) -> tuple[str, ...]:
        """The IRIs *subject* reaches by *predicate*, and those that reach it by *inverse*."""
        found = {*iris(subject, predicate)}
        found.update(str(s) for s in graph.subjects(URIRef(inverse), subject) if isinstance(s, URIRef))
        return tuple(sorted(found))

    def publisher(node: Any) -> tuple[str, str]:
        """(name, homepage) of the publisher *node*; an IRI stands for both when they are not given."""
        if isinstance(node, Literal):
            return (str(node).strip(), "")
        names = texts(node, _FOAF + "name", _RDFS + "label")
        homepages = iris(node, _FOAF + "homepage")
        fallback = str(node) if isinstance(node, URIRef) else ""
        return (names[0] if names else fallback, homepages[0] if homepages else fallback)

    def creator(node: Any) -> tuple[str, str, str]:
        """(name, affiliation, IRI) of the creator *node*; an IRI stands for the name when none is given."""
        if isinstance(node, Literal):
            return (str(node).strip(), "", "")
        name_predicates = (_FOAF + "name", *(space + "name" for space in _SCHEMA), _RDFS + "label")
        affiliations: list[str] = []
        for space in _SCHEMA:
            for organisation in graph.objects(node, URIRef(space + "affiliation")):
                if isinstance(organisation, Literal):
                    affiliations.append(str(organisation).strip())
                else:
                    affiliations += texts(organisation, *name_predicates)[:1]
        names = texts(node, *name_predicates)
        iri = str(node) if isinstance(node, URIRef) else ""
        return (names[0] if names else iri, ", ".join(sorted({a for a in affiliations if a})), iri)

    ontologies = sorted(set(graph.subjects(URIRef(_RDF + "type"), URIRef(_OWL + "Ontology"))), key=str)
    fields: dict[str, tuple[str, ...]] = {
        "version_iris": (),
        "version_infos": (),
        "titles": (),
        "licences": (),
        "licence_literals": (),
        "prior_versions": (),
        "descriptions": (),
        "issued": (),
        "pages": (),
    }
    publishers: tuple[tuple[str, str], ...] = ()
    creators: tuple[tuple[str, str, str], ...] = ()
    if len(ontologies) == 1:
        ontology = ontologies[0]
        licences = list(graph.objects(ontology, URIRef(_DCTERMS + "license")))
        fields.update(
            version_iris=iris(ontology, _OWL + "versionIRI"),
            version_infos=tuple(sorted(str(v) for v in graph.objects(ontology, URIRef(_OWL + "versionInfo")))),
            titles=texts(ontology, _DCTERMS + "title"),
            licences=tuple(sorted(str(v) for v in licences if isinstance(v, URIRef))),
            licence_literals=tuple(sorted(str(v) for v in licences if not isinstance(v, URIRef))),
            prior_versions=iris(ontology, _OWL + "priorVersion"),
            descriptions=texts(ontology, _DCTERMS + "description"),
            issued=tuple(sorted(str(v) for v in graph.objects(ontology, URIRef(_DCTERMS + "issued")))),
            pages=tuple(sorted({*iris(ontology, _RDFS + "seeAlso"), *iris(ontology, _FOAF + "page")})),
        )
        named = (publisher(node) for node in graph.objects(ontology, URIRef(_DCTERMS + "publisher")))
        publishers = tuple(sorted(found for found in named if found[0]))
        people = (creator(node) for node in graph.objects(ontology, URIRef(_DCTERMS + "creator")))
        creators = tuple(sorted(found for found in people if found[0]))

    subjects = sorted({subject for subject in graph.subjects() if isinstance(subject, URIRef)}, key=str)
    deprecated = {
        str(subject)
        for subject in subjects
        if any(
            isinstance(value, Literal) and (value.toPython() is True or str(value).strip().lower() == "true")
            for value in graph.objects(subject, URIRef(_OWL + "deprecated"))
        )
    }
    terms = []
    for subject in subjects:
        types = {str(value) for value in graph.objects(subject, URIRef(_RDF + "type"))}
        kinds = tuple(word for type_iri, word in TERM_TYPES.items() if type_iri in types)
        if not kinds:
            continue
        scheme = _SKOS + "ConceptScheme" in types
        terms.append(
            Term(
                iri=str(subject),
                kinds=kinds,
                labels=texts(
                    subject,
                    _SKOS + "prefLabel",
                    _RDFS + "label",
                    *([_DCTERMS + "title"] if scheme else []),
                    english_only=True,
                ),
                definitions=texts(
                    subject,
                    _SKOS + "definition",
                    _RDFS + "comment",
                    *([_DCTERMS + "description"] if scheme else []),
                ),
                deprecated=str(subject) in deprecated,
                replaced_by=iris(subject, _DCTERMS + "isReplacedBy"),
                alt_labels=texts(subject, _SKOS + "altLabel", english_only=True),
                scope_notes=texts(subject, _SKOS + "scopeNote"),
                broader=related(subject, _SKOS + "broader", _SKOS + "narrower"),
                narrower=related(subject, _SKOS + "narrower", _SKOS + "broader"),
                in_scheme=related(subject, _SKOS + "inScheme", _SKOS + "hasTopConcept"),
                top_concepts=related(subject, _SKOS + "hasTopConcept", _SKOS + "topConceptOf"),
                matches=tuple((predicate, iri) for predicate in MATCHES for iri in iris(subject, predicate)),
                see_also=iris(subject, _RDFS + "seeAlso"),
            )
        )
    return Vocabulary(
        ontologies=tuple(f"_:{node}" if isinstance(node, BNode) else str(node) for node in ontologies),
        subjects=frozenset(str(subject) for subject in subjects),
        deprecated=frozenset(deprecated),
        replacements=tuple(
            (str(subject), target) for subject in subjects for target in iris(subject, _DCTERMS + "isReplacedBy")
        ),
        terms=tuple(terms),
        publishers=publishers,
        creators=creators,
        **fields,
    )


def own_terms(vocabulary: Vocabulary, prefix: str) -> dict[str, Term]:
    """The terms *vocabulary* defines under def/{prefix}/, keyed by local name."""
    space = f"{DEF_BASE}{prefix}/"
    return {term.iri[len(space) :]: term for term in vocabulary.terms if term.iri.startswith(space)}


def _own_names(iris: Iterable[str], prefix: str) -> set[str]:
    """The local names of *iris* under def/{prefix}/, leaving out version IRIs, which are not terms."""
    space = f"{DEF_BASE}{prefix}/"
    return {iri[len(space) :] for iri in iris if iri.startswith(space) and not VERSION_RE.fullmatch(iri[len(space) :])}


def _is_backport(version: str, later: str) -> bool:
    """Whether *version* reads as a backport beside *later*: a patch release of an older X.Y line."""
    major, minor, patch = release_key(version)[0]
    return patch > 0 and (major, minor) < release_key(later)[0][:2]


def _check_release(release: Release, vocabulary: Vocabulary, where: str) -> list[str]:
    """Every way one release breaks the rules that need no other release."""
    ontology = DEF_BASE + release.prefix
    version_iri = f"{ontology}/{release.version}"
    problems = []
    if vocabulary.ontologies != (ontology,):
        found = ", ".join(f"<{iri}>" for iri in vocabulary.ontologies) or "none"
        problems.append(f"{where}: declares the owl:Ontology {found}; it must declare exactly one, <{ontology}>")
    else:
        if vocabulary.version_iris != (version_iri,):
            found = ", ".join(f"<{iri}>" for iri in vocabulary.version_iris) or "none"
            problems.append(f"{where}: owl:versionIRI is {found}, not <{version_iri}>")
        if vocabulary.version_infos != (release.version,):
            found = ", ".join(f'"{info}"' for info in vocabulary.version_infos) or "none"
            problems.append(f'{where}: owl:versionInfo is {found}, not "{release.version}"')
        if not vocabulary.titles:
            problems.append(f"{where}: the ontology has no dcterms:title")
        if not vocabulary.licences:
            problems.append(f"{where}: the ontology has no dcterms:license that is an IRI, such as a licence's URL")
    space = ontology + "/"
    for subject in sorted(vocabulary.subjects):
        if not subject.startswith(BATTINFO_ROOT) or subject in (ontology, version_iri):
            continue
        if not subject.startswith(space):
            problems.append(f"{where}: <{subject}> lies outside the vocabulary's own space, {space}")
        elif not TERM_RE.fullmatch(subject[len(space) :]):
            problems.append(
                f"{where}: <{subject}>: a local name starts with a letter and holds only letters, digits and _"
            )
    for subject, target in vocabulary.replacements:
        if target.startswith(space) and target not in vocabulary.subjects:
            problems.append(f"{where}: <{subject}> dcterms:isReplacedBy <{target}>, which this release does not define")
    for local, term in own_terms(vocabulary, release.prefix).items():
        if not term.labels:
            problems.append(f"{where}: {local} has no English label (rdfs:label or skos:prefLabel with @en)")
        if not term.definitions:
            problems.append(f"{where}: {local} has no definition (skos:definition or rdfs:comment)")
    return problems


def check(def_dir: Path = DEF_DIR) -> list[str]:
    """Every way the vocabularies under *def_dir* break the rules, one line each."""
    from battinfo.namespace import publisher_prefix

    found, problems = _walk(def_dir)
    by_prefix: dict[str, list[Release]] = {}
    for release in found:
        by_prefix.setdefault(release.prefix, []).append(release)
    for prefix, in_prefix in by_prefix.items():
        if not PREFIX_RE.fullmatch(prefix) or publisher_prefix(prefix) is None:
            problems.append(
                f"{_shown(def_dir / prefix, def_dir)}: {prefix} is not a prefix allocated in "
                "src/battinfo/data/namespace/prefixes.json"
            )
            continue
        space = f"{DEF_BASE}{prefix}/"
        versions = {release.version for release in in_prefix}
        first_seen: dict[str, str] = {}  # each local name, and the first release that has it
        deprecated_in: dict[str, str] = {}  # each deprecated local name, and the first release that deprecates it
        blamed: set[str] = set()  # the backport terms already reported
        for release in in_prefix:
            where = _shown(release.path, def_dir)
            try:
                vocabulary = read_vocabulary(release.path)
            except ValueError as exc:
                problems.append(f"{where}: does not parse as Turtle: {exc}")
                continue
            problems += _check_release(release, vocabulary, where)
            if vocabulary.ontologies == (DEF_BASE + prefix,):
                for prior in vocabulary.prior_versions:
                    earlier = prior[len(space) :] if prior.startswith(space) else ""
                    if earlier not in versions or release_key(earlier) >= release_key(release.version):
                        problems.append(
                            f"{where}: owl:priorVersion <{prior}> is not the version IRI of a release under "
                            f"def/{prefix}/ that sorts below {release.version}"
                        )
            names = _own_names(vocabulary.subjects, prefix)
            deprecated = _own_names(vocabulary.deprecated, prefix)
            for local, version in first_seen.items():
                if local in names:
                    continue
                if _is_backport(version, release.version):
                    if local not in blamed:
                        blamed.add(local)
                        backport = _shown(def_dir / prefix / version / VOCABULARY_FILE, def_dir)
                        problems.append(
                            f"{backport}: the backport {version} adds {local}, which the later release "
                            f"{release.version} lacks; a backport adds only what later releases have"
                        )
                else:
                    problems.append(
                        f"{where}: drops {local}, which release {version} has; a term is never removed, it is "
                        "marked owl:deprecated true"
                    )
            for local, version in deprecated_in.items():
                if local in names and local not in deprecated:
                    problems.append(
                        f"{where}: {local} is not owl:deprecated, but release {version} deprecates it; a deprecated "
                        "term stays deprecated"
                    )
            for local in names:
                first_seen.setdefault(local, release.version)
            for local in deprecated:
                deprecated_in.setdefault(local, release.version)
    return problems


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", check=False
    )


def _release_folder(path: str) -> str | None:
    """The release folder def/{prefix}/{X.Y.Z} that the repository path *path* lies in, or None."""
    parts = path.split("/")
    if len(parts) >= 4 and parts[0] == "def" and VERSION_RE.fullmatch(parts[2]):
        return "/".join(parts[:3])
    return None


def changed_releases(ref: str, root: Path = ROOT) -> list[str]:
    """Every file of a release folder at *ref* that the working tree changes, deletes or renames, one line each.

    A file added to a release folder that *ref* holds counts too. Raises
    ``ValueError`` when *ref* is not a commit of the repository at *root*.
    """
    commit = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if commit.returncode != 0:
        said = commit.stderr.strip().splitlines()
        raise ValueError(
            f"{ref} is not a commit of this repository; a shallow clone may lack it" + (f" ({said[0]})" if said else "")
        )
    sha = commit.stdout.strip()
    listed = _git(root, "ls-tree", "-r", "-z", "--name-only", sha, "--", "def/")
    held = {folder for path in listed.stdout.split("\0") if (folder := _release_folder(path))}
    diff = _git(root, "diff", "--name-status", "-z", "-M", "--no-ext-diff", sha, "--", "def/")
    if diff.returncode != 0:
        raise ValueError(f"git diff against {ref} failed: {diff.stderr.strip()}")
    # With -z each change is its status letter (and score), then its path, or
    # for a rename the old path and the new one, each ended by a NUL.
    fields = diff.stdout.split("\0")
    problems = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index][0]
        if status in "RC":
            old, new = fields[index + 1], fields[index + 2]
            index += 3
        else:
            old = new = fields[index + 1]
            index += 2
        if status in "MT" and _release_folder(old) in held:
            problems.append(f"{old}: modified since {ref}; {_FIX}")
        elif status == "D" and _release_folder(old) in held:
            problems.append(f"{old}: deleted since {ref}; {_FIX}")
        elif status == "R" and _release_folder(old) in held:
            problems.append(f"{old}: renamed to {new} since {ref}; {_FIX}")
        elif status in "ACR" and _release_folder(new) in held:
            problems.append(f"{new}: added to the release {_release_folder(new)}/ since {ref}; {_FIX}")
    return problems


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--unchanged-since",
        metavar="REF",
        help="also fail when a release that the commit REF holds has changed since",
    )
    args = parser.parse_args(argv)
    problems = check(root / "def")
    if args.unchanged_since is not None:
        try:
            problems += changed_releases(args.unchanged_since, root)
        except ValueError as exc:
            print(f"check_def_vocabularies.py: --unchanged-since: {exc}", file=sys.stderr)
            return 2
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    count = len(releases(root / "def"))
    since = f"; none changed since {args.unchanged_since}" if args.unchanged_since is not None else ""
    print(f"def/: {count} release(s) pass the checks{since}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
