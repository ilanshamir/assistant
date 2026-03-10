"""Unix socket server and JSON request handler for the aa daemon."""

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
    """Handles JSON requests from the CLI."""

    def __init__(self, config: AppConfig, db: Database) -> None:
        self.config = config
        self.db = db

    def parse_request(self, data: str) -> dict | None:
        """Parse JSON request string, return None on failure."""
        try:
            return json.loads(data)
        except (json.JSONDecodeError, ValueError):
            return None

    async def handle(self, request: dict) -> dict:
        """Dispatch to command handler based on request['command']."""
        command = request.get("command")
        args = request.get("args", {})

        handlers = {
            "status": self._cmd_status,
            "inbox": self._cmd_inbox,
            "show": self._cmd_show,
            "todo": self._cmd_todo,
            "todo_add": self._cmd_todo_add,
            "todo_done": self._cmd_todo_done,
            "todo_edit": self._cmd_todo_edit,
            "todo_rm": self._cmd_todo_rm,
            "todo_link": self._cmd_todo_link,
            "reprioritize": self._cmd_reprioritize,
            "dismiss": self._cmd_dismiss,
            "rule_add": self._cmd_rule_add,
            "rule_list": self._cmd_rule_list,
            "rule_rm": self._cmd_rule_rm,
            "calendar": self._cmd_calendar,
            "ask": self._cmd_ask,
            "reply": self._cmd_reply,
        }

        handler = handlers.get(command)
        if handler is None:
            return {"ok": False, "error": f"Unknown command: {command}"}

        try:
            return await handler(args)
        except Exception as exc:
            logger.exception("Error handling command %s", command)
            return {"ok": False, "error": str(exc)}

    async def _cmd_status(self, args: dict) -> dict:
        """Return daemon status and per-source sync state."""
        sources = {}
        for source_name in self.config.sources:
            state = await self.db.get_sync_state(source_name)
            sources[source_name] = state or {"status": "never_synced"}
        return {"ok": True, "status": "running", "sources": sources}

    async def _cmd_inbox(self, args: dict) -> dict:
        """List unread items, optionally filtered by source."""
        source = args.get("source")
        items = await self.db.list_items(source=source)
        return {"ok": True, "items": items}

    async def _cmd_show(self, args: dict) -> dict:
        """Get single item by id."""
        item_id = args.get("id")
        if not item_id:
            return {"ok": False, "error": "Missing 'id' argument"}
        item = await self.db.get_item(item_id)
        if item is None:
            return {"ok": False, "error": f"Item not found: {item_id}"}
        return {"ok": True, "item": item}

    async def _cmd_todo(self, args: dict) -> dict:
        """List todos, optionally filtered by category/project."""
        category = args.get("category")
        project = args.get("project")
        todos = await self.db.list_todos(category=category, project=project)
        return {"ok": True, "todos": todos}

    async def _cmd_todo_add(self, args: dict) -> dict:
        """Create a todo."""
        title = args.get("title")
        if not title:
            return {"ok": False, "error": "Missing 'title' argument"}
        todo_id = await self.db.insert_todo(
            title=title,
            priority=args.get("priority", 3),
            category=args.get("category"),
            project=args.get("project"),
            due_date=args.get("due_date"),
        )
        return {"ok": True, "id": todo_id}

    async def _cmd_todo_done(self, args: dict) -> dict:
        """Mark a todo as done."""
        todo_id = args.get("id")
        if not todo_id:
            return {"ok": False, "error": "Missing 'id' argument"}
        await self.db.update_todo(todo_id, status="done")
        return {"ok": True}

    async def _cmd_todo_edit(self, args: dict) -> dict:
        """Update todo fields."""
        todo_id = args.get("id")
        if not todo_id:
            return {"ok": False, "error": "Missing 'id' argument"}
        fields = {k: v for k, v in args.items() if k != "id"}
        if not fields:
            return {"ok": False, "error": "No fields to update"}
        await self.db.update_todo(todo_id, **fields)
        return {"ok": True}

    async def _cmd_todo_rm(self, args: dict) -> dict:
        """Delete a todo."""
        todo_id = args.get("id")
        if not todo_id:
            return {"ok": False, "error": "Missing 'id' argument"}
        await self.db.delete_todo(todo_id)
        return {"ok": True}

    async def _cmd_todo_link(self, args: dict) -> dict:
        """Link a todo to an item."""
        todo_id = args.get("todo_id")
        item_id = args.get("item_id")
        if not todo_id or not item_id:
            return {"ok": False, "error": "Missing 'todo_id' or 'item_id' argument"}
        link_id = await self.db.link_todo(todo_id, item_id)
        return {"ok": True, "id": link_id}

    async def _cmd_reprioritize(self, args: dict) -> dict:
        """Change item priority and record feedback."""
        item_id = args.get("id")
        priority = args.get("priority")
        if not item_id or priority is None:
            return {"ok": False, "error": "Missing 'id' or 'priority' argument"}
        item = await self.db.get_item(item_id)
        if item is None:
            return {"ok": False, "error": f"Item not found: {item_id}"}
        original_priority = item.get("priority")
        original_action = item.get("action")
        await self.db.update_item_triage(item_id, priority, original_action or "fyi")
        await self.db.insert_feedback(
            item_id=item_id,
            original_priority=original_priority,
            corrected_priority=priority,
            original_action=original_action,
            corrected_action=original_action,
        )
        return {"ok": True}

    async def _cmd_dismiss(self, args: dict) -> dict:
        """Set item to priority 5/ignore and record feedback."""
        item_id = args.get("id")
        if not item_id:
            return {"ok": False, "error": "Missing 'id' argument"}
        item = await self.db.get_item(item_id)
        if item is None:
            return {"ok": False, "error": f"Item not found: {item_id}"}
        original_priority = item.get("priority")
        original_action = item.get("action")
        await self.db.update_item_triage(item_id, 5, "ignore")
        await self.db.insert_feedback(
            item_id=item_id,
            original_priority=original_priority,
            corrected_priority=5,
            original_action=original_action,
            corrected_action="ignore",
        )
        return {"ok": True}

    async def _cmd_rule_add(self, args: dict) -> dict:
        """Add a triage rule."""
        rule = args.get("rule")
        if not rule:
            return {"ok": False, "error": "Missing 'rule' argument"}
        rule_id = await self.db.insert_rule(rule)
        return {"ok": True, "id": rule_id}

    async def _cmd_rule_list(self, args: dict) -> dict:
        """List triage rules."""
        rules = await self.db.list_rules()
        return {"ok": True, "rules": rules}

    async def _cmd_rule_rm(self, args: dict) -> dict:
        """Delete a triage rule."""
        rule_id = args.get("id")
        if not rule_id:
            return {"ok": False, "error": "Missing 'id' argument"}
        await self.db.delete_rule(rule_id)
        return {"ok": True}

    async def _cmd_calendar(self, args: dict) -> dict:
        """List calendar events from items."""
        items = await self.db.list_items(source="calendar")
        return {"ok": True, "events": items}

    async def _cmd_ask(self, args: dict) -> dict:
        """Placeholder for AI ask command."""
        return {"ok": False, "error": "Ask requires the AI engine (not yet available in this context)"}

    async def _cmd_reply(self, args: dict) -> dict:
        """Placeholder for AI reply command."""
        return {"ok": False, "error": "Reply requires the AI engine (not yet available in this context)"}


class SocketServer:
    """Unix domain socket server for the aa daemon."""

    def __init__(self, handler: RequestHandler, socket_path: str | Path) -> None:
        self.handler = handler
        self.socket_path = Path(socket_path)
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        """Create and start the Unix socket server."""
        # Remove stale socket file if it exists
        if self.socket_path.exists():
            self.socket_path.unlink()
        self._server = await asyncio.start_unix_server(
            self._client_connected, path=str(self.socket_path)
        )
        logger.info("Socket server listening on %s", self.socket_path)

    async def stop(self) -> None:
        """Close the server and remove the socket file."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self.socket_path.exists():
            self.socket_path.unlink()
        logger.info("Socket server stopped")

    async def _client_connected(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a client connection: read request, handle, write response."""
        try:
            data = await reader.read(1024 * 1024)  # 1 MB max
            if not data:
                return
            request = self.handler.parse_request(data.decode("utf-8"))
            if request is None:
                response = {"ok": False, "error": "Invalid JSON request"}
            else:
                response = await self.handler.handle(request)
            writer.write(json.dumps(response).encode("utf-8"))
            await writer.drain()
        except Exception:
            logger.exception("Error handling client connection")
        finally:
            writer.close()
            await writer.wait_closed()
