from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from backend.workflows.common.prompts import append_footer
from backend.workflows.common.requirements import requirements_hash
from backend.workflows.common.room_rules import find_better_room_dates
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import append_audit_entry, load_rooms, update_event_metadata
from backend.debug.hooks import trace_db_read, trace_db_write, trace_detour, trace_gate, trace_state, trace_step
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


@trace_step("Step3_Room")
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

    thread_id = _thread_id(state)
    state.current_step = 3

    date_confirmed_ok = bool(event_entry.get("date_confirmed"))
    trace_gate(thread_id, "Step3_Room", "P1 date_confirmed", date_confirmed_ok, {"date_confirmed": date_confirmed_ok})
    if not date_confirmed_ok:
        return _detour_to_date(state, event_entry)

    requirements = event_entry.get("requirements") or {}
    current_req_hash = event_entry.get("requirements_hash")
    computed_hash = requirements_hash(requirements) if requirements else None
    if computed_hash and computed_hash != current_req_hash:
        update_event_metadata(event_entry, requirements_hash=computed_hash)
        current_req_hash = computed_hash
        state.extras["persist"] = True

    participants = _extract_participants(requirements)

    capacity_shortcut = False
    if state.user_info.get("shortcut_capacity_ok"):
        shortcuts = event_entry.setdefault("shortcuts", {})
        if not shortcuts.get("capacity_ok"):
            shortcuts["capacity_ok"] = True
            state.extras["persist"] = True
        capacity_shortcut = True
    if not capacity_shortcut:
        capacity_shortcut = bool((event_entry.get("shortcuts") or {}).get("capacity_ok"))

    capacity_ok = participants is not None or capacity_shortcut
    trace_gate(
        thread_id,
        "Step3_Room",
        "P3 capacity_present",
        capacity_ok,
        {"participants": participants, "capacity_shortcut": capacity_shortcut},
    )
    if not capacity_ok:
        return _detour_for_capacity(state, event_entry)

    hil_step = state.user_info.get("hil_approve_step")
    if hil_step == 3:
        decision = state.user_info.get("hil_decision") or "approve"
        return _apply_hil_decision(state, event_entry, decision)

    chosen_date = event_entry.get("chosen_date")
    if not chosen_date:
        return _detour_to_date(state, event_entry)

    user_requested_room = state.user_info.get("room")
    locked_room_id = event_entry.get("locked_room_id")
    room_eval_hash = event_entry.get("room_eval_hash")

    requirements_changed = current_req_hash != room_eval_hash
    explicit_room_change = bool(user_requested_room and user_requested_room != locked_room_id)
    missing_lock = locked_room_id is None

    eval_needed = missing_lock or explicit_room_change or requirements_changed
    trace_gate(
        thread_id,
        "Step3_Room",
        "room_eval_needed",
        eval_needed,
        {
            "missing_lock": missing_lock,
            "explicit_room_change": explicit_room_change,
            "requirements_changed": requirements_changed,
        },
    )
    if not eval_needed:
        return _skip_room_evaluation(state, event_entry)

    room_statuses = evaluate_room_statuses(state.db, chosen_date)
    trace_db_read(
        thread_id,
        "Step3_Room",
        "db.rooms.search",
        {"date": chosen_date, "rooms": len(room_statuses)},
    )
    summary = summarize_room_statuses(room_statuses)
    status_map = _flatten_statuses(room_statuses)

    preferred_room = _preferred_room(event_entry, user_requested_room)
    selected_room, selected_status = _select_room(preferred_room, status_map)

    outcome = selected_status or ROOM_OUTCOME_UNAVAILABLE
    skip_capacity_prompt = bool(capacity_shortcut)

    summary_text = _compose_outcome_message(
        outcome,
        selected_room,
        chosen_date,
        requirements,
        skip_capacity_prompt=skip_capacity_prompt,
    )

    wish_products = _collect_wish_products(event_entry)
    table_rows, actions = _build_room_menu_rows(
        chosen_date,
        status_map,
        selected_room,
        wish_products,
    )
    actions = actions[:5]

    alt_dates: List[str] = []
    if _needs_better_room_alternatives(state.user_info, status_map, event_entry):
        alt_dates = find_better_room_dates(event_entry)
    guidance_line = (
        "I've summarised the best room/menu pairings below. Please choose one so I can queue it for approval."
        if actions
        else "I've listed the room status overview below. Let me know if you'd like me to look at other dates."
    )
    body_lines = [summary_text, guidance_line]
    if alt_dates:
        body_lines.append("If you'd like more space, these alternative dates keep larger rooms open.")
    body_text = "\n\n".join(line for line in body_lines if line)
    body_with_footer = append_footer(
        body_text,
        step=3,
        next_step="Choose a room",
        thread_state="Awaiting Client",
    )

    outcome_topic = {
        ROOM_OUTCOME_AVAILABLE: "room_available",
        ROOM_OUTCOME_OPTION: "room_option",
        ROOM_OUTCOME_UNAVAILABLE: "room_unavailable",
    }[outcome]

    table_blocks: List[Dict[str, Any]] = []
    if table_rows:
        table_blocks.append(
            {
                "type": "room_menu",
                "label": "Room & menu options",
                "rows": table_rows,
            }
        )
    if alt_dates:
        table_blocks.append(
            {
                "type": "dates",
                "label": "Alternative dates",
                "rows": [{"date": value} for value in alt_dates],
            }
        )

    draft_message = {
        "body": body_with_footer,
        "step": 3,
        "next_step": "Choose a room",
        "thread_state": "Awaiting Client",
        "topic": outcome_topic,
        "room": selected_room,
        "status": outcome,
        "table_blocks": table_blocks,
        "actions": actions[:5],
    }
    if alt_dates:
        draft_message["alt_dates_for_better_room"] = alt_dates
    state.add_draft_message(draft_message)

    event_entry["room_pending_decision"] = {
        "selected_room": selected_room,
        "selected_status": outcome,
        "requirements_hash": current_req_hash,
        "summary": summary,
        "menu": table_rows[0]["menu"] if table_rows else None,
        "wish_products": wish_products,
    }

    update_event_metadata(
        event_entry,
        thread_state="Awaiting Client",
        current_step=3,
    )
    trace_db_write(
        thread_id,
        "Step3_Room",
        "db.events.update_room",
        {"selected_room": selected_room, "status": outcome},
    )

    state.set_thread_state("Awaiting Client")
    state.caller_step = event_entry.get("caller_step")
    state.current_step = 3
    state.extras["persist"] = True

    trace_state(
        thread_id,
        "Step3_Room",
        {
            "selected_room": selected_room,
            "status": outcome,
            "eval_hash": current_req_hash,
            "room_eval_hash": event_entry.get("room_eval_hash"),
            "requirements_hash": event_entry.get("requirements_hash") or current_req_hash,
            "locked_room_id": event_entry.get("locked_room_id"),
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "rooms": room_statuses,
        "summary": summary,
        "selected_room": selected_room,
        "selected_status": outcome,
        "room_menu_rows": table_rows,
        "wish_products": wish_products,
        "actions": actions,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
    }
    if alt_dates:
        payload["alt_dates_for_better_room"] = alt_dates
    if skip_capacity_prompt:
        payload["shortcut_capacity_ok"] = True
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

    trace_detour(
        _thread_id(state),
        "Step3_Room",
        "Step2_Date",
        "date_confirmed_missing",
        {"date_confirmed": event_entry.get("date_confirmed")},
    )
    if event_entry.get("caller_step") is None:
        update_event_metadata(event_entry, caller_step=3)
    update_event_metadata(
        event_entry,
        current_step=2,
        date_confirmed=False,
        thread_state="Awaiting Client",
    )
    append_audit_entry(event_entry, 3, 2, "room_requires_confirmed_date")
    state.current_step = 2
    state.caller_step = 3
    state.set_thread_state("Awaiting Client")
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


def _detour_for_capacity(state: WorkflowState, event_entry: dict) -> GroupResult:
    """[Trigger] Redirect to Step 1 when attendee count is missing."""

    trace_detour(
        _thread_id(state),
        "Step3_Room",
        "Step1_Intake",
        "capacity_missing",
        {},
    )
    if event_entry.get("caller_step") is None:
        update_event_metadata(event_entry, caller_step=3)
    update_event_metadata(
        event_entry,
        current_step=1,
        thread_state="Awaiting Client",
    )
    append_audit_entry(event_entry, 3, 1, "room_requires_capacity")
    state.current_step = 1
    state.caller_step = 3
    state.set_thread_state("Awaiting Client")
    state.extras["persist"] = True
    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "reason": "capacity_missing",
        "context": state.context_snapshot,
        "persisted": True,
    }
    return GroupResult(action="room_detour_capacity", payload=payload, halt=False)


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

    update_event_metadata(
        event_entry,
        locked_room_id=selected_room,
        room_eval_hash=requirements_hash,
        current_step=4,
        thread_state="Waiting on HIL",
    )
    trace_db_write(
        _thread_id(state),
        "Step3_Room",
        "db.events.lock_room",
        {"locked_room_id": selected_room, "room_eval_hash": requirements_hash},
    )
    append_audit_entry(event_entry, 3, 4, "room_hil_approved")
    event_entry.pop("room_pending_decision", None)

    state.current_step = 4
    state.caller_step = None
    state.set_thread_state("Waiting on HIL")
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
    *,
    skip_capacity_prompt: bool = False,
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

    capacity_sentence = ""
    if not skip_capacity_prompt:
        capacity_sentence = f"It comfortably fits {capacity_text}. "

    if status == ROOM_OUTCOME_AVAILABLE and room_name:
        return (
            f"Good news — {room_name} is available on {chosen_date}. "
            f"{capacity_sentence}"
            "Shall we proceed with this room and date?"
        ).replace("  ", " ").strip()

    if status == ROOM_OUTCOME_OPTION and room_name:
        return (
            f"{room_name} is currently on option for {chosen_date}. "
            f"{capacity_sentence}"
            "We can proceed under this option or consider other dates/rooms — what would you prefer?"
        ).replace("  ", " ").strip()

    capacity_clause = f" for {capacity_text}" if not skip_capacity_prompt else ""
    return (
        f"Thanks for your request. Unfortunately, no suitable room is available on {chosen_date}{capacity_clause}. "
        "Would one of these alternative dates work, or would you like to adjust the attendee count or layout?"
    ).strip()


def _extract_participants(requirements: Dict[str, Any]) -> Optional[int]:
    raw = requirements.get("number_of_participants")
    if raw in (None, "", "Not specified", "none"):
        raw = requirements.get("participants")
    if raw in (None, "", "Not specified", "none"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _collect_wish_products(event_entry: Dict[str, Any]) -> List[str]:
    wish_products = event_entry.get("wish_products") or []
    result: List[str] = []
    for item in wish_products:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _build_room_menu_rows(
    chosen_date: str,
    status_map: Dict[str, str],
    primary_room: Optional[str],
    wish_products: List[str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    for room, status in status_map.items():
        normalized_status = status or "Unknown"
        is_primary = bool(primary_room and room == primary_room)
        row: Dict[str, Any] = {
            "date": chosen_date,
            "room": room,
            "status": normalized_status,
            "menu": _menu_label(wish_products, is_primary),
            "match_score": _match_score(normalized_status, is_primary, wish_products),
        }
        if wish_products:
            row["wish_products"] = wish_products
            row["matches_all_wishes"] = is_primary
        rows.append(row)

    rows.sort(key=lambda entry: (-entry["match_score"], entry["room"]))

    actions: List[Dict[str, Any]] = []
    for row in rows:
        if row["status"] in {ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION}:
            actions.append(
                {
                    "type": "select_room",
                    "label": f"Proceed with {row['room']} ({row['menu']})",
                    "room": row["room"],
                    "date": chosen_date,
                    "menu": row["menu"],
                    "status": row["status"],
                }
            )
    return rows, actions


def _menu_label(wish_products: List[str], is_primary: bool) -> str:
    if not wish_products:
        return "Atelier seasonal menu"
    base = ", ".join(wish_products)
    suffix = " · fully covered" if is_primary else " · may require adjustments"
    return f"{base}{suffix}"


def _match_score(status: str, is_primary: bool, wish_products: List[str]) -> int:
    status_weight = _status_weight(status)
    preference_bonus = len(wish_products) if is_primary else max(len(wish_products) - 1, 0)
    return status_weight * 10 + preference_bonus


def _status_weight(status: str) -> int:
    lookup = {
        ROOM_OUTCOME_AVAILABLE: 3,
        ROOM_OUTCOME_OPTION: 2,
        ROOM_OUTCOME_UNAVAILABLE: 1,
    }
    return lookup.get(status, 0)


def _thread_id(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    message = state.message
    if message and message.msg_id:
        return str(message.msg_id)
    return "unknown-thread"
