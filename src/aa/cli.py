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

_config = AppConfig()


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


def _todo_list_impl(show_all: bool = False, category: str | None = None, project: str | None = None):
    """Shared implementation for listing todos."""
    args: dict = {}
    if category:
        args["category"] = category
    if project:
        args["project"] = project
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
@click.option("--project", "-p", default=None, help="Filter by project")
def todo_list(show_all, category, project):
    """List todos with optional filters."""
    _todo_list_impl(show_all=show_all, category=category, project=project)


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
# Setup
# ---------------------------------------------------------------------------

@main.command()
def setup():
    """First-run setup wizard."""
    click.echo("AA Setup Wizard")
    click.echo("=" * 40)

    api_key = click.prompt("Anthropic API key", default="", show_default=False)
    notes_file = click.prompt(
        "Path to notes file (or empty to skip)", default="", show_default=False
    )

    config = AppConfig()
    if api_key:
        config.anthropic_api_key = api_key
    if notes_file:
        config.notes_file = notes_file

    config.ensure_dirs()
    config.save()
    click.echo(f"\nConfig saved to {config.data_dir / 'config.json'}")


if __name__ == "__main__":
    main()
