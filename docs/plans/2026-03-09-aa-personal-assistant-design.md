# AA — Personal Assistant Design

## Overview

`aa` is a Python CLI + background daemon that unifies email, calendar, Slack, Mattermost, and text notes into a single prioritized view. It uses Claude API for continuous triage, prioritization, response drafting, and todo extraction. It never sends anything without explicit user approval.

## Data Sources

| Source | Provider | Auth Method |
|--------|----------|-------------|
| Email (Resilio) | Gmail / Google Workspace | OAuth 2.0 (self-registered app) |
| Email (personal) | Outlook consumer | OAuth 2.0 (Microsoft) |
| Email (Nasuni) | Outlook / Okta | Microsoft Graph; fallback to browser-based Okta auth |
| Calendar (Resilio) | Google Calendar | Same OAuth as Resilio email |
| Calendar (personal) | Outlook Calendar | Same OAuth as personal Outlook |
| Calendar (Nasuni) | Outlook Calendar | Same OAuth as Nasuni email |
| Slack (workspace 1) | Slack | Bot/User token |
| Slack (workspace 2) | Slack | Bot/User token |
| Mattermost | Mattermost | Personal access token |
| Notes | Local text file | Filesystem watcher |

Additional email accounts can be added later via config — no code changes needed.

## Architecture

```
┌─────────────────────────────────────────────┐
│              CLI Interface (aa)              │
│  commands: inbox, todo, ask, reply, etc.     │
└──────────────────┬──────────────────────────┘
                   │ Unix socket
┌──────────────────▼──────────────────────────┐
│              Core Engine                     │
│  - Polling loop (per-source intervals)       │
│  - AI triage & prioritization (Claude API)   │
│  - Draft response generation                 │
│  - Notification manager                      │
│  - Notes file watcher                        │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│            State Store (SQLite)              │
│  - items, todos, todo_links, drafts          │
│  - sync_state, feedback, triage_rules, config│
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│           Source Connectors                   │
│  Gmail · Outlook (x2) · Slack (x2)          │
│  Google Cal · Outlook Cal (x2)               │
│  Mattermost · Notes file watcher             │
└──────────────────────────────────────────────┘
```

The daemon runs in the background, polling all sources. The CLI communicates with the daemon via a Unix socket at `~/.assistant/assistant.sock`.

## Data Model

### items — Unified inbox

All messages/events from all sources land here.

- `id` TEXT PRIMARY KEY
- `source` TEXT — e.g., 'resilio', 'outlook_personal', 'outlook_nasuni', 'slack_workspace1', 'slack_workspace2', 'mattermost'
- `source_id` TEXT — original ID in the source system
- `type` TEXT — 'email', 'dm', 'mention', 'channel_msg', 'calendar_event'
- `from_name` TEXT
- `from_address` TEXT
- `subject` TEXT
- `body` TEXT
- `timestamp` DATETIME
- `is_read` BOOLEAN DEFAULT 0
- `is_actionable` BOOLEAN DEFAULT 0
- `priority` INTEGER — 1 (critical) to 5 (low), set by AI
- `ai_summary` TEXT — one-line Claude summary
- `ai_suggested_action` TEXT — 'reply', 'schedule', 'delegate', 'fyi', 'ignore'
- `raw_json` TEXT — full original payload
- `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP

### todos — Prioritized task list

- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `title` TEXT NOT NULL
- `description` TEXT
- `priority` INTEGER DEFAULT 3 — 1 (critical) to 5 (low)
- `status` TEXT DEFAULT 'pending' — 'pending', 'in_progress', 'done'
- `source` TEXT DEFAULT 'user' — 'user' or 'ai'
- `notes` TEXT
- `due_date` DATETIME
- `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP
- `completed_at` DATETIME

### todo_links — Links todos to source items

- `todo_id` INTEGER REFERENCES todos(id)
- `item_id` TEXT REFERENCES items(id)
- PRIMARY KEY (todo_id, item_id)

### sync_state — Polling watermarks per source

- `source` TEXT PRIMARY KEY
- `last_sync` DATETIME
- `cursor` TEXT — pagination token / last seen ID
- `status` TEXT — 'ok', 'error', 'auth_expired'

### drafts — Responses awaiting approval

- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `item_id` TEXT REFERENCES items(id)
- `body` TEXT
- `status` TEXT DEFAULT 'pending' — 'pending', 'approved', 'rejected', 'sent'
- `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP

### feedback — User corrections to AI triage

- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `item_id` TEXT REFERENCES items(id)
- `original_priority` INTEGER
- `corrected_priority` INTEGER
- `original_action` TEXT
- `corrected_action` TEXT
- `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP

### triage_rules — Explicit user guidance

- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `rule` TEXT — natural language rule, e.g., "Anything from Bob is priority 1"
- `active` BOOLEAN DEFAULT 1
- `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP

### config — Key-value settings

- `key` TEXT PRIMARY KEY
- `value` TEXT — JSON blob

## AI Triage Flow

Each polling cycle:

1. Connectors fetch new items since last cursor
2. New items stored in SQLite
3. Untriaged items batched and sent to Claude API with context:
   - The new items
   - Today's calendar
   - Active todos
   - Recent high-priority items (rolling window)
   - Triage rules
   - Summary of past feedback patterns
4. Claude returns per item: priority, summary, suggested action, whether to create a todo, draft response if applicable
5. Results written back to SQLite
6. Priority 1-2 items trigger terminal notifications

## Feedback & Learning

- `aa reprioritize <id> <1-5>` and `aa dismiss <id>` store corrections in the feedback table
- `aa rule add "description"` creates explicit triage rules
- Before each triage call, Claude receives: all active rules + a summary of feedback patterns
- Over time, the system learns what matters to the user

## CLI Commands

```
# Daemon
aa start                           # start background daemon
aa stop                            # stop daemon
aa status                          # health, last sync times, errors

# Inbox / triage
aa inbox                           # unread items sorted by priority
aa inbox --source slack             # filter by source
aa show <id>                       # full detail + AI summary + suggested action
aa reply <id>                      # draft response, review/edit/send
aa dismiss <id>                    # not important, feeds into triage learning
aa reprioritize <id> <1-5>         # correct AI priority

# Todos
aa todo                            # list sorted by priority
aa todo add "title" [--priority N] [--due DATE] [--note "..."]
aa todo done <id>
aa todo edit <id> [--priority N] [--note "..."] [--title "..."]
aa todo link <id> <item-id>
aa todo rm <id>

# Calendar
aa calendar                        # today's schedule
aa calendar tomorrow
aa calendar week

# Chat
aa ask "What should I focus on right now?"
aa ask "Summarize the thread with Alice about the migration"

# Rules
aa rule add "description"
aa rule list
aa rule rm <id>

# Config & help
aa setup                           # first-run auth wizard
aa config                          # show config
aa help                            # list all commands
aa help <command>                  # detailed usage
```

Shell tab completion provided via click's built-in completion support (bash/zsh).

## Authentication

- **Resilio (Gmail):** OAuth 2.0 via self-registered Google Cloud project
- **Outlook consumer:** Standard Microsoft OAuth 2.0
- **Outlook Nasuni (Okta):** Microsoft Graph with delegated permissions; fallback to browser-based Okta auth if Graph access unavailable
- **Slack:** Bot or User tokens per workspace
- **Mattermost:** Personal access token
- **Credentials storage:** `~/.assistant/credentials.enc`, encrypted at rest via system keyring or master password

## Notifications

- Terminal bell + formatted message for priority 1-2 items
- Tmux status bar integration if running in tmux
- Configurable threshold: `aa config set notifications.level 2`

## Error Handling

- Each connector fails independently — one source down doesn't affect others
- Auth failures surface as notifications with remediation: `[AUTH] Outlook/nasuni token expired. Run: aa setup outlook_nasuni`
- Network failures retry with exponential backoff (max 5 min)
- All errors logged to `~/.assistant/logs/` with rotation
- `aa status` shows per-source health

## Rate Limiting

- Claude API: batch items per cycle
- Slack/Graph APIs: respect rate limit headers, auto back-off
- Polling intervals configurable per source (default: email 60s, Slack 30s, calendar 5min)

## Project Structure

```
assistant/
├── pyproject.toml
├── src/
│   └── aa/
│       ├── __init__.py
│       ├── cli.py
│       ├── daemon.py
│       ├── server.py
│       ├── db.py
│       ├── engine.py
│       ├── notifications.py
│       ├── notes_watcher.py
│       ├── config.py
│       ├── connectors/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── gmail.py
│       │   ├── outlook.py
│       │   ├── slack.py
│       │   ├── mattermost.py
│       │   └── calendar.py
│       └── ai/
│           ├── __init__.py
│           ├── triage.py
│           ├── drafts.py
│           └── rules.py
├── tests/
└── docs/
    └── plans/
```

## Key Dependencies

- `click` — CLI framework with shell completion
- `anthropic` — Claude API
- `google-api-python-client` + `google-auth` — Gmail & Google Calendar
- `msal` — Microsoft auth
- `msgraph-sdk` — Microsoft Graph API
- `slack-sdk` — Slack
- `mattermostdriver` — Mattermost
- `watchdog` — filesystem watcher
- `uvloop` — faster async event loop

## Testing Strategy

- **Unit tests:** Mock-based tests per connector (no real API calls)
- **AI tests:** Snapshot-based — known inputs, assert reasonable priority/action outputs
- **Integration tests:** Daemon with mock connectors
- **Manual:** `aa --dry-run` mode — polls but doesn't persist or notify
