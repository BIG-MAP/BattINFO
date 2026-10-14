"""The release workflow: a pushed v tag is the only route to PyPI, and the release gates run first.

release.yml uploads to PyPI and drafts the GitHub Release only for a pushed
``v`` tag; a manual run can only rehearse on TestPyPI, on any ref, a tag ref
included. Before any upload it runs ci.yml, install-smoke.yml (the built
wheel in empty environments on the oldest and the newest supported Python)
and the hosted-file check, which blocks a final tag only. The ``if:``
conditions are evaluated here for each kind of run, and the shell steps that
decide something are run with bash where it is available. CI also lints
every workflow file with actionlint.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# The kinds of run release.yml can see: (event, ref).
RUNS = [
    ("push", "refs/tags/v0.8.0"),
    ("push", "refs/tags/v0.8.0rc1"),
    ("push", "refs/tags/v0.8.0.dev1"),
    ("workflow_dispatch", "refs/heads/main"),
    ("workflow_dispatch", "refs/heads/release/0.8.0"),
    ("workflow_dispatch", "refs/tags/v0.8.0rc1"),
    ("workflow_dispatch", "refs/tags/v0.8.0"),
]


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # YAML 1.1 reads the bare key `on` as the boolean True.
    return workflow.get("on", workflow.get(True)) or {}


def _step(job: dict, *, name: str | None = None, step_id: str | None = None, uses: str | None = None) -> dict:
    for step in job["steps"]:
        if name is not None and step.get("name") == name:
            return step
        if step_id is not None and step.get("id") == step_id:
            return step
        if uses is not None and str(step.get("uses", "")).startswith(uses):
            return step
    raise AssertionError(f"no step {name or step_id or uses} in {job.get('name')}")


# ── A small evaluator for the GitHub expressions release.yml uses ─────────────

_TOKEN = re.compile(
    r"\s*(?:(?P<string>'(?:[^']|'')*')|(?P<number>\d+(?:\.\d+)?)"
    r"|(?P<op>==|!=|&&|\|\||!|\(|\)|,)|(?P<name>[A-Za-z_][\w-]*(?:\.[A-Za-z_][\w-]*)*))"
)


def _tokens(text: str) -> list[tuple[str, str]]:
    tokens, position = [], 0
    text = text.strip()
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match or match.end() == position:
            raise ValueError(f"cannot read {text[position:]!r}")
        kind = match.lastgroup
        assert kind is not None
        tokens.append((kind, match.group(kind)))
        position = match.end()
    return tokens


class _Expression:
    """Parses and evaluates `==`, `!=`, `&&`, `||`, `!`, parentheses, literals,
    context names and startsWith/endsWith/contains, as GitHub does (strings
    compare ignoring case)."""

    def __init__(self, text: str, context: dict[str, Any]) -> None:
        text = text.strip()
        if text.startswith("${{") and text.endswith("}}"):
            text = text[3:-2]
        self.tokens = _tokens(text)
        self.position = 0
        self.context = context

    def value(self) -> Any:
        result = self._or()
        if self.position != len(self.tokens):
            raise ValueError(f"unexpected {self.tokens[self.position]}")
        return result

    def _peek(self) -> tuple[str, str] | None:
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def _take(self, value: str | None = None) -> tuple[str, str]:
        token = self.tokens[self.position]
        if value is not None and token[1] != value:
            raise ValueError(f"expected {value}, found {token[1]}")
        self.position += 1
        return token

    def _or(self) -> Any:
        left = self._and()
        while self._peek() == ("op", "||"):
            self._take()
            right = self._and()
            left = left if _truthy(left) else right
        return left

    def _and(self) -> Any:
        left = self._unary()
        while self._peek() == ("op", "&&"):
            self._take()
            right = self._unary()
            left = right if _truthy(left) else left
        return left

    def _unary(self) -> Any:
        if self._peek() == ("op", "!"):
            self._take()
            return not _truthy(self._unary())
        return self._comparison()

    def _comparison(self) -> Any:
        left = self._primary()
        token = self._peek()
        if token in (("op", "=="), ("op", "!=")):
            self._take()
            right = self._primary()
            same = _fold(left) == _fold(right)
            return same if token == ("op", "==") else not same
        return left

    def _primary(self) -> Any:
        kind, text = self._take()
        if kind == "string":
            return text[1:-1].replace("''", "'")
        if kind == "number":
            return float(text)
        if kind == "op" and text == "(":
            result = self._or()
            self._take(")")
            return result
        if kind == "name":
            if self._peek() == ("op", "("):
                return self._call(text)
            if text in ("true", "false"):
                return text == "true"
            if text == "null":
                return None
            node: Any = self.context
            for part in text.split("."):
                node = node.get(part) if isinstance(node, dict) else None
            return node
        raise ValueError(f"unexpected {text}")

    def _call(self, function: str) -> Any:
        self._take("(")
        args = []
        while self._peek() != ("op", ")"):
            args.append(self._or())
            if self._peek() == ("op", ","):
                self._take()
        self._take(")")
        if function in ("success", "always"):
            return True  # _runs asks whether a job runs once the jobs it needs have succeeded
        if function in ("failure", "cancelled"):
            return False
        text, part = (str(arg or "").lower() for arg in args)
        if function == "startsWith":
            return text.startswith(part)
        if function == "endsWith":
            return text.endswith(part)
        if function == "contains":
            return part in text
        raise ValueError(f"unknown function {function}")


def _truthy(value: Any) -> bool:
    return value not in (None, False, "", 0)


def _fold(value: Any) -> Any:
    return value.lower() if isinstance(value, str) else value


def _runs(job: dict, event: str, ref: str, target: str = "testpypi") -> bool:
    """Whether *job* runs for this event and ref, once the jobs it needs have succeeded."""
    condition = job.get("if")
    if condition is None:
        return True
    context = {"github": {"event_name": event, "ref": ref}, "inputs": {"target": target if event != "push" else None}}
    return _truthy(_Expression(str(condition), context).value())


def test_the_expression_reader_reads_what_github_reads() -> None:
    context = {"github": {"event_name": "push", "ref": "refs/tags/v1.0.0"}, "inputs": {}}
    assert _Expression("github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')", context).value()
    assert not _Expression("github.event_name == 'workflow_dispatch' || inputs.target == 'pypi'", context).value()
    assert _Expression("${{ !(github.ref == 'refs/heads/main') }}", context).value()
    assert _Expression("github.event_name == 'PUSH'", context).value()  # strings compare ignoring case


# ── release.yml ───────────────────────────────────────────────────────────────


def _release() -> dict:
    return _workflow("release.yml")


def _jobs_that_upload_to_pypi(jobs: dict) -> list[str]:
    """Jobs whose publish step goes to PyPI (no repository-url means pypi.org)."""
    found = []
    for name, job in jobs.items():
        for step in job.get("steps", []):
            if str(step.get("uses", "")).startswith("pypa/gh-action-pypi-publish@"):
                if not (step.get("with") or {}).get("repository-url"):
                    found.append(name)
    return found


def test_only_a_pushed_v_tag_reaches_pypi() -> None:
    jobs = _release()["jobs"]
    assert _jobs_that_upload_to_pypi(jobs) == ["publish-pypi"]
    for event, ref in RUNS:
        for target in ("testpypi", "pypi"):
            expected = event == "push" and ref.startswith("refs/tags/v")
            assert _runs(jobs["publish-pypi"], event, ref, target) is expected, (event, ref, target)
    assert jobs["publish-pypi"]["environment"]["name"] == "pypi"


def test_the_github_release_is_drafted_only_for_a_pushed_v_tag_after_the_upload() -> None:
    job = _release()["jobs"]["github-release"]
    assert "publish-pypi" in job["needs"]
    for event, ref in RUNS:
        assert _runs(job, event, ref) is (event == "push" and ref.startswith("refs/tags/v")), (event, ref)
    settings = _step(job, uses="softprops/action-gh-release@")["with"]
    assert settings["draft"] is True  # Zenodo archives every published release, pre-releases too
    assert "needs.build.outputs.prerelease" in str(settings["prerelease"])
    assert "build" in job["needs"]


def test_a_manual_run_can_only_rehearse_on_testpypi() -> None:
    workflow = _release()
    target = _triggers(workflow)["workflow_dispatch"]["inputs"]["target"]
    assert target["options"] == ["testpypi"]
    assert target["default"] == "testpypi"
    job = workflow["jobs"]["publish-testpypi"]
    assert job["environment"]["name"] == "testpypi"
    for event, ref in RUNS:
        assert _runs(job, event, ref, "testpypi") is (event == "workflow_dispatch"), (event, ref)
    # Only a tag push starts the workflow by itself, never a branch push.
    assert set(_triggers(workflow)["push"]) == {"tags"}


def test_the_pypi_upload_can_be_finished_by_a_rerun_and_testpypi_never_skips() -> None:
    jobs = _release()["jobs"]
    pypi = _step(jobs["publish-pypi"], uses="pypa/gh-action-pypi-publish@")["with"]
    assert pypi["skip-existing"] is True
    testpypi = _step(jobs["publish-testpypi"], uses="pypa/gh-action-pypi-publish@")["with"]
    assert testpypi["repository-url"] == "https://test.pypi.org/legacy/"
    assert not testpypi.get("skip-existing")


def test_every_upload_waits_for_the_ci_and_install_gates_and_pypi_for_the_hosted_check() -> None:
    jobs = _release()["jobs"]
    assert jobs["ci"]["uses"] == "./.github/workflows/ci.yml"
    assert jobs["install-smoke"]["uses"] == "./.github/workflows/install-smoke.yml"
    assert set(jobs["build"]["needs"]) == {"ci", "install-smoke"}
    assert jobs["publish-testpypi"]["needs"] == "build"
    assert set(jobs["publish-pypi"]["needs"]) == {"build", "hosted"}


def _bash() -> str | None:
    """A POSIX bash: on Windows Git's, never the WSL launcher in System32."""
    candidates = [shutil.which("bash")]
    git = shutil.which("git")
    if os.name == "nt" and git:
        git_root = Path(git).resolve().parents[1]
        candidates += [str(git_root / "bin" / "bash.exe"), str(git_root / "usr" / "bin" / "bash.exe")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and "system32" not in candidate.lower():
            return candidate
    return None


def _run_step(script: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    bash = _bash()
    if bash is None:
        pytest.skip("needs bash")
    # GitHub runs a bash step with `bash -e -o pipefail`.
    return subprocess.run(
        [bash, "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
        cwd=cwd,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("event", "ref", "blocks"),
    [
        ("push", "refs/tags/v0.8.0", True),
        ("push", "refs/tags/v1.12.3", True),
        ("push", "refs/tags/v0.8.0rc1", False),
        ("push", "refs/tags/v0.8.0.dev1", False),
        ("workflow_dispatch", "refs/heads/release/0.8.0", False),
        ("workflow_dispatch", "refs/tags/v0.8.0", False),
    ],
)
def test_a_hosted_mismatch_blocks_only_a_pushed_final_tag(event: str, ref: str, blocks: bool, tmp_path: Path) -> None:
    job = _release()["jobs"]["hosted"]
    compare = _step(job, step_id="compare")
    assert compare["continue-on-error"] is True
    assert compare["run"].startswith("python scripts/check_hosted_files.py")
    block = _step(job, name="Block a final release on a mismatch")
    # Any outcome but success, so a step that ran out of time is decided here too.
    assert block["if"] == "steps.compare.outcome != 'success'"

    proc = _run_step(block["run"], tmp_path, {"GITHUB_EVENT_NAME": event, "GITHUB_REF": ref})
    assert proc.returncode == (1 if blocks else 0), proc.stdout + proc.stderr
    assert ("::error::" if blocks else "::warning::") in proc.stdout


def _deadline(run: str) -> float:
    match = re.search(r"--deadline (\d+)", run)
    assert match, f"no --deadline in {run!r}"
    return float(match.group(1))


def test_a_host_that_does_not_answer_cannot_time_the_hosted_job_out() -> None:
    # The job's own time limit is not covered by continue-on-error: had it
    # killed the job, publish-pypi (which needs it) would be skipped even for a
    # pre-release, with no report written. The script stops asking at its
    # deadline and writes the report; the step's time limit backs that up and,
    # unlike the job's, is a step failure that the block step then decides.
    job = _release()["jobs"]["hosted"]
    compare = _step(job, step_id="compare")
    assert compare["timeout-minutes"] < job["timeout-minutes"]
    assert _deadline(compare["run"]) < compare["timeout-minutes"] * 60
    assert "--summary" in compare["run"]


@pytest.mark.parametrize(
    ("tag", "wheel", "ok", "prerelease"),
    [
        ("v0.8.0", "battinfo-0.8.0-py3-none-any.whl", True, "false"),
        ("v0.8.0rc1", "battinfo-0.8.0rc1-py3-none-any.whl", True, "true"),
        ("v0.8.0.dev1", "battinfo-0.8.0.dev1-py3-none-any.whl", True, "true"),
        ("v0.8.0", "battinfo-0.8.0rc1-py3-none-any.whl", False, None),
    ],
)
def test_the_tag_must_name_the_built_version_and_a_pre_release_tag_is_marked(
    tag: str, wheel: str, ok: bool, prerelease: str | None, tmp_path: Path
) -> None:
    step = _step(_release()["jobs"]["build"], step_id="tag")
    assert step["if"] == "startsWith(github.ref, 'refs/tags/')"
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / wheel).write_bytes(b"")
    output = tmp_path / "github-output"
    output.write_text("", encoding="utf-8")

    proc = _run_step(step["run"], tmp_path, {"GITHUB_REF_NAME": tag, "GITHUB_OUTPUT": output.as_posix()})

    assert (proc.returncode == 0) is ok, proc.stdout + proc.stderr
    if ok:
        assert output.read_text(encoding="utf-8").split() == [f"prerelease={prerelease}"]
    else:
        assert "does not match package version" in proc.stdout


# ── install-smoke.yml, the install gate ───────────────────────────────────────


def test_the_install_gate_can_be_called_and_tests_the_oldest_and_newest_python() -> None:
    workflow = _workflow("install-smoke.yml")
    assert "workflow_call" in _triggers(workflow)
    [job] = workflow["jobs"].values()
    matrix = job["strategy"]["matrix"]
    supported = _workflow("ci.yml")["jobs"]["test"]["strategy"]["matrix"]["python-version"]
    assert matrix["python-version"] == [supported[0], supported[-1]]
    assert sorted(matrix["os"]) == ["ubuntu-latest", "windows-latest"]
    assert _step(job, uses="actions/setup-python@")["with"]["python-version"] == "${{ matrix.python-version }}"


GIT_INSTALL_STEP = "pip install git+https://github.com/BIG-MAP/BattINFO.git"


def test_in_a_release_the_git_url_install_takes_the_commit_being_released() -> None:
    # Without a commit the git URL install takes main, which a hotfix tag cut
    # from a release branch never contains.
    assert _release()["jobs"]["install-smoke"]["with"] == {"ref": "${{ github.sha }}"}
    workflow = _workflow("install-smoke.yml")
    ref = _triggers(workflow)["workflow_call"]["inputs"]["ref"]
    assert (ref["type"], ref["default"]) == ("string", "")
    [job] = workflow["jobs"].values()
    step = _step(job, name=GIT_INSTALL_STEP)
    assert step["env"] == {"REF": "${{ inputs.ref }}"}
    assert '"$py" -m pip install "$spec"' in step["run"]
    [spec_line] = [line for line in step["run"].splitlines() if line.strip().startswith("spec=")]

    def spec(ref: str) -> str:
        proc = _run_step(f'{spec_line}\necho "$spec"', ROOT, {"REF": ref})
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.strip()

    sha = "0123456789abcdef0123456789abcdef01234567"
    assert spec(sha) == f"git+https://github.com/BIG-MAP/BattINFO.git@{sha}"
    # Run on its own (a pull request, a push to main), it installs main, as the README line does.
    assert spec("") == "git+https://github.com/BIG-MAP/BattINFO.git"


def test_the_install_gate_runs_the_cli_from_the_wheel_core_only_and_with_processing() -> None:
    [job] = _workflow("install-smoke.yml")["jobs"].values()
    script = _step(job, name="wheel in an empty environment, outside the checkout")["run"]
    core, processing = script.split('"$py" -m pip install "${wheel}[processing]"')
    assert '"$py" -m pip install "$wheel"' in core
    assert '"$cli" --help > /dev/null' in core
    assert "quickstart.py" in core
    assert '"$cli" --help > /dev/null' in processing
    assert "convert_smoke.py" in processing


# ── ci.yml and the scheduled hosted check ─────────────────────────────────────


def test_ci_lints_the_workflow_files_with_a_pinned_actionlint() -> None:
    jobs = _workflow("ci.yml")["jobs"]
    steps = [step for job in jobs.values() for step in job.get("steps", [])]
    lint = [str(step["uses"]) for step in steps if "actionlint" in str(step.get("uses", ""))]
    assert len(lint) == 1
    assert re.fullmatch(r"docker://rhysd/actionlint:\d+\.\d+\.\d+", lint[0]), "pin an actionlint release"


def test_the_ci_test_job_fetches_the_release_tags() -> None:
    # Without the tags the freeze checks against each release skip, so a pull request
    # could change a released v1 term together with the snapshot, or a released schema.
    job = _workflow("ci.yml")["jobs"]["test"]
    assert _step(job, uses="actions/checkout@")["with"]["fetch-depth"] == 0


def test_a_scheduled_job_checks_the_hosted_context_keeps_the_released_terms() -> None:
    workflow = _workflow("hosted-files.yml")
    assert _triggers(workflow)["schedule"]
    job = workflow["jobs"]["release-terms"]
    assert _step(job, uses="actions/checkout@")["with"]["fetch-depth"] == 0  # the release tags
    run = _step(job, name="Compare the hosted v1 context with the last release's terms")["run"]
    assert run.startswith("python scripts/check_hosted_files.py --release-terms")
    assert "--attempts" in run
    assert _deadline(run) < job["timeout-minutes"] * 60  # it reports before the job is killed


def test_a_scheduled_job_checks_the_ontology_iris_serve_the_last_release() -> None:
    # The versionIRI resolves only once the tag's own docs deploy has run, so
    # this is checked after the release, never as a gate before the upload.
    workflow = _workflow("hosted-files.yml")
    job = workflow["jobs"]["ontology"]
    assert _step(job, uses="actions/checkout@")["with"]["fetch-depth"] == 0  # the release tags
    run = _step(job, name="Check that the w3id ontology IRIs serve the last release's battinfo.ttl")["run"]
    assert run.startswith("python scripts/check_hosted_files.py --ontology ")
    assert "--attempts" in run
    assert _deadline(run) < job["timeout-minutes"] * 60
    release_runs = [str(step.get("run", "")) for job in _release()["jobs"].values() for step in job.get("steps", [])]
    assert not [run for run in release_runs if "--ontology" in run]
