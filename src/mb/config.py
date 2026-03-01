"""Load/save ~/.config/mb/config.toml; env var fallback."""

import os
import tomllib
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "mb"
CONFIG_FILE = CONFIG_DIR / "config.toml"


def _load_config_file() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, "rb") as f:
        return tomllib.load(f)


def get_token() -> str | None:
    """Return token from MB_TOKEN env var or config file."""
    token = os.environ.get("MB_TOKEN")
    if token:
        return token
    return _load_config_file().get("token")


def get_username() -> str | None:
    """Return cached username from config file."""
    return _load_config_file().get("username")


def save_config(token: str, username: str | None = None) -> None:
    """Write token (and optional username) to config file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f'token = "{token}"']
    if username:
        lines.append(f'username = "{username}"')
    CONFIG_FILE.write_text("\n".join(lines) + "\n")
