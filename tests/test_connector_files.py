"""Tests for FilesConnector."""
from __future__ import annotations

import json

import pytest

from aa.connectors.files import FilesConnector


class TestSingleFile:
    """Test FilesConnector with a single file path."""

    @pytest.mark.asyncio
    async def test_first_poll_returns_item(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello world")
        conn = FilesConnector(source_name="local", path=str(f))

        items, cursor = await conn.fetch_new_items(cursor=None)

        assert len(items) == 1
        item = items[0]
        assert item["source"] == "local"
        assert item["type"] == "notes"
        assert item["subject"] == "notes.txt"
        assert item["body"] == "hello world"
        assert item["id"].startswith("local-")
        assert cursor is not None

    @pytest.mark.asyncio
    async def test_unchanged_file_returns_empty(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello world")
        conn = FilesConnector(source_name="local", path=str(f))

        _, cursor = await conn.fetch_new_items(cursor=None)
        items, _ = await conn.fetch_new_items(cursor=cursor)

        assert items == []

    @pytest.mark.asyncio
    async def test_changed_file_detected(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello world")
        conn = FilesConnector(source_name="local", path=str(f))

        _, cursor = await conn.fetch_new_items(cursor=None)
        f.write_text("updated content")
        items, cursor2 = await conn.fetch_new_items(cursor=cursor)

        assert len(items) == 1
        assert items[0]["body"] == "updated content"
        assert cursor2 is not None
        assert cursor2 != cursor

    @pytest.mark.asyncio
    async def test_missing_file_returns_empty(self):
        conn = FilesConnector(source_name="local", path="/nonexistent/path/file.txt")

        items, cursor = await conn.fetch_new_items(cursor=None)

        assert items == []
        assert cursor is not None


class TestDirectory:
    """Test FilesConnector with a directory path."""

    @pytest.mark.asyncio
    async def test_reads_all_files_recursively(self, tmp_path):
        (tmp_path / "a.txt").write_text("aaa")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("bbb")

        conn = FilesConnector(source_name="local", path=str(tmp_path))
        items, cursor = await conn.fetch_new_items(cursor=None)

        subjects = {item["subject"] for item in items}
        assert "a.txt" in subjects
        assert "b.txt" in subjects
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_only_changed_files_returned(self, tmp_path):
        (tmp_path / "a.txt").write_text("aaa")
        (tmp_path / "b.txt").write_text("bbb")

        conn = FilesConnector(source_name="local", path=str(tmp_path))
        _, cursor = await conn.fetch_new_items(cursor=None)

        (tmp_path / "a.txt").write_text("aaa modified")
        items, _ = await conn.fetch_new_items(cursor=cursor)

        assert len(items) == 1
        assert items[0]["subject"] == "a.txt"
        assert items[0]["body"] == "aaa modified"

    @pytest.mark.asyncio
    async def test_new_file_detected(self, tmp_path):
        (tmp_path / "a.txt").write_text("aaa")

        conn = FilesConnector(source_name="local", path=str(tmp_path))
        _, cursor = await conn.fetch_new_items(cursor=None)

        (tmp_path / "c.txt").write_text("new file")
        items, _ = await conn.fetch_new_items(cursor=cursor)

        assert len(items) == 1
        assert items[0]["subject"] == "c.txt"
        assert items[0]["body"] == "new file"

    @pytest.mark.asyncio
    async def test_binary_files_skipped(self, tmp_path):
        (tmp_path / "text.txt").write_text("hello")
        (tmp_path / "image.bin").write_bytes(b"\x00\x01\x02\x03binary")

        conn = FilesConnector(source_name="local", path=str(tmp_path))
        items, _ = await conn.fetch_new_items(cursor=None)

        assert len(items) == 1
        assert items[0]["subject"] == "text.txt"

    @pytest.mark.asyncio
    async def test_empty_directory_returns_empty(self, tmp_path):
        conn = FilesConnector(source_name="local", path=str(tmp_path))
        items, cursor = await conn.fetch_new_items(cursor=None)

        assert items == []
        assert cursor is not None


class TestAuthenticate:
    """Test authenticate is a no-op."""

    @pytest.mark.asyncio
    async def test_authenticate_noop(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello")
        conn = FilesConnector(source_name="local", path=str(f))

        # Should not raise
        await conn.authenticate()
