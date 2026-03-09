# AA Personal Assistant Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `aa`, a CLI + daemon that unifies email, calendar, Slack, Mattermost, and notes into a prioritized view powered by Claude API.

**Architecture:** Python CLI (click) communicates with a background daemon via Unix socket. Daemon polls source connectors on intervals, stores items in SQLite, and uses Claude API for triage/prioritization. Feedback loop lets user correct AI and add explicit rules.

**Tech Stack:** Python 3.12+, click, anthropic, SQLite, google-api-python-client, msal, msgraph-sdk, slack-sdk, mattermostdriver, watchdog, uvloop, asyncio

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/aa/__init__.py`
- Create: `src/aa/cli.py`
- Create: `tests/__init__.py`
- Create: `tests/test_cli.py`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "aa"
version = "0.1.0"
description = "Personal AI assistant"
requires-python = ">=3.12"
dependencies = [
    "click>=8.1",
    "anthropic>=0.40",
    "google-api-python-client>=2.0",
    "google-auth>=2.0",
    "google-auth-oauthlib>=1.0",
    "msal>=1.28",
    "msgraph-sdk>=1.0",
    "slack-sdk>=3.27",
    "mattermostdriver>=7.3",
    "watchdog>=4.0",
    "uvloop>=0.19",
    "aiosqlite>=0.20",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5.0",
]

[project.scripts]
aa = "aa.cli:main"
```

**Step 2: Create minimal CLI entry point**

```python
# src/aa/__init__.py
"""AA - Personal AI Assistant."""

# src/aa/cli.py
import click

@click.group()
@click.version_option(version="0.1.0")
def main():
    """AA - Personal AI Assistant."""
    pass

@main.command()
def help():
    """Show available commands."""
    click.echo(main.get_help(click.Context(main)))

if __name__ == "__main__":
    main()
```

**Step 3: Write test**

```python
# tests/test_cli.py
from click.testing import CliRunner
from aa.cli import main

def test_cli_runs():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output

def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
```

**Step 4: Install and run tests**

```bash
pip install -e ".[dev]"
pytest tests/test_cli.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "feat: project scaffolding with minimal CLI"
```

---

### Task 2: SQLite Database Layer

**Files:**
- Create: `src/aa/db.py`
- Create: `tests/test_db.py`

**Step 1: Write failing tests**

```python
# tests/test_db.py
import pytest
import asyncio
from pathlib import Path
from aa.db import Database

@pytest.fixture
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
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_db.py -v
```
Expected: FAIL — module aa.db does not exist

**Step 3: Implement db.py**

```python
# src/aa/db.py
from __future__ import annotations

import aiosqlite
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    source_id       TEXT,
    type            TEXT NOT NULL,
    from_name       TEXT,
    from_address    TEXT,
    subject         TEXT,
    body            TEXT,
    timestamp       DATETIME,
    is_read         BOOLEAN DEFAULT 0,
    is_actionable   BOOLEAN DEFAULT 0,
    priority        INTEGER,
    ai_summary      TEXT,
    ai_suggested_action TEXT,
    raw_json        TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS todos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    description     TEXT,
    priority        INTEGER DEFAULT 3,
    status          TEXT DEFAULT 'pending',
    source          TEXT DEFAULT 'user',
    notes           TEXT,
    due_date        DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at    DATETIME
);

CREATE TABLE IF NOT EXISTS todo_links (
    todo_id         INTEGER REFERENCES todos(id),
    item_id         TEXT REFERENCES items(id),
    PRIMARY KEY (todo_id, item_id)
);

CREATE TABLE IF NOT EXISTS sync_state (
    source          TEXT PRIMARY KEY,
    last_sync       DATETIME,
    cursor          TEXT,
    status          TEXT
);

CREATE TABLE IF NOT EXISTS drafts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         TEXT REFERENCES items(id),
    body            TEXT,
    status          TEXT DEFAULT 'pending',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         TEXT,
    original_priority INTEGER,
    corrected_priority INTEGER,
    original_action TEXT,
    corrected_action TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS triage_rules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rule            TEXT NOT NULL,
    active          BOOLEAN DEFAULT 1,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS config (
    key             TEXT PRIMARY KEY,
    value           TEXT
);
"""


class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self):
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    async def list_tables(self) -> list[str]:
        cursor = await self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        rows = await cursor.fetchall()
        return [row["name"] for row in rows]

    # --- Items ---

    async def insert_item(self, item: dict[str, Any]):
        await self._conn.execute(
            """INSERT OR REPLACE INTO items
            (id, source, source_id, type, from_name, from_address, subject, body, timestamp)
            VALUES (:id, :source, :source_id, :type, :from_name, :from_address, :subject, :body, :timestamp)""",
            item,
        )
        await self._conn.commit()

    async def get_item(self, item_id: str) -> dict | None:
        cursor = await self._conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_untriaged_items(self) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM items WHERE priority IS NULL ORDER BY timestamp DESC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_item_triage(
        self, item_id: str, priority: int, summary: str, action: str
    ):
        await self._conn.execute(
            """UPDATE items SET priority = ?, ai_summary = ?, ai_suggested_action = ?,
            is_actionable = CASE WHEN ? IN ('reply', 'schedule', 'delegate') THEN 1 ELSE 0 END
            WHERE id = ?""",
            (priority, summary, action, action, item_id),
        )
        await self._conn.commit()

    async def list_items(
        self, source: str | None = None, unread_only: bool = False, limit: int = 50
    ) -> list[dict]:
        query = "SELECT * FROM items WHERE 1=1"
        params: list[Any] = []
        if source:
            query += " AND source = ?"
            params.append(source)
        if unread_only:
            query += " AND is_read = 0"
        query += " ORDER BY priority ASC NULLS LAST, timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = await self._conn.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Todos ---

    async def insert_todo(
        self,
        title: str,
        priority: int = 3,
        description: str | None = None,
        source: str = "user",
        notes: str | None = None,
        due_date: str | None = None,
    ) -> int:
        cursor = await self._conn.execute(
            """INSERT INTO todos (title, priority, description, source, notes, due_date)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (title, priority, description, source, notes, due_date),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_todo(self, todo_id: int) -> dict | None:
        cursor = await self._conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_todos(self, include_done: bool = False) -> list[dict]:
        query = "SELECT * FROM todos"
        if not include_done:
            query += " WHERE status != 'done'"
        query += " ORDER BY priority ASC, created_at ASC"
        cursor = await self._conn.execute(query)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_todo(self, todo_id: int, **fields):
        if "status" in fields and fields["status"] == "done":
            fields["completed_at"] = datetime.now(timezone.utc).isoformat()
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values())
        vals.append(todo_id)
        await self._conn.execute(f"UPDATE todos SET {sets} WHERE id = ?", vals)
        await self._conn.commit()

    async def delete_todo(self, todo_id: int):
        await self._conn.execute("DELETE FROM todo_links WHERE todo_id = ?", (todo_id,))
        await self._conn.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        await self._conn.commit()

    async def link_todo(self, todo_id: int, item_id: str):
        await self._conn.execute(
            "INSERT OR IGNORE INTO todo_links (todo_id, item_id) VALUES (?, ?)",
            (todo_id, item_id),
        )
        await self._conn.commit()

    async def get_todo_links(self, todo_id: int) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM todo_links WHERE todo_id = ?", (todo_id,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Drafts ---

    async def insert_draft(self, item_id: str, body: str) -> int:
        cursor = await self._conn.execute(
            "INSERT INTO drafts (item_id, body) VALUES (?, ?)", (item_id, body)
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_draft(self, draft_id: int) -> dict | None:
        cursor = await self._conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_draft(self, draft_id: int, **fields):
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values())
        vals.append(draft_id)
        await self._conn.execute(f"UPDATE drafts SET {sets} WHERE id = ?", vals)
        await self._conn.commit()

    # --- Sync State ---

    async def update_sync_state(self, source: str, cursor: str = "", status: str = "ok"):
        await self._conn.execute(
            """INSERT OR REPLACE INTO sync_state (source, last_sync, cursor, status)
            VALUES (?, ?, ?, ?)""",
            (source, datetime.now(timezone.utc).isoformat(), cursor, status),
        )
        await self._conn.commit()

    async def get_sync_state(self, source: str) -> dict | None:
        cur = await self._conn.execute(
            "SELECT * FROM sync_state WHERE source = ?", (source,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    # --- Feedback ---

    async def insert_feedback(
        self,
        item_id: str,
        original_priority: int,
        corrected_priority: int,
        original_action: str,
        corrected_action: str,
    ) -> int:
        cursor = await self._conn.execute(
            """INSERT INTO feedback
            (item_id, original_priority, corrected_priority, original_action, corrected_action)
            VALUES (?, ?, ?, ?, ?)""",
            (item_id, original_priority, corrected_priority, original_action, corrected_action),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def list_feedback(self, limit: int = 50) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Triage Rules ---

    async def insert_rule(self, rule: str) -> int:
        cursor = await self._conn.execute(
            "INSERT INTO triage_rules (rule) VALUES (?)", (rule,)
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def list_rules(self) -> list[dict]:
        cursor = await self._conn.execute(
            "SELECT * FROM triage_rules WHERE active = 1 ORDER BY created_at ASC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def delete_rule(self, rule_id: int):
        await self._conn.execute("DELETE FROM triage_rules WHERE id = ?", (rule_id,))
        await self._conn.commit()

    # --- Config ---

    async def get_config(self, key: str) -> str | None:
        cursor = await self._conn.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row["value"] if row else None

    async def set_config(self, key: str, value: str):
        await self._conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value)
        )
        await self._conn.commit()
```

**Step 4: Run tests**

```bash
pytest tests/test_db.py -v
```
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/aa/db.py tests/test_db.py
git commit -m "feat: SQLite database layer with full schema and async API"
```

---

### Task 3: Connector Base Class

**Files:**
- Create: `src/aa/connectors/__init__.py`
- Create: `src/aa/connectors/base.py`
- Create: `tests/test_connectors_base.py`

**Step 1: Write failing test**

```python
# tests/test_connectors_base.py
import pytest
from aa.connectors.base import BaseConnector

class MockConnector(BaseConnector):
    source_name = "mock"

    async def authenticate(self):
        self._authenticated = True

    async def fetch_new_items(self, cursor: str | None = None) -> tuple[list[dict], str | None]:
        return [
            {
                "id": "mock-1",
                "source": "mock",
                "source_id": "m1",
                "type": "dm",
                "from_name": "Test",
                "from_address": "test@test.com",
                "subject": "Hi",
                "body": "Hello",
                "timestamp": "2026-03-09T10:00:00",
            }
        ], "cursor-abc"

def test_connector_has_source_name():
    c = MockConnector()
    assert c.source_name == "mock"

@pytest.mark.asyncio
async def test_connector_fetch():
    c = MockConnector()
    items, cursor = await c.fetch_new_items()
    assert len(items) == 1
    assert cursor == "cursor-abc"

def test_base_connector_not_instantiable():
    with pytest.raises(TypeError):
        BaseConnector()
```

**Step 2: Run tests to verify failure**

```bash
pytest tests/test_connectors_base.py -v
```
Expected: FAIL

**Step 3: Implement**

```python
# src/aa/connectors/__init__.py
"""Source connectors for aa."""

# src/aa/connectors/base.py
from __future__ import annotations
from abc import ABC, abstractmethod


class BaseConnector(ABC):
    source_name: str

    @abstractmethod
    async def authenticate(self):
        """Authenticate with the service. Called once at startup."""
        ...

    @abstractmethod
    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        """Fetch new items since cursor. Returns (items, new_cursor)."""
        ...
```

**Step 4: Run tests**

```bash
pytest tests/test_connectors_base.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/aa/connectors/ tests/test_connectors_base.py
git commit -m "feat: base connector abstract class"
```

---

### Task 4: Gmail (Resilio) Connector

**Files:**
- Create: `src/aa/connectors/gmail.py`
- Create: `tests/test_connector_gmail.py`

**Step 1: Write failing test with mocked Google API**

```python
# tests/test_connector_gmail.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aa.connectors.gmail import GmailConnector


@pytest.fixture
def mock_gmail_messages():
    return {
        "messages": [
            {"id": "msg1", "threadId": "t1"},
            {"id": "msg2", "threadId": "t2"},
        ]
    }


@pytest.fixture
def mock_gmail_message_detail():
    return {
        "id": "msg1",
        "threadId": "t1",
        "internalDate": "1741500000000",
        "payload": {
            "headers": [
                {"name": "From", "value": "Alice <alice@resilio.com>"},
                {"name": "Subject", "value": "Q3 Planning"},
            ],
            "body": {"data": "SGVsbG8gd29ybGQ="},  # "Hello world" base64
        },
    }


@pytest.mark.asyncio
async def test_gmail_fetch_new_items(mock_gmail_messages, mock_gmail_message_detail):
    connector = GmailConnector.__new__(GmailConnector)
    connector.source_name = "resilio"

    mock_service = MagicMock()
    messages_resource = MagicMock()
    mock_service.users.return_value.messages.return_value = messages_resource

    list_req = MagicMock()
    list_req.execute.return_value = mock_gmail_messages
    messages_resource.list.return_value = list_req

    get_req = MagicMock()
    get_req.execute.return_value = mock_gmail_message_detail
    messages_resource.get.return_value = get_req

    connector._service = mock_service

    items, new_cursor = await connector.fetch_new_items(cursor=None)
    assert len(items) >= 1
    assert items[0]["source"] == "resilio"
    assert items[0]["type"] == "email"
    assert items[0]["from_name"] == "Alice"
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_connector_gmail.py -v
```

**Step 3: Implement**

```python
# src/aa/connectors/gmail.py
from __future__ import annotations

import base64
import email.utils
import re
from datetime import datetime, timezone
from typing import Any

from aa.connectors.base import BaseConnector


class GmailConnector(BaseConnector):
    source_name = "resilio"

    def __init__(self, credentials_path: str | None = None, token_path: str | None = None):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._service = None

    async def authenticate(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        import os

        SCOPES = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/calendar.readonly",
        ]

        creds = None
        if self.token_path and os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)
            if self.token_path:
                with open(self.token_path, "w") as f:
                    f.write(creds.to_json())

        self._service = build("gmail", "v1", credentials=creds)

    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        query = "is:unread"
        if cursor:
            query += f" after:{cursor}"

        results = (
            self._service.users()
            .messages()
            .list(userId="me", q=query, maxResults=50)
            .execute()
        )

        messages = results.get("messages", [])
        items = []
        new_cursor = None

        for msg_stub in messages:
            msg = (
                self._service.users()
                .messages()
                .get(userId="me", id=msg_stub["id"], format="full")
                .execute()
            )
            item = self._parse_message(msg)
            items.append(item)

            # Use the latest message's internal date as cursor
            if new_cursor is None:
                ts = int(msg.get("internalDate", "0")) // 1000
                new_cursor = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                    "%Y/%m/%d"
                )

        return items, new_cursor

    def _parse_message(self, msg: dict[str, Any]) -> dict:
        headers = {
            h["name"].lower(): h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }

        from_header = headers.get("from", "")
        from_name, from_address = self._parse_from(from_header)

        body = self._extract_body(msg.get("payload", {}))

        ts = int(msg.get("internalDate", "0")) // 1000
        timestamp = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        return {
            "id": f"resilio-{msg['id']}",
            "source": self.source_name,
            "source_id": msg["id"],
            "type": "email",
            "from_name": from_name,
            "from_address": from_address,
            "subject": headers.get("subject", ""),
            "body": body,
            "timestamp": timestamp,
            "raw_json": str(msg),
        }

    @staticmethod
    def _parse_from(from_header: str) -> tuple[str, str]:
        match = re.match(r"(.+?)\s*<(.+?)>", from_header)
        if match:
            return match.group(1).strip().strip('"'), match.group(2)
        return from_header, from_header

    @staticmethod
    def _extract_body(payload: dict) -> str:
        if "body" in payload and payload["body"].get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode(
                "utf-8", errors="replace"
            )
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode(
                    "utf-8", errors="replace"
                )
        return ""
```

**Step 4: Run tests**

```bash
pytest tests/test_connector_gmail.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/aa/connectors/gmail.py tests/test_connector_gmail.py
git commit -m "feat: Gmail (Resilio) connector with OAuth and message parsing"
```

---

### Task 5: Outlook Connector

**Files:**
- Create: `src/aa/connectors/outlook.py`
- Create: `tests/test_connector_outlook.py`

**Step 1: Write failing test**

```python
# tests/test_connector_outlook.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from aa.connectors.outlook import OutlookConnector


@pytest.fixture
def mock_graph_messages():
    return {
        "value": [
            {
                "id": "AAMk-1",
                "receivedDateTime": "2026-03-09T10:00:00Z",
                "from": {
                    "emailAddress": {
                        "name": "Bob Chen",
                        "address": "bob@nasuni.com",
                    }
                },
                "subject": "Production Issue",
                "bodyPreview": "We have a problem with...",
                "body": {"content": "We have a problem with the deploy.", "contentType": "text"},
            }
        ]
    }


@pytest.mark.asyncio
async def test_outlook_parse_messages(mock_graph_messages):
    connector = OutlookConnector.__new__(OutlookConnector)
    connector.source_name = "outlook_nasuni"
    items = connector._parse_messages(mock_graph_messages["value"])
    assert len(items) == 1
    assert items[0]["source"] == "outlook_nasuni"
    assert items[0]["from_name"] == "Bob Chen"
    assert items[0]["type"] == "email"
    assert "problem" in items[0]["body"]
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_connector_outlook.py -v
```

**Step 3: Implement**

```python
# src/aa/connectors/outlook.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aa.connectors.base import BaseConnector


class OutlookConnector(BaseConnector):
    def __init__(
        self,
        source_name: str,
        client_id: str | None = None,
        tenant_id: str = "common",
        token_cache_path: str | None = None,
    ):
        self.source_name = source_name
        self.client_id = client_id
        self.tenant_id = tenant_id
        self.token_cache_path = token_cache_path
        self._token: str | None = None

    async def authenticate(self):
        import msal
        import json
        import os

        cache = msal.SerializableTokenCache()
        if self.token_cache_path and os.path.exists(self.token_cache_path):
            with open(self.token_cache_path) as f:
                cache.deserialize(f.read())

        app = msal.PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            token_cache=cache,
        )

        scopes = ["Mail.Read", "Calendars.Read"]

        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(scopes, account=accounts[0])
        else:
            result = app.acquire_token_interactive(scopes)

        if "access_token" in result:
            self._token = result["access_token"]
        else:
            raise RuntimeError(f"Auth failed for {self.source_name}: {result.get('error_description', 'unknown')}")

        if self.token_cache_path and cache.has_state_changed:
            with open(self.token_cache_path, "w") as f:
                f.write(cache.serialize())

    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        import httpx

        headers = {"Authorization": f"Bearer {self._token}"}
        params = {
            "$top": 50,
            "$orderby": "receivedDateTime desc",
            "$filter": "isRead eq false",
        }
        if cursor:
            params["$filter"] += f" and receivedDateTime gt {cursor}"

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://graph.microsoft.com/v1.0/me/messages",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        messages = data.get("value", [])
        items = self._parse_messages(messages)

        new_cursor = None
        if messages:
            new_cursor = messages[0].get("receivedDateTime")

        return items, new_cursor

    def _parse_messages(self, messages: list[dict[str, Any]]) -> list[dict]:
        items = []
        for msg in messages:
            from_data = msg.get("from", {}).get("emailAddress", {})
            items.append({
                "id": f"{self.source_name}-{msg['id']}",
                "source": self.source_name,
                "source_id": msg["id"],
                "type": "email",
                "from_name": from_data.get("name", ""),
                "from_address": from_data.get("address", ""),
                "subject": msg.get("subject", ""),
                "body": msg.get("body", {}).get("content", msg.get("bodyPreview", "")),
                "timestamp": msg.get("receivedDateTime", ""),
                "raw_json": str(msg),
            })
        return items
```

**Step 4: Run tests**

```bash
pytest tests/test_connector_outlook.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/aa/connectors/outlook.py tests/test_connector_outlook.py
git commit -m "feat: Outlook connector with Microsoft Graph API"
```

---

### Task 6: Slack Connector

**Files:**
- Create: `src/aa/connectors/slack.py`
- Create: `tests/test_connector_slack.py`

**Step 1: Write failing test**

```python
# tests/test_connector_slack.py
import pytest
from unittest.mock import MagicMock, AsyncMock
from aa.connectors.slack import SlackConnector


@pytest.mark.asyncio
async def test_slack_parse_dm():
    connector = SlackConnector.__new__(SlackConnector)
    connector.source_name = "slack_workspace1"

    raw_msg = {
        "type": "message",
        "user": "U1234",
        "text": "Hey, can you review the PR?",
        "ts": "1741500000.000000",
        "channel": "D9876",
    }
    user_info = {"real_name": "Alice Smith", "profile": {"email": "alice@company.com"}}

    item = connector._parse_message(raw_msg, user_info, msg_type="dm")
    assert item["source"] == "slack_workspace1"
    assert item["type"] == "dm"
    assert item["from_name"] == "Alice Smith"
    assert "review the PR" in item["body"]


@pytest.mark.asyncio
async def test_slack_parse_mention():
    connector = SlackConnector.__new__(SlackConnector)
    connector.source_name = "slack_workspace2"

    raw_msg = {
        "type": "message",
        "user": "U5678",
        "text": "<@UME> thoughts on this approach?",
        "ts": "1741500100.000000",
        "channel": "C1111",
    }
    user_info = {"real_name": "Bob Jones", "profile": {"email": "bob@company.com"}}

    item = connector._parse_message(raw_msg, user_info, msg_type="mention")
    assert item["type"] == "mention"
    assert item["from_name"] == "Bob Jones"
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_connector_slack.py -v
```

**Step 3: Implement**

```python
# src/aa/connectors/slack.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aa.connectors.base import BaseConnector


class SlackConnector(BaseConnector):
    def __init__(self, source_name: str, bot_token: str | None = None):
        self.source_name = source_name
        self.bot_token = bot_token
        self._client = None
        self._user_cache: dict[str, dict] = {}
        self._my_user_id: str | None = None
        self._watched_channels: list[str] = []

    async def authenticate(self):
        from slack_sdk.web.async_client import AsyncWebClient

        self._client = AsyncWebClient(token=self.bot_token)
        auth = await self._client.auth_test()
        self._my_user_id = auth["user_id"]

    def set_watched_channels(self, channel_ids: list[str]):
        self._watched_channels = channel_ids

    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        items = []
        latest_ts = cursor

        # Fetch DMs
        dm_items, dm_ts = await self._fetch_dms(cursor)
        items.extend(dm_items)
        if dm_ts and (not latest_ts or dm_ts > latest_ts):
            latest_ts = dm_ts

        # Fetch mentions from watched channels
        mention_items, mention_ts = await self._fetch_mentions(cursor)
        items.extend(mention_items)
        if mention_ts and (not latest_ts or mention_ts > latest_ts):
            latest_ts = mention_ts

        return items, latest_ts

    async def _fetch_dms(self, cursor: str | None) -> tuple[list[dict], str | None]:
        convos = await self._client.conversations_list(types="im", limit=100)
        items = []
        latest_ts = None

        for convo in convos.get("channels", []):
            params = {"channel": convo["id"], "limit": 20}
            if cursor:
                params["oldest"] = cursor

            history = await self._client.conversations_history(**params)
            for msg in history.get("messages", []):
                if msg.get("user") == self._my_user_id:
                    continue
                user_info = await self._get_user_info(msg.get("user", ""))
                items.append(self._parse_message(msg, user_info, msg_type="dm"))
                if not latest_ts or msg["ts"] > latest_ts:
                    latest_ts = msg["ts"]

        return items, latest_ts

    async def _fetch_mentions(self, cursor: str | None) -> tuple[list[dict], str | None]:
        items = []
        latest_ts = None

        for channel_id in self._watched_channels:
            params = {"channel": channel_id, "limit": 50}
            if cursor:
                params["oldest"] = cursor

            history = await self._client.conversations_history(**params)
            for msg in history.get("messages", []):
                if self._my_user_id and f"<@{self._my_user_id}>" in msg.get("text", ""):
                    user_info = await self._get_user_info(msg.get("user", ""))
                    items.append(self._parse_message(msg, user_info, msg_type="mention"))
                    if not latest_ts or msg["ts"] > latest_ts:
                        latest_ts = msg["ts"]

        return items, latest_ts

    async def _get_user_info(self, user_id: str) -> dict:
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        if self._client and user_id:
            resp = await self._client.users_info(user=user_id)
            info = resp.get("user", {})
            self._user_cache[user_id] = info
            return info
        return {}

    def _parse_message(
        self, msg: dict[str, Any], user_info: dict, msg_type: str
    ) -> dict:
        ts_float = float(msg.get("ts", "0"))
        timestamp = datetime.fromtimestamp(ts_float, tz=timezone.utc).isoformat()

        return {
            "id": f"{self.source_name}-{msg.get('ts', '')}",
            "source": self.source_name,
            "source_id": msg.get("ts", ""),
            "type": msg_type,
            "from_name": user_info.get("real_name", "Unknown"),
            "from_address": user_info.get("profile", {}).get("email", ""),
            "subject": "",
            "body": msg.get("text", ""),
            "timestamp": timestamp,
            "raw_json": str(msg),
        }
```

**Step 4: Run tests**

```bash
pytest tests/test_connector_slack.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/aa/connectors/slack.py tests/test_connector_slack.py
git commit -m "feat: Slack connector with DM and mention polling"
```

---

### Task 7: Mattermost Connector

**Files:**
- Create: `src/aa/connectors/mattermost.py`
- Create: `tests/test_connector_mattermost.py`

**Step 1: Write failing test**

```python
# tests/test_connector_mattermost.py
import pytest
from aa.connectors.mattermost import MattermostConnector


@pytest.mark.asyncio
async def test_mattermost_parse_post():
    connector = MattermostConnector.__new__(MattermostConnector)
    connector.source_name = "mattermost"

    raw_post = {
        "id": "post123",
        "create_at": 1741500000000,
        "message": "Can you check the logs?",
        "channel_id": "ch1",
        "user_id": "user1",
    }
    user_info = {
        "username": "jdoe",
        "first_name": "John",
        "last_name": "Doe",
        "email": "jdoe@company.com",
    }

    item = connector._parse_post(raw_post, user_info, msg_type="dm")
    assert item["source"] == "mattermost"
    assert item["from_name"] == "John Doe"
    assert "check the logs" in item["body"]
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_connector_mattermost.py -v
```

**Step 3: Implement**

```python
# src/aa/connectors/mattermost.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aa.connectors.base import BaseConnector


class MattermostConnector(BaseConnector):
    source_name = "mattermost"

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
    ):
        self.url = url
        self.token = token
        self._driver = None
        self._my_user_id: str | None = None
        self._user_cache: dict[str, dict] = {}
        self._watched_channels: list[str] = []

    async def authenticate(self):
        from mattermostdriver import Driver

        self._driver = Driver({
            "url": self.url,
            "token": self.token,
            "scheme": "https",
            "port": 443,
        })
        self._driver.login()
        me = self._driver.users.get_user("me")
        self._my_user_id = me["id"]

    def set_watched_channels(self, channel_ids: list[str]):
        self._watched_channels = channel_ids

    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        items = []
        latest_ts = cursor

        # Direct messages
        dm_channels = self._driver.channels.get_channels_for_user(self._my_user_id, "direct")
        for ch in dm_channels:
            posts = self._driver.posts.get_posts_for_channel(ch["id"])
            for post_id in posts.get("order", []):
                post = posts["posts"][post_id]
                if post["user_id"] == self._my_user_id:
                    continue
                post_ts = str(post["create_at"])
                if cursor and post_ts <= cursor:
                    continue
                user_info = self._get_user_info(post["user_id"])
                items.append(self._parse_post(post, user_info, msg_type="dm"))
                if not latest_ts or post_ts > latest_ts:
                    latest_ts = post_ts

        # Watched channels — mentions only
        for ch_id in self._watched_channels:
            posts = self._driver.posts.get_posts_for_channel(ch_id)
            for post_id in posts.get("order", []):
                post = posts["posts"][post_id]
                if self._my_user_id and f"@{self._get_my_username()}" in post.get("message", ""):
                    post_ts = str(post["create_at"])
                    if cursor and post_ts <= cursor:
                        continue
                    user_info = self._get_user_info(post["user_id"])
                    items.append(self._parse_post(post, user_info, msg_type="mention"))
                    if not latest_ts or post_ts > latest_ts:
                        latest_ts = post_ts

        return items, latest_ts

    def _get_user_info(self, user_id: str) -> dict:
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        info = self._driver.users.get_user(user_id)
        self._user_cache[user_id] = info
        return info

    def _get_my_username(self) -> str:
        if self._my_user_id:
            info = self._get_user_info(self._my_user_id)
            return info.get("username", "")
        return ""

    def _parse_post(self, post: dict[str, Any], user_info: dict, msg_type: str) -> dict:
        ts_ms = post.get("create_at", 0)
        timestamp = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()

        name = f"{user_info.get('first_name', '')} {user_info.get('last_name', '')}".strip()
        if not name:
            name = user_info.get("username", "Unknown")

        return {
            "id": f"mattermost-{post['id']}",
            "source": self.source_name,
            "source_id": post["id"],
            "type": msg_type,
            "from_name": name,
            "from_address": user_info.get("email", ""),
            "subject": "",
            "body": post.get("message", ""),
            "timestamp": timestamp,
            "raw_json": str(post),
        }
```

**Step 4: Run tests**

```bash
pytest tests/test_connector_mattermost.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/aa/connectors/mattermost.py tests/test_connector_mattermost.py
git commit -m "feat: Mattermost connector with DM and mention polling"
```

---

### Task 8: Calendar Connector

**Files:**
- Create: `src/aa/connectors/calendar.py`
- Create: `tests/test_connector_calendar.py`

**Step 1: Write failing test**

```python
# tests/test_connector_calendar.py
import pytest
from aa.connectors.calendar import GoogleCalendarConnector, OutlookCalendarConnector


@pytest.mark.asyncio
async def test_google_calendar_parse_event():
    connector = GoogleCalendarConnector.__new__(GoogleCalendarConnector)
    connector.source_name = "resilio"

    raw_event = {
        "id": "evt1",
        "summary": "Team Standup",
        "start": {"dateTime": "2026-03-09T09:00:00-05:00"},
        "end": {"dateTime": "2026-03-09T09:30:00-05:00"},
        "organizer": {"displayName": "Alice", "email": "alice@resilio.com"},
        "attendees": [
            {"email": "me@resilio.com", "responseStatus": "accepted"},
        ],
    }

    item = connector._parse_event(raw_event)
    assert item["type"] == "calendar_event"
    assert item["subject"] == "Team Standup"
    assert item["from_name"] == "Alice"


@pytest.mark.asyncio
async def test_outlook_calendar_parse_event():
    connector = OutlookCalendarConnector.__new__(OutlookCalendarConnector)
    connector.source_name = "outlook_nasuni"

    raw_event = {
        "id": "AAMk-evt1",
        "subject": "1:1 with Manager",
        "start": {"dateTime": "2026-03-09T14:00:00", "timeZone": "UTC"},
        "end": {"dateTime": "2026-03-09T14:30:00", "timeZone": "UTC"},
        "organizer": {
            "emailAddress": {"name": "Manager Bob", "address": "bob@nasuni.com"}
        },
    }

    item = connector._parse_event(raw_event)
    assert item["type"] == "calendar_event"
    assert item["subject"] == "1:1 with Manager"
    assert item["from_name"] == "Manager Bob"
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_connector_calendar.py -v
```

**Step 3: Implement**

```python
# src/aa/connectors/calendar.py
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from aa.connectors.base import BaseConnector


class GoogleCalendarConnector(BaseConnector):
    source_name = "resilio"

    def __init__(self, service=None):
        self._service = service

    async def authenticate(self):
        # Reuses the same credentials as GmailConnector
        # Service is injected from shared auth
        pass

    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=7)).isoformat()

        events_result = (
            self._service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=50,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = events_result.get("items", [])
        items = [self._parse_event(e) for e in events]
        return items, now.isoformat()

    def _parse_event(self, event: dict[str, Any]) -> dict:
        organizer = event.get("organizer", {})
        start = event.get("start", {})
        start_dt = start.get("dateTime", start.get("date", ""))

        return {
            "id": f"gcal-{event['id']}",
            "source": self.source_name,
            "source_id": event["id"],
            "type": "calendar_event",
            "from_name": organizer.get("displayName", organizer.get("email", "")),
            "from_address": organizer.get("email", ""),
            "subject": event.get("summary", "(No title)"),
            "body": event.get("description", ""),
            "timestamp": start_dt,
            "raw_json": str(event),
        }


class OutlookCalendarConnector(BaseConnector):
    def __init__(self, source_name: str, token: str | None = None):
        self.source_name = source_name
        self._token = token

    async def authenticate(self):
        # Token shared with OutlookConnector
        pass

    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        import httpx

        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=7)).isoformat()

        headers = {"Authorization": f"Bearer {self._token}"}
        params = {
            "startDateTime": time_min,
            "endDateTime": time_max,
            "$top": 50,
            "$orderby": "start/dateTime",
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://graph.microsoft.com/v1.0/me/calendarview",
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        events = data.get("value", [])
        items = [self._parse_event(e) for e in events]
        return items, now.isoformat()

    def _parse_event(self, event: dict[str, Any]) -> dict:
        organizer = event.get("organizer", {}).get("emailAddress", {})
        start = event.get("start", {})
        start_dt = start.get("dateTime", "")

        return {
            "id": f"{self.source_name}-cal-{event['id']}",
            "source": self.source_name,
            "source_id": event["id"],
            "type": "calendar_event",
            "from_name": organizer.get("name", ""),
            "from_address": organizer.get("address", ""),
            "subject": event.get("subject", "(No title)"),
            "body": event.get("bodyPreview", ""),
            "timestamp": start_dt,
            "raw_json": str(event),
        }
```

**Step 4: Run tests**

```bash
pytest tests/test_connector_calendar.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/aa/connectors/calendar.py tests/test_connector_calendar.py
git commit -m "feat: Google and Outlook calendar connectors"
```

---

### Task 9: Notes File Watcher

**Files:**
- Create: `src/aa/notes_watcher.py`
- Create: `tests/test_notes_watcher.py`

**Step 1: Write failing test**

```python
# tests/test_notes_watcher.py
import pytest
from aa.notes_watcher import extract_new_content


def test_extract_new_content_from_diff():
    old = "Buy groceries\nCall dentist\n"
    new = "Buy groceries\nCall dentist\nReview Q3 budget\nEmail Alice about deploy\n"
    result = extract_new_content(old, new)
    assert "Review Q3 budget" in result
    assert "Email Alice about deploy" in result
    assert "Buy groceries" not in result


def test_extract_new_content_no_change():
    old = "Buy groceries\n"
    new = "Buy groceries\n"
    result = extract_new_content(old, new)
    assert result == ""


def test_extract_new_content_from_empty():
    old = ""
    new = "First note\nSecond note\n"
    result = extract_new_content(old, new)
    assert "First note" in result
    assert "Second note" in result
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_notes_watcher.py -v
```

**Step 3: Implement**

```python
# src/aa/notes_watcher.py
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Awaitable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent


def extract_new_content(old: str, new: str) -> str:
    """Return lines present in new but not in old."""
    old_lines = set(old.strip().splitlines())
    new_lines = new.strip().splitlines()
    added = [line for line in new_lines if line and line not in old_lines]
    return "\n".join(added)


class NotesFileHandler(FileSystemEventHandler):
    def __init__(
        self,
        file_path: Path,
        callback: Callable[[str], Awaitable[None]],
        loop: asyncio.AbstractEventLoop,
    ):
        self.file_path = file_path
        self.callback = callback
        self.loop = loop
        self._last_content = file_path.read_text() if file_path.exists() else ""

    def on_modified(self, event):
        if not isinstance(event, FileModifiedEvent):
            return
        if Path(event.src_path).resolve() != self.file_path.resolve():
            return

        current = self.file_path.read_text()
        new_content = extract_new_content(self._last_content, current)
        self._last_content = current

        if new_content:
            asyncio.run_coroutine_threadsafe(self.callback(new_content), self.loop)


class NotesWatcher:
    def __init__(
        self,
        file_path: str | Path,
        callback: Callable[[str], Awaitable[None]],
        loop: asyncio.AbstractEventLoop,
    ):
        self.file_path = Path(file_path).resolve()
        self.callback = callback
        self.loop = loop
        self._observer: Observer | None = None

    def start(self):
        handler = NotesFileHandler(self.file_path, self.callback, self.loop)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.file_path.parent), recursive=False)
        self._observer.start()

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
```

**Step 4: Run tests**

```bash
pytest tests/test_notes_watcher.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/aa/notes_watcher.py tests/test_notes_watcher.py
git commit -m "feat: notes file watcher with diff-based change detection"
```

---

### Task 10: AI Triage Engine

**Files:**
- Create: `src/aa/ai/__init__.py`
- Create: `src/aa/ai/triage.py`
- Create: `tests/test_ai_triage.py`

**Step 1: Write failing test**

```python
# tests/test_ai_triage.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from aa.ai.triage import TriageEngine


@pytest.fixture
def mock_items():
    return [
        {
            "id": "item-1",
            "source": "resilio",
            "type": "email",
            "from_name": "CEO",
            "subject": "Urgent: Board meeting prep",
            "body": "Need the slides by EOD.",
            "timestamp": "2026-03-09T10:00:00",
        },
        {
            "id": "item-2",
            "source": "slack_workspace1",
            "type": "mention",
            "from_name": "Bob",
            "subject": "",
            "body": "Anyone know the wifi password?",
            "timestamp": "2026-03-09T10:05:00",
        },
    ]


@pytest.fixture
def mock_context():
    return {
        "calendar_today": [
            {"subject": "Board Prep", "timestamp": "2026-03-09T14:00:00"}
        ],
        "active_todos": [{"title": "Finish slides", "priority": 1}],
        "rules": ["Anything from CEO is priority 1"],
        "feedback_summary": "User prioritizes executive requests.",
    }


@pytest.mark.asyncio
async def test_triage_builds_prompt(mock_items, mock_context):
    engine = TriageEngine(api_key="test-key")
    prompt = engine._build_triage_prompt(mock_items, mock_context)
    assert "CEO" in prompt
    assert "Urgent: Board meeting prep" in prompt
    assert "Anything from CEO is priority 1" in prompt
    assert "Finish slides" in prompt


@pytest.mark.asyncio
async def test_triage_parses_response():
    engine = TriageEngine(api_key="test-key")
    raw_response = json.dumps([
        {
            "id": "item-1",
            "priority": 1,
            "summary": "CEO needs board slides by EOD",
            "action": "reply",
            "create_todo": True,
            "todo_title": "Prepare board meeting slides",
            "draft": "I'll have the slides ready by 4pm. Want me to share a draft first?",
        },
        {
            "id": "item-2",
            "priority": 5,
            "summary": "Someone asking about wifi",
            "action": "ignore",
            "create_todo": False,
            "todo_title": None,
            "draft": None,
        },
    ])
    results = engine._parse_triage_response(raw_response)
    assert len(results) == 2
    assert results[0]["priority"] == 1
    assert results[0]["action"] == "reply"
    assert results[1]["priority"] == 5
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_ai_triage.py -v
```

**Step 3: Implement**

```python
# src/aa/ai/__init__.py
"""AI components for aa."""

# src/aa/ai/triage.py
from __future__ import annotations

import json
from typing import Any

import anthropic


TRIAGE_SYSTEM_PROMPT = """You are a personal assistant that triages and prioritizes incoming messages and events.

For each item, provide:
- priority: 1 (critical/urgent) to 5 (low/noise)
- summary: one-line summary
- action: one of "reply", "schedule", "delegate", "fyi", "ignore"
- create_todo: boolean — should this become a todo item?
- todo_title: string or null — title for the todo if created
- draft: string or null — draft response if action is "reply"

Respond ONLY with a JSON array. No markdown, no explanation."""

TRIAGE_USER_TEMPLATE = """## User Rules
{rules}

## Learned Preferences
{feedback_summary}

## Today's Calendar
{calendar}

## Active Todos
{todos}

## New Items to Triage
{items}

Triage each item. Return a JSON array with one object per item, each containing: id, priority, summary, action, create_todo, todo_title, draft."""


class TriageEngine:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key
        self.model = model
        self._client: anthropic.AsyncAnthropic | None = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if not self._client:
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def triage(
        self, items: list[dict], context: dict[str, Any]
    ) -> list[dict]:
        if not items:
            return []

        prompt = self._build_triage_prompt(items, context)
        client = self._get_client()

        response = await client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=TRIAGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text
        return self._parse_triage_response(text)

    def _build_triage_prompt(
        self, items: list[dict], context: dict[str, Any]
    ) -> str:
        rules_text = "\n".join(
            f"- {r}" if isinstance(r, str) else f"- {r.get('rule', '')}"
            for r in context.get("rules", [])
        ) or "None"

        calendar_text = "\n".join(
            f"- {e.get('subject', '')} at {e.get('timestamp', '')}"
            for e in context.get("calendar_today", [])
        ) or "None"

        todos_text = "\n".join(
            f"- [{t.get('priority', 3)}] {t.get('title', '')}"
            for t in context.get("active_todos", [])
        ) or "None"

        items_text = ""
        for item in items:
            items_text += f"\n### Item: {item['id']}\n"
            items_text += f"Source: {item.get('source', '')}\n"
            items_text += f"Type: {item.get('type', '')}\n"
            items_text += f"From: {item.get('from_name', '')}\n"
            items_text += f"Subject: {item.get('subject', '')}\n"
            items_text += f"Body: {item.get('body', '')[:500]}\n"
            items_text += f"Time: {item.get('timestamp', '')}\n"

        return TRIAGE_USER_TEMPLATE.format(
            rules=rules_text,
            feedback_summary=context.get("feedback_summary", "None yet."),
            calendar=calendar_text,
            todos=todos_text,
            items=items_text,
        )

    def _parse_triage_response(self, text: str) -> list[dict]:
        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        return json.loads(text)
```

**Step 4: Run tests**

```bash
pytest tests/test_ai_triage.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/aa/ai/ tests/test_ai_triage.py
git commit -m "feat: AI triage engine with Claude API integration"
```

---

### Task 11: AI Draft Response Generator

**Files:**
- Create: `src/aa/ai/drafts.py`
- Create: `tests/test_ai_drafts.py`

**Step 1: Write failing test**

```python
# tests/test_ai_drafts.py
import pytest
from aa.ai.drafts import DraftGenerator


@pytest.mark.asyncio
async def test_draft_builds_prompt():
    gen = DraftGenerator(api_key="test-key")
    item = {
        "id": "item-1",
        "source": "resilio",
        "type": "email",
        "from_name": "Alice",
        "subject": "Meeting tomorrow?",
        "body": "Hey, can we meet at 2pm tomorrow to discuss the project?",
    }
    prompt = gen._build_draft_prompt(item, user_instruction=None)
    assert "Alice" in prompt
    assert "Meeting tomorrow?" in prompt


@pytest.mark.asyncio
async def test_draft_with_user_instruction():
    gen = DraftGenerator(api_key="test-key")
    item = {
        "id": "item-1",
        "source": "resilio",
        "type": "email",
        "from_name": "Alice",
        "subject": "Meeting tomorrow?",
        "body": "Can we meet at 2pm?",
    }
    prompt = gen._build_draft_prompt(item, user_instruction="Say I'm free at 3pm instead")
    assert "3pm instead" in prompt
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_ai_drafts.py -v
```

**Step 3: Implement**

```python
# src/aa/ai/drafts.py
from __future__ import annotations

from typing import Any

import anthropic


DRAFT_SYSTEM_PROMPT = """You are drafting a response on behalf of the user. Write in their voice — professional but not stiff.
Keep it concise. Do not add pleasantries unless the conversation warrants it.
Return ONLY the response text. No subject line, no explanation."""

DRAFT_USER_TEMPLATE = """## Original Message
From: {from_name}
Subject: {subject}
Body:
{body}

{instruction_section}
Draft a response."""


class DraftGenerator:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key
        self.model = model
        self._client: anthropic.AsyncAnthropic | None = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if not self._client:
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def generate_draft(
        self, item: dict[str, Any], user_instruction: str | None = None
    ) -> str:
        prompt = self._build_draft_prompt(item, user_instruction)
        client = self._get_client()

        response = await client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=DRAFT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        return response.content[0].text.strip()

    def _build_draft_prompt(
        self, item: dict[str, Any], user_instruction: str | None = None
    ) -> str:
        instruction_section = ""
        if user_instruction:
            instruction_section = f"## User Instruction\n{user_instruction}\n"

        return DRAFT_USER_TEMPLATE.format(
            from_name=item.get("from_name", ""),
            subject=item.get("subject", ""),
            body=item.get("body", "")[:2000],
            instruction_section=instruction_section,
        )
```

**Step 4: Run tests**

```bash
pytest tests/test_ai_drafts.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/aa/ai/drafts.py tests/test_ai_drafts.py
git commit -m "feat: AI draft response generator"
```

---

### Task 12: AI Rules & Feedback Manager

**Files:**
- Create: `src/aa/ai/rules.py`
- Create: `tests/test_ai_rules.py`

**Step 1: Write failing test**

```python
# tests/test_ai_rules.py
import pytest
from aa.ai.rules import build_feedback_summary


def test_build_feedback_summary_empty():
    result = build_feedback_summary([])
    assert result == "No feedback yet."


def test_build_feedback_summary_with_data():
    feedbacks = [
        {"original_priority": 4, "corrected_priority": 1, "original_action": "fyi", "corrected_action": "reply"},
        {"original_priority": 3, "corrected_priority": 1, "original_action": "fyi", "corrected_action": "reply"},
        {"original_priority": 2, "corrected_priority": 5, "original_action": "reply", "corrected_action": "ignore"},
    ]
    result = build_feedback_summary(feedbacks)
    assert isinstance(result, str)
    assert len(result) > 0
    # Should mention patterns
    assert "priority" in result.lower() or "upgraded" in result.lower() or "correction" in result.lower()
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_ai_rules.py -v
```

**Step 3: Implement**

```python
# src/aa/ai/rules.py
from __future__ import annotations

from collections import Counter


def build_feedback_summary(feedbacks: list[dict]) -> str:
    """Build a human-readable summary of user feedback patterns for the AI."""
    if not feedbacks:
        return "No feedback yet."

    lines = []
    upgrades = [f for f in feedbacks if f["corrected_priority"] < f["original_priority"]]
    downgrades = [f for f in feedbacks if f["corrected_priority"] > f["original_priority"]]
    action_changes = [f for f in feedbacks if f["corrected_action"] != f["original_action"]]

    if upgrades:
        lines.append(
            f"User upgraded priority on {len(upgrades)} items (AI under-prioritized)."
        )
    if downgrades:
        lines.append(
            f"User downgraded priority on {len(downgrades)} items (AI over-prioritized)."
        )
    if action_changes:
        change_counts = Counter(
            f"{f['original_action']} -> {f['corrected_action']}" for f in action_changes
        )
        for change, count in change_counts.most_common(5):
            lines.append(f"User changed action {change} ({count} times).")

    return " ".join(lines) if lines else "No significant patterns yet."
```

**Step 4: Run tests**

```bash
pytest tests/test_ai_rules.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/aa/ai/rules.py tests/test_ai_rules.py
git commit -m "feat: feedback summary builder for AI triage context"
```

---

### Task 13: Notification Manager

**Files:**
- Create: `src/aa/notifications.py`
- Create: `tests/test_notifications.py`

**Step 1: Write failing test**

```python
# tests/test_notifications.py
import pytest
from aa.notifications import format_notification, should_notify


def test_format_notification():
    item = {
        "source": "slack_workspace1",
        "from_name": "Bob Chen",
        "ai_summary": "Production is down, needs immediate help",
        "ai_suggested_action": "reply",
        "priority": 1,
    }
    text = format_notification(item)
    assert "Bob Chen" in text
    assert "slack" in text.lower()
    assert "Production is down" in text


def test_should_notify_high_priority():
    assert should_notify(priority=1, threshold=2) is True
    assert should_notify(priority=2, threshold=2) is True


def test_should_not_notify_low_priority():
    assert should_notify(priority=3, threshold=2) is False
    assert should_notify(priority=5, threshold=2) is False
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_notifications.py -v
```

**Step 3: Implement**

```python
# src/aa/notifications.py
from __future__ import annotations

import sys


def format_notification(item: dict) -> str:
    priority_labels = {1: "URGENT", 2: "HIGH", 3: "MEDIUM", 4: "LOW", 5: "FYI"}
    label = priority_labels.get(item.get("priority", 5), "")
    source = item.get("source", "unknown")
    from_name = item.get("from_name", "Unknown")
    summary = item.get("ai_summary", "")
    action = item.get("ai_suggested_action", "")

    return f"[{label}] {source}: from {from_name}: \"{summary}\" → suggested: {action}"


def should_notify(priority: int, threshold: int = 2) -> bool:
    return priority <= threshold


def send_terminal_notification(text: str):
    """Send notification to terminal via bell + stderr."""
    sys.stderr.write(f"\a\n{'='*60}\n{text}\n{'='*60}\n")
    sys.stderr.flush()
```

**Step 4: Run tests**

```bash
pytest tests/test_notifications.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/aa/notifications.py tests/test_notifications.py
git commit -m "feat: terminal notification formatting and filtering"
```

---

### Task 14: Config Manager

**Files:**
- Create: `src/aa/config.py`
- Create: `tests/test_config.py`

**Step 1: Write failing test**

```python
# tests/test_config.py
import pytest
from pathlib import Path
from aa.config import AppConfig


def test_default_config():
    config = AppConfig()
    assert config.data_dir.name == ".assistant"
    assert config.poll_interval_email == 60
    assert config.poll_interval_slack == 30
    assert config.notification_threshold == 2


def test_config_from_file(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"poll_interval_email": 120, "notification_threshold": 1}')
    config = AppConfig.from_file(config_file)
    assert config.poll_interval_email == 120
    assert config.notification_threshold == 1
    # Defaults still work for unset values
    assert config.poll_interval_slack == 30


def test_config_db_path():
    config = AppConfig()
    assert config.db_path.name == "aa.db"


def test_config_sources():
    config = AppConfig()
    config.sources = {"resilio": {"type": "gmail", "enabled": True}}
    assert config.sources["resilio"]["type"] == "gmail"
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_config.py -v
```

**Step 3: Implement**

```python
# src/aa/config.py
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class AppConfig:
    data_dir: Path = field(default_factory=lambda: Path.home() / ".assistant")
    poll_interval_email: int = 60
    poll_interval_slack: int = 30
    poll_interval_calendar: int = 300
    poll_interval_mattermost: int = 30
    notification_threshold: int = 2
    notes_file: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-20250514"
    sources: dict[str, Any] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "aa.db"

    @property
    def socket_path(self) -> Path:
        return self.data_dir / "assistant.sock"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @classmethod
    def from_file(cls, path: Path) -> AppConfig:
        data = json.loads(path.read_text())
        config = cls()
        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return config

    def ensure_dirs(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def save(self, path: Path | None = None):
        path = path or (self.data_dir / "config.json")
        data = {
            "poll_interval_email": self.poll_interval_email,
            "poll_interval_slack": self.poll_interval_slack,
            "poll_interval_calendar": self.poll_interval_calendar,
            "poll_interval_mattermost": self.poll_interval_mattermost,
            "notification_threshold": self.notification_threshold,
            "notes_file": self.notes_file,
            "anthropic_model": self.anthropic_model,
            "sources": self.sources,
        }
        path.write_text(json.dumps(data, indent=2))
```

**Step 4: Run tests**

```bash
pytest tests/test_config.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/aa/config.py tests/test_config.py
git commit -m "feat: config manager with defaults and file persistence"
```

---

### Task 15: Daemon & Unix Socket Server

**Files:**
- Create: `src/aa/server.py`
- Create: `src/aa/daemon.py`
- Create: `tests/test_server.py`

**Step 1: Write failing test**

```python
# tests/test_server.py
import pytest
import asyncio
import json
from pathlib import Path
from aa.server import RequestHandler


@pytest.fixture
def handler(tmp_path):
    from aa.db import Database
    from aa.config import AppConfig

    config = AppConfig(data_dir=tmp_path)
    return RequestHandler(config=config, db=None)


def test_parse_request():
    handler = RequestHandler.__new__(RequestHandler)
    req = handler.parse_request('{"command": "status"}')
    assert req["command"] == "status"


def test_parse_request_invalid():
    handler = RequestHandler.__new__(RequestHandler)
    req = handler.parse_request("not json")
    assert req is None
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_server.py -v
```

**Step 3: Implement**

```python
# src/aa/server.py
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from aa.config import AppConfig
from aa.db import Database

logger = logging.getLogger(__name__)


class RequestHandler:
    def __init__(self, config: AppConfig, db: Database | None):
        self.config = config
        self.db = db

    def parse_request(self, data: str) -> dict | None:
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None

    async def handle(self, request: dict) -> dict:
        command = request.get("command", "")
        args = request.get("args", {})

        handlers = {
            "status": self._handle_status,
            "inbox": self._handle_inbox,
            "show": self._handle_show,
            "todo": self._handle_todo,
            "todo_add": self._handle_todo_add,
            "todo_done": self._handle_todo_done,
            "todo_edit": self._handle_todo_edit,
            "todo_rm": self._handle_todo_rm,
            "todo_link": self._handle_todo_link,
            "reprioritize": self._handle_reprioritize,
            "dismiss": self._handle_dismiss,
            "rule_add": self._handle_rule_add,
            "rule_list": self._handle_rule_list,
            "rule_rm": self._handle_rule_rm,
            "calendar": self._handle_calendar,
            "ask": self._handle_ask,
            "reply": self._handle_reply,
        }

        handler_fn = handlers.get(command)
        if not handler_fn:
            return {"error": f"Unknown command: {command}"}

        return await handler_fn(args)

    async def _handle_status(self, args: dict) -> dict:
        sources = []
        # Get sync state for all sources
        for source_name in ["resilio", "outlook_personal", "outlook_nasuni",
                            "slack_workspace1", "slack_workspace2", "mattermost"]:
            state = await self.db.get_sync_state(source_name)
            sources.append({
                "source": source_name,
                "last_sync": state["last_sync"] if state else "never",
                "status": state["status"] if state else "not configured",
            })
        return {"status": "running", "sources": sources}

    async def _handle_inbox(self, args: dict) -> dict:
        source = args.get("source")
        items = await self.db.list_items(source=source, unread_only=True)
        return {"items": items}

    async def _handle_show(self, args: dict) -> dict:
        item = await self.db.get_item(args.get("id", ""))
        if not item:
            return {"error": "Item not found"}
        return {"item": item}

    async def _handle_todo(self, args: dict) -> dict:
        include_done = args.get("include_done", False)
        todos = await self.db.list_todos(include_done=include_done)
        return {"todos": todos}

    async def _handle_todo_add(self, args: dict) -> dict:
        todo_id = await self.db.insert_todo(
            title=args["title"],
            priority=args.get("priority", 3),
            due_date=args.get("due"),
            notes=args.get("note"),
        )
        return {"id": todo_id, "message": "Todo added"}

    async def _handle_todo_done(self, args: dict) -> dict:
        await self.db.update_todo(args["id"], status="done")
        return {"message": "Todo marked done"}

    async def _handle_todo_edit(self, args: dict) -> dict:
        fields = {k: v for k, v in args.items() if k != "id" and v is not None}
        await self.db.update_todo(args["id"], **fields)
        return {"message": "Todo updated"}

    async def _handle_todo_rm(self, args: dict) -> dict:
        await self.db.delete_todo(args["id"])
        return {"message": "Todo removed"}

    async def _handle_todo_link(self, args: dict) -> dict:
        await self.db.link_todo(args["todo_id"], args["item_id"])
        return {"message": "Link added"}

    async def _handle_reprioritize(self, args: dict) -> dict:
        item = await self.db.get_item(args["id"])
        if not item:
            return {"error": "Item not found"}
        await self.db.insert_feedback(
            item_id=args["id"],
            original_priority=item.get("priority", 3),
            corrected_priority=args["priority"],
            original_action=item.get("ai_suggested_action", ""),
            corrected_action=item.get("ai_suggested_action", ""),
        )
        await self.db.update_item_triage(
            args["id"], args["priority"],
            item.get("ai_summary", ""), item.get("ai_suggested_action", "")
        )
        return {"message": "Priority updated"}

    async def _handle_dismiss(self, args: dict) -> dict:
        item = await self.db.get_item(args["id"])
        if not item:
            return {"error": "Item not found"}
        await self.db.insert_feedback(
            item_id=args["id"],
            original_priority=item.get("priority", 3),
            corrected_priority=5,
            original_action=item.get("ai_suggested_action", ""),
            corrected_action="ignore",
        )
        await self.db.update_item_triage(args["id"], 5, item.get("ai_summary", ""), "ignore")
        return {"message": "Item dismissed"}

    async def _handle_rule_add(self, args: dict) -> dict:
        rule_id = await self.db.insert_rule(args["rule"])
        return {"id": rule_id, "message": "Rule added"}

    async def _handle_rule_list(self, args: dict) -> dict:
        rules = await self.db.list_rules()
        return {"rules": rules}

    async def _handle_rule_rm(self, args: dict) -> dict:
        await self.db.delete_rule(args["id"])
        return {"message": "Rule removed"}

    async def _handle_calendar(self, args: dict) -> dict:
        # Filter calendar events from items
        items = await self.db.list_items()
        events = [i for i in items if i["type"] == "calendar_event"]
        return {"events": events}

    async def _handle_ask(self, args: dict) -> dict:
        # Placeholder — will be wired to Claude in engine
        return {"answer": "Ask functionality requires running daemon with AI engine."}

    async def _handle_reply(self, args: dict) -> dict:
        # Placeholder — will be wired to draft generator in engine
        return {"draft": "Reply functionality requires running daemon with AI engine."}


class SocketServer:
    def __init__(self, handler: RequestHandler, socket_path: Path):
        self.handler = handler
        self.socket_path = socket_path
        self._server: asyncio.Server | None = None

    async def start(self):
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self._server = await asyncio.start_unix_server(
            self._client_connected, path=str(self.socket_path)
        )
        logger.info(f"Server listening on {self.socket_path}")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if self.socket_path.exists():
            self.socket_path.unlink()

    async def _client_connected(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        try:
            data = await reader.read(65536)
            request = self.handler.parse_request(data.decode())
            if request is None:
                response = {"error": "Invalid request"}
            else:
                response = await self.handler.handle(request)
            writer.write(json.dumps(response).encode())
            await writer.drain()
        except Exception as e:
            logger.exception("Error handling request")
            writer.write(json.dumps({"error": str(e)}).encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
```

```python
# src/aa/daemon.py
from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

from aa.config import AppConfig
from aa.db import Database
from aa.server import RequestHandler, SocketServer
from aa.notifications import format_notification, should_notify, send_terminal_notification
from aa.ai.triage import TriageEngine
from aa.ai.rules import build_feedback_summary

logger = logging.getLogger(__name__)


class Daemon:
    def __init__(self, config: AppConfig):
        self.config = config
        self.db: Database | None = None
        self.server: SocketServer | None = None
        self.triage_engine: TriageEngine | None = None
        self.connectors: dict = {}
        self._running = False

    async def start(self):
        self.config.ensure_dirs()

        # Initialize DB
        self.db = Database(self.config.db_path)
        await self.db.initialize()

        # Initialize AI
        if self.config.anthropic_api_key:
            self.triage_engine = TriageEngine(
                api_key=self.config.anthropic_api_key,
                model=self.config.anthropic_model,
            )

        # Initialize server
        handler = RequestHandler(config=self.config, db=self.db)
        self.server = SocketServer(handler, self.config.socket_path)
        await self.server.start()

        # Start polling loop
        self._running = True
        logger.info("Daemon started")
        await self._poll_loop()

    async def stop(self):
        self._running = False
        if self.server:
            await self.server.stop()
        if self.db:
            await self.db.close()
        logger.info("Daemon stopped")

    async def _poll_loop(self):
        while self._running:
            try:
                await self._poll_all_sources()
                await self._run_triage()
            except Exception:
                logger.exception("Error in poll loop")

            await asyncio.sleep(min(
                self.config.poll_interval_email,
                self.config.poll_interval_slack,
            ))

    async def _poll_all_sources(self):
        for name, connector in self.connectors.items():
            try:
                state = await self.db.get_sync_state(name)
                cursor = state["cursor"] if state else None

                items, new_cursor = await connector.fetch_new_items(cursor=cursor)

                for item in items:
                    await self.db.insert_item(item)

                if new_cursor:
                    await self.db.update_sync_state(name, cursor=new_cursor, status="ok")

            except Exception as e:
                logger.error(f"Error polling {name}: {e}")
                await self.db.update_sync_state(name, status=f"error: {e}")

    async def _run_triage(self):
        if not self.triage_engine:
            return

        untriaged = await self.db.get_untriaged_items()
        if not untriaged:
            return

        # Build context
        all_items = await self.db.list_items()
        calendar_events = [i for i in all_items if i["type"] == "calendar_event"]
        todos = await self.db.list_todos()
        rules = await self.db.list_rules()
        feedbacks = await self.db.list_feedback(limit=50)

        context = {
            "calendar_today": calendar_events[:10],
            "active_todos": todos[:20],
            "rules": rules,
            "feedback_summary": build_feedback_summary(feedbacks),
        }

        results = await self.triage_engine.triage(untriaged, context)

        for result in results:
            item_id = result.get("id")
            if not item_id:
                continue

            await self.db.update_item_triage(
                item_id,
                priority=result.get("priority", 3),
                summary=result.get("summary", ""),
                action=result.get("action", "fyi"),
            )

            # Create todo if suggested
            if result.get("create_todo") and result.get("todo_title"):
                todo_id = await self.db.insert_todo(
                    title=result["todo_title"],
                    source="ai",
                    priority=result.get("priority", 3),
                )
                await self.db.link_todo(todo_id, item_id)

            # Store draft if provided
            if result.get("draft"):
                await self.db.insert_draft(item_id=item_id, body=result["draft"])

            # Notify if high priority
            if should_notify(result.get("priority", 5), self.config.notification_threshold):
                item = await self.db.get_item(item_id)
                if item:
                    text = format_notification(item)
                    send_terminal_notification(text)


def run_daemon(config: AppConfig):
    """Entry point for running the daemon."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    loop = asyncio.new_event_loop()
    daemon = Daemon(config)

    def shutdown(sig, frame):
        loop.create_task(daemon.stop())

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    try:
        loop.run_until_complete(daemon.start())
    except KeyboardInterrupt:
        loop.run_until_complete(daemon.stop())
    finally:
        loop.close()
```

**Step 4: Run tests**

```bash
pytest tests/test_server.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add src/aa/server.py src/aa/daemon.py tests/test_server.py
git commit -m "feat: daemon with polling loop, triage, and Unix socket server"
```

---

### Task 16: Full CLI Implementation

**Files:**
- Modify: `src/aa/cli.py`
- Create: `tests/test_cli_commands.py`

**Step 1: Write failing tests**

```python
# tests/test_cli_commands.py
import pytest
import json
from unittest.mock import patch, AsyncMock
from click.testing import CliRunner
from aa.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def mock_send_command(response):
    async def _send(socket_path, request):
        return response
    return _send


def test_inbox_command(runner):
    items = [
        {"id": "1", "source": "resilio", "from_name": "Alice", "subject": "Hello",
         "priority": 1, "ai_summary": "Greeting", "ai_suggested_action": "reply"}
    ]
    with patch("aa.cli.send_command", new=mock_send_command({"items": items})):
        result = runner.invoke(main, ["inbox"])
        assert result.exit_code == 0
        assert "Alice" in result.output


def test_todo_list_command(runner):
    todos = [
        {"id": 1, "title": "Fix bug", "priority": 1, "status": "pending",
         "source": "user", "due_date": None}
    ]
    with patch("aa.cli.send_command", new=mock_send_command({"todos": todos})):
        result = runner.invoke(main, ["todo"])
        assert result.exit_code == 0
        assert "Fix bug" in result.output


def test_todo_add_command(runner):
    with patch("aa.cli.send_command", new=mock_send_command({"id": 1, "message": "Todo added"})):
        result = runner.invoke(main, ["todo", "add", "Write tests", "--priority", "2"])
        assert result.exit_code == 0
        assert "added" in result.output.lower() or "Todo" in result.output


def test_rule_add_command(runner):
    with patch("aa.cli.send_command", new=mock_send_command({"id": 1, "message": "Rule added"})):
        result = runner.invoke(main, ["rule", "add", "Emails from CEO are priority 1"])
        assert result.exit_code == 0


def test_status_command(runner):
    resp = {"status": "running", "sources": [
        {"source": "resilio", "last_sync": "2026-03-09T10:00:00", "status": "ok"}
    ]}
    with patch("aa.cli.send_command", new=mock_send_command(resp)):
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0
        assert "resilio" in result.output
```

**Step 2: Run tests to verify failure**

```bash
pytest tests/test_cli_commands.py -v
```

**Step 3: Implement full CLI**

```python
# src/aa/cli.py
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from aa.config import AppConfig

DEFAULT_CONFIG = AppConfig()


async def send_command(socket_path: Path, request: dict) -> dict:
    """Send a command to the daemon and return the response."""
    try:
        reader, writer = await asyncio.open_unix_connection(str(socket_path))
        writer.write(json.dumps(request).encode())
        await writer.drain()
        data = await reader.read(1_000_000)
        writer.close()
        await writer.wait_closed()
        return json.loads(data.decode())
    except (ConnectionRefusedError, FileNotFoundError):
        return {"error": "Daemon is not running. Start it with: aa start"}


def run_async(coro):
    """Run an async function synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def send(request: dict) -> dict:
    """Convenience wrapper."""
    return run_async(send_command(DEFAULT_CONFIG.socket_path, request))


PRIORITY_COLORS = {1: "red", 2: "yellow", 3: "white", 4: "blue", 5: "bright_black"}
PRIORITY_LABELS = {1: "P1", 2: "P2", 3: "P3", 4: "P4", 5: "P5"}


@click.group()
@click.version_option(version="0.1.0")
def main():
    """aa - Personal AI Assistant"""
    pass


# --- Daemon ---

@main.command()
def start():
    """Start the background daemon."""
    import subprocess
    import os

    config_path = DEFAULT_CONFIG.data_dir / "config.json"
    if not config_path.exists():
        click.echo("No config found. Run 'aa setup' first.")
        return

    pid_file = DEFAULT_CONFIG.data_dir / "daemon.pid"
    if pid_file.exists():
        click.echo("Daemon may already be running. Check 'aa status'.")
        return

    # Start daemon as background process
    proc = subprocess.Popen(
        [sys.executable, "-m", "aa.daemon"],
        stdout=open(DEFAULT_CONFIG.log_dir / "daemon.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    pid_file.write_text(str(proc.pid))
    click.echo(f"Daemon started (PID {proc.pid})")


@main.command()
def stop():
    """Stop the background daemon."""
    import os
    import signal

    pid_file = DEFAULT_CONFIG.data_dir / "daemon.pid"
    if not pid_file.exists():
        click.echo("No daemon running.")
        return

    pid = int(pid_file.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        click.echo("Daemon stopped.")
    except ProcessLookupError:
        click.echo("Daemon was not running.")
    pid_file.unlink(missing_ok=True)


@main.command()
def status():
    """Show daemon status and source health."""
    resp = send({"command": "status"})
    if "error" in resp:
        click.echo(resp["error"])
        return

    click.echo(f"Daemon: {resp['status']}")
    click.echo()
    for s in resp.get("sources", []):
        color = "green" if s["status"] == "ok" else "red"
        click.echo(
            f"  {s['source']:20s} last sync: {s['last_sync']:25s} "
            f"status: {click.style(s['status'], fg=color)}"
        )


# --- Inbox ---

@main.command()
@click.option("--source", "-s", default=None, help="Filter by source")
def inbox(source):
    """Show unread items sorted by priority."""
    args = {}
    if source:
        args["source"] = source
    resp = send({"command": "inbox", "args": args})
    if "error" in resp:
        click.echo(resp["error"])
        return

    items = resp.get("items", [])
    if not items:
        click.echo("Inbox empty.")
        return

    for item in items:
        p = item.get("priority") or 5
        label = click.style(PRIORITY_LABELS.get(p, "P?"), fg=PRIORITY_COLORS.get(p, "white"))
        source_name = item.get("source", "")[:15]
        from_name = item.get("from_name", "")[:20]
        summary = item.get("ai_summary") or item.get("subject", "")
        action = item.get("ai_suggested_action", "")
        click.echo(f"  {label} [{source_name}] {from_name:20s} {summary[:50]:50s} → {action}")
    click.echo(f"\n{len(items)} items. Use 'aa show <id>' for details.")


@main.command()
@click.argument("item_id")
def show(item_id):
    """Show full detail for an item."""
    resp = send({"command": "show", "args": {"id": item_id}})
    if "error" in resp:
        click.echo(resp["error"])
        return

    item = resp["item"]
    click.echo(f"ID:       {item['id']}")
    click.echo(f"Source:   {item['source']}")
    click.echo(f"Type:     {item['type']}")
    click.echo(f"From:     {item['from_name']} <{item['from_address']}>")
    click.echo(f"Subject:  {item['subject']}")
    click.echo(f"Time:     {item['timestamp']}")
    click.echo(f"Priority: {item.get('priority', 'untriaged')}")
    click.echo(f"Summary:  {item.get('ai_summary', 'N/A')}")
    click.echo(f"Action:   {item.get('ai_suggested_action', 'N/A')}")
    click.echo(f"\n--- Body ---\n{item.get('body', '')}")


# --- Reply ---

@main.command()
@click.argument("item_id")
def reply(item_id):
    """Draft a response for an item."""
    resp = send({"command": "reply", "args": {"id": item_id}})
    if "error" in resp:
        click.echo(resp["error"])
        return
    click.echo(f"Draft:\n{resp.get('draft', 'No draft available')}")


# --- Reprioritize / Dismiss ---

@main.command()
@click.argument("item_id")
@click.argument("priority", type=int)
def reprioritize(item_id, priority):
    """Change priority of an item (1-5)."""
    resp = send({"command": "reprioritize", "args": {"id": item_id, "priority": priority}})
    click.echo(resp.get("message", resp.get("error", "")))


@main.command()
@click.argument("item_id")
def dismiss(item_id):
    """Dismiss an item as not important."""
    resp = send({"command": "dismiss", "args": {"id": item_id}})
    click.echo(resp.get("message", resp.get("error", "")))


# --- Todos ---

@main.group()
def todo():
    """Manage your todo list."""
    pass


@todo.command("list")
@click.option("--all", "include_done", is_flag=True, help="Include completed todos")
def todo_list(include_done):
    """List todos sorted by priority."""
    resp = send({"command": "todo", "args": {"include_done": include_done}})
    if "error" in resp:
        click.echo(resp["error"])
        return

    todos = resp.get("todos", [])
    if not todos:
        click.echo("No todos.")
        return

    for t in todos:
        p = t.get("priority", 3)
        label = click.style(PRIORITY_LABELS.get(p, "P?"), fg=PRIORITY_COLORS.get(p, "white"))
        status = "✓" if t["status"] == "done" else "○"
        source_tag = f" [AI]" if t.get("source") == "ai" else ""
        due = f" due:{t['due_date']}" if t.get("due_date") else ""
        click.echo(f"  {status} {label} #{t['id']} {t['title']}{source_tag}{due}")


@todo.command("add")
@click.argument("title")
@click.option("--priority", "-p", type=int, default=3, help="Priority 1-5")
@click.option("--due", type=str, default=None, help="Due date")
@click.option("--note", type=str, default=None, help="Note")
def todo_add(title, priority, due, note):
    """Add a new todo."""
    resp = send({"command": "todo_add", "args": {
        "title": title, "priority": priority, "due": due, "note": note
    }})
    click.echo(resp.get("message", resp.get("error", "")))


@todo.command("done")
@click.argument("todo_id", type=int)
def todo_done(todo_id):
    """Mark a todo as complete."""
    resp = send({"command": "todo_done", "args": {"id": todo_id}})
    click.echo(resp.get("message", resp.get("error", "")))


@todo.command("edit")
@click.argument("todo_id", type=int)
@click.option("--priority", "-p", type=int, default=None)
@click.option("--title", type=str, default=None)
@click.option("--note", type=str, default=None)
def todo_edit(todo_id, priority, title, note):
    """Edit a todo."""
    args = {"id": todo_id}
    if priority is not None:
        args["priority"] = priority
    if title is not None:
        args["title"] = title
    if note is not None:
        args["notes"] = note
    resp = send({"command": "todo_edit", "args": args})
    click.echo(resp.get("message", resp.get("error", "")))


@todo.command("rm")
@click.argument("todo_id", type=int)
def todo_rm(todo_id):
    """Remove a todo."""
    resp = send({"command": "todo_rm", "args": {"id": todo_id}})
    click.echo(resp.get("message", resp.get("error", "")))


@todo.command("link")
@click.argument("todo_id", type=int)
@click.argument("item_id")
def todo_link(todo_id, item_id):
    """Link a todo to an inbox item."""
    resp = send({"command": "todo_link", "args": {"todo_id": todo_id, "item_id": item_id}})
    click.echo(resp.get("message", resp.get("error", "")))


# --- Calendar ---

@main.command()
@click.argument("when", default="today")
def calendar(when):
    """Show calendar events."""
    resp = send({"command": "calendar", "args": {"when": when}})
    if "error" in resp:
        click.echo(resp["error"])
        return

    events = resp.get("events", [])
    if not events:
        click.echo("No events.")
        return

    for e in events:
        click.echo(f"  {e.get('timestamp', ''):20s} {e.get('subject', '')} (from {e.get('from_name', '')})")


# --- Ask ---

@main.command()
@click.argument("question")
def ask(question):
    """Ask the AI assistant a question."""
    resp = send({"command": "ask", "args": {"question": question}})
    click.echo(resp.get("answer", resp.get("error", "")))


# --- Rules ---

@main.group()
def rule():
    """Manage triage rules."""
    pass


@rule.command("add")
@click.argument("description")
def rule_add(description):
    """Add a new triage rule."""
    resp = send({"command": "rule_add", "args": {"rule": description}})
    click.echo(resp.get("message", resp.get("error", "")))


@rule.command("list")
def rule_list():
    """List active triage rules."""
    resp = send({"command": "rule_list", "args": {}})
    if "error" in resp:
        click.echo(resp["error"])
        return
    for r in resp.get("rules", []):
        click.echo(f"  #{r['id']} {r['rule']}")


@rule.command("rm")
@click.argument("rule_id", type=int)
def rule_rm(rule_id):
    """Remove a triage rule."""
    resp = send({"command": "rule_rm", "args": {"id": rule_id}})
    click.echo(resp.get("message", resp.get("error", "")))


# --- Setup ---

@main.command()
def setup():
    """First-run setup wizard."""
    click.echo("AA Setup Wizard")
    click.echo("=" * 40)

    config = AppConfig()
    config.ensure_dirs()

    # Anthropic API key
    api_key = click.prompt("Anthropic API key", hide_input=True)
    config.anthropic_api_key = api_key

    # Notes file
    notes = click.prompt("Path to notes file (or leave empty)", default="", show_default=False)
    if notes:
        config.notes_file = notes

    config.save()
    click.echo(f"\nConfig saved to {config.data_dir / 'config.json'}")
    click.echo("Run 'aa start' to begin.")


# Make `aa todo` without subcommand show the list
original_todo_invoke = todo.invoke

def patched_todo_invoke(ctx):
    if not ctx.invoked_subcommand:
        return ctx.invoke(todo_list)
    return original_todo_invoke(ctx)

todo.invoke = patched_todo_invoke
todo.result_callback = lambda *a, **kw: None


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

```bash
pytest tests/test_cli_commands.py -v
```
Expected: PASS

**Step 5: Generate shell completions**

Add to `pyproject.toml`:
```toml
[project.scripts]
aa = "aa.cli:main"
```

Users run: `eval "$(_AA_COMPLETE=bash_source aa)"` to enable tab completion.

**Step 6: Commit**

```bash
git add src/aa/cli.py tests/test_cli_commands.py
git commit -m "feat: full CLI with inbox, todo, rules, calendar, and ask commands"
```

---

### Task 17: Integration Test — End-to-End Flow

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write integration test**

```python
# tests/test_integration.py
import pytest
from pathlib import Path
from aa.db import Database
from aa.server import RequestHandler
from aa.config import AppConfig


@pytest.fixture
async def setup(tmp_path):
    config = AppConfig(data_dir=tmp_path)
    db = Database(tmp_path / "test.db")
    await db.initialize()
    handler = RequestHandler(config=config, db=db)
    return handler, db


@pytest.mark.asyncio
async def test_full_flow(setup):
    handler, db = await setup

    # 1. Insert an item (simulating a connector)
    await db.insert_item({
        "id": "flow-1",
        "source": "resilio",
        "source_id": "x1",
        "type": "email",
        "from_name": "CEO",
        "from_address": "ceo@resilio.com",
        "subject": "Board prep",
        "body": "Need slides by EOD",
        "timestamp": "2026-03-09T10:00:00",
    })

    # 2. Triage it
    await db.update_item_triage("flow-1", priority=1, summary="CEO needs slides", action="reply")

    # 3. Check inbox via handler
    resp = await handler.handle({"command": "inbox", "args": {}})
    assert len(resp["items"]) == 1
    assert resp["items"][0]["priority"] == 1

    # 4. Add a todo
    resp = await handler.handle({"command": "todo_add", "args": {"title": "Make slides", "priority": 1}})
    todo_id = resp["id"]

    # 5. Link todo to item
    await handler.handle({"command": "todo_link", "args": {"todo_id": todo_id, "item_id": "flow-1"}})

    # 6. List todos
    resp = await handler.handle({"command": "todo", "args": {}})
    assert len(resp["todos"]) == 1

    # 7. Add a rule
    await handler.handle({"command": "rule_add", "args": {"rule": "CEO emails are always priority 1"}})
    resp = await handler.handle({"command": "rule_list", "args": {}})
    assert len(resp["rules"]) == 1

    # 8. Give feedback (reprioritize)
    await handler.handle({"command": "reprioritize", "args": {"id": "flow-1", "priority": 2}})
    item = await db.get_item("flow-1")
    assert item["priority"] == 2

    # 9. Mark todo done
    await handler.handle({"command": "todo_done", "args": {"id": todo_id}})
    todo = await db.get_todo(todo_id)
    assert todo["status"] == "done"
```

**Step 2: Run integration test**

```bash
pytest tests/test_integration.py -v
```
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: end-to-end integration test for full inbox-to-todo flow"
```

---

### Task 18: Run All Tests & Final Cleanup

**Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short
```
Expected: ALL PASS

**Step 2: Add tests/__init__.py if missing**

```bash
touch tests/__init__.py
```

**Step 3: Verify CLI installs and runs**

```bash
pip install -e ".[dev]"
aa --version
aa --help
```

**Step 4: Commit any cleanup**

```bash
git add -A
git commit -m "chore: final cleanup and test suite verification"
```
