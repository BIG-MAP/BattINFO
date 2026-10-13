"""The dependencies pyproject.toml declares, and the lock that records them.

The floors become permanent PyPI metadata once a release is uploaded, so each
one has to be a release battinfo works with. uv.lock records the declared
requirements, and CI installs from it with ``--frozen``, which never compares
the two: a floor changed without ``uv lock`` would pass CI while the lock
still recorded the old one.
"""

from __future__ import annotations

import re
import tomllib
from collections import Counter
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


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


def _requirement_key(name: str, extras: object, specifier: str, group: str | None) -> tuple:
    return (canonicalize_name(name), tuple(sorted(extras or ())), str(SpecifierSet(specifier)), group)


def _declared_requirements() -> Counter:
    pyproject = _pyproject()
    project = pyproject["project"]
    declared: Counter = Counter()
    groups: list[tuple[str | None, list[str]]] = [(None, project["dependencies"])]
    groups += [(f"extra:{extra}", reqs) for extra, reqs in project["optional-dependencies"].items()]
    groups += [(f"group:{group}", reqs) for group, reqs in pyproject.get("dependency-groups", {}).items()]
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
        group = f"extra:{extra.group(1)}" if extra else None
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
