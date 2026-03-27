# Web UI for AA Personal Assistant

## Overview

A task-management-focused web interface for the AA personal assistant. The UI is a dense, hybrid table (compact rows with expandable details) served via htmx + Jinja2 templates from within the existing daemon process. A resizable bottom chat panel provides multi-turn `/ask` functionality with actionable response buttons.

Desktop-only, localhost-only. Mobile/responsive is out of scope.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary focus | Task management | Todos are the core workflow; inbox/calendar/ask are supporting |
| Layout | Hybrid dense table | Compact for scanning, expandable for details |
| Frontend tech | htmx + Jinja2 | No build step, no JS framework, fits Python backend |
| Chat panel | Bottom resizable panel | Always accessible without losing todo context |
| Bulk actions | Checkbox + toolbar | Select rows, toolbar appears with bulk operations |
| Filtering | Column sorts + search box | Minimal — keeps UI clean |
| Chat capability | Multi-turn with action buttons | AI responses include executable actions |

## Architecture

The HTTP server embeds in the existing daemon process, sharing its asyncio event loop and DB connection.

```
daemon starts → asyncio loop
  ├── Unix socket server (existing CLI protocol, unchanged)
  ├── HTTP server on localhost:8080 (new, serves web UI)
  ├── polling loop (existing, unchanged)
  └── auto-export (existing, unchanged)
```

**Startup sequence:** The HTTP server starts using `aiohttp.web.AppRunner` + `TCPSite` (non-blocking), the same pattern as the existing `asyncio.start_unix_server`. Both servers are started *before* entering the poll loop. `aiohttp.web.run_app()` must NOT be used — it would take over the event loop.

```python
# Pseudocode for daemon.start()
async def start(self):
    await self._init_db()
    await self._start_socket_server()   # existing
    if self.config.web_enabled:
        await self._start_web_server()  # new: AppRunner + TCPSite
    await self._poll_loop()             # existing, blocks until shutdown
```

- One process to manage. No IPC overhead.
- Web UI starts/stops with the daemon.
- Enabled via `web_enabled` config flag or `--web` flag on `aa start`.

### Security

Even on localhost, CSRF is a concern (malicious sites can POST to localhost). All POST/PATCH routes check the `Origin` header — reject requests where Origin is not `http://localhost:{port}`. This is a simple middleware check, no tokens needed.

## Routes

| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Full page — todo table + chat panel |
| `/todos` | GET | htmx partial — filtered/sorted todo rows |
| `/todos/<id>` | PATCH | Inline edit (priority, due date, title, category, details) |
| `/todos/<id>/detail` | GET | Expanded row content |
| `/todos/<id>/done` | POST | Mark done |
| `/todos/<id>/delete` | POST | Soft delete |
| `/todos/bulk` | POST | Bulk action (done, delete, set priority, set due date) |
| `/todos/new` | POST | Create todo |
| `/chat` | POST | Send message to ask engine, get streamed response (SSE) |
| `/chat/action` | POST | Execute action button (create todo, set due date, etc.) |

## The Table

### Columns

`☐ | P | Title | Due | Category | Project`

Default sort: priority ascending, then due date ascending (urgent + soonest first). This requires adding `sort` parameter support to `db.list_todos()` — the current implementation sorts by `priority, created_at`.

### Inline Editing

- **Priority** — click cell → dropdown (P1-P5), color-coded. Submits on select.
- **Due date** — click cell → native date picker. Submits on change.
- **Category/Project** — click cell → text input with datalist (autocomplete from existing values). Submits on blur/enter.
- **Title** — edited in the expanded detail view, not inline (too disruptive to dense layout).

All inline edits: cell click swaps to input via htmx, blur/enter/select sends `PATCH /todos/<id>`, server returns updated row partial.

**Sort-order changes:** When an inline edit changes priority or due date, the PATCH response includes an `HX-Trigger: refreshTable` header. The `<tbody>` listens via `hx-trigger="refreshTable from:body"` and re-fetches `GET /todos` to re-sort the full table.

### Row Expansion

Click anywhere on a row (except checkboxes and editable cells) → `GET /todos/<id>/detail` → detail panel slides open below the row.

Expanded view shows:
- Description/details (editable textarea, saves on blur)
- Linked inbox items
- Created date
- Delete button

### Creating Todos

A `+ New` button above the table inserts an empty row at the top with inline inputs for title, priority, due date, category, and project. Press Enter or click a "Save" button to `POST /todos/new`. Press Escape to cancel.

### Bulk Actions

- Hidden by default.
- Appears as a fixed toolbar above the chat panel when 1+ checkboxes are selected.
- Shows: `"N selected: [Done] [Delete] [Priority ▾] [Due Date ▾]"`
- Actions send `POST /todos/bulk` with selected IDs + action.
- Response includes `HX-Trigger: refreshTable` to re-fetch the table body.
- Toolbar hidden via JS after action completes.

### Search & Sort

- Single search input above the table. Filters on keyup (debounced 300ms) via htmx, targeting the `<tbody>`. Searches title, category, project, details. This requires extending `db.list_todos()` keyword search to also match `category` and `project` fields.
- Click column headers to toggle asc/desc sort. Server-side sort via query params (`?sort=priority&dir=asc`), htmx replaces table body.

### Error Handling

- Inline edit failures: the PATCH response returns a 422 with the original cell value, htmx swaps it back. A brief toast notification appears at top-right ("Failed to update priority").
- Bulk action partial failures: response returns success count + failures as a toast.
- Network errors: htmx's built-in `htmx:responseError` event triggers a generic toast.

## Chat Panel

### Layout

- Bottom of page, resizable via drag handle (like browser devtools).
- Default height ~200px.
- Contains: message history area, text input, send button, clear/reset button.

### Conversation Flow

1. User types question → `POST /chat` with message + conversation history
2. Server calls `AskEngine.ask_stream()` with full context (todos, inbox, calendar) + conversation history
3. Response streams back via SSE with typed events
4. Client JS accumulates text events, renders action events as buttons

### Streaming Protocol (SSE)

The `POST /chat` endpoint returns an SSE stream with typed events:

```
event: text
data: Here's what I recommend

event: text
data:  for today...

event: action
data: {"type": "create_todo", "title": "Review compliance docs", "priority": 2, "due": "2026-03-28"}

event: action
data: {"type": "mark_done", "todo_id": "abc12345"}

event: action
data: {"type": "set_priority", "todo_id": "def45678", "priority": 1}

event: done
data: {}
```

Client-side JS (minimal, ~50 lines alongside htmx):
- `text` events: append to current message bubble
- `action` events: render as clickable buttons below the message
- `done` event: close the EventSource, enable input

### Action Button Format

The ask engine's system prompt is extended to emit structured JSON action blocks in a fenced section:

```
Your natural language response here...

\```actions
[{"type": "create_todo", "title": "Review compliance docs", "priority": 2, "due": "2026-03-28"}]
\```
```

The server parses the fenced `actions` block from the completed response, strips it from the displayed text, and sends each action as a separate SSE `action` event. Supported action types:

| Type | Fields | Maps to |
|------|--------|---------|
| `create_todo` | `title`, `priority?`, `due?`, `category?`, `project?` | `POST /todos/new` |
| `mark_done` | `todo_id` | `POST /todos/<id>/done` |
| `set_priority` | `todo_id`, `priority` | `PATCH /todos/<id>` |
| `set_due` | `todo_id`, `due` | `PATCH /todos/<id>` |
| `delete_todo` | `todo_id` | `POST /todos/<id>/delete` |

Clicking a button → `POST /chat/action` with the action JSON → executes the command → returns confirmation message as a new chat bubble + sends `HX-Trigger: refreshTable` to update the todo table.

**Streaming implementation:** Add `ask_stream()` method to `AskEngine` using `self._client.messages.stream()` (Anthropic SDK streaming API). This yields incremental text chunks. The server forwards chunks as SSE `text` events. After the stream completes, the server parses the full response for the `actions` fence and emits `action` events.

### Session Management

- Server generates a session ID via `Set-Cookie` on first `GET /` request.
- Conversation history stored in server memory (dict keyed by session ID).
- Max 10 sessions with LRU eviction.
- Resets on browser refresh or explicit clear button.
- No persistence to DB — ephemeral by design.

### Error Handling

- API key missing/invalid: chat panel shows an inline error message.
- Rate limit / API error: SSE stream sends an `event: error` with message, client renders it.
- Unparseable action block: actions silently omitted, text response displayed normally.

## File Organization

### New Files

```
src/aa/
├── web.py                    # aiohttp routes, startup/shutdown, CSRF middleware
├── templates/
│   ├── base.html             # page shell (table + chat panel + bulk toolbar)
│   └── partials/
│       ├── todo_row.html     # single table row
│       ├── todo_detail.html  # expanded detail panel
│       ├── todo_table.html   # full table body (for sort/filter refreshes)
│       ├── chat_message.html # single chat message bubble
│       └── bulk_toolbar.html # bulk action bar
└── static/
    ├── style.css             # all styles (single file)
    └── htmx.min.js           # vendored htmx (no CDN dependency)
```

### New Dependencies

- `aiohttp>=3.9` — async HTTP server
- `jinja2>=3.1` — template engine
- `aiohttp-jinja2>=1.6` — aiohttp + Jinja2 integration

Note: SSE is implemented directly with `aiohttp.web.StreamResponse` — no `aiohttp-sse` dependency needed.

### Changes to Existing Files

| File | Change |
|------|--------|
| `daemon.py` | Add `_start_web_server()` using `AppRunner`+`TCPSite`, called before poll loop |
| `config.py` | Add `web_port: int = 8080` and `web_enabled: bool = False` |
| `cli.py` | Add `--web` flag to `aa start` |
| `ai/ask.py` | Add `ask_stream()` method using SDK streaming; extend system prompt for structured action blocks; add conversation history parameter |
| `db.py` | Add `sort` parameter to `list_todos()`; extend keyword search to include `category` and `project` |

### No Changes To

- `server.py` — Unix socket protocol stays as-is for CLI
- All connectors — unchanged
