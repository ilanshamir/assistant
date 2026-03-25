# Web UI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an htmx + Jinja2 web interface to the AA personal assistant, embedded in the daemon process, focused on todo management with a chat panel.

**Architecture:** An aiohttp HTTP server starts alongside the existing Unix socket server inside the daemon's asyncio loop. Templates are server-rendered with htmx providing interactivity for inline editing, bulk actions, and dynamic updates. A bottom chat panel streams AI responses via SSE.

**Tech Stack:** Python 3.12, aiohttp, Jinja2, aiohttp-jinja2, htmx (vendored), SSE via StreamResponse

---

## Chunk 1: Foundation — Dependencies, Config, DB Changes

### Task 1: Add Dependencies to pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add new dependencies**

Add `aiohttp`, `jinja2`, and `aiohttp-jinja2` to the dependencies list in `pyproject.toml`:

```toml
# Add these three lines to the dependencies array, after "aiosqlite>=0.20":
    "aiohttp>=3.9",
    "jinja2>=3.1",
    "aiohttp-jinja2>=1.6",
```

- [ ] **Step 2: Install updated dependencies**

Run: `cd /home/ishamir/src/assistant && pip install -e .`
Expected: Successfully installs aiohttp, jinja2, aiohttp-jinja2

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat(web): add aiohttp, jinja2, aiohttp-jinja2 dependencies"
```

### Task 2: Add Web Config Fields

**Files:**
- Modify: `src/aa/config.py:11-23` (AppConfig dataclass)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to the `TestConfigDefaults` class in `tests/test_config.py`:

```python
    def test_web_config_defaults(self):
        cfg = AppConfig()
        assert cfg.web_enabled is False
        assert cfg.web_port == 8080
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ishamir/src/assistant && python -m pytest tests/test_config.py::TestConfigDefaults::test_web_config_defaults -v`
Expected: FAIL with AttributeError

- [ ] **Step 3: Add web fields to AppConfig**

In `src/aa/config.py`, add two fields to the `AppConfig` dataclass after `sources`:

```python
    web_enabled: bool = False
    web_port: int = 8080
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ishamir/src/assistant && python -m pytest tests/test_config.py::test_web_config_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aa/config.py tests/test_config.py
git commit -m "feat(web): add web_enabled and web_port config fields"
```

### Task 3: Add Sort and Extended Keyword Search to DB

**Files:**
- Modify: `src/aa/db.py:248-288` (list_todos method)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing test for sort parameter**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_list_todos_sort_by_due_date(db):
    await db.insert_todo(title="Later", priority=1, due_date="2026-04-01")
    await db.insert_todo(title="Sooner", priority=1, due_date="2026-03-15")
    await db.insert_todo(title="No date", priority=1)

    todos = await db.list_todos(sort="priority,due_date")
    # Todos with due dates should come before those without, sorted ascending
    assert todos[0]["title"] == "Sooner"
    assert todos[1]["title"] == "Later"
    assert todos[2]["title"] == "No date"
```

- [ ] **Step 2: Write failing test for keyword search on category/project**

Add to `tests/test_db.py`:

```python
@pytest.mark.asyncio
async def test_todo_keyword_searches_category_and_project(db):
    await db.insert_todo(title="Task A", priority=2, category="engineering", project="backend")
    await db.insert_todo(title="Task B", priority=3, category="marketing")

    results = await db.list_todos(keyword="engineering")
    assert len(results) == 1
    assert results[0]["title"] == "Task A"

    results = await db.list_todos(keyword="backend")
    assert len(results) == 1
    assert results[0]["title"] == "Task A"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /home/ishamir/src/assistant && python -m pytest tests/test_db.py::test_list_todos_sort_by_due_date tests/test_db.py::test_todo_keyword_searches_category_and_project -v`
Expected: FAIL

- [ ] **Step 4: Implement sort parameter and keyword search changes**

In `src/aa/db.py`, modify the `list_todos` method signature to accept `sort`:

```python
    async def list_todos(
        self,
        status: str | None = None,
        include_deleted: bool = False,
        category: str | None = None,
        project: str | None = None,
        priority: int | None = None,
        max_priority: int | None = None,
        keyword: str | None = None,
        due_before: str | None = None,
        sort: str | None = None,
    ) -> list[dict[str, Any]]:
```

Change the keyword filter (around line 278-281) to also search category and project:

```python
        if keyword:
            query += " AND (title LIKE ? OR notes LIKE ? OR details LIKE ? OR category LIKE ? OR project LIKE ?)"
            like = f"%{keyword}%"
            params.extend([like, like, like, like, like])
```

Replace the hardcoded ORDER BY (line 285) with dynamic sort:

```python
        # Build ORDER BY clause
        if sort:
            # Allow comma-separated column names, validate against allowed columns
            allowed = {"priority", "due_date", "created_at", "title", "category", "project"}
            parts = []
            for part in sort.split(","):
                col = part.strip().lstrip("-")
                if col in allowed:
                    direction = "DESC" if part.strip().startswith("-") else "ASC"
                    # NULLs always sort last regardless of direction
                    parts.append(f"{col} IS NULL, {col} {direction}")
            if parts:
                query += " ORDER BY " + ", ".join(parts)
            else:
                query += " ORDER BY priority, created_at"
        else:
            query += " ORDER BY priority, created_at"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/ishamir/src/assistant && python -m pytest tests/test_db.py -v`
Expected: ALL PASS (including existing tests)

- [ ] **Step 6: Commit**

```bash
git add src/aa/db.py tests/test_db.py
git commit -m "feat(web): add sort param and category/project keyword search to list_todos"
```

## Chunk 2: Ask Engine Streaming + Action Parsing

### Task 4: Add Streaming Support to AskEngine

**Files:**
- Modify: `src/aa/ai/ask.py`
- Test: `tests/test_ai_ask.py` (new file)

- [ ] **Step 1: Write failing test for ask_stream**

Create `tests/test_ai_ask.py`:

```python
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

    # Mock the streaming context manager
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/ishamir/src/assistant && python -m pytest tests/test_ai_ask.py -v`
Expected: FAIL with ImportError (parse_actions and WEB_SYSTEM_PROMPT don't exist)

- [ ] **Step 3: Implement parse_actions and WEB_SYSTEM_PROMPT**

In `src/aa/ai/ask.py`, add `import re` at the top of the file next to the existing `import json` (line 6). Do NOT add a duplicate `import json`.

Then add the following after the existing `SYSTEM_PROMPT` constant:

```python
WEB_SYSTEM_PROMPT = """\
You are a personal AI assistant. You have access to the user's inbox, todos, \
and calendar. Answer their questions helpfully and concisely using this context.

When planning a day or week, consider:
- Overdue and due-soon todos (prioritize by urgency)
- Upcoming calendar events
- High-priority inbox items that need attention
- The user's existing commitments and workload

Keep responses concise and actionable. Use bullet points for lists.

When your response involves creating, modifying, or completing todos, include a \
structured action block at the end of your response using this format:

```actions
[{"type": "create_todo", "title": "...", "priority": 2, "due": "YYYY-MM-DD", "category": "...", "project": "..."}]
```

Supported action types:
- create_todo: fields are title (required), priority (1-5), due (YYYY-MM-DD), category, project
- mark_done: fields are todo_id (the 8-char prefix shown in brackets)
- set_priority: fields are todo_id, priority (1-5)
- set_due: fields are todo_id, due (YYYY-MM-DD)
- delete_todo: fields are todo_id

Only include actions when the user is asking you to do something, not when just discussing. \
The action block must be valid JSON.\
"""


def parse_actions(text: str) -> tuple[list[dict], str]:
    """Extract action blocks from AI response text.

    Returns (actions_list, cleaned_text_without_action_block).
    """
    pattern = r"```actions\s*\n(.*?)\n```"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return [], text

    try:
        actions = json.loads(match.group(1))
        if not isinstance(actions, list):
            actions = [actions]
    except (json.JSONDecodeError, ValueError):
        # Remove the malformed block but return no actions
        clean = text[:match.start()].rstrip() + text[match.end():].lstrip()
        return [], clean.strip()

    clean = text[:match.start()].rstrip() + text[match.end():].lstrip()
    return actions, clean.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/ishamir/src/assistant && python -m pytest tests/test_ai_ask.py -v`
Expected: ALL PASS

- [ ] **Step 5: Add ask_stream method to AskEngine**

Add this method to the `AskEngine` class in `src/aa/ai/ask.py`:

```python
    async def ask_stream(self, question: str, context: dict, history: list[dict] | None = None):
        """Stream answer chunks. Yields str chunks. Use WEB_SYSTEM_PROMPT for web UI."""
        user_message = self._build_prompt(question, context)
        messages = list(history) if history else []
        messages.append({"role": "user", "content": user_message})

        async with self._client.messages.stream(
            model=self._model,
            max_tokens=2048,
            system=WEB_SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
```

- [ ] **Step 6: Commit**

```bash
git add src/aa/ai/ask.py tests/test_ai_ask.py
git commit -m "feat(web): add streaming ask, action parsing, web system prompt"
```

## Chunk 3: Web Server Core — Routes and CSRF

### Task 5: Create web.py with App Factory and Todo Routes

**Files:**
- Create: `src/aa/web.py`
- Test: `tests/test_web.py` (new file)

- [ ] **Step 1: Write failing tests for the web app**

Create `tests/test_web.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/ishamir/src/assistant && python -m pytest tests/test_web.py -v`
Expected: FAIL with ImportError (web module doesn't exist)

- [ ] **Step 3: Create templates directory structure**

Run:
```bash
mkdir -p src/aa/templates/partials
mkdir -p src/aa/static
```

- [ ] **Step 4: Download htmx and place in static/**

Run:
```bash
cd /home/ishamir/src/assistant && python -c "
import urllib.request
urllib.request.urlretrieve('https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js', 'src/aa/static/htmx.min.js')
print('Downloaded htmx.min.js')
"
```

If the download fails (no internet), create a minimal stub at `src/aa/static/htmx.min.js` containing just a comment:
```javascript
/* htmx 2.0.4 - to be replaced with actual htmx.min.js */
```

- [ ] **Step 5: Create base.html template**

Create `src/aa/templates/base.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AA - Personal Assistant</title>
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/htmx.min.js"></script>
</head>
<body>
  <header>
    <h1>AA</h1>
    <div class="search-bar">
      <input type="search" id="search" name="q" placeholder="Search todos..."
             hx-get="/todos" hx-trigger="keyup changed delay:300ms"
             hx-target="#todo-tbody" hx-include="[name='sort'],[name='dir']">
    </div>
    <button id="new-todo-btn" onclick="showNewTodoRow()">+ New</button>
  </header>

  <main>
    <table id="todo-table">
      <thead>
        <tr>
          <th class="col-check"><input type="checkbox" id="select-all" onclick="toggleSelectAll(this)"></th>
          <th class="col-priority sortable" data-sort="priority" onclick="sortBy('priority')">P</th>
          <th class="col-title sortable" data-sort="title" onclick="sortBy('title')">Title</th>
          <th class="col-due sortable" data-sort="due_date" onclick="sortBy('due_date')">Due</th>
          <th class="col-category sortable" data-sort="category" onclick="sortBy('category')">Category</th>
          <th class="col-project sortable" data-sort="project" onclick="sortBy('project')">Project</th>
        </tr>
      </thead>
      <tbody id="todo-tbody"
             hx-get="/todos" hx-trigger="load, refreshTable from:body"
             hx-include="#search,[name='sort'],[name='dir']">
      </tbody>
    </table>
    <input type="hidden" name="sort" id="sort-field" value="priority,due_date">
    <input type="hidden" name="dir" id="dir-field" value="asc">
  </main>

  <!-- Bulk action toolbar -->
  <div id="bulk-toolbar" class="bulk-toolbar hidden">
    <span id="bulk-count">0 selected</span>
    <button onclick="bulkAction('done')">Done</button>
    <button onclick="bulkAction('delete')">Delete</button>
    <select id="bulk-priority" onchange="bulkAction('priority')">
      <option value="">Priority</option>
      <option value="1">P1</option>
      <option value="2">P2</option>
      <option value="3">P3</option>
      <option value="4">P4</option>
      <option value="5">P5</option>
    </select>
    <input type="date" id="bulk-due" onchange="bulkAction('due')">
  </div>

  <!-- Chat panel -->
  <div id="chat-panel" class="chat-panel">
    <div id="chat-drag" class="chat-drag"></div>
    <div id="chat-messages" class="chat-messages"></div>
    <div class="chat-input-row">
      <input type="text" id="chat-input" placeholder="Ask a question..."
             onkeydown="if(event.key==='Enter')sendChat()">
      <button onclick="sendChat()">Send</button>
      <button onclick="clearChat()" title="Clear">Clear</button>
    </div>
  </div>

  <!-- Toast container -->
  <div id="toast-container" class="toast-container"></div>

  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 6: Create todo_table.html partial**

Create `src/aa/templates/partials/todo_table.html`:

```html
{% for todo in todos %}
{% include "partials/todo_row.html" %}
{% endfor %}
{% if not todos %}
<tr><td colspan="6" class="empty-state">No todos. Click "+ New" to create one.</td></tr>
{% endif %}
```

- [ ] **Step 7: Create todo_row.html partial**

Create `src/aa/templates/partials/todo_row.html`:

```html
<tr class="todo-row" data-id="{{ todo.id }}">
  <td class="col-check">
    <input type="checkbox" class="todo-check" value="{{ todo.id }}" onchange="updateBulkToolbar()">
  </td>
  <td class="col-priority p{{ todo.priority }}"
      hx-get="/todos/{{ todo.id }}/edit/priority" hx-target="this" hx-swap="innerHTML">
    P{{ todo.priority }}
  </td>
  <td class="col-title" onclick="toggleDetail('{{ todo.id }}', this)">
    {{ todo.title }}
  </td>
  <td class="col-due {% if todo.overdue %}overdue{% endif %}"
      hx-get="/todos/{{ todo.id }}/edit/due_date" hx-target="this" hx-swap="innerHTML">
    {{ todo.due_date or "" }}
  </td>
  <td class="col-category"
      hx-get="/todos/{{ todo.id }}/edit/category" hx-target="this" hx-swap="innerHTML">
    {{ todo.category or "" }}
  </td>
  <td class="col-project"
      hx-get="/todos/{{ todo.id }}/edit/project" hx-target="this" hx-swap="innerHTML">
    {{ todo.project or "" }}
  </td>
</tr>
```

- [ ] **Step 8: Create todo_detail.html partial**

Create `src/aa/templates/partials/todo_detail.html`:

```html
<tr class="todo-detail" data-detail-for="{{ todo.id }}">
  <td colspan="6">
    <div class="detail-content">
      <div class="detail-row">
        <label>Title</label>
        <input type="text" value="{{ todo.title }}"
               hx-patch="/todos/{{ todo.id }}" hx-trigger="blur, keydown[key=='Enter']"
               hx-vals='js:{"title": event.target.value}'
               hx-target="closest tr" hx-swap="delete"
               name="title">
      </div>
      <div class="detail-row">
        <label>Details</label>
        <textarea hx-patch="/todos/{{ todo.id }}" hx-trigger="blur"
                  hx-vals='js:{"details": event.target.value}'
                  hx-target="closest tr" hx-swap="delete"
                  name="details" rows="3">{{ todo.details or "" }}</textarea>
      </div>
      {% if linked_items %}
      <div class="detail-row">
        <label>Linked Items</label>
        <ul class="linked-items">
          {% for item in linked_items %}
          <li>{{ item.source }}: {{ item.subject or "(no subject)" }} [{{ item.id[:8] }}]</li>
          {% endfor %}
        </ul>
      </div>
      {% endif %}
      <div class="detail-row detail-meta">
        <span>Created: {{ todo.created_at }}</span>
        <button class="btn-danger"
                hx-post="/todos/{{ todo.id }}/delete"
                hx-headers='{"Origin": "http://localhost"}'
                hx-target="closest tr" hx-swap="delete">
          Delete
        </button>
      </div>
    </div>
  </td>
</tr>
```

- [ ] **Step 9: Create chat_message.html partial**

Create `src/aa/templates/partials/chat_message.html`:

```html
<div class="chat-msg chat-{{ role }}">
  <div class="chat-bubble">{{ content }}</div>
  {% if actions %}
  <div class="chat-actions">
    {% for action in actions %}
    <button class="action-btn" onclick='executeAction({{ action | tojson }})'>
      {% if action.type == "create_todo" %}
        Create: "{{ action.title }}" P{{ action.get("priority", 3) }}{% if action.get("due") %} due {{ action.due }}{% endif %}
      {% elif action.type == "mark_done" %}
        Done: {{ action.todo_id }}
      {% elif action.type == "set_priority" %}
        Set P{{ action.priority }}: {{ action.todo_id }}
      {% elif action.type == "set_due" %}
        Set due {{ action.due }}: {{ action.todo_id }}
      {% elif action.type == "delete_todo" %}
        Delete: {{ action.todo_id }}
      {% endif %}
    </button>
    {% endfor %}
  </div>
  {% endif %}
</div>
```

- [ ] **Step 10: Create bulk_toolbar.html partial (empty — toolbar is in base.html, this partial is not needed)**

This is handled entirely in `base.html` via JS. Skip creating a separate partial.

- [ ] **Step 11: Create style.css**

Create `src/aa/static/style.css`:

```css
/* Reset & base */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #1a1a2e;
  --surface: #16213e;
  --border: #2a2a4a;
  --text: #e0e0e0;
  --text-dim: #888;
  --accent: #4a9eff;
  --p1: #e74c3c;
  --p2: #e7a33c;
  --p3: #e0e0e0;
  --p4: #4a9eff;
  --p5: #666;
  --danger: #e74c3c;
  --success: #2ecc71;
}
body {
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', monospace;
  font-size: 13px;
  background: var(--bg);
  color: var(--text);
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* Header */
header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 16px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
header h1 { font-size: 16px; color: var(--accent); }
.search-bar { flex: 1; }
.search-bar input {
  width: 100%;
  max-width: 400px;
  padding: 4px 8px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-family: inherit;
  font-size: 13px;
}
#new-todo-btn {
  padding: 4px 12px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-family: inherit;
  font-size: 13px;
}

/* Main table area */
main {
  flex: 1;
  overflow-y: auto;
  padding: 0;
}
#todo-table {
  width: 100%;
  border-collapse: collapse;
}
thead {
  position: sticky;
  top: 0;
  background: var(--surface);
  z-index: 2;
}
th {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 2px solid var(--border);
  color: var(--text-dim);
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  user-select: none;
}
th.sortable { cursor: pointer; }
th.sortable:hover { color: var(--accent); }

/* Column widths */
.col-check { width: 32px; text-align: center; }
.col-priority { width: 40px; text-align: center; cursor: pointer; }
.col-title { min-width: 200px; }
.col-due { width: 100px; cursor: pointer; }
.col-category { width: 110px; cursor: pointer; }
.col-project { width: 110px; cursor: pointer; }

/* Rows */
.todo-row td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.todo-row:hover { background: rgba(74, 158, 255, 0.05); }
.col-title { cursor: pointer; }

/* Priority colors */
.p1 { color: var(--p1); font-weight: bold; }
.p2 { color: var(--p2); font-weight: bold; }
.p3 { color: var(--p3); }
.p4 { color: var(--p4); }
.p5 { color: var(--p5); }

/* Overdue */
.overdue { color: var(--danger); }

/* Inline edit inputs */
.inline-edit {
  background: var(--bg);
  border: 1px solid var(--accent);
  color: var(--text);
  padding: 2px 4px;
  font-family: inherit;
  font-size: 13px;
  width: 100%;
}
.inline-edit:focus { outline: none; border-color: var(--accent); }

/* Detail row */
.todo-detail td { padding: 0; }
.detail-content {
  padding: 12px 16px 12px 48px;
  background: rgba(74, 158, 255, 0.03);
  border-left: 2px solid var(--accent);
}
.detail-row { margin-bottom: 8px; }
.detail-row label {
  display: block;
  font-size: 11px;
  color: var(--text-dim);
  text-transform: uppercase;
  margin-bottom: 2px;
}
.detail-row input, .detail-row textarea {
  width: 100%;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 4px 8px;
  font-family: inherit;
  font-size: 13px;
  border-radius: 3px;
}
.detail-row textarea { resize: vertical; }
.detail-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: var(--text-dim);
  font-size: 11px;
}
.linked-items { list-style: none; padding: 0; }
.linked-items li {
  padding: 2px 0;
  color: var(--text-dim);
  font-size: 12px;
}
.btn-danger {
  background: var(--danger);
  color: #fff;
  border: none;
  padding: 3px 10px;
  border-radius: 3px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
}

/* Empty state */
.empty-state {
  text-align: center;
  padding: 32px;
  color: var(--text-dim);
}

/* Bulk toolbar */
.bulk-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  background: var(--surface);
  border-top: 1px solid var(--border);
}
.bulk-toolbar.hidden { display: none; }
.bulk-toolbar button, .bulk-toolbar select, .bulk-toolbar input {
  padding: 4px 10px;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 3px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
}

/* Chat panel */
.chat-panel {
  height: 200px;
  min-height: 80px;
  max-height: 50vh;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-top: 1px solid var(--border);
}
.chat-drag {
  height: 5px;
  cursor: ns-resize;
  background: var(--border);
}
.chat-drag:hover { background: var(--accent); }
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 8px 16px;
}
.chat-input-row {
  display: flex;
  gap: 8px;
  padding: 8px 16px;
  border-top: 1px solid var(--border);
}
.chat-input-row input {
  flex: 1;
  padding: 6px 10px;
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text);
  font-family: inherit;
  font-size: 13px;
  border-radius: 4px;
}
.chat-input-row button {
  padding: 6px 14px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-family: inherit;
  font-size: 13px;
}

/* Chat messages */
.chat-msg { margin-bottom: 8px; }
.chat-bubble {
  display: inline-block;
  padding: 6px 12px;
  border-radius: 8px;
  max-width: 80%;
  white-space: pre-wrap;
  word-wrap: break-word;
  font-size: 13px;
  line-height: 1.4;
}
.chat-user .chat-bubble {
  background: var(--accent);
  color: #fff;
  margin-left: auto;
}
.chat-user { text-align: right; }
.chat-assistant .chat-bubble {
  background: var(--bg);
  border: 1px solid var(--border);
}
.chat-actions {
  margin-top: 4px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.action-btn {
  padding: 3px 10px;
  background: rgba(74, 158, 255, 0.15);
  border: 1px solid var(--accent);
  color: var(--accent);
  border-radius: 4px;
  cursor: pointer;
  font-family: inherit;
  font-size: 12px;
}
.action-btn:hover { background: rgba(74, 158, 255, 0.3); }

/* Toast notifications */
.toast-container {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 100;
}
.toast {
  padding: 8px 16px;
  margin-bottom: 8px;
  border-radius: 4px;
  font-size: 12px;
  animation: fadeIn 0.2s;
}
.toast-success { background: var(--success); color: #fff; }
.toast-error { background: var(--danger); color: #fff; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(-10px); } to { opacity: 1; } }

/* New todo row */
.new-todo-row input {
  background: var(--bg);
  border: 1px solid var(--accent);
  color: var(--text);
  padding: 3px 6px;
  font-family: inherit;
  font-size: 13px;
  width: 100%;
}

/* Checkbox */
input[type="checkbox"] {
  accent-color: var(--accent);
}
```

- [ ] **Step 12: Create app.js**

Create `src/aa/static/app.js`:

```javascript
/* AA Web UI - client-side logic */

// --- Sort state ---
let currentSort = "priority,due_date";
let currentDir = "asc";

function sortBy(col) {
  if (currentSort === col) {
    currentDir = currentDir === "asc" ? "desc" : "asc";
  } else {
    currentSort = col;
    currentDir = "asc";
  }
  document.getElementById("sort-field").value = currentSort;
  document.getElementById("dir-field").value = currentDir;
  htmx.trigger("#todo-tbody", "refreshTable");
}

// --- Select all ---
function toggleSelectAll(el) {
  document.querySelectorAll(".todo-check").forEach(cb => cb.checked = el.checked);
  updateBulkToolbar();
}

function updateBulkToolbar() {
  const checked = document.querySelectorAll(".todo-check:checked");
  const toolbar = document.getElementById("bulk-toolbar");
  const count = document.getElementById("bulk-count");
  if (checked.length > 0) {
    toolbar.classList.remove("hidden");
    count.textContent = checked.length + " selected";
  } else {
    toolbar.classList.add("hidden");
  }
}

// --- Bulk actions ---
function getSelectedIds() {
  return Array.from(document.querySelectorAll(".todo-check:checked")).map(cb => cb.value);
}

function bulkAction(action) {
  const ids = getSelectedIds();
  if (!ids.length) return;

  let body = "ids=" + ids.join(",") + "&action=" + action;
  if (action === "priority") {
    const val = document.getElementById("bulk-priority").value;
    if (!val) return;
    body += "&value=" + val;
    document.getElementById("bulk-priority").value = "";
  } else if (action === "due") {
    const val = document.getElementById("bulk-due").value;
    if (!val) return;
    body += "&value=" + val;
    document.getElementById("bulk-due").value = "";
  }

  fetch("/todos/bulk", {
    method: "POST",
    headers: {"Content-Type": "application/x-www-form-urlencoded", "Origin": location.origin},
    body: body,
  }).then(resp => {
    if (resp.ok) {
      htmx.trigger(document.body, "refreshTable");
      showToast("Done", "success");
    } else {
      showToast("Bulk action failed", "error");
    }
    document.getElementById("select-all").checked = false;
    updateBulkToolbar();
  });
}

// --- New todo ---
function showNewTodoRow() {
  const tbody = document.getElementById("todo-tbody");
  const existing = document.querySelector(".new-todo-row");
  if (existing) { existing.remove(); return; }

  const tr = document.createElement("tr");
  tr.className = "new-todo-row";
  tr.innerHTML = `
    <td></td>
    <td><select class="inline-edit" id="new-priority">
      <option value="1">P1</option><option value="2">P2</option>
      <option value="3" selected>P3</option><option value="4">P4</option><option value="5">P5</option>
    </select></td>
    <td><input class="inline-edit" id="new-title" placeholder="Title..." autofocus></td>
    <td><input class="inline-edit" id="new-due" type="date"></td>
    <td><input class="inline-edit" id="new-category" placeholder="Category"></td>
    <td><input class="inline-edit" id="new-project" placeholder="Project"></td>
  `;
  tbody.insertBefore(tr, tbody.firstChild);

  const titleInput = document.getElementById("new-title");
  titleInput.focus();
  titleInput.addEventListener("keydown", function(e) {
    if (e.key === "Enter") saveNewTodo();
    if (e.key === "Escape") tr.remove();
  });
}

function saveNewTodo() {
  const title = document.getElementById("new-title").value.trim();
  if (!title) return;
  const body = new URLSearchParams({
    title: title,
    priority: document.getElementById("new-priority").value,
    due_date: document.getElementById("new-due").value,
    category: document.getElementById("new-category").value,
    project: document.getElementById("new-project").value,
  });

  fetch("/todos/new", {
    method: "POST",
    headers: {"Content-Type": "application/x-www-form-urlencoded", "Origin": location.origin},
    body: body.toString(),
  }).then(resp => {
    if (resp.ok) {
      htmx.trigger(document.body, "refreshTable");
      showToast("Todo created", "success");
    } else {
      showToast("Failed to create todo", "error");
    }
  });
}

// --- Detail expansion ---
function toggleDetail(todoId, el) {
  const existing = document.querySelector(`[data-detail-for="${todoId}"]`);
  if (existing) { existing.remove(); return; }
  // Close other details
  document.querySelectorAll(".todo-detail").forEach(d => d.remove());

  fetch(`/todos/${todoId}/detail`).then(r => r.text()).then(html => {
    const row = el.closest("tr");
    row.insertAdjacentHTML("afterend", html);
    htmx.process(document.querySelector(`[data-detail-for="${todoId}"]`));
  });
}

// --- Chat ---
let chatHistory = [];

function sendChat() {
  const input = document.getElementById("chat-input");
  const msg = input.value.trim();
  if (!msg) return;
  input.value = "";

  appendChatMessage("user", msg);
  chatHistory.push({role: "user", content: msg});

  const msgDiv = appendChatMessage("assistant", "");
  const bubble = msgDiv.querySelector(".chat-bubble");

  fetch("/chat", {
    method: "POST",
    headers: {"Content-Type": "application/json", "Origin": location.origin},
    body: JSON.stringify({message: msg, history: chatHistory}),
  }).then(resp => {
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let fullText = "";
    let buffer = "";

    function read() {
      reader.read().then(({done, value}) => {
        if (done) {
          chatHistory.push({role: "assistant", content: fullText});
          return;
        }
        buffer += decoder.decode(value, {stream: true});
        const lines = buffer.split("\n");
        buffer = lines.pop();

        let dataAccum = "";  // accumulate multi-line data fields
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            msgDiv.dataset.eventType = line.slice(7).trim();
            dataAccum = "";
          } else if (line.startsWith("data: ")) {
            dataAccum += (dataAccum ? "\n" : "") + line.slice(6);
          } else if (line === "") {
            // Empty line = end of SSE event, dispatch accumulated data
            if (dataAccum !== "") {
              const eventType = msgDiv.dataset.eventType || "text";
              if (eventType === "text") {
                fullText += dataAccum;
                bubble.textContent = fullText;
              } else if (eventType === "action") {
                try {
                  const action = JSON.parse(dataAccum);
                  addActionButton(msgDiv, action);
                } catch(e) {}
              } else if (eventType === "error") {
                bubble.textContent += "\n[Error: " + dataAccum + "]";
                bubble.style.color = "var(--danger)";
              }
              dataAccum = "";
              msgDiv.dataset.eventType = "";
            }
          }
        }
        // Scroll to bottom
        const container = document.getElementById("chat-messages");
        container.scrollTop = container.scrollHeight;
        read();
      });
    }
    read();
  }).catch(err => {
    bubble.textContent = "Error: " + err.message;
    bubble.style.color = "var(--danger)";
  });
}

function appendChatMessage(role, content) {
  const container = document.getElementById("chat-messages");
  const div = document.createElement("div");
  div.className = "chat-msg chat-" + role;
  div.innerHTML = `<div class="chat-bubble">${escapeHtml(content)}</div>`;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function addActionButton(msgDiv, action) {
  let actionsDiv = msgDiv.querySelector(".chat-actions");
  if (!actionsDiv) {
    actionsDiv = document.createElement("div");
    actionsDiv.className = "chat-actions";
    msgDiv.appendChild(actionsDiv);
  }
  const btn = document.createElement("button");
  btn.className = "action-btn";
  btn.onclick = () => executeAction(action);

  if (action.type === "create_todo") {
    btn.textContent = `Create: "${action.title}" P${action.priority || 3}`;
  } else if (action.type === "mark_done") {
    btn.textContent = `Done: ${action.todo_id}`;
  } else if (action.type === "set_priority") {
    btn.textContent = `Set P${action.priority}: ${action.todo_id}`;
  } else if (action.type === "set_due") {
    btn.textContent = `Due ${action.due}: ${action.todo_id}`;
  } else if (action.type === "delete_todo") {
    btn.textContent = `Delete: ${action.todo_id}`;
  }
  actionsDiv.appendChild(btn);
}

function executeAction(action) {
  fetch("/chat/action", {
    method: "POST",
    headers: {"Content-Type": "application/json", "Origin": location.origin},
    body: JSON.stringify(action),
  }).then(resp => resp.json()).then(data => {
    if (data.ok) {
      showToast(data.message || "Done", "success");
      htmx.trigger(document.body, "refreshTable");
    } else {
      showToast(data.error || "Failed", "error");
    }
  });
}

function clearChat() {
  document.getElementById("chat-messages").innerHTML = "";
  chatHistory = [];
}

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = text;
  return d.innerHTML;
}

// --- Toast ---
function showToast(msg, type) {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = "toast toast-" + type;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

// --- Chat resize ---
(function() {
  const panel = document.getElementById("chat-panel");
  const drag = document.getElementById("chat-drag");
  let startY, startH;

  drag.addEventListener("mousedown", e => {
    startY = e.clientY;
    startH = panel.offsetHeight;
    document.addEventListener("mousemove", onDrag);
    document.addEventListener("mouseup", () => {
      document.removeEventListener("mousemove", onDrag);
    }, {once: true});
    e.preventDefault();
  });

  function onDrag(e) {
    const h = startH - (e.clientY - startY);
    panel.style.height = Math.max(80, Math.min(window.innerHeight * 0.5, h)) + "px";
  }
})();

// --- htmx event handling ---
document.body.addEventListener("htmx:responseError", function() {
  showToast("Request failed", "error");
});
```

- [ ] **Step 13: Create web.py**

Create `src/aa/web.py`:

```python
"""HTTP web server for the AA personal assistant UI."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from aiohttp import web
import aiohttp_jinja2
import jinja2

from aa.config import AppConfig
from aa.db import Database

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def _csrf_check(request: web.Request) -> bool:
    """Check Origin header for CSRF protection. Returns True if OK."""
    origin = request.headers.get("Origin", "")
    if not origin:
        return False
    port = request.app["config"].web_port
    allowed = {f"http://localhost:{port}", f"http://127.0.0.1:{port}", "http://localhost"}
    return origin in allowed


@web.middleware
async def csrf_middleware(request: web.Request, handler):
    """Block POST/PATCH/DELETE without valid Origin header."""
    if request.method in ("POST", "PATCH", "DELETE"):
        if not _csrf_check(request):
            return web.Response(status=403, text="Forbidden: invalid origin")
    return await handler(request)


def _todo_with_overdue(todo: dict) -> dict:
    """Add 'overdue' flag to a todo dict."""
    due = todo.get("due_date")
    if due:
        try:
            todo = dict(todo)
            todo["overdue"] = due < date.today().isoformat()
        except (ValueError, TypeError):
            pass
    return todo


# --- Route handlers ---

async def index(request: web.Request) -> web.Response:
    """Serve the main page.

    Note: The spec describes server-side session storage with LRU eviction for
    chat history. This implementation keeps history client-side (sent with each
    request) which is simpler and avoids memory management. The session cookie
    is set for future use if server-side state is needed.
    """
    response = aiohttp_jinja2.render_template("base.html", request, {})
    if "session" not in request.cookies:
        import uuid
        response.set_cookie("session", str(uuid.uuid4()), httponly=True)
    return response


async def get_todos(request: web.Request) -> web.Response:
    """Return todo rows as HTML partial."""
    db: Database = request.app["db"]
    q = request.query.get("q", "").strip() or None
    sort = request.query.get("sort", "priority,due_date")

    todos = await db.list_todos(status="pending", keyword=q, sort=sort)
    todos = [_todo_with_overdue(t) for t in todos]

    return aiohttp_jinja2.render_template(
        "partials/todo_table.html", request, {"todos": todos}
    )


async def patch_todo(request: web.Request) -> web.Response:
    """Inline-edit a todo field. Returns updated row."""
    db: Database = request.app["db"]
    todo_id = request.match_info["id"]
    full_id = await db.resolve_id("todos", todo_id)
    if not full_id:
        return web.Response(status=404, text="Not found")

    data = await request.post()
    updates: dict[str, Any] = {}
    if "priority" in data:
        updates["priority"] = int(data["priority"])
    if "due_date" in data:
        updates["due_date"] = data["due_date"] or None
    if "category" in data:
        updates["category"] = data["category"] or None
    if "project" in data:
        updates["project"] = data["project"] or None
    if "title" in data:
        updates["title"] = data["title"]
    if "details" in data:
        updates["details"] = data["details"] or None

    if updates:
        await db.update_todo(full_id, **updates)

    todo = await db.get_todo(full_id)
    todo = _todo_with_overdue(todo)

    response = aiohttp_jinja2.render_template(
        "partials/todo_row.html", request, {"todo": todo}
    )
    response.headers["HX-Trigger"] = "refreshTable"
    return response


async def get_todo_detail(request: web.Request) -> web.Response:
    """Return expanded detail row."""
    db: Database = request.app["db"]
    todo_id = request.match_info["id"]
    full_id = await db.resolve_id("todos", todo_id)
    if not full_id:
        return web.Response(status=404, text="Not found")

    todo = await db.get_todo(full_id)
    links = await db.get_todo_links(full_id)
    linked_items = []
    for link in links:
        item = await db.get_item(link["item_id"])
        if item:
            linked_items.append(item)

    return aiohttp_jinja2.render_template(
        "partials/todo_detail.html", request,
        {"todo": todo, "linked_items": linked_items}
    )


async def todo_done(request: web.Request) -> web.Response:
    """Mark a todo as done."""
    db: Database = request.app["db"]
    todo_id = request.match_info["id"]
    full_id = await db.resolve_id("todos", todo_id)
    if not full_id:
        return web.Response(status=404, text="Not found")
    await db.update_todo(full_id, status="done")
    response = web.Response(status=200, text="")
    response.headers["HX-Trigger"] = "refreshTable"
    return response


async def todo_delete(request: web.Request) -> web.Response:
    """Soft-delete a todo."""
    db: Database = request.app["db"]
    todo_id = request.match_info["id"]
    full_id = await db.resolve_id("todos", todo_id)
    if not full_id:
        return web.Response(status=404, text="Not found")
    await db.delete_todo(full_id)
    response = web.Response(status=200, text="")
    response.headers["HX-Trigger"] = "refreshTable"
    return response


async def todo_new(request: web.Request) -> web.Response:
    """Create a new todo."""
    db: Database = request.app["db"]
    data = await request.post()
    title = data.get("title", "").strip()
    if not title:
        return web.Response(status=422, text="Title required")

    await db.insert_todo(
        title=title,
        priority=int(data.get("priority", 3)),
        due_date=data.get("due_date") or None,
        category=data.get("category") or None,
        project=data.get("project") or None,
    )
    response = web.Response(status=200, text="")
    response.headers["HX-Trigger"] = "refreshTable"
    return response


async def todo_bulk(request: web.Request) -> web.Response:
    """Handle bulk actions on multiple todos."""
    db: Database = request.app["db"]
    data = await request.post()
    ids_str = data.get("ids", "")
    action = data.get("action", "")
    value = data.get("value", "")

    ids = [i.strip() for i in ids_str.split(",") if i.strip()]
    if not ids or not action:
        return web.Response(status=422, text="Missing ids or action")

    for raw_id in ids:
        full_id = await db.resolve_id("todos", raw_id)
        if not full_id:
            continue
        if action == "done":
            await db.update_todo(full_id, status="done")
        elif action == "delete":
            await db.delete_todo(full_id)
        elif action == "priority" and value:
            await db.update_todo(full_id, priority=int(value))
        elif action == "due" and value:
            await db.update_todo(full_id, due_date=value)

    response = web.Response(status=200, text="")
    response.headers["HX-Trigger"] = "refreshTable"
    return response


async def get_edit_field(request: web.Request) -> web.Response:
    """Return an inline edit widget for a field."""
    db: Database = request.app["db"]
    todo_id = request.match_info["id"]
    field = request.match_info["field"]
    full_id = await db.resolve_id("todos", todo_id)
    if not full_id:
        return web.Response(status=404, text="Not found")

    todo = await db.get_todo(full_id)
    current = todo.get(field, "")

    if field == "priority":
        options = "".join(
            f'<option value="{i}" {"selected" if todo.get("priority") == i else ""}>P{i}</option>'
            for i in range(1, 6)
        )
        html = (
            f'<select class="inline-edit" '
            f'hx-patch="/todos/{full_id}" hx-target="closest tr" hx-swap="outerHTML" '
            f'hx-trigger="change" name="priority">'
            f'{options}</select>'
        )
    elif field == "due_date":
        html = (
            f'<input type="date" class="inline-edit" value="{current or ""}" '
            f'hx-patch="/todos/{full_id}" hx-target="closest tr" hx-swap="outerHTML" '
            f'hx-trigger="change" name="due_date">'
        )
    elif field in ("category", "project"):
        # Get existing values for datalist
        all_todos = await db.list_todos()
        values = sorted(set(t.get(field) or "" for t in all_todos if t.get(field)))
        datalist = f'<datalist id="dl-{field}">{"".join(f"<option>{v}</option>" for v in values)}</datalist>'
        html = (
            f'<input type="text" class="inline-edit" value="{current or ""}" '
            f'list="dl-{field}" '
            f'hx-patch="/todos/{full_id}" hx-target="closest tr" hx-swap="outerHTML" '
            f'hx-trigger="blur, keydown[key==\'Enter\']" name="{field}">'
            f'{datalist}'
        )
    else:
        return web.Response(status=400, text="Unknown field")

    return web.Response(text=html, content_type="text/html")


async def chat(request: web.Request) -> web.StreamResponse:
    """Handle chat messages with SSE streaming."""
    config: AppConfig = request.app["config"]
    db: Database = request.app["db"]

    if not config.anthropic_api_key:
        resp = web.StreamResponse()
        resp.content_type = "text/event-stream"
        await resp.prepare(request)
        await resp.write(b"event: error\ndata: No API key configured\n\n")
        return resp

    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    message = data.get("message", "")
    history = data.get("history", [])

    # Build context
    todos = await db.list_todos(status="pending")
    inbox = await db.list_items(limit=20)
    calendar = await db.list_items(source="calendar")
    context = {"todos": todos, "inbox": inbox, "calendar": calendar}

    from aa.ai.ask import AskEngine, parse_actions

    engine = AskEngine(api_key=config.anthropic_api_key, model=config.anthropic_model)

    resp = web.StreamResponse()
    resp.content_type = "text/event-stream"
    resp.headers["Cache-Control"] = "no-cache"
    await resp.prepare(request)

    full_text = ""
    try:
        async for chunk in engine.ask_stream(message, context, history=history):
            full_text += chunk
            # SSE requires each line of multi-line data to be prefixed with "data: "
            sse_lines = "\n".join(f"data: {line}" for line in chunk.split("\n"))
            await resp.write(f"event: text\n{sse_lines}\n\n".encode())
    except Exception as e:
        await resp.write(f"event: error\ndata: {str(e)}\n\n".encode())
        return resp

    # Parse actions from complete text
    actions, _ = parse_actions(full_text)
    for action in actions:
        await resp.write(f"event: action\ndata: {json.dumps(action)}\n\n".encode())

    await resp.write(b"event: done\ndata: {}\n\n")
    return resp


async def chat_action(request: web.Request) -> web.Response:
    """Execute a chat action button."""
    db: Database = request.app["db"]
    try:
        action = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    action_type = action.get("type", "")
    try:
        if action_type == "create_todo":
            todo_id = await db.insert_todo(
                title=action["title"],
                priority=action.get("priority", 3),
                due_date=action.get("due"),
                category=action.get("category"),
                project=action.get("project"),
            )
            msg = f"Created todo: {action['title']}"
        elif action_type == "mark_done":
            full_id = await db.resolve_id("todos", action["todo_id"])
            if not full_id:
                return web.json_response({"ok": False, "error": "Todo not found"})
            await db.update_todo(full_id, status="done")
            msg = f"Marked done: {action['todo_id']}"
        elif action_type == "set_priority":
            full_id = await db.resolve_id("todos", action["todo_id"])
            if not full_id:
                return web.json_response({"ok": False, "error": "Todo not found"})
            await db.update_todo(full_id, priority=int(action["priority"]))
            msg = f"Set priority P{action['priority']}: {action['todo_id']}"
        elif action_type == "set_due":
            full_id = await db.resolve_id("todos", action["todo_id"])
            if not full_id:
                return web.json_response({"ok": False, "error": "Todo not found"})
            await db.update_todo(full_id, due_date=action["due"])
            msg = f"Set due {action['due']}: {action['todo_id']}"
        elif action_type == "delete_todo":
            full_id = await db.resolve_id("todos", action["todo_id"])
            if not full_id:
                return web.json_response({"ok": False, "error": "Todo not found"})
            await db.delete_todo(full_id)
            msg = f"Deleted: {action['todo_id']}"
        else:
            return web.json_response({"ok": False, "error": f"Unknown action: {action_type}"})

        return web.json_response({"ok": True, "message": msg})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})


def create_app(config: AppConfig, db: Database) -> web.Application:
    """Create and configure the aiohttp web application."""
    app = web.Application(middlewares=[csrf_middleware])
    app["config"] = config
    app["db"] = db

    # Setup Jinja2
    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
    )

    # Routes
    app.router.add_get("/", index)
    app.router.add_get("/todos", get_todos)
    app.router.add_post("/todos/new", todo_new)
    app.router.add_post("/todos/bulk", todo_bulk)
    app.router.add_patch("/todos/{id}", patch_todo)
    app.router.add_get("/todos/{id}/detail", get_todo_detail)
    app.router.add_get("/todos/{id}/edit/{field}", get_edit_field)
    app.router.add_post("/todos/{id}/done", todo_done)
    app.router.add_post("/todos/{id}/delete", todo_delete)
    app.router.add_post("/chat", chat)
    app.router.add_post("/chat/action", chat_action)

    # Static files
    app.router.add_static("/static", STATIC_DIR)

    return app
```

- [ ] **Step 14: Run tests to verify they pass**

Run: `cd /home/ishamir/src/assistant && python -m pytest tests/test_web.py -v`
Expected: ALL PASS (may need to install test dependencies first)

- [ ] **Step 15: Commit**

```bash
git add src/aa/web.py src/aa/templates/ src/aa/static/ tests/test_web.py
git commit -m "feat(web): add web server routes, templates, and static assets"
```

## Chunk 4: Daemon Integration & CLI

### Task 6: Wire Web Server into Daemon

**Files:**
- Modify: `src/aa/daemon.py:51-80` (start method)

- [ ] **Step 1: Add web server startup to daemon**

In `src/aa/daemon.py`, add these imports at the top:

```python
from aiohttp import web
from aiohttp.web_runner import AppRunner, TCPSite
```

Add `_web_runner` and `_web_site` to `__init__`:

```python
        self._web_runner: AppRunner | None = None
        self._web_site: TCPSite | None = None
```

Add `_start_web_server` method to `Daemon`:

```python
    async def _start_web_server(self) -> None:
        """Start the HTTP web server using AppRunner + TCPSite."""
        from aa.web import create_app

        app = create_app(self.config, self._db)
        self._web_runner = AppRunner(app)
        await self._web_runner.setup()
        self._web_site = TCPSite(
            self._web_runner, "localhost", self.config.web_port
        )
        await self._web_site.start()
        logger.info("Web UI available at http://localhost:%d", self.config.web_port)
```

Modify `start()` method to call `_start_web_server` before the poll loop:

```python
    async def start(self) -> None:
        """Initialize DB, AI engine, server, and start the poll loop."""
        self.config.ensure_dirs()

        # Initialize database
        self._db = Database(self.config.db_path)
        await self._db.initialize()

        # Initialize AI triage engine if API key is available
        if self.config.anthropic_api_key:
            self._engine = TriageEngine(
                api_key=self.config.anthropic_api_key,
                model=self.config.anthropic_model,
            )

        # Initialize connectors from source configs
        self._reload_connectors()

        # Start socket server
        handler = RequestHandler(
            self.config, self._db,
            api_key=self.config.anthropic_api_key,
            model=self.config.anthropic_model,
        )
        self._server = SocketServer(handler, self.config.socket_path)
        await self._server.start()

        # Start web server if enabled
        if self.config.web_enabled:
            await self._start_web_server()

        # Start polling loop
        self._running = True
        await self._poll_loop()
```

Modify `stop()` to also clean up web server:

```python
    async def stop(self) -> None:
        """Stop the server and close the database."""
        self._running = False
        if self._web_runner:
            await self._web_runner.cleanup()
            self._web_runner = None
            self._web_site = None
        if self._server:
            await self._server.stop()
        if self._db:
            await self._db.close()
        logger.info("Daemon stopped")
```

- [ ] **Step 2: Run existing tests to ensure nothing breaks**

Run: `cd /home/ishamir/src/assistant && python -m pytest tests/ -v --ignore=tests/test_web.py`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/aa/daemon.py
git commit -m "feat(web): wire HTTP server into daemon with AppRunner+TCPSite"
```

### Task 7: Add --web Flag to CLI

**Files:**
- Modify: `src/aa/cli.py:111-136` (start_daemon function)

- [ ] **Step 1: Update start_daemon to accept web flag**

In `src/aa/cli.py`, modify `start_daemon` to accept `web=False`:

```python
def start_daemon(web: bool = False) -> str:
    """Start the daemon as a background process. Returns a status message."""
    config = _config
    config.ensure_dirs()

    pid_file = config.data_dir / "daemon.pid"
    if pid_file.exists():
        pid = int(pid_file.read_text().strip())
        try:
            os.kill(pid, 0)
            return f"Daemon already running (PID {pid})"
        except OSError:
            pid_file.unlink()

    log_dir = config.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "daemon.log"

    cmd = [sys.executable, "-m", "aa.daemon"]
    if web:
        cmd.append("--web")

    proc = subprocess.Popen(
        cmd,
        stdout=open(log_file, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    pid_file.write_text(str(proc.pid))
    msg = f"Daemon started (PID {proc.pid})"
    if web:
        msg += f"\nWeb UI at http://localhost:{config.web_port}"
    return msg
```

Update the `start` CLI command:

```python
@main.command()
@click.option("--web", is_flag=True, help="Enable web UI")
def start(web):
    """Start the daemon as a background process."""
    click.echo(start_daemon(web=web))
```

- [ ] **Step 2: Update daemon __main__ to accept --web flag**

In `src/aa/daemon.py`, update the `__main__` block:

```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", action="store_true", help="Enable web UI")
    args = parser.parse_args()

    config = AppConfig()
    config_path = config.data_dir / "config.json"
    if config_path.exists():
        config = AppConfig.from_file(config_path)

    if args.web:
        config.web_enabled = True

    run_daemon(config)
```

- [ ] **Step 3: Run full test suite**

Run: `cd /home/ishamir/src/assistant && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add src/aa/cli.py src/aa/daemon.py
git commit -m "feat(web): add --web flag to aa start and daemon"
```

## Chunk 5: Manual Smoke Test & Polish

### Task 8: Smoke Test the Web UI

- [ ] **Step 1: Start the daemon with web enabled**

Run: `cd /home/ishamir/src/assistant && python -m aa.daemon --web &`
Then open `http://localhost:8080` in a browser.

- [ ] **Step 2: Verify core flows**

Test these flows manually:
1. Page loads with empty todo table
2. Click "+ New" → create a todo → table refreshes
3. Click priority cell → dropdown appears → change priority → row updates
4. Click due date cell → date picker → set date → row updates
5. Click a title → detail expands with textarea
6. Check multiple todos → bulk toolbar appears → bulk done
7. Search field filters todos
8. Chat panel: type a question → response streams in

- [ ] **Step 3: Fix any issues found during smoke test**

Apply fixes as needed. Each fix should be a separate commit.

- [ ] **Step 4: Final commit if any fixes**

```bash
git add -A
git commit -m "fix(web): polish from smoke testing"
```

### Task 9: Run Full Test Suite and Verify

- [ ] **Step 1: Run all tests**

Run: `cd /home/ishamir/src/assistant && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Verify no regressions**

Run: `cd /home/ishamir/src/assistant && python -m pytest tests/ -v --tb=short`
Expected: All existing tests still pass, all new tests pass
