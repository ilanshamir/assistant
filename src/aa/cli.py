"""Full CLI for the aa personal assistant.

Communicates with the daemon via Unix socket using JSON requests/responses.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import click

from aa.config import AppConfig

# ---------------------------------------------------------------------------
# Socket communication helpers
# ---------------------------------------------------------------------------

def _load_config() -> AppConfig:
    """Load config from file if it exists, otherwise use defaults."""
    config = AppConfig()
    config_path = config.data_dir / "config.json"
    if config_path.exists():
        config = AppConfig.from_file(config_path)
    # Also check env for API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        config.anthropic_api_key = api_key
    return config

_config = _load_config()


async def send_command(socket_path: str | Path, request: dict) -> dict:
    """Send a JSON request to the daemon socket and return the response dict."""
    try:
        reader, writer = await asyncio.open_unix_connection(str(socket_path))
        writer.write(json.dumps(request).encode("utf-8"))
        await writer.drain()
        writer.write_eof()
        data = await reader.read(1024 * 1024)
        writer.close()
        await writer.wait_closed()
        return json.loads(data.decode("utf-8"))
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return {"error": "Daemon is not running. Start it with: aa start"}


def send(request: dict) -> dict:
    """Synchronous wrapper around send_command."""
    return asyncio.run(send_command(_config.socket_path, request))


# ---------------------------------------------------------------------------
# Output formatting helpers
# ---------------------------------------------------------------------------

PRIORITY_COLORS = {1: "red", 2: "yellow", 3: "white", 4: "blue", 5: "bright_black"}


def priority_label(p: int | None) -> str:
    p = p or 3
    color = PRIORITY_COLORS.get(p, "white")
    return click.style(f"P{p}", fg=color)


def status_indicator(status: str | None) -> str:
    if status == "done":
        return click.style("\u2713", fg="green")
    return click.style("\u25cb", fg="white")


def truncate(text: str | None, length: int) -> str:
    if not text:
        return ""
    if len(text) <= length:
        return text
    return text[: length - 1] + "\u2026"


def display_error(resp: dict) -> None:
    """Display an error from a response dict."""
    msg = resp.get("error", "Unknown error")
    click.echo(click.style(f"Error: {msg}", fg="red"))


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True)
@click.version_option(version="0.1.0")
@click.pass_context
def main(ctx):
    """AA - Personal AI Assistant."""
    if ctx.invoked_subcommand is None:
        from aa.shell import AAShell
        shell = AAShell()
        shell.cmdloop()


# ---------------------------------------------------------------------------
# Daemon control
# ---------------------------------------------------------------------------

def start_daemon() -> str:
    """Start the daemon as a background process. Returns a status message."""
    config = _config
    config.ensure_dirs()

    pid_file = config.data_dir / "daemon.pid"
    if pid_file.exists():
        pid = int(pid_file.read_text().strip())
        try:
            os.kill(pid, 0)
            return f"Daemon already running (PID {pid})"
        except OSError:
            pid_file.unlink()

    log_dir = config.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "daemon.log"

    proc = subprocess.Popen(
        [sys.executable, "-m", "aa.daemon"],
        stdout=open(log_file, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    pid_file.write_text(str(proc.pid))
    return f"Daemon started (PID {proc.pid})"


def stop_daemon() -> str:
    """Stop the daemon. Returns a status message."""
    pid_file = _config.data_dir / "daemon.pid"
    if not pid_file.exists():
        return "Daemon is not running."
    pid = int(pid_file.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        msg = f"Stopped daemon (PID {pid})"
    except OSError:
        msg = "Daemon process not found."
    pid_file.unlink(missing_ok=True)
    return msg


@main.command()
def start():
    """Start the daemon as a background process."""
    click.echo(start_daemon())


@main.command()
def stop():
    """Stop the daemon."""
    click.echo(stop_daemon())


@main.command()
def status():
    """Show daemon health and per-source sync state."""
    resp = send({"command": "status", "args": {}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return

    daemon_status = resp.get("status", "unknown")
    color = "green" if daemon_status == "running" else "red"
    click.echo(f"Daemon: {click.style(daemon_status, fg=color)}")

    sources = resp.get("sources", {})
    if not sources:
        click.echo("  No sources configured.")
        return

    for name, state in sources.items():
        src_status = state.get("status", "unknown")
        src_color = "green" if src_status == "ok" else ("red" if src_status == "error" else "yellow")
        last = state.get("updated_at") or state.get("last_sync") or "never"
        click.echo(f"  {truncate(name, 15):15s}  {click.style(src_status, fg=src_color):10s}  last: {last}")


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------

@main.command()
@click.option("--source", "-s", default=None, help="Filter by source")
def inbox(source):
    """Show unread inbox items sorted by priority."""
    args = {}
    if source:
        args["source"] = source
    resp = send({"command": "inbox", "args": args})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return

    items = resp.get("items", [])
    if not items:
        click.echo("Inbox is empty.")
        return

    for item in items:
        p = priority_label(item.get("priority"))
        src = truncate(item.get("source", ""), 15)
        frm = truncate(item.get("from_name", ""), 20)
        subj = item.get("subject", "(no subject)")
        iid = item.get("id", "")[:8]
        click.echo(f"  {p}  {src:15s}  {frm:20s}  {subj}  [{iid}]")


# ---------------------------------------------------------------------------
# Show item
# ---------------------------------------------------------------------------

@main.command()
@click.argument("item_id")
def show(item_id):
    """Show full detail for an item."""
    resp = send({"command": "show", "args": {"id": item_id}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return

    item = resp.get("item", {})
    click.echo(f"ID:       {item.get('id', '')}")
    click.echo(f"Source:   {item.get('source', '')}")
    click.echo(f"From:     {item.get('from_name', '')}")
    click.echo(f"Subject:  {item.get('subject', '')}")
    click.echo(f"Priority: {priority_label(item.get('priority'))}")
    click.echo(f"Action:   {item.get('action', '')}")
    click.echo(f"Received: {item.get('received_at', '')}")
    linked_todos = resp.get("linked_todos", [])
    if linked_todos:
        click.echo(f"\nLinked todos:")
        for t in linked_todos:
            p = priority_label(t.get("priority"))
            tid = t.get("id", "")[:8]
            click.echo(f"  {p}  {t.get('title', '')}  [{tid}]")
    click.echo(f"\n{item.get('body', '')}")


# ---------------------------------------------------------------------------
# Reply / Reprioritize / Dismiss
# ---------------------------------------------------------------------------

@main.command()
@click.argument("item_id")
def reply(item_id):
    """Request a draft response for an item."""
    resp = send({"command": "reply", "args": {"id": item_id}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return
    draft = resp.get("draft", "")
    click.echo(draft)


@main.command()
@click.argument("item_id")
@click.argument("priority", type=int)
def reprioritize(item_id, priority):
    """Change an item's priority."""
    resp = send({"command": "reprioritize", "args": {"id": item_id, "priority": priority}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return
    click.echo("Priority updated.")


@main.command()
@click.argument("item_id")
def dismiss(item_id):
    """Dismiss an item."""
    resp = send({"command": "dismiss", "args": {"id": item_id}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return
    click.echo("Item dismissed.")


# ---------------------------------------------------------------------------
# Todo group
# ---------------------------------------------------------------------------

@main.group(invoke_without_command=True)
@click.pass_context
def todo(ctx):
    """Manage todos."""
    if ctx.invoked_subcommand is None:
        # Default: list all todos
        _todo_list_impl()


main.add_command(todo)


def _todo_list_impl(
    show_all: bool = False,
    show_details: bool = False,
    category: str | None = None,
    project: str | None = None,
    priority: int | None = None,
    max_priority: int | None = None,
    keyword: str | None = None,
    due: str | None = None,
):
    """Shared implementation for listing todos."""
    args: dict = {}
    if category:
        args["category"] = category
    if project:
        args["project"] = project
    if priority is not None:
        args["priority"] = priority
    if max_priority is not None:
        args["max_priority"] = max_priority
    if keyword:
        args["keyword"] = keyword
    if due:
        # Handle special keywords
        from datetime import date, timedelta
        today = date.today()
        if due == "overdue":
            args["due_before"] = (today - timedelta(days=1)).isoformat()
        elif due == "today":
            args["due_before"] = today.isoformat()
        elif due == "week":
            args["due_before"] = (today + timedelta(days=7)).isoformat()
        else:
            args["due_before"] = due  # assume YYYY-MM-DD
    if show_all:
        args["all"] = True

    resp = send({"command": "todo", "args": args})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return

    todos = resp.get("todos", [])
    if not todos:
        click.echo("No todos.")
        return

    for t in todos:
        ind = status_indicator(t.get("status"))
        p = priority_label(t.get("priority"))
        title = t.get("title", "")
        tid = t.get("id", "")[:8]
        due = t.get("due_date") or ""
        cat = t.get("category") or ""
        has_details = bool(t.get("details"))
        parts = [f"  {ind} {p}  {title}  [{tid}]"]
        if due:
            parts.append(f"due:{due}")
        if cat:
            parts.append(f"@{cat}")
        if has_details:
            parts.append("[+]")
        click.echo("  ".join(parts))
        if show_details and has_details:
            for line in t["details"].splitlines():
                click.echo(f"       {line}")


@todo.command("list")
@click.option("--all", "show_all", is_flag=True, help="Show all including done")
@click.option("--details", is_flag=True, help="Show details inline")
@click.option("--category", "-c", default=None, help="Filter by category")
@click.option("--project", "-j", default=None, help="Filter by project")
@click.option("--priority", "-p", type=int, default=None, help="Filter by exact priority (1-5)")
@click.option("--urgent", "-u", is_flag=True, help="Show only P1-P2 items")
@click.option("--keyword", "-k", default=None, help="Search title and notes")
@click.option("--due", "-d", default=None, help="Filter by due date: overdue, today, week, or YYYY-MM-DD")
def todo_list(show_all, details, category, project, priority, urgent, keyword, due):
    """List todos with optional filters."""
    max_priority = 2 if urgent else None
    _todo_list_impl(
        show_all=show_all, show_details=details, category=category, project=project,
        priority=priority, max_priority=max_priority, keyword=keyword, due=due,
    )


@todo.command("add")
@click.argument("title")
@click.option("--priority", "-p", type=int, default=3, help="Priority (1-5)")
@click.option("--due", "-d", default=None, help="Due date")
@click.option("--note", "-n", default=None, help="Note text")
@click.option("--details", default=None, help="Detailed description")
@click.option("--category", "-c", default=None, help="Category")
@click.option("--project", "-j", default=None, help="Project")
def todo_add(title, priority, due, note, details, category, project):
    """Add a new todo."""
    args: dict = {"title": title, "priority": priority}
    if due:
        args["due_date"] = due
    if note:
        args["note"] = note
    if details:
        args["details"] = details
    if category:
        args["category"] = category
    if project:
        args["project"] = project

    resp = send({"command": "todo_add", "args": args})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return
    click.echo(f"Created todo {resp.get('id', '')}")


@todo.command("show")
@click.argument("todo_id")
def todo_show(todo_id):
    """Show full detail for a todo."""
    resp = send({"command": "todo_show", "args": {"id": todo_id}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return
    t = resp.get("todo", {})
    click.echo(f"ID:       {t.get('id', '')}")
    click.echo(f"Title:    {t.get('title', '')}")
    click.echo(f"Priority: {priority_label(t.get('priority'))}")
    click.echo(f"Status:   {t.get('status', '')}")
    cat = t.get("category") or ""
    proj = t.get("project") or ""
    due = t.get("due_date") or ""
    if cat:
        click.echo(f"Category: {cat}")
    if proj:
        click.echo(f"Project:  {proj}")
    if due:
        click.echo(f"Due:      {due}")
    notes = t.get("notes") or ""
    if notes:
        click.echo(f"Notes:    {notes}")
    details = t.get("details") or ""
    if details:
        click.echo(f"\nDetails:\n{details}")
    linked_items = resp.get("linked_items", [])
    if linked_items:
        click.echo(f"\nLinked items:")
        for item in linked_items:
            src = truncate(item.get("source", ""), 15)
            subj = item.get("subject", "(no subject)")
            iid = item.get("id", "")[:8]
            click.echo(f"  {src:15s}  {subj}  [{iid}]")


@todo.command("done")
@click.argument("todo_ids", nargs=-1, required=True)
def todo_done(todo_ids):
    """Mark one or more todos as done."""
    for todo_id in todo_ids:
        resp = send({"command": "todo_done", "args": {"id": todo_id}})
        if "error" in resp and not resp.get("ok"):
            display_error(resp)
        else:
            click.echo(f"Done: {todo_id}")


@todo.command("edit")
@click.argument("todo_ids", nargs=-1, required=True)
@click.option("--priority", "-p", type=int, default=None, help="Priority (1-5)")
@click.option("--title", "-t", default=None, help="Title")
@click.option("--note", "-n", default=None, help="Note")
@click.option("--details", default=None, help="Detailed description")
@click.option("--category", "-c", default=None, help="Category")
@click.option("--project", "-j", default=None, help="Project")
@click.option("--due", "-d", default=None, help="Due date")
def todo_edit(todo_ids, priority, title, note, details, category, project, due):
    """Edit one or more todos."""
    edit_args: dict = {}
    if priority is not None:
        edit_args["priority"] = priority
    if title:
        edit_args["title"] = title
    if note:
        edit_args["note"] = note
    if details:
        edit_args["details"] = details
    if category:
        edit_args["category"] = category
    if project:
        edit_args["project"] = project
    if due:
        edit_args["due_date"] = due

    for todo_id in todo_ids:
        resp = send({"command": "todo_edit", "args": {"id": todo_id, **edit_args}})
        if "error" in resp and not resp.get("ok"):
            display_error(resp)
        else:
            click.echo(f"Updated {todo_id}")


@todo.command("link")
@click.argument("todo_id")
@click.argument("item_id")
def todo_link(todo_id, item_id):
    """Link a todo to an inbox item."""
    resp = send({"command": "todo_link", "args": {"todo_id": todo_id, "item_id": item_id}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return
    click.echo("Linked.")


@todo.command("rm")
@click.argument("todo_ids", nargs=-1, required=True)
def todo_rm(todo_ids):
    """Remove one or more todos."""
    for todo_id in todo_ids:
        resp = send({"command": "todo_rm", "args": {"id": todo_id}})
        if "error" in resp and not resp.get("ok"):
            display_error(resp)
        else:
            click.echo(f"Removed {todo_id}")


def _default_export_path() -> str:
    from datetime import datetime
    export_dir = _config.data_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(export_dir / f"todos_{ts}.csv")


def export_todos_csv(todos: list[dict], output: str) -> str:
    """Write todos to a CSV file. Returns the output path."""
    import csv

    fields = ["id", "title", "priority", "status", "category", "project",
              "due_date", "notes", "details", "created_at", "completed_at"]
    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(todos)
    return output


@todo.command("export")
@click.option("--output", "-o", default=None, help="Output file path (default: todos_<datetime>.csv)")
def todo_export(output):
    """Export all todos (including done and removed) to CSV."""
    resp = send({"command": "todo_export", "args": {}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return

    todos = resp.get("todos", [])
    if not todos:
        click.echo("No todos to export.")
        return

    output = output or _default_export_path()
    export_todos_csv(todos, output)
    click.echo(f"Exported {len(todos)} todos to {output}")


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

@main.command()
@click.argument("when", default="today")
def calendar(when):
    """Show calendar events (today/tomorrow/week)."""
    resp = send({"command": "calendar", "args": {"when": when}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return

    events = resp.get("events", [])
    if not events:
        click.echo("No events.")
        return

    for ev in events:
        subj = ev.get("subject", "(no subject)")
        time = ev.get("received_at", "")
        click.echo(f"  {time}  {subj}")


# ---------------------------------------------------------------------------
# Ask
# ---------------------------------------------------------------------------

@main.command()
@click.argument("question")
def ask(question):
    """Ask the AI assistant a question."""
    resp = send({"command": "ask", "args": {"question": question}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return
    click.echo(resp.get("answer", ""))


# ---------------------------------------------------------------------------
# Rules group
# ---------------------------------------------------------------------------

@main.group()
def rule():
    """Manage triage rules."""
    pass


main.add_command(rule)


@rule.command("add")
@click.argument("description")
def rule_add(description):
    """Add a triage rule."""
    resp = send({"command": "rule_add", "args": {"rule": description}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return
    click.echo(f"Rule added: {resp.get('id', '')}")


@rule.command("list")
def rule_list():
    """List all triage rules."""
    resp = send({"command": "rule_list", "args": {}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return

    rules = resp.get("rules", [])
    if not rules:
        click.echo("No rules.")
        return

    for r in rules:
        rid = r.get("id", "")
        text = r.get("rule", "")
        click.echo(f"  [{rid}]  {text}")


@rule.command("rm")
@click.argument("rule_id")
def rule_rm(rule_id):
    """Remove a triage rule."""
    resp = send({"command": "rule_rm", "args": {"id": rule_id}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return
    click.echo("Rule removed.")


# ---------------------------------------------------------------------------
# Source management
# ---------------------------------------------------------------------------

VALID_SOURCE_TYPES = ("gmail", "outlook", "slack", "mattermost", "files")


def list_sources() -> list[str]:
    """List configured sources. Returns lines of output."""
    config = _config
    sources = config.sources
    if not sources:
        return ["No sources configured."]

    # Try to get sync state from the daemon
    sync_states: dict = {}
    try:
        resp = send({"command": "status", "args": {}})
        if resp.get("ok"):
            sync_states = resp.get("sources", {})
    except Exception:
        pass

    lines = []
    for name, src in sources.items():
        src_type = src.get("type", "unknown")
        status = "enabled" if src.get("enabled", True) else "disabled"
        parts = f"  {name:20s} {src_type:12s} {status}"
        token_file = src.get("token_path") or src.get("token_cache_path")
        if token_file:
            from pathlib import Path as _P
            if _P(token_file).expanduser().exists():
                parts += "   token: valid"
        state = sync_states.get(name, {})
        last_sync = state.get("updated_at") or state.get("last_sync")
        if last_sync:
            parts += f"   last sync: {last_sync}"
        else:
            parts += "   last sync: never"
        lines.append(parts)
    return lines


def add_source(
    name: str,
    source_type: str,
    *,
    credentials_file: str | None = None,
    client_id: str | None = None,
    tenant_id: str | None = None,
    token: str | None = None,
    url: str | None = None,
    channels: str | None = None,
    path: str | None = None,
) -> str:
    """Add or configure a source. Returns a status message or raises ValueError."""
    config = _config

    if source_type not in VALID_SOURCE_TYPES:
        raise ValueError(f"Invalid source type: {source_type}. Must be one of: {', '.join(VALID_SOURCE_TYPES)}")

    if source_type == "gmail":
        if not credentials_file:
            raise ValueError("--credentials-file is required for gmail sources")
        token_path = str(config.credentials_dir / f"{name}.token.json")
        source_cfg = {
            "type": "gmail",
            "credentials_file": credentials_file,
            "token_path": token_path,
            "enabled": True,
        }
        msg = f"Source '{name}' (gmail) added. OAuth will run when the daemon starts."

    elif source_type == "outlook":
        if not client_id:
            raise ValueError("--client-id is required for outlook sources")
        token_cache_path = str(config.credentials_dir / f"{name}.token.json")
        source_cfg = {
            "type": "outlook",
            "client_id": client_id,
            "tenant_id": tenant_id or "common",
            "token_cache_path": token_cache_path,
            "enabled": True,
        }
        msg = f"Source '{name}' (outlook) added. OAuth will run when the daemon starts."

    elif source_type == "slack":
        if not token:
            raise ValueError("--token is required for slack sources")
        watched = [ch.strip() for ch in channels.split(",")] if channels else []
        source_cfg = {
            "type": "slack",
            "token": token,
            "watched_channels": watched,
            "enabled": True,
        }
        msg = f"Source '{name}' (slack) added."

    elif source_type == "mattermost":
        if not url:
            raise ValueError("--url is required for mattermost sources")
        if not token:
            raise ValueError("--token is required for mattermost sources")
        watched = [ch.strip() for ch in channels.split(",")] if channels else []
        source_cfg = {
            "type": "mattermost",
            "url": url,
            "token": token,
            "watched_channels": watched,
            "enabled": True,
        }
        msg = f"Source '{name}' (mattermost) added."

    elif source_type == "files":
        if not path:
            raise ValueError("--path is required for files sources")
        source_cfg = {
            "type": "files",
            "path": path,
            "enabled": True,
        }
        msg = f"Source '{name}' (files) added."

    config.ensure_dirs()
    config.sources[name] = source_cfg
    config.save()
    return msg


def remove_source(name: str) -> str:
    """Remove a source. Returns a status message or raises ValueError."""
    config = _config
    if name not in config.sources:
        raise ValueError(f"Source '{name}' not found.")

    src = config.sources.pop(name)

    token_file = src.get("token_path") or src.get("token_cache_path")
    if token_file:
        from pathlib import Path as _P
        p = _P(token_file).expanduser()
        if p.exists():
            p.unlink()

    config.save()
    return f"Source '{name}' removed."


@main.group(invoke_without_command=True)
@click.pass_context
def source(ctx):
    """Manage source credentials."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


main.add_command(source)


@source.command("add")
@click.argument("name")
@click.option("--type", "source_type", required=True, type=click.Choice(VALID_SOURCE_TYPES),
              help="Source type")
@click.option("--credentials-file", default=None, help="Path to OAuth client secret JSON (gmail)")
@click.option("--client-id", default=None, help="OAuth client ID (outlook)")
@click.option("--tenant-id", default=None, help="Azure AD tenant ID (outlook, default: common)")
@click.option("--token", default=None, help="API token (slack, mattermost)")
@click.option("--url", default=None, help="Server URL (mattermost)")
@click.option("--channels", default=None, help="Comma-separated channel IDs to watch")
@click.option("--path", default=None, help="File or directory path (files)")
def source_add(name, source_type, credentials_file, client_id, tenant_id, token, url, channels, path):
    """Add or configure a source."""
    try:
        msg = add_source(
            name, source_type,
            credentials_file=credentials_file, client_id=client_id,
            tenant_id=tenant_id, token=token, url=url,
            channels=channels, path=path,
        )
        click.echo(msg)
    except ValueError as e:
        raise click.UsageError(str(e))


@source.command("list")
def source_list():
    """List configured sources."""
    for line in list_sources():
        click.echo(line)


@source.command("rm")
@click.argument("name")
def source_rm(name):
    """Remove a source."""
    try:
        click.echo(remove_source(name))
    except ValueError as e:
        click.echo(click.style(str(e), fg="red"))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
