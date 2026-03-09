"""SQLite database layer for the aa personal assistant."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    type TEXT NOT NULL,
    from_name TEXT DEFAULT '',
    from_address TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    body TEXT DEFAULT '',
    timestamp TEXT,
    triaged INTEGER DEFAULT 0,
    priority INTEGER,
    action TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS todos (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    priority INTEGER DEFAULT 3,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS todo_links (
    id TEXT PRIMARY KEY,
    todo_id TEXT NOT NULL REFERENCES todos(id),
    item_id TEXT NOT NULL REFERENCES items(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sync_state (
    source TEXT PRIMARY KEY,
    cursor TEXT,
    status TEXT DEFAULT 'ok',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES items(id),
    body TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    item_id TEXT,
    original_priority INTEGER,
    corrected_priority INTEGER,
    original_action TEXT,
    corrected_action TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS triage_rules (
    id TEXT PRIMARY KEY,
    rule TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    return dict(row)


class Database:
    """Async SQLite database for the aa assistant."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open the database and create tables."""
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        assert self._db is not None, "Database not initialized"
        return self._db

    # --- Tables ---

    async def list_tables(self) -> list[str]:
        cursor = await self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [row["name"] for row in rows]

    # --- Items ---

    async def insert_item(self, item: dict[str, Any]) -> str:
        item_id = item.get("id") or _new_id()
        await self.db.execute(
            """INSERT INTO items (id, source, source_id, type, from_name, from_address,
               subject, body, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item_id,
                item["source"],
                item["source_id"],
                item["type"],
                item.get("from_name", ""),
                item.get("from_address", ""),
                item.get("subject", ""),
                item.get("body", ""),
                item.get("timestamp"),
            ),
        )
        await self.db.commit()
        return item_id

    async def get_item(self, item_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        row = await cursor.fetchone()
        return _row_to_dict(row) if row else None

    async def get_untriaged_items(self) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM items WHERE triaged = 0 ORDER BY timestamp"
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(r) for r in rows]

    async def update_item_triage(
        self, item_id: str, priority: int, action: str
    ) -> None:
        await self.db.execute(
            "UPDATE items SET triaged = 1, priority = ?, action = ?, updated_at = ? WHERE id = ?",
            (priority, action, _now(), item_id),
        )
        await self.db.commit()

    async def list_items(
        self, source: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        if source:
            cursor = await self.db.execute(
                "SELECT * FROM items WHERE source = ? ORDER BY timestamp DESC LIMIT ?",
                (source, limit),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM items ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
        rows = await cursor.fetchall()
        return [_row_to_dict(r) for r in rows]

    # --- Todos ---

    async def insert_todo(self, title: str, priority: int = 3) -> str:
        todo_id = _new_id()
        await self.db.execute(
            "INSERT INTO todos (id, title, priority) VALUES (?, ?, ?)",
            (todo_id, title, priority),
        )
        await self.db.commit()
        return todo_id

    async def get_todo(self, todo_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute("SELECT * FROM todos WHERE id = ?", (todo_id,))
        row = await cursor.fetchone()
        return _row_to_dict(row) if row else None

    async def list_todos(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            cursor = await self.db.execute(
                "SELECT * FROM todos WHERE status = ? ORDER BY priority, created_at",
                (status,),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM todos ORDER BY priority, created_at"
            )
        rows = await cursor.fetchall()
        return [_row_to_dict(r) for r in rows]

    async def update_todo(self, todo_id: str, **kwargs: Any) -> None:
        sets = []
        values = []
        for key, value in kwargs.items():
            sets.append(f"{key} = ?")
            values.append(value)
        if "status" in kwargs and kwargs["status"] == "done" and "completed_at" not in kwargs:
            sets.append("completed_at = ?")
            values.append(_now())
        values.append(todo_id)
        await self.db.execute(
            f"UPDATE todos SET {', '.join(sets)} WHERE id = ?", values
        )
        await self.db.commit()

    async def delete_todo(self, todo_id: str) -> None:
        await self.db.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        await self.db.commit()

    async def link_todo(self, todo_id: str, item_id: str) -> str:
        link_id = _new_id()
        await self.db.execute(
            "INSERT INTO todo_links (id, todo_id, item_id) VALUES (?, ?, ?)",
            (link_id, todo_id, item_id),
        )
        await self.db.commit()
        return link_id

    async def get_todo_links(self, todo_id: str) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM todo_links WHERE todo_id = ?", (todo_id,)
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(r) for r in rows]

    # --- Drafts ---

    async def insert_draft(self, item_id: str, body: str) -> str:
        draft_id = _new_id()
        await self.db.execute(
            "INSERT INTO drafts (id, item_id, body) VALUES (?, ?, ?)",
            (draft_id, item_id, body),
        )
        await self.db.commit()
        return draft_id

    async def get_draft(self, draft_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT * FROM drafts WHERE id = ?", (draft_id,)
        )
        row = await cursor.fetchone()
        return _row_to_dict(row) if row else None

    async def update_draft(self, draft_id: str, **kwargs: Any) -> None:
        sets = ["updated_at = ?"]
        values = [_now()]
        for key, value in kwargs.items():
            sets.append(f"{key} = ?")
            values.append(value)
        values.append(draft_id)
        await self.db.execute(
            f"UPDATE drafts SET {', '.join(sets)} WHERE id = ?", values
        )
        await self.db.commit()

    # --- Sync State ---

    async def update_sync_state(
        self, source: str, cursor: str | None = None, status: str = "ok"
    ) -> None:
        await self.db.execute(
            """INSERT INTO sync_state (source, cursor, status, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(source) DO UPDATE SET cursor = ?, status = ?, updated_at = ?""",
            (source, cursor, status, _now(), cursor, status, _now()),
        )
        await self.db.commit()

    async def get_sync_state(self, source: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT * FROM sync_state WHERE source = ?", (source,)
        )
        row = await cursor.fetchone()
        return _row_to_dict(row) if row else None

    # --- Feedback ---

    async def insert_feedback(
        self,
        item_id: str | None = None,
        original_priority: int | None = None,
        corrected_priority: int | None = None,
        original_action: str | None = None,
        corrected_action: str | None = None,
    ) -> str:
        feedback_id = _new_id()
        await self.db.execute(
            """INSERT INTO feedback (id, item_id, original_priority, corrected_priority,
               original_action, corrected_action) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                feedback_id,
                item_id,
                original_priority,
                corrected_priority,
                original_action,
                corrected_action,
            ),
        )
        await self.db.commit()
        return feedback_id

    async def list_feedback(self, limit: int = 50) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(r) for r in rows]

    # --- Triage Rules ---

    async def insert_rule(self, rule: str) -> str:
        rule_id = _new_id()
        await self.db.execute(
            "INSERT INTO triage_rules (id, rule) VALUES (?, ?)", (rule_id, rule)
        )
        await self.db.commit()
        return rule_id

    async def list_rules(self) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM triage_rules ORDER BY created_at"
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(r) for r in rows]

    async def delete_rule(self, rule_id: str) -> None:
        await self.db.execute("DELETE FROM triage_rules WHERE id = ?", (rule_id,))
        await self.db.commit()

    # --- Config ---

    async def get_config(self, key: str) -> str | None:
        cursor = await self.db.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row["value"] if row else None

    async def set_config(self, key: str, value: str) -> None:
        await self.db.execute(
            """INSERT INTO config (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?""",
            (key, value, _now(), value, _now()),
        )
        await self.db.commit()
