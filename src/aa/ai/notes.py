"""AI-powered extraction of todos from notes content."""

from __future__ import annotations

import json
import re

import anthropic

SYSTEM_PROMPT = """\
You are extracting actionable to-do items from the user's notes. The notes may contain:
- Explicit to-do items (lines starting with "TODO", "- [ ]", "* ", "- ", or similar)
- Meeting notes that contain implicit action items (e.g., "I need to send Bob the report")
- Mixed content where only some parts are actionable

For EACH actionable item you find, return a JSON object with:
- "title": concise, actionable title (imperative form, e.g., "Send Bob the Q3 report")
- "priority": integer 1-5 (1 = critical/urgent, 5 = low/someday). Infer from context, \
urgency words, deadlines mentioned, etc. Default to 3 if unclear.
- "category": infer from context — "work" or "private". Default to "work" if unclear.
- "project": infer a project name if one is apparent, otherwise null
- "due_date": if a deadline is mentioned, extract it as "YYYY-MM-DD". Otherwise null.
- "notes": any relevant context from the surrounding text (brief, 1-2 sentences max). \
Include who asked, what meeting it came from, etc. Null if no extra context.

Return ONLY a JSON array of objects. If there are no actionable items, return [].
Do not include non-actionable content (pure notes, observations, FYIs with no action needed).\
"""

USER_TEMPLATE = """\
Today's date is {today}.

Extract all actionable to-do items from these notes:

---
{content}
---

Return a JSON array of to-do objects."""


class NotesExtractor:
    """Uses Claude to extract actionable todos from notes content."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key
        self.model = model
        self._client: anthropic.AsyncAnthropic | None = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if not self._client:
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def extract_todos(self, content: str, today: str | None = None) -> list[dict]:
        """Extract actionable todos from notes content.

        Returns a list of dicts with: title, priority, category, project, due_date, notes
        """
        if not content.strip():
            return []

        if today is None:
            from datetime import date
            today = date.today().isoformat()

        prompt = USER_TEMPLATE.format(today=today, content=content)
        client = self._get_client()

        response = await client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        return self._parse_response(response.content[0].text)

    def _build_prompt(self, content: str, today: str) -> str:
        """Build the extraction prompt. Exposed for testing."""
        return USER_TEMPLATE.format(today=today, content=content)

    @staticmethod
    def _parse_response(text: str) -> list[dict]:
        """Parse JSON array from Claude response, handling markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
            text = text.strip()
        return json.loads(text)
