"""Tests for BaseConnector abstract base class."""
from __future__ import annotations

import pytest

from aa.connectors.base import BaseConnector


class TestBaseConnectorCannotBeInstantiated:
    def test_direct_instantiation_raises(self):
        with pytest.raises(TypeError):
            BaseConnector()


class TestMockSubclass:
    """A concrete subclass should work when all abstract methods are implemented."""

    def _make_connector(self):
        class FakeConnector(BaseConnector):
            source_name = "fake"

            async def authenticate(self):
                return "authenticated"

            async def fetch_new_items(self, cursor: str | None = None) -> tuple[list[dict], str | None]:
                items = [{"id": "1", "text": "hello"}]
                next_cursor = "cursor_abc"
                return items, next_cursor

        return FakeConnector()

    def test_subclass_instantiation(self):
        conn = self._make_connector()
        assert isinstance(conn, BaseConnector)

    def test_source_name(self):
        conn = self._make_connector()
        assert conn.source_name == "fake"

    @pytest.mark.asyncio
    async def test_authenticate(self):
        conn = self._make_connector()
        result = await conn.authenticate()
        assert result == "authenticated"

    @pytest.mark.asyncio
    async def test_fetch_new_items(self):
        conn = self._make_connector()
        items, cursor = await conn.fetch_new_items()
        assert len(items) == 1
        assert items[0]["id"] == "1"
        assert cursor == "cursor_abc"

    @pytest.mark.asyncio
    async def test_fetch_new_items_with_cursor(self):
        conn = self._make_connector()
        items, cursor = await conn.fetch_new_items(cursor="some_cursor")
        assert isinstance(items, list)
        assert cursor is not None


class TestIncompleteSubclass:
    def test_missing_methods_raises(self):
        class IncompleteConnector(BaseConnector):
            source_name = "incomplete"

        with pytest.raises(TypeError):
            IncompleteConnector()
