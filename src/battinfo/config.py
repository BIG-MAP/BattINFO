from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ── User preferences ──────────────────────────────────────────────────────────

USER_CONFIG_PATH = Path.home() / ".battinfo" / "config.yaml"

_USER_CONFIG_KEYS = {"creator", "license", "community", "zenodo_token"}


def load_user_config() -> dict[str, Any]:
    """Load ~/.battinfo/config.yaml, returning an empty dict if absent."""
    if not USER_CONFIG_PATH.exists():
        return {}
    try:
        import yaml  # type: ignore[import-untyped]
        text = USER_CONFIG_PATH.read_text(encoding="utf-8")
        return dict(yaml.safe_load(text) or {})
    except Exception:
        return {}


def save_user_config(config: dict[str, Any]) -> None:
    """Write the full config dict to ~/.battinfo/config.yaml."""
    import yaml  # type: ignore[import-untyped]
    USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    USER_CONFIG_PATH.write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def set_user_config_value(key: str, value: str) -> None:
    """Set a single key in the user config file."""
    if key not in _USER_CONFIG_KEYS:
        raise ValueError(f"Unknown config key {key!r}. Valid keys: {sorted(_USER_CONFIG_KEYS)}")
    cfg = load_user_config()
    cfg[key] = value
    save_user_config(cfg)


def get_user_config_value(key: str) -> str | None:
    """Get a single key from the user config file."""
    return load_user_config().get(key)


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
