"""Slack connector using slack_sdk AsyncWebClient."""
from __future__ import annotations

from slack_sdk.web.async_client import AsyncWebClient

from aa.connectors.base import BaseConnector


class SlackConnector(BaseConnector):
    """Connector for Slack workspaces — polls DMs and channel mentions."""

    def __init__(self, source_name: str, bot_token: str | None = None) -> None:
        self.source_name = source_name
        self.bot_token = bot_token
        self.client = AsyncWebClient(token=bot_token)
        self.my_user_id: str | None = None
        self._watched_channels: list[str] = []
        self._user_cache: dict[str, dict] = {}

    async def authenticate(self) -> None:
        """Authenticate via auth_test and store our own user ID."""
        response = await self.client.auth_test()
        self.my_user_id = response["user_id"]

    def set_watched_channels(self, channel_ids: list[str]) -> None:
        """Configure which channels to monitor for mentions."""
        self._watched_channels = list(channel_ids)

    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        """Fetch DMs and mentions from watched channels.

        Args:
            cursor: Unix timestamp string; only messages after this are returned.

        Returns:
            Tuple of (items, latest_timestamp_as_cursor).
        """
        dm_items = await self._fetch_dms(cursor)
        mention_items = await self._fetch_mentions(cursor)

        items = dm_items + mention_items
        if not items:
            return items, cursor

        latest_ts = max(item["timestamp"] for item in items)
        return items, latest_ts

    async def _fetch_dms(self, cursor: str | None) -> list[dict]:
        """Fetch direct messages, skipping our own."""
        response = await self.client.conversations_list(types="im")
        channels = response.get("channels", [])

        items: list[dict] = []
        for ch in channels:
            kwargs: dict = {"channel": ch["id"], "limit": 100}
            if cursor:
                kwargs["oldest"] = cursor

            hist = await self.client.conversations_history(**kwargs)
            for msg in hist.get("messages", []):
                if msg.get("user") == self.my_user_id:
                    continue
                user_info = await self._get_user_info(msg["user"])
                items.append(self._parse_message(msg, user_info, "dm"))

        return items

    async def _fetch_mentions(self, cursor: str | None) -> list[dict]:
        """Check watched channels for messages mentioning us."""
        items: list[dict] = []
        for channel_id in self._watched_channels:
            kwargs: dict = {"channel": channel_id, "limit": 100}
            if cursor:
                kwargs["oldest"] = cursor

            hist = await self.client.conversations_history(**kwargs)
            for msg in hist.get("messages", []):
                if f"<@{self.my_user_id}>" in msg.get("text", ""):
                    user_info = await self._get_user_info(msg["user"])
                    items.append(self._parse_message(msg, user_info, "mention"))

        return items

    async def _get_user_info(self, user_id: str) -> dict:
        """Look up user info, caching results."""
        if user_id not in self._user_cache:
            response = await self.client.users_info(user=user_id)
            self._user_cache[user_id] = response["user"]
        return self._user_cache[user_id]

    def _parse_message(self, msg: dict, user_info: dict, msg_type: str) -> dict:
        """Convert a Slack message to our standard item dict."""
        return {
            "id": f"{self.source_name}-{msg['ts']}",
            "source": self.source_name,
            "type": msg_type,
            "from_name": user_info.get("real_name", ""),
            "from_address": user_info.get("profile", {}).get("email"),
            "body": msg.get("text", ""),
            "timestamp": msg["ts"],
        }
