# Shell Mode & File Sources Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an interactive shell, make files/folders a proper source type, and remove setup/import-notes commands.

**Architecture:** A new `FilesConnector` polls files/folders for changes using content hashing, extracts todos via `NotesExtractor`. A `cmd.Cmd`-based interactive shell provides tab-completed commands. Existing one-shot CLI commands are unchanged.

**Tech Stack:** Python `cmd` stdlib, `shlex` for argument parsing, existing `aiosqlite`/`click` stack.

---

### Task 1: Remove `notes_file` from AppConfig and update tests

**Files:**
- Modify: `src/aa/config.py:20` (remove `notes_file` field)
- Modify: `tests/test_config.py:25-27,68,73` (remove notes_file tests)

**Step 1: Update config.py**

In `src/aa/config.py`, remove line 20:
```python
    notes_file: str | None = None
```

Add new field after `poll_interval_mattermost`:
```python
    poll_interval_files: int = 120
```

**Step 2: Update tests/test_config.py**

Remove the `test_default_notes_file_is_none` test (lines 25-27).

In `test_from_file_overrides_defaults`, change the config data from:
```python
        config_file.write_text(json.dumps({
            "poll_interval_email": 120,
            "notification_threshold": 5,
            "notes_file": "/tmp/notes.md",
        }))
        cfg = AppConfig.from_file(config_file)
        assert cfg.poll_interval_email == 120
        assert cfg.notification_threshold == 5
        assert cfg.notes_file == "/tmp/notes.md"
```
to:
```python
        config_file.write_text(json.dumps({
            "poll_interval_email": 120,
            "notification_threshold": 5,
            "poll_interval_files": 60,
        }))
        cfg = AppConfig.from_file(config_file)
        assert cfg.poll_interval_email == 120
        assert cfg.notification_threshold == 5
        assert cfg.poll_interval_files == 60
```

**Step 3: Run tests to verify**

Run: `pytest tests/test_config.py -v`
Expected: All pass.

**Step 4: Commit**

```bash
git add src/aa/config.py tests/test_config.py
git commit -m "refactor: replace notes_file with poll_interval_files in config"
```

---

### Task 2: Delete notes_watcher.py and its tests

**Files:**
- Delete: `src/aa/notes_watcher.py`
- Delete: `tests/test_notes_watcher.py`
- Modify: `pyproject.toml:21` (remove `watchdog` dependency)

**Step 1: Delete the files**

```bash
rm src/aa/notes_watcher.py tests/test_notes_watcher.py
```

**Step 2: Remove watchdog from pyproject.toml**

In `pyproject.toml`, remove this line from `dependencies`:
```
    "watchdog>=4.0",
```

**Step 3: Run tests to verify nothing else breaks**

Run: `pytest --tb=short -q`
Expected: All remaining tests pass. No imports of `notes_watcher` remain (daemon.py will be updated in Task 5).

**Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove notes_watcher and watchdog dependency"
```

---

### Task 3: Create FilesConnector with tests

**Files:**
- Create: `src/aa/connectors/files.py`
- Create: `tests/test_connector_files.py`

**Step 1: Write the failing tests**

Create `tests/test_connector_files.py`:

```python
"""Tests for FilesConnector."""
from __future__ import annotations

import json
import pytest
import pytest_asyncio

from aa.connectors.files import FilesConnector


class TestFilesConnectorSingleFile:
    """Test FilesConnector with a single file path."""

    @pytest.mark.asyncio
    async def test_first_poll_returns_file_as_item(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("TODO: buy milk\nsome other text\n")

        conn = FilesConnector(source_name="mynotes", path=str(f))
        items, cursor = await conn.fetch_new_items(cursor=None)

        assert len(items) == 1
        assert items[0]["source"] == "mynotes"
        assert items[0]["type"] == "notes"
        assert items[0]["body"] == "TODO: buy milk\nsome other text\n"
        assert items[0]["subject"] == "notes.txt"
        assert cursor is not None
        # Cursor is a JSON dict of {filepath: hash}
        cursor_data = json.loads(cursor)
        assert str(f) in cursor_data

    @pytest.mark.asyncio
    async def test_second_poll_unchanged_returns_empty(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("TODO: buy milk\n")

        conn = FilesConnector(source_name="mynotes", path=str(f))
        items, cursor = await conn.fetch_new_items(cursor=None)
        assert len(items) == 1

        # Poll again with same cursor — no changes
        items2, cursor2 = await conn.fetch_new_items(cursor=cursor)
        assert len(items2) == 0

    @pytest.mark.asyncio
    async def test_changed_file_detected(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("line one\n")

        conn = FilesConnector(source_name="mynotes", path=str(f))
        _, cursor = await conn.fetch_new_items(cursor=None)

        # Modify the file
        f.write_text("line one\nline two\n")
        items, cursor2 = await conn.fetch_new_items(cursor=cursor)
        assert len(items) == 1
        assert "line two" in items[0]["body"]

    @pytest.mark.asyncio
    async def test_missing_file_returns_empty(self, tmp_path):
        f = tmp_path / "nonexistent.txt"
        conn = FilesConnector(source_name="mynotes", path=str(f))
        items, cursor = await conn.fetch_new_items(cursor=None)
        assert items == []


class TestFilesConnectorDirectory:
    """Test FilesConnector with a directory path."""

    @pytest.mark.asyncio
    async def test_reads_all_files_recursively(self, tmp_path):
        (tmp_path / "a.txt").write_text("file a\n")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("file b\n")

        conn = FilesConnector(source_name="docs", path=str(tmp_path))
        items, cursor = await conn.fetch_new_items(cursor=None)

        bodies = {item["body"] for item in items}
        assert "file a\n" in bodies
        assert "file b\n" in bodies
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_only_changed_files_on_second_poll(self, tmp_path):
        (tmp_path / "a.txt").write_text("original\n")
        (tmp_path / "b.txt").write_text("also original\n")

        conn = FilesConnector(source_name="docs", path=str(tmp_path))
        _, cursor = await conn.fetch_new_items(cursor=None)

        # Only change one file
        (tmp_path / "a.txt").write_text("modified\n")
        items, _ = await conn.fetch_new_items(cursor=cursor)
        assert len(items) == 1
        assert items[0]["subject"] == "a.txt"

    @pytest.mark.asyncio
    async def test_new_file_detected(self, tmp_path):
        (tmp_path / "a.txt").write_text("file a\n")

        conn = FilesConnector(source_name="docs", path=str(tmp_path))
        _, cursor = await conn.fetch_new_items(cursor=None)

        (tmp_path / "c.txt").write_text("new file\n")
        items, _ = await conn.fetch_new_items(cursor=cursor)
        assert len(items) == 1
        assert items[0]["subject"] == "c.txt"

    @pytest.mark.asyncio
    async def test_skips_binary_files(self, tmp_path):
        (tmp_path / "notes.txt").write_text("text file\n")
        (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        conn = FilesConnector(source_name="docs", path=str(tmp_path))
        items, _ = await conn.fetch_new_items(cursor=None)
        subjects = [item["subject"] for item in items]
        assert "notes.txt" in subjects
        assert "image.png" not in subjects

    @pytest.mark.asyncio
    async def test_empty_directory(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        conn = FilesConnector(source_name="docs", path=str(empty))
        items, cursor = await conn.fetch_new_items(cursor=None)
        assert items == []


class TestAuthenticate:
    @pytest.mark.asyncio
    async def test_authenticate_is_noop(self):
        conn = FilesConnector(source_name="mynotes", path="/tmp/notes.txt")
        await conn.authenticate()  # Should not raise
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_connector_files.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aa.connectors.files'`

**Step 3: Write the implementation**

Create `src/aa/connectors/files.py`:

```python
"""Connector that polls local files and directories for changes."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from aa.connectors.base import BaseConnector

logger = logging.getLogger(__name__)


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _is_text_file(path: Path) -> bool:
    """Check if a file is likely a text file by reading a small sample."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
        # Check for null bytes (binary indicator)
        return b"\x00" not in chunk
    except (OSError, PermissionError):
        return False


class FilesConnector(BaseConnector):
    """Polls local files/directories for changes, returning changed content as items."""

    def __init__(self, source_name: str, path: str) -> None:
        self.source_name = source_name
        self.path = Path(path)

    async def authenticate(self) -> None:
        """No authentication needed for local files."""
        pass

    async def fetch_new_items(
        self, cursor: str | None = None
    ) -> tuple[list[dict], str | None]:
        """Read files, compare hashes to cursor, return changed files as items."""
        old_hashes: dict[str, str] = {}
        if cursor:
            old_hashes = json.loads(cursor)

        # Collect all files to check
        files = self._collect_files()

        items = []
        new_hashes: dict[str, str] = {}

        for file_path in files:
            try:
                content = file_path.read_text()
            except (OSError, UnicodeDecodeError):
                continue

            content_hash = _hash_content(content)
            key = str(file_path)
            new_hashes[key] = content_hash

            if old_hashes.get(key) != content_hash:
                items.append({
                    "id": f"{self.source_name}-{content_hash[:16]}",
                    "source": self.source_name,
                    "source_id": key,
                    "type": "notes",
                    "from_name": "",
                    "from_address": "",
                    "subject": file_path.name,
                    "body": content,
                    "timestamp": None,
                })

        new_cursor = json.dumps(new_hashes) if new_hashes else None
        return items, new_cursor

    def _collect_files(self) -> list[Path]:
        """Collect text files from path (single file or recursive directory)."""
        if not self.path.exists():
            return []

        if self.path.is_file():
            if _is_text_file(self.path):
                return [self.path]
            return []

        if self.path.is_dir():
            files = []
            for p in sorted(self.path.rglob("*")):
                if p.is_file() and _is_text_file(p):
                    files.append(p)
            return files

        return []
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_connector_files.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/aa/connectors/files.py tests/test_connector_files.py
git commit -m "feat: add FilesConnector for polling local files and directories"
```

---

### Task 4: Add `files` to CLI source commands

**Files:**
- Modify: `src/aa/cli.py:554,570-571,578-638` (source add)
- Modify: `tests/test_cli_source.py` (add files tests)

**Step 1: Write the failing tests**

Add to `tests/test_cli_source.py`, inside the `TestSourceAdd` class:

```python
    def test_add_files_source_single_file(self, runner, patched_config, tmp_path):
        notes = tmp_path / "notes.txt"
        notes.write_text("some notes")
        result = runner.invoke(main, [
            "source", "add", "mynotes",
            "--type", "files",
            "--path", str(notes),
        ])
        assert result.exit_code == 0, result.output
        assert "mynotes" in result.output

        cfg = AppConfig.from_file(patched_config.data_dir / "config.json")
        src = cfg.sources["mynotes"]
        assert src["type"] == "files"
        assert src["path"] == str(notes)
        assert src["enabled"] is True

    def test_add_files_source_directory(self, runner, patched_config, tmp_path):
        notes_dir = tmp_path / "notes"
        notes_dir.mkdir()
        result = runner.invoke(main, [
            "source", "add", "alldocs",
            "--type", "files",
            "--path", str(notes_dir),
        ])
        assert result.exit_code == 0, result.output

        cfg = AppConfig.from_file(patched_config.data_dir / "config.json")
        src = cfg.sources["alldocs"]
        assert src["type"] == "files"
        assert src["path"] == str(notes_dir)

    def test_add_files_missing_path(self, runner, patched_config):
        result = runner.invoke(main, [
            "source", "add", "mynotes",
            "--type", "files",
        ])
        assert result.exit_code != 0
        assert "path" in result.output.lower() or "required" in result.output.lower()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_source.py::TestSourceAdd::test_add_files_source_single_file -v`
Expected: FAIL — `files` is not a valid choice.

**Step 3: Update cli.py**

In `src/aa/cli.py`, change line 554:
```python
VALID_SOURCE_TYPES = ("gmail", "outlook", "slack", "mattermost", "files")
```

Add `--path` option to `source_add` (after the `--channels` option):
```python
@click.option("--path", default=None, help="File or directory path (files)")
```

Update the `source_add` function signature to include `path`:
```python
def source_add(name, source_type, credentials_file, client_id, tenant_id, token, url, channels, path):
```

Add the `files` case before the final `config.ensure_dirs()` line, after the mattermost elif:

```python
    elif source_type == "files":
        if not path:
            raise click.UsageError("--path is required for files sources")
        source_cfg = {
            "type": "files",
            "path": path,
            "enabled": True,
        }
        msg = f"Source '{name}' (files) added."
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_source.py -v`
Expected: All pass (old + new tests).

**Step 5: Commit**

```bash
git add src/aa/cli.py tests/test_cli_source.py
git commit -m "feat: add files source type to CLI source commands"
```

---

### Task 5: Update daemon to use FilesConnector and remove notes watcher code

**Files:**
- Modify: `src/aa/daemon.py`

**Step 1: Update daemon.py**

Replace the entire file. Key changes:
- Remove imports: `NotesExtractor`, `NotesWatcher`
- Remove from `__init__`: `_notes_extractor`, `_notes_watcher`
- Remove methods: `_import_notes_file`, `_on_notes_changed`, `_extract_and_store_todos`
- Remove notes watcher start/stop code from `start()` and `stop()`
- Add `FilesConnector` import and case in `_create_connector()`
- Add `"files": "poll_interval_files"` to `POLL_INTERVALS`

In imports, remove:
```python
from aa.ai.notes import NotesExtractor
```
Add:
```python
from aa.connectors.files import FilesConnector
```

Change `POLL_INTERVALS` to:
```python
POLL_INTERVALS: dict[str, str] = {
    "gmail": "poll_interval_email",
    "outlook": "poll_interval_email",
    "slack": "poll_interval_slack",
    "mattermost": "poll_interval_mattermost",
    "files": "poll_interval_files",
}
```

In `__init__`, remove:
```python
        self._notes_extractor: NotesExtractor | None = None
        self._notes_watcher = None
```

In `start()`, remove all notes-related blocks (lines 62-65, 67-69, 89-97).

In `stop()`, remove:
```python
        if self._notes_watcher:
            self._notes_watcher.stop()
```

In `_create_connector()`, add the `files` case:
```python
        elif source_type == "files":
            return FilesConnector(
                source_name=source_name,
                path=source_config.get("path", ""),
            )
```

Delete these methods entirely:
- `_import_notes_file`
- `_on_notes_changed`
- `_extract_and_store_todos`

**Step 2: Run all tests**

Run: `pytest --tb=short -q`
Expected: All pass. The daemon no longer references `notes_watcher` or `NotesExtractor` directly.

**Step 3: Commit**

```bash
git add src/aa/daemon.py
git commit -m "refactor: remove notes watcher, add FilesConnector to daemon"
```

---

### Task 6: Remove setup and import-notes commands from CLI

**Files:**
- Modify: `src/aa/cli.py:690-798` (remove setup and import-notes commands)

**Step 1: Remove commands**

In `src/aa/cli.py`, delete:
- The `import_notes` command function (lines 690-761)
- The `_add_todos_to_db` helper (lines 763-775)
- The `setup` command function (lines 778-798)

**Step 2: Run tests**

Run: `pytest --tb=short -q`
Expected: All pass. No existing tests reference `setup` or `import-notes`.

**Step 3: Commit**

```bash
git add src/aa/cli.py
git commit -m "refactor: remove setup and import-notes CLI commands"
```

---

### Task 7: Create interactive shell with tests

**Files:**
- Create: `src/aa/shell.py`
- Create: `tests/test_shell.py`

**Step 1: Write the failing tests**

Create `tests/test_shell.py`:

```python
"""Tests for the interactive AA shell."""
from __future__ import annotations

from io import StringIO
from unittest.mock import patch, MagicMock

import pytest

from aa.shell import AAShell


def make_shell(**send_responses):
    """Create a shell with mocked send function."""
    default_status = {"ok": True, "status": "running", "sources": {}}
    default_inbox = {"ok": True, "items": []}
    default_todos = {"ok": True, "todos": []}

    responses = {
        "status": default_status,
        "inbox": default_inbox,
        "todo": default_todos,
        **send_responses,
    }

    def mock_send(request):
        cmd = request.get("command", "")
        return responses.get(cmd, {"ok": True})

    shell = AAShell.__new__(AAShell)
    shell.send = mock_send
    shell.prompt = "aa> "
    shell.use_rawinput = False
    return shell


class TestShellCommands:
    def test_do_inbox_calls_send(self):
        items = [
            {"id": "abc", "source": "gmail", "from_name": "Alice",
             "subject": "Hello", "priority": 1}
        ]
        shell = make_shell(inbox={"ok": True, "items": items})
        out = StringIO()
        shell.stdout = out
        shell.do_inbox("")
        assert "Alice" in out.getvalue()

    def test_do_status(self):
        shell = make_shell(status={
            "ok": True, "status": "running",
            "sources": {"gmail": {"status": "ok"}},
        })
        out = StringIO()
        shell.stdout = out
        shell.do_status("")
        assert "running" in out.getvalue().lower()

    def test_do_todo_lists(self):
        todos = [{"id": "t1", "title": "Buy milk", "priority": 2,
                  "status": "pending", "category": None, "project": None,
                  "due_date": None}]
        shell = make_shell(todo={"ok": True, "todos": todos})
        out = StringIO()
        shell.stdout = out
        shell.do_todo("")
        assert "Buy milk" in out.getvalue()

    def test_do_todo_add(self):
        calls = []
        shell = make_shell()
        original_send = shell.send
        def capturing_send(req):
            calls.append(req)
            return {"ok": True, "id": "new-id"}
        shell.send = capturing_send
        out = StringIO()
        shell.stdout = out
        shell.do_todo('add "Fix bug" -p 1')
        assert any(c.get("command") == "todo_add" for c in calls)

    def test_do_quit_returns_true(self):
        shell = make_shell()
        assert shell.do_quit("") is True

    def test_do_exit_returns_true(self):
        shell = make_shell()
        assert shell.do_exit("") is True

    def test_do_EOF_returns_true(self):
        shell = make_shell()
        assert shell.do_EOF("") is True

    def test_help_lists_commands(self):
        shell = make_shell()
        out = StringIO()
        shell.stdout = out
        shell.do_help("")
        output = out.getvalue()
        assert "inbox" in output
        assert "todo" in output
        assert "status" in output


class TestShellCompletion:
    def test_complete_todo_subcommands(self):
        shell = make_shell()
        completions = shell.complete_todo("", "todo ", 5, 5)
        assert "list" in completions
        assert "add" in completions
        assert "done" in completions

    def test_complete_todo_partial(self):
        shell = make_shell()
        completions = shell.complete_todo("li", "todo li", 5, 7)
        assert "list" in completions
        assert "add" not in completions

    def test_complete_rule_subcommands(self):
        shell = make_shell()
        completions = shell.complete_rule("", "rule ", 5, 5)
        assert "add" in completions
        assert "list" in completions
        assert "rm" in completions

    def test_complete_source_subcommands(self):
        shell = make_shell()
        completions = shell.complete_source("", "source ", 7, 7)
        assert "add" in completions
        assert "list" in completions
        assert "rm" in completions
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_shell.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aa.shell'`

**Step 3: Write the implementation**

Create `src/aa/shell.py`:

```python
"""Interactive shell for the aa personal assistant."""

from __future__ import annotations

import cmd
import shlex
from typing import Any

from aa.cli import send, priority_label, truncate, status_indicator, PRIORITY_COLORS


class AAShell(cmd.Cmd):
    """Interactive shell with tab completion for aa commands."""

    prompt = "aa> "
    intro = ""

    def __init__(self, send_fn=None):
        super().__init__()
        self.send = send_fn or send
        self._build_intro()

    def _build_intro(self):
        """Build welcome banner with status summary."""
        parts = ["AA Assistant"]
        try:
            resp = self.send({"command": "status", "args": {}})
            if resp.get("ok"):
                parts.append(f"daemon: {resp.get('status', 'unknown')}")
        except Exception:
            parts.append("daemon: not connected")

        try:
            resp = self.send({"command": "inbox", "args": {}})
            if resp.get("ok"):
                count = len(resp.get("items", []))
                parts.append(f"{count} unread")
        except Exception:
            pass

        try:
            resp = self.send({"command": "todo", "args": {}})
            if resp.get("ok"):
                todos = resp.get("todos", [])
                pending = sum(1 for t in todos if t.get("status") != "done")
                parts.append(f"{pending} todos")
        except Exception:
            pass

        self.intro = " | ".join(parts)

    def _print(self, text: str):
        """Print to stdout (supports redirection in tests)."""
        self.stdout.write(text + "\n")

    def _display_error(self, resp: dict):
        self._print(f"Error: {resp.get('error', 'Unknown error')}")

    # --- Commands ---

    def do_inbox(self, arg: str):
        """Show unread inbox items. Usage: inbox [--source SOURCE]"""
        args = {}
        parts = shlex.split(arg) if arg else []
        if "--source" in parts or "-s" in parts:
            flag = "--source" if "--source" in parts else "-s"
            idx = parts.index(flag)
            if idx + 1 < len(parts):
                args["source"] = parts[idx + 1]

        resp = self.send({"command": "inbox", "args": args})
        if not resp.get("ok"):
            self._display_error(resp)
            return

        items = resp.get("items", [])
        if not items:
            self._print("Inbox is empty.")
            return

        for item in items:
            p = priority_label(item.get("priority"))
            src = truncate(item.get("source", ""), 15)
            frm = truncate(item.get("from_name", ""), 20)
            subj = item.get("subject", "(no subject)")
            iid = item.get("id", "")[:8]
            self._print(f"  {p}  {src:15s}  {frm:20s}  {subj}  [{iid}]")

    def do_show(self, arg: str):
        """Show full detail for an item. Usage: show ITEM_ID"""
        if not arg.strip():
            self._print("Usage: show ITEM_ID")
            return
        resp = self.send({"command": "show", "args": {"id": arg.strip()}})
        if not resp.get("ok"):
            self._display_error(resp)
            return
        item = resp.get("item", {})
        self._print(f"ID:       {item.get('id', '')}")
        self._print(f"Source:   {item.get('source', '')}")
        self._print(f"From:     {item.get('from_name', '')}")
        self._print(f"Subject:  {item.get('subject', '')}")
        self._print(f"Priority: {priority_label(item.get('priority'))}")
        self._print(f"Action:   {item.get('action', '')}")
        self._print(f"Received: {item.get('received_at', '')}")
        self._print(f"\n{item.get('body', '')}")

    def do_reply(self, arg: str):
        """Request a draft response. Usage: reply ITEM_ID"""
        if not arg.strip():
            self._print("Usage: reply ITEM_ID")
            return
        resp = self.send({"command": "reply", "args": {"id": arg.strip()}})
        if not resp.get("ok"):
            self._display_error(resp)
            return
        self._print(resp.get("draft", ""))

    def do_reprioritize(self, arg: str):
        """Change an item's priority. Usage: reprioritize ITEM_ID PRIORITY"""
        parts = shlex.split(arg) if arg else []
        if len(parts) < 2:
            self._print("Usage: reprioritize ITEM_ID PRIORITY")
            return
        resp = self.send({"command": "reprioritize", "args": {"id": parts[0], "priority": int(parts[1])}})
        if not resp.get("ok"):
            self._display_error(resp)
            return
        self._print("Priority updated.")

    def do_dismiss(self, arg: str):
        """Dismiss an item. Usage: dismiss ITEM_ID"""
        if not arg.strip():
            self._print("Usage: dismiss ITEM_ID")
            return
        resp = self.send({"command": "dismiss", "args": {"id": arg.strip()}})
        if not resp.get("ok"):
            self._display_error(resp)
            return
        self._print("Item dismissed.")

    def do_todo(self, arg: str):
        """Manage todos. Usage: todo [list|add|done|edit|rm|link] [args]"""
        parts = shlex.split(arg) if arg else []
        subcmd = parts[0] if parts else "list"
        rest = parts[1:]

        if subcmd == "list":
            self._todo_list(rest)
        elif subcmd == "add":
            self._todo_add(rest)
        elif subcmd == "done":
            self._todo_done(rest)
        elif subcmd == "edit":
            self._todo_edit(rest)
        elif subcmd == "rm":
            self._todo_rm(rest)
        elif subcmd == "link":
            self._todo_link(rest)
        else:
            self._print("Unknown todo subcommand. Use: list, add, done, edit, rm, link")

    def _todo_list(self, parts: list[str]):
        args: dict[str, Any] = {}
        i = 0
        while i < len(parts):
            if parts[i] in ("--category", "-c") and i + 1 < len(parts):
                args["category"] = parts[i + 1]; i += 2
            elif parts[i] == "--project" and i + 1 < len(parts):
                args["project"] = parts[i + 1]; i += 2
            elif parts[i] in ("--priority", "-p") and i + 1 < len(parts):
                args["priority"] = int(parts[i + 1]); i += 2
            elif parts[i] == "--urgent":
                args["max_priority"] = 2; i += 1
            elif parts[i] in ("--keyword", "-k") and i + 1 < len(parts):
                args["keyword"] = parts[i + 1]; i += 2
            elif parts[i] == "--due" and i + 1 < len(parts):
                from datetime import date, timedelta
                today = date.today()
                val = parts[i + 1]
                if val == "overdue":
                    args["due_before"] = (today - timedelta(days=1)).isoformat()
                elif val == "today":
                    args["due_before"] = today.isoformat()
                elif val == "week":
                    args["due_before"] = (today + timedelta(days=7)).isoformat()
                else:
                    args["due_before"] = val
                i += 2
            elif parts[i] == "--all":
                args["all"] = True; i += 1
            else:
                i += 1

        resp = self.send({"command": "todo", "args": args})
        if not resp.get("ok"):
            self._display_error(resp)
            return

        todos = resp.get("todos", [])
        if not todos:
            self._print("No todos.")
            return

        for t in todos:
            ind = status_indicator(t.get("status"))
            p = priority_label(t.get("priority"))
            title = t.get("title", "")
            tid = t.get("id", "")[:8]
            due = t.get("due_date") or ""
            cat = t.get("category") or ""
            line_parts = [f"  {ind} {p}  {title}  [{tid}]"]
            if due:
                line_parts.append(f"due:{due}")
            if cat:
                line_parts.append(f"@{cat}")
            self._print("  ".join(line_parts))

    def _todo_add(self, parts: list[str]):
        if not parts:
            self._print("Usage: todo add TITLE [-p PRIORITY] [-c CATEGORY] [--project P] [--due DATE]")
            return
        args: dict[str, Any] = {}
        title_parts = []
        i = 0
        while i < len(parts):
            if parts[i] in ("--priority", "-p") and i + 1 < len(parts):
                args["priority"] = int(parts[i + 1]); i += 2
            elif parts[i] in ("--category", "-c") and i + 1 < len(parts):
                args["category"] = parts[i + 1]; i += 2
            elif parts[i] == "--project" and i + 1 < len(parts):
                args["project"] = parts[i + 1]; i += 2
            elif parts[i] == "--due" and i + 1 < len(parts):
                args["due_date"] = parts[i + 1]; i += 2
            elif parts[i] == "--note" and i + 1 < len(parts):
                args["note"] = parts[i + 1]; i += 2
            else:
                title_parts.append(parts[i]); i += 1
        args["title"] = " ".join(title_parts)
        if not args["title"]:
            self._print("Usage: todo add TITLE")
            return
        if "priority" not in args:
            args["priority"] = 3
        resp = self.send({"command": "todo_add", "args": args})
        if not resp.get("ok"):
            self._display_error(resp)
            return
        self._print(f"Created todo {resp.get('id', '')}")

    def _todo_done(self, parts: list[str]):
        if not parts:
            self._print("Usage: todo done TODO_ID")
            return
        resp = self.send({"command": "todo_done", "args": {"id": parts[0]}})
        if not resp.get("ok"):
            self._display_error(resp)
            return
        self._print("Todo marked as done.")

    def _todo_edit(self, parts: list[str]):
        if not parts:
            self._print("Usage: todo edit TODO_ID [--title T] [-p N] [-c CAT] [--project P] [--due D]")
            return
        args: dict[str, Any] = {"id": parts[0]}
        i = 1
        while i < len(parts):
            if parts[i] in ("--priority", "-p") and i + 1 < len(parts):
                args["priority"] = int(parts[i + 1]); i += 2
            elif parts[i] == "--title" and i + 1 < len(parts):
                args["title"] = parts[i + 1]; i += 2
            elif parts[i] in ("--category", "-c") and i + 1 < len(parts):
                args["category"] = parts[i + 1]; i += 2
            elif parts[i] == "--project" and i + 1 < len(parts):
                args["project"] = parts[i + 1]; i += 2
            elif parts[i] == "--due" and i + 1 < len(parts):
                args["due_date"] = parts[i + 1]; i += 2
            elif parts[i] == "--note" and i + 1 < len(parts):
                args["note"] = parts[i + 1]; i += 2
            else:
                i += 1
        resp = self.send({"command": "todo_edit", "args": args})
        if not resp.get("ok"):
            self._display_error(resp)
            return
        self._print("Todo updated.")

    def _todo_rm(self, parts: list[str]):
        if not parts:
            self._print("Usage: todo rm TODO_ID")
            return
        resp = self.send({"command": "todo_rm", "args": {"id": parts[0]}})
        if not resp.get("ok"):
            self._display_error(resp)
            return
        self._print("Todo removed.")

    def _todo_link(self, parts: list[str]):
        if len(parts) < 2:
            self._print("Usage: todo link TODO_ID ITEM_ID")
            return
        resp = self.send({"command": "todo_link", "args": {"todo_id": parts[0], "item_id": parts[1]}})
        if not resp.get("ok"):
            self._display_error(resp)
            return
        self._print("Linked.")

    def do_calendar(self, arg: str):
        """Show calendar events. Usage: calendar [today|tomorrow|week]"""
        when = arg.strip() or "today"
        resp = self.send({"command": "calendar", "args": {"when": when}})
        if not resp.get("ok"):
            self._display_error(resp)
            return
        events = resp.get("events", [])
        if not events:
            self._print("No events.")
            return
        for ev in events:
            subj = ev.get("subject", "(no subject)")
            time = ev.get("received_at", "")
            self._print(f"  {time}  {subj}")

    def do_ask(self, arg: str):
        """Ask the AI a question. Usage: ask QUESTION"""
        if not arg.strip():
            self._print("Usage: ask QUESTION")
            return
        resp = self.send({"command": "ask", "args": {"question": arg.strip()}})
        if not resp.get("ok"):
            self._display_error(resp)
            return
        self._print(resp.get("answer", ""))

    def do_rule(self, arg: str):
        """Manage triage rules. Usage: rule [list|add|rm] [args]"""
        parts = shlex.split(arg) if arg else []
        subcmd = parts[0] if parts else "list"
        rest = parts[1:]

        if subcmd == "list":
            resp = self.send({"command": "rule_list", "args": {}})
            if not resp.get("ok"):
                self._display_error(resp)
                return
            rules = resp.get("rules", [])
            if not rules:
                self._print("No rules.")
                return
            for r in rules:
                self._print(f"  [{r.get('id', '')}]  {r.get('rule', '')}")
        elif subcmd == "add":
            if not rest:
                self._print("Usage: rule add DESCRIPTION")
                return
            resp = self.send({"command": "rule_add", "args": {"rule": " ".join(rest)}})
            if not resp.get("ok"):
                self._display_error(resp)
                return
            self._print(f"Rule added: {resp.get('id', '')}")
        elif subcmd == "rm":
            if not rest:
                self._print("Usage: rule rm RULE_ID")
                return
            resp = self.send({"command": "rule_rm", "args": {"id": rest[0]}})
            if not resp.get("ok"):
                self._display_error(resp)
                return
            self._print("Rule removed.")
        else:
            self._print("Unknown rule subcommand. Use: list, add, rm")

    def do_source(self, arg: str):
        """Manage sources. Usage: source [list|add|rm] [args]"""
        parts = shlex.split(arg) if arg else []
        subcmd = parts[0] if parts else "list"

        if subcmd == "list":
            self._print("Use 'aa source list' from the command line to manage sources.")
        elif subcmd == "add":
            self._print("Use 'aa source add' from the command line to manage sources.")
        elif subcmd == "rm":
            self._print("Use 'aa source rm' from the command line to manage sources.")
        else:
            self._print("Use 'aa source' from the command line to manage sources.")

    def do_status(self, arg: str):
        """Show daemon health and sync state."""
        resp = self.send({"command": "status", "args": {}})
        if not resp.get("ok"):
            self._display_error(resp)
            return
        status = resp.get("status", "unknown")
        self._print(f"Daemon: {status}")
        sources = resp.get("sources", {})
        if not sources:
            self._print("  No sources configured.")
            return
        for name, state in sources.items():
            src_status = state.get("status", "unknown")
            self._print(f"  {truncate(name, 15):15s}  {src_status}")

    def do_start(self, arg: str):
        """Start the daemon. (Use from command line instead: aa start)"""
        self._print("Use 'aa start' from the command line to start the daemon.")

    def do_stop(self, arg: str):
        """Stop the daemon. (Use from command line instead: aa stop)"""
        self._print("Use 'aa stop' from the command line to stop the daemon.")

    def do_quit(self, arg: str):
        """Exit the shell."""
        return True

    def do_exit(self, arg: str):
        """Exit the shell."""
        return True

    def do_EOF(self, arg: str):
        """Exit the shell (Ctrl-D)."""
        self._print("")
        return True

    def do_help(self, arg: str):
        """List available commands."""
        if arg:
            super().do_help(arg)
            return
        self._print("Available commands:")
        self._print("  inbox          Show unread inbox items")
        self._print("  show ID        Show full detail for an item")
        self._print("  reply ID       Request a draft response")
        self._print("  reprioritize ID PRIORITY  Change priority")
        self._print("  dismiss ID     Dismiss an item")
        self._print("  todo           Manage todos (list/add/done/edit/rm/link)")
        self._print("  calendar       Show calendar events")
        self._print("  ask QUESTION   Ask the AI a question")
        self._print("  rule           Manage triage rules (list/add/rm)")
        self._print("  source         Manage sources (list/add/rm)")
        self._print("  status         Show daemon health")
        self._print("  quit / exit    Exit the shell")

    # --- Tab completion ---

    def complete_todo(self, text, line, begidx, endidx):
        subs = ["list", "add", "done", "edit", "rm", "link"]
        return [s for s in subs if s.startswith(text)]

    def complete_rule(self, text, line, begidx, endidx):
        subs = ["list", "add", "rm"]
        return [s for s in subs if s.startswith(text)]

    def complete_source(self, text, line, begidx, endidx):
        subs = ["list", "add", "rm"]
        return [s for s in subs if s.startswith(text)]
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_shell.py -v`
Expected: All pass.

**Step 5: Commit**

```bash
git add src/aa/shell.py tests/test_shell.py
git commit -m "feat: add interactive shell with tab completion"
```

---

### Task 8: Wire shell into CLI entry point

**Files:**
- Modify: `src/aa/cli.py:96-102` (main group)

**Step 1: Update main() in cli.py**

Change the `main` function from:
```python
@click.group(invoke_without_command=True)
@click.version_option(version="0.1.0")
@click.pass_context
def main(ctx):
    """AA - Personal AI Assistant."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
```

to:
```python
@click.group(invoke_without_command=True)
@click.version_option(version="0.1.0")
@click.pass_context
def main(ctx):
    """AA - Personal AI Assistant."""
    if ctx.invoked_subcommand is None:
        from aa.shell import AAShell
        shell = AAShell()
        shell.cmdloop()
```

**Step 2: Run tests**

Run: `pytest --tb=short -q`
Expected: All pass. The existing CLI test for `main` with no subcommand may need updating — check `test_cli.py`.

**Step 3: Commit**

```bash
git add src/aa/cli.py
git commit -m "feat: launch interactive shell when aa is invoked with no arguments"
```

---

### Task 9: Final test run and cleanup

**Step 1: Run full test suite**

Run: `pytest -v`
Expected: All tests pass.

**Step 2: Verify the CLI still works**

Run: `aa --help`
Expected: Shows help with all commands.

Run: `echo "quit" | aa`
Expected: Shows banner, then exits.

**Step 3: Check for any remaining references to removed code**

Run: `grep -r "notes_watcher\|import.notes\|notes_file\|watchdog" src/`
Expected: No matches (except possibly in ai/notes.py which is still used by the triage engine).

**Step 4: Commit any cleanup**

```bash
git add -A
git commit -m "chore: final cleanup after shell and file sources migration"
```
