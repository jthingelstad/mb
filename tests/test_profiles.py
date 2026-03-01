"""Tests for multi-profile configuration."""

from unittest.mock import patch

from mb.config import (
    get_token,
    get_username,
    get_blog,
    save_config,
    list_profiles,
    DEFAULT_PROFILE,
)


class TestProfileConfig:
    def test_save_and_load_default_profile(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "mb"
        config_file = config_dir / "config.toml"
        monkeypatch.delenv("MB_TOKEN", raising=False)

        with patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            save_config(token="tok-default", username="defaultuser", profile="default")
            assert get_token(profile="default") == "tok-default"
            assert get_username(profile="default") == "defaultuser"

    def test_save_and_load_named_profile(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "mb"
        config_file = config_dir / "config.toml"
        monkeypatch.delenv("MB_TOKEN", raising=False)

        with patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            save_config(token="tok-default", username="defaultuser", profile="default")
            save_config(token="tok-test", username="testuser", blog="https://test.micro.blog/", profile="test")

            assert get_token(profile="default") == "tok-default"
            assert get_token(profile="test") == "tok-test"
            assert get_blog(profile="test") == "https://test.micro.blog/"

    def test_env_var_overrides_profile(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "mb"
        config_file = config_dir / "config.toml"
        monkeypatch.setenv("MB_TOKEN", "env-token")

        with patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            save_config(token="file-token", username="fileuser", profile="default")
            assert get_token(profile="default") == "env-token"

    def test_mb_blog_env_var(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "mb"
        config_file = config_dir / "config.toml"
        monkeypatch.setenv("MB_BLOG", "https://env.micro.blog/")

        with patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            assert get_blog(profile="default") == "https://env.micro.blog/"

    def test_list_profiles(self, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "mb"
        config_file = config_dir / "config.toml"
        monkeypatch.delenv("MB_TOKEN", raising=False)

        with patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            save_config(token="tok1", username="user1", profile="default")
            save_config(token="tok2", username="user2", blog="https://b2.micro.blog/", profile="test")
            profiles = list_profiles()
            assert len(profiles) == 2
            names = [p["name"] for p in profiles]
            assert "default" in names
            assert "test" in names

    def test_legacy_flat_format_compat(self, tmp_path, monkeypatch):
        """Legacy flat config (no sections) should work as the default profile."""
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('token = "legacy-token"\nusername = "legacyuser"\n')
        monkeypatch.delenv("MB_TOKEN", raising=False)

        with patch("mb.config.CONFIG_FILE", config_file):
            assert get_token(profile="default") == "legacy-token"
            assert get_username(profile="default") == "legacyuser"

    def test_legacy_migration_on_new_profile(self, tmp_path, monkeypatch):
        """Saving a new profile should migrate legacy flat format to sections."""
        config_dir = tmp_path / ".config" / "mb"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text('token = "legacy-token"\nusername = "legacyuser"\n')
        monkeypatch.delenv("MB_TOKEN", raising=False)

        with patch("mb.config.CONFIG_DIR", config_dir), \
             patch("mb.config.CONFIG_FILE", config_file):
            save_config(token="new-token", username="newuser", profile="test")
            # Both should work now
            assert get_token(profile="default") == "legacy-token"
            assert get_token(profile="test") == "new-token"
