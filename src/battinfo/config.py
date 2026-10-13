from __future__ import annotations

import os
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from battinfo._jsonio import write_private_text

# ── User preferences ──────────────────────────────────────────────────────────

USER_CONFIG_PATH = Path.home() / ".battinfo" / "config.yaml"

_USER_CONFIG_KEYS = {"creator", "license", "community", "zenodo_token"}

_FIX_HINT = "Fix it by hand, or move it aside and set the values again with `battinfo config set`."

# A config key whose name contains one of these holds a secret. "key" counts only
# as a word of its own (api_key, accessKey), so "keywords" is not a secret.
_SECRET_MARKERS = ("token", "secret", "password", "passwd", "apikey", "api_key")


class UserConfigError(ValueError):
    """``~/.battinfo/config.yaml`` exists but cannot be read as ``key: value`` pairs."""

    def __init__(self, message: str, *, path: Path | None = None) -> None:
        super().__init__(message)
        self.path = path


def _yaml_problem(exc: Exception) -> str:
    """What PyYAML found wrong, on one line, with its place in the file when known."""
    problem = getattr(exc, "problem", None) or next(iter(str(exc).strip().splitlines()), "a syntax error")
    mark = getattr(exc, "problem_mark", None)
    if mark is None:
        return str(problem)
    return f"{problem}, line {mark.line + 1}, column {mark.column + 1}"


def _parse_user_config(path: Path) -> tuple[dict[str, Any], str | None]:
    """Read ``path``: its values, and why it cannot be used (``None`` when it can).

    A file that is empty or holds only comments has no values and no problem.
    """
    import yaml  # type: ignore[import-untyped]

    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return {}, "is not UTF-8 text"
    except OSError as exc:
        return {}, f"cannot be read ({exc.strerror or type(exc).__name__})"
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return {}, f"is not valid YAML ({_yaml_problem(exc)})"
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        kind = "a list" if isinstance(data, list) else "a single value"
        return {}, f"holds {kind}, not key: value pairs"
    return dict(data), None


def _unusable(path: Path, problem: str, consequence: str) -> UserConfigError:
    return UserConfigError(f"{path} {problem}, so {consequence}. {_FIX_HINT}", path=path)


def load_user_config(*, strict: bool = False) -> dict[str, Any]:
    """Load ~/.battinfo/config.yaml, returning an empty dict if absent.

    A file that exists but cannot be read as ``key: value`` pairs raises
    :class:`UserConfigError` with ``strict=True``. Otherwise it gives a warning
    that names the file and says how to fix it, and its values are left out, so
    the result is an empty dict.
    """
    path = USER_CONFIG_PATH
    if not path.exists():
        return {}
    config, problem = _parse_user_config(path)
    if problem is None:
        return config
    if strict:
        raise _unusable(path, problem, "its values cannot be used")
    warnings.warn(str(_unusable(path, problem, "its values are ignored")), UserWarning, stacklevel=2)
    return {}


def save_user_config(config: dict[str, Any]) -> None:
    """Write the full config dict to ~/.battinfo/config.yaml.

    The file is written to a temporary file in the same folder and then renamed
    over the old one, so a failed write leaves the old file as it was. It is
    readable by its owner only (mode 0600; Windows ignores the mode). An existing
    file that cannot be read as ``key: value`` pairs is not overwritten: a
    :class:`UserConfigError` names it. Values must be plain YAML (strings,
    numbers, lists and mappings), so the file can always be read back.
    """
    import yaml  # type: ignore[import-untyped]

    path = USER_CONFIG_PATH
    if path.exists():
        _, problem = _parse_user_config(path)
        if problem is not None:
            raise _unusable(path, problem, "it was left unchanged")
    write_private_text(path, yaml.safe_dump(dict(config), default_flow_style=False, allow_unicode=True))


def set_user_config_value(key: str, value: str) -> None:
    """Set a single key in the user config file, keeping the other values.

    Raises :class:`UserConfigError`, and leaves the file as it is, when the
    existing file cannot be read as ``key: value`` pairs.
    """
    if key not in _USER_CONFIG_KEYS:
        raise ValueError(f"Unknown config key {key!r}. Valid keys: {sorted(_USER_CONFIG_KEYS)}")
    path = USER_CONFIG_PATH
    config: dict[str, Any] = {}
    if path.exists():
        config, problem = _parse_user_config(path)
        if problem is not None:
            raise _unusable(path, problem, f"{key} was not saved and the file was left unchanged")
    config[key] = value
    save_user_config(config)


def get_user_config_value(key: str) -> str | None:
    """Get a single key from the user config file.

    A file that cannot be read gives a warning, as :func:`load_user_config` does, and no value.
    """
    return load_user_config().get(key)


def _is_secret_key(name: object) -> bool:
    """Whether a config key holds a secret (a token, key, password or secret), judged by its name."""
    text = str(name)
    if any(marker in text.lower() for marker in _SECRET_MARKERS):
        return True
    words = re.findall(r"[a-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).lower())
    return "key" in words


def _masked(value: object) -> str:
    """``value`` with all but its last four characters hidden.

    A value shorter than 12 characters is hidden entirely: its last four would
    give away too much of it.
    """
    text = str(value)
    return "****" + text[-4:] if len(text) >= 12 else "****"


def _shown_value(key: object, value: object) -> str:
    """A config value as ``battinfo config show`` prints it: masked when the key names a secret."""
    if value is None or value == "" or not _is_secret_key(key):
        return str(value)
    return _masked(value)


def resolve_creators(cli_creators: list[str] | None) -> list[dict[str, str]]:
    """Parse CLI --creator strings, falling back to config file if none given.

    Each entry is ``"Family, Given"`` or ``"Family, Given; Affiliation"``.
    """
    raw: list[str] = []
    if cli_creators:
        raw = list(cli_creators)
    else:
        stored = get_user_config_value("creator")
        if stored:
            raw = [s.strip() for s in stored.split("|") if s.strip()]

    creators = []
    for entry in raw:
        if ";" in entry:
            name, affiliation = entry.split(";", 1)
            creators.append({"name": name.strip(), "affiliation": affiliation.strip()})
        else:
            creators.append({"name": entry.strip()})
    return creators


def resolve_zenodo_token(cli_token: str | None = None) -> str | None:
    """Return Zenodo token from CLI arg → config file → ZENODO_API_TOKEN env var."""
    if cli_token and cli_token.strip():
        return cli_token.strip()
    stored = get_user_config_value("zenodo_token")
    if stored:
        return stored.strip()
    env = os.environ.get("ZENODO_API_TOKEN", "").strip()
    return env or None


@dataclass(frozen=True)
class DestinationConfig:
    name: str
    mode: str
    registry_base_url: str | None = None
    api_key: str | None = None
    api_key_header: str = "X-Battinfo-API-Key"
    platform_base_url: str | None = None
    workspace_id: str | None = None
    publisher_id: str | None = None
    source_version: str | None = None


def resolve_destination_config(
    destination: str,
    *,
    registry_base_url: str | None = None,
    api_key: str | None = None,
    api_key_header: str | None = None,
    platform_base_url: str | None = None,
    workspace_id: str | None = None,
    publisher_id: str | None = None,
    source_version: str | None = None,
) -> DestinationConfig:
    normalized = destination.strip().lower().replace("_", "-")
    if normalized not in {"local", "registry", "battery-genome", "staging", "production"}:
        raise ValueError("destination must be one of: local, registry, battery-genome, staging, production")

    if normalized == "local":
        return DestinationConfig(
            name="local",
            mode="local",
            workspace_id=workspace_id,
            publisher_id=publisher_id,
            source_version=source_version,
        )

    if normalized == "registry":
        env_prefix = "BATTINFO"
        mode = "registry"
    elif normalized == "battery-genome":
        env_prefix = "BATTINFO"
        mode = "battery-genome"
    elif normalized == "staging":
        env_prefix = "BATTINFO_STAGING"
        mode = "battery-genome"
    else:
        env_prefix = "BATTINFO_PRODUCTION"
        mode = "battery-genome"

    resolved_registry_base_url = registry_base_url or _env(f"{env_prefix}_REGISTRY_URL")
    resolved_api_key = api_key or _env(f"{env_prefix}_API_KEY")
    resolved_api_key_header = api_key_header or _env(f"{env_prefix}_API_KEY_HEADER") or "X-Battinfo-API-Key"
    resolved_workspace_id = workspace_id or _env(f"{env_prefix}_WORKSPACE_ID") or _env(f"{env_prefix}_PROJECT_ID")
    resolved_publisher_id = publisher_id or _env(f"{env_prefix}_PUBLISHER_ID")
    resolved_source_version = source_version or _env(f"{env_prefix}_SOURCE_VERSION")

    if mode == "battery-genome":
        if normalized == "battery-genome":
            resolved_platform_base_url = platform_base_url or _env("BATTERY_GENOME_PLATFORM_URL")
        elif normalized == "staging":
            resolved_platform_base_url = platform_base_url or _env("BATTERY_GENOME_STAGING_PLATFORM_URL")
        else:
            resolved_platform_base_url = platform_base_url or _env("BATTERY_GENOME_PRODUCTION_PLATFORM_URL")
    else:
        resolved_platform_base_url = platform_base_url

    return DestinationConfig(
        name=normalized,
        mode=mode,
        registry_base_url=resolved_registry_base_url,
        api_key=resolved_api_key,
        api_key_header=resolved_api_key_header,
        platform_base_url=resolved_platform_base_url,
        workspace_id=resolved_workspace_id,
        publisher_id=resolved_publisher_id,
        source_version=resolved_source_version,
    )


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


__all__ = ["DestinationConfig", "resolve_destination_config"]
