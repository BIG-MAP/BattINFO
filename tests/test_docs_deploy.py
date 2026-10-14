""".github/workflows/docs-deploy.sh, run against a scratch gh-pages tree.

docs.yml deploys the docs of every v* tag. A pre-release tag such as
v0.8.0rc1 gets its own folder and nothing else, so during the soak stable/,
switcher.json and the root index.html still show the last final release. A
final tag vX.Y.Z updates them, but stable/ only follows the newest final
release, so a backport does not replace it.

The script runs with bash and git, against a local bare repository standing
in for origin; nothing leaves the machine.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "workflows" / "docs-deploy.sh"

# The gh-pages tree before the deploys: dev/, the v0.7.0 release and its stable/
# copy, and a switcher and root page that the script did not write.
SEED = {
    "dev/index.html": "dev build\n",
    "v0.7.0/index.html": "v0.7.0 build\n",
    "stable/index.html": "v0.7.0 build\n",
    "switcher.json": '[{"version": "dev"}, {"version": "v0.7.0", "preferred": true}]\n',
    "index.html": "seeded root page\n",
    ".nojekyll": "",
}


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


def _deploy(site: tuple[Path, Path, dict[str, str]], version: str) -> None:
    """Run the script as docs.yml does: in a fresh clone holding the built docs."""
    tmp_path, origin, env = site
    checkout = tmp_path / f"checkout-{len(list(tmp_path.glob('checkout-*')))}"
    _git(tmp_path, env, "clone", "-q", str(origin), str(checkout))
    build = checkout / "docs" / "_build" / "html"
    build.mkdir(parents=True)
    (build / "index.html").write_bytes(f"{version} build\n".encode())
    bash = _bash()
    assert bash is not None
    proc = subprocess.run(
        [bash, SCRIPT.as_posix(), version], cwd=checkout, env=env, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def _published(site: tuple[Path, Path, dict[str, str]], relative: str) -> bytes:
    _checkout, origin, env = site
    proc = subprocess.run(
        ["git", "--git-dir", str(origin), "show", f"gh-pages:{relative}"], env=env, capture_output=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.replace(b"\r\n", b"\n")


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


def test_deploys_run_one_at_a_time_and_a_running_one_is_never_cancelled() -> None:
    """A tag's deploy and main's would otherwise both push to gh-pages, and the second push be refused."""
    docs = yaml.safe_load((ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8"))
    deploy = docs["jobs"]["deploy"]
    assert deploy["concurrency"]["cancel-in-progress"] is False
    assert "${{" not in deploy["concurrency"]["group"]  # one group for every ref
    assert deploy["steps"][-1]["run"] == 'bash .github/workflows/docs-deploy.sh "$DOCS_VERSION"'
