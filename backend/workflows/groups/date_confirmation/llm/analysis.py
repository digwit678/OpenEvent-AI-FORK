from __future__ import annotations

__workflow_role__ = "llm"


def compose_date_confirmation_reply(event_date: str, pax_label: str) -> str:
    """[LLM] Draft the acknowledgement after a client confirms the date."""

    group_fragment = pax_label or "your group"
    return (
        f"Great — I’ve marked {event_date} for your event. "
        f"We’ll now check room availability for {group_fragment} and share the results shortly."
    )
