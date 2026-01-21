"""
Central Detour Acknowledgment Utility

This module provides acknowledgment messages for detours (date, room, requirements changes).
It's called from pre_route.py when a change is detected and processed.

The acknowledgment is added as a draft message that appears BEFORE other content,
providing immediate feedback about the change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from workflows.common.types import WorkflowState
from workflows.change_propagation import ChangeType, EnhancedChangeResult

logger = logging.getLogger(__name__)


@dataclass
class DetourAckResult:
    """Result of detour acknowledgment generation."""

    generated: bool = False
    message: str = ""
    change_type: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None


def _format_date_display(date_str: Optional[str]) -> str:
    """Format date for user-friendly display."""
    if not date_str:
        return "your requested date"
    # If already in DD.MM.YYYY format, return as is
    if "." in date_str:
        return f"**{date_str}**"
    # If in YYYY-MM-DD format, convert to DD.MM.YYYY
    if "-" in date_str and len(date_str) == 10:
        parts = date_str.split("-")
        if len(parts) == 3:
            return f"**{parts[2]}.{parts[1]}.{parts[0]}**"
    return f"**{date_str}**"


def _format_room_display(room_name: Optional[str]) -> str:
    """Format room name for user-friendly display."""
    if not room_name:
        return "your requested room"
    return f"**{room_name}**"


def generate_detour_acknowledgment(
    change_type: ChangeType,
    decision: EnhancedChangeResult,
    event_entry: Dict[str, Any],
    user_info: Optional[Dict[str, Any]] = None,
) -> DetourAckResult:
    """
    Generate an acknowledgment message for a detour.

    Args:
        change_type: Type of change detected (DATE, ROOM, REQUIREMENTS, etc.)
        decision: The routing decision from route_change_on_updated_variable
        event_entry: Current event entry with state
        user_info: Extracted user info with the new values

    Returns:
        DetourAckResult with generated acknowledgment message
    """
    result = DetourAckResult()
    result.change_type = change_type.value

    user_info = user_info or {}

    if change_type == ChangeType.DATE:
        # Date change acknowledgment
        old_date = decision.old_value or event_entry.get("chosen_date")
        new_date = (
            user_info.get("date")
            or user_info.get("event_date")
            or event_entry.get("chosen_date")  # After update
        )
        result.old_value = old_date
        result.new_value = new_date

        if new_date:
            formatted_date = _format_date_display(new_date)
            result.message = f"I've updated your event to {formatted_date}. "
            result.generated = True

    elif change_type == ChangeType.ROOM:
        # Room change acknowledgment
        old_room = decision.old_value or event_entry.get("locked_room_id")
        new_room = (
            user_info.get("room")
            or user_info.get("preferred_room")
            or event_entry.get("locked_room_id")  # After update
        )
        result.old_value = old_room
        result.new_value = new_room

        if new_room:
            formatted_room = _format_room_display(new_room)
            result.message = f"I've noted your preference for {formatted_room}. "
            result.generated = True

    elif change_type == ChangeType.REQUIREMENTS:
        # Requirements change acknowledgment
        result.message = "I've noted your updated requirements. "
        result.generated = True

    elif change_type == ChangeType.PRODUCTS:
        # Product change acknowledgment
        result.message = "I've updated your product selections. "
        result.generated = True

    elif change_type == ChangeType.SITE_VISIT:
        # Site visit change acknowledgment
        result.message = "I've noted your site visit request. "
        result.generated = True

    elif change_type == ChangeType.CLIENT_INFO:
        # Client info change acknowledgment (billing handled separately)
        result.message = "I've updated your contact information. "
        result.generated = True

    if result.generated:
        logger.debug(
            "[DETOUR_ACK] Generated acknowledgment for %s change: %s -> %s",
            change_type.value,
            result.old_value,
            result.new_value,
        )

    return result


def add_detour_acknowledgment_draft(
    state: WorkflowState,
    ack_result: DetourAckResult,
) -> bool:
    """
    Add a draft message with the detour acknowledgment.

    The acknowledgment is added with prepend_mode=True so it appears
    BEFORE other content in the response.

    Args:
        state: Workflow state to add draft message to
        ack_result: Result from generate_detour_acknowledgment()

    Returns:
        True if acknowledgment was added, False otherwise
    """
    if not ack_result.generated or not ack_result.message:
        return False

    # Check if we already added an acknowledgment this turn
    if state.turn_notes.get("_detour_ack_added"):
        return False

    state.add_draft_message({
        "body_markdown": ack_result.message,
        "topic": f"{ack_result.change_type}_change_acknowledged",
        "prepend_mode": True,  # Signal to prepend to existing response
        "requires_approval": False,
    })

    state.turn_notes["_detour_ack_added"] = True
    logger.info(
        "[DETOUR_ACK] Added acknowledgment draft for %s change",
        ack_result.change_type,
    )

    return True


__all__ = [
    "DetourAckResult",
    "generate_detour_acknowledgment",
    "add_detour_acknowledgment_draft",
]
