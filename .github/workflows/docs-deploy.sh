#!/usr/bin/env bash
# Versioned GitHub Pages deploy for the Sphinx docs (gold-standard plan C.5).
#
# Layout on gh-pages:
#   dev/        latest main               <tag>/   one folder per v* tag
#   stable/     copy of the newest final release (vX.Y.Z)
#   switcher.json + index.html at the root, listing dev/ and the final releases
#   battinfo.ttl + battinfo.html at the root: the newest final release's ontology
#   battinfo/versions/X.Y.Z/battinfo.ttl + battinfo.html: each final release's
#
# Only a final release tag (vX.Y.Z) updates stable/, and only when it is the
# newest final release, so a backport such as v0.8.2 after v0.9.0 leaves
# stable/ alone. A pre-release tag such as v0.8.0rc1 deploys to its own folder
# and changes nothing else: neither stable/ nor switcher.json nor index.html.
#
# A final tag also publishes the checkout's battinfo.ttl where w3id's ontology
# rules look for it: https://w3id.org/battinfo/X.Y.Z (no v) answers with
# battinfo/versions/X.Y.Z/battinfo.ttl, or battinfo.html for a browser, and
# https://w3id.org/battinfo with the root copies, which follow the newest final
# release like stable/. battinfo.html is a short page generated here with the
# version, the version IRI, the imports and links. A battinfo.ttl that does not
# declare the tag's version is not published: the docs still deploy, and the
# script then exits 1.
# tests/test_docs_deploy.py runs this script against a scratch gh-pages tree.
#
# Usage: docs-deploy.sh <version>   (e.g. "dev", "v0.8.0rc1" or "v0.8.0")
# PYTHON names the Python interpreter to use (default: python3).
set -euo pipefail
VERSION="$1"
BUILD_DIR="docs/_build/html"
ONTOLOGY="battinfo.ttl"
SITE_DIR="$(mktemp -d)"
PYTHON="${PYTHON:-python3}"
FINAL_RELEASE='^v[0-9]+\.[0-9]+\.[0-9]+$'
ontology_failed=""

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

  if [[ "$VERSION" =~ $FINAL_RELEASE ]]; then
    # The ontology at its w3id paths: battinfo/versions/X.Y.Z/ for every final
    # release, and the root for the newest one.
    newest_release=false
    [[ "$VERSION" == "$newest" ]] && newest_release=true
    if ! "$PYTHON" - "$SITE_DIR" "${VERSION#v}" "$newest_release" "$ONTOLOGY" <<'PY'
import html, re, sys
from pathlib import Path

site, release, newest, source = Path(sys.argv[1]), sys.argv[2], sys.argv[3] == "true", Path(sys.argv[4])
if not source.is_file():
    sys.exit(f"{source} is missing from the checkout, so the ontology of v{release} was not published.")
ttl = source.read_bytes().replace(b"\r\n", b"\n")
text = ttl.decode("utf-8")
version_iri = f"https://w3id.org/battinfo/{release}/battinfo"
declared = re.findall(r'owl:versionInfo\s+"([^"]*)"', text)
declared_iri = re.findall(r"owl:versionIRI\s+<([^>]*)>", text)
if declared != [release] or declared_iri != [version_iri]:
    sys.exit(
        f"{source} declares owl:versionInfo {declared} and owl:versionIRI {declared_iri}, not {release} "
        f"and <{version_iri}>, so the ontology of v{release} was not published. Set the version with "
        "scripts/set_version.py, then rerun this deploy from a tag that carries it."
    )
imports = re.findall(r"owl:imports\s+<([^>]*)>", text)
docs = f"https://big-map.github.io/BattINFO/v{release}/"
source_url = f"https://github.com/BIG-MAP/BattINFO/blob/v{release}/battinfo.ttl"
items = "\n".join(f'<li><a href="{html.escape(iri)}">{html.escape(iri)}</a></li>' for iri in imports)
page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BattINFO ontology {release}</title>
<link rel="alternate" type="text/turtle" href="battinfo.ttl">
<style>body{{font-family:system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;line-height:1.5}}a{{overflow-wrap:anywhere}}</style>
</head>
<body>
<h1>BattINFO ontology {release}</h1>
<p>The BattINFO application ontology names the EMMO modules that BattINFO {release} uses, each at a pinned version. It defines no terms of its own: battery concepts come from the imported modules.</p>
<p>Version IRI: <code>{version_iri}</code><br>Version: {release}</p>
<h2>Imports</h2>
<ul>
{items}
</ul>
<h2>Files</h2>
<ul>
<li><a href="battinfo.ttl">battinfo.ttl</a> (Turtle)</li>
<li><a href="{source_url}">battinfo.ttl in the v{release} source</a></li>
<li><a href="{docs}">BattINFO {release} documentation</a></li>
</ul>
</body>
</html>
"""
folders = [site / "battinfo" / "versions" / release] + ([site] if newest else [])
for folder in folders:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "battinfo.ttl").write_bytes(ttl)
    (folder / "battinfo.html").write_text(page, encoding="utf-8", newline="\n")
where = "battinfo/versions/" + release + "/" + (" and the root" if newest else "")
print(f"ontology {release}: {where}", file=sys.stderr)
PY
    then
      ontology_failed=1
    fi
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

if [[ -n "$ontology_failed" ]]; then
  echo "::error::The docs of $VERSION are deployed, but its ontology is not; the message above says why." >&2
  exit 1
fi
