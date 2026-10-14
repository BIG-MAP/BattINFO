"""scripts/check_hosted_files.py: the files w3id serves against this checkout's copies.

release.yml runs the script before an upload: every hosted file (the v1
records context, each JSON Schema at its $id, the record vocabulary) must have
the sha256 of the checkout's copy, line endings aside. The scheduled workflow
runs it with --release-terms: the hosted context must still hold the last
release's terms with the same values, and terms added since do not count.
The ontology IRIs are checked with --ontology-routes before a tag and with
--ontology after it. Nothing here reaches the network: the fetches are
answered from memory.
"""

from __future__ import annotations

import email.message
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("check_hosted_files", ROOT / "scripts" / "check_hosted_files.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check = _load()


class _Hosted:
    """Answers each URL with the checkout's copy, unless told otherwise."""

    def __init__(self, root: Path = ROOT) -> None:
        self.by_url = {f.url: (root / f.path).read_bytes() for f in check.hosted_files(root)}
        self.requests: list[tuple[str, str]] = []

    def __call__(self, url: str, accept: str) -> bytes:
        self.requests.append((url, accept))
        body = self.by_url.get(url)
        if isinstance(body, Exception):
            raise body
        if body is None:
            raise check.FetchError("HTTP 404", status=404)
        return body


def test_the_hosted_files_are_the_context_every_schema_at_its_id_and_the_vocabulary() -> None:
    files = check.hosted_files()
    by_path = {f.path.as_posix(): f for f in files}

    context = by_path["src/battinfo/data/context/records.context.v1.json"]
    assert context.url == "https://w3id.org/battinfo/context/records/v1.json"
    assert context.accept == "application/ld+json"

    schemas = sorted((ROOT / "src/battinfo/data/schemas").rglob("*.json"))
    assert len(schemas) >= 40
    for path in schemas:
        relative = path.relative_to(ROOT).as_posix()
        schema_id = json.loads(path.read_text(encoding="utf-8"))["$id"]
        assert by_path[relative].url == schema_id
        assert schema_id.startswith("https://w3id.org/battinfo/schema/")

    vocabulary = by_path["assets/vocab/battinfo-records.ttl"]
    assert vocabulary.url == "https://w3id.org/battinfo/sourceType"
    assert vocabulary.accept == "text/turtle"
    assert len(files) == len(schemas) + 2


def test_hosted_files_equal_to_the_checkout_pass(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    hosted = _Hosted()
    summary = tmp_path / "summary.md"

    assert check.main(["--summary", str(summary)], fetch_file=hosted) == 0

    assert len(hosted.requests) == len(check.hosted_files())
    out = capsys.readouterr().out
    assert f"{len(hosted.requests)} files: {len(hosted.requests)} same, 0 differs, 0 missing, 0 unreachable." in out
    assert "### Hosted files" in summary.read_text(encoding="utf-8")


def test_line_endings_do_not_count() -> None:
    hosted = _Hosted()
    hosted.by_url[check.CONTEXT_URL] = hosted.by_url[check.CONTEXT_URL].replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    status, _log, _markdown = check.check_files(hosted)
    assert status == 0


def test_a_hosted_file_that_differs_fails_and_is_named(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    hosted = _Hosted()
    url = "https://w3id.org/battinfo/schema/cell-spec.schema.json"
    stale = json.loads(hosted.by_url[url])
    stale["title"] = "an older copy"
    hosted.by_url[url] = json.dumps(stale).encode("utf-8")
    summary = tmp_path / "summary.md"

    assert check.main(["--summary", str(summary)], fetch_file=hosted) == 1

    out = capsys.readouterr().out
    assert f"differs      {url}  (hosted sha256 " in out
    assert "1 differs" in out
    assert f"| {url} | differs |" in summary.read_text(encoding="utf-8")


def test_a_file_that_is_not_served_or_cannot_be_fetched_fails() -> None:
    hosted = _Hosted()
    missing = "https://w3id.org/battinfo/schema/test.schema.json"
    del hosted.by_url[missing]
    hosted.by_url[check.VOCABULARY_URL] = check.FetchError("no answer after 4 attempts (timed out)")

    status, log, _markdown = check.check_files(hosted)

    assert status == 1
    text = "\n".join(log)
    assert f"missing      {missing}  (HTTP 404)" in text
    assert f"unreachable  {check.VOCABULARY_URL}  (no answer after 4 attempts (timed out))" in text


class _Reply(io.BytesIO):
    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _busy(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "busy", None, io.BytesIO(b""))  # type: ignore[arg-type]


URL = "https://w3id.org/battinfo/sourceType"


def test_a_busy_or_silent_server_is_asked_again_with_growing_waits() -> None:
    answers: list[object] = [_busy(URL, 503), urllib.error.URLError("timed out"), _Reply(b"body")]
    waits: list[float] = []

    def opener(request, timeout):  # noqa: ANN001, ANN202
        assert request.get_header("Accept") == "text/turtle"
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert check.fetch(URL, "text/turtle", attempts=4, wait=10, opener=opener, sleep=waits.append) == b"body"
    assert waits == [10, 20]


def test_a_definite_answer_is_not_asked_again_and_attempts_are_limited() -> None:
    calls: list[int] = []

    def not_found(request, timeout):  # noqa: ANN001, ANN202
        calls.append(1)
        raise _busy(URL, 404)

    with pytest.raises(check.FetchError) as excinfo:
        check.fetch(URL, "text/turtle", attempts=4, opener=not_found, sleep=lambda _: None)
    assert excinfo.value.status == 404 and len(calls) == 1

    def silent(request, timeout):  # noqa: ANN001, ANN202
        calls.append(1)
        raise urllib.error.URLError("timed out")

    calls.clear()
    with pytest.raises(check.FetchError, match="no answer after 3 attempts") as excinfo:
        check.fetch(URL, "text/turtle", attempts=3, opener=silent, sleep=lambda _: None)
    assert excinfo.value.status is None and len(calls) == 3


def test_the_newest_final_release_tag_is_the_last_release() -> None:
    tags = ["v0.2.0", "v0.6.0", "test", "0.5.0", "v0.10.0rc1", "v0.9.1", "v0.10.0.dev1", "v0.8.0"]
    assert check.latest_release(tags) == "v0.9.1"
    assert check.latest_release([*tags, "v0.10.0"]) == "v0.10.0"
    assert check.latest_release(["v0.8.0rc1", "test"]) is None


RELEASED = {"@context": {"@version": 1.1, "battinfo": "https://w3id.org/battinfo/", "degC": "emmo:DegreeCelsius"}}


def test_the_hosted_context_may_add_terms_to_the_release() -> None:
    hosted = {"@context": {**RELEASED["@context"], "NewTerm": "battinfo:NewTerm"}}
    assert check.release_term_problems(RELEASED, hosted) == []


def test_a_released_term_that_changed_or_went_missing_is_a_problem() -> None:
    changed = {"@context": {**RELEASED["@context"], "degC": "emmo:EMMO_36a9bf69"}}
    assert check.release_term_problems(RELEASED, changed) == [
        'degC: "emmo:DegreeCelsius" in the release, "emmo:EMMO_36a9bf69" hosted'
    ]
    dropped = {"@context": {k: v for k, v in RELEASED["@context"].items() if k != "battinfo"}}
    assert check.release_term_problems(RELEASED, dropped) == ["battinfo: missing"]
    assert check.release_term_problems(RELEASED, {"terms": {}}) == [
        "the hosted context document has no @context object"
    ]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
        check=True,
        capture_output=True,
    )


@pytest.fixture()
def releases(tmp_path: Path) -> Path:
    """A repository whose v0.6.0 has no records context and whose v0.8.0 has RELEASED."""
    if shutil.which("git") is None:
        pytest.skip("needs git")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "README.md").write_text("ontology only\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "0.6.0")
    _git(repo, "tag", "v0.6.0")
    context = repo / check.CONTEXT_PATH
    context.parent.mkdir(parents=True)
    context.write_text(json.dumps(RELEASED), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "0.8.0")
    _git(repo, "tag", "v0.8.0")
    _git(repo, "tag", "v0.9.0rc1")  # a pre-release is never the last release
    return repo


def _serving(context: dict) -> _Hosted:
    hosted = _Hosted()
    hosted.by_url = {check.CONTEXT_URL: json.dumps(context).encode("utf-8")}
    return hosted


def test_the_scheduled_check_compares_with_the_newest_release(
    releases: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    grown = {"@context": {**RELEASED["@context"], "NewTerm": "battinfo:NewTerm"}}
    assert check.main(["--release-terms"], fetch_file=_serving(grown), root=releases) == 0
    assert "holds all 3 terms of v0.8.0 with the same values" in capsys.readouterr().out

    changed = {"@context": {**RELEASED["@context"], "degC": "emmo:EMMO_36a9bf69"}}
    assert check.main(["--release-terms"], fetch_file=_serving(changed), root=releases) == 1
    out = capsys.readouterr().out
    assert "lacks or changed 1 of the 3 terms of v0.8.0" in out and "degC:" in out


def test_a_release_without_the_records_context_has_no_terms_to_check(
    releases: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check.main(["--release-terms", "--tag", "v0.6.0"], fetch_file=_serving({}), root=releases) == 0
    assert "v0.6.0 has no src/battinfo/data/context/records.context.v1.json" in capsys.readouterr().out
    assert check.main(["--release-terms", "--tag", "v9.9.9"], fetch_file=_serving({}), root=releases) == 1


def test_without_tags_the_scheduled_check_fails_rather_than_pass_unchecked(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("needs git")
    _git(tmp_path, "init", "-q")
    status, log, _markdown = check.check_release_terms(_serving(RELEASED), None, tmp_path)
    assert status == 1 and "No vX.Y.Z tag found" in log[0]


# ── The ontology at its w3id IRIs ──
#
# docs-deploy.sh publishes battinfo.ttl on GitHub Pages for each final release:
# at battinfo/versions/X.Y.Z/, where w3id sends https://w3id.org/battinfo/X.Y.Z,
# and at the root, where w3id sends https://w3id.org/battinfo. The registry
# answers the versionIRI, https://w3id.org/battinfo/X.Y.Z/battinfo, with a 303 to
# https://w3id.org/battinfo/X.Y.Z. --ontology-routes checks where each IRI
# leads, before the tag; --ontology checks, after it and every day, that they
# serve the last release's battinfo.ttl.

PAGES = "https://big-map.github.io/BattINFO"
OLD_IMPORT = "https://w3id.org/emmo/domain/battery/0.13.0-beta/battery"
IMPORTS = [
    "https://w3id.org/emmo/domain/battery/0.21.0/battery",
    "https://w3id.org/emmo/domain/electrochemistry/0.39.0/electrochemistry",
]


def _ontology(version: str, imports: list[str] = IMPORTS, version_iri: str | None = None) -> bytes:
    """A battinfo.ttl laid out as the real one, declaring *version*."""
    iri = version_iri or f"https://w3id.org/battinfo/{version}/battinfo"
    lines = ["@prefix owl: <http://www.w3.org/2002/07/owl#> .", "@prefix battinfo: <https://w3id.org/battinfo#> .", ""]
    lines += ["battinfo: a owl:Ontology ;", f"    owl:versionIRI <{iri}> ;"]
    lines += [f"    owl:imports <{import_iri}> ;" for import_iri in imports]
    lines += [f'    owl:versionInfo "{version}" .', ""]
    return "\n".join(lines).encode("utf-8")


def _landings(ttl: bytes, version: str) -> dict[str, object]:
    """Where each ontology IRI lands once *version* is released and deployed, serving *ttl*."""
    versioned = f"{PAGES}/battinfo/versions/{version}/battinfo.ttl"
    return {
        "https://w3id.org/battinfo": check.Landing(f"{PAGES}/battinfo.ttl", 200, ttl),
        "https://w3id.org/battinfo/latest": check.Landing(check.LATEST_FILE, 200, ttl),
        f"https://w3id.org/battinfo/{version}": check.Landing(versioned, 200, ttl),
        f"https://w3id.org/battinfo/{version}/battinfo": check.Landing(versioned, 200, ttl),
    }


class _Traced:
    """Answers each ontology IRI from a table of landings, and records what was asked."""

    def __init__(self, landings: dict[str, object]) -> None:
        self.landings = landings
        self.requests: list[tuple[str, str]] = []

    def __call__(self, url: str, accept: str) -> object:
        self.requests.append((url, accept))
        landing = self.landings[url]
        if isinstance(landing, Exception):
            raise landing
        return landing


def test_ontology_facts_read_the_version_iri_and_the_imports() -> None:
    facts = check.ontology_facts((ROOT / "battinfo.ttl").read_bytes())
    assert facts.version_iri == f"https://w3id.org/battinfo/{facts.version}/battinfo"
    assert "https://w3id.org/emmo/domain/battery/0.21.0/battery" in facts.imports
    assert len(facts.imports) == 3
    old = check.ontology_facts(_ontology("0.8.0-beta", [OLD_IMPORT]).replace(b"\n", b"\r\n"))
    assert old == check.OntologyFacts(
        "https://w3id.org/battinfo/0.8.0-beta/battinfo", "0.8.0-beta", frozenset([OLD_IMPORT])
    )


@pytest.fixture()
def ontology_releases(tmp_path: Path) -> Path:
    """A repository whose v0.6.0 predates the ontology deploy and whose v0.8.0 has a battinfo.ttl for 0.8.0."""
    if shutil.which("git") is None:
        pytest.skip("needs git")
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "battinfo.ttl").write_bytes(_ontology("0.6.0", [OLD_IMPORT]))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "0.6.0")
    _git(repo, "tag", "v0.6.0")
    (repo / "battinfo.ttl").write_bytes(_ontology("0.8.0"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "0.8.0")
    _git(repo, "tag", "v0.8.0")
    _git(repo, "tag", "v0.9.0rc1")  # a pre-release is never the last release
    return repo


def test_the_ontology_check_passes_when_every_iri_serves_the_last_release(
    ontology_releases: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    traced = _Traced(_landings(_ontology("0.8.0"), "0.8.0"))
    summary = tmp_path / "summary.md"
    assert check.main(["--ontology", "--summary", str(summary)], trace_url=traced, root=ontology_releases) == 0
    out = capsys.readouterr().out
    assert "serve the battinfo.ttl of v0.8.0" in out
    # Not /latest, which follows main rather than the release.
    assert {url for url, _accept in traced.requests} == {
        "https://w3id.org/battinfo",
        "https://w3id.org/battinfo/0.8.0",
        "https://w3id.org/battinfo/0.8.0/battinfo",
    }
    assert {accept for _url, accept in traced.requests} == {"text/turtle"}
    assert "### Hosted ontology" in summary.read_text(encoding="utf-8")


def test_a_root_that_still_serves_an_older_ontology_fails(
    ontology_releases: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    landings = _landings(_ontology("0.8.0"), "0.8.0")
    stale = _ontology("0.8.0-beta", [OLD_IMPORT])
    landings["https://w3id.org/battinfo"] = check.Landing(f"{PAGES}/battinfo.ttl", 200, stale)
    assert check.main(["--ontology"], trace_url=_Traced(landings), root=ontology_releases) == 1
    out = capsys.readouterr().out
    assert "differs      https://w3id.org/battinfo  (" in out
    assert "0.8.0-beta" in out and OLD_IMPORT in out


def test_a_version_iri_the_registry_does_not_route_yet_fails(
    ontology_releases: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    landings = _landings(_ontology("0.8.0"), "0.8.0")
    registry = "https://battinfo-registry.onrender.com/w3id/0.8.0/battinfo"
    landings["https://w3id.org/battinfo/0.8.0/battinfo"] = check.Landing(registry, 404)
    assert check.main(["--ontology"], trace_url=_Traced(landings), root=ontology_releases) == 1
    out = capsys.readouterr().out
    assert f"misrouted    https://w3id.org/battinfo/0.8.0/battinfo  (lands on {registry} (HTTP 404)" in out


def test_a_version_folder_that_is_not_deployed_fails(ontology_releases: Path) -> None:
    landings = _landings(_ontology("0.8.0"), "0.8.0")
    landings["https://w3id.org/battinfo/0.8.0"] = check.Landing(f"{PAGES}/battinfo/versions/0.8.0/battinfo.ttl", 404)
    landings["https://w3id.org/battinfo/0.8.0/battinfo"] = check.FetchError("no answer after 4 attempts (timed out)")
    status, log, _markdown = check.check_ontology(_Traced(landings), None, ontology_releases)
    assert status == 1
    text = "\n".join(log)
    assert (
        f"missing      https://w3id.org/battinfo/0.8.0  (lands on {PAGES}/battinfo/versions/0.8.0/battinfo.ttl (HTTP 404)"
        in text
    )
    assert "unreachable  https://w3id.org/battinfo/0.8.0/battinfo  (no answer after 4 attempts" in text


def test_a_release_before_the_ontology_deploy_has_nothing_to_check(
    ontology_releases: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    traced = _Traced({})
    assert check.main(["--ontology", "--tag", "v0.6.0"], trace_url=traced, root=ontology_releases) == 0
    assert "v0.6.0 predates" in capsys.readouterr().out
    assert traced.requests == []
    assert check.main(["--ontology", "--tag", "v9.9.9"], trace_url=traced, root=ontology_releases) == 1


def test_without_tags_the_ontology_check_fails_rather_than_pass_unchecked(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("needs git")
    _git(tmp_path, "init", "-q")
    status, log, _markdown = check.check_ontology(_Traced({}), None, tmp_path)
    assert status == 1 and "No vX.Y.Z tag found" in log[0]


def _before_the_tag() -> dict[str, object]:
    """w3id routes every IRI right, but only the file at /latest is this release's yet."""
    ttl = (ROOT / "battinfo.ttl").read_bytes()
    version = check.ontology_facts(ttl).version
    assert version
    landings = _landings(ttl, version)
    landings["https://w3id.org/battinfo"] = check.Landing(f"{PAGES}/battinfo.ttl", 200, _ontology("0.8.0-beta"))
    for iri in (f"https://w3id.org/battinfo/{version}", f"https://w3id.org/battinfo/{version}/battinfo"):
        landing = landings[iri]
        assert isinstance(landing, check.Landing)
        landings[iri] = check.Landing(landing.url, 404)
    return landings


def test_before_the_tag_the_routes_check_passes_when_each_iri_leads_where_w3id_should_send_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    traced = _Traced(_before_the_tag())
    assert check.main(["--ontology-routes"], trace_url=traced) == 0
    out = capsys.readouterr().out
    assert f"https://w3id.org/battinfo/latest  (lands on {check.LATEST_FILE}" in out
    assert len(traced.requests) == 4
    # After the tag, every IRI must also serve the battinfo.ttl of the checkout.
    assert check.main(["--ontology-routes", "--served"], trace_url=_Traced(_before_the_tag())) == 1


def test_a_route_that_leads_elsewhere_fails(capsys: pytest.CaptureFixture[str]) -> None:
    landings = _before_the_tag()
    master = "https://raw.githubusercontent.com/BIG-MAP/BattINFO/master/battinfo.ttl"
    landings["https://w3id.org/battinfo/latest"] = check.Landing(master, 200, _ontology("0.8.0-beta"))
    assert check.main(["--ontology-routes"], trace_url=_Traced(landings)) == 1
    assert f"misrouted    https://w3id.org/battinfo/latest  (lands on {master}" in capsys.readouterr().out


def test_after_the_tag_every_route_serves_the_ontology_of_the_checkout() -> None:
    ttl = (ROOT / "battinfo.ttl").read_bytes()
    version = check.ontology_facts(ttl).version
    assert version
    assert check.main(["--ontology-routes", "--served"], trace_url=_Traced(_landings(ttl, version))) == 0


def test_served_belongs_to_the_routes_check() -> None:
    with pytest.raises(SystemExit):
        check.main(["--ontology", "--served"], trace_url=_Traced({}))


class _Answer(io.BytesIO):
    """A response to one request, as urlopen gives it."""

    def __init__(self, body: bytes = b"", status: int = 200) -> None:
        super().__init__(body)
        self.status = status

    def __enter__(self) -> _Answer:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _redirect(url: str, code: int, location: str) -> urllib.error.HTTPError:
    headers = email.message.Message()
    headers["Location"] = location
    return urllib.error.HTTPError(url, code, "See Other", headers, io.BytesIO(b""))


def test_trace_follows_each_redirect_and_reports_where_it_lands() -> None:
    answers: dict[str, list[object]] = {
        "https://w3id.org/battinfo": [_redirect("https://w3id.org/battinfo", 301, "/battinfo/")],
        "https://w3id.org/battinfo/": [_redirect("https://w3id.org/battinfo/", 303, f"{PAGES}/battinfo.ttl")],
        f"{PAGES}/battinfo.ttl": [_busy(f"{PAGES}/battinfo.ttl", 503), _Answer(b"@prefix owl: <x> .")],
    }
    asked: list[tuple[str, str]] = []
    waits: list[float] = []

    def opener(request, timeout):  # noqa: ANN001, ANN202
        asked.append((request.full_url, request.get_header("Accept")))
        answer = answers[request.full_url].pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    landing = check.trace("https://w3id.org/battinfo", "text/turtle", opener=opener, wait=5, sleep=waits.append)
    assert landing == check.Landing(
        f"{PAGES}/battinfo.ttl",
        200,
        b"@prefix owl: <x> .",
        ("https://w3id.org/battinfo", "https://w3id.org/battinfo/", f"{PAGES}/battinfo.ttl"),
    )
    assert {accept for _url, accept in asked} == {"text/turtle"}
    assert waits == [5]


def test_trace_lands_on_a_404_and_stops_a_redirect_loop() -> None:
    def not_found(request, timeout):  # noqa: ANN001, ANN202
        raise _busy(request.full_url, 404)

    landing = check.trace(f"{PAGES}/battinfo/versions/0.8.0/battinfo.ttl", "text/turtle", opener=not_found)
    assert landing.status == 404 and landing.body == b""

    def loop(request, timeout):  # noqa: ANN001, ANN202
        raise _redirect(request.full_url, 302, request.full_url)

    with pytest.raises(check.FetchError, match="redirects"):
        check.trace("https://w3id.org/battinfo/loop", "text/turtle", opener=loop, max_hops=3)
