from __future__ import annotations

import os
from typing import Any, Dict

from backend.domain import IntentLabel
from backend.workflows.common.datetime_parse import to_iso_date
from backend.workflows.common.requirements import build_requirements, merge_client_profile, requirements_hash
from backend.workflows.common.timeutils import format_ts_to_ddmmyyyy
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.common.capture import capture_user_fields
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
from backend.workflows.llm import adapter as llm_adapter

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
    metadata = llm_adapter.last_call_metadata()
    if metadata:
        llm_meta = state.telemetry.setdefault("llm", {})
        adapter_label = metadata.get("adapter")
        if adapter_label:
            llm_meta["adapter"] = adapter_label
        model_name = metadata.get("model")
        if model_name:
            llm_meta["model"] = model_name
        intent_model = metadata.get("intent_model")
        if intent_model and "intent_model" not in llm_meta:
            llm_meta["intent_model"] = intent_model
        entity_model = metadata.get("entity_model")
        if entity_model and "entity_model" not in llm_meta:
            llm_meta["entity_model"] = entity_model
        phase = metadata.get("phase")
        if phase:
            llm_meta["phase"] = phase

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

    needs_manual_review = not is_event_request(intent) or confidence < 0.85
    if needs_manual_review and not _manual_review_disabled():
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
    elif needs_manual_review:
        intent = IntentLabel.EVENT_REQUEST
        state.intent = intent
        confidence = max(confidence, 0.9)
        state.confidence = confidence

    event_entry = _ensure_event_record(state, message_payload, user_info)
    state.event_entry = event_entry
    state.event_id = event_entry["event_id"]
    state.current_step = event_entry.get("current_step")
    state.caller_step = event_entry.get("caller_step")
    state.thread_state = event_entry.get("thread_state")

    capture_user_fields(
        state,
        current_step=event_entry.get("current_step") or 1,
        source=state.message.msg_id,
    )

    if merge_client_profile(event_entry, user_info):
        state.extras["persist"] = True

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

    confirm_intents = {IntentLabel.CONFIRM_DATE, IntentLabel.CONFIRM_DATE_PARTIAL}
    if new_date and new_date != event_entry.get("chosen_date"):
        if state.intent in confirm_intents:
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
        else:
            iso_date = state.user_info.get("date") or to_iso_date(new_date)
            state.extras["delta_date_query"] = iso_date

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
def _manual_review_disabled() -> bool:
    flag = os.getenv("DISABLE_MANUAL_REVIEW_FOR_TESTS")
    if flag is None:
        return False
    return flag.strip().lower() in {"1", "true", "yes", "on"}
