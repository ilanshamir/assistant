"""AI draft response generator using the Claude API."""

from __future__ import annotations

import anthropic

SYSTEM_PROMPT = (
    "You are drafting a response on behalf of the user. Write in their voice "
    "— professional but not stiff. Keep it concise. Return ONLY the response text."
)


class DraftGenerator:
    """Uses the Claude API to draft responses to incoming messages."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def generate_draft(self, item: dict, user_instruction: str | None = None) -> str:
        """Call Claude to draft a response to the given item."""
        user_message = self._build_draft_prompt(item, user_instruction)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    def _build_draft_prompt(self, item: dict, user_instruction: str | None = None) -> str:
        """Build the prompt with original message details and optional instruction."""
        sections: list[str] = []

        sections.append(
            f"## Original Message\n"
            f"From: {item.get('from_name', 'Unknown')}\n"
            f"Subject: {item.get('subject', '(no subject)')}\n"
            f"Body:\n{item.get('body', '')}"
        )

        if user_instruction:
            sections.append(f"## User Instruction\n{user_instruction}")

        sections.append("Please draft a reply to this message.")

        return "\n\n".join(sections)
