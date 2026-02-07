"""Change routing pipeline for Step 1 intake.

Orchestrates: vague date reset, DAG routing, and four fallback chains
(date, missing date, requirements hash, room preference).  Mutates
``event_entry`` in place (consistent with ``change_application.py``
convention) and returns a small result with flags the caller needs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class ChangeRoutingResult:
    """Aggregate output of the change routing pipeline."""
    detoured_to_step2: bool = False
    change_detour: bool = False


def run_change_routing_pipeline(
    *,
    state: Any,
    event_entry: Dict[str, Any],
    user_info: Dict[str, Any],
    requirements: Dict[str, Any],
    unified_detection: Any,
    needs_vague_date_confirmation: bool,
    prev_req_hash: Optional[str],
    new_req_hash: Optional[str],
    message_payload: Dict[str, Any],
    thread_id: str,
    trace_marker_fn: Any,
) -> ChangeRoutingResult:
    """Run the full change detection and routing pipeline.

    Mutates ``event_entry`` via ``update_event_metadata`` / ``append_audit_entry``.
    Also mutates ``state.extras`` for ``change_detour`` and ``past_date_rejected``.
    """
    from workflows.change_propagation import route_change_on_updated_variable
    from workflows.io.database import append_audit_entry, update_event_metadata, tag_message

    from .change_routing_step1 import (
        build_change_context,
        detect_change_with_guards,
        should_skip_vague_date_reset,
    )
    from .change_fallback import (
        check_date_fallback,
        check_missing_date_fallback,
        check_requirements_hash_fallback,
        check_room_preference_fallback,
        FallbackAction,
    )
    from .change_application import apply_dag_routing

    result = ChangeRoutingResult()

    new_preferred_room = requirements.get("preferred_room")
    new_date = user_info.get("event_date")
    previous_step = state.current_step or 1

    message_text = state.message.body or ""

    # Build context for change detection (billing flow, deposit date, site visit guards)
    change_context = build_change_context(
        event_entry=event_entry,
        message_text=message_text,
        unified_detection=unified_detection,
        state_extras=state.extras,
    )

    # Detect changes with guards applied
    change_result = detect_change_with_guards(
        event_entry=event_entry,
        user_info=user_info,
        message_text=message_text,
        unified_detection=unified_detection,
        context=change_context,
    )
    change_type = change_result.change_type
    is_qna_no_change = change_result.is_qna_no_change

    # Q&A guard for vague date reset
    skip_vague_date_reset = should_skip_vague_date_reset(
        has_qna_question=change_context.has_qna_question,
        date_already_confirmed=change_context.date_already_confirmed,
    )

    # Extract guards from context for fallback routing
    in_billing_flow = change_context.in_billing_flow
    skip_guards = {
        "in_billing_flow": change_context.in_billing_flow,
        "is_deposit_date_context": change_context.is_deposit_date_context,
        "site_visit_active": change_context.site_visit_active,
        "site_visit_change": change_context.site_visit_scheduled and change_context.is_sv_change_request,
        "is_qna_no_change": is_qna_no_change,
    }

    # Vague date reset
    if needs_vague_date_confirmation and not in_billing_flow and not skip_vague_date_reset:
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
        result.detoured_to_step2 = True
        state.set_thread_state("Awaiting Client Response")
    elif needs_vague_date_confirmation and skip_vague_date_reset:
        logger.debug("[Step1] Skipping vague date reset - Q&A detected and date already confirmed")

    # Handle change routing using DAG-based change propagation
    logger.info("[Step1][CHANGE_ROUTING] change_type=%s, previous_step=%s", change_type, previous_step)
    if change_type is not None and previous_step > 1:
        decision = route_change_on_updated_variable(event_entry, change_type, from_step=previous_step)
        logger.info(
            "[Step1][CHANGE_ROUTING] decision: next_step=%s, caller_step=%s",
            decision.next_step, decision.updated_caller_step,
        )

        routing_result = apply_dag_routing(
            event_entry=event_entry,
            decision=decision,
            change_type=change_type,
            previous_step=previous_step,
            in_billing_flow=in_billing_flow,
            thread_id=thread_id,
            trace_marker_fn=trace_marker_fn,
        )
        if routing_result.detoured_to_step2:
            result.detoured_to_step2 = True
        if routing_result.change_detour:
            result.change_detour = True

    # Fallback: date routing for cases not handled by DAG change propagation
    elif change_type is None:
        date_fb = check_date_fallback(
            new_date=new_date,
            event_entry=event_entry,
            previous_step=previous_step,
            skip_guards=skip_guards,
        )
        if date_fb.action != FallbackAction.NONE:
            if date_fb.set_caller_step is not None:
                update_event_metadata(event_entry, caller_step=date_fb.set_caller_step)
            if date_fb.next_step is not None:
                update_event_metadata(
                    event_entry,
                    chosen_date=date_fb.new_date if date_fb.action != FallbackAction.PAST_DATE_TO_STEP2 else None,
                    date_confirmed=date_fb.date_confirmed,
                    current_step=date_fb.next_step,
                    room_eval_hash=None,
                    locked_room_id=None,
                )
                if date_fb.new_date:
                    event_entry.setdefault("event_data", {})["Event Date"] = date_fb.new_date
                if date_fb.action == FallbackAction.PAST_DATE_TO_STEP2:
                    state.extras["past_date_rejected"] = new_date
                append_audit_entry(event_entry, previous_step, date_fb.next_step, date_fb.audit_reason or "date_fallback")
                if date_fb.next_step == 2:
                    result.detoured_to_step2 = True

    # Fallback: missing date routing
    missing_date_fb = check_missing_date_fallback(
        new_date=new_date,
        event_entry=event_entry,
        change_type=change_type,
        needs_vague_date_confirmation=needs_vague_date_confirmation,
        previous_step=previous_step,
    )
    if missing_date_fb.action != FallbackAction.NONE:
        update_event_metadata(
            event_entry,
            chosen_date=None,
            date_confirmed=False,
            current_step=2,
            room_eval_hash=None,
            locked_room_id=None,
        )
        event_entry.setdefault("event_data", {})["Event Date"] = "Not specified"
        append_audit_entry(event_entry, previous_step, 2, missing_date_fb.audit_reason or "date_missing")
        result.detoured_to_step2 = True

    # Fallback: requirements hash mismatch routing
    req_fb = check_requirements_hash_fallback(
        prev_req_hash=prev_req_hash,
        new_req_hash=new_req_hash,
        event_entry=event_entry,
        previous_step=previous_step,
        change_type=change_type,
        detoured_to_step2=result.detoured_to_step2,
        is_qna_no_change=is_qna_no_change,
    )
    if req_fb.action != FallbackAction.NONE:
        if req_fb.set_caller_step is not None:
            update_event_metadata(event_entry, caller_step=req_fb.set_caller_step)
        if req_fb.next_step is not None:
            update_event_metadata(event_entry, current_step=req_fb.next_step)
            append_audit_entry(event_entry, previous_step, req_fb.next_step, req_fb.audit_reason or "requirements_updated")
            event_entry.pop("negotiation_pending_decision", None)

    # Fallback: room preference change routing
    room_fb = check_room_preference_fallback(
        new_preferred_room=new_preferred_room,
        event_entry=event_entry,
        previous_step=previous_step,
        change_type=change_type,
        detoured_to_step2=result.detoured_to_step2,
        is_qna_no_change=is_qna_no_change,
        in_billing_flow=in_billing_flow,
    )
    if room_fb.action != FallbackAction.NONE:
        if room_fb.set_caller_step is not None:
            update_event_metadata(event_entry, caller_step=room_fb.set_caller_step)
        if room_fb.next_step is not None:
            update_event_metadata(event_entry, current_step=room_fb.next_step)
            append_audit_entry(event_entry, room_fb.set_caller_step or previous_step, room_fb.next_step, room_fb.audit_reason or "room_preference_updated")

    # Tag the message and set default thread state
    tag_message(event_entry, message_payload.get("msg_id"))

    if not event_entry.get("thread_state"):
        update_event_metadata(event_entry, thread_state="Awaiting Client")

    return result
