"""Tests for AI rules / feedback summary builder."""

from aa.ai.rules import build_feedback_summary


def test_empty_feedbacks_returns_no_feedback():
    assert build_feedback_summary([]) == "No feedback yet."


def test_feedback_summary_with_data():
    feedbacks = [
        # upgrade: corrected (1) < original (3)
        {"original_priority": 3, "corrected_priority": 1, "original_action": "fyi", "corrected_action": "fyi"},
        {"original_priority": 3, "corrected_priority": 1, "original_action": "fyi", "corrected_action": "fyi"},
        # downgrade: corrected (4) > original (2)
        {"original_priority": 2, "corrected_priority": 4, "original_action": "reply", "corrected_action": "reply"},
        # action change
        {"original_priority": 2, "corrected_priority": 2, "original_action": "fyi", "corrected_action": "reply"},
        {"original_priority": 2, "corrected_priority": 2, "original_action": "fyi", "corrected_action": "reply"},
        {"original_priority": 2, "corrected_priority": 2, "original_action": "fyi", "corrected_action": "reply"},
    ]
    result = build_feedback_summary(feedbacks)
    assert "upgraded" in result.lower() or "upgrade" in result.lower()
    assert "downgrade" in result.lower() or "downgraded" in result.lower()
    assert "fyi" in result.lower()
    assert "reply" in result.lower()
    # Check counts appear
    assert "2" in result  # 2 upgrades
    assert "1" in result  # 1 downgrade
    assert "3" in result  # 3 action changes fyi->reply


def test_feedback_summary_only_upgrades():
    feedbacks = [
        {"original_priority": 5, "corrected_priority": 1, "original_action": "fyi", "corrected_action": "fyi"},
    ]
    result = build_feedback_summary(feedbacks)
    assert "upgraded" in result.lower() or "upgrade" in result.lower()
    assert "downgrade" not in result.lower()


def test_feedback_summary_only_action_changes():
    feedbacks = [
        {"original_priority": 2, "corrected_priority": 2, "original_action": "fyi", "corrected_action": "reply"},
    ]
    result = build_feedback_summary(feedbacks)
    assert "fyi" in result.lower()
    assert "reply" in result.lower()
    assert "upgrade" not in result.lower()
    assert "downgrade" not in result.lower()
