"""The release version is set in one place and checked everywhere it is stamped.

scripts/set_version.py writes ``__version__`` and the stamps that follow from it
(battinfo.ttl, CITATION.cff, SECURITY.md), reruns the generators that embed the
version, and has a check mode. tests/installed_smoke.py compares the installed
distribution's version with ``battinfo.__version__`` instead of pinning one.
"""

from __future__ import annotations

import ast
import importlib.metadata
import importlib.util
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sv = _load("set_version", ROOT / "scripts" / "set_version.py")
smoke = _load("installed_smoke", ROOT / "tests" / "installed_smoke.py")

CURRENT = sv.read_version(ROOT)
BASE = sv.parse_version(CURRENT).base
STAMPED = ["src/battinfo/__init__.py", "battinfo.ttl", "CITATION.cff", "SECURITY.md", "CHANGELOG.md"]
GENERATED = [
    *(page.relative_to(ROOT).as_posix() for page in sorted((ROOT / "docs" / "records").glob("*.md"))),
    "web/lib/showcase.generated.ts",
]


def _copy_stamped_files(dest: Path) -> Path:
    for rel in [*STAMPED, "tests/installed_smoke.py", *GENERATED]:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    return dest


def _regenerate(root: Path, version: str) -> None:
    """What the generators change when the version moves: the provenance stamp."""
    for rel in GENERATED:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        path.write_text(
            re.sub(r'"battinfo_version": "[^"]*"', f'"battinfo_version": "{version}"', text), encoding="utf-8"
        )


def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


# ── installed_smoke: the installed distribution matches battinfo.__version__ ──


@pytest.mark.parametrize(
    ("version", "recorded"),
    [("0.8.0", "0.8.0"), ("0.8.0rc1", "0.8.0rc1"), ("0.8.0.dev1", "0.8.0.dev1"), ("0.8.0-rc1", "0.8.0rc1")],
)
def test_installed_smoke_spells_the_version_as_the_wheel_records_it(version: str, recorded: str) -> None:
    assert smoke.wheel_version(version) == recorded


@pytest.mark.parametrize("version", ["0.8.0", "0.8.0rc1", "0.8.0.dev1", "0.8.0-rc1", "0.8.0a2", "0.8.0b1"])
def test_installed_smoke_normalises_as_packaging_does(version: str) -> None:
    packaging_version = pytest.importorskip("packaging.version")
    assert smoke.wheel_version(version) == str(packaging_version.Version(version))


@pytest.mark.parametrize("version", ["0.8.0", "0.8.0rc1", "0.8.0.dev1", "0.8.0-rc1"])
def test_installed_smoke_version_check_passes_for_release_versions(
    version: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_version = importlib.metadata.version
    recorded = smoke.wheel_version(version)
    monkeypatch.setattr(battinfo, "__version__", version)
    monkeypatch.setattr(
        importlib.metadata, "version", lambda name: recorded if name == "battinfo" else real_version(name)
    )
    assert smoke.check_version() == recorded


def test_installed_smoke_version_check_fails_on_a_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    real_version = importlib.metadata.version
    monkeypatch.setattr(battinfo, "__version__", "0.8.0rc1")
    monkeypatch.setattr(
        importlib.metadata, "version", lambda name: "0.8.0" if name == "battinfo" else real_version(name)
    )
    with pytest.raises(AssertionError, match="0.8.0rc1"):
        smoke.check_version()


def test_installed_smoke_pins_no_version_and_uses_only_the_curated_top_level() -> None:
    source = _read(ROOT, "tests/installed_smoke.py")
    assert "__version__ ==" not in source
    used = {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "battinfo"
    }
    assert used and used <= set(battinfo.__all__), sorted(used - set(battinfo.__all__))


# ── set_version.py --check ──


def test_the_repository_version_stamps_agree() -> None:
    problems = sv.check(ROOT)
    assert not problems, (
        "the version stamps disagree with __version__; set the version with "
        "`python scripts/set_version.py <version>` (RELEASING.md step 1):\n" + "\n".join(problems)
    )


def test_check_mode_exits_zero_on_this_checkout(capsys: pytest.CaptureFixture[str]) -> None:
    assert sv.main(["--check"]) == 0
    assert CURRENT in capsys.readouterr().out


@pytest.mark.parametrize(
    ("rel", "pattern", "replacement"),
    [
        ("src/battinfo/__init__.py", r'^__version__ = "[^"]*"$', '__version__ = "0.8"'),
        ("battinfo.ttl", r'owl:versionInfo "[^"]*"', 'owl:versionInfo "0.0.9"'),
        ("battinfo.ttl", r"battinfo/[^/>]+/battinfo>", "battinfo/0.0.9/battinfo>"),
        ("CITATION.cff", r"^version: .*$", "version: 0.0.9"),
        ("CITATION.cff", r"^date-released: .*$", "date-released: 1999-01-01"),
        ("CITATION.cff", r"^# Set to the day the v\S+ tag", "# Set to the day the v0.0.9 tag"),
        ("SECURITY.md", r"^\| \d+\.\d+\.x \|", "| 0.0.x |"),
        ("SECURITY.md", r"^\| < \d+\.\d+\.\d+ \|", "| < 0.0.1 |"),
        (
            "tests/installed_smoke.py",
            r"^def main\(\) -> None:$",
            'def main() -> None:\n    assert battinfo.__version__ == "0.0.9"',
        ),
        ("docs/records/cells.md", r'"battinfo_version": "[^"]*"', '"battinfo_version": "0.0.9"'),
        ("web/lib/showcase.generated.ts", r'"battinfo_version": "[^"]*"', '"battinfo_version": "0.0.9"'),
    ],
)
def test_check_mode_names_a_stamp_that_disagrees(
    tmp_path: Path, rel: str, pattern: str, replacement: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _copy_stamped_files(tmp_path)
    text, count = re.subn(pattern, replacement, _read(root, rel), count=1, flags=re.MULTILINE)
    assert count == 1, (rel, pattern)
    (root / rel).write_text(text, encoding="utf-8")
    problems = sv.check(root)
    assert problems and all(rel in problem for problem in problems), problems
    assert sv.main(["--check", "--root", str(root)]) == 1
    assert rel in capsys.readouterr().err


def test_check_mode_wants_the_changelog_heading_for_the_release(tmp_path: Path) -> None:
    root = _copy_stamped_files(tmp_path)
    changelog = _read(root, "CHANGELOG.md")
    (root / "CHANGELOG.md").write_text(changelog.replace(f"## [{BASE}] - ", "## [9.9.9] - ", 1), encoding="utf-8")
    problems = sv.check(root)
    assert len(problems) == 1 and "CHANGELOG.md" in problems[0] and BASE in problems[0], problems


# ── set_version.py: writing a version ──


@pytest.mark.parametrize("suffix", ["rc", ".dev"])
def test_a_pre_release_sets_only_the_package_version(tmp_path: Path, suffix: str) -> None:
    root = _copy_stamped_files(tmp_path)
    # A version other than the current one, which on an rc branch may itself be X.Y.Zrc1.
    version = next(f"{BASE}{suffix}{n}" for n in range(1, 4) if f"{BASE}{suffix}{n}" != CURRENT)
    sv.set_version(root, version, generate=False)

    assert f'__version__ = "{version}"' in _read(root, "src/battinfo/__init__.py")
    for rel in ("battinfo.ttl", "CITATION.cff", "SECURITY.md", "CHANGELOG.md"):
        assert (root / rel).read_bytes() == (ROOT / rel).read_bytes(), rel
    # Until the generators run, their output still carries the old version.
    stale = sv.check(root)
    assert stale and all(any(rel in problem for rel in GENERATED) for problem in stale), stale
    _regenerate(root, version)
    assert sv.check(root) == []


def test_a_new_release_moves_every_stamp(tmp_path: Path) -> None:
    root = _copy_stamped_files(tmp_path)
    sv.set_version(root, "9.10.0", date="2031-02-03", generate=False)

    assert '__version__ = "9.10.0"' in _read(root, "src/battinfo/__init__.py")
    ttl = _read(root, "battinfo.ttl")
    assert "owl:versionIRI <https://w3id.org/battinfo/9.10.0/battinfo>" in ttl
    assert 'owl:versionInfo "9.10.0"' in ttl
    citation = _read(root, "CITATION.cff")
    assert re.search(r"^version: 9\.10\.0$", citation, re.MULTILINE)
    assert re.search(r"^date-released: 2031-02-03$", citation, re.MULTILINE)
    assert "v9.10.0 tag" in citation
    security = _read(root, "SECURITY.md")
    assert "| 9.10.x | :white_check_mark: |" in security
    assert "| < 9.10.0 | :x: |" in security

    _regenerate(root, "9.10.0")
    problems = sv.check(root)
    assert len(problems) == 1 and "CHANGELOG.md" in problems[0], problems
    changelog = _read(root, "CHANGELOG.md")
    (root / "CHANGELOG.md").write_text(
        changelog.replace("## [Unreleased]", "## [Unreleased]\n\n## [9.10.0] - 2031-02-03", 1), encoding="utf-8"
    )
    assert sv.check(root) == []


def test_a_release_rc_of_a_new_version_takes_the_changelog_date(tmp_path: Path) -> None:
    root = _copy_stamped_files(tmp_path)
    changelog = _read(root, "CHANGELOG.md")
    (root / "CHANGELOG.md").write_text(
        changelog.replace("## [Unreleased]", "## [Unreleased]\n\n## [9.10.0] - 2031-02-03", 1), encoding="utf-8"
    )
    sv.set_version(root, "9.10.0rc2", generate=False)
    citation = _read(root, "CITATION.cff")
    assert re.search(r"^version: 9\.10\.0$", citation, re.MULTILINE)
    assert re.search(r"^date-released: 2031-02-03$", citation, re.MULTILINE)
    _regenerate(root, "9.10.0rc2")
    assert sv.check(root) == []


def test_date_sets_the_citation_and_changelog_release_date(tmp_path: Path) -> None:
    root = _copy_stamped_files(tmp_path)
    sv.set_version(root, BASE, date="2031-02-03", generate=False)
    assert re.search(r"^date-released: 2031-02-03$", _read(root, "CITATION.cff"), re.MULTILINE)
    assert f"## [{BASE}] - 2031-02-03" in _read(root, "CHANGELOG.md")
    _regenerate(root, BASE)
    assert sv.check(root) == []


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_line_endings_are_kept(tmp_path: Path, newline: bytes) -> None:
    root = _copy_stamped_files(tmp_path)
    citation = root / "CITATION.cff"
    citation.write_bytes(citation.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", newline))
    sv.set_version(root, BASE, date="2031-02-03", generate=False)
    data = citation.read_bytes()
    assert b"date-released: 2031-02-03" + newline in data
    assert data.count(b"\r\n") == (data.count(b"\n") if newline == b"\r\n" else 0)


def test_an_installed_smoke_pin_follows_the_version(tmp_path: Path) -> None:
    root = _copy_stamped_files(tmp_path)
    smoke_path = root / "tests" / "installed_smoke.py"
    smoke_path.write_text(
        _read(root, "tests/installed_smoke.py").replace(
            "def main() -> None:", f'def main() -> None:\n    assert battinfo.__version__ == "{CURRENT}"', 1
        ),
        encoding="utf-8",
    )
    sv.set_version(root, f"{BASE}rc1", generate=False)
    assert f'battinfo.__version__ == "{BASE}rc1"' in _read(root, "tests/installed_smoke.py")


@pytest.mark.parametrize("version", ["0.8", "v0.8.0", "0.8.0+local", "0.8.0rc", "0.08.0", "0.8.0.rc1", "latest"])
def test_a_version_the_script_cannot_stamp_is_refused(tmp_path: Path, version: str) -> None:
    root = _copy_stamped_files(tmp_path)
    with pytest.raises(ValueError, match="version"):
        sv.set_version(root, version, generate=False)
    assert _read(root, "src/battinfo/__init__.py") == _read(ROOT, "src/battinfo/__init__.py")


def test_a_malformed_date_is_refused(tmp_path: Path) -> None:
    root = _copy_stamped_files(tmp_path)
    with pytest.raises(ValueError, match="date"):
        sv.set_version(root, BASE, date="13 October 2026", generate=False)
