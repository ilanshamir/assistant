"""Tests for OutlookConnector."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aa.connectors.outlook import OutlookConnector

SAMPLE_MESSAGES = [
    {
        "id": "AAMkAGI2",
        "subject": "Team standup notes",
        "from": {
            "emailAddress": {
                "name": "Alice Smith",
                "address": "alice@example.com",
            }
        },
        "body": {"content": "Here are today's standup notes."},
        "receivedDateTime": "2024-11-15T10:30:00Z",
        "isRead": False,
    },
    {
        "id": "BBNlBHJ3",
        "subject": "Quarterly review",
        "from": {
            "emailAddress": {
                "name": "Bob Jones",
                "address": "bob@example.com",
            }
        },
        "body": {"content": "Please review the attached document."},
        "receivedDateTime": "2024-11-15T11:00:00Z",
        "isRead": False,
    },
]


class TestParseMessages:
    """Test _parse_messages converts Graph API messages to standard items."""

    def test_parse_two_messages(self):
        conn = OutlookConnector(
            source_name="outlook_personal",
            client_id="fake-client-id",
        )
        items = conn._parse_messages(SAMPLE_MESSAGES)

        assert len(items) == 2

        item0 = items[0]
        assert item0["id"] == "outlook_personal-AAMkAGI2"
        assert item0["source"] == "outlook_personal"
        assert item0["type"] == "email"
        assert item0["from_name"] == "Alice Smith"
        assert item0["from_address"] == "alice@example.com"
        assert item0["subject"] == "Team standup notes"
        assert item0["body"] == "Here are today's standup notes."
        assert item0["timestamp"] == "2024-11-15T10:30:00Z"

        item1 = items[1]
        assert item1["id"] == "outlook_personal-BBNlBHJ3"
        assert item1["from_name"] == "Bob Jones"
        assert item1["from_address"] == "bob@example.com"

    def test_parse_empty_list(self):
        conn = OutlookConnector(
            source_name="outlook_nasuni",
            client_id="fake-client-id",
        )
        items = conn._parse_messages([])
        assert items == []

    def test_different_source_name(self):
        conn = OutlookConnector(
            source_name="outlook_nasuni",
            client_id="fake-client-id",
        )
        items = conn._parse_messages(SAMPLE_MESSAGES[:1])
        assert items[0]["id"] == "outlook_nasuni-AAMkAGI2"
        assert items[0]["source"] == "outlook_nasuni"


class TestFetchNewItems:
    """Test fetch_new_items with mocked httpx response."""

    @pytest.mark.asyncio
    async def test_fetch_unread_no_cursor(self):
        conn = OutlookConnector(
            source_name="outlook_personal",
            client_id="fake-client-id",
        )
        conn._access_token = "fake-token"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "value": SAMPLE_MESSAGES,
        }

        with patch("httpx.AsyncClient") as MockClient:
            mock_client_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(
                return_value=mock_client_instance
            )
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client_instance.get.return_value = mock_response

            items, cursor = await conn.fetch_new_items()

        assert len(items) == 2
        assert items[0]["id"] == "outlook_personal-AAMkAGI2"
        assert items[1]["id"] == "outlook_personal-BBNlBHJ3"
        # No @odata.nextLink means cursor is None
        assert cursor is None

        # Verify the URL used
        call_args = mock_client_instance.get.call_args
        url = call_args[0][0]
        assert "graph.microsoft.com" in url
        assert "messages" in url

    @pytest.mark.asyncio
    async def test_fetch_with_cursor(self):
        conn = OutlookConnector(
            source_name="outlook_personal",
            client_id="fake-client-id",
        )
        conn._access_token = "fake-token"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "value": SAMPLE_MESSAGES[:1],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=10",
        }

        with patch("httpx.AsyncClient") as MockClient:
            mock_client_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(
                return_value=mock_client_instance
            )
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client_instance.get.return_value = mock_response

            items, cursor = await conn.fetch_new_items(
                cursor="2024-11-15T10:00:00Z"
            )

        assert len(items) == 1
        assert cursor == "https://graph.microsoft.com/v1.0/me/messages?$skip=10"

        # Verify filter includes receivedDateTime
        call_args = mock_client_instance.get.call_args
        params = call_args[1].get("params", {})
        assert "receivedDateTime" in params.get("$filter", "")

    @pytest.mark.asyncio
    async def test_fetch_empty(self):
        conn = OutlookConnector(
            source_name="outlook_personal",
            client_id="fake-client-id",
        )
        conn._access_token = "fake-token"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"value": []}

        with patch("httpx.AsyncClient") as MockClient:
            mock_client_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(
                return_value=mock_client_instance
            )
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client_instance.get.return_value = mock_response

            items, cursor = await conn.fetch_new_items()

        assert items == []
        assert cursor is None


class TestAuthenticate:
    """Test authenticate with mocked MSAL."""

    @pytest.mark.asyncio
    async def test_authenticate_interactive(self, tmp_path):
        token_cache_path = str(tmp_path / "token_cache.bin")
        conn = OutlookConnector(
            source_name="outlook_personal",
            client_id="fake-client-id",
            token_cache_path=token_cache_path,
        )

        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_app.acquire_token_interactive.return_value = {
            "access_token": "new-access-token",
        }

        with patch("msal.PublicClientApplication", return_value=mock_app):
            await conn.authenticate()

        assert conn._access_token == "new-access-token"
        mock_app.acquire_token_interactive.assert_called_once()

    @pytest.mark.asyncio
    async def test_authenticate_silent(self, tmp_path):
        token_cache_path = str(tmp_path / "token_cache.bin")
        conn = OutlookConnector(
            source_name="outlook_personal",
            client_id="fake-client-id",
            token_cache_path=token_cache_path,
        )

        mock_account = {"username": "user@example.com"}
        mock_app = MagicMock()
        mock_app.get_accounts.return_value = [mock_account]
        mock_app.acquire_token_silent.return_value = {
            "access_token": "cached-access-token",
        }

        with patch("msal.PublicClientApplication", return_value=mock_app):
            await conn.authenticate()

        assert conn._access_token == "cached-access-token"
        mock_app.acquire_token_silent.assert_called_once()
        mock_app.acquire_token_interactive.assert_not_called()
