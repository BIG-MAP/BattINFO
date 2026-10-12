"""emmo_closure_terms.py — record what the tests need to know about the pinned EMMO closure.

Follows owl:imports from the three versioned modules battinfo.ttl imports
(domain-battery, domain-electrochemistry, domain-chemical-substance) through
every module they import, reading each file from its release tag on
raw.githubusercontent.com, and writes two lists to
tests/fixtures/emmo/closure-terms.json: every owl:deprecated term with its
prefLabel and dcterms:isReplacedBy, and every class that is a measurement unit
(a named subclass, at any depth, of EMMO's MeasurementUnit).
tests/test_mapping_governance.py checks that no IRI the emitters use is
deprecated, that every unit IRI they write is a unit, and that the lists were
made for the versions battinfo.ttl pins. Run it after moving a pin, next to
refresh_emmo_context.py.

Usage:
    python .tools/quality/emmo_closure_terms.py
    python .tools/quality/emmo_closure_terms.py --check   # exit 1 when the fixture is stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import rdflib
from rdflib.namespace import DCTERMS, OWL, RDFS, SKOS

ROOT = Path(__file__).resolve().parents[2]
BATTINFO_TTL = ROOT / "battinfo.ttl"
OUT = ROOT / "tests" / "fixtures" / "emmo" / "closure-terms.json"
MEASUREMENT_UNIT = "https://w3id.org/emmo#EMMO_b081b346_7279_46ef_9a3d_2c088fcd79f4"
RAW = "https://raw.githubusercontent.com/emmo-repo/{repo}/refs/tags/{tag}/{path}"
TIMEOUT = 30

# Domain segment of a w3id IRI -> (GitHub repository, file stem of the top module).
DOMAINS = {
    "battery": ("domain-battery", "battery"),
    "electrochemistry": ("domain-electrochemistry", "electrochemistry"),
    "chemical-substance": ("domain-chemical-substance", "chemical-substance"),
    "characterisation-methodology": ("domain-characterisation-methodology", "chameo"),
}
DOMAIN_IRI = re.compile(r"^https://w3id\.org/emmo/domain/([a-z-]+)/([^/]+)/(.+)$")
EMMO_IRI = re.compile(r"^https://w3id\.org/emmo/(\d+\.\d+\.\d+)(?:/(.+))?$")


def _candidates(iri: str, importer: tuple[str, str] | None) -> list[tuple[str, str, str]]:
    """(repository, tag, path) guesses for one ontology IRI, most likely first."""
    match = DOMAIN_IRI.match(iri.rstrip("/"))
    if match:
        domain, version, rest = match.groups()
        if domain == "manufacturing":
            # Incubating modules shipped inside domain-electrochemistry, versioned with it.
            return [(importer[0], importer[1], rest + ".ttl")] if importer else []
        repo, stem = DOMAINS[domain]
        if rest == stem:
            return [(repo, version, stem + ".ttl")]
        if rest == "dependencies":
            return [(repo, version, stem + "-dependencies.ttl")]
        base = rest.split("/")[-1]
        return [(repo, version, rest + ".ttl")] + [
            (repo, version, f"{folder}/{base}.ttl") for folder in ("modules", "subdomains", "reference")
        ]
    match = EMMO_IRI.match(iri.rstrip("/"))
    if match:
        version, rest = match.group(1), match.group(2) or "emmo"
        base = rest.split("/")[-1]
        return [("EMMO", version, rest + ".ttl"), ("EMMO", version, f"{rest}/{base}.ttl"),
                ("EMMO", version, f"foundation/{base}.ttl")]
    return []


def _fetch(repo: str, tag: str, path: str) -> str | None:
    url = RAW.format(repo=repo, tag=tag, path=path)
    request = urllib.request.Request(url, headers={"User-Agent": "battinfo-emmo-closure-terms/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def pinned_imports() -> dict[str, str]:
    """domain -> version for each versioned owl:imports in battinfo.ttl."""
    text = BATTINFO_TTL.read_text(encoding="utf-8")
    pins = re.findall(r"owl:imports\s+<https://w3id\.org/emmo/domain/([a-z-]+)/([^/]+)/[a-z-]+>", text)
    return dict(pins)


def build() -> dict:
    pins = pinned_imports()
    queue: list[tuple[str, tuple[str, str] | None]] = [
        (f"https://w3id.org/emmo/domain/{domain}/{version}/{DOMAINS[domain][1]}", None)
        for domain, version in pins.items()
    ]
    graph = rdflib.Graph()
    seen: set[str] = set()
    modules: list[str] = []
    while queue:
        iri, importer = queue.pop()
        if iri in seen:
            continue
        seen.add(iri)
        for repo, tag, path in _candidates(iri, importer):
            text = _fetch(repo, tag, path)
            if text is None:
                continue
            module = rdflib.Graph()
            module.parse(data=text, format="turtle")
            graph += module
            modules.append(f"{repo}@{tag}:{path}")
            queue.extend((str(target), (repo, tag)) for target in module.objects(None, OWL.imports))
            break
        else:
            raise SystemExit(f"ERROR: could not resolve {iri}")
    versions: dict[str, set[str]] = {}
    for module_name in modules:
        repo, tag = module_name.split(":")[0].split("@")
        versions.setdefault(repo, set()).add(tag)
    deprecated = sorted(
        {str(s) for s, o in graph.subject_objects(OWL.deprecated) if str(o).lower() == "true"}
    )
    subclasses: dict[str, set[str]] = {}
    for sub, sup in graph.subject_objects(RDFS.subClassOf):
        if isinstance(sub, rdflib.URIRef) and isinstance(sup, rdflib.URIRef):
            subclasses.setdefault(str(sup), set()).add(str(sub))
    units: set[str] = set()
    stack = [MEASUREMENT_UNIT]
    while stack:
        for unit in subclasses.get(stack.pop(), set()):
            if unit not in units:
                units.add(unit)
                stack.append(unit)
    return {
        "description": (
            "The owl:deprecated terms and the measurement-unit classes of the EMMO import closure "
            "battinfo.ttl pins, read from the release tags by .tools/quality/emmo_closure_terms.py. "
            "tests/test_mapping_governance.py checks that no IRI the emitters use is deprecated and "
            "that every unit IRI they write is a unit. Regenerate it when the pins move."
        ),
        "closure": {repo: sorted(tags) for repo, tags in sorted(versions.items())},
        "deprecated": [
            {
                "iri": iri,
                "pref_label": next((str(x) for x in graph.objects(rdflib.URIRef(iri), SKOS.prefLabel)), ""),
                "replaced_by": sorted(str(x) for x in graph.objects(rdflib.URIRef(iri), DCTERMS.isReplacedBy)),
            }
            for iri in deprecated
        ],
        "measurement_units": sorted(units),
    }


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Compare with the fixture instead of writing it.")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current.replace("\r\n", "\n") != text:
            print(f"{OUT.relative_to(ROOT)} is stale; run .tools/quality/emmo_closure_terms.py")
            return 1
        print(f"{OUT.relative_to(ROOT)} matches the pinned closure.")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    written = json.loads(text)
    print(
        f"Wrote {OUT.relative_to(ROOT)} ({len(written['deprecated'])} deprecated terms, "
        f"{len(written['measurement_units'])} measurement units)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
