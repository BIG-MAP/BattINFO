"""The record IRI patterns of the v1 JSON Schemas accept both record shapes (BIG-MAP/BattINFO#478).

Every pattern that reads a record IRI is built by ``battinfo.namespace`` and
written by ``scripts/sync_schema_iri_patterns.py``. It accepts the old form
``https://w3id.org/battinfo/{segment}/{uid}`` and the prefixed form
``https://w3id.org/battinfo/id/{prefix}/{segment}/{uid}``. A pattern that reads
a reference to a maker, a product model or a material also accepts a shared
thing, ``https://w3id.org/battinfo/id/{uid}``; a record's own id never does.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.validate.schema import schema_for_rel_path, validate_schema_data  # noqa: E402

UID = "b6yn-0sxe-t2qk-9mjv"
THING = f"https://w3id.org/battinfo/id/{UID}"
SCHEMAS = ROOT / "src" / "battinfo" / "data" / "schemas"


def _sync_script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "sync_schema_iri_patterns", ROOT / "scripts" / "sync_schema_iri_patterns.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SYNC = _sync_script()


def _schema_patterns() -> list[tuple[str, tuple[str, ...], str]]:
    found = []
    for path in sorted(SCHEMAS.rglob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        rel = path.relative_to(SCHEMAS).as_posix()
        found += [(rel, where, node["pattern"]) for where, node in SYNC._patterns(document)]
    return found


PATTERNS = _schema_patterns()


def test_every_pattern_is_the_one_the_namespace_module_builds() -> None:
    stale = []
    for tree in SYNC.TREES:
        for path in sorted(tree.rglob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            stale += SYNC.synced(document, path.relative_to(ROOT).as_posix())
    assert not stale, "Run `uv run python scripts/sync_schema_iri_patterns.py`:\n" + "\n".join(stale)


def test_the_schemas_carry_the_patterns_of_the_erratum() -> None:
    """84 record IRI patterns in 32 files, plus the three reference $defs split from an own-id one."""
    assert len(PATTERNS) == 87
    assert len({rel for rel, _, _ in PATTERNS}) == 32
    assert sum(SYNC._takes_things(where) for _, where, _ in PATTERNS) == 31


@pytest.mark.parametrize(("rel", "where", "pattern"), PATTERNS, ids=[f"{r}#/{'/'.join(w)}" for r, w, _ in PATTERNS])
def test_a_pattern_accepts_both_shapes_and_a_thing_only_where_it_reads_a_reference(
    rel: str, where: tuple[str, ...], pattern: str
) -> None:
    compiled = re.compile(pattern)
    segments = SYNC._segments(pattern, rel)
    other = next(name for name in ("dataset", "cell", "organization") if name not in segments)
    for segment in segments:
        for iri in (
            f"https://w3id.org/battinfo/{segment}/{UID}",
            f"https://w3id.org/battinfo/id/1001/{segment}/{UID}",
            f"https://w3id.org/battinfo/id/1002/{segment}/{UID}",
        ):
            assert compiled.search(iri), iri
        for iri in (
            f"https://w3id.org/battinfo/id/1/{segment}/{UID}",
            f"https://w3id.org/battinfo/id/abc/{segment}/{UID}",
            f"https://w3id.org/battinfo/{segment}/{UID[:-1]}I",
            f"https://w3id.org/battinfo/id/1001/{UID}",
        ):
            assert not compiled.search(iri), iri
    assert not compiled.search(f"https://w3id.org/battinfo/{other}/{UID}")
    assert bool(compiled.search(THING)) is SYNC._takes_things(where)


# ── Whole records ───────────────────────────────────────────────────────────


def _example(relative: str) -> dict[str, Any]:
    return json.loads((ROOT / "examples" / relative).read_text(encoding="utf-8"))


def _errors(document: dict[str, Any], schema: str) -> list[str]:
    report = validate_schema_data(document, schema_for_rel_path(schema))
    return [f"{issue.path}: {issue.message}" for issue in report.issues]


def _with(document: dict[str, Any], *path_and_value: Any) -> dict[str, Any]:
    out = copy.deepcopy(document)
    *path, key, value = path_and_value
    node = out
    for step in path:
        node = node[step]
    node[key] = value
    return out


def test_an_organization_takes_a_prefixed_own_id_and_a_shared_parent_but_never_a_thing_as_its_own_id() -> None:
    record = _example("organization/A123.json")
    assert _errors(record, "organization.schema.json") == []
    prefixed = _with(record, "organization", "id", f"https://w3id.org/battinfo/id/1002/organization/{UID}")
    assert _errors(prefixed, "organization.schema.json") == []
    assert _errors(_with(record, "organization", "parent_organization", THING), "organization.schema.json") == []
    assert _errors(_with(record, "organization", "id", THING), "organization.schema.json")


def test_a_manufacturer_may_be_a_shared_thing() -> None:
    record = _example("cell-spec/A123__ANR26650M1-B.json")
    assert _errors(_with(record, "cell_spec", "manufacturer", "id", THING), "cell-spec.schema.json") == []
    assert _errors(_with(record, "cell_spec", "id", THING), "cell-spec.schema.json")


def test_a_cell_may_point_at_a_product_model_and_any_hub_but_is_never_a_thing_itself() -> None:
    record = _example("cell-instance/cell-3m6k-9t2p-7x4h-9nq8.json")
    assert _errors(record, "cell-instance.schema.json") == []
    for spec in (THING, f"https://w3id.org/battinfo/id/1002/spec/{UID}"):
        assert _errors(_with(record, "cell_instance", "cell_spec_id", spec), "cell-instance.schema.json") == []
    prefixed = _with(record, "cell_instance", "id", f"https://w3id.org/battinfo/id/1001/cell/{UID}")
    assert _errors(prefixed, "cell-instance.schema.json") == []
    assert _errors(_with(record, "cell_instance", "id", THING), "cell-instance.schema.json")
    assert _errors(
        _with(record, "cell_instance", "id", f"https://w3id.org/battinfo/id/1/cell/{UID}"), "cell-instance.schema.json"
    )


def test_a_material_lot_may_point_at_a_shared_material() -> None:
    record = _example("material/material-4azv-ppez-1aeg-14yv.json")
    assert _errors(record, "material.schema.json") == []
    assert _errors(_with(record, "material", "material_spec_id", THING), "material.schema.json") == []
    assert _errors(_with(record, "material", "supplier", "id", THING), "material.schema.json") == []
    assert _errors(_with(record, "material", "id", THING), "material.schema.json")
