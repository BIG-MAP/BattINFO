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


def test_convert_page_matrix_matches_the_library_guidance(tmp_path: Path) -> None:
    """Every format the /convert capability matrix lists must appear in the
    library's own convert() guidance — the web page cannot overpromise."""
    ws = battinfo.workspace(root=tmp_path)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        ws.convert()  # empty workspace -> prints the full capability guidance
    guidance = buffer.getvalue()

    content = (WEB / "content.ts").read_text(encoding="utf-8")
    match = re.search(r"export const converterMatrix = \{(.*?)\} as const;", content, re.DOTALL)
    assert match, "converterMatrix not found in content.ts"
    extensions = re.findall(r'ext:\s*"([^"]+)"', match.group(1))
    assert extensions, "converterMatrix lists no extensions"
    missing = [ext for ext in extensions if ext not in guidance]
    assert not missing, (
        f"/convert lists {missing} but ws.convert()'s guidance does not mention them — "
        "update web/lib/content.ts converterMatrix or the library guidance"
    )


def test_web_validator_discriminators_match_the_entity_registry() -> None:
    """The browser validator's record-type map must mirror battinfo.entities.

    A new record type added to ENTITY_KINDS without updating web/lib/validate.ts
    would silently fail closed in the browser for a record the library accepts.
    """
    from battinfo.entities import ENTITY_KINDS

    source = (WEB / "validate.ts").read_text(encoding="utf-8")
    match = re.search(r"export const DISCRIMINATORS[^=]*= \{(.*?)\};", source, re.DOTALL)
    assert match, "DISCRIMINATORS not found in web/lib/validate.ts"
    web_map = dict(re.findall(r'(\w+):\s*"([^"]+)"', match.group(1)))

    expected = {kind.record_key: kind.schema_file for kind in ENTITY_KINDS}
    expected["organization"] = "organization.schema.json"  # not an ENTITY_KIND yet

    assert web_map == expected, (
        "web/lib/validate.ts DISCRIMINATORS drifted from battinfo.entities.ENTITY_KINDS: "
        f"web-only={set(web_map) - set(expected)}, missing={set(expected) - set(web_map)}"
    )


def test_docs_page_quickstart_python_executes(tmp_path: Path) -> None:
    """The /docs quickstart snippet must RUN, not just look plausible.

    Red-team: the site's own quickstart used cell_format= (which CellSpec
    rejects) and crashed verbatim - the drift suite only covered the hero
    snippet. Every self-contained Python constant on the site executes here.
    """
    snippet = _ts_constant(WEB / "examples.ts", "quickstartPython")
    import contextlib
    import io
    import os

    cwd = os.getcwd()
    buffer = io.StringIO()
    try:
        os.chdir(tmp_path)  # publish(destination="local") writes .battinfo/ here
        with contextlib.redirect_stdout(buffer):
            exec(compile(snippet, "<web quickstartPython>", "exec"), {})  # noqa: S102
    finally:
        os.chdir(cwd)
    assert "w3id.org/battinfo/spec/" in buffer.getvalue()
