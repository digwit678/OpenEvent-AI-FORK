from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from workflows.common.requirements import merge_client_profile, requirements_hash
from workflows.common.billing_gate import refresh_billing as _refresh_billing
from .product_ops import (
    apply_product_operations as _apply_product_operations,
    autofill_products_from_preferences as _autofill_products_from_preferences,
    ensure_products_container as _ensure_products_container,
)
from workflows.common.types import GroupResult, WorkflowState
from workflows.io.database import update_event_metadata
from workflows.io.config_store import get_product_autofill_threshold
from workflows.nlu import detect_sequential_workflow_request
from debug.hooks import trace_step, trace_marker
from debug.trace import set_hil_open
from utils.profiler import profile_step
# CQ-3 refactoring: Helpers extracted to helpers.py
from .helpers import (
    _thread_id,
    _normalize_quotes,          # re-export for characterization tests
    _looks_like_offer_acceptance,
    _present_general_room_qna,
)

# Re-exports for process.py backward compatibility
from .compose import build_offer, _record_offer  # noqa: F401
from .offer_summary import compose_offer_summary as _compose_offer_summary  # noqa: F401

# Preconditions (Jan 2026 god-file refactoring)
from .preconditions import (
    evaluate_preconditions as _evaluate_preconditions,
    route_to_owner_step as _route_to_owner_step,
    handle_products_pending as _handle_products_pending,
)

__workflow_role__ = "trigger"


@trace_step("Step4_Offer")
@profile_step("workflow.step4.offer")
def process(state: WorkflowState) -> GroupResult:
    """[Trigger] Run Step 4 — offer preparation and transmission."""

    event_entry = state.event_entry
    if not event_entry:
        payload = {
            "client_id": state.client_id,
            "event_id": None,
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "reason": "missing_event",
            "context": state.context_snapshot,
        }
        return GroupResult(action="offer_missing_event", payload=payload, halt=True)

    previous_step = event_entry.get("current_step") or 3
    state.current_step = 4
    thread_id = _thread_id(state)

    # If an acceptance is already awaiting HIL (step 5), do not emit another offer.
    pending_negotiation = event_entry.get("negotiation_pending_decision")
    pending_hil = [
        req for req in (event_entry.get("pending_hil_requests") or []) if req.get("step") == 5
    ]
    if pending_negotiation or pending_hil:
        state.set_thread_state("Waiting on HIL")
        set_hil_open(thread_id, True)
        payload = {
            "client_id": state.client_id,
            "event_id": event_entry.get("event_id"),
            "intent": state.intent.value if state.intent else None,
            "confidence": round(state.confidence or 0.0, 3),
            "pending_decision": pending_negotiation,
            "thread_state": state.thread_state,
            "context": state.context_snapshot,
        }
        return GroupResult(action="offer_waiting_hil", payload=payload, halt=True)

    # -------------------------------------------------------------------------
    # SITE VISIT HANDLING: If site_visit_state.status == "proposed", route to Step 7
    # Client's date mentions are for site visits, not event date changes
    # -------------------------------------------------------------------------
    visit_state = event_entry.get("site_visit_state") or {}
    if visit_state.get("status") == "proposed":
        # Route to Step 7 for site visit handling
        update_event_metadata(event_entry, current_step=7)
        state.current_step = 7
        state.extras["persist"] = True
        return GroupResult(
            action="route_to_site_visit",
            payload={
                "client_id": state.client_id,
                "event_id": event_entry.get("event_id"),
                "reason": "site_visit_in_progress",
                "persisted": True,
            },
            halt=False,  # Continue to Step 7
        )

    if merge_client_profile(event_entry, state.user_info or {}):
        state.extras["persist"] = True

    if (event_entry.get("billing_requirements") or {}).get("awaiting_billing_for_accept"):
        # Skip billing capture for synthetic deposit payment messages
        # (their body is "I have paid the deposit." which would corrupt billing)
        is_deposit_signal = (state.message.extras or {}).get("deposit_just_paid", False)
        if not is_deposit_signal:
            message_text = (state.message.body or "").strip() if state.message else ""
            if message_text:
                event_entry.setdefault("event_data", {})["Billing Address"] = message_text
                state.extras["persist"] = True

    billing_missing = _refresh_billing(event_entry)
    state.extras["persist"] = True

    # [CONFIRMATION GATE] Stale offer_accepted clearing (BUG-053) + prerequisite checks
    from .confirmation_continuation import handle_confirmation_continuation
    confirmation_halt = handle_confirmation_continuation(state, event_entry, previous_step, thread_id)
    if confirmation_halt is not None:
        return confirmation_halt

    # [CHANGE DETECTION + Q&A + NONSENSE GATE] Run before offer composition
    from .change_routing_step4 import run_change_detection
    change_result = run_change_detection(state, event_entry, thread_id)
    if change_result.halt_result is not None:
        return change_result.halt_result
    classification = change_result.classification
    message_text = change_result.message_text
    normalized_message_text = change_result.normalized_message_text
    user_info = change_result.user_info
    unified_detection = change_result.unified_detection

    # [ACCEPTANCE] Billing gate → deposit gate → HIL routing
    from .acceptance import handle_offer_acceptance
    acceptance_result = handle_offer_acceptance(
        state, event_entry, normalized_message_text, user_info, previous_step, thread_id,
    )
    if acceptance_result is not None:
        return acceptance_result

    # No change detected: check if Q&A should be handled
    # Note: has_offer_update previously used for deferred Q&A - now handled differently

    # -------------------------------------------------------------------------
    # SEQUENTIAL WORKFLOW DETECTION
    # If the client accepts the offer AND asks about next steps (site visit, deposit),
    # that's NOT general Q&A - it's natural workflow continuation.
    # Example: "Accept the offer, when can we do a site visit?"
    # -------------------------------------------------------------------------
    sequential_check = detect_sequential_workflow_request(message_text, current_step=4)
    if sequential_check.get("is_sequential"):
        # Client is accepting offer AND asking about next step - natural flow
        classification["is_general"] = False
        classification["workflow_lookahead"] = sequential_check.get("asks_next_step")
        state.extras["general_qna_detected"] = False
        state.extras["workflow_lookahead"] = sequential_check.get("asks_next_step")
        state.extras["_general_qna_classification"] = classification
        if thread_id:
            trace_marker(
                thread_id,
                "SEQUENTIAL_WORKFLOW",
                detail=f"step4_to_step{sequential_check.get('asks_next_step')}",
                data=sequential_check,
            )

    deferred_general_qna = False
    general_qna_applicable = classification.get("is_general")
    # Skip Q&A when products change was detected - we need to regenerate the offer
    if state.extras.get("products_change_detected"):
        general_qna_applicable = False
        logger.debug("[Step4] Skipping Q&A dispatch - products change detected")

    # [FIX JAN-12-2026] At Step 4, Q&A should be sent SEPARATELY from offer (never in same message).
    # Send Q&A first with requires_approval=False, then continue to generate offer.
    # This ensures: 1) Q&A is answered immediately, 2) Offer goes through HIL approval.
    if general_qna_applicable:
        # Check if we should be generating an offer (room and date confirmed)
        room_locked = bool(event_entry.get("locked_room_id"))
        date_confirmed = event_entry.get("date_confirmed", False)
        should_generate_offer = room_locked and date_confirmed

        if should_generate_offer:
            # Check if this is PURE Q&A (no acceptance signal, no room confirmation this turn)
            # LLM-first: Check unified detection for acceptance signal
            llm_has_acceptance = (
                unified_detection is not None
                and unified_detection.is_acceptance
            )
            text_has_acceptance = _looks_like_offer_acceptance(normalized_message_text)
            has_acceptance = llm_has_acceptance or text_has_acceptance
            # LLM-first: Check unified detection for question signal (fixes BUG-036)
            # Only use question mark as fallback when LLM detection unavailable
            llm_says_question = (
                unified_detection is not None
                and unified_detection.is_question
                and not unified_detection.is_change_request
            )
            question_mark_fallback = unified_detection is None and "?" in message_text
            is_pure_question = llm_says_question or question_mark_fallback
            # Room confirmation prefix indicates room was just confirmed by Step 3 in this turn
            # When present, we should generate the offer (not treat as pure Q&A)
            room_just_confirmed = bool(event_entry.get("room_confirmation_prefix"))

            # Check if we came from a detour (date/room change) - if so, always generate offer
            is_detour_call = event_entry.get("caller_step") is not None

            # Guard: If user is providing contact info, it's NOT pure Q&A
            # e.g., "You can reach Sarah at sarah@acme.com for any questions" provides booking info
            has_contact_info = (
                unified_detection is not None
                and (unified_detection.contact_name or unified_detection.contact_email or unified_detection.contact_phone)
            )

            # Debug logging for QNA_GUARD decision
            logger.debug(
                "[Step4][QNA_GUARD_CHECK] is_question=%s, has_acceptance=%s (llm=%s, text=%s), "
                "room_confirmed=%s, detour=%s, has_contact=%s",
                is_pure_question, has_acceptance, llm_has_acceptance, text_has_acceptance,
                room_just_confirmed, is_detour_call, has_contact_info
            )

            if is_pure_question and not has_acceptance and not room_just_confirmed and not is_detour_call and not has_contact_info:
                # PURE Q&A: Return early - don't generate offer or progress steps
                # E.g., "Does Room A have a projector?" at Step 4 should stay at Step 4
                # But NOT for detour calls - those must regenerate the offer
                logger.info("[Step4][QNA_GUARD] Pure Q&A detected - returning without offer generation")
                result = _present_general_room_qna(state, event_entry, classification, thread_id)
                return result
            elif is_detour_call:
                logger.info("[Step4][DETOUR_BYPASS] Bypassing QNA_GUARD - came from detour (caller=%s)", event_entry.get("caller_step"))
            elif has_contact_info:
                logger.info("[Step4][CONTACT_BYPASS] Bypassing QNA_GUARD - contact info provided")
            else:
                # HYBRID: Room confirmation + Q&A, or acceptance + Q&A
                # E.g., "Room B looks perfect. Do you offer catering?" - confirm room, answer Q&A, then offer
                # E.g., "Yes I accept. What's your parking policy?" - answer Q&A then process acceptance
                if room_just_confirmed:
                    logger.info("[Step4][HYBRID] Room just confirmed - generating offer with Q&A")
                qa_result = _present_general_room_qna(state, event_entry, classification, thread_id)
                if qa_result and state.draft_messages:
                    for draft in state.draft_messages:
                        draft["requires_approval"] = False
                    logger.debug("[Step4] Q&A sent separately before offer generation (hybrid message)")
                # Continue to generate offer below
        else:
            # Not ready for offer - just return Q&A (legacy behavior)
            result = _present_general_room_qna(state, event_entry, classification, thread_id)
            return result

    requirements = event_entry.get("requirements") or {}
    current_req_hash = event_entry.get("requirements_hash")
    computed_hash = requirements_hash(requirements) if requirements else None
    if computed_hash and computed_hash != current_req_hash:
        update_event_metadata(event_entry, requirements_hash=computed_hash)
        current_req_hash = computed_hash
        state.extras["persist"] = True

    _ensure_products_container(event_entry)
    # [SKIP PRODUCTS TEXT DETECTION] Detect "no extras", "skip products" etc. from message body
    if state.user_info is not None:
        message_body = (state.message.body or "").lower() if state.message else ""
        skip_phrases = (
            "no extras", "keine extras", "skip products", "skip product",
            "without extras", "ohne extras", "no add-ons", "no addons",
            "proceed without", "just the room", "nur den raum",
            "no catering", "keine produkte", "no products",
        )
        if any(phrase in message_body for phrase in skip_phrases):
            state.user_info["skip_products"] = True
            logger.debug("[Step4] Detected skip products phrase in message")
    products_changed = _apply_product_operations(event_entry, state.user_info or {})
    if products_changed:
        state.extras["persist"] = True
    autofilled = _autofill_products_from_preferences(
        event_entry,
        state.user_info or {},
        min_score=get_product_autofill_threshold(),
    )
    if autofilled:
        state.extras["persist"] = True

    precondition = _evaluate_preconditions(event_entry, current_req_hash, thread_id)
    if precondition:
        code, target = precondition
        if target in (2, 3):
            return _route_to_owner_step(state, event_entry, target, code, thread_id)
        return _handle_products_pending(state, event_entry, code)

    # [COMPOSE + FINALIZE] Pricing → recording → deposit → summary → draft → step advancement
    from .compose import compose_and_finalize_offer
    return compose_and_finalize_offer(
        state, event_entry, previous_step, thread_id,
        classification=classification,
        deferred_general_qna=deferred_general_qna,
    )


