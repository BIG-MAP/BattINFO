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

The rest of the metadata is fixed at upload as well: the licence expression,
the project URLs, the keywords and the classifiers. scripts/check_distribution.py
checks that the built wheel and sdist carry what pyproject.toml declares, and
that the sdist leaves the tests out.
"""

from __future__ import annotations

import importlib.util
import io
import re
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from packaging.licenses import canonicalize_license_expression
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


set_version = _load_script("set_version")

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


# ── Metadata an index keeps as it was uploaded ──


def test_the_licence_expression_names_every_licence_in_the_wheel() -> None:
    # Besides battinfo's own code (Apache-2.0), the wheel ships the EMMO-derived
    # context and labels (CC BY 4.0) and five BPX example parameter sets (MIT).
    # NOTICE says which files are which, and ships next to LICENSE.
    project = _pyproject()["project"]
    assert project["license"] == "Apache-2.0 AND CC-BY-4.0 AND MIT"
    assert canonicalize_license_expression(project["license"]) == project["license"]
    assert {"LICENSE", "NOTICE"} <= set(project["license-files"])
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "Creative Commons Attribution 4.0 International (CC BY 4.0)" in notice
    assert "Licence: MIT" in notice


def test_the_project_urls_point_at_the_rendered_docs_the_website_and_the_release_changelog() -> None:
    urls = _pyproject()["project"]["urls"]
    assert urls["Homepage"] == "https://battinfo.org"
    # The root of the docs site forwards to stable/, the newest final release
    # (to dev/ before the first one), as .github/workflows/docs-deploy.sh writes it.
    assert urls["Documentation"] == "https://big-map.github.io/BattINFO/"
    # The changelog as tagged; scripts/set_version.py moves it with the version.
    base = set_version.parse_version(set_version.read_version(ROOT)).base
    assert urls["Changelog"] == f"https://github.com/BIG-MAP/BattINFO/blob/v{base}/CHANGELOG.md"
    assert urls["Repository"] == "https://github.com/BIG-MAP/BattINFO"
    assert urls["Issues"] == "https://github.com/BIG-MAP/BattINFO/issues"


def test_the_package_and_the_citation_share_their_keywords_and_battery_pass_is_not_one() -> None:
    keywords = _pyproject()["project"]["keywords"]
    citation = _yaml("CITATION.cff")
    assert citation["keywords"] == keywords
    assert not [keyword for keyword in keywords if "battery pass" in keyword.lower()]


def test_typed_is_claimed_only_once_mypy_checks_every_module() -> None:
    # py.typed ships, so type checkers read battinfo's annotations. The modules
    # in the ignore_errors override are not type-checked yet, so the
    # "Typing :: Typed" classifier waits until that list is empty.
    pyproject = _pyproject()
    unchecked = [
        module
        for override in pyproject["tool"]["mypy"].get("overrides", [])
        if override.get("ignore_errors")
        for module in override["module"]
    ]
    typed = "Typing :: Typed" in pyproject["project"]["classifiers"]
    assert not (typed and unchecked), f"'Typing :: Typed' is claimed while mypy skips {unchecked}"
    assert "py.typed" in pyproject["tool"]["setuptools"]["package-data"]["battinfo"]
    assert (ROOT / "src" / "battinfo" / "py.typed").is_file()


def test_the_sdist_leaves_the_tests_out() -> None:
    # setuptools puts tests/test*.py into an sdist by default, but not the
    # fixtures, docs, scripts and web files they read, so they could not run
    # from it. They run from a checkout of the release tag instead.
    lines = [line.strip() for line in (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()]
    assert "prune tests" in lines


# ── scripts/check_distribution.py, which CI and release.yml run on dist/ ──


@pytest.fixture()
def distribution_check() -> ModuleType:
    return _load_script("check_distribution")


def _metadata_fields(**replace: list[str]) -> list[tuple[str, str]]:
    """The fields setuptools writes into METADATA for this pyproject.toml, with some replaced."""
    project = _pyproject()["project"]
    fields: dict[str, list[str]] = {
        "Metadata-Version": ["2.4"],
        "Name": ["battinfo"],
        "Version": [set_version.read_version(ROOT)],
        "License-Expression": [project["license"]],
        "Project-URL": [f"{label}, {url}" for label, url in project["urls"].items()],
        "Keywords": [",".join(project["keywords"])],
        "Classifier": list(project["classifiers"]),
        "License-File": list(project["license-files"]),
    }
    fields.update(replace)
    return [(name, value) for name, values in fields.items() for value in values]


def _write_dist(
    dist: Path,
    *,
    fields: list[tuple[str, str]] | None = None,
    sdist_extra: Iterable[str] = (),
    wheel_licences: Iterable[str] = ("LICENSE", "NOTICE"),
) -> Path:
    """A wheel and an sdist holding only what scripts/check_distribution.py reads."""
    fields = fields if fields is not None else _metadata_fields()
    metadata = "".join(f"{name}: {value}\n" for name, value in fields).encode("utf-8") + b"\nThe README.\n"
    version = set_version.read_version(ROOT)
    dist.mkdir(parents=True, exist_ok=True)
    info = f"battinfo-{version}.dist-info"
    with zipfile.ZipFile(dist / f"battinfo-{version}-py3-none-any.whl", "w") as wheel:
        wheel.writestr("battinfo/__init__.py", "")
        wheel.writestr(f"{info}/METADATA", metadata)
        for name in wheel_licences:
            wheel.writestr(f"{info}/licenses/{name}", f"{name}\n")
    top = f"battinfo-{version}"
    members = {
        f"{top}/PKG-INFO": metadata,
        f"{top}/LICENSE": b"LICENSE\n",
        f"{top}/NOTICE": b"NOTICE\n",
        f"{top}/pyproject.toml": b"",
        f"{top}/src/battinfo/__init__.py": b"",
        **{f"{top}/{name}": b"" for name in sdist_extra},
    }
    with tarfile.open(dist / f"battinfo-{version}.tar.gz", "w:gz") as sdist:
        for name, data in members.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            sdist.addfile(member, io.BytesIO(data))
    return dist


def test_a_distribution_built_from_this_pyproject_passes(
    distribution_check: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dist = _write_dist(tmp_path / "dist")
    assert distribution_check.check(dist, ROOT) == []
    assert distribution_check.main([str(dist)]) == 0
    assert "match pyproject.toml" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("License-Expression", ["Apache-2.0"]),
        ("Project-URL", ["Documentation, https://github.com/BIG-MAP/BattINFO/tree/main/docs"]),
        ("Keywords", ["batteries,Battery Pass"]),
        ("Classifier", ["Typing :: Typed"]),
        ("License-File", ["LICENSE"]),
    ],
)
def test_metadata_that_differs_from_pyproject_is_named(
    distribution_check: ModuleType, tmp_path: Path, field: str, values: list[str]
) -> None:
    dist = _write_dist(tmp_path / "dist", fields=_metadata_fields(**{field: values}))
    problems = distribution_check.check(dist, ROOT)
    assert problems and all(field in problem for problem in problems), problems
    assert any(".whl" in problem for problem in problems) and any(".tar.gz" in problem for problem in problems)


def test_a_licence_file_missing_from_the_wheel_fails(distribution_check: ModuleType, tmp_path: Path) -> None:
    dist = _write_dist(tmp_path / "dist", wheel_licences=["LICENSE"])
    problems = distribution_check.check(dist, ROOT)
    assert len(problems) == 1 and "NOTICE" in problems[0], problems


def test_tests_in_the_sdist_fail(distribution_check: ModuleType, tmp_path: Path) -> None:
    dist = _write_dist(tmp_path / "dist", sdist_extra=["tests/test_api.py"])
    problems = distribution_check.check(dist, ROOT)
    assert len(problems) == 1 and "tests/" in problems[0], problems


def test_a_dist_folder_without_exactly_one_wheel_and_one_sdist_fails(
    distribution_check: ModuleType, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert distribution_check.main([str(empty)]) == 1
    dist = _write_dist(tmp_path / "dist")
    wheel = next(dist.glob("*.whl"))
    (dist / "battinfo-0.0.1-py3-none-any.whl").write_bytes(wheel.read_bytes())
    problems = distribution_check.check(dist, ROOT)
    assert problems and "one wheel" in problems[0], problems


def test_ci_and_the_release_build_check_the_distribution() -> None:
    command = "python3 scripts/check_distribution.py dist"
    assert command in _run_text(_ci_jobs()["package"])
    release_build = _yaml(".github/workflows/release.yml")["jobs"]["build"]
    assert command in _run_text(release_build)
