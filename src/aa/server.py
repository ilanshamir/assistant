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

    def __init__(self, config: AppConfig, db: Database, api_key: str | None = None, model: str = "claude-sonnet-4-20250514") -> None:
        self.config = config
        self.db = db
        self._api_key = api_key
        self._model = model

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
            "todo_show": self._cmd_todo_show,
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

    async def _resolve_item(self, raw_id: str) -> str | None:
        """Resolve a partial item ID to a full ID."""
        return await self.db.resolve_id("items", raw_id)

    async def _resolve_todo(self, raw_id: str) -> str | None:
        """Resolve a partial todo ID to a full ID."""
        return await self.db.resolve_id("todos", raw_id)

    async def _cmd_show(self, args: dict) -> dict:
        """Get single item by id."""
        raw_id = args.get("id")
        if not raw_id:
            return {"ok": False, "error": "Missing 'id' argument"}
        item_id = await self._resolve_item(raw_id)
        if not item_id:
            return {"ok": False, "error": f"Item not found: {raw_id}"}
        item = await self.db.get_item(item_id)
        if item is None:
            return {"ok": False, "error": f"Item not found: {raw_id}"}
        # Fetch linked todos
        links = await self.db.get_item_links(item_id)
        linked_todos = []
        for link in links:
            todo = await self.db.get_todo(link["todo_id"])
            if todo:
                linked_todos.append(todo)
        return {"ok": True, "item": item, "linked_todos": linked_todos}

    async def _cmd_todo(self, args: dict) -> dict:
        """List todos with filters."""
        todos = await self.db.list_todos(
            category=args.get("category"),
            project=args.get("project"),
            priority=args.get("priority"),
            max_priority=args.get("max_priority"),
            keyword=args.get("keyword"),
            due_before=args.get("due_before"),
        )
        return {"ok": True, "todos": todos}

    async def _cmd_todo_show(self, args: dict) -> dict:
        """Get single todo by id."""
        raw_id = args.get("id")
        if not raw_id:
            return {"ok": False, "error": "Missing 'id' argument"}
        todo_id = await self._resolve_todo(raw_id)
        if not todo_id:
            return {"ok": False, "error": f"Todo not found: {raw_id}"}
        todo = await self.db.get_todo(todo_id)
        if todo is None:
            return {"ok": False, "error": f"Todo not found: {raw_id}"}
        # Fetch linked items
        links = await self.db.get_todo_links(todo_id)
        linked_items = []
        for link in links:
            item = await self.db.get_item(link["item_id"])
            if item:
                linked_items.append(item)
        return {"ok": True, "todo": todo, "linked_items": linked_items}

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
            details=args.get("details"),
        )
        return {"ok": True, "id": todo_id}

    async def _cmd_todo_done(self, args: dict) -> dict:
        """Mark a todo as done."""
        raw_id = args.get("id")
        if not raw_id:
            return {"ok": False, "error": "Missing 'id' argument"}
        todo_id = await self._resolve_todo(raw_id)
        if not todo_id:
            return {"ok": False, "error": f"Todo not found: {raw_id}"}
        await self.db.update_todo(todo_id, status="done")
        return {"ok": True}

    async def _cmd_todo_edit(self, args: dict) -> dict:
        """Update todo fields."""
        raw_id = args.get("id")
        if not raw_id:
            return {"ok": False, "error": "Missing 'id' argument"}
        todo_id = await self._resolve_todo(raw_id)
        if not todo_id:
            return {"ok": False, "error": f"Todo not found: {raw_id}"}
        fields = {k: v for k, v in args.items() if k != "id"}
        if not fields:
            return {"ok": False, "error": "No fields to update"}
        await self.db.update_todo(todo_id, **fields)
        return {"ok": True}

    async def _cmd_todo_rm(self, args: dict) -> dict:
        """Delete a todo."""
        raw_id = args.get("id")
        if not raw_id:
            return {"ok": False, "error": "Missing 'id' argument"}
        todo_id = await self._resolve_todo(raw_id)
        if not todo_id:
            return {"ok": False, "error": f"Todo not found: {raw_id}"}
        await self.db.delete_todo(todo_id)
        return {"ok": True}

    async def _cmd_todo_link(self, args: dict) -> dict:
        """Link a todo to an item."""
        raw_todo = args.get("todo_id")
        raw_item = args.get("item_id")
        if not raw_todo or not raw_item:
            return {"ok": False, "error": "Missing 'todo_id' or 'item_id' argument"}
        todo_id = await self._resolve_todo(raw_todo)
        if not todo_id:
            return {"ok": False, "error": f"Todo not found: {raw_todo}"}
        item_id = await self._resolve_item(raw_item)
        if not item_id:
            return {"ok": False, "error": f"Item not found: {raw_item}"}
        link_id = await self.db.link_todo(todo_id, item_id)
        return {"ok": True, "id": link_id}

    async def _cmd_reprioritize(self, args: dict) -> dict:
        """Change item priority and record feedback."""
        raw_id = args.get("id")
        priority = args.get("priority")
        if not raw_id or priority is None:
            return {"ok": False, "error": "Missing 'id' or 'priority' argument"}
        item_id = await self._resolve_item(raw_id)
        if not item_id:
            return {"ok": False, "error": f"Item not found: {raw_id}"}
        item = await self.db.get_item(item_id)
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
        raw_id = args.get("id")
        if not raw_id:
            return {"ok": False, "error": "Missing 'id' argument"}
        item_id = await self._resolve_item(raw_id)
        if not item_id:
            return {"ok": False, "error": f"Item not found: {raw_id}"}
        item = await self.db.get_item(item_id)
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
        raw_id = args.get("id")
        if not raw_id:
            return {"ok": False, "error": "Missing 'id' argument"}
        rule_id = await self.db.resolve_id("triage_rules", raw_id)
        if not rule_id:
            return {"ok": False, "error": f"Rule not found: {raw_id}"}
        await self.db.delete_rule(rule_id)
        return {"ok": True}

    async def _cmd_calendar(self, args: dict) -> dict:
        """List calendar events from items."""
        items = await self.db.list_items(source="calendar")
        return {"ok": True, "events": items}

    async def _cmd_ask(self, args: dict) -> dict:
        """Answer a user question using AI with full context."""
        question = args.get("question")
        if not question:
            return {"ok": False, "error": "Missing 'question' argument"}
        if not self._api_key:
            return {"ok": False, "error": "No API key configured. Set ANTHROPIC_API_KEY or configure it in ~/.assistant/config.json"}

        from aa.ai.ask import AskEngine

        engine = AskEngine(api_key=self._api_key, model=self._model)

        # Build context from DB
        todos = await self.db.list_todos(status="pending")
        inbox = await self.db.list_items(limit=20)
        calendar = await self.db.list_items(source="calendar")

        context = {
            "todos": todos,
            "inbox": inbox,
            "calendar": calendar,
        }

        answer = await engine.ask(question, context)
        return {"ok": True, "answer": answer}

    async def _cmd_reply(self, args: dict) -> dict:
        """Generate a draft reply to an item using AI."""
        raw_id = args.get("id")
        if not raw_id:
            return {"ok": False, "error": "Missing 'id' argument"}
        if not self._api_key:
            return {"ok": False, "error": "No API key configured. Set ANTHROPIC_API_KEY or configure it in ~/.assistant/config.json"}

        item_id = await self._resolve_item(raw_id)
        if not item_id:
            return {"ok": False, "error": f"Item not found: {raw_id}"}

        item = await self.db.get_item(item_id)
        if not item:
            return {"ok": False, "error": f"Item not found: {raw_id}"}

        from aa.ai.drafts import DraftGenerator

        generator = DraftGenerator(api_key=self._api_key, model=self._model)
        instruction = args.get("instruction")
        draft_text = await generator.generate_draft(item, user_instruction=instruction)

        # Store the draft
        draft_id = await self.db.insert_draft(item_id, draft_text)

        return {"ok": True, "draft": draft_text, "draft_id": draft_id}


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
