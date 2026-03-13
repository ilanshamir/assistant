"""AI triage engine using the Claude API to prioritize incoming items."""

from __future__ import annotations

import json
import re

import anthropic

SYSTEM_PROMPT = """\
You are a personal AI assistant responsible for triaging incoming messages and \
notifications. Your job is to prioritize items and recommend actions based on the \
user's rules, preferences, calendar, and active to-do list.

For EACH item, return a JSON object with these fields:
- "id": the item's original id
- "priority": integer 1-5 (1 = most urgent, 5 = least urgent)
- "summary": a single-line summary of what the item is about
- "action": one of "reply", "schedule", "delegate", "fyi", or "ignore"
- "create_todo": boolean — whether new to-do(s) should be created
- "todo_title": string or null — title for the to-do if create_todo is true (single todo)
- "todos": list or null — for items containing multiple action items (e.g. meeting notes), \
a list of {"title": string, "priority": int} objects. Each becomes a separate to-do. \
Use this instead of todo_title when the item contains multiple distinct tasks.
- "draft": string or null — a draft reply if the action is "reply"

IMPORTANT: When an item is a notes or document type (e.g. meeting notes, a to-do list file), \
carefully extract ALL individual action items and return them in the "todos" list. \
Do not collapse multiple tasks into a single to-do. Skip items already marked as done \
(e.g. prefixed with [done]) and skip items that duplicate existing active todos.

IMPORTANT: Pay close attention to due dates on existing todos. If an incoming item \
is related to a todo that is due soon, elevate its priority accordingly. Items \
connected to overdue or imminently-due tasks should be treated as more urgent.

Return ONLY a JSON array of objects. Do not include any other text or explanation.\
"""


class TriageEngine:
    """Uses the Claude API to prioritize and triage incoming items."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def triage(self, items: list[dict], context: dict) -> list[dict]:
        """Send items + context to Claude, parse structured response."""
        user_message = self._build_triage_prompt(items, context)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        text = response.content[0].text
        return self._parse_triage_response(text)

    def _build_triage_prompt(self, items: list[dict], context: dict) -> str:
        """Build the user message with all context and items."""
        sections: list[str] = []

        # Triage rules
        rules = context.get("rules", [])
        if rules:
            rules_text = "\n".join(f"- {r}" for r in rules)
            sections.append(f"## Triage Rules\n{rules_text}")
        else:
            sections.append("## Triage Rules\nNo custom rules configured.")

        # Feedback / learned preferences
        feedback = context.get("feedback_summary", "")
        if feedback:
            sections.append(f"## Learned Preferences\n{feedback}")

        # Today's calendar
        calendar = context.get("calendar_today", [])
        if calendar:
            cal_lines = []
            for event in calendar:
                cal_lines.append(f"- {event.get('subject', 'Untitled')} at {event.get('timestamp', 'unknown time')}")
            sections.append(f"## Today's Calendar\n" + "\n".join(cal_lines))
        else:
            sections.append("## Today's Calendar\nNo events today.")

        # Active todos with due dates
        todos = context.get("active_todos", [])
        if todos:
            todo_lines = []
            for todo in todos:
                due = todo.get("due_date", "no due date")
                prio = todo.get("priority", "?")
                todo_lines.append(f"- [{prio}] {todo.get('title', 'Untitled')} (due: {due})")
            sections.append(
                "## Active Todos (consider due dates for urgency)\n" + "\n".join(todo_lines)
            )
        else:
            sections.append("## Active Todos\nNo active todos.")

        # Dismissed/done/deleted todos — do NOT re-create these
        dismissed = context.get("dismissed_todos", [])
        if dismissed:
            dismissed_lines = [f"- {t.get('title', '')}" for t in dismissed]
            sections.append(
                "## Removed/Completed Todos (DO NOT re-create these)\n" + "\n".join(dismissed_lines)
            )

        # Items to triage
        sections.append(f"## Items to Triage\n```json\n{json.dumps(items, indent=2)}\n```")

        return "\n\n".join(sections)

    def _parse_triage_response(self, text: str) -> list[dict]:
        """Parse a JSON array from Claude's response text.

        Handles both plain JSON and markdown-wrapped JSON (```json ... ``` or ``` ... ```).
        """
        # Try to extract from markdown code block first
        code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if code_block:
            json_str = code_block.group(1).strip()
        else:
            json_str = text.strip()

        try:
            result = json.loads(json_str)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse triage response as JSON: {exc}") from exc

        if not isinstance(result, list):
            raise ValueError("Expected a JSON array from triage response")

        return result
