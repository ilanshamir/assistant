"""Outlook connector using Microsoft Graph API and MSAL."""
from __future__ import annotations

import json
import os

import httpx
import msal

from aa.connectors.base import BaseConnector

GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0/me/messages"
SCOPES = ["Mail.Read"]


class OutlookConnector(BaseConnector):
    """Connector for Outlook email via Microsoft Graph API."""

    def __init__(
        self,
        source_name: str,
        client_id: str,
        tenant_id: str = "common",
        token_cache_path: str | None = None,
    ) -> None:
        self.source_name = source_name
        self.client_id = client_id
        self.tenant_id = tenant_id
        self.token_cache_path = token_cache_path
        self._access_token: str | None = None

    async def authenticate(self) -> None:
        """Authenticate using MSAL with interactive/silent token acquisition.

        Stores token cache to file if token_cache_path is set.
        """
        cache = msal.SerializableTokenCache()
        if self.token_cache_path and os.path.exists(self.token_cache_path):
            with open(self.token_cache_path) as f:
                cache.deserialize(f.read())

        app = msal.PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            token_cache=cache,
        )

        accounts = app.get_accounts()
        result = None

        if accounts:
            result = app.acquire_token_silent(SCOPES, account=accounts[0])

        if not result or "access_token" not in result:
            result = app.acquire_token_interactive(scopes=SCOPES)

        self._access_token = result["access_token"]

        if self.token_cache_path and cache.has_state_changed:
            with open(self.token_cache_path, "w") as f:
                f.write(cache.serialize())

    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        """Fetch unread emails via Microsoft Graph API.

        Args:
            cursor: Optional receivedDateTime ISO string to filter messages
                received after that time.

        Returns:
            Tuple of (list of item dicts, next cursor or None).
        """
        params: dict[str, str] = {
            "$filter": "isRead eq false",
            "$orderby": "receivedDateTime desc",
            "$top": "50",
        }

        if cursor:
            params["$filter"] = (
                f"isRead eq false and receivedDateTime gt {cursor}"
            )

        headers = {
            "Authorization": f"Bearer {self._access_token}",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                GRAPH_ENDPOINT, headers=headers, params=params
            )
            response.raise_for_status()
            data = response.json()

        messages = data.get("value", [])
        next_cursor = data.get("@odata.nextLink")

        items = self._parse_messages(messages)
        return items, next_cursor

    def _parse_messages(self, messages: list[dict]) -> list[dict]:
        """Convert Graph API message list to standard item dicts.

        Args:
            messages: List of message dicts from Graph API.

        Returns:
            List of standardised item dicts.
        """
        items: list[dict] = []
        for msg in messages:
            email_address = msg.get("from", {}).get("emailAddress", {})
            items.append(
                {
                    "id": f"{self.source_name}-{msg['id']}",
                    "source": self.source_name,
                    "type": "email",
                    "from_name": email_address.get("name", ""),
                    "from_address": email_address.get("address", ""),
                    "subject": msg.get("subject", ""),
                    "body": msg.get("body", {}).get("content", ""),
                    "timestamp": msg.get("receivedDateTime", ""),
                }
            )
        return items
