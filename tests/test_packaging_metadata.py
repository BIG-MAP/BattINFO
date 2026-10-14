"""The dependencies and Python versions pyproject.toml declares, and how CI keeps them true.

The floors become permanent PyPI metadata once a release is uploaded, so each
one has to be a release battinfo works with. uv.lock records the declared
requirements, and CI installs from it with ``--frozen``, which never compares
the two: a floor changed without ``uv lock`` would pass CI while the lock
still recorded the old one.

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
