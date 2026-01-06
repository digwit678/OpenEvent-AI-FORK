"""
Smart Shortcuts - Intent Parser.

Extracted from smart_shortcuts.py as part of S3 refactoring (Dec 2025).

This module handles intent parsing for the shortcuts planner:
- Room intent parsing (room selection requests)
- Participants intent parsing (headcount updates)
- Billing intent parsing (billing address capture)
- Intent deferral and persistence

Usage:
    from .intent_parser import (
        parse_room_intent, parse_participants_intent, parse_billing_intent,
        add_needs_input, defer_intent, persist_pending_intents,
    )
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from detection.special.room_conflict import (
    ConflictType,
    detect_conflict_type,
)

from .shortcuts_types import ParsedIntent

if TYPE_CHECKING:
    from .smart_shortcuts import _ShortcutPlanner


# --------------------------------------------------------------------------
# Room intent parsing
# --------------------------------------------------------------------------


def parse_room_intent(planner: "_ShortcutPlanner") -> None:
    """Parse room selection intent from user_info.

    If a room is mentioned and can be locked (matching pending decision),
    adds a verifiable room_selection intent. Otherwise defers for availability.

    Args:
        planner: The shortcuts planner instance
    """
    room = planner.user_info.get("room")
    if not room:
        return

    can_lock, failure_reason = can_lock_room(planner, room)
    if can_lock:
        intent = ParsedIntent("room_selection", {"room": room}, verifiable=True)
        planner.verifiable.append(intent)
    else:
        # Pass the specific failure reason so the message can be tailored
        reason = failure_reason or "room_requires_date"
        add_needs_input(
            planner,
            "availability",
            {"room": room, "reason": reason},
            reason=reason,
        )


def can_lock_room(planner: "_ShortcutPlanner", requested_room: str) -> tuple:
    """Check if a requested room can be locked.

    Room can be locked if:
    1. Room exists in the database (validated centrally via detect_conflict_type)
    2. There's a pending decision with matching room and status Available/Option, OR
    3. No pending decision but we can verify availability directly (for initial messages)

    Args:
        planner: The shortcuts planner instance
        requested_room: The room name to check

    Returns:
        Tuple of (can_lock: bool, failure_reason: str or None)
        - (True, None) if room can be locked
        - (False, "room_not_found") if room doesn't exist
        - (False, "room_unavailable") if room is booked
        - (False, "room_requires_date") if need date to check
        - (False, "room_conflict") if soft/hard conflict exists
    """
    requested_normalized = str(requested_room).strip().lower()

    # Path 1: Check pending decision from previous Step 3 run
    pending = planner.event.get("room_pending_decision") or {}
    selected = pending.get("selected_room")
    status = pending.get("selected_status")
    if selected and selected.lower() == requested_normalized:
        if status in {"Available", "Option"}:
            return True, None
        return False, "room_unavailable"  # Room exists in pending but is unavailable

    # Path 2: No pending decision - check availability directly (for initial messages)
    # This allows shortcuts to fire on the very first message when client specifies a room
    chosen_date = planner.event.get("chosen_date")
    if not chosen_date:
        return False, "room_requires_date"  # Need a date to check availability

    # Use detect_conflict_type() which properly excludes our own event_id
    # This prevents the bug where our newly created event is detected as a conflict
    event_id = planner.event.get("event_id")
    db = planner.state.db if hasattr(planner.state, "db") else {}

    conflict_type, conflict_info = detect_conflict_type(
        db=db,
        event_id=event_id,  # Exclude our own event
        room_id=requested_room,
        event_date=chosen_date,
        action="select",
        event_entry=planner.event,  # Enables time-aware conflict detection
    )

    # Check for invalid room first
    if conflict_type == ConflictType.INVALID_ROOM:
        return False, "room_not_found"

    # Only allow if no conflict (NONE) - Available room
    # If SOFT conflict (another client has Option), defer to Step 3 for conflict UI
    # If HARD conflict (Confirmed booking), room is unavailable
    if conflict_type == ConflictType.NONE:
        planner.event["room_pending_decision"] = {
            "selected_room": requested_room,
            "selected_status": "Available",
            "requirements_hash": planner.event.get("requirements_hash"),
        }
        return True, None

    # SOFT or HARD conflict
    return False, "room_conflict"


# --------------------------------------------------------------------------
# Participants intent parsing
# --------------------------------------------------------------------------


def parse_participants_intent(planner: "_ShortcutPlanner") -> None:
    """Parse participants/headcount intent from user_info.

    If participants is a valid number, adds a verifiable participants_update
    intent. Otherwise defers for clarification.

    Args:
        planner: The shortcuts planner instance
    """
    participants = planner.user_info.get("participants")
    if participants is None:
        return

    if isinstance(participants, (int, float)) or str(participants).isdigit():
        intent = ParsedIntent(
            "participants_update",
            {"participants": int(participants)},
            verifiable=True,
        )
        planner.verifiable.append(intent)
    else:
        add_needs_input(
            planner,
            "requirements",
            {"reason": "participants_unclear"},
            reason="participants_unclear",
        )


# --------------------------------------------------------------------------
# Billing intent parsing
# --------------------------------------------------------------------------


def parse_billing_intent(planner: "_ShortcutPlanner") -> None:
    """Parse billing address intent from user_info.

    Billing is always deferred (needs offer acceptance first).

    Args:
        planner: The shortcuts planner instance
    """
    billing = planner.user_info.get("billing_address")
    if billing:
        add_needs_input(
            planner,
            "billing",
            {"billing_address": billing, "reason": "billing_after_offer"},
            reason="billing_after_offer",
        )


# --------------------------------------------------------------------------
# Intent deferral and persistence
# --------------------------------------------------------------------------


def add_needs_input(
    planner: "_ShortcutPlanner",
    intent_type: str,
    data: Dict[str, Any],
    reason: str = "needs_input",
) -> None:
    """Add a deferred intent that needs user input.

    Creates a ParsedIntent with verifiable=False and adds to needs_input list.
    Also records telemetry and pending items for persistence.

    Args:
        planner: The shortcuts planner instance
        intent_type: Type of intent (e.g., "availability", "billing")
        data: Intent data/entities
        reason: Reason for deferral
    """
    planner.needs_input.append(
        ParsedIntent(intent_type, data, verifiable=False, reason=reason)
    )
    payload = {
        "type": intent_type,
        "entities": data,
        "confidence": 0.75,
        "reason_deferred": reason,
        "ts": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }
    planner.telemetry.deferred.append(payload)
    planner.pending_items.append(payload)


def defer_intent(
    planner: "_ShortcutPlanner",
    intent: ParsedIntent,
    reason: str,
) -> None:
    """Defer a parsed intent for later processing.

    Records the intent in telemetry and pending items. If reason is
    "combined_limit_reached" and intent is product_add, also adds
    a product_followup needs_input.

    Args:
        planner: The shortcuts planner instance
        intent: The intent to defer
        reason: Reason for deferral
    """
    payload = {
        "type": intent.type,
        "entities": intent.data,
        "confidence": 0.95,
        "reason_deferred": reason,
        "ts": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }
    planner.telemetry.deferred.append(payload)
    planner.pending_items.append(payload)

    if reason == "combined_limit_reached" and intent.type == "product_add":
        planner.needs_input.append(
            ParsedIntent("product_followup", intent.data, verifiable=False, reason=reason)
        )


def persist_pending_intents(planner: "_ShortcutPlanner") -> None:
    """Persist pending intents to event storage.

    Appends all pending_items to the event's pending_intents list
    and marks state for persistence.

    Args:
        planner: The shortcuts planner instance
    """
    if not planner.pending_items:
        return

    existing = list(planner.event.get("pending_intents") or [])
    existing.extend(planner.pending_items)
    planner.event["pending_intents"] = existing
    planner.state.extras["persist"] = True


__all__ = [
    # Room parsing
    "parse_room_intent",
    "can_lock_room",
    # Participants parsing
    "parse_participants_intent",
    # Billing parsing
    "parse_billing_intent",
    # Deferral
    "add_needs_input",
    "defer_intent",
    "persist_pending_intents",
]
