from __future__ import annotations

import os
from datetime import datetime, time
from typing import Any, Dict, Optional, Tuple

from backend.workflows.common.prompts import append_footer
from backend.workflows.common.requirements import build_requirements, merge_client_profile, requirements_hash
from backend.workflows.common.timeutils import format_ts_to_ddmmyyyy, format_iso_date_to_ddmmyyyy
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.change_propagation import detect_change_type, route_change_on_updated_variable
import json

from backend.domain import IntentLabel
from backend.debug.hooks import (
    trace_db_write,
    trace_entity,
    trace_marker,
    trace_prompt_in,
    trace_prompt_out,
    trace_state,
    trace_step,
)
from backend.workflows.io.database import (
    append_history,
    append_audit_entry,
    context_snapshot,
    create_event_entry,
    default_event_record,
    find_event_idx_by_id,
    last_event_for_email,
    load_rooms,
    tag_message,
    update_event_entry,
    update_event_metadata,
    upsert_client,
)

from ..db_pers.tasks import enqueue_manual_review_task
from ..condition.checks import is_event_request
import re
from ..llm.analysis import classify_intent, extract_user_information
from backend.workflows.nlu.preferences import extract_preferences
from backend.workflows.groups.room_availability import handle_select_room_action
from ..billing_flow import handle_billing_capture
from backend.workflows.common.datetime_parse import parse_first_date, parse_time_range

__workflow_role__ = "trigger"


def _needs_vague_date_confirmation(user_info: Dict[str, Any]) -> bool:
    explicit_date = bool(user_info.get("event_date") or user_info.get("date"))
    vague_tokens = any(
        bool(user_info.get(key))
        for key in ("range_query_detected", "vague_month", "vague_weekday", "vague_time_of_day")
    )
    return vague_tokens and not explicit_date


def _initial_intent_detail(intent: IntentLabel) -> str:
    if intent == IntentLabel.EVENT_REQUEST:
        return "event_intake"
    if intent == IntentLabel.NON_EVENT:
        return "non_event"
    return intent.value


def _has_same_turn_shortcut(user_info: Dict[str, Any]) -> bool:
    participants = user_info.get("participants") or user_info.get("number_of_participants")
    date_value = user_info.get("date") or user_info.get("event_date")
    return bool(participants and date_value)


_DATE_TOKEN = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b")
_MONTH_TOKENS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_AFFIRMATIVE_TOKENS = (
    "ok",
    "okay",
    "great",
    "sounds good",
    "lets do",
    "let's do",
    "we'll take",
    "lock",
    "confirm",
    "go with",
    "works",
    "take",
)

def _fallback_year_from_ts(ts: Optional[str]) -> int:
    if not ts:
        return datetime.utcnow().year
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).year
    except ValueError:
        return datetime.utcnow().year


def _extract_confirmation_details(text: str, fallback_year: int) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    parsed = parse_first_date(text, fallback_year=fallback_year)
    iso_date = parsed.isoformat() if parsed else None
    start, end, _ = parse_time_range(text)

    def _fmt(value: Optional[time]) -> Optional[str]:
        if not value:
            return None
        return f"{value.hour:02d}:{value.minute:02d}"

    return iso_date, _fmt(start), _fmt(end)

def _looks_like_gate_confirmation(message_text: str, linked_event: Optional[Dict[str, Any]]) -> bool:
    if not linked_event:
        return False
    if linked_event.get("current_step") != 2:
        return False
    thread_state = (linked_event.get("thread_state") or "").lower()
    if thread_state not in {"awaiting client", "awaiting client response", "waiting on hil"}:
        return False

    text = (message_text or "").strip()
    if not text:
        return False
    lowered = text.lower()

    has_date_token = bool(_DATE_TOKEN.search(lowered))
    if not has_date_token:
        # handle formats like "07 feb" or "7 february"
        month_hit = any(token in lowered for token in _MONTH_TOKENS)
        day_hit = any(str(day) in lowered for day in range(1, 32))
        has_date_token = month_hit and day_hit

    if not has_date_token:
        return False

    if any(token in lowered for token in _AFFIRMATIVE_TOKENS):
        return True

    # plain date replies like "07.02.2026" or "2026-02-07"
    stripped_digits = lowered.replace(" ", "")
    if stripped_digits.replace(".", "").replace("-", "").replace("/", "").isdigit():
        return True

    # short replies with date plus punctuation
    if len(lowered.split()) <= 6 and has_date_token:
        return True

    return False


def _normalize_room_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _detect_room_choice(message_text: str, linked_event: Optional[Dict[str, Any]]) -> Optional[str]:
    if not message_text or not linked_event:
        return None
    try:
        current_step = int(linked_event.get("current_step") or 0)
    except (TypeError, ValueError):
        current_step = 0
    if current_step != 3:
        return None

    rooms = load_rooms()
    if not rooms:
        return None

    text = message_text.strip()
    if not text:
        return None
    lowered = text.lower()
    condensed = _normalize_room_token(text)

    # direct match against known room labels
    for room in rooms:
        room_lower = room.lower()
        if room_lower in lowered:
            return room
        if _normalize_room_token(room) and _normalize_room_token(room) == condensed:
            return room

    # pattern like "room a" or "room-a"
    match = re.search(r"\broom\s*([a-z0-9]+)\b", lowered)
    if match:
        token = match.group(1)
        token_norm = _normalize_room_token(token)
        for room in rooms:
            room_tokens = room.split()
            if room_tokens:
                last_token = _normalize_room_token(room_tokens[-1])
                if token_norm and token_norm == last_token:
                    return room

    # single token equals last token of room name (e.g., "A")
    if len(lowered.split()) == 1:
        token_norm = condensed
        if token_norm:
            for room in rooms:
                last_token = _normalize_room_token(room.split()[-1])
                if token_norm == last_token:
                    return room

    return None


@trace_step("Step1_Intake")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Entry point for Group A — intake and data capture."""

    message_payload = state.message.to_payload()
    thread_id = _thread_id(state)
    owner_step = "Step1_Intake"
    trace_marker(
        thread_id,
        "TRIGGER_Intake",
        detail=message_payload.get("subject"),
        data={"msg_id": state.message.msg_id},
        owner_step=owner_step,
    )
    prompt_payload = (
        f"Subject: {message_payload.get('subject') or ''}\n"
        f"Body:\n{message_payload.get('body') or ''}"
    )
    trace_prompt_in(thread_id, owner_step, "classify_intent", prompt_payload)
    intent, confidence = classify_intent(message_payload)
    trace_prompt_out(
        thread_id,
        owner_step,
        "classify_intent",
        json.dumps({"intent": intent.value, "confidence": round(confidence, 3)}, ensure_ascii=False),
        outputs={"intent": intent.value, "confidence": round(confidence, 3)},
    )
    trace_marker(
        thread_id,
        "AGENT_CLASSIFY",
        detail=intent.value,
        data={"confidence": round(confidence, 3)},
        owner_step=owner_step,
    )
    state.intent = intent
    state.confidence = confidence
    state.intent_detail = _initial_intent_detail(intent)

    trace_prompt_in(thread_id, owner_step, "extract_user_information", prompt_payload)
    user_info = extract_user_information(message_payload)
    trace_prompt_out(
        thread_id,
        owner_step,
        "extract_user_information",
        json.dumps(user_info, ensure_ascii=False),
        outputs=user_info,
    )
    needs_vague_date_confirmation = _needs_vague_date_confirmation(user_info)
    if needs_vague_date_confirmation:
        user_info.pop("event_date", None)
        user_info.pop("date", None)
    preferences = extract_preferences(user_info)
    if preferences:
        user_info["preferences"] = preferences
    state.user_info = user_info
    if intent == IntentLabel.EVENT_REQUEST and _has_same_turn_shortcut(user_info):
        state.intent_detail = "event_intake_shortcut"
        state.extras["shortcut_detected"] = True
        state.record_subloop("shortcut")
    _trace_user_entities(state, message_payload, user_info)

    client = upsert_client(
        state.db,
        message_payload.get("from_email", ""),
        message_payload.get("from_name"),
    )
    state.client = client
    state.client_id = (message_payload.get("from_email") or "").lower()
    linked_event = last_event_for_email(state.db, state.client_id)
    append_history(client, message_payload, intent.value, confidence, user_info)

    context = context_snapshot(state.db, client, state.client_id)
    state.record_context(context)

    if not is_event_request(intent) or confidence < 0.85:
        body_text = message_payload.get("body") or ""
        if _looks_like_gate_confirmation(body_text, linked_event):
            intent = IntentLabel.EVENT_REQUEST
            confidence = max(confidence, 0.95)
            state.intent = intent
            state.confidence = confidence
            state.intent_detail = "event_intake_followup"
            fallback_year = _fallback_year_from_ts(message_payload.get("ts"))
            iso_date, start_time, end_time = _extract_confirmation_details(body_text, fallback_year)
            if iso_date:
                user_info["date"] = iso_date
                user_info["event_date"] = format_iso_date_to_ddmmyyyy(iso_date)
            if start_time:
                user_info["start_time"] = start_time
            if end_time:
                user_info["end_time"] = end_time
        else:
            room_choice = _detect_room_choice(body_text, linked_event)
            if room_choice:
                intent = IntentLabel.EVENT_REQUEST
                confidence = max(confidence, 0.96)
                state.intent = intent
                state.confidence = confidence
                state.intent_detail = "event_intake_room_choice"
                user_info["room"] = room_choice
                state.extras["room_choice_selected"] = room_choice
            else:
                trace_marker(
                    thread_id,
                    "CONDITIONAL_HIL",
                    detail="manual_review_required",
                    data={"intent": intent.value, "confidence": round(confidence, 3)},
                    owner_step=owner_step,
                )
                linked_event_id = linked_event.get("event_id") if linked_event else None
                task_payload: Dict[str, Any] = {
                    "subject": message_payload.get("subject"),
                    "snippet": (message_payload.get("body") or "")[:200],
                    "ts": message_payload.get("ts"),
                    "reason": "manual_review_required",
                    "thread_id": thread_id,
                }
                task_id = enqueue_manual_review_task(
                    state.db,
                    state.client_id,
                    linked_event_id,
                    task_payload,
                )
                state.extras.update({"task_id": task_id, "persist": True})
                clarification = (
                    "Thanks for your message. A member of our team will review it shortly "
                    "to make sure it reaches the right place."
                )
                clarification = append_footer(
                    clarification,
                    step=1,
                    next_step="Team review (HIL)",
                    thread_state="Waiting on HIL",
                )
                state.add_draft_message(
                    {
                        "body": clarification,
                        "step": 1,
                        "topic": "manual_review",
                    }
                )
                state.set_thread_state("Waiting on HIL")
                if os.getenv("OE_DEBUG") == "1":
                    print(
                        "[DEBUG] manual_review_enqueued:",
                        f"conf={confidence:.2f}",
                        f"parsed_date={user_info.get('date')}",
                        f"intent={intent.value}",
                    )
                payload = {
                    "client_id": state.client_id,
                    "event_id": linked_event_id,
                    "intent": intent.value,
                    "confidence": round(confidence, 3),
                    "persisted": True,
                    "task_id": task_id,
                    "user_info": user_info,
                    "context": context,
                    "draft_messages": state.draft_messages,
                    "thread_state": state.thread_state,
                }
                return GroupResult(action="manual_review_enqueued", payload=payload, halt=True)

    event_entry = _ensure_event_record(state, message_payload, user_info)
    if merge_client_profile(event_entry, user_info):
        state.extras["persist"] = True
    handle_billing_capture(state, event_entry)
    state.event_entry = event_entry
    state.event_id = event_entry["event_id"]
    state.current_step = event_entry.get("current_step")
    state.caller_step = event_entry.get("caller_step")
    state.thread_state = event_entry.get("thread_state")

    requirements_snapshot = event_entry.get("requirements") or {}
    if not user_info.get("participants") and requirements_snapshot.get("number_of_participants"):
        user_info["participants"] = requirements_snapshot.get("number_of_participants")

    requirements = build_requirements(user_info)
    new_req_hash = requirements_hash(requirements)
    prev_req_hash = event_entry.get("requirements_hash")
    update_event_metadata(
        event_entry,
        requirements=requirements,
        requirements_hash=new_req_hash,
    )

    preferences = user_info.get("preferences") or {}
    wish_products = list((preferences.get("wish_products") or []))
    vague_month = user_info.get("vague_month")
    vague_weekday = user_info.get("vague_weekday")
    vague_time = user_info.get("vague_time_of_day")
    week_index = user_info.get("week_index")
    weekdays_hint = user_info.get("weekdays_hint")
    window_scope = user_info.get("window") if isinstance(user_info.get("window"), dict) else None
    metadata_updates: Dict[str, Any] = {}
    if wish_products:
        metadata_updates["wish_products"] = wish_products
    if preferences:
        metadata_updates["preferences"] = preferences
    if vague_month:
        metadata_updates["vague_month"] = vague_month
    if vague_weekday:
        metadata_updates["vague_weekday"] = vague_weekday
    if vague_time:
        metadata_updates["vague_time_of_day"] = vague_time
    if week_index:
        metadata_updates["week_index"] = week_index
    if weekdays_hint:
        metadata_updates["weekdays_hint"] = list(weekdays_hint) if isinstance(weekdays_hint, (list, tuple, set)) else weekdays_hint
    if window_scope:
        metadata_updates["window_scope"] = {
            key: value
            for key, value in window_scope.items()
            if key in {"month", "week_index", "weekdays_hint"}
        }
    if metadata_updates:
        update_event_metadata(event_entry, **metadata_updates)

    room_choice_selected = state.extras.pop("room_choice_selected", None)
    if room_choice_selected:
        pending_info = event_entry.get("room_pending_decision") or {}
        selected_status = None
        if isinstance(pending_info, dict) and pending_info.get("selected_room") == room_choice_selected:
            selected_status = pending_info.get("selected_status")
        status_value = selected_status or "Available"
        chosen_date = (
            event_entry.get("chosen_date")
            or user_info.get("event_date")
            or user_info.get("date")
        )
        return handle_select_room_action(
            state,
            room=room_choice_selected,
            status=status_value,
            date=chosen_date,
        )

    new_preferred_room = requirements.get("preferred_room")

    new_date = user_info.get("event_date")
    previous_step = state.current_step or 1
    detoured_to_step2 = False

    # Use centralized change propagation system for systematic change detection and routing
    message_text = (state.message.subject or "") + "\n" + (state.message.body or "")
    change_type = detect_change_type(event_entry, user_info, message_text=message_text)

    if needs_vague_date_confirmation:
        event_entry["range_query_detected"] = True
        update_event_metadata(
            event_entry,
            chosen_date=None,
            date_confirmed=False,
            current_step=2,
            room_eval_hash=None,
            locked_room_id=None,
            thread_state="Awaiting Client Response",
        )
        event_entry.setdefault("event_data", {})["Event Date"] = "Not specified"
        append_audit_entry(event_entry, previous_step, 2, "date_pending_vague_request")
        detoured_to_step2 = True
        state.set_thread_state("Awaiting Client Response")

    # Handle change routing using DAG-based change propagation
    if change_type is not None and previous_step > 1:
        decision = route_change_on_updated_variable(event_entry, change_type, from_step=previous_step)

        # Apply the routing decision
        if decision.updated_caller_step is not None and event_entry.get("caller_step") is None:
            update_event_metadata(event_entry, caller_step=decision.updated_caller_step)
            trace_marker(
                _thread_id(state),
                "CHANGE_DETECTED",
                detail=f"change_type={change_type.value}",
                data={
                    "change_type": change_type.value,
                    "from_step": previous_step,
                    "to_step": decision.next_step,
                    "caller_step": decision.updated_caller_step,
                },
                owner_step="Step1_Intake",
            )

        if decision.next_step != previous_step:
            update_event_metadata(event_entry, current_step=decision.next_step)
            audit_reason = f"{change_type.value}_change_detected"
            append_audit_entry(event_entry, previous_step, decision.next_step, audit_reason)

            # Clear room lock for date/requirements changes
            if change_type.value in ("date", "requirements") and decision.next_step in (2, 3):
                if decision.next_step == 2:
                    update_event_metadata(
                        event_entry,
                        date_confirmed=False,
                        room_eval_hash=None,
                        locked_room_id=None,
                    )
                    detoured_to_step2 = True

    # Fallback: legacy logic for cases not handled by change propagation
    elif new_date and new_date != event_entry.get("chosen_date"):
        if (
            previous_step not in (None, 1, 2)
            and event_entry.get("caller_step") is None
        ):
            update_event_metadata(event_entry, caller_step=previous_step)
        if previous_step <= 1:
            update_event_metadata(
                event_entry,
                chosen_date=new_date,
                date_confirmed=True,
                current_step=3,
                room_eval_hash=None,
                locked_room_id=None,
            )
            event_entry.setdefault("event_data", {})["Event Date"] = new_date
            append_audit_entry(event_entry, previous_step, 3, "date_updated_initial")
            detoured_to_step2 = False
        else:
            update_event_metadata(
                event_entry,
                chosen_date=new_date,
                date_confirmed=False,
                current_step=2,
                room_eval_hash=None,
                locked_room_id=None,
            )
            event_entry.setdefault("event_data", {})["Event Date"] = new_date
            append_audit_entry(event_entry, previous_step, 2, "date_updated")
            detoured_to_step2 = True

    # Handle missing date (initial flow, not a change)
    if needs_vague_date_confirmation:
        new_date = None
    if not new_date and not event_entry.get("chosen_date") and change_type is None:
        update_event_metadata(
            event_entry,
            chosen_date=None,
            date_confirmed=False,
            current_step=2,
            room_eval_hash=None,
            locked_room_id=None,
        )
        event_entry.setdefault("event_data", {})["Event Date"] = "Not specified"
        append_audit_entry(event_entry, previous_step, 2, "date_missing")
        detoured_to_step2 = True

    # Fallback: requirements change detection (legacy)
    if prev_req_hash is not None and prev_req_hash != new_req_hash and not detoured_to_step2 and change_type is None:
        target_step = 3
        if previous_step != target_step and event_entry.get("caller_step") is None:
            update_event_metadata(event_entry, caller_step=previous_step)
            update_event_metadata(event_entry, current_step=target_step)
            append_audit_entry(event_entry, previous_step, target_step, "requirements_updated")

    # Fallback: room change detection (legacy)
    if new_preferred_room and new_preferred_room != event_entry.get("locked_room_id") and change_type is None:
        if not detoured_to_step2:
            prev_step_for_room = event_entry.get("current_step") or previous_step
            if prev_step_for_room != 3 and event_entry.get("caller_step") is None:
                update_event_metadata(event_entry, caller_step=prev_step_for_room)
                update_event_metadata(event_entry, current_step=3)
                append_audit_entry(event_entry, prev_step_for_room, 3, "room_preference_updated")

    tag_message(event_entry, message_payload.get("msg_id"))

    update_event_metadata(event_entry, thread_state="Waiting on HIL")

    state.current_step = event_entry.get("current_step")
    state.caller_step = event_entry.get("caller_step")
    state.thread_state = event_entry.get("thread_state")
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": intent.value,
        "confidence": round(confidence, 3),
        "user_info": user_info,
        "context": context,
        "persisted": True,
        "current_step": event_entry.get("current_step"),
        "caller_step": event_entry.get("caller_step"),
        "thread_state": event_entry.get("thread_state"),
        "draft_messages": state.draft_messages,
    }
    trace_state(
        _thread_id(state),
        "Step1_Intake",
        {
            "requirements_hash": event_entry.get("requirements_hash"),
            "current_step": event_entry.get("current_step"),
            "caller_step": event_entry.get("caller_step"),
            "thread_state": event_entry.get("thread_state"),
        },
    )
    return GroupResult(action="intake_complete", payload=payload)


def _ensure_event_record(
    state: WorkflowState,
    message_payload: Dict[str, Any],
    user_info: Dict[str, Any],
) -> Dict[str, Any]:
    """[Trigger] Create or refresh the event record for the intake step."""

    received_date = format_ts_to_ddmmyyyy(state.message.ts)
    event_data = default_event_record(user_info, message_payload, received_date)

    last_event = last_event_for_email(state.db, state.client_id)
    if not last_event:
        create_event_entry(state.db, event_data)
        event_entry = state.db["events"][-1]
        trace_db_write(_thread_id(state), "Step1_Intake", "db.events.create", {"event_id": event_entry.get("event_id")})
        return event_entry

    idx = find_event_idx_by_id(state.db, last_event["event_id"])
    if idx is None:
        create_event_entry(state.db, event_data)
        event_entry = state.db["events"][-1]
        trace_db_write(_thread_id(state), "Step1_Intake", "db.events.create", {"event_id": event_entry.get("event_id")})
        return event_entry

    state.updated_fields = update_event_entry(state.db, idx, event_data)
    event_entry = state.db["events"][idx]
    trace_db_write(
        _thread_id(state),
        "Step1_Intake",
        "db.events.update",
        {"event_id": event_entry.get("event_id"), "updated": list(state.updated_fields)},
    )
    update_event_metadata(event_entry, status=event_entry.get("status", "Lead"))
    return event_entry


def _trace_user_entities(state: WorkflowState, message_payload: Dict[str, Any], user_info: Dict[str, Any]) -> None:
    thread_id = _thread_id(state)
    if not thread_id:
        return

    email = message_payload.get("from_email")
    owner_step = "Step1_Intake"
    if email:
        trace_entity(thread_id, owner_step, "email", "message_header", True, {"value": email})

    event_date = user_info.get("event_date") or user_info.get("date")
    if event_date:
        trace_entity(thread_id, owner_step, "event_date", "llm", True, {"value": event_date})

    participants = user_info.get("participants") or user_info.get("number_of_participants")
    if participants:
        trace_entity(thread_id, owner_step, "participants", "llm", True, {"value": participants})


def _thread_id(state: WorkflowState) -> str:
    if state.thread_id:
        return str(state.thread_id)
    if state.client_id:
        return str(state.client_id)
    msg_id = state.message.msg_id if state.message else None
    if msg_id:
        return str(msg_id)
    return "unknown-thread"
