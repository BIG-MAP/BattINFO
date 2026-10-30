"""Lay out the publishers' vocabularies under def/ as GitHub Pages serves them.

The first form checks def/ with ``scripts/check_def_vocabularies.py`` and, when
it passes, writes for each release ``def/{prefix}/{X.Y.Z}/vocab.ttl``:

* ``OUT_DIR/def/{prefix}/{X.Y.Z}/vocab.ttl``, a byte copy;
* ``OUT_DIR/def/{prefix}/{X.Y.Z}/index.html``, a page laid out like a
  vocabulary's documentation usually is: the title, publisher and
  description, a table of the ontology and version IRIs, issue date,
  creators, namespace, licence, download and releases, links to the publisher's own
  documentation, a list of the terms, an outline of each concept scheme, and
  a block for each term, anchored by its local name, with its IRI,
  definition, notes, other labels, broader and narrower terms and SKOS
  matches (a matched EMMO term shown by its name, read from the vendored
  domain-battery JSON-LD context);

and then, from the release folders under ``OUT_DIR/def``:

* ``def/{prefix}/vocab.ttl`` and ``index.html``, copies of the newest final
  release's files, or of the newest pre-release while none is final;
* ``def/index.html``, which lists the vocabularies and their releases.

The pages are in the BattINFO style: brand/tokens.css and the BattINFO symbol
are copied into each page, which is light or dark as the visitor chose on
the docs site, or as their system is set.

w3id sends https://w3id.org/battinfo/def/{prefix} and each term
.../def/{prefix}/{term} to def/{prefix}/ (to #{term} on its page, for a
browser), and the version IRI .../def/{prefix}/{X.Y.Z} to its own folder. A
release's page depends on that release alone, so it serves unchanged at
def/{prefix}/ and a new release never changes it; its links to other
releases are absolute.

The second form is what ``.github/workflows/docs-deploy.sh`` runs on a
checkout of gh-pages. It copies each release folder of BUILT_DIR/def (an
OUT_DIR of the first form) that SITE_DIR/def lacks, and never replaces or
removes a published one: when a published release's vocab.ttl differs from
the built one, the published copy stays and a ``::warning::`` says so. When
it is the same, only the release's index.html is written again, so a fix to
the page reaches releases already published. It then
writes the newest-release files and def/index.html again from every release
under SITE_DIR/def, so a deploy from an older checkout keeps the newer
releases. It needs only the standard library, since the deploy job runs a
bare python3.

Usage::

    python scripts/build_def_site.py OUT_DIR
    python scripts/build_def_site.py --merge BUILT_DIR SITE_DIR

The exit status is 1 when def/ fails its checks, and 0 otherwise.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_def_vocabularies as check  # noqa: E402

PAGES_DEF = "https://big-map.github.io/BattINFO/def/"
SOURCE_DEF = "https://github.com/BIG-MAP/BattINFO/tree/main/def"
SOURCE_FILE = "https://github.com/BIG-MAP/BattINFO/blob/main/def/{prefix}/{version}/" + check.VOCABULARY_FILE
HOME = "https://battinfo.org/"
NAMESPACE = "https://w3id.org/battinfo/"
REGISTER = check.ROOT / "src" / "battinfo" / "data" / "namespace" / "prefixes.json"
#: Names for EMMO IRIs that a vocabulary matches its terms to.
EMMO_NAMES = check.ROOT / "src" / "battinfo" / "data" / "context" / "domain-battery.context.json"
EMMO_BASE = "https://w3id.org/emmo"
#: The BattINFO design tokens and symbol, copied into every page so that it stands alone.
BRAND = check.ROOT / "brand"
PAGE_FILE = "index.html"
# The page's own rules, on top of brand/tokens.css. Like every BattINFO
# surface they use the semantic --bi-* tokens only (brand/AGENTS.md).
_STYLE = (
    ".shell{max-width:52rem;margin:0 auto;padding:0 1rem 3rem;line-height:1.55}"
    ".top{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem;padding:1rem 0;margin-bottom:2rem;"
    "border-bottom:1px solid var(--bi-border);font-size:.95rem}"
    ".top svg{display:block;width:20px;height:auto}"
    ".top .home{color:var(--bi-text-primary);font-weight:700}"
    ".top .crumb{color:var(--bi-text-muted)}"
    ':root[data-theme="dark"] .mark-light,:root:not([data-theme="dark"]) .mark-dark{display:none}'
    "h1{font-size:2rem;line-height:1.2;margin:.25rem 0 .5rem}"
    "h2{font-size:1.35rem;margin:2.5rem 0 .75rem}"
    "h3{display:flex;flex-wrap:wrap;align-items:center;gap:.5rem;font-size:1.1rem;margin:0 0 .5rem}"
    ".eyebrow{margin:0;color:var(--bi-text-muted);font-size:.8rem;font-weight:600;letter-spacing:.06em;"
    "text-transform:uppercase}"
    ".byline{margin:0 0 1rem;color:var(--bi-text-secondary)}"
    ".lead{font-size:1.1rem;color:var(--bi-text-secondary)}"
    ".bi-card{padding:.75rem 1.25rem;margin:1rem 0}.bi-card>h2{margin:.5rem 0}.facts td>ul{margin:0;padding-left:1.25rem}"
    ".facts{width:100%;border-collapse:collapse}"
    ".facts th{width:9.5rem;padding:.45rem 1rem .45rem 0;text-align:left;vertical-align:top;font-weight:600;"
    "color:var(--bi-text-secondary)}"
    ".facts td{padding:.45rem 0;vertical-align:top}"
    ".facts tr+tr>*{border-top:1px solid var(--bi-border)}"
    "a,code{overflow-wrap:anywhere}code{font-size:.88em}"
    # A link inside running text is underlined, not told apart by colour alone (WCAG 1.4.1).
    ".byline a,.lead a,.facts td a,footer a{text-decoration:underline;text-underline-offset:3px}"
    ".bi-badge{padding:2px 10px;font-size:12px}"
    ".bi-badge.deprecated{background:var(--bi-warning-bg);color:var(--bi-warning)}"
    ".term{scroll-margin-top:1rem}.term:target{border-color:var(--bi-brand-text)}"
    ".toc ul{columns:2;column-gap:2rem;margin:.5rem 0;padding-left:1.25rem}"
    ".tree ul{margin:.25rem 0;padding-left:1.25rem}"
    "footer{margin-top:3rem;padding-top:1rem;border-top:1px solid var(--bi-border);color:var(--bi-text-muted);"
    "font-size:.9rem}"
    "@media (max-width:40rem){h1{font-size:1.6rem}.toc ul{columns:1}"
    ".facts tr{display:block;padding:.4rem 0}.facts tr+tr{border-top:1px solid var(--bi-border)}"
    ".facts th,.facts td{display:block;width:auto;padding:.1rem 0;border:0!important}}"
)
# Sets data-theme before the page paints: light or dark as chosen on the
# BattINFO docs site (same origin; pydata-sphinx-theme keeps the choice under
# the localStorage key "mode"), else as the system is set, which is also what
# "auto" means there. Without JavaScript the page stays light.
_THEME = (
    "<script>(function(){var t;try{t=localStorage.getItem('mode')}catch(e){}"
    "if(t!=='light'&&t!=='dark'){t=window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches"
    "?'dark':'light'}document.documentElement.setAttribute('data-theme',t)})()</script>"
)


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def _link(iri: str, text: str | None = None) -> str:
    """A link to *iri*, or the IRI as text when it is not an http(s) URL."""
    shown = _escape(text if text is not None else iri)
    if not re.match(r"https?://", iri, re.IGNORECASE):
        return f"<code>{shown}</code>"
    return f'<a href="{_escape(iri)}">{shown}</a>'


_emmo_names: dict[str, str] | None = None


def emmo_name(iri: str) -> str | None:
    """The name of the EMMO term *iri* in the vendored domain-battery context, or None.

    Where the context gives one IRI several names, such as a corrected
    spelling beside the old one, the first in sorted order is used.
    """
    global _emmo_names
    if _emmo_names is None:
        try:
            context = json.loads(EMMO_NAMES.read_text(encoding="utf-8"))["@context"]
        except (OSError, ValueError, KeyError):
            context = {}
        names: dict[str, str] = {}
        for name in sorted(context):
            value = context[name]
            target = value.get("@id") if isinstance(value, dict) else value
            if isinstance(target, str) and target.startswith(EMMO_BASE):
                names.setdefault(target, name)
        _emmo_names = names
    return _emmo_names.get(iri)


_brand: tuple[str, str, str] | None = None


def _brand_parts() -> tuple[str, str, str]:
    """(brand/tokens.css, the symbol for light pages, the symbol for dark pages), each empty when missing."""
    global _brand
    if _brand is None:

        def read(relative: str) -> str:
            try:
                text = (BRAND / relative).read_text(encoding="utf-8")
            except OSError:
                return ""
            return "" if "</" + "style" in text.lower() else text.strip()

        _brand = (read("tokens.css"), read("assets/icon/icon.svg"), read("assets/icon/icon-reversed.svg"))
    return _brand


def _rows(rows: list[tuple[str, str]]) -> str:
    """A table of (heading, HTML) rows; the headings are escaped here, the HTML is not."""
    lines = [f"<tr><th>{_escape(heading)}</th><td>{cell}</td></tr>" for heading, cell in rows]
    return "\n".join(['<table class="facts">', *lines, "</table>"])


def _page(title: str, body: list[str], footer: str, head: str = "", *, index: bool = False) -> str:
    """A page in the BattINFO style, with the site bar, *body* in <main> and *footer*."""
    tokens, light, dark = _brand_parts()
    marks = []
    if light and dark:
        marks = [
            f'<span class="mark-light" aria-hidden="true">{light}</span>',
            f'<span class="mark-dark" aria-hidden="true">{dark}</span>',
        ]
    section = "Publisher vocabularies" if index else _link(PAGES_DEF, "Publisher vocabularies")
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en" data-theme="light">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{_escape(title)}</title>",
            _THEME,
            *([head] if head else []),
            f"<style>{tokens}\n{_STYLE}</style>",
            "</head>",
            "<body>",
            '<div class="shell">',
            '<header class="top">',
            *marks,
            f'<a class="home" href="{HOME}">BattINFO</a>',
            '<span class="crumb" aria-hidden="true">/</span>',
            section,
            "</header>",
            "<main>",
            *body,
            "</main>",
            f"<footer>{footer}</footer>",
            "</div>",
            "</body>",
            "</html>",
            "",
        ]
    )


def release_page(prefix: str, version: str, vocabulary: check.Vocabulary) -> str:
    """The index.html of the release *version* of the vocabulary of *prefix*, read as *vocabulary*."""
    ontology = check.DEF_BASE + prefix
    space = ontology + "/"
    title = vocabulary.titles[0]
    licences = ", ".join(_link(iri) for iri in vocabulary.licences)
    terms = check.own_terms(vocabulary, prefix)

    def label_of(local: str) -> str:
        return terms[local].labels[0] if terms[local].labels else local

    def sort_key(local: str) -> tuple[str, str]:
        return (label_of(local).casefold(), local)

    def own(iri: str) -> str | None:
        """The local name of *iri* when it is a term of this release."""
        local = iri[len(space) :] if iri.startswith(space) else None
        return local if local in terms else None

    def ref(iri: str) -> str:
        """A link to *iri*: to its entry when it is a term here, else to the IRI, by its EMMO name if it has one."""
        local = own(iri)
        if local is not None:
            return f'<a href="#{_escape(local)}">{_escape(label_of(local))}</a>'
        return _link(iri, emmo_name(iri))

    def refs(iris: tuple[str, ...]) -> str:
        return ", ".join(ref(iri) for iri in sorted(iris, key=lambda iri: (own(iri) is None, iri)))

    def outline(iris: tuple[str, ...], seen: frozenset[str]) -> list[str]:
        """Nested lists of the terms *iris* and their narrower terms, each term once on a branch."""
        items = []
        found = {local for iri in iris if (local := own(iri)) is not None}
        for local in sorted(found - seen, key=sort_key):
            below = outline(terms[local].narrower, seen | {local})
            items.append(f"<li>{ref(space + local)}{''.join(below)}</li>")
        return ["<ul>", *items, "</ul>"] if items else []

    ordered = sorted(terms, key=sort_key)
    schemes = []
    for local in ordered:
        if "concept scheme" in terms[local].kinds:
            tree = outline(terms[local].top_concepts, frozenset({local}))
            schemes.append(
                "\n".join(
                    ['<div class="bi-card tree">', f"<p><strong>{ref(space + local)}</strong></p>", *tree, "</div>"]
                )
            )

    articles = []
    for local in ordered:
        term = terms[local]
        anchor = _escape(local)
        badges = [f'<span class="bi-badge">{_escape(kind)}</span>' for kind in term.kinds]
        if term.deprecated:
            badges.append('<span class="bi-badge deprecated">deprecated</span>')
        rows = [("IRI", f"<code>{_escape(term.iri)}</code>")]
        rows += [("Definition", _escape(text)) for text in term.definitions[:1]]
        rows += [("Note", _escape(note)) for note in term.scope_notes]
        if term.alt_labels:
            rows.append(("Also called", ", ".join(_escape(text) for text in term.alt_labels)))
        if term.broader:
            rows.append(("Broader", refs(term.broader)))
        if term.narrower:
            rows.append(("Narrower", refs(term.narrower)))
        for predicate, word in check.MATCHES.items():
            matched = tuple(iri for found, iri in term.matches if found == predicate)
            if matched:
                rows.append((word, refs(matched)))
        if term.see_also:
            rows.append(("See also", ", ".join(_link(iri) for iri in term.see_also)))
        if term.replaced_by:
            rows.append(("Replaced by", refs(term.replaced_by)))
        articles.append(
            "\n".join(
                [
                    f'<article class="bi-card term" id="{anchor}">',
                    f'<h3><a href="#{anchor}">{_escape(label_of(local))}</a> {" ".join(badges)}</h3>',
                    _rows(rows),
                    "</article>",
                ]
            )
        )

    facts = [
        ("Ontology IRI", f"<code>{_escape(ontology)}</code>"),
        ("Version IRI", f"<code>{_escape(f'{ontology}/{version}')}</code>"),
        ("Version", _escape(version)),
    ]
    facts += [("Previous release", _link(prior, prior.rsplit("/", 1)[-1])) for prior in vocabulary.prior_versions]
    facts += [("Issued", _escape(date)) for date in vocabulary.issued]
    creators = [
        (_link(iri, name) if iri else _escape(name)) + (f", {_escape(affiliation)}" if affiliation else "")
        for name, affiliation, iri in vocabulary.creators
    ]
    if creators:
        facts.append(("Creators", "\n".join(["<ul>", *(f"<li>{entry}</li>" for entry in creators), "</ul>"])))
    facts += [
        ("Namespace", f"<code>{_escape(space)}</code>"),
        ("Licence", licences),
        ("Download", f'<a href="{check.VOCABULARY_FILE}">{check.VOCABULARY_FILE}</a> (Turtle)'),
    ]
    if vocabulary.pages:
        facts.append(("Documentation", ", ".join(_link(iri) for iri in vocabulary.pages)))
    facts.append(("Releases", f"{_link(ontology, 'newest')}, {_link(f'{PAGES_DEF}#{prefix}', 'all releases')}"))

    publishers = [_link(homepage, name) if homepage else _escape(name) for name, homepage in vocabulary.publishers]
    contents = [f'<li><a href="#{_escape(local)}">{_escape(label_of(local))}</a></li>' for local in ordered]
    body = [
        f'<p class="eyebrow">Vocabulary, prefix {_escape(prefix)}</p>',
        f"<h1>{_escape(title)}</h1>",
        *([f'<p class="byline">Published by {", ".join(publishers)}</p>'] if publishers else []),
        *(f'<p class="lead">{_escape(text)}</p>' for text in vocabulary.descriptions[:1]),
        f'<section class="bi-card">\n{_rows(facts)}\n</section>',
        *(
            [
                '<nav class="bi-card toc" aria-label="Contents">',
                "<strong>Terms</strong>",
                "<ul>",
                *contents,
                "</ul>",
                "</nav>",
            ]
            if contents
            else []
        ),
        *(['<h2 id="schemes">Concept schemes</h2>', *schemes] if schemes else []),
        f'<h2 id="terms">Terms ({len(terms)})</h2>',
        *(articles or ["<p>This release defines no terms.</p>"]),
    ]
    source = SOURCE_FILE.format(prefix=prefix, version=version)
    footer = (
        f"Hosted in the BattINFO namespace, <code>{_escape(NAMESPACE)}</code>. "
        f"Source: {_link(source, f'def/{prefix}/{version}/{check.VOCABULARY_FILE}')}"
    )
    head = f'<link rel="alternate" type="text/turtle" href="{check.VOCABULARY_FILE}">'
    if vocabulary.descriptions:
        head += f'\n<meta name="description" content="{_escape(vocabulary.descriptions[0])}">'
    return _page(f"{title} {version}", body, footer, head)


def _holders() -> dict[str, str]:
    """Each allocated prefix and its holder, read from the register without battinfo."""
    try:
        entries = json.loads(REGISTER.read_text(encoding="utf-8"))["prefixes"]
    except (OSError, ValueError, KeyError):
        return {}
    return {entry["prefix"]: entry["holder"] for entry in entries}


def _title(page: Path) -> str | None:
    """The title on a release page this script wrote (its h1)."""
    try:
        found = re.search(r"<h1>(.*?)</h1>", page.read_text(encoding="utf-8"), re.S)
    except OSError:
        return None
    return html.unescape(found[1]) if found else None


def _folders(parent: Path, pattern: re.Pattern[str]) -> list[Path]:
    if not parent.is_dir():
        return []
    return sorted(entry for entry in parent.iterdir() if entry.is_dir() and pattern.fullmatch(entry.name))


def index_page(vocabularies: list[tuple[str, str, list[str], str]]) -> str:
    """def/index.html, listing each vocabulary as (prefix, title, versions newest first, the version served)."""
    holders = _holders()
    body = [
        '<p class="eyebrow">BattINFO namespace</p>',
        "<h1>Publisher vocabularies</h1>",
        f'<p class="lead">Terms that publishers define under <code>{_escape(check.DEF_BASE)}{{prefix}}/</code>. '
        f"Each vocabulary is kept in {_link(SOURCE_DEF, 'def/')} in the BattINFO repository.</p>",
    ]
    if not vocabularies:
        body.append("<p>No vocabulary is published yet.</p>")
    for prefix, title, versions, served in vocabularies:
        ontology = check.DEF_BASE + prefix
        holder = holders.get(prefix)
        releases = [
            f'<li><a href="{_escape(prefix)}/{_escape(version)}/">{_escape(version)}</a>'
            + (", served at the ontology IRI" if version == served else "")
            + "</li>"
            for version in versions
        ]
        rows = [
            ("Ontology IRI", _link(ontology)),
            ("Prefix", _escape(prefix) + (f", {_escape(holder)}" if holder else "")),
            ("Releases", "\n".join(["<ul>", *releases, "</ul>"])),
        ]
        body.append(
            f'<section class="bi-card">\n<h2 id="{_escape(prefix)}">{_escape(title)}</h2>\n{_rows(rows)}\n</section>'
        )
    footer = f"Hosted in the BattINFO namespace, <code>{_escape(NAMESPACE)}</code>. Source: {_link(SOURCE_DEF, 'def/')}"
    return _page("Publisher vocabularies", body, footer, index=True)


def finish(root: Path, *, always: bool) -> list[str]:
    """Write the newest-release files of each vocabulary under *root*/def, and def/index.html.

    They are written from the release folders there. def/index.html is
    written when there is a vocabulary, or *always*. Returns what was done,
    one line each.
    """
    def_dir = root / "def"
    done = []
    vocabularies = []
    for prefix_dir in _folders(def_dir, check.PREFIX_RE):
        versions = [d.name for d in _folders(prefix_dir, check.VERSION_RE) if (d / check.VOCABULARY_FILE).is_file()]
        if not versions:
            continue
        served = check.newest_release(versions)
        for name in (check.VOCABULARY_FILE, PAGE_FILE):
            if (prefix_dir / served / name).is_file():
                shutil.copyfile(prefix_dir / served / name, prefix_dir / name)
        title = _title(prefix_dir / served / PAGE_FILE) or f"Vocabulary {prefix_dir.name}"
        newest_first = sorted(versions, key=check.release_key, reverse=True)
        vocabularies.append((prefix_dir.name, title, newest_first, served))
        done.append(f"def/{prefix_dir.name}: {len(versions)} release(s), {served} at the ontology IRI")
    if vocabularies or always:
        def_dir.mkdir(parents=True, exist_ok=True)
        (def_dir / PAGE_FILE).write_text(index_page(vocabularies), encoding="utf-8", newline="\n")
    return done


def build(out_dir: Path, def_dir: Path = check.DEF_DIR) -> list[str]:
    """Write the published layout of *def_dir* to *out_dir*/def, or return why not, one problem per line."""
    problems = check.check(def_dir)
    if problems:
        return problems
    target = out_dir / "def"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for release in check.releases(def_dir):
        folder = target / release.prefix / release.version
        folder.mkdir(parents=True)
        shutil.copyfile(release.path, folder / check.VOCABULARY_FILE)
        page = release_page(release.prefix, release.version, check.read_vocabulary(release.path))
        (folder / PAGE_FILE).write_text(page, encoding="utf-8", newline="\n")
    finish(out_dir, always=True)
    return []


def merge(built: Path, site: Path) -> list[str]:
    """Add the release folders of *built*/def that *site*/def lacks, then rewrite the newest-release files.

    A published release folder, one that holds vocab.ttl, is never replaced
    or removed, and its vocab.ttl never changes. Its index.html is written
    again when the vocab.ttl is the built one and the built page differs, so
    a fix to the page reaches published releases. Returns what was done, one
    line each, with a ``::warning::`` line for each published release whose
    vocab.ttl differs from the built one.
    """
    done = []
    for prefix_dir in _folders(built / "def", check.PREFIX_RE):
        for release_dir in _folders(prefix_dir, check.VERSION_RE):
            name = f"def/{prefix_dir.name}/{release_dir.name}"
            published = site / name
            if (published / check.VOCABULARY_FILE).is_file():
                if (published / check.VOCABULARY_FILE).read_bytes() != (
                    release_dir / check.VOCABULARY_FILE
                ).read_bytes():
                    done.append(
                        f"::warning::{name}/{check.VOCABULARY_FILE} on gh-pages differs from this checkout's. "
                        "A published release never changes, so the published copy is kept."
                    )
                elif (release_dir / PAGE_FILE).is_file() and (
                    not (published / PAGE_FILE).is_file()
                    or (published / PAGE_FILE).read_bytes() != (release_dir / PAGE_FILE).read_bytes()
                ):
                    shutil.copyfile(release_dir / PAGE_FILE, published / PAGE_FILE)
                    done.append(f"{name}/{PAGE_FILE}: written again from this checkout")
                continue
            # Written beside its place and renamed into it, so the folder is
            # either whole or absent; one an older run left without its
            # vocab.ttl is not a release, and is replaced.
            published.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=f".{release_dir.name}-", dir=published.parent))
            try:
                shutil.copytree(release_dir, staging, dirs_exist_ok=True)
                if published.exists():
                    shutil.rmtree(published)
                staging.rename(published)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            done.append(f"{name}: published")
    return done + finish(site, always=False)


def main(argv: list[str] | None = None, *, def_dir: Path = check.DEF_DIR) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out_dir", type=Path, metavar="OUT_DIR", help="where def/ is written (the site's root)")
    parser.add_argument(
        "--merge",
        type=Path,
        metavar="BUILT_DIR",
        help="merge BUILT_DIR/def, the output of an earlier run, into OUT_DIR/def instead",
    )
    args = parser.parse_args(argv)
    if args.merge is not None:
        for line in merge(args.merge, args.out_dir):
            print(line, file=sys.stderr)
        return 0
    problems = build(args.out_dir, def_dir)
    if problems:
        print("def/ fails its checks, so no pages were built:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    count = len(check.releases(def_dir))
    print(f"{args.out_dir.as_posix()}/def: {count} release(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
