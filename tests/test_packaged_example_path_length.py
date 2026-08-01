"""Guard the packaged example tree against MAX_PATH-breaking filenames.

`pip install` on default Windows (LongPathsEnabled=0) caps the full path at
260 chars. The wheel ships the example records under
``site-packages/battinfo/data/examples/**``; a filename that is too deep pushes
the install path past the cap under a realistic venv prefix and the install
fails outright. The 0.8 PyPI release widens that exposure, so this test fails
CI if a future example filename regrows the tail.

The historical worst offender duplicated its directory in the filename
(``<type>/<type>-<uid>.json``), e.g.
``current-collector-spec/current-collector-spec-vkaf-f5bv-fwt2-e6yz.json`` at 93
chars below ``site-packages``. Dropping the redundant ``<type>-`` prefix
(``<type>/<uid>.json``) removed those. The remaining ceiling is the descriptive
``cell-spec/research/*.example.json`` records (82 below ``site-packages``),
which are referenced by name in several other tests and so are not renamed.

The budget is expressed "below site-packages", i.e. counting from the installed
top-level ``battinfo/`` package directory, which is the segment that actually
adds to the install path. It leaves headroom for the research records while
still failing any reintroduced type-prefixed (long) filename.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from battinfo.api import EXAMPLES_ROOT, PACKAGE_ROOT

# Max length, in characters, that any packaged example file may occupy below
# site-packages (i.e. "battinfo/data/examples/<...>"). See module docstring.
MAX_EXAMPLE_PATH_BELOW_SITE_PACKAGES = 85

# The installed top-level package directory name, prepended because it is part
# of every path below site-packages.
_PACKAGE_PREFIX = PACKAGE_ROOT.name + "/"


def _below_site_packages(path) -> str:
    rel = PurePosixPath(*path.relative_to(PACKAGE_ROOT).parts)
    return _PACKAGE_PREFIX + rel.as_posix()


def test_packaged_example_paths_fit_windows_max_path() -> None:
    worst_len = 0
    worst_path = ""
    for path in EXAMPLES_ROOT.rglob("*"):
        if not path.is_file():
            continue
        below = _below_site_packages(path)
        if len(below) > worst_len:
            worst_len = len(below)
            worst_path = below

    assert worst_len <= MAX_EXAMPLE_PATH_BELOW_SITE_PACKAGES, (
        f"Packaged example path is {worst_len} chars below site-packages "
        f"(budget {MAX_EXAMPLE_PATH_BELOW_SITE_PACKAGES}); this risks breaking "
        f"`pip install` on default Windows (MAX_PATH=260) under deep venv "
        f"prefixes. Offender: {worst_path}. Shorten the filename (drop any "
        f"redundant '<type>-' prefix; use '<type>/<uid>.json') in examples/ and "
        f"re-run `python scripts/sync_examples.py`."
    )
