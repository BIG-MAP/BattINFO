#!/usr/bin/env python
"""Re-mint electrode records to deterministic content-derived ids.

Before the first-class electrode model, ``create_electrode_spec`` took whatever
uid it was handed, so existing corpora carry electrode-spec / electrode records
whose ids say nothing about what they identify. This script re-mints them the way
the engine now does — electrode-spec from (producer, product, grade, kind,
processing route); electrode batch from (spec_id, batch) — backfills the required
``kind`` (and the polarity it implies) from the record's own active material,
rewrites the record files, fixes cross-references (electrode batch -> spec;
cell-spec ``positive/negative_electrode_spec_id`` and inline-holder
``electrode_spec_id``), and prints the old-id -> new-id map.

It covers the RECORD-FILE side only. The registry supersede/backfill (so old IRIs
resolve forever per IDENTIFIER_POLICY) is operated separately with the map this
prints. Point it at a copy before running with ``--write``.

Usage::

    # dry run: print the id map, write nothing
    python scripts/migrate_electrode_ids.py --source-root path/to/records

    # apply: rewrite files (renamed to the new uid) and emit the map JSON
    python scripts/migrate_electrode_ids.py --source-root path/to/records --write \\
        --map-out electrode-id-map.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from battinfo.electrodes import electrode_polarity_for_kind, resolve_electrode_kind
from battinfo.entities import (
    electrode_identity_seed,
    electrode_spec_identity_seed,
    stable_uid,
)

_SPEC_BASE = "https://w3id.org/battinfo/spec/"
_ELECTRODE_BASE = "https://w3id.org/battinfo/electrode/"
_SPEC_REF_KEYS = (
    "electrode_spec_id",
    "positive_electrode_spec_id",
    "negative_electrode_spec_id",
)


def _short_id(dashed_uid: str) -> str:
    return dashed_uid.replace("-", "")[:6]


def _org_name(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        name = value.get("name")
        return name if isinstance(name, str) else None
    return None


def _active_material_names(body: dict) -> list[str]:
    """Names of the coating's active materials — the kind's fallback source."""
    coating = body.get("coating")
    component = coating.get("component") if isinstance(coating, dict) else None
    actives = component.get("active_material") if isinstance(component, dict) else None
    if not isinstance(actives, list):
        return []
    return [m["name"] for m in actives if isinstance(m, dict) and isinstance(m.get("name"), str)]


def _resolved_kind(body: dict) -> str | None:
    """Resolve the electrode's kind from its own content, in confidence order."""
    candidates: list[Any] = [body.get("kind"), *_active_material_names(body), body.get("name")]
    for candidate in candidates:
        resolved = resolve_electrode_kind(candidate)
        if resolved is not None:
            return resolved
    return None


def _spec_uid(body: dict, kind: str | None) -> str:
    """Deterministic uid for an electrode-spec body (mirrors api._components)."""
    processing = body.get("processing")
    route = processing.get("route") if isinstance(processing, dict) else None
    return stable_uid(
        electrode_spec_identity_seed(
            producer=_org_name(body.get("manufacturer")),
            product=body.get("product_id") or body.get("name"),
            grade=body.get("grade"),
            kind=kind,
            route=route if isinstance(route, str) else None,
        )
    )


def _electrode_uid(body: dict, spec_id: str) -> str:
    """Deterministic uid for an electrode batch body (mirrors api._components)."""
    batch = body.get("batch_id") or body.get("lot_id") or body.get("name") or ""
    return stable_uid(electrode_identity_seed(electrode_spec_id=spec_id, batch=str(batch)))


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _renamed(path: Path, prefix: str, new_uid: str) -> Path:
    """New filename, keeping whichever naming convention the corpus already uses.

    ``examples/`` names files by the bare uid; a records root names them
    ``<type>-<uid>.json``. Re-minting must not quietly switch a corpus from one
    to the other.
    """
    bare = path.stem == path.stem.replace(f"{prefix}-", "")
    return path.with_name(f"{new_uid}.json" if bare else f"{prefix}-{new_uid}.json")


def migrate(source_root: Path, *, write: bool) -> dict[str, str]:
    id_map: dict[str, str] = {}

    # ── Pass 1: electrode specs ─────────────────────────────────────────────
    spec_dir = source_root / "electrode-spec"
    for path in sorted(spec_dir.glob("*.json")) if spec_dir.exists() else []:
        doc = _load(path)
        body = doc.get("electrode_spec")
        if not isinstance(body, dict):
            continue
        old_id = body.get("id", "")
        kind = _resolved_kind(body)
        if kind and body.get("kind") != kind:
            body["kind"] = kind
        polarity = electrode_polarity_for_kind(kind)
        if polarity and not body.get("polarity"):
            body["polarity"] = polarity
        new_uid = _spec_uid(body, kind)
        new_id = f"{_SPEC_BASE}{new_uid}"
        if new_id != old_id:
            id_map[old_id] = new_id
            body["id"] = new_id
            body["short_id"] = _short_id(new_uid)
            if write:
                _dump(path, doc)
                path.rename(_renamed(path, "electrode-spec", new_uid))
        elif write:
            _dump(path, doc)

    # ── Pass 2: electrode batches (remap spec ref, then re-mint) ─────────────
    inst_dir = source_root / "electrode"
    for path in sorted(inst_dir.glob("*.json")) if inst_dir.exists() else []:
        doc = _load(path)
        body = doc.get("electrode")
        if not isinstance(body, dict):
            continue
        old_id = body.get("id", "")
        spec_ref = body.get("electrode_spec_id", "")
        spec_ref = id_map.get(spec_ref, spec_ref)
        body["electrode_spec_id"] = spec_ref
        new_uid = _electrode_uid(body, spec_ref)
        new_id = f"{_ELECTRODE_BASE}{new_uid}"
        if new_id != old_id:
            id_map[old_id] = new_id
            body["id"] = new_id
            body["short_id"] = _short_id(new_uid)
            if write:
                _dump(path, doc)
                path.rename(_renamed(path, "electrode", new_uid))
        elif write:
            _dump(path, doc)

    # ── Pass 3: fix electrode-spec references embedded in cell specs ─────────
    if id_map:
        cs_dir = source_root / "cell-spec"
        for path in sorted(cs_dir.rglob("*.json")) if cs_dir.exists() else []:
            doc = _load(path)
            if _remap_refs(doc, id_map) and write:
                _dump(path, doc)

    return id_map


def _remap_refs(node: object, id_map: dict[str, str]) -> bool:
    """Recursively rewrite every electrode-spec reference key."""
    changed = False
    if isinstance(node, dict):
        for key in _SPEC_REF_KEYS:
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
                        help="Records root (containing electrode-spec/, electrode/, cell-spec/).")
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
