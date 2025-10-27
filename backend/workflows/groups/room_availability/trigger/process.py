from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from backend.workflows.common.room_rules import find_better_room_dates
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import append_audit_entry, load_rooms, update_event_metadata
from backend.utils.profiler import profile_step

from ..condition.decide import room_status_on_date
from ..llm.analysis import summarize_room_statuses

__workflow_role__ = "trigger"


ROOM_OUTCOME_UNAVAILABLE = "Unavailable"
ROOM_OUTCOME_AVAILABLE = "Available"
ROOM_OUTCOME_OPTION = "Option"

ROOM_SIZE_ORDER = {
    "Room A": 1,
    "Room B": 2,
    "Room C": 3,
    "Punkt.Null": 4,
}


@profile_step("workflow.step3.room_availability")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Execute Group C — room availability assessment with entry guards and caching."""

    event_entry = state.event_entry
    if not event_entry:
        payload = {
            "client_id": state.client_id,
            "event_id": state.event_id,
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "missing_event_record",
            "context": state.context_snapshot,
        }
        return GroupResult(action="room_eval_missing_event", payload=payload, halt=True)

    state.current_step = 3

    hil_step = state.user_info.get("hil_approve_step")
    if hil_step == 3:
        decision = state.user_info.get("hil_decision") or "approve"
        return _apply_hil_decision(state, event_entry, decision)

    chosen_date = event_entry.get("chosen_date")
    if not chosen_date:
        return _detour_to_date(state, event_entry)

    user_requested_room = state.user_info.get("room")
    locked_room_id = event_entry.get("locked_room_id")
    current_req_hash = event_entry.get("requirements_hash")
    room_eval_hash = event_entry.get("room_eval_hash")

    requirements_changed = bool(current_req_hash and current_req_hash != room_eval_hash)
    explicit_room_change = bool(user_requested_room and user_requested_room != locked_room_id)
    missing_lock = locked_room_id is None

    if not (missing_lock or explicit_room_change or requirements_changed):
        return _skip_room_evaluation(state, event_entry)

    room_statuses = evaluate_room_statuses(state.db, chosen_date)
    summary = summarize_room_statuses(room_statuses)
    status_map = _flatten_statuses(room_statuses)

    preferred_room = _preferred_room(event_entry, user_requested_room)
    selected_room, selected_status = _select_room(preferred_room, status_map)
    requirements = event_entry.get("requirements") or {}

    outcome = selected_status or ROOM_OUTCOME_UNAVAILABLE
    draft_text = _compose_outcome_message(
        outcome,
        selected_room,
        chosen_date,
        requirements,
    )

    alt_dates: List[str] = []
    if _needs_better_room_alternatives(state.user_info, status_map, event_entry):
        alt_dates = find_better_room_dates(event_entry)
        if alt_dates:
            draft_text = _append_alt_dates(draft_text, alt_dates)

    outcome_topic = {
        ROOM_OUTCOME_AVAILABLE: "room_available",
        ROOM_OUTCOME_OPTION: "room_option",
        ROOM_OUTCOME_UNAVAILABLE: "room_unavailable",
    }[outcome]

    draft_message = {
        "body": draft_text,
        "step": 3,
        "topic": outcome_topic,
        "room": selected_room,
        "status": outcome,
    }
    if alt_dates:
        draft_message["alt_dates_for_better_room"] = alt_dates
    state.add_draft_message(draft_message)

    event_entry["room_pending_decision"] = {
        "selected_room": selected_room,
        "selected_status": outcome,
        "requirements_hash": current_req_hash,
        "summary": summary,
    }

    update_event_metadata(
        event_entry,
        thread_state="Awaiting Client Response",
        current_step=3,
    )

    state.set_thread_state("Awaiting Client Response")
    state.caller_step = event_entry.get("caller_step")
    state.current_step = 3
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "rooms": room_statuses,
        "summary": summary,
        "selected_room": selected_room,
        "selected_status": outcome,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    if alt_dates:
        payload["alt_dates_for_better_room"] = alt_dates
    return GroupResult(action="room_avail_result", payload=payload, halt=True)


def evaluate_room_statuses(db: Dict[str, Any], target_date: str | None) -> List[Dict[str, str]]:
    """[Trigger] Evaluate each configured room for the requested event date."""

    rooms = load_rooms()
    statuses: List[Dict[str, str]] = []
    for room_name in rooms:
        status = room_status_on_date(db, target_date, room_name)
        statuses.append({room_name: status})
    return statuses


def _detour_to_date(state: WorkflowState, event_entry: dict) -> GroupResult:
    """[Trigger] Redirect to Step 2 when no chosen date exists."""

    if event_entry.get("caller_step") is None:
        update_event_metadata(event_entry, caller_step=3)
    update_event_metadata(
        event_entry,
        current_step=2,
        date_confirmed=False,
        thread_state="Awaiting Client Response",
    )
    append_audit_entry(event_entry, 3, 2, "room_requires_confirmed_date")
    state.current_step = 2
    state.caller_step = 3
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "reason": "date_missing",
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="room_detour_date", payload=payload, halt=False)


def _skip_room_evaluation(state: WorkflowState, event_entry: dict) -> GroupResult:
    """[Trigger] Skip Step 3 and return to the caller when caching allows."""

    caller = event_entry.get("caller_step")
    if caller is not None:
        append_audit_entry(event_entry, 3, caller, "room_eval_cache_hit")
        update_event_metadata(event_entry, current_step=caller, caller_step=None)
        state.current_step = caller
        state.caller_step = None
    else:
        state.current_step = event_entry.get("current_step")
    state.extras["persist"] = True
    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "cached": True,
        "thread_state": event_entry.get("thread_state"),
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="room_eval_skipped", payload=payload, halt=False)


def _preferred_room(event_entry: dict, user_requested_room: Optional[str]) -> Optional[str]:
    """[Trigger] Determine the preferred room priority."""

    if user_requested_room:
        return user_requested_room
    requirements = event_entry.get("requirements") or {}
    preferred_room = requirements.get("preferred_room")
    if preferred_room:
        return preferred_room
    return event_entry.get("locked_room_id")


def _flatten_statuses(statuses: List[Dict[str, str]]) -> Dict[str, str]:
    """[Trigger] Convert list of {room: status} mappings into a single dict."""

    result: Dict[str, str] = {}
    for entry in statuses:
        result.update(entry)
    return result


def _select_room(preferred_room: Optional[str], status_map: Dict[str, str]) -> Tuple[Optional[str], Optional[str]]:
    """[Trigger] Choose the best room candidate based on availability."""

    if preferred_room:
        status = status_map.get(preferred_room)
        if status and status != "Confirmed":
            return preferred_room, status

    for room, status in status_map.items():
        if status == ROOM_OUTCOME_AVAILABLE:
            return room, status

    for room, status in status_map.items():
        if status == ROOM_OUTCOME_OPTION:
            return room, status

    return None, None


def _apply_hil_decision(state: WorkflowState, event_entry: Dict[str, Any], decision: str) -> GroupResult:
    """Handle HIL approval or rejection for the latest room evaluation."""

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
        update_event_metadata(event_entry, current_step=3, thread_state="Awaiting Client Response")
        state.set_thread_state("Awaiting Client Response")
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

    update_event_metadata(
        event_entry,
        locked_room_id=selected_room,
        room_eval_hash=requirements_hash,
        current_step=4,
        thread_state="In Progress",
    )
    append_audit_entry(event_entry, 3, 4, "room_hil_approved")
    event_entry.pop("room_pending_decision", None)

    state.current_step = 4
    state.caller_step = None
    state.set_thread_state("In Progress")
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


def _needs_better_room_alternatives(
    user_info: Dict[str, Any],
    status_map: Dict[str, str],
    event_entry: Dict[str, Any],
) -> bool:
    if (user_info or {}).get("room_feedback") != "not_good_enough":
        return False

    requirements = event_entry.get("requirements") or {}
    baseline_room = event_entry.get("locked_room_id") or requirements.get("preferred_room")
    baseline_rank = ROOM_SIZE_ORDER.get(str(baseline_room), 0)
    if baseline_rank == 0:
        return True

    larger_available = False
    for room_name, status in status_map.items():
        if ROOM_SIZE_ORDER.get(room_name, 0) > baseline_rank and status == ROOM_OUTCOME_AVAILABLE:
            larger_available = True
            break

    if not larger_available:
        return True

    participants = (requirements.get("number_of_participants") or 0)
    participants_val: Optional[int]
    try:
        participants_val = int(participants)
    except (TypeError, ValueError):
        participants_val = None

    capacity_map = {
        1: 36,
        2: 54,
        3: 96,
        4: 140,
    }
    if participants_val is not None:
        baseline_capacity = capacity_map.get(baseline_rank)
        if baseline_capacity and participants_val > baseline_capacity:
            return True

    return False


def _append_alt_dates(message: str, alt_dates: List[str]) -> str:
    if not alt_dates:
        return message
    lines = [message.rstrip(), "", "Here are a few alternative dates with larger rooms available:"]
    lines.extend(f"- {date}" for date in alt_dates)
    return "\n".join(lines)


def _compose_outcome_message(
    status: str,
    room_name: Optional[str],
    chosen_date: str,
    requirements: Dict[str, Any],
) -> str:
    """[Trigger] Build the draft message for the selected outcome."""

    participants = requirements.get("number_of_participants")
    layout = requirements.get("seating_layout")

    if participants and layout:
        capacity_text = f"{participants} guests in {layout}"
    elif participants:
        capacity_text = f"{participants} guests"
    elif layout:
        capacity_text = f"a {layout} layout"
    else:
        capacity_text = "your requirements"

    if status == ROOM_OUTCOME_AVAILABLE and room_name:
        return (
            f"Good news — {room_name} is available on {chosen_date}. "
            f"It comfortably fits {capacity_text}. "
            "Shall we proceed with this room and date?"
        )

    if status == ROOM_OUTCOME_OPTION and room_name:
        return (
            f"{room_name} is currently on option for {chosen_date}. "
            f"It comfortably fits {capacity_text}. "
            "We can proceed under this option or consider other dates/rooms — what would you prefer?"
        )

    return (
        f"Thanks for your request. Unfortunately, no suitable room is available on {chosen_date} for {capacity_text}. "
        "Would one of these alternative dates work, or would you like to adjust the attendee count or layout?"
    )
