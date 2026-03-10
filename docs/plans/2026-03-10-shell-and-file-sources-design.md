# Shell Mode & File Sources Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an interactive shell, make files/folders a proper source type, remove setup and import-notes commands.

**Architecture:** Replace special-case notes handling with a generic `FilesConnector` that polls files/folders and extracts todos via AI. Add a `cmd.Cmd`-based interactive shell entered when `aa` is invoked with no arguments. All existing one-shot CLI commands remain unchanged.

**Tech Stack:** Python `cmd` stdlib module for shell, existing polling infrastructure for file sources.

---

## 1. Remove `setup` and `import-notes`

- Delete `aa setup` command from `cli.py`
- Delete `aa import-notes` command and `_add_todos_to_db` helper from `cli.py`
- Remove `notes_file` field from `AppConfig` dataclass
- Remove `notes_watcher.py` module
- Remove watchdog-related code from `daemon.py` (`_import_notes_file`, `_on_notes_changed`, `_extract_and_store_todos`, notes watcher init)
- Remove `watchdog` from dependencies in `pyproject.toml`

## 2. Files as a Source Type

### Config format

Single file:
```json
{
  "type": "files",
  "path": "/mnt/c/Users/ilans/Documents/Meetings.txt",
  "enabled": true
}
```

Directory (recursive):
```json
{
  "type": "files",
  "path": "/mnt/c/Users/ilans/Documents/Notes",
  "enabled": true
}
```

Auto-detect: if path is a file, watch that file. If directory, watch recursively.

### CLI

`aa source add mynotes --type files --path /path/to/file-or-folder`

Add `files` to `VALID_SOURCE_TYPES`. Add `--path` option to `source add`.

### FilesConnector

New connector at `src/aa/connectors/files.py`:
- Implements `BaseConnector` interface
- `source_name` set from config
- `fetch_new_items(cursor)` method:
  - If path is a file: read it, hash content
  - If path is a directory: walk recursively, read all text files, hash each
  - Cursor is a JSON dict of `{filepath: content_hash}`
  - For changed/new files: use `NotesExtractor` to extract todos
  - Return items with `source=source_name`, `type="notes"`
- Needs API key passed through for NotesExtractor

### Config changes

- Add `poll_interval_files: int = 120` to `AppConfig`
- Add `"files": "poll_interval_files"` to `POLL_INTERVALS` in `daemon.py`

### Daemon changes

- Add `files` case to `_create_connector()` in `daemon.py`
- Remove all notes_watcher code and notes file import code
- FilesConnector creates items in DB; triage engine handles them like any other items

## 3. Interactive Shell

### Entry point

When `aa` is invoked with no arguments, instead of showing help, enter the interactive shell.

### Implementation

`src/aa/shell.py` — `cmd.Cmd` subclass:
- Prompt: `aa> `
- Welcome banner: `AA Assistant | daemon: running | 3 unread | 5 todos`
  - Fetches status, inbox count, todo count on startup
- Commands mirror CLI: `inbox`, `show`, `todo`, `reply`, `reprioritize`, `dismiss`, `calendar`, `ask`, `rule`, `source`, `status`, `start`, `stop`
- `todo` with no args lists todos; `todo list`, `todo add`, `todo done`, `todo edit`, `todo rm`, `todo link` as subcommands
- `rule` with no args lists rules; `rule add`, `rule rm` as subcommands
- `source` with no args lists sources; `source add`, `source list`, `source rm` as subcommands
- Tab completion on command names and subcommands
- `help` lists available commands
- `quit` / `exit` / Ctrl-D / EOF to leave
- Uses the same `send()` function from `cli.py` for daemon communication
- Parses arguments with `shlex.split()` for proper quoting

### CLI integration

In `cli.py`, change `main()` group's `invoke_without_command` behavior:
- If no subcommand, launch the shell instead of showing help
- All existing `aa <command>` one-shot usage continues to work

## 4. Testing

- `test_shell.py` — test shell command parsing, help, quit
- `test_connector_files.py` — test FilesConnector with tmp files/dirs
- Update `test_cli.py` / `test_cli_commands.py` to remove setup/import-notes tests
- Update `test_config.py` if notes_file removal affects it
