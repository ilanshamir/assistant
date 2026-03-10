"""Tests for the AI triage engine."""

from __future__ import annotations

import json
import textwrap

import pytest

from aa.ai.triage import TriageEngine


@pytest.fixture
def engine():
    return TriageEngine(api_key="test-key")


@pytest.fixture
def sample_context():
    return {
        "calendar_today": [
            {"subject": "Sprint Planning", "timestamp": "2026-03-09T10:00:00"},
            {"subject": "1:1 with Manager", "timestamp": "2026-03-09T14:00:00"},
        ],
        "active_todos": [
            {"title": "Finish quarterly report", "priority": 1, "due_date": "2026-03-10"},
            {"title": "Review PR #42", "priority": 3, "due_date": "2026-03-15"},
        ],
        "rules": [
            "Anything from CEO is priority 1",
            "Marketing newsletters are FYI only",
        ],
        "feedback_summary": "User prioritizes executive requests and time-sensitive deadlines.",
    }


@pytest.fixture
def sample_items():
    return [
        {"id": "msg-1", "from": "ceo@company.com", "subject": "Q1 Strategy", "snippet": "Need your input on Q1 strategy."},
        {"id": "msg-2", "from": "newsletter@marketing.com", "subject": "Weekly Digest", "snippet": "This week in marketing..."},
    ]


class TestBuildTriagePrompt:
    """Tests for _build_triage_prompt."""

    def test_includes_rules(self, engine, sample_items, sample_context):
        prompt = engine._build_triage_prompt(sample_items, sample_context)
        assert "Anything from CEO is priority 1" in prompt
        assert "Marketing newsletters are FYI only" in prompt

    def test_includes_calendar_events(self, engine, sample_items, sample_context):
        prompt = engine._build_triage_prompt(sample_items, sample_context)
        assert "Sprint Planning" in prompt
        assert "1:1 with Manager" in prompt

    def test_includes_todos_with_due_dates(self, engine, sample_items, sample_context):
        prompt = engine._build_triage_prompt(sample_items, sample_context)
        assert "Finish quarterly report" in prompt
        assert "2026-03-10" in prompt
        assert "Review PR #42" in prompt
        assert "2026-03-15" in prompt

    def test_includes_feedback_summary(self, engine, sample_items, sample_context):
        prompt = engine._build_triage_prompt(sample_items, sample_context)
        assert "User prioritizes executive requests" in prompt

    def test_includes_items(self, engine, sample_items, sample_context):
        prompt = engine._build_triage_prompt(sample_items, sample_context)
        assert "ceo@company.com" in prompt
        assert "Q1 Strategy" in prompt
        assert "newsletter@marketing.com" in prompt

    def test_handles_empty_context(self, engine, sample_items):
        context: dict = {
            "calendar_today": [],
            "active_todos": [],
            "rules": [],
            "feedback_summary": "",
        }
        prompt = engine._build_triage_prompt(sample_items, context)
        # Should still include items even with empty context
        assert "Q1 Strategy" in prompt


class TestParseTriageResponse:
    """Tests for _parse_triage_response."""

    def test_parses_json_array(self, engine):
        response_text = json.dumps([
            {
                "id": "msg-1",
                "priority": 1,
                "summary": "CEO needs input on Q1 strategy",
                "action": "reply",
                "create_todo": True,
                "todo_title": "Reply to CEO re: Q1 Strategy",
                "draft": "Hi, I'll review and get back to you by EOD.",
            },
            {
                "id": "msg-2",
                "priority": 5,
                "summary": "Marketing newsletter",
                "action": "fyi",
                "create_todo": False,
                "todo_title": None,
                "draft": None,
            },
        ])
        result = engine._parse_triage_response(response_text)
        assert len(result) == 2
        assert result[0]["id"] == "msg-1"
        assert result[0]["priority"] == 1
        assert result[0]["action"] == "reply"
        assert result[0]["create_todo"] is True
        assert result[1]["id"] == "msg-2"
        assert result[1]["priority"] == 5
        assert result[1]["action"] == "fyi"

    def test_parses_markdown_wrapped_json(self, engine):
        response_text = textwrap.dedent("""\
            Here is the triage result:

            ```json
            [
                {
                    "id": "msg-1",
                    "priority": 2,
                    "summary": "Follow up needed",
                    "action": "schedule",
                    "create_todo": true,
                    "todo_title": "Schedule follow-up",
                    "draft": null
                }
            ]
            ```
        """)
        result = engine._parse_triage_response(response_text)
        assert len(result) == 1
        assert result[0]["id"] == "msg-1"
        assert result[0]["priority"] == 2
        assert result[0]["action"] == "schedule"

    def test_parses_plain_code_block(self, engine):
        response_text = "```\n[{\"id\": \"msg-1\", \"priority\": 3, \"summary\": \"Test\", \"action\": \"fyi\", \"create_todo\": false, \"todo_title\": null, \"draft\": null}]\n```"
        result = engine._parse_triage_response(response_text)
        assert len(result) == 1
        assert result[0]["id"] == "msg-1"

    def test_raises_on_invalid_json(self, engine):
        with pytest.raises(ValueError, match="parse"):
            engine._parse_triage_response("This is not JSON at all")
