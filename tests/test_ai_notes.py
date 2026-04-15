"""Tests for AI-powered notes extraction."""

import json
import pytest
from aa.ai.notes import NotesExtractor


@pytest.fixture
def extractor():
    return NotesExtractor(api_key="test-key")


class TestBuildPrompt:
    def test_includes_content(self, extractor):
        prompt = extractor._build_prompt("TODO: buy milk", today="2026-03-09")
        assert "buy milk" in prompt

    def test_includes_today_date(self, extractor):
        prompt = extractor._build_prompt("some notes", today="2026-03-09")
        assert "2026-03-09" in prompt

    def test_handles_multiline_content(self, extractor):
        content = "Meeting with Bob\n- Need to send report\n- Follow up on Q3"
        prompt = extractor._build_prompt(content, today="2026-03-09")
        assert "send report" in prompt
        assert "Follow up on Q3" in prompt

    def test_omits_existing_block_when_lists_empty(self, extractor):
        prompt = extractor._build_prompt("TODO: x", today="2026-03-09")
        assert "Existing categories" not in prompt
        assert "Existing projects" not in prompt

    def test_includes_existing_categories_and_projects(self, extractor):
        prompt = extractor._build_prompt(
            "TODO: x",
            today="2026-03-09",
            existing_categories=["work", "private"],
            existing_projects=["Q3 launch", "garden"],
        )
        assert "Existing categories: work, private" in prompt
        assert "Existing projects: Q3 launch, garden" in prompt

    def test_includes_only_categories_when_projects_empty(self, extractor):
        prompt = extractor._build_prompt(
            "TODO: x",
            today="2026-03-09",
            existing_categories=["work"],
            existing_projects=[],
        )
        assert "Existing categories: work" in prompt
        assert "Existing projects" not in prompt


class TestParseResponse:
    def test_parses_json_array(self):
        raw = json.dumps([
            {"title": "Send report to Bob", "priority": 2, "category": "work",
             "project": "Q3", "due_date": "2026-03-15", "notes": "From Monday standup"},
            {"title": "Buy groceries", "priority": 4, "category": "private",
             "project": None, "due_date": None, "notes": None},
        ])
        result = NotesExtractor._parse_response(raw)
        assert len(result) == 2
        assert result[0]["title"] == "Send report to Bob"
        assert result[0]["due_date"] == "2026-03-15"
        assert result[1]["category"] == "private"

    def test_parses_markdown_wrapped(self):
        raw = "```json\n" + json.dumps([{"title": "Do thing", "priority": 3}]) + "\n```"
        result = NotesExtractor._parse_response(raw)
        assert len(result) == 1

    def test_empty_array(self):
        result = NotesExtractor._parse_response("[]")
        assert result == []

    def test_raises_on_invalid(self):
        with pytest.raises(json.JSONDecodeError):
            NotesExtractor._parse_response("not json")
