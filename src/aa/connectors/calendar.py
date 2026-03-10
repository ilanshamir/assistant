"""Google Calendar and Outlook Calendar connectors."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from aa.connectors.base import BaseConnector

GRAPH_CALENDARVIEW_ENDPOINT = (
    "https://graph.microsoft.com/v1.0/me/calendarview"
)


class GoogleCalendarConnector(BaseConnector):
    """Connector for Google Calendar via the Google API (Resilio source)."""

    source_name = "resilio"

    def __init__(self, service=None) -> None:
        self.service = service

    async def authenticate(self) -> None:
        """No-op — authentication is shared from Gmail connector."""

    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        """Fetch events for next 7 days from primary calendar.

        Args:
            cursor: Optional page token for pagination.

        Returns:
            Tuple of (list of item dicts, next page token or None).
        """
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=7)

        kwargs: dict = {
            "calendarId": "primary",
            "timeMin": now.isoformat(),
            "timeMax": time_max.isoformat(),
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if cursor:
            kwargs["pageToken"] = cursor

        response = self.service.events().list(**kwargs).execute()
        events = response.get("items", [])
        next_cursor = response.get("nextPageToken")

        items = [self._parse_event(event) for event in events]
        return items, next_cursor

    def _parse_event(self, event: dict) -> dict:
        """Convert a Google Calendar API event to a standard item dict."""
        organizer = event.get("organizer", {})
        from_name = organizer.get("displayName") or organizer.get("email", "")

        start = event.get("start", {})
        timestamp = start.get("dateTime") or start.get("date", "")

        return {
            "id": f"gcal-{event['id']}",
            "type": "calendar_event",
            "from_name": from_name,
            "subject": event.get("summary", ""),
            "body": event.get("description", ""),
            "timestamp": timestamp,
        }


class OutlookCalendarConnector(BaseConnector):
    """Connector for Outlook Calendar via Microsoft Graph API."""

    def __init__(self, source_name: str, token: str | None = None) -> None:
        self.source_name = source_name
        self._access_token = token

    async def authenticate(self) -> None:
        """No-op — authentication is shared from Outlook mail connector."""

    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        """Fetch calendar events for next 7 days using Microsoft Graph.

        Args:
            cursor: Optional OData next link for pagination.

        Returns:
            Tuple of (list of item dicts, next cursor or None).
        """
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=7)

        params: dict[str, str] = {
            "startDateTime": now.isoformat(),
            "endDateTime": time_max.isoformat(),
            "$orderby": "start/dateTime",
            "$top": "50",
        }

        headers = {
            "Authorization": f"Bearer {self._access_token}",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                GRAPH_CALENDARVIEW_ENDPOINT,
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            data = response.json()

        events = data.get("value", [])
        next_cursor = data.get("@odata.nextLink")

        items = [self._parse_event(event) for event in events]
        return items, next_cursor

    def _parse_event(self, event: dict) -> dict:
        """Convert a Microsoft Graph calendar event to a standard item dict."""
        organizer = event.get("organizer", {}).get("emailAddress", {})

        return {
            "id": f"{self.source_name}-cal-{event['id']}",
            "type": "calendar_event",
            "from_name": organizer.get("name", ""),
            "subject": event.get("subject", ""),
            "timestamp": event.get("start", {}).get("dateTime", ""),
        }
