"""
Step 3 Room Selection Action Handler.

Extracted from step3_handler.py as part of R3 refactoring (Dec 2025).

This module handles the room selection action triggered when a client
confirms their room choice. It persists the selection and prompts for products.

Usage:
    from .selection import handle_select_room_action
"""

from __future__ import annotations

from datetime import datetime as dt
from typing import Any, Dict, List, Optional

from backend.debug.hooks import trace_db_write, trace_state
from backend.detection.special.room_conflict import (
    ConflictType,
    detect_conflict_type,
    compose_conflict_warning_message,
)
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import update_event_metadata, update_event_room


def _thread_id(state: WorkflowState) -> str:
    """Get thread identifier from state, preferring thread_id over client_id over message id."""
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"


def _reset_room_attempts(event_entry: dict) -> None:
    """Reset room proposal attempt counter after successful selection."""
    if not event_entry.get("room_proposal_attempts"):
        return
    event_entry["room_proposal_attempts"] = 0
    update_event_metadata(event_entry, room_proposal_attempts=0)


def _format_display_date(chosen_date: Optional[str]) -> str:
    """Format date for display, falling back to raw date or placeholder."""
    display = format_iso_date_to_ddmmyyyy(chosen_date)
    if display:
        return display
    return chosen_date or "your requested date"


def handle_select_room_action(
    state: WorkflowState,
    *,
    room: str,
    status: str,
    date: Optional[str] = None,
) -> GroupResult:
    """[OpenEvent Action] Persist the client's room choice and prompt for products."""

    thread_id = _thread_id(state)
    event_entry = state.event_entry
    if not event_entry or not event_entry.get("event_id"):
        payload = {
            "client_id": state.client_id,
            "intent": state.intent.value if state.intent else None,
            "reason": "missing_event_record",
            "context": state.context_snapshot,
        }
        return GroupResult(action="room_select_missing", payload=payload, halt=True)

    event_id = event_entry["event_id"]

    # [SOFT CONFLICT CHECK] Detect if another client has an Option on this room/date
    chosen_date = date or event_entry.get("chosen_date") or ""
    conflict_type, conflict_info = detect_conflict_type(
        db=state.db,
        event_id=event_id,
        room_id=room,
        event_date=chosen_date,
        action="select",  # Client is selecting (becoming Option)
    )

    # Handle soft conflict: NOTIFY client and ask if they insist
    if conflict_type == ConflictType.SOFT and conflict_info:
        display_date = _format_display_date(chosen_date)

        # Store conflict info for follow-up handling when client responds
        event_entry["conflict_pending_decision"] = {
            "room_id": room,
            "room_status": status,
            "event_date": chosen_date,
            "conflict_info": dict(conflict_info),
            "created_at": dt.now().isoformat(),
        }

        # Mark event with soft conflict flag
        event_entry["has_conflict"] = True
        event_entry["conflict_with"] = conflict_info.get("conflicting_event_id")
        event_entry["conflict_type"] = "soft_pending"  # Pending client decision
        state.extras["persist"] = True

        # Compose warning message using existing function
        warning = compose_conflict_warning_message(room, display_date)
        body_with_footer = append_footer(
            warning,
            step=3,
            next_step="Room decision",
            thread_state="Awaiting Client",
        )

        # Return response with action buttons asking what client wants to do
        state.draft_messages.clear()
        state.add_draft_message({
            "body": body_with_footer,
            "body_markdown": warning,
            "step": 3,
            "next_step": "Room decision",
            "thread_state": "Awaiting Client",
            "topic": "soft_conflict_warning",
            "actions": [
                {
                    "type": "conflict_choose_alternative",
                    "label": "Show me other options",
                    "room": room,
                    "date": chosen_date,
                },
                {
                    "type": "conflict_insist",
                    "label": "I need this room (explain why)",
                    "room": room,
                    "date": chosen_date,
                },
            ],
            "requires_approval": False,
        })

        # Create manager visibility task (non-blocking)
        tasks = state.db.setdefault("tasks", {})
        task_id = f"soft_conflict_{event_id}_{dt.now().strftime('%Y%m%d%H%M%S')}"
        tasks[task_id] = {
            "type": "soft_room_conflict_notification",
            "status": "pending",
            "created_at": dt.now().isoformat(),
            "event_id": event_id,
            "data": {
                "room_id": room,
                "event_date": chosen_date,
                "client_1": {
                    "event_id": conflict_info.get("conflicting_event_id"),
                    "email": conflict_info.get("conflicting_client_email"),
                    "name": conflict_info.get("conflicting_client_name"),
                    "status": conflict_info.get("status"),
                },
                "client_2": {
                    "event_id": event_id,
                    "email": event_entry.get("client_email"),
                    "name": event_entry.get("client_name"),
                    "status": "Considering (notified of conflict)",
                },
            },
            "description": (
                f"Soft Conflict: {room} on {display_date}\n\n"
                f"Client 1: {conflict_info.get('conflicting_client_email')} (already {conflict_info.get('status')})\n"
                f"Client 2: {event_entry.get('client_email')} (has been notified)\n\n"
                f"Client 2 is deciding whether to insist or choose alternative."
            ),
        }
        event_entry["conflict_task_id"] = task_id

        payload = {
            "client_id": state.client_id,
            "event_id": event_id,
            "intent": state.intent.value if state.intent else None,
            "conflict_type": "soft",
            "conflict_room": room,
            "conflict_date": chosen_date,
            "draft_messages": state.draft_messages,
            "thread_state": "Awaiting Client",
            "context": state.context_snapshot,
        }
        return GroupResult(action="soft_conflict_warning", payload=payload, halt=False)

    update_event_room(
        state.db,
        event_id,
        selected_room=room,
        status=status,
    )

    # Get requirements_hash to lock the room with current requirements snapshot
    requirements_hash = event_entry.get("requirements_hash")

    update_event_metadata(
        event_entry,
        locked_room_id=room,
        room_eval_hash=requirements_hash,
        current_step=4,
        thread_state="Awaiting Client",
        status="Option",  # Room selected → calendar blocked as Option
    )
    _reset_room_attempts(event_entry)

    event_entry["selected_room"] = room
    event_entry["selected_room_status"] = status
    flags = event_entry.setdefault("flags", {})
    flags["room_selected"] = True
    pending = event_entry.setdefault("room_pending_decision", {})
    pending["selected_room"] = room
    pending["selected_status"] = status

    if not hasattr(state, "flags") or not isinstance(getattr(state, "flags"), dict):
        state.flags = {}
    state.flags["room_selected"] = True

    preferences = event_entry.get("preferences") or state.user_info.get("preferences") or {}
    wish_products: List[str] = []
    if isinstance(preferences, dict):
        raw_wishes = preferences.get("wish_products") or []
        if isinstance(raw_wishes, (list, tuple)):
            wish_products = [str(item).strip() for item in raw_wishes if str(item).strip()]

    top_summary = (
        f"Top picks: {', '.join(wish_products[:3])}."
        if wish_products
        else "Products available for this room."
    )

    chosen_date = date or event_entry.get("chosen_date") or ""
    display_date = _format_display_date(chosen_date)

    body_lines = [
        f"Great — {room} on {display_date} is reserved as an option.",
        "Would you like to (A) review products for this room, or (B) confirm products now?",
        top_summary,
    ]
    body_text = "\n\n".join(body_lines)
    body_with_footer = append_footer(
        body_text,
        step=4,
        next_step="Pick products",
        thread_state="Awaiting Client",
    )

    state.draft_messages.clear()
    follow_up = {
        "body": body_with_footer,
        "step": 4,
        "next_step": "Pick products",
        "thread_state": "Awaiting Client",
        "topic": "room_selected_follow_up",
        "actions": [
            {
                "type": "explore_products",
                "label": f"Explore products for {room}",
                "room": room,
                "date": chosen_date or display_date,
            },
            {
                "type": "confirm_products",
                "label": f"Confirm products for {room}",
                "room": room,
                "date": chosen_date or display_date,
            },
        ],
        "requires_approval": False,
    }
    state.add_draft_message(follow_up)

    state.current_step = 4
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True

    trace_db_write(
        thread_id,
        "Step3_Room",
        "db.events.update_room",
        {"selected_room": room, "status": status},
    )

    trace_state(
        thread_id,
        "Step3_Room",
        {
            "selected_room": room,
            "selected_status": status,
            "room_hint": top_summary if wish_products else "Products available",
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": event_id,
        "intent": state.intent.value if state.intent else None,
        "selected_room": room,
        "selected_status": status,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="room_selected", payload=payload, halt=False)


__all__ = [
    "handle_select_room_action",
    "_thread_id",
    "_reset_room_attempts",
    "_format_display_date",
]
