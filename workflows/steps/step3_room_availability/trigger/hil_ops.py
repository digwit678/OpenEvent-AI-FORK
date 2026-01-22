"""
Step 3 HIL Operations and Room Helpers.

Extracted from step3_handler.py as part of R8 refactoring (Jan 2026).

This module contains:
- apply_hil_decision: Handle HIL approval/rejection for room evaluation
- preferred_room: Determine preferred room priority
- increment_room_attempt: Track room proposal attempts

Usage:
    from .hil_ops import (
        apply_hil_decision,
        preferred_room,
        increment_room_attempt,
    )
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from workflows.common.types import GroupResult, WorkflowState
from workflows.io.database import append_audit_entry, update_event_metadata
from debug.hooks import trace_db_write, trace_gate

from .selection import _reset_room_attempts, _thread_id

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# HIL Decision Handling
# -----------------------------------------------------------------------------


def apply_hil_decision(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    decision: str,
) -> GroupResult:
    """Handle HIL approval or rejection for the latest room evaluation.

    Args:
        state: Current workflow state
        event_entry: Event database entry
        decision: "approve" or "reject"

    Returns:
        GroupResult with appropriate action and payload
    """
    thread_id = _thread_id(state)
    pending = event_entry.get("room_pending_decision")
    if not pending:
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "no_pending_room_decision",
            "context": state.context_snapshot,
        }
        return GroupResult(action="room_hil_missing", payload=payload, halt=True)

    if decision != "approve":
        # Reset pending decision and keep awaiting further actions.
        event_entry.pop("room_pending_decision", None)
        draft = {
            "body": "Approval rejected — please provide updated guidance on the room.",
            "step": 3,
            "topic": "room_hil_reject",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        update_event_metadata(event_entry, current_step=3, thread_state="Waiting on HIL")
        state.set_thread_state("Waiting on HIL")
        state.extras["persist"] = True
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "draft_messages": state.draft_messages,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
            "persisted": True,
        }
        return GroupResult(action="room_hil_rejected", payload=payload, halt=True)

    selected_room = pending.get("selected_room")
    requirements_hash = event_entry.get("requirements_hash") or pending.get("requirements_hash")

    manager_requested = bool((event_entry.get("flags") or {}).get("manager_requested"))
    next_thread_state = "Waiting on HIL" if manager_requested else "Awaiting Client"

    update_event_metadata(
        event_entry,
        locked_room_id=selected_room,
        room_eval_hash=requirements_hash,
        current_step=4,
        thread_state=next_thread_state,
        status="Option",  # Room selected → calendar blocked as Option
    )
    _reset_room_attempts(event_entry)
    trace_gate(
        thread_id,
        "Step3_Room",
        "room_selected",
        True,
        {"locked_room_id": selected_room, "status": "Option"},
    )
    trace_gate(
        thread_id,
        "Step3_Room",
        "requirements_match",
        bool(requirements_hash),
        {"requirements_hash": requirements_hash, "room_eval_hash": requirements_hash},
    )
    trace_db_write(
        thread_id,
        "Step3_Room",
        "db.events.lock_room",
        {"locked_room_id": selected_room, "room_eval_hash": requirements_hash, "status": "Option"},
    )
    append_audit_entry(event_entry, 3, 4, "room_hil_approved")
    event_entry.pop("room_pending_decision", None)

    state.current_step = 4
    state.caller_step = None
    state.set_thread_state(next_thread_state)
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "selected_room": selected_room,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="room_hil_approved", payload=payload, halt=False)


# -----------------------------------------------------------------------------
# Room Preference Helper
# -----------------------------------------------------------------------------


def preferred_room(
    event_entry: Dict[str, Any],
    user_requested_room: Optional[str],
) -> Optional[str]:
    """Determine the preferred room priority.

    Priority order:
    1. User-requested room (from current message)
    2. Preferred room from requirements
    3. Already locked room

    Args:
        event_entry: Event database entry
        user_requested_room: Room explicitly requested in current message

    Returns:
        Preferred room name or None
    """
    if user_requested_room:
        return user_requested_room
    requirements = event_entry.get("requirements") or {}
    pref_room = requirements.get("preferred_room")
    if pref_room:
        return pref_room
    return event_entry.get("locked_room_id")


# -----------------------------------------------------------------------------
# Room Attempt Counter
# -----------------------------------------------------------------------------


def increment_room_attempt(event_entry: Dict[str, Any]) -> int:
    """Increment and return the room proposal attempt counter.

    Args:
        event_entry: Event database entry

    Returns:
        Updated attempt count
    """
    try:
        current = int(event_entry.get("room_proposal_attempts") or 0)
    except (TypeError, ValueError):
        current = 0
    updated = current + 1
    event_entry["room_proposal_attempts"] = updated
    update_event_metadata(event_entry, room_proposal_attempts=updated)
    return updated


# -----------------------------------------------------------------------------
# Backward-compatible aliases (prefixed with underscore)
# -----------------------------------------------------------------------------

_apply_hil_decision = apply_hil_decision
_preferred_room = preferred_room
_increment_room_attempt = increment_room_attempt


# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = [
    # Public names
    "apply_hil_decision",
    "preferred_room",
    "increment_room_attempt",
    # Backward-compatible underscore aliases
    "_apply_hil_decision",
    "_preferred_room",
    "_increment_room_attempt",
]
