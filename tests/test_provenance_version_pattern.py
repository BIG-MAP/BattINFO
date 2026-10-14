"""Records written by a release-candidate or development build validate.

Every record's provenance carries ``battinfo_version``, the version of the
build that wrote it (``battinfo.__version__``, stamped on save). Release
rehearsals run PEP 440 pre-release and development builds (0.8.0rc1,
0.8.0.dev1), so the schemas accept those versions as well as the hyphenated
X.Y.Z-suffix form they accepted before. Most record schemas carry their own
copy of the provenance block instead of referencing the module, so these
tests check every copy, and author a record of every kind under each version.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402
from battinfo.entities import ENTITY_KINDS, kind_for_doc  # noqa: E402

MODULE = ROOT / "assets" / "schemas" / "modules" / "common" / "provenance.schema.json"
SCHEMA_TREES = (ROOT / "assets" / "schemas", ROOT / "src" / "battinfo" / "data" / "schemas")
PROFILE_FRAGMENT = (
    ROOT / "src" / "battinfo" / "data" / "profiles" / "cell-spec" / "generated" / "provenance.schema.fragment.json"
)

_base_match = re.match(r"\d+\.\d+\.\d+", battinfo.__version__)
assert _base_match is not None, battinfo.__version__
BASE = _base_match.group(0)


def _module_definition() -> dict[str, Any]:
    return json.loads(MODULE.read_text(encoding="utf-8"))["properties"]["battinfo_version"]


def _version_definitions(node: Any, where: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every ``battinfo_version`` property declared anywhere in a schema document."""
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict) and isinstance(properties.get("battinfo_version"), dict):
            yield where, properties["battinfo_version"]
        for key, value in node.items():
            yield from _version_definitions(value, f"{where}/{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _version_definitions(item, f"{where}/{index}")


def _schema_documents() -> list[Path]:
    paths = [path for tree in SCHEMA_TREES for path in sorted(tree.rglob("*.json"))]
    return [*paths, PROFILE_FRAGMENT]


def test_every_schema_copy_uses_the_module_pattern() -> None:
    expected = _module_definition()["pattern"]
    found: list[str] = []
    stale: list[str] = []
    for path in _schema_documents():
        document = json.loads(path.read_text(encoding="utf-8"))
        for where, definition in _version_definitions(document, path.relative_to(ROOT).as_posix()):
            found.append(where)
            if definition.get("pattern") != expected:
                stale.append(f"{where}: pattern {definition.get('pattern')!r}")
            if "semantic versioning" in str(definition.get("description", "")):
                stale.append(f"{where}: description still says 'semantic versioning'")
    # Each schema tree carries the module and the copies, plus the profile fragment.
    assert len(found) > 2 * len(ENTITY_KINDS), found
    assert not stale, "battinfo_version differs from modules/common/provenance.schema.json:\n" + "\n".join(stale)


@pytest.mark.parametrize(
    "version",
    [
        "0.8.0",
        "0.8.0a1",
        "0.8.0b2",
        "0.8.0rc1",
        "0.8.0.dev1",
        "0.8.0rc1.dev2",
        "0.8.0.post1",
        "0.8.0+local.7",
        "0.8.0-rc1",
        "0.8.0-beta.2",
        "10.12.3",
    ],
)
def test_the_pattern_accepts_pep440_and_hyphenated_versions(version: str) -> None:
    from jsonschema import Draft202012Validator

    assert Draft202012Validator(_module_definition()).is_valid(version)


@pytest.mark.parametrize(
    "version",
    ["", "0.8", "v0.8.0", "0.8.0-", "0.8.0+", "0.8.0 rc1", "0.8.0rc1-", "latest"],
)
def test_the_pattern_rejects_other_strings(version: str) -> None:
    from jsonschema import Draft202012Validator

    assert not Draft202012Validator(_module_definition()).is_valid(version)


@pytest.fixture(scope="module")
def reference_generator() -> Any:
    """scripts/gen_reference_records.py, whose snippets author a record of every kind."""
    spec = importlib.util.spec_from_file_location(
        "gen_reference_records_for_versions", ROOT / "scripts" / "gen_reference_records.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("version", [f"{BASE}rc1", f"{BASE}.dev1"])
def test_records_of_every_kind_from_a_pre_release_build_validate_under_strict(
    version: str, reference_generator: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each reference snippet authors its record through the library, which stamps
    the version; build_sections then validates it under the strict policy (failing on
    any issue) and emits its JSON-LD. A schema copy left on an older pattern fails here."""
    monkeypatch.setattr(battinfo, "__version__", version)
    kinds: set[str] = set()
    for family in reference_generator.FAMILIES:
        try:
            sections = reference_generator.build_sections(family)
        except SystemExit as exc:
            pytest.fail(f"{family['slug']} at {version}: {exc}")
        for section in sections:
            record = section["record"]
            assert record["provenance"]["battinfo_version"] == version, (family["slug"], section["heading"])
            assert section["jsonld"], (family["slug"], section["heading"])
            kind = kind_for_doc(record)
            assert kind is not None, (family["slug"], section["heading"])
            kinds.add(kind.entity_type)
    assert kinds == {kind.entity_type for kind in ENTITY_KINDS}
