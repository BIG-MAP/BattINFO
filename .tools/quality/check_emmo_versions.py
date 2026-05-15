"""check_emmo_versions.py — report whether EMMO domain imports in battinfo.ttl are up to date.

Usage:
    python .tools/quality/check_emmo_versions.py
    python .tools/quality/check_emmo_versions.py --json          # machine-readable output

Exit codes:
    0 — all declared imports match the latest published releases
    1 — one or more dependencies are behind the latest release (or fetch failed)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BATTINFO_TTL = ROOT / "ontology" / "battinfo.ttl"

# Map each declared IRI pattern to its GitHub repository.
# Keyed by a display name; values are (iri_pattern_re, github_org_repo).
TRACKED_DEPS: dict[str, tuple[re.Pattern[str], str]] = {
    "domain-battery": (
        re.compile(r"owl:imports\s+<https://w3id\.org/emmo/domain/battery/([^/]+)/battery>"),
        "emmo-repo/domain-battery",
    ),
    "domain-electrochemistry": (
        re.compile(r"owl:imports\s+<https://w3id\.org/emmo/domain/electrochemistry/([^/]+)/electrochemistry>"),
        "emmo-repo/domain-electrochemistry",
    ),
}

GITHUB_RELEASE_API = "https://api.github.com/repos/{repo}/releases/latest"
GITHUB_TAGS_API = "https://api.github.com/repos/{repo}/tags?per_page=10"
TIMEOUT = 10
_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "battinfo-version-check/0.1"}
_VERSION_RE = re.compile(r"^v?(\d+\.\d+[\.\d]*)$")


def _declared_version(ttl_content: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(ttl_content)
    return match.group(1) if match else None


def _fetch_json(url: str) -> object | None:
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


def _latest_release(repo: str) -> str | None:
    # Try the /releases/latest endpoint first; not all repos use GitHub Releases.
    data = _fetch_json(GITHUB_RELEASE_API.format(repo=repo))
    if isinstance(data, dict) and data.get("tag_name"):
        return data["tag_name"].lstrip("v") or None

    # Fall back to the most recent tag whose name looks like a semver.
    tags = _fetch_json(GITHUB_TAGS_API.format(repo=repo))
    if isinstance(tags, list):
        for tag in tags:
            name = tag.get("name", "")
            m = _VERSION_RE.match(name)
            if m:
                return m.group(1)
    return None


def _compare_versions(declared: str, latest: str) -> int:
    """Return -1/0/1 like cmp, comparing semver strings numerically."""
    def parts(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in re.split(r"[.-]", v) if x.isdigit())
    d, l = parts(declared), parts(latest)
    return (d > l) - (d < l)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON report to stdout.")
    args = parser.parse_args(argv)

    if not BATTINFO_TTL.exists():
        print(f"ERROR: {BATTINFO_TTL} not found.", file=sys.stderr)
        return 1

    ttl = BATTINFO_TTL.read_text(encoding="utf-8")
    results: list[dict[str, object]] = []
    any_behind = False

    for name, (pattern, repo) in TRACKED_DEPS.items():
        declared = _declared_version(ttl, pattern)
        latest = _latest_release(repo)

        if declared is None:
            status = "not-declared"
            msg = f"No pinned import found for {name} in battinfo.ttl."
            any_behind = True
        elif latest is None:
            status = "fetch-failed"
            msg = f"Could not fetch latest release from github.com/{repo}."
            any_behind = True
        elif _compare_versions(declared, latest) == 0:
            status = "up-to-date"
            msg = f"{name} {declared} matches latest release."
        elif _compare_versions(declared, latest) > 0:
            status = "ahead"
            msg = f"{name} declared {declared} is ahead of latest published release {latest} — verify this is intentional."
        else:
            status = "behind"
            msg = (
                f"{name} declared {declared} but latest is {latest}. "
                f"Update owl:imports in ontology/battinfo.ttl and re-verify compatibility."
            )
            any_behind = True

        results.append({"dependency": name, "repo": repo, "declared": declared, "latest": latest, "status": status, "message": msg})

    if args.json:
        print(json.dumps({"status": "ok" if not any_behind else "outdated", "dependencies": results}, indent=2))
    else:
        for r in results:
            icon = "OK" if r["status"] in ("up-to-date", "ahead") else "!!"
            print(f"  {icon}  {r['message']}")
        if any_behind:
            print("\nSome dependencies are outdated or could not be verified.", file=sys.stderr)
        else:
            print("\nAll EMMO dependencies are up to date.")

    return 1 if any_behind else 0


if __name__ == "__main__":
    sys.exit(main())
