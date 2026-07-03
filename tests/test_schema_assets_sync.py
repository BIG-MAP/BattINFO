"""Every schema shipped in the package must match its source of truth in assets/schemas.

`profile.json`'s source_of_truth_order names `assets/schemas/...` as authoritative; the packaged
`src/battinfo/data/schemas/` tree is a synced copy. The per-family contract tests only gate a handful
of named top-level schemas, so `cell-spec.schema.json` and the `modules/components/*` sub-schemas could
(and did) drift silently. This gate covers the WHOLE packaged tree: edit assets/schemas first, then
re-sync the packaged copy."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "schemas"
PACKAGE = ROOT / "src" / "battinfo" / "data" / "schemas"

_PACKAGED = sorted(p.relative_to(PACKAGE).as_posix() for p in PACKAGE.rglob("*.json"))


def test_packaged_schema_tree_is_non_empty() -> None:
    assert _PACKAGED, "no packaged schemas found — path drift?"


@pytest.mark.parametrize("rel", _PACKAGED)
def test_packaged_schema_matches_assets_source_of_truth(rel: str) -> None:
    assets_path = ASSETS / rel
    assert assets_path.exists(), (
        f"{rel} is packaged but missing from assets/schemas (the source of truth). "
        "Add it to assets/schemas, then re-sync."
    )
    assets_doc = json.loads(assets_path.read_text(encoding="utf-8"))
    package_doc = json.loads((PACKAGE / rel).read_text(encoding="utf-8"))
    assert assets_doc == package_doc, (
        f"schema drift for {rel}: edit assets/schemas (the source of truth), then re-sync the "
        "packaged copy under src/battinfo/data/schemas."
    )
