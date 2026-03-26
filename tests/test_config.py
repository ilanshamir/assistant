"""Tests for config manager."""

import json
from pathlib import Path

from aa.config import AppConfig


class TestConfigDefaults:
    def test_default_data_dir(self):
        cfg = AppConfig()
        assert cfg.data_dir == Path.home() / ".assistant"

    def test_default_poll_intervals(self):
        cfg = AppConfig()
        assert cfg.poll_interval_email == 60
        assert cfg.poll_interval_slack == 30
        assert cfg.poll_interval_calendar == 300
        assert cfg.poll_interval_mattermost == 30
        assert cfg.poll_interval_files == 120

    def test_default_notification_threshold(self):
        cfg = AppConfig()
        assert cfg.notification_threshold == 2

    def test_default_anthropic_api_key_is_none(self):
        cfg = AppConfig()
        assert cfg.anthropic_api_key is None

    def test_default_anthropic_model(self):
        cfg = AppConfig()
        assert cfg.anthropic_model == "claude-sonnet-4-20250514"

    def test_default_sources_empty_dict(self):
        cfg = AppConfig()
        assert cfg.sources == {}

    def test_web_config_defaults(self):
        cfg = AppConfig()
        assert cfg.web_enabled is False
        assert cfg.web_port == 8080


class TestConfigProperties:
    def test_db_path(self):
        cfg = AppConfig()
        assert cfg.db_path == cfg.data_dir / "aa.db"

    def test_socket_path(self):
        cfg = AppConfig()
        assert cfg.socket_path == cfg.data_dir / "assistant.sock"

    def test_log_dir(self):
        cfg = AppConfig()
        assert cfg.log_dir == cfg.data_dir / "logs"

    def test_properties_with_custom_data_dir(self, tmp_path):
        cfg = AppConfig(data_dir=tmp_path / "custom")
        assert cfg.db_path == tmp_path / "custom" / "aa.db"
        assert cfg.socket_path == tmp_path / "custom" / "assistant.sock"
        assert cfg.log_dir == tmp_path / "custom" / "logs"


class TestConfigFromFile:
    def test_from_file_overrides_defaults(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "poll_interval_email": 120,
            "notification_threshold": 5,
            "poll_interval_files": 60,
        }))
        cfg = AppConfig.from_file(config_file)
        assert cfg.poll_interval_email == 120
        assert cfg.notification_threshold == 5
        assert cfg.poll_interval_files == 60
        # defaults preserved
        assert cfg.poll_interval_slack == 30

    def test_from_file_with_data_dir(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "data_dir": str(tmp_path / "mydata"),
        }))
        cfg = AppConfig.from_file(config_file)
        assert cfg.data_dir == tmp_path / "mydata"

    def test_from_file_with_sources(self, tmp_path):
        config_file = tmp_path / "config.json"
        sources = {"gmail": {"credentials": "/path/to/creds.json"}}
        config_file.write_text(json.dumps({"sources": sources}))
        cfg = AppConfig.from_file(config_file)
        assert cfg.sources == sources


class TestConfigSources:
    def test_sources_dict_works(self):
        sources = {"slack": {"token": "xoxb-123"}, "gmail": {"creds": "path"}}
        cfg = AppConfig(sources=sources)
        assert cfg.sources["slack"]["token"] == "xoxb-123"
        assert "gmail" in cfg.sources


class TestConfigEnsureDirs:
    def test_ensure_dirs_creates_directories(self, tmp_path):
        cfg = AppConfig(data_dir=tmp_path / "newdir")
        assert not cfg.data_dir.exists()
        cfg.ensure_dirs()
        assert cfg.data_dir.exists()
        assert cfg.log_dir.exists()


class TestConfigSave:
    def test_save_to_default_path(self, tmp_path):
        cfg = AppConfig(data_dir=tmp_path, poll_interval_email=120)
        cfg.ensure_dirs()
        cfg.save()
        saved = json.loads((tmp_path / "config.json").read_text())
        assert saved["poll_interval_email"] == 120

    def test_save_to_custom_path(self, tmp_path):
        cfg = AppConfig(data_dir=tmp_path)
        out = tmp_path / "custom.json"
        cfg.save(out)
        assert out.exists()
        saved = json.loads(out.read_text())
        assert saved["data_dir"] == str(tmp_path)

    def test_save_excludes_api_key(self, tmp_path):
        cfg = AppConfig(data_dir=tmp_path, anthropic_api_key="sk-secret")
        cfg.save(tmp_path / "config.json")
        saved = json.loads((tmp_path / "config.json").read_text())
        assert "anthropic_api_key" not in saved
