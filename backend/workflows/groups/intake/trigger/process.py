from __future__ import annotations

from typing import Any, Dict

from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import (
    append_history,
    context_snapshot,
    last_event_for_email,
    upsert_client,
)

from ..db_pers.tasks import enqueue_manual_review_task, enqueue_missing_event_date_task
from ..condition.checks import has_event_date, is_event_request, suggest_dates
from ..llm.analysis import classify_intent, extract_user_information

__workflow_role__ = "trigger"


def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Entry point for Group A — intake and data capture."""

    message_payload = state.message.to_payload()
    intent, confidence = classify_intent(message_payload)
    state.intent = intent
    state.confidence = confidence

    user_info = extract_user_information(message_payload)
    state.user_info = user_info

    client = upsert_client(
        state.db,
        message_payload.get("from_email", ""),
        message_payload.get("from_name"),
    )
    state.client = client
    state.client_id = (message_payload.get("from_email") or "").lower()
    append_history(client, message_payload, intent.value, confidence, user_info)

    context = context_snapshot(state.db, client, state.client_id)
    state.record_context(context)

    if not is_event_request(intent):
        last_event = last_event_for_email(state.db, state.client_id)
        linked_event_id = last_event.get("event_id") if last_event else None
        task_payload: Dict[str, Any] = {
            "subject": message_payload.get("subject"),
            "snippet": (message_payload.get("body") or "")[:200],
            "ts": message_payload.get("ts"),
            "reason": "not_event",
        }
        task_id = enqueue_manual_review_task(
            state.db,
            state.client_id,
            linked_event_id,
            task_payload,
        )
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
        task_id = enqueue_missing_event_date_task(
            state.db,
            state.client_id,
            linked_event_id,
            task_payload,
        )
        state.extras.update(
            {"task_id": task_id, "suggested_dates": suggestions, "persist": True}
        )
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
