"""Load/save ~/.config/mb/config.toml; env var fallback. Supports named profiles."""

import json
import os
import stat
import tomllib
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "mb"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_PROFILE = "default"


def _load_config_file() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, "rb") as f:
        return tomllib.load(f)


def _get_profile(config: dict, profile: str) -> dict:
    """Resolve a profile from config. Supports both flat (legacy) and sectioned formats."""
    # New format: profiles are TOML sections
    if profile in config and isinstance(config[profile], dict):
        return config[profile]
    # Legacy flat format: treat entire file as the default profile
    if profile == DEFAULT_PROFILE and "token" in config:
        return config
    return {}


def get_token(profile: str = DEFAULT_PROFILE) -> str | None:
    """Return token from MB_TOKEN env var or config file profile."""
    token = os.environ.get("MB_TOKEN")
    if token:
        return token
    return _get_profile(_load_config_file(), profile).get("token")


def get_username(profile: str = DEFAULT_PROFILE) -> str | None:
    """Return cached username from config file profile."""
    return _get_profile(_load_config_file(), profile).get("username")


def get_blog(profile: str = DEFAULT_PROFILE) -> str | None:
    """Return configured blog destination from config file profile."""
    blog = os.environ.get("MB_BLOG")
    if blog:
        return blog
    return _get_profile(_load_config_file(), profile).get("blog")


def list_profiles() -> list[dict]:
    """Return all configured profiles with their settings (token masked)."""
    config = _load_config_file()
    profiles = []
    # Legacy flat format
    if "token" in config and not any(isinstance(v, dict) for v in config.values()):
        profiles.append({
            "name": DEFAULT_PROFILE,
            "username": config.get("username", ""),
            "blog": config.get("blog", ""),
        })
        return profiles
    # Sectioned format
    for name, section in config.items():
        if isinstance(section, dict) and "token" in section:
            profiles.append({
                "name": name,
                "username": section.get("username", ""),
                "blog": section.get("blog", ""),
            })
    return profiles


def get_checkpoint(profile: str = DEFAULT_PROFILE) -> int | None:
    """Return saved timeline checkpoint ID from config file profile."""
    val = _get_profile(_load_config_file(), profile).get("checkpoint")
    return int(val) if val is not None else None


def save_checkpoint(checkpoint_id: int, profile: str = DEFAULT_PROFILE) -> None:
    """Save a timeline checkpoint ID to the config file profile."""
    save_named_checkpoint("timeline", checkpoint_id, profile=profile)


def get_named_checkpoint(name: str, profile: str = DEFAULT_PROFILE) -> int | None:
    """Return a named checkpoint ID from the config file profile."""
    key = "checkpoint" if name == "timeline" else f"{name}_checkpoint"
    val = _get_profile(_load_config_file(), profile).get(key)
    return int(val) if val is not None else None


def save_named_checkpoint(name: str, checkpoint_id: int, profile: str = DEFAULT_PROFILE) -> None:
    """Save a named checkpoint ID to the config file profile."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = _load_config_file()

    # Migrate legacy flat format if needed
    if "token" in config and not any(isinstance(v, dict) for v in config.values()):
        old = dict(config)
        config = {DEFAULT_PROFILE: old}

    if profile not in config or not isinstance(config.get(profile), dict):
        config[profile] = {}

    key = "checkpoint" if name == "timeline" else f"{name}_checkpoint"
    config[profile][key] = checkpoint_id
    _write_config(config)


def save_config(token: str, username: str | None = None,
                blog: str | None = None, profile: str = DEFAULT_PROFILE) -> None:
    """Write token (and optional username/blog) to a profile in config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = _load_config_file()

    # Migrate legacy flat format if saving to a non-default profile
    if "token" in config and not any(isinstance(v, dict) for v in config.values()):
        old = dict(config)
        config = {DEFAULT_PROFILE: old}

    # Ensure sectioned format
    if profile not in config or not isinstance(config.get(profile), dict):
        config[profile] = {}

    config[profile]["token"] = token
    if username:
        config[profile]["username"] = username
    if blog:
        config[profile]["blog"] = blog

    _write_config(config)


def _write_config(config: dict) -> None:
    """Serialize config dict to TOML and write to file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    # Check if flat format (legacy — single profile with no sections)
    if "token" in config and not any(isinstance(v, dict) for v in config.values()):
        for key, value in config.items():
            lines.append(f'{key} = {json.dumps(value)}')
    else:
        for section_name, section in config.items():
            if not isinstance(section, dict):
                continue
            lines.append(f"[{section_name}]")
            for key, value in section.items():
                lines.append(f'{key} = {json.dumps(value)}')
            lines.append("")
    CONFIG_FILE.write_text("\n".join(lines) + "\n")
    # Restrict permissions — token is sensitive
    CONFIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
