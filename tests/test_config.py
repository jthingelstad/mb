"""Tests for configuration loading and saving."""

import os
from pathlib import Path
from unittest.mock import patch

from mb.config import get_token, get_username, get_checkpoint, save_checkpoint, save_config


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


class TestCheckpoint:
    def test_get_checkpoint_returns_none_when_missing(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text('[default]\ntoken = "t"\n')
        with patch("mb.config.CONFIG_FILE", config_dir / "config.toml"):
            assert get_checkpoint() is None

    def test_get_checkpoint_returns_int(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        (config_dir / "config.toml").write_text('[default]\ntoken = "t"\ncheckpoint = 85444200\n')
        with patch("mb.config.CONFIG_FILE", config_dir / "config.toml"):
            assert get_checkpoint() == 85444200

    def test_save_checkpoint(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "t"\nusername = "testuser"\n')
        with patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            save_checkpoint(85444200)
            assert get_checkpoint() == 85444200
            # Token should still be present
            content = config_file.read_text()
            assert "token" in content

    def test_save_checkpoint_named_profile(self, tmp_path):
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('[default]\ntoken = "t"\n\n[work]\ntoken = "w"\n')
        with patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            save_checkpoint(12345, profile="work")
            assert get_checkpoint(profile="work") == 12345
            assert get_checkpoint(profile="default") is None
