#!/usr/bin/env bash
# Versioned GitHub Pages deploy for the Sphinx docs (gold-standard plan C.5).
#
# Layout on gh-pages:
#   dev/        latest main               <tag>/   one folder per v* tag
#   stable/     copy of the newest final release (vX.Y.Z)
#   switcher.json + index.html at the root, listing dev/ and the final releases
#
# Only a final release tag (vX.Y.Z) updates stable/, and only when it is the
# newest final release, so a backport such as v0.8.2 after v0.9.0 leaves
# stable/ alone. A pre-release tag such as v0.8.0rc1 deploys to its own folder
# and changes nothing else: neither stable/ nor switcher.json nor index.html.
# tests/test_docs_deploy.py runs this script against a scratch gh-pages tree.
#
# Usage: docs-deploy.sh <version>   (e.g. "dev", "v0.8.0rc1" or "v0.8.0")
# PYTHON names the Python interpreter to use (default: python3).
set -euo pipefail
VERSION="$1"
BUILD_DIR="docs/_build/html"
SITE_DIR="$(mktemp -d)"
PYTHON="${PYTHON:-python3}"
FINAL_RELEASE='^v[0-9]+\.[0-9]+\.[0-9]+$'

git fetch origin gh-pages:gh-pages 2>/dev/null || true
if git rev-parse --verify gh-pages >/dev/null 2>&1; then
  git worktree add "$SITE_DIR" gh-pages
else
  git worktree add --detach "$SITE_DIR"
  git -C "$SITE_DIR" checkout --orphan gh-pages
  git -C "$SITE_DIR" rm -rf --quiet . 2>/dev/null || true
fi

rm -rf "$SITE_DIR/${VERSION:?}"
cp -r "$BUILD_DIR" "$SITE_DIR/$VERSION"
touch "$SITE_DIR/.nojekyll"

if [[ "$VERSION" == dev || "$VERSION" =~ $FINAL_RELEASE ]]; then
  # Regenerate switcher.json and index.html from the final releases published,
  # and print the newest of them.
  newest="$("$PYTHON" - "$SITE_DIR" <<'PY'
import json, re, sys
from pathlib import Path

site = Path(sys.argv[1])
releases = sorted(
    (d.name for d in site.iterdir() if d.is_dir() and re.fullmatch(r"v\d+\.\d+\.\d+", d.name)),
    key=lambda v: tuple(int(x) for x in v[1:].split(".")),
    reverse=True,
)
entries = [{"name": "dev (main)", "version": "dev", "url": "https://big-map.github.io/BattINFO/dev/"}]
for index, release in enumerate(releases):
    entries.append({
        "name": f"{release} (stable)" if index == 0 else release,
        "version": release,
        "url": f"https://big-map.github.io/BattINFO/{release}/",
        **({"preferred": True} if index == 0 else {}),
    })
(site / "switcher.json").write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8", newline="\n")

target = "stable" if releases else "dev"
(site / "index.html").write_text(
    f'<!doctype html><meta http-equiv="refresh" content="0; url=./{target}/">'
    f'<link rel="canonical" href="https://big-map.github.io/BattINFO/{target}/">\n',
    encoding="utf-8",
    newline="\n",
)
print(f"switcher: dev + {len(releases)} release(s); root -> {target}/", file=sys.stderr)
print(releases[0] if releases else "")
PY
)"
  # stable/ mirrors the newest final release.
  if [[ "$VERSION" == "$newest" ]]; then
    rm -rf "$SITE_DIR/stable"
    cp -r "$BUILD_DIR" "$SITE_DIR/stable"
  fi
fi

cd "$SITE_DIR"
git add -A
if git diff --cached --quiet; then
  echo "No docs changes to deploy."
else
  git -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
    commit -m "Deploy docs: $VERSION"
  git push origin gh-pages
fi
