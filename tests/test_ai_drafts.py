"""Tests for the AI draft response generator."""

from __future__ import annotations

import pytest

from aa.ai.drafts import DraftGenerator


@pytest.fixture
def generator():
    return DraftGenerator(api_key="test-key")


@pytest.fixture
def sample_item():
    return {
        "from_name": "Alice Johnson",
        "subject": "Team lunch tomorrow?",
        "body": "Hey, are you free for a team lunch tomorrow at noon? Let me know!",
    }


class TestBuildDraftPrompt:
    """Tests for _build_draft_prompt."""

    def test_includes_item_details(self, generator, sample_item):
        prompt = generator._build_draft_prompt(sample_item)
        assert "Alice Johnson" in prompt
        assert "Team lunch tomorrow?" in prompt
        assert "are you free for a team lunch" in prompt

    def test_with_user_instruction(self, generator, sample_item):
        instruction = "Say I'm free at 3pm instead"
        prompt = generator._build_draft_prompt(sample_item, user_instruction=instruction)
        assert "Alice Johnson" in prompt
        assert "Team lunch tomorrow?" in prompt
        assert "Say I'm free at 3pm instead" in prompt

    def test_without_user_instruction(self, generator, sample_item):
        prompt = generator._build_draft_prompt(sample_item)
        assert "Alice Johnson" in prompt
        # Should not contain an instruction section when none given
        assert "Instruction" not in prompt or "None" not in prompt
