#!/usr/bin/env bash
# Versioned GitHub Pages deploy for the Sphinx docs (gold-standard plan C.5).
#
# Layout on gh-pages:
#   dev/        latest main               <tag>/   one folder per v* tag
#   stable/     copy of the newest final release (vX.Y.Z)
#   switcher.json + index.html at the root, listing dev/ and the final releases
#   battinfo.ttl + battinfo.html at the root: the newest final release's ontology
#   battinfo/versions/X.Y.Z/battinfo.ttl + battinfo.html: each final release's
#   battinfo-inferred.ttl beside each battinfo.ttl, when the reasoner made one
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
#
# Beside each battinfo.ttl it publishes goes battinfo-inferred.ttl, for
# https://w3id.org/battinfo/inferred and /X.Y.Z/inferred: ROBOT merges the
# import closure, reading docs-deploy-catalog.xml beside this script, and adds
# what HermiT infers, and the file declares the versionIRI
# https://w3id.org/battinfo/X.Y.Z/inferred. ROBOT names the command that runs
# ROBOT (docs.yml sets it on a tag). Reasoning is optional: when ROBOT is not
# set, fails, or runs longer than REASONER_TIMEOUT seconds (default 1200), the
# ontology is published without the file and the job warns. A root
# battinfo-inferred.ttl of an older release is then removed, so /inferred never
# answers for another version than /.
#
# Each deploy of main or of a final tag also tidies the ontology files:
# - The root battinfo.ttl keeps its versionIRI. When the root declares
#   https://w3id.org/battinfo/V/battinfo and battinfo/versions/V/ does not
#   exist, the root's battinfo.ttl and battinfo-inferred.ttl are copied there
#   with a battinfo.html, before a release replaces them. This keeps the 2024
#   file, versionIRI 0.8.0-beta, at a w3id address; every root since was
#   published in its version folder in the first place.
# - The root versions/ folder is removed. It held copies of that 2024 file
#   under the numbers of older releases, which no w3id rule reads.
#
# tests/test_docs_deploy.py runs this script against a scratch gh-pages tree.
#
# Usage: docs-deploy.sh <version>   (e.g. "dev", "v0.8.0rc1" or "v0.8.0")
# PYTHON names the Python interpreter to use (default: python3).
set -euo pipefail
VERSION="$1"
BUILD_DIR="docs/_build/html"
ONTOLOGY="battinfo.ttl"
CATALOG=".github/workflows/docs-deploy-catalog.xml"
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

  # The ontology at its w3id paths: battinfo/versions/X.Y.Z/ for every final
  # release, and the root for the newest one. main's deploy only tidies.
  release=""
  newest_release=false
  if [[ "$VERSION" =~ $FINAL_RELEASE ]]; then
    release="${VERSION#v}"
    [[ "$VERSION" == "$newest" ]] && newest_release=true
  fi
  if ! "$PYTHON" - "$SITE_DIR" "$release" "$newest_release" "$ONTOLOGY" "$CATALOG" <<'PY'
import html, os, re, shlex, shutil, subprocess, sys, tempfile
from pathlib import Path

site, release, newest = Path(sys.argv[1]), sys.argv[2], sys.argv[3] == "true"
source, catalog = Path(sys.argv[4]), sys.argv[5]
W3ID = "https://w3id.org/battinfo"
INFERRED = "battinfo-inferred.ttl"


def version_iris(path):
    return re.findall(r"owl:versionIRI\s+<([^>]*)>", path.read_text(encoding="utf-8", errors="replace"))


def write_page(folder, version, version_iri, about, links):
    """Write the short battinfo.html of the ontology in *folder*."""
    imports = re.findall(r"owl:imports\s+<([^>]*)>", (folder / "battinfo.ttl").read_text(encoding="utf-8"))
    items = "\n".join(f'<li><a href="{html.escape(iri)}">{html.escape(iri)}</a></li>' for iri in imports)
    files = ['<li><a href="battinfo.ttl">battinfo.ttl</a> (Turtle)</li>']
    if (folder / INFERRED).is_file():
        what = "Turtle, the imports merged with what a reasoner infers"
        files.append(f'<li><a href="{INFERRED}">{INFERRED}</a> ({what})</li>')
    files += [f'<li><a href="{html.escape(href)}">{html.escape(text)}</a></li>' for href, text in links]
    rows = "\n".join(files)
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BattINFO ontology {version}</title>
<link rel="alternate" type="text/turtle" href="battinfo.ttl">
<style>body{{font-family:system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem;line-height:1.5}}a{{overflow-wrap:anywhere}}</style>
</head>
<body>
<h1>BattINFO ontology {version}</h1>
<p>{about}</p>
<p>Version IRI: <code>{version_iri}</code><br>Version: {version}</p>
<h2>Imports</h2>
<ul>
{items}
</ul>
<h2>Files</h2>
<ul>
{rows}
</ul>
</body>
</html>
"""
    (folder / "battinfo.html").write_text(page, encoding="utf-8", newline="\n")


def run_robot(release):
    """(the battinfo-inferred.ttl ROBOT writes for *release*, "") or (None, why there is none)."""
    command = shlex.split(os.environ.get("ROBOT", ""))
    if not command:
        return None, "ROBOT is not set"
    limit = float(os.environ.get("REASONER_TIMEOUT") or 1200)
    expected = f"{W3ID}/{release}/inferred"
    with tempfile.TemporaryDirectory() as scratch:
        output = Path(scratch) / INFERRED
        args = [
            *command,
            "merge", "--catalog", catalog, "--input", str(source),
            "reason", "--reasoner", "HermiT",
            "annotate", "--ontology-iri", f"{W3ID}/inferred", "--version-iri", expected,
            "--link-annotation", "http://www.w3.org/ns/prov#wasDerivedFrom", f"{W3ID}/{release}/battinfo",
            "--output", str(output),
        ]
        try:
            proc = subprocess.run(
                args, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", timeout=limit
            )
        except subprocess.TimeoutExpired:
            return None, f"the reasoner ran for more than {limit:.0f} s"
        except OSError as exc:
            return None, f"ROBOT did not start ({exc})"
        said = [line.strip() for line in (proc.stderr + "\n" + proc.stdout).splitlines() if line.strip()]
        if proc.returncode != 0:
            print("\n".join(said[:10]), file=sys.stderr)
            first = next((line for line in said if "error" in line.lower()), said[0] if said else "")
            first = re.sub(r"^\d{4}-\d\d-\d\d [\d:,]+ ", "", first).rstrip(".")  # without the log's timestamp
            return None, f"ROBOT exited with {proc.returncode}" + (f": {first}" if first else "")
        if not output.is_file():
            return None, "ROBOT wrote no file"
        if version_iris(output) != [expected]:
            return None, f"the file ROBOT wrote does not declare the versionIRI <{expected}>"
        return output.read_bytes().replace(b"\r\n", b"\n"), ""


def reason(release):
    """battinfo-inferred.ttl of *release*, made with ROBOT and HermiT, or None (with a warning) if there is none."""
    inferred, problem = run_robot(release)
    if inferred is None:
        print(f"::warning::No {INFERRED} for {release}: {problem}. The ontology is published without it.", file=sys.stderr)
    return inferred


# The root versions/ folder holds the 2024 battinfo.ttl under the numbers of
# older releases (0.5.0, v0.2.0, v0.6.0, test). No w3id rule reads it: the
# ontology's version folders are under battinfo/versions/.
if (site / "versions").is_dir():
    shutil.rmtree(site / "versions")
    print("ontology: removed the root versions/ folder", file=sys.stderr)

# Before a release replaces the root, keep the root's files at their versionIRI.
root = site / "battinfo.ttl"
declared = version_iris(root) if root.is_file() else []
kept_version = re.compile(re.escape(W3ID) + r"/(\d+\.\d+\.\d+[0-9A-Za-z.+-]*)/battinfo")
match = kept_version.fullmatch(declared[0]) if len(declared) == 1 else None
if match and not (site / "battinfo" / "versions" / match[1] / "battinfo.ttl").exists():
    kept = site / "battinfo" / "versions" / match[1]
    kept.parent.mkdir(parents=True, exist_ok=True)
    # Written beside its place and renamed into it, so the folder is either
    # whole or absent; a partial one from an older run is replaced.
    staging = Path(tempfile.mkdtemp(prefix=f".{match[1]}-", dir=kept.parent))
    try:
        shutil.copyfile(root, staging / "battinfo.ttl")
        # The root's inferred file goes along when it is of the same version.
        inferred_iris = version_iris(site / INFERRED) if (site / INFERRED).is_file() else []
        if inferred_iris and all(iri.startswith(f"{W3ID}/{match[1]}/") for iri in inferred_iris):
            shutil.copyfile(site / INFERRED, staging / INFERRED)
        about = (
            f"The ontology that {W3ID} served before each release was published in a folder of its own, "
            "kept here so that its version IRI still resolves."
        )
        write_page(staging, match[1], declared[0], about, [])
        if kept.exists():
            shutil.rmtree(kept)
        staging.rename(kept)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    print(f"ontology {match[1]}: kept the root's files in battinfo/versions/{match[1]}/", file=sys.stderr)

if not release:
    sys.exit(0)

if not source.is_file():
    sys.exit(f"{source} is missing from the checkout, so the ontology of v{release} was not published.")
ttl = source.read_bytes().replace(b"\r\n", b"\n")
text = ttl.decode("utf-8")
version_iri = f"{W3ID}/{release}/battinfo"
declared = re.findall(r'owl:versionInfo\s+"([^"]*)"', text)
declared_iri = re.findall(r"owl:versionIRI\s+<([^>]*)>", text)
if declared != [release] or declared_iri != [version_iri]:
    sys.exit(
        f"{source} declares owl:versionInfo {declared} and owl:versionIRI {declared_iri}, not {release} "
        f"and <{version_iri}>, so the ontology of v{release} was not published. Set the version with "
        "scripts/set_version.py, then rerun this deploy from a tag that carries it."
    )
inferred = reason(release)
about = (
    f"The BattINFO application ontology names the EMMO modules that BattINFO {release} uses, each at a pinned "
    "version. It defines no terms of its own: battery concepts come from the imported modules."
)
links = [
    (f"https://github.com/BIG-MAP/BattINFO/blob/v{release}/battinfo.ttl", f"battinfo.ttl in the v{release} source"),
    (f"https://big-map.github.io/BattINFO/v{release}/", f"BattINFO {release} documentation"),
]
folders = [site / "battinfo" / "versions" / release] + ([site] if newest else [])
for folder in folders:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "battinfo.ttl").write_bytes(ttl)
    if inferred is not None:
        (folder / INFERRED).write_bytes(inferred)
    elif (folder / INFERRED).is_file() and version_iris(folder / INFERRED) != [f"{W3ID}/{release}/inferred"]:
        (folder / INFERRED).unlink()  # another version's: /inferred must not answer with it
        place = "the root" if folder == site else folder.relative_to(site).as_posix() + "/"
        print(f"ontology {release}: removed the {INFERRED} of another version from {place}", file=sys.stderr)
    write_page(folder, release, version_iri, about, links)
where = "battinfo/versions/" + release + "/" + (" and the root" if newest else "")
print(f"ontology {release}: {where}" + ("" if inferred is None else f", with {INFERRED}"), file=sys.stderr)
PY
  then
    ontology_failed=1
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
