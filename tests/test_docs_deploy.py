""".github/workflows/docs-deploy.sh, run against a scratch gh-pages tree.

docs.yml deploys the docs of every v* tag. A pre-release tag such as
v0.8.0rc1 gets its own folder and nothing else, so during the soak stable/,
switcher.json and the root index.html still show the last final release. A
final tag vX.Y.Z updates them, but stable/ only follows the newest final
release, so a backport does not replace it.

A final tag also publishes the ontology where w3id looks for it: battinfo.ttl,
and a small battinfo.html for browsers, in battinfo/versions/X.Y.Z/ for
https://w3id.org/battinfo/X.Y.Z, and at the root for https://w3id.org/battinfo
when the tag is the newest final release. Beside each goes the
battinfo-inferred.ttl that ROBOT writes, when it does; a stand-in for ROBOT
answers here, and the deploy goes on without the file when it fails.

Main's deploy and a final tag's also keep the 2024 root ontology at its
versionIRI, 0.8.0-beta, and drop the root versions/ folder of mislabelled
copies of it.

Every deploy adds the releases of the publishers' vocabularies under def/
that gh-pages lacks, as scripts/build_def_site.py laid them out in the build
job, and never replaces a published one. The fixture vocabulary of
tests/fixtures/def-vocabularies/ stands in for a publisher's.

The script runs with bash and git, against a local bare repository standing
in for origin; nothing leaves the machine.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "workflows" / "docs-deploy.sh"
FIXTURE_DEF = ROOT / "tests" / "fixtures" / "def-vocabularies" / "def"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def_site = _load("build_def_site")

# The ontology files published in 2024: the root battinfo.ttl declares the
# versionIRI of 0.8.0-beta, and battinfo-inferred.ttl is its inferred form.
BETA_IMPORT = "https://w3id.org/emmo/domain/battery/0.13.0-beta/battery"
BETA = (
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n\n"
    "<https://w3id.org/battinfo> a owl:Ontology ;\n"
    f"    owl:imports <{BETA_IMPORT}> ;\n"
    "    owl:versionIRI <https://w3id.org/battinfo/0.8.0-beta/battinfo> ;\n"
    '    owl:versionInfo "0.8.0" .\n'
)
BETA_INFERRED = (
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n\n"
    "<https://w3id.org/battinfo/battinfo-inferred> a owl:Ontology ;\n"
    "    owl:versionIRI <https://w3id.org/battinfo/0.8.0-beta/battinfo-inferred> .\n"
)

# The gh-pages tree before the deploys: dev/, the v0.7.0 release and its stable/
# copy, a switcher and root page that the script did not write, and the
# ontology files published by hand before 0.8.0, with the root versions/ folder
# that holds copies of them under older release numbers.
SEED = {
    "dev/index.html": "dev build\n",
    "v0.7.0/index.html": "v0.7.0 build\n",
    "stable/index.html": "v0.7.0 build\n",
    "switcher.json": '[{"version": "dev"}, {"version": "v0.7.0", "preferred": true}]\n',
    "index.html": "seeded root page\n",
    "battinfo.ttl": BETA,
    "battinfo-inferred.ttl": BETA_INFERRED,
    "battinfo.html": "old class index\n",
    "versions/0.5.0/battinfo.ttl": BETA,
    "versions/v0.6.0/battinfo-inferred.ttl": BETA_INFERRED,
    "versions/test/context/context.json": "{}\n",
    ".nojekyll": "",
}

# Stands in for ROBOT. It writes --output declaring the --version-iri it was
# given, with the arguments other than the paths in a comment, unless
# FAKE_ROBOT tells it to fail, to run too long or to declare another version.
FAKE_ROBOT = """\
import os, sys, time

args = sys.argv[1:]
mode = os.environ["FAKE_ROBOT"]
if mode == "slow":
    time.sleep(60)
if mode == "fail":
    sys.exit("ERROR There are 3670 unsatisfiable classes in the ontology.")
shown = [arg for index, arg in enumerate(args) if index == 0 or args[index - 1] not in ("--catalog", "--input", "--output")]
iri = args[args.index("--version-iri") + 1] if mode == "infer" else "https://w3id.org/battinfo/0.0.0/inferred"
with open(args[args.index("--output") + 1], "w", encoding="utf-8") as out:
    out.write("# robot " + " ".join(shown) + "\\n")
    out.write("<https://w3id.org/battinfo/inferred> a owl:Ontology ;\\n    owl:versionIRI <" + iri + "> .\\n")
"""
REASONED = (
    "# robot merge --catalog --input reason --reasoner HermiT annotate --ontology-iri https://w3id.org/battinfo/inferred "
    "--version-iri https://w3id.org/battinfo/{0}/inferred "
    "--link-annotation http://www.w3.org/ns/prov#wasDerivedFrom https://w3id.org/battinfo/{0}/battinfo --output\n"
)

IMPORTS = [
    "https://w3id.org/emmo/domain/battery/0.21.0/battery",
    "https://w3id.org/emmo/domain/electrochemistry/0.39.0/electrochemistry",
]


def _ontology(version: str) -> bytes:
    """A battinfo.ttl laid out as the real one, declaring *version*."""
    imports = "".join(f"    owl:imports <{iri}> ;\n" for iri in IMPORTS)
    return (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix battinfo: <https://w3id.org/battinfo#> .\n\n"
        "battinfo: a owl:Ontology ;\n"
        f"    owl:versionIRI <https://w3id.org/battinfo/{version}/battinfo> ;\n"
        f"{imports}"
        f'    owl:versionInfo "{version}" .\n'
    ).encode("utf-8")


def _inferred(version: str) -> bytes:
    """The battinfo-inferred.ttl the stand-in for ROBOT writes for *version*."""
    return (
        REASONED.format(version) + "<https://w3id.org/battinfo/inferred> a owl:Ontology ;\n"
        f"    owl:versionIRI <https://w3id.org/battinfo/{version}/inferred> .\n"
    ).encode("utf-8")


def _bash() -> str | None:
    """A POSIX bash: on Windows Git's, never the WSL launcher in System32."""
    candidates = [shutil.which("bash")]
    git = shutil.which("git")
    if os.name == "nt" and git:
        git_root = Path(git).resolve().parents[1]
        candidates += [str(git_root / "bin" / "bash.exe"), str(git_root / "usr" / "bin" / "bash.exe")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and "system32" not in candidate.lower():
            return candidate
    return None


def _env(tmp_path: Path) -> dict[str, str]:
    """git without the user's or the system's configuration, and a temporary folder inside tmp_path."""
    scratch = tmp_path / "tmp"
    scratch.mkdir(exist_ok=True)
    return {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "TMPDIR": scratch.as_posix(),
        "PYTHON": Path(sys.executable).as_posix(),
    }


def _git(cwd: Path, env: dict[str, str], *args: str) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", "-c", "init.defaultBranch=main", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


@pytest.fixture()
def site(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """(the test's folder, the bare repository standing in for origin, the environment)."""
    if _bash() is None or shutil.which("git") is None:
        pytest.skip("needs bash and git")
    env = _env(tmp_path)
    origin = tmp_path / "origin.git"
    _git(tmp_path, env, "init", "-q", "--bare", str(origin))

    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, env, "init", "-q")
    (seed / "README.md").write_text("main\n", encoding="utf-8")
    _git(seed, env, "add", "-A")
    _git(seed, env, "commit", "-q", "-m", "main")
    _git(seed, env, "checkout", "-q", "--orphan", "gh-pages")
    _git(seed, env, "rm", "-q", "-rf", ".")
    for relative, text in SEED.items():
        path = seed / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    _git(seed, env, "add", "-A")
    _git(seed, env, "commit", "-q", "-m", "seed the site")
    _git(seed, env, "push", "-q", str(origin), "main", "gh-pages")
    return tmp_path, origin, env


def _deploy(
    site: tuple[Path, Path, dict[str, str]],
    version: str,
    *,
    ontology: str | None = None,
    ok: bool = True,
    reasoner: str | None = None,
    reasoner_timeout: str = "120",
    vocabularies: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the script as docs.yml does: in a fresh clone of the tag, holding the built docs.

    The clone's battinfo.ttl declares *ontology*, by default the tag's own
    version (0.8.0 for a branch build or a pre-release). With *reasoner*, ROBOT
    is the stand-in, doing what FAKE_ROBOT says for that word; without it,
    ROBOT is not set. *vocabularies* is the clone's def/ folder, which the
    build job lays out in docs/_build/def-site; without it, def/ holds no
    vocabulary.
    """
    tmp_path, origin, env = site
    checkout = tmp_path / f"checkout-{len(list(tmp_path.glob('checkout-*')))}"
    _git(tmp_path, env, "clone", "-q", str(origin), str(checkout))
    build = checkout / "docs" / "_build" / "html"
    build.mkdir(parents=True)
    (build / "index.html").write_bytes(f"{version} build\n".encode())
    def_dir = vocabularies if vocabularies is not None else checkout / "def"
    assert def_site.build(checkout / "docs" / "_build" / "def-site", def_dir) == []
    final = re.fullmatch(r"v(\d+\.\d+\.\d+)", version)
    (checkout / "battinfo.ttl").write_bytes(_ontology(ontology or (final.group(1) if final else "0.8.0")))
    env = {**env, "ROBOT": "", "REASONER_TIMEOUT": reasoner_timeout}
    if reasoner is not None:
        robot = tmp_path / "fake_robot.py"
        robot.write_text(FAKE_ROBOT, encoding="utf-8")
        env.update(ROBOT=f'"{Path(sys.executable).as_posix()}" "{robot.as_posix()}"', FAKE_ROBOT=reasoner)
    bash = _bash()
    assert bash is not None
    proc = subprocess.run(
        [bash, SCRIPT.as_posix(), version], cwd=checkout, env=env, capture_output=True, text=True, check=False
    )
    assert (proc.returncode == 0) is ok, proc.stdout + proc.stderr
    return proc


def _published(site: tuple[Path, Path, dict[str, str]], relative: str) -> bytes:
    _checkout, origin, env = site
    proc = subprocess.run(
        ["git", "--git-dir", str(origin), "show", f"gh-pages:{relative}"], env=env, capture_output=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.replace(b"\r\n", b"\n")


def _is_published(site: tuple[Path, Path, dict[str, str]], relative: str) -> bool:
    _checkout, origin, env = site
    proc = subprocess.run(
        ["git", "--git-dir", str(origin), "cat-file", "-e", f"gh-pages:{relative}"],
        env=env,
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def _listed(site: tuple[Path, Path, dict[str, str]], folder: str) -> list[str]:
    _checkout, origin, env = site
    proc = subprocess.run(
        ["git", "--git-dir", str(origin), "ls-tree", "--name-only", f"gh-pages:{folder}"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return [folder + name for name in proc.stdout.split()]


def _add_to_site(site: tuple[Path, Path, dict[str, str]], files: dict[str, str]) -> None:
    """Commit *files* to gh-pages on origin, as a deploy that stopped part-way might have."""
    tmp_path, origin, env = site
    clone = tmp_path / "add-to-site"
    _git(tmp_path, env, "clone", "-q", "--branch", "gh-pages", str(origin), str(clone))
    for relative, text in files.items():
        path = clone / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    _git(clone, env, "add", "-A")
    _git(clone, env, "commit", "-q", "-m", "add to the site")
    _git(clone, env, "push", "-q", "origin", "gh-pages")


def _switcher(site: tuple[Path, Path, dict[str, str]]) -> list[dict]:
    return json.loads(_published(site, "switcher.json"))


def test_a_release_candidate_gets_its_own_folder_and_leaves_stable_and_the_switcher_alone(
    site: tuple[Path, Path, dict[str, str]],
) -> None:
    _deploy(site, "v0.8.0rc1")

    assert _published(site, "v0.8.0rc1/index.html") == b"v0.8.0rc1 build\n"
    assert _published(site, "stable/index.html") == b"v0.7.0 build\n"
    assert _published(site, "switcher.json") == SEED["switcher.json"].encode()
    assert _published(site, "index.html") == SEED["index.html"].encode()
    # A pre-release does not publish its ontology, nor tidy the old files.
    assert _published(site, "battinfo.ttl") == SEED["battinfo.ttl"].encode()
    assert _published(site, "battinfo.html") == SEED["battinfo.html"].encode()
    assert _published(site, "battinfo-inferred.ttl") == SEED["battinfo-inferred.ttl"].encode()
    assert _published(site, "versions/0.5.0/battinfo.ttl") == SEED["versions/0.5.0/battinfo.ttl"].encode()
    assert not _is_published(site, "battinfo/versions")


def test_a_final_release_updates_stable_and_the_switcher_and_a_backport_does_not_take_stable(
    site: tuple[Path, Path, dict[str, str]],
) -> None:
    _deploy(site, "v0.8.0rc1")
    _deploy(site, "v0.8.0")

    assert _published(site, "stable/index.html") == b"v0.8.0 build\n"
    assert _published(site, "v0.8.0/index.html") == b"v0.8.0 build\n"
    switcher = _switcher(site)
    assert [entry["version"] for entry in switcher] == ["dev", "v0.8.0", "v0.7.0"]  # no release candidate
    assert switcher[1] == {
        "name": "v0.8.0 (stable)",
        "version": "v0.8.0",
        "url": "https://big-map.github.io/BattINFO/v0.8.0/",
        "preferred": True,
    }
    assert b'url=./stable/"' in _published(site, "index.html")

    # A backport is listed, but stable/ keeps the newest final release.
    _deploy(site, "v0.7.1")
    assert _published(site, "stable/index.html") == b"v0.8.0 build\n"
    assert [entry["version"] for entry in _switcher(site)] == ["dev", "v0.8.0", "v0.7.1", "v0.7.0"]

    # main's docs go to dev/ and leave the releases as they are.
    _deploy(site, "dev")
    assert _published(site, "dev/index.html") == b"dev build\n"
    assert _published(site, "stable/index.html") == b"v0.8.0 build\n"
    assert [entry["version"] for entry in _switcher(site)] == ["dev", "v0.8.0", "v0.7.1", "v0.7.0"]


def test_a_final_release_publishes_the_ontology_at_its_version_and_the_newest_at_the_root(
    site: tuple[Path, Path, dict[str, str]],
) -> None:
    _deploy(site, "v0.8.0", reasoner="infer")

    for folder in ("battinfo/versions/0.8.0/", ""):
        assert _published(site, f"{folder}battinfo.ttl") == _ontology("0.8.0")
        assert _published(site, f"{folder}battinfo-inferred.ttl") == _inferred("0.8.0")
        page = _published(site, f"{folder}battinfo.html").decode("utf-8")
        assert "BattINFO ontology 0.8.0" in page
        assert 'href="battinfo.ttl"' in page
        assert 'href="battinfo-inferred.ttl"' in page
        assert "https://w3id.org/battinfo/0.8.0/battinfo" in page
        assert all(iri in page for iri in IMPORTS)
        assert "https://big-map.github.io/BattINFO/v0.8.0/" in page
    assert not _is_published(site, "battinfo/versions/v0.8.0")  # w3id's path has no v

    # A backport gets its version folder; the root keeps the newest release.
    _deploy(site, "v0.7.1", reasoner="infer")
    assert _published(site, "battinfo/versions/0.7.1/battinfo.ttl") == _ontology("0.7.1")
    assert _published(site, "battinfo/versions/0.7.1/battinfo-inferred.ttl") == _inferred("0.7.1")
    assert _published(site, "battinfo.ttl") == _ontology("0.8.0")
    assert _published(site, "battinfo-inferred.ttl") == _inferred("0.8.0")
    assert "BattINFO ontology 0.8.0" in _published(site, "battinfo.html").decode("utf-8")

    # main's docs leave the ontology alone.
    _deploy(site, "dev", ontology="0.9.0", reasoner="infer")
    assert _published(site, "battinfo.ttl") == _ontology("0.8.0")
    assert _published(site, "battinfo-inferred.ttl") == _inferred("0.8.0")
    assert not _is_published(site, "battinfo/versions/0.9.0")

    # Without the reasoner, a rerun keeps the inferred files the release has.
    proc = _deploy(site, "v0.8.0")
    assert "No docs changes to deploy." in proc.stdout, proc.stdout + proc.stderr
    assert _published(site, "battinfo-inferred.ttl") == _inferred("0.8.0")


def test_before_a_release_replaces_the_root_its_ontology_is_kept_at_its_version_iri(
    site: tuple[Path, Path, dict[str, str]],
) -> None:
    # main's deploy keeps the 2024 files where w3id sends their versionIRI,
    # https://w3id.org/battinfo/0.8.0-beta/battinfo, and leaves the root alone.
    _deploy(site, "dev")

    kept = "battinfo/versions/0.8.0-beta/"
    assert _published(site, f"{kept}battinfo.ttl") == BETA.encode()
    assert _published(site, f"{kept}battinfo-inferred.ttl") == BETA_INFERRED.encode()
    page = _published(site, f"{kept}battinfo.html").decode("utf-8")
    assert "BattINFO ontology 0.8.0-beta" in page
    assert "https://w3id.org/battinfo/0.8.0-beta/battinfo" in page
    assert BETA_IMPORT in page
    assert 'href="battinfo.ttl"' in page and 'href="battinfo-inferred.ttl"' in page
    assert "big-map.github.io/BattINFO/v0.8.0-beta" not in page  # no docs were published for it
    assert _published(site, "battinfo.ttl") == BETA.encode()
    assert _published(site, "battinfo-inferred.ttl") == BETA_INFERRED.encode()
    # The root versions/ folder of mislabelled copies is gone.
    assert not _is_published(site, "versions")

    # Running again changes nothing.
    proc = _deploy(site, "dev")
    assert "No docs changes to deploy." in proc.stdout, proc.stdout + proc.stderr

    # The release replaces the root; the beta stays in its folder.
    _deploy(site, "v0.8.0", reasoner="infer")
    assert _published(site, "battinfo.ttl") == _ontology("0.8.0")
    assert _published(site, "battinfo-inferred.ttl") == _inferred("0.8.0")
    assert _published(site, f"{kept}battinfo.ttl") == BETA.encode()
    assert _published(site, f"{kept}battinfo-inferred.ttl") == BETA_INFERRED.encode()


def test_a_partly_written_beta_folder_is_replaced_whole(site: tuple[Path, Path, dict[str, str]]) -> None:
    # The folder is written beside its place and renamed into it; one that an
    # older run left without its battinfo.ttl is replaced, not skipped.
    _add_to_site(site, {"battinfo/versions/0.8.0-beta/battinfo.html": "half written\n"})
    _deploy(site, "dev")

    assert _published(site, "battinfo/versions/0.8.0-beta/battinfo.ttl") == BETA.encode()
    assert _published(site, "battinfo/versions/0.8.0-beta/battinfo-inferred.ttl") == BETA_INFERRED.encode()
    assert "BattINFO ontology 0.8.0-beta" in _published(site, "battinfo/versions/0.8.0-beta/battinfo.html").decode()
    assert _listed(site, "battinfo/versions/") == ["battinfo/versions/0.8.0-beta"]  # nothing left beside it


def test_a_release_tag_keeps_the_beta_and_drops_the_root_versions_folder_on_its_own(
    site: tuple[Path, Path, dict[str, str]],
) -> None:
    # No main deploy between this change and the tag: the tag's deploy keeps the
    # beta before it replaces the root.
    _deploy(site, "v0.8.0", reasoner="infer")

    assert _published(site, "battinfo/versions/0.8.0-beta/battinfo.ttl") == BETA.encode()
    assert _published(site, "battinfo/versions/0.8.0-beta/battinfo-inferred.ttl") == BETA_INFERRED.encode()
    assert _published(site, "battinfo.ttl") == _ontology("0.8.0")
    assert not _is_published(site, "versions")


@pytest.mark.parametrize(
    ("reasoner", "said"),
    [
        (None, "ROBOT is not set"),
        ("fail", "ROBOT exited with 1: ERROR There are 3670 unsatisfiable classes in the ontology."),
        ("slow", "the reasoner ran for more than 2 s"),
        ("other", "the file ROBOT wrote does not declare the versionIRI <https://w3id.org/battinfo/0.8.0/inferred>"),
    ],
)
def test_without_a_reasoned_file_the_ontology_is_published_and_the_root_drops_the_beta_inferred_file(
    site: tuple[Path, Path, dict[str, str]], reasoner: str | None, said: str
) -> None:
    proc = _deploy(site, "v0.8.0", reasoner=reasoner, reasoner_timeout="2")

    for folder in ("battinfo/versions/0.8.0/", ""):
        assert _published(site, f"{folder}battinfo.ttl") == _ontology("0.8.0")
        assert not _is_published(site, f"{folder}battinfo-inferred.ttl")
        assert "battinfo-inferred.ttl" not in _published(site, f"{folder}battinfo.html").decode("utf-8")
    # /inferred no longer answers with the beta's file; its own folder keeps it.
    assert _published(site, "battinfo/versions/0.8.0-beta/battinfo-inferred.ttl") == BETA_INFERRED.encode()
    assert f"::warning::No battinfo-inferred.ttl for 0.8.0: {said}" in proc.stderr, proc.stderr


def test_a_final_tag_whose_ontology_names_another_version_deploys_its_docs_but_not_the_ontology(
    site: tuple[Path, Path, dict[str, str]],
) -> None:
    proc = _deploy(site, "v0.8.1", ontology="0.8.0", ok=False, reasoner="infer")

    assert "0.8.1" in proc.stderr and "battinfo.ttl" in proc.stderr, proc.stderr
    assert _published(site, "v0.8.1/index.html") == b"v0.8.1 build\n"
    assert not _is_published(site, "battinfo/versions/0.8.1")
    assert not _is_published(site, "battinfo/versions/0.8.0")
    assert _published(site, "battinfo.ttl") == SEED["battinfo.ttl"].encode()
    assert _published(site, "battinfo-inferred.ttl") == SEED["battinfo-inferred.ttl"].encode()


def test_deploys_run_one_at_a_time_and_a_running_one_is_never_cancelled() -> None:
    """A tag's deploy and main's would otherwise both push to gh-pages, and the second push be refused."""
    docs = yaml.safe_load((ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8"))
    deploy = docs["jobs"]["deploy"]
    assert deploy["concurrency"]["cancel-in-progress"] is False
    assert "${{" not in deploy["concurrency"]["group"]  # one group for every ref
    assert deploy["steps"][-1]["run"] == 'bash .github/workflows/docs-deploy.sh "$DOCS_VERSION"'


def test_the_reasoner_reads_the_emmo_release_that_battinfo_ttl_pins() -> None:
    # w3id answers the EMMO version IRI with a squashed file in which HermiT
    # finds the closure incoherent; the catalog sends ROBOT to the release's
    # own emmo.ttl, and must name the EMMO version battinfo.ttl is pinned to.
    pinned = re.search(r"^#\s+EMMO core\s+(\S+)$", (ROOT / "battinfo.ttl").read_text(encoding="utf-8"), re.M)
    assert pinned is not None
    catalog = (ROOT / ".github" / "workflows" / "docs-deploy-catalog.xml").read_text(encoding="utf-8")
    entries = re.findall(r'<uri name="([^"]+)" uri="([^"]+)"/>', catalog)
    version = pinned.group(1)
    assert entries == [
        (f"https://w3id.org/emmo/{version}", f"https://raw.githubusercontent.com/emmo-repo/EMMO/{version}/emmo.ttl")
    ]
    assert 'CATALOG=".github/workflows/docs-deploy-catalog.xml"' in SCRIPT.read_text(encoding="utf-8")


def test_robot_is_pinned_checked_and_cannot_stop_a_deploy() -> None:
    docs = yaml.safe_load((ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8"))
    deploy = docs["jobs"]["deploy"]
    (install,) = [step for step in deploy["steps"] if "robot.jar" in step.get("run", "")]
    assert install["continue-on-error"] is True
    # A stalled download cannot take the deploy's time.
    assert install["timeout-minutes"] <= 5
    assert "--max-time 300" in install["run"]
    # When it fails, a step says so.
    (warn,) = [step for step in deploy["steps"] if step.get("if") == f"steps.{install['id']}.outcome == 'failure'"]
    assert "::warning::" in warn["run"]
    assert install["if"] == "startsWith(github.ref, 'refs/tags/v')"
    assert re.fullmatch(r"\d+\.\d+\.\d+", install["env"]["ROBOT_VERSION"])
    assert re.fullmatch(r"[0-9a-f]{64}", install["env"]["ROBOT_SHA256"])
    assert "sha256sum --check" in install["run"]
    # ROBOT is set only once the jar passed the check.
    assert install["run"].index("sha256sum") < install["run"].index("GITHUB_ENV")
    # The job outlasts the reasoner's time limit.
    limit = re.search(r'get\("REASONER_TIMEOUT"\) or (\d+)', SCRIPT.read_text(encoding="utf-8"))
    assert limit is not None
    assert deploy["timeout-minutes"] * 60 >= int(limit.group(1)) + 5 * 60


# The publishers' vocabularies under def/.

PRIOR_OF_THE_BETA = "    owl:priorVersion <https://w3id.org/battinfo/def/1000/1.0.0> ;\n"


def _vocabularies(site: tuple[Path, Path, dict[str, str]], *versions: str, first_beta: bool = False) -> Path:
    """A checkout's def/ folder holding the fixture releases *versions* of prefix 1000.

    With *first_beta*, 1.1.0-beta.1 is the vocabulary's first release, so it
    names no prior version.
    """
    tmp_path = site[0]
    def_dir = tmp_path / f"def-{len(list(tmp_path.glob('def-*')))}" / "def"
    for version in versions:
        shutil.copytree(FIXTURE_DEF / "1000" / version, def_dir / "1000" / version)
    if first_beta:
        beta = def_dir / "1000" / "1.1.0-beta.1" / "vocab.ttl"
        beta.write_text(beta.read_text(encoding="utf-8").replace(PRIOR_OF_THE_BETA, ""), encoding="utf-8")
    return def_dir


def _release(def_dir: Path, version: str) -> bytes:
    return (def_dir / "1000" / version / "vocab.ttl").read_bytes().replace(b"\r\n", b"\n")


def test_without_vocabularies_nothing_is_published_under_def(site: tuple[Path, Path, dict[str, str]]) -> None:
    _deploy(site, "dev")
    assert not _is_published(site, "def")


def test_vocabulary_releases_are_published_and_the_vocabulary_serves_its_newest_final_release(
    site: tuple[Path, Path, dict[str, str]],
) -> None:
    # A pre-release alone is served at the vocabulary's address.
    beta_only = _vocabularies(site, "1.1.0-beta.1", first_beta=True)
    _deploy(site, "dev", vocabularies=beta_only)
    assert _published(site, "def/1000/1.1.0-beta.1/vocab.ttl") == _release(beta_only, "1.1.0-beta.1")
    beta_page = _published(site, "def/1000/1.1.0-beta.1/index.html")
    assert (
        b"<tr><th>Version IRI</th><td><code>https://w3id.org/battinfo/def/1000/1.1.0-beta.1</code></td></tr>"
        in beta_page
    )
    assert _published(site, "def/1000/vocab.ttl") == _release(beta_only, "1.1.0-beta.1")
    assert _published(site, "def/1000/index.html") == beta_page
    assert b'<a href="1000/1.1.0-beta.1/">1.1.0-beta.1</a>, served at the ontology IRI' in _published(
        site, "def/index.html"
    )

    # A final release is added beside it and takes the vocabulary's address.
    with_final = _vocabularies(site, "1.1.0-beta.1", "1.1.0", first_beta=True)
    _deploy(site, "dev", vocabularies=with_final)
    assert sorted(_listed(site, "def/1000/")) == [
        "def/1000/1.1.0",
        "def/1000/1.1.0-beta.1",
        "def/1000/index.html",
        "def/1000/vocab.ttl",
    ]
    assert _published(site, "def/1000/1.1.0-beta.1/index.html") == beta_page
    assert _published(site, "def/1000/vocab.ttl") == _release(with_final, "1.1.0")
    assert _published(site, "def/1000/index.html") == _published(site, "def/1000/1.1.0/index.html")
    index = _published(site, "def/index.html").decode("utf-8")
    assert re.findall(r'<li><a href="1000/([^/]+)/">', index) == ["1.1.0", "1.1.0-beta.1"]
    assert '<a href="1000/1.1.0/">1.1.0</a>, served at the ontology IRI' in index

    # Running again changes nothing.
    proc = _deploy(site, "dev", vocabularies=with_final)
    assert "No docs changes to deploy." in proc.stdout, proc.stdout + proc.stderr


def test_a_tag_built_from_an_older_checkout_keeps_the_newer_releases(site: tuple[Path, Path, dict[str, str]]) -> None:
    every = _vocabularies(site, "1.0.0", "1.1.0-beta.1", "1.1.0")
    _deploy(site, "dev", vocabularies=every)

    # A pre-release tag deploys the vocabularies too, and a tag cut before the
    # newer releases leaves them, and the vocabulary's address, as they are.
    for tag in ("v0.8.1rc1", "v0.8.1"):
        _deploy(site, tag, vocabularies=_vocabularies(site, "1.0.0"))
        for version in ("1.0.0", "1.1.0-beta.1", "1.1.0"):
            assert _published(site, f"def/1000/{version}/vocab.ttl") == _release(every, version)
        assert _published(site, "def/1000/vocab.ttl") == _release(every, "1.1.0")
        index = _published(site, "def/index.html").decode("utf-8")
        assert re.findall(r'<li><a href="1000/([^/]+)/">', index) == ["1.1.0", "1.1.0-beta.1", "1.0.0"]

    # A checkout that no longer has a release does not remove it either.
    _deploy(site, "dev")
    assert _published(site, "def/1000/1.0.0/vocab.ttl") == _release(every, "1.0.0")


def test_a_published_release_is_never_replaced_and_a_different_copy_is_warned_about(
    site: tuple[Path, Path, dict[str, str]],
) -> None:
    first = _vocabularies(site, "1.0.0")
    _deploy(site, "dev", vocabularies=first)
    page = _published(site, "def/1000/1.0.0/index.html")

    changed = _vocabularies(site, "1.0.0")
    vocab = changed / "1000" / "1.0.0" / "vocab.ttl"
    vocab.write_text(vocab.read_text(encoding="utf-8").replace('"sample"@en', '"specimen"@en'), encoding="utf-8")
    proc = _deploy(site, "dev", vocabularies=changed)

    assert _published(site, "def/1000/1.0.0/vocab.ttl") == _release(first, "1.0.0")
    assert _published(site, "def/1000/1.0.0/index.html") == page
    assert _published(site, "def/1000/vocab.ttl") == _release(first, "1.0.0")
    assert "::warning::def/1000/1.0.0/vocab.ttl on gh-pages differs from this checkout's." in proc.stderr, proc.stderr
    assert "No docs changes to deploy." in proc.stdout, proc.stdout + proc.stderr


def test_a_fix_to_the_page_reaches_a_published_release_whose_vocabulary_is_unchanged(
    site: tuple[Path, Path, dict[str, str]],
) -> None:
    def_dir = _vocabularies(site, "1.0.0")
    _deploy(site, "dev", vocabularies=def_dir)
    page = _published(site, "def/1000/1.0.0/index.html")
    vocab = _published(site, "def/1000/1.0.0/vocab.ttl")
    # The page an older build of the site wrote.
    _add_to_site(site, {"def/1000/1.0.0/index.html": "older page\n", "def/1000/index.html": "older page\n"})

    proc = _deploy(site, "dev", vocabularies=def_dir)
    assert _published(site, "def/1000/1.0.0/index.html") == page
    assert _published(site, "def/1000/index.html") == page
    assert _published(site, "def/1000/1.0.0/vocab.ttl") == vocab
    assert "::warning::" not in proc.stderr, proc.stderr


def test_a_partly_written_release_folder_is_replaced_whole(site: tuple[Path, Path, dict[str, str]]) -> None:
    # A folder without vocab.ttl is not a published release.
    _add_to_site(site, {"def/1000/1.0.0/index.html": "half written\n"})
    def_dir = _vocabularies(site, "1.0.0")
    _deploy(site, "dev", vocabularies=def_dir)

    assert _published(site, "def/1000/1.0.0/vocab.ttl") == _release(def_dir, "1.0.0")
    assert b"<h1>Example vocabulary</h1>" in _published(site, "def/1000/1.0.0/index.html")
    assert _listed(site, "def/1000/1.0.0/") == ["def/1000/1.0.0/index.html", "def/1000/1.0.0/vocab.ttl"]
    assert _listed(site, "def/1000/") == ["def/1000/1.0.0", "def/1000/index.html", "def/1000/vocab.ttl"]


def test_the_build_job_lays_out_the_vocabularies_where_the_deploy_reads_them() -> None:
    docs = yaml.safe_load((ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8"))
    build, deploy = docs["jobs"]["build"], docs["jobs"]["deploy"]
    (step,) = [s for s in build["steps"] if "scripts/build_def_site.py" in s.get("run", "")]
    assert step["run"].endswith("scripts/build_def_site.py docs/_build/def-site")
    (upload,) = [s for s in build["steps"] if s.get("with", {}).get("name") == "def-site"]
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["with"]["path"] == "docs/_build/def-site"
    (download,) = [s for s in deploy["steps"] if s.get("with", {}).get("name") == "def-site"]
    assert download["uses"].startswith("actions/download-artifact@")
    assert download["with"]["path"] == "docs/_build/def-site"
    assert 'DEF_SITE="docs/_build/def-site"' in SCRIPT.read_text(encoding="utf-8")
    # A merge that changes only def/ deploys: main's pushes have no path filter.
    triggers = docs.get("on", docs.get(True))
    assert triggers["push"] == {"branches": ["main"], "tags": ["v*"]}
