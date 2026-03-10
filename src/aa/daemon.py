"""Daemon process with polling loop, triage, and Unix socket server."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from aa.ai.rules import build_feedback_summary
from aa.ai.triage import TriageEngine
from aa.config import AppConfig
from aa.connectors.base import BaseConnector
from aa.connectors.calendar import CalendarConnector
from aa.connectors.gmail import GmailConnector
from aa.connectors.mattermost import MattermostConnector
from aa.connectors.outlook import OutlookConnector
from aa.connectors.slack import SlackConnector
from aa.db import Database
from aa.notifications import format_notification, send_terminal_notification, should_notify
from aa.server import RequestHandler, SocketServer

logger = logging.getLogger(__name__)

CONNECTOR_MAP: dict[str, type[BaseConnector]] = {
    "gmail": GmailConnector,
    "outlook": OutlookConnector,
    "slack": SlackConnector,
    "mattermost": MattermostConnector,
    "calendar": CalendarConnector,
}

# Map source names to their poll interval config keys
POLL_INTERVALS: dict[str, str] = {
    "gmail": "poll_interval_email",
    "outlook": "poll_interval_email",
    "slack": "poll_interval_slack",
    "mattermost": "poll_interval_mattermost",
    "calendar": "poll_interval_calendar",
}


class Daemon:
    """Main daemon process that polls sources, runs triage, and serves requests."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._db: Database | None = None
        self._engine: TriageEngine | None = None
        self._server: SocketServer | None = None
        self._connectors: list[BaseConnector] = []
        self._running = False

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

        # Initialize connectors
        for source_name, source_config in self.config.sources.items():
            connector_cls = CONNECTOR_MAP.get(source_name)
            if connector_cls:
                connector = connector_cls(source_config)
                self._connectors.append(connector)
                logger.info("Initialized connector: %s", source_name)

        # Start socket server
        handler = RequestHandler(self.config, self._db)
        self._server = SocketServer(handler, self.config.socket_path)
        await self._server.start()

        # Start polling loop
        self._running = True
        await self._poll_loop()

    async def stop(self) -> None:
        """Stop the server and close the database."""
        self._running = False
        if self._server:
            await self._server.stop()
        if self._db:
            await self._db.close()
        logger.info("Daemon stopped")

    async def _poll_loop(self) -> None:
        """Poll all sources, run triage, then sleep."""
        while self._running:
            try:
                await self._poll_all_sources()
                await self._run_triage()
            except Exception:
                logger.exception("Error during poll cycle")

            # Sleep for the minimum poll interval
            min_interval = min(
                (getattr(self.config, attr) for attr in POLL_INTERVALS.values()),
                default=30,
            )
            try:
                await asyncio.sleep(min_interval)
            except asyncio.CancelledError:
                break

    async def _poll_all_sources(self) -> None:
        """Iterate connectors, fetch new items, store in DB."""
        assert self._db is not None
        for connector in self._connectors:
            source_name = connector.source_name
            try:
                # Get current sync cursor
                sync_state = await self._db.get_sync_state(source_name)
                cursor = sync_state["cursor"] if sync_state else None

                # Fetch new items
                items, new_cursor = await connector.fetch_new_items(cursor=cursor)

                # Store items
                for item in items:
                    await self._db.insert_item(item)

                # Update sync state
                await self._db.update_sync_state(
                    source_name, cursor=new_cursor, status="ok"
                )
                logger.info(
                    "Polled %s: %d new items", source_name, len(items)
                )
            except Exception:
                logger.exception("Error polling %s", source_name)
                await self._db.update_sync_state(source_name, status="error")

    async def _run_triage(self) -> None:
        """Get untriaged items, build context, call triage engine, store results."""
        assert self._db is not None
        if self._engine is None:
            return

        untriaged = await self._db.get_untriaged_items()
        if not untriaged:
            return

        # Build context for triage
        rules = await self._db.list_rules()
        rule_texts = [r["rule"] for r in rules]

        feedbacks = await self._db.list_feedback()
        feedback_summary = build_feedback_summary(feedbacks)

        # Get active todos including due_dates for context
        todos = await self._db.list_todos(status="pending")

        # Get today's calendar events
        calendar_items = await self._db.list_items(source="calendar")

        context: dict[str, Any] = {
            "rules": rule_texts,
            "feedback_summary": feedback_summary,
            "active_todos": todos,
            "calendar_today": calendar_items,
        }

        try:
            results = await self._engine.triage(untriaged, context)
        except Exception:
            logger.exception("Triage engine failed")
            return

        for result in results:
            item_id = result.get("id")
            if not item_id:
                continue

            priority = result.get("priority", 3)
            action = result.get("action", "fyi")

            # Store triage result (3 args: item_id, priority, action)
            await self._db.update_item_triage(item_id, priority, action)

            # Create todo if suggested
            if result.get("create_todo") and result.get("todo_title"):
                todo_id = await self._db.insert_todo(title=result["todo_title"], priority=priority)
                await self._db.link_todo(todo_id, item_id)

            # Store draft if present
            draft_text = result.get("draft")
            if draft_text:
                await self._db.insert_draft(item_id, draft_text)

            # Send notification if priority meets threshold
            if should_notify(priority, self.config.notification_threshold):
                # Build an item-like dict with triage info for the notification
                item = await self._db.get_item(item_id)
                if item:
                    notification_text = format_notification(item)
                    send_terminal_notification(notification_text)

        logger.info("Triaged %d items", len(results))


def run_daemon(config: AppConfig) -> None:
    """Entry point that sets up signal handlers and runs the daemon."""
    daemon = Daemon(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _run() -> None:
        # Set up signal handlers for graceful shutdown
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(daemon.stop()))
        await daemon.start()

    try:
        loop.run_until_complete(_run())
    except KeyboardInterrupt:
        loop.run_until_complete(daemon.stop())
    finally:
        loop.close()
