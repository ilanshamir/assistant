"""Daemon process with polling loop, triage, and Unix socket server."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from aa.ai.notes import NotesExtractor
from aa.ai.rules import build_feedback_summary
from aa.ai.triage import TriageEngine
from aa.config import AppConfig
from aa.connectors.base import BaseConnector
from aa.connectors.calendar import GoogleCalendarConnector, OutlookCalendarConnector
from aa.connectors.gmail import GmailConnector
from aa.connectors.mattermost import MattermostConnector
from aa.connectors.outlook import OutlookConnector
from aa.connectors.slack import SlackConnector
from aa.db import Database
from aa.notifications import format_notification, send_terminal_notification, should_notify
from aa.server import RequestHandler, SocketServer

logger = logging.getLogger(__name__)

# Map source types to their poll interval config keys
POLL_INTERVALS: dict[str, str] = {
    "gmail": "poll_interval_email",
    "outlook": "poll_interval_email",
    "slack": "poll_interval_slack",
    "mattermost": "poll_interval_mattermost",
}


class Daemon:
    """Main daemon process that polls sources, runs triage, and serves requests."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._db: Database | None = None
        self._engine: TriageEngine | None = None
        self._notes_extractor: NotesExtractor | None = None
        self._notes_watcher = None
        self._server: SocketServer | None = None
        self._connectors: list[BaseConnector] = []
        self._running = False

    async def start(self) -> None:
        """Initialize DB, AI engine, server, and start the poll loop."""
        self.config.ensure_dirs()

        # Initialize database
        self._db = Database(self.config.db_path)
        await self._db.initialize()

        # Initialize AI triage engine and notes extractor if API key is available
        if self.config.anthropic_api_key:
            self._engine = TriageEngine(
                api_key=self.config.anthropic_api_key,
                model=self.config.anthropic_model,
            )
            self._notes_extractor = NotesExtractor(
                api_key=self.config.anthropic_api_key,
                model=self.config.anthropic_model,
            )

        # Process existing notes file on startup
        if self.config.notes_file and self._notes_extractor:
            await self._import_notes_file()

        # Initialize connectors from source configs
        for source_name, source_config in self.config.sources.items():
            if not source_config.get("enabled", True):
                continue
            source_type = source_config.get("type", "")
            try:
                connector = self._create_connector(source_name, source_config)
                if connector:
                    self._connectors.append(connector)
                    logger.info("Initialized connector: %s (%s)", source_name, source_type)
            except Exception:
                logger.exception("Failed to initialize connector: %s", source_name)

        # Start socket server
        handler = RequestHandler(self.config, self._db)
        self._server = SocketServer(handler, self.config.socket_path)
        await self._server.start()

        # Start notes file watcher
        if self.config.notes_file and self._notes_extractor:
            from aa.notes_watcher import NotesWatcher

            loop = asyncio.get_event_loop()
            self._notes_watcher = NotesWatcher(
                self.config.notes_file, self._on_notes_changed, loop
            )
            self._notes_watcher.start()

        # Start polling loop
        self._running = True
        await self._poll_loop()

    def _create_connector(
        self, source_name: str, source_config: dict
    ) -> BaseConnector | None:
        """Create a connector instance from source config."""
        source_type = source_config.get("type", "")

        if source_type == "gmail":
            return GmailConnector(
                credentials_path=source_config.get("credentials_file", ""),
                token_path=source_config.get("token_path", ""),
            )
        elif source_type == "outlook":
            return OutlookConnector(
                source_name=source_name,
                client_id=source_config.get("client_id", ""),
                tenant_id=source_config.get("tenant_id", "common"),
                token_cache_path=source_config.get("token_cache_path"),
            )
        elif source_type == "slack":
            connector = SlackConnector(
                source_name=source_name,
                bot_token=source_config.get("token"),
            )
            channels = source_config.get("watched_channels", [])
            if channels:
                connector.set_watched_channels(channels)
            return connector
        elif source_type == "mattermost":
            connector = MattermostConnector(
                url=source_config.get("url"),
                token=source_config.get("token"),
            )
            channels = source_config.get("watched_channels", [])
            if channels:
                connector.set_watched_channels(channels)
            return connector
        else:
            logger.warning("Unknown source type: %s for %s", source_type, source_name)
            return None

    async def _import_notes_file(self) -> None:
        """Process the entire notes file on startup, extracting todos."""
        from pathlib import Path

        assert self._db is not None
        assert self._notes_extractor is not None

        notes_path = Path(self.config.notes_file)
        if not notes_path.exists():
            logger.warning("Notes file not found: %s", notes_path)
            return

        # Check if we've already imported this file (avoid re-importing on restart)
        last_import = await self._db.get_config("notes_last_import_hash")
        content = notes_path.read_text()
        import hashlib
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        if last_import == content_hash:
            logger.info("Notes file unchanged since last import, skipping")
            return

        logger.info("Importing todos from notes file: %s", notes_path)
        await self._extract_and_store_todos(content)
        await self._db.set_config("notes_last_import_hash", content_hash)

    async def _on_notes_changed(self, new_content: str) -> None:
        """Callback when the notes file has new content."""
        logger.info("Notes file changed, extracting todos from new content")
        await self._extract_and_store_todos(new_content)

        # Update the hash so we don't re-import on restart
        if self._db and self.config.notes_file:
            from pathlib import Path
            import hashlib
            content = Path(self.config.notes_file).read_text()
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            await self._db.set_config("notes_last_import_hash", content_hash)

    async def _extract_and_store_todos(self, content: str) -> None:
        """Use AI to extract todos from notes content and store them in DB."""
        assert self._db is not None
        assert self._notes_extractor is not None

        try:
            todos = await self._notes_extractor.extract_todos(content)
        except Exception:
            logger.exception("Failed to extract todos from notes")
            return

        for todo in todos:
            title = todo.get("title", "").strip()
            if not title:
                continue

            # Check for duplicate by title (avoid adding the same todo twice)
            existing = await self._db.list_todos()
            if any(t["title"].lower() == title.lower() for t in existing):
                logger.debug("Skipping duplicate todo: %s", title)
                continue

            todo_id = await self._db.insert_todo(
                title=title,
                priority=todo.get("priority", 3),
                category=todo.get("category"),
                project=todo.get("project"),
                due_date=todo.get("due_date"),
            )

            # Store the extraction notes as a todo note if provided
            notes_text = todo.get("notes")
            if notes_text:
                await self._db.update_todo(todo_id, notes=notes_text)

            logger.info("Added todo from notes: %s (P%d)", title, todo.get("priority", 3))

        if todos:
            logger.info("Extracted %d todos from notes", len(todos))

    async def stop(self) -> None:
        """Stop the server and close the database."""
        self._running = False
        if self._notes_watcher:
            self._notes_watcher.stop()
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
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

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


if __name__ == "__main__":
    import os

    config = AppConfig()
    config_path = config.data_dir / "config.json"
    if config_path.exists():
        config = AppConfig.from_file(config_path)

    # Load API key from environment or config
    api_key = os.environ.get("ANTHROPIC_API_KEY") or config.anthropic_api_key
    if api_key:
        config.anthropic_api_key = api_key

    run_daemon(config)
