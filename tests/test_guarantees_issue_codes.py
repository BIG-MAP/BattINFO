"""The issue codes docs/guarantees.md lists are codes the validator emits.

Integrators match on these codes, so a listed code that nothing emits sends them
looking for an issue that never comes.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARANTEES = ROOT / "docs" / "guarantees.md"
SOURCE = ROOT / "src" / "battinfo"


def _listed_codes() -> list[str]:
    text = GUARANTEES.read_text(encoding="utf-8")
    section = text.split("Representative issue codes:", 1)[1].split("\n### ", 1)[0]
    return sorted(set(re.findall(r"`([a-z_]+(?:\.[a-z_]+)+)`", section)))


def _source_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in SOURCE.rglob("*.py"))


def test_every_listed_issue_code_is_emitted() -> None:
    codes = _listed_codes()
    assert "jsonld.parse_error" in codes
    source = _source_text()
    # schema.* codes are built from the JSON Schema keyword that failed
    # (schema.required, schema.format.uri); every other code is a literal.
    assert 'return f"schema.format.{fmt}"' in source and 'return f"schema.{validator}"' in source
    missing = [code for code in codes if not code.startswith("schema.") and f'"{code}"' not in source]
    assert missing == [], f"docs/guarantees.md lists issue codes nothing emits: {missing}"
