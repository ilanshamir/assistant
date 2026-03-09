import pytest
import pytest_asyncio
import asyncio
from pathlib import Path
from aa.db import Database

@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.initialize()
    yield database
    await database.close()

@pytest.mark.asyncio
async def test_initialize_creates_tables(db):
    tables = await db.list_tables()
    assert "items" in tables
    assert "todos" in tables
    assert "todo_links" in tables
    assert "sync_state" in tables
    assert "drafts" in tables
    assert "feedback" in tables
    assert "triage_rules" in tables
    assert "config" in tables

@pytest.mark.asyncio
async def test_insert_and_get_item(db):
    item = {
        "id": "test-1",
        "source": "resilio",
        "source_id": "abc123",
        "type": "email",
        "from_name": "Alice",
        "from_address": "alice@example.com",
        "subject": "Hello",
        "body": "Hi there",
        "timestamp": "2026-03-09T10:00:00",
    }
    await db.insert_item(item)
    result = await db.get_item("test-1")
    assert result["source"] == "resilio"
    assert result["subject"] == "Hello"

@pytest.mark.asyncio
async def test_insert_and_list_todos(db):
    todo_id = await db.insert_todo(title="Fix bug", priority=1)
    todos = await db.list_todos()
    assert len(todos) == 1
    assert todos[0]["title"] == "Fix bug"
    assert todos[0]["priority"] == 1

@pytest.mark.asyncio
async def test_update_todo_status(db):
    todo_id = await db.insert_todo(title="Task", priority=3)
    await db.update_todo(todo_id, status="done")
    todo = await db.get_todo(todo_id)
    assert todo["status"] == "done"
    assert todo["completed_at"] is not None

@pytest.mark.asyncio
async def test_todo_link(db):
    item = {
        "id": "item-1",
        "source": "slack_workspace1",
        "source_id": "msg1",
        "type": "dm",
        "from_name": "Bob",
        "from_address": "",
        "subject": "",
        "body": "Can you review this?",
        "timestamp": "2026-03-09T10:00:00",
    }
    await db.insert_item(item)
    todo_id = await db.insert_todo(title="Review Bob's thing", priority=2)
    await db.link_todo(todo_id, "item-1")
    links = await db.get_todo_links(todo_id)
    assert len(links) == 1
    assert links[0]["item_id"] == "item-1"

@pytest.mark.asyncio
async def test_insert_and_get_draft(db):
    item = {
        "id": "item-2",
        "source": "resilio",
        "source_id": "xyz",
        "type": "email",
        "from_name": "Carol",
        "from_address": "carol@example.com",
        "subject": "Meeting",
        "body": "Can we meet?",
        "timestamp": "2026-03-09T11:00:00",
    }
    await db.insert_item(item)
    draft_id = await db.insert_draft(item_id="item-2", body="Sure, how about 3pm?")
    draft = await db.get_draft(draft_id)
    assert draft["body"] == "Sure, how about 3pm?"
    assert draft["status"] == "pending"

@pytest.mark.asyncio
async def test_sync_state(db):
    await db.update_sync_state("resilio", cursor="abc123", status="ok")
    state = await db.get_sync_state("resilio")
    assert state["cursor"] == "abc123"
    assert state["status"] == "ok"

@pytest.mark.asyncio
async def test_feedback(db):
    feedback_id = await db.insert_feedback(
        item_id="test-1",
        original_priority=4,
        corrected_priority=1,
        original_action="fyi",
        corrected_action="reply",
    )
    feedbacks = await db.list_feedback(limit=10)
    assert len(feedbacks) == 1
    assert feedbacks[0]["corrected_priority"] == 1

@pytest.mark.asyncio
async def test_triage_rules(db):
    rule_id = await db.insert_rule("Anything from Bob is priority 1")
    rules = await db.list_rules()
    assert len(rules) == 1
    assert rules[0]["rule"] == "Anything from Bob is priority 1"
    await db.delete_rule(rule_id)
    rules = await db.list_rules()
    assert len(rules) == 0

@pytest.mark.asyncio
async def test_items_untriaged(db):
    item = {
        "id": "untriaged-1",
        "source": "resilio",
        "source_id": "u1",
        "type": "email",
        "from_name": "Dave",
        "from_address": "dave@example.com",
        "subject": "Urgent",
        "body": "Help",
        "timestamp": "2026-03-09T12:00:00",
    }
    await db.insert_item(item)
    untriaged = await db.get_untriaged_items()
    assert len(untriaged) == 1
    assert untriaged[0]["id"] == "untriaged-1"
