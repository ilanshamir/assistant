"""Tests for the web UI routes."""

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, TestServer
from pathlib import Path

from aa.db import Database
from aa.config import AppConfig


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.initialize()
    yield database
    await database.close()


@pytest_asyncio.fixture
async def web_client(db, tmp_path):
    from aa.web import create_app
    config = AppConfig(data_dir=tmp_path, web_port=0)
    app = create_app(config, db)

    from aiohttp.test_utils import TestClient, TestServer
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


@pytest.mark.asyncio
async def test_index_returns_html(web_client):
    resp = await web_client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "<!DOCTYPE html>" in text.lower() or "<!doctype html>" in text.lower()


@pytest.mark.asyncio
async def test_get_todos_empty(web_client):
    resp = await web_client.get("/todos")
    assert resp.status == 200


@pytest.mark.asyncio
async def test_create_todo(web_client, db):
    resp = await web_client.post(
        "/todos/new",
        data={"title": "Test todo", "priority": "2"},
        headers={"Origin": "http://localhost"},
    )
    assert resp.status == 200
    todos = await db.list_todos()
    assert len(todos) == 1
    assert todos[0]["title"] == "Test todo"
    assert todos[0]["priority"] == 2


@pytest.mark.asyncio
async def test_patch_todo_priority(web_client, db):
    todo_id = await db.insert_todo(title="Patch me", priority=3)
    resp = await web_client.patch(
        f"/todos/{todo_id}",
        data={"priority": "1"},
        headers={"Origin": "http://localhost"},
    )
    assert resp.status == 200
    updated = await db.get_todo(todo_id)
    assert updated["priority"] == 1


@pytest.mark.asyncio
async def test_mark_todo_done(web_client, db):
    todo_id = await db.insert_todo(title="Done me", priority=3)
    resp = await web_client.post(
        f"/todos/{todo_id}/done",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status == 200
    updated = await db.get_todo(todo_id)
    assert updated["status"] == "done"


@pytest.mark.asyncio
async def test_delete_todo(web_client, db):
    todo_id = await db.insert_todo(title="Delete me", priority=3)
    resp = await web_client.post(
        f"/todos/{todo_id}/delete",
        headers={"Origin": "http://localhost"},
    )
    assert resp.status == 200
    updated = await db.get_todo(todo_id)
    assert updated["status"] == "deleted"


@pytest.mark.asyncio
async def test_bulk_done(web_client, db):
    id1 = await db.insert_todo(title="A", priority=1)
    id2 = await db.insert_todo(title="B", priority=2)
    resp = await web_client.post(
        "/todos/bulk",
        data={"ids": f"{id1},{id2}", "action": "done"},
        headers={"Origin": "http://localhost"},
    )
    assert resp.status == 200
    assert (await db.get_todo(id1))["status"] == "done"
    assert (await db.get_todo(id2))["status"] == "done"


@pytest.mark.asyncio
async def test_get_todo_detail(web_client, db):
    todo_id = await db.insert_todo(title="Detail me", priority=2, details="Some details")
    resp = await web_client.get(f"/todos/{todo_id}/detail")
    assert resp.status == 200
    text = await resp.text()
    assert "Some details" in text


@pytest.mark.asyncio
async def test_csrf_blocks_no_origin(web_client, db):
    resp = await web_client.post(
        "/todos/new",
        data={"title": "Blocked", "priority": "3"},
        # No Origin header
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_csrf_blocks_bad_origin(web_client, db):
    resp = await web_client.post(
        "/todos/new",
        data={"title": "Blocked", "priority": "3"},
        headers={"Origin": "http://evil.com"},
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_todos_sort_by_query(web_client, db):
    await db.insert_todo(title="Low", priority=5, due_date="2026-04-01")
    await db.insert_todo(title="High", priority=1, due_date="2026-03-01")
    resp = await web_client.get("/todos?sort=priority,due_date")
    assert resp.status == 200
    text = await resp.text()
    # High priority should appear before Low
    assert text.index("High") < text.index("Low")


@pytest.mark.asyncio
async def test_todos_search(web_client, db):
    await db.insert_todo(title="Buy groceries", priority=3)
    await db.insert_todo(title="Review PR", priority=2)
    resp = await web_client.get("/todos?q=groceries")
    assert resp.status == 200
    text = await resp.text()
    assert "Buy groceries" in text
    assert "Review PR" not in text


@pytest.mark.asyncio
async def test_chat_action_create_todo(web_client, db):
    resp = await web_client.post(
        "/chat/action",
        json={"type": "create_todo", "title": "From chat", "priority": 2},
        headers={"Origin": "http://localhost"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["ok"] is True
    todos = await db.list_todos()
    assert len(todos) == 1
    assert todos[0]["title"] == "From chat"


@pytest.mark.asyncio
async def test_chat_action_mark_done(web_client, db):
    todo_id = await db.insert_todo(title="Finish it", priority=2)
    resp = await web_client.post(
        "/chat/action",
        json={"type": "mark_done", "todo_id": todo_id},
        headers={"Origin": "http://localhost"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["ok"] is True
    updated = await db.get_todo(todo_id)
    assert updated["status"] == "done"


@pytest.mark.asyncio
async def test_get_edit_field_priority(web_client, db):
    todo_id = await db.insert_todo(title="Edit me", priority=3)
    resp = await web_client.get(f"/todos/{todo_id}/edit/priority")
    assert resp.status == 200
    text = await resp.text()
    assert "<select" in text
    assert "P3" in text


@pytest.mark.asyncio
async def test_bulk_priority(web_client, db):
    id1 = await db.insert_todo(title="A", priority=3)
    id2 = await db.insert_todo(title="B", priority=3)
    resp = await web_client.post(
        "/todos/bulk",
        data={"ids": f"{id1},{id2}", "action": "priority", "value": "1"},
        headers={"Origin": "http://localhost"},
    )
    assert resp.status == 200
    assert (await db.get_todo(id1))["priority"] == 1
    assert (await db.get_todo(id2))["priority"] == 1
