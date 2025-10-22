from __future__ import annotations

from typing import Any, Dict

from backend.workflows.common.requirements import build_requirements, requirements_hash
from backend.workflows.common.timeutils import format_ts_to_ddmmyyyy
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.io.database import (
    append_history,
    append_audit_entry,
    context_snapshot,
    create_event_entry,
    default_event_record,
    find_event_idx_by_id,
    last_event_for_email,
    tag_message,
    update_event_entry,
    update_event_metadata,
    upsert_client,
)

from ..db_pers.tasks import enqueue_manual_review_task
from ..condition.checks import is_event_request
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

    if not is_event_request(intent) or confidence < 0.85:
        linked_event = last_event_for_email(state.db, state.client_id)
        linked_event_id = linked_event.get("event_id") if linked_event else None
        task_payload: Dict[str, Any] = {
            "subject": message_payload.get("subject"),
            "snippet": (message_payload.get("body") or "")[:200],
            "ts": message_payload.get("ts"),
            "reason": "manual_review_required",
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
        state.add_draft_message(
            {
                "body": clarification,
                "step": 1,
                "topic": "manual_review",
            }
        )
        state.set_thread_state("In Progress")
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
    state.event_entry = event_entry
    state.event_id = event_entry["event_id"]
    state.current_step = event_entry.get("current_step")
    state.caller_step = event_entry.get("caller_step")
    state.thread_state = event_entry.get("thread_state")

    requirements = build_requirements(user_info)
    new_req_hash = requirements_hash(requirements)
    prev_req_hash = event_entry.get("requirements_hash")
    update_event_metadata(
        event_entry,
        requirements=requirements,
        requirements_hash=new_req_hash,
    )

    new_preferred_room = requirements.get("preferred_room")

    new_date = user_info.get("event_date")
    previous_step = state.current_step or 1
    detoured_to_step2 = False

    if new_date and new_date != event_entry.get("chosen_date"):
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

    if not new_date and not event_entry.get("chosen_date"):
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

    if prev_req_hash is not None and prev_req_hash != new_req_hash and not detoured_to_step2:
        target_step = 3
        if previous_step != target_step and event_entry.get("caller_step") is None:
            update_event_metadata(event_entry, caller_step=previous_step)
            update_event_metadata(event_entry, current_step=target_step)
            append_audit_entry(event_entry, previous_step, target_step, "requirements_updated")

    if new_preferred_room and new_preferred_room != event_entry.get("locked_room_id"):
        if not detoured_to_step2:
            prev_step_for_room = event_entry.get("current_step") or previous_step
            if prev_step_for_room != 3 and event_entry.get("caller_step") is None:
                update_event_metadata(event_entry, caller_step=prev_step_for_room)
                update_event_metadata(event_entry, current_step=3)
                append_audit_entry(event_entry, prev_step_for_room, 3, "room_preference_updated")

    tag_message(event_entry, message_payload.get("msg_id"))

    update_event_metadata(event_entry, thread_state="In Progress")

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
        return event_entry

    idx = find_event_idx_by_id(state.db, last_event["event_id"])
    if idx is None:
        create_event_entry(state.db, event_data)
        event_entry = state.db["events"][-1]
        return event_entry

    state.updated_fields = update_event_entry(state.db, idx, event_data)
    event_entry = state.db["events"][idx]
    update_event_metadata(event_entry, status=event_entry.get("status", "Lead"))
    return event_entry
