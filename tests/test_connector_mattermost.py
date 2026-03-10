"""Tests for MattermostConnector."""
from __future__ import annotations

from aa.connectors.mattermost import MattermostConnector


class TestParsePost:
    """Test _parse_post converts Mattermost posts to standard item dicts."""

    def _make_connector(self) -> MattermostConnector:
        conn = MattermostConnector.__new__(MattermostConnector)
        conn.source_name = "mattermost"
        conn.url = "https://mm.example.com"
        conn.token = "fake-token"
        conn.driver = None
        conn.my_user_id = "user123"
        conn._watched_channels = []
        conn._user_cache = {}
        return conn

    def test_parse_dm(self):
        conn = self._make_connector()
        post = {
            "id": "post_abc123",
            "message": "Hey, can you review this PR?",
            "create_at": 1700000000000,
        }
        user_info = {
            "first_name": "Alice",
            "last_name": "Smith",
            "username": "asmith",
        }
        item = conn._parse_post(post, user_info, "dm")

        assert item["id"] == "mattermost-post_abc123"
        assert item["source"] == "mattermost"
        assert item["type"] == "dm"
        assert item["from_name"] == "Alice Smith"
        assert item["body"] == "Hey, can you review this PR?"
        assert item["timestamp"] == 1700000000.0

    def test_parse_mention(self):
        conn = self._make_connector()
        post = {
            "id": "post_def456",
            "message": "@myuser please take a look at this",
            "create_at": 1700000001000,
        }
        user_info = {
            "first_name": "Bob",
            "last_name": "Jones",
            "username": "bjones",
        }
        item = conn._parse_post(post, user_info, "mention")

        assert item["id"] == "mattermost-post_def456"
        assert item["source"] == "mattermost"
        assert item["type"] == "mention"
        assert item["from_name"] == "Bob Jones"
        assert item["body"] == "@myuser please take a look at this"
        assert item["timestamp"] == 1700000001.0

    def test_parse_post_falls_back_to_username(self):
        conn = self._make_connector()
        post = {
            "id": "post_ghi789",
            "message": "hello",
            "create_at": 1700000002000,
        }
        user_info = {
            "first_name": "",
            "last_name": "",
            "username": "mysterious_user",
        }
        item = conn._parse_post(post, user_info, "dm")

        assert item["from_name"] == "mysterious_user"

    def test_parse_post_no_first_or_last_name(self):
        conn = self._make_connector()
        post = {
            "id": "post_jkl012",
            "message": "test",
            "create_at": 1700000003000,
        }
        user_info = {
            "username": "only_username",
        }
        item = conn._parse_post(post, user_info, "dm")

        assert item["from_name"] == "only_username"

    def test_parse_post_timestamp_conversion(self):
        """create_at is in milliseconds; timestamp should be seconds."""
        conn = self._make_connector()
        post = {
            "id": "post_ts",
            "message": "timing test",
            "create_at": 1609459200000,  # 2021-01-01 00:00:00 UTC in ms
        }
        user_info = {"first_name": "Test", "last_name": "User", "username": "tuser"}
        item = conn._parse_post(post, user_info, "dm")

        assert item["timestamp"] == 1609459200.0


class TestSetWatchedChannels:
    """Test set_watched_channels configures channel monitoring."""

    def _make_connector(self) -> MattermostConnector:
        conn = MattermostConnector.__new__(MattermostConnector)
        conn._watched_channels = []
        return conn

    def test_set_watched_channels(self):
        conn = self._make_connector()
        conn.set_watched_channels(["ch1", "ch2"])
        assert conn._watched_channels == ["ch1", "ch2"]

    def test_set_watched_channels_replaces(self):
        conn = self._make_connector()
        conn._watched_channels = ["old_ch"]
        conn.set_watched_channels(["new_ch"])
        assert conn._watched_channels == ["new_ch"]
