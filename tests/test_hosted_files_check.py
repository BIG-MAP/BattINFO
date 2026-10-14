"""scripts/check_hosted_files.py: the files w3id serves against this checkout's copies.

release.yml runs the script before an upload: every hosted file (the v1
records context, each JSON Schema at its $id, the record vocabulary) must have
the sha256 of the checkout's copy, line endings aside. The scheduled workflow
runs it with --release-terms: the hosted context must still hold the last
release's terms with the same values, and terms added since do not count.
Nothing here reaches the network: the fetches are answered from memory.
"""

from __future__ import annotations

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
