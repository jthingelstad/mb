"""Load/save ~/.config/mb/config.toml; env var fallback. Supports named profiles."""

import json
import os
import re
import secrets
import tomllib
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "mb"
CONFIG_FILE = CONFIG_DIR / "config.toml"

DEFAULT_PROFILE = "default"
NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


class ConfigError(ValueError):
    """A config input or file problem, reported as a structured error; never holds a token."""


def validate_name(kind: str, name: str) -> str:
    """Profile and checkpoint names become TOML sections and keys, so keep them plain."""
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        raise ConfigError(
            f"Invalid {kind} name {json.dumps(name)}: use only letters, digits, _ and -"
        )
    return name


def default_state_path() -> Path:
    """The shared receipt and checkpoint store. MB 2.0 named it mcp-state.sqlite3;
    keep using that file when it is the only one, so no receipts are left behind."""
    current = CONFIG_DIR / "state.sqlite3"
    legacy = CONFIG_DIR / "mcp-state.sqlite3"
    return legacy if legacy.exists() and not current.exists() else current


def _load_config_file() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        # The decoder message names the line and column, never the file contents.
        raise ConfigError(f"Config file {CONFIG_FILE} is not valid TOML: {exc}") from None


def _get_profile(config: dict, profile: str) -> dict:
    """Resolve a profile from config. Supports both flat (legacy) and sectioned formats."""
    validate_name("profile", profile)
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
        profiles.append(
            {
                "name": DEFAULT_PROFILE,
                "username": config.get("username", ""),
                "blog": config.get("blog", ""),
            }
        )
        return profiles
    # Sectioned format
    for name, section in config.items():
        if isinstance(section, dict) and "token" in section:
            profiles.append(
                {
                    "name": name,
                    "username": section.get("username", ""),
                    "blog": section.get("blog", ""),
                }
            )
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
    validate_name("checkpoint", name)
    key = "checkpoint" if name == "timeline" else f"{name}_checkpoint"
    val = _get_profile(_load_config_file(), profile).get(key)
    return int(val) if val is not None else None


def list_named_checkpoints(profile: str = DEFAULT_PROFILE) -> dict[str, int]:
    """Return all saved checkpoints for a profile."""
    profile_data = _get_profile(_load_config_file(), profile)
    checkpoints = {}
    for key, value in profile_data.items():
        if key == "checkpoint":
            checkpoints["timeline"] = int(value)
        elif key.endswith("_checkpoint"):
            checkpoints[key.removesuffix("_checkpoint")] = int(value)
    return checkpoints


def save_named_checkpoint(name: str, checkpoint_id: int, profile: str = DEFAULT_PROFILE) -> None:
    """Save a named checkpoint ID to the config file profile."""
    validate_name("checkpoint", name)
    validate_name("profile", profile)
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


def clear_named_checkpoint(name: str, profile: str = DEFAULT_PROFILE) -> bool:
    """Remove one named checkpoint from the config file profile."""
    validate_name("checkpoint", name)
    config = _load_config_file()
    profile_data = _get_profile(config, profile)
    if not profile_data:
        return False
    key = "checkpoint" if name == "timeline" else f"{name}_checkpoint"
    if key not in profile_data:
        return False
    del profile_data[key]
    _write_config(config)
    return True


def clear_all_named_checkpoints(profile: str = DEFAULT_PROFILE) -> int:
    """Remove all checkpoints from the config file profile."""
    config = _load_config_file()
    profile_data = _get_profile(config, profile)
    if not profile_data:
        return 0
    keys = [key for key in profile_data if key == "checkpoint" or key.endswith("_checkpoint")]
    for key in keys:
        del profile_data[key]
    if keys:
        _write_config(config)
    return len(keys)


def save_config(
    token: str, username: str | None = None, blog: str | None = None, profile: str = DEFAULT_PROFILE
) -> None:
    """Write token (and optional username/blog) to a profile in config file."""
    validate_name("profile", profile)
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
            lines.append(f"{key} = {json.dumps(value)}")
    else:
        for section_name, section in config.items():
            if not isinstance(section, dict):
                continue
            lines.append(f"[{section_name}]")
            for key, value in section.items():
                lines.append(f"{key} = {json.dumps(value)}")
            lines.append("")
    # The token is sensitive: write a private file beside the config, then swap it in,
    # so the config is never briefly world-readable or left truncated by a crash.
    temporary = CONFIG_DIR / f".{CONFIG_FILE.name}.{secrets.token_hex(8)}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write("\n".join(lines) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, CONFIG_FILE)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
