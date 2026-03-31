"""Daemon process with polling loop, triage, and Unix socket server."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from typing import Any

from aa.ai.rules import build_feedback_summary
from aa.ai.triage import TriageEngine
from aa.config import AppConfig
from aa.connectors.base import BaseConnector
from aa.connectors.files import FilesConnector
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
    "files": "poll_interval_files",
}


class Daemon:
    """Main daemon process that polls sources, runs triage, and serves requests."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._config_path = config.data_dir / "config.json"
        self._db: Database | None = None
        self._engine: TriageEngine | None = None
        self._server: SocketServer | None = None
        self._web_runner = None
        self._web_site = None
        self._connectors: dict[str, BaseConnector] = {}
        self._running = False
        self._last_export: float = 0

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
        elif source_type == "files":
            return FilesConnector(
                source_name=source_name,
                path=source_config.get("path", ""),
            )
        else:
            logger.warning("Unknown source type: %s for %s", source_type, source_name)
            return None

    def _reload_connectors(self) -> None:
        """Re-read config from disk and reconcile connectors."""
        if self._config_path.exists():
            try:
                new_config = AppConfig.from_file(self._config_path)
                # Preserve runtime-only fields
                api_key = self.config.anthropic_api_key
                new_config.anthropic_api_key = api_key
                self.config.sources = new_config.sources
            except Exception:
                logger.exception("Failed to reload config")
                return

        # Determine desired enabled sources
        desired: dict[str, dict] = {}
        for name, src_cfg in self.config.sources.items():
            if src_cfg.get("enabled", True):
                desired[name] = src_cfg

        # Remove connectors for sources that were deleted or disabled
        for name in list(self._connectors):
            if name not in desired:
                del self._connectors[name]
                logger.info("Removed connector: %s", name)

        # Add connectors for new sources
        for name, src_cfg in desired.items():
            if name not in self._connectors:
                source_type = src_cfg.get("type", "")
                try:
                    connector = self._create_connector(name, src_cfg)
                    if connector:
                        self._connectors[name] = connector
                        logger.info("Initialized connector: %s (%s)", name, source_type)
                except Exception:
                    logger.exception("Failed to initialize connector: %s", name)

    async def _start_web_server(self) -> None:
        """Start the HTTP web server using AppRunner + TCPSite."""
        from aiohttp.web_runner import AppRunner, TCPSite
        from aa.web import create_app

        app = create_app(self.config, self._db)
        self._web_runner = AppRunner(app)
        await self._web_runner.setup()
        self._web_site = TCPSite(
            self._web_runner, "localhost", self.config.web_port
        )
        await self._web_site.start()
        logger.info("Web UI available at http://localhost:%d", self.config.web_port)

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

    async def _poll_loop(self) -> None:
        """Poll all sources, run triage, then sleep."""
        while self._running:
            try:
                self._reload_connectors()
                await self._poll_all_sources()
                await self._run_triage()
                await self._maybe_export_todos()
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
        for connector in self._connectors.values():
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

    async def _maybe_export_todos(self) -> None:
        """Export todos to CSV every 12 hours."""
        export_interval = 12 * 60 * 60  # 12 hours in seconds
        now = time.time()
        if now - self._last_export < export_interval:
            return

        assert self._db is not None
        from aa.cli import export_todos_csv

        todos = await self._db.list_todos(include_deleted=True)
        if not todos:
            return

        export_dir = self.config.data_dir / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = str(export_dir / f"todos_{ts}.csv")
        export_todos_csv(todos, output)
        self._last_export = now
        logger.info("Auto-exported %d todos to %s", len(todos), output)

    async def _run_triage(self) -> None:
        """Get untriaged items, build context, call triage engine, store results."""
        assert self._db is not None
        if self._engine is None:
            return

        untriaged = await self._db.get_untriaged_items()
        if not untriaged:
            return

        # Split notes-type items from regular items — notes get dedicated extraction
        notes_items = [i for i in untriaged if i.get("type") == "notes"]
        regular_items = [i for i in untriaged if i.get("type") != "notes"]

        # Process notes items through NotesExtractor (purpose-built for todo extraction)
        if notes_items:
            await self._extract_notes_todos(notes_items)

        # Process regular items through TriageEngine
        if regular_items:
            await self._triage_regular_items(regular_items)

    async def _extract_notes_todos(self, items: list[dict]) -> None:
        """Use NotesExtractor to extract todos from notes-type items."""
        assert self._db is not None
        from aa.ai.notes import NotesExtractor

        extractor = NotesExtractor(
            api_key=self.config.anthropic_api_key,
            model=self.config.anthropic_model,
        )

        # Get ALL todo titles (pending, in_progress, done, deleted) to avoid
        # re-creating todos that were completed, deleted, or already exist.
        # Use fuzzy matching because the AI may produce slightly different
        # wording each time it processes the same file.
        from difflib import SequenceMatcher

        all_todos = await self._db.list_todos(include_deleted=True)
        existing_titles = [t["title"].lower().strip() for t in all_todos]

        def _is_duplicate(title: str) -> bool:
            """Check if title is a fuzzy match against any existing todo."""
            t = title.lower().strip()
            for existing in existing_titles:
                if existing == t:
                    return True
                if SequenceMatcher(None, existing, t).ratio() > 0.8:
                    return True
            return False

        for item in items:
            item_id = item.get("id")
            body = item.get("body", "")
            if not item_id or not body.strip():
                await self._db.update_item_triage(item_id, 5, "fyi")
                continue

            try:
                extracted = await extractor.extract_todos(body)
            except Exception:
                logger.exception("Notes extraction failed for %s", item_id)
                await self._db.update_item_triage(item_id, 3, "fyi")
                continue

            created = 0
            for todo_spec in extracted:
                title = todo_spec.get("title", "").strip()
                if not title:
                    continue
                if _is_duplicate(title):
                    continue
                todo_id = await self._db.insert_todo(
                    title=title,
                    priority=todo_spec.get("priority", 3),
                    category=todo_spec.get("category"),
                    project=todo_spec.get("project"),
                    due_date=todo_spec.get("due_date"),
                    details=todo_spec.get("notes"),
                    reviewed=False,
                )
                await self._db.link_todo(todo_id, item_id)
                existing_titles.append(title.lower().strip())
                created += 1

            # Mark the item as triaged
            await self._db.update_item_triage(item_id, 3, "fyi")
            logger.info("Extracted %d todos from %s", created, item.get("subject", item_id))

    async def _triage_regular_items(self, untriaged: list[dict]) -> None:
        """Triage non-notes items through the standard TriageEngine."""
        assert self._db is not None

        # Build context for triage
        rules = await self._db.list_rules()
        rule_texts = [r["rule"] for r in rules]

        feedbacks = await self._db.list_feedback()
        feedback_summary = build_feedback_summary(feedbacks)

        # Get active todos including due_dates for context
        todos = await self._db.list_todos(status="pending")

        # Get removed/done todos so triage won't re-create them
        done_todos = await self._db.list_todos(status="done")
        deleted_todos = await self._db.list_todos(status="deleted", include_deleted=True)
        dismissed_todos = [
            {"title": t["title"]} for t in done_todos + deleted_todos
        ]

        # Get today's calendar events
        calendar_items = await self._db.list_items(source="calendar")

        context: dict[str, Any] = {
            "rules": rule_texts,
            "feedback_summary": feedback_summary,
            "active_todos": todos,
            "dismissed_todos": dismissed_todos,
            "calendar_today": calendar_items,
        }

        # Collect all existing todo titles for fuzzy dedup
        from difflib import SequenceMatcher

        all_todos = await self._db.list_todos(include_deleted=True)
        existing_titles = [t["title"].lower().strip() for t in all_todos]

        def _is_duplicate(title: str) -> bool:
            t = title.lower().strip()
            for existing in existing_titles:
                if existing == t:
                    return True
                if SequenceMatcher(None, existing, t).ratio() > 0.8:
                    return True
            return False

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

            # Store triage result
            await self._db.update_item_triage(item_id, priority, action)

            # Create todo(s) if suggested, skipping duplicates
            todos_list = result.get("todos") or []
            if not todos_list and result.get("create_todo") and result.get("todo_title"):
                todos_list = [{"title": result["todo_title"], "priority": priority}]
            for todo_spec in todos_list:
                todo_title = todo_spec.get("title")
                if not todo_title:
                    continue
                if _is_duplicate(todo_title):
                    continue
                todo_prio = todo_spec.get("priority", priority)
                todo_id = await self._db.insert_todo(title=todo_title, priority=todo_prio, reviewed=False)
                await self._db.link_todo(todo_id, item_id)
                existing_titles.append(todo_title.lower().strip())

            # Store draft if present
            draft_text = result.get("draft")
            if draft_text:
                await self._db.insert_draft(item_id, draft_text)

            # Send notification if priority meets threshold
            if should_notify(priority, self.config.notification_threshold):
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

    # Always check env var for API key
    api_key = os.environ.get("ANTHROPIC_API_KEY") or config.anthropic_api_key
    if api_key:
        config.anthropic_api_key = api_key

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
