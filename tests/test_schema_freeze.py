"""Guard: from the v0.8.0 tag a served schema changes in place only in its annotations.

Section 11.1 of IDENTIFIER_POLICY.md freezes the JSON Schemas served under
``https://w3id.org/battinfo/schema/`` at the v0.8.0 tag. At a published URL a
schema may change only in ``description``, ``title``, ``$comment`` or
``examples``; any other change, a new optional property included, goes to a new
versioned URL. The registry serves the copies bundled in
``src/battinfo/data/schemas/``, so in a checkout that has release tags from
v0.8.0 on, each schema a tag holds must still be there, with the same content
once those four annotations are set aside. Without the tags (a shallow CI clone
or an sdist) the check skips, and review holds the line.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = "src/battinfo/data/schemas"
CELL_SPEC = f"{SCHEMAS}/cell-spec.schema.json"

# The edits section 11.1 allows in place.
ANNOTATIONS = frozenset({"description", "title", "$comment", "examples"})
# Keywords whose value maps names to subschemas: the names are data, not keywords.
_SUBSCHEMA_MAPS = frozenset({"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"})
# Keywords whose value is data, never a subschema.
_DATA = frozenset({"const", "enum", "default", "required", "dependentRequired"})
_FINAL_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def validation_content(schema: Any) -> Any:
    """*schema* without the annotations that may change in place."""
    if isinstance(schema, list):
        return [validation_content(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    content = {}
    for key, value in schema.items():
        if key in ANNOTATIONS:
            continue
        if key in _DATA:
            content[key] = value
        elif key in _SUBSCHEMA_MAPS and isinstance(value, dict):
            content[key] = {name: validation_content(sub) for name, sub in value.items()}
        else:
            content[key] = validation_content(value)
    return content


def tagged_schema_problems(
    tags: Iterable[str],
    list_schemas: Callable[[str], list[str]],
    read: Callable[[str, str], str],
    root: Path = ROOT,
) -> list[str]:
    """Each schema a tag holds that the checkout has removed or changes beyond its annotations."""
    problems = []
    for tag in tags:
        for path in list_schemas(tag):
            current = root / path
            if not current.exists():
                problems.append(f"{tag}: {path} removed")
                continue
            tagged = validation_content(json.loads(read(tag, path)))
            if validation_content(json.loads(current.read_text(encoding="utf-8"))) != tagged:
                problems.append(f"{tag}: {path} changes what it accepts")
    return problems


def _final_release_tags() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "tag", "--list", "v*"], capture_output=True, text=True, check=False
        )
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [
        tag
        for tag in result.stdout.split()
        if (match := _FINAL_TAG.match(tag)) and tuple(int(part) for part in match.groups()) >= (0, 8, 0)
    ]


def _schemas_at(tag: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", tag, "--", SCHEMAS],
        capture_output=True,
        text=True,
        check=True,
    )
    return [path for path in result.stdout.split() if path.endswith(".json")]


def _read_at(tag: str, path: str) -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{tag}:{path}"], capture_output=True, check=True
    ).stdout.decode("utf-8")


def test_served_schemas_keep_what_they_accept_from_each_tagged_release() -> None:
    tags = _final_release_tags()
    if not tags:
        pytest.skip("this checkout has no release tag from v0.8.0 on")
    problems = tagged_schema_problems(tags, _schemas_at, _read_at)
    assert not problems, (
        "A schema served at a published URL changes in place only in description, title, $comment or "
        "examples (IDENTIFIER_POLICY.md section 11.1); publish any other change at a new versioned URL. "
        + "; ".join(problems)
    )


def test_validation_content_drops_only_the_annotations() -> None:
    schema = {
        "title": "Thing",
        "description": "A thing.",
        "$comment": "note",
        "examples": [{"description": "kept as data"}],
        "type": "object",
        "required": ["description"],
        "properties": {
            "description": {"type": "string", "description": "A property named description."},
            "kind": {"enum": ["a", "b"], "title": "Kind"},
            "nested": {"const": {"title": "data, not an annotation"}},
        },
        "additionalProperties": False,
    }
    assert validation_content(schema) == {
        "type": "object",
        "required": ["description"],
        "properties": {
            "description": {"type": "string"},
            "kind": {"enum": ["a", "b"]},
            "nested": {"const": {"title": "data, not an annotation"}},
        },
        "additionalProperties": False,
    }


def test_tagged_schema_check_allows_annotation_edits_only(tmp_path) -> None:
    tagged_text = (ROOT / CELL_SPEC).read_text(encoding="utf-8")
    checkout = tmp_path / "checkout"
    current = checkout / CELL_SPEC
    current.parent.mkdir(parents=True)

    def check(schema: dict | None) -> list[str]:
        if schema is None:
            current.unlink(missing_ok=True)
        else:
            current.write_text(json.dumps(schema), encoding="utf-8")
        return tagged_schema_problems(["v0.8.0"], lambda tag: [CELL_SPEC], lambda tag, path: tagged_text, checkout)

    schema = json.loads(tagged_text)
    assert check(schema) == []

    schema["description"] = "Reworded."
    schema["title"] = "Retitled"
    schema["$comment"] = "A note added after the release."
    assert check(schema) == []

    schema = json.loads(tagged_text)
    schema["properties"]["added_after_the_release"] = {"type": "string"}
    assert check(schema) == [f"v0.8.0: {CELL_SPEC} changes what it accepts"]

    schema = json.loads(tagged_text)
    schema["required"] = [*schema.get("required", []), "added_requirement"]
    assert check(schema) == [f"v0.8.0: {CELL_SPEC} changes what it accepts"]

    assert check(None) == [f"v0.8.0: {CELL_SPEC} removed"]
