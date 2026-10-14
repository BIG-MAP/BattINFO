"""The dependencies and Python versions pyproject.toml declares, and how CI keeps them true.

The floors become permanent PyPI metadata once a release is uploaded, so each
one has to be a release battinfo works with. uv.lock records the declared
requirements, and CI installs from it with ``--frozen``, which never compares
the two: a floor changed without ``uv lock`` would pass CI while the lock
still recorded the old one. Every other CI job installs the locked, newest
versions, so one job installs the floors themselves, and Dependabot only
refreshes the lock.

The classifiers name the Python versions CI tests, and the install pages, the
contributor guides and the scope page state the same range.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import yaml
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]

# The Python versions 0.8.0 supports. Python 3.15 is left out until PyYAML
# publishes wheels for it: without them a core install on Windows needs a C
# compiler (docs/scope.md, known limitations).
SUPPORTED_PYTHONS = ["3.11", "3.12", "3.13", "3.14"]

# Files that state the Python versions battinfo supports and CI tests.
PYTHON_RANGE_STATEMENTS = [
    "README.md",
    "QUICKSTART.md",
    "CONTRIBUTING.md",
    "AGENTS.md",
    "docs/scope.md",
    "docs/pages/getting-started.rst",
]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _yaml(relative: str) -> dict:
    return yaml.safe_load((ROOT / relative).read_text(encoding="utf-8"))


def _ci_jobs() -> dict:
    return _yaml(".github/workflows/ci.yml")["jobs"]


def _run_text(job: dict) -> str:
    """The shell commands of every step of a workflow job, one string."""
    return "\n".join(str(step.get("run", "")) for step in job.get("steps", []))


def _core() -> dict[str, Requirement]:
    requirements = (Requirement(raw) for raw in _pyproject()["project"]["dependencies"])
    return {canonicalize_name(req.name): req for req in requirements}


def _floor(requirement: Requirement) -> Version:
    floors = [Version(spec.version) for spec in requirement.specifier if spec.operator == ">="]
    assert floors, f"{requirement} declares no lower bound"
    return max(floors)


def test_pydantic_floor_is_a_release_battinfo_imports_on() -> None:
    # testmethod.py imports ModelWrapValidatorHandler from pydantic, which only
    # 2.10.4 and later export there, so import battinfo fails on 2.7.0-2.10.3.
    # The LinkML-generated models (bundle_generated.py) also set
    # serialize_by_alias and validate_by_name, ConfigDict keys added in 2.11.
    assert _floor(_core()["pydantic"]) >= Version("2.11")


def test_pyshacl_is_a_core_dependency() -> None:
    # The check ws.zenodo() runs before it mints a DOI includes the SHACL
    # publication shapes, so a plain install has to be able to run them.
    core = _core()
    assert "pyshacl" in core
    assert _floor(core["pyshacl"]) >= Version("0.40.1")
    for extra, requirements in _pyproject()["project"]["optional-dependencies"].items():
        names = {canonicalize_name(Requirement(raw).name) for raw in requirements}
        assert "pyshacl" not in names, f"pyshacl is a core dependency; the [{extra}] extra lists it again"


def test_rdflib_floor_is_one_pyshacl_can_use() -> None:
    # pyshacl 0.40.1 needs owlrl 7.6.2, which requires rdflib>=7.6.0, so an
    # older rdflib can never be installed next to it.
    assert _floor(_core()["rdflib"]) >= Version("7.6")


def test_rich_floor_is_one_the_typer_floor_allows() -> None:
    # typer 0.27.0 requires rich>=13.8.0, so a lower rich floor could never be
    # installed, and the CI job that installs the floors could not test it.
    assert _floor(_core()["rich"]) >= Version("13.8")


def test_import_battinfo_does_not_load_pyshacl() -> None:
    # pyshacl is imported only when a SHACL check runs, so making it a core
    # dependency adds nothing to the time import battinfo takes.
    code = "import sys, battinfo, battinfo.validate; print('pyshacl' in sys.modules)"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, check=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False"


def _requirement_key(name: str, extras: Iterable[str] | None, specifier: str, group: str) -> tuple:
    return (canonicalize_name(name), tuple(sorted(extras or ())), str(SpecifierSet(specifier)), group)


def _declared_requirements() -> Counter:
    pyproject = _pyproject()
    project = pyproject["project"]
    groups: list[tuple[str, list[str]]] = [("core", project["dependencies"])]
    groups += [(f"extra:{extra}", reqs) for extra, reqs in project["optional-dependencies"].items()]
    groups += [(f"group:{group}", reqs) for group, reqs in pyproject.get("dependency-groups", {}).items()]
    declared: Counter = Counter()
    for group, requirements in groups:
        for raw in requirements:
            req = Requirement(raw)
            declared[_requirement_key(req.name, req.extras, str(req.specifier), group)] += 1
    return declared


def _locked_requirements() -> tuple[Counter, dict]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    package = next(p for p in lock["package"] if p["name"] == "battinfo")
    metadata = package["metadata"]
    locked: Counter = Counter()
    for entry in metadata.get("requires-dist", []):
        extra = re.search(r"extra == '([^']+)'", entry.get("marker", ""))
        group = f"extra:{extra.group(1)}" if extra else "core"
        locked[_requirement_key(entry["name"], entry.get("extras"), entry.get("specifier", ""), group)] += 1
    for group, entries in metadata.get("requires-dev", {}).items():
        for entry in entries:
            key = _requirement_key(entry["name"], entry.get("extras"), entry.get("specifier", ""), f"group:{group}")
            locked[key] += 1
    return locked, lock


def test_uv_lock_records_the_declared_requirements() -> None:
    locked, lock = _locked_requirements()
    declared = _declared_requirements()
    assert locked == declared, (
        "uv.lock does not record the requirements pyproject.toml declares; run uv lock. "
        f"Only in pyproject.toml: {sorted((declared - locked).elements())}. "
        f"Only in uv.lock: {sorted((locked - declared).elements())}."
    )
    assert lock["requires-python"] == _pyproject()["project"]["requires-python"]


def test_ci_tests_every_supported_python_on_linux_and_windows() -> None:
    matrix = _ci_jobs()["test"]["strategy"]["matrix"]
    assert matrix["python-version"] == SUPPORTED_PYTHONS
    assert sorted(matrix["os"]) == ["ubuntu-latest", "windows-latest"]
    # No include or exclude: every version runs on both systems.
    assert set(matrix) == {"os", "python-version"}


def test_classifiers_name_the_python_versions_ci_tests() -> None:
    classifiers = _pyproject()["project"]["classifiers"]
    minor = [
        c.rsplit("::", 1)[1].strip()
        for c in classifiers
        if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)
    ]
    assert minor == _ci_jobs()["test"]["strategy"]["matrix"]["python-version"]
    # requires-python keeps no upper bound: with a cap, pip on a newer Python
    # would quietly install an older battinfo release instead of this one.
    assert _pyproject()["project"]["requires-python"] == ">=3.11"


def test_docs_state_the_python_versions_ci_tests() -> None:
    tested = _ci_jobs()["test"]["strategy"]["matrix"]["python-version"]
    span = f"{tested[0]}\N{EN DASH}{tested[-1]}"
    for relative in PYTHON_RANGE_STATEMENTS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert span in text, f"{relative} does not state the tested range Python {span}"
        stale = re.findall(r"3\.11(?:/| and )3\.12\b|Python 3\.11\+", text)
        assert not stale, f"{relative} still states an older range: {stale}"


def test_a_ci_job_installs_the_declared_floors() -> None:
    # The floors become permanent metadata on PyPI, and every other job
    # installs the locked, newest versions. The requirements are read from
    # pyproject.toml so that uv treats them as direct ones: given the wheel,
    # it would treat them as transitive and install the newest versions.
    # uv.lock is not used, because it is resolved for every extra at once, so a
    # requirement of the dev or docs extras can lift a core package above its floor.
    jobs = [job for job in _ci_jobs().values() if "--resolution lowest-direct" in _run_text(job)]
    assert len(jobs) == 1, "ci.yml needs one job that installs the lowest versions pyproject.toml allows"
    run = _run_text(jobs[0])
    assert re.search(r"uv venv --python 3\.11\b", run), "the floors are tested on the oldest supported Python"
    assert "uv pip install --resolution lowest-direct -r pyproject.toml --extra publish --extra processing" in run
    assert "uv sync" not in run
    assert "tests/installed_smoke.py" in run
    assert "pytest" in run


def test_dependabot_refreshes_the_lock_and_leaves_the_floors_alone() -> None:
    updates = _yaml(".github/dependabot.yml")["updates"]
    uv = next(entry for entry in updates if entry["package-ecosystem"] == "uv")
    assert uv.get("versioning-strategy") == "lockfile-only"
    ignored = {canonicalize_name(entry["dependency-name"]) for entry in uv.get("ignore", [])}
    build_requires = {canonicalize_name(Requirement(raw).name) for raw in _pyproject()["build-system"]["requires"]}
    assert build_requires <= ignored, (
        f"Dependabot may still change the build requirements {sorted(build_requires - ignored)}"
    )
