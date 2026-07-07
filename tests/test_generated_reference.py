"""Committed generated reference pages must match what the code produces today."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load(script: str):
    spec = importlib.util.spec_from_file_location(script, ROOT / "scripts" / f"{script}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schema_reference_matches_the_schemas() -> None:
    gen = _load("gen_schema_reference")
    expected = gen.build()
    actual = gen.OUT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert actual == expected.replace("\r\n", "\n"), (
        "docs/pages/schema-reference.md drifts — run `uv run python scripts/gen_schema_reference.py`"
    )


def test_cli_reference_matches_the_typer_app() -> None:
    # gen_cli_reference normalises path separators, so the committed page is
    # byte-identical no matter which platform generated or checks it.
    gen = _load("gen_cli_reference")
    expected = gen.build()
    actual = gen.OUT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert actual == expected, (
        "docs/pages/cli-reference.md drifts from the CLI — regenerate with "
        "`uv run python scripts/gen_cli_reference.py`"
    )


def test_battinfo_vocab_covers_every_emitted_term() -> None:
    gen = _load("gen_battinfo_vocab")

    committed = (ROOT / "assets" / "vocab" / "battinfo-records.ttl").read_text(encoding="utf-8")
    assert committed == gen.build(), (
        "assets/vocab/battinfo-records.ttl is stale - a battinfo: term was "
        "added/removed; regenerate with `uv run python scripts/gen_battinfo_vocab.py`"
    )


def test_property_reference_matches_the_mapping_tables() -> None:
    gen = _load("gen_property_reference")

    committed = (ROOT / "docs" / "pages" / "property-reference.md").read_text(encoding="utf-8")
    assert committed == gen.build(), (
        "docs/pages/property-reference.md is stale - regenerate with "
        "`uv run python scripts/gen_property_reference.py`"
    )
