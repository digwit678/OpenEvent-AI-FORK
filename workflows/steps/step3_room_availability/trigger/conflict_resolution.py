"""
Step 3 Conflict Resolution Module.

Handles client response to soft conflict warning (Option + Option scenario).
Extracted from step3_handler.py as part of god-file refactoring (Jan 2026).

This module contains:
- Conflict response handling (alternative vs insist)
- Client intent detection for conflict resolution
- Alternative dates collection and formatting

Usage:
    from .conflict_resolution import (
        handle_conflict_response,
        collect_alternative_dates,
        format_alternative_dates_section,
    )
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from workflows.common.prompts import append_footer
from workflows.common.types import GroupResult, WorkflowState
from workflows.common.timeutils import parse_ddmmyyyy
from workflows.io.database import append_audit_entry, update_event_metadata
from detection.special.room_conflict import (
    get_available_rooms_on_date,
    handle_hard_conflict,
)
from debug.hooks import trace_marker

from .selection import _format_display_date


# -----------------------------------------------------------------------------
# Utility functions
# -----------------------------------------------------------------------------


def _strip_system_subject(subject: str) -> str:
    """Strip system-generated metadata from subject lines.

    The API adds "Client follow-up (YYYY-MM-DD HH:MM)" to follow-up messages.
    This timestamp should NOT be used for change detection as it represents
    when the message was sent, not the requested event date.
    """
    import re
    pattern = r"^Client follow-up\s*\(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\)\s*"
    return re.sub(pattern, "", subject, flags=re.IGNORECASE).strip()


def _message_text(state: WorkflowState) -> str:
    """Extract full message text from state.

    BUG FIX: Strips system-generated timestamps from subject before combining.
    These timestamps were incorrectly triggering DATE change detection.
    """
    message = state.message
    if not message:
        return ""
    subject = message.subject or ""
    body = message.body or ""
    clean_subject = _strip_system_subject(subject)
    if clean_subject and body:
        return f"{clean_subject}\n{body}"
    return clean_subject or body


def _format_short_date(iso_date: str) -> str:
    """Format ISO date to DD.MM.YYYY for display."""
    try:
        parsed = datetime.strptime(iso_date, "%Y-%m-%d")
        return parsed.strftime("%d.%m.%Y")
    except ValueError:
        return iso_date


def _to_iso(display_date: Optional[str]) -> Optional[str]:
    """Convert display date (DD.MM.YYYY) to ISO format (YYYY-MM-DD)."""
    if not display_date:
        return None
    parsed = parse_ddmmyyyy(display_date)
    if not parsed:
        return None
    return parsed.strftime("%Y-%m-%d")


# -----------------------------------------------------------------------------
# Client intent detection for conflicts
# -----------------------------------------------------------------------------


def detect_wants_alternative(message_lower: str, state: WorkflowState) -> bool:
    """Detect if client wants to see alternative rooms."""
    user_info = state.user_info or {}
    if user_info.get("clicked_action") == "conflict_choose_alternative":
        return True

    alternative_keywords = [
        "other option", "other room", "alternative", "different room",
        "show me other", "what else", "another room", "see other",
        "different date", "another date",
    ]
    return any(kw in message_lower for kw in alternative_keywords)


def detect_wants_to_insist(message_lower: str, state: WorkflowState) -> bool:
    """Detect if client wants to insist on this room."""
    user_info = state.user_info or {}
    if user_info.get("clicked_action") == "conflict_insist":
        return True

    insist_keywords = [
        "i need this", "i really need", "must have", "insist",
        "this room please", "please this room", "important",
        "birthday", "anniversary", "special", "only this",
        "can't change", "no other", "has to be",
    ]
    return any(kw in message_lower for kw in insist_keywords)


def extract_insist_reason(message_text: str, state: WorkflowState) -> Optional[str]:
    """Extract the reason why client insists on this room."""
    # Note: state parameter kept for API compatibility but not currently used
    _ = state  # Suppress unused warning
    if not message_text or len(message_text) < 10:
        return None

    generic_patterns = ["yes", "ok", "okay", "sure", "proceed", "continue"]
    text_lower = message_text.lower().strip()
    if text_lower in generic_patterns:
        return None

    return message_text


def is_generic_question(message_lower: str) -> bool:
    """Check if message is a generic question rather than a reason."""
    question_starters = ["what", "when", "where", "how", "why", "can you", "do you"]
    return any(message_lower.strip().startswith(q) for q in question_starters)


# -----------------------------------------------------------------------------
# Main conflict response handler
# -----------------------------------------------------------------------------


def handle_conflict_response(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    conflict_pending: Dict[str, Any],
    thread_id: str,
) -> Optional[GroupResult]:
    """Handle client response to soft conflict warning.

    Args:
        state: Workflow state
        event_entry: Event entry dict
        conflict_pending: The conflict_pending_decision dict from event
        thread_id: Thread identifier for tracing

    Returns:
        GroupResult if handled, None if client hasn't made clear choice
    """
    message_text = _message_text(state) or ""
    message_lower = message_text.lower()

    room_id = conflict_pending.get("room_id")
    event_date = conflict_pending.get("event_date")
    conflict_info = conflict_pending.get("conflict_info") or {}

    wants_alternative = detect_wants_alternative(message_lower, state)
    wants_to_insist = detect_wants_to_insist(message_lower, state)
    has_reason = extract_insist_reason(message_text, state)

    if thread_id:
        trace_marker(
            thread_id,
            "CONFLICT_RESPONSE",
            detail=f"alternative={wants_alternative}, insist={wants_to_insist}, has_reason={bool(has_reason)}",
            data={
                "room_id": room_id,
                "event_date": event_date,
                "message_preview": message_text[:100] if message_text else "",
            },
            owner_step="Step3_Room",
        )

    # Case 1: Client wants alternatives
    if wants_alternative:
        return _handle_conflict_choose_alternative(state, event_entry, conflict_pending, thread_id)

    # Case 2: Client insists WITH reason - escalate to HIL
    if wants_to_insist and has_reason:
        return _handle_conflict_insist_with_reason(
            state, event_entry, conflict_pending, has_reason, thread_id
        )

    # Case 3: Client insists WITHOUT reason - ask for reason
    if wants_to_insist and not has_reason:
        return _handle_conflict_ask_for_reason(state, event_entry, conflict_pending, thread_id)

    # Case 4: Unclear response but has substantive text - treat as reason to insist
    if message_text and len(message_text) > 20 and not is_generic_question(message_lower):
        return _handle_conflict_insist_with_reason(
            state, event_entry, conflict_pending, message_text, thread_id
        )

    # No clear choice - fall through to normal flow
    return None


# -----------------------------------------------------------------------------
# Conflict resolution actions
# -----------------------------------------------------------------------------


def _handle_conflict_choose_alternative(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    conflict_pending: Dict[str, Any],
    thread_id: str,
) -> GroupResult:
    """Handle client choosing to see alternative rooms."""
    event_id: str = str(event_entry.get("event_id") or "")
    conflicted_room = conflict_pending.get("room_id")
    event_date: str = str(conflict_pending.get("event_date") or "")

    # Clear conflict pending state
    event_entry.pop("conflict_pending_decision", None)
    event_entry.pop("has_conflict", None)
    event_entry.pop("conflict_with", None)
    event_entry.pop("conflict_type", None)

    # Get available rooms excluding the conflicted one
    available_rooms = get_available_rooms_on_date(
        state.db, event_id, event_date, exclude_statuses=["confirmed"]
    )
    alternative_rooms = [r for r in available_rooms if r.lower() != (conflicted_room or "").lower()]

    state.extras["persist"] = True
    append_audit_entry(event_entry, 3, 3, "conflict_chose_alternative")

    if thread_id:
        trace_marker(
            thread_id,
            "CONFLICT_ALTERNATIVE",
            detail=f"alternatives={len(alternative_rooms)}",
            data={"conflicted_room": conflicted_room, "alternatives": alternative_rooms},
            owner_step="Step3_Room",
        )

    if alternative_rooms:
        alt_list = ", ".join(alternative_rooms[:5])
        body = (
            f"No problem! Let me show you some alternatives.\n\n"
            f"The following rooms are available on {_format_display_date(event_date)}:\n"
            f"{alt_list}\n\n"
            f"Would you like me to recommend one based on your requirements, or do you have a preference?"
        )
    else:
        body = (
            f"I'm sorry, but all rooms are already reserved for {_format_display_date(event_date)}.\n\n"
            f"Would you like to check a different date? Let me know and I'll find available options."
        )

    body_with_footer = append_footer(
        body,
        step=3,
        next_step="Room selection",
        thread_state="Awaiting Client",
    )

    state.clear_regular_drafts()
    state.add_draft_message({
        "body": body_with_footer,
        "body_markdown": body,
        "step": 3,
        "thread_state": "Awaiting Client",
        "topic": "conflict_alternatives",
        "requires_approval": False,
    })

    return GroupResult(
        action="conflict_chose_alternative",
        payload={
            "client_id": state.client_id,
            "event_id": event_id,
            "conflicted_room": conflicted_room,
            "alternatives": alternative_rooms,
            "draft_messages": state.draft_messages,
        },
        halt=False,
    )


def _handle_conflict_insist_with_reason(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    conflict_pending: Dict[str, Any],
    reason: str,
    thread_id: str,
) -> GroupResult:
    """Handle client insisting on the room with a reason - escalate to HIL."""
    event_id: str = str(event_entry.get("event_id") or "")
    conflict_info: Dict[str, Any] = conflict_pending.get("conflict_info") or {}

    result = handle_hard_conflict(
        db=state.db,
        event_id=event_id,
        conflict_info=conflict_info,
        client_reason=reason,
    )

    event_entry.pop("conflict_pending_decision", None)
    state.extras["persist"] = True
    append_audit_entry(event_entry, 3, 3, "conflict_escalated_to_hil")

    if thread_id:
        trace_marker(
            thread_id,
            "CONFLICT_HIL_CREATED",
            detail=f"task_id={result.get('task_id')}",
            data={"reason_preview": reason[:100]},
            owner_step="Step3_Room",
        )

    body = result.get("message", "I'm reviewing your request and will get back to you shortly.")
    body_with_footer = append_footer(
        body,
        step=3,
        next_step="Awaiting decision",
        thread_state="Waiting on HIL",
    )

    state.clear_regular_drafts()
    state.add_draft_message({
        "body": body_with_footer,
        "body_markdown": body,
        "step": 3,
        "thread_state": "Waiting on HIL",
        "topic": "conflict_hil_pending",
        "requires_approval": False,
    })

    update_event_metadata(event_entry, thread_state="Waiting on HIL")
    state.set_thread_state("Waiting on HIL")

    return GroupResult(
        action="conflict_escalated_to_hil",
        payload={
            "client_id": state.client_id,
            "event_id": event_id,
            "task_id": result.get("task_id"),
            "draft_messages": state.draft_messages,
        },
        halt=False,
    )


def _handle_conflict_ask_for_reason(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    conflict_pending: Dict[str, Any],
    thread_id: str,
) -> GroupResult:
    """Ask client to provide reason for insisting on this room."""
    event_id = event_entry.get("event_id")
    room_id = conflict_pending.get("room_id")
    event_date = conflict_pending.get("event_date")

    if thread_id:
        trace_marker(
            thread_id,
            "CONFLICT_ASK_REASON",
            detail="asking_for_reason",
            owner_step="Step3_Room",
        )

    body = (
        f"I understand you'd like to keep {room_id} for {_format_display_date(event_date)}.\n\n"
        f"Could you share why this specific room is important for your event? "
        f"For example, is it a special occasion like a birthday or anniversary?\n\n"
        f"This will help our manager make a fair decision when reviewing both bookings."
    )

    body_with_footer = append_footer(
        body,
        step=3,
        next_step="Awaiting reason",
        thread_state="Awaiting Client",
    )

    state.clear_regular_drafts()
    state.add_draft_message({
        "body": body_with_footer,
        "body_markdown": body,
        "step": 3,
        "thread_state": "Awaiting Client",
        "topic": "conflict_ask_reason",
        "requires_approval": False,
    })

    state.extras["persist"] = True

    return GroupResult(
        action="conflict_ask_reason",
        payload={
            "client_id": state.client_id,
            "event_id": event_id,
            "room_id": room_id,
            "draft_messages": state.draft_messages,
        },
        halt=False,
    )


# -----------------------------------------------------------------------------
# Alternative dates handling
# -----------------------------------------------------------------------------


def collect_alternative_dates(
    state: WorkflowState,
    preferred_room: Optional[str],
    chosen_date: Optional[str],
    *,
    count: int = 7,
) -> List[str]:
    """Collect alternative dates for room availability."""
    from workflows.common.catalog import list_free_dates

    try:
        alt = list_free_dates(count=count, db=state.db, preferred_room=preferred_room)
    except Exception:
        alt = []

    chosen_iso = _to_iso(chosen_date)
    iso_dates: List[str] = []
    for value in alt:
        label = str(value).strip()
        if not label:
            continue
        candidate_iso = _to_iso(label) or label if len(label) == 10 and label.count("-") == 2 else None
        if not candidate_iso:
            continue
        if chosen_iso and candidate_iso == chosen_iso:
            continue
        if candidate_iso not in iso_dates:
            iso_dates.append(candidate_iso)
    return iso_dates


def merge_alternative_dates(primary: List[str], fallback: List[str]) -> List[str]:
    """Merge two lists of alternative dates, preserving order."""
    combined: List[str] = []
    for source in (primary, fallback):
        for value in source:
            if value and value not in combined:
                combined.append(value)
    return combined


def dedupe_dates(dates: List[str], chosen_date: Optional[str]) -> List[str]:
    """Deduplicate dates and remove the chosen date."""
    result: List[str] = []
    for date in dates:
        if not date:
            continue
        if chosen_date and date == chosen_date:
            continue
        if date not in result:
            result.append(date)
    return result


def format_alternative_dates_section(dates: List[str], more_available: bool) -> str:
    """Format alternative dates as a display section."""
    if not dates and not more_available:
        return "Alternative Dates:\n- Let me know if you'd like me to explore additional dates."
    if not dates:
        return "Alternative Dates:\n- More options are available on request."

    label = "Alternative Dates"
    if len(dates) > 1:
        label = f"Alternative Dates (top {len(dates)})"

    lines = [f"{label}:"]
    for value in dates:
        display = _format_short_date(value)
        lines.append(f"- {display}")
    if more_available:
        lines.append("More options are available on request.")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Backwards compatibility aliases (underscore prefix)
# -----------------------------------------------------------------------------

_handle_conflict_response = handle_conflict_response
_detect_wants_alternative = detect_wants_alternative
_detect_wants_to_insist = detect_wants_to_insist
_extract_insist_reason = extract_insist_reason
_is_generic_question = is_generic_question
_collect_alternative_dates = collect_alternative_dates
_merge_alternative_dates = merge_alternative_dates
_dedupe_dates = dedupe_dates
_format_alternative_dates_section = format_alternative_dates_section


__all__ = [
    # Main handler
    "handle_conflict_response",
    # Detection functions
    "detect_wants_alternative",
    "detect_wants_to_insist",
    "extract_insist_reason",
    "is_generic_question",
    # Alternative dates
    "collect_alternative_dates",
    "merge_alternative_dates",
    "dedupe_dates",
    "format_alternative_dates_section",
    # Utilities (used by handler)
    "_message_text",
    "_to_iso",
    "_format_short_date",
    # Backwards compat aliases
    "_handle_conflict_response",
    "_detect_wants_alternative",
    "_detect_wants_to_insist",
    "_extract_insist_reason",
    "_is_generic_question",
    "_collect_alternative_dates",
    "_merge_alternative_dates",
    "_dedupe_dates",
    "_format_alternative_dates_section",
]
