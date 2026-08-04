"""refresh_emmo_context.py — update the bundled EMMO domain-battery JSON-LD context.

The context is fetched at the version pinned in battinfo.ttl and written to
src/battinfo/data/context/domain-battery.context.json.  Run this whenever
upgrading the EMMO domain-battery dependency declared in battinfo.ttl.

The default URL is the release tag, not the canonical w3id.org URL: w3id serves
whatever the ontology's default branch currently holds, and the bundled copy has
to match the pinned import so records stay reproducible. Point --url at
https://w3id.org/emmo/domain/battery/context to preview the unreleased context.

Usage:
    python .tools/quality/refresh_emmo_context.py
    python .tools/quality/refresh_emmo_context.py --dry-run   # show size, do not write
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Keep in step with the owl:imports pin in battinfo.ttl.
PINNED_VERSION = "0.20.1"
CONTEXT_URL = (
    f"https://raw.githubusercontent.com/emmo-repo/domain-battery/{PINNED_VERSION}/context/context.json"
)
LATEST_CONTEXT_URL = "https://w3id.org/emmo/domain/battery/context"
CONTEXT_PATH = ROOT / "src" / "battinfo" / "data" / "context" / "domain-battery.context.json"
TIMEOUT = 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Fetch but do not write the file.")
    parser.add_argument("--url", default=CONTEXT_URL, help=f"Context URL to fetch (default: {CONTEXT_URL})")
    args = parser.parse_args(argv)

    print(f"Fetching: {args.url}")
    req = urllib.request.Request(
        args.url,
        headers={
            "Accept": "application/json, application/ld+json",
            "User-Agent": "battinfo-context-refresh/0.1",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.URLError as exc:
        print(f"ERROR: could not fetch context: {exc}", file=sys.stderr)
        return 1

    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: response is not valid JSON: {exc}", file=sys.stderr)
        return 1

    size = len(raw)
    print(f"Fetched {size:,} bytes ({len(data)} top-level keys)")

    if args.dry_run:
        print("Dry run — not writing.")
        return 0

    CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTEXT_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Written to {CONTEXT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
