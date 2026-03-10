"""Tests for Google and Outlook calendar connectors."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aa.connectors.calendar import GoogleCalendarConnector, OutlookCalendarConnector

SAMPLE_GOOGLE_EVENT = {
    "id": "evt123",
    "summary": "Team Sync",
    "description": "Weekly team sync meeting.",
    "organizer": {
        "displayName": "Alice Smith",
        "email": "alice@example.com",
    },
    "start": {
        "dateTime": "2024-11-20T10:00:00-05:00",
    },
}

SAMPLE_GOOGLE_EVENT_ALL_DAY = {
    "id": "evt456",
    "summary": "Company Holiday",
    "organizer": {
        "email": "admin@example.com",
    },
    "start": {
        "date": "2024-12-25",
    },
}

SAMPLE_OUTLOOK_EVENT = {
    "id": "AAMkABC",
    "subject": "Sprint Planning",
    "organizer": {
        "emailAddress": {
            "name": "Bob Jones",
            "address": "bob@example.com",
        }
    },
    "bodyPreview": "Let's plan the next sprint.",
    "start": {
        "dateTime": "2024-11-20T14:00:00.0000000",
        "timeZone": "UTC",
    },
}


class TestGoogleCalendarParseEvent:
    """Test GoogleCalendarConnector._parse_event."""

    def _make_connector(self):
        conn = GoogleCalendarConnector.__new__(GoogleCalendarConnector)
        conn.source_name = "resilio"
        return conn

    def test_parse_event_with_datetime(self):
        conn = self._make_connector()
        item = conn._parse_event(SAMPLE_GOOGLE_EVENT)

        assert item["id"] == "gcal-evt123"
        assert item["type"] == "calendar_event"
        assert item["from_name"] == "Alice Smith"
        assert item["subject"] == "Team Sync"
        assert item["body"] == "Weekly team sync meeting."
        assert item["timestamp"] == "2024-11-20T10:00:00-05:00"

    def test_parse_event_all_day(self):
        conn = self._make_connector()
        item = conn._parse_event(SAMPLE_GOOGLE_EVENT_ALL_DAY)

        assert item["id"] == "gcal-evt456"
        assert item["type"] == "calendar_event"
        assert item["from_name"] == "admin@example.com"
        assert item["subject"] == "Company Holiday"
        assert item["body"] == ""
        assert item["timestamp"] == "2024-12-25"

    def test_parse_event_missing_fields(self):
        conn = self._make_connector()
        event = {
            "id": "evt789",
            "organizer": {},
            "start": {},
        }
        item = conn._parse_event(event)
        assert item["id"] == "gcal-evt789"
        assert item["from_name"] == ""
        assert item["subject"] == ""
        assert item["body"] == ""
        assert item["timestamp"] == ""


class TestOutlookCalendarParseEvent:
    """Test OutlookCalendarConnector._parse_event."""

    def test_parse_event(self):
        conn = OutlookCalendarConnector(source_name="outlook_personal")
        item = conn._parse_event(SAMPLE_OUTLOOK_EVENT)

        assert item["id"] == "outlook_personal-cal-AAMkABC"
        assert item["type"] == "calendar_event"
        assert item["from_name"] == "Bob Jones"
        assert item["subject"] == "Sprint Planning"
        assert item["timestamp"] == "2024-11-20T14:00:00.0000000"

    def test_parse_event_different_source(self):
        conn = OutlookCalendarConnector(source_name="outlook_nasuni")
        item = conn._parse_event(SAMPLE_OUTLOOK_EVENT)

        assert item["id"] == "outlook_nasuni-cal-AAMkABC"

    def test_parse_event_missing_fields(self):
        conn = OutlookCalendarConnector(source_name="outlook_personal")
        event = {
            "id": "XYZ",
            "organizer": {"emailAddress": {}},
            "start": {},
        }
        item = conn._parse_event(event)
        assert item["id"] == "outlook_personal-cal-XYZ"
        assert item["from_name"] == ""
        assert item["subject"] == ""
        assert item["timestamp"] == ""


class TestGoogleCalendarFetchNewItems:
    """Test GoogleCalendarConnector.fetch_new_items with mocked service."""

    @pytest.mark.asyncio
    async def test_fetch_events(self):
        conn = GoogleCalendarConnector.__new__(GoogleCalendarConnector)
        conn.source_name = "resilio"

        mock_service = MagicMock()
        conn.service = mock_service

        mock_list = MagicMock()
        mock_list.execute.return_value = {
            "items": [SAMPLE_GOOGLE_EVENT, SAMPLE_GOOGLE_EVENT_ALL_DAY],
            "nextPageToken": "page2",
        }
        mock_service.events().list.return_value = mock_list

        items, cursor = await conn.fetch_new_items()

        assert len(items) == 2
        assert items[0]["id"] == "gcal-evt123"
        assert items[1]["id"] == "gcal-evt456"
        assert cursor == "page2"

    @pytest.mark.asyncio
    async def test_fetch_empty(self):
        conn = GoogleCalendarConnector.__new__(GoogleCalendarConnector)
        conn.source_name = "resilio"

        mock_service = MagicMock()
        conn.service = mock_service

        mock_list = MagicMock()
        mock_list.execute.return_value = {}
        mock_service.events().list.return_value = mock_list

        items, cursor = await conn.fetch_new_items()

        assert items == []
        assert cursor is None


class TestOutlookCalendarFetchNewItems:
    """Test OutlookCalendarConnector.fetch_new_items with mocked httpx."""

    @pytest.mark.asyncio
    async def test_fetch_events(self):
        conn = OutlookCalendarConnector(
            source_name="outlook_personal", token="fake-token"
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "value": [SAMPLE_OUTLOOK_EVENT],
        }

        with patch("httpx.AsyncClient") as MockClient:
            mock_client_instance = AsyncMock()
            MockClient.return_value.__aenter__ = AsyncMock(
                return_value=mock_client_instance
            )
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client_instance.get.return_value = mock_response

            items, cursor = await conn.fetch_new_items()

        assert len(items) == 1
        assert items[0]["id"] == "outlook_personal-cal-AAMkABC"
        assert cursor is None

    @pytest.mark.asyncio
    async def test_fetch_empty(self):
        conn = OutlookCalendarConnector(
            source_name="outlook_personal", token="fake-token"
        )

        mock_response = MagicMock()
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
