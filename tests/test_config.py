"""Tests for configuration loading and saving."""

import os
from pathlib import Path
from unittest.mock import patch

from mb.config import get_token, get_username, save_config


class TestGetToken:
    def test_env_var_takes_precedence(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text('token = "file-token"\n')

        monkeypatch.setenv("MB_TOKEN", "env-token")
        with patch("mb.config.CONFIG_FILE", config_dir / "config.toml"):
            assert get_token() == "env-token"

    def test_falls_back_to_file(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text('token = "file-token"\n')

        monkeypatch.delenv("MB_TOKEN", raising=False)
        with patch("mb.config.CONFIG_FILE", config_dir / "config.toml"):
            assert get_token() == "file-token"

    def test_returns_none_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MB_TOKEN", raising=False)
        with patch("mb.config.CONFIG_FILE", tmp_path / "nonexistent.toml"):
            assert get_token() is None


class TestSaveConfig:
    def test_creates_config_file(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_file = config_dir / "config.toml"
        with patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            save_config(token="my-token", username="testuser")
            content = config_file.read_text()
            assert 'token = "my-token"' in content
            assert 'username = "testuser"' in content


class TestGetUsername:
    def test_returns_username(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text('token = "t"\nusername = "testuser"\n')
        with patch("mb.config.CONFIG_FILE", config_dir / "config.toml"):
            assert get_username() == "testuser"
