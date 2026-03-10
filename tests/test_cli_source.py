"""Tests for aa source add/list/rm commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from aa.cli import main
from aa.config import AppConfig


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_config(tmp_path):
    """Return an AppConfig pointing at a temp directory."""
    cfg = AppConfig(data_dir=tmp_path / ".assistant")
    cfg.ensure_dirs()
    cfg.save()
    return cfg


@pytest.fixture
def patched_config(tmp_config):
    """Patch the module-level _config in cli.py to use tmp_config."""
    with patch("aa.cli._config", tmp_config):
        yield tmp_config


# ---------------------------------------------------------------------------
# source add
# ---------------------------------------------------------------------------


class TestSourceAdd:
    def test_add_gmail_source(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "resilio",
            "--type", "gmail",
            "--credentials-file", "/path/to/client_secret.json",
        ])
        assert result.exit_code == 0, result.output
        assert "resilio" in result.output

        # Verify config was saved
        cfg = AppConfig.from_file(patched_config.data_dir / "config.json")
        src = cfg.sources["resilio"]
        assert src["type"] == "gmail"
        assert src["credentials_file"] == "/path/to/client_secret.json"
        assert src["enabled"] is True
        assert "token_path" in src

    def test_add_outlook_source_defaults(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "outlook_personal",
            "--type", "outlook",
            "--client-id", "abc123",
        ])
        assert result.exit_code == 0, result.output
        assert "outlook_personal" in result.output

        cfg = AppConfig.from_file(patched_config.data_dir / "config.json")
        src = cfg.sources["outlook_personal"]
        assert src["type"] == "outlook"
        assert src["client_id"] == "abc123"
        assert src["tenant_id"] == "common"
        assert src["enabled"] is True

    def test_add_outlook_source_with_tenant(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "outlook_nasuni",
            "--type", "outlook",
            "--client-id", "abc123",
            "--tenant-id", "nasuni-tenant-id",
        ])
        assert result.exit_code == 0, result.output

        cfg = AppConfig.from_file(patched_config.data_dir / "config.json")
        src = cfg.sources["outlook_nasuni"]
        assert src["tenant_id"] == "nasuni-tenant-id"

    def test_add_slack_source(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "slack_work",
            "--type", "slack",
            "--token", "xoxb-my-token",
        ])
        assert result.exit_code == 0, result.output

        cfg = AppConfig.from_file(patched_config.data_dir / "config.json")
        src = cfg.sources["slack_work"]
        assert src["type"] == "slack"
        assert src["token"] == "xoxb-my-token"
        assert src["enabled"] is True

    def test_add_slack_source_with_channels(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "slack_work",
            "--type", "slack",
            "--token", "xoxb-my-token",
            "--channels", "C123,C456",
        ])
        assert result.exit_code == 0, result.output

        cfg = AppConfig.from_file(patched_config.data_dir / "config.json")
        src = cfg.sources["slack_work"]
        assert src["watched_channels"] == ["C123", "C456"]

    def test_add_mattermost_source(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "mm_work",
            "--type", "mattermost",
            "--url", "https://mm.company.com",
            "--token", "my-mm-token",
        ])
        assert result.exit_code == 0, result.output

        cfg = AppConfig.from_file(patched_config.data_dir / "config.json")
        src = cfg.sources["mm_work"]
        assert src["type"] == "mattermost"
        assert src["url"] == "https://mm.company.com"
        assert src["token"] == "my-mm-token"
        assert src["enabled"] is True

    def test_add_mattermost_source_with_channels(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "mm_work",
            "--type", "mattermost",
            "--url", "https://mm.company.com",
            "--token", "my-mm-token",
            "--channels", "ch1,ch2",
        ])
        assert result.exit_code == 0, result.output

        cfg = AppConfig.from_file(patched_config.data_dir / "config.json")
        assert cfg.sources["mm_work"]["watched_channels"] == ["ch1", "ch2"]

    def test_add_gmail_missing_credentials_file(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "resilio",
            "--type", "gmail",
        ])
        assert result.exit_code != 0
        assert "credentials-file" in result.output.lower() or "required" in result.output.lower()

    def test_add_outlook_missing_client_id(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "outlook_personal",
            "--type", "outlook",
        ])
        assert result.exit_code != 0
        assert "client-id" in result.output.lower() or "required" in result.output.lower()

    def test_add_slack_missing_token(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "slack_work",
            "--type", "slack",
        ])
        assert result.exit_code != 0
        assert "token" in result.output.lower() or "required" in result.output.lower()

    def test_add_mattermost_missing_url(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "mm",
            "--type", "mattermost",
            "--token", "tok",
        ])
        assert result.exit_code != 0
        assert "url" in result.output.lower() or "required" in result.output.lower()

    def test_add_mattermost_missing_token(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "mm",
            "--type", "mattermost",
            "--url", "https://mm.example.com",
        ])
        assert result.exit_code != 0
        assert "token" in result.output.lower() or "required" in result.output.lower()

    def test_add_unknown_type(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "foo",
            "--type", "unknown_type",
        ])
        assert result.exit_code != 0

    def test_add_creates_credentials_dir(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "resilio",
            "--type", "gmail",
            "--credentials-file", "/path/to/creds.json",
        ])
        assert result.exit_code == 0
        assert patched_config.credentials_dir.is_dir()


# ---------------------------------------------------------------------------
# source list
# ---------------------------------------------------------------------------


class TestSourceList:
    def test_list_empty(self, runner, patched_config):
        result = runner.invoke(main, ["source", "list"])
        assert result.exit_code == 0
        assert "no sources" in result.output.lower()

    def test_list_shows_configured_sources(self, runner, patched_config):
        # Add two sources first
        runner.invoke(main, [
            "source", "add", "slack_work",
            "--type", "slack",
            "--token", "xoxb-tok",
        ])
        runner.invoke(main, [
            "source", "add", "mm",
            "--type", "mattermost",
            "--url", "https://mm.co",
            "--token", "tok",
        ])

        result = runner.invoke(main, ["source", "list"])
        assert result.exit_code == 0
        assert "slack_work" in result.output
        assert "slack" in result.output
        assert "mm" in result.output
        assert "mattermost" in result.output
        assert "enabled" in result.output


# ---------------------------------------------------------------------------
# source rm
# ---------------------------------------------------------------------------


class TestSourceRm:
    def test_rm_existing_source(self, runner, patched_config):
        # Add then remove
        runner.invoke(main, [
            "source", "add", "slack_work",
            "--type", "slack",
            "--token", "xoxb-tok",
        ])
        result = runner.invoke(main, ["source", "rm", "slack_work"])
        assert result.exit_code == 0
        assert "removed" in result.output.lower()

        cfg = AppConfig.from_file(patched_config.data_dir / "config.json")
        assert "slack_work" not in cfg.sources

    def test_rm_nonexistent_source(self, runner, patched_config):
        result = runner.invoke(main, ["source", "rm", "nope"])
        assert result.exit_code != 0 or "not found" in result.output.lower()

    def test_rm_deletes_credential_file(self, runner, patched_config):
        # Add a gmail source, create a fake token file, then rm
        runner.invoke(main, [
            "source", "add", "resilio",
            "--type", "gmail",
            "--credentials-file", "/path/to/creds.json",
        ])
        # Create the token file that would exist
        cfg = AppConfig.from_file(patched_config.data_dir / "config.json")
        token_path = Path(cfg.sources["resilio"]["token_path"]).expanduser()
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("{}")

        result = runner.invoke(main, ["source", "rm", "resilio"])
        assert result.exit_code == 0
        assert not token_path.exists()


# ---------------------------------------------------------------------------
# config.credentials_dir
# ---------------------------------------------------------------------------


class TestCredentialsDir:
    def test_credentials_dir_property(self):
        cfg = AppConfig()
        assert cfg.credentials_dir == cfg.data_dir / "credentials"

    def test_ensure_dirs_creates_credentials_dir(self, tmp_path):
        cfg = AppConfig(data_dir=tmp_path / "newdir")
        cfg.ensure_dirs()
        assert cfg.credentials_dir.is_dir()
