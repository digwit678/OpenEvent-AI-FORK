from __future__ import annotations

__workflow_role__ = "llm"


def compose_date_confirmation_reply(event_date: str, preferred_room: str | None) -> str:
    """[LLM] Draft a short acknowledgement for the confirmed date."""

    acknowledgement = (
        f"Thank you for confirming {event_date}. "
        "We will check room availability and follow up with the options."
    )
    if preferred_room and preferred_room != "Not specified":
        acknowledgement = (
            f"Thank you for confirming {event_date}. "
            f"We have noted {preferred_room} and will share availability updates shortly."
        )
    return acknowledgement + "\n\nNEXT STEP: I'll send the room availability update shortly."
