"""Lay out the publishers' vocabularies under def/ as GitHub Pages serves them.

The first form checks def/ with ``scripts/check_def_vocabularies.py`` and, when
it passes, writes for each release ``def/{prefix}/{X.Y.Z}/vocab.ttl``:

* ``OUT_DIR/def/{prefix}/{X.Y.Z}/vocab.ttl``, a byte copy;
* ``OUT_DIR/def/{prefix}/{X.Y.Z}/index.html``, a page with the title, the
  version IRI, the licence, links to the Turtle and to the other releases, and
  the terms, each anchored by its local name;

and then, from the release folders under ``OUT_DIR/def``:

* ``def/{prefix}/vocab.ttl`` and ``index.html``, copies of the newest final
  release's files, or of the newest pre-release while none is final;
* ``def/index.html``, which lists the vocabularies and their releases.

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
REGISTER = check.ROOT / "src" / "battinfo" / "data" / "namespace" / "prefixes.json"
PAGE_FILE = "index.html"
_STYLE = (
    "body{font-family:system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;line-height:1.5}"
    "a{overflow-wrap:anywhere}dt{margin-top:.75rem}dd{margin-left:1.5rem}small{color:#555}"
)


def _escape(text: str) -> str:
    return html.escape(text, quote=True)


def _link(iri: str, text: str | None = None) -> str:
    """A link to *iri*, or the IRI as text when it is not an http(s) URL."""
    shown = _escape(text if text is not None else iri)
    if not re.match(r"https?://", iri):
        return f"<code>{shown}</code>"
    return f'<a href="{_escape(iri)}">{shown}</a>'


def _page(title: str, body: list[str], head: str = "") -> str:
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{_escape(title)}</title>",
            *([head] if head else []),
            f"<style>{_STYLE}</style>",
            "</head>",
            "<body>",
            *body,
            "</body>",
            "</html>",
            "",
        ]
    )


def release_page(prefix: str, version: str, vocabulary: check.Vocabulary) -> str:
    """The index.html of the release *version* of the vocabulary of *prefix*, read as *vocabulary*."""
    ontology = check.DEF_BASE + prefix
    title = vocabulary.titles[0]
    licences = ", ".join(_link(iri) for iri in vocabulary.licences)
    releases = []
    for prior in vocabulary.prior_versions:
        releases.append(f"<li>Previous release: {_link(prior, prior.rsplit('/', 1)[-1])}</li>")
    releases.append(f"<li>Newest release: {_link(ontology)}</li>")
    releases.append(f"<li>All releases: {_link(f'{PAGES_DEF}#{prefix}', PAGES_DEF)}</li>")

    terms = check.own_terms(vocabulary, prefix)
    entries = []
    for local in sorted(terms, key=lambda name: (name.casefold(), name)):
        term = terms[local]
        anchor = _escape(local)
        label = term.labels[0] if term.labels else local
        about = ", ".join(term.kinds) + (", deprecated" if term.deprecated else "")
        entries.append(
            f'<dt id="{anchor}"><a href="#{anchor}">{_escape(label)}</a> <small>{_escape(about)}</small></dt>'
        )
        lines = [f"<code>{_escape(term.iri)}</code>"]
        if term.definitions:
            lines.append(_escape(term.definitions[0]))
        if term.replaced_by:
            space = ontology + "/"
            replacements = [
                f'<a href="#{_escape(iri[len(space) :])}">{_escape(iri[len(space) :])}</a>'
                if iri.startswith(space) and iri[len(space) :] in terms
                else _link(iri)
                for iri in term.replaced_by
            ]
            lines.append("Replaced by " + ", ".join(replacements))
        entries.append(f"<dd>{'<br>'.join(lines)}</dd>")
    listed = ["<dl>", *entries, "</dl>"] if entries else ["<p>This release defines no terms.</p>"]

    body = [
        f"<h1>{_escape(title)}</h1>",
        f"<p>Version: {_escape(version)}<br>"
        f"Version IRI: <code>{_escape(f'{ontology}/{version}')}</code><br>"
        f"Ontology IRI: <code>{_escape(ontology)}</code><br>"
        f"Licence: {licences}</p>",
        "<h2>Files</h2>",
        "<ul>",
        f'<li><a href="{check.VOCABULARY_FILE}">{check.VOCABULARY_FILE}</a> (Turtle)</li>',
        "</ul>",
        "<h2>Releases</h2>",
        "<ul>",
        *releases,
        "</ul>",
        f"<h2>Terms ({len(terms)})</h2>",
        *listed,
    ]
    head = f'<link rel="alternate" type="text/turtle" href="{check.VOCABULARY_FILE}">'
    return _page(f"{title} {version}", body, head)


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
        "<h1>Publisher vocabularies</h1>",
        f"<p>Terms that publishers define under <code>{_escape(check.DEF_BASE)}{{prefix}}/</code>. "
        f"Each vocabulary is kept in {_link(SOURCE_DEF, 'def/')} in the BattINFO repository.</p>",
    ]
    if not vocabularies:
        body.append("<p>No vocabulary is published yet.</p>")
    for prefix, title, versions, served in vocabularies:
        ontology = check.DEF_BASE + prefix
        holder = holders.get(prefix)
        body += [
            f'<h2 id="{_escape(prefix)}">{_escape(title)}</h2>',
            f"<p>Ontology IRI: {_link(ontology)}<br>Prefix: {_escape(prefix)}"
            + (f", {_escape(holder)}" if holder else "")
            + "</p>",
            "<ul>",
            *(
                f'<li><a href="{_escape(prefix)}/{_escape(version)}/">{_escape(version)}</a>'
                + (", served at the ontology IRI" if version == served else "")
                + "</li>"
                for version in versions
            ),
            "</ul>",
        ]
    return _page("Publisher vocabularies", body)


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
