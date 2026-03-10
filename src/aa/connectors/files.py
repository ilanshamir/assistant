"""Local files connector — polls files/directories for changes."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from aa.connectors.base import BaseConnector


class FilesConnector(BaseConnector):
    """Connector that watches local files and directories for changes."""

    source_name: str

    def __init__(self, source_name: str, path: str) -> None:
        self.source_name = source_name
        self.path = path

    async def authenticate(self) -> None:
        """No-op for local files."""

    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        """Read files, compare hashes to cursor, return changed files as items."""
        old_hashes: dict[str, str] = json.loads(cursor) if cursor else {}
        new_hashes: dict[str, str] = {}
        items: list[dict] = []

        for filepath in self._collect_files():
            content = self._read_file(filepath)
            if content is None:
                continue

            content_hash = hashlib.sha256(content.encode()).hexdigest()
            new_hashes[filepath] = content_hash

            if old_hashes.get(filepath) == content_hash:
                continue

            items.append(
                {
                    "id": f"{self.source_name}-{hashlib.sha256(filepath.encode()).hexdigest()[:8]}-{content_hash[:8]}",
                    "source": self.source_name,
                    "source_id": filepath,
                    "type": "notes",
                    "from_name": "",
                    "from_address": "",
                    "subject": os.path.basename(filepath),
                    "body": content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

        return items, json.dumps(new_hashes)

    def _collect_files(self) -> list[str]:
        """Return list of file paths to check."""
        if not os.path.exists(self.path):
            return []

        if os.path.isfile(self.path):
            return [self.path]

        files: list[str] = []
        for dirpath, _, filenames in os.walk(self.path):
            for name in filenames:
                files.append(os.path.join(dirpath, name))
        return sorted(files)

    def _read_file(self, filepath: str) -> str | None:
        """Read a file, returning None for binary or unreadable files."""
        try:
            with open(filepath, "rb") as f:
                chunk = f.read(8192)
            if b"\x00" in chunk:
                return None
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except (OSError, UnicodeDecodeError):
            return None
