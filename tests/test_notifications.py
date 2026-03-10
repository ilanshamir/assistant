"""Tests for notification formatting and filtering."""

import sys
from io import StringIO
from aa.notifications import format_notification, should_notify, send_terminal_notification


class TestFormatNotification:
    def test_full_item(self):
        item = {
            "source": "slack_workspace1",
            "from_name": "Bob Chen",
            "subject": "Production is down",
            "action": "reply",
            "priority": 1,
        }
        result = format_notification(item)
        assert result == '[URGENT] slack_workspace1: from Bob Chen: "Production is down" → suggested: reply'

    def test_priority_labels(self):
        base = {"source": "email", "from_name": "A", "subject": "B", "action": "read", "priority": 5}
        assert format_notification(base).startswith("[FYI]")
        base["priority"] = 3
        assert format_notification(base).startswith("[MEDIUM]")

    def test_missing_action_defaults(self):
        item = {"source": "email", "from_name": "X", "subject": "Y", "priority": 2}
        result = format_notification(item)
        assert "suggested: none" in result


class TestShouldNotify:
    def test_high_priority_returns_true(self):
        assert should_notify(1) is True
        assert should_notify(2) is True

    def test_low_priority_returns_false(self):
        assert should_notify(3) is False
        assert should_notify(5) is False

    def test_custom_threshold(self):
        assert should_notify(3, threshold=3) is True
        assert should_notify(4, threshold=3) is False


class TestSendTerminalNotification:
    def test_writes_bell_and_text_to_stderr(self, monkeypatch):
        buf = StringIO()
        monkeypatch.setattr(sys, "stderr", buf)
        send_terminal_notification("hello")
        output = buf.getvalue()
        assert "\a" in output
        assert "hello" in output
