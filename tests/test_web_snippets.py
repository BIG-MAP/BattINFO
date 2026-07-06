"""The website's publishing recipe cannot drift from ws.quickstart().

The homepage hero (web/lib/examples.ts: publishJourneySnippet) and the /publish
pipeline stages (web/lib/content.ts: publishJourney) show ws.* code. If the
library renames a verb or reorders the taught sequence, ws.quickstart() changes
— and these tests fail until the website is updated to match. Same guard
philosophy as the executable docs funnel, applied to marketing.
"""
from __future__ import annotations

import io
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402

WEB = ROOT / "web" / "lib"


def _quickstart_text(tmp_path: Path) -> str:
    ws = battinfo.workspace(root=tmp_path)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        ws.quickstart()
    return buffer.getvalue()


def _ws_verbs(text: str) -> list[str]:
    return re.findall(r"\bws\.([a-z_]+)\(", text)


def _ts_constant(file: Path, name: str) -> str:
    source = file.read_text(encoding="utf-8")
    match = re.search(rf"export const {name} = `(.*?)`;", source, re.DOTALL)
    assert match, f"{name} not found in {file.name}"
    return match.group(1)


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    it = iter(haystack)
    return all(item in it for item in needle)


@pytest.fixture()
def quickstart(tmp_path: Path) -> str:
    return _quickstart_text(tmp_path)


def test_hero_snippet_teaches_the_quickstart_sequence(quickstart: str) -> None:
    hero = _ts_constant(WEB / "examples.ts", "publishJourneySnippet")
    hero_verbs = _ws_verbs(hero)
    recipe_verbs = _ws_verbs(quickstart)
    assert hero_verbs, "hero snippet must contain ws.* calls"
    assert _is_subsequence(hero_verbs, recipe_verbs), (
        f"homepage hero teaches {hero_verbs}, but ws.quickstart() teaches "
        f"{recipe_verbs} — update web/lib/examples.ts to match the library"
    )
    assert "battinfo.workspace(" in hero and "battinfo.workspace(" in quickstart


def test_publish_page_stages_use_real_verbs(quickstart: str) -> None:
    content = (WEB / "content.ts").read_text(encoding="utf-8")
    match = re.search(r"export const publishJourney = \[(.*?)\] as const;", content, re.DOTALL)
    assert match, "publishJourney not found in content.ts"
    stage_verbs = set(_ws_verbs(match.group(1)))
    recipe_verbs = set(_ws_verbs(quickstart))
    unknown = stage_verbs - recipe_verbs
    assert not unknown, (
        f"/publish page uses ws verbs {sorted(unknown)} that ws.quickstart() does not teach — "
        "update web/lib/content.ts or the quickstart recipe"
    )


def test_quickstart_recipe_itself_mentions_the_payoffs(quickstart: str) -> None:
    # The web hero promises a DOI and the registry; the recipe must actually
    # deliver both mentions, or the promise is marketing-only.
    assert "zenodo" in quickstart.lower()
    assert "publish" in quickstart.lower()
