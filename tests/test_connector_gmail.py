"""Tests for GmailConnector (Resilio)."""
from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from aa.connectors.gmail import GmailConnector


class TestParseFrom:
    """Test _parse_from extracts name and email from From header."""

    def _make_connector(self):
        conn = GmailConnector.__new__(GmailConnector)
        conn.source_name = "resilio"
        return conn

    def test_name_and_email(self):
        conn = self._make_connector()
        name, email = conn._parse_from("Alice Smith <alice@example.com>")
        assert name == "Alice Smith"
        assert email == "alice@example.com"

    def test_email_only(self):
        conn = self._make_connector()
        name, email = conn._parse_from("bob@example.com")
        assert name == ""
        assert email == "bob@example.com"

    def test_quoted_name(self):
        conn = self._make_connector()
        name, email = conn._parse_from('"Charlie D" <charlie@example.com>')
        assert name == "Charlie D"
        assert email == "charlie@example.com"


class TestExtractBody:
    """Test _extract_body decodes text/plain from payload."""

    def _make_connector(self):
        conn = GmailConnector.__new__(GmailConnector)
        conn.source_name = "resilio"
        return conn

    def test_simple_text_plain(self):
        conn = self._make_connector()
        body_text = "Hello, world!"
        encoded = base64.urlsafe_b64encode(body_text.encode()).decode()
        payload = {
            "mimeType": "text/plain",
            "body": {"data": encoded},
        }
        assert conn._extract_body(payload) == body_text

    def test_multipart_extracts_text_plain(self):
        conn = self._make_connector()
        body_text = "Plain text body"
        encoded = base64.urlsafe_b64encode(body_text.encode()).decode()
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": encoded},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": base64.urlsafe_b64encode(b"<p>HTML</p>").decode()},
                },
            ],
        }
        assert conn._extract_body(payload) == body_text

    def test_empty_payload(self):
        conn = self._make_connector()
        payload = {"mimeType": "text/plain", "body": {}}
        assert conn._extract_body(payload) == ""


class TestParseMessage:
    """Test _parse_message converts Gmail API message to standard item dict."""

    def _make_connector(self):
        conn = GmailConnector.__new__(GmailConnector)
        conn.source_name = "resilio"
        return conn

    def test_full_message(self):
        conn = self._make_connector()
        body_text = "Test email body"
        encoded_body = base64.urlsafe_b64encode(body_text.encode()).decode()
        msg = {
            "id": "abc123",
            "internalDate": "1700000000000",
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "From", "value": "Alice <alice@example.com>"},
                    {"name": "Subject", "value": "Test Subject"},
                ],
                "body": {"data": encoded_body},
            },
        }
        item = conn._parse_message(msg)
        assert item["id"] == "resilio-abc123"
        assert item["source"] == "resilio"
        assert item["source_id"] == "abc123"
        assert item["type"] == "email"
        assert item["from_name"] == "Alice"
        assert item["from_address"] == "alice@example.com"
        assert item["subject"] == "Test Subject"
        assert item["body"] == body_text
        assert item["timestamp"] == "1700000000000"


class TestFetchNewItems:
    """Test fetch_new_items with mocked Gmail service."""

    @pytest.mark.asyncio
    async def test_fetch_unread_messages(self):
        connector = GmailConnector.__new__(GmailConnector)
        connector.source_name = "resilio"

        body_text = "Hello from test"
        encoded_body = base64.urlsafe_b64encode(body_text.encode()).decode()

        # Mock service
        mock_service = MagicMock()
        connector.service = mock_service

        # messages().list() returns message ids
        mock_list = MagicMock()
        mock_list.execute.return_value = {
            "messages": [{"id": "msg1"}, {"id": "msg2"}],
            "nextPageToken": "token123",
        }
        mock_service.users().messages().list.return_value = mock_list

        # messages().get() returns full message
        def make_get_response(msg_id):
            mock_get = MagicMock()
            mock_get.execute.return_value = {
                "id": msg_id,
                "internalDate": "1700000000000",
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": f"Sender <sender@example.com>"},
                        {"name": "Subject", "value": f"Subject {msg_id}"},
                    ],
                    "body": {"data": encoded_body},
                },
            }
            return mock_get

        mock_service.users().messages().get.side_effect = (
            lambda userId, id, format: make_get_response(id)
        )

        items, cursor = await connector.fetch_new_items(cursor=None)

        assert len(items) == 2
        assert items[0]["id"] == "resilio-msg1"
        assert items[1]["id"] == "resilio-msg2"
        assert items[0]["source"] == "resilio"
        assert items[0]["type"] == "email"
        assert cursor == "token123"

    @pytest.mark.asyncio
    async def test_fetch_empty(self):
        connector = GmailConnector.__new__(GmailConnector)
        connector.source_name = "resilio"

        mock_service = MagicMock()
        connector.service = mock_service

        mock_list = MagicMock()
        mock_list.execute.return_value = {}
        mock_service.users().messages().list.return_value = mock_list

        items, cursor = await connector.fetch_new_items()
        assert items == []
        assert cursor is None


class TestAuthenticate:
    """Test authenticate with mocked Google OAuth."""

    @pytest.mark.asyncio
    async def test_authenticate_with_valid_token(self, tmp_path):
        connector = GmailConnector(
            credentials_path=str(tmp_path / "creds.json"),
            token_path=str(tmp_path / "token.json"),
        )

        mock_creds = MagicMock()
        mock_creds.valid = True

        with (
            patch("aa.connectors.gmail.Credentials.from_authorized_user_file", return_value=mock_creds),
            patch("aa.connectors.gmail.build") as mock_build,
            patch("builtins.open", MagicMock()),
            patch("os.path.exists", return_value=True),
        ):
            await connector.authenticate()
            mock_build.assert_called_once()

    @pytest.mark.asyncio
    async def test_authenticate_refreshes_expired_token(self, tmp_path):
        connector = GmailConnector(
            credentials_path=str(tmp_path / "creds.json"),
            token_path=str(tmp_path / "token.json"),
        )

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "some_refresh_token"

        with (
            patch("aa.connectors.gmail.Credentials.from_authorized_user_file", return_value=mock_creds),
            patch("aa.connectors.gmail.build") as mock_build,
            patch("aa.connectors.gmail.Request") as mock_request,
            patch("builtins.open", MagicMock()),
            patch("os.path.exists", return_value=True),
        ):
            await connector.authenticate()
            mock_creds.refresh.assert_called_once_with(mock_request())
            mock_build.assert_called_once()
