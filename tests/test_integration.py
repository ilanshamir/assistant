"""Integration test: end-to-end flow through RequestHandler + Database."""

from __future__ import annotations

import pytest
import pytest_asyncio

from aa.config import AppConfig
from aa.db import Database
from aa.server import RequestHandler


@pytest_asyncio.fixture
async def setup(tmp_path):
    config = AppConfig(data_dir=tmp_path)
    db = Database(tmp_path / "test.db")
    await db.initialize()
    handler = RequestHandler(config=config, db=db)
    yield handler, db
    await db.close()


@pytest.mark.asyncio
async def test_full_flow(setup):
    handler, db = setup

    # 1. Insert an item directly into DB (simulating a connector)
    item_id = await db.insert_item(
        {
            "source": "email",
            "source_id": "msg-001",
            "type": "email",
            "from_name": "Alice",
            "from_address": "alice@example.com",
            "subject": "Important project update",
            "body": "Please review the attached document.",
            "timestamp": "2026-03-09T10:00:00Z",
        }
    )
    assert item_id

    # 2. Triage it via db.update_item_triage
    await db.update_item_triage(item_id, priority=1, action="reply")

    # 3. Check inbox via handler — verify item shows up with priority
    result = await handler.handle({"command": "inbox", "args": {}})
    assert result["ok"] is True
    items = result["items"]
    assert len(items) >= 1
    matched = [i for i in items if i["id"] == item_id]
    assert len(matched) == 1
    assert matched[0]["priority"] == 1
    assert matched[0]["action"] == "reply"

    # 4. Add a todo via handler (with category and due_date)
    result = await handler.handle(
        {
            "command": "todo_add",
            "args": {
                "title": "Reply to Alice",
                "priority": 1,
                "category": "email",
                "due_date": "2026-03-10",
            },
        }
    )
    assert result["ok"] is True
    todo_id = result["id"]
    assert todo_id

    # 5. Link todo to item via handler
    result = await handler.handle(
        {
            "command": "todo_link",
            "args": {"todo_id": todo_id, "item_id": item_id},
        }
    )
    assert result["ok"] is True
    assert result["id"]  # link_id returned

    # 6. List todos via handler — verify it shows up
    result = await handler.handle({"command": "todo", "args": {}})
    assert result["ok"] is True
    todos = result["todos"]
    assert any(t["id"] == todo_id for t in todos)

    # 7. List todos filtered by category
    result = await handler.handle(
        {"command": "todo", "args": {"category": "email"}}
    )
    assert result["ok"] is True
    assert any(t["id"] == todo_id for t in result["todos"])

    # Verify filtering actually filters: a different category yields no match
    result = await handler.handle(
        {"command": "todo", "args": {"category": "nonexistent"}}
    )
    assert result["ok"] is True
    assert not any(t["id"] == todo_id for t in result["todos"])

    # 8. Add a triage rule via handler
    result = await handler.handle(
        {
            "command": "rule_add",
            "args": {"rule": "If from Alice, set priority 1"},
        }
    )
    assert result["ok"] is True
    rule_id = result["id"]

    # 9. List rules — verify
    result = await handler.handle({"command": "rule_list", "args": {}})
    assert result["ok"] is True
    rules = result["rules"]
    assert any(r["id"] == rule_id for r in rules)
    matched_rule = [r for r in rules if r["id"] == rule_id][0]
    assert matched_rule["rule"] == "If from Alice, set priority 1"

    # 10. Reprioritize the item via handler
    result = await handler.handle(
        {"command": "reprioritize", "args": {"id": item_id, "priority": 3}}
    )
    assert result["ok"] is True

    # 11. Verify item priority changed in DB
    item = await db.get_item(item_id)
    assert item is not None
    assert item["priority"] == 3

    # 12. Mark todo done via handler
    result = await handler.handle(
        {"command": "todo_done", "args": {"id": todo_id}}
    )
    assert result["ok"] is True

    # 13. Verify todo status is "done" with completed_at set
    todo = await db.get_todo(todo_id)
    assert todo is not None
    assert todo["status"] == "done"
    assert todo["completed_at"] is not None
