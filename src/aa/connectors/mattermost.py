"""Mattermost connector using mattermostdriver."""
from __future__ import annotations

from mattermostdriver import Driver

from aa.connectors.base import BaseConnector


class MattermostConnector(BaseConnector):
    """Connector for Mattermost — polls DMs and channel mentions."""

    source_name = "mattermost"

    def __init__(self, url: str | None = None, token: str | None = None) -> None:
        self.url = url or ""
        self.token = token or ""
        self.driver = Driver(
            {
                "url": self.url,
                "token": self.token,
                "scheme": "https",
                "port": 443,
            }
        )
        self.my_user_id: str | None = None
        self._watched_channels: list[str] = []
        self._user_cache: dict[str, dict] = {}

    async def authenticate(self) -> None:
        """Login via the Mattermost driver and store our own user ID."""
        self.driver.login()
        me = self.driver.users.get_user("me")
        self.my_user_id = me["id"]

    def set_watched_channels(self, channel_ids: list[str]) -> None:
        """Configure which channels to monitor for mentions."""
        self._watched_channels = list(channel_ids)

    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        """Fetch DMs and mentions from watched channels.

        Args:
            cursor: Timestamp string (seconds); only posts after this are returned.

        Returns:
            Tuple of (items, latest_timestamp_as_cursor).
        """
        dm_items = self._fetch_dms(cursor)
        mention_items = self._fetch_mentions(cursor)

        items = dm_items + mention_items
        if not items:
            return items, cursor

        latest_ts = str(max(item["timestamp"] for item in items))
        return items, latest_ts

    def _fetch_dms(self, cursor: str | None) -> list[dict]:
        """Fetch direct messages to the authenticated user."""
        channels = self.driver.channels.get_channels_for_user(self.my_user_id)
        dm_channels = [
            ch for ch in channels if ch.get("type") == "D"
        ]

        items: list[dict] = []
        for ch in dm_channels:
            posts_resp = self.driver.posts.get_posts_for_channel(ch["id"])
            order = posts_resp.get("order", [])
            posts = posts_resp.get("posts", {})

            for post_id in order:
                post = posts[post_id]
                if post.get("user_id") == self.my_user_id:
                    continue
                if cursor and post["create_at"] / 1000.0 <= float(cursor):
                    continue
                user_info = self._get_user_info(post["user_id"])
                items.append(self._parse_post(post, user_info, "dm"))

        return items

    def _fetch_mentions(self, cursor: str | None) -> list[dict]:
        """Check watched channels for posts mentioning us."""
        items: list[dict] = []
        me = self.driver.users.get_user("me")
        my_username = me.get("username", "")

        for channel_id in self._watched_channels:
            posts_resp = self.driver.posts.get_posts_for_channel(channel_id)
            order = posts_resp.get("order", [])
            posts = posts_resp.get("posts", {})

            for post_id in order:
                post = posts[post_id]
                if cursor and post["create_at"] / 1000.0 <= float(cursor):
                    continue
                if f"@{my_username}" in post.get("message", ""):
                    user_info = self._get_user_info(post["user_id"])
                    items.append(self._parse_post(post, user_info, "mention"))

        return items

    def _get_user_info(self, user_id: str) -> dict:
        """Look up user info, caching results."""
        if user_id not in self._user_cache:
            self._user_cache[user_id] = self.driver.users.get_user(user_id)
        return self._user_cache[user_id]

    def _parse_post(self, post: dict, user_info: dict, msg_type: str) -> dict:
        """Convert a Mattermost post to a standard item dict."""
        first = user_info.get("first_name", "").strip()
        last = user_info.get("last_name", "").strip()
        full_name = f"{first} {last}".strip()
        if not full_name:
            full_name = user_info.get("username", "")

        return {
            "id": f"mattermost-{post['id']}",
            "source": self.source_name,
            "type": msg_type,
            "from_name": full_name,
            "body": post.get("message", ""),
            "timestamp": post["create_at"] / 1000.0,
        }
