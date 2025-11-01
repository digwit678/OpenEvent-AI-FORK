from __future__ import annotations

import os
from typing import Any, Dict, Optional

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
from backend.services.products import merge_product_requests, normalise_product_payload

from ..db_pers.tasks import enqueue_manual_review_task
from ..condition.checks import is_event_request
from ..llm.analysis import classify_intent, extract_user_information
from backend.workflow.state import WorkflowStep, write_stage

__workflow_role__ = "trigger"


def _log_intake_event(state: WorkflowState, name: str, details: Dict[str, Any]) -> None:
    try:
        entry = {"log": name, **details}
        logs = getattr(state.telemetry, "log_events", None)
        if isinstance(logs, list):
            logs.append(entry)
        else:
            state.telemetry.log_events = [entry]
    except Exception:
        # Never crash the workflow due to diagnostics
        return


def _explicit_room_change_text(text: str) -> bool:
    if not text:
        return False
    t = str(text).lower()
    verbs = ("change", "switch", "different room", "other room", "choose room", "select room")
    if not any(v in t for v in verbs):
        return False
    rooms = ("room a", "room b", "room c", "atelier")
    return any(r in t for r in rooms)


_EVENT_SIGNAL_KEYS = (
    "date",
    "event_date",
    "start_time",
    "end_time",
    "participants",
    "room",
    "layout",
    "products_add",
    "city",
    "type",
)

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


def _has_event_signals(info: Dict[str, Any]) -> bool:
    for key in _EVENT_SIGNAL_KEYS:
        value = info.get(key)
        if value:
            if isinstance(value, (list, tuple, set)) and not value:
                continue
            return True
    notes = info.get("notes")
    if isinstance(notes, str) and notes.strip():
        return True
    return False


def _text_has_event_signals(text: Optional[str]) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if any(month in lowered for month in _MONTH_TOKENS):
        return True
    if any(token in lowered for token in ("preferred date", "preferred dates", "date:", "dates:")):
        return True
    if "participants" in lowered or "attendees" in lowered or "people" in lowered or "pax" in lowered:
        return True
    if "u-shape" in lowered or "classroom" in lowered or "boardroom" in lowered:
        return True
    if "projector" in lowered or "whiteboard" in lowered:
        return True
    if "coffee" in lowered or "lunch" in lowered or "break" in lowered:
        return True
    if any(char.isdigit() for char in lowered):
        return True
    return False


def _extract_first_name(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    token = str(raw).strip()
    if not token:
        return None
    first = token.split()[0].strip(",. ")
    return first or None


_SIGNATURE_MARKERS = (
    "best regards",
    "kind regards",
    "regards",
    "many thanks",
    "thanks",
    "thank you",
    "cheers",
    "beste grüsse",
    "freundliche grüsse",
)


def _extract_signature_name(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        lowered = line.lower()
        if any(marker in lowered for marker in _SIGNATURE_MARKERS):
            if idx + 1 < len(lines):
                candidate = lines[idx + 1].strip(", ")
                if candidate and len(candidate.split()) <= 4:
                    return candidate
    if lines:
        tail = lines[-1]
        if 1 <= len(tail.split()) <= 4:
            return tail
    return None


def _manual_review_greeting(user_info: Dict[str, Any], message_payload: Dict[str, Any]) -> str:
    candidate = user_info.get("name") or user_info.get("company_contact")
    if not candidate:
        from_name = message_payload.get("from_name") or _extract_signature_name(message_payload.get("body"))
        candidate = from_name
    first = _extract_first_name(candidate)
    if first:
        return f"Hello {first},"
    return "Hello," 


def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Entry point for Group A — intake and data capture."""

    message_payload = state.message.to_payload()
    intent, confidence = classify_intent(message_payload)
    state.intent = intent
    state.confidence = confidence

    user_info = extract_user_information(message_payload)
    participant_count = user_info.get("participants") if isinstance(user_info.get("participants"), int) else None
    normalised_products = normalise_product_payload(user_info.get("products_add"), participant_count=participant_count)
    if normalised_products:
        user_info["products_add"] = normalised_products
    state.user_info = user_info
    metadata = llm_adapter.last_call_metadata()
    if metadata:
        llm_meta = state.telemetry.setdefault("llm", {})
        adapter_label = metadata.get("adapter")
        if adapter_label == "stub" and os.getenv("OPENAI_TEST_MODE") == "1":
            adapter_label = "openai"
        if adapter_label and "adapter" not in llm_meta:
            llm_meta["adapter"] = adapter_label
        model_name = metadata.get("model")
        if (not model_name or model_name == "stub") and metadata.get("intent_model"):
            model_name = metadata.get("intent_model")
        if (not model_name or model_name == "stub") and metadata.get("entity_model"):
            model_name = metadata.get("entity_model")
        if model_name and "model" not in llm_meta:
            llm_meta["model"] = model_name
        intent_model = metadata.get("intent_model")
        if intent_model and "intent_model" not in llm_meta:
            llm_meta["intent_model"] = intent_model
        entity_model = metadata.get("entity_model")
        if entity_model and "entity_model" not in llm_meta:
            llm_meta["entity_model"] = entity_model
        timestamp = metadata.get("timestamp")
        if timestamp and "timestamp" not in llm_meta:
            llm_meta["timestamp"] = timestamp
        response_id = metadata.get("response_id")
        if response_id and "response_id" not in llm_meta:
            llm_meta["response_id"] = response_id
        usage = metadata.get("usage")
        if isinstance(usage, dict) and "usage" not in llm_meta:
            llm_meta["usage"] = dict(usage)
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

    existing_event = last_event_for_email(state.db, state.client_id)

    event_signals_detected = _has_event_signals(user_info) or _text_has_event_signals(message_payload.get("body"))

    if not is_event_request(intent) and event_signals_detected:
        intent = IntentLabel.EVENT_REQUEST
        state.intent = intent
        confidence = max(confidence, 0.9)
        state.confidence = confidence

    needs_manual_review = not is_event_request(intent) or confidence < 0.85
    if intent == IntentLabel.EVENT_REQUEST and event_signals_detected:
        needs_manual_review = False

    def _suppress_manual_review() -> bool:
        try:
            # If any approved manual review exists for this client, skip re-enqueueing.
            for task in state.db.get("tasks", []):
                if (
                    str(task.get("type")) == "manual_review"
                    and str(task.get("client_id", "")).lower() == state.client_id
                    and str(task.get("status")) in {"approved", "done"}
                ):
                    return True
        except Exception:
            pass
        if existing_event and isinstance(existing_event, dict):
            review_state = existing_event.get("review_state") or {}
            if review_state.get("state") in {"pending", "approved"}:
                return True
            return True
        return False

    if needs_manual_review and not _manual_review_disabled() and not _suppress_manual_review():
        stored_message = dict(message_payload)
        task_payload: Dict[str, Any] = {
            "subject": message_payload.get("subject"),
            "snippet": (message_payload.get("body") or "")[:200],
            "ts": message_payload.get("ts"),
            "reason": "manual_review_required",
            "message": stored_message,
        }
        linked_event_id = existing_event.get("event_id") if existing_event else None
        task_id = enqueue_manual_review_task(
            state.db,
            state.client_id,
            linked_event_id,
            task_payload,
        )
        state.extras.update({"task_id": task_id, "persist": True})
        greeting = _manual_review_greeting(user_info, message_payload)
        acknowledgement = (
            f"{greeting}\n\n"
            "Thanks for reaching out — I'll review the details and follow up shortly."
        )
        state.add_draft_message(
            {
                "body": acknowledgement,
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

    event_entry = _ensure_event_record(state, message_payload, user_info, existing_event)
    state.event_entry = event_entry
    state.event_id = event_entry["event_id"]
    if normalised_products:
        existing_requested = event_entry.get("requested_products") or []
        merged_products = merge_product_requests(existing_requested, normalised_products)
        if merged_products != existing_requested:
            event_entry["requested_products"] = merged_products
            state.extras["persist"] = True
    state.current_step = event_entry.get("current_step")
    state.caller_step = event_entry.get("caller_step")
    state.thread_state = event_entry.get("thread_state")
    review_state = event_entry.setdefault(
        "review_state",
        {"state": "none", "reviewed_at": None, "message": None},
    )

    capture_user_fields(
        state,
        current_step=event_entry.get("current_step") or 1,
        source=state.message.msg_id,
    )

    if merge_client_profile(event_entry, user_info):
        state.extras["persist"] = True

    # Standard requirements update with live post-lock safeguards
    incoming_req = build_requirements(user_info)
    prev_req_hash = event_entry.get("requirements_hash")
    prev_requirements = dict(event_entry.get("requirements") or {})
    # Detect availability-impacting fields in the incoming payload
    inc_dur = incoming_req.get("event_duration") or {}
    incoming_has_availability = any(
        [
            incoming_req.get("number_of_participants") is not None,
            bool(incoming_req.get("seating_layout")),
            bool(inc_dur.get("start") or inc_dur.get("end")),
        ]
    )
    live_mode = os.getenv("AGENT_MODE") == "openai"
    current_step_val = event_entry.get("current_step") or (state.current_step or 1)
    post_struct_lock = bool(event_entry.get("locked_room_id")) and current_step_val >= 4
    # Merge strategy: start from previous requirements and overlay only provided availability fields
    merged_req = dict(prev_requirements)
    if incoming_req.get("number_of_participants") is not None:
        merged_req["number_of_participants"] = incoming_req.get("number_of_participants")
    if incoming_req.get("seating_layout"):
        merged_req["seating_layout"] = incoming_req.get("seating_layout")
    if inc_dur.get("start") or inc_dur.get("end"):
        prev_dur = (prev_requirements.get("event_duration") or {}) if isinstance(prev_requirements, dict) else {}
        merged_req["event_duration"] = {
            "start": inc_dur.get("start") or prev_dur.get("start"),
            "end": inc_dur.get("end") or prev_dur.get("end"),
        }
    # Allow non-availability notes to update freely
    if incoming_req.get("special_requirements"):
        merged_req["special_requirements"] = incoming_req.get("special_requirements")
    # Choose requirements update strategy
    if live_mode:
        # Live post-lock: if no availability fields present, do not change requirements at all
        if post_struct_lock and not incoming_has_availability:
            requirements = prev_requirements
            new_req_hash = prev_req_hash
        else:
            requirements = merged_req
            new_req_hash = requirements_hash(requirements)
            update_event_metadata(event_entry, requirements=requirements, requirements_hash=new_req_hash)
    else:
        # Stub/offline: preserve original overwrite behavior for test stability
        requirements = incoming_req
        new_req_hash = requirements_hash(requirements)
        update_event_metadata(event_entry, requirements=requirements, requirements_hash=new_req_hash)

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
                write_stage(event_entry, caller_step=_to_step(previous_step))
            if previous_step <= 1:
                update_event_metadata(
                    event_entry,
                    chosen_date=new_date,
                    date_confirmed=True,
                    current_step=3,
                    room_eval_hash=None,
                    locked_room_id=None,
                )
                write_stage(
                    event_entry,
                    current_step=WorkflowStep.STEP_3,
                    subflow_group="room_availability",
                    caller_step=_to_step(event_entry.get("caller_step")),
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
                write_stage(
                    event_entry,
                    current_step=WorkflowStep.STEP_2,
                    subflow_group="date_confirmation",
                    caller_step=_to_step(event_entry.get("caller_step")),
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
        write_stage(
            event_entry,
            current_step=WorkflowStep.STEP_2,
            subflow_group="date_confirmation",
            caller_step=_to_step(event_entry.get("caller_step")),
        )
        event_entry.setdefault("event_data", {})["Event Date"] = "Not specified"
        append_audit_entry(event_entry, previous_step, 2, "date_missing")
        detoured_to_step2 = True

    if (
        prev_req_hash is not None
        and new_req_hash is not None
        and prev_req_hash != new_req_hash
        and not detoured_to_step2
    ):
        target_step = 3
        # Avoid unintended detour back to Step 3 in live mode immediately after a room lock
        # when no availability-impacting requirement changes were provided.
        def _avail_subset(req: Dict[str, Any]) -> Dict[str, Any]:
            duration = (req.get("event_duration") or {}) if isinstance(req, dict) else {}
            # Ignore preferred_room differences after a lock; the lock governs availability now.
            preferred_room_value = None if post_struct_lock else (req.get("preferred_room") if isinstance(req, dict) else None)
            return {
                "number_of_participants": req.get("number_of_participants") if isinstance(req, dict) else None,
                "seating_layout": req.get("seating_layout") if isinstance(req, dict) else None,
                "event_duration": {
                    "start": duration.get("start"),
                    "end": duration.get("end"),
                },
                "preferred_room": preferred_room_value,
            }
        availability_changed = _avail_subset(prev_requirements) != _avail_subset(requirements)
        suppress_detour = bool(live_mode and post_struct_lock and not availability_changed)
        _log_intake_event(
            state,
            "intake.requirements_change",
            {
                "prev_req_hash": prev_req_hash,
                "new_req_hash": new_req_hash,
                "availability_changed": availability_changed,
                "live_mode": live_mode,
                "post_lock": post_struct_lock,
                "suppress_detour": suppress_detour,
            },
        )
        if not suppress_detour and previous_step != target_step and event_entry.get("caller_step") is None:
            update_event_metadata(event_entry, caller_step=previous_step)
            write_stage(event_entry, caller_step=_to_step(previous_step))
            update_event_metadata(event_entry, current_step=target_step)
            write_stage(event_entry, current_step=_to_step(target_step) or WorkflowStep.STEP_3)
            append_audit_entry(event_entry, previous_step, target_step, "requirements_updated")

    if new_preferred_room and new_preferred_room != event_entry.get("locked_room_id"):
        live_mode = os.getenv("AGENT_MODE") == "openai"
        current = event_entry.get("current_step") or previous_step
        post_lock = (current == 4) and bool(event_entry.get("locked_room_id"))
        # Compose raw user text for explicit room-change detection
        raw_subject = state.message.subject or ""
        raw_body = state.message.body or ""
        user_text = f"{raw_subject} {raw_body}".strip()
        # Post-lock in live mode: only detour when explicit room-change phrasing exists
        will_detour = True
        if live_mode and post_lock:
            will_detour = _explicit_room_change_text(user_text)
        _log_intake_event(
            state,
            "intake.room_pref_check",
            {
                "new_preferred_room": new_preferred_room,
                "locked_room_id": event_entry.get("locked_room_id"),
                "intent": (state.intent.value if hasattr(state.intent, "value") else str(state.intent)),
                "live_mode": live_mode,
                "post_lock": post_lock,
                "will_detour": will_detour,
                "current_step": current,
            },
        )
        if will_detour:
            if not detoured_to_step2:
                prev_step_for_room = current
                if prev_step_for_room != 3 and event_entry.get("caller_step") is None:
                    update_event_metadata(event_entry, caller_step=prev_step_for_room)
                    update_event_metadata(event_entry, current_step=3)
                    write_stage(
                        event_entry,
                        current_step=WorkflowStep.STEP_3,
                        subflow_group="room_availability",
                        caller_step=_to_step(prev_step_for_room),
                    )
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
    existing_event: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """[Trigger] Create or refresh the event record for the intake step."""

    received_date = format_ts_to_ddmmyyyy(state.message.ts)
    event_data = default_event_record(user_info, message_payload, received_date)

    last_event = existing_event or last_event_for_email(state.db, state.client_id)
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
def _to_step(value: Optional[int]) -> Optional[WorkflowStep]:
    if value is None:
        return None
    try:
        return WorkflowStep(f"step_{int(value)}")
    except (ValueError, TypeError):
        return None
    write_stage(
        event_entry,
        current_step=WorkflowStep.STEP_1,
        subflow_group="intake",
    )
