from __future__ import annotations
from datetime import datetime, time, date
from typing import Any, Dict, List, Optional, Sequence, Tuple
import re
import logging

from domain import TaskStatus, TaskType
from workflows.io.config_store import get_timezone
from debug.hooks import (
    set_subloop,
    trace_db_read,
    trace_db_write,
    trace_entity,
    trace_marker,
    trace_state,
    trace_step,
    trace_gate,
    trace_general_qa_status,
)
from workflows.common.datetime_parse import (
    build_window_iso,
    parse_all_dates,
    parse_first_date,
    parse_time_range,
    to_ddmmyyyy,
    to_iso_date,
)
from workflows.common.prompts import append_footer, format_sections_with_headers, verbalize_draft_body
from workflows.common.capture import capture_user_fields, capture_workflow_requirements, promote_fields
from workflows.common.requirements import requirements_hash
from workflows.common.gatekeeper import refresh_gatekeeper
from workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from workflows.common.menu_options import (
    build_menu_payload,
    build_menu_title,
    extract_menu_request,
    format_menu_line,
    format_menu_line_short,
    MENU_CONTENT_CHAR_THRESHOLD,
    normalize_menu_for_display,
    select_menu_options,
)
from utils.pseudolinks import generate_qna_link
from utils.page_snapshots import create_snapshot
from workflows.common.general_qna import (
    append_general_qna_to_primary,
    render_general_qna_reply,
    enrich_general_qna_step2,
    _fallback_structured_body,
)
from workflows.change_propagation import (
    detect_change_type,
    detect_change_type_enhanced,
    route_change_on_updated_variable,
)
from workflows.common.detour_acknowledgment import (
    generate_detour_acknowledgment,
    add_detour_acknowledgment_draft,
)
from workflows.qna.router import route_general_qna, generate_hybrid_qna_response
from workflows.common.types import GroupResult, WorkflowState
# MIGRATED: from workflows.common.confidence -> backend.detection.intent.confidence
from detection.intent.confidence import check_nonsense_gate
from workflows.common.detection_utils import get_unified_detection
from workflows.steps.step1_intake.condition.checks import suggest_dates
from workflows.io.database import (
    append_audit_entry,
    link_event_to_client,
    load_db,
    load_rooms,
    tag_message,
    update_event_metadata,
)
from workflows.nlu import detect_general_room_query, detect_sequential_workflow_request
from utils.profiler import profile_step
from services.availability import next_five_venue_dates, validate_window
# D10: from_hints, MONTH_INDEX_TO_NAME now used in candidate_dates.py
from utils.calendar_events import update_calendar_event_status
from workflow.state import WorkflowStep, default_subflow, write_stage

from ..condition.decide import is_valid_ddmmyyyy

# D1 refactoring: Types and constants extracted to dedicated modules
from .types import ConfirmationWindow, WindowHints
# D12: Constants moved to step2_utils.py and confirmation.py - no longer needed here

# D2 refactoring: Date parsing utilities extracted to dedicated module
from .date_parsing import (
    safe_parse_iso_date as _safe_parse_iso_date,
    iso_date_is_past as _iso_date_is_past,
    next_matching_date as _next_matching_date,
    format_display_dates as _format_display_dates,
    human_join as _human_join,
    parse_weekday_mentions as _parse_weekday_mentions,
    weekday_indices_from_hint as _weekday_indices_from_hint,
    normalize_month_token as _normalize_month_token,
    normalize_weekday_tokens as _normalize_weekday_tokens,
)

# D3 refactoring: Proposal tracking utilities extracted to dedicated module
from .proposal_tracking import (
    increment_date_attempt as _increment_date_attempt,
    reset_date_attempts as _reset_date_attempts,
    proposal_skip_dates as _proposal_skip_dates,
    update_proposal_history as _update_proposal_history,
)

# D4 refactoring: Calendar check utilities extracted to dedicated module
# D13b: preferred_room added, D14a: calendar_conflict_reason added
from .calendar_checks import (
    candidate_is_calendar_free as _candidate_is_calendar_free,
    maybe_fuzzy_friday_candidates as _maybe_fuzzy_friday_candidates,
    preferred_room as _preferred_room,
    calendar_conflict_reason as _calendar_conflict_reason,
)

# D5 refactoring: General Q&A bridge extracted to dedicated module
# Window helpers provide shared functions used by both step2_handler and general_qna
from .window_helpers import (
    _reference_date_from_state,
    _resolve_window_hints,
    _has_window_constraints,
    _window_filters,
    _extract_participants_from_state,
    _candidate_dates_for_constraints,
)
from .general_qna import (
    _present_general_room_qna,
    _search_range_availability,
)

# D6 refactoring: Pure utilities extracted to step2_utils.py
# D13: compose_greeting, with_greeting added
from .step2_utils import (
    _extract_first_name,
    _extract_signature_name,
    compose_greeting,
    with_greeting,
    _extract_candidate_tokens,
    _strip_system_subject,
    _preface_with_apology,
    _format_label_text,
    _date_header_label,
    _format_time_label,
    _format_day_list,
    _weekday_label_from_dates,
    _month_label_from_dates,
    _pluralize_weekday_hint,
    _describe_constraints,
    _format_window,
    _normalize_time_value,
    _to_time,
    _window_hash,
    _is_affirmative_reply,
    _message_signals_confirmation,
    _message_mentions_new_date,
    # D10: _is_weekend_token now used in candidate_dates.py
    _window_payload,
    _window_from_payload,
    # D9: Additional utilities
    has_range_tokens,
    range_query_pending,
    get_message_text,
    build_select_date_action,
    format_room_availability,
    compact_products_summary,
    user_requested_products,
    # D13d: Tracing
    trace_candidate_gate as _trace_candidate_gate,
)

# D7 refactoring: Candidate date generation extracted to candidate_dates.py
from .candidate_dates import (
    _collect_preferred_weekday_alternatives,
    collect_candidates_from_week_scope,
    collect_candidates_from_fuzzy,
    resolve_week_scope,
    preferred_weekday_label,
)

# D8 refactoring: Pure confirmation helpers extracted to confirmation.py
# D13c: should_auto_accept_first_date added
from .confirmation import (
    determine_date,
    find_existing_time_window,
    collect_candidate_iso_list,
    record_confirmation_log,
    set_pending_time_state,
    complete_from_time_hint,
    should_auto_accept_first_date as _should_auto_accept_first_date,
)

# D15 refactoring: State-dependent helpers extracted to step2_state.py
from .step2_state import (
    thread_id as _thread_id_impl,
    emit_step2_snapshot as _emit_step2_snapshot_impl,
    client_requested_dates as _client_requested_dates_impl,
    maybe_general_qa_payload as _maybe_general_qa_payload_impl,
)

# D16b refactoring: Menu handling extracted to step2_menu.py
from .step2_menu import append_menu_options_if_requested as _append_menu_impl

# D-PRES refactoring: Candidate presentation extracted to candidate_presentation.py
from .candidate_presentation import (
    build_past_date_message,
    build_reason_message,
    build_attempt_message,
    build_unavailable_message,
    build_date_list_lines,
    build_closing_prompt,
    build_date_table_rows,
    build_date_actions,
    build_table_label,
    assemble_candidate_draft,
    verbalize_candidate_message,
)

# D-CTX refactoring: Date context resolution extracted to date_context.py
from .date_context import (
    parse_requested_dates,
    resolve_weekday_preferences,
    resolve_time_hints,
    resolve_anchor_date,
    calculate_collection_limits,
    get_preferred_room,
)

__workflow_role__ = "trigger"

logger = logging.getLogger(__name__)


# D15a: Thin wrapper delegating to step2_state.thread_id
def _thread_id(state: WorkflowState) -> str:
    return _thread_id_impl(state)


# D15b: Thin wrapper delegating to step2_state.emit_step2_snapshot
def _emit_step2_snapshot(
    state: WorkflowState,
    event_entry: dict,
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    _emit_step2_snapshot_impl(state, event_entry, extra=extra)


# D15c: Thin wrapper delegating to step2_state.client_requested_dates
def _client_requested_dates(state: WorkflowState) -> List[str]:
    return _client_requested_dates_impl(state)


# D16b: Thin wrapper delegating to step2_menu.append_menu_options_if_requested
def _append_menu_options_if_requested(state: WorkflowState, message_lines: List[str], month_hint: Optional[str]) -> None:
    _append_menu_impl(state, message_lines, month_hint)


def _maybe_append_general_qna(
    result: GroupResult,
    state: WorkflowState,
    event_entry: dict,
    classification: Dict[str, Any],
    thread_id: str,
    qa_payload: Optional[Dict[str, Any]],
    requested_client_dates: Sequence[str],
    deferred_general_qna: bool,
) -> GroupResult:
    # HYBRID FIX: Also allow Q&A appending when qna_types exist (workflow + Q&A in same message)
    has_qna_types = state.extras.get("_has_qna_types", False)
    has_qna_signal = classification.get("is_general") or has_qna_types
    if not deferred_general_qna or not requested_client_dates or not has_qna_signal:
        return result

    pre_count = len(state.draft_messages)
    original_candidate_dates = list(event_entry.get("candidate_dates") or [])
    original_thread_state = event_entry.get("thread_state")
    original_current_step = event_entry.get("current_step")
    original_state_thread = state.thread_state

    qa_result = _present_general_room_qna(state, event_entry, classification, thread_id, qa_payload)
    if qa_result is None or len(state.draft_messages) <= pre_count:
        event_entry["candidate_dates"] = list(original_candidate_dates)
        update_event_metadata(
            event_entry,
            candidate_dates=event_entry.get("candidate_dates"),
            current_step=original_current_step,
            thread_state=original_thread_state,
        )
        state.thread_state = original_state_thread
        return result

    structured_ok = bool(qa_result.payload.get("structured_qna"))
    if not structured_ok:
        while len(state.draft_messages) > pre_count:
            state.draft_messages.pop()
        event_entry["candidate_dates"] = list(original_candidate_dates)
        update_event_metadata(
            event_entry,
            candidate_dates=event_entry.get("candidate_dates"),
            current_step=original_current_step,
            thread_state=original_thread_state,
        )
        state.thread_state = original_state_thread
        return result

    attached = append_general_qna_to_primary(state)
    if not attached:
        while len(state.draft_messages) > pre_count:
            state.draft_messages.pop()
        event_entry["candidate_dates"] = list(original_candidate_dates)
        update_event_metadata(
            event_entry,
            candidate_dates=event_entry.get("candidate_dates"),
            current_step=original_current_step,
            thread_state=original_thread_state,
        )
        state.thread_state = original_state_thread
        return result

    event_entry["candidate_dates"] = list(original_candidate_dates)
    update_event_metadata(
        event_entry,
        candidate_dates=event_entry.get("candidate_dates"),
        current_step=original_current_step,
        thread_state=original_thread_state,
    )
    state.thread_state = original_state_thread

    return result


# D14a: _calendar_conflict_reason moved to calendar_checks.py


# D13: Thin wrapper delegating to pure compose_greeting
def _compose_greeting(state: WorkflowState) -> str:
    profile = (state.client or {}).get("profile", {}) if state.client else {}
    user_info_name = None
    if state.user_info:
        user_info_name = state.user_info.get("name") or state.user_info.get("company_contact")
    raw_name = user_info_name or profile.get("name")
    msg = state.message
    return compose_greeting(raw_name, msg.body if msg else None, msg.from_name if msg else None)


# D13: Thin wrapper delegating to pure with_greeting
def _with_greeting(state: WorkflowState, body: str) -> str:
    return with_greeting(_compose_greeting(state), body)


@trace_step("Step2_Date")
@profile_step("workflow.step2.date_confirmation")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Run Group B — date negotiation and confirmation."""

    event_entry = state.event_entry
    if not event_entry:
        payload = {
            "client_id": state.client_id,
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "missing_event_record",
            "context": state.context_snapshot,
        }
        return GroupResult(action="date_invalid", payload=payload, halt=True)

    state.current_step = 2
    state.subflow_group = "date_confirmation"
    write_stage(event_entry, current_step=WorkflowStep.STEP_2, subflow_group="date_confirmation")

    capture_user_fields(state, current_step=2, source=state.message.msg_id if state.message else None)

    hil_step = state.user_info.get("hil_approve_step")
    if hil_step == 2:
        decision = state.user_info.get("hil_decision") or "approve"
        return _apply_step2_hil_decision(state, event_entry, decision)

    # D9: Use extracted function
    msg = state.message
    message_text = get_message_text(msg.subject if msg else None, msg.body if msg else None)

    # Capture requirements from workflow context (statements only, not questions)
    if message_text and state.user_info:
        capture_workflow_requirements(state, message_text, state.user_info)

    # -------------------------------------------------------------------------
    # NONSENSE GATE: Check for off-topic/nonsense using existing confidence
    # -------------------------------------------------------------------------
    nonsense_action = check_nonsense_gate(state.confidence or 0.0, message_text)
    if nonsense_action == "ignore":
        # Provide guidance instead of silent ignore (F-04 fix)
        guidance_message = (
            "Thanks for your message! We're waiting for you to confirm your preferred event date. "
            "Please let us know which date works best for you."
        )
        state.add_draft_message({
            "body_markdown": guidance_message,
            "topic": "nonsense_guidance",
        })
        return GroupResult(
            action="nonsense_guided",  # Changed from _ignored to _guided
            payload={"reason": "low_confidence_no_workflow_signal", "step": 2},
            halt=True,
        )
    if nonsense_action == "hil":
        # Borderline - defer to human
        draft = {
            "body": append_footer(
                "I'm not sure I understood your message. I've forwarded it to our team for review.",
                step=2,
                next_step=2,
                thread_state="Awaiting Manager Review",
            ),
            "topic": "nonsense_hil_review",
            "requires_approval": True,
        }
        state.add_draft_message(draft)
        update_event_metadata(event_entry, current_step=2, thread_state="Awaiting Manager Review")
        state.set_thread_state("Awaiting Manager Review")
        state.extras["persist"] = True
        return GroupResult(
            action="nonsense_hil_deferred",
            payload={"reason": "borderline_confidence", "step": 2},
            halt=True,
        )
    # -------------------------------------------------------------------------

    classification = detect_general_room_query(message_text, state)
    state.extras["_general_qna_classification"] = classification
    # HYBRID FIX: Also check qna_types from unified detection for hybrid messages
    # (workflow action + Q&A in same message, e.g., "Book May 15 for 30. Parking available?")
    # IMPORTANT: Only use qna_types if LLM detected is_question=True
    unified_detection = get_unified_detection(state)
    has_qna_types = bool(getattr(unified_detection, "qna_types", None) if unified_detection else False)
    is_question = bool(getattr(unified_detection, "is_question", False) if unified_detection else False)
    has_valid_qna = has_qna_types and is_question  # Only valid if LLM says it's a question
    state.extras["general_qna_detected"] = bool(classification.get("is_general")) or has_valid_qna
    state.extras["_has_qna_types"] = has_valid_qna  # Track for deferred Q&A logic

    # HYBRID FIX: Pre-generate hybrid Q&A response for hybrid messages
    # This will be appended to the workflow response by api/routes/messages.py
    if has_valid_qna and not classification.get("is_general"):
        qna_types = getattr(unified_detection, "qna_types", []) or []
        if qna_types:
            hybrid_qna_response = generate_hybrid_qna_response(
                qna_types=qna_types,
                message_text=state.message.body or "",
                event_entry=event_entry,
                db=state.db,
            )
            if hybrid_qna_response:
                state.extras["hybrid_qna_response"] = hybrid_qna_response
                logger.debug("[STEP2][HYBRID_QNA] Generated hybrid Q&A response for types: %s", qna_types)

    classification.setdefault("primary", "general_qna")
    if not classification.get("secondary"):
        classification["secondary"] = ["general"]
    thread_id = _thread_id(state)
    if thread_id:
        trace_marker(
            thread_id,
            "QNA_CLASSIFY",
            detail="general_room_query" if classification["is_general"] else "not_general",
            data={
                "heuristics": classification.get("heuristics"),
                "parsed": classification.get("parsed"),
                "constraints": classification.get("constraints"),
                "llm_called": classification.get("llm_called"),
                "llm_result": classification.get("llm_result"),
                "cached": classification.get("cached"),
            },
            owner_step="Step2_Date",
        )
    qa_payload = _maybe_general_qa_payload(state)

    # [CHANGE DETECTION] Tap incoming stream BEFORE Q&A dispatch to detect client revisions
    # ("actually we're 50 now") and route them back to dependent nodes while hashes stay valid.
    # Use enhanced detection with dual-condition logic (revision signal + bound target)
    #
    # GUARD: Skip date change detection when site visit flow is active
    # When client selects a date for site visit, it should NOT update the event date
    from workflows.common.site_visit_state import is_site_visit_active
    site_visit_active = is_site_visit_active(event_entry)

    user_info = state.user_info or {}
    # Pass unified_detection so Q&A messages don't trigger false change detours
    unified_detection = get_unified_detection(state)
    enhanced_result = detect_change_type_enhanced(
        event_entry, user_info, message_text=message_text, unified_detection=unified_detection
    )
    change_type = enhanced_result.change_type if enhanced_result.is_change else None

    # If site visit is active, suppress date change detection
    # Date in message is for site visit selection, not event date change
    if site_visit_active and change_type and change_type.value == "date":
        logger.info("[STEP2][SV_GUARD] Site visit active - suppressing date change detection")
        change_type = None

    if change_type is not None:
        # Change detected: route it per DAG rules and skip Q&A dispatch
        decision = route_change_on_updated_variable(event_entry, change_type, from_step=2)

        # Trace logging for parity with Step 1
        if thread_id:
            trace_marker(
                thread_id,
                "CHANGE_DETECTED",
                detail=f"change_type={change_type.value}",
                data={
                    "change_type": change_type.value,
                    "from_step": 2,
                    "to_step": decision.next_step,
                    "caller_step": decision.updated_caller_step,
                    "needs_reeval": decision.needs_reeval,
                    "skip_reason": decision.skip_reason,
                },
                owner_step="Step2_Date",
            )

        # Apply routing decision: update current_step and caller_step
        if decision.updated_caller_step is not None:
            update_event_metadata(event_entry, caller_step=decision.updated_caller_step)

        if decision.next_step != 2:
            update_event_metadata(event_entry, current_step=decision.next_step)

            # For date changes: Update the date, keep room lock, invalidate room_eval_hash
            # Step 3 will check if the locked room is still available on the new date
            if change_type.value == "date":
                # Get the new date from user_info
                new_date = user_info.get("date") or user_info.get("event_date")
                if new_date:
                    # Normalize to DD.MM.YYYY format
                    from workflows.common.datetime_parse import parse_all_dates
                    from datetime import date as dt_date
                    parsed = list(parse_all_dates(str(new_date), fallback_year=dt_date.today().year, limit=1))
                    if parsed:
                        new_date_str = parsed[0].strftime("%d.%m.%Y")
                        update_event_metadata(
                            event_entry,
                            chosen_date=new_date_str,
                            date_confirmed=True,  # Date is now confirmed
                            room_eval_hash=None,  # Invalidate to trigger re-verification in Step 3
                            # NOTE: Keep locked_room_id to allow fast-skip if room still available
                        )
                        logger.info("[STEP2][DATE_CHANGE] Updated date from %s to %s",
                                    event_entry.get("chosen_date"), new_date_str)
                elif decision.next_step == 2:
                    # No new date found, just invalidate for re-confirmation
                    update_event_metadata(
                        event_entry,
                        date_confirmed=False,
                        room_eval_hash=None,
                    )
            # For requirements changes, clear the lock since room may no longer fit
            elif change_type.value == "requirements" and decision.next_step in (2, 3):
                # BUG FIX: Only set date_confirmed=False when going to Step 2
                # Passing None would overwrite existing True value!
                metadata_updates = {
                    "room_eval_hash": None,
                    "locked_room_id": None,
                }
                if decision.next_step == 2:
                    metadata_updates["date_confirmed"] = False
                update_event_metadata(event_entry, **metadata_updates)

            append_audit_entry(event_entry, 2, decision.next_step, f"{change_type.value}_change_detected")

            # BUG-024 FIX: Set flag for date change acknowledgment in step5
            # This flag is persisted to event_entry so it survives across routing loops
            if change_type.value == "date":
                event_entry["_pending_date_change_ack"] = True

            # IMMEDIATE ACKNOWLEDGMENT: Add detour acknowledgment draft
            # This provides immediate feedback to the user about the change
            ack_result = generate_detour_acknowledgment(
                change_type=change_type,
                decision=decision,
                event_entry=event_entry,
                user_info=user_info,
            )
            if ack_result.generated:
                add_detour_acknowledgment_draft(state, ack_result)

            # Skip Q&A: return detour signal
            # CRITICAL: Update event_entry BEFORE state.current_step so routing loop sees the change
            update_event_metadata(event_entry, current_step=decision.next_step)
            state.current_step = decision.next_step
            state.set_thread_state("In Progress")
            state.extras["persist"] = True
            state.extras["change_detour"] = True
            # Clear stale hybrid Q&A from previous turns (prevents old Q&A being appended to detour response)
            state.extras.pop("hybrid_qna_response", None)

            payload = {
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "intent": state.intent.value if state.intent else None,
                "confidence": round(state.confidence or 0.0, 3),
                "change_type": change_type.value,
                "detour_to_step": decision.next_step,
                "caller_step": decision.updated_caller_step,
                "thread_state": state.thread_state,
                "context": state.context_snapshot,
                "persisted": True,
            }
            return GroupResult(action="change_detour", payload=payload, halt=False)

    # No change detected: proceed with Q&A dispatch as normal
    explicit_confirmation = bool(
        user_info.get("date")
        or user_info.get("event_date")
        or _message_signals_confirmation(message_text)
    )

    # -------------------------------------------------------------------------
    # SEQUENTIAL WORKFLOW DETECTION
    # If the client confirms the current step AND asks about the next step,
    # that's NOT general Q&A - it's natural workflow continuation.
    # Example: "Please confirm May 8 and show me available rooms"
    # -------------------------------------------------------------------------
    sequential_check = detect_sequential_workflow_request(message_text, current_step=2)
    if sequential_check.get("is_sequential"):
        # Client is confirming date AND asking about rooms - this is natural flow
        classification["is_general"] = False
        classification["workflow_lookahead"] = sequential_check.get("asks_next_step")
        state.extras["general_qna_detected"] = False
        state.extras["workflow_lookahead"] = sequential_check.get("asks_next_step")
        state.extras["_general_qna_classification"] = classification
        if thread_id:
            trace_marker(
                thread_id,
                "SEQUENTIAL_WORKFLOW",
                detail=f"step2_to_step{sequential_check.get('asks_next_step')}",
                data=sequential_check,
            )
    elif classification.get("is_general") and explicit_confirmation:
        classification["is_general"] = False
        state.extras["general_qna_detected"] = False
        state.extras["_general_qna_classification"] = classification

    requested_client_dates = _client_requested_dates(state)
    deferred_general_qna = False
    general_qna_applicable = classification.get("is_general") and not bool(event_entry.get("date_confirmed"))
    # HYBRID FIX: Also defer Q&A when qna_types exist (workflow + Q&A in same message)
    has_qna_types = state.extras.get("_has_qna_types", False)
    if general_qna_applicable and requested_client_dates:
        deferred_general_qna = True
        general_qna_applicable = False
    elif has_qna_types and requested_client_dates and not general_qna_applicable:
        # Hybrid message: workflow action (date) + Q&A question - defer Q&A to append after workflow response
        deferred_general_qna = True
    if general_qna_applicable:
        result = _present_general_room_qna(state, event_entry, classification, thread_id, qa_payload)
        enrich_general_qna_step2(state, classification)
        return result

    # FIX: Handle Q&A even when date is already confirmed
    # "Does Room A have a projector?" should be answered inline, not trigger Step 3 auto-run
    llm_is_question = bool(getattr(unified_detection, "is_question", False) if unified_detection else False)
    llm_general_qna = bool(
        getattr(unified_detection, "intent", "") in ("general_qna", "non_event") if unified_detection else False
    )
    is_likely_qna = classification.get("is_general") or llm_is_question or llm_general_qna

    if is_likely_qna and bool(event_entry.get("date_confirmed")):
        # Pure Q&A when date already confirmed - answer inline and halt
        # Don't progress to Step 3 for room selection
        logger.info("[STEP2][QNA_GUARD] Q&A detected with date_confirmed=True - handling inline (is_general=%s, llm_is_question=%s)",
                    classification.get("is_general"), llm_is_question)
        result = _present_general_room_qna(state, event_entry, classification, thread_id, qa_payload)
        enrich_general_qna_step2(state, classification)
        return result

    pending_future_payload = event_entry.get("pending_future_confirmation")
    if pending_future_payload:
        body_text = state.message.body or ""
        if _message_mentions_new_date(body_text):
            event_entry.pop("pending_future_confirmation", None)
        elif _message_signals_confirmation(body_text):
            pending_future_window = _window_from_payload(pending_future_payload)
            event_entry.pop("pending_future_confirmation", None)
            if pending_future_window:
                return _finalize_confirmation(state, event_entry, pending_future_window)

    user_info = state.user_info or {}

    # If the current message contains an explicit date (e.g., "change to 2026-02-28"),
    # skip range_pending check and try to confirm that date directly
    message_has_explicit_date = bool(requested_client_dates)
    # D9: Use extracted function
    range_pending = False if message_has_explicit_date else range_query_pending(user_info, event_entry)

    window = None if range_pending else _resolve_confirmation_window(state, event_entry)
    if window is None:
        result = _present_candidate_dates(
            state,
            event_entry,
            requested_client_dates=requested_client_dates,
        )
        return _maybe_append_general_qna(
            result,
            state,
            event_entry,
            classification,
            thread_id,
            qa_payload,
            requested_client_dates,
            deferred_general_qna,
        )

    if window.partial:
        # D11: Use extracted complete_from_time_hint with explicit time hint
        time_hint = (state.user_info or {}).get("vague_time_of_day") or event_entry.get("vague_time_of_day")
        filled = complete_from_time_hint(window, time_hint)
        if filled:
            window = filled
        else:
            # If room is already locked (detour case), skip time confirmation.
            # Time is handled in Step 3 (room availability), not Step 2.
            locked_room = event_entry.get("locked_room_id")
            if locked_room:
                # Complete the window with default time and proceed
                default_start = time(14, 0)
                default_end = time(22, 0)
                start_iso, end_iso = build_window_iso(window.iso_date, default_start, default_end)
                window = ConfirmationWindow(
                    display_date=window.display_date,
                    iso_date=window.iso_date,
                    start_time="14:00",
                    end_time="22:00",
                    start_iso=start_iso,
                    end_iso=end_iso,
                    inherited_times=True,
                    partial=False,
                    source_message_id=window.source_message_id,
                )
            else:
                return _handle_partial_confirmation(state, event_entry, window)

    pending_window_payload = event_entry.get("pending_date_confirmation")
    if pending_window_payload:
        pending_window = _window_from_payload(pending_window_payload)
        if _is_affirmative_reply(state.message.body or "") and pending_window:
            event_entry.pop("pending_date_confirmation", None)
            return _finalize_confirmation(state, event_entry, pending_window)
        if _message_mentions_new_date(state.message.body or ""):
            event_entry.pop("pending_date_confirmation", None)
        elif pending_window and not window.partial:
            if (
                pending_window.iso_date == window.iso_date
                and pending_window.start_time == window.start_time
                and pending_window.end_time == window.end_time
            ):
                event_entry.pop("pending_date_confirmation", None)
                return _finalize_confirmation(state, event_entry, window)

    reference_day = _reference_date_from_state(state)
    feasible, reason = validate_window(window.iso_date, window.start_time, window.end_time, reference=reference_day)
    if not feasible:
        result = _present_candidate_dates(
            state,
            event_entry,
            reason,
            requested_client_dates=requested_client_dates,
        )
        return _maybe_append_general_qna(
            result,
            state,
            event_entry,
            classification,
            thread_id,
            qa_payload,
            requested_client_dates,
            deferred_general_qna,
        )

    conflict_reason = _calendar_conflict_reason(event_entry, window)
    if conflict_reason:
        event_entry.pop("pending_date_confirmation", None)
        result = _present_candidate_dates(
            state,
            event_entry,
            conflict_reason,
            skip_dates=[window.iso_date],
            focus_iso=window.iso_date,
            requested_client_dates=requested_client_dates,
        )
        return _maybe_append_general_qna(
            result,
            state,
            event_entry,
            classification,
            thread_id,
            qa_payload,
            requested_client_dates,
            deferred_general_qna,
        )

    auto_accept = _should_auto_accept_first_date(event_entry) and not range_pending
    if user_info.get("date") or user_info.get("event_date"):
        auto_accept = True
    if _message_signals_confirmation(state.message.body or "") or auto_accept:
        event_entry.pop("pending_date_confirmation", None)
        return _finalize_confirmation(state, event_entry, window)

    event_entry["pending_date_confirmation"] = _window_payload(window)
    return _prompt_confirmation(state, event_entry, window)


def _present_candidate_dates(
    state: WorkflowState,
    event_entry: dict,
    reason: Optional[str] = None,
    *,
    skip_dates: Optional[Sequence[str]] = None,
    focus_iso: Optional[str] = None,
    requested_client_dates: Optional[Sequence[str]] = None,
) -> GroupResult:
    """[Trigger] Provide five deterministic candidate dates to the client."""

    requested_dates = list(requested_client_dates or _client_requested_dates(state))
    # D-CTX: Use extracted function for parsing requested dates
    requested_date_objs, min_requested_date, preferred_weekdays = parse_requested_dates(requested_dates)
    attempt = _increment_date_attempt(event_entry)
    skip_set = _proposal_skip_dates(event_entry, attempt, skip_dates)
    escalate_to_hil = attempt >= 3
    user_info = state.user_info or {}

    user_text = f"{state.message.subject or ''} {state.message.body or ''}".strip()
    reference_day = _reference_date_from_state(state)

    # D-CTX: Use extracted functions for context resolution
    preferred_weekdays = resolve_weekday_preferences(
        user_text, user_info, event_entry, preferred_weekdays
    )
    fuzzy_candidates = _maybe_fuzzy_friday_candidates(user_text, reference_day)

    preferred_room = get_preferred_room(event_entry)
    start_hint, end_hint, start_time_obj, end_time_obj = resolve_time_hints(user_info)
    start_pref = start_hint or "18:00"
    end_pref = end_hint or "22:00"

    # D-CTX: Use extracted functions for anchor and limits
    anchor, anchor_dt = resolve_anchor_date(user_text, reference_day, requested_dates, focus_iso)
    limit, collection_cap = calculate_collection_limits(reason, attempt, preferred_weekdays)

    formatted_dates: List[str] = []
    seen_iso: set[str] = set()
    busy_skipped: set[str] = set()
    event_entry.pop("pending_future_confirmation", None)

    # D10: Use extracted resolve_week_scope from candidate_dates.py
    week_scope = None if attempt > 1 else resolve_week_scope(user_info, event_entry, reference_day)
    week_label_value: Optional[str] = None
    if not preferred_weekdays and week_scope:
        preferred_weekdays = _weekday_indices_from_hint(week_scope.get("weekdays_hint"))

    if week_scope:
        limit = min(len(week_scope["dates"]), max(limit, 5))

    if week_scope:
        # D7: Use extracted collection function
        formatted_dates, seen_iso, busy_skipped = collect_candidates_from_week_scope(
            week_scope,
            skip_set=skip_set,
            min_requested_date=min_requested_date,
            preferred_room=preferred_room,
            start_time_obj=start_time_obj,
            end_time_obj=end_time_obj,
        )
        week_label_value = week_scope["label"]
        event_entry["week_index"] = week_scope["week_index"]
        event_entry["weekdays_hint"] = list(week_scope.get("weekdays_hint") or [])
        event_entry["window_scope"] = {
            "month": week_scope["month_label"],
            "week_index": week_scope["week_index"],
            "weekdays_hint": list(week_scope.get("weekdays_hint") or []),
        }
        update_event_metadata(
            event_entry,
            week_index=week_scope["week_index"],
            weekdays_hint=list(week_scope.get("weekdays_hint") or []),
            window_scope=event_entry["window_scope"],
        )
    elif fuzzy_candidates:
        # D7: Use extracted collection function
        formatted_dates, seen_iso, busy_skipped = collect_candidates_from_fuzzy(
            fuzzy_candidates,
            skip_set=skip_set,
            seen_iso=seen_iso,
            min_requested_date=min_requested_date,
            preferred_room=preferred_room,
            start_time_obj=start_time_obj,
            end_time_obj=end_time_obj,
        )
    else:
        constraints_for_window = {
            "vague_month": user_info.get("vague_month") or event_entry.get("vague_month"),
            "weekday": user_info.get("vague_weekday") or event_entry.get("vague_weekday"),
            "time_of_day": user_info.get("vague_time_of_day") or event_entry.get("vague_time_of_day"),
        }
        window_hints = _resolve_window_hints(constraints_for_window, state)
        strict_window = _has_window_constraints(window_hints)
        if strict_window:
            hinted_dates = _candidate_dates_for_constraints(
                state,
                constraints_for_window,
                limit=limit,
                window_hints=window_hints,
                strict=attempt == 1,
            )
            for iso_value in hinted_dates:
                if (
                    not iso_value
                    or iso_value in seen_iso
                    or iso_value in skip_set
                    or _iso_date_is_past(iso_value)
                ):
                    continue
                candidate_dt = _safe_parse_iso_date(iso_value)
                if min_requested_date and candidate_dt and candidate_dt < min_requested_date:
                    continue
                if not _candidate_is_calendar_free(preferred_room, iso_value, start_time_obj, end_time_obj):
                    busy_skipped.add(iso_value)
                    continue
                seen_iso.add(iso_value)
                formatted_dates.append(iso_value)

        days_ahead = min(180, 45 + (attempt - 1) * 30)
        max_results = 5 if attempt <= 2 else 7

        candidate_dates_ddmmyyyy: List[str] = suggest_dates(
            state.db,
            preferred_room=preferred_room,
            start_from_iso=anchor_dt.isoformat() if anchor_dt else state.message.ts,
            days_ahead=days_ahead,
            max_results=max_results,
        )
        trace_db_read(
            _thread_id(state),
            "Step2_Date",
            "db.dates.next5",
            {
                "preferred_room": preferred_room,
                "anchor": anchor_dt.isoformat() if anchor_dt else state.message.ts,
                "result_count": len(candidate_dates_ddmmyyyy),
                "days_ahead": days_ahead,
            },
        )

        for raw in candidate_dates_ddmmyyyy:
            iso_value = to_iso_date(raw)
            if not iso_value:
                continue
            if (
                _iso_date_is_past(iso_value)
                or iso_value in seen_iso
                or iso_value in skip_set
            ):
                continue
            candidate_dt = _safe_parse_iso_date(iso_value)
            if min_requested_date and candidate_dt and candidate_dt < min_requested_date:
                continue
            if not _candidate_is_calendar_free(preferred_room, iso_value, start_time_obj, end_time_obj):
                busy_skipped.add(iso_value)
                continue
            seen_iso.add(iso_value)
            formatted_dates.append(iso_value)

        if len(formatted_dates) < limit:
            skip_dates_for_next = {_safe_parse_iso_date(iso) for iso in seen_iso.union(skip_set)}
            supplemental = next_five_venue_dates(
                anchor_dt,
                skip_dates={dt for dt in skip_dates_for_next if dt is not None},
                count=max(limit * 2, 10 if attempt > 1 else 5),
            )
            trace_db_read(
                _thread_id(state),
                "Step2_Date",
                "db.dates.next5",
                {
                    "preferred_room": preferred_room,
                    "anchor": anchor_dt.isoformat() if anchor_dt else state.message.ts,
                    "result_count": len(supplemental),
                    "days_ahead": days_ahead,
                },
            )
            for candidate in supplemental:
                iso_candidate = candidate if isinstance(candidate, str) else candidate.isoformat()
                if (
                    iso_candidate in seen_iso
                    or iso_candidate in skip_set
                    or _iso_date_is_past(iso_candidate)
                ):
                    continue
                candidate_dt = _safe_parse_iso_date(iso_candidate)
                if min_requested_date and candidate_dt and candidate_dt < min_requested_date:
                    continue
                if not _candidate_is_calendar_free(preferred_room, iso_candidate, start_time_obj, end_time_obj):
                    busy_skipped.add(iso_candidate)
                    continue
                seen_iso.add(iso_candidate)
                formatted_dates.append(iso_candidate)
                if len(formatted_dates) >= collection_cap:
                    break

    prioritized_dates: List[str] = []
    weekday_shortfall = False
    preferred_weekday_list = sorted(preferred_weekdays)
    if preferred_weekdays:
        weekday_cache: Dict[str, Optional[int]] = {}

        def _weekday_for(iso_value: str) -> Optional[int]:
            if iso_value not in weekday_cache:
                parsed = _safe_parse_iso_date(iso_value)
                weekday_cache[iso_value] = parsed.weekday() if parsed else None
            return weekday_cache[iso_value]

        formatted_dates = sorted(
            formatted_dates,
            key=lambda iso: (
                0 if (_weekday_for(iso) in preferred_weekdays) else 1,
                iso,
            ),
        )
        prioritized_matches = [iso for iso in formatted_dates if _weekday_for(iso) in preferred_weekdays]
        prioritized_rest = [iso for iso in formatted_dates if _weekday_for(iso) not in preferred_weekdays]
        if not prioritized_matches:
            supplemental_matches = _collect_preferred_weekday_alternatives(
                start_from=min_requested_date or reference_day,
                preferred_weekdays=preferred_weekday_list,
                preferred_room=preferred_room,
                start_time=start_time_obj,
                end_time=end_time_obj,
                skip_dates=skip_set.union(busy_skipped),
                existing=seen_iso,
                limit=collection_cap,
            )
            if supplemental_matches:
                for iso_value in supplemental_matches:
                    if iso_value in seen_iso:
                        continue
                    seen_iso.add(iso_value)
                    formatted_dates.append(iso_value)
                formatted_dates = sorted(
                    formatted_dates,
                    key=lambda iso: (
                        0 if (_weekday_for(iso) in preferred_weekdays) else 1,
                        iso,
                    ),
                )
                prioritized_matches = [iso for iso in formatted_dates if _weekday_for(iso) in preferred_weekdays]
                prioritized_rest = [iso for iso in formatted_dates if _weekday_for(iso) not in preferred_weekdays]
        if prioritized_matches:
            formatted_dates = prioritized_matches
            prioritized_dates = prioritized_matches
        else:
            formatted_dates = prioritized_rest
            prioritized_dates = prioritized_rest
            weekday_shortfall = bool(formatted_dates)
    else:
        formatted_dates = sorted(formatted_dates)
        prioritized_dates = list(formatted_dates)

    if fuzzy_candidates:
        formatted_dates = formatted_dates[:4]
    formatted_dates = formatted_dates[:limit]
    unavailable_requested = [iso for iso in requested_dates if iso not in seen_iso]

    if start_pref and end_pref:
        slot_text = f"{start_pref}–{end_pref}"
    elif start_pref:
        slot_text = start_pref
    elif end_pref:
        slot_text = end_pref
    else:
        slot_text = "18:00–22:00"

    if week_scope and week_scope.get("weekdays_hint"):
        hint_order = []
        for hint in week_scope["weekdays_hint"]:
            try:
                hint_order.append(int(hint))
            except (TypeError, ValueError):
                continue
        if hint_order:
            prioritized: List[str] = []
            remaining = list(formatted_dates)
            for day_hint in hint_order:
                for iso_value in list(remaining):
                    try:
                        day_val = datetime.fromisoformat(iso_value).day
                    except ValueError:
                        continue
                    if day_val == day_hint and iso_value not in prioritized:
                        prioritized.append(iso_value)
                        remaining.remove(iso_value)
            formatted_dates = prioritized + [val for val in formatted_dates if val not in prioritized]

    greeting = _compose_greeting(state)
    message_lines: List[str] = [greeting, ""]

    original_requested = parse_first_date(
        user_text,
        fallback_year=reference_day.year,
        reference=reference_day,
    )
    future_suggestion = None
    future_display: Optional[str] = None
    if original_requested and original_requested < reference_day:
        future_suggestion = _next_matching_date(original_requested, reference_day)

    if reason and "past" in reason.lower() and future_suggestion and original_requested:
        # D-PRES: Use extracted function for past date message
        past_msg, original_display, future_display = build_past_date_message(
            original_requested, future_suggestion
        )
        message_lines.append(past_msg)

        future_iso = future_suggestion.isoformat()
        start_iso_val = end_iso_val = None
        if start_hint and end_hint:
            try:
                start_iso_val, end_iso_val = build_window_iso(
                    future_iso,
                    _to_time(start_hint),
                    _to_time(end_hint),
                )
            except ValueError:
                start_iso_val = end_iso_val = None
        pending_window = ConfirmationWindow(
            display_date=future_display,
            iso_date=future_iso,
            start_time=start_hint,
            end_time=end_hint,
            start_iso=start_iso_val,
            end_iso=end_iso_val,
            inherited_times=False,
            partial=not (start_hint and end_hint),
            source_message_id=state.message.msg_id,
        )
        event_entry["pending_future_confirmation"] = _window_payload(pending_window)
        # Don't add redundant phrases - the date suggestion above is sufficient
    elif reason:
        # D-PRES: Use extracted function for reason message
        message_lines.extend(build_reason_message(reason))
    else:
        # D-PRES: Use extracted function for attempt message
        message_lines.append(build_attempt_message(attempt))

    if unavailable_requested:
        # D-PRES: Use extracted function for unavailable message
        message_lines.extend(build_unavailable_message(unavailable_requested))
    if weekday_shortfall and formatted_dates:
        message_lines.append(
            "I couldn't find a free Thursday or Friday in that range. These are the closest available slots right now."
        )

    if future_suggestion:
        target_month = future_suggestion.strftime("%Y-%m")
        filtered_dates = [iso for iso in formatted_dates if iso.startswith(target_month)]
        if filtered_dates:
            formatted_dates = filtered_dates[:4]
            prioritized_dates = []  # Clear - we're using target month dates now
        else:
            # No dates found in the target month - collect dates starting from future_suggestion
            # This happens when past date is requested and initial collection didn't reach target month
            future_anchor = datetime.combine(future_suggestion, time(hour=12))
            skip_parsed = {_safe_parse_iso_date(iso) for iso in seen_iso if iso}
            supplemental_for_month = next_five_venue_dates(
                future_anchor,
                skip_dates={dt for dt in skip_parsed if dt is not None},
                count=5,
            )
            month_dates = []
            for iso_candidate in supplemental_for_month:
                if iso_candidate.startswith(target_month):
                    if not _candidate_is_calendar_free(preferred_room, iso_candidate, start_time_obj, end_time_obj):
                        continue
                    month_dates.append(iso_candidate)
            if month_dates:
                formatted_dates = month_dates[:4]
                prioritized_dates = []  # Clear - we're using target month dates now

    sample_dates = prioritized_dates[:4] if prioritized_dates else formatted_dates[:4]
    if week_scope:
        sample_dates = list(formatted_dates)
    day_line, day_year = _format_day_list(sample_dates)
    month_hint_value = (
        week_scope["month_label"]
        if week_scope
        else user_info.get("vague_month") or event_entry.get("vague_month")
    )
    date_header_label = _date_header_label(month_hint_value, week_label_value)
    weekday_hint_value = user_info.get("vague_weekday") or event_entry.get("vague_weekday")
    weekday_label = None
    if not week_scope:
        # D10: Use extracted preferred_weekday_label from candidate_dates.py
        preferred_label = preferred_weekday_label(preferred_weekday_list, sample_dates)
        if preferred_label:
            weekday_label = preferred_label
        elif len(preferred_weekdays) == 1:
            weekday_label = _weekday_label_from_dates(sample_dates, _pluralize_weekday_hint(weekday_hint_value))
    parsed_sample_dates = [_safe_parse_iso_date(iso_value) for iso_value in sample_dates]
    sample_month_pairs = {(value.year, value.month) for value in parsed_sample_dates if value}
    sample_years = {value.year for value in parsed_sample_dates if value}
    multi_month = len(sample_month_pairs) > 1 or len(sample_years) > 1
    month_for_line: Optional[str] = None
    if parsed_sample_dates and multi_month:
        formatted_labels = [
            value.strftime("%d %b %Y") for value in parsed_sample_dates if value
        ]
        if formatted_labels:
            message_lines.append("")
            label_prefix = weekday_label or "Dates"
            message_lines.append(f"{label_prefix} coming up: {', '.join(formatted_labels)}")
            message_lines.append("")
            date_header_label = f"{label_prefix} coming up"
    else:
        month_for_line = week_scope["label"] if week_scope else _month_label_from_dates(
            sample_dates, month_hint_value
        )
        if day_line and month_for_line and day_year:
            message_lines.append("")
            if week_scope:
                message_lines.append(
                    f"Dates available in {_format_label_text(week_scope['label'])} {day_year}: {day_line}"
                )
            else:
                label_prefix = weekday_label or "Dates"
                message_lines.append(
                    f"{label_prefix} available in {_format_label_text(month_for_line)} {day_year}: {day_line}"
                )
            message_lines.append("")

    _append_menu_options_if_requested(state, message_lines, month_hint_value or month_for_line)

    # Show available dates in a friendly format
    if formatted_dates:
        message_lines.append("")
        message_lines.append("Here are some dates that work:")
        for iso_value in formatted_dates[:5]:
            message_lines.append(f"- {iso_value} {slot_text}")
    else:
        message_lines.append("")
        message_lines.append("I couldn't find suitable slots within the next 60 days, but I'm still looking.")

    # D-PRES: Next step guidance via extracted function
    message_lines.append("")
    message_lines.append(build_closing_prompt(future_display))
    prompt = "\n".join(message_lines)

    weekday_hint = weekday_hint_value
    time_hint = user_info.get("vague_time_of_day") or event_entry.get("vague_time_of_day")
    time_display = str(time_hint).strip().capitalize() if time_hint else slot_text

    if week_scope and week_scope.get("weekdays_hint"):
        hint_order = []
        for hint in week_scope["weekdays_hint"]:
            try:
                hint_order.append(int(hint))
            except (TypeError, ValueError):
                continue
        if hint_order:
            prioritized: List[str] = []
            remaining = list(formatted_dates)
            for day_hint in hint_order:
                for iso_value in list(remaining):
                    try:
                        day_val = datetime.fromisoformat(iso_value).day
                    except ValueError:
                        continue
                    if day_val == day_hint and iso_value not in prioritized:
                        prioritized.append(iso_value)
                        remaining.remove(iso_value)
            formatted_dates = prioritized + [val for val in formatted_dates if val not in prioritized]
    # D-PRES: Use extracted functions for table/actions building
    table_rows = build_date_table_rows(formatted_dates, time_display, limit=5)
    actions_payload = build_date_actions(formatted_dates, time_display, limit=5)
    label_base = build_table_label(
        weekday_label, month_for_line, date_header_label, time_hint, time_display
    )

    _trace_candidate_gate(_thread_id(state), formatted_dates[:5])

    # D-PRES: Universal Verbalizer via extracted function
    participants = _extract_participants_from_state(state)
    body_markdown = verbalize_candidate_message(prompt, participants, formatted_dates)

    # D-PRES: Use extracted function for draft assembly
    headers = ["Availability overview"]
    if date_header_label:
        headers.append(date_header_label)
    if escalate_to_hil:
        headers.append("Manual follow-up required")

    draft_message = assemble_candidate_draft(
        body_markdown=body_markdown,
        formatted_dates=formatted_dates,
        table_rows=table_rows,
        actions_payload=actions_payload,
        label_base=label_base,
        headers=headers,
        escalate_to_hil=escalate_to_hil,
    )
    thread_state_label = draft_message["thread_state"]
    if actions_payload:
        event_entry["candidate_dates"] = [action["date"] for action in actions_payload]
    history = _update_proposal_history(event_entry, event_entry.get("candidate_dates") or formatted_dates[:5])
    state.add_draft_message(draft_message)

    # Check for secondary Q&A types (catering_for, products_for, etc.) and append router content
    classification = state.extras.get("_general_qna_classification") or {}
    secondary_types = list(classification.get("secondary") or [])
    router_types = {"catering_for", "products_for", "rooms_by_feature", "room_features", "free_dates", "parking_policy", "site_visit_overview"}
    router_applicable = bool(set(secondary_types) & router_types)

    if router_applicable:
        message = state.message
        msg_payload = {
            "subject": (message.subject if message else "") or "",
            "body": (message.body if message else "") or "",
            "thread_id": state.thread_id,
        }
        router_result = route_general_qna(
            msg_payload,
            event_entry,
            event_entry,
            None,  # db not needed for catering/products router responses
            classification,
        )
        router_blocks = router_result.get("post_step") or router_result.get("pre_step") or []
        if router_blocks:
            router_body = router_blocks[0].get("body", "")
            if router_body:
                # Add info link for catering Q&A
                qna_link_suffix = ""
                if "catering_for" in secondary_types:
                    query_params = {"room": event_entry.get("preferred_room") or "general"}
                    snapshot_data = {"catering_options": router_body, "event_id": event_entry.get("event_id")}
                    snapshot_id = create_snapshot(
                        snapshot_type="catering",
                        data=snapshot_data,
                        event_id=event_entry.get("event_id"),
                        params=query_params,
                    )
                    qna_link = generate_qna_link("Catering", query_params=query_params, snapshot_id=snapshot_id)
                    qna_link_suffix = f"\n\nFull menu details: {qna_link}"
                # Append router Q&A content to the draft message body
                original_body = draft_message.get("body", "")
                draft_message["body"] = f"{original_body}\n\n---\n\n{router_body}{qna_link_suffix}"
                draft_message["body_markdown"] = draft_message["body"]
                draft_message["router_qna_appended"] = True

    update_event_metadata(
        event_entry,
        thread_state=thread_state_label,
        current_step=2,
        candidate_dates=event_entry.get("candidate_dates"),
        date_proposal_attempts=attempt,
        date_proposal_history=history,
    )
    write_stage(event_entry, current_step=WorkflowStep.STEP_2, subflow_group="date_confirmation")
    state.set_thread_state(thread_state_label)
    state.extras["persist"] = True
    _emit_step2_snapshot(
        state,
        event_entry,
        extra={
            "candidate_dates": formatted_dates[:5],
            "slot_text": slot_text,
            "attempt": attempt,
            "hil_escalated": escalate_to_hil,
            "calendar_omitted": sorted(busy_skipped),
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "candidate_dates": formatted_dates[:5],
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "date_proposal_attempts": attempt,
        "hil_escalated": escalate_to_hil,
        "calendar_skipped": sorted(busy_skipped),
        "answered_question_first": True,
    }
    payload["actions"] = list(actions_payload) if actions_payload else [{"type": "send_reply"}]
    gatekeeper = refresh_gatekeeper(event_entry)
    state.telemetry.answered_question_first = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    message_text = f"{state.message.subject or ''} {state.message.body or ''}"
    lowered_msg = message_text.lower()
    question_triggers = (
        "?" in message_text,
        "please advise" in lowered_msg,
        "could you" in lowered_msg,
        "can you" in lowered_msg,
        "would you" in lowered_msg,
        "let me know" in lowered_msg,
    )
    if any(question_triggers) or state.extras.get("general_qna_detected"):
        state.intent_detail = "event_intake_with_question"
    elif not state.intent_detail:
        state.intent_detail = "event_intake"
    return GroupResult(action="date_options_proposed", payload=payload, halt=True)


# D13c: _should_auto_accept_first_date moved to confirmation.py
# D13b: _preferred_room moved to calendar_checks.py


def _resolve_confirmation_window(state: WorkflowState, event_entry: dict) -> Optional[ConfirmationWindow]:
    """Resolve the requested window from the latest client message."""

    user_info = state.user_info or {}
    body_text = state.message.body or ""
    subject_text = state.message.subject or ""

    reference_day = _reference_date_from_state(state)
    # D8: Use extracted function
    display_date, iso_date = determine_date(
        user_info,
        body_text,
        subject_text,
        event_entry,
        reference_day,
    )
    if not display_date or not iso_date:
        return None

    start_time = _normalize_time_value(user_info.get("start_time"))
    end_time = _normalize_time_value(user_info.get("end_time"))

    inherited_times = False
    start_obj: Optional[time] = None
    end_obj: Optional[time] = None

    if start_time:
        try:
            start_obj = _to_time(start_time)
        except ValueError:
            start_time = None
            start_obj = None
    if end_time:
        try:
            end_obj = _to_time(end_time)
        except ValueError:
            end_time = None
            end_obj = None

    if start_obj and end_obj and start_obj >= end_obj:
        end_time = None
        end_obj = None

    if not (start_time and end_time):
        parsed_start, parsed_end, matched = parse_time_range(body_text)
        if parsed_start and parsed_end:
            start_obj = parsed_start
            end_obj = parsed_end
            start_time = f"{parsed_start.hour:02d}:{parsed_start.minute:02d}"
            end_time = f"{parsed_end.hour:02d}:{parsed_end.minute:02d}"
        elif matched and not start_time:
            start_time = None

    if start_time and not end_time and (body_text or subject_text):
        combined_text = " ".join(value for value in (subject_text, body_text) if value)
        time_tokens: List[str] = []
        for match in re.findall(r"\b(\d{1,2}:\d{2})\b", combined_text):
            normalized_token = _normalize_time_value(match)
            if normalized_token and normalized_token not in time_tokens:
                time_tokens.append(normalized_token)
        if time_tokens:
            if start_time and not start_obj:
                try:
                    start_obj = _to_time(start_time)
                except ValueError:
                    start_obj = None
            chosen_token: Optional[str] = None
            chosen_obj: Optional[time] = None
            for token in time_tokens:
                if start_time and token == start_time:
                    continue
                try:
                    candidate_obj = _to_time(token)
                except ValueError:
                    continue
                if start_obj and candidate_obj <= start_obj:
                    continue
                chosen_token = token
                chosen_obj = candidate_obj
                break
            if chosen_obj is None:
                for token in time_tokens:
                    if start_time and token == start_time:
                        continue
                    try:
                        candidate_obj = _to_time(token)
                    except ValueError:
                        continue
                    chosen_token = token
                    chosen_obj = candidate_obj
                    break
            if chosen_token and chosen_obj:
                end_time = chosen_token
                end_obj = chosen_obj

    if not (start_time and end_time):
        # D8: Use extracted function
        fallback = find_existing_time_window(event_entry, iso_date)
        if fallback:
            start_time, end_time = fallback
            inherited_times = True
            try:
                start_obj = _to_time(start_time)
            except (TypeError, ValueError):
                start_obj = None
            try:
                end_obj = _to_time(end_time)
            except (TypeError, ValueError):
                end_obj = None

    if start_obj and end_obj and start_obj >= end_obj:
        end_time = None
        end_obj = None

    if start_time and not start_obj:
        try:
            start_obj = _to_time(start_time)
        except ValueError:
            start_obj = None
            start_time = None
    if end_time and not end_obj:
        try:
            end_obj = _to_time(end_time)
        except ValueError:
            end_obj = None
            end_time = None

    # [FIX] Infer 4-hour default duration when only start time is provided
    # This prevents the loop of repeatedly asking for time when user provides single time
    if start_obj and not end_obj:
        # Check if we're already in a pending_time_request loop for this date
        pending = event_entry.get("pending_time_request") or {}
        if pending.get("iso_date") == iso_date:
            # Already asked for time once - infer 4-hour default duration
            from datetime import timedelta
            default_duration_hours = 4
            start_dt = datetime.combine(datetime.today(), start_obj)
            end_dt = start_dt + timedelta(hours=default_duration_hours)
            end_obj = end_dt.time()
            end_time = f"{end_obj.hour:02d}:{end_obj.minute:02d}"
            logger.debug("[Step2][TIME_INFER] Single time %s detected, inferring end_time=%s (4-hour default)",
                        start_time, end_time)

    if start_time:
        user_info["start_time"] = start_time
    elif "start_time" in user_info:
        user_info.pop("start_time", None)
    if end_time:
        user_info["end_time"] = end_time
    elif "end_time" in user_info:
        user_info.pop("end_time", None)

    partial = not (start_time and end_time)
    start_iso = end_iso = None
    if start_obj and end_obj:
        start_iso, end_iso = build_window_iso(iso_date, start_obj, end_obj)

    return ConfirmationWindow(
        display_date=display_date,
        iso_date=iso_date,
        start_time=start_time,
        end_time=end_time,
        start_iso=start_iso,
        end_iso=end_iso,
        inherited_times=inherited_times,
        partial=partial,
        source_message_id=state.message.msg_id,
    )


def _handle_partial_confirmation(
    state: WorkflowState,
    event_entry: dict,
    window: ConfirmationWindow,
) -> GroupResult:
    """Persist the date and request a time clarification without stalling the flow."""

    # [FIX] Loop detection: If we've already asked for time on this date, use defaults
    pending = event_entry.get("pending_time_request") or {}
    if pending.get("iso_date") == window.iso_date:
        # Check for loop - if pending was set recently and we're still partial, break the loop
        time_request_count = pending.get("_request_count", 0) + 1
        if time_request_count >= 2:
            # Already asked twice - use default time window
            logger.debug("[Step2][LOOP_BREAK] Time request loop detected for %s, using default window",
                        window.display_date)
            window = ConfirmationWindow(
                display_date=window.display_date,
                iso_date=window.iso_date,
                start_time="14:00",
                end_time="18:00",
                start_iso=None,  # Will be computed downstream
                end_iso=None,
                inherited_times=False,
                partial=False,  # No longer partial!
                source_message_id=window.source_message_id,
            )
            # Clean up pending state
            event_entry.pop("pending_time_request", None)
            # Return successful confirmation instead of asking again
            state.user_info["event_date"] = window.display_date
            state.user_info["date"] = window.iso_date
            state.user_info["start_time"] = window.start_time
            state.user_info["end_time"] = window.end_time
            # Continue with full confirmation flow - return None to let caller proceed
            return None  # Signal to caller to use non-partial path

    _reset_date_attempts(event_entry)

    event_entry.setdefault("event_data", {})["Event Date"] = window.display_date
    # D8: Use extracted function
    set_pending_time_state(event_entry, window)
    # Track request count for loop detection
    event_entry["pending_time_request"]["_request_count"] = pending.get("_request_count", 0) + 1

    state.user_info["event_date"] = window.display_date
    state.user_info["date"] = window.iso_date

    prompt = _with_greeting(
        state,
        f"Great, I've noted **{window.display_date}**. What time works best for you? For example, 14:00–18:00 or 18:00–22:00.",
    )
    state.add_draft_message({"body": prompt, "step": 2, "topic": "date_time_clarification"})

    update_event_metadata(
        event_entry,
        chosen_date=window.display_date,
        date_confirmed=False,
        thread_state="Awaiting Client Response",
        current_step=2,
    )
    write_stage(event_entry, current_step=WorkflowStep.STEP_2, subflow_group="date_confirmation")

    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    _emit_step2_snapshot(
        state,
        event_entry,
        extra={
            "pending_time": True,
            "proposed_date": window.display_date,
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "pending_time": True,
        "event_date": window.display_date,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "answered_question_first": True,
    }
    gatekeeper = refresh_gatekeeper(event_entry)
    state.telemetry.answered_question_first = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    return GroupResult(action="date_time_clarification", payload=payload, halt=True)


def _prompt_confirmation(
    state: WorkflowState,
    event_entry: dict,
    window: ConfirmationWindow,
) -> GroupResult:
    formatted_window = _format_window(window)
    prompt = _with_greeting(
        state,
        f"**{formatted_window}** works on our end! Should I check room availability for this time? Just say yes, or let me know if you'd prefer a different date or time.",
    )

    draft_message = {
        "body": prompt,
        "step": 2,
        "topic": "date_confirmation_pending",
        "proposed_date": window.display_date,
        "proposed_time": f"{window.start_time or ''}–{window.end_time or ''}".strip("–"),
    }
    state.add_draft_message(draft_message)

    update_event_metadata(
        event_entry,
        current_step=2,
        thread_state="Awaiting Client Response",
        date_confirmed=False,
    )
    write_stage(event_entry, current_step=WorkflowStep.STEP_2, subflow_group="date_confirmation")
    state.set_thread_state("Awaiting Client Response")
    state.extras["persist"] = True
    _emit_step2_snapshot(
        state,
        event_entry,
        extra={
            "pending_confirmation": True,
            "proposed_date": window.display_date,
        },
    )

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "pending_confirmation": True,
        "proposed_date": window.iso_date,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": True,
        "answered_question_first": True,
    }
    gatekeeper = refresh_gatekeeper(event_entry)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    state.telemetry.answered_question_first = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    return GroupResult(action="date_confirmation_pending", payload=payload, halt=True)


def _finalize_confirmation(
    state: WorkflowState,
    event_entry: dict,
    window: ConfirmationWindow,
) -> GroupResult:
    """Persist the requested window and trigger availability."""

    _reset_date_attempts(event_entry)

    thread_id = _thread_id(state)
    if isinstance(window, str):
        try:
            parsed_date = datetime.strptime(window, "%Y-%m-%d")
            display_date = parsed_date.strftime("%d.%m.%Y")
            iso_date = window
        except ValueError:
            display_date = window
            iso_date = to_iso_date(window) or window
        fallback_window = event_entry.get("requested_window") or {}
        start_time = fallback_window.get("start_time")
        end_time = fallback_window.get("end_time")
        start_iso = fallback_window.get("start")
        end_iso = fallback_window.get("end")
        window = ConfirmationWindow(
            display_date=display_date,
            iso_date=iso_date,
            start_time=start_time,
            end_time=end_time,
            start_iso=start_iso,
            end_iso=end_iso,
            inherited_times=bool(start_time and end_time),
            partial=not (start_time and end_time),
            source_message_id=fallback_window.get("source_message_id"),
        )

    state.event_id = event_entry.get("event_id")
    _clear_step2_hil_tasks(state, event_entry)
    tag_message(event_entry, window.source_message_id)
    event_entry.setdefault("event_data", {})["Event Date"] = window.display_date
    event_entry["event_data"]["Start Time"] = window.start_time
    event_entry["event_data"]["End Time"] = window.end_time

    requirements = dict(event_entry.get("requirements") or {})
    requirements["event_duration"] = {"start": window.start_time, "end": window.end_time}
    new_req_hash = requirements_hash(requirements)

    state.user_info["event_date"] = window.display_date
    state.user_info["date"] = window.iso_date
    state.user_info["start_time"] = window.start_time
    state.user_info["end_time"] = window.end_time

    previous_window = event_entry.get("requested_window") or {}
    new_hash = _window_hash(window.iso_date, window.start_iso, window.end_iso)
    reuse_previous = previous_window.get("hash") == new_hash

    requested_payload = {
        "display_date": window.display_date,
        "date_iso": window.iso_date,
        "start_time": window.start_time,
        "end_time": window.end_time,
        "start": window.start_iso,
        "end": window.end_iso,
        "tz": get_timezone(),
        "hash": new_hash,
        "times_inherited": window.inherited_times,
        "source_message_id": window.source_message_id,
        "updated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "cached": reuse_previous,
    }
    event_entry["requested_window"] = requested_payload
    event_entry.pop("pending_time_request", None)

    update_event_metadata(
        event_entry,
        chosen_date=window.display_date,
        date_confirmed=True,
        requirements=requirements,
        requirements_hash=new_req_hash,
        thread_state="In Progress",
    )
    if event_entry.get("calendar_event_id"):
        try:
            update_calendar_event_status(event_entry.get("event_id", ""), event_entry.get("status", ""), "lead")
            from utils.calendar_events import create_calendar_event

            create_calendar_event(event_entry, "lead")
        except Exception as exc:  # pragma: no cover - best-effort calendar logging
            logger.warning("Failed to update calendar event: %s", exc)
    if not reuse_previous:
        # Invalidate room_eval_hash so Step 3 re-verifies room availability
        # on the new date. KEEP locked_room_id so Step 3 can fast-skip if
        # the same room is still available on the new date.
        update_event_metadata(
            event_entry,
            room_eval_hash=None,
            # NOTE: Do NOT clear locked_room_id here - Step 3 will verify
            # availability and clear it only if the room is no longer available
        )

    # Always proceed to Step 3 (Room Availability) after confirming a date.
    #
    # If a previous step (e.g. Step 5) triggered a detour and the window is
    # unchanged, Step 3's own hash + caller_step guards will immediately skip
    # reevaluation and route control back to the caller. This keeps the
    # detour semantics intact while avoiding stale caller_step values causing
    # Step 2 to jump directly to unrelated steps.
    next_step = 3

    _emit_step2_snapshot(
        state,
        event_entry,
        extra={
            "confirmed_date": window.display_date,
            "date_confirmed": True,
        },
    )
    append_audit_entry(event_entry, 2, next_step, "date_confirmed")
    update_event_metadata(event_entry, current_step=next_step)
    try:
        next_stage = WorkflowStep(f"step_{next_step}")
    except ValueError:
        next_stage = WorkflowStep.STEP_3
    write_stage(event_entry, current_step=next_stage, subflow_group=default_subflow(next_stage))

    if state.client and state.event_id:
        link_event_to_client(state.client, state.event_id)

    # D8: Use extracted function
    record_confirmation_log(event_entry, state, window, reuse_previous)

    state.set_thread_state("In Progress")
    state.current_step = next_step
    # Preserve caller_step so Step 3 can optionally hand control back.
    state.caller_step = event_entry.get("caller_step")
    state.subflow_group = default_subflow(next_stage)
    state.extras["persist"] = True

    payload = {
        "client_id": state.client_id,
        "event_id": state.event_id,
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "event_date": window.display_date,
        "requested_window": requested_payload,
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "next_step": next_step,
        "cache_reused": reuse_previous,
        "context": state.context_snapshot,
        "persisted": True,
        "answered_question_first": True,
    }
    payload["actions"] = [{"type": "send_reply"}]
    gatekeeper = refresh_gatekeeper(event_entry)
    state.telemetry.answered_question_first = True
    state.telemetry.gatekeeper_passed = dict(gatekeeper)
    payload["gatekeeper_passed"] = dict(gatekeeper)
    state.intent_detail = "event_update"

    promote_fields(
        state,
        event_entry,
        {
            ("date",): window.iso_date,
            ("event_date",): window.display_date,
            ("start_time",): window.start_time,
            ("end_time",): window.end_time,
        },
        remove_deferred=["date_confirmation"],
    )
    if event_entry.get("caller_step") is not None:
        # Prevent downstream steps from re-detecting the same date change
        # within this routing loop (e.g., Step 4 looping back to Step 2).
        state.extras["detour_change_applied"] = "date"
        # BUG-024 FIX: Also persist to event_entry for acknowledgment in step5
        # The flag in state.extras is lost between routing loops
        event_entry["_pending_date_change_ack"] = True
        state.extras["persist"] = True

    autorun_failed = False
    autorun_result: Optional[GroupResult] = None
    autorun_error: Optional[Dict[str, Any]] = None
    if next_step == 3:
        try:
            from workflows.steps.step3_room_availability.trigger.process import process as room_process

            room_result = room_process(state)
            if isinstance(room_result.payload, dict):
                room_result.payload.setdefault("confirmed_date", window.display_date)
                room_result.payload.setdefault("gatekeeper_passed", dict(gatekeeper))
            autorun_result = room_result
        except Exception as exc:  # pragma: no cover - defensive guard
            autorun_failed = True
            state.extras["room_autorun_failed"] = True
            autorun_error = {
                "type": exc.__class__.__name__,
                "message": str(exc),
            }
            trace_marker(
                thread_id,
                "STEP3_AUTORUN_FAILED",
                detail=str(exc),
                data={
                    "type": exc.__class__.__name__,
                    "event_id": state.event_id,
                },
                owner_step="Step2_Date",
            )

    participants = _extract_participants_from_state(state)
    noted_line = (
        f"Perfect! I've locked in **{window.display_date}** for **{participants} guests**."
        if participants
        else f"Perfect! **{window.display_date}** is confirmed."
    )
    follow_up_line = "Let me find the best rooms for you now."
    ack_body, ack_headers = format_sections_with_headers(
        [("Next step", [noted_line, follow_up_line])]
    )
    if not autorun_result:
        state.add_draft_message(
            {
                "body": ack_body,
                "body_markdown": ack_body,
                "step": next_step,
                "topic": "date_confirmed",
                "headers": ack_headers,
            }
        )
    if autorun_failed:
        payload["room_autorun_failed"] = True
        if autorun_error:
            payload["room_autorun_error"] = autorun_error
        return GroupResult(action="date_confirmed", payload=payload, halt=False)
    if autorun_result:
        if isinstance(autorun_result.payload, dict):
            autorun_result.payload.setdefault("confirmed_date", window.display_date)
            autorun_result.payload.setdefault("gatekeeper_passed", dict(gatekeeper))
            autorun_result.payload.setdefault("room_autorun", True)
        state.extras["room_autorun_action"] = autorun_result.action
        return autorun_result
    return GroupResult(action="date_confirmed", payload=payload, halt=True)


# D13d: _trace_candidate_gate moved to step2_utils.py


def _clear_step2_hil_tasks(state: WorkflowState, event_entry: dict) -> None:
    """Remove pending Step 2 HIL artifacts once a date is confirmed."""

    pending = event_entry.get("pending_hil_requests") or []
    filtered = [entry for entry in pending if entry.get("step") != 2]
    if len(filtered) != len(pending):
        event_entry["pending_hil_requests"] = filtered
        state.extras["persist"] = True

    tasks = state.db.get("tasks") if state.db else None
    if not tasks:
        return
    changed = False
    for task in tasks:
        if (
            task.get("event_id") == event_entry.get("event_id")
            and task.get("type") == TaskType.DATE_CONFIRMATION_MESSAGE.value
            and task.get("status") == TaskStatus.PENDING.value
        ):
            task["status"] = TaskStatus.DONE.value
            changed = True
    if changed:
        state.extras["persist"] = True


def _apply_step2_hil_decision(state: WorkflowState, event_entry: dict, decision: str) -> GroupResult:
    """Handle HIL approval or rejection for pending date confirmation."""

    pending_window = _window_from_payload(event_entry.get("pending_date_confirmation") or {})
    if not pending_window:
        pending_window = _window_from_payload(event_entry.get("pending_future_confirmation") or {})

    normalized_decision = (decision or "").strip().lower() or "approve"
    if normalized_decision != "approve":
        event_entry.pop("pending_date_confirmation", None)
        event_entry.pop("pending_future_confirmation", None)
        _clear_step2_hil_tasks(state, event_entry)
        draft_message = {
            "body": "Manual review declined. Please advise which alternative dates to offer next.",
            "step": 2,
            "topic": "date_hil_reject",
            "requires_approval": True,
        }
        state.add_draft_message(draft_message)
        update_event_metadata(event_entry, current_step=2, thread_state="Waiting on HIL")
        state.set_thread_state("Waiting on HIL")
        state.extras["persist"] = True
        append_audit_entry(event_entry, 2, 2, "date_hil_rejected")
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
        return GroupResult(action="date_hil_rejected", payload=payload, halt=True)

    if not pending_window:
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "no_pending_date_decision",
            "context": state.context_snapshot,
        }
        return GroupResult(action="date_hil_missing", payload=payload, halt=True)

    event_entry.pop("pending_date_confirmation", None)
    event_entry.pop("pending_future_confirmation", None)
    return _finalize_confirmation(state, event_entry, pending_window)


# D15d: Thin wrapper delegating to step2_state.maybe_general_qa_payload
def _maybe_general_qa_payload(state: WorkflowState) -> Optional[Dict[str, Any]]:
    return _maybe_general_qa_payload_impl(state)
