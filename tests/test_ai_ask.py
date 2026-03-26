"""Tests for the AskEngine streaming and action parsing."""

import pytest
from aa.ai.ask import AskEngine, parse_actions, WEB_SYSTEM_PROMPT


def test_parse_actions_extracts_json_block():
    text = """Here's what I recommend.

```actions
[{"type": "create_todo", "title": "Review docs", "priority": 2}]
```

Let me know if you need anything else."""

    actions, clean_text = parse_actions(text)
    assert len(actions) == 1
    assert actions[0]["type"] == "create_todo"
    assert actions[0]["title"] == "Review docs"
    assert "```actions" not in clean_text
    assert "Review docs" not in clean_text
    assert "Here's what I recommend." in clean_text
    assert "Let me know if you need anything else." in clean_text


def test_parse_actions_no_block():
    text = "Just a regular response with no actions."
    actions, clean_text = parse_actions(text)
    assert actions == []
    assert clean_text == text


def test_parse_actions_multiple_actions():
    text = """Done.

```actions
[{"type": "create_todo", "title": "Task A", "priority": 1}, {"type": "mark_done", "todo_id": "abc123"}]
```"""

    actions, clean_text = parse_actions(text)
    assert len(actions) == 2
    assert actions[0]["type"] == "create_todo"
    assert actions[1]["type"] == "mark_done"


def test_parse_actions_invalid_json():
    text = """Response.

```actions
not valid json
```"""

    actions, clean_text = parse_actions(text)
    assert actions == []
    assert "Response." in clean_text


def test_web_system_prompt_mentions_actions():
    assert "```actions" in WEB_SYSTEM_PROMPT
    assert "create_todo" in WEB_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_ask_stream_yields_chunks():
    """Test ask_stream with a mocked Anthropic client."""
    from unittest.mock import AsyncMock, MagicMock, patch

    engine = AskEngine.__new__(AskEngine)
    engine._model = "test-model"

    mock_stream = AsyncMock()

    async def fake_text_stream():
        for chunk in ["Hello", " world"]:
            yield chunk

    mock_stream.text_stream = fake_text_stream()
    mock_context = AsyncMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_stream)
    mock_context.__aexit__ = AsyncMock(return_value=False)

    mock_client = AsyncMock()
    mock_client.messages.stream = MagicMock(return_value=mock_context)
    engine._client = mock_client

    chunks = []
    async for chunk in engine.ask_stream("test?", {"todos": [], "inbox": [], "calendar": []}):
        chunks.append(chunk)

    assert chunks == ["Hello", " world"]
    mock_client.messages.stream.assert_called_once()
