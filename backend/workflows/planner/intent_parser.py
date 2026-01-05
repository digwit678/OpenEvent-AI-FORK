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

    if can_lock_room(planner, room):
        intent = ParsedIntent("room_selection", {"room": room}, verifiable=True)
        planner.verifiable.append(intent)
    else:
        add_needs_input(
            planner,
            "availability",
            {"room": room, "reason": "room_requires_date"},
            reason="room_requires_date",
        )


def can_lock_room(planner: "_ShortcutPlanner", requested_room: str) -> bool:
    """Check if a requested room can be locked.

    Room can be locked if there's a pending decision with matching room
    and status is Available or Option.

    Args:
        planner: The shortcuts planner instance
        requested_room: The room name to check

    Returns:
        True if room can be locked, False otherwise
    """
    pending = planner.event.get("room_pending_decision") or {}
    selected = pending.get("selected_room")
    status = pending.get("selected_status")
    if not selected:
        return False
    return (
        selected.lower() == str(requested_room).strip().lower()
        and status in {"Available", "Option"}
    )


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
