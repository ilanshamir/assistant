"""AI assistant for answering user questions with context."""

from __future__ import annotations

import json
import re
from datetime import date

import anthropic

SYSTEM_PROMPT = """\
You are a personal AI assistant. You have access to the user's inbox, todos, \
and calendar. Answer their questions helpfully and concisely using this context.

When planning a day or week, consider:
- Overdue and due-soon todos (prioritize by urgency)
- Upcoming calendar events
- High-priority inbox items that need attention
- The user's existing commitments and workload

Keep responses concise and actionable. Use bullet points for lists.\
"""

WEB_SYSTEM_PROMPT = """\
You are a personal AI assistant. You have access to the user's inbox, todos, \
and calendar. Answer their questions helpfully and concisely using this context.

When planning a day or week, consider:
- Overdue and due-soon todos (prioritize by urgency)
- Upcoming calendar events
- High-priority inbox items that need attention
- The user's existing commitments and workload

Keep responses concise and actionable. Use bullet points for lists.

When your response involves creating, modifying, or completing todos, include a \
structured action block at the end of your response using this format:

```actions
[{"type": "create_todo", "title": "...", "priority": 2, "due": "YYYY-MM-DD", "category": "...", "project": "..."}]
```

Supported action types:
- create_todo: fields are title (required), priority (1-5), due (YYYY-MM-DD), category, project
- mark_done: fields are todo_id (the 8-char prefix shown in brackets)
- set_priority: fields are todo_id, priority (1-5)
- set_due: fields are todo_id, due (YYYY-MM-DD)
- delete_todo: fields are todo_id

Only include actions when the user is asking you to do something, not when just discussing. \
The action block must be valid JSON.\
"""


def parse_actions(text: str) -> tuple[list[dict], str]:
    """Extract action blocks from AI response text.

    Returns (actions_list, cleaned_text_without_action_block).
    """
    pattern = r"```actions\s*\n(.*?)\n```"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return [], text

    try:
        actions = json.loads(match.group(1))
        if not isinstance(actions, list):
            actions = [actions]
    except (json.JSONDecodeError, ValueError):
        clean = text[:match.start()].rstrip() + text[match.end():].lstrip()
        return [], clean.strip()

    clean = text[:match.start()].rstrip() + text[match.end():].lstrip()
    return actions, clean.strip()


class AskEngine:
    """Uses the Claude API to answer user questions with context."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def ask(self, question: str, context: dict) -> str:
        """Send question + context to Claude, return the answer."""
        user_message = self._build_prompt(question, context)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    async def ask_stream(self, question: str, context: dict, history: list[dict] | None = None):
        """Stream answer chunks. Yields str chunks. Use WEB_SYSTEM_PROMPT for web UI."""
        user_message = self._build_prompt(question, context)
        messages = list(history) if history else []
        messages.append({"role": "user", "content": user_message})

        async with self._client.messages.stream(
            model=self._model,
            max_tokens=2048,
            system=WEB_SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    def _build_prompt(self, question: str, context: dict) -> str:
        """Build the user message with context and question."""
        sections: list[str] = []
        today = date.today().isoformat()
        sections.append(f"Today's date: {today}")

        # Active todos
        todos = context.get("todos", [])
        if todos:
            todo_lines = []
            for t in todos:
                due = t.get("due_date") or "no due date"
                prio = t.get("priority", "?")
                cat = t.get("category") or ""
                proj = t.get("project") or ""
                line = f"- [P{prio}] {t.get('title', 'Untitled')} (due: {due})"
                if cat:
                    line += f" @{cat}"
                if proj:
                    line += f" #{proj}"
                todo_lines.append(line)
            sections.append("## Active Todos\n" + "\n".join(todo_lines))
        else:
            sections.append("## Active Todos\nNo active todos.")

        # Recent inbox
        inbox = context.get("inbox", [])
        if inbox:
            inbox_lines = []
            for item in inbox[:20]:  # Limit to 20 most recent
                prio = item.get("priority", "?")
                frm = item.get("from_name", "Unknown")
                subj = item.get("subject", "(no subject)")
                action = item.get("action", "")
                inbox_lines.append(f"- [P{prio}] From {frm}: {subj} (action: {action})")
            sections.append("## Recent Inbox\n" + "\n".join(inbox_lines))
        else:
            sections.append("## Recent Inbox\nNo inbox items.")

        # Calendar
        calendar = context.get("calendar", [])
        if calendar:
            cal_lines = []
            for ev in calendar:
                subj = ev.get("subject", "Untitled")
                time = ev.get("timestamp", "unknown time")
                cal_lines.append(f"- {subj} at {time}")
            sections.append("## Calendar\n" + "\n".join(cal_lines))
        else:
            sections.append("## Calendar\nNo calendar events.")

        sections.append(f"## Question\n{question}")

        return "\n\n".join(sections)
