"""Configuration manager for the assistant."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class AppConfig:
    """Application configuration with sensible defaults."""

    data_dir: Path = field(default_factory=lambda: Path.home() / ".assistant")
    poll_interval_email: int = 60
    poll_interval_slack: int = 30
    poll_interval_calendar: int = 300
    poll_interval_mattermost: int = 30
    notification_threshold: int = 2
    notes_file: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    sources: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "aa.db"

    @property
    def socket_path(self) -> Path:
        return self.data_dir / "assistant.sock"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @classmethod
    def from_file(cls, path: Path | str) -> AppConfig:
        """Load config from a JSON file, applying values over defaults."""
        path = Path(path)
        with open(path) as f:
            data = json.load(f)
        if "data_dir" in data:
            data["data_dir"] = Path(data["data_dir"])
        return cls(**data)

    def ensure_dirs(self) -> None:
        """Create data_dir and log_dir if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def save(self, path: Path | str | None = None) -> None:
        """Save config to JSON. Does not save api_key to file."""
        if path is None:
            path = self.data_dir / "config.json"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = asdict(self)
        # Convert Path to string for JSON serialization
        data["data_dir"] = str(data["data_dir"])
        # Don't save api key to file
        data.pop("anthropic_api_key", None)

        with open(path, "w") as f:
            json.dump(data, f, indent=2)
