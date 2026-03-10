"""Tests for SlackConnector."""
from __future__ import annotations

import pytest

from aa.connectors.slack import SlackConnector


class TestParseMessage:
    """Test _parse_message converts Slack messages to standard item dicts."""

    def _make_connector(self, source_name: str = "slack_workspace1"):
        conn = SlackConnector.__new__(SlackConnector)
        conn.source_name = source_name
        conn.my_user_id = "U_ME"
        conn._user_cache = {}
        conn._watched_channels = []
        return conn

    def test_parse_dm(self):
        conn = self._make_connector()
        msg = {"ts": "1700000000.000100", "text": "Hey, can you review this?"}
        user_info = {
            "real_name": "Alice Smith",
            "profile": {"email": "alice@example.com"},
        }
        item = conn._parse_message(msg, user_info, "dm")

        assert item["id"] == "slack_workspace1-1700000000.000100"
        assert item["source"] == "slack_workspace1"
        assert item["type"] == "dm"
        assert item["from_name"] == "Alice Smith"
        assert item["from_address"] == "alice@example.com"
        assert item["body"] == "Hey, can you review this?"
        assert item["timestamp"] == "1700000000.000100"

    def test_parse_mention(self):
        conn = self._make_connector()
        msg = {"ts": "1700000001.000200", "text": "<@U_ME> please take a look"}
        user_info = {
            "real_name": "Bob Jones",
            "profile": {"email": "bob@example.com"},
        }
        item = conn._parse_message(msg, user_info, "mention")

        assert item["id"] == "slack_workspace1-1700000001.000200"
        assert item["source"] == "slack_workspace1"
        assert item["type"] == "mention"
        assert item["from_name"] == "Bob Jones"
        assert item["from_address"] == "bob@example.com"
        assert item["body"] == "<@U_ME> please take a look"
        assert item["timestamp"] == "1700000001.000200"

    def test_parse_message_missing_email(self):
        conn = self._make_connector()
        msg = {"ts": "1700000002.000300", "text": "hello"}
        user_info = {
            "real_name": "No Email User",
            "profile": {},
        }
        item = conn._parse_message(msg, user_info, "dm")

        assert item["from_name"] == "No Email User"
        assert item["from_address"] is None
        assert item["body"] == "hello"

    def test_parse_message_different_source(self):
        conn = self._make_connector(source_name="slack_other")
        msg = {"ts": "1700000003.000400", "text": "test"}
        user_info = {
            "real_name": "Charlie",
            "profile": {"email": "charlie@example.com"},
        }
        item = conn._parse_message(msg, user_info, "dm")

        assert item["id"] == "slack_other-1700000003.000400"
        assert item["source"] == "slack_other"


class TestSetWatchedChannels:
    """Test set_watched_channels configures channel monitoring."""

    def test_set_watched_channels(self):
        conn = SlackConnector.__new__(SlackConnector)
        conn._watched_channels = []
        conn.set_watched_channels(["C123", "C456"])
        assert conn._watched_channels == ["C123", "C456"]

    def test_set_watched_channels_replaces(self):
        conn = SlackConnector.__new__(SlackConnector)
        conn._watched_channels = ["C_OLD"]
        conn.set_watched_channels(["C_NEW"])
        assert conn._watched_channels == ["C_NEW"]
