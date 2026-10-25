"""Write the record IRI patterns of the JSON Schemas from ``battinfo.namespace``.

Every ``pattern`` in a schema that reads a BattINFO record IRI is the
expression ``battinfo.namespace.record_iri_regex`` builds for the segments it
names, so the schemas and the SDK's recognisers accept the same IRIs. Each
pattern accepts both record shapes, ``https://w3id.org/battinfo/{segment}/{uid}``
and ``https://w3id.org/battinfo/id/{prefix}/{segment}/{uid}`` (IRI ruling of
22 October 2026, BIG-MAP/BattINFO#476). A pattern that reads a reference to a
maker, a product model or a material also accepts a shared thing,
``https://w3id.org/battinfo/id/{uid}``: the pattern of a ``$defs`` entry whose
name ends in ``RefIri``, and the pattern of a ``material_spec_id`` property.

The script rewrites the patterns in ``assets/schemas`` (the source), in its
packaged copy ``src/battinfo/data/schemas`` and in the cell-spec profile under
``src/battinfo/data/profiles``, whose fragments repeat parts of the schemas. A
pattern that starts with the record base but is not one the module builds
stops the script, so a hand-written pattern cannot slip in.

Usage:
    uv run python scripts/sync_schema_iri_patterns.py            # rewrite the patterns
    uv run python scripts/sync_schema_iri_patterns.py --check    # exit 1 if one differs
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.namespace import BATTINFO_ROOT, PREFIX_PATTERN, UID_PATTERN, record_iri_regex  # noqa: E402

TREES = (
    ROOT / "assets" / "schemas",
    ROOT / "src" / "battinfo" / "data" / "schemas",
    ROOT / "src" / "battinfo" / "data" / "profiles",
)
# A pattern that reads a record IRI starts with the anchored record base.
_RECORD_PATTERN_START = "^" + re.escape(BATTINFO_ROOT)
_SEGMENT = re.compile(r"[a-z][a-z0-9-]*")
# Where a pattern reads a reference to a maker, a product model or a material.
_THING_DEF_SUFFIX = "RefIri"
_THING_PROPERTIES = frozenset({"material_spec_id"})


def _patterns(node: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], dict[str, Any]]]:
    """Each object of *node* that holds a record IRI ``pattern``, with its path."""
    if isinstance(node, dict):
        pattern = node.get("pattern")
        if isinstance(pattern, str) and pattern.startswith(_RECORD_PATTERN_START):
            yield path, node
        for key, value in node.items():
            yield from _patterns(value, (*path, key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _patterns(value, (*path, str(index)))


def _takes_things(path: tuple[str, ...]) -> bool:
    if len(path) >= 2 and path[-2] == "$defs":
        return path[-1].endswith(_THING_DEF_SUFFIX)
    return bool(path) and path[-1] in _THING_PROPERTIES


def _segments(pattern: str, where: str) -> tuple[str, ...]:
    """The record segments *pattern* names, checked to be a pattern the namespace module builds."""
    middle = pattern[len(_RECORD_PATTERN_START) :].removesuffix(UID_PATTERN + "$").replace(PREFIX_PATTERN, "")
    segments = tuple(name for name in _SEGMENT.findall(middle) if name != "id")
    built = {
        record_iri_regex(*segments, both_shapes=both, things=things)
        for both in (False, True)
        for things in (False, True)
    }
    if not segments or pattern not in built:
        raise SystemExit(
            f"{where}: {pattern!r} reads a record IRI but is not a pattern battinfo.namespace builds. "
            "Write it as record_iri_regex() would and run this script again."
        )
    return segments


def synced(document: Any, where: str) -> list[str]:
    """Rewrite the record IRI patterns of *document* in place; the JSON paths it changed."""
    changed = []
    for path, node in _patterns(document):
        location = f"{where}#/{'/'.join(path)}"
        segments = _segments(node["pattern"], location)
        pattern = record_iri_regex(*segments, both_shapes=True, things=_takes_things(path))
        if node["pattern"] != pattern:
            node["pattern"] = pattern
            changed.append(location)
    return changed


def _dumped(document: Any, raw: str) -> str | None:
    """*document* serialised the way the file that held *raw* was, or ``None`` if no known way reproduces it."""
    original = json.loads(raw)
    for ensure_ascii in (False, True):
        if json.dumps(original, indent=2, ensure_ascii=ensure_ascii) + "\n" == raw:
            return json.dumps(document, indent=2, ensure_ascii=ensure_ascii) + "\n"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="change nothing; exit 1 if a pattern differs")
    args = parser.parse_args(argv)

    stale: list[str] = []
    files = 0
    for tree in TREES:
        for path in sorted(tree.rglob("*.json")):
            raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
            document = json.loads(raw)
            changed = synced(document, path.relative_to(ROOT).as_posix())
            if not changed:
                continue
            stale.extend(changed)
            files += 1
            if args.check:
                continue
            text = _dumped(document, raw)
            if text is None:
                raise SystemExit(f"{path.relative_to(ROOT).as_posix()}: cannot rewrite it without reformatting it.")
            path.write_text(text, encoding="utf-8", newline="\n")

    if args.check:
        if stale:
            print("Record IRI patterns that battinfo.namespace builds differently:", file=sys.stderr)
            print("\n".join(f"  {location}" for location in stale), file=sys.stderr)
            print("Run: uv run python scripts/sync_schema_iri_patterns.py", file=sys.stderr)
            return 1
        print("Schema IRI patterns in sync.")
        return 0
    print(f"Rewrote {len(stale)} patterns in {files} files." if stale else "Schema IRI patterns in sync.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
