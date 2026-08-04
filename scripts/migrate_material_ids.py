#!/usr/bin/env python
"""Re-mint random-id material records to deterministic content-derived ids.

Before the first-class materials model, ``create_material_spec`` minted a random
IRI on every call (readiness report H1), so existing corpora accumulated
material-spec / material records whose ids carry no identity. This script re-mints
them the way the engine now does — material-spec from (manufacturer, product,
grade, kind); material instance from (spec_id, lot) — rewrites the record files,
fixes cross-references (material instance -> spec; cell-spec electrode components'
``material_spec_id`` / composition ``base_material_id``), and prints the
old-id -> new-id map.

It covers the RECORD-FILE side only. The registry supersede/backfill (so old IRIs
resolve forever per IDENTIFIER_POLICY) is operated separately with the map this
prints. It does NOT touch battinfo-records or any OCV branch — point it at a copy.

Usage::

    # dry run: print the id map, write nothing
    python scripts/migrate_material_ids.py --source-root path/to/records

    # apply: rewrite files (renamed to the new uid) and emit the map JSON
    python scripts/migrate_material_ids.py --source-root path/to/records --write \\
        --map-out material-id-map.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from battinfo.entities import stable_uid
from battinfo.materials import resolve_material_kind

_SPEC_BASE = "https://w3id.org/battinfo/spec/"
_MATERIAL_BASE = "https://w3id.org/battinfo/material/"


def _short_id(dashed_uid: str) -> str:
    return dashed_uid.replace("-", "")[:6]


def _org_name(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name")
        return name if isinstance(name, str) else None
    return None


def _spec_uid(body: dict) -> str:
    """Deterministic uid for a material-spec body (mirrors api._components)."""
    kind = resolve_material_kind(body.get("kind")) or resolve_material_kind(body.get("name")) or ""
    manufacturer = _org_name(body.get("manufacturer"))
    product = body.get("product_id") or body.get("name")
    seed = "::".join(
        [
            "material-spec",
            (manufacturer or "unknown-manufacturer").strip().lower(),
            (product or "unknown-product").strip().lower(),
            (body.get("grade") or "").strip().lower(),
            kind,
        ]
    )
    return stable_uid(seed)


def _material_uid(body: dict, spec_id: str) -> str:
    """Deterministic uid for a material instance body (mirrors api._components)."""
    lot = body.get("lot_id") or body.get("batch_id") or body.get("name") or ""
    return stable_uid("::".join(["material", spec_id.strip(), str(lot).strip()]))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def migrate(source_root: Path, *, write: bool) -> dict[str, str]:
    id_map: dict[str, str] = {}

    # ── Pass 1: material specs ──────────────────────────────────────────────
    spec_dir = source_root / "material-spec"
    spec_files = sorted(spec_dir.glob("*.json")) if spec_dir.exists() else []
    for path in spec_files:
        doc = _load(path)
        body = doc.get("material_spec")
        if not isinstance(body, dict):
            continue
        old_id = body.get("id", "")
        new_uid = _spec_uid(body)
        new_id = f"{_SPEC_BASE}{new_uid}"
        # Backfill a resolved kind while we are here (required for authored specs).
        resolved_kind = resolve_material_kind(body.get("kind")) or resolve_material_kind(body.get("name"))
        if resolved_kind and body.get("kind") != resolved_kind:
            body["kind"] = resolved_kind
        if new_id != old_id:
            id_map[old_id] = new_id
            body["id"] = new_id
            body["short_id"] = _short_id(new_uid)
            if write:
                _dump(path, doc)
                path.rename(path.with_name(f"material-spec-{new_uid}.json"))
        elif write:
            _dump(path, doc)

    # ── Pass 2: material instances (remap spec ref, then re-mint) ────────────
    mat_dir = source_root / "material"
    mat_files = sorted(mat_dir.glob("*.json")) if mat_dir.exists() else []
    for path in mat_files:
        doc = _load(path)
        body = doc.get("material")
        if not isinstance(body, dict):
            continue
        old_id = body.get("id", "")
        spec_ref = body.get("material_spec_id", "")
        spec_ref = id_map.get(spec_ref, spec_ref)
        body["material_spec_id"] = spec_ref
        new_uid = _material_uid(body, spec_ref)
        new_id = f"{_MATERIAL_BASE}{new_uid}"
        if new_id != old_id:
            id_map[old_id] = new_id
            body["id"] = new_id
            body["short_id"] = _short_id(new_uid)
            if write:
                _dump(path, doc)
                path.rename(path.with_name(f"material-{new_uid}.json"))
        elif write:
            _dump(path, doc)

    # ── Pass 3: fix material references embedded in cell specs ───────────────
    if id_map:
        cs_dir = source_root / "cell-spec"
        for path in sorted(cs_dir.glob("*.json")) if cs_dir.exists() else []:
            doc = _load(path)
            if _remap_refs(doc, id_map) and write:
                _dump(path, doc)

    return id_map


def _remap_refs(node: object, id_map: dict[str, str]) -> bool:
    """Recursively rewrite material_spec_id / base_material_id references."""
    changed = False
    if isinstance(node, dict):
        for key in ("material_spec_id", "base_material_id"):
            val = node.get(key)
            if isinstance(val, str) and val in id_map:
                node[key] = id_map[val]
                changed = True
        for value in node.values():
            changed = _remap_refs(value, id_map) or changed
    elif isinstance(node, list):
        for item in node:
            changed = _remap_refs(item, id_map) or changed
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path,
                        help="Records root (containing material-spec/, material/, cell-spec/).")
    parser.add_argument("--write", action="store_true",
                        help="Rewrite record files in place (default: dry run).")
    parser.add_argument("--map-out", type=Path, default=None,
                        help="Write the old-id -> new-id map to this JSON file.")
    args = parser.parse_args(argv)

    if not args.source_root.exists():
        print(f"source-root does not exist: {args.source_root}", file=sys.stderr)
        return 2

    id_map = migrate(args.source_root, write=args.write)
    mode = "rewrote" if args.write else "would re-mint"
    print(f"{mode} {len(id_map)} record id(s):")
    for old, new in id_map.items():
        print(f"  {old}  ->  {new}")
    if args.map_out is not None:
        args.map_out.write_text(json.dumps(id_map, indent=2) + "\n", encoding="utf-8")
        print(f"id map written to {args.map_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
