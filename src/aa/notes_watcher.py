"""Notes file watcher with diff-based change detection."""

import asyncio
import logging
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


def extract_new_content(old: str, new: str) -> str:
    """Return only the lines in `new` that don't appear in `old`."""
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    # Build a multiset of old lines so duplicate handling is correct
    old_counts: dict[str, int] = {}
    for line in old_lines:
        old_counts[line] = old_counts.get(line, 0) + 1

    result: list[str] = []
    for line in new_lines:
        if old_counts.get(line, 0) > 0:
            old_counts[line] -= 1
        else:
            result.append(line)

    return "\n".join(result)


class NotesFileHandler(FileSystemEventHandler):
    """Handles file modification events for a notes file."""

    def __init__(self, file_path: Path, callback, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.file_path = file_path
        self.callback = callback
        self.loop = loop
        self._last_content = ""
        # Read initial content if file exists
        if file_path.exists():
            self._last_content = file_path.read_text()

    def on_modified(self, event):
        if event.is_directory:
            return
        if Path(event.src_path).resolve() != self.file_path.resolve():
            return

        try:
            current_content = self.file_path.read_text()
        except Exception:
            logger.exception("Failed to read notes file %s", self.file_path)
            return

        new_content = extract_new_content(self._last_content, current_content)
        self._last_content = current_content

        if new_content:
            asyncio.run_coroutine_threadsafe(self.callback(new_content), self.loop)


class NotesWatcher:
    """Watches a notes file for changes and invokes a callback with new content."""

    def __init__(
        self,
        file_path: str | Path,
        callback,
        loop: asyncio.AbstractEventLoop,
    ):
        self.file_path = Path(file_path)
        self.callback = callback
        self.loop = loop
        self._observer: Observer | None = None

    def start(self):
        """Start watching the file's parent directory for changes."""
        handler = NotesFileHandler(self.file_path, self.callback, self.loop)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.file_path.parent), recursive=False)
        self._observer.start()
        logger.info("Started watching %s", self.file_path)

    def stop(self):
        """Stop watching for changes."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Stopped watching %s", self.file_path)
