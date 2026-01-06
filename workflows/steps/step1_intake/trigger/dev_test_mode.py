"""
Dev/test mode utilities for Step1 intake.

Extracted from step1_handler.py for better modularity (I2 refactoring).
Isolates the DEV_TEST_MODE "continue or reset" prompt so it doesn't pollute
production flows.

Usage:
    When DEV_TEST_MODE=1/true/yes is set, existing events at step > 1
    will trigger a choice prompt instead of auto-continuing.
"""

import os
from typing import Any, Dict, Optional

from workflows.common.types import GroupResult


def is_dev_test_mode_enabled() -> bool:
    """Check if dev/test mode is enabled via environment variable."""
    return os.getenv("DEV_TEST_MODE", "").lower() in ("1", "true", "yes")


def should_show_dev_choice(
    linked_event: Optional[Dict[str, Any]],
    current_step: int,
    skip_dev_choice: bool,
) -> bool:
    """
    Determine if the dev choice prompt should be shown.

    Returns True when:
    - DEV_TEST_MODE is enabled
    - There's an existing linked event
    - The event is past step 1
    - The skip_dev_choice flag is not set
    """
    if not is_dev_test_mode_enabled():
        return False
    if not linked_event:
        return False
    if current_step <= 1:
        return False
    if skip_dev_choice:
        return False
    return True


def build_dev_choice_result(
    linked_event: Dict[str, Any],
    current_step: int,
    owner_step: str,
    client_email: str,
) -> GroupResult:
    """
    Build the GroupResult for the dev choice prompt.

    This halts the workflow and presents the user with options to
    continue the existing event or reset the client data.
    """
    event_id = linked_event.get("event_id")
    event_date = (
        linked_event.get("chosen_date")
        or (linked_event.get("event_data") or {}).get("Event Date", "unknown")
    )
    locked_room = linked_event.get("locked_room_id") or "none"
    offer_accepted = bool(linked_event.get("offer_accepted"))

    return GroupResult(
        action="dev_choice_required",
        payload={
            "client_id": client_email,
            "event_id": event_id,
            "current_step": current_step,
            "step_name": owner_step,
            "event_date": event_date,
            "locked_room": locked_room,
            "offer_accepted": offer_accepted,
            "options": [
                {"id": "continue", "label": f"Continue at {owner_step}"},
                {"id": "reset", "label": "Reset client (delete all data)"},
            ],
            "message": (
                f"Existing event detected for {client_email} at {owner_step}. "
                f"Date: {event_date}, Room: {locked_room}"
            ),
        },
        halt=True,
    )


def maybe_show_dev_choice(
    linked_event: Optional[Dict[str, Any]],
    current_step: int,
    owner_step: str,
    client_email: str,
    skip_dev_choice: bool,
) -> Optional[GroupResult]:
    """
    Check if dev choice should be shown and return the result if so.

    This is the main entry point for dev mode handling. Call this early
    in the intake process to intercept existing events in dev mode.

    Returns:
        GroupResult with action="dev_choice_required" if dev choice should
        be shown, None otherwise.
    """
    if not should_show_dev_choice(linked_event, current_step, skip_dev_choice):
        return None

    # linked_event is guaranteed non-None here due to should_show_dev_choice
    return build_dev_choice_result(
        linked_event,  # type: ignore[arg-type]
        current_step,
        owner_step,
        client_email,
    )


__all__ = [
    "is_dev_test_mode_enabled",
    "should_show_dev_choice",
    "build_dev_choice_result",
    "maybe_show_dev_choice",
]
