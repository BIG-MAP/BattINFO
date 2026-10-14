"""Check the built wheel and sdist against pyproject.toml before they are uploaded.

An index keeps a release's metadata as it was uploaded, so a wrong licence,
URL, keyword or classifier stays on the project page of that version. For a
folder holding one wheel and one sdist of the same version, this checks:

* that the wheel's METADATA and the sdist's PKG-INFO carry the licence
  expression, the project URLs, the keywords and the classifiers that
  pyproject.toml declares, and name the same licence files;
* that both hold every licence file pyproject.toml lists;
* that the sdist holds no ``tests/`` folder. MANIFEST.in prunes it: the tests
  read fixtures, docs and scripts that the sdist leaves out, so they run from a
  checkout of the release tag instead.

The CI package job and the build job of ``.github/workflows/release.yml`` run
it on ``dist/`` after ``twine check``.

Usage::

    python scripts/check_distribution.py [DIST_DIR]   (default: dist)

The exit status is 0 when everything matches and 1 otherwise. Only the
standard library is used, so it runs without battinfo installed.
"""

from __future__ import annotations

import argparse
import email.message
import email.parser
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _parse(metadata: bytes) -> email.message.Message:
    return email.parser.BytesHeaderParser().parsebytes(metadata)


def _expected(root: Path) -> dict[str, list[str]]:
    """The metadata fields pyproject.toml fixes, as a wheel's METADATA spells them."""
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return {
        "License-Expression": [project["license"]],
        "Project-URL": [f"{label}, {url}" for label, url in project.get("urls", {}).items()],
        "Keywords": [",".join(project.get("keywords", []))] if project.get("keywords") else [],
        "Classifier": list(project.get("classifiers", [])),
        "License-File": list(project.get("license-files", [])),
    }


def _compare(name: str, metadata: email.message.Message, expected: dict[str, list[str]]) -> list[str]:
    problems = []
    for field, values in expected.items():
        found = [str(value) for value in metadata.get_all(field) or []]
        if sorted(found) != sorted(values):
            problems.append(f"{name}: {field} is {found}, pyproject.toml declares {values}")
    return problems


def _check_wheel(path: Path, expected: dict[str, list[str]]) -> tuple[str | None, list[str]]:
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        infos = sorted({name.split("/", 1)[0] for name in names if name.split("/", 1)[0].endswith(".dist-info")})
        if len(infos) != 1 or f"{infos[0]}/METADATA" not in names:
            return None, [f"{path.name}: no single .dist-info folder with a METADATA file"]
        metadata = _parse(wheel.read(f"{infos[0]}/METADATA"))
    problems = _compare(path.name, metadata, expected)
    for licence in expected["License-File"]:
        if f"{infos[0]}/licenses/{licence}" not in names:
            problems.append(f"{path.name}: the licence file {licence} is missing from {infos[0]}/licenses/")
    return metadata.get("Version"), problems


def _check_sdist(path: Path, expected: dict[str, list[str]]) -> tuple[str | None, list[str]]:
    with tarfile.open(path) as sdist:
        names = sdist.getnames()
        tops = {name.split("/", 1)[0] for name in names}
        if len(tops) != 1:
            return None, [f"{path.name}: expected one top-level folder, found {sorted(tops)}"]
        top = tops.pop()
        member = sdist.extractfile(f"{top}/PKG-INFO") if f"{top}/PKG-INFO" in names else None
        if member is None:
            return None, [f"{path.name}: no {top}/PKG-INFO"]
        metadata = _parse(member.read())
    problems = _compare(path.name, metadata, expected)
    for licence in expected["License-File"]:
        if f"{top}/{licence}" not in names:
            problems.append(f"{path.name}: the licence file {licence} is missing")
    tests = sorted(name for name in names if name == f"{top}/tests" or name.startswith(f"{top}/tests/"))
    if tests:
        problems.append(f"{path.name}: has a tests/ folder ({len(tests)} entries), which MANIFEST.in prunes")
    return metadata.get("Version"), problems


def check(dist: Path, root: Path = ROOT) -> list[str]:
    """Every way the distribution in *dist* differs from what pyproject.toml under *root* declares."""
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        found = [path.name for path in [*wheels, *sdists]]
        return [f"{dist}: expected one wheel and one sdist, found {found}"]
    expected = _expected(root)
    wheel_version, problems = _check_wheel(wheels[0], expected)
    sdist_version, sdist_problems = _check_sdist(sdists[0], expected)
    problems += sdist_problems
    if wheel_version and sdist_version and wheel_version != sdist_version:
        problems.append(f"the wheel is version {wheel_version} and the sdist {sdist_version}")
    return problems


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dist", nargs="?", type=Path, default=Path("dist"), help="the folder uv build wrote")
    args = parser.parse_args(argv)
    problems = check(args.dist, root)
    if problems:
        print("The distribution does not match pyproject.toml:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"{args.dist}: the wheel and the sdist match pyproject.toml, and the sdist has no tests/ folder.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
