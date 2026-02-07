from __future__ import annotations

import logging

logger = logging.getLogger(__name__)
from typing import Any, Dict

from workflows.common.requirements import merge_client_profile
from workflows.common.types import GroupResult, WorkflowState

from debug.hooks import (
    trace_entity,
    trace_marker,
    trace_state,
    trace_step,
)
from workflows.io.database import (
    append_history,
    context_snapshot,
    last_event_for_email,
    update_event_metadata,
    upsert_client,
)

from ..db_pers.tasks import enqueue_manual_review_task
from services import client_memory
from ..billing_flow import handle_billing_capture
from workflows.qna.router import generate_hybrid_qna_response
from detection.intent.classifier import _detect_qna_types

# Extracted pure helpers (I1 refactoring)
from .normalization import normalize_quotes as _normalize_quotes
from .date_fallback import fallback_year_from_ts as _fallback_year_from_ts
from workflows.common.detection_utils import get_unified_detection

# I2 refactoring: Extracted modules
from .event_bootstrap import ensure_event_record as _ensure_event_record
from .billing_detection import extract_billing_from_body as _extract_billing_from_body
from .early_detection import (
    should_boost_confidence as _should_boost_confidence,
)
from .early_pipeline import run_early_detection_pipeline as _run_early_detection_pipeline
from .manual_review_gate import (
    check_manual_review_gate as _check_manual_review_gate,
    apply_gate_result as _apply_gate_result,
)
from .room_shortcut import handle_smart_shortcut_path as _handle_smart_shortcut_path
from .room_confirmation import (
    check_room_confirmation as _check_room_confirmation,
    apply_room_confirmation as _apply_room_confirmation,
    RoomConfirmDecision as _RoomConfirmDecision,
)
from .change_pipeline import run_change_routing_pipeline as _run_change_routing_pipeline
from .classification_extraction import classify_and_extract as _classify_and_extract

# I1 Phase 1: Intent helpers
from .intent_helpers import resolve_owner_step as _resolve_owner_step


# I2: Requirements fallback
from .requirements_fallback import process_requirements as _process_requirements

# Dev/test mode helper (I2 refactoring)
from .dev_test_mode import maybe_show_dev_choice as _maybe_show_dev_choice

__workflow_role__ = "trigger"


# Generic product suffixes that shouldn't match standalone.
# These appear as the last word in product names (e.g., "Vegetarian Menu")
# but are too ambiguous to match without the full product name context.
@trace_step("Step1_Intake")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Entry point for Group A — intake and data capture."""
    message_payload = state.message.to_payload()
    thread_id = _thread_id(state)

    # Resolve owner step for tracing based on existing conversation state
    email = (message_payload.get("from_email") or "").lower()
    linked_event = last_event_for_email(state.db, email) if email else None
    current_step = linked_event.get("current_step") if linked_event else 1
    # Fallback if current_step is None/invalid
    if not isinstance(current_step, int):
        current_step = 1
    owner_step = _resolve_owner_step(current_step)

    # [TESTING CONVENIENCE] Dev/test mode choice prompt (I2 extraction)
    skip_dev_choice = state.extras.get("skip_dev_choice", False)
    dev_choice_result = _maybe_show_dev_choice(
        linked_event=linked_event,
        current_step=current_step,
        owner_step=owner_step,
        client_email=email,
        skip_dev_choice=skip_dev_choice,
    )
    if dev_choice_result:
        return dev_choice_result

    trace_marker(
        thread_id,
        "TRIGGER_Intake",
        detail=message_payload.get("subject"),
        data={"msg_id": state.message.msg_id},
        owner_step=owner_step,
    )

    # LLM classification and entity extraction (extracted module)
    classification = _classify_and_extract(message_payload, thread_id, owner_step)
    intent = classification.intent
    confidence = classification.confidence
    user_info = classification.user_info
    needs_vague_date_confirmation = classification.needs_vague_date_confirmation
    state.intent = intent
    state.confidence = confidence
    state.intent_detail = classification.intent_detail
    if classification.shortcut_detected:
        state.extras["shortcut_detected"] = True
        state.record_subloop("shortcut")
    _trace_user_entities(state, message_payload, user_info, owner_step)

    client = upsert_client(
        state.db,
        message_payload.get("from_email", ""),
        message_payload.get("from_name"),
    )
    state.client = client
    state.client_id = (message_payload.get("from_email") or "").lower()
    # linked_event is already fetched above
    body_text_raw = message_payload.get("body") or ""
    body_text = _normalize_quotes(body_text_raw)
    fallback_year = _fallback_year_from_ts(message_payload.get("ts"))

    # [EARLY DETECTION PIPELINE] Run all early detections in one call
    unified_detection = get_unified_detection(state)
    early = _run_early_detection_pipeline(
        body_text=body_text,
        linked_event=linked_event,
        user_info=user_info,
        fallback_year=fallback_year,
        unified_detection=unified_detection,
        message_payload=message_payload,
        current_intent=intent,
        current_confidence=confidence,
        current_intent_detail=state.intent_detail,
    )

    # Apply confirmation results to user_info
    if early.confirmation_detected:
        user_info["date"] = early.confirmation_date_iso
        user_info["event_date"] = early.confirmation_event_date
        if early.confirmation_start_time and "start_time" not in user_info:
            user_info["start_time"] = early.confirmation_start_time
        if early.confirmation_end_time and "end_time" not in user_info:
            user_info["end_time"] = early.confirmation_end_time

    # Apply acceptance results
    if early.acceptance_detected and linked_event:
        user_info.setdefault("hil_approve_step", early.acceptance_target_step)
        update_event_metadata(
            linked_event,
            current_step=early.acceptance_target_step,
            thread_state="Waiting on HIL",
            caller_step=None,
        )

    # Apply Q&A signals
    if early.should_set_general_qna:
        state.extras["general_qna_detected"] = True
        state.extras["_has_qna_types"] = True

    # Apply time validation warnings
    if not early.time_valid:
        state.extras["time_warning"] = early.time_warning
        state.extras["time_warning_issue"] = early.time_warning_issue
        if linked_event is not None:
            linked_event.setdefault("time_validation", {})
            linked_event["time_validation"]["issue"] = early.time_warning_issue
            linked_event["time_validation"]["warning"] = early.time_warning
            linked_event["time_validation"]["start_time"] = early.time_start
            linked_event["time_validation"]["end_time"] = early.time_end

    # Apply room choice
    if early.room_name:
        user_info["room"] = early.room_name
        user_info["_room_choice_detected"] = True
        state.extras["room_choice_selected"] = early.room_name
        logger.info("[Step1] Set _room_choice_detected=True for room=%s", early.room_name)

    # Apply menu choice
    if early.menu_name:
        user_info["menu_choice"] = early.menu_name
        if early.menu_product_payload:
            existing = user_info.get("products_add") or []
            if isinstance(existing, list):
                user_info["products_add"] = existing + [early.menu_product_payload]
            else:
                user_info["products_add"] = [early.menu_product_payload]

    # Apply product update
    if early.product_update_detected:
        state.extras["product_update_detected"] = True

    # Apply intent/confidence/detail overrides
    if early.override_intent is not None:
        intent = early.override_intent
        confidence = early.override_confidence or confidence
        state.intent = intent
        state.confidence = confidence
    if early.override_intent_detail is not None:
        state.intent_detail = early.override_intent_detail

    # Apply extras updates (e.g. persist flag from acceptance)
    state.extras.update(early.extras_updates)

    state.user_info = user_info
    append_history(client, message_payload, intent.value, confidence, user_info)

    # Store in client memory for personalization (if enabled)
    client_memory.append_message(
        client,
        role="client",
        text=message_payload.get("body") or "",
        metadata={"intent": intent.value, "confidence": confidence},
    )
    # Update profile with detected language/preferences
    if user_info.get("language"):
        client_memory.update_profile(client, language=user_info["language"])

    context = context_snapshot(state.db, client, state.client_id)
    state.record_context(context)

    # [CONFIDENCE BOOST] Use extracted module for clear event request boost
    should_boost, boosted_confidence = _should_boost_confidence(intent, confidence, user_info)
    if should_boost:
        confidence = boosted_confidence
        state.confidence = confidence

    # [MANUAL REVIEW GATE] Check if message needs special handling
    gate_result = _check_manual_review_gate(
        intent=intent,
        confidence=confidence,
        linked_event=linked_event,
        message_payload=message_payload,
        user_info=user_info,
        unified_detection=unified_detection,
        state_message=state.message,
    )

    # Apply gate result (may return early with halt=True for QNA/MANUAL_REVIEW)
    halt_result = _apply_gate_result(
        gate_result,
        state=state,
        user_info=user_info,
        linked_event=linked_event,
        message_payload=message_payload,
        thread_id=thread_id,
        owner_step=owner_step,
        context=context,
        enqueue_manual_review_task_fn=enqueue_manual_review_task,
        trace_marker_fn=trace_marker,
    )
    if halt_result is not None:
        return halt_result

    # For CONTINUE: gate already updated state.intent / state.confidence / user_info
    intent = state.intent
    confidence = state.confidence

    event_entry = _ensure_event_record(state, message_payload, user_info)
    if event_entry.get("pending_hil_requests"):
        event_entry["pending_hil_requests"] = []
        state.extras["persist"] = True

    # Persist country/timezone from account profile for downstream scheduling/time rendering.
    profile = (client or {}).get("profile") if isinstance(client, dict) else {}
    profile_country = profile.get("country") if isinstance(profile, dict) else None
    profile_timezone = profile.get("timezone") if isinstance(profile, dict) else None
    effective_timezone = profile_timezone or state.extras.get("client_timezone")
    timezone_updates: Dict[str, Any] = {}
    if profile_country and event_entry.get("client_country") != profile_country:
        timezone_updates["client_country"] = profile_country
    if effective_timezone and event_entry.get("client_timezone") != effective_timezone:
        timezone_updates["client_timezone"] = effective_timezone
    if timezone_updates:
        update_event_metadata(event_entry, **timezone_updates)
        state.extras["persist"] = True

    if merge_client_profile(event_entry, user_info):
        state.extras["persist"] = True

    # Extract billing from message body if not already captured
    # This allows billing to be captured even from event requests that include billing info
    if not user_info.get("billing_address"):
        body_text = message_payload.get("body") or ""
        extracted_billing = _extract_billing_from_body(body_text)
        if extracted_billing:
            user_info["billing_address"] = extracted_billing
            trace_entity(thread_id, owner_step, "billing_address", extracted_billing[:100], True)

    handle_billing_capture(state, event_entry)
    menu_choice_name = user_info.get("menu_choice")
    if menu_choice_name:
        catering_list = event_entry.setdefault("selected_catering", [])
        if menu_choice_name not in catering_list:
            catering_list.append(menu_choice_name)
            event_entry.setdefault("event_data", {})["Catering Preference"] = menu_choice_name
            state.extras["persist"] = True
    state.event_entry = event_entry
    state.event_id = event_entry["event_id"]
    state.current_step = event_entry.get("current_step")
    state.caller_step = event_entry.get("caller_step")
    state.thread_state = event_entry.get("thread_state")

    # Process requirements with fallback and products-only detection
    req_result = _process_requirements(user_info, event_entry)
    requirements = req_result.requirements
    new_req_hash = req_result.requirements_hash

    prev_req_hash = event_entry.get("requirements_hash")
    update_event_metadata(
        event_entry,
        requirements=requirements,
        requirements_hash=new_req_hash,
    )

    # [SMART SHORTCUT] Check past-date → eligibility → evaluate → apply (all in one call)
    shortcut_halt = _handle_smart_shortcut_path(
        state=state,
        event_entry=event_entry,
        requirements=requirements,
        user_info=user_info,
        new_req_hash=new_req_hash,
        needs_vague_date_confirmation=needs_vague_date_confirmation,
        intent=intent,
        confidence=confidence,
    )
    if shortcut_halt is not None:
        return shortcut_halt

    # Apply metadata updates from preferences and vague date hints
    metadata_updates = _build_metadata_updates(user_info)
    if metadata_updates:
        update_event_metadata(event_entry, **metadata_updates)

    # [ROOM CONFIRMATION] Use extracted module for room choice handling
    room_choice_selected = state.extras.pop("room_choice_selected", None)
    if room_choice_selected:
        confirm_result = _check_room_confirmation(
            room_choice_selected, event_entry, user_info,
            state.extras, state.message.body or "", state.db
        )

        if confirm_result.decision == _RoomConfirmDecision.DEFER_ARRANGEMENT:
            # Missing products - defer to Step 3
            user_info["room"] = room_choice_selected
            user_info["_room_choice_detected"] = True
        elif confirm_result.decision == _RoomConfirmDecision.CONFIRM_AND_ADVANCE:
            # Apply room confirmation
            _apply_room_confirmation(event_entry, confirm_result, state.current_step or 1)
            state.current_step = 4
            state.caller_step = None
            state.set_thread_state("Awaiting Client")
            state.extras["persist"] = True

            # Store hybrid Q&A response if generated
            if confirm_result.hybrid_qna_response:
                state.extras["hybrid_qna_response"] = confirm_result.hybrid_qna_response

            # Add draft message
            if confirm_result.draft_message:
                state.add_draft_message(confirm_result.draft_message)

            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": intent.value,
                "confidence": round(confidence, 3),
                "locked_room_id": room_choice_selected,
                "thread_state": state.thread_state,
                "persisted": True,
            }
            return GroupResult(action="room_choice_captured", payload=payload, halt=False)
        # SKIP decision falls through to normal flow

    # [CHANGE ROUTING PIPELINE] Vague date reset + DAG routing + 4 fallback chains
    change_routing = _run_change_routing_pipeline(
        state=state,
        event_entry=event_entry,
        user_info=user_info,
        requirements=requirements,
        unified_detection=unified_detection,
        needs_vague_date_confirmation=needs_vague_date_confirmation,
        prev_req_hash=prev_req_hash,
        new_req_hash=new_req_hash,
        message_payload=message_payload,
        thread_id=_thread_id(state),
        trace_marker_fn=trace_marker,
    )
    if change_routing.change_detour:
        state.extras["change_detour"] = True

    state.current_step = event_entry.get("current_step")
    state.caller_step = event_entry.get("caller_step")
    state.thread_state = event_entry.get("thread_state")
    state.extras["persist"] = True

    # Handle hybrid messages: booking intent + Q&A questions in same message
    _generate_hybrid_qna_if_needed(state, event_entry)

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


def _build_metadata_updates(user_info: Dict[str, Any]) -> Dict[str, Any]:
    """Build metadata updates dict from user_info preferences and vague date hints."""
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
    return metadata_updates


def _generate_hybrid_qna_if_needed(state: WorkflowState, event_entry: Dict[str, Any]) -> None:
    """Generate hybrid Q&A response if detected and not already generated."""
    if not state.extras.get("general_qna_detected"):
        return
    if state.extras.get("hybrid_qna_response"):
        return

    # Try unified_detection first, fall back to keyword detection
    unified_detection = state.extras.get("unified_detection") or {}
    qna_types = unified_detection.get("qna_types") or []
    if not qna_types:
        message_text = state.message.body or ""
        qna_types = _detect_qna_types(message_text.lower())
        if not qna_types:
            qna_types = ["general"]

    if qna_types:
        message_text = state.message.body or ""
        hybrid_qna_response = generate_hybrid_qna_response(
            qna_types=qna_types,
            message_text=message_text,
            event_entry=event_entry,
            db=state.db,
        )
        if hybrid_qna_response:
            state.extras["hybrid_qna_response"] = hybrid_qna_response


def _trace_user_entities(state: WorkflowState, message_payload: Dict[str, Any], user_info: Dict[str, Any], owner_step: str) -> None:
    thread_id = _thread_id(state)
    if not thread_id:
        return

    email = message_payload.get("from_email")
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
