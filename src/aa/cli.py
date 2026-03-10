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
        click.echo(ctx.get_help())


# ---------------------------------------------------------------------------
# Daemon control
# ---------------------------------------------------------------------------

@main.command()
def start():
    """Start the daemon as a background process."""
    config = _config
    config.ensure_dirs()

    pid_file = config.data_dir / "daemon.pid"
    if pid_file.exists():
        pid = int(pid_file.read_text().strip())
        try:
            os.kill(pid, 0)
            click.echo(f"Daemon already running (PID {pid})")
            return
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
    click.echo(f"Daemon started (PID {proc.pid})")


@main.command()
def stop():
    """Stop the daemon."""
    pid_file = _config.data_dir / "daemon.pid"
    if not pid_file.exists():
        click.echo("Daemon is not running.")
        return
    pid = int(pid_file.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        click.echo(f"Stopped daemon (PID {pid})")
    except OSError:
        click.echo("Daemon process not found.")
    pid_file.unlink(missing_ok=True)


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
        last = state.get("last_sync", "never")
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
        parts = [f"  {ind} {p}  {title}  [{tid}]"]
        if due:
            parts.append(f"due:{due}")
        if cat:
            parts.append(f"@{cat}")
        click.echo("  ".join(parts))


@todo.command("list")
@click.option("--all", "show_all", is_flag=True, help="Show all including done")
@click.option("--category", "-c", default=None, help="Filter by category")
@click.option("--project", default=None, help="Filter by project")
@click.option("--priority", "-p", type=int, default=None, help="Filter by exact priority (1-5)")
@click.option("--urgent", is_flag=True, help="Show only P1-P2 items")
@click.option("--keyword", "-k", default=None, help="Search title and notes")
@click.option("--due", default=None, help="Filter by due date: overdue, today, week, or YYYY-MM-DD")
def todo_list(show_all, category, project, priority, urgent, keyword, due):
    """List todos with optional filters."""
    max_priority = 2 if urgent else None
    _todo_list_impl(
        show_all=show_all, category=category, project=project,
        priority=priority, max_priority=max_priority, keyword=keyword, due=due,
    )


@todo.command("add")
@click.argument("title")
@click.option("--priority", "-p", type=int, default=3, help="Priority (1-5)")
@click.option("--due", default=None, help="Due date")
@click.option("--note", default=None, help="Note text")
@click.option("--category", "-c", default=None, help="Category")
@click.option("--project", default=None, help="Project")
def todo_add(title, priority, due, note, category, project):
    """Add a new todo."""
    args: dict = {"title": title, "priority": priority}
    if due:
        args["due_date"] = due
    if note:
        args["note"] = note
    if category:
        args["category"] = category
    if project:
        args["project"] = project

    resp = send({"command": "todo_add", "args": args})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return
    click.echo(f"Created todo {resp.get('id', '')}")


@todo.command("done")
@click.argument("todo_id")
def todo_done(todo_id):
    """Mark a todo as done."""
    resp = send({"command": "todo_done", "args": {"id": todo_id}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return
    click.echo("Todo marked as done.")


@todo.command("edit")
@click.argument("todo_id")
@click.option("--priority", "-p", type=int, default=None, help="Priority (1-5)")
@click.option("--title", default=None, help="Title")
@click.option("--note", default=None, help="Note")
@click.option("--category", "-c", default=None, help="Category")
@click.option("--project", default=None, help="Project")
@click.option("--due", default=None, help="Due date")
def todo_edit(todo_id, priority, title, note, category, project, due):
    """Edit a todo."""
    args: dict = {"id": todo_id}
    if priority is not None:
        args["priority"] = priority
    if title:
        args["title"] = title
    if note:
        args["note"] = note
    if category:
        args["category"] = category
    if project:
        args["project"] = project
    if due:
        args["due_date"] = due

    resp = send({"command": "todo_edit", "args": args})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return
    click.echo("Todo updated.")


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
@click.argument("todo_id")
def todo_rm(todo_id):
    """Remove a todo."""
    resp = send({"command": "todo_rm", "args": {"id": todo_id}})
    if "error" in resp and not resp.get("ok"):
        display_error(resp)
        return
    click.echo("Todo removed.")


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
    config = _config

    # Validate required options per type
    if source_type == "gmail":
        if not credentials_file:
            raise click.UsageError("--credentials-file is required for gmail sources")
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
            raise click.UsageError("--client-id is required for outlook sources")
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
            raise click.UsageError("--token is required for slack sources")
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
            raise click.UsageError("--url is required for mattermost sources")
        if not token:
            raise click.UsageError("--token is required for mattermost sources")
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
            raise click.UsageError("--path is required for files sources")
        source_cfg = {
            "type": "files",
            "path": path,
            "enabled": True,
        }
        msg = f"Source '{name}' (files) added."

    config.ensure_dirs()
    config.sources[name] = source_cfg
    config.save()
    click.echo(msg)


@source.command("list")
def source_list():
    """List configured sources."""
    config = _config
    sources = config.sources
    if not sources:
        click.echo("No sources configured.")
        return

    for name, src in sources.items():
        src_type = src.get("type", "unknown")
        status = "enabled" if src.get("enabled", True) else "disabled"
        parts = f"  {name:20s} {src_type:12s} {status}"
        # For OAuth sources, check if token file exists
        token_file = src.get("token_path") or src.get("token_cache_path")
        if token_file:
            from pathlib import Path as _P
            if _P(token_file).expanduser().exists():
                parts += "   token: valid"
        click.echo(parts)


@source.command("rm")
@click.argument("name")
def source_rm(name):
    """Remove a source."""
    config = _config
    if name not in config.sources:
        click.echo(click.style(f"Source '{name}' not found.", fg="red"))
        raise SystemExit(1)

    src = config.sources.pop(name)

    # Clean up credential files for OAuth sources
    token_file = src.get("token_path") or src.get("token_cache_path")
    if token_file:
        from pathlib import Path as _P
        p = _P(token_file).expanduser()
        if p.exists():
            p.unlink()

    config.save()
    click.echo(f"Source '{name}' removed.")


if __name__ == "__main__":
    main()
