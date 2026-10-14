"""Set the release version wherever it is stamped, or check that every stamp agrees.

The package, the CLI and the ontology share one version line (RELEASING.md).
``__version__`` in src/battinfo/__init__.py is its source: the build reads it,
and every record the library writes carries it in ``provenance.battinfo_version``.
This script writes it, then the stamps that follow from it:

- ``owl:versionIRI`` and ``owl:versionInfo`` in battinfo.ttl,
- ``version`` and ``date-released`` in CITATION.cff, and the tag named in the
  comment above the date,
- the supported-versions table in SECURITY.md,
- the Changelog URL in pyproject.toml, which names the release's tag,
- a version pin in tests/installed_smoke.py, should one come back,

and reruns the generators whose output embeds the version in record provenance:
scripts/gen_reference_records.py (docs/records/) and scripts/gen_web_examples.py
(web/lib/showcase.generated.ts).

The stamps outside ``__version__`` take the base version, X.Y.Z without its
pre-release, post-release or development part. On a tree at 0.8.0, setting a
release candidate (0.8.0rc1) or a rehearsal build (0.8.0.dev1) therefore changes
only ``__version__`` and the generated files: battinfo.ttl, CITATION.cff,
SECURITY.md and pyproject.toml keep naming the release it leads to.

``--date`` sets the release date: ``date-released`` in CITATION.cff and the date
of the release's heading in CHANGELOG.md, which RELEASING.md has you add first.
Without it the date changes only when CITATION.cff moves to another version, and
then takes the date of that version's CHANGELOG.md heading, or today's date if
there is no heading yet. A heading dated with a placeholder such as ``<date>``
is refused; give the day with ``--date``.

``--check`` changes nothing. It exits 1 when a stamp or a generated file
disagrees with ``__version__``, or when CHANGELOG.md has no heading for the
release or dates it differently from CITATION.cff. tests/test_set_version.py
runs the same check in CI.

An editable install keeps the version it was installed with in its metadata,
which tests/installed_smoke.py compares with ``__version__``. ``uv sync`` and
``uv run`` reinstall it when ``__version__`` changes, because pyproject.toml
lists src/battinfo/__init__.py among uv's cache keys; a pip editable install
needs ``pip install -e .`` again. The script says so whenever it changes
``__version__``.

Usage:
    python scripts/set_version.py 0.8.0rc1                 # a release candidate
    python scripts/set_version.py 0.8.0 --date 2026-10-20  # the release itself
    python scripts/set_version.py --check
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]

INIT = "src/battinfo/__init__.py"
ONTOLOGY = "battinfo.ttl"
CITATION = "CITATION.cff"
SECURITY = "SECURITY.md"
PYPROJECT = "pyproject.toml"
SMOKE = "tests/installed_smoke.py"
CHANGELOG = "CHANGELOG.md"
GENERATORS = ("scripts/gen_reference_records.py", "scripts/gen_web_examples.py")
GENERATED = ("docs/records/*.md", "web/lib/showcase.generated.ts")

_N = r"(?:0|[1-9]\d*)"
# PEP 440 in normal form, with three release numbers and no local part (an index
# refuses local versions): 0.8.0, 0.8.0rc1, 0.8.0.post1, 0.8.0.dev1, 0.8.0rc1.dev2.
# Also the hyphenated pre-release 0.8.0-rc1, which the build records as 0.8.0rc1.
_VERSION = re.compile(
    rf"(?P<base>(?P<series>{_N}\.{_N})\.{_N})"
    rf"(?:(?:(?:a|b|rc){_N})?(?:\.post{_N})?(?:\.dev{_N})?|-(?:a|b|rc){_N})"
)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

_INIT_VERSION = re.compile(r'^__version__ = "(?P<value>[^"]*)"$', re.MULTILINE)
_CITATION_VERSION = re.compile(r'^version: "?(?P<value>[^"\s]*)"?[ \t]*$', re.MULTILINE)
_CITATION_DATE = re.compile(r'^date-released: "?(?P<value>[^"\s]*)"?[ \t]*$', re.MULTILINE)
_GENERATED_STAMP = re.compile(r'"battinfo_version": "(?P<value>[^"]*)"')


class Version(NamedTuple):
    """A release version and the parts of it the stamps use."""

    text: str  # as written into __version__, such as 0.8.0rc1
    base: str  # X.Y.Z
    series: str  # X.Y


class _Stamp(NamedTuple):
    rel: str
    pattern: re.Pattern[str]  # group "value" holds the stamped text
    label: str
    value: Callable[[Version], str]
    required: bool = True


STAMPS = (
    _Stamp(INIT, _INIT_VERSION, "__version__", lambda v: v.text),
    _Stamp(
        ONTOLOGY,
        re.compile(r"owl:versionIRI <https://w3id\.org/battinfo/(?P<value>[^/>]*)/battinfo>"),
        "the version in owl:versionIRI",
        lambda v: v.base,
    ),
    _Stamp(ONTOLOGY, re.compile(r'owl:versionInfo "(?P<value>[^"]*)"'), "owl:versionInfo", lambda v: v.base),
    _Stamp(CITATION, _CITATION_VERSION, "version", lambda v: v.base),
    _Stamp(
        CITATION,
        re.compile(r"^# Set to the day the v(?P<value>\S+) tag is pushed\.$", re.MULTILINE),
        "the tag named above date-released",
        lambda v: v.base,
        required=False,
    ),
    _Stamp(
        SECURITY,
        re.compile(r"^\| (?P<value>\d+\.\d+)\.x \| :white_check_mark: \|", re.MULTILINE),
        "the supported series",
        lambda v: v.series,
    ),
    _Stamp(
        SECURITY,
        re.compile(r"^\| < (?P<value>\d+\.\d+\.\d+) \| :x: \|", re.MULTILINE),
        "the oldest supported version",
        lambda v: f"{v.series}.0",
    ),
    # The package metadata on PyPI keeps the URL it was uploaded with, so it
    # names the release's tag rather than main.
    _Stamp(
        PYPROJECT,
        re.compile(
            r'^Changelog = "https://github\.com/BIG-MAP/BattINFO/blob/v(?P<value>[^/"]+)/CHANGELOG\.md"$', re.MULTILINE
        ),
        "the tag in the Changelog URL",
        lambda v: v.base,
    ),
    _Stamp(
        SMOKE, re.compile(r'__version__ == "(?P<value>[^"]*)"'), "the version pin", lambda v: v.text, required=False
    ),
)


def parse_version(text: str) -> Version:
    """Split *text* into its base and series, or raise ValueError if it is no release version."""
    match = _VERSION.fullmatch(text)
    if match is None:
        raise ValueError(
            f"{text!r} is not a version this script can stamp: write X.Y.Z, optionally followed by "
            "aN, bN or rcN, then .postN, then .devN (0.8.0, 0.8.0rc1, 0.8.0.dev1)"
        )
    return Version(text=text, base=match["base"], series=match["series"])


def _check_date(date: str) -> str:
    try:
        if _DATE.fullmatch(date) is None:
            raise ValueError("not in the form YYYY-MM-DD")
        dt.date.fromisoformat(date)
    except ValueError as exc:
        raise ValueError(f"the date {date!r} is not a release date: {exc}") from None
    return date


def _changelog_heading(base: str) -> re.Pattern[str]:
    return re.compile(rf"^## \[{re.escape(base)}\] - (?P<value>\S+)", re.MULTILINE)


class _TextFile:
    """A text file read with its newlines normalised and written back with its own."""

    def __init__(self, root: Path, rel: str) -> None:
        self.rel = rel
        self.path = root / rel
        raw = self.path.read_bytes().decode("utf-8")
        self.newline = "\r\n" if "\r\n" in raw else "\n"
        self.original = raw.replace("\r\n", "\n")
        self.text = self.original

    def values(self, pattern: re.Pattern[str]) -> list[str]:
        return [match["value"] for match in pattern.finditer(self.text)]

    def set(self, pattern: re.Pattern[str], value: str) -> int:
        def replace(match: re.Match[str]) -> str:
            start, end = match.span("value")
            offset = match.start()
            return match[0][: start - offset] + value + match[0][end - offset :]

        self.text, count = pattern.subn(replace, self.text)
        return count

    def write(self) -> bool:
        if self.text == self.original:
            return False
        self.path.write_bytes(self.text.replace("\n", self.newline).encode("utf-8"))
        return True


def read_version(root: Path = ROOT) -> str:
    """``__version__`` as written in src/battinfo/__init__.py (the package is not imported)."""
    values = _TextFile(root, INIT).values(_INIT_VERSION)
    if len(values) != 1:
        raise ValueError(f'{INIT}: expected one line __version__ = "...", found {len(values)}')
    return values[0]


def check(root: Path = ROOT) -> list[str]:
    """Every way the files under *root* disagree with ``__version__``; empty when they agree."""
    try:
        version = parse_version(read_version(root))
    except ValueError as exc:
        return [f"{INIT}: {exc}"]

    problems: list[str] = []
    files: dict[str, _TextFile] = {}
    for stamp in STAMPS:
        if stamp.rel not in files:
            if not (root / stamp.rel).is_file():
                if stamp.required:
                    problems.append(f"{stamp.rel}: file not found")
                continue
            files[stamp.rel] = _TextFile(root, stamp.rel)
        values = files[stamp.rel].values(stamp.pattern)
        expected = stamp.value(version)
        if not values and stamp.required:
            problems.append(f"{stamp.rel}: no {stamp.label} found")
        problems.extend(
            f"{stamp.rel}: {stamp.label} is {value}, expected {expected}" for value in values if value != expected
        )

    citation_dates = files[CITATION].values(_CITATION_DATE) if CITATION in files else []
    if len(citation_dates) != 1 or _DATE.fullmatch(citation_dates[0]) is None:
        problems.append(f"{CITATION}: expected one date-released: YYYY-MM-DD line, found {citation_dates}")
    if (root / CHANGELOG).is_file():
        headings = _TextFile(root, CHANGELOG).values(_changelog_heading(version.base))
        if not headings:
            problems.append(
                f"{CHANGELOG}: no '## [{version.base}] - <date>' heading; move the [Unreleased] entries "
                "under one, then date it with --date (RELEASING.md)"
            )
        elif citation_dates and headings[0] != citation_dates[0]:
            problems.append(
                f"{CITATION}: date-released is {citation_dates[0]}, but the {version.base} heading in "
                f"{CHANGELOG} says {headings[0]}; set both with --date"
            )
    else:
        problems.append(f"{CHANGELOG}: file not found")

    for pattern in GENERATED:
        for path in sorted(root.glob(pattern)):
            stale = sorted(
                set(_TextFile(root, path.relative_to(root).as_posix()).values(_GENERATED_STAMP)) - {version.text}
            )
            if stale:
                problems.append(
                    f"{path.relative_to(root).as_posix()}: records carry battinfo_version {', '.join(stale)}, "
                    f"expected {version.text}; rerun {' and '.join(GENERATORS)}"
                )
    return problems


def run_generators(root: Path = ROOT) -> None:
    """Rerun the generators whose output embeds the version, in a fresh interpreter each."""
    for script in GENERATORS:
        print(f"Running {script}", flush=True)
        subprocess.run([sys.executable, str(root / script)], cwd=root, check=True)


def set_version(root: Path, version: str, *, date: str | None = None, generate: bool = True) -> list[str]:
    """Write *version* and the stamps that follow from it; return the files that changed.

    Nothing is written when the version or the date is malformed, or when a stamp
    cannot be found. With *generate*, the generators rerun afterwards.
    """
    parsed = parse_version(version)
    if date is not None:
        _check_date(date)

    files = {CITATION: _TextFile(root, CITATION), CHANGELOG: _TextFile(root, CHANGELOG)}
    citation_moves = files[CITATION].values(_CITATION_VERSION) != [parsed.base]
    for stamp in STAMPS:
        if stamp.rel not in files:
            if not (root / stamp.rel).is_file() and not stamp.required:
                continue
            files[stamp.rel] = _TextFile(root, stamp.rel)
        if files[stamp.rel].set(stamp.pattern, stamp.value(parsed)) == 0 and stamp.required:
            raise ValueError(f"{stamp.rel}: found no {stamp.label} to set")

    changelog = files[CHANGELOG]
    heading = _changelog_heading(parsed.base)
    if date is None and citation_moves:
        dates = changelog.values(heading)
        date = dates[0] if dates else dt.date.today().isoformat()
        try:
            _check_date(date)
        except ValueError:
            raise ValueError(
                f"{CHANGELOG}: the {parsed.base} heading is dated {date!r}; give the release day with --date"
            ) from None
    if date is not None:
        if files[CITATION].set(_CITATION_DATE, date) == 0:
            raise ValueError(f"{CITATION}: found no date-released to set")
        changelog.set(heading, date)

    changed = [rel for rel, file in files.items() if file.write()]
    if generate:
        run_generators(root)
    return changed


def _report(root: Path, *, after_setting: bool = False) -> int:
    problems = check(root)
    if problems:
        print("Still to do:" if after_setting else "The version stamps disagree:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        if not after_setting:
            print("Set the version with: python scripts/set_version.py <version>", file=sys.stderr)
        return 1
    print(f"Version {read_version(root)}: every stamp agrees.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Set the battinfo version in every file that carries it, or check that they agree."
    )
    parser.add_argument("version", nargs="?", help="the version to set: 0.8.0, 0.8.0rc1, 0.8.0.dev1 ...")
    parser.add_argument("--date", help="the release date (YYYY-MM-DD) for CITATION.cff and the CHANGELOG.md heading")
    parser.add_argument("--check", action="store_true", help="change nothing; exit 1 if a stamp disagrees")
    parser.add_argument("--no-generate", action="store_true", help="do not rerun the generators")
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository (default: this checkout)")
    args = parser.parse_args(argv)

    if args.check:
        if args.version or args.date or args.no_generate:
            parser.error("--check takes no version, --date or --no-generate")
        return _report(args.root)
    if not args.version:
        parser.error("give the version to set, or --check")
    try:
        changed = set_version(args.root, args.version, date=args.date, generate=not args.no_generate)
    except (OSError, ValueError) as exc:
        print(f"set_version: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(
            f"set_version: the stamps are written, but {exc.cmd[-1]} failed (exit {exc.returncode}); "
            "fix what it reports and rerun it",
            file=sys.stderr,
        )
        return exc.returncode
    for rel in changed:
        print(f"Updated {rel}")
    if INIT in changed:
        print(
            "An editable install of battinfo keeps the old version in its metadata until it is reinstalled: "
            "uv sync and uv run do that, and a pip editable install needs pip install -e . again."
        )
    sys.stdout.flush()  # keep these lines ahead of the report's stderr in a shared log
    return _report(args.root, after_setting=True)


if __name__ == "__main__":
    raise SystemExit(main())
