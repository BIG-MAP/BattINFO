"""Sync the canonical example records into the packaged data directory.

`examples/` (repo root) is the SINGLE SOURCE OF TRUTH for example records. The
package ships a read-only copy at `src/battinfo/data/examples/` so the records
are available from the installed wheel (the runtime API resolves them there via
``battinfo.api.EXAMPLES_ROOT``). This script regenerates that copy.

Usage:
    python scripts/sync_examples.py            # regenerate the packaged copy
    python scripts/sync_examples.py --check    # fail (exit 1) if it is stale

The generated copy is committed so the wheel always contains the files; the
``--check`` mode runs on CI to guarantee it never drifts from the source.
"""
from __future__ import annotations

import filecmp
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "examples"
GENERATED = REPO_ROOT / "src" / "battinfo" / "data" / "examples"

# Written into the generated copy so it is obvious the directory must not be
# edited by hand. Kept deterministic (no timestamps) so --check is reproducible.
NOTICE_NAME = "_GENERATED.md"
NOTICE_BODY = """\
# Generated — do not edit

The files in this directory are an auto-generated, read-only copy of the
canonical examples in the repository root [`examples/`](../../../../examples).

They are packaged here so the example records ship inside the installed
`battinfo` wheel. **Do not edit anything in this directory.** Edit the files
under `examples/` instead and regenerate with:

    python scripts/sync_examples.py

CI runs `python scripts/sync_examples.py --check` and fails if this copy is out
of sync with the source.
"""


def _build_into(dest: Path) -> None:
    """Render the canonical examples plus the generated-notice into ``dest``."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SOURCE, dest)
    (dest / NOTICE_NAME).write_text(NOTICE_BODY, encoding="utf-8", newline="\n")


def _dirs_equal(a: Path, b: Path) -> list[str]:
    """Return a list of human-readable differences between two trees (empty = equal)."""
    cmp = filecmp.dircmp(a, b)
    diffs: list[str] = []

    def _walk(node: filecmp.dircmp, rel: str) -> None:
        for name in node.left_only:
            diffs.append(f"only in source: {rel}{name}")
        for name in node.right_only:
            diffs.append(f"only in packaged copy: {rel}{name}")
        for name in node.diff_files:
            diffs.append(f"differs: {rel}{name}")
        for name in node.funny_files:
            diffs.append(f"could not compare: {rel}{name}")
        for sub, subnode in node.subdirs.items():
            _walk(subnode, f"{rel}{sub}/")

    _walk(cmp, "")
    return diffs


def main(argv: list[str]) -> int:
    check = "--check" in argv[1:]

    if not SOURCE.exists():
        print(f"source examples not found: {SOURCE}", file=sys.stderr)
        return 2

    if check:
        with tempfile.TemporaryDirectory() as tmp:
            expected = Path(tmp) / "examples"
            _build_into(expected)
            diffs = _dirs_equal(expected, GENERATED)
        if diffs:
            print("Packaged examples are out of sync with examples/:", file=sys.stderr)
            for d in diffs:
                print(f"  - {d}", file=sys.stderr)
            print("\nRun: python scripts/sync_examples.py", file=sys.stderr)
            return 1
        print("Packaged examples are in sync.")
        return 0

    _build_into(GENERATED)
    rel = GENERATED.relative_to(REPO_ROOT)
    print(f"Synced examples/ -> {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
