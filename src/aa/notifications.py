"""Terminal notification formatting and filtering."""

from __future__ import annotations

import sys

PRIORITY_LABELS = {1: "URGENT", 2: "HIGH", 3: "MEDIUM", 4: "LOW", 5: "FYI"}


def format_notification(item: dict) -> str:
    """Format an item dict into a human-readable notification string."""
    priority = item.get("priority", 3)
    label = PRIORITY_LABELS.get(priority, "MEDIUM")
    source = item.get("source", "unknown")
    from_name = item.get("from_name", "unknown")
    summary = item.get("subject", "")
    action = item.get("action", "none") or "none"
    return f'[{label}] {source}: from {from_name}: "{summary}" \u2192 suggested: {action}'


def should_notify(priority: int, threshold: int = 2) -> bool:
    """Return True if priority is at or above (numerically <=) the threshold."""
    return priority <= threshold


def send_terminal_notification(text: str) -> None:
    """Write a bell character and formatted text to stderr."""
    sys.stderr.write(f"\a{text}\n")
    sys.stderr.flush()
