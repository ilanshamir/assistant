"""Feedback summary builder for AI triage context."""

from collections import Counter


def build_feedback_summary(feedbacks: list[dict]) -> str:
    """Build a human-readable summary of feedback patterns for the AI triage prompt.

    Args:
        feedbacks: List of dicts, each with original_priority, corrected_priority,
                   original_action, and corrected_action.

    Returns:
        A concise summary string describing patterns found in user corrections.
    """
    if not feedbacks:
        return "No feedback yet."

    upgrades = 0
    downgrades = 0
    action_changes: Counter[tuple[str, str]] = Counter()

    for fb in feedbacks:
        orig_p = fb["original_priority"]
        corr_p = fb["corrected_priority"]
        orig_a = fb["original_action"]
        corr_a = fb["corrected_action"]

        if corr_p < orig_p:
            upgrades += 1
        elif corr_p > orig_p:
            downgrades += 1

        if orig_a != corr_a:
            action_changes[(orig_a, corr_a)] += 1

    parts: list[str] = []

    if upgrades:
        parts.append(f"User upgraded priority on {upgrades} item{'s' if upgrades != 1 else ''}.")

    if downgrades:
        parts.append(f"User downgraded priority on {downgrades} item{'s' if downgrades != 1 else ''}.")

    for (orig_a, corr_a), count in action_changes.most_common():
        parts.append(f"User changed action {orig_a} -> {corr_a} ({count} time{'s' if count != 1 else ''}).")

    return " ".join(parts) if parts else "No feedback yet."
