"""~/.battinfo/config.yaml: a file that cannot be read is never overwritten, a
failed write keeps the old file, and secrets stay out of the CLI output.

`battinfo config set` used to read a config file that was not valid YAML as
empty and write the one value it was setting over it, so the stored Zenodo
token, creator and community were lost, and `battinfo config show` said there
was no config file at all. A value PyYAML cannot build, such as the date
2026-02-30, makes a file unreadable too. Every test points the config path at a
temporary folder, so the real home folder is never read or written.
"""

from __future__ import annotations

import errno
import json
import os
import sys
import warnings
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import config  # noqa: E402
from battinfo.cli import app  # noqa: E402

runner = CliRunner()

TOKEN = "zt_live_8f3a91c2d4e5b6a7"
API_KEY = "bk_live_c0ffee1234567890"
GOOD = f"community: battery-lab\ncreator: Lovelace, Ada; Analytical Engines\nzenodo_token: {TOKEN}\n"
# The fourth line is not valid YAML: a plain value cannot hold ": ".
CORRUPT = GOOD + "license: CC-BY-4.0: oops\n"
# The fourth line is valid YAML syntax, but the date does not exist, and PyYAML
# raises a plain ValueError for it rather than a YAML error.
IMPOSSIBLE_DATE = GOOD + "embargo_until: 2026-02-30\n"
# A test marked with this runs on both kinds of file that cannot be read.
unreadable = pytest.mark.parametrize("content", [CORRUPT, IMPOSSIBLE_DATE], ids=["syntax-error", "impossible-date"])


@pytest.fixture(autouse=True)
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the user config at a temporary home folder, with no token exported."""
    path = tmp_path / "home" / ".battinfo" / "config.yaml"
    monkeypatch.setattr(config, "USER_CONFIG_PATH", path)
    monkeypatch.delenv("ZENODO_API_TOKEN", raising=False)
    return path


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ── Reading ──────────────────────────────────────────────────────────────────


def test_a_missing_config_file_reads_as_empty() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert config.load_user_config() == {}
        assert config.load_user_config(strict=True) == {}


@pytest.mark.parametrize("text", ["", "# only a comment\n"])
def test_a_config_file_without_values_reads_as_empty(config_path: Path, text: str) -> None:
    _write(config_path, text)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert config.load_user_config(strict=True) == {}


def test_a_valid_config_file_reads_as_its_values(config_path: Path) -> None:
    _write(config_path, GOOD)
    assert config.load_user_config(strict=True) == {
        "community": "battery-lab",
        "creator": "Lovelace, Ada; Analytical Engines",
        "zenodo_token": TOKEN,
    }


@unreadable
def test_a_corrupt_config_file_gives_a_warning_that_names_it(config_path: Path, content: str) -> None:
    _write(config_path, content)
    with pytest.warns(UserWarning) as caught:
        assert config.load_user_config() == {}
    message = str(caught[0].message)
    assert str(config_path) in message
    assert "not valid YAML" in message
    assert "line 4" in message
    assert "battinfo config set" in message  # says how to fix it


@unreadable
def test_strict_loading_of_a_corrupt_config_file_raises_and_names_it(config_path: Path, content: str) -> None:
    _write(config_path, content)
    with pytest.raises(config.UserConfigError) as caught:
        config.load_user_config(strict=True)
    assert str(config_path) in str(caught.value)
    assert caught.value.path == config_path
    assert isinstance(caught.value, ValueError)


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        (b"- creator\n- license\n", "holds a list"),
        (b"just one value\n", "holds a single value"),
        (b"creator: Lovelace\nlicense: CC\xff0\n", "not UTF-8 text"),
        (b"creator: Lovelace\n---\nlicense: CC0-1.0\n", "not valid YAML"),
        # Python's own wording: "day is out of range for month" up to 3.13, "day 30 must be in range ..." from 3.14.
        (b"creator: Lovelace\nembargo_until: 2026-02-30\n", r"not valid YAML \(day [^,]*month[^,]*, line 2"),
        (b"creator: Lovelace\nopen: !!bool maybe\n", r"not valid YAML \(cannot read the value as !!bool, line 2"),
        (b"creator: " + b"[" * 2000 + b"]" * 2000 + b"\n", "not valid YAML"),
    ],
    ids=["list", "scalar", "not-utf8", "two-documents", "impossible-date", "value-against-its-tag", "nested-too-deep"],
)
def test_a_config_file_that_is_not_key_value_pairs_is_reported(config_path: Path, content: bytes, problem: str) -> None:
    config_path.parent.mkdir(parents=True)
    config_path.write_bytes(content)
    with pytest.raises(config.UserConfigError, match=problem):
        config.load_user_config(strict=True)


@unreadable
def test_the_creator_fallback_warns_about_a_corrupt_config_file(config_path: Path, content: str) -> None:
    _write(config_path, content)
    with pytest.warns(UserWarning, match="not valid YAML"):
        assert config.resolve_creators(None) == []


@unreadable
def test_the_token_fallback_warns_and_still_reads_the_environment(
    config_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    _write(config_path, content)
    monkeypatch.setenv("ZENODO_API_TOKEN", "zt_from_the_environment")
    with pytest.warns(UserWarning, match="not valid YAML"):
        assert config.resolve_zenodo_token(None) == "zt_from_the_environment"


# ── Writing ──────────────────────────────────────────────────────────────────


@unreadable
def test_save_refuses_to_overwrite_a_corrupt_config_file(config_path: Path, content: str) -> None:
    _write(config_path, content)
    before = config_path.read_bytes()
    with pytest.raises(config.UserConfigError) as caught:
        config.save_user_config({"license": "CC0-1.0"})
    assert str(config_path) in str(caught.value)
    assert config_path.read_bytes() == before


@unreadable
def test_set_value_refuses_to_overwrite_a_corrupt_config_file(config_path: Path, content: str) -> None:
    _write(config_path, content)
    before = config_path.read_bytes()
    with pytest.raises(config.UserConfigError, match="license was not saved"):
        config.set_user_config_value("license", "CC0-1.0")
    assert config_path.read_bytes() == before


def test_set_value_keeps_the_other_values(config_path: Path) -> None:
    _write(config_path, GOOD)
    config.set_user_config_value("license", "CC0-1.0")
    assert config.load_user_config(strict=True) == {
        "community": "battery-lab",
        "creator": "Lovelace, Ada; Analytical Engines",
        "license": "CC0-1.0",
        "zenodo_token": TOKEN,
    }


def test_set_value_creates_the_config_file_and_its_folder(config_path: Path) -> None:
    config.set_user_config_value("community", "battery-lab")
    assert config.load_user_config(strict=True) == {"community": "battery-lab"}


@pytest.mark.parametrize("failing_call", ["fsync", "replace"])
def test_a_failed_write_leaves_the_old_config_intact(
    config_path: Path, monkeypatch: pytest.MonkeyPatch, failing_call: str
) -> None:
    _write(config_path, GOOD)
    before = config_path.read_bytes()

    def disk_full(*args: object, **kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, failing_call, disk_full)
    with pytest.raises(OSError, match="No space left"):
        config.set_user_config_value("license", "CC0-1.0")
    monkeypatch.undo()
    assert config_path.read_bytes() == before
    # No temporary file is left next to it either.
    assert [p.name for p in config_path.parent.iterdir()] == ["config.yaml"]


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs extra rights on Windows")
def test_save_writes_through_a_symlinked_config_file(config_path: Path, tmp_path: Path) -> None:
    target = _write(tmp_path / "dotfiles" / "battinfo.yaml", GOOD)
    config_path.parent.mkdir(parents=True)
    config_path.symlink_to(target)
    config.set_user_config_value("license", "CC0-1.0")
    assert config_path.is_symlink()
    assert "license: CC0-1.0" in target.read_text(encoding="utf-8")


def test_save_refuses_values_it_could_not_read_back(config_path: Path) -> None:
    _write(config_path, GOOD)
    before = config_path.read_bytes()
    with pytest.raises(yaml.representer.RepresenterError):
        config.save_user_config({"creator": object()})
    assert config_path.read_bytes() == before


# ── Masking ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name", ["zenodo_token", "ZENODO_API_TOKEN", "api_key", "apiKey", "R2_SECRET_ACCESS_KEY", "password", "key"]
)
def test_names_of_secrets_are_recognised(name: str) -> None:
    assert config._is_secret_key(name)


@pytest.mark.parametrize("name", ["creator", "license", "community", "keywords", "monkey"])
def test_other_names_are_not_secret(name: str) -> None:
    assert not config._is_secret_key(name)


def test_a_masked_secret_shows_only_its_last_four_characters() -> None:
    assert config._masked(TOKEN) == "****" + TOKEN[-4:]
    assert config._masked("short-key") == "****"  # too short to show any of it


# ── CLI ──────────────────────────────────────────────────────────────────────


@unreadable
def test_config_set_on_a_corrupt_file_fails_and_keeps_the_file(config_path: Path, content: str) -> None:
    _write(config_path, content)
    before = config_path.read_bytes()
    result = runner.invoke(app, ["config", "set", "community", "my-community"])
    assert result.exit_code == 1, result.output
    assert str(config_path) in result.stderr
    assert "not valid YAML" in result.stderr
    assert config_path.read_bytes() == before


@unreadable
def test_config_show_reports_a_corrupt_file(config_path: Path, content: str) -> None:
    _write(config_path, content)
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 1, result.output
    assert str(config_path) in result.stderr
    assert "not valid YAML" in result.stderr
    assert "No config file" not in result.output


def test_config_show_on_an_empty_file_does_not_say_it_is_missing(config_path: Path) -> None:
    _write(config_path, "")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert "No config file" not in result.output
    assert "no values" in result.output


def test_config_set_masks_a_token(config_path: Path) -> None:
    result = runner.invoke(app, ["config", "set", "zenodo_token", TOKEN])
    assert result.exit_code == 0, result.output
    assert TOKEN not in result.output
    assert "****" + TOKEN[-4:] in result.output
    assert config.load_user_config(strict=True) == {"zenodo_token": TOKEN}  # stored in full


def test_config_set_echoes_a_value_that_is_not_secret(config_path: Path) -> None:
    result = runner.invoke(app, ["config", "set", "license", "CC0-1.0"])
    assert result.exit_code == 0, result.output
    assert "'CC0-1.0'" in result.output


def test_config_show_masks_secrets_and_shows_the_rest(config_path: Path) -> None:
    _write(config_path, GOOD + f"api_key: {API_KEY}\n")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert TOKEN not in result.output
    assert API_KEY not in result.output
    assert "zenodo_token: ****" + TOKEN[-4:] in result.output
    assert "api_key: ****" + API_KEY[-4:] in result.output
    assert "creator: Lovelace, Ada; Analytical Engines" in result.output
    assert "community: battery-lab" in result.output


def test_config_show_lists_keys_of_mixed_types(config_path: Path) -> None:
    _write(config_path, "creator: Lovelace\n2026: a year\n")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert "2026: a year" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["batch", "package", "{folder}", "--creator", "Lovelace, Ada"],
        ["batch", "upload", "{folder}", "--creator", "Lovelace, Ada", "--token", TOKEN],
        ["push", "{folder}", "--cell-spec", "Example R2032", "--creator", "Lovelace, Ada", "--dry-run"],
    ],
    ids=["batch-package", "batch-upload", "push"],
)
@unreadable
def test_commands_that_read_config_defaults_stop_on_a_corrupt_file(
    config_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str], content: str
) -> None:
    import battinfo.contribution
    import battinfo.zenodo

    def must_not_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("ran with a config file it could not read")

    monkeypatch.setattr(battinfo.contribution, "package_batch", must_not_run)
    monkeypatch.setattr(battinfo.contribution, "push_batch", must_not_run)
    monkeypatch.setattr(battinfo.zenodo, "upload_zenodo_package", must_not_run)
    _write(config_path, content)
    folder = tmp_path / "data"
    folder.mkdir()
    result = runner.invoke(app, [arg.format(folder=folder) for arg in args])
    assert result.exit_code == 1, result.output
    assert str(config_path) in result.stderr
    assert "not valid YAML" in result.stderr


@unreadable
def test_push_reports_a_corrupt_config_file_as_json(config_path: Path, tmp_path: Path, content: str) -> None:
    _write(config_path, content)
    folder = tmp_path / "data"
    folder.mkdir()
    result = runner.invoke(
        app, ["push", str(folder), "--cell-spec", "Example R2032", "--creator", "Lovelace, Ada", "--json"]
    )
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert str(config_path) in payload["error"]
