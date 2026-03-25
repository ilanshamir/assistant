# Web UI for AA Personal Assistant

## Overview

A task-management-focused web interface for the AA personal assistant. The UI is a dense, hybrid table (compact rows with expandable details) served via htmx + Jinja2 templates from within the existing daemon process. A resizable bottom chat panel provides multi-turn `/ask` functionality with actionable response buttons.

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

- One process to manage. No IPC overhead.
- Web UI starts/stops with the daemon.
- Enabled via `web_enabled` config flag or `--web` flag on `aa start`.

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
| `/chat` | POST | Send message to ask engine, get streamed response |
| `/chat/action` | POST | Execute action button (create todo, set due date, etc.) |

## The Table

### Columns

`☐ | P | Title | Due | Category | Project`

Default sort: priority ascending, then due date ascending (urgent + soonest first).

### Inline Editing

- **Priority** — click cell → dropdown (P1-P5), color-coded. Submits on select.
- **Due date** — click cell → native date picker. Submits on change.
- **Category/Project** — click cell → text input with datalist (autocomplete from existing values). Submits on blur/enter.
- **Title** — edited in the expanded detail view, not inline (too disruptive to dense layout).

All inline edits: cell click swaps to input via htmx, blur/enter/select sends `PATCH /todos/<id>`, server returns updated row partial.

### Row Expansion

Click anywhere on a row (except checkboxes and editable cells) → `GET /todos/<id>/detail` → detail panel slides open below the row.

Expanded view shows:
- Description/details (editable textarea, saves on blur)
- Linked inbox items
- Created date
- Delete button

### Bulk Actions

- Hidden by default.
- Appears as a fixed toolbar above the chat panel when 1+ checkboxes are selected.
- Shows: `"N selected: [Done] [Delete] [Priority ▾] [Due Date ▾]"`
- Actions send `POST /todos/bulk` with selected IDs + action.
- Toolbar disappears after action completes and table refreshes.

### Search & Sort

- Single search input above the table. Filters on keyup (debounced 300ms) via htmx. Searches title, category, project, details.
- Click column headers to toggle asc/desc sort. Server-side sort, htmx replaces table body.

## Chat Panel

### Layout

- Bottom of page, resizable via drag handle (like browser devtools).
- Default height ~200px.
- Contains: message history area, text input, send button, clear/reset button.

### Conversation Flow

1. User types question → `POST /chat` with message + conversation history
2. Server calls `AskEngine` with full context (todos, inbox, calendar) + conversation history
3. Response streams back via SSE (Server-Sent Events) — text appears incrementally
4. Server parses AI response for structured action blocks, renders clickable buttons

### Action Buttons

The ask engine's system prompt is extended to emit structured actions alongside natural language. The server parses these and renders clickable buttons in the chat:

```
[Create Todo: "Review compliance docs" P2 due Mar 28]
[Set Priority: todo abc123 → P1]
[Mark Done: todo def456]
```

Clicking a button → `POST /chat/action` → executes the command → returns confirmation message in chat + refreshes the todo table via htmx.

### Session Management

- Conversation history held in server memory (dict keyed by session cookie).
- Resets on browser refresh or explicit clear button.
- No persistence to DB — ephemeral by design.

## File Organization

### New Files

```
src/aa/
├── web.py                    # aiohttp routes, startup/shutdown
├── templates/
│   ├── base.html             # page shell (table + chat panel + bulk toolbar)
│   └── partials/
│       ├── todo_row.html     # single table row
│       ├── todo_detail.html  # expanded detail panel
│       ├── todo_table.html   # full table body (for sort/filter refreshes)
│       ├── chat_message.html # single chat message bubble
│       └── bulk_toolbar.html # bulk action bar
└── static/
    └── style.css             # all styles (single file)
```

### New Dependencies

- `aiohttp>=3.9` — async HTTP server
- `jinja2>=3.1` — template engine
- `aiohttp-jinja2>=1.6` — aiohttp + Jinja2 integration
- `aiohttp-sse>=2.1` — server-sent events for chat streaming

### Changes to Existing Files

| File | Change |
|------|--------|
| `daemon.py` | Add HTTP server startup alongside Unix socket server |
| `config.py` | Add `web_port: int = 8080` and `web_enabled: bool = False` |
| `cli.py` | Add `--web` flag to `aa start` |
| `ai/ask.py` | Extend system prompt for structured actions; add conversation history support |

### No Changes To

- `db.py` — existing query methods are sufficient
- `server.py` — Unix socket protocol stays as-is for CLI
- All connectors — unchanged
