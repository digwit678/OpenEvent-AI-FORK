from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from vocabulary import TaskType

from workflows.common.timeutils import format_ts_to_ddmmyyyy
from workflows.common.types import GroupResult, WorkflowState
from workflows.conditions.checks import has_event_date, is_event_request
from workflows.io.database import append_history, context_snapshot, last_event_for_email, upsert_client
from workflows.io.tasks import enqueue_task
from workflows.llm.adapter import classify_intent, extract_user_information


def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Entry point for Group A — intake and data capture."""

    message_payload = state.message.to_payload()
    intent, confidence = classify_intent(message_payload)
    state.intent = intent
    state.confidence = confidence

    user_info = extract_user_information(message_payload)
    state.user_info = user_info

    client = upsert_client(state.db, message_payload.get("from_email", ""), message_payload.get("from_name"))
    state.client = client
    state.client_id = (message_payload.get("from_email") or "").lower()
    append_history(client, message_payload, intent.value, confidence, user_info)

    context = context_snapshot(state.db, client, state.client_id)
    state.record_context(context)

    if not is_event_request(intent):
        last_event = last_event_for_email(state.db, state.client_id)
        linked_event_id = last_event.get("event_id") if last_event else None
        task_payload = {
            "subject": message_payload.get("subject"),
            "snippet": (message_payload.get("body") or "")[:200],
            "ts": message_payload.get("ts"),
            "reason": "not_event",
        }
        task_id = enqueue_task(state.db, TaskType.MANUAL_REVIEW, state.client_id, linked_event_id, task_payload)
        state.extras.update({"task_id": task_id, "persist": True})
        payload = {
            "client_id": state.client_id,
            "event_id": linked_event_id,
            "intent": intent.value,
            "confidence": round(confidence, 3),
            "updated_fields": [],
            "persisted": True,
            "task_id": task_id,
            "user_info": user_info,
            "context": context,
        }
        return GroupResult(action="manual_review_enqueued", payload=payload, halt=True)

    if not has_event_date(user_info):
        preferred_room = user_info.get("room") or "Not specified"
        suggestions = suggest_dates(
            state.db,
            preferred_room=preferred_room,
            start_from_iso=message_payload.get("ts"),
        )
        last_event = last_event_for_email(state.db, state.client_id)
        linked_event_id = last_event.get("event_id") if last_event else None
        task_payload = {
            "suggested_dates": suggestions,
            "preferred_room": preferred_room,
            "user_info": user_info,
        }
        task_id = enqueue_task(state.db, TaskType.REQUEST_MISSING_EVENT_DATE, state.client_id, linked_event_id, task_payload)
        state.extras.update({"task_id": task_id, "suggested_dates": suggestions, "persist": True})
        payload = {
            "client_id": state.client_id,
            "event_id": linked_event_id,
            "intent": intent.value,
            "confidence": round(confidence, 3),
            "updated_fields": [],
            "persisted": True,
            "task_id": task_id,
            "suggested_dates": suggestions,
            "user_info": user_info,
            "context": context,
        }
        return GroupResult(action="ask_for_date_enqueued", payload=payload, halt=True)

    state.extras["persist"] = True
    payload = {
        "client_id": state.client_id,
        "intent": intent.value,
        "confidence": round(confidence, 3),
        "user_info": user_info,
        "context": context,
        "persisted": True,
    }
    return GroupResult(action="intake_complete", payload=payload)


def suggest_dates(
    db: Dict[str, Any],
    preferred_room: str,
    start_from_iso: Any,
    days_ahead: int = 30,
    max_results: int = 5,
) -> List[str]:
    """[Condition] Offer candidate dates for a preferred room when missing."""

    today = date.today()
    start_date = today
    if start_from_iso:
        try:
            start_dt = datetime.fromisoformat(str(start_from_iso).replace("Z", "+00:00"))
            start_date = start_dt.date()
        except ValueError:
            start_date = today
    if start_date < today:
        start_date = today
    suggestions: List[str] = []
    for offset in range(days_ahead):
        day = start_date + timedelta(days=offset)
        day_ddmmyyyy = day.strftime("%d.%m.%Y")
        status = room_status_on_date(db, day_ddmmyyyy, preferred_room)
        if status == "Available":
            suggestions.append(day_ddmmyyyy)
            if len(suggestions) >= max_results:
                break
    return suggestions


def room_status_on_date(db: Dict[str, Any], date_ddmmyyyy: str, room_name: str) -> str:
    """[Condition] Check existing events on a given date for the same room."""

    if not room_name or room_name == "Not specified":
        return "Available"
    room_lc = room_name.lower()
    status_found = None
    for event in db.get("events", []):
        data = event.get("event_data", {})
        if data.get("Event Date") != date_ddmmyyyy:
            continue
        stored_room = data.get("Preferred Room")
        if not stored_room or stored_room.lower() != room_lc:
            continue
        status = (data.get("Status") or "").lower()
        if status == "confirmed":
            return "Confirmed"
        if status in {"option", "lead"}:
            status_found = "Option"
    return status_found or "Available"
