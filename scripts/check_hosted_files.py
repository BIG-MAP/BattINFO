"""Check that the files w3id serves are the ones this checkout bundles.

The registry (battinfo-registry) serves the v1 records context, the JSON
Schemas and the record vocabulary at their w3id IRIs, from copies it vendors
at a pinned BattINFO commit. This script compares each with the copy in this
checkout by the sha256 of its bytes, with line endings normalised to LF, as
the registry's own vendoring check compares them:

* the v1 records context, ``src/battinfo/data/context/records.context.v1.json``,
  at https://w3id.org/battinfo/context/records/v1.json, asked for as
  ``application/ld+json``;
* every JSON Schema under ``src/battinfo/data/schemas/``, at its ``$id``;
* the record vocabulary, ``assets/vocab/battinfo-records.ttl``, which w3id
  serves for each term it declares, such as https://w3id.org/battinfo/batchId.

``.github/workflows/release.yml`` runs it before an upload, and a mismatch
blocks only a final release tag. With ``--release-terms`` it checks instead
that the hosted context still holds every term of the last release's v1
context with the same value, so terms added on main since that release do not
count; ``.github/workflows/hosted-files.yml`` runs that every day.

The ontology, battinfo.ttl, is served from GitHub Pages, where
.github/workflows/docs-deploy.sh puts it for each final release. w3id sends
https://w3id.org/battinfo to the newest release's copy at the root of the site,
https://w3id.org/battinfo/X.Y.Z to battinfo/versions/X.Y.Z/battinfo.ttl, and
https://w3id.org/battinfo/latest to battinfo.ttl on main. The versionIRI,
https://w3id.org/battinfo/X.Y.Z/battinfo, reaches the registry, which answers
with a 303 to https://w3id.org/battinfo/X.Y.Z. Each request asks for
``text/turtle`` and follows the redirects one at a time, so the report says
where each IRI landed:

* ``--ontology-routes`` checks that the root, /latest, /X.Y.Z and the
  versionIRI of this checkout's battinfo.ttl land where w3id should send them.
  Before the tag the release's files are not there yet, so a 404 in the right
  place passes. With ``--served`` each must also answer with this checkout's
  battinfo.ttl, which is the check after the tag. /latest still leads to the
  master branch until a perma-id pull request moves it to main; while it does,
  it is reported as ``pending`` and does not fail the check.
* ``--ontology`` checks that the root declares the last release's versionIRI
  and imports, and that /X.Y.Z and the versionIRI serve that release's
  battinfo.ttl. ``.github/workflows/hosted-files.yml`` runs it every day. It is
  not part of release.yml, because the versionIRI resolves only after the
  tag's own docs deploy, and it leaves /latest out, since that follows main.

A request is tried again when the server is busy or does not answer, since the
registry's host can take a minute to wake up. So that a run always ends with a
report, even when w3id or the registry is down, it stops asking once
``--deadline`` seconds have passed (600 by default), and after two files in a
row got no answer it reports the rest as unreachable without asking.

Usage::

    python scripts/check_hosted_files.py [--summary FILE]
    python scripts/check_hosted_files.py --release-terms [--tag vX.Y.Z] [--summary FILE]
    python scripts/check_hosted_files.py --ontology-routes [--served] [--summary FILE]
    python scripts/check_hosted_files.py --ontology [--tag vX.Y.Z] [--summary FILE]

Each also takes ``--attempts``, ``--wait`` and ``--deadline``.

The exit status is 0 when everything matches and 1 when anything differs or
could not be fetched. Only the standard library is used, so it runs without
battinfo installed.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

CONTEXT_PATH = Path("src/battinfo/data/context/records.context.v1.json")
CONTEXT_URL = "https://w3id.org/battinfo/context/records/v1.json"
SCHEMAS_PATH = Path("src/battinfo/data/schemas")
VOCABULARY_PATH = Path("assets/vocab/battinfo-records.ttl")
# w3id forwards a bare term IRI to the registry, which answers with a 303 to
# /vocab/battinfo-records.ttl, so this IRI stands for the vocabulary document.
# batchId is a term the vocabulary declares and the v1 context maps (batch_id),
# so the IRI keeps resolving if the registry ever routes declared terms only.
VOCABULARY_URL = "https://w3id.org/battinfo/batchId"

ONTOLOGY_PATH = Path("battinfo.ttl")
ONTOLOGY_IRI = "https://w3id.org/battinfo"
LATEST_IRI = "https://w3id.org/battinfo/latest"
PAGES = "https://big-map.github.io/BattINFO"
LATEST_FILE = "https://raw.githubusercontent.com/BIG-MAP/BattINFO/main/battinfo.ttl"
# Where /latest leads until the perma-id pull request that moves it to main is
# merged. Landing there is reported as pending and does not fail a check.
LATEST_FILE_ON_MASTER = "https://raw.githubusercontent.com/BIG-MAP/BattINFO/master/battinfo.ttl"
# docs-deploy.sh publishes the ontology from this release on; older releases
# were published by hand, under other paths.
FIRST_ONTOLOGY_RELEASE = (0, 8, 0)

FINAL_RELEASE_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
USER_AGENT = "battinfo-hosted-check (+https://github.com/BIG-MAP/BattINFO)"
# Statuses that mean "busy or waking up, ask again"; any other is the answer.
RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
# How a hosted file can compare with the checkout's copy, in report order.
STATUSES = ("same", "differs", "missing", "unreachable")
# How an ontology IRI can come out, in report order. "routed" lands in the right
# place (before the tag the file there may not exist yet); "pending" lands where
# the IRI leads until a known routing change is merged; "misrouted" elsewhere.
ONTOLOGY_STATUSES = ("same", "routed", "pending", "differs", "missing", "misrouted", "unreachable")
# Seconds a run may spend asking before it reports what it has (--deadline).
DEFAULT_DEADLINE = 600.0
# After this many files in a row got no answer, the host is taken to be down
# and the remaining files are reported unreachable without a request.
GIVE_UP_AFTER = 2


@dataclass(frozen=True)
class HostedFile:
    """A file w3id serves (*url*, asked for as *accept*) and its copy in the checkout (*path*)."""

    url: str
    accept: str
    path: Path


@dataclass(frozen=True)
class Outcome:
    """How the hosted copy of *file* compares: ``same``, ``differs``, ``missing`` or ``unreachable``."""

    file: HostedFile
    status: str
    detail: str = ""


class FetchError(Exception):
    """A file could not be fetched. *status* is the HTTP status, or None when nothing answered."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


Fetch = Callable[[str, str], bytes]


@dataclass(frozen=True)
class Landing:
    """Where a request ended: the first answer that is not a redirect, and the URLs on the way (*hops*)."""

    url: str
    status: int
    body: bytes = b""
    hops: tuple[str, ...] = ()


Trace = Callable[[str, str], Landing]


@dataclass(frozen=True)
class OntologyFacts:
    """What a battinfo.ttl declares: its ``owl:versionIRI``, ``owl:versionInfo`` and ``owl:imports``."""

    version_iri: str | None
    version: str | None
    imports: frozenset[str]


@dataclass(frozen=True)
class Route:
    """An ontology IRI, and the file on GitHub that w3id should send it to (*lands*).

    *interim* is where the IRI leads until a routing change outside this
    repository is merged; landing there is reported as pending, not as a fault.
    """

    iri: str
    lands: str
    interim: str | None = None


def hosted_files(root: Path = ROOT) -> list[HostedFile]:
    """The files the registry serves at w3id IRIs, each with its copy in *root*.

    A schema is served at its ``$id``. One without an ``$id`` is listed with an
    empty URL, which the comparison reports as missing.
    """
    files = [HostedFile(CONTEXT_URL, "application/ld+json", CONTEXT_PATH)]
    for path in sorted((root / SCHEMAS_PATH).rglob("*.json")):
        schema_id = json.loads(path.read_text(encoding="utf-8")).get("$id")
        url = schema_id if isinstance(schema_id, str) else ""
        files.append(HostedFile(url, "application/schema+json, application/json", path.relative_to(root)))
    files.append(HostedFile(VOCABULARY_URL, "text/turtle", VOCABULARY_PATH))
    return files


def normalised_sha256(data: bytes) -> str:
    """The sha256 of *data* with CRLF line endings turned into LF."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _ask(
    open_url: Callable[..., Any],
    request: urllib.request.Request,
    *,
    attempts: int,
    wait: float,
    timeout: float,
    sleep: Callable[[float], None],
    deadline: float | None,
    clock: Callable[[], float],
    source: str = "",
) -> tuple[int, bytes]:
    """Send *request* until a server gives a definite answer; return its status and body.

    No answer, a dropped connection or a status in :data:`RETRY_STATUSES` is
    tried again, up to *attempts* times, waiting *wait* seconds longer before
    each new attempt. Any other HTTP status is a definite answer and comes back
    as the :class:`urllib.error.HTTPError` it was raised as.

    *deadline* is a reading of *clock* after which nothing more is sent: a
    request gets at most the time left, and when that is used up, or too short
    for the next wait, :class:`FetchError` is raised at once, as it is after the
    last attempt. *source* names the URL in that message.
    """
    problem = ""
    for attempt in range(1, attempts + 1):
        left = None if deadline is None else deadline - clock()
        if left is not None and left <= 0:
            if attempt == 1:
                raise FetchError("not asked: the check's time limit had run out")
            raise FetchError(f"no answer{source} before the time limit, after {attempt - 1} attempts ({problem})")
        try:
            with open_url(request, timeout=timeout if left is None else min(timeout, left)) as response:
                return getattr(response, "status", 200), response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_STATUSES:
                raise
            problem = f"HTTP {exc.code}"
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            problem = str(getattr(exc, "reason", exc)) or type(exc).__name__
        if attempt == attempts:
            raise FetchError(f"no answer{source} after {attempts} attempts ({problem})")
        pause = wait * attempt
        if deadline is not None and deadline - clock() <= pause:
            raise FetchError(f"no answer{source} before the time limit, after {attempt} attempts ({problem})")
        sleep(pause)
    raise AssertionError("unreachable")  # pragma: no cover


def fetch(
    url: str,
    accept: str,
    *,
    attempts: int = 4,
    wait: float = 10.0,
    timeout: float = 90.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> bytes:
    """GET *url*, following redirects, and return the body.

    No answer, a dropped connection or a status in :data:`RETRY_STATUSES` is
    tried again, up to *attempts* times, waiting *wait* seconds longer before
    each new attempt, and never past *deadline*, a reading of *clock*. Any
    other HTTP status raises :class:`FetchError` at once.
    """
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
    try:
        _status, body = _ask(
            opener,
            request,
            attempts=attempts,
            wait=wait,
            timeout=timeout,
            sleep=sleep,
            deadline=deadline,
            clock=clock,
        )
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code}", status=exc.code) from exc
    return body


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Hand each redirect back to :func:`trace`, which follows it and notes where it went."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        return None


def trace(
    url: str,
    accept: str,
    *,
    attempts: int = 4,
    wait: float = 10.0,
    timeout: float = 90.0,
    opener: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    max_hops: int = 10,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Landing:
    """GET *url* and follow its redirects one at a time, asking for *accept* each time.

    Return where the request landed: the first answer that is not a redirect,
    whatever its status, so a 404 at the end is a result, not an error. Each
    request is tried again as :func:`fetch` does, within the same *deadline*.
    :class:`FetchError` is raised when a server does not answer, or after
    *max_hops* redirects.
    """
    open_url = opener or urllib.request.build_opener(_NoRedirect).open
    current = url
    hops = [url]
    for _hop in range(max_hops + 1):
        request = urllib.request.Request(current, headers={"Accept": accept, "User-Agent": USER_AGENT})
        try:
            status, body = _ask(
                open_url,
                request,
                attempts=attempts,
                wait=wait,
                timeout=timeout,
                sleep=sleep,
                deadline=deadline,
                clock=clock,
                source=f" from {current}",
            )
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if exc.headers is not None else None
            if exc.code in REDIRECT_STATUSES and location:
                current = urllib.parse.urljoin(current, location)
                hops.append(current)
                continue
            return Landing(current, exc.code, b"", tuple(hops))
        return Landing(current, status, body, tuple(hops))
    raise FetchError(f"more than {max_hops} redirects from {url}")


def compare_files(
    files: Iterable[HostedFile], fetch_file: Fetch, root: Path = ROOT, *, give_up_after: int | None = GIVE_UP_AFTER
) -> list[Outcome]:
    """Compare the hosted copy of each file with its copy in *root*.

    Every file is reached through w3id and the registry, so once
    *give_up_after* files in a row got no answer at all, the remaining files
    are reported unreachable without a request.
    """
    outcomes: list[Outcome] = []
    silent = 0  # files in a row that got no answer
    for hosted_file in files:
        if not hosted_file.url:
            outcomes.append(Outcome(hosted_file, "missing", "it declares no $id, so nothing serves it"))
            continue
        if give_up_after is not None and silent >= give_up_after:
            detail = f"not asked: {silent} files in a row before it got no answer"
            outcomes.append(Outcome(hosted_file, "unreachable", detail))
            continue
        local = normalised_sha256((root / hosted_file.path).read_bytes())
        try:
            served = normalised_sha256(fetch_file(hosted_file.url, hosted_file.accept))
        except FetchError as exc:
            status = "missing" if exc.status == 404 else "unreachable"
            silent = silent + 1 if exc.status is None else 0
            outcomes.append(Outcome(hosted_file, status, str(exc)))
            continue
        silent = 0
        if served == local:
            outcomes.append(Outcome(hosted_file, "same"))
        else:
            outcomes.append(Outcome(hosted_file, "differs", f"hosted sha256 {served}, this checkout {local}"))
    return outcomes


def release_term_problems(release: object, hosted: object) -> list[str]:
    """The terms of the *release* context that the *hosted* context lacks or maps differently.

    Both are parsed context documents. A term only the hosted context has does
    not count: the v1 context only ever gains terms.
    """
    release_terms = release.get("@context") if isinstance(release, dict) else None
    hosted_terms = hosted.get("@context") if isinstance(hosted, dict) else None
    if not isinstance(release_terms, dict):
        return ["the release's context document has no @context object"]
    if not isinstance(hosted_terms, dict):
        return ["the hosted context document has no @context object"]
    problems: list[str] = []
    for term, value in release_terms.items():
        if term not in hosted_terms:
            problems.append(f"{term}: missing")
        elif hosted_terms[term] != value:
            problems.append(f"{term}: {json.dumps(value)} in the release, {json.dumps(hosted_terms[term])} hosted")
    return problems


def latest_release(tags: Iterable[str]) -> str | None:
    """The newest final release tag (vX.Y.Z) among *tags*; pre-release tags such as v0.8.0rc1 do not count."""
    releases = []
    for tag in tags:
        match = FINAL_RELEASE_TAG.fullmatch(tag)
        if match:
            releases.append((tuple(int(part) for part in match.groups()), tag))
    return max(releases)[1] if releases else None


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)


def _report_files(outcomes: list[Outcome]) -> tuple[list[str], list[str]]:
    """Plain lines for the log and Markdown lines for the job summary."""
    counts = {status: sum(1 for o in outcomes if o.status == status) for status in STATUSES}
    log = ["Hosted files compared with this checkout (sha256, LF line endings):"]
    for outcome in outcomes:
        detail = f"  ({outcome.detail})" if outcome.detail else ""
        log.append(f"  {outcome.status:<12} {outcome.file.url or outcome.file.path.as_posix()}{detail}")
    totals = ", ".join(f"{counts[status]} {status}" for status in STATUSES)
    log.append(f"{len(outcomes)} files: {totals}.")
    markdown = ["### Hosted files", "", f"{len(outcomes)} files compared with this commit: {totals}.", ""]
    odd = [outcome for outcome in outcomes if outcome.status != "same"]
    if odd:
        markdown += ["| File | Result | Detail |", "|---|---|---|"]
        markdown += [f"| {o.file.url or o.file.path.as_posix()} | {o.status} | {o.detail} |" for o in odd]
    return log, markdown


def check_files(fetch_file: Fetch, root: Path = ROOT) -> tuple[int, list[str], list[str]]:
    """Compare every hosted file; return the exit status, the log and the Markdown summary."""
    outcomes = compare_files(hosted_files(root), fetch_file, root)
    log, markdown = _report_files(outcomes)
    return (0 if all(outcome.status == "same" for outcome in outcomes) else 1), log, markdown


def check_release_terms(fetch_file: Fetch, tag: str | None, root: Path = ROOT) -> tuple[int, list[str], list[str]]:
    """Check the hosted v1 context against the terms of release *tag* (default: the newest final tag)."""
    if tag is None:
        listed = _git(root, "tag", "--list", "v*")
        tag = latest_release(listed.stdout.decode().split()) if listed.returncode == 0 else None
        if tag is None:
            message = "No vX.Y.Z tag found in this checkout. Fetch the tags (actions/checkout with fetch-depth: 0)."
            return 1, [message], ["### Hosted context", "", message]
    if _git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}").returncode != 0:
        message = f"There is no tag {tag} in this checkout."
        return 1, [message], ["### Hosted context", "", message]
    shown = _git(root, "show", f"{tag}:{CONTEXT_PATH.as_posix()}")
    if shown.returncode != 0:
        message = f"{tag} has no {CONTEXT_PATH.as_posix()}, so there are no released terms to check."
        return 0, [message], ["### Hosted context", "", message]
    release = json.loads(shown.stdout.decode("utf-8"))
    try:
        hosted = json.loads(fetch_file(CONTEXT_URL, "application/ld+json").decode("utf-8"))
    except FetchError as exc:
        message = f"{CONTEXT_URL} could not be fetched: {exc}."
        return 1, [message], ["### Hosted context", "", message]
    except ValueError as exc:
        message = f"{CONTEXT_URL} is not JSON: {exc}."
        return 1, [message], ["### Hosted context", "", message]
    problems = release_term_problems(release, hosted)
    released = release.get("@context") if isinstance(release, dict) else None
    count = len(released) if isinstance(released, dict) else 0
    if problems:
        head = f"The hosted v1 context lacks or changed {len(problems)} of the {count} terms of {tag}:"
    else:
        head = f"The hosted v1 context holds all {count} terms of {tag} with the same values."
    log = [head, *(f"  {problem}" for problem in problems)]
    markdown = ["### Hosted context", "", f"{head} Terms added since {tag} are not checked.", ""]
    markdown += [f"- {problem}" for problem in problems]
    return (1 if problems else 0), log, markdown


_VERSION_IRI = re.compile(r"(?:owl:versionIRI|<http://www\.w3\.org/2002/07/owl#versionIRI>)\s+<([^>]+)>")
_VERSION_INFO = re.compile(r'(?:owl:versionInfo|<http://www\.w3\.org/2002/07/owl#versionInfo>)\s+"([^"]*)"')
_IMPORTS = re.compile(r"(?:owl:imports|<http://www\.w3\.org/2002/07/owl#imports>)\s+<([^>]+)>")


def ontology_facts(turtle: bytes) -> OntologyFacts:
    """Read the version IRI, the version and the imports from a battinfo.ttl laid out as this repository's."""
    text = turtle.decode("utf-8", errors="replace")
    version_iri = _VERSION_IRI.search(text)
    version = _VERSION_INFO.search(text)
    return OntologyFacts(
        version_iri.group(1) if version_iri else None,
        version.group(1) if version else None,
        frozenset(_IMPORTS.findall(text)),
    )


def ontology_routes(facts: OntologyFacts, version: str, *, latest: bool) -> list[Route]:
    """The ontology IRIs of release *version* and where w3id should send each one."""
    versioned = f"{PAGES}/battinfo/versions/{version}/battinfo.ttl"
    routes = [Route(ONTOLOGY_IRI, f"{PAGES}/battinfo.ttl")]
    if latest:
        routes.append(Route(LATEST_IRI, LATEST_FILE, interim=LATEST_FILE_ON_MASTER))
    routes.append(Route(f"{ONTOLOGY_IRI}/{version}", versioned))
    if facts.version_iri:
        routes.append(Route(facts.version_iri, versioned))
    return routes


def _describe(facts: OntologyFacts) -> str:
    return f"versionIRI {facts.version_iri}, imports {', '.join(sorted(facts.imports)) or 'none'}"


def _ontology_outcome(route: Route, landing: Landing, expected: bytes, *, by_imports: bool, served: bool) -> Outcome:
    """Compare where *route* landed, and what it served, with the *expected* battinfo.ttl."""
    hosted_file = HostedFile(route.iri, "text/turtle", ONTOLOGY_PATH)
    where = f"lands on {landing.url} (HTTP {landing.status})"
    if landing.url != route.lands:
        if route.interim is not None and landing.url == route.interim:
            detail = f"{where}, where it leads until the perma-id change to {route.lands} is merged"
            return Outcome(hosted_file, "pending", detail)
        return Outcome(hosted_file, "misrouted", f"{where}, expected {route.lands}")
    if landing.status != 200:
        return Outcome(hosted_file, "missing" if served else "routed", where)
    if by_imports:
        hosted, wanted = ontology_facts(landing.body), ontology_facts(expected)
        same = (hosted.version_iri, hosted.imports) == (wanted.version_iri, wanted.imports)
        if not same:
            return Outcome(hosted_file, "differs", f"{where}: {_describe(hosted)}; expected {_describe(wanted)}")
        return Outcome(hosted_file, "same", where)
    if normalised_sha256(landing.body) == normalised_sha256(expected):
        return Outcome(hosted_file, "same", where)
    if not served:
        return Outcome(hosted_file, "routed", f"{where}, serving another battinfo.ttl")
    detail = f"{where}: hosted sha256 {normalised_sha256(landing.body)}, expected {normalised_sha256(expected)}"
    return Outcome(hosted_file, "differs", detail)


def _report_ontology(outcomes: list[Outcome], head: str) -> tuple[list[str], list[str]]:
    counts = {status: sum(1 for o in outcomes if o.status == status) for status in ONTOLOGY_STATUSES}
    totals = ", ".join(f"{counts[status]} {status}" for status in ONTOLOGY_STATUSES if counts[status])
    log = [head]
    for outcome in outcomes:
        detail = f"  ({outcome.detail})" if outcome.detail else ""
        log.append(f"  {outcome.status:<12} {outcome.file.url}{detail}")
    log.append(f"{len(outcomes)} IRIs: {totals}.")
    markdown = ["### Hosted ontology", "", head, "", "| IRI | Result | Detail |", "|---|---|---|"]
    markdown += [f"| {o.file.url} | {o.status} | {o.detail} |" for o in outcomes]
    return log, markdown


def _trace_routes(
    trace_url: Trace, routes: list[Route], expected: bytes, *, served: bool, root_by_imports: bool
) -> list[Outcome]:
    outcomes = []
    for route in routes:
        try:
            landing = trace_url(route.iri, "text/turtle")
        except FetchError as exc:
            outcomes.append(Outcome(HostedFile(route.iri, "text/turtle", ONTOLOGY_PATH), "unreachable", str(exc)))
            continue
        by_imports = root_by_imports and route.iri == ONTOLOGY_IRI
        outcomes.append(_ontology_outcome(route, landing, expected, by_imports=by_imports, served=served))
    return outcomes


def check_ontology_routes(
    trace_url: Trace, *, served: bool = False, root: Path = ROOT
) -> tuple[int, list[str], list[str]]:
    """Check where the ontology IRIs of this checkout's battinfo.ttl land, and with *served* what they serve."""
    expected = (root / ONTOLOGY_PATH).read_bytes()
    facts = ontology_facts(expected)
    if not facts.version or not facts.version_iri:
        message = f"{ONTOLOGY_PATH} declares no owl:versionInfo or owl:versionIRI."
        return 1, [message], ["### Hosted ontology", "", message]
    routes = ontology_routes(facts, facts.version, latest=True)
    outcomes = _trace_routes(trace_url, routes, expected, served=served, root_by_imports=False)
    # /latest still on master is reported but never fails the check: the
    # perma-id pull request that moves it has its own review, outside this
    # repository, and does not block a release.
    passing = {"same", "pending"} if served else {"same", "routed", "pending"}
    if served:
        head = f"The w3id ontology IRIs, which must serve this checkout's battinfo.ttl ({facts.version}):"
    else:
        head = f"Where the w3id ontology IRIs of this checkout's battinfo.ttl ({facts.version}) land:"
    log, markdown = _report_ontology(outcomes, head)
    return (0 if all(o.status in passing for o in outcomes) else 1), log, markdown


def check_ontology(trace_url: Trace, tag: str | None, root: Path = ROOT) -> tuple[int, list[str], list[str]]:
    """Check that the ontology IRIs serve the battinfo.ttl of release *tag* (default: the newest final tag)."""
    if tag is None:
        listed = _git(root, "tag", "--list", "v*")
        tag = latest_release(listed.stdout.decode().split()) if listed.returncode == 0 else None
        if tag is None:
            message = "No vX.Y.Z tag found in this checkout. Fetch the tags (actions/checkout with fetch-depth: 0)."
            return 1, [message], ["### Hosted ontology", "", message]
    match = FINAL_RELEASE_TAG.fullmatch(tag)
    if match is None or _git(root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}").returncode != 0:
        message = f"There is no final release tag {tag} in this checkout."
        return 1, [message], ["### Hosted ontology", "", message]
    if tuple(int(part) for part in match.groups()) < FIRST_ONTOLOGY_RELEASE:
        first = ".".join(str(part) for part in FIRST_ONTOLOGY_RELEASE)
        message = (
            f"{tag} predates {first}, the first release whose docs deploy published the ontology; nothing to check."
        )
        return 0, [message], ["### Hosted ontology", "", message]
    shown = _git(root, "show", f"{tag}:{ONTOLOGY_PATH.as_posix()}")
    if shown.returncode != 0:
        message = f"{tag} has no {ONTOLOGY_PATH.as_posix()}."
        return 1, [message], ["### Hosted ontology", "", message]
    expected = shown.stdout
    facts = ontology_facts(expected)
    version = tag[1:]
    routes = ontology_routes(facts, version, latest=False)
    outcomes = _trace_routes(trace_url, routes, expected, served=True, root_by_imports=True)
    problems = []
    if facts.version != version or not facts.version_iri:
        problems.append(f"{tag}'s own battinfo.ttl declares version {facts.version} and versionIRI {facts.version_iri}")
    status = 0 if not problems and all(o.status == "same" for o in outcomes) else 1
    if status == 0:
        head = f"The w3id ontology IRIs serve the battinfo.ttl of {tag}."
    else:
        head = f"The w3id ontology IRIs do not all serve the battinfo.ttl of {tag}:"
    log, markdown = _report_ontology(outcomes, head)
    return status, [*problems, *log], [*markdown, *(f"- {problem}" for problem in problems)]


def main(
    argv: list[str] | None = None,
    *,
    fetch_file: Fetch | None = None,
    trace_url: Trace | None = None,
    root: Path = ROOT,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--release-terms",
        action="store_true",
        help="check that the hosted v1 context holds the last release's terms, instead of comparing every file",
    )
    mode.add_argument(
        "--ontology",
        action="store_true",
        help="check that the w3id ontology IRIs serve the last release's battinfo.ttl",
    )
    mode.add_argument(
        "--ontology-routes",
        action="store_true",
        help="check where the w3id ontology IRIs of this checkout's battinfo.ttl land",
    )
    parser.add_argument(
        "--served",
        action="store_true",
        help="with --ontology-routes: each IRI must also serve this checkout's battinfo.ttl (after the tag)",
    )
    parser.add_argument(
        "--tag",
        help="with --release-terms or --ontology: the release to check against (default: the newest vX.Y.Z tag)",
    )
    parser.add_argument(
        "--summary", type=Path, help="append a Markdown summary to this file, such as $GITHUB_STEP_SUMMARY"
    )
    parser.add_argument("--attempts", type=int, default=4, help="requests per file before giving up (default 4)")
    parser.add_argument(
        "--wait", type=float, default=10.0, help="seconds before the second request; each later one waits longer"
    )
    parser.add_argument(
        "--deadline",
        type=float,
        default=DEFAULT_DEADLINE,
        help=(
            f"seconds the run may spend asking (default {DEFAULT_DEADLINE:.0f}); after that, what has not "
            "answered is reported unreachable, so the run always ends with a report"
        ),
    )
    args = parser.parse_args(argv)
    if args.served and not args.ontology_routes:
        parser.error("--served goes with --ontology-routes")
    if args.tag and not (args.release_terms or args.ontology):
        parser.error("--tag goes with --release-terms or --ontology")
    if args.deadline <= 0:
        parser.error("--deadline must be a positive number of seconds")
    deadline = time.monotonic() + args.deadline

    if fetch_file is None:

        def fetch_file(url: str, accept: str) -> bytes:
            return fetch(url, accept, attempts=args.attempts, wait=args.wait, deadline=deadline)

    if trace_url is None:

        def trace_url(url: str, accept: str) -> Landing:
            return trace(url, accept, attempts=args.attempts, wait=args.wait, deadline=deadline)

    if args.release_terms:
        status, log, markdown = check_release_terms(fetch_file, args.tag, root)
    elif args.ontology:
        status, log, markdown = check_ontology(trace_url, args.tag, root)
    elif args.ontology_routes:
        status, log, markdown = check_ontology_routes(trace_url, served=args.served, root=root)
    else:
        status, log, markdown = check_files(fetch_file, root)
    print("\n".join(log))
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(markdown) + "\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
