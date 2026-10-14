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
  serves for a vocabulary term IRI such as https://w3id.org/battinfo/sourceType.

``.github/workflows/release.yml`` runs it before an upload, and a mismatch
blocks only a final release tag. With ``--release-terms`` it checks instead
that the hosted context still holds every term of the last release's v1
context with the same value, so terms added on main since that release do not
count; ``.github/workflows/hosted-files.yml`` runs that every day.

A request is tried again when the server is busy or does not answer, since the
registry's host can take a minute to wake up.

Usage::

    python scripts/check_hosted_files.py [--summary FILE]
    python scripts/check_hosted_files.py --release-terms [--tag vX.Y.Z] [--summary FILE]

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
# w3id forwards any bare term IRI to the registry, which answers with a 303 to
# /vocab/battinfo-records.ttl, so this IRI stands for the vocabulary document.
VOCABULARY_URL = "https://w3id.org/battinfo/sourceType"

FINAL_RELEASE_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
USER_AGENT = "battinfo-hosted-check (+https://github.com/BIG-MAP/BattINFO)"
# Statuses that mean "busy or waking up, ask again"; any other is the answer.
RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
# How a hosted file can compare with the checkout's copy, in report order.
STATUSES = ("same", "differs", "missing", "unreachable")


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


def fetch(
    url: str,
    accept: str,
    *,
    attempts: int = 4,
    wait: float = 10.0,
    timeout: float = 90.0,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    """GET *url*, following redirects, and return the body.

    No answer, a dropped connection or a status in :data:`RETRY_STATUSES` is
    tried again, up to *attempts* times, waiting *wait* seconds longer before
    each new attempt. Any other HTTP status raises :class:`FetchError` at once.
    """
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": USER_AGENT})
    for attempt in range(1, attempts + 1):
        try:
            with opener(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_STATUSES:
                raise FetchError(f"HTTP {exc.code}", status=exc.code) from exc
            problem = f"HTTP {exc.code}"
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            problem = str(getattr(exc, "reason", exc)) or type(exc).__name__
        if attempt == attempts:
            raise FetchError(f"no answer after {attempts} attempts ({problem})")
        sleep(wait * attempt)
    raise AssertionError("unreachable")  # pragma: no cover


def compare_files(files: Iterable[HostedFile], fetch_file: Fetch, root: Path = ROOT) -> list[Outcome]:
    """Compare the hosted copy of each file with its copy in *root*."""
    outcomes: list[Outcome] = []
    for hosted_file in files:
        if not hosted_file.url:
            outcomes.append(Outcome(hosted_file, "missing", "it declares no $id, so nothing serves it"))
            continue
        local = normalised_sha256((root / hosted_file.path).read_bytes())
        try:
            served = normalised_sha256(fetch_file(hosted_file.url, hosted_file.accept))
        except FetchError as exc:
            status = "missing" if exc.status == 404 else "unreachable"
            outcomes.append(Outcome(hosted_file, status, str(exc)))
            continue
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


def main(argv: list[str] | None = None, *, fetch_file: Fetch | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--release-terms",
        action="store_true",
        help="check that the hosted v1 context holds the last release's terms, instead of comparing every file",
    )
    parser.add_argument(
        "--tag", help="with --release-terms: the release to check against (default: the newest vX.Y.Z tag)"
    )
    parser.add_argument(
        "--summary", type=Path, help="append a Markdown summary to this file, such as $GITHUB_STEP_SUMMARY"
    )
    parser.add_argument("--attempts", type=int, default=4, help="requests per file before giving up (default 4)")
    parser.add_argument(
        "--wait", type=float, default=10.0, help="seconds before the second request; each later one waits longer"
    )
    args = parser.parse_args(argv)

    if fetch_file is None:

        def fetch_file(url: str, accept: str) -> bytes:
            return fetch(url, accept, attempts=args.attempts, wait=args.wait)

    if args.release_terms:
        status, log, markdown = check_release_terms(fetch_file, args.tag, root)
    else:
        status, log, markdown = check_files(fetch_file, root)
    print("\n".join(log))
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(markdown) + "\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
