"""HTTP web server for the AA personal assistant UI."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date
from html import escape as html_escape
from pathlib import Path
from typing import Any

from aiohttp import web
import aiohttp_jinja2
import jinja2

from aa.config import AppConfig
from aa.db import Database

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"


def _csrf_check(request: web.Request) -> bool:
    """Check Origin header for CSRF protection. Returns True if OK."""
    origin = request.headers.get("Origin", "")
    if not origin:
        return False
    port = request.app["config"].web_port
    allowed = {f"http://localhost:{port}", f"http://127.0.0.1:{port}", "http://localhost"}
    return origin in allowed


@web.middleware
async def csrf_middleware(request: web.Request, handler):
    """Block POST/PATCH/DELETE without valid Origin header."""
    if request.method in ("POST", "PATCH", "DELETE"):
        if not _csrf_check(request):
            return web.Response(status=403, text="Forbidden: invalid origin")
    return await handler(request)


def _todo_with_overdue(todo: dict) -> dict:
    """Add 'overdue' flag to a todo dict."""
    due = todo.get("due_date")
    if due:
        try:
            todo = dict(todo)
            todo["overdue"] = due < date.today().isoformat()
        except (ValueError, TypeError):
            pass
    return todo


# --- Route handlers ---

async def index(request: web.Request) -> web.Response:
    """Serve the main page.

    Note: The spec describes server-side session storage with LRU eviction for
    chat history. This implementation keeps history client-side (sent with each
    request) which is simpler and avoids memory management. The session cookie
    is set for future use if server-side state is needed.
    """
    db: Database = request.app["db"]
    all_todos = await db.list_todos(status=["pending", "in_progress"])
    categories = sorted({t["category"] for t in all_todos if t.get("category")})
    projects = sorted({t["project"] for t in all_todos if t.get("project")})
    response = aiohttp_jinja2.render_template(
        "base.html", request, {"categories": categories, "projects": projects}
    )
    if "session" not in request.cookies:
        response.set_cookie("session", str(uuid.uuid4()), httponly=True, samesite="Lax")
    return response


async def get_todos(request: web.Request) -> web.Response:
    """Return todo rows as HTML partial."""
    db: Database = request.app["db"]
    q = request.query.get("q", "").strip() or None
    sort = request.query.get("sort", "priority,due_date")
    dir_val = request.query.get("dir", "asc")
    # Per-column directions encoded as "-col" take precedence; only apply the
    # global dir param when none of the parts already carry a sign.
    has_signed = any(p.strip().startswith("-") for p in sort.split(","))
    if dir_val == "desc" and not has_signed:
        sort = ",".join(f"-{col.strip()}" for col in sort.split(","))

    todos = await db.list_todos(
        status=["pending", "in_progress"], keyword=q, sort=sort
    )
    todos = [_todo_with_overdue(t) for t in todos]

    return aiohttp_jinja2.render_template(
        "partials/todo_table.html", request, {"todos": todos}
    )


async def patch_todo(request: web.Request) -> web.Response:
    """Inline-edit a todo field. Returns updated row."""
    db: Database = request.app["db"]
    todo_id = request.match_info["id"]
    full_id = await db.resolve_id("todos", todo_id)
    if not full_id:
        return web.Response(status=404, text="Not found")

    data = await request.post()
    updates: dict[str, Any] = {}
    if "priority" in data:
        try:
            p = int(data["priority"])
            if not 1 <= p <= 5:
                return web.Response(status=422, text="Priority must be 1-5")
            updates["priority"] = p
        except (ValueError, TypeError):
            return web.Response(status=422, text="Invalid priority")
    if "due_date" in data:
        updates["due_date"] = data["due_date"] or None
    if "category" in data:
        updates["category"] = data["category"] or None
    if "project" in data:
        updates["project"] = data["project"] or None
    if "title" in data:
        updates["title"] = data["title"]
    if "details" in data:
        updates["details"] = data["details"] or None
    if "reviewed" in data:
        updates["reviewed"] = int(data["reviewed"])
    if "status" in data and data["status"] in ("pending", "in_progress", "done"):
        updates["status"] = data["status"]

    if updates:
        await db.update_todo(full_id, **updates)

    todo = await db.get_todo(full_id)
    todo = _todo_with_overdue(todo)

    response = aiohttp_jinja2.render_template(
        "partials/todo_row.html", request, {"todo": todo}
    )
    response.headers["HX-Trigger"] = "refreshTable"
    return response


async def get_todo_detail(request: web.Request) -> web.Response:
    """Return expanded detail row."""
    db: Database = request.app["db"]
    todo_id = request.match_info["id"]
    full_id = await db.resolve_id("todos", todo_id)
    if not full_id:
        return web.Response(status=404, text="Not found")

    todo = await db.get_todo(full_id)
    links = await db.get_todo_links(full_id)
    linked_items = []
    for link in links:
        item = await db.get_item(link["item_id"])
        if item:
            linked_items.append(item)

    return aiohttp_jinja2.render_template(
        "partials/todo_detail.html", request,
        {"todo": todo, "linked_items": linked_items}
    )


async def todo_done(request: web.Request) -> web.Response:
    """Mark a todo as done."""
    db: Database = request.app["db"]
    todo_id = request.match_info["id"]
    full_id = await db.resolve_id("todos", todo_id)
    if not full_id:
        return web.Response(status=404, text="Not found")
    await db.update_todo(full_id, status="done")
    response = web.Response(status=200, text="")
    response.headers["HX-Trigger"] = "refreshTable"
    return response


async def todo_delete(request: web.Request) -> web.Response:
    """Soft-delete a todo."""
    db: Database = request.app["db"]
    todo_id = request.match_info["id"]
    full_id = await db.resolve_id("todos", todo_id)
    if not full_id:
        return web.Response(status=404, text="Not found")
    await db.delete_todo(full_id)
    response = web.Response(status=200, text="")
    response.headers["HX-Trigger"] = "refreshTable"
    return response


async def todo_new(request: web.Request) -> web.Response:
    """Create a new todo."""
    db: Database = request.app["db"]
    data = await request.post()
    title = data.get("title", "").strip()
    if not title:
        return web.Response(status=422, text="Title required")

    try:
        priority = int(data.get("priority", 3))
        if not 1 <= priority <= 5:
            priority = 3
    except (ValueError, TypeError):
        priority = 3

    await db.insert_todo(
        title=title,
        priority=priority,
        due_date=data.get("due_date") or None,
        category=data.get("category") or None,
        project=data.get("project") or None,
    )
    response = web.Response(status=200, text="")
    response.headers["HX-Trigger"] = "refreshTable"
    return response


async def todo_bulk(request: web.Request) -> web.Response:
    """Handle bulk actions on multiple todos."""
    db: Database = request.app["db"]
    data = await request.post()
    ids_str = data.get("ids", "")
    action = data.get("action", "")
    value = data.get("value", "")

    ids = [i.strip() for i in ids_str.split(",") if i.strip()]
    if not ids or not action:
        return web.Response(status=422, text="Missing ids or action")

    for raw_id in ids:
        full_id = await db.resolve_id("todos", raw_id)
        if not full_id:
            continue
        if action == "done":
            await db.update_todo(full_id, status="done")
        elif action == "delete":
            await db.delete_todo(full_id)
        elif action == "priority" and value:
            await db.update_todo(full_id, priority=int(value))
        elif action == "due" and value:
            await db.update_todo(full_id, due_date=value)
        elif action == "category" and value:
            await db.update_todo(full_id, category=value)
        elif action == "project" and value:
            await db.update_todo(full_id, project=value)
        elif action == "review":
            await db.update_todo(full_id, reviewed=1)
        elif action == "in_progress":
            await db.update_todo(full_id, status="in_progress")

    response = web.Response(status=200, text="")
    response.headers["HX-Trigger"] = "refreshTable"
    return response


async def get_edit_field(request: web.Request) -> web.Response:
    """Return an inline edit widget for a field."""
    db: Database = request.app["db"]
    todo_id = request.match_info["id"]
    field = request.match_info["field"]
    full_id = await db.resolve_id("todos", todo_id)
    if not full_id:
        return web.Response(status=404, text="Not found")

    todo = await db.get_todo(full_id)
    current = todo.get(field, "")

    if field == "priority":
        options = "".join(
            f'<option value="{i}" {"selected" if todo.get("priority") == i else ""}>P{i}</option>'
            for i in range(1, 6)
        )
        html = (
            f'<select class="inline-edit" '
            f'hx-patch="/todos/{full_id}" hx-target="closest tr" hx-swap="outerHTML" '
            f'hx-trigger="change" name="priority">'
            f'{options}</select>'
        )
    elif field == "due_date":
        esc_val = html_escape(str(current or ""), quote=True)
        html = (
            f'<input type="date" class="inline-edit" value="{esc_val}" '
            f'hx-patch="/todos/{full_id}" hx-target="closest tr" hx-swap="outerHTML" '
            f'hx-trigger="change" name="due_date">'
        )
    elif field in ("category", "project"):
        # Get existing values for datalist
        all_todos = await db.list_todos(status="pending")
        values = sorted(set(t.get(field) or "" for t in all_todos if t.get(field)))
        datalist_opts = "".join(f"<option>{html_escape(v)}</option>" for v in values)
        datalist = f'<datalist id="dl-{field}">{datalist_opts}</datalist>'
        esc_val = html_escape(str(current or ""), quote=True)
        html = (
            f'<input type="text" class="inline-edit" value="{esc_val}" '
            f'list="dl-{field}" '
            f'hx-patch="/todos/{full_id}" hx-target="closest tr" hx-swap="outerHTML" '
            f'hx-trigger="blur, keydown[key==\'Enter\']" name="{field}">'
            f'{datalist}'
        )
    else:
        return web.Response(status=400, text="Unknown field")

    return web.Response(text=html, content_type="text/html")


async def chat(request: web.Request) -> web.StreamResponse:
    """Handle chat messages with SSE streaming."""
    config: AppConfig = request.app["config"]
    db: Database = request.app["db"]

    if not config.anthropic_api_key:
        resp = web.StreamResponse()
        resp.content_type = "text/event-stream"
        await resp.prepare(request)
        await resp.write(b"event: error\ndata: No API key configured\n\n")
        return resp

    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    message = data.get("message", "")
    history = data.get("history", [])

    # Build context — include both pending and in_progress todos
    pending = await db.list_todos(status="pending")
    in_progress = await db.list_todos(status="in_progress")
    todos = in_progress + pending
    inbox = await db.list_items(limit=20)
    calendar = await db.list_items(source="calendar")
    context = {"todos": todos, "inbox": inbox, "calendar": calendar}

    from aa.ai.ask import AskEngine, parse_actions

    engine = AskEngine(api_key=config.anthropic_api_key, model=config.anthropic_model)

    resp = web.StreamResponse()
    resp.content_type = "text/event-stream"
    resp.headers["Cache-Control"] = "no-cache"
    await resp.prepare(request)

    full_text = ""
    try:
        async for chunk in engine.ask_stream(message, context, history=history):
            full_text += chunk
            # SSE requires each line of multi-line data to be prefixed with "data: "
            sse_lines = "\n".join(f"data: {line}" for line in chunk.split("\n"))
            await resp.write(f"event: text\n{sse_lines}\n\n".encode())
    except Exception as e:
        err_msg = str(e).replace("\n", " ")
        await resp.write(f"event: error\ndata: {err_msg}\n\n".encode())
        return resp

    # Parse actions from complete text
    actions, _ = parse_actions(full_text)
    for action in actions:
        await resp.write(f"event: action\ndata: {json.dumps(action)}\n\n".encode())

    await resp.write(b"event: done\ndata: {}\n\n")
    return resp


async def chat_action(request: web.Request) -> web.Response:
    """Execute a chat action button."""
    db: Database = request.app["db"]
    try:
        action = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    action_type = action.get("type", "")
    try:
        if action_type == "create_todo":
            todo_id = await db.insert_todo(
                title=action["title"],
                priority=action.get("priority", 3),
                due_date=action.get("due"),
                category=action.get("category"),
                project=action.get("project"),
            )
            msg = f"Created todo: {action['title']}"
        elif action_type == "mark_done":
            full_id = await db.resolve_id("todos", action["todo_id"])
            if not full_id:
                return web.json_response({"ok": False, "error": "Todo not found"})
            await db.update_todo(full_id, status="done")
            msg = f"Marked done: {action['todo_id']}"
        elif action_type == "set_priority":
            full_id = await db.resolve_id("todos", action["todo_id"])
            if not full_id:
                return web.json_response({"ok": False, "error": "Todo not found"})
            await db.update_todo(full_id, priority=int(action["priority"]))
            msg = f"Set priority P{action['priority']}: {action['todo_id']}"
        elif action_type == "set_due":
            full_id = await db.resolve_id("todos", action["todo_id"])
            if not full_id:
                return web.json_response({"ok": False, "error": "Todo not found"})
            await db.update_todo(full_id, due_date=action["due"])
            msg = f"Set due {action['due']}: {action['todo_id']}"
        elif action_type == "delete_todo":
            full_id = await db.resolve_id("todos", action["todo_id"])
            if not full_id:
                return web.json_response({"ok": False, "error": "Todo not found"})
            await db.delete_todo(full_id)
            msg = f"Deleted: {action['todo_id']}"
        else:
            return web.json_response({"ok": False, "error": f"Unknown action: {action_type}"})

        return web.json_response({"ok": True, "message": msg})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})


def create_app(config: AppConfig, db: Database) -> web.Application:
    """Create and configure the aiohttp web application."""
    app = web.Application(middlewares=[csrf_middleware])
    app["config"] = config  # type: ignore[assignment]
    app["db"] = db  # type: ignore[assignment]

    # Setup Jinja2 with autoescaping enabled
    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=jinja2.select_autoescape(default_for_string=True, default=True),
    )

    # Routes
    app.router.add_get("/", index)
    app.router.add_get("/todos", get_todos)
    app.router.add_post("/todos/new", todo_new)
    app.router.add_post("/todos/bulk", todo_bulk)
    app.router.add_patch("/todos/{id}", patch_todo)
    app.router.add_get("/todos/{id}/detail", get_todo_detail)
    app.router.add_get("/todos/{id}/edit/{field}", get_edit_field)
    app.router.add_post("/todos/{id}/done", todo_done)
    app.router.add_post("/todos/{id}/delete", todo_delete)
    app.router.add_post("/chat", chat)
    app.router.add_post("/chat/action", chat_action)

    # Static files
    app.router.add_static("/static", STATIC_DIR)

    return app
