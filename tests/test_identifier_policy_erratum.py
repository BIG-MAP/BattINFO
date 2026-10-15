"""Guard: the erratum to section 11.1 of IDENTIFIER_POLICY.md stays complete and reachable.

Section 11.1 freezes the v1 records context and the served schemas from the
v0.8.0 tag. Its erratum lists every change made to them in place before the tag,
so that someone holding an earlier copy can tell what differs. Each entry of
``PRE_RELEASE_CORRECTIONS`` in ``scripts/gen_context.py`` is such a change, so it
has to be listed there. The changelog and the docs point at the erratum, and
those links have to land on a heading that exists.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "IDENTIFIER_POLICY.md"
CHANGELOG = ROOT / "CHANGELOG.md"
ERRATUM_HEADING = "Erratum: changes made in place before 0.8.0"
ERRATUM_ANCHOR = "erratum-changes-made-in-place-before-080"

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_POLICY_LINK = re.compile(r"IDENTIFIER_POLICY\.md#([^)\s>\"']+)")
_LOCAL_LINK = re.compile(r"\]\(#([^)\s]+)\)")


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_context", ROOT / "scripts" / "gen_context.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def github_anchor(heading: str) -> str:
    """The fragment GitHub gives a Markdown heading: lower case, punctuation dropped, spaces as hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _headings(text: str) -> list[tuple[int, str]]:
    """(level, title) of each heading outside fenced code blocks."""
    found, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        match = None if fenced else _HEADING.match(line)
        if match:
            found.append((len(match.group(1)), match.group(2)))
    return found


def _erratum(text: str) -> str:
    """The erratum's text, from its heading to the next heading of the same or a higher level."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.lstrip("#").strip() == ERRATUM_HEADING)
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if (match := _HEADING.match(lines[i])) and len(match.group(1)) <= level
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _documents_linking_the_policy() -> list[Path]:
    paths = [ROOT / name for name in ("CHANGELOG.md", "AGENTS.md", "RELEASING.md", "README.md", "CONTRIBUTING.md")]
    paths += sorted((ROOT / "docs").rglob("*.md"))
    return [path for path in paths if path.is_file()]


def test_github_anchor_matches_github() -> None:
    assert github_anchor(ERRATUM_HEADING) == ERRATUM_ANCHOR
    assert github_anchor("11.1 Served-Artifact Immutability") == "111-served-artifact-immutability"
    assert github_anchor("The `v1` records context") == "the-v1-records-context"


def test_the_erratum_is_a_heading_under_section_11_1() -> None:
    headings = _headings(POLICY.read_text(encoding="utf-8"))
    titles = [title for _, title in headings]
    assert ERRATUM_HEADING in titles, f"IDENTIFIER_POLICY.md has no heading {ERRATUM_HEADING!r}"
    section = titles.index("11.1 Served-Artifact Immutability")
    assert titles.index(ERRATUM_HEADING) > section
    assert headings[titles.index(ERRATUM_HEADING)][0] > headings[section][0], "the erratum belongs inside 11.1"


def test_every_pre_release_correction_is_in_the_erratum() -> None:
    """A correction of v1 before the tag is an in-place change, so the erratum must name its term."""
    named = set(re.findall(r"`([^`]+)`", _erratum(POLICY.read_text(encoding="utf-8"))))
    missing = sorted(set(_load_gen().PRE_RELEASE_CORRECTIONS) - named)
    assert not missing, (
        f"PRE_RELEASE_CORRECTIONS changes {missing} in place, but the erratum to section 11.1 of "
        "IDENTIFIER_POLICY.md does not list them. Add each term to its table of v1 terms."
    )


def test_links_into_the_identifier_policy_land_on_a_heading() -> None:
    policy = POLICY.read_text(encoding="utf-8")
    anchors = {github_anchor(title) for _, title in _headings(policy)}
    broken = [f"IDENTIFIER_POLICY.md: #{anchor}" for anchor in _LOCAL_LINK.findall(policy) if anchor not in anchors]
    for path in _documents_linking_the_policy():
        for anchor in _POLICY_LINK.findall(path.read_text(encoding="utf-8")):
            if anchor not in anchors:
                broken.append(f"{path.relative_to(ROOT).as_posix()}: IDENTIFIER_POLICY.md#{anchor}")
    assert not broken, "links to headings IDENTIFIER_POLICY.md does not have:\n" + "\n".join(broken)


def test_changelog_mentions_of_the_erratum_link_to_it() -> None:
    """Each changelog entry that sends the reader to the erratum links to it, so the pointer can be followed."""
    unlinked = [
        line.strip()[:120]
        for line in CHANGELOG.read_text(encoding="utf-8").splitlines()
        if re.search(r"erratum", line, re.IGNORECASE)
        and "11.1" in line
        and f"IDENTIFIER_POLICY.md#{ERRATUM_ANCHOR}" not in line
    ]
    assert not unlinked, (
        "These changelog entries mention the erratum to section 11.1 without linking to it; write the "
        f"reference as [the erratum to section 11.1 of IDENTIFIER_POLICY.md](IDENTIFIER_POLICY.md#{ERRATUM_ANCHOR}):\n"
        + "\n".join(unlinked)
    )
